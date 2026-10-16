"""Live bid and ask for coins from two exchanges' public feeds (no key).

- Coinbase Exchange: last trade, best bid and ask, 24-hour volume, and the
  time of the last trade; whether the coin trades there right now (online,
  disabled, cancel-only, limit-only); and daily candles.
- Kraken: the same prices without a time, so the time FCC received the
  answer is used and the snapshot says so.

Both are real time. They are used to check the price the desk works from,
to measure the spread, to catch a data source quoting a different coin that
shares the ticker, and to notice a coin an exchange has stopped trading.
"""

import asyncio
import time
from collections.abc import Callable

from loguru import logger

from ...resilience import HostLimit, ServiceError, Web
from ..indicators import Bar
from ..information import QuoteSnapshot, VenueStatus, seconds_from_iso

COINBASE = "https://api.exchange.coinbase.com"
KRAKEN = "https://api.kraken.com"
LIMITS: dict[str, HostLimit] = {
    "api.exchange.coinbase.com": HostLimit(3.0, 3),
    "api.kraken.com": HostLimit(1.0, 2),
}
"""Inside both exchanges' published public limits."""

KRAKEN_NAMES = {"BTC": "XBT", "DOGE": "XDG"}
"""Kraken's own names for a few coins."""


class OrderBooks:
    def __init__(self, web: Web, *, wall: Callable[[], float] = time.time) -> None:
        self._web = web
        self._wall = wall

    async def coinbase(self, coin: str) -> QuoteSnapshot:
        product = f"{coin.upper()}-USD"
        body = await self._web.get_json(
            f"{COINBASE}/products/{product}/ticker", what="Coinbase Exchange"
        )
        received = self._wall()
        if not isinstance(body, dict):
            raise ServiceError(f"Coinbase Exchange sent no ticker for {product}.")
        stamp = seconds_from_iso(body.get("time"))
        return QuoteSnapshot(
            provider="Coinbase Exchange",
            symbol=coin.upper(),
            exchange="Coinbase",
            asset_class="crypto",
            currency="USD",
            timestamp=stamp,
            received_at=received,
            exchange_tz="UTC",
            realtime=True,
            delayed_minutes=0,
            last=_number(body.get("price")),
            bid=_number(body.get("bid")),
            ask=_number(body.get("ask")),
            volume=_number(body.get("volume")),
            source_kind="exchange",
            notes=() if stamp is not None else ("Coinbase gave no time",),
            volume_unit="coins, 24 hours",
        )

    async def coinbase_status(self, coin: str) -> VenueStatus:
        """Whether Coinbase trades the coin against USD right now. A coin it
        doesn't list comes back as not listed (that isn't a problem)."""
        product = f"{coin.upper()}-USD"
        try:
            body = await self._web.get_json(
                f"{COINBASE}/products/{product}", what="Coinbase Exchange"
            )
        except ServiceError as error:
            if error.status == 404:
                return VenueStatus("Coinbase", coin.upper(), listed=False)
            raise
        if not isinstance(body, dict):
            raise ServiceError(f"Coinbase Exchange sent no product for {product}.")
        return VenueStatus(
            "Coinbase",
            coin.upper(),
            listed=True,
            status=str(body.get("status") or "unknown"),
            trading_disabled=body.get("trading_disabled") is True,
            cancel_only=body.get("cancel_only") is True,
            limit_only=body.get("limit_only") is True,
            post_only=body.get("post_only") is True,
            auction=body.get("auction_mode") is True,
            message=str(body.get("status_message") or "")[:200],
        )

    async def coinbase_daily(self, coin: str) -> list[Bar]:
        """Up to 300 daily candles, oldest first. Coinbase counts volume in
        coins; it is turned into dollars (volume times close) so it matches the
        other coin sources."""
        product = f"{coin.upper()}-USD"
        body = await self._web.get_json(
            f"{COINBASE}/products/{product}/candles",
            params={"granularity": 86_400},
            what="Coinbase Exchange",
        )
        if not isinstance(body, list):
            raise ServiceError(f"Coinbase Exchange sent no candles for {product}.")
        bars: list[Bar] = []
        for row in body:
            # Each row is [time, low, high, open, close, volume].
            if not isinstance(row, list) or len(row) < 6:
                continue
            stamp, low, high, opened, close, volume = row[:6]
            numbers = (low, high, opened, close, volume)
            if not isinstance(stamp, int | float) or not all(
                isinstance(value, int | float) and not isinstance(value, bool)
                for value in numbers
            ):
                continue
            if close <= 0:
                continue
            bars.append(
                Bar(
                    t=int(stamp),
                    o=float(opened),
                    h=float(max(high, opened, close)),
                    l=float(min(low, opened, close)),
                    c=float(close),
                    v=float(volume) * float(close),
                )
            )
        bars.sort(key=lambda bar: bar.t)
        return bars

    async def kraken(self, coin: str) -> QuoteSnapshot:
        name = KRAKEN_NAMES.get(coin.upper(), coin.upper())
        body = await self._web.get_json(
            f"{KRAKEN}/0/public/Ticker", params={"pair": f"{name}USD"}, what="Kraken"
        )
        received = self._wall()
        errors = body.get("error") if isinstance(body, dict) else None
        result = body.get("result") if isinstance(body, dict) else None
        if errors or not isinstance(result, dict) or not result:
            detail = "; ".join(str(error) for error in errors or []) or "no ticker"
            raise ServiceError(f"Kraken has no {name}/USD ticker ({detail}).")
        ticker = next(iter(result.values()))
        if not isinstance(ticker, dict):
            raise ServiceError(f"Kraken sent an odd ticker for {name}/USD.")
        volume = ticker.get("v")
        return QuoteSnapshot(
            provider="Kraken",
            symbol=coin.upper(),
            exchange="Kraken",
            asset_class="crypto",
            currency="USD",
            timestamp=received,
            received_at=received,
            exchange_tz="UTC",
            realtime=True,
            delayed_minutes=0,
            last=_first(ticker.get("c")),
            bid=_first(ticker.get("b")),
            ask=_first(ticker.get("a")),
            volume=_number(volume[1]) if isinstance(volume, list) and volume else None,
            source_kind="exchange",
            notes=("Kraken gives no time; the time FCC received it is used",),
            volume_unit="coins, 24 hours",
        )

    async def snapshots(self, coin: str) -> list[QuoteSnapshot]:
        """Both exchanges' prices; one that fails is left out (and logged)."""
        found: list[QuoteSnapshot] = []
        answers = await asyncio.gather(
            self.coinbase(coin), self.kraken(coin), return_exceptions=True
        )
        for answer in answers:
            if isinstance(answer, QuoteSnapshot):
                found.append(answer)
            elif isinstance(answer, ServiceError):
                logger.info("Trading: no exchange price for {} ({})", coin, answer)
            elif isinstance(answer, BaseException):
                raise answer
        return found


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        try:
            found = float(value)
        except ValueError:
            return None
        return found if found > 0 else None
    return None


def _first(value: object) -> float | None:
    return _number(value[0]) if isinstance(value, list) and value else None
