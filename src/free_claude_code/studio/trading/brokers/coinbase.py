"""Coinbase Advanced Trade: crypto with a Coinbase Developer Platform API key.

Requests carry a short-lived JWT signed with the key's private key: ES256 for
an ECDSA key (a PEM block), EdDSA for an Ed25519 key (base64). Orders carry
FCC's client id, which Coinbase uses to refuse a duplicate, and a lost answer
is looked up among recent orders before anything is sent again. Coins trade
against US dollars (or USDC) by default.
"""

import base64
import json
import secrets
import time
from collections.abc import Callable, Mapping

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

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
    masked,
)
from .common import items, make_web, number, obj, text

HOST = "api.coinbase.com"
API = f"https://{HOST}"
STATUSES = {
    "FILLED": "filled",
    "CANCELLED": "cancelled",
    "EXPIRED": "cancelled",
    "FAILED": "rejected",
}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwt_token(
    key_name: str,
    private_key: str,
    method: str,
    path: str,
    *,
    now: float | None = None,
    nonce: str | None = None,
) -> str:
    """A two-minute JWT for one request (``path`` without the query)."""
    issued = int(now if now is not None else time.time())
    uri = f"{method} {HOST}{path}"
    pem = private_key.strip().replace("\\n", "\n")
    if pem.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ServiceError(
                "That Coinbase key isn't an ECDSA (ES256) key.", transient=False
            )
        algorithm = "ES256"
        payload = {
            "sub": key_name,
            "iss": "cdp",
            "nbf": issued,
            "exp": issued + 120,
            "uri": uri,
        }
    else:
        try:
            seed = base64.b64decode(pem)[:32]
            key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        except ValueError as error:
            raise ServiceError(
                "That Coinbase private key can't be read.", transient=False
            ) from error
        algorithm = "EdDSA"
        payload = {
            "sub": key_name,
            "iss": "cdp",
            "aud": ["cdp_service"],
            "nbf": issued,
            "exp": issued + 120,
            "uris": [uri],
        }
    header = {
        "alg": algorithm,
        "kid": key_name,
        "nonce": nonce or secrets.token_hex(16),
        "typ": "JWT",
    }
    signing = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    if isinstance(key, ec.EllipticCurvePrivateKey):
        r, s = decode_dss_signature(
            key.sign(signing.encode(), ec.ECDSA(hashes.SHA256()))
        )
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        signature = key.sign(signing.encode())
    return f"{signing}.{_b64url(signature)}"


class CoinbaseBroker:
    id = "coinbase"
    name = "Coinbase"
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
        self._key_name = values.get("key_name", "")
        self._private_key = values.get("private_key", "")
        self._quote = (values.get("quote") or "USD").upper()
        self._web = make_web(transport, HOST, per_second=5.0, burst=5)
        self._clock = clock
        self._data = data

    def markets(self) -> frozenset[str]:
        return frozenset({"crypto"})

    def _headers(self, method: str, path: str) -> dict[str, str]:
        token = jwt_token(
            self._key_name, self._private_key, method, path, now=self._clock()
        )
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def _get(
        self, path: str, params: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        return obj(
            await self._web.get_json(
                f"{API}{path}",
                params=params,
                headers=self._headers("GET", path),
                what="Coinbase",
            )
        )

    def _product(self, instrument: Instrument) -> str:
        return f"{instrument.symbol}-{self._quote}"

    async def account(self) -> Account:
        body = await self._get("/api/v3/brokerage/accounts", {"limit": 250})
        cash = 0.0
        equity = 0.0
        for row in items(body.get("accounts")):
            currency = text(row.get("currency")).upper()
            amount = number(obj(row.get("available_balance")).get("value")) + number(
                obj(row.get("hold")).get("value")
            )
            if currency in {self._quote, "USD", "USDC"} and currency == self._quote:
                cash += number(obj(row.get("available_balance")).get("value"))
                equity += amount
            elif amount > 0:
                try:
                    product = await self._get(
                        f"/api/v3/brokerage/products/{currency}-{self._quote}"
                    )
                    equity += amount * number(product.get("price"))
                except ServiceError:
                    continue
        return Account(
            number=masked(self._key_name.rsplit("/", 1)[-1]),
            fingerprint=fingerprint(self.id, self._key_name),
            currency="USD" if self._quote == "USDC" else self._quote,
            equity=equity,
            cash=cash,
            buying_power=cash,
            live=True,
            note="Coinbase Advanced Trade (identified by its API key).",
        )

    async def positions(self) -> list[Holding]:
        body = await self._get("/api/v3/brokerage/accounts", {"limit": 250})
        found: list[Holding] = []
        for row in items(body.get("accounts")):
            currency = text(row.get("currency")).upper()
            amount = number(obj(row.get("available_balance")).get("value")) + number(
                obj(row.get("hold")).get("value")
            )
            if amount > 0 and currency not in {"USD", "USDC", "AUD", "EUR", "GBP"}:
                found.append(Holding(currency, amount, 0.0, self._quote))
        return found

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market != "crypto":
            return Rules(tradable=False, note="Coinbase trades crypto only.")
        product_id = self._product(instrument)
        try:
            product = await self._get(f"/api/v3/brokerage/products/{product_id}")
        except ServiceError as error:
            if error.status in {400, 404}:
                return Rules(
                    tradable=False, note=f"Coinbase has no {product_id} market."
                )
            raise
        disabled = bool(product.get("trading_disabled")) or bool(
            product.get("is_disabled")
        )
        return Rules(
            tradable=not disabled
            and text(product.get("status") or "online") == "online",
            broker_symbol=product_id,
            min_qty=number(product.get("base_min_size")),
            qty_step=number(product.get("base_increment")),
            min_value=number(product.get("quote_min_size")),
        )

    async def quote(self, instrument: Instrument) -> Quote | None:
        product_id = self._product(instrument)
        try:
            body = await self._get(
                "/api/v3/brokerage/best_bid_ask", {"product_ids": product_id}
            )
        except ServiceError:
            return None
        books = items(body.get("pricebooks"))
        if not books:
            return None
        bids, asks = items(books[0].get("bids")), items(books[0].get("asks"))
        bid = number(bids[0].get("price")) if bids else 0.0
        ask = number(asks[0].get("price")) if asks else 0.0
        if bid <= 0 or ask <= 0:
            return None
        currency = "USD" if self._quote == "USDC" else self._quote
        at = seconds_from_iso(books[0].get("time"))
        return Quote(
            instrument.symbol,
            (bid + ask) / 2,
            currency,
            at or self._clock(),
            "Coinbase",
            bid,
            ask,
            stamped=at is not None,
        )

    async def place(self, order: OrderRequest) -> OrderResult:
        rules = await self.rules(order.instrument)
        if not rules.tradable:
            raise ServiceError(rules.note, transient=False)
        size = f"{order.qty:.10f}".rstrip("0").rstrip(".")
        if order.order_type == "limit" and order.limit_price is not None:
            limit = order.limit_price
            if order.price_currency != rules_currency(self._quote):
                limit *= await self._data.fx(
                    order.price_currency, rules_currency(self._quote)
                )
            configuration: dict[str, object] = {
                "limit_limit_gtc": {
                    "base_size": size,
                    "limit_price": f"{limit:.8g}",
                    "post_only": False,
                }
            }
        else:
            configuration = {"market_market_ioc": {"base_size": size}}
        path = "/api/v3/brokerage/orders"
        response = await self._web.request(
            "POST",
            f"{API}{path}",
            json={
                "client_order_id": order.client_id,
                "product_id": rules.broker_symbol,
                "side": order.side.upper(),
                "order_configuration": configuration,
            },
            headers=self._headers("POST", path),
            retry=False,
            what="Coinbase",
        )
        body = obj(read_json(response, what="Coinbase"))
        if not body.get("success"):
            error = obj(body.get("error_response"))
            raise ServiceError(
                f"Coinbase refused the order: {text(error.get('message') or error.get('error') or body.get('failure_reason'))}",
                transient=False,
            )
        made = obj(body.get("success_response"))
        return OrderResult(
            broker_order_id=text(made.get("order_id")),
            status="submitted",
            client_id=order.client_id,
            symbol=order.instrument.symbol,
            raw={"currency": rules_currency(self._quote)},
        )

    async def _recent(self, params: Mapping[str, object]) -> list[OrderResult]:
        body = await self._get("/api/v3/brokerage/orders/historical/batch", params)
        return [_order(row, self._quote) for row in items(body.get("orders"))]

    async def find(self, client_id: str) -> OrderResult | None:
        for result in await self._recent({"limit": 100}):
            if result.client_id == client_id:
                return result
        return None

    async def cancel(self, broker_order_id: str) -> None:
        path = "/api/v3/brokerage/orders/batch_cancel"
        await self._web.request(
            "POST",
            f"{API}{path}",
            json={"order_ids": [broker_order_id]},
            headers=self._headers("POST", path),
            what="Coinbase",
        )

    async def open_orders(self) -> list[OrderResult]:
        return await self._recent({"order_status": "OPEN", "limit": 100})

    async def aclose(self) -> None:
        await self._web.aclose()


def rules_currency(quote: str) -> str:
    return "USD" if quote == "USDC" else quote


def _order(row: Mapping[str, object], quote: str) -> OrderResult:
    status = text(row.get("status")).upper()
    filled = number(row.get("filled_size"))
    mapped = STATUSES.get(status, "submitted")
    if status == "OPEN" and filled > 0:
        mapped = "partially_filled"
    product = text(row.get("product_id"))
    return OrderResult(
        broker_order_id=text(row.get("order_id")),
        status=mapped,
        client_id=text(row.get("client_order_id")),
        symbol=product.split("-")[0] if product else "",
        filled_qty=filled,
        fill_price=number(row.get("average_filled_price")) or None,
        fees=number(row.get("total_fees")),
        raw={"currency": rules_currency(quote), "status": status},
    )
