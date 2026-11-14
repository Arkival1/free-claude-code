"""The scorecard: seven plain-code marks for a proposed buy, and a final
confidence that can only lower the Portfolio Manager's.

Each category is scored 0-100 with the reason:
- data quality: the data checks' score;
- technical setup: the trend, where the price sits against its averages,
  and whether it is stretched (RSI);
- research evidence: how much of the evidence the buy rests on held up in
  the information stress test;
- macro: the market's mood, and events inside the holding window;
- risk quality: the reward for the risk, the stop's distance in ATRs, and
  the worst stressed loss against its limit;
- portfolio fit: correlation with what's held and the position's share of
  the account;
- execution quality: the spread and the order's share of a day's trading.

Final confidence = 30% agreement among the seats + 20% data + 20% reward
for risk + 15% history (the base rate of similar setups) + 15% execution.
The order goes ahead with the lower of this and the Portfolio Manager's own
confidence, so the scorecard can stop a weak buy but never rescue one.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

WEIGHTS = {
    "agreement": 30,
    "data": 20,
    "reward_risk": 20,
    "history": 15,
    "execution": 15,
}
MACRO_BY_KIND = {
    "bull_trend": 80,
    "low_volatility": 70,
    "sideways": 55,
    "unclear": 45,
    "bear_trend": 35,
    "high_volatility": 30,
}
EVENT_PENALTY = 15


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class Category:
    name: str
    score: int
    why: str

    def view(self) -> JsonObject:
        return {"name": self.name, "score": self.score, "why": self.why}


@dataclass(frozen=True, slots=True)
class Scorecard:
    categories: tuple[Category, ...]
    parts: tuple[tuple[str, float], ...]
    """The final confidence's parts, each 0-1."""
    confidence: float

    def lines(self) -> str:
        rows = [
            f"{item.name.replace('_', ' ')}: {item.score}/100 ({item.why})"
            for item in self.categories
        ]
        rows.append(
            "Final confidence "
            f"{self.confidence:.2f} = "
            + " + ".join(
                f"{WEIGHTS[name]}% {name.replace('_', ' ')} {value:.2f}"
                for name, value in self.parts
            )
        )
        return "\n".join(rows)

    def view(self) -> JsonObject:
        return {
            "categories": [item.view() for item in self.categories],
            "parts": {name: round(value, 4) for name, value in self.parts},
            "confidence": round(self.confidence, 4),
        }


@dataclass(frozen=True, slots=True)
class TradeFacts:
    """What the scorecard reads, all worked out elsewhere in code."""

    consensus: float
    buy_share: float
    quality_score: int
    reward_risk: float | None
    stop_atr: float | None
    trend: str
    price: float
    sma50: float | None
    sma200: float | None
    rsi: float | None
    held_up: int | None
    """Load-bearing items that held in the information stress test."""
    tested: int | None
    regime_kind: str
    regime_extreme: bool
    events_in_window: int
    stress_worst_pct: float | None
    stress_limit_pct: float
    max_correlation: float | None
    correlation_limit: float
    position_pct: float | None
    position_cap_pct: float
    spread_pct: float | None
    spread_limit_pct: float
    adv_pct: float | None
    adv_limit_pct: float
    base_target_first: float | None


def score_trade(facts: TradeFacts) -> Scorecard:
    categories: list[Category] = []

    def add(name: str, value: float, why: str) -> None:
        categories.append(Category(name, round(_clamp(value / 100) * 100), why))

    add("data_quality", facts.quality_score, "the data checks' score")

    technical = 50.0
    notes: list[str] = []
    if facts.trend == "up":
        technical += 20
        notes.append("uptrend")
    elif facts.trend == "down":
        technical -= 20
        notes.append("downtrend")
    for name, level in (("50-day", facts.sma50), ("200-day", facts.sma200)):
        if level:
            above = facts.price > level
            technical += 10 if above else -10
            notes.append(f"{'above' if above else 'below'} the {name} average")
    if facts.rsi is not None and facts.rsi > 75:
        technical -= 10
        notes.append(f"stretched (RSI {facts.rsi:.0f})")
    add("technical_setup", technical, ", ".join(notes) or "no clear trend")

    if facts.tested:
        held = facts.held_up or 0
        add(
            "research_evidence",
            100 * held / facts.tested,
            f"{held} of {facts.tested} load-bearing items held up",
        )
    else:
        add("research_evidence", 50, "the evidence wasn't stress-tested")

    macro = float(MACRO_BY_KIND.get(facts.regime_kind, 45))
    macro -= EVENT_PENALTY * facts.events_in_window
    if facts.regime_extreme:
        macro = 0
    add(
        "macro",
        macro,
        f"{facts.regime_kind.replace('_', ' ')}"
        + (", extreme" if facts.regime_extreme else "")
        + (
            f", {facts.events_in_window} event(s) in the holding window"
            if facts.events_in_window
            else ""
        ),
    )

    reward = _clamp(((facts.reward_risk or 0.0) - 1) / 2)
    stop = _clamp((facts.stop_atr or 0.0) / 2)
    stress = (
        _clamp(1 - facts.stress_worst_pct / facts.stress_limit_pct)
        if facts.stress_worst_pct is not None and facts.stress_limit_pct > 0
        else 0.5
    )
    add(
        "risk_quality",
        100 * (reward + stop + stress) / 3,
        f"reward for risk {facts.reward_risk or 0:.2f}, stop "
        f"{facts.stop_atr or 0:.2f} ATR, worst stressed loss "
        + (
            f"{facts.stress_worst_pct:.2f}% (limit {facts.stress_limit_pct:g}%)"
            if facts.stress_worst_pct is not None
            else "unknown"
        ),
    )

    correlation = (
        _clamp((facts.max_correlation or 0.0) / facts.correlation_limit)
        if facts.correlation_limit > 0
        else 0.0
    )
    share = (
        _clamp((facts.position_pct or 0.0) / facts.position_cap_pct)
        if facts.position_cap_pct > 0
        else 0.0
    )
    add(
        "portfolio_fit",
        100 * (1 - 0.5 * correlation - 0.5 * share),
        f"highest correlation {facts.max_correlation or 0:+.2f}, position "
        f"{facts.position_pct or 0:.1f}% of the account",
    )

    spread = (
        _clamp((facts.spread_pct or 0.0) / facts.spread_limit_pct)
        if facts.spread_limit_pct > 0
        else 0.0
    )
    volume = (
        _clamp((facts.adv_pct or 0.0) / facts.adv_limit_pct)
        if facts.adv_limit_pct > 0
        else 0.0
    )
    execution = _clamp(1 - 0.5 * spread - 0.5 * volume)
    add(
        "execution_quality",
        100 * execution,
        (
            f"spread {facts.spread_pct:.3f}%"
            if facts.spread_pct is not None
            else "spread unknown (assumed)"
        )
        + f", {facts.adv_pct or 0:.3f}% of a day's trading",
    )

    agreement = 0.5 * _clamp(facts.buy_share) + 0.5 * _clamp(
        (facts.consensus - 0.5) / 0.25
    )
    history = (
        _clamp(facts.base_target_first) if facts.base_target_first is not None else 0.5
    )
    parts = (
        ("agreement", agreement),
        ("data", _clamp(facts.quality_score / 100)),
        ("reward_risk", reward),
        ("history", history),
        ("execution", execution),
    )
    confidence = sum(WEIGHTS[name] * value for name, value in parts) / 100
    return Scorecard(tuple(categories), parts, round(confidence, 4))


def spread_of(spreads: Sequence[float | None]) -> float | None:
    found = [value for value in spreads if value is not None]
    return min(found) if found else None
