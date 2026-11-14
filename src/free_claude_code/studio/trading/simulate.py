"""Simulations from past price behaviour: not predictions.

Price paths are rebuilt from the asset's own past days, only from candles
that started before now. Whole days are drawn in blocks of five in a row
(block bootstrap), so calm and wild stretches stay as they were. Each day
keeps its open gap, high, low, and close relative to the day before, so a
stop can be jumped over at the open (a stop doesn't guarantee its price).

Each path runs the actual plan: entry, stop, target, an optional trailing
stop, and a time exit, with the round-trip costs taken off. The result says
how often, in that history, the stop or the target came first, the typical
and the worst outcomes, and the worst dip along the way. The random draws
come from a recorded seed, so the same inputs always give the same numbers.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from free_claude_code.core.json_types import JsonObject

from .indicators import Bar

PATHS = 2000
BLOCK_DAYS = 5
MIN_DAYS = 60
MAX_HISTORY_DAYS = 750
MAX_HOLDING_DAYS = 60


@dataclass(frozen=True, slots=True)
class Plan:
    entry: float
    stop: float
    target: float
    holding_days: int
    side: Literal["long", "short"] = "long"
    trailing_pct: float | None = None
    """A trailing stop this far (in %) behind the best price since entry."""
    cost_pct: float = 0.0
    """Round-trip costs in % of the position: fees, spread, slippage."""
    label: str = "the plan"


@dataclass(frozen=True, slots=True)
class Day:
    """One past day, relative to the close before it (log changes)."""

    gap: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class SimResult:
    label: str
    paths: int
    seed: int
    horizon_days: int
    history_days: int
    p_stop_first: float
    p_target_first: float
    p_time_exit: float
    mean_pct: float
    median_pct: float
    worst_5pct: float
    """The 5th-percentile result: 1 path in 20 did this badly or worse."""
    tail_mean_pct: float
    """The average of that worst 5%."""
    dip_median_pct: float
    """The typical worst dip below the entry along the way."""
    dip_95pct: float
    """1 path in 20 dipped this far or further."""
    gapped_stops: float
    """Share of stop exits that filled beyond the stop (gapped through)."""

    def lines(self) -> str:
        return (
            f"Simulation of {self.label} from past price behaviour, not a "
            f"prediction ({self.paths:,} paths over {self.horizon_days} days, "
            f"built from {self.history_days} past days in {BLOCK_DAYS}-day "
            f"blocks; seed {self.seed}): stop first {self.p_stop_first:.0%}, "
            f"target first {self.p_target_first:.0%}, time ran out "
            f"{self.p_time_exit:.0%}; median result {self.median_pct:+.2f}%, "
            f"average {self.mean_pct:+.2f}%; worst 1 in 20: "
            f"{self.worst_5pct:+.2f}% or worse (those average "
            f"{self.tail_mean_pct:+.2f}%); typical worst dip "
            f"{self.dip_median_pct:+.2f}% (1 in 20: {self.dip_95pct:+.2f}%); "
            f"stops that gapped past their price {self.gapped_stops:.0%}."
        )

    def view(self) -> JsonObject:
        return {
            "label": self.label,
            "paths": self.paths,
            "seed": self.seed,
            "horizon_days": self.horizon_days,
            "history_days": self.history_days,
            "p_stop_first": round(self.p_stop_first, 4),
            "p_target_first": round(self.p_target_first, 4),
            "p_time_exit": round(self.p_time_exit, 4),
            "mean_pct": round(self.mean_pct, 3),
            "median_pct": round(self.median_pct, 3),
            "worst_5pct": round(self.worst_5pct, 3),
            "tail_mean_pct": round(self.tail_mean_pct, 3),
            "dip_median_pct": round(self.dip_median_pct, 3),
            "dip_95pct": round(self.dip_95pct, 3),
            "gapped_stops": round(self.gapped_stops, 4),
        }


def past_days(daily: Sequence[Bar], *, now: float) -> list[Day]:
    """Each past day relative to the close before it, using only candles that
    started before ``now`` (never anything later)."""
    bars = sorted((bar for bar in daily if bar.t < now), key=lambda bar: bar.t)
    bars = bars[-(MAX_HISTORY_DAYS + 1) :]
    days: list[Day] = []
    for before, bar in pairwise(bars):
        if before.c <= 0 or min(bar.o, bar.h, bar.l, bar.c) <= 0:
            continue
        base = before.c
        days.append(
            Day(
                gap=math.log(bar.o / base),
                high=math.log(max(bar.h, bar.o, bar.c) / base),
                low=math.log(min(bar.l, bar.o, bar.c) / base),
                close=math.log(bar.c / base),
            )
        )
    return days


def simulate(
    plan: Plan,
    daily: Sequence[Bar],
    *,
    now: float,
    seed: int,
    paths: int = PATHS,
) -> SimResult | None:
    """Run the plan over paths rebuilt from the past; None when there are
    fewer than ``MIN_DAYS`` usable past days (too little to say anything)."""
    days = past_days(daily, now=now)
    if len(days) < MIN_DAYS or plan.entry <= 0 or paths <= 0:
        return None
    long = plan.side == "long"
    if long and not (plan.stop < plan.entry < plan.target):
        return None
    if not long and not (plan.target < plan.entry < plan.stop):
        return None
    horizon = max(1, min(int(plan.holding_days), MAX_HOLDING_DAYS))
    draw = random.Random(seed)
    starts = len(days) - BLOCK_DAYS + 1
    results: list[float] = []
    dips: list[float] = []
    stops = targets = gapped = 0
    for _ in range(paths):
        path: list[Day] = []
        while len(path) < horizon:
            first = draw.randrange(starts)
            path.extend(days[first : first + BLOCK_DAYS])
        exit_price, how, worst, jumped = _walk(plan, path[:horizon], long=long)
        if how == "stop":
            stops += 1
            gapped += jumped
        elif how == "target":
            targets += 1
        change = exit_price / plan.entry - 1 if long else 1 - exit_price / plan.entry
        results.append(change * 100 - plan.cost_pct)
        dips.append(worst)
    results.sort()
    dips.sort()
    tail = results[: max(1, paths // 20)]
    return SimResult(
        label=plan.label,
        paths=paths,
        seed=seed,
        horizon_days=horizon,
        history_days=len(days),
        p_stop_first=stops / paths,
        p_target_first=targets / paths,
        p_time_exit=(paths - stops - targets) / paths,
        mean_pct=sum(results) / paths,
        median_pct=_percentile(results, 0.5),
        worst_5pct=_percentile(results, 0.05),
        tail_mean_pct=sum(tail) / len(tail),
        dip_median_pct=_percentile(dips, 0.5),
        dip_95pct=_percentile(dips, 0.05),
        gapped_stops=gapped / stops if stops else 0.0,
    )


def _walk(
    plan: Plan, path: Sequence[Day], *, long: bool
) -> tuple[float, str, float, bool]:
    """One path: (exit price, how it ended, worst dip in %, stop gapped).
    The dip only counts prices while the position was still open."""
    sign = 1.0 if long else -1.0

    def dip(price: float) -> float:
        return (price / plan.entry - 1) * 100 * sign

    price = plan.entry
    stop = plan.stop
    best = plan.entry
    worst = 0.0
    for day in path:
        opened = price * math.exp(day.gap)
        high = price * math.exp(day.high)
        low = price * math.exp(day.low)
        close = price * math.exp(day.close)
        hit_stop_open = opened <= stop if long else opened >= stop
        hit_target_open = opened >= plan.target if long else opened <= plan.target
        if hit_stop_open:
            return opened, "stop", min(worst, dip(opened)), True
        if hit_target_open:
            return opened, "target", worst, False
        adverse, favourable = (low, high) if long else (high, low)
        # Both touched in one day: assume the stop came first (cautious).
        if (adverse <= stop) if long else (adverse >= stop):
            return stop, "stop", min(worst, dip(stop)), False
        worst = min(worst, dip(adverse))
        if (favourable >= plan.target) if long else (favourable <= plan.target):
            return plan.target, "target", worst, False
        if plan.trailing_pct:
            if long:
                best = max(best, high)
                stop = max(stop, best * (1 - plan.trailing_pct / 100))
            else:
                best = min(best, low)
                stop = min(stop, best * (1 + plan.trailing_pct / 100))
        price = close
    return price, "time", worst, False


def _percentile(ordered: Sequence[float], share: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def seed_for(*parts: str) -> int:
    """A stable seed from the round and the plan, so a rerun matches."""
    total = 0
    for char in "|".join(parts):
        total = (total * 131 + ord(char)) % 2_147_483_647
    return total
