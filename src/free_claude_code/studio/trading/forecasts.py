"""Forecasts: saved when made, scored when due, turned into track records.

Every seat's opening and closing forecast and the Portfolio Manager's call
are saved for every debated symbol, traded or not, so the desk learns from
every debate. When one comes due it is scored against the price:
- hit: did the price move the way the seat leaned;
- Brier score: (chance said - what happened)²; 0 is perfect, 0.25 a coin toss;
- log score: rewards confidence when right and punishes it when wrong;
- target first: did a +2 ATR target come before a -1 ATR stop (or the plan's).
Track records turn into vote weights (0.5x to 2x) once a seat has 20 scored
forecasts; until then everyone counts the same.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from .indicators import Bar
from .records import TradeForecast

DAY_MS = 86_400_000
MIN_SCORED_FOR_WEIGHT = 20
WEIGHT_FLOOR = 0.5
WEIGHT_CAP = 2.0
RECENT = 50
VOID_AFTER_MS = 5 * DAY_MS
"""A forecast with no price this long after it came due is set aside."""


def due_at(created_ms: int, horizon_days: int, market: str) -> int:
    """When a forecast comes due: trading days for shares, calendar days for
    coins (which trade every day)."""
    calendar_days = (
        horizon_days if market in {"crypto", "dex"} else math.ceil(horizon_days * 7 / 5)
    )
    return created_ms + calendar_days * DAY_MS


@dataclass(frozen=True, slots=True)
class Score:
    outcome_move: float
    hit: bool
    brier: float
    log_score: float
    target_first: bool | None


def score(forecast: TradeForecast, bars: Sequence[Bar]) -> Score | None:
    """Score a forecast against daily bars, or None while the price at its due
    time isn't known yet."""
    if forecast.entry_price <= 0:
        return None
    due_s = forecast.due_at // 1000
    created_s = forecast.created_at // 1000
    after = [bar for bar in bars if bar.t >= due_s - 43_200]
    if not after:
        return None
    closing = after[0].c
    move = (closing / forecast.entry_price - 1) * 100
    went_up = move > 0
    p = min(0.99, max(0.01, forecast.p_up))
    target_first: bool | None = None
    if forecast.target is not None and forecast.stop is not None:
        for bar in bars:
            if bar.t <= created_s - 43_200 or bar.t > due_s + 43_200:
                continue
            if bar.l <= forecast.stop:
                target_first = False
                break
            if bar.h >= forecast.target:
                target_first = True
                break
        else:
            target_first = False
    return Score(
        outcome_move=move,
        hit=(forecast.p_up >= 0.5) == went_up,
        brier=(forecast.p_up - (1.0 if went_up else 0.0)) ** 2,
        log_score=math.log(p if went_up else 1 - p),
        target_first=target_first,
    )


@dataclass(frozen=True, slots=True)
class Bucket:
    said: float
    happened: float
    count: int


@dataclass(frozen=True, slots=True)
class SeatRecord:
    seat: int
    scored: int
    hit_rate: float | None
    brier: float | None
    skill: float | None
    """Brier skill against a coin toss: above 0 beats it, 1 is perfect."""
    weight: float
    buckets: tuple[Bucket, ...]
    overconfident_above: float | None

    def line(self) -> str:
        if not self.scored:
            return "No scored forecasts yet."
        parts = [
            f"{self.scored} scored forecasts",
            f"direction right {self.hit_rate:.0%}" if self.hit_rate is not None else "",
            f"Brier skill {self.skill:+.2f}" if self.skill is not None else "",
            f"vote weight x{self.weight:.2f}",
        ]
        text = ", ".join(part for part in parts if part)
        if self.overconfident_above is not None:
            bucket = next(
                (b for b in self.buckets if b.said >= self.overconfident_above), None
            )
            if bucket is not None:
                text += (
                    f"; overconfident above {self.overconfident_above:.0%} (you said "
                    f"{bucket.said:.0%}, it happened {bucket.happened:.0%})"
                )
        return text + "."

    def view(self) -> JsonObject:
        return {
            "seat": self.seat,
            "scored": self.scored,
            "hit_rate": self.hit_rate,
            "brier": self.brier,
            "skill": self.skill,
            "weight": self.weight,
            "buckets": [
                {"said": b.said, "happened": b.happened, "count": b.count}
                for b in self.buckets
            ],
            "overconfident_above": self.overconfident_above,
            "line": self.line(),
        }


def track_record(
    seat: int, forecasts: Iterable[TradeForecast], *, recent: int = RECENT
) -> SeatRecord:
    """A seat's record over its latest scored forecasts."""
    scored = sorted(
        (
            f
            for f in forecasts
            if f.seat == seat and f.status == "scored" and f.brier is not None
        ),
        key=lambda f: f.scored_at or 0,
    )[-recent:]
    if not scored:
        return SeatRecord(seat, 0, None, None, None, 1.0, (), None)
    brier = sum(f.brier or 0.0 for f in scored) / len(scored)
    hits = sum(1 for f in scored if f.hit) / len(scored)
    skill = 1 - brier / 0.25
    weight = (
        max(WEIGHT_FLOOR, min(WEIGHT_CAP, 1 + 2 * skill))
        if len(scored) >= MIN_SCORED_FOR_WEIGHT
        else 1.0
    )
    buckets: list[Bucket] = []
    for low, high in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        # The chance given to the direction the seat leaned: 0.3 up is 0.7 down.
        group = [f for f in scored if low <= max(f.p_up, 1 - f.p_up) < high]
        if not group:
            continue
        said = sum(max(f.p_up, 1 - f.p_up) for f in group) / len(group)
        happened = sum(1 for f in group if f.hit) / len(group)
        buckets.append(Bucket(round(said, 3), round(happened, 3), len(group)))
    overconfident = next(
        (
            bucket.said
            for bucket in buckets
            if bucket.count >= 5
            and bucket.said - bucket.happened > 0.1
            and bucket.said >= 0.6
        ),
        None,
    )
    return SeatRecord(
        seat,
        len(scored),
        round(hits, 3),
        round(brier, 4),
        round(skill, 3),
        round(weight, 3),
        tuple(buckets),
        round(overconfident, 2) if overconfident is not None else None,
    )


def records(
    forecasts: Sequence[TradeForecast], *, market: str = ""
) -> dict[int, SeatRecord]:
    """Every seat's record, in one market or across all of them."""
    chosen = [f for f in forecasts if not market or f.market == market]
    return {seat: track_record(seat, chosen) for seat in range(1, 6)}


def weighted(
    forecasts: dict[int, tuple[float, str]], weights: dict[int, float]
) -> tuple[float, float]:
    """The weighted chance of a rise and the weighted share leaning buy, from
    each seat's (p_up, stance)."""
    total = sum(weights.get(seat, 1.0) for seat in forecasts)
    if total <= 0:
        return 0.5, 0.0
    chance = (
        sum(weights.get(seat, 1.0) * p for seat, (p, _) in forecasts.items()) / total
    )
    buying = (
        sum(
            weights.get(seat, 1.0)
            for seat, (_, stance) in forecasts.items()
            if stance == "buy"
        )
        / total
    )
    return chance, buying
