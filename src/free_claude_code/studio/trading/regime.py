"""The market's mood: is the index trending, and is it calm or wild?

Read from the market's own yardstick (the ASX 200, the S&P 500, Bitcoin) and,
for shares, the VIX. The Macro seat and the Portfolio Manager see it, and a
wild or falling market shrinks every position.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from .indicators import Bar, atr, closes, roc, sma


@dataclass(frozen=True, slots=True)
class Regime:
    market: str
    trend: str
    """up, down, or range."""
    volatility: str
    """low, normal, or high."""
    index_change_20d: float | None
    vix: float | None
    risk_scale: float
    """What every position size is multiplied by in this regime."""

    @property
    def label(self) -> str:
        return f"{self.trend} · {self.volatility} volatility"

    def view(self) -> JsonObject:
        return {
            "market": self.market,
            "trend": self.trend,
            "volatility": self.volatility,
            "label": self.label,
            "index_change_20d": (
                round(self.index_change_20d, 2)
                if self.index_change_20d is not None
                else None
            ),
            "vix": round(self.vix, 1) if self.vix is not None else None,
            "risk_scale": self.risk_scale,
        }

    def lines(self) -> str:
        change = (
            f"{self.index_change_20d:+.1f}% over 20 days"
            if self.index_change_20d is not None
            else "change unknown"
        )
        vix = f"; VIX {self.vix:.1f}" if self.vix is not None else ""
        return (
            f"Market regime ({self.market}): {self.label}; index {change}{vix}; "
            f"position sizes scaled x{self.risk_scale:g}"
        )


UNKNOWN = Regime("unknown", "range", "normal", None, None, 1.0)


def read_regime(market: str, index: Sequence[Bar], vix: Sequence[Bar] = ()) -> Regime:
    """Read the index's trend and volatility (and the VIX for shares)."""
    if len(index) < 60:
        return Regime(market, "range", "normal", None, None, 1.0)
    values = closes(index)
    price = values[-1]
    short = sma(values, 50)
    long = sma(values, 200)
    s50, s200 = short[-1], long[-1]
    earlier = short[-21] if len(short) > 21 else None
    slope = s50 / earlier - 1 if s50 is not None and earlier else 0.0
    if s50 is not None and price > s50 and (s200 is None or s50 > s200) and slope > 0:
        trend = "up"
    elif s50 is not None and price < s50 and (s200 is None or s50 < s200) and slope < 0:
        trend = "down"
    else:
        trend = "range"
    ranges = [
        value / close * 100
        for value, close in zip(atr(index), values, strict=True)
        if value is not None and close
    ]
    volatility = "normal"
    if len(ranges) > 20:
        typical = statistics.median(ranges[-250:])
        if typical > 0:
            ratio = ranges[-1] / typical
            volatility = "high" if ratio > 1.4 else "low" if ratio < 0.75 else "normal"
    vix_level = vix[-1].c if vix else None
    if vix_level is not None:
        if vix_level > 25:
            volatility = "high"
        elif vix_level < 14 and volatility == "normal":
            volatility = "low"
    scale = 0.5 if volatility == "high" else 0.75 if trend == "down" else 1.0
    return Regime(market, trend, volatility, roc(values, 20), vix_level, scale)
