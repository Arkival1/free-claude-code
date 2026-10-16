"""Market data for the desk: bars, quotes, exchange rates, and meme-coin facts.

Every answer is kept for a while that suits it (a day's bars for an hour, a
quote for 20 seconds), so a scan never asks twice, and each kind has a backup:
- shares, indices, and currencies: Yahoo Finance;
- coins: Yahoo, then CoinGecko;
- meme-coin liquidity, age, and buying pressure: DexScreener.

``snapshots`` gives each source's price exactly as it reported it (its own
time, exchange, delay, and bid/ask where it has them) for the data-quality
checks; coins add Coinbase's and Kraken's live order books. A failed source
is left out and asked again next time, never remembered as "nothing".
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from loguru import logger

from free_claude_code.core.json_types import JsonObject

from ..resilience import HostLimit, ServiceError, Web
from .indicators import Bar
from .information import (
    ASSET_CLASS,
    EXCHANGE_TZ,
    PROVIDER_DELAY_MINUTES,
    QuoteSnapshot,
    SourceKind,
    VenueStatus,
)
from .instruments import COINGECKO_IDS, INDEX_FOR_MARKET, Instrument, parse_symbol
from .providers.coingecko import CoinGecko
from .providers.dexscreener import DexFacts, DexScreener
from .providers.news import LIMITS as NEWS_LIMITS
from .providers.orderbook import LIMITS as BOOK_LIMITS
from .providers.orderbook import OrderBooks
from .providers.yahoo import YahooChart

BAR_SECONDS: dict[str, float] = {"1d": 3600.0, "1h": 600.0, "15m": 180.0, "1m": 30.0}
"""How long bars of each size are kept before they're fetched again."""
QUOTE_SECONDS = 20.0
SNAPSHOT_SECONDS = 10.0
FX_SECONDS = 600.0
FACTS_SECONDS = 900.0
MIN_DAILY_BARS = 30

DATA_LIMITS: dict[str, HostLimit] = {
    "query1.finance.yahoo.com": HostLimit(2.0, 4),
    "query2.finance.yahoo.com": HostLimit(2.0, 4),
    "api.coingecko.com": HostLimit(0.2, 2),
    "api.dexscreener.com": HostLimit(4.0, 4),
    **BOOK_LIMITS,
    **NEWS_LIMITS,
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
    note: str = ""
    """What the source flagged: "halted", or "last close" for a price from
    before today's first trade."""

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
            "note": self.note,
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
        self._books = OrderBooks(web, wall=wall)
        self._clock = clock
        self._wall = wall
        self._cache: dict[tuple[str, ...], tuple[float, object]] = {}
        self._snapshots: dict[str, tuple[float, tuple[QuoteSnapshot, ...]]] = {}
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
        self._snapshots.clear()

    async def bars(self, instrument: Instrument, interval: str = "1d") -> list[Bar]:
        """Candles for one symbol; an empty list when no source has any."""
        seconds = BAR_SECONDS.get(interval, 600.0)
        key = ("bars", instrument.symbol, interval)
        found = await self._cached(
            key, seconds, lambda: self._load_bars(instrument, interval)
        )
        if not found:
            # Nothing came back (an outage, most likely): ask again next
            # time rather than remember "no history" for an hour.
            self._cache.pop(key, None)
        return found

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
        try:
            bars = await self._books.coinbase_daily(instrument.symbol)
        except ServiceError as error:
            logger.info(
                "Trading: Coinbase has no {} history ({})", instrument.symbol, error
            )
        if bars:
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

    async def _yahoo_minute(
        self, instrument: Instrument
    ) -> tuple[list[Bar], dict[str, object]]:
        """Yahoo's 1-minute chart and its meta block (one call for both the
        quote and the snapshot); a failure raises and isn't kept."""
        return await self._cached(
            ("chart1m", instrument.symbol),
            QUOTE_SECONDS,
            lambda: self._yahoo.chart(instrument.yahoo, "1m"),
        )

    async def snapshots(self, instrument: Instrument) -> list[QuoteSnapshot]:
        """Each source's latest price as it reported it; empty when none has
        one. Coins add Coinbase's and Kraken's live bid and ask."""
        found = self._snapshots.get(instrument.symbol)
        now = self._clock()
        if found is not None and now - found[0] < SNAPSHOT_SECONDS:
            return list(found[1])
        taken: list[QuoteSnapshot] = []
        if instrument.yahoo:
            try:
                bars, meta = await self._yahoo_minute(instrument)
            except ServiceError as error:
                logger.info(
                    "Trading: Yahoo has no {} price ({})", instrument.symbol, error
                )
            else:
                snap = yahoo_snapshot(instrument, meta, bars, received=self._wall())
                if snap is not None:
                    taken.append(snap)
        if instrument.market == "crypto":
            taken.extend(await self._books.snapshots(instrument.symbol))
        if instrument.market == "dex" or instrument.meme:
            facts = await self.dex_facts(instrument)
            if facts is not None and facts.price_usd:
                received = self._wall()
                taken.append(
                    QuoteSnapshot(
                        provider="DexScreener",
                        symbol=instrument.symbol,
                        exchange=facts.dex or "DEX",
                        asset_class="crypto",
                        currency="USD",
                        timestamp=None,
                        received_at=received,
                        exchange_tz="UTC",
                        realtime=True,
                        delayed_minutes=0,
                        last=facts.price_usd,
                        volume=facts.volume_24h or None,
                        source_kind="aggregator",
                        notes=("DexScreener gives no time for its price",),
                    )
                )
        if taken:
            self._snapshots[instrument.symbol] = (now, tuple(taken))
        return taken

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
            bars, meta = await self._yahoo_minute(instrument)
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

    async def venue_status(self, instrument: Instrument) -> VenueStatus | None:
        """Whether Coinbase trades the coin right now; None for anything
        that isn't a coin, or when Coinbase couldn't be asked (not kept, so
        it is asked again next time)."""
        if instrument.market != "crypto":
            return None
        key = ("venue", instrument.symbol)
        found = self._cache.get(key)
        now = self._clock()
        if found is not None and now - found[0] < FACTS_SECONDS:
            return cast(VenueStatus, found[1])
        try:
            status = await self._books.coinbase_status(instrument.symbol)
        except ServiceError as error:
            logger.info("Trading: Coinbase status for {}: {}", instrument.symbol, error)
            return None
        self._cache[key] = (now, status)
        return status

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


def yahoo_snapshot(
    instrument: Instrument,
    meta: dict[str, object],
    bars: list[Bar],
    *,
    received: float,
) -> QuoteSnapshot | None:
    """Yahoo's chart meta as a snapshot: its own trade time, exchange, and
    the delay Yahoo publishes for that market. Yahoo gives no bid or ask."""
    price = meta.get("regularMarketPrice")
    stamp = meta.get("regularMarketTime")
    if not isinstance(price, int | float) or isinstance(price, bool):
        if not bars:
            return None
        price, stamp = bars[-1].c, bars[-1].t
    if price <= 0:
        return None
    volume = meta.get("regularMarketVolume")
    delay = PROVIDER_DELAY_MINUTES.get(("Yahoo Finance", instrument.market), 0)
    exchange = meta.get("exchangeName") or meta.get("fullExchangeName") or ""
    zone = meta.get("exchangeTimezoneName") or EXCHANGE_TZ.get(instrument.market, "UTC")
    return QuoteSnapshot(
        provider="Yahoo Finance",
        symbol=instrument.symbol,
        exchange=str(exchange),
        asset_class=ASSET_CLASS.get(instrument.market, instrument.market),
        currency=str(meta.get("currency") or instrument.currency).upper(),
        timestamp=float(stamp) if isinstance(stamp, int | float) else None,
        received_at=received,
        exchange_tz=str(zone),
        realtime=delay == 0,
        delayed_minutes=delay,
        last=float(price),
        volume=float(volume)
        if isinstance(volume, int | float) and not isinstance(volume, bool)
        else None,
        source_kind="aggregator",
        notes=(f"Yahoo publishes {instrument.market.upper()} prices {delay} min late",)
        if delay
        else (),
    )


def quote_snapshot(
    quote: Quote,
    instrument: Instrument,
    *,
    received: float,
    realtime: bool = True,
    source_kind: SourceKind = "broker",
    stamped: bool = True,
) -> QuoteSnapshot:
    """A broker's quote as a snapshot. ``stamped`` is False when the broker
    gave no time and ``quote.at`` is only when FCC received it."""
    return QuoteSnapshot(
        provider=quote.source,
        symbol=instrument.symbol,
        exchange=quote.source,
        asset_class=ASSET_CLASS.get(instrument.market, instrument.market),
        currency=quote.currency,
        timestamp=quote.at if quote.at > 0 else None,
        received_at=received,
        exchange_tz=EXCHANGE_TZ.get(instrument.market, "UTC"),
        realtime=realtime,
        delayed_minutes=0,
        last=quote.price if quote.price > 0 else None,
        bid=quote.bid,
        ask=quote.ask,
        source_kind=source_kind,
        notes=tuple(
            note
            for note in (
                quote.note,
                "" if stamped else f"{quote.source} gives no time; time received used",
            )
            if note
        ),
    )
