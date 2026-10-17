"""Independent Reserve: an Australian exchange trading coins in AUD.

Private calls POST a JSON body holding apiKey, nonce, and signature: an
uppercase hex HMAC-SHA256, keyed with the secret, over the full URL, then
apiKey=, nonce=, and each parameter as name=value in the documented order,
joined by commas. Orders carry FCC's client id (clientId), so a lost answer
is looked up with GetOrderDetails before anything is sent again.
"""

import hashlib
import hmac
import time
from collections.abc import Callable, Mapping

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

HOST = "api.independentreserve.com"
API = f"https://{HOST}"
STATUSES = {
    "Filled": "filled",
    "PartiallyFilled": "partially_filled",
    "Cancelled": "cancelled",
    "PartiallyFilledAndCancelled": "partially_filled",
    "Expired": "cancelled",
    "Failed": "rejected",
}


def ir_code(symbol: str) -> str:
    """Independent Reserve's currency code: BTC is Xbt, the rest title case."""
    return "Xbt" if symbol.upper() == "BTC" else symbol.capitalize()


def fcc_code(code: str) -> str:
    return "BTC" if code.lower() == "xbt" else code.upper()


def signature(
    url: str, key: str, nonce: int, params: list[tuple[str, object]], secret: str
) -> str:
    parts = [
        url,
        f"apiKey={key}",
        f"nonce={nonce}",
        *(f"{name}={value}" for name, value in params),
    ]
    return (
        hmac.new(secret.encode(), ",".join(parts).encode(), hashlib.sha256)
        .hexdigest()
        .upper()
    )


class IndependentReserveBroker:
    id = "independentreserve"
    name = "Independent Reserve"
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
        self._web = make_web(transport, HOST, per_second=1.0, burst=2)
        self._nonce = Nonce(clock)
        self._clock = clock
        self._minimums: dict[str, float] | None = None
        self._data = data

    def markets(self) -> frozenset[str]:
        return frozenset({"crypto"})

    async def _private(
        self, method: str, params: list[tuple[str, object]], *, retry: bool = True
    ) -> object:
        url = f"{API}/Private/{method}"
        nonce = self._nonce()
        body: dict[str, object] = {
            "apiKey": self._key,
            "nonce": nonce,
            **dict(params),
            "signature": signature(url, self._key, nonce, params, self._secret),
        }
        response = await self._web.request(
            "POST", url, json=body, retry=retry, what="Independent Reserve"
        )
        return read_json(response, what="Independent Reserve")

    async def _public(
        self, method: str, params: Mapping[str, object] | None = None
    ) -> object:
        return await self._web.get_json(
            f"{API}/Public/{method}", params=params, what="Independent Reserve"
        )

    async def account(self) -> Account:
        rows = items(await self._private("GetAccounts", []))
        cash = 0.0
        equity = 0.0
        guid = ""
        for row in rows:
            code = text(row.get("CurrencyCode"))
            total = number(row.get("TotalBalance"))
            if code.lower() == "aud":
                cash = number(row.get("AvailableBalance"))
                equity += total
                guid = text(row.get("AccountGuid"))
            elif total > 0:
                price = await self._last(code)
                equity += total * (price or 0.0)
        return Account(
            number=guid or fingerprint(self.id, self._key),
            fingerprint=fingerprint(self.id, guid or self._key),
            currency="AUD",
            equity=equity,
            cash=cash,
            buying_power=cash,
            live=True,
        )

    async def positions(self) -> list[Holding]:
        return [
            Holding(
                fcc_code(text(row.get("CurrencyCode"))),
                number(row.get("TotalBalance")),
                0.0,
                "AUD",
            )
            for row in items(await self._private("GetAccounts", []))
            if text(row.get("CurrencyCode")).lower() != "aud"
            and number(row.get("TotalBalance")) > 0
        ]

    async def _last(self, code: str) -> float | None:
        try:
            body = obj(
                await self._public(
                    "GetMarketSummary",
                    {
                        "primaryCurrencyCode": code.lower(),
                        "secondaryCurrencyCode": "aud",
                    },
                )
            )
        except ServiceError:
            return None
        return number(body.get("LastPrice")) or None

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market != "crypto":
            return Rules(tradable=False, note="Independent Reserve trades crypto only.")
        if self._minimums is None:
            body = obj(await self._public("GetOrderMinimumVolumes"))
            self._minimums = {key.lower(): number(value) for key, value in body.items()}
        code = ir_code(instrument.symbol)
        if code.lower() not in self._minimums:
            return Rules(
                tradable=False,
                note=f"Independent Reserve doesn't list {instrument.symbol}.",
            )
        return Rules(
            tradable=True,
            broker_symbol=code,
            min_qty=self._minimums[code.lower()],
            qty_step=1e-8,
        )

    async def quote(self, instrument: Instrument) -> Quote | None:
        try:
            body = obj(
                await self._public(
                    "GetMarketSummary",
                    {
                        "primaryCurrencyCode": ir_code(instrument.symbol).lower(),
                        "secondaryCurrencyCode": "aud",
                    },
                )
            )
        except ServiceError:
            return None
        last = number(body.get("LastPrice"))
        if last <= 0:
            return None
        at = seconds_from_iso(body.get("CreatedTimestampUtc"))
        return Quote(
            instrument.symbol,
            last,
            "AUD",
            at or self._clock(),
            "Independent Reserve",
            number(body.get("CurrentHighestBidPrice")) or None,
            number(body.get("CurrentLowestOfferPrice")) or None,
            stamped=at is not None,
        )

    async def place(self, order: OrderRequest) -> OrderResult:
        rules = await self.rules(order.instrument)
        if not rules.tradable:
            raise ServiceError(rules.note, transient=False)
        volume = f"{order.qty:.8f}".rstrip("0").rstrip(".")
        if order.order_type == "limit" and order.limit_price is not None:
            limit = order.limit_price
            if order.price_currency != "AUD":
                limit *= await self._data.fx(order.price_currency, "AUD")
            params: list[tuple[str, object]] = [
                ("primaryCurrencyCode", rules.broker_symbol),
                ("secondaryCurrencyCode", "Aud"),
                ("orderType", "LimitBid" if order.side == "buy" else "LimitOffer"),
                ("price", f"{limit:.2f}"),
                ("volume", volume),
                ("clientId", order.client_id),
            ]
            method = "PlaceLimitOrder"
        else:
            params = [
                ("primaryCurrencyCode", rules.broker_symbol),
                ("secondaryCurrencyCode", "Aud"),
                ("orderType", "MarketBid" if order.side == "buy" else "MarketOffer"),
                ("volume", volume),
                ("clientId", order.client_id),
            ]
            method = "PlaceMarketOrder"
        return _order(
            obj(await self._private(method, params, retry=False)), order.client_id
        )

    async def find(self, client_id: str) -> OrderResult | None:
        try:
            body = obj(
                await self._private("GetOrderDetails", [("clientId", client_id)])
            )
        except ServiceError as error:
            if error.status in {400, 404} or "not found" in str(error).lower():
                return None
            raise
        return _order(body, client_id) if body else None

    async def cancel(self, broker_order_id: str) -> None:
        await self._private("CancelOrder", [("orderGuid", broker_order_id)])

    async def open_orders(self) -> list[OrderResult]:
        body = obj(
            await self._private("GetOpenOrders", [("pageIndex", 1), ("pageSize", 50)])
        )
        return [
            _order(row, text(row.get("ClientId"))) for row in items(body.get("Data"))
        ]

    async def aclose(self) -> None:
        await self._web.aclose()


def _order(row: Mapping[str, object], client_id: str) -> OrderResult:
    status = text(row.get("Status"))
    return OrderResult(
        broker_order_id=text(row.get("OrderGuid")),
        status=STATUSES.get(status, "submitted"),
        client_id=client_id,
        symbol=fcc_code(text(row.get("PrimaryCurrencyCode"))),
        filled_qty=number(row.get("VolumeFilled")),
        fill_price=number(row.get("AvgPrice")) or None,
        fees=number(row.get("FeePercent"))
        * number(row.get("VolumeFilled"))
        * number(row.get("AvgPrice")),
        raw={"currency": "AUD", "fee_currency": "AUD", "status": status},
    )
