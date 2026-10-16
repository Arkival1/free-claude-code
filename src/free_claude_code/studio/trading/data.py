"""Market data for the desk: bars, quotes, exchange rates, and meme-coin facts.

Every answer is kept for a while that suits it (a day's bars for an hour, a
quote for 20 seconds), so a scan never asks twice, and each kind has a backup:
- shares, indices, and currencies: Yahoo Finance;
- coins: Yahoo, then CoinGecko;
- meme-coin liquidity, age, and buying pressure: DexScreener.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from loguru import logger

from free_claude_code.core.json_types import JsonObject

from ..resilience import HostLimit, ServiceError, Web
from .indicators import Bar
from .instruments import COINGECKO_IDS, INDEX_FOR_MARKET, Instrument, parse_symbol
from .providers.coingecko import CoinGecko
from .providers.dexscreener import DexFacts, DexScreener
from .providers.yahoo import YahooChart

BAR_SECONDS: dict[str, float] = {"1d": 3600.0, "1h": 600.0, "15m": 180.0, "1m": 30.0}
"""How long bars of each size are kept before they're fetched again."""
QUOTE_SECONDS = 20.0
FX_SECONDS = 600.0
FACTS_SECONDS = 900.0
MIN_DAILY_BARS = 30

DATA_LIMITS: dict[str, HostLimit] = {
    "query1.finance.yahoo.com": HostLimit(2.0, 4),
    "query2.finance.yahoo.com": HostLimit(2.0, 4),
    "api.coingecko.com": HostLimit(0.2, 2),
    "api.dexscreener.com": HostLimit(4.0, 4),
}
"""Each free source's pace, inside its published or observed limits."""


class MarketDataError(RuntimeError):
    """No source had the data; the message says what was tried."""


@dataclass(frozen=True, slots=True)
class Quote:
    """The latest price of one symbol."""

    symbol: str
    price: float
    currency: str
    at: float
    """Unix seconds."""
    source: str
    bid: float | None = None
    ask: float | None = None

    @property
    def spread_pct(self) -> float | None:
        if self.bid is None or self.ask is None or self.price <= 0:
            return None
        return (self.ask - self.bid) / self.price * 100

    def view(self) -> JsonObject:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "currency": self.currency,
            "at": self.at,
            "source": self.source,
            "bid": self.bid,
            "ask": self.ask,
        }


class MarketData:
    """Cached bars, quotes, rates, and facts from free sources."""

    def __init__(
        self,
        web: Web,
        *,
        coingecko_key: Callable[[], str] = lambda: "",
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._web = web
        self._yahoo = YahooChart(web)
        self._coingecko_key = coingecko_key
        self._dex = DexScreener(web)
        self._clock = clock
        self._wall = wall
        self._cache: dict[tuple[str, ...], tuple[float, object]] = {}
        self._coin_ids: dict[str, str] = dict(COINGECKO_IDS)

    def _gecko(self) -> CoinGecko:
        return CoinGecko(self._web, key=self._coingecko_key())

    async def _cached[T](
        self, key: tuple[str, ...], seconds: float, load: Callable[[], Awaitable[T]]
    ) -> T:
        now = self._clock()
        found = self._cache.get(key)
        if found is not None and now - found[0] < seconds:
            # The cache only ever holds what this key's loader returned.
            return cast(T, found[1])
        value = await load()
        self._cache[key] = (now, value)
        return value

    def forget(self) -> None:
        """Drop everything kept (the Refresh button)."""
        self._cache.clear()

    async def bars(self, instrument: Instrument, interval: str = "1d") -> list[Bar]:
        """Candles for one symbol; an empty list when no source has any."""
        seconds = BAR_SECONDS.get(interval, 600.0)
        return await self._cached(
            ("bars", instrument.symbol, interval),
            seconds,
            lambda: self._load_bars(instrument, interval),
        )

    async def _load_bars(self, instrument: Instrument, interval: str) -> list[Bar]:
        if instrument.market == "dex":
            return []
        symbol = instrument.yahoo if instrument.market != "index" else instrument.symbol
        try:
            bars, _ = await self._yahoo.chart(symbol, interval)
        except ServiceError as error:
            bars = []
            logger.info(
                "Trading: Yahoo has no {} {} bars ({})", symbol, interval, error
            )
        if bars or instrument.market != "crypto" or interval != "1d":
            return bars
        coin = await self.coin_id(instrument.symbol)
        if not coin:
            return []
        try:
            return await self._gecko().daily(coin)
        except ServiceError as error:
            logger.info("Trading: CoinGecko has no {} history ({})", coin, error)
            return []

    async def coin_id(self, symbol: str) -> str:
        found = self._coin_ids.get(symbol)
        if found is not None:
            return found
        try:
            found = await self._gecko().find_id(symbol)
        except ServiceError:
            return ""
        self._coin_ids[symbol] = found
        return found

    async def index_bars(self, market: str) -> list[Bar]:
        """The yardstick a market is read against (ASX 200, S&P 500, Bitcoin)."""
        symbol = INDEX_FOR_MARKET.get(
            "crypto" if market in {"crypto", "dex"} else market
        )
        if not symbol:
            return []
        return await self.bars(parse_symbol(symbol), "1d")

    async def quote(self, instrument: Instrument) -> Quote:
        """The latest price; raises MarketDataError when no source has one."""
        return await self._cached(
            ("quote", instrument.symbol),
            QUOTE_SECONDS,
            lambda: self._load_quote(instrument),
        )

    async def _load_quote(self, instrument: Instrument) -> Quote:
        tried: list[str] = []
        if instrument.market == "dex":
            facts = await self.dex_facts(instrument)
            if facts is not None and facts.price_usd:
                return Quote(
                    instrument.symbol,
                    facts.price_usd,
                    "USD",
                    self._wall(),
                    "DexScreener",
                )
            raise MarketDataError(f"No price for {instrument.symbol} on DexScreener.")
        try:
            bars, meta = await self._yahoo.chart(instrument.yahoo, "1m")
        except ServiceError as error:
            tried.append(f"Yahoo: {error}")
        else:
            price = meta.get("regularMarketPrice")
            stamp = meta.get("regularMarketTime")
            if not isinstance(price, int | float) and bars:
                price = bars[-1].c
            if isinstance(price, int | float) and price > 0:
                currency = str(meta.get("currency") or instrument.currency).upper()
                return Quote(
                    instrument.symbol,
                    float(price),
                    currency,
                    float(stamp) if isinstance(stamp, int | float) else self._wall(),
                    "Yahoo Finance",
                )
            tried.append("Yahoo: no price")
        if instrument.market == "crypto":
            daily = await self.bars(instrument, "1d")
            if daily:
                return Quote(
                    instrument.symbol,
                    daily[-1].c,
                    "USD",
                    float(daily[-1].t),
                    "CoinGecko",
                )
            tried.append("CoinGecko: no price")
        raise MarketDataError(
            f"No price for {instrument.symbol} ({'; '.join(tried) or 'no source'})."
        )

    async def fx(self, currency: str, base: str = "AUD") -> float:
        """How much of ``base`` one unit of ``currency`` is worth."""
        currency, base = currency.upper(), base.upper()
        if not currency or currency == base:
            return 1.0
        return await self._cached(
            ("fx", currency, base), FX_SECONDS, lambda: self._load_fx(currency, base)
        )

    async def _load_fx(self, currency: str, base: str) -> float:
        # Yahoo's AUDUSD=X is US dollars per Australian dollar.
        try:
            bars, meta = await self._yahoo.chart(f"{base}{currency}=X", "1d")
        except ServiceError as error:
            raise MarketDataError(f"No {base}/{currency} rate: {error}") from error
        rate = meta.get("regularMarketPrice")
        if not isinstance(rate, int | float) and bars:
            rate = bars[-1].c
        if not isinstance(rate, int | float) or rate <= 0:
            raise MarketDataError(f"No {base}/{currency} rate from Yahoo.")
        return 1.0 / float(rate)

    async def dex_facts(self, instrument: Instrument) -> DexFacts | None:
        """Liquidity, age, and buying pressure for a meme coin or DEX token."""
        if not (instrument.meme or instrument.market == "dex"):
            return None

        async def load() -> DexFacts | None:
            try:
                return await self._dex.facts(
                    instrument.symbol,
                    chain=instrument.chain,
                    address=instrument.address,
                )
            except ServiceError as error:
                logger.info("Trading: DexScreener: {}", error)
                return None

        return await self._cached(("dex", instrument.symbol), FACTS_SECONDS, load)

    async def trending_coins(self) -> list[str]:
        """Coins people are searching for and meme coins with heavy trading."""

        async def load() -> list[str]:
            found: list[str] = []
            gecko = self._gecko()
            try:
                found.extend(await gecko.trending())
                found.extend(
                    str(row.get("symbol", "")).upper()
                    for row in await gecko.meme_movers(count=15)
                )
            except ServiceError as error:
                logger.info("Trading: CoinGecko trends: {}", error)
            return [symbol for symbol in dict.fromkeys(found) if symbol]

        return await self._cached(("trending",), 1800.0, load)

    def health(self) -> dict[str, str]:
        return self._web.health()
