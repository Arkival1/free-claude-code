"""Protection: the circuit breaker and the kill switch's latch.

The circuit breaker pauses new trades when something has gone wrong, while
positions are still managed (stops, targets, and exits keep working):
- the account is down more than the owner's daily loss limit today;
- the last few closed trades all lost money;
- a fill slipped far further than the slippage limit allows;
- the desk keeps hitting errors (several in a short time);
- the data keeps failing its checks (several candidates in a row);
- FCC's records and an account's couldn't be matched up.
It records the reason and the time, and lets trading resume by itself only
after the cool-down and once the cause has cleared; the owner can also
reset it from the PC. The owner's limits are read, never changed.

The kill switch stops everything new at once and latches: the desk can't
be started again until the owner releases it on purpose (from the PC).
Closing every position as well needs a second, typed confirmation.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from .config import BreakerLimits

FLATTEN_PHRASE = "CLOSE EVERYTHING"
"""Typed to close every position with the kill switch (the second step)."""


@dataclass(frozen=True, slots=True)
class Trip:
    kind: str
    reason: str
    at: float
    until: float

    def view(self) -> JsonObject:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "at": self.at,
            "until": self.until,
        }

    @classmethod
    def read(cls, value: object) -> Trip | None:
        if not isinstance(value, Mapping):
            return None
        at, until = value.get("at"), value.get("until")
        if not isinstance(at, int | float) or not isinstance(until, int | float):
            return None
        return cls(
            str(value.get("kind") or ""), str(value.get("reason") or ""), at, until
        )


@dataclass(frozen=True, slots=True)
class Health:
    """What the breaker looks at, gathered by the desk each tick."""

    day_change_pct: float | None
    max_daily_loss_pct: float
    recent_results: Sequence[float]
    """Profit or loss of the latest closed trades, newest first."""
    last_slippage_pct: float | None
    slippage_limit_pct: float
    errors_recent: int
    stale_streak: int
    reconcile_failed: str = ""


def check(health: Health, limits: BreakerLimits) -> tuple[str, str] | None:
    """(kind, reason) when the breaker should trip, else None."""
    if (
        health.day_change_pct is not None
        and health.day_change_pct <= -health.max_daily_loss_pct
    ):
        return (
            "daily_loss",
            f"the account is down {-health.day_change_pct:.1f}% today (limit "
            f"{health.max_daily_loss_pct:g}%)",
        )
    losses = limits.consecutive_losses
    latest = list(health.recent_results)[:losses]
    if len(latest) >= losses and all(result < 0 for result in latest):
        return ("losing_streak", f"the last {losses} closed trades all lost money")
    spike = health.slippage_limit_pct * limits.slippage_spike_times
    if health.last_slippage_pct is not None and health.last_slippage_pct > spike:
        return (
            "slippage",
            f"the last fill slipped {health.last_slippage_pct:.2f}% from the "
            f"decision's price (over {spike:g}%)",
        )
    if health.errors_recent >= limits.errors:
        return (
            "errors",
            f"{health.errors_recent} errors in the last {limits.errors_minutes} min",
        )
    if health.stale_streak >= limits.stale_rounds:
        return (
            "stale_data",
            f"the data failed its checks for {health.stale_streak} candidates in a row",
        )
    if health.reconcile_failed:
        return ("reconciliation", health.reconcile_failed)
    return None


def trip(found: tuple[str, str], *, now: float, limits: BreakerLimits) -> Trip:
    kind, reason = found
    return Trip(kind, reason, now, now + limits.cooldown_minutes * 60)


def may_clear(current: Trip, health: Health, limits: BreakerLimits, now: float) -> bool:
    """The cool-down is over and the cause is gone."""
    return now >= current.until and check(health, limits) is None
