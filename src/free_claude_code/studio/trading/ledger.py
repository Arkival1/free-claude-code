"""The trade ledger: profit and loss in the base currency, and the tax file.

Fills are matched first-in, first-out, the way the ATO expects when lots
aren't identified. Each sale becomes a capital gains row in Australian
dollars (cost base and proceeds after fees) and says whether the asset was
held more than 12 months, which matters for the 50% CGT discount. It is a
record to hand an accountant, not tax advice.
"""

import csv
import io
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from free_claude_code.core.json_types import JsonObject

from .records import TradeOrder

DAY_MS = 86_400_000


@dataclass(slots=True)
class _Lot:
    qty: float
    cost: float
    """Base currency, fees included, for the whole lot."""
    at: int


@dataclass(frozen=True, slots=True)
class Disposal:
    symbol: str
    qty: float
    acquired_at: int
    disposed_at: int
    cost_base: float
    proceeds: float

    @property
    def gain(self) -> float:
        return self.proceeds - self.cost_base

    @property
    def held_days(self) -> float:
        return (self.disposed_at - self.acquired_at) / DAY_MS

    @property
    def discount_eligible(self) -> bool:
        return self.held_days > 365 and self.gain > 0


@dataclass(slots=True)
class Ledger:
    disposals: list[Disposal] = field(default_factory=list)
    open_lots: dict[str, list[_Lot]] = field(default_factory=dict)

    @property
    def realised(self) -> float:
        return sum(item.gain for item in self.disposals)

    def realised_since(self, since_ms: int) -> float:
        return sum(item.gain for item in self.disposals if item.disposed_at >= since_ms)

    def by_symbol(self) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for item in self.disposals:
            totals[item.symbol] += item.gain
        return dict(totals)

    def view(self) -> JsonObject:
        wins = [item for item in self.disposals if item.gain > 0]
        return {
            "realised": round(self.realised, 2),
            "closed_trades": len(self.disposals),
            "win_rate": round(len(wins) / len(self.disposals), 3)
            if self.disposals
            else None,
            "by_symbol": {
                key: round(value, 2) for key, value in self.by_symbol().items()
            },
        }


def build_ledger(orders: Iterable[TradeOrder]) -> Ledger:
    """Match every filled order first-in, first-out."""
    ledger = Ledger()
    lots: dict[str, deque[_Lot]] = defaultdict(deque)
    fills = sorted(
        (order for order in orders if order.filled_qty > 0 and order.fill_price),
        key=lambda order: order.updated_at,
    )
    for order in fills:
        price = order.fill_price or 0.0
        value = order.filled_qty * price * order.fx_rate
        if order.side == "buy":
            lots[order.symbol].append(
                _Lot(order.filled_qty, value + order.fees, order.updated_at)
            )
            continue
        left = order.filled_qty
        proceeds_per_unit = (value - order.fees) / order.filled_qty
        queue = lots[order.symbol]
        while left > 1e-12 and queue:
            lot = queue[0]
            take = min(left, lot.qty)
            share = take / lot.qty
            cost = lot.cost * share
            ledger.disposals.append(
                Disposal(
                    symbol=order.symbol,
                    qty=take,
                    acquired_at=lot.at,
                    disposed_at=order.updated_at,
                    cost_base=cost,
                    proceeds=proceeds_per_unit * take,
                )
            )
            lot.qty -= take
            lot.cost -= cost
            left -= take
            if lot.qty <= 1e-12:
                queue.popleft()
    ledger.open_lots = {symbol: list(queue) for symbol, queue in lots.items() if queue}
    return ledger


def tax_csv(ledger: Ledger, *, currency: str = "AUD") -> str:
    """A CSV of every disposal for an accountant (capital gains records)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "Asset",
            "Quantity",
            "Acquired (UTC)",
            "Disposed (UTC)",
            "Days held",
            f"Cost base ({currency}, incl. fees)",
            f"Proceeds ({currency}, after fees)",
            f"Gain or loss ({currency})",
            "Held over 12 months",
        ]
    )
    for item in ledger.disposals:
        writer.writerow(
            [
                item.symbol,
                f"{item.qty:.8g}",
                _day(item.acquired_at),
                _day(item.disposed_at),
                f"{item.held_days:.0f}",
                f"{item.cost_base:.2f}",
                f"{item.proceeds:.2f}",
                f"{item.gain:.2f}",
                "yes" if item.held_days > 365 else "no",
            ]
        )
    return out.getvalue()


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")
