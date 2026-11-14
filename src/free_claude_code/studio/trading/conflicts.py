"""Conflicts the data checks can't see: seats that confidently oppose a buy,
and a price history that doesn't match the live price.

Price and news conflicts between sources are found by the data checks
(quality.py). Here:
- seat conflicts: each seat whose closing view is a confident sell or
  avoid while the Portfolio Manager buys costs confidence and size (never
  blocks on its own: the consensus, the review and the final challenge do);
- data conflicts: the daily history's last close is so far from the live
  price that they are likely different instruments: the buy is blocked.

Each conflict keeps both sides, which one is used, and why.
"""

from collections.abc import Mapping, Sequence

from .indicators import Bar
from .information import Conflict, iso
from .log import SEAT_NAMES
from .seats import Forecast

CONFIDENT = 0.7
"""A seat this sure of a sell or avoid counts as opposing the buy."""
SEAT_PENALTY = 5.0
"""Confidence points off for each confident opposing seat."""
SEAT_SIZE = 0.75
"""What each confident opposing seat leaves of the size."""
HISTORY_GAP_PCT: dict[str, float] = {"crypto": 40.0, "dex": 40.0}
"""The last daily close and the live price further apart than this (25%
for shares) are treated as different instruments."""


def seat_conflicts(
    symbol: str, closing: Mapping[int, Forecast], *, buying: bool
) -> list[Conflict]:
    if not buying:
        return []
    found: list[Conflict] = []
    for seat, view in sorted(closing.items()):
        if view.stance in {"sell", "avoid"} and view.confidence >= CONFIDENT:
            found.append(
                Conflict(
                    kind="seat",
                    subject=symbol,
                    items=(
                        {
                            "source": SEAT_NAMES.get(seat, str(seat)),
                            "value": f"{view.stance}, {view.p_up:.0%} up, "
                            f"confidence {view.confidence:.2f}",
                            "when": "closing",
                        },
                        {
                            "source": "Portfolio Manager",
                            "value": "buy",
                            "when": "decision",
                        },
                    ),
                    preferred="the weighted vote",
                    reason="a confident seat opposes the buy; confidence and size are cut",
                    confidence_penalty=SEAT_PENALTY,
                    size_factor=SEAT_SIZE,
                )
            )
    return found


def data_conflicts(
    symbol: str, market: str, daily: Sequence[Bar], price: float, *, source: str
) -> list[Conflict]:
    if not daily or price <= 0:
        return []
    last = daily[-1]
    if last.c <= 0:
        return []
    gap = abs(last.c / price - 1) * 100
    limit = HISTORY_GAP_PCT.get(market, 25.0)
    if gap <= limit:
        return []
    return [
        Conflict(
            kind="data",
            subject=symbol,
            items=(
                {
                    "source": source or "daily candles",
                    "value": f"last close {last.c:g}",
                    "when": iso(float(last.t)),
                },
                {"source": "the price checked", "value": f"{price:g}", "when": "now"},
            ),
            preferred="none",
            reason=f"they are {gap:.0f}% apart (over {limit:g}%): likely different "
            "instruments",
            blocking=True,
        )
    ]


def applied(conflicts: Sequence[Conflict]) -> tuple[float, float, bool]:
    """(confidence points off, size left, blocking) for these conflicts."""
    penalty = sum(item.confidence_penalty for item in conflicts if not item.blocking)
    size = 1.0
    for item in conflicts:
        size *= item.size_factor
    return penalty, size, any(item.blocking for item in conflicts)
