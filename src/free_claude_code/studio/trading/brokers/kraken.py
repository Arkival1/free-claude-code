"""Kraken: crypto (meme coins included) in Australian or US dollars.

Kraken is available in Australia. Private calls are signed the documented
way: HMAC-SHA512, keyed with the base64-decoded secret, over the URL path
plus the SHA-256 of the nonce and the form body. Orders carry a client order
id (a UUID made from FCC's own id), so a lost answer is looked up, never
re-sent blindly. The pair is the coin against the chosen currency (AUD by
default), falling back to USD where Kraken has no AUD market.
"""

import base64
import hashlib
import hmac
import time
import uuid
from collections.abc import Callable, Mapping
from urllib.parse import urlencode

import httpx

from ...resilience import ServiceError, read_json
from ..data import MarketData, Quote
from ..instruments import Instrument
from .base import Account, Holding, OrderRequest, OrderResult, Rules, fingerprint
from .common import Nonce, make_web, number, obj, text

API = "https://api.kraken.com"
PAIRS_SECONDS = 3600.0
CLIENT_IDS = uuid.UUID("6f2a43c1-2a5d-4f8e-9c55-3b2d7e1fcc00")
"""A fixed namespace: FCC's client id always maps to the same Kraken UUID."""

ALIASES = {"BTC": ("XBT", "BTC"), "DOGE": ("XDG", "DOGE")}
"""Kraken's own codes for a few coins."""

TRANSIENT_ERRORS = (
    "EAPI:Rate limit",
    "EService:",
    "EGeneral:Temporary",
    "EOrder:Rate limit",
)
STATUSES = {"canceled": "cancelled", "expired": "cancelled"}


def sign(path: str, body: str, nonce: str, secret: str) -> str:
    """Kraken's API-Sign for one private call."""
    digest = hashlib.sha256((nonce + body).encode()).digest()
    mac = hmac.new(base64.b64decode(secret), path.encode() + digest, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def kraken_client_id(client_id: str) -> str:
    return str(uuid.uuid5(CLIENT_IDS, client_id))


def fcc_asset(code: str) -> str:
    """XXBT → BTC, XETH → ETH, XXDG → DOGE, ZAUD → AUD, SOL → SOL."""
    name = code.split(".")[0]
    if (
        len(name) == 4
        and name[0] in "XZ"
        and name[1:]
        in {
            "XBT",
            "XDG",
            "ETH",
            "LTC",
            "XRP",
            "XLM",
            "ETC",
            "MLN",
            "REP",
            "ZEC",
            "XMR",
            "AUD",
            "USD",
            "EUR",
            "GBP",
            "CAD",
            "JPY",
        }
    ):
        name = name[1:]
    return {"XBT": "BTC", "XDG": "DOGE"}.get(name, name)


class KrakenBroker:
    id = "kraken"
    name = "Kraken"
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
        self._quote = (values.get("quote") or "AUD").upper()
        self._web = make_web(transport, "api.kraken.com", per_second=1.0, burst=3)
        self._nonce = Nonce(clock)
        self._clock = clock
        self._pairs: tuple[float, dict[str, dict[str, object]]] | None = None
        self._data = data

    def markets(self) -> frozenset[str]:
        return frozenset({"crypto"})

    async def _private(
        self,
        method: str,
        fields: Mapping[str, object] | None = None,
        *,
        retry: bool = True,
    ) -> dict[str, object]:
        path = f"/0/private/{method}"
        nonce = str(self._nonce())
        body = urlencode(
            {
                "nonce": nonce,
                **{k: v for k, v in (fields or {}).items() if v is not None},
            }
        )
        response = await self._web.request(
            "POST",
            f"{API}{path}",
            content=body,
            headers={
                "API-Key": self._key,
                "API-Sign": sign(path, body, nonce, self._secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            retry=retry,
            what="Kraken",
        )
        return _result(read_json(response, what="Kraken"))

    async def _public(
        self, method: str, params: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        return _result(
            await self._web.get_json(
                f"{API}/0/public/{method}", params=params, what="Kraken"
            )
        )

    async def _pair(
        self, instrument: Instrument
    ) -> tuple[str, dict[str, object]] | None:
        now = self._clock()
        if self._pairs is None or now - self._pairs[0] > PAIRS_SECONDS:
            found = await self._public("AssetPairs")
            self._pairs = (
                now,
                {
                    text(info.get("altname")): info
                    for info in (obj(value) for value in found.values())
                    if info.get("altname")
                },
            )
        pairs = self._pairs[1]
        codes = ALIASES.get(instrument.symbol, (instrument.symbol,))
        for quote_currency in dict.fromkeys((self._quote, "USD")):
            for code in codes:
                name = f"{code}{quote_currency}"
                if name in pairs:
                    return name, pairs[name]
        return None

    async def account(self) -> Account:
        balances = await self._private("Balance")
        quote_code = {"AUD": "ZAUD", "USD": "ZUSD"}.get(self._quote, self._quote)
        trade = await self._private("TradeBalance", {"asset": quote_code})
        cash = sum(
            number(value)
            for key, value in balances.items()
            if fcc_asset(key) == self._quote
        )
        return Account(
            number=self._key[-8:],
            fingerprint=fingerprint(self.id, self._key),
            currency=self._quote,
            equity=number(trade.get("eb"), cash),
            cash=cash,
            buying_power=cash,
            live=True,
            note="Kraken account (identified by its API key).",
        )

    async def positions(self) -> list[Holding]:
        balances = await self._private("Balance")
        return [
            Holding(
                symbol=fcc_asset(key),
                qty=number(value),
                avg_price=0.0,
                currency=self._quote,
            )
            for key, value in balances.items()
            if number(value) > 0
            and fcc_asset(key) not in {"AUD", "USD", "EUR", "GBP", "CAD", "JPY"}
        ]

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market != "crypto":
            return Rules(tradable=False, note="Kraken trades crypto only.")
        found = await self._pair(instrument)
        if found is None:
            return Rules(
                tradable=False, note=f"Kraken has no {instrument.symbol} market."
            )
        name, info = found
        decimals = int(number(info.get("lot_decimals"), 8))
        return Rules(
            tradable=text(info.get("status") or "online") == "online",
            broker_symbol=name,
            min_qty=number(info.get("ordermin")),
            qty_step=10.0**-decimals,
            min_value=number(info.get("costmin")),
        )

    async def quote(self, instrument: Instrument) -> Quote | None:
        found = await self._pair(instrument)
        if found is None:
            return None
        name, info = found
        try:
            tickers = await self._public("Ticker", {"pair": name})
        except ServiceError:
            return None
        row = obj(next(iter(tickers.values()), {}))
        last = _first(row.get("c"))
        bid, ask = _first(row.get("b")), _first(row.get("a"))
        if last <= 0:
            return None
        currency = fcc_asset(text(info.get("quote")) or self._quote)
        return Quote(
            instrument.symbol,
            last,
            currency,
            self._clock(),
            "Kraken",
            bid or None,
            ask or None,
        )

    async def place(self, order: OrderRequest) -> OrderResult:
        rules = await self.rules(order.instrument)
        if not rules.tradable:
            raise ServiceError(rules.note, transient=False)
        fields: dict[str, object] = {
            "ordertype": order.order_type,
            "type": order.side,
            "volume": f"{order.qty:.10f}".rstrip("0").rstrip("."),
            "pair": rules.broker_symbol,
            "cl_ord_id": kraken_client_id(order.client_id),
        }
        pair_currency = await self._pair_currency(order.instrument)
        if order.order_type == "limit" and order.limit_price is not None:
            limit = order.limit_price
            if order.price_currency != pair_currency:
                limit *= await self._data.fx(order.price_currency, pair_currency)
            fields["price"] = f"{limit:.8g}"
        result = await self._private("AddOrder", fields, retry=False)
        txids = result.get("txid")
        txid = txids[0] if isinstance(txids, list) and txids else ""
        return OrderResult(
            broker_order_id=text(txid),
            status="submitted",
            client_id=order.client_id,
            symbol=order.instrument.symbol,
            note=text(obj(result.get("descr")).get("order")),
            raw={"currency": pair_currency},
        )

    async def _pair_currency(self, instrument: Instrument) -> str:
        found = await self._pair(instrument)
        if found is None:
            return self._quote
        return fcc_asset(text(found[1].get("quote")) or self._quote)

    async def find(self, client_id: str) -> OrderResult | None:
        wanted = kraken_client_id(client_id)
        for method, key in (("OpenOrders", "open"), ("ClosedOrders", "closed")):
            found = await self._private(method, {"cl_ord_id": wanted})
            for txid, row in obj(found.get(key)).items():
                details = obj(row)
                if text(details.get("cl_ord_id")) in {wanted, ""}:
                    return _order(txid, details, client_id)
        return None

    async def cancel(self, broker_order_id: str) -> None:
        await self._private("CancelOrder", {"txid": broker_order_id})

    async def open_orders(self) -> list[OrderResult]:
        found = await self._private("OpenOrders")
        return [
            _order(txid, obj(row), "") for txid, row in obj(found.get("open")).items()
        ]

    async def aclose(self) -> None:
        await self._web.aclose()


def _result(body: object) -> dict[str, object]:
    data = obj(body)
    errors = data.get("error")
    if isinstance(errors, list) and errors:
        message = "; ".join(str(item) for item in errors)
        raise ServiceError(
            f"Kraken: {message}",
            transient=any(message.startswith(prefix) for prefix in TRANSIENT_ERRORS),
            host="api.kraken.com",
        )
    return obj(data.get("result"))


def _first(value: object) -> float:
    return number(value[0]) if isinstance(value, list) and value else 0.0


def _order(txid: str, row: Mapping[str, object], client_id: str) -> OrderResult:
    """A Kraken order; its prices and fees are in the pair's quote currency."""
    executed = number(row.get("vol_exec"))
    status = text(row.get("status"))
    mapped = STATUSES.get(status, "submitted")
    if status == "closed":
        mapped = "filled" if executed > 0 else "cancelled"
    elif executed > 0 and status == "open":
        mapped = "partially_filled"
    descr = obj(row.get("descr"))
    pair = text(descr.get("pair"))
    currency = next((c for c in ("AUD", "USD", "EUR", "GBP") if pair.endswith(c)), "")
    return OrderResult(
        broker_order_id=txid,
        status=mapped,
        client_id=client_id,
        symbol=fcc_asset(pair[: -len(currency)]) if currency else fcc_asset(pair),
        filled_qty=executed,
        fill_price=number(row.get("price")) or None,
        fees=number(row.get("fee")),
        raw={"status": status, **({"currency": currency} if currency else {})},
    )
