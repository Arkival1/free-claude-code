"""BTC Markets: an Australian exchange trading coins in AUD.

API v3. Private calls send BM-AUTH-APIKEY, BM-AUTH-TIMESTAMP (milliseconds),
and BM-AUTH-SIGNATURE: HMAC-SHA512, keyed with the base64-decoded secret,
over method + path + timestamp (+ the JSON body for POST), base64-encoded.
Orders carry FCC's client id, so a lost answer is looked up first.
"""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from urllib.parse import urlencode

import httpx

from ...resilience import ServiceError, read_json
from ..data import MarketData, Quote
from ..information import seconds_from_iso
from ..instruments import Instrument
from .base import (
    Account,
    Holding,
    OrderRequest,
    OrderResult,
    Rules,
    fingerprint,
)
from .common import Nonce, items, make_web, number, obj, text

HOST = "api.btcmarkets.net"
API = f"https://{HOST}"
MARKETS_SECONDS = 3600.0
STATUSES = {
    "Fully Matched": "filled",
    "Partially Matched": "partially_filled",
    "Cancelled": "cancelled",
    "Partially Cancelled": "cancelled",
    "Failed": "rejected",
}


def sign(method: str, path: str, timestamp: str, body: str, secret: str) -> str:
    message = f"{method}{path}{timestamp}{body}".encode()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


class BtcMarketsBroker:
    id = "btcmarkets"
    name = "BTC Markets"
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
        self._web = make_web(transport, HOST, per_second=3.0, burst=5)
        self._nonce = Nonce(clock)
        self._clock = clock
        self._markets: tuple[float, dict[str, dict[str, object]]] | None = None
        self._data = data

    def markets(self) -> frozenset[str]:
        return frozenset({"crypto"})

    async def _call(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        body: Mapping[str, object] | None = None,
        retry: bool = True,
    ) -> object:
        timestamp = str(self._nonce())
        payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "BM-AUTH-APIKEY": self._key,
            "BM-AUTH-TIMESTAMP": timestamp,
            "BM-AUTH-SIGNATURE": sign(method, path, timestamp, payload, self._secret),
        }
        url = f"{API}{path}" + (f"?{urlencode(query)}" if query else "")
        response = await self._web.request(
            method,
            url,
            content=payload or None,
            headers=headers,
            retry=retry and method == "GET",
            what="BTC Markets",
        )
        return read_json(response, what="BTC Markets") if response.content else {}

    async def _markets_by_id(self) -> dict[str, dict[str, object]]:
        now = self._clock()
        if self._markets is None or now - self._markets[0] > MARKETS_SECONDS:
            rows = items(
                await self._web.get_json(f"{API}/v3/markets", what="BTC Markets")
            )
            self._markets = (now, {text(row.get("marketId")): row for row in rows})
        return self._markets[1]

    async def account(self) -> Account:
        rows = items(await self._call("GET", "/v3/accounts/me/balances"))
        cash = 0.0
        equity = 0.0
        for row in rows:
            asset = text(row.get("assetName")).upper()
            balance = number(row.get("balance"))
            if asset == "AUD":
                cash = number(row.get("available"))
                equity += balance
            elif balance > 0:
                quote = await self._ticker(f"{asset}-AUD")
                equity += balance * (quote or 0.0)
        return Account(
            number=fingerprint(self.id, self._key),
            fingerprint=fingerprint(self.id, self._key),
            currency="AUD",
            equity=equity,
            cash=cash,
            buying_power=cash,
            live=True,
            note="BTC Markets account (identified by its API key).",
        )

    async def positions(self) -> list[Holding]:
        return [
            Holding(
                text(row.get("assetName")).upper(),
                number(row.get("balance")),
                0.0,
                "AUD",
            )
            for row in items(await self._call("GET", "/v3/accounts/me/balances"))
            if text(row.get("assetName")).upper() != "AUD"
            and number(row.get("balance")) > 0
        ]

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market != "crypto":
            return Rules(tradable=False, note="BTC Markets trades crypto only.")
        market_id = f"{instrument.symbol}-AUD"
        market = (await self._markets_by_id()).get(market_id)
        if market is None:
            return Rules(tradable=False, note=f"BTC Markets has no {market_id} market.")
        decimals = int(number(market.get("amountDecimals"), 8))
        return Rules(
            tradable=text(market.get("status") or "Online") == "Online",
            broker_symbol=market_id,
            min_qty=number(market.get("minOrderAmount")),
            qty_step=10.0**-decimals,
        )

    async def _ticker(self, market_id: str) -> float | None:
        try:
            body = obj(
                await self._web.get_json(
                    f"{API}/v3/markets/{market_id}/ticker", what="BTC Markets"
                )
            )
        except ServiceError:
            return None
        return number(body.get("lastPrice")) or None

    async def quote(self, instrument: Instrument) -> Quote | None:
        market_id = f"{instrument.symbol}-AUD"
        try:
            body = obj(
                await self._web.get_json(
                    f"{API}/v3/markets/{market_id}/ticker", what="BTC Markets"
                )
            )
        except ServiceError:
            return None
        last = number(body.get("lastPrice"))
        if last <= 0:
            return None
        at = seconds_from_iso(body.get("timestamp"))
        return Quote(
            instrument.symbol,
            last,
            "AUD",
            at or self._clock(),
            "BTC Markets",
            number(body.get("bestBid")) or None,
            number(body.get("bestAsk")) or None,
            stamped=at is not None,
        )

    async def place(self, order: OrderRequest) -> OrderResult:
        rules = await self.rules(order.instrument)
        if not rules.tradable:
            raise ServiceError(rules.note, transient=False)
        body: dict[str, object] = {
            "marketId": rules.broker_symbol,
            "amount": f"{order.qty:.10f}".rstrip("0").rstrip("."),
            "type": "Limit" if order.order_type == "limit" else "Market",
            "side": "Bid" if order.side == "buy" else "Ask",
            "clientOrderId": order.client_id,
        }
        if order.order_type == "limit" and order.limit_price is not None:
            limit = order.limit_price
            if order.price_currency != "AUD":
                limit *= await self._data.fx(order.price_currency, "AUD")
            body["price"] = f"{limit:.8g}"
        return _order(
            obj(await self._call("POST", "/v3/orders", body=body, retry=False))
        )

    async def find(self, client_id: str) -> OrderResult | None:
        for row in items(
            await self._call("GET", "/v3/orders", query={"status": "all", "limit": 100})
        ):
            if text(row.get("clientOrderId")) == client_id:
                return await self._with_fill(_order(row))
        return None

    async def _with_fill(self, result: OrderResult) -> OrderResult:
        """Add the average price and fees from the order's trades."""
        if result.filled_qty <= 0:
            return result
        try:
            trades = items(
                await self._call(
                    "GET", "/v3/trades", query={"orderId": result.broker_order_id}
                )
            )
        except ServiceError:
            return result
        amount = sum(number(t.get("amount")) for t in trades)
        if amount <= 0:
            return result
        price = (
            sum(number(t.get("price")) * number(t.get("amount")) for t in trades)
            / amount
        )
        fees = sum(number(t.get("fee")) for t in trades)
        return OrderResult(
            broker_order_id=result.broker_order_id,
            status=result.status,
            client_id=result.client_id,
            symbol=result.symbol,
            filled_qty=result.filled_qty,
            fill_price=price,
            fees=fees,
            raw=result.raw,
        )

    async def cancel(self, broker_order_id: str) -> None:
        await self._call("DELETE", f"/v3/orders/{broker_order_id}")

    async def open_orders(self) -> list[OrderResult]:
        return [
            _order(row)
            for row in items(
                await self._call("GET", "/v3/orders", query={"status": "open"})
            )
        ]

    async def aclose(self) -> None:
        await self._web.aclose()


def _order(row: Mapping[str, object]) -> OrderResult:
    amount = number(row.get("amount"))
    open_amount = number(row.get("openAmount"))
    status = text(row.get("status"))
    filled = (
        max(0.0, amount - open_amount) if row.get("openAmount") is not None else 0.0
    )
    mapped = STATUSES.get(status, "submitted")
    if mapped == "cancelled" and filled > 0:
        mapped = "partially_filled"
    return OrderResult(
        broker_order_id=text(row.get("orderId")),
        status=mapped,
        client_id=text(row.get("clientOrderId")),
        symbol=text(row.get("marketId")).split("-")[0],
        filled_qty=filled,
        fill_price=number(row.get("price")) or None,
        raw={"currency": "AUD", "fee_currency": "AUD", "status": status},
    )
