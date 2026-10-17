"""Any platform, by webhook: each approved order is posted as JSON to a URL.

For anything without its own adapter: TradersPost, a bot of your own, a
Discord or Slack channel, a no-code automation. The body is a JSON template
with placeholders ({symbol}, {code}, {side}, {qty}, {price}, {stop},
{take_profit}, {order_type}, {client_id}, {market}); the default suits
TradersPost-style receivers. An optional secret goes in a header, and the
body is signed (HMAC-SHA256, hex) in X-FCC-Signature so the receiver can
check it came from this PC.

A webhook can't say whether the order filled, so FCC books it as filled at
the decision's price, marked unconfirmed, and keeps the position itself for
stops and targets. Without an account URL the account check uses the
account size you enter; with one (and the JSON paths to read), it reads the
real balance first.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

import httpx

from free_claude_code.core.json_types import JsonObject

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
from .common import make_web, number, obj, text

DEFAULT_TEMPLATE: JsonObject = {
    "ticker": "{code}",
    "action": "{side}",
    "quantity": "{qty}",
    "orderType": "{order_type}",
    "price": "{price}",
    "stopLoss": {"stopPrice": "{stop}"},
    "takeProfit": {"limitPrice": "{take_profit}"},
    "clientOrderId": "{client_id}",
    "sentBy": "FCC Studio trading desk",
}


def render(template: object, values: Mapping[str, object]) -> object:
    """Fill a JSON template: a string that is just "{name}" becomes the typed
    value (a number stays a number); placeholders inside text are filled as
    text."""
    if isinstance(template, dict):
        return {key: render(value, values) for key, value in template.items()}
    if isinstance(template, list):
        return [render(item, values) for item in template]
    if isinstance(template, str):
        stripped = template.strip()
        if (
            stripped.startswith("{")
            and stripped.endswith("}")
            and stripped[1:-1] in values
        ):
            return values[stripped[1:-1]]
        filled = template
        for name, value in values.items():
            filled = filled.replace(
                "{" + name + "}", "" if value is None else str(value)
            )
        return filled
    return template


def dig(data: object, path: str) -> object:
    """Read a dotted path such as ``account.equity`` out of JSON."""
    for key in [part for part in path.split(".") if part]:
        if isinstance(data, list) and key.isdigit():
            index = int(key)
            data = data[index] if index < len(data) else None
        elif isinstance(data, dict):
            data = data.get(key)
        else:
            return None
    return data


class WebhookBroker:
    id = "webhook"
    name = "Any platform (webhook)"
    live = True
    supports_brackets = False
    reports_positions = False
    """FCC keeps the positions itself: a webhook can't report them."""

    def __init__(
        self,
        values: Mapping[str, str],
        data: MarketData,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._url = values.get("url", "").strip()
        if urlsplit(self._url).scheme not in {"http", "https"}:
            raise ValueError(
                "The webhook URL must start with https:// (or http:// on this PC)."
            )
        self._secret = values.get("secret", "")
        self._header = values.get("header") or "Authorization"
        raw_template = values.get("template", "").strip()
        try:
            self._template: object = (
                json.loads(raw_template) if raw_template else DEFAULT_TEMPLATE
            )
        except ValueError as error:
            raise ValueError(
                f"The webhook template isn't valid JSON: {error}"
            ) from error
        self._account_url = values.get("account_url", "").strip()
        self._equity_path = values.get("equity_path", "") or "equity"
        self._cash_path = values.get("cash_path", "") or "cash"
        self._size = number(values.get("account_size"), 0.0)
        self._currency = (values.get("currency") or "AUD").upper()
        host = urlsplit(self._url).hostname or "webhook"
        self._web = make_web(transport, host, per_second=2.0, burst=3)
        self._sent: dict[str, OrderResult] = {}
        self._tried: set[str] = set()
        self._clock = clock
        self._data = data

    def markets(self) -> frozenset[str]:
        return frozenset({"us", "asx", "crypto"})

    async def account(self) -> Account:
        equity = cash = self._size
        if self._account_url:
            body = await self._web.get_json(
                self._account_url, headers=self._auth_header(), what="The account URL"
            )
            equity = number(dig(body, self._equity_path), equity)
            cash = number(dig(body, self._cash_path), equity)
        if equity <= 0:
            raise ServiceError(
                "Enter the account size (or an account URL) for the webhook platform.",
                transient=False,
            )
        return Account(
            number=urlsplit(self._url).hostname or "webhook",
            fingerprint=fingerprint(self.id, self._url),
            currency=self._currency,
            equity=equity,
            cash=cash,
            buying_power=cash,
            live=True,
            note="Orders go to your webhook; fills aren't confirmed back.",
        )

    async def positions(self) -> list[Holding]:
        return []

    async def rules(self, instrument: Instrument) -> Rules:
        if not instrument.tradable:
            return Rules(tradable=False, note="DEX tokens can't be traded.")
        return Rules(
            tradable=True,
            broker_symbol=instrument.symbol,
            fractional=instrument.market != "asx",
            qty_step=1.0 if instrument.market == "asx" else 0.0,
        )

    async def quote(self, instrument: Instrument) -> Quote | None:
        return None

    def _auth_header(self) -> dict[str, str]:
        if not self._secret:
            return {}
        value = (
            self._secret
            if self._header != "Authorization" or " " in self._secret
            else f"Bearer {self._secret}"
        )
        return {self._header: value}

    async def place(self, order: OrderRequest) -> OrderResult:
        if order.client_id in self._sent:
            return self._sent[order.client_id]
        price = order.limit_price
        if price is None:
            quote = None
            try:
                quote = await self._data.quote(order.instrument)
            except Exception:
                quote = None
            price = quote.price if quote is not None else None
        values = {
            "symbol": order.instrument.symbol,
            "code": order.instrument.code,
            "market": order.instrument.market,
            "side": order.side,
            "qty": order.qty,
            "price": price,
            "stop": order.stop_loss,
            "take_profit": order.take_profit,
            "order_type": order.order_type,
            "client_id": order.client_id,
            "currency": order.price_currency,
        }
        body = json.dumps(render(self._template, values), separators=(",", ":"))
        self._tried.add(order.client_id)
        headers = {"Content-Type": "application/json", **self._auth_header()}
        if self._secret:
            headers["X-FCC-Signature"] = hmac.new(
                self._secret.encode(), body.encode(), hashlib.sha256
            ).hexdigest()
        response = await self._web.request(
            "POST",
            self._url,
            content=body,
            headers=headers,
            retry=False,
            what="The webhook",
        )
        reply: dict[str, object] = {}
        if response.content:
            try:
                reply = obj(read_json(response, what="The webhook"))
            except ServiceError:
                reply = {}
        result = OrderResult(
            broker_order_id=text(reply.get("id") or reply.get("order_id"))
            or f"webhook-{order.client_id}",
            status="filled",
            client_id=order.client_id,
            symbol=order.instrument.symbol,
            filled_qty=order.qty,
            fill_price=price,
            note="Sent by webhook; the fill isn't confirmed by the platform.",
            raw={"currency": order.price_currency, "unconfirmed": True},
        )
        self._sent[order.client_id] = result
        return result

    def remember(self, sent: Sent) -> None:
        """After a restart: an order that may have been posted (a webhook
        can't be asked, so it is never posted again)."""
        self._tried.add(sent.client_id)

    async def find(self, client_id: str) -> OrderResult | None:
        if client_id in self._sent:
            return self._sent[client_id]
        if client_id in self._tried:
            # It may have arrived: a webhook can't be asked, so never resend.
            raise ServiceError(
                "The webhook may have received this order; it was not sent again.",
                transient=False,
            )
        return None

    async def cancel(self, broker_order_id: str) -> None:
        return None

    async def open_orders(self) -> list[OrderResult]:
        return []

    async def aclose(self) -> None:
        await self._web.aclose()
