"""Swyftx (beta): an Australian exchange with a demo (practice) mode.

The API key is swapped for an access token (POST /auth/refresh/), sent as a
bearer token on every call. Orders are placed in AUD for a coin: market buy
and sell (types 1 and 2) or limit buy and sell (3 and 4, the trigger price).
Choose the demo environment first to practise with Swyftx's demo funds.

Swyftx has no client order ids: the desk keeps each order's Swyftx id, and
after a lost answer (or a restart) looks through recent orders for one of
the same side and size made since it was sent. When there is none it can't
tell whether the order went through, so it never sends again: the order
stays open and new trades pause until a later check matches it. Marked
beta: checked against open-source clients, not yet against a live account;
use the demo environment or a small order first.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

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
from .common import items, make_web, number, obj, text

LIVE_URL = "https://api.swyftx.com.au"
DEMO_URL = "https://api.demo.swyftx.com.au"
TOKEN_SECONDS = 50 * 60.0
ASSETS_SECONDS = 3600.0
ORDER_TYPES = {
    ("buy", "market"): 1,
    ("sell", "market"): 2,
    ("buy", "limit"): 3,
    ("sell", "limit"): 4,
}
DONE = {4, "4", "COMPLETED", "FILLED", "COMPLETE"}
CANCELLED = {5, "5", "CANCELLED", "CANCELED", 6, "6", "FAILED"}
SIDES = {1: "buy", 3: "buy", 2: "sell", 4: "sell"}
CLOCK_SKEW_SECONDS = 60.0
"""How far Swyftx's clock and this PC's may differ when matching times."""


@dataclass(frozen=True, slots=True)
class _Attempt:
    coin: str
    side: str
    qty: float
    at: float


class SwyftxBroker:
    id = "swyftx"
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
        self._demo = values.get("environment", "demo") != "live"
        self._base = DEMO_URL if self._demo else LIVE_URL
        self.name = "Swyftx (demo)" if self._demo else "Swyftx"
        self._web = make_web(
            transport, self._base.removeprefix("https://"), per_second=3.0, burst=5
        )
        self._clock = clock
        self._token: tuple[float, str] | None = None
        self._assets: tuple[float, dict[str, dict[str, object]]] | None = None
        self._attempts: dict[str, _Attempt] = {}
        self._ids: dict[str, str] = {}
        self._data = data

    def markets(self) -> frozenset[str]:
        return frozenset({"crypto"})

    async def _auth(self) -> dict[str, str]:
        now = self._clock()
        if self._token is None or now - self._token[0] > TOKEN_SECONDS:
            response = await self._web.request(
                "POST",
                f"{self._base}/auth/refresh/",
                json={"apiKey": self._key},
                what="Swyftx",
            )
            token = text(obj(read_json(response, what="Swyftx")).get("accessToken"))
            if not token:
                raise ServiceError(
                    "Swyftx didn't return an access token; check the API key.",
                    transient=False,
                )
            self._token = (now, token)
        return {"Authorization": f"Bearer {self._token[1]}"}

    async def _get(
        self, path: str, params: Mapping[str, object] | None = None
    ) -> object:
        return await self._web.get_json(
            f"{self._base}{path}",
            params=params,
            headers=await self._auth(),
            what="Swyftx",
        )

    async def _asset_codes(self) -> dict[str, dict[str, object]]:
        now = self._clock()
        if self._assets is None or now - self._assets[0] > ASSETS_SECONDS:
            rows = items(await self._get("/markets/assets/"))
            self._assets = (now, {text(row.get("code")).upper(): row for row in rows})
        return self._assets[1]

    async def account(self) -> Account:
        assets = await self._asset_codes()
        by_id = {text(row.get("id")): code for code, row in assets.items()}
        cash = 0.0
        equity = 0.0
        for row in items(await self._get("/user/balance/")):
            code = by_id.get(text(row.get("assetId")), "")
            amount = number(row.get("availableBalance"))
            if code == "AUD":
                cash = amount
                equity += amount
            elif amount > 0 and code:
                quote = await self.quote_code(code)
                equity += amount * (quote or 0.0)
        return Account(
            number=fingerprint(self.id + (":demo" if self._demo else ""), self._key),
            fingerprint=fingerprint(
                self.id + (":demo" if self._demo else ""), self._key
            ),
            currency="AUD",
            equity=equity,
            cash=cash,
            buying_power=cash,
            live=True,
            note="Swyftx demo account (practice funds)."
            if self._demo
            else "Swyftx account.",
        )

    async def positions(self) -> list[Holding]:
        assets = await self._asset_codes()
        by_id = {text(row.get("id")): code for code, row in assets.items()}
        return [
            Holding(
                by_id[text(row.get("assetId"))],
                number(row.get("availableBalance")),
                0.0,
                "AUD",
            )
            for row in items(await self._get("/user/balance/"))
            if by_id.get(text(row.get("assetId")), "AUD") != "AUD"
            and number(row.get("availableBalance")) > 0
        ]

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market != "crypto":
            return Rules(tradable=False, note="Swyftx trades crypto only.")
        if instrument.symbol not in await self._asset_codes():
            return Rules(
                tradable=False, note=f"Swyftx doesn't list {instrument.symbol}."
            )
        return Rules(tradable=True, broker_symbol=instrument.symbol, qty_step=1e-8)

    async def quote_code(self, code: str) -> float | None:
        try:
            response = await self._web.request(
                "POST",
                f"{self._base}/orders/rate/",
                json={"buy": code, "sell": "AUD", "amount": "1", "limit": code},
                headers=await self._auth(),
                what="Swyftx",
            )
        except ServiceError:
            return None
        body = obj(read_json(response, what="Swyftx"))
        return number(body.get("price")) or None

    async def quote(self, instrument: Instrument) -> Quote | None:
        price = await self.quote_code(instrument.symbol)
        if price is None:
            return None
        return Quote(instrument.symbol, price, "AUD", self._clock(), self.name)

    async def place(self, order: OrderRequest) -> OrderResult:
        coin = order.instrument.symbol
        self._attempts[order.client_id] = _Attempt(
            coin, order.side, order.qty, self._clock()
        )
        body: dict[str, object] = {
            "primary": "AUD",
            "secondary": coin,
            "quantity": f"{order.qty:.8f}".rstrip("0").rstrip("."),
            "assetQuantity": coin,
            "orderType": ORDER_TYPES[(order.side, order.order_type)],
        }
        if order.order_type == "limit" and order.limit_price is not None:
            limit = order.limit_price
            if order.price_currency != "AUD":
                limit *= await self._data.fx(order.price_currency, "AUD")
            body["trigger"] = f"{limit:.8g}"
        response = await self._web.request(
            "POST",
            f"{self._base}/orders/",
            json=body,
            headers=await self._auth(),
            retry=False,
            what="Swyftx",
        )
        found = obj(read_json(response, what="Swyftx"))
        uuid = text(found.get("orderUuid") or obj(found.get("order")).get("orderUuid"))
        if not uuid:
            raise ServiceError(
                f"Swyftx didn't confirm the order: {found}", transient=False
            )
        self._ids[order.client_id] = uuid
        details = obj(found.get("order"))
        return (
            _order(uuid, details, order.client_id, coin)
            if details
            else OrderResult(
                broker_order_id=uuid,
                status="submitted",
                client_id=order.client_id,
                symbol=coin,
                raw={"currency": "AUD"},
            )
        )

    def remember(self, sent: Sent) -> None:
        """After a restart: an order FCC sent, so ``find`` can look for it."""
        self._attempts.setdefault(
            sent.client_id, _Attempt(sent.symbol, sent.side, sent.qty, sent.at)
        )
        if sent.broker_order_id:
            self._ids.setdefault(sent.client_id, sent.broker_order_id)

    async def find(self, client_id: str) -> OrderResult | None:
        uuid = self._ids.get(client_id)
        attempt = self._attempts.get(client_id)
        if uuid:
            body = obj(await self._get(f"/orders/byId/{uuid}/"))
            return _order(uuid, body, client_id, attempt.coin if attempt else "")
        if attempt is None:
            return None
        recent = await self._get("/orders/", {"limit": 20})
        rows = items(recent if isinstance(recent, list) else obj(recent).get("orders"))
        for row in rows:
            if abs(number(row.get("quantity")) - attempt.qty) > max(
                1e-8, attempt.qty * 1e-6
            ):
                continue
            # Only an order made after this one was sent, on the same side,
            # can be it; one with no readable time can't be told apart from
            # an older one.
            created = number(row.get("created_time") or row.get("createdTime")) / 1000
            if not created or created < attempt.at - CLOCK_SKEW_SECONDS:
                continue
            kind = number(row.get("order_type") or row.get("orderType"))
            side = SIDES.get(int(kind)) if kind.is_integer() else None
            if side is not None and side != attempt.side:
                continue
            found_uuid = text(row.get("orderUuid"))
            self._ids[client_id] = found_uuid
            return _order(found_uuid, row, client_id, attempt.coin)
        # Not among the recent orders: it may never have arrived, or be older
        # than the list goes. Nobody can say, so it is not sent again.
        raise ServiceError(
            f"Swyftx shows no recent {attempt.coin} {attempt.side} of "
            f"{attempt.qty:g} since FCC sent it.",
            transient=False,
        )

    async def cancel(self, broker_order_id: str) -> None:
        await self._web.request(
            "DELETE",
            f"{self._base}/orders/{broker_order_id}/",
            headers=await self._auth(),
            what="Swyftx",
        )

    async def open_orders(self) -> list[OrderResult]:
        recent = await self._get("/orders/", {"limit": 50})
        rows = items(recent if isinstance(recent, list) else obj(recent).get("orders"))
        found = [_order(text(row.get("orderUuid")), row, "", "") for row in rows]
        return [order for order in found if order.status == "submitted"]

    async def aclose(self) -> None:
        await self._web.aclose()


def _order(
    uuid: str, row: Mapping[str, object], client_id: str, coin: str
) -> OrderResult:
    status = row.get("status")
    status_key = status.upper() if isinstance(status, str) else status
    amount = number(row.get("amount")) or number(row.get("quantity"))
    total = number(row.get("total"))
    rate = number(row.get("rate"))
    mapped = (
        "filled"
        if status_key in DONE
        else "cancelled"
        if status_key in CANCELLED
        else "submitted"
    )
    return OrderResult(
        broker_order_id=uuid,
        status=mapped,
        client_id=client_id,
        symbol=coin,
        filled_qty=amount if mapped == "filled" else 0.0,
        fill_price=rate or (total / amount if amount and total else None),
        fees=number(row.get("feeAudValue")),
        raw={"currency": "AUD", "fee_currency": "AUD", "status": str(status)},
    )
