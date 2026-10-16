"""The paper account: practice trading on real prices with pretend money.

Market orders fill at the live quote plus a little slippage, and pay a fee;
limit orders wait until the price reaches them (the desk's tick checks). Cash
is kept in the base currency (AUD by default) and each fill is converted at
the day's exchange rate, so the profit and loss read like a real Australian
account's. The ASX's minimum first parcel ($500) applies, and ASX shares
trade in whole units.
"""

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from ...models import now_ms
from ...store import StudioStore
from ..data import MarketData, MarketDataError, Quote
from ..instruments import Instrument, parse_symbol
from ..records import TradePosition
from .base import Account, Holding, OrderRequest, OrderResult, Rules, rejected

ASX_MIN_PARCEL = 500.0
SLIPPAGE_PCT = 0.05
MAX_KEPT_ORDERS = 500


class PaperBroker:
    id = "paper"
    name = "Paper account (practice)"
    live = False
    supports_brackets = False

    def __init__(
        self,
        store: StudioStore,
        path: Path,
        data: MarketData,
        *,
        currency: str = "AUD",
        starting_cash: float = 10_000.0,
        fee_pct: float = 0.1,
        min_fee: float = 1.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._path = path
        self._data = data
        self._currency = currency
        self._starting_cash = starting_cash
        self._fee_pct = fee_pct
        self._min_fee = min_fee
        self._clock = clock

    def markets(self) -> frozenset[str]:
        return frozenset({"us", "asx", "crypto"})

    # ------------------------------------------------------------ state

    def _read(self) -> dict[str, object]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError, ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("cash", self._starting_cash)
        data.setdefault("currency", self._currency)
        data.setdefault("orders", {})
        return data

    def _write(self, data: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(temporary, self._path)

    def reset(self, cash: float) -> None:
        """Start the practice account again with this much cash."""
        self._write({"cash": cash, "currency": self._currency, "orders": {}})

    async def clear_positions(self) -> None:
        await self._store.delete_where(TradePosition, {"broker": self.id})

    @property
    def cash(self) -> float:
        value = self._read().get("cash")
        return float(value) if isinstance(value, int | float) else self._starting_cash

    # ------------------------------------------------------------ account

    async def _holdings(self) -> list[TradePosition]:
        return list(await self._store.find(TradePosition, where={"broker": self.id}))

    async def account(self) -> Account:
        cash = self.cash
        value = 0.0
        for position in await self._holdings():
            value += await self._value(position)
        equity = cash + value
        return Account(
            number="PAPER",
            fingerprint="paper",
            currency=self._currency,
            equity=equity,
            cash=cash,
            buying_power=cash,
            live=False,
            note="Practice money on real prices.",
        )

    async def _value(self, position: TradePosition) -> float:
        """A holding's value in the base currency (its cost if no price)."""
        try:
            instrument = parse_symbol(position.symbol)
            quote = await self._data.quote(instrument)
            rate = await self._data.fx(quote.currency, self._currency)
        except MarketDataError, ValueError:
            return position.cost_base
        return position.qty * quote.price * rate

    async def positions(self) -> list[Holding]:
        return [
            Holding(
                symbol=position.symbol,
                qty=position.qty,
                avg_price=position.avg_price,
                currency=position.currency,
            )
            for position in await self._holdings()
        ]

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market == "asx":
            return Rules(
                tradable=True,
                broker_symbol=instrument.symbol,
                qty_step=1.0,
                fractional=False,
                min_value=ASX_MIN_PARCEL,
                note="ASX shares trade in whole units; a new holding needs $500.",
            )
        if instrument.market in {"us", "crypto"}:
            return Rules(tradable=True, broker_symbol=instrument.symbol)
        return Rules(
            tradable=False,
            note="DEX tokens can't be traded: that needs a wallet key FCC never holds.",
        )

    async def quote(self, instrument: Instrument) -> Quote | None:
        try:
            return await self._data.quote(instrument)
        except MarketDataError:
            return None

    # ------------------------------------------------------------ orders

    async def place(self, order: OrderRequest) -> OrderResult:
        state = self._read()
        orders = _orders(state)
        if order.client_id in orders:
            return _result(orders[order.client_id])
        rules = await self.rules(order.instrument)
        if not rules.tradable:
            raise rejected(rules.note or f"{order.instrument.symbol} can't be traded.")
        quote = await self.quote(order.instrument)
        if quote is None:
            raise rejected(f"No live price for {order.instrument.symbol}, so no fill.")
        held = await self._store.get(
            TradePosition, f"{self.id}:{order.instrument.symbol}"
        )
        if order.side == "sell" and (held is None or held.qty + 1e-12 < order.qty):
            raise rejected(
                f"The paper account holds {held.qty if held else 0:g} "
                f"{order.instrument.symbol}, less than {order.qty:g}."
            )
        entry: dict[str, object] = {
            "client_id": order.client_id,
            "broker_order_id": f"paper-{order.client_id}",
            "symbol": order.instrument.symbol,
            "side": order.side,
            "qty": order.qty,
            "order_type": order.order_type,
            "limit_price": order.limit_price,
            "status": "submitted",
            "filled_qty": 0.0,
            "fill_price": None,
            "fees": 0.0,
            "at": self._clock(),
        }
        if order.order_type == "limit" and not _limit_reached(order, quote.price):
            orders[order.client_id] = entry
            self._save_orders(state, orders)
            return _result(entry)
        filled = await self._fill(order, quote, entry, held)
        state = self._read()
        orders = _orders(state)
        orders[order.client_id] = filled
        self._save_orders(state, orders)
        return _result(filled)

    async def _fill(
        self,
        order: OrderRequest,
        quote: Quote,
        entry: dict[str, object],
        held: TradePosition | None,
    ) -> dict[str, object]:
        slip = SLIPPAGE_PCT / 100
        price = quote.price * (1 + slip if order.side == "buy" else 1 - slip)
        if order.order_type == "limit" and order.limit_price is not None:
            price = (
                min(price, order.limit_price)
                if order.side == "buy"
                else max(price, order.limit_price)
            )
        rate = await self._data.fx(quote.currency, self._currency)
        value = order.qty * price * rate
        fees = max(self._min_fee, value * self._fee_pct / 100)
        state = self._read()
        cash = _float(state.get("cash"))
        if order.side == "buy":
            if (
                order.instrument.market == "asx"
                and held is None
                and value < ASX_MIN_PARCEL
            ):
                raise rejected(
                    f"A first ASX parcel must be worth ${ASX_MIN_PARCEL:.0f}; "
                    f"this one is ${value:,.2f}."
                )
            if value + fees > cash + 1e-6:
                raise rejected(
                    f"Not enough paper cash: ${cash:,.2f} for ${value + fees:,.2f}."
                )
            cash -= value + fees
            await self._add(order, price, quote.currency, value + fees, held)
        else:
            cash += value - fees
            await self._remove(order, held)
        state["cash"] = round(cash, 6)
        self._write(state)
        return {
            **entry,
            "status": "filled",
            "filled_qty": order.qty,
            "fill_price": price,
            "fees": round(fees, 6),
            "fx_rate": rate,
        }

    async def _add(
        self,
        order: OrderRequest,
        price: float,
        currency: str,
        cost: float,
        held: TradePosition | None,
    ) -> None:
        symbol = order.instrument.symbol
        if held is None:
            await self._store.put(
                TradePosition(
                    id=f"{self.id}:{symbol}",
                    broker=self.id,
                    symbol=symbol,
                    market=order.instrument.market,
                    qty=order.qty,
                    avg_price=price,
                    currency=currency,
                    cost_base=cost,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                )
            )
            return
        qty = held.qty + order.qty
        await self._store.put(
            held.model_copy(
                update={
                    "qty": qty,
                    "avg_price": (held.avg_price * held.qty + price * order.qty) / qty,
                    "cost_base": held.cost_base + cost,
                    "stop_loss": order.stop_loss or held.stop_loss,
                    "take_profit": order.take_profit or held.take_profit,
                    "updated_at": now_ms(),
                }
            )
        )

    async def _remove(self, order: OrderRequest, held: TradePosition | None) -> None:
        if held is None:
            return
        left = held.qty - order.qty
        if left <= 1e-12:
            await self._store.delete(TradePosition, held.id)
            return
        share = left / held.qty
        await self._store.put(
            held.model_copy(
                update={
                    "qty": left,
                    "cost_base": held.cost_base * share,
                    "updated_at": now_ms(),
                }
            )
        )

    def _save_orders(
        self, state: dict[str, object], orders: dict[str, dict[str, object]]
    ) -> None:
        if len(orders) > MAX_KEPT_ORDERS:
            for key in sorted(orders, key=lambda k: float(_at(orders[k])))[
                : len(orders) - MAX_KEPT_ORDERS
            ]:
                orders.pop(key, None)
        state["orders"] = orders
        self._write(state)

    async def tick(self) -> list[OrderResult]:
        """Fill waiting limit orders whose price has been reached."""
        state = self._read()
        filled: list[OrderResult] = []
        for client_id, entry in list(_orders(state).items()):
            if entry.get("status") != "submitted":
                continue
            try:
                instrument = parse_symbol(str(entry.get("symbol") or ""))
            except ValueError:
                continue
            quote = await self.quote(instrument)
            limit = entry.get("limit_price")
            order = OrderRequest(
                client_id=client_id,
                instrument=instrument,
                side="sell" if entry.get("side") == "sell" else "buy",
                qty=_float(entry.get("qty")),
                order_type="limit",
                limit_price=float(limit) if isinstance(limit, int | float) else None,
            )
            if quote is None or not _limit_reached(order, quote.price):
                continue
            held = await self._store.get(
                TradePosition, f"{self.id}:{instrument.symbol}"
            )
            try:
                done = await self._fill(order, quote, entry, held)
            except Exception as error:
                done = {**entry, "status": "rejected", "note": str(error)}
            state = self._read()
            orders = _orders(state)
            orders[client_id] = done
            self._save_orders(state, orders)
            filled.append(_result(done))
        return filled

    async def find(self, client_id: str) -> OrderResult | None:
        entry = _orders(self._read()).get(client_id)
        return _result(entry) if entry is not None else None

    async def cancel(self, broker_order_id: str) -> None:
        state = self._read()
        orders = _orders(state)
        for entry in orders.values():
            if (
                entry.get("broker_order_id") == broker_order_id
                and entry.get("status") == "submitted"
            ):
                entry["status"] = "cancelled"
        self._save_orders(state, orders)

    async def open_orders(self) -> list[OrderResult]:
        return [
            _result(entry)
            for entry in _orders(self._read()).values()
            if entry.get("status") == "submitted"
        ]

    async def aclose(self) -> None:
        return None


def _float(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _orders(state: dict[str, object]) -> dict[str, dict[str, object]]:
    found = state.get("orders")
    if not isinstance(found, dict):
        return {}
    return {
        str(key): dict(value) for key, value in found.items() if isinstance(value, dict)
    }


def _at(entry: dict[str, object]) -> float:
    value = entry.get("at")
    return float(value) if isinstance(value, int | float) else 0.0


def _limit_reached(order: OrderRequest, price: float) -> bool:
    if order.limit_price is None:
        return True
    return (
        price <= order.limit_price
        if order.side == "buy"
        else price >= order.limit_price
    )


def _result(entry: dict[str, object]) -> OrderResult:
    price = entry.get("fill_price")
    return OrderResult(
        broker_order_id=str(entry.get("broker_order_id") or ""),
        status=str(entry.get("status") or "submitted"),
        client_id=str(entry.get("client_id") or ""),
        symbol=str(entry.get("symbol") or ""),
        filled_qty=_float(entry.get("filled_qty")),
        fill_price=float(price) if isinstance(price, int | float) else None,
        fees=_float(entry.get("fees")),
        note=str(entry.get("note") or ""),
        raw={
            key: value
            for key, value in entry.items()
            if isinstance(value, str | int | float | bool) or value is None
        },
    )
