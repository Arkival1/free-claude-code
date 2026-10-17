"""The position manager: what FCC does with a holding between the buy and
the sell, by the plan the desk agreed to.

- It keeps the highest and lowest price seen since the buy (how far the
  trade went for and against it), from the prices FCC checks while the
  market is open (every few seconds; a move between checks can be missed).
- Once the price has gained as much as the plan risked (+1R: the entry
  minus the first stop), the stop moves up to the entry.
- With a trailing stop in the plan, the stop follows the highest price
  seen, that percentage below it.
- When the plan's holding period is over, the holding is sold (a time exit).
A stop only ever moves up, never down: nothing here loosens the plan. When
the platform holds the stop itself (a bracket), that stop stays where it is
and only the time exit and the record keeping apply.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

DAY_S = 86_400
STOP_STEP = 0.0025
"""A trailing stop moves in steps of at least this (0.25% of its level)."""


@dataclass(frozen=True, slots=True)
class Plan:
    """What the desk agreed to when it bought, kept with the position."""

    entry: float
    initial_stop: float | None
    trailing_pct: float | None
    holding_days: int | None
    opened_at: float
    """When the first part filled (seconds since 1970)."""

    @classmethod
    def read(cls, value: object) -> Plan | None:
        if not isinstance(value, Mapping):
            return None
        entry, opened = value.get("entry"), value.get("opened_at")
        if not isinstance(entry, int | float) or entry <= 0:
            return None
        if not isinstance(opened, int | float):
            return None
        stop = value.get("initial_stop")
        trailing = value.get("trailing_pct")
        days = value.get("holding_days")
        return cls(
            entry=float(entry),
            initial_stop=float(stop)
            if isinstance(stop, int | float) and 0 < stop < entry
            else None,
            trailing_pct=float(trailing)
            if isinstance(trailing, int | float) and 0 < trailing <= 50
            else None,
            holding_days=int(days)
            if isinstance(days, int | float)
            and not isinstance(days, bool)
            and days >= 1
            else None,
            opened_at=float(opened),
        )

    def view(self) -> JsonObject:
        return {
            "entry": self.entry,
            "initial_stop": self.initial_stop,
            "trailing_pct": self.trailing_pct,
            "holding_days": self.holding_days,
            "opened_at": self.opened_at,
        }


@dataclass(frozen=True, slots=True)
class Step:
    """What one look at the price changes."""

    stop: float | None
    high: float
    low: float
    exit: str
    """Why to sell now (the holding period is over), or ""."""
    notes: tuple[str, ...] = ()

    def excursions(self, entry: float) -> tuple[float, float]:
        """The worst move against (<= 0) and best move for (>= 0) the trade
        so far, in percent of the entry."""
        return (
            round(min(0.0, (self.low / entry - 1) * 100), 3),
            round(max(0.0, (self.high / entry - 1) * 100), 3),
        )


def manage(
    plan: Plan,
    *,
    price: float,
    stop: float | None,
    high: float,
    low: float,
    now: float,
    move_stop: bool = True,
) -> Step:
    high, low = max(high, price), min(low, price)
    new_stop = stop
    notes: list[str] = []
    if move_stop and plan.initial_stop is not None:
        risk = plan.entry - plan.initial_stop
        if high >= plan.entry + risk and (new_stop is None or new_stop < plan.entry):
            new_stop = plan.entry
            notes.append(
                f"up {(high / plan.entry - 1) * 100:.1f}% (as much as it risked): "
                f"stop moved up to the entry, {plan.entry:g}"
            )
    if move_stop and plan.trailing_pct is not None:
        trail = high * (1 - plan.trailing_pct / 100)
        if new_stop is None or trail > new_stop * (1 + STOP_STEP):
            new_stop = trail
            notes.append(
                f"trailing stop raised to {trail:.6g} ({plan.trailing_pct:g}% under "
                f"the high of {high:.6g})"
            )
    exit_reason = ""
    if plan.holding_days and now - plan.opened_at >= plan.holding_days * DAY_S:
        exit_reason = f"the plan's holding period ({plan.holding_days} days) is over"
    return Step(new_stop, high, low, exit_reason, tuple(notes))
