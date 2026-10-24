"""The market's mood: is the index trending, and is it calm or wild?

Read from the market's own yardstick (the ASX 200, the S&P 500, Bitcoin) and,
for shares, the VIX. The Macro seat and the Portfolio Manager see it, and a
wild or falling market shrinks every position.

Each reading also gets one of six labels (bull trend, bear trend, sideways,
high volatility, low volatility, unclear) and an "extreme" flag, and a
policy in code that can only make the desk more careful: a higher minimum
confidence, fewer trades a day, a wider minimum stop, a smaller size, or no
new trades at all in an extreme market. It never loosens the owner's limits.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

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
    index_at: float | None = None
    """When the index's latest daily candle started (Unix seconds)."""
    vix_at: float | None = None

    @property
    def label(self) -> str:
        return f"{self.trend} · {self.volatility} volatility"

    @property
    def kind(self) -> RegimeKind:
        if self.market == "unknown":
            return "unclear"
        if self.volatility == "high":
            return "high_volatility"
        if self.trend == "up":
            return "bull_trend"
        if self.trend == "down":
            return "bear_trend"
        if self.volatility == "low":
            return "low_volatility"
        return "sideways"

    @property
    def extreme(self) -> bool:
        """A crash or panic: the VIX very high, or the index down sharply."""
        if self.vix is not None and self.vix >= EXTREME_VIX:
            return True
        fall = EXTREME_FALL_PCT.get(self.market, EXTREME_FALL_PCT["us"])
        return self.index_change_20d is not None and self.index_change_20d <= fall

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
            "kind": self.kind,
            "extreme": self.extreme,
        }

    def lines(self) -> str:
        change = (
            f"{self.index_change_20d:+.1f}% over 20 days"
            if self.index_change_20d is not None
            else "change unknown"
        )
        vix = f"; VIX {self.vix:.1f}" if self.vix is not None else ""
        return (
            f"Market regime ({self.market}): {self.label} "
            f"({self.kind.replace('_', ' ')}{', EXTREME' if self.extreme else ''}); "
            f"index {change}{vix}; position sizes scaled x{self.risk_scale:g}"
        )


UNKNOWN = Regime("unknown", "range", "normal", None, None, 1.0)


type RegimeKind = Literal[
    "bull_trend",
    "bear_trend",
    "sideways",
    "high_volatility",
    "low_volatility",
    "unclear",
]
EXTREME_VIX = 35.0
EXTREME_FALL_PCT: dict[str, float] = {"us": -15.0, "asx": -15.0, "crypto": -30.0}
"""A 20-day index fall this deep counts as a crash."""


@dataclass(frozen=True, slots=True)
class RegimePolicy:
    """What the market's mood changes, only ever towards caution."""

    kind: RegimeKind
    extreme: bool
    size_factor: float
    """On top of the regime's own size scale (never above 1)."""
    confidence_add: float
    """Added to the owner's minimum confidence (never below 0)."""
    trades_factor: float
    """The share of the owner's trades-a-day limit allowed (never above 1)."""
    stop_atr_factor: float
    """The minimum stop distance is multiplied by this (never below 1)."""
    allow_new_trades: bool
    note: str

    def view(self) -> JsonObject:
        return {
            "kind": self.kind,
            "extreme": self.extreme,
            "size_factor": self.size_factor,
            "confidence_add": self.confidence_add,
            "trades_factor": self.trades_factor,
            "stop_atr_factor": self.stop_atr_factor,
            "allow_new_trades": self.allow_new_trades,
            "note": self.note,
        }


_POLICIES: dict[str, tuple[float, float, float, float, str]] = {
    "bull_trend": (1.0, 0.0, 1.0, 1.0, "a rising market: the usual limits"),
    "low_volatility": (1.0, 0.0, 1.0, 1.0, "a calm market: the usual limits"),
    "sideways": (0.9, 0.02, 1.0, 1.0, "a market going nowhere: a little smaller"),
    "bear_trend": (
        1.0,
        0.05,
        0.5,
        1.25,
        "a falling market: surer calls, half the trades, wider stops",
    ),
    "high_volatility": (
        1.0,
        0.05,
        0.5,
        1.5,
        "a wild market: surer calls, half the trades, stops further away",
    ),
    "unclear": (
        0.75,
        0.05,
        0.5,
        1.0,
        "the market's mood is unknown: smaller, surer, fewer trades",
    ),
}


def policy_for(regime: Regime) -> RegimePolicy:
    size, confidence, trades, stop, note = _POLICIES[regime.kind]
    if regime.extreme:
        return RegimePolicy(
            regime.kind,
            True,
            min(1.0, size),
            max(0.0, confidence),
            min(1.0, trades),
            max(1.0, stop),
            False,
            "an extreme market (a crash or panic): no new trades",
        )
    return RegimePolicy(
        regime.kind,
        False,
        min(1.0, size),
        max(0.0, confidence),
        min(1.0, trades),
        max(1.0, stop),
        True,
        note,
    )


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
    return Regime(
        market,
        trend,
        volatility,
        roc(values, 20),
        vix_level,
        scale,
        index_at=float(index[-1].t) if index else None,
        vix_at=float(vix[-1].t) if vix else None,
    )
