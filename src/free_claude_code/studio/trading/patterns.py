"""Base rates: what happened the other times a chart looked like this.

Every past day in the symbol's own history is given a setup signature: above
or below the 200-day average, the 20-day average above or below the 50-day,
an RSI bucket, a volume spike or not, and how stretched the price is from the
20-day average. The days that match today's signature say how often the
price was higher 1, 5, and 20 days later, by how much on average, and how
often a target of a few ATRs was hit before a stop. Too few exact matches
loosen the signature; too few even then fall back to the market's index.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from .indicators import Bar, atr, closes, rsi, sma

HORIZONS = (1, 5, 20)
MIN_SAMPLES = 15


@dataclass(frozen=True, slots=True)
class BaseRate:
    signature: str
    level: str
    """exact, relaxed, broad, or index (the market's index, not the symbol)."""
    samples: int
    win_rate: dict[int, float]
    """Share of matches higher after each horizon (days)."""
    avg_move: dict[int, float]
    """Average move after each horizon, percent."""
    target_first: float | None
    stop_first: float | None
    target_atr: float
    stop_atr: float

    def view(self) -> JsonObject:
        return {
            "signature": self.signature,
            "level": self.level,
            "samples": self.samples,
            "win_rate": {str(h): round(v, 3) for h, v in self.win_rate.items()},
            "avg_move": {str(h): round(v, 2) for h, v in self.avg_move.items()},
            "target_first": (
                round(self.target_first, 3) if self.target_first is not None else None
            ),
            "stop_first": (
                round(self.stop_first, 3) if self.stop_first is not None else None
            ),
            "target_atr": self.target_atr,
            "stop_atr": self.stop_atr,
        }

    def lines(self) -> str:
        where = "this market's index" if self.level == "index" else "its own history"
        horizons = ", ".join(
            f"{h}d: up {self.win_rate[h] * 100:.0f}% (avg {self.avg_move[h]:+.1f}%)"
            for h in sorted(self.win_rate)
        )
        hits = (
            f"; a +{self.target_atr:g} ATR target came before a -{self.stop_atr:g} "
            f"ATR stop {self.target_first * 100:.0f}% of the time"
            if self.target_first is not None
            else ""
        )
        return (
            f"Base rates ({self.samples} similar days in {where}, {self.level} "
            f"match of [{self.signature}]): {horizons}{hits}"
        )


@dataclass(frozen=True, slots=True)
class _Features:
    above_200: str
    short_over_long: str
    rsi_bucket: str
    volume_spike: str
    stretch: str

    def at(self, level: str) -> tuple[str, ...]:
        if level == "exact":
            return (
                self.above_200,
                self.short_over_long,
                self.rsi_bucket,
                self.volume_spike,
                self.stretch,
            )
        if level == "relaxed":
            return (self.above_200, self.short_over_long, self.rsi_bucket)
        if level == "broad":
            return (self.above_200, self.rsi_bucket)
        # "loose": for a symbol too young to know its 200-day average.
        return (self.short_over_long, self.rsi_bucket)

    def label(self) -> str:
        return " ".join(
            (
                f"200d:{self.above_200}",
                f"20>50:{self.short_over_long}",
                f"RSI:{self.rsi_bucket}",
                f"vol:{self.volume_spike}",
                f"stretch:{self.stretch}",
            )
        )


def _rsi_bucket(value: float | None) -> str:
    if value is None:
        return "?"
    for edge, name in ((30, "<30"), (45, "30-45"), (55, "45-55"), (70, "55-70")):
        if value < edge:
            return name
    return ">70"


def _stretch(price: float, average: float | None) -> str:
    if average is None or average == 0:
        return "?"
    gap = (price / average - 1) * 100
    for edge, name in (
        (-5, "<-5%"),
        (-1.5, "-5..-1.5%"),
        (1.5, "flat"),
        (5, "1.5..5%"),
    ):
        if gap < edge:
            return name
    return ">5%"


def _features(bars: Sequence[Bar]) -> list[_Features]:
    values = closes(bars)
    s20, s50, s200 = sma(values, 20), sma(values, 50), sma(values, 200)
    strength = rsi(values)
    found: list[_Features] = []
    for index, bar in enumerate(bars):
        window = bars[max(0, index - 20) : index]
        average_volume = sum(item.v for item in window) / len(window) if window else 0
        spike = "y" if average_volume and bar.v > 1.8 * average_volume else "n"
        long = s200[index]
        short, middle = s20[index], s50[index]
        found.append(
            _Features(
                above_200="?" if long is None else ("y" if bar.c > long else "n"),
                short_over_long=(
                    "?"
                    if short is None or middle is None
                    else ("y" if short > middle else "n")
                ),
                rsi_bucket=_rsi_bucket(strength[index]),
                volume_spike=spike,
                stretch=_stretch(bar.c, short),
            )
        )
    return found


def _matches(
    features: list[_Features], level: str, *, start: int, end: int
) -> list[int]:
    today = features[-1].at(level)
    return [i for i in range(start, end) if features[i].at(level) == today]


def _rates(
    bars: Sequence[Bar],
    indices: list[int],
    ranges: list[float | None],
    *,
    target_atr: float,
    stop_atr: float,
    within: int,
) -> tuple[dict[int, float], dict[int, float], float | None, float | None]:
    win: dict[int, float] = {}
    move: dict[int, float] = {}
    for horizon in HORIZONS:
        changes = [
            (bars[i + horizon].c / bars[i].c - 1) * 100
            for i in indices
            if i + horizon < len(bars) and bars[i].c
        ]
        if changes:
            win[horizon] = sum(1 for change in changes if change > 0) / len(changes)
            move[horizon] = sum(changes) / len(changes)
    targets = stops = counted = 0
    for i in indices:
        size = ranges[i]
        if size is None or size <= 0 or i + 1 >= len(bars):
            continue
        counted += 1
        entry = bars[i].c
        up, down = entry + target_atr * size, entry - stop_atr * size
        for j in range(i + 1, min(len(bars), i + 1 + within)):
            # A bar touching both counts as the stop: the cautious reading.
            if bars[j].l <= down:
                stops += 1
                break
            if bars[j].h >= up:
                targets += 1
                break
    if not counted:
        return win, move, None, None
    return win, move, targets / counted, stops / counted


def base_rates(
    bars: Sequence[Bar],
    *,
    index: Sequence[Bar] = (),
    target_atr: float = 2.0,
    stop_atr: float = 1.0,
    within: int = 20,
    min_samples: int = MIN_SAMPLES,
) -> BaseRate | None:
    """Base rates for today's setup, or None with too little history."""
    found = _from(
        bars,
        target_atr,
        stop_atr,
        within,
        min_samples,
        levels=("exact", "relaxed", "broad"),
    )
    if found is not None or len(index) <= 60 or len(bars) < 21:
        return found
    # Too few similar days of its own: read the market's index at the same
    # setup (today's signature is the symbol's, the history is the index's).
    features = _features(index)
    features[-1] = _features(bars)[-1]
    return _from(
        index,
        target_atr,
        stop_atr,
        within,
        min_samples,
        levels=("loose",),
        features=features,
        label="index",
    )


def _from(
    bars: Sequence[Bar],
    target_atr: float,
    stop_atr: float,
    within: int,
    min_samples: int,
    *,
    levels: tuple[str, ...],
    features: list[_Features] | None = None,
    label: str = "",
) -> BaseRate | None:
    if len(bars) < 60:
        return None
    features = features or _features(bars)
    ranges = atr(bars)
    start = min(200, len(bars) // 3)
    end = len(bars) - 1 - max(HORIZONS[0], 1)
    for level in levels:
        indices = _matches(features, level, start=start, end=end)
        if len(indices) < min_samples:
            continue
        win, move, target_first, stop_first = _rates(
            bars,
            indices,
            ranges,
            target_atr=target_atr,
            stop_atr=stop_atr,
            within=within,
        )
        if not win:
            continue
        return BaseRate(
            signature=features[-1].label(),
            level=label or level,
            samples=len(indices),
            win_rate=win,
            avg_move=move,
            target_first=target_first,
            stop_first=stop_first,
            target_atr=target_atr,
            stop_atr=stop_atr,
        )
    return None


def setup_tag(bars: Sequence[Bar]) -> str:
    """Today's signature, used to tag forecasts and lessons."""
    if len(bars) < 21:
        return ""
    return _features(bars)[-1].label()
