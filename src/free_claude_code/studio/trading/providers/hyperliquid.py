"""Hyperliquid's public market data (no key): the exchange the Invo app
trades on.

- The order book for a coin's perpetual future: best bid and ask, with the
  exchange's own time.
- Each coin's funding rate (paid every hour between longs and shorts),
  open interest, mark and oracle prices, and the day's traded value.
- The list of coins it trades and how finely each one's size can be set.

Prices here are for perpetual futures, which follow the coin's price but
can sit a little above or below it (the funding rate pulls them back).
"""

import time
from collections.abc import Callable

from ...resilience import ServiceError, Web
from ..brokers.common import items, number, obj, text
from ..information import QuoteSnapshot

MAINNET = "https://api.hyperliquid.xyz"
TESTNET = "https://api.hyperliquid-testnet.xyz"
META_SECONDS = 600.0


class HyperliquidData:
    def __init__(
        self,
        web: Web,
        *,
        base: str = MAINNET,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._web = web
        self._base = base
        self._wall = wall
        self._meta: (
            tuple[float, list[dict[str, object]], list[dict[str, object]]] | None
        ) = None

    async def info(self, body: dict[str, object]) -> object:
        response = await self._web.request(
            "POST", f"{self._base}/info", json=body, what="Hyperliquid"
        )
        try:
            return response.json()
        except ValueError as error:
            raise ServiceError("Hyperliquid sent a reply that isn't JSON.") from error

    async def universe(self) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Every coin it trades (name, size decimals, most leverage) and each
        one's market figures, in the exchange's own order (the asset number)."""
        now = self._wall()
        if self._meta is not None and now - self._meta[0] < META_SECONDS:
            return self._meta[1], self._meta[2]
        found = await self.info({"type": "metaAndAssetCtxs"})
        if not isinstance(found, list) or len(found) < 2:
            raise ServiceError("Hyperliquid sent no coin list.")
        coins = items(obj(found[0]).get("universe"))
        contexts = items(found[1])
        self._meta = (now, coins, contexts)
        return coins, contexts

    async def asset(
        self, coin: str
    ) -> tuple[int, dict[str, object], dict[str, object]]:
        """The coin's asset number, its listing and its market figures."""
        coins, contexts = await self.universe()
        for index, row in enumerate(coins):
            if text(row.get("name")).upper() == coin.upper() and not row.get(
                "isDelisted"
            ):
                return index, row, contexts[index] if index < len(contexts) else {}
        raise ServiceError(f"Hyperliquid doesn't trade {coin}.", transient=False)

    async def book(self, coin: str) -> QuoteSnapshot:
        body = obj(await self.info({"type": "l2Book", "coin": coin.upper()}))
        received = self._wall()
        levels = body.get("levels")
        sides = levels if isinstance(levels, list) and len(levels) == 2 else [[], []]
        bids, asks = items(sides[0]), items(sides[1])
        bid = number(bids[0].get("px")) if bids else 0.0
        ask = number(asks[0].get("px")) if asks else 0.0
        stamp = number(body.get("time")) / 1000 or None
        notes: list[str] = ["perpetual future (can sit a little off the coin's price)"]
        try:
            _, _, context = await self.asset(coin)
        except ServiceError:
            context = {}
        funding = context.get("funding")
        if funding is not None:
            rate = number(funding) * 100
            notes.append(
                f"funding {rate:+.4f}% an hour ("
                + ("longs pay shorts" if rate >= 0 else "shorts pay longs")
                + ")"
            )
        return QuoteSnapshot(
            provider="Hyperliquid",
            symbol=coin.upper(),
            exchange="Hyperliquid",
            asset_class="crypto",
            currency="USD",
            timestamp=stamp,
            received_at=received,
            exchange_tz="UTC",
            realtime=True,
            delayed_minutes=0,
            last=(bid + ask) / 2 if bid and ask else None,
            bid=bid or None,
            ask=ask or None,
            volume=number(context.get("dayNtlVlm")) or None,
            source_kind="exchange",
            notes=tuple(notes),
            volume_unit="USD, 24 hours",
        )

    async def funding(self, coin: str) -> float | None:
        """The hourly funding rate (0.0001 is 0.01% an hour), when known."""
        _, _, context = await self.asset(coin)
        value = context.get("funding")
        return number(value) if value is not None else None
