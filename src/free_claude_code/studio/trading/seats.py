"""The five seats: who they are, what they're asked, and the JSON they answer in.

Every answer is a small JSON object. Small local models wander, so each
schema is forgiving: "60%" reads as 0.6, "bullish" as buy, a lone string as a
one-item list, unknown keys are ignored. An answer that still can't be read
is asked for once more; after that the seat sits the turn out.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..jsonish import lenient_object
from ..llm import strip_thinking
from .config import SeatConfig

type Think = Callable[[SeatConfig, str, str, int], Awaitable[str]]
"""Ask one seat: (seat, system prompt, prompt, max tokens) → its reply text."""

ROLES: dict[int, str] = {
    1: (
        "You are the Technical Analyst on a five-seat trading desk. You read "
        "charts: trend, momentum, volume, support and resistance, volatility, "
        "and the base rates of similar setups. Judge only what the numbers "
        "show."
    ),
    2: (
        "You are the Fundamental and Web Researcher on a five-seat trading "
        "desk. You read the news, earnings, announcements, and company or "
        "token facts gathered for you and judge what they mean for the price. "
        "Use only facts in your notes; never invent news."
    ),
    3: (
        "You are the Macro and Sentiment Predictor on a five-seat trading "
        "desk. You judge the overall market trend, the sector, the crowd's "
        "mood, and events such as interest-rate decisions, inflation data, "
        "and crypto-wide news."
    ),
    4: (
        "You are the Risk Guardian and devil's advocate on a five-seat "
        "trading desk. You find what would make a trade lose money and argue "
        "against bad trades. Be specific and fair: name concrete risks and "
        "worst cases, and mark which points must block the trade unless they "
        "are answered. When the case is genuinely strong, say so."
    ),
    5: (
        "You are the Portfolio Manager on a five-seat trading desk and you "
        "make the final call. Protect the account first. Weigh each seat by "
        "its track record, the base rates, and the market regime; answer "
        "every blocking objection; buy only when the odds and the reward for "
        "the risk are clearly in favour, otherwise hold. Long trades only: "
        "buy to open, sell to close."
    ),
}

ANGLES: dict[int, str] = {
    1: "the chart, the volume, and the base rates",
    2: "the news, earnings, and fundamentals",
    3: "the market regime, the sector, sentiment, and upcoming events",
    4: "everything that could go wrong",
    5: "the whole picture",
}

CALIBRATION = (
    "Be calibrated: a 0.60 chance means you would be right 6 times in 10. "
    "Reply with ONE JSON object and nothing else."
)

FORECAST_KEYS = (
    '"stance": "buy|hold|sell|avoid", "p_up": 0-1 (chance the price is higher '
    'after horizon_days), "horizon_days": 1-20, "expected_move_pct": number, '
    '"p_target": 0-1 (chance a target of about 2 ATR comes before a 1 ATR '
    'stop), "confidence": 0-1, "reasons": ["up to 3 short reasons"], '
    '"risks": ["up to 2"]'
)

_STANCES = {
    "buy": "buy",
    "long": "buy",
    "bullish": "buy",
    "accumulate": "buy",
    "strong buy": "buy",
    "hold": "hold",
    "neutral": "hold",
    "wait": "hold",
    "watch": "hold",
    "sell": "sell",
    "bearish": "sell",
    "short": "sell",
    "reduce": "sell",
    "avoid": "avoid",
    "pass": "avoid",
    "skip": "avoid",
}


def probability(value: object, default: float = 0.5) -> float:
    """Read a chance written as 0.6, 60, "60%", or "0.6"."""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, str):
        text = value.strip().rstrip("%").strip()
        try:
            number = float(text)
        except ValueError:
            return default
        if value.strip().endswith("%"):
            number /= 100
    elif isinstance(value, int | float):
        number = float(value)
    else:
        return default
    if number > 1.0:
        number = number / 100 if number <= 100 else 1.0
    return max(0.0, min(1.0, number))


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        found = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        return float(found.group()) if found else default
    return default


def _texts(value: object, limit: int) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    found = [" ".join(str(item).split())[:240] for item in items if str(item).strip()]
    return found[:limit]


class Forecast(BaseModel):
    """A measurable call: direction, chance, horizon, and why."""

    model_config = ConfigDict(extra="ignore")

    stance: str = "hold"
    p_up: float = 0.5
    horizon_days: int = 5
    expected_move_pct: float = 0.0
    p_target: float | None = None
    confidence: float = 0.5
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    @field_validator("stance", mode="before")
    @classmethod
    def _stance(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return _STANCES.get(
            text, _STANCES.get(text.split()[0], "hold") if text else "hold"
        )

    @field_validator("p_up", "confidence", mode="before")
    @classmethod
    def _chance(cls, value: object) -> float:
        return probability(value)

    @field_validator("p_target", mode="before")
    @classmethod
    def _target_chance(cls, value: object) -> float | None:
        return None if value is None or value == "" else probability(value)

    @field_validator("horizon_days", mode="before")
    @classmethod
    def _horizon(cls, value: object) -> int:
        return max(1, min(60, int(_number(value, 5) or 5)))

    @field_validator("expected_move_pct", mode="before")
    @classmethod
    def _move(cls, value: object) -> float:
        return max(-95.0, min(500.0, _number(value)))

    @field_validator("reasons", mode="before")
    @classmethod
    def _reasons(cls, value: object) -> list[str]:
        return _texts(value, 4)

    @field_validator("risks", mode="before")
    @classmethod
    def _risks(cls, value: object) -> list[str]:
        return _texts(value, 3)

    def line(self) -> str:
        target = (
            f", target-first {self.p_target:.0%}" if self.p_target is not None else ""
        )
        why = "; ".join(self.reasons[:2])
        return (
            f"{self.stance} · {self.p_up:.0%} up in {self.horizon_days}d "
            f"({self.expected_move_pct:+.1f}%){target} · confidence "
            f"{self.confidence:.2f}" + (f" — {why}" if why else "")
        )


class Researched(Forecast):
    next_earnings: str = ""
    """YYYY-MM-DD, or empty when the notes don't say."""

    @field_validator("next_earnings", mode="before")
    @classmethod
    def _date(cls, value: object) -> str:
        found = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
        return found.group() if found else ""


class Event(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    date: str = ""

    @field_validator("date", mode="before")
    @classmethod
    def _date(cls, value: object) -> str:
        found = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
        return found.group() if found else ""


class MacroView(Forecast):
    events: list[Event] = Field(default_factory=list)

    @field_validator("events", mode="before")
    @classmethod
    def _events(cls, value: object) -> list[object]:
        return value[:6] if isinstance(value, list) else []


class CrossExam(Forecast):
    agree: list[str] = Field(default_factory=list)
    disagree: list[str] = Field(default_factory=list)
    question: str = ""

    @field_validator("agree", "disagree", mode="before")
    @classmethod
    def _points(cls, value: object) -> list[str]:
        return _texts(value, 4)

    @field_validator("question", mode="before")
    @classmethod
    def _question(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:300]


_SEAT_NAMES = {
    "technical": 1,
    "chart": 1,
    "analyst": 1,
    "research": 2,
    "fundamental": 2,
    "macro": 3,
    "sentiment": 3,
    "guardian": 4,
    "risk": 4,
    "portfolio": 5,
    "manager": 5,
    "pm": 5,
}


class Objection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target: int = 1
    """The seat it's aimed at (1-3, or 5 for the Portfolio Manager)."""
    point: str
    blocking: bool = False

    @field_validator("target", mode="before")
    @classmethod
    def _target(cls, value: object) -> int:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return max(1, min(5, int(value)))
        text = str(value or "").lower()
        digit = re.search(r"[1-5]", text)
        if digit:
            return int(digit.group())
        for word, seat in _SEAT_NAMES.items():
            if word in text:
                return seat
        return 1

    @field_validator("point", mode="before")
    @classmethod
    def _point(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:300]

    @field_validator("blocking", mode="before")
    @classmethod
    def _blocking(cls, value: object) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "blocking", "block", "1"}
        return bool(value)


def _objections(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    found: list[object] = [
        item for item in value if isinstance(item, dict) and item.get("point")
    ]
    return found[:6]


def _verdict(value: object, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    for word in allowed:
        if text.startswith(word):
            return word
    return default


class PreMortem(Forecast):
    failure_story: str = ""
    worst_case_pct: float = 0.0
    objections: list[Objection] = Field(default_factory=list)
    verdict: str = "caution"

    @field_validator("objections", mode="before")
    @classmethod
    def _list(cls, value: object) -> list[object]:
        return _objections(value)

    @field_validator("worst_case_pct", mode="before")
    @classmethod
    def _worst(cls, value: object) -> float:
        return abs(_number(value))

    @field_validator("verdict", mode="before")
    @classmethod
    def _call(cls, value: object) -> str:
        return _verdict(value, ("proceed", "caution", "block"), "caution")


class Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    point: str = ""
    answer: str = ""
    conceded: bool = False

    @field_validator("point", "answer", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:400]


def _answers(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    found: list[object] = [item for item in value if isinstance(item, dict)]
    return found[:8]


class Rebuttal(Forecast):
    answers: list[Answer] = Field(default_factory=list)

    @field_validator("answers", mode="before")
    @classmethod
    def _list(cls, value: object) -> list[object]:
        return _answers(value)


class GuardianReply(Forecast):
    resolved: list[str] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)
    verdict: str = "caution"

    @field_validator("resolved", mode="before")
    @classmethod
    def _resolved(cls, value: object) -> list[str]:
        return _texts(value, 6)

    @field_validator("objections", mode="before")
    @classmethod
    def _list(cls, value: object) -> list[object]:
        return _objections(value)

    @field_validator("verdict", mode="before")
    @classmethod
    def _call(cls, value: object) -> str:
        return _verdict(value, ("proceed", "caution", "block"), "caution")


class Decision(BaseModel):
    """The Portfolio Manager's call and, for a buy, the order plan."""

    model_config = ConfigDict(extra="ignore")

    action: Literal["buy", "sell", "hold"] = "hold"
    order_type: Literal["market", "limit"] = "market"
    limit_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    size_pct: float = 100.0
    horizon_days: int = 5
    p_up: float = 0.5
    p_target: float | None = None
    confidence: float = 0.5
    rationale: str = ""
    answers: list[Answer] = Field(default_factory=list)

    @field_validator("action", mode="before")
    @classmethod
    def _action(cls, value: object) -> str:
        stance = _STANCES.get(str(value or "").strip().lower(), "hold")
        return stance if stance in {"buy", "sell"} else "hold"

    @field_validator("order_type", mode="before")
    @classmethod
    def _type(cls, value: object) -> str:
        return "limit" if str(value or "").strip().lower() == "limit" else "market"

    @field_validator("limit_price", "stop_loss", "take_profit", mode="before")
    @classmethod
    def _price(cls, value: object) -> float | None:
        number = _number(value, 0.0)
        return number if number > 0 else None

    @field_validator("size_pct", mode="before")
    @classmethod
    def _size(cls, value: object) -> float:
        number = _number(value, 100.0)
        if 0 < number <= 1 and not (isinstance(value, str) and "%" in value):
            number *= 100
        return max(0.0, min(100.0, number))

    @field_validator("horizon_days", mode="before")
    @classmethod
    def _horizon(cls, value: object) -> int:
        return max(1, min(60, int(_number(value, 5) or 5)))

    @field_validator("p_up", "confidence", mode="before")
    @classmethod
    def _chance(cls, value: object) -> float:
        return probability(value)

    @field_validator("p_target", mode="before")
    @classmethod
    def _target_chance(cls, value: object) -> float | None:
        return None if value is None or value == "" else probability(value)

    @field_validator("rationale", mode="before")
    @classmethod
    def _why(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:800]

    @field_validator("answers", mode="before")
    @classmethod
    def _list(cls, value: object) -> list[object]:
        return _answers(value)

    def line(self) -> str:
        if self.action != "buy":
            return f"{self.action} — {self.rationale}"
        plan = f"{self.order_type}" + (
            f" at {self.limit_price:g}" if self.limit_price else ""
        )
        return (
            f"buy ({plan}), stop {self.stop_loss or 'none'}, target "
            f"{self.take_profit or 'none'}, size {self.size_pct:.0f}% of max, "
            f"{self.p_up:.0%} up in {self.horizon_days}d, confidence "
            f"{self.confidence:.2f} — {self.rationale}"
        )


class Challenge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    verdict: str = "clear"
    point: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _call(cls, value: object) -> str:
        return _verdict(value, ("clear", "block"), "clear")

    @field_validator("point", mode="before")
    @classmethod
    def _point(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:400]


class RiskNote(BaseModel):
    """One seat's view in the risk assessment period."""

    model_config = ConfigDict(extra="ignore")

    grade: str = ""
    concerns: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    size_factor: float = 1.0
    defer: bool = False
    note: str = ""

    @field_validator("grade", mode="before")
    @classmethod
    def _grade(cls, value: object) -> str:
        found = re.search(r"[A-F]", str(value or "").upper())
        return found.group() if found else ""

    @field_validator("concerns", "conditions", mode="before")
    @classmethod
    def _list(cls, value: object) -> list[str]:
        return _texts(value, 4)

    @field_validator("size_factor", mode="before")
    @classmethod
    def _factor(cls, value: object) -> float:
        number = _number(value, 1.0)
        if number > 1:
            number /= 100
        return max(0.0, min(1.0, number))

    @field_validator("defer", mode="before")
    @classmethod
    def _defer(cls, value: object) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "defer", "1"}
        return bool(value)

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:400]


class DebriefNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    predicted: str = ""
    happened: str = ""
    missed: str = ""
    lesson: str = ""

    @field_validator("predicted", "happened", "missed", "lesson", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:500]


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = ""
    setting: str = ""
    value: float | str | None = None


class WeeklyReview(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    suggestions: list[Suggestion] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:1500]

    @field_validator("suggestions", mode="before")
    @classmethod
    def _list(cls, value: object) -> list[object]:
        if not isinstance(value, list):
            return []
        found: list[object] = [item for item in value if isinstance(item, dict)]
        return found[:2]


def system_for(seat: int) -> str:
    return f"{ROLES[seat]} {CALIBRATION}"


def read_model[M: BaseModel](text: str, model: type[M]) -> M | None:
    data = lenient_object(strip_thinking(text))
    if not data:
        return None
    try:
        return model.model_validate(data)
    except ValidationError:
        return None


async def ask_json[M: BaseModel](
    think: Think,
    seat: SeatConfig,
    prompt: str,
    model: type[M],
    *,
    max_tokens: int,
    keys: str,
) -> M | None:
    """Ask a seat for one JSON object; ask once more if it can't be read."""
    system = system_for(seat.seat)
    reply = await think(seat, system, prompt, max_tokens)
    found = read_model(reply, model)
    if found is not None:
        return found
    again = (
        f"{prompt}\n\nYour last reply could not be read. Reply again with ONLY "
        f"this JSON object and nothing before or after it: {{{keys}}}"
    )
    return read_model(await think(seat, system, again, max_tokens), model)


class SessionNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    watch: str = ""

    @field_validator("summary", "watch", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:1200]


class MissNotes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    notes: list[str] = Field(default_factory=list)
    lesson: str = ""

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, value: object) -> list[str]:
        return _texts(value, 5)

    @field_validator("lesson", mode="before")
    @classmethod
    def _lesson(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:500]
