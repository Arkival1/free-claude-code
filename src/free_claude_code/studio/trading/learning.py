"""Controlled learning: how much each seat's vote counts, changed only in
small, checked, versioned steps.

The seats' forecasts are scored when they come due (see ``forecasts``).
From those, a new set of vote weights may be proposed:
- only seats with at least 50 scored forecasts can move; the rest stay put;
- the forecasts are split by time: the older 70% to work the weights out
  (newer ones counting more, older ones fading), the newest 30% held back
  to test them on (never seen while working them out);
- a weight moves at most 10% from the current one per version and stays
  between 0.5x and 2x;
- the new set is adopted only if, on the held-back forecasts, the weighted
  call of the seats is better calibrated (a lower Brier score) and gets the
  direction right at least as often as the current set does. Otherwise it is
  kept as rejected, with the reason.
Every version is kept (none is ever deleted), the active one can be rolled
back by the owner on the PC, and an active version that does worse than the
one before it on newer forecasts is rolled back by itself.

Learning changes vote weights only. It never touches the owner's limits,
safety rules, money settings, keys, or the kill switch, and it makes no
claim about future profit: a past score is not a promise.
"""

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from .records import TradeForecast

SEATS = (1, 2, 3, 4, 5)
MIN_SAMPLES = 50
HOLDOUT_SHARE = 0.3
MAX_CHANGE = 0.10
LOWEST, HIGHEST = 0.5, 2.0
HALF_LIFE_DAYS = 60.0
WINDOWS = (10, 50, 100)
DAY_MS = 86_400_000
WORSE_BY = 0.005
"""How much worse (Brier) an active version must do to be rolled back."""


@dataclass(frozen=True, slots=True)
class Check:
    """The weighted call of the seats on a set of forecasts."""

    calls: int
    brier: float | None
    hit_rate: float | None

    def view(self) -> JsonObject:
        return {"calls": self.calls, "brier": self.brier, "hit_rate": self.hit_rate}


@dataclass(frozen=True, slots=True)
class Proposal:
    weights: dict[int, float]
    accepted: bool
    reason: str
    current: Check
    proposed: Check
    samples: dict[int, int]

    def view(self) -> JsonObject:
        return {
            "weights": {str(seat): w for seat, w in self.weights.items()},
            "accepted": self.accepted,
            "reason": self.reason,
            "current": self.current.view(),
            "proposed": self.proposed.view(),
            "samples": {str(seat): n for seat, n in self.samples.items()},
        }


def _usable(forecasts: Sequence[TradeForecast]) -> list[TradeForecast]:
    return sorted(
        (
            f
            for f in forecasts
            if f.status == "scored"
            and f.seat in SEATS
            and f.brier is not None
            and f.outcome_move is not None
        ),
        key=lambda f: f.created_at,
    )


def _fit(seat_forecasts: Sequence[TradeForecast], now_ms: int) -> float:
    """A weight from a seat's decayed Brier skill (the same rule as the track
    records: 1 + 2 x skill, within the bounds)."""
    total = weighted = 0.0
    for forecast in seat_forecasts:
        age_days = max(0.0, (now_ms - forecast.created_at) / DAY_MS)
        decay = 0.5 ** (age_days / HALF_LIFE_DAYS)
        total += decay
        weighted += decay * (forecast.brier or 0.0)
    if total <= 0:
        return 1.0
    skill = 1 - (weighted / total) / 0.25
    return min(HIGHEST, max(LOWEST, 1 + 2 * skill))


def check(forecasts: Sequence[TradeForecast], weights: Mapping[int, float]) -> Check:
    """Score the seats' weighted call per debate (one per round and stage)."""
    groups: dict[tuple[str, str], list[TradeForecast]] = {}
    for forecast in forecasts:
        groups.setdefault((forecast.round_id, forecast.stage), []).append(forecast)
    briers: list[float] = []
    hits: list[bool] = []
    for group in groups.values():
        total = sum(weights.get(f.seat, 1.0) for f in group)
        if total <= 0:
            continue
        chance = sum(weights.get(f.seat, 1.0) * f.p_up for f in group) / total
        rose = (group[0].outcome_move or 0.0) > 0
        briers.append((chance - (1.0 if rose else 0.0)) ** 2)
        if chance != 0.5:
            hits.append((chance > 0.5) == rose)
    return Check(
        calls=len(briers),
        brier=round(statistics.fmean(briers), 5) if briers else None,
        hit_rate=round(sum(hits) / len(hits), 4) if hits else None,
    )


def propose(
    forecasts: Sequence[TradeForecast],
    current: Mapping[int, float],
    *,
    now_ms: int,
) -> Proposal:
    usable = _usable(forecasts)
    cut = math.floor(len(usable) * (1 - HOLDOUT_SHARE))
    fit, held = usable[:cut], usable[cut:]
    samples = {seat: sum(1 for f in fit if f.seat == seat) for seat in SEATS}
    weights: dict[int, float] = {}
    for seat in SEATS:
        now = current.get(seat, 1.0)
        if samples[seat] < MIN_SAMPLES:
            weights[seat] = now
            continue
        target = _fit([f for f in fit if f.seat == seat], now_ms)
        step = min(now * (1 + MAX_CHANGE), max(now * (1 - MAX_CHANGE), target))
        weights[seat] = round(min(HIGHEST, max(LOWEST, step)), 4)
    before = check(held, current)
    after = check(held, weights)
    if all(samples[seat] < MIN_SAMPLES for seat in SEATS):
        reason = f"no seat has {MIN_SAMPLES} scored forecasts to learn from yet"
        accepted = False
    elif all(abs(weights[seat] - current.get(seat, 1.0)) < 1e-6 for seat in SEATS):
        reason = "the track records don't call for a change"
        accepted = False
    elif before.brier is None or after.brier is None:
        reason = "no held-back forecasts to test the change on"
        accepted = False
    elif after.brier >= before.brier:
        reason = (
            f"not better on the held-back forecasts (Brier {after.brier:.4f} vs "
            f"{before.brier:.4f} now)"
        )
        accepted = False
    elif (after.hit_rate or 0.0) < (before.hit_rate or 0.0):
        reason = (
            "better calibrated but less often right on direction "
            f"({after.hit_rate:.1%} vs {before.hit_rate:.1%})"
        )
        accepted = False
    else:
        reason = (
            f"better on {after.calls} held-back calls (Brier {after.brier:.4f} vs "
            f"{before.brier:.4f}), direction right at least as often"
        )
        accepted = True
    return Proposal(weights, accepted, reason, before, after, samples)


def worse_than_before(
    forecasts: Sequence[TradeForecast],
    active: Mapping[int, float],
    previous: Mapping[int, float],
    *,
    since_ms: int,
) -> str:
    """Why the active weights should be rolled back ("" if they shouldn't):
    on forecasts made since they were adopted, the previous set did
    clearly better."""
    newer = [f for f in _usable(forecasts) if f.created_at >= since_ms]
    now, then = check(newer, active), check(newer, previous)
    if now.calls < 20 or now.brier is None or then.brier is None:
        return ""
    if now.brier > then.brier + WORSE_BY:
        return (
            f"since it was adopted the previous set did better on {now.calls} calls "
            f"(Brier {then.brier:.4f} vs {now.brier:.4f})"
        )
    return ""


def windows(forecasts: Sequence[TradeForecast]) -> JsonObject:
    """Each seat's latest 10, 50 and 100 scored forecasts, overall and by
    market and by market regime."""
    usable = _usable(forecasts)

    def summary(items: Sequence[TradeForecast]) -> JsonObject:
        found: JsonObject = {}
        for size in WINDOWS:
            latest = list(items)[-size:]
            if not latest:
                continue
            found[str(size)] = {
                "count": len(latest),
                "hit_rate": round(sum(1 for f in latest if f.hit) / len(latest), 3),
                "brier": round(statistics.fmean(f.brier or 0.0 for f in latest), 4),
            }
        return found

    report: JsonObject = {}
    for seat in SEATS:
        mine = [f for f in usable if f.seat == seat]
        report[str(seat)] = {
            "all": summary(mine),
            "markets": {
                market: summary([f for f in mine if f.market == market])
                for market in sorted({f.market for f in mine if f.market})
            },
            "regimes": {
                regime: summary([f for f in mine if f.regime == regime])
                for regime in sorted({f.regime for f in mine if f.regime})
            },
        }
    return report


def trade_results(
    forecasts: Sequence[TradeForecast], results: Mapping[str, float]
) -> JsonObject:
    """For trades that closed (round id to profit or loss), how often each
    seat's closing lean matched the result."""
    found: JsonObject = {}
    for seat in SEATS:
        calls = [
            f
            for f in forecasts
            if f.seat == seat and f.stage == "closing" and f.round_id in results
        ]
        right = [f for f in calls if (f.p_up > 0.5) == (results[f.round_id] > 0)]
        found[str(seat)] = {
            "trades": len(calls),
            "matched": len(right),
            "rate": round(len(right) / len(calls), 3) if calls else None,
        }
    return found
