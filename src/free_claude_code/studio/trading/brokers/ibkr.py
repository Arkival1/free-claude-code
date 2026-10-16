"""Interactive Brokers: ASX and US shares through IBKR's Client Portal Gateway.

IBKR Australia gives an Australian account access to the ASX and the US. The
owner runs IBKR's Client Portal Gateway on this PC (a small Java program from
IBKR) and logs in once in the browser at https://localhost:5000; FCC then
talks to it there. Only a gateway on this PC is accepted, and only there is
its self-signed certificate allowed.

Orders carry FCC's client id (cOID), so a lost answer is looked up among the
day's orders. When IBKR answers an order with a warning to confirm (a
"reply"), the desk never confirms it by itself: the order waits for the
owner's Approve, which answers the reply.
"""

import time
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

import httpx

from free_claude_code.core.json_types import JsonObject

from ...resilience import ServiceError, read_json
from ..data import MarketData, Quote
from ..instruments import Instrument
from .base import Account, Holding, OrderRequest, OrderResult, Rules, fingerprint
from .common import items, make_web, number, obj, text

DEFAULT_GATEWAY = "https://localhost:5000"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
STATUSES = {
    "Filled": "filled",
    "Cancelled": "cancelled",
    "ApiCancelled": "cancelled",
    "Inactive": "rejected",
    "Rejected": "rejected",
}


class IbkrSetupError(ValueError):
    """The gateway address isn't one FCC will use."""


class IbkrBroker:
    id = "ibkr"
    name = "Interactive Brokers"
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
        gateway = (values.get("gateway") or DEFAULT_GATEWAY).rstrip("/")
        host = urlsplit(gateway).hostname or ""
        if host not in LOOPBACK:
            raise IbkrSetupError(
                "The IBKR gateway must run on this PC (https://localhost:5000)."
            )
        self._base = f"{gateway}/v1/api"
        self._chosen = values.get("account", "").strip()
        self._web = make_web(transport, host, per_second=5.0, burst=5, verify=False)
        self._clock = clock
        self._conids: dict[str, int] = {}
        self._account_id = ""
        self._data = data

    def markets(self) -> frozenset[str]:
        return frozenset({"us", "asx"})

    async def _get(
        self, path: str, params: Mapping[str, object] | None = None
    ) -> object:
        return await self._web.get_json(
            f"{self._base}{path}", params=params, what="IBKR gateway"
        )

    async def _post(self, path: str, body: object, *, retry: bool = True) -> object:
        response = await self._web.request(
            "POST", f"{self._base}{path}", json=body, retry=retry, what="IBKR gateway"
        )
        return read_json(response, what="IBKR gateway") if response.content else {}

    async def _account(self) -> str:
        status = obj(await self._post("/iserver/auth/status", {}))
        if not status.get("authenticated"):
            raise ServiceError(
                "Log in to the IBKR gateway in your browser (https://localhost:5000), then try again.",
                transient=False,
            )
        await self._post("/tickle", {})
        body = obj(await self._get("/iserver/accounts"))
        listed = body.get("accounts")
        accounts = (
            [text(item) for item in listed if item] if isinstance(listed, list) else []
        )
        if self._chosen and self._chosen not in accounts:
            raise ServiceError(
                f"The gateway isn't logged in to account {self._chosen}.",
                transient=False,
            )
        chosen = (
            self._chosen
            or text(body.get("selectedAccount"))
            or (accounts[0] if accounts else "")
        )
        if not chosen:
            raise ServiceError("The IBKR gateway shows no accounts.", transient=False)
        self._account_id = chosen
        return chosen

    async def account(self) -> Account:
        account_id = await self._account()
        summary = obj(await self._get(f"/portfolio/{account_id}/summary"))
        equity = obj(summary.get("netliquidation"))
        return Account(
            number=account_id,
            fingerprint=fingerprint(self.id, account_id),
            currency=text(equity.get("currency")) or "AUD",
            equity=number(equity.get("amount")),
            cash=number(obj(summary.get("totalcashvalue")).get("amount")),
            buying_power=number(obj(summary.get("buyingpower")).get("amount")),
            live=True,
            note="Interactive Brokers via the gateway on this PC.",
        )

    async def positions(self) -> list[Holding]:
        account_id = self._account_id or await self._account()
        held: list[Holding] = []
        for row in items(await self._get(f"/portfolio/{account_id}/positions/0")):
            ticker = text(row.get("ticker") or row.get("contractDesc")).split(" ")[0]
            exchange = text(row.get("listingExchange"))
            symbol = f"{ticker}.AX" if exchange == "ASX" else ticker
            quantity = number(row.get("position"))
            if quantity:
                held.append(
                    Holding(
                        symbol,
                        quantity,
                        number(row.get("avgPrice") or row.get("avgCost")),
                        text(row.get("currency")) or "USD",
                        number(row.get("mktValue")) or None,
                    )
                )
        return held

    async def _conid(self, instrument: Instrument) -> int | None:
        if instrument.symbol in self._conids:
            return self._conids[instrument.symbol]
        body = obj(await self._get("/trsrv/stocks", {"symbols": instrument.code}))
        for entry in items(body.get(instrument.code)):
            for contract in items(entry.get("contracts")):
                exchange = text(contract.get("exchange"))
                wanted = (
                    exchange == "ASX"
                    if instrument.market == "asx"
                    else bool(contract.get("isUS"))
                )
                if wanted and contract.get("conid"):
                    conid = int(number(contract.get("conid")))
                    self._conids[instrument.symbol] = conid
                    return conid
        return None

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market not in {"us", "asx"}:
            return Rules(
                tradable=False, note="FCC trades shares through IBKR (ASX and US)."
            )
        conid = await self._conid(instrument)
        if conid is None:
            return Rules(tradable=False, note=f"IBKR has no {instrument.symbol} share.")
        return Rules(
            tradable=True,
            broker_symbol=str(conid),
            qty_step=1.0,
            fractional=False,
            min_value=500.0 if instrument.market == "asx" else 0.0,
            note="Whole shares; a first ASX parcel must be worth $500.",
        )

    async def quote(self, instrument: Instrument) -> Quote | None:
        conid = await self._conid(instrument)
        if conid is None:
            return None
        for _ in range(2):
            # The first snapshot only subscribes; the second has the prices.
            rows = items(
                await self._get(
                    "/iserver/marketdata/snapshot",
                    {"conids": conid, "fields": "31,84,86"},
                )
            )
            row = rows[0] if rows else {}
            raw = text(row.get("31"))
            # IBKR prefixes a halted symbol's price with H, and the last
            # close (no trade yet today) with C: neither is a live price, so
            # the quote says so and carries no time.
            halted, closed = raw.startswith("H"), raw.startswith("C")
            last = number(raw.lstrip("CH"))
            if last > 0:
                return Quote(
                    instrument.symbol,
                    last,
                    "AUD" if instrument.market == "asx" else "USD",
                    0.0 if halted or closed else self._clock(),
                    "IBKR",
                    number(row.get("84")) or None,
                    number(row.get("86")) or None,
                    note="halted" if halted else "last close" if closed else "",
                )
        return None

    async def place(self, order: OrderRequest) -> OrderResult:
        account_id = self._account_id or await self._account()
        conid = await self._conid(order.instrument)
        if conid is None:
            raise ServiceError(
                f"IBKR has no {order.instrument.symbol} share.", transient=False
            )
        ticket: dict[str, object] = {
            "conid": conid,
            "orderType": "LMT" if order.order_type == "limit" else "MKT",
            "side": order.side.upper(),
            "quantity": int(order.qty),
            "tif": "DAY",
            "cOID": order.client_id,
        }
        if order.order_type == "limit" and order.limit_price is not None:
            ticket["price"] = round(order.limit_price, 4)
        answer = await self._post(
            f"/iserver/account/{account_id}/orders", {"orders": [ticket]}, retry=False
        )
        return self._placed(answer, order.client_id, order.instrument.symbol)

    async def answer_reply(
        self, reply: JsonObject, client_id: str, symbol: str
    ) -> OrderResult:
        """The owner approved IBKR's warning: confirm it and see what follows."""
        reply_id = text(reply.get("reply_id"))
        if not reply_id:
            raise ServiceError("Nothing to confirm with IBKR.", transient=False)
        answer = await self._post(
            f"/iserver/reply/{reply_id}", {"confirmed": True}, retry=False
        )
        return self._placed(answer, client_id, symbol)

    def _placed(self, answer: object, client_id: str, symbol: str) -> OrderResult:
        rows = items(answer) or [obj(answer)]
        first = rows[0] if rows else {}
        if first.get("order_id"):
            status = STATUSES.get(text(first.get("order_status")), "submitted")
            return OrderResult(
                broker_order_id=text(first.get("order_id")),
                status=status,
                client_id=client_id,
                symbol=symbol,
            )
        if first.get("id") and first.get("message"):
            messages = first.get("message")
            text_messages = (
                [str(item) for item in messages]
                if isinstance(messages, list)
                else [str(messages)]
            )
            return OrderResult(
                broker_order_id="",
                status="needs_reply",
                client_id=client_id,
                symbol=symbol,
                note="IBKR asks you to confirm: " + " ".join(text_messages),
                raw={
                    "reply": {
                        "reply_id": text(first.get("id")),
                        "messages": text_messages,
                    }
                },
            )
        error = text(first.get("error") or obj(answer).get("error"))
        raise ServiceError(
            f"IBKR refused the order: {error or answer}", transient=False
        )

    async def find(self, client_id: str) -> OrderResult | None:
        body = obj(await self._get("/iserver/account/orders"))
        for row in items(body.get("orders")):
            if text(row.get("order_ref")) == client_id:
                return _order(row)
        return None

    async def cancel(self, broker_order_id: str) -> None:
        account_id = self._account_id or await self._account()
        await self._web.request(
            "DELETE",
            f"{self._base}/iserver/account/{account_id}/order/{broker_order_id}",
            what="IBKR gateway",
        )

    async def open_orders(self) -> list[OrderResult]:
        body = obj(await self._get("/iserver/account/orders"))
        return [
            _order(row)
            for row in items(body.get("orders"))
            if text(row.get("status")) in {"PreSubmitted", "Submitted", "PendingSubmit"}
        ]

    async def aclose(self) -> None:
        await self._web.aclose()


def _order(row: Mapping[str, object]) -> OrderResult:
    status = text(row.get("status"))
    filled = number(row.get("filledQuantity"))
    mapped = STATUSES.get(status, "submitted")
    if mapped == "submitted" and filled > 0:
        mapped = "partially_filled"
    exchange = text(row.get("listingExchange"))
    ticker = text(row.get("ticker"))
    return OrderResult(
        broker_order_id=text(row.get("orderId")),
        status=mapped,
        client_id=text(row.get("order_ref")),
        symbol=f"{ticker}.AX" if exchange == "ASX" else ticker,
        filled_qty=filled,
        fill_price=number(row.get("avgPrice")) or None,
        raw={
            "status": status,
            **({"currency": text(row.get("cashCcy"))} if row.get("cashCcy") else {}),
        },
    )
