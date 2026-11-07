"""Keeping the desk's background work dependable, and showing how it runs.

- One desk at a time: a lease file in the desk's folder names the FCC that
  runs the loop and is renewed every pass. A second FCC on the same data
  (two copies open) finds a fresh lease and does nothing until it lapses,
  so the same order can't be placed twice from two places.
- A heartbeat: when the loop last finished a pass, so a stalled desk shows.
- Each step of the loop is timed, with its last error kept.
- Background jobs (debriefs) that fail are tried again after a growing wait,
  up to three times, then set aside for good and recorded (a dead letter):
  never retried forever, never dropped without a word.
- Measures taken from the desk's own records: how long a cycle takes, how
  long from the start of a cycle to its decision, how many orders fill or
  are refused, the slippage against the decision's price, and the fees.
"""

import json
import os
import statistics
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from free_claude_code.core.json_types import JsonObject

from .records import TradeDecision, TradeOrder, TradeRound

LEASE_SECONDS = 60.0
"""A lease not renewed for this long is free (its FCC stopped)."""
JOB_TRIES = 3
JOB_WAIT_SECONDS = 120.0
"""The wait before the first retry; it doubles each time."""


class Lease:
    """Who runs the desk's loop: this FCC, or another one."""

    def __init__(self, path: Path, holder: str, clock: Callable[[], float]) -> None:
        self._path = path
        self._holder = holder
        self._clock = clock

    def _read(self) -> dict[str, object]:
        try:
            found = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError, ValueError, OSError:
            return {}
        return found if isinstance(found, dict) else {}

    def take(self) -> str:
        """Take or renew the lease: "" when this FCC holds it, else when the
        other holder last renewed it."""
        now = self._clock()
        found = self._read()
        at = found.get("at")
        if (
            found.get("holder") not in {None, self._holder}
            and isinstance(at, int | float)
            and now - at < LEASE_SECONDS
        ):
            return f"another FCC renewed it {now - at:.0f} s ago"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"holder": self._holder, "at": now, "pid": os.getpid()}),
            encoding="utf-8",
        )
        os.replace(temporary, self._path)
        return ""

    def release(self) -> None:
        if self._read().get("holder") == self._holder:
            self._path.unlink(missing_ok=True)


@dataclass(slots=True)
class StepStat:
    runs: int = 0
    failures: int = 0
    last_ms: float = 0.0
    slowest_ms: float = 0.0
    last_error: str = ""
    last_error_at: float = 0.0

    def view(self) -> JsonObject:
        return {
            "runs": self.runs,
            "failures": self.failures,
            "last_ms": round(self.last_ms, 1),
            "slowest_ms": round(self.slowest_ms, 1),
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
        }


@dataclass(slots=True)
class Steps:
    """Each loop step's timing and last error."""

    stats: dict[str, StepStat] = field(default_factory=dict)

    def record(self, name: str, seconds: float, *, error: str = "", at: float) -> None:
        stat = self.stats.setdefault(name, StepStat())
        stat.runs += 1
        stat.last_ms = seconds * 1000
        stat.slowest_ms = max(stat.slowest_ms, stat.last_ms)
        if error:
            stat.failures += 1
            stat.last_error = error[:300]
            stat.last_error_at = at

    def view(self) -> JsonObject:
        return {name: stat.view() for name, stat in self.stats.items()}


@dataclass(slots=True)
class Job:
    """A background job (a debrief) and how often it has failed."""

    run: Callable[[], Awaitable[object]]
    name: str = "debrief"
    tries: int = 0
    due: float = 0.0
    errors: list[str] = field(default_factory=list)

    def failed(self, error: str, now: float) -> bool:
        """Note a failure; True when it may be tried again (and when)."""
        self.tries += 1
        self.errors.append(error[:300])
        if self.tries >= JOB_TRIES:
            return False
        self.due = now + JOB_WAIT_SECONDS * 2 ** (self.tries - 1)
        return True


def metrics(
    rounds: Sequence[TradeRound],
    orders: Sequence[TradeOrder],
    decisions: Sequence[TradeDecision],
) -> JsonObject:
    """How the desk has been doing, from its own records (none invented: a
    measure with nothing to measure is left out)."""
    found: JsonObject = {}
    cycles = [
        (item.updated_at - item.created_at) / 1000
        for item in rounds
        if item.status != "running" and item.updated_at > item.created_at
    ]
    if cycles:
        found["cycle_seconds_median"] = round(statistics.median(cycles), 1)
        found["cycle_seconds_slowest"] = round(max(cycles), 1)
    latencies: list[float] = []
    for decision in decisions:
        timing = decision.data.get("timing")
        if not isinstance(timing, dict):
            continue
        start, decided = timing.get("cycle_start"), timing.get("order_decision")
        if isinstance(start, int | float) and isinstance(decided, int | float):
            latencies.append(max(0.0, float(decided) - float(start)))
    if latencies:
        found["decision_seconds_median"] = round(statistics.median(latencies), 1)
    sent = [
        order
        for order in orders
        if order.status
        in {"submitted", "partially_filled", "filled", "rejected", "cancelled"}
    ]
    if sent:
        filled = [order for order in sent if order.filled_qty > 0]
        refused = [order for order in sent if order.status == "rejected"]
        found["orders_sent"] = len(sent)
        found["fill_rate_pct"] = round(len(filled) / len(sent) * 100, 1)
        found["reject_rate_pct"] = round(len(refused) / len(sent) * 100, 1)
        slips = [
            (order.fill_price / order.entry_price - 1) * 100
            if order.side == "buy"
            else (1 - order.fill_price / order.entry_price) * 100
            for order in filled
            if order.fill_price and order.entry_price
        ]
        if slips:
            found["slippage_pct_average"] = round(statistics.fmean(slips), 3)
            found["slippage_pct_worst"] = round(max(slips), 3)
        found["fees_total"] = round(sum(order.fees for order in filled), 2)
    return found
