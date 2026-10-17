"""The seats' answer contract: every answer is JSON with set fields, checked
in code before anyone acts on it.

A seat's call names the symbol and asset class, a direction (long, short,
sell what we hold, hold, or no trade), a confidence from 0 to 100, its main
reason and thesis, what would prove it wrong, the evidence numbers it relies
on, and for a trade: an entry range, the order type, a stop-loss, a target,
an optional trailing stop, the holding period, the most it would risk, the
events ahead, and its read of liquidity, spread, and gap risk. It echoes the
evidence pack's id, so a call can't be based on older data. Between debate
rounds it also gives up to two open questions and up to three ideas.

Nothing is guessed: an answer that is missing a field, names something that
isn't in the pack, or has a plan that doesn't add up (a stop above the entry
of a long, an entry far from the price) is sent back once with the problems
listed; if the second answer still fails, that seat is left out of the round
and the reason is recorded. Model names and versions are filled in by code,
never taken from the answer.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from free_claude_code.core.json_types import JsonObject

from ..jsonish import lenient_object
from ..llm import strip_thinking
from .config import SeatConfig
from .instruments import Instrument
from .seats import Answer, Event, Think, system_for

PROMPT_VERSION = "2026-10-16.2"
"""Changes whenever the contract or its prompts change; kept with every call."""

ENTRY_BAND_PCT = 5.0
"""How far from the current price an entry range may sit."""

type Direction = Literal["long", "short", "sell", "hold", "no_trade"]
type OrderType = Literal["market", "limit", "stop", "stop_limit"]
type Level = Literal["low", "medium", "high", "unknown"]

_DIRECTIONS: dict[str, str] = {
    "long": "long",
    "buy": "long",
    "short": "short",
    "sell": "sell",
    "exit": "sell",
    "close": "sell",
    "hold": "hold",
    "keep": "hold",
    "no_trade": "no_trade",
    "no trade": "no_trade",
    "none": "no_trade",
    "wait": "no_trade",
    "pass": "no_trade",
}
"""Exact words a model may use, mapped; anything else is refused, never
turned into "hold"."""

_ORDER_TYPES: dict[str, str] = {
    "market": "market",
    "limit": "limit",
    "stop": "stop",
    "stop_limit": "stop_limit",
    "stop-limit": "stop_limit",
    "stop limit": "stop_limit",
}
_LEVELS = {"low", "medium", "high", "unknown"}

TRADES = frozenset({"long", "short"})
ENTRY_ORDERS = frozenset({"market", "limit"})
"""The entry orders the desk places today (stop entries come later)."""
LIMIT_ABOVE_PRICE = 1.02
"""A limit buy may pay at most this much over the price now (the old rule)."""
MARKET_SLACK = 0.01
"""A market order's entry range must include the price now, give or take 1%."""
FACT_PREFIXES = frozenset("FMCNPR")
"""Evidence a trade can rest on: facts, market, calculations, news,
portfolio, rules. Opinions (O) and web reading (W) can't carry a trade."""


def _word(value: object, table: dict[str, str], what: str) -> object:
    if isinstance(value, str):
        key = " ".join(value.strip().lower().replace("-", " ").split())
        found = table.get(key) or table.get(key.replace(" ", "_"))
        if found is not None:
            return found
        raise ValueError(f"{what} must be one of {sorted(set(table.values()))}")
    return value


def _refs(value: object) -> object:
    """["F1", "[N2]", "c3"] -> ["F1", "N2", "C3"]; anything else is left for
    validation to refuse."""
    if isinstance(value, str):
        value = [part for part in value.replace(";", ",").split(",") if part.strip()]
    if isinstance(value, list):
        return [
            str(item).strip().strip("[]").upper() if isinstance(item, str) else item
            for item in value
        ]
    return value


def _clean_text(value: object) -> object:
    return " ".join(value.split()) if isinstance(value, str) else value


class Idea(BaseModel):
    model_config = ConfigDict(extra="ignore")

    idea: str = Field(min_length=3, max_length=240)
    kind: Literal["needs_data", "simulate", "argue"]

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, value: object) -> object:
        return _word(
            value,
            {
                "needs_data": "needs_data",
                "needs data": "needs_data",
                "data": "needs_data",
                "research": "needs_data",
                "simulate": "simulate",
                "simulation": "simulate",
                "argue": "argue",
                "debate": "argue",
            },
            "kind",
        )


class Fact(BaseModel):
    """A claim the Researcher makes, tied to the evidence it comes from."""

    model_config = ConfigDict(extra="ignore")

    claim: str = Field(min_length=3, max_length=300)
    ref: str

    @field_validator("ref", mode="before")
    @classmethod
    def _ref(cls, value: object) -> object:
        return value.strip().strip("[]").upper() if isinstance(value, str) else value


class TradePlan(BaseModel):
    """The plan fields every trade-shaped answer shares."""

    model_config = ConfigDict(extra="ignore")

    entry_low: float | None = Field(default=None, gt=0)
    entry_high: float | None = Field(default=None, gt=0)
    order_type: OrderType | None = None
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    trailing_stop_pct: float | None = Field(default=None, gt=0, le=50)
    holding_days: int | None = Field(default=None, ge=1, le=365)
    max_risk_pct: float | None = Field(default=None, gt=0, le=5)
    """The most of the account this trade may lose at the stop, in %."""

    @field_validator("order_type", mode="before")
    @classmethod
    def _order_type(cls, value: object) -> object:
        return None if value in (None, "") else _word(value, _ORDER_TYPES, "order_type")


def _date(value: object) -> object:
    """A YYYY-MM-DD date found in the text, or empty: never a guess."""
    if value is None:
        return ""
    if isinstance(value, str):
        found = re.search(r"\d{4}-\d{2}-\d{2}", value)
        return found.group() if found else ""
    return value


class SeatCall(TradePlan):
    symbol: str = Field(min_length=1, max_length=40)
    asset_class: Literal["equity", "crypto"]
    direction: Direction
    confidence: int = Field(ge=0, le=100)
    p_up: float = Field(ge=0, le=1)
    """The chance the price is higher at the end of the holding period."""
    p_target: float | None = Field(default=None, ge=0, le=1)
    """The chance the target comes before the stop."""
    expected_move_pct: float | None = Field(default=None, ge=-95, le=500)
    main_reason: str = Field(min_length=3, max_length=400)
    thesis: str = Field(min_length=3, max_length=1500)
    prove_wrong: list[str] = Field(default_factory=list, max_length=5)
    """What would prove the call wrong (its invalidation conditions)."""
    evidence: list[str] = Field(default_factory=list, max_length=20)
    facts: list[Fact] = Field(default_factory=list, max_length=8)
    events: list[Event] = Field(default_factory=list, max_length=6)
    """Dated events ahead (rate decisions, results, unlocks)."""
    next_earnings: str = ""
    """The next results date, YYYY-MM-DD, or empty when the pack doesn't say."""
    liquidity_risk: Level = "unknown"
    spread_risk: Level = "unknown"
    gap_risk: Level = "unknown"
    data_timestamp: str = Field(min_length=1, max_length=80)
    """The evidence pack's id (or its cut-off), echoed back."""
    open_questions: list[str] = Field(default_factory=list, max_length=2)
    ideas: list[Idea] = Field(default_factory=list, max_length=3)
    changed: str = Field(default="", max_length=800)
    """From round 2: what changed in this seat's view, and why."""

    @field_validator("direction", mode="before")
    @classmethod
    def _direction(cls, value: object) -> object:
        return _word(value, _DIRECTIONS, "direction")

    @field_validator("asset_class", mode="before")
    @classmethod
    def _asset_class(cls, value: object) -> object:
        return _word(
            value,
            {
                "equity": "equity",
                "share": "equity",
                "shares": "equity",
                "stock": "equity",
                "crypto": "crypto",
                "coin": "crypto",
                "cryptocurrency": "crypto",
            },
            "asset_class",
        )

    @field_validator("liquidity_risk", "spread_risk", "gap_risk", mode="before")
    @classmethod
    def _level(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() in _LEVELS:
            return value.strip().lower()
        return value

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, value: object) -> object:
        return _refs(value)

    @field_validator("main_reason", "thesis", "changed", mode="before")
    @classmethod
    def _text(cls, value: object) -> object:
        return _clean_text(value)

    @field_validator("next_earnings", mode="before")
    @classmethod
    def _earnings(cls, value: object) -> object:
        return _date(value)

    @field_validator("prove_wrong", "open_questions", mode="before")
    @classmethod
    def _texts(cls, value: object) -> object:
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            return [
                " ".join(item.split())[:300] if isinstance(item, str) else item
                for item in value
                if not (isinstance(item, str) and not item.strip())
            ]
        return value


class PMDecision(TradePlan):
    """The Portfolio Manager's decision, bounded later by the Guardian and
    the hard limits in code."""

    action: Direction
    size_pct: float = Field(default=100.0, ge=0, le=100)
    """The share of the size the limits allow that the PM wants."""
    confidence: int = Field(ge=0, le=100)
    p_up: float = Field(ge=0, le=1)
    p_target: float | None = Field(default=None, ge=0, le=1)
    """The chance the target is reached before the stop."""
    rationale: str = Field(min_length=3, max_length=1500)
    supporting: list[str] = Field(default_factory=list, max_length=20)
    opposing: list[str] = Field(default_factory=list, max_length=20)
    prove_wrong: list[str] = Field(default_factory=list, max_length=5)
    answers: list[Answer] = Field(default_factory=list, max_length=12)
    """An answer to each unresolved blocking objection, by its number."""
    data_timestamp: str = Field(min_length=1, max_length=80)

    @field_validator("action", mode="before")
    @classmethod
    def _action(cls, value: object) -> object:
        return _word(value, _DIRECTIONS, "action")

    @field_validator("supporting", "opposing", mode="before")
    @classmethod
    def _evidence(cls, value: object) -> object:
        return _refs(value)

    @field_validator("rationale", mode="before")
    @classmethod
    def _text(cls, value: object) -> object:
        return _clean_text(value)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=3, max_length=80)
    fall_pct: float = Field(ge=0, le=90)
    """A move against the position, 0-90%."""


class GuardianCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    check: str = Field(min_length=2, max_length=120)
    ok: bool
    note: str = Field(default="", max_length=300)


class GuardianReview(BaseModel):
    """The Risk Guardian's verdict on the draft plan code built: it can
    approve, approve smaller, delay, or reject (a veto)."""

    model_config = ConfigDict(extra="ignore")

    verdict: Literal["approved", "approved_smaller", "delayed", "rejected"]
    size_factor: float = Field(default=1.0, gt=0, le=1)
    reasons: list[str] = Field(min_length=1, max_length=8)
    evidence: list[str] = Field(default_factory=list, max_length=20)
    checks: list[GuardianCheck] = Field(default_factory=list, max_length=12)
    scenarios: list[Scenario] = Field(default_factory=list, max_length=2)
    data_timestamp: str = Field(min_length=1, max_length=80)

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, value: object) -> object:
        return _word(
            value,
            {
                "approved": "approved",
                "approve": "approved",
                "approved_smaller": "approved_smaller",
                "approved smaller": "approved_smaller",
                "smaller": "approved_smaller",
                "delayed": "delayed",
                "delay": "delayed",
                "rejected": "rejected",
                "reject": "rejected",
                "veto": "rejected",
            },
            "verdict",
        )

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, value: object) -> object:
        return _refs(value)


class AttackItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    verdict: Literal["holds", "weak", "fails"]
    why: str = Field(default="", max_length=400)

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, value: object) -> object:
        return value.strip().strip("[]").upper() if isinstance(value, str) else value

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, value: object) -> object:
        return _word(
            value,
            {
                "holds": "holds",
                "hold": "holds",
                "ok": "holds",
                "weak": "weak",
                "fails": "fails",
                "fail": "fails",
                "wrong": "fails",
            },
            "verdict",
        )


class EvidenceAttack(BaseModel):
    """A seat's attempt to knock down the evidence a buy rests on."""

    model_config = ConfigDict(extra="ignore")

    items: list[AttackItem] = Field(min_length=1, max_length=20)
    still_buy_without_strongest: bool
    note: str = Field(default="", max_length=600)


class FinalCheck(BaseModel):
    """The Risk Guardian's last word on the exact order: clear it or block it."""

    model_config = ConfigDict(extra="ignore")

    verdict: Literal["clear", "block"]
    point: str = Field(default="", max_length=400)

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, value: object) -> object:
        return _word(
            value,
            {
                "clear": "clear",
                "cleared": "clear",
                "block": "block",
                "blocked": "block",
            },
            "verdict",
        )

    @field_validator("point", mode="before")
    @classmethod
    def _point(cls, value: object) -> object:
        return _clean_text(value)


# ---------------------------------------------------------------- checks


@dataclass(frozen=True, slots=True)
class PackView:
    """What the checks need to know about the evidence pack."""

    id: str
    cutoff_text: str
    refs: frozenset[str]


def _stamp_problem(stamp: str, pack: PackView) -> list[str]:
    if pack.id in stamp or (pack.cutoff_text and pack.cutoff_text in stamp):
        return []
    return [
        f"data_timestamp must be this pack's id ({pack.id}); it was {stamp!r}, so "
        "the answer may rest on older data"
    ]


def _ref_problems(refs: Sequence[str], pack: PackView, field_name: str) -> list[str]:
    unknown = [ref for ref in refs if ref not in pack.refs]
    if unknown:
        return [
            f"{field_name} names evidence that isn't in the pack: {', '.join(unknown[:6])}"
        ]
    return []


def plan_problems(
    plan: TradePlan,
    direction: str,
    *,
    price: float,
    band_pct: float = ENTRY_BAND_PCT,
) -> list[str]:
    """Does the plan add up? Only for a new long or short."""
    if direction not in TRADES:
        return []
    found: list[str] = []
    missing = [
        name
        for name in (
            "entry_low",
            "entry_high",
            "order_type",
            "stop_loss",
            "take_profit",
            "holding_days",
        )
        if getattr(plan, name) is None
    ]
    if missing:
        return [f"a {direction} needs {', '.join(missing)}"]
    low, high = plan.entry_low or 0.0, plan.entry_high or 0.0
    stop, target = plan.stop_loss or 0.0, plan.take_profit or 0.0
    if low > high:
        found.append("entry_low is above entry_high")
    if direction == "long":
        if stop >= low:
            found.append(f"a long's stop ({stop:g}) must be below its entry ({low:g})")
        if target <= high:
            found.append(
                f"a long's target ({target:g}) must be above its entry ({high:g})"
            )
    else:
        if stop <= high:
            found.append(
                f"a short's stop ({stop:g}) must be above its entry ({high:g})"
            )
        if target >= low:
            found.append(
                f"a short's target ({target:g}) must be below its entry ({low:g})"
            )
    if price > 0:
        far = max(abs(low / price - 1), abs(high / price - 1)) * 100
        if far > band_pct:
            found.append(
                f"the entry range {low:g}-{high:g} is {far:.1f}% from the price "
                f"{price:g} (at most {band_pct:g}%)"
            )
    return found


def check_call(
    call: SeatCall,
    *,
    instrument: Instrument,
    pack: PackView,
    price: float,
    held: bool,
) -> list[str]:
    """Everything wrong with a seat's call; an empty list means it stands."""
    found: list[str] = []
    want = instrument.symbol.upper()
    got = call.symbol.strip().upper()
    if got not in {want, instrument.code.upper(), want.removesuffix("-USD")}:
        found.append(f"symbol must be {instrument.symbol}, not {call.symbol}")
    expected_class = "crypto" if instrument.market in {"crypto", "dex"} else "equity"
    if call.asset_class != expected_class:
        found.append(f"asset_class must be {expected_class}")
    found += _stamp_problem(call.data_timestamp, pack)
    found += _ref_problems(call.evidence, pack, "evidence")
    found += _ref_problems([fact.ref for fact in call.facts], pack, "facts")
    if call.direction == "sell" and not held:
        found.append("sell is only for something we hold; use no_trade or short")
    if call.direction in TRADES | {"sell"}:
        if not call.evidence:
            found.append(f"a {call.direction} must cite evidence numbers")
        elif call.direction in TRADES and not any(
            ref[:1] in FACT_PREFIXES for ref in call.evidence
        ):
            found.append("a trade can't rest only on opinions (O) or web reading (W)")
        if call.direction in TRADES and not call.prove_wrong:
            found.append("say what would prove the call wrong (prove_wrong)")
    if call.direction == "long" and call.p_up <= 0.5:
        found.append("a long needs p_up above 0.5")
    if call.direction == "short" and call.p_up >= 0.5:
        found.append("a short needs p_up below 0.5")
    found += plan_problems(call, call.direction, price=price)
    return found


def check_decision(
    decision: PMDecision,
    *,
    pack: PackView,
    price: float,
    held: bool,
    shorts_allowed: bool,
    order_types: frozenset[str] | None = None,
    blocking: int = 0,
) -> list[str]:
    """Everything wrong with the Portfolio Manager's decision. ``order_types``
    are the entry orders the desk can place; ``blocking`` is how many
    unresolved blocking objections a trade must answer."""
    found = _stamp_problem(decision.data_timestamp, pack)
    found += _ref_problems(decision.supporting, pack, "supporting")
    found += _ref_problems(decision.opposing, pack, "opposing")
    if decision.action == "sell" and not held:
        found.append("sell is only for something we hold")
    if decision.action == "short" and not shorts_allowed:
        found.append("shorts are switched off; choose long, hold, or no_trade")
    if decision.action in TRADES:
        if not decision.supporting:
            found.append("a trade must cite its supporting evidence")
        elif not any(ref[:1] in FACT_PREFIXES for ref in decision.supporting):
            found.append("a trade can't rest only on opinions (O) or web reading (W)")
        if not decision.prove_wrong:
            found.append("say what would prove the decision wrong (prove_wrong)")
        if decision.size_pct <= 0:
            found.append("size_pct must be above 0 for a trade")
        if (
            order_types is not None
            and decision.order_type is not None
            and decision.order_type not in order_types
        ):
            found.append(
                f"the desk places {' or '.join(sorted(order_types))} entries; "
                f"not {decision.order_type}"
            )
        if len(decision.answers) < blocking:
            found.append(
                f"answer every unresolved blocking objection by its number "
                f"({len(decision.answers)} of {blocking} answered)"
            )
    found += plan_problems(decision, decision.action, price=price)
    if decision.action == "long" and None not in (
        decision.entry_low,
        decision.entry_high,
        decision.order_type,
        decision.stop_loss,
        decision.take_profit,
    ):
        found += _long_order_problems(decision, price)
    return found


def _long_order_problems(decision: PMDecision, price: float) -> list[str]:
    """The rules the desk's buy orders always had, kept as they were: the
    stop below the price, the target above it, a limit no more than 2%
    over it; and a market order's entry range must include the price."""
    found: list[str] = []
    stop, target = decision.stop_loss or 0.0, decision.take_profit or 0.0
    low, high = decision.entry_low or 0.0, decision.entry_high or 0.0
    if stop >= price:
        found.append(f"the stop_loss ({stop:g}) must be below the price ({price:g})")
    if target <= price:
        found.append(
            f"the take_profit ({target:g}) must be above the price ({price:g})"
        )
    if decision.order_type == "limit" and high > price * LIMIT_ABOVE_PRICE:
        found.append(
            f"a limit buy pays at most entry_high ({high:g}), which must be at "
            f"or below {price * LIMIT_ABOVE_PRICE:g} (2% over the price)"
        )
    if decision.order_type == "market" and not (
        low <= price * (1 + MARKET_SLACK) and high >= price * (1 - MARKET_SLACK)
    ):
        found.append(
            f"a market order fills near the price ({price:g}); the entry range "
            f"{low:g}-{high:g} must include it"
        )
    return found


def check_review(review: GuardianReview, *, pack: PackView) -> list[str]:
    found = _stamp_problem(review.data_timestamp, pack)
    found += _ref_problems(review.evidence, pack, "evidence")
    if review.verdict == "approved_smaller" and review.size_factor >= 1:
        found.append("approved_smaller needs a size_factor below 1")
    return found


def check_final(found: FinalCheck) -> list[str]:
    if found.verdict == "block" and not found.point.strip():
        return ["say what is wrong with the order (point)"]
    return []


def check_attack(attack: EvidenceAttack, *, wanted: Sequence[str]) -> list[str]:
    found: list[str] = []
    asked = set(wanted)
    unknown = [item.id for item in attack.items if item.id not in asked]
    if unknown:
        found.append(f"only judge the listed items; not {', '.join(unknown[:6])}")
    unexplained = [
        item.id
        for item in attack.items
        if item.verdict != "holds" and not item.why.strip()
    ]
    if unexplained:
        found.append(f"say why for {', '.join(unexplained[:6])}")
    return found


# ---------------------------------------------------------------- asking


@dataclass(frozen=True, slots=True)
class Checked[M: BaseModel]:
    """One seat's checked answer, with who answered and what went wrong."""

    seat: int
    model_name: str
    prompt_version: str
    value: M | None
    problems: tuple[str, ...] = ()
    """What was wrong with the first answer (and the second, if refused)."""
    repaired: bool = False
    at: float = field(default_factory=time.time)

    @property
    def ignored(self) -> bool:
        return self.value is None

    def view(self) -> JsonObject:
        return {
            "seat": self.seat,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
            "value": self.value.model_dump() if self.value is not None else None,
            "problems": list(self.problems),
            "repaired": self.repaired,
            "ignored": self.ignored,
            "at": self.at,
        }


def read_checked[M: BaseModel](
    text: str, model: type[M], check: Callable[[M], list[str]]
) -> tuple[M | None, list[str]]:
    data = lenient_object(strip_thinking(text))
    if not data:
        return None, ["the reply had no JSON object"]
    try:
        found = model.model_validate(data)
    except ValidationError as error:
        problems = []
        for item in error.errors()[:8]:
            where = ".".join(str(part) for part in item.get("loc", ())) or "answer"
            problems.append(f"{where}: {item.get('msg', 'invalid')}")
        return None, problems
    problems = check(found)
    return (found if not problems else None), problems


async def ask_checked[M: BaseModel](
    think: Think,
    seat: SeatConfig,
    prompt: str,
    model: type[M],
    *,
    check: Callable[[M], list[str]],
    keys: str,
    max_tokens: int,
    clock: Callable[[], float] = time.time,
) -> Checked[M]:
    """Ask once; if the answer fails its checks, ask once more with the
    problems listed; a second failure leaves the seat out (recorded)."""
    system = system_for(seat.seat)
    name = seat.model or "default"
    reply = await think(seat, system, prompt, max_tokens)
    found, problems = read_checked(reply, model, check)
    if found is not None:
        return Checked(seat.seat, name, PROMPT_VERSION, found, at=clock())
    again = (
        f"{prompt}\n\nYour last answer was not accepted:\n"
        + "\n".join(f"- {problem}" for problem in problems[:8])
        + f"\nReply again with ONLY this JSON object and nothing else: {{{keys}}}"
    )
    second, more = read_checked(
        await think(seat, system, again, max_tokens), model, check
    )
    if second is not None:
        return Checked(
            seat.seat, name, PROMPT_VERSION, second, tuple(problems), True, clock()
        )
    return Checked(
        seat.seat, name, PROMPT_VERSION, None, tuple(problems + more), True, clock()
    )
