"""The debate: forecast, cross-examine, attack, rebut, close, decide, challenge.

1. Opening: the three analysts forecast on their own, blind to each other,
   so nobody anchors on the first voice (at max depth each asks three times
   and averages: self-consistency).
2. Cross-examination: each analyst reads the other two, agrees and disagrees
   point by point, asks one question, and revises.
3. Pre-mortem: the Risk Guardian assumes the trade lost money, says how, and
   aims objections at each analyst, marking the ones that must block.
4. Rebuttals: the analysts answer what was aimed at them and the Guardian
   replies, round after round (1, 2, or 4 by depth) until the views settle.
5. Closing: seats 1-4 give their final forecasts.
6. Decision: the Portfolio Manager weighs the closings by track record,
   answers every unresolved blocking objection by name, and decides.
7. Final challenge: the Guardian gets one last word on the actual order; a
   block sends it back to the Portfolio Manager for one reply.
Every turn goes to the live feed as it happens.
"""

import asyncio
import statistics
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from loguru import logger

from free_claude_code.core.json_types import JsonObject

from ..llm import StudioLLMError
from .briefing import Briefing
from .config import OPENING_SAMPLES, REBUTTAL_ROUNDS, DeskConfig, SeatConfig
from .forecasts import weighted
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
    MacroView,
    Objection,
    PreMortem,
    Rebuttal,
    Researched,
    Think,
    ask_json,
)

CONVERGED_MOVE = 0.03
"""Rebuttals stop once the analysts' average chance of a rise moves less."""

TOKENS = {
    "opening": 500,
    "cross_exam": 500,
    "pre_mortem": 700,
    "rebuttal": 350,
    "guardian_reply": 500,
    "closing": 350,
    "decision": 700,
    "final_challenge": 250,
}

OBJECTION_KEYS = '{"target": 1-3, "point": "...", "blocking": true|false}'
DECISION_KEYS = (
    '"action": "buy|sell|hold", "order_type": "market|limit", "limit_price": '
    'number or null, "stop_loss": number or null, "take_profit": number or null, '
    '"size_pct": 0-100 (share of the most the risk rules allow), "horizon_days": '
    '1-20, "p_up": 0-1, "p_target": 0-1 (chance the take-profit comes before the '
    'stop), "confidence": 0-1, "rationale": "2-3 sentences", "answers": '
    '[{"point": "objection number", "answer": "..."}]'
)


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
    ) -> None:
        self._think = think
        self._feed = feed
        self._config = config
        self._brief = briefing
        self._round = round_id
        self._weights = dict(weights)
        self._limits_text = limits_text
        self._on_stage = on_stage or (lambda stage, seat: None)
        self.result = DebateResult(weights=dict(weights))

    # ------------------------------------------------------------ plumbing

    def _seat(self, number: int) -> SeatConfig:
        return self._config.seat(number)

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

    async def _ask[M: Forecast | Decision | Challenge](
        self,
        seat: int,
        stage: str,
        prompt: str,
        model: type[M],
        keys: str,
        tokens: int,
        *,
        temperature_step: float = 0.0,
    ) -> M | None:
        self._on_stage(stage, seat)
        config = self._seat(seat)
        if temperature_step:
            config = config.model_copy(
                update={"temperature": min(1.5, config.temperature + temperature_step)}
            )
        try:
            found = await ask_json(
                self._think, config, prompt, model, max_tokens=tokens, keys=keys
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
        analysts = [seat for seat in (1, 2, 3) if self._seat(seat).on]
        await self._say(
            "briefing",
            0,
            "Briefing",
            f"Briefing for {self._brief.symbol}: {self._brief.tech.trend} trend, "
            f"{self._brief.regime.label}"
            + (f"; {self._brief.base.lines()}" if self._brief.base is not None else ""),
            {"briefing": self._brief.view()},
        )
        latest: dict[int, Forecast] = await self._each(
            {seat: self._opening(seat, OPENING_SAMPLES[depth]) for seat in analysts}
        )
        self.result.openings = dict(latest)
        if depth != "fast" and len(latest) >= 2:
            latest.update(
                await self._each(
                    {seat: self._cross_exam(seat, latest) for seat in latest}
                )
            )
        premortem = await self._premortem(latest)
        guardian: Forecast | None = premortem
        objections = list(premortem.objections) if premortem is not None else []
        limit = REBUTTAL_ROUNDS[depth]
        while self.result.rebuttal_rounds < limit:
            aimed = {o.target for o in objections if o.target in latest}
            if not aimed:
                break
            self.result.rebuttal_rounds += 1
            number = self.result.rebuttal_rounds
            before = _mean_up(latest, analysts)
            replies = await self._each(
                {
                    seat: self._rebuttal(seat, number, limit, objections, latest)
                    for seat in sorted(aimed)
                }
            )
            latest.update(replies)
            reply = await self._guardian_reply(
                number, limit, objections, replies, latest
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
                    f"Rebuttal {number}/{limit}",
                    f"The seats have settled (average chance of a rise moved "
                    f"{moved:.2f}); moving to closing statements.",
                )
                break
        self.result.objections = [o for o in objections if o.blocking]
        final: dict[int, Forecast] = dict(latest)
        if guardian is not None:
            final[4] = guardian
        if depth != "fast":
            closers = [*latest, 4] if guardian is not None else list(latest)
            final.update(
                await self._each({seat: self._closing(seat, final) for seat in closers})
            )
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
        decision = await self._decide(final, chance, buying, self.result.objections)
        if decision is not None and decision.action == "buy":
            challenge = await self._challenge(decision)
            self.result.challenge = challenge
            if challenge is not None and challenge.verdict == "block":
                decision = await self._decide(
                    final,
                    chance,
                    buying,
                    self.result.objections,
                    blocked=challenge.point,
                )
        self.result.decision = decision
        return self.result

    # ------------------------------------------------------------ stages

    async def _opening(self, seat: int, samples: int) -> Forecast | None:
        model: type[Forecast] = (
            Researched if seat == 2 else MacroView if seat == 3 else Forecast
        )
        keys = FORECAST_KEYS + (
            ', "next_earnings": "YYYY-MM-DD or empty"'
            if seat == 2
            else ', "events": [{"name": "...", "date": "YYYY-MM-DD"}]'
            if seat == 3
            else ""
        )
        prompt = self._prompt(
            seat,
            task=(
                f"Opening forecast. Give your own independent view of "
                f"{self._brief.symbol} from {ANGLES[seat]}. The other seats "
                "haven't spoken; don't guess what they think."
                + (
                    " Also give the next earnings or results date if your notes say."
                    if seat == 2
                    else " Also list dated events (rate decisions, inflation data, "
                    "token unlocks) in the next weeks if your notes say."
                    if seat == 3
                    else ""
                )
            ),
            keys=keys,
        )
        views = [
            view
            for view in await asyncio.gather(
                *(
                    self._ask(
                        seat,
                        "Opening",
                        prompt,
                        model,
                        keys,
                        TOKENS["opening"],
                        temperature_step=0.25 * index,
                    )
                    for index in range(samples)
                )
            )
            if view is not None
        ]
        if not views:
            return None
        view = _average(views) if len(views) > 1 else views[0]
        if isinstance(view, Researched) and view.next_earnings:
            self.result.earnings = view.next_earnings
        if isinstance(view, MacroView) and view.events:
            self.result.events = list(view.events)
        note = f" (average of {len(views)} tries)" if len(views) > 1 else ""
        await self._say(
            "opening",
            seat,
            "Opening",
            view.line() + note,
            {"forecast": view.model_dump()},
        )
        return view

    async def _cross_exam(
        self, seat: int, views: Mapping[int, Forecast]
    ) -> Forecast | None:
        mine = views[seat]
        prompt = self._prompt(
            seat,
            f"YOUR OPENING: {mine.line()}",
            "THE OTHER ANALYSTS SAID:\n" + self._views(views, skip=seat),
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
        number: int,
        limit: int,
        objections: list[Objection],
        views: Mapping[int, Forecast],
    ) -> Forecast | None:
        aimed = [o for o in objections if o.target == seat]
        stage = f"Rebuttal {number}/{limit}"
        prompt = self._prompt(
            seat,
            f"YOUR CURRENT VIEW: {views[seat].line()}",
            "THE RISK GUARDIAN'S OBJECTIONS TO YOU:\n" + self._numbered(aimed),
            "THE OTHER SEATS NOW:\n" + self._views(views, skip=seat),
            task=(
                f"{stage}. Answer each objection: defend it with evidence from the "
                "briefing, or concede it honestly. Then give your updated forecast."
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
        number: int,
        limit: int,
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
        stage = f"Guardian reply {number}/{limit}"
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

    async def _closing(
        self, seat: int, views: Mapping[int, Forecast]
    ) -> Forecast | None:
        prompt = self._prompt(
            seat,
            "WHERE THE DEBATE ENDED:\n" + self._views(views),
            task=(
                "Closing statement. Having heard everything, give your final "
                "forecast for this symbol."
            ),
            keys=FORECAST_KEYS,
        )
        found = await self._ask(
            seat, "Closing", prompt, Forecast, FORECAST_KEYS, TOKENS["closing"]
        )
        if found is not None:
            await self._say(
                "closing",
                seat,
                "Closing",
                found.line(),
                {"forecast": found.model_dump()},
            )
        return found

    async def _decide(
        self,
        views: Mapping[int, Forecast],
        chance: float,
        buying: float,
        objections: list[Objection],
        *,
        blocked: str = "",
    ) -> Decision | None:
        brief = self._brief
        weights = "\n".join(
            f"- {SEAT_NAMES[seat]} (vote weight x{self._weights.get(seat, 1.0):.2f}): {view.line()}"
            for seat, view in sorted(views.items())
        )
        held = (
            "We hold it, so sell (to close) is possible."
            if brief.held
            else "We don't hold it."
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
            f"PRICE NOW {brief.price:g}; ATR {brief.tech.atr or 0:g}. {held}",
            self._limits_text,
        ]
        if blocked:
            sections.append(
                f"THE RISK GUARDIAN BLOCKED YOUR ORDER: {blocked}\n"
                "Fix the order (size, stop, entry, or target) or hold."
            )
        task = (
            "Decide: buy (long only), sell (only if we hold it), or hold. For a buy, "
            "set the stop-loss below a real support and at least 1 ATR from the "
            "price, a realistic take-profit, market or limit entry, and size_pct "
            "(0-100 of the most the risk rules allow). Answer every unresolved "
            "blocking objection by its number."
        )
        stage = "PM reply" if blocked else "Decision"
        prompt = self._prompt(5, *sections, task=task, keys=DECISION_KEYS)
        found = await self._ask(
            5, stage, prompt, Decision, DECISION_KEYS, TOKENS["decision"]
        )
        if found is None:
            return None
        problem = _plan_problem(found, brief.price, held=brief.held is not None)
        if (
            problem is None
            and found.action == "buy"
            and len(found.answers) < len(objections)
        ):
            problem = (
                f"you answered {len(found.answers)} of {len(objections)} blocking "
                "objections; answer every one by number"
            )
        if problem is not None:
            again = await self._ask(
                5,
                stage,
                prompt + f"\n\nYOUR LAST ANSWER WAS NOT USABLE: {problem}. Try again.",
                Decision,
                DECISION_KEYS,
                TOKENS["decision"],
            )
            if again is not None:
                found = again
                problem = _plan_problem(found, brief.price, held=brief.held is not None)
                if (
                    problem is None
                    and found.action == "buy"
                    and len(found.answers) < len(objections)
                ):
                    problem = "blocking objections were left unanswered"
            if problem is not None:
                await self._say(
                    "decision", 5, stage, f"Hold: the plan wasn't usable ({problem})."
                )
                return found.model_copy(
                    update={
                        "action": "hold",
                        "rationale": f"Plan not usable: {problem}",
                    }
                )
        await self._say(
            "decision", 5, stage, found.line(), {"decision": found.model_dump()}
        )
        return found

    async def _challenge(self, decision: Decision) -> Challenge | None:
        prompt = self._prompt(
            4,
            f"THE PORTFOLIO MANAGER'S ORDER: {decision.line()}",
            task=(
                "Final challenge. Is there one specific thing wrong with this exact "
                "order (its size, stop placement, entry, timing, or target)? If so, "
                "block it and say what; otherwise clear it."
            ),
            keys='"verdict": "clear|block", "point": "..."',
        )
        found = await self._ask(
            4,
            "Final challenge",
            prompt,
            Challenge,
            '"verdict": "clear|block", "point": "..."',
            TOKENS["final_challenge"],
        )
        if found is not None:
            await self._say(
                "final_challenge",
                4,
                "Final challenge",
                ("Blocked: " if found.verdict == "block" else "Cleared. ")
                + found.point,
                {"challenge": found.model_dump()},
            )
        return found


def _mean_up(views: Mapping[int, Forecast], seats: list[int]) -> float:
    chances = [views[seat].p_up for seat in seats if seat in views]
    return sum(chances) / len(chances) if chances else 0.5


def _average(views: list[Forecast]) -> Forecast:
    """Self-consistency: the average of several tries at the same forecast."""
    chance = sum(v.p_up for v in views) / len(views)
    targets = [v.p_target for v in views if v.p_target is not None]
    stances = [v.stance for v in views]
    stance = max(set(stances), key=stances.count)
    if stances.count(stance) * 2 <= len(stances):
        stance = "hold"
    closest = min(views, key=lambda v: abs(v.p_up - chance))
    return closest.model_copy(
        update={
            "p_up": round(chance, 3),
            "p_target": round(sum(targets) / len(targets), 3) if targets else None,
            "confidence": round(sum(v.confidence for v in views) / len(views), 3),
            "expected_move_pct": round(
                sum(v.expected_move_pct for v in views) / len(views), 2
            ),
            "horizon_days": int(statistics.median(v.horizon_days for v in views)),
            "stance": stance,
        }
    )


def _plan_problem(decision: Decision, price: float, *, held: bool) -> str | None:
    if decision.action == "sell" and not held:
        return "sell is only for something we hold"
    if decision.action != "buy":
        return None
    if decision.stop_loss is None:
        return "a buy needs a stop_loss below the price"
    if decision.stop_loss >= price:
        return f"the stop_loss ({decision.stop_loss:g}) must be below the price ({price:g})"
    if decision.take_profit is not None and decision.take_profit <= price:
        return f"the take_profit ({decision.take_profit:g}) must be above the price ({price:g})"
    if decision.order_type == "limit" and (
        decision.limit_price is None or decision.limit_price > price * 1.02
    ):
        return "a limit order needs a limit_price at or below the price"
    if decision.size_pct <= 0:
        return "size_pct must be above 0 for a buy"
    return None
