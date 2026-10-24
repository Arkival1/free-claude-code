"""Code compares the seats' calls before anyone argues: where they agree,
where they split, and which evidence only one of them relies on. Plain
arithmetic, no model; the lines go to the feed and into the
cross-examination, so the seats argue about real differences."""

from collections import Counter
from collections.abc import Mapping

from .contract import SeatCall
from .log import SEAT_NAMES

CHANCE_SPREAD = 0.15
CONFIDENCE_SPREAD = 25
LEVEL_SPREAD_ATR = 0.5
"""Stops or targets further apart than this many ATRs differ."""
LEVEL_SPREAD_PCT = 1.0
"""...or than this share of the price, when the ATR isn't known."""


def compare_calls(
    calls: Mapping[int, SeatCall], *, price: float, atr: float
) -> list[str]:
    if len(calls) < 2:
        return []
    lines: list[str] = []
    by_direction: dict[str, list[int]] = {}
    for seat, call in sorted(calls.items()):
        by_direction.setdefault(call.direction, []).append(seat)
    if len(by_direction) > 1:
        lines.append(
            "Directions split: "
            + "; ".join(
                f"{direction.replace('_', ' ')}: "
                + ", ".join(SEAT_NAMES.get(seat, str(seat)) for seat in seats)
                for direction, seats in by_direction.items()
            )
            + "."
        )
    else:
        lines.append(f"All say {next(iter(by_direction)).replace('_', ' ')}.")
    chances = [call.p_up for call in calls.values()]
    if max(chances) - min(chances) >= CHANCE_SPREAD:
        lines.append(
            f"The chance of a rise ranges from {min(chances):.0%} to {max(chances):.0%}."
        )
    confidence = [call.confidence for call in calls.values()]
    if max(confidence) - min(confidence) >= CONFIDENCE_SPREAD:
        lines.append(
            f"Confidence ranges from {min(confidence)} to {max(confidence)} out of 100."
        )
    longs = {
        seat: call
        for seat, call in sorted(calls.items())
        if call.direction == "long"
        and call.stop_loss is not None
        and call.take_profit is not None
    }
    if len(longs) >= 2:
        for name, values in (
            ("Stops", {seat: call.stop_loss or 0.0 for seat, call in longs.items()}),
            (
                "Targets",
                {seat: call.take_profit or 0.0 for seat, call in longs.items()},
            ),
        ):
            spread = max(values.values()) - min(values.values())
            wide = (
                spread >= LEVEL_SPREAD_ATR * atr
                if atr > 0
                else price > 0 and spread / price * 100 >= LEVEL_SPREAD_PCT
            )
            if wide:
                lines.append(
                    f"{name} differ: "
                    + ", ".join(
                        f"{value:g} ({SEAT_NAMES.get(seat, str(seat))})"
                        for seat, value in values.items()
                    )
                    + "."
                )
    cited = Counter(ref for call in calls.values() for ref in set(call.evidence))
    shared = sorted(ref for ref, count in cited.items() if count == len(calls))
    if shared:
        lines.append("All cite " + " ".join(f"[{ref}]" for ref in shared) + ".")
    for seat, call in sorted(calls.items()):
        alone = [ref for ref in dict.fromkeys(call.evidence) if cited[ref] == 1]
        if alone:
            lines.append(
                f"Only the {SEAT_NAMES.get(seat, str(seat))} cites "
                + " ".join(f"[{ref}]" for ref in alone[:5])
                + "."
            )
    return lines
