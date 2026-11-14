"""CoinSpot (beta): Australia's big coin exchange, with hundreds of meme coins.

API v2. Private calls POST a JSON body with an increasing nonce, and send the
key in a ``key`` header and an HMAC-SHA512 (hex) of that exact body, keyed
with the secret, in a ``sign`` header. Market buys and sells fill at once
("buy now"), with the decision's price and the slippage limit sent as the
rate and threshold so a runaway price is refused rather than paid.

CoinSpot has no client order ids. Each attempt is noted first (and noted
again after FCC restarts); after a lost answer the desk looks for a
completed order of the same coin, side and size made since the attempt. When
there is none it can't tell whether the order went through, so it never
sends again: the order stays open and new trades pause until a later check
matches it. Marked beta: checked against CoinSpot's API page and an
open-source client, not yet against a live account; try it with a small
order first.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

import httpx

from ...resilience import ServiceError, read_json
from ..data import MarketData, Quote
from ..instruments import Instrument
from .base import (
    Account,
    Holding,
    OrderRequest,
    OrderResult,
    Rules,
    Sent,
    fingerprint,
)
from .common import Nonce, items, make_web, number, obj, text

HOST = "www.coinspot.com.au"
PRIVATE = f"https://{HOST}/api/v2"
PUBLIC = f"https://{HOST}/pubapi/v2"
CLOCK_SKEW_SECONDS = 60.0
"""How far CoinSpot's clock and this PC's may differ when matching times."""


def sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha512).hexdigest()


@dataclass(frozen=True, slots=True)
class _Attempt:
    coin: str
    side: str
    qty: float
    at: float


class CoinSpotBroker:
    id = "coinspot"
    name = "CoinSpot"
    live = True
    supports_brackets = False

    def __init__(
        self,
        values: Mapping[str, str],
        data: MarketData,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._key = values.get("api_key", "")
        self._secret = values.get("api_secret", "")
        self._slippage = number(values.get("slippage_pct"), 1.0) or 1.0
        self._web = make_web(transport, HOST, per_second=5.0, burst=5)
        self._nonce = Nonce(clock)
        self._clock = clock
        self._attempts: dict[str, _Attempt] = {}
        self._done: dict[str, OrderResult] = {}
        self._data = data

    def markets(self) -> frozenset[str]:
        return frozenset({"crypto"})

    async def _private(
        self,
        path: str,
        fields: Mapping[str, object] | None = None,
        *,
        retry: bool = True,
    ) -> dict[str, object]:
        body = json.dumps(
            {"nonce": self._nonce(), **(fields or {})}, separators=(",", ":")
        )
        response = await self._web.request(
            "POST",
            f"{PRIVATE}{path}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "key": self._key,
                "sign": sign(body, self._secret),
            },
            retry=retry,
            what="CoinSpot",
        )
        found = obj(read_json(response, what="CoinSpot"))
        if text(found.get("status")).lower() != "ok":
            raise ServiceError(
                f"CoinSpot: {text(found.get('message')) or 'request refused'}",
                transient=False,
            )
        return found

    async def account(self) -> Account:
        found = await self._private("/ro/my/balances")
        cash = 0.0
        equity = 0.0
        for entry in items(found.get("balances")):
            for code, value in entry.items():
                info = obj(value)
                equity += number(info.get("audbalance"))
                if code.upper() == "AUD":
                    cash = number(info.get("balance"))
        return Account(
            number=fingerprint(self.id, self._key),
            fingerprint=fingerprint(self.id, self._key),
            currency="AUD",
            equity=equity,
            cash=cash,
            buying_power=cash,
            live=True,
            note="CoinSpot account (identified by its API key).",
        )

    async def positions(self) -> list[Holding]:
        found = await self._private("/ro/my/balances")
        held: list[Holding] = []
        for entry in items(found.get("balances")):
            for code, value in entry.items():
                info = obj(value)
                if code.upper() != "AUD" and number(info.get("balance")) > 0:
                    held.append(
                        Holding(code.upper(), number(info.get("balance")), 0.0, "AUD")
                    )
        return held

    async def _prices(self, coin: str) -> dict[str, object]:
        body = obj(await self._web.get_json(f"{PUBLIC}/latest/{coin}", what="CoinSpot"))
        if text(body.get("status")).lower() != "ok":
            raise ServiceError(f"CoinSpot doesn't list {coin}.", status=404)
        return obj(body.get("prices"))

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market != "crypto":
            return Rules(tradable=False, note="CoinSpot trades crypto only.")
        try:
            await self._prices(instrument.symbol)
        except ServiceError:
            return Rules(
                tradable=False, note=f"CoinSpot doesn't list {instrument.symbol}."
            )
        return Rules(
            tradable=True, broker_symbol=instrument.symbol, qty_step=1e-8, min_value=1.0
        )

    async def quote(self, instrument: Instrument) -> Quote | None:
        try:
            prices = await self._prices(instrument.symbol)
        except ServiceError:
            return None
        last = number(prices.get("last"))
        if last <= 0:
            return None
        return Quote(
            instrument.symbol,
            last,
            "AUD",
            self._clock(),
            "CoinSpot",
            number(prices.get("bid")) or None,
            number(prices.get("ask")) or None,
        )

    async def place(self, order: OrderRequest) -> OrderResult:
        coin = order.instrument.symbol
        self._attempts[order.client_id] = _Attempt(
            coin, order.side, order.qty, self._clock()
        )
        amount = round(order.qty, 8)
        if order.order_type == "limit" and order.limit_price is not None:
            limit = order.limit_price
            if order.price_currency != "AUD":
                limit *= await self._data.fx(order.price_currency, "AUD")
            path = "/my/buy" if order.side == "buy" else "/my/sell"
            found = await self._private(
                path,
                {
                    "cointype": coin,
                    "amount": amount,
                    "rate": round(limit, 8),
                    "markettype": "AUD",
                },
                retry=False,
            )
            result = OrderResult(
                broker_order_id=text(found.get("id")),
                status="submitted",
                client_id=order.client_id,
                symbol=coin,
                raw={"currency": "AUD", "side": order.side},
            )
        else:
            quote = await self.quote(order.instrument)
            fields: dict[str, object] = {
                "cointype": coin,
                "amounttype": "coin",
                "amount": amount,
            }
            if quote is not None:
                fields.update(
                    {
                        "rate": round(quote.price, 8),
                        "threshold": self._slippage,
                        "direction": "UP" if order.side == "buy" else "DOWN",
                    }
                )
            path = "/my/buy/now" if order.side == "buy" else "/my/sell/now"
            found = await self._private(path, fields, retry=False)
            filled = number(found.get("amount"), amount)
            total = number(found.get("total"))
            result = OrderResult(
                broker_order_id=f"coinspot-{order.client_id}",
                status="filled",
                client_id=order.client_id,
                symbol=coin,
                filled_qty=filled,
                fill_price=total / filled if filled and total else None,
                raw={"currency": "AUD", "fee_currency": "AUD"},
            )
        self._done[order.client_id] = result
        return result

    def remember(self, sent: Sent) -> None:
        """After a restart: an order FCC sent, so ``find`` can look for it."""
        self._attempts.setdefault(
            sent.client_id, _Attempt(sent.symbol, sent.side, sent.qty, sent.at)
        )

    async def find(self, client_id: str) -> OrderResult | None:
        if client_id in self._done:
            return self._done[client_id]
        attempt = self._attempts.get(client_id)
        if attempt is None:
            return None
        found = await self._private(
            "/ro/my/orders/market/completed", {"cointype": attempt.coin, "limit": 50}
        )
        for info in items(
            found.get("buyorders" if attempt.side == "buy" else "sellorders")
        ):
            if abs(number(info.get("amount")) - attempt.qty) > max(
                1e-8, attempt.qty * 1e-6
            ):
                continue
            # Only an order completed after this one was sent can be it; one
            # with no readable time can't be told apart from an older one.
            sold = _when(info.get("solddate"))
            if sold is None or sold < attempt.at - CLOCK_SKEW_SECONDS:
                continue
            filled = number(info.get("amount"))
            total = number(info.get("audtotal")) or number(info.get("total"))
            result = OrderResult(
                broker_order_id=text(info.get("id")) or f"coinspot-{client_id}",
                status="filled",
                client_id=client_id,
                symbol=attempt.coin,
                filled_qty=filled,
                fill_price=total / filled
                if filled and total
                else number(info.get("rate")) or None,
                raw={"currency": "AUD", "fee_currency": "AUD"},
            )
            self._done[client_id] = result
            return result
        # Not among the completed orders yet: it may still be on its way, or
        # never have arrived. Nobody can say, so it is not sent again.
        raise ServiceError(
            f"CoinSpot shows no completed {attempt.coin} {attempt.side} of "
            f"{attempt.qty:g} since FCC sent it.",
            transient=False,
            host=HOST,
        )

    async def cancel(self, broker_order_id: str) -> None:
        for path in ("/my/buy/cancel", "/my/sell/cancel"):
            try:
                await self._private(path, {"id": broker_order_id})
                return
            except ServiceError:
                continue

    async def open_orders(self) -> list[OrderResult]:
        found = await self._private("/ro/my/orders/market/open")
        return [
            OrderResult(
                broker_order_id=text(info.get("id")),
                status="submitted",
                symbol=text(info.get("coin")).upper(),
                raw={"currency": "AUD"},
            )
            for key in ("buyorders", "sellorders")
            for info in items(found.get(key))
        ]

    async def aclose(self) -> None:
        await self._web.aclose()


def _when(value: object) -> float | None:
    """CoinSpot's order time (an ISO date, or seconds or milliseconds since
    1970) in seconds, or None when it can't be read."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value / 1000 if value > 1e11 else float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp() if parsed.tzinfo is not None else None
