"""Alpaca: US shares, ETFs, and crypto, with a free paper (practice) account.

Anyone can open a paper account; live accounts are open to residents of many
countries (check Australia at sign-up). Every order carries FCC's client id,
so a retry never doubles one. A buy of whole shares with a stop and a target
goes as a bracket order: the stop-loss and take-profit then sit on Alpaca's
servers and work while the PC is off. Fractional shares and crypto can't be
bracketed, so the desk watches those stops itself.
"""

from collections.abc import Mapping
from dataclasses import replace
from urllib.parse import quote

import httpx

from ...resilience import ServiceError, read_json
from ..data import MarketData, Quote
from ..instruments import Instrument
from .base import Account, Holding, OrderRequest, OrderResult, Rules, fingerprint
from .common import items, make_web, number, obj, text

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"

STATUSES = {
    "filled": "filled",
    "partially_filled": "partially_filled",
    "canceled": "cancelled",
    "expired": "cancelled",
    "done_for_day": "cancelled",
    "rejected": "rejected",
}


def alpaca_symbol(instrument: Instrument) -> str:
    return (
        f"{instrument.symbol}/USD"
        if instrument.market == "crypto"
        else instrument.symbol
    )


def fcc_symbol(symbol: str, asset_class: str) -> str:
    if asset_class == "crypto":
        return symbol.replace("/", "").removesuffix("USD")
    return symbol


class AlpacaBroker:
    id = "alpaca"
    live = True
    supports_brackets = True

    def __init__(
        self,
        values: Mapping[str, str],
        data: MarketData,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._paper = values.get("account", "paper") != "live"
        self._base = PAPER_URL if self._paper else LIVE_URL
        self._headers = {
            "APCA-API-KEY-ID": values.get("key_id", ""),
            "APCA-API-SECRET-KEY": values.get("secret", ""),
        }
        host = self._base.removeprefix("https://")
        self._web = make_web(transport, host, per_second=3.0, burst=5)
        self._data = data
        self.name = "Alpaca (paper)" if self._paper else "Alpaca"

    def markets(self) -> frozenset[str]:
        return frozenset({"us", "crypto"})

    async def _get(
        self, path: str, params: Mapping[str, object] | None = None, *, base: str = ""
    ) -> object:
        return await self._web.get_json(
            f"{base or self._base}{path}",
            params=params,
            headers=self._headers,
            what="Alpaca",
        )

    async def account(self) -> Account:
        body = obj(await self._get("/v2/account"))
        blocked = bool(body.get("account_blocked")) or bool(body.get("trading_blocked"))
        status = (
            "blocked"
            if blocked
            else "active"
            if text(body.get("status")).upper() == "ACTIVE"
            else "restricted"
        )
        number_text = text(body.get("account_number"))
        return Account(
            number=number_text,
            fingerprint=fingerprint(self.id, number_text),
            currency=text(body.get("currency")) or "USD",
            equity=number(body.get("equity")),
            cash=number(body.get("cash")),
            buying_power=number(body.get("buying_power")),
            status=status,
            live=True,
            day_trades=int(number(body.get("daytrade_count"))),
            pattern_day_trader=bool(body.get("pattern_day_trader")),
            note="Paper account (practice money)." if self._paper else "Live account.",
        )

    async def positions(self) -> list[Holding]:
        return [
            Holding(
                symbol=fcc_symbol(
                    text(row.get("symbol")), text(row.get("asset_class"))
                ),
                qty=number(row.get("qty")),
                avg_price=number(row.get("avg_entry_price")),
                currency="USD",
                market_value=number(row.get("market_value")),
            )
            for row in items(await self._get("/v2/positions"))
        ]

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market not in {"us", "crypto"}:
            return Rules(
                tradable=False, note="Alpaca trades US shares and crypto only."
            )
        symbol = alpaca_symbol(instrument)
        try:
            asset = obj(await self._get(f"/v2/assets/{quote(symbol, safe='')}"))
        except ServiceError as error:
            if error.status == 404:
                return Rules(tradable=False, note=f"Alpaca doesn't list {symbol}.")
            raise
        tradable = bool(asset.get("tradable")) and text(asset.get("status")) == "active"
        if instrument.market == "crypto":
            return Rules(
                tradable=tradable,
                broker_symbol=symbol,
                min_qty=number(asset.get("min_order_size")),
                qty_step=number(asset.get("min_trade_increment")),
            )
        fractional = bool(asset.get("fractionable"))
        return Rules(
            tradable=tradable,
            broker_symbol=symbol,
            fractional=fractional,
            qty_step=0.0 if fractional else 1.0,
            note="" if tradable else f"Alpaca won't trade {symbol} right now.",
        )

    async def quote(self, instrument: Instrument) -> Quote | None:
        symbol = alpaca_symbol(instrument)
        try:
            if instrument.market == "crypto":
                body = obj(
                    await self._get(
                        "/v1beta3/crypto/us/latest/quotes",
                        {"symbols": symbol},
                        base=DATA_URL,
                    )
                )
                row = obj(obj(body.get("quotes")).get(symbol))
            else:
                body = obj(
                    await self._get(
                        f"/v2/stocks/{symbol}/quotes/latest",
                        {"feed": "iex"},
                        base=DATA_URL,
                    )
                )
                row = obj(body.get("quote"))
        except ServiceError:
            return None
        bid, ask = number(row.get("bp")), number(row.get("ap"))
        if bid <= 0 or ask <= 0:
            return None
        return Quote(instrument.symbol, (bid + ask) / 2, "USD", 0.0, "Alpaca", bid, ask)

    async def place(self, order: OrderRequest) -> OrderResult:
        crypto = order.instrument.market == "crypto"
        whole = float(order.qty).is_integer()
        body: dict[str, object] = {
            "symbol": alpaca_symbol(order.instrument),
            "qty": f"{order.qty:.9g}",
            "side": order.side,
            "type": order.order_type,
            "time_in_force": "gtc" if crypto else "day",
            "client_order_id": order.client_id,
        }
        if order.order_type == "limit" and order.limit_price is not None:
            body["limit_price"] = f"{order.limit_price:.6g}"
        bracket = (
            not crypto
            and whole
            and order.side == "buy"
            and order.stop_loss is not None
            and order.take_profit is not None
        )
        if bracket:
            body.update(
                {
                    "order_class": "bracket",
                    # Good till cancelled, so the stop and target outlast today.
                    "time_in_force": "gtc",
                    "take_profit": {"limit_price": f"{order.take_profit:.6g}"},
                    "stop_loss": {"stop_price": f"{order.stop_loss:.6g}"},
                }
            )
        response = await self._web.request(
            "POST",
            f"{self._base}/v2/orders",
            json=body,
            headers=self._headers,
            retry=False,
            what="Alpaca",
        )
        result = _order(obj(read_json(response, what="Alpaca")))
        return replace(result, raw={**result.raw, "bracket": bracket})

    async def find(self, client_id: str) -> OrderResult | None:
        try:
            body = await self._get(
                "/v2/orders:by_client_order_id", {"client_order_id": client_id}
            )
        except ServiceError as error:
            if error.status == 404:
                return None
            raise
        return _order(obj(body))

    async def cancel(self, broker_order_id: str) -> None:
        await self._web.request(
            "DELETE",
            f"{self._base}/v2/orders/{broker_order_id}",
            headers=self._headers,
            what="Alpaca",
        )

    async def open_orders(self) -> list[OrderResult]:
        return [
            _order(row)
            for row in items(
                await self._get("/v2/orders", {"status": "open", "limit": 100})
            )
        ]

    async def aclose(self) -> None:
        await self._web.aclose()


def _order(row: Mapping[str, object]) -> OrderResult:
    status = STATUSES.get(text(row.get("status")), "submitted")
    filled = number(row.get("filled_qty"))
    price = number(row.get("filled_avg_price"))
    return OrderResult(
        broker_order_id=text(row.get("id")),
        status=status,
        client_id=text(row.get("client_order_id")),
        symbol=fcc_symbol(text(row.get("symbol")), text(row.get("asset_class"))),
        filled_qty=filled,
        fill_price=price or None,
        raw={"status": text(row.get("status"))},
    )
