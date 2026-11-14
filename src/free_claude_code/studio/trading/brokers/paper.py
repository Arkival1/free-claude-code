"""The paper account: practice trading on real prices with pretend money.

Orders fill the way the real market would let them (see ``fills``): a buy
pays the live ask and a sell gets the bid (an assumed spread, labelled,
when no live book is known), plus slippage that grows with the order's
size; a thin market fills an order bit by bit over the following minutes;
a limit order waits until the ask or bid reaches it and expires after a
day. Each fill pays a fee. Cash is kept in the base currency (AUD by
default) and each fill is converted at the day's exchange rate, so the
profit and loss read like a real Australian account's. The ASX's minimum
first parcel ($500) applies, and ASX shares trade in whole units.
"""

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from ...models import now_ms
from ...resilience import ServiceError
from ...store import StudioStore
from ..config import DataQualityLimits
from ..data import MarketData, MarketDataError, Quote
from ..fills import LIMIT_HOURS, Conditions, conditions, next_slice
from ..information import QuoteSnapshot
from ..instruments import Instrument, parse_symbol
from ..quality import bid_ask_source, profile_of
from ..records import TradePosition
from ..sessions import session
from .base import Account, Holding, OrderRequest, OrderResult, Rules, rejected

_LOCKS: dict[str, asyncio.Lock] = {}
"""One writer at a time per practice account file (the loop's fills and an
order placed at the same moment would otherwise lose one's update)."""

ASX_MIN_PARCEL = 500.0
MAX_KEPT_ORDERS = 500
WORKING = frozenset({"submitted", "partially_filled"})
"""Orders still filling (the rest of a partial fill, or a waiting limit)."""


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
        limits: DataQualityLimits | None = None,
        coin_book: Callable[[str], Awaitable[QuoteSnapshot]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._path = path
        self._data = data
        self._currency = currency
        self._starting_cash = starting_cash
        self._fee_pct = fee_pct
        self._min_fee = min_fee
        self._limits = limits or DataQualityLimits()
        self._coin_book = coin_book
        """When set, coins fill on this book (Hyperliquid's, for Invo)."""
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

    def _lock(self) -> asyncio.Lock:
        return _LOCKS.setdefault(str(self._path.resolve()), asyncio.Lock())

    async def place(self, order: OrderRequest) -> OrderResult:
        async with self._lock():
            return await self._place(order)

    async def _place(self, order: OrderRequest) -> OrderResult:
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
        now = self._clock()
        entry: dict[str, object] = {
            "client_id": order.client_id,
            "broker_order_id": f"paper-{order.client_id}",
            "symbol": order.instrument.symbol,
            "side": order.side,
            "qty": order.qty,
            "order_type": order.order_type,
            "limit_price": order.limit_price,
            "stop_loss": order.stop_loss,
            "take_profit": order.take_profit,
            "status": "submitted",
            "filled_qty": 0.0,
            "fill_price": None,
            "fees": 0.0,
            "value": 0.0,
            "at": now,
            # The first part may take one minute's share of the market.
            "last_fill_at": now - 60,
            "expires_at": now + LIMIT_HOURS * 3600,
        }
        filled = await self._fill(order, quote, entry, held, first=True)
        state = self._read()
        orders = _orders(state)
        orders[order.client_id] = filled
        self._save_orders(state, orders)
        return _result(filled)

    async def _conditions(self, instrument: Instrument, quote: Quote) -> Conditions:
        """The live book (the quote's own, else a fresh coin exchange's in
        the same currency) and the daily candles for size and volatility."""
        bid, ask, book = quote.bid, quote.ask, quote.source
        if quote.spread_pct is None:
            bid = ask = None
            book = ""
            if instrument.market == "crypto":
                snapshots = [
                    snap
                    for snap in await self._data.snapshots(instrument)
                    if snap.currency == quote.currency
                ]
                if self._coin_book is not None:
                    # Practice on the account's own market: only its book.
                    try:
                        snapshots = [await self._coin_book(instrument.symbol)]
                    except ServiceError:
                        snapshots = []
                found = bid_ask_source(
                    snapshots,
                    None,
                    now=self._clock(),
                    limits=self._limits,
                    profile=profile_of(instrument),
                )
                if found is not None:
                    bid, ask, book = found.bid, found.ask, found.provider
        bars = []
        try:
            bars = await self._data.bars(instrument, "1d")
        except MarketDataError:
            bars = []
        return conditions(
            quote.price, bars, market=instrument.market, bid=bid, ask=ask, book=book
        )

    async def _fill(
        self,
        order: OrderRequest,
        quote: Quote,
        entry: dict[str, object],
        held: TradePosition | None,
        *,
        first: bool = False,
    ) -> dict[str, object]:
        """Fill what the market allows now; the rest waits for later ticks.
        A first part that can't be paid for is refused; a later one ends
        the order with what has filled so far."""
        before = _float(entry.get("filled_qty"))
        remaining = order.qty - before
        if order.side == "sell":
            remaining = min(remaining, held.qty if held is not None else 0.0)
        if remaining <= 1e-12:
            return {**entry, "status": "filled" if before else "cancelled"}
        now = self._clock()
        rules = await self.rules(order.instrument)
        piece = next_slice(
            side=order.side,
            remaining=remaining,
            seen=await self._conditions(order.instrument, quote),
            profile=profile_of(order.instrument),
            market=order.instrument.market,
            minutes=(now - _float(entry.get("last_fill_at"), now - 60)) / 60,
            limit=order.limit_price if order.order_type == "limit" else None,
            step=rules.qty_step
            if rules.qty_step > 0
            else (0.0 if rules.fractional else 1.0),
        )
        if piece.qty <= 0:
            return {**entry, "basis": piece.basis}
        rate = await self._data.fx(quote.currency, self._currency)
        value = piece.qty * piece.price * rate
        # One fee for the whole order (the minimum applies once), charged as
        # it fills.
        value_total = _float(entry.get("value")) + value
        fees_total = max(self._min_fee, value_total * self._fee_pct / 100)
        fees = max(0.0, fees_total - _float(entry.get("fees")))
        state = self._read()
        cash = _float(state.get("cash"))
        problem = ""
        if order.side == "buy":
            whole = order.qty * piece.price * rate
            if (
                order.instrument.market == "asx"
                and held is None
                and before == 0
                and whole < ASX_MIN_PARCEL
            ):
                problem = (
                    f"A first ASX parcel must be worth ${ASX_MIN_PARCEL:.0f}; "
                    f"this one is ${whole:,.2f}."
                )
            elif value + fees > cash + 1e-6:
                problem = (
                    f"Not enough paper cash: ${cash:,.2f} for ${value + fees:,.2f}."
                )
        if problem:
            if first:
                raise rejected(problem)
            return {
                **entry,
                "status": "cancelled" if before else "rejected",
                "note": problem,
            }
        if order.side == "buy":
            cash -= value + fees
            await self._add(order, piece.qty, piece.price, quote.currency, value + fees)
        else:
            cash += value - fees
            await self._remove(piece.qty, held)
        state["cash"] = round(cash, 6)
        self._write(state)
        total = before + piece.qty
        price_before = _float(entry.get("fill_price"))
        return {
            **entry,
            "status": "filled" if total >= order.qty - 1e-12 else "partially_filled",
            "filled_qty": total,
            "fill_price": (before * price_before + piece.qty * piece.price) / total,
            "fees": round(_float(entry.get("fees")) + fees, 6),
            "value": round(value_total, 6),
            "fx_rate": rate,
            "last_fill_at": now,
            "basis": piece.basis,
            "slippage_pct": round(piece.slippage_pct, 4),
        }

    async def _add(
        self,
        order: OrderRequest,
        qty: float,
        price: float,
        currency: str,
        cost: float,
    ) -> None:
        symbol = order.instrument.symbol
        held = await self._store.get(TradePosition, f"{self.id}:{symbol}")
        if held is None:
            await self._store.put(
                TradePosition(
                    id=f"{self.id}:{symbol}",
                    broker=self.id,
                    symbol=symbol,
                    market=order.instrument.market,
                    qty=qty,
                    avg_price=price,
                    currency=currency,
                    cost_base=cost,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                )
            )
            return
        total = held.qty + qty
        await self._store.put(
            held.model_copy(
                update={
                    "qty": total,
                    "avg_price": (held.avg_price * held.qty + price * qty) / total,
                    "cost_base": held.cost_base + cost,
                    "stop_loss": order.stop_loss or held.stop_loss,
                    "take_profit": order.take_profit or held.take_profit,
                    "updated_at": now_ms(),
                }
            )
        )

    async def _remove(self, qty: float, held: TradePosition | None) -> None:
        if held is None:
            return
        held = await self._store.get(TradePosition, held.id) or held
        left = held.qty - qty
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

    def _open(self, instrument: Instrument) -> bool:
        return session(
            instrument.market, datetime.fromtimestamp(self._clock(), tz=UTC)
        ).open

    async def tick(self) -> list[OrderResult]:
        """Carry on with orders still filling: the rest of a partial fill as
        the market allows, a limit once its price is reached, and expiry."""
        async with self._lock():
            return await self._tick()

    async def _tick(self) -> list[OrderResult]:
        state = self._read()
        changed: list[OrderResult] = []
        now = self._clock()
        for client_id, entry in list(_orders(state).items()):
            if entry.get("status") not in WORKING:
                continue
            try:
                instrument = parse_symbol(str(entry.get("symbol") or ""))
            except ValueError:
                continue
            if now >= _float(entry.get("expires_at"), float("inf")):
                done = {**entry, "status": "cancelled", "note": "Expired unfilled."}
            else:
                if not self._open(instrument):
                    continue
                quote = await self.quote(instrument)
                if quote is None:
                    continue
                limit = entry.get("limit_price")
                stop = entry.get("stop_loss")
                target = entry.get("take_profit")
                order = OrderRequest(
                    client_id=client_id,
                    instrument=instrument,
                    side="sell" if entry.get("side") == "sell" else "buy",
                    qty=_float(entry.get("qty")),
                    order_type="limit"
                    if entry.get("order_type") == "limit"
                    else "market",
                    limit_price=float(limit)
                    if isinstance(limit, int | float)
                    else None,
                    stop_loss=float(stop) if isinstance(stop, int | float) else None,
                    take_profit=float(target)
                    if isinstance(target, int | float)
                    else None,
                )
                held = await self._store.get(
                    TradePosition, f"{self.id}:{instrument.symbol}"
                )
                try:
                    done = await self._fill(order, quote, entry, held)
                except Exception as error:
                    done = {
                        **entry,
                        "status": "cancelled"
                        if _float(entry.get("filled_qty"))
                        else "rejected",
                        "note": str(error),
                    }
            if done.get("status") == entry.get("status") and _float(
                done.get("filled_qty")
            ) == _float(entry.get("filled_qty")):
                continue
            state = self._read()
            orders = _orders(state)
            orders[client_id] = done
            self._save_orders(state, orders)
            changed.append(_result(done))
        return changed

    async def find(self, client_id: str) -> OrderResult | None:
        entry = _orders(self._read()).get(client_id)
        return _result(entry) if entry is not None else None

    async def cancel(self, broker_order_id: str) -> None:
        async with self._lock():
            self._cancel(broker_order_id)

    def _cancel(self, broker_order_id: str) -> None:
        state = self._read()
        orders = _orders(state)
        for entry in orders.values():
            if (
                entry.get("broker_order_id") == broker_order_id
                and entry.get("status") in WORKING
            ):
                entry["status"] = "cancelled"
        self._save_orders(state, orders)

    async def open_orders(self) -> list[OrderResult]:
        return [
            _result(entry)
            for entry in _orders(self._read()).values()
            if entry.get("status") in WORKING
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
