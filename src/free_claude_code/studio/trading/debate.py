"""The debate: several rounds (4 by default), with research, brainstorming,
and simulating between them.

Round 1, opening: the three analysts give their calls on their own, blind
to each other (at max depth each is asked three times and averaged: self-
consistency); code compares the calls; each analyst cross-examines the
others (not at fast depth).

Between rounds (breaks.py): the seats' ideas are de-duplicated and sorted;
their open questions are looked up (dated news, a few web searches, the
latest prices) and what is new joins the evidence pack as numbered items;
the leading plans and a few variants run through price paths rebuilt from
the asset's past (not a prediction), and the results join the pack too.

Round 2, attack: every seat updates its call, saying what changed and
citing the new evidence; the Risk Guardian's pre-mortem aims objections at
the analysts; rebuttals and the Guardian's replies follow, round after
round (1, 2, or 4 by depth) until the views settle.

Middle rounds, re-examine: updated calls again, then the objections still
standing are answered again.

Last round, close: closing calls, the weighted consensus, the Portfolio
Manager's decision (answering every standing blocking objection by
number), the information stress test (infotest.py), the Guardian's review
of the draft plan (approve, approve smaller, delay, or veto), and the final
challenge. A blocked order goes back to the Portfolio Manager once, and the
reply faces every check again, the final challenge included.

Calls, decisions, attacks, reviews, and the final challenge are checked
answers (contract.py): sent back once with the problems, then left out and
recorded; a check that can't be read never lets a buy through. Every turn
goes to the live feed as it happens.
"""

import asyncio
import statistics
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from loguru import logger
from pydantic import BaseModel

from free_claude_code.core.json_types import JsonObject

from ..llm import StudioLLMError
from .breaks import (
    BUDGETS,
    Brainstorm,
    Findings,
    LookUp,
    merge_questions,
    new_findings,
    plans_from,
    run_simulations,
    simulation_items,
    sort_ideas,
    variants,
)
from .briefing import Briefing
from .compare import compare_calls
from .config import (
    ANSWER_LENGTH,
    OPENING_SAMPLES,
    REBUTTAL_ROUNDS,
    DataQualityLimits,
    DeskConfig,
    SeatConfig,
)
from .contract import (
    ENTRY_ORDERS,
    EvidenceAttack,
    FinalCheck,
    GuardianReview,
    PackView,
    PMDecision,
    SeatCall,
    ask_checked,
    check_attack,
    check_call,
    check_decision,
    check_final,
    check_review,
)
from .evidence import EvidencePack, extend_pack
from .forecasts import weighted
from .information import QuoteSnapshot, iso
from .infotest import InfoStress, ItemCheck, check_items, combine, load_bearing
from .log import SEAT_NAMES, Feed
from .seats import (
    ANGLES,
    FORECAST_KEYS,
    Challenge,
    CrossExam,
    Decision,
    Event,
    Forecast,
    GuardianReply,
    Objection,
    PreMortem,
    Rebuttal,
    Think,
    ask_json,
)
from .simulate import Plan, SimResult

CONVERGED_MOVE = 0.03
"""Rebuttals stop once the analysts' average chance of a rise moves less."""

TOKENS = {
    "call": 900,
    "cross_exam": 500,
    "pre_mortem": 700,
    "rebuttal": 350,
    "guardian_reply": 500,
    "decision": 1000,
    "attack": 700,
    "review": 700,
    "final_challenge": 300,
}
"""The usual answer lengths; the depth setting scales them (ANSWER_LENGTH)."""

OBJECTION_KEYS = '{"target": 1-3, "point": "...", "blocking": true|false}'
PM_KEYS = (
    '"action": "long|sell|hold|no_trade", "confidence": 0-100, "p_up": 0-1, '
    '"p_target": 0-1 (chance the take-profit comes before the stop), '
    '"rationale": "2-4 sentences citing [ids]", "supporting": ["evidence ids"], '
    '"opposing": ["evidence ids"], "prove_wrong": ["what would prove it wrong"], '
    '"entry_low": number or null, "entry_high": number or null, "order_type": '
    '"market|limit" or null, "stop_loss": number or null, "take_profit": number '
    'or null, "holding_days": 1-60 or null, "size_pct": 0-100 (share of the most '
    'the risk rules allow), "answers": [{"point": "objection number", "answer": '
    '"..."}], "data_timestamp": "PACK"'
)
ATTACK_KEYS = (
    '"items": [{"id": "F1", "verdict": "holds|weak|fails", "why": "..."}], '
    '"still_buy_without_strongest": true|false, "note": "..."'
)
REVIEW_KEYS = (
    '"verdict": "approved|approved_smaller|delayed|rejected", "size_factor": '
    'above 0, at most 1 (below 1 for approved_smaller), "reasons": ["citing '
    '[ids]"], "evidence": ["ids"], "checks": [{"check": "...", "ok": true|false, '
    '"note": "..."}], "scenarios": [{"name": "...", "fall_pct": 0-90}], '
    '"data_timestamp": "PACK"'
)
FINAL_KEYS = '"verdict": "clear|block", "point": "..."'
STANCES = {
    "long": "buy",
    "short": "sell",
    "sell": "sell",
    "hold": "hold",
    "no_trade": "avoid",
}
"""A call's direction as the stance the forecasts and the consensus use."""


@dataclass(frozen=True, slots=True)
class DebateTools:
    """What the debate uses besides the seats: the evidence pack, the clock,
    a way to look things up between rounds, the latest price, and where new
    versions of the pack are kept."""

    pack: EvidencePack | None = None
    clock: Callable[[], float] = time.time
    look_up: LookUp | None = None
    latest: Callable[[], Awaitable[QuoteSnapshot | None]] | None = None
    keep_pack: Callable[[EvidencePack], Awaitable[None]] | None = None
    data: DataQualityLimits = field(default_factory=DataQualityLimits)
    profile: str = "crypto"
    """The rule set the symbol trades under: us, asx, crypto, or meme."""
    cost_pct: float = 0.3
    """Round-trip costs for the simulations, in % of the position."""
    shorts_allowed: bool = False


@dataclass(slots=True)
class DebateResult:
    openings: dict[int, Forecast] = field(default_factory=dict)
    closing: dict[int, Forecast] = field(default_factory=dict)
    premortem: PreMortem | None = None
    objections: list[Objection] = field(default_factory=list)
    """Blocking objections still standing at the end."""
    decision: Decision | None = None
    challenge: Challenge | None = None
    consensus: float = 0.5
    buy_share: float = 0.0
    rebuttal_rounds: int = 0
    converged: bool = False
    earnings: str = ""
    events: list[Event] = field(default_factory=list)
    weights: dict[int, float] = field(default_factory=dict)
    abstained: list[int] = field(default_factory=list)
    rounds: int = 0
    plan: PMDecision | None = None
    """The Portfolio Manager's last checked decision."""
    blocked: str = ""
    """Why the checks after the decision stopped a buy; empty if none did."""
    info_test: InfoStress | None = None
    review: GuardianReview | None = None
    size_factor: float = 1.0
    """What the information stress test and the review left of the size."""
    challenges: int = 0
    pack_id: str = ""
    """The evidence pack version the decision was made on."""
    evidence_text: str = ""
    """That version's text, for the steps after the debate."""
    calls: list[JsonObject] = field(default_factory=list)
    """Every checked answer: who, which model, repaired or left out, why."""
    breaks: list[JsonObject] = field(default_factory=list)
    simulations: list[JsonObject] = field(default_factory=list)

    def record(self) -> JsonObject:
        """What the round keeps of the debate (the feed has every word)."""
        return {
            "rounds": self.rounds,
            "pack_id": self.pack_id,
            "plan": self.plan.model_dump() if self.plan is not None else None,
            "blocked": self.blocked,
            "info_test": self.info_test.view() if self.info_test is not None else None,
            "review": self.review.model_dump() if self.review is not None else None,
            "size_factor": self.size_factor,
            "challenges": self.challenges,
            "calls": self.calls,
            "breaks": self.breaks,
            "simulations": self.simulations,
            "abstained": sorted(set(self.abstained)),
        }


Stage = Callable[[str, int], None]
"""Tell the page which stage the debate is in and which seat is speaking."""


class Debate:
    def __init__(
        self,
        *,
        think: Think,
        feed: Feed,
        config: DeskConfig,
        briefing: Briefing,
        round_id: str,
        weights: Mapping[int, float],
        limits_text: str = "",
        on_stage: Stage | None = None,
        tools: DebateTools | None = None,
    ) -> None:
        self._think = think
        self._feed = feed
        self._config = config
        self._brief = briefing
        self._round = round_id
        self._weights = dict(weights)
        self._limits_text = limits_text
        self._on_stage = on_stage or (lambda stage, seat: None)
        self._tools = tools or DebateTools()
        self._pack = self._tools.pack
        self._calls: dict[int, SeatCall] = {}
        """Each seat's latest checked call."""
        self._last: dict[int, SeatCall] = {}
        """The calls made in the round just finished (for the break)."""
        self._agenda: tuple[str, ...] = ()
        self._fresh: tuple[str, ...] = ()
        """Evidence numbers added in the last break."""
        self._dates: set[str] = set()
        self._events: dict[tuple[str, str], Event] = {}
        self._simulated: set[str] = set()
        """Plans already simulated (an unchanged plan isn't run again)."""
        self.result = DebateResult(weights=dict(weights))

    # ------------------------------------------------------------ plumbing

    def _seat(self, number: int) -> SeatConfig:
        return self._config.seat(number)

    def _tokens(self, kind: str) -> int:
        return int(TOKENS[kind] * ANSWER_LENGTH[self._config.depth])

    def _view(self) -> PackView:
        if self._pack is None:
            return PackView("no-pack", "", frozenset())
        return PackView(self._pack.id, iso(self._pack.cutoff), self._pack.refs)

    @property
    def _held(self) -> bool:
        return self._brief.held is not None

    def _asset_class(self) -> str:
        market = self._brief.instrument.market
        return "crypto" if market in {"crypto", "dex"} else "equity"

    def _price_line(self) -> str:
        brief = self._brief
        held = (
            "We hold it, so sell (to close) is possible."
            if brief.held
            else "We don't hold it."
        )
        return f"PRICE NOW {brief.price:g}; ATR {brief.tech.atr or 0:g}. {held}"

    async def _say(
        self,
        kind: str,
        seat: int,
        stage: str,
        text: str,
        data: JsonObject | None = None,
    ) -> None:
        await self._feed.emit(
            kind,
            text,
            seat=seat,
            round_id=self._round,
            symbol=self._brief.symbol,
            stage=stage,
            data=data or {},
        )

    async def _ask[M: Forecast](
        self,
        seat: int,
        stage: str,
        prompt: str,
        model: type[M],
        keys: str,
        tokens: int,
    ) -> M | None:
        """The argument turns (cross-examination, pre-mortem, rebuttals,
        replies): forgiving JSON, asked again once if unreadable."""
        self._on_stage(stage, seat)
        try:
            found = await ask_json(
                self._think,
                self._seat(seat),
                prompt,
                model,
                max_tokens=tokens,
                keys=keys,
            )
        except StudioLLMError as error:
            await self._say(
                "error", seat, stage, f"{SEAT_NAMES[seat]} couldn't answer: {error}"
            )
            self.result.abstained.append(seat)
            return None
        if found is None:
            await self._say(
                "info",
                seat,
                stage,
                f"{SEAT_NAMES[seat]}'s answer couldn't be read twice; it sits this turn out.",
            )
            self.result.abstained.append(seat)
        return found

    async def _checked[M: BaseModel](
        self,
        seat: int,
        stage: str,
        prompt: str,
        model: type[M],
        *,
        check: Callable[[M], list[str]],
        keys: str,
        tokens: int,
        temperature_step: float = 0.0,
    ) -> M | None:
        """A checked answer (contract.py): one repair, then the seat sits it
        out; who answered, with which model, and what was wrong is kept."""
        self._on_stage(stage, seat)
        config = self._seat(seat)
        if temperature_step:
            config = config.model_copy(
                update={"temperature": min(1.5, config.temperature + temperature_step)}
            )
        try:
            found = await ask_checked(
                self._think,
                config,
                prompt,
                model,
                check=check,
                keys=keys,
                max_tokens=tokens,
                clock=self._tools.clock,
            )
        except StudioLLMError as error:
            await self._say(
                "error", seat, stage, f"{SEAT_NAMES[seat]} couldn't answer: {error}"
            )
            self.result.abstained.append(seat)
            self.result.calls.append(
                {
                    "stage": stage,
                    "seat": seat,
                    "ignored": True,
                    "problems": [str(error)[:300]],
                }
            )
            return None
        self.result.calls.append(
            {
                "stage": stage,
                "seat": seat,
                "model_name": found.model_name,
                "prompt_version": found.prompt_version,
                "repaired": found.repaired,
                "ignored": found.ignored,
                "problems": list(found.problems)[:8],
                "at": found.at,
            }
        )
        if found.value is None:
            await self._say(
                "info",
                seat,
                stage,
                f"{SEAT_NAMES[seat]}'s answer was sent back once and still didn't "
                "pass the checks, so it sits this turn out: "
                + "; ".join(found.problems[-3:]),
                {"problems": list(found.problems)},
            )
            self.result.abstained.append(seat)
        return found.value

    async def _each[T](self, calls: Mapping[int, Awaitable[T | None]]) -> dict[int, T]:
        seats = list(calls)
        answers = await asyncio.gather(*calls.values(), return_exceptions=True)
        found: dict[int, T] = {}
        for seat, answer in zip(seats, answers, strict=True):
            if isinstance(answer, asyncio.CancelledError):
                raise answer
            if isinstance(answer, BaseException):
                logger.warning("Trading: seat {} failed: {}", seat, answer)
                continue
            if answer is not None:
                found[seat] = answer
        return found

    def _prompt(self, seat: int, *sections: str, task: str, keys: str) -> str:
        parts = [
            self._brief.for_seat(seat),
            *[s for s in sections if s],
            f"TASK: {task}",
        ]
        parts.append(f"Reply with ONLY this JSON object: {{{keys}}}")
        return "\n\n".join(parts)

    @staticmethod
    def _views(views: Mapping[int, Forecast], *, skip: int = 0) -> str:
        return "\n".join(
            f"- {SEAT_NAMES[seat]}: {view.line()}"
            + (
                f" Asks: {view.question}"
                if isinstance(view, CrossExam) and view.question
                else ""
            )
            for seat, view in sorted(views.items())
            if seat != skip
        )

    @staticmethod
    def _numbered(objections: list[Objection]) -> str:
        return "\n".join(
            f"{index}. [{'BLOCKING' if objection.blocking else 'note'}] to "
            f"{SEAT_NAMES.get(objection.target, 'the desk')}: {objection.point}"
            for index, objection in enumerate(objections, 1)
        )

    # ------------------------------------------------------------ the run

    async def run(self) -> DebateResult:
        depth = self._config.depth
        rounds = self._config.debate_rounds
        analysts = [seat for seat in (1, 2, 3) if self._seat(seat).on]
        await self._say(
            "briefing",
            0,
            "Briefing",
            f"Briefing for {self._brief.symbol}: {self._brief.tech.trend} trend, "
            f"{self._brief.regime.label}"
            + (f"; {self._brief.base.lines()}" if self._brief.base is not None else "")
            + f". {rounds} debate round{'s' if rounds != 1 else ''}.",
            {"briefing": self._brief.view(), "rounds": rounds},
        )
        latest: dict[int, Forecast] = {}
        guardian: Forecast | None = None
        objections: list[Objection] = []
        attack = min(2, rounds)
        for number in range(1, rounds + 1):
            if number > 1:
                await self._break(number - 1)
            stage = f"Round {number} of {rounds}"
            await self._say("round", 0, stage, f"{stage}: {_title(number, rounds)}.")
            if number == 1:
                opened = await self._each(
                    {
                        seat: self._opening(seat, OPENING_SAMPLES[depth])
                        for seat in analysts
                    }
                )
                self._take(opened)
                latest.update({seat: _forecast(c) for seat, c in opened.items()})
                self.result.openings = dict(latest)
                lines = await self._compare(opened)
                if depth != "fast" and len(latest) >= 2:
                    latest.update(
                        await self._each(
                            {
                                seat: self._cross_exam(seat, latest, lines)
                                for seat in latest
                            }
                        )
                    )
            elif number < rounds or rounds == 2:
                updated = await self._each(
                    {
                        seat: self._update(seat, number, rounds, latest, objections)
                        for seat in [*analysts, 4]
                    }
                )
                self._take(updated)
                for seat, call in updated.items():
                    if seat == 4:
                        guardian = _forecast(call)
                    else:
                        latest[seat] = _forecast(call)
            if number == attack:
                guardian, objections = await self._attack(latest, analysts, guardian)
            elif 1 < number < rounds:
                guardian, objections = await self._reexamine(
                    number, rounds, latest, analysts, guardian, objections
                )
            if number == rounds:
                await self._close(latest, guardian, objections)
        self.result.rounds = rounds
        self.result.pack_id = self._pack.id if self._pack is not None else ""
        self.result.evidence_text = self._brief.evidence_text
        self._settle_dates()
        return self.result

    def _take(self, calls: Mapping[int, SeatCall]) -> None:
        self._calls.update(calls)
        self._last = dict(calls)

    # ------------------------------------------------------------ calls

    def _call_keys(self, seat: int, *, changed: bool) -> str:
        keys = [
            f'"symbol": "{self._brief.symbol}"',
            f'"asset_class": "{self._asset_class()}"',
            '"direction": "long|short|sell|hold|no_trade"',
            '"confidence": 0-100',
            '"p_up": 0-1 (chance the price is higher after holding_days)',
            '"p_target": 0-1 or null (chance the take-profit comes before the stop)',
            '"expected_move_pct": number',
            '"main_reason": "one sentence citing [ids]"',
            '"thesis": "2-4 sentences citing [ids]"',
            '"prove_wrong": ["what would prove this call wrong"]',
            '"evidence": ["the ids you rely on, e.g. F1, C2"]',
            '"entry_low": number or null',
            '"entry_high": number or null',
            '"order_type": "market|limit" or null',
            '"stop_loss": number or null',
            '"take_profit": number or null',
            '"holding_days": 1-60 or null',
            '"liquidity_risk": "low|medium|high|unknown"',
            '"spread_risk": "low|medium|high|unknown"',
            '"gap_risk": "low|medium|high|unknown"',
        ]
        if seat == 2:
            keys += [
                '"facts": [{"claim": "...", "ref": "N1"}]',
                '"next_earnings": "YYYY-MM-DD or empty"',
            ]
        if seat == 3:
            keys.append('"events": [{"name": "...", "date": "YYYY-MM-DD"}]')
        keys += [
            '"open_questions": ["up to 2: what would change your mind"]',
            '"ideas": [{"idea": "a risk nobody raised, another explanation, or '
            'another way to do the trade", "kind": "needs_data|simulate|argue"}]',
        ]
        if changed:
            keys.append(
                '"changed": "what changed in your view since your last call, and '
                'why ([ids])"'
            )
        keys.append(f'"data_timestamp": "{self._view().id}"')
        return ", ".join(keys)

    def _call_rules(self) -> str:
        return (
            f"YOUR CALL IS ABOUT {self._brief.symbol} ({self._asset_class()}): long "
            "(buy), short, sell (only what we hold), hold, or no_trade. For a long or "
            "a short give an entry range within 5% of the price, the order type, a "
            "stop-loss, a take-profit, and holding_days. Cite evidence by its number "
            "from the pack; a trade can't rest only on opinions (O) or web reading "
            "(W). Copy the pack's id into data_timestamp."
        )

    async def _call(
        self,
        seat: int,
        stage: str,
        *sections: str,
        task: str,
        changed: bool,
        temperature_step: float = 0.0,
    ) -> SeatCall | None:
        keys = self._call_keys(seat, changed=changed)
        view = self._view()
        instrument, price, held = self._brief.instrument, self._brief.price, self._held

        def check(found: SeatCall) -> list[str]:
            return check_call(
                found, instrument=instrument, pack=view, price=price, held=held
            )

        prompt = self._prompt(
            seat,
            *sections,
            self._call_rules(),
            self._price_line(),
            task=task,
            keys=keys,
        )
        return await self._checked(
            seat,
            stage,
            prompt,
            SeatCall,
            check=check,
            keys=keys,
            tokens=self._tokens("call"),
            temperature_step=temperature_step,
        )

    def _note_dates(self, call: SeatCall) -> None:
        if call.next_earnings:
            self._dates.add(call.next_earnings)
        for event in call.events:
            if event.date:
                self._events.setdefault((event.name.casefold(), event.date), event)

    def _settle_dates(self) -> None:
        """The soonest results date any seat gave (so the blackout errs on
        the safe side), and every dated event."""
        today = datetime.fromtimestamp(self._tools.clock(), tz=UTC).date().isoformat()
        upcoming = sorted(day for day in self._dates if day >= today)
        self.result.earnings = upcoming[0] if upcoming else ""
        self.result.events = list(self._events.values())[:10]

    async def _show(
        self, kind: str, seat: int, stage: str, call: SeatCall, *, note: str = ""
    ) -> None:
        await self._say(
            kind,
            seat,
            stage,
            _call_line(call) + note,
            {"forecast": _forecast(call).model_dump(), "call": call.model_dump()},
        )

    async def _opening(self, seat: int, samples: int) -> SeatCall | None:
        extra = (
            " Also give the next results date if the pack says (next_earnings)."
            if seat == 2
            else " Also list dated events (rate decisions, inflation data, token "
            "unlocks) in the next weeks if the pack says."
            if seat == 3
            else ""
        )
        task = (
            f"Opening forecast. Give your own independent call on "
            f"{self._brief.symbol} from {ANGLES[seat]}. The other seats haven't "
            "spoken; don't guess what they think. Brainstorm too: up to 2 open "
            "questions that would change your mind, and up to 3 ideas." + extra
        )
        tries = await asyncio.gather(
            *(
                self._call(
                    seat,
                    "Opening",
                    task=task,
                    changed=False,
                    temperature_step=0.25 * index,
                )
                for index in range(samples)
            )
        )
        found = [call for call in tries if call is not None]
        if not found:
            return None
        call = _average_calls(found) if len(found) > 1 else found[0]
        self._note_dates(call)
        await self._show(
            "opening",
            seat,
            "Opening",
            call,
            note=f" (average of {len(found)} tries)" if len(found) > 1 else "",
        )
        return call

    def _news_section(self) -> str:
        if self._pack is None:
            return ""
        if not self._fresh:
            return "NEW SINCE YOUR LAST CALL: nothing new was found."
        return "NEW SINCE YOUR LAST CALL (added to the pack):\n" + "\n".join(
            self._pack.line(ref) for ref in self._fresh
        )

    async def _update(
        self,
        seat: int,
        number: int,
        rounds: int,
        views: Mapping[int, Forecast],
        objections: list[Objection],
    ) -> SeatCall | None:
        mine = self._calls.get(seat)
        stage = f"Round {number} update"
        sections = [
            f"YOUR LAST CALL: {_call_line(mine)}"
            if mine is not None
            else "You haven't made a call yet.",
            self._news_section(),
            (
                "TO ARGUE THIS ROUND (from the brainstorm):\n"
                + "\n".join(f"- {idea}" for idea in self._agenda)
            )
            if self._agenda
            else "",
            "WHERE THE ANALYSTS STAND:\n" + (self._views(views, skip=seat) or "- none"),
            ("OBJECTIONS STILL STANDING:\n" + self._numbered(objections))
            if objections
            else "",
        ]
        task = (
            f"Updated forecast (round {number} of {rounds}). Re-examine your call "
            f"from {ANGLES[seat]} with the evidence added since the last round. In "
            "changed, say what changed in your view and why, citing the new item "
            "numbers, or why nothing did. Then give your full updated call, up to 2 "
            "new open questions, and up to 3 new ideas."
        )
        call = await self._call(seat, stage, *sections, task=task, changed=True)
        if call is not None:
            self._note_dates(call)
            await self._show("update", seat, stage, call)
        return call

    async def _closing(
        self, seat: int, views: Mapping[int, Forecast]
    ) -> SeatCall | None:
        call = await self._call(
            seat,
            "Closing",
            "WHERE THE DEBATE ENDED:\n" + self._views(views),
            self._news_section() if self._fresh else "",
            task=(
                "Closing statement. Having heard everything, give your final call "
                "on this symbol; in changed, say what changed since your last call "
                "and why."
            ),
            changed=True,
        )
        if call is not None:
            self._note_dates(call)
            await self._show("closing", seat, "Closing", call)
        return call

    async def _compare(self, calls: Mapping[int, SeatCall]) -> list[str]:
        lines = compare_calls(
            calls, price=self._brief.price, atr=self._brief.tech.atr or 0.0
        )
        if lines:
            await self._say(
                "compare",
                0,
                "Compare",
                "Where the opening calls agree and differ:\n" + "\n".join(lines),
                {"lines": lines},
            )
        return lines

    # ------------------------------------------------------------ arguing

    async def _cross_exam(
        self, seat: int, views: Mapping[int, Forecast], lines: list[str]
    ) -> Forecast | None:
        mine = views[seat]
        prompt = self._prompt(
            seat,
            f"YOUR OPENING: {mine.line()}",
            "THE OTHER ANALYSTS SAID:\n" + self._views(views, skip=seat),
            ("WHERE THE CALLS DIFFER (FCC's comparison):\n" + "\n".join(lines))
            if lines
            else "",
            task=(
                "Cross-examine. Say which of their points you agree and disagree "
                "with (point by point), ask the sharpest question you have, and "
                "give your revised forecast."
            ),
            keys=FORECAST_KEYS
            + ', "agree": ["..."], "disagree": ["..."], "question": "..."',
        )
        found = await self._ask(
            seat, "Cross-exam", prompt, CrossExam, FORECAST_KEYS, TOKENS["cross_exam"]
        )
        if found is None:
            return None
        parts = [found.line()]
        if found.disagree:
            parts.append("Disagrees: " + "; ".join(found.disagree[:2]))
        if found.question:
            parts.append("Asks: " + found.question)
        await self._say(
            "cross_exam",
            seat,
            "Cross-exam",
            " | ".join(parts),
            {"forecast": found.model_dump()},
        )
        return found

    async def _attack(
        self,
        latest: dict[int, Forecast],
        analysts: list[int],
        guardian: Forecast | None,
    ) -> tuple[Forecast | None, list[Objection]]:
        """The pre-mortem, then rebuttals and replies until the views settle."""
        premortem = await self._premortem(latest)
        if premortem is not None:
            guardian = premortem
        objections = list(premortem.objections) if premortem is not None else []
        limit = REBUTTAL_ROUNDS[self._config.depth]
        count = 0
        while count < limit:
            aimed = {
                o.target
                for o in objections
                if o.target in analysts and o.target in latest
            }
            if not aimed:
                break
            count += 1
            self.result.rebuttal_rounds += 1
            before = _mean_up(latest, analysts)
            replies = await self._each(
                {
                    seat: self._rebuttal(
                        seat, f"Rebuttal {count}/{limit}", objections, latest
                    )
                    for seat in sorted(aimed)
                }
            )
            latest.update(replies)
            reply = await self._guardian_reply(
                f"Guardian reply {count}/{limit}", objections, replies, latest
            )
            new_blocking = False
            if reply is not None:
                guardian = reply
                known = {o.point.casefold() for o in objections}
                new_blocking = any(
                    o.blocking and o.point.casefold() not in known
                    for o in reply.objections
                )
                objections = list(reply.objections)
            moved = abs(_mean_up(latest, analysts) - before)
            if moved < CONVERGED_MOVE and not new_blocking:
                self.result.converged = True
                await self._say(
                    "info",
                    0,
                    f"Rebuttal {count}/{limit}",
                    f"The seats have settled (average chance of a rise moved "
                    f"{moved:.2f}); the attack ends here.",
                )
                break
        return guardian, objections

    async def _reexamine(
        self,
        number: int,
        rounds: int,
        latest: dict[int, Forecast],
        analysts: list[int],
        guardian: Forecast | None,
        objections: list[Objection],
    ) -> tuple[Forecast | None, list[Objection]]:
        """A middle round: the objections still standing are answered again."""
        aimed = {
            o.target for o in objections if o.target in analysts and o.target in latest
        }
        if not aimed:
            await self._say(
                "info",
                0,
                f"Round {number} of {rounds}",
                "No objection is aimed at an analyst any more; nothing to answer again.",
            )
            return guardian, objections
        self.result.rebuttal_rounds += 1
        replies = await self._each(
            {
                seat: self._rebuttal(
                    seat, f"Rebuttal (round {number} of {rounds})", objections, latest
                )
                for seat in sorted(aimed)
            }
        )
        latest.update(replies)
        reply = await self._guardian_reply(
            f"Guardian reply (round {number} of {rounds})", objections, replies, latest
        )
        if reply is None:
            return guardian, objections
        return reply, list(reply.objections)

    async def _premortem(self, views: Mapping[int, Forecast]) -> PreMortem | None:
        prompt = self._prompt(
            4,
            "THE ANALYSTS' CURRENT VIEWS:\n" + (self._views(views) or "- none"),
            task=(
                f"Pre-mortem. Assume a long trade in {self._brief.symbol} was opened "
                "now and lost money. Say how that most likely happened and the worst "
                "realistic loss in percent. Then aim specific objections at the "
                "seats (target 1 Technical, 2 Researcher, 3 Macro) and mark "
                "blocking: true only for points that must stop the trade unless "
                "answered. Give your own forecast too."
            ),
            keys=FORECAST_KEYS
            + ', "failure_story": "...", "worst_case_pct": number, "objections": ['
            + OBJECTION_KEYS
            + '], "verdict": "proceed|caution|block"',
        )
        found = await self._ask(
            4, "Pre-mortem", prompt, PreMortem, FORECAST_KEYS, TOKENS["pre_mortem"]
        )
        if found is None:
            return None
        self.result.premortem = found
        await self._say(
            "pre_mortem",
            4,
            "Pre-mortem",
            f"{found.failure_story} Worst case about -{found.worst_case_pct:.1f}%. "
            f"Verdict: {found.verdict}."
            + (f"\n{self._numbered(found.objections)}" if found.objections else ""),
            {"premortem": found.model_dump()},
        )
        return found

    async def _rebuttal(
        self,
        seat: int,
        stage: str,
        objections: list[Objection],
        views: Mapping[int, Forecast],
    ) -> Forecast | None:
        aimed = [o for o in objections if o.target == seat]
        prompt = self._prompt(
            seat,
            f"YOUR CURRENT VIEW: {views[seat].line()}",
            "THE RISK GUARDIAN'S OBJECTIONS TO YOU:\n" + self._numbered(aimed),
            "THE OTHER SEATS NOW:\n" + self._views(views, skip=seat),
            task=(
                f"{stage}. Answer each objection: defend it with evidence from the "
                "pack (cite numbers), or concede it honestly. Then give your updated "
                "forecast."
            ),
            keys=FORECAST_KEYS
            + ', "answers": [{"point": "objection number", "answer": "...", '
            '"conceded": true|false}]',
        )
        found = await self._ask(
            seat, stage, prompt, Rebuttal, FORECAST_KEYS, TOKENS["rebuttal"]
        )
        if found is None:
            return None
        answers = " ".join(
            f"[{'concedes' if answer.conceded else 'answers'} {answer.point}] {answer.answer}"
            for answer in found.answers[:3]
        )
        await self._say(
            "rebuttal",
            seat,
            stage,
            found.line() + (f" | {answers}" if answers else ""),
            {"forecast": found.model_dump()},
        )
        return found

    async def _guardian_reply(
        self,
        stage: str,
        objections: list[Objection],
        replies: Mapping[int, Forecast],
        views: Mapping[int, Forecast],
    ) -> GuardianReply | None:
        lines: list[str] = []
        for index, objection in enumerate(objections, 1):
            reply = replies.get(objection.target)
            answer = ""
            if isinstance(reply, Rebuttal):
                matched = [
                    a
                    for a in reply.answers
                    if str(index) in a.point
                    or a.point.casefold() in objection.point.casefold()
                ]
                if matched:
                    answer = (
                        "CONCEDED: " if matched[0].conceded else "ANSWER: "
                    ) + matched[0].answer
            lines.append(
                f"{index}. [{'BLOCKING' if objection.blocking else 'note'}] to "
                f"{SEAT_NAMES.get(objection.target, '?')}: {objection.point}\n   "
                + (answer or "No direct answer.")
            )
        prompt = self._prompt(
            4,
            "YOUR OBJECTIONS AND THEIR ANSWERS:\n" + "\n".join(lines),
            "THE ANALYSTS NOW:\n" + self._views(views),
            task=(
                f"{stage}. Which objections are resolved now? List the ones that "
                "still stand (keep blocking only where the answer failed). Add a new "
                "objection only if something new and important came up. Give your "
                "updated forecast."
            ),
            keys=FORECAST_KEYS
            + ', "resolved": ["..."], "objections": ['
            + OBJECTION_KEYS
            + '], "verdict": "proceed|caution|block"',
        )
        found = await self._ask(
            4, stage, prompt, GuardianReply, FORECAST_KEYS, TOKENS["guardian_reply"]
        )
        if found is None:
            return None
        standing = [o for o in found.objections if o.blocking]
        await self._say(
            "guardian_reply",
            4,
            stage,
            (f"Resolved: {'; '.join(found.resolved)}. " if found.resolved else "")
            + (
                f"Still blocking:\n{self._numbered(standing)}"
                if standing
                else "No blocking objections left."
            )
            + f" Verdict: {found.verdict}.",
            {"reply": found.model_dump()},
        )
        return found

    # ------------------------------------------------------------ between rounds

    async def _break(self, after: int) -> None:
        """Brainstorm, research, and simulate between round ``after`` and the
        next; whatever is new joins the evidence pack, numbered."""
        stage = f"After round {after}"
        self._on_stage(stage, 0)
        given = dict(self._last)
        storm = sort_ideas({seat: call.ideas for seat, call in given.items()})
        questions = merge_questions(
            {seat: call.open_questions for seat, call in given.items()},
            extra=storm.needs_data,
        )
        await self._say(
            "brainstorm",
            0,
            stage,
            _storm_text(storm, questions),
            {"brainstorm": storm.view(), "questions": questions},
        )
        found = Findings(problems=("research between rounds isn't available here",))
        if self._tools.look_up is not None:
            try:
                found = await self._tools.look_up(
                    questions, BUDGETS[self._config.depth]
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    "Trading: research after round {} failed: {}", after, error
                )
                found = Findings(
                    problems=(f"the research failed ({type(error).__name__})",)
                )
        fresh = new_findings(found, self._pack)
        await self._say(
            "research",
            0,
            stage,
            _research_text(questions, fresh),
            {"questions": questions, "findings": fresh.view()},
        )
        sims = await self._simulate_round(after, stage, storm.simulate)
        self._agenda = storm.argue
        added = await self._grow_pack(after, stage, fresh, sims)
        self.result.breaks.append(
            {
                "after_round": after,
                "questions": questions,
                "brainstorm": storm.view(),
                "searched": list(fresh.searched),
                "problems": list(fresh.problems),
                "added": list(added),
                "simulations": [result.view() for result in sims],
                "pack_id": self._pack.id if self._pack is not None else "",
            }
        )

    async def _simulate_round(
        self, after: int, stage: str, asked: tuple[str, ...]
    ) -> list[SimResult]:
        plans = plans_from(
            self._calls, weights=self._weights, cost_pct=self._tools.cost_pct
        )
        if not plans:
            await self._say(
                "simulation",
                0,
                stage,
                "No seat proposed a long plan, so there was nothing to simulate.",
            )
            return []
        runs = [
            plan
            for plan in (
                *plans,
                *variants(plans[0], atr=self._brief.tech.atr or 0.0, asked=asked),
            )
            if plan.label not in self._simulated
        ]
        if not runs:
            await self._say(
                "simulation",
                0,
                stage,
                "The plans haven't changed since they were simulated; the earlier "
                "results stand.",
            )
            return []
        self._simulated.update(plan.label for plan in runs)
        results = await run_simulations(
            runs,
            self._brief.daily,
            now=self._tools.clock(),
            seed_parts=(self._round, str(after)),
        )
        if not results:
            await self._say(
                "simulation",
                0,
                stage,
                "Too little price history to simulate (at least 60 past days are needed).",
            )
            return []
        self.result.simulations.extend(result.view() for result in results)
        await self._say(
            "simulation",
            0,
            stage,
            "\n".join(result.lines() for result in results),
            {"simulations": [result.view() for result in results]},
        )
        return results

    async def _grow_pack(
        self, after: int, stage: str, fresh: Findings, sims: list[SimResult]
    ) -> tuple[str, ...]:
        self._fresh = ()
        pack = self._pack
        if pack is None:
            return ()
        now = self._tools.clock()
        calcs = simulation_items(sims, now=now, symbol=self._brief.symbol)
        missing = [
            line
            for line in (
                f"Research between rounds couldn't finish: {problem}"
                for problem in fresh.problems
            )
            if line not in pack.missing
        ]
        if fresh.empty and not calcs and not missing:
            return ()
        before = pack.refs
        grown = extend_pack(
            pack,
            now=now,
            round_no=after,
            facts=fresh.facts,
            calcs=calcs,
            news=fresh.news,
            reading=fresh.reading,
            missing=missing,
        )
        self._pack = grown
        added = tuple(ref for ref, _ in grown.added if ref not in before)
        self._fresh = added
        self._brief = replace(self._brief, evidence_text=grown.text)
        if self._tools.keep_pack is not None:
            try:
                await self._tools.keep_pack(grown)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("Trading: couldn't keep pack {}: {}", grown.id, error)
        await self._say(
            "evidence",
            0,
            stage,
            f"Evidence pack {grown.id}: {len(added)} new numbered item(s) after "
            f"round {after}" + (f" ({', '.join(added[:12])})" if added else "") + ".",
            {
                "id": grown.id,
                "digest": grown.digest,
                "cutoff": grown.cutoff,
                "version": grown.version,
                "added": list(added),
            },
        )
        return added

    # ------------------------------------------------------------ closing

    async def _close(
        self,
        latest: dict[int, Forecast],
        guardian: Forecast | None,
        objections: list[Objection],
    ) -> None:
        self.result.objections = [o for o in objections if o.blocking]
        final: dict[int, Forecast] = dict(latest)
        if guardian is not None:
            final[4] = guardian
        # A checked call outranks a looser view from the same seat.
        final.update({seat: _forecast(call) for seat, call in self._calls.items()})
        if self._config.depth != "fast":
            closings = await self._each(
                {seat: self._closing(seat, final) for seat in sorted(final)}
            )
            self._take(closings)
            final.update({seat: _forecast(call) for seat, call in closings.items()})
        self.result.closing = final
        chance, buying = weighted(
            {seat: (view.p_up, view.stance) for seat, view in final.items()},
            self._weights,
        )
        self.result.consensus, self.result.buy_share = chance, buying
        await self._say(
            "consensus",
            0,
            "Closing",
            f"Weighted by track record: {chance:.0%} chance of a rise; "
            f"{buying:.0%} of the vote leans buy.",
            {
                "consensus": chance,
                "buy_share": buying,
                "weights": {str(seat): w for seat, w in self._weights.items()},
            },
        )
        self.result.decision = await self._settle(
            final, chance, buying, self.result.objections
        )

    async def _settle(
        self,
        views: Mapping[int, Forecast],
        chance: float,
        buying: float,
        objections: list[Objection],
    ) -> Decision:
        """The decision, then every check a buy must pass; a blocked order
        goes back once and the reply faces all of them again."""
        plan = await self._decide(views, chance, buying, objections)
        for attempt in (1, 2):
            if plan is None:
                return _hold(
                    "The Portfolio Manager's decision didn't pass its checks "
                    "twice, so nothing is ordered."
                )
            if plan.action != "long":
                return _decision(plan)
            info = await self._info_test(plan)
            if info.blocked:
                return await self._stop(
                    plan,
                    "The information stress test stopped the buy: "
                    + "; ".join(info.reasons),
                )
            review = await self._review(plan, info)
            if review is None:
                return await self._stop(
                    plan,
                    "The Risk Guardian's review couldn't be read, so nothing is "
                    "ordered.",
                )
            if review.verdict in {"rejected", "delayed"}:
                verb = "vetoed" if review.verdict == "rejected" else "delayed"
                return await self._stop(
                    plan,
                    f"The Risk Guardian {verb} the plan: "
                    + "; ".join(review.reasons[:3]),
                )
            factor = info.size_factor * (
                review.size_factor if review.verdict == "approved_smaller" else 1.0
            )
            decision = _decision(
                plan, size_factor=factor, confidence_cut=info.confidence_cut
            )
            challenge = await self._challenge(decision)
            self.result.challenge = challenge
            self.result.challenges += 1
            if challenge is None:
                return await self._stop(
                    plan, "The final challenge couldn't be read, so nothing is ordered."
                )
            if challenge.verdict == "clear":
                self.result.size_factor = factor
                return decision
            if attempt == 2:
                return await self._stop(
                    plan,
                    "The Risk Guardian blocked the Portfolio Manager's reply too: "
                    + challenge.point,
                )
            plan = await self._decide(
                views, chance, buying, objections, blocked=challenge.point
            )
        return _hold("No decision.")

    async def _stop(self, plan: PMDecision, reason: str) -> Decision:
        self.result.blocked = reason
        decision = _hold(reason, plan)
        await self._say(
            "decision",
            5,
            "Decision",
            f"Hold: {reason}",
            {"decision": decision.model_dump(), "blocked": reason},
        )
        return decision

    async def _decide(
        self,
        views: Mapping[int, Forecast],
        chance: float,
        buying: float,
        objections: list[Objection],
        *,
        blocked: str = "",
    ) -> PMDecision | None:
        weights = "\n".join(
            f"- {SEAT_NAMES[seat]} (vote weight x{self._weights.get(seat, 1.0):.2f}): {view.line()}"
            for seat, view in sorted(views.items())
        )
        sections = [
            "CLOSING FORECASTS:\n" + (weights or "- none"),
            f"WEIGHTED CONSENSUS: {chance:.0%} chance of a rise; {buying:.0%} of the vote leans buy.",
            (
                "UNRESOLVED BLOCKING OBJECTIONS (answer each by number):\n"
                + self._numbered(objections)
            )
            if objections
            else "No blocking objections are left.",
            self._price_line(),
            self._limits_text,
        ]
        if blocked:
            sections.append(
                f"THE RISK GUARDIAN BLOCKED YOUR ORDER: {blocked}\n"
                "Fix the order (size, stop, entry, or target), or hold."
            )
        task = (
            "Decide: long (buy to open), sell (only if we hold it), hold, or "
            "no_trade. For a long: an entry range within 5% of the price (a market "
            "order's range must include the price; a limit buy pays at most "
            "entry_high, no more than 2% over the price), order_type market or "
            "limit, the stop-loss below a real support and at least 1 ATR from "
            "the price, a realistic take-profit, holding_days, and size_pct (of "
            "the most the risk rules allow). Cite the supporting and opposing "
            "evidence numbers, say what would prove the decision wrong, and answer "
            "every unresolved blocking objection by its number."
        )
        view = self._view()
        keys = PM_KEYS.replace("PACK", view.id)
        price, held = self._brief.price, self._held
        shorts = self._tools.shorts_allowed
        needed = len(objections)

        def check(found: PMDecision) -> list[str]:
            return check_decision(
                found,
                pack=view,
                price=price,
                held=held,
                shorts_allowed=shorts,
                order_types=ENTRY_ORDERS,
                blocking=needed,
            )

        stage = "PM reply" if blocked else "Decision"
        found = await self._checked(
            5,
            stage,
            self._prompt(5, *sections, task=task, keys=keys),
            PMDecision,
            check=check,
            keys=keys,
            tokens=self._tokens("decision"),
        )
        if found is None:
            await self._say(
                "decision",
                5,
                stage,
                "Hold: the Portfolio Manager's decision didn't pass its checks twice.",
            )
            return None
        self.result.plan = found
        decision = _decision(found)
        await self._say(
            "decision",
            5,
            stage,
            decision.line(),
            {"decision": decision.model_dump(), "plan": found.model_dump()},
        )
        return found

    async def _info_test(self, plan: PMDecision) -> InfoStress:
        refs = load_bearing(plan.supporting, self._calls, direction="long")
        latest: QuoteSnapshot | None = None
        if self._tools.latest is not None:
            try:
                latest = await self._tools.latest()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.info("Trading: the latest price couldn't be read: {}", error)
        data = self._tools.data
        if self._pack is None:
            checks = [
                ItemCheck(ref, "fails", "there is no evidence pack") for ref in refs
            ]
        else:
            checks = check_items(
                refs,
                self._pack,
                now=self._tools.clock(),
                latest=latest,
                tolerance_pct=data.conflict_pct.get(self._tools.profile, 0.5),
                news_max_age_s=data.news_max_age_days * 86_400,
            )
        attackers = [seat for seat in (2, 4) if self._seat(seat).on]
        answers = await asyncio.gather(
            *(self._attack_items(seat, plan, refs) for seat in attackers),
            return_exceptions=True,
        )
        attacks: dict[int, EvidenceAttack | None] = {}
        for seat, answer in zip(attackers, answers, strict=True):
            if isinstance(answer, asyncio.CancelledError):
                raise answer
            if isinstance(answer, BaseException):
                logger.warning("Trading: seat {} failed its attack: {}", seat, answer)
                attacks[seat] = None
            else:
                attacks[seat] = answer
        info = combine(checks, attacks)
        self.result.info_test = info
        await self._say(
            "info_test",
            0,
            "Information stress test",
            info.lines(),
            {"info_test": info.view()},
        )
        return info

    async def _attack_items(
        self, seat: int, plan: PMDecision, refs: list[str]
    ) -> EvidenceAttack | None:
        pack = self._pack
        items = "\n".join(
            pack.line(ref) if pack is not None else f"[{ref}]" for ref in refs
        )
        prompt = self._prompt(
            seat,
            f"THE PORTFOLIO MANAGER'S BUY: {_decision(plan).line()}",
            "ITEMS TO TEST (the evidence this buy rests on):\n" + items,
            task=(
                "Evidence attack. Try to knock down each listed item: is it true, "
                "current, from a reliable source, confirmed, and does it really "
                "support this buy? Judge every listed item, and only those: holds, "
                "weak, or fails, with why (required for weak and fails). Then say "
                "whether you would still buy without the strongest item."
            ),
            keys=ATTACK_KEYS,
        )
        found = await self._checked(
            seat,
            "Evidence attack",
            prompt,
            EvidenceAttack,
            check=lambda attack: check_attack(attack, wanted=refs),
            keys=ATTACK_KEYS,
            tokens=self._tokens("attack"),
        )
        if found is not None:
            await self._say(
                "evidence_attack",
                seat,
                "Information stress test",
                "; ".join(
                    f"[{item.id}] {item.verdict}"
                    + (f": {item.why}" if item.why else "")
                    for item in found.items[:8]
                )
                + (
                    " | Would still buy without the strongest item."
                    if found.still_buy_without_strongest
                    else " | Would not buy without the strongest item."
                ),
                {"attack": found.model_dump()},
            )
        return found

    async def _review(
        self, plan: PMDecision, info: InfoStress
    ) -> GuardianReview | None:
        simulated = await self._simulate_decision(plan)
        view = self._view()
        keys = REVIEW_KEYS.replace("PACK", view.id)
        prompt = self._prompt(
            4,
            "THE DRAFT PLAN (built by FCC's code from the Portfolio Manager's "
            "decision):\n" + self._draft(plan, info),
            "SIMULATION OF THIS EXACT PLAN (past price behaviour, not a "
            "prediction):\n"
            + (
                simulated.lines()
                if simulated is not None
                else "Not enough price history to simulate it."
            ),
            "INFORMATION STRESS TEST:\n" + info.lines(),
            task=(
                "Risk review. Approve this exact plan, approve it smaller "
                "(size_factor below 1), delay it, or reject it (a veto). Give "
                "reasons citing [ids], the checks you made, and up to 2 extra bad "
                "scenarios (a name and how far the price falls against us, 0-90%) "
                "for the stress test."
            ),
            keys=keys,
        )
        found = await self._checked(
            4,
            "Risk review",
            prompt,
            GuardianReview,
            check=lambda review: check_review(review, pack=view),
            keys=keys,
            tokens=self._tokens("review"),
        )
        if found is None:
            return None
        self.result.review = found
        await self._say(
            "guardian_review",
            4,
            "Risk review",
            found.verdict.replace("_", " ").capitalize()
            + (
                f" (size x{found.size_factor:.2f})"
                if found.verdict == "approved_smaller"
                else ""
            )
            + ": "
            + "; ".join(found.reasons[:3])
            + (
                " | Scenarios: "
                + "; ".join(f"{s.name} -{s.fall_pct:g}%" for s in found.scenarios)
                if found.scenarios
                else ""
            ),
            {"review": found.model_dump()},
        )
        return found

    async def _simulate_decision(self, plan: PMDecision) -> SimResult | None:
        price = self._brief.price
        entry = (plan.entry_high or price) if plan.order_type == "limit" else price
        stop, target = plan.stop_loss or 0.0, plan.take_profit or 0.0
        if not stop < entry < target:
            return None
        found = await run_simulations(
            [
                Plan(
                    entry=entry,
                    stop=stop,
                    target=target,
                    holding_days=plan.holding_days or 5,
                    trailing_pct=plan.trailing_stop_pct,
                    cost_pct=self._tools.cost_pct,
                    label="the Portfolio Manager's plan",
                )
            ],
            self._brief.daily,
            now=self._tools.clock(),
            seed_parts=(self._round, "decision"),
        )
        if not found:
            return None
        self.result.simulations.append(found[0].view())
        return found[0]

    def _draft(self, plan: PMDecision, info: InfoStress) -> str:
        brief = self._brief
        price, atr = brief.price, brief.tech.atr or 0.0
        entry = (plan.entry_high or price) if plan.order_type == "limit" else price
        stop, target = plan.stop_loss or 0.0, plan.take_profit or 0.0
        risk, reward = entry - stop, target - entry
        ratio = reward / risk if risk > 0 else 0.0
        lines = [
            f"Long {brief.symbol}: {plan.order_type} entry "
            f"{plan.entry_low or 0:g}-{plan.entry_high or 0:g} (fills near "
            f"{entry:g}), stop {stop:g} ({(stop / entry - 1) * 100:+.2f}%"
            + (f", {risk / atr:.1f} ATR" if atr > 0 else "")
            + f"), target {target:g} ({(target / entry - 1) * 100:+.2f}%), "
            f"reward-to-risk {ratio:.2f}, hold up to {plan.holding_days or 5} days.",
            f"Size: {plan.size_pct or 0:g}% of the most the limits allow; after the "
            f"information stress test x{info.size_factor:.2f} = "
            f"{(plan.size_pct or 0) * info.size_factor:.1f}%. The hard limits in code cap "
            "it further.",
            f"Confidence {plan.confidence}/100"
            + (
                f", minus {info.confidence_cut * 100:.0f} points for weak evidence"
                if info.confidence_cut
                else ""
            )
            + f"; chance of a rise {plan.p_up:.0%}.",
        ]
        return "\n".join(lines)

    async def _challenge(self, decision: Decision) -> Challenge | None:
        prompt = self._prompt(
            4,
            f"THE PORTFOLIO MANAGER'S ORDER: {decision.line()}",
            task=(
                "Final challenge. Is there one specific thing wrong with this exact "
                "order (its size, stop placement, entry, timing, or target)? If so, "
                "block it and say what; otherwise clear it."
            ),
            keys=FINAL_KEYS,
        )
        found = await self._checked(
            4,
            "Final challenge",
            prompt,
            FinalCheck,
            check=check_final,
            keys=FINAL_KEYS,
            tokens=self._tokens("final_challenge"),
        )
        if found is None:
            return None
        challenge = Challenge(verdict=found.verdict, point=found.point)
        await self._say(
            "final_challenge",
            4,
            "Final challenge",
            ("Blocked: " if found.verdict == "block" else "Cleared. ") + found.point,
            {"challenge": challenge.model_dump()},
        )
        return challenge


def _title(number: int, rounds: int) -> str:
    parts: list[str] = []
    if number == 1:
        parts.append("opening calls, comparison, cross-examination")
    elif number < rounds or rounds == 2:
        parts.append("updated calls")
    if number == min(2, rounds):
        parts.append("pre-mortem, rebuttals, and replies")
    elif 1 < number < rounds:
        parts.append("standing objections answered again")
    if number == rounds:
        parts.append(
            "closing calls, decision, information stress test, risk review, "
            "final challenge"
        )
    return "; ".join(parts)


def _storm_text(storm: Brainstorm, questions: list[str]) -> str:
    rows = [
        f"Brainstorm: {storm.count} idea(s) after removing repeats "
        f"(of {storm.raw} given)."
    ]
    for name, ideas in (
        ("Needs data (researched now)", storm.needs_data),
        ("To simulate", storm.simulate),
        ("To argue next round", storm.argue),
    ):
        if ideas:
            rows.append(f"{name}: " + "; ".join(ideas))
    rows.append(
        "Open questions to look up: " + ("; ".join(questions) if questions else "none")
    )
    return "\n".join(rows)


def _research_text(questions: list[str], found: Findings) -> str:
    rows = [
        f"Research: looked up {len(found.searched)} question(s); found "
        f"{len(found.news)} new dated stor{'y' if len(found.news) == 1 else 'ies'}, "
        f"{len(found.reading)} new piece(s) of web reading, and "
        f"{len(found.facts)} fresh price(s)."
    ]
    if found.searched:
        rows.append("Searched: " + "; ".join(found.searched))
    elif questions:
        rows.append("No web search ran for: " + "; ".join(questions))
    if found.problems:
        rows.append("Couldn't: " + "; ".join(found.problems))
    return "\n".join(rows)


def _call_line(call: SeatCall) -> str:
    plan = ""
    if call.direction in {"long", "short"} and call.stop_loss and call.take_profit:
        plan = (
            f" (entry {call.entry_low or 0:g}-{call.entry_high or 0:g}, stop "
            f"{call.stop_loss:g}, target {call.take_profit:g}, "
            f"{call.holding_days or 0} days)"
        )
    cites = " ".join(f"[{ref}]" for ref in call.evidence[:6])
    changed = f" | Changed: {call.changed}" if call.changed else ""
    return (
        f"{call.direction.replace('_', ' ')} · {call.p_up:.0%} up · confidence "
        f"{call.confidence}/100{plan} — {call.main_reason}"
        + (f" {cites}" if cites else "")
        + changed
    )


def _forecast(call: SeatCall) -> Forecast:
    """A checked call as the forecast the consensus and the scoring use."""
    return Forecast(
        stance=STANCES[call.direction],
        p_up=call.p_up,
        horizon_days=min(60, call.holding_days or 5),
        expected_move_pct=call.expected_move_pct or 0.0,
        p_target=call.p_target,
        confidence=call.confidence / 100,
        reasons=[call.main_reason],
        risks=call.prove_wrong[:2],
    )


def _decision(
    plan: PMDecision, *, size_factor: float = 1.0, confidence_cut: float = 0.0
) -> Decision:
    """The checked decision as the order plan the desk sizes and places: a
    limit buy pays at most the top of the entry range; the size and the
    confidence carry the cuts from the checks (never an increase)."""
    action = {"long": "buy", "sell": "sell"}.get(plan.action, "hold")
    limit = action == "buy" and plan.order_type == "limit"
    return Decision.model_construct(
        action=action,
        order_type="limit" if limit else "market",
        limit_price=plan.entry_high if limit else None,
        stop_loss=plan.stop_loss,
        take_profit=plan.take_profit,
        size_pct=round((plan.size_pct or 0.0) * min(1.0, size_factor), 4),
        horizon_days=max(1, min(60, plan.holding_days or 5)),
        p_up=plan.p_up,
        p_target=plan.p_target,
        confidence=max(0.0, round(plan.confidence / 100 - confidence_cut, 4)),
        rationale=plan.rationale,
        answers=list(plan.answers),
    )


def _hold(reason: str, plan: PMDecision | None = None) -> Decision:
    """Hold, keeping the Portfolio Manager's forecast (it is still scored)."""
    if plan is None:
        return Decision.model_construct(action="hold", rationale=reason)
    return Decision.model_construct(
        action="hold",
        horizon_days=max(1, min(60, plan.holding_days or 5)),
        p_up=plan.p_up,
        p_target=plan.p_target,
        confidence=plan.confidence / 100,
        rationale=reason,
    )


def _mean_up(views: Mapping[int, Forecast], seats: list[int]) -> float:
    chances = [views[seat].p_up for seat in seats if seat in views]
    return sum(chances) / len(chances) if chances else 0.5


def _average_calls(calls: list[SeatCall]) -> SeatCall:
    """Self-consistency: several tries at the same call. The direction most
    tries share (more than half) wins, with the average of those tries'
    chances; without a majority the call is no trade."""
    directions = [call.direction for call in calls]
    top = max(set(directions), key=directions.count)
    if directions.count(top) * 2 <= len(directions):
        chance = statistics.fmean(call.p_up for call in calls)
        closest = min(calls, key=lambda call: abs(call.p_up - chance))
        return closest.model_copy(
            update={
                "direction": "no_trade",
                "p_up": round(chance, 3),
                "confidence": round(statistics.fmean(c.confidence for c in calls)),
            }
        )
    same = [call for call in calls if call.direction == top]
    chance = statistics.fmean(call.p_up for call in same)
    closest = min(same, key=lambda call: abs(call.p_up - chance))
    targets = [call.p_target for call in same if call.p_target is not None]
    return closest.model_copy(
        update={
            "p_up": round(chance, 3),
            "confidence": round(statistics.fmean(c.confidence for c in same)),
            "p_target": round(statistics.fmean(targets), 3) if targets else None,
        }
    )
