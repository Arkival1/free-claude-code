"""What the desk does between debate rounds: research, brainstorming, and
simulating.

- Brainstorming: each seat's answer carries up to three ideas (a risk nobody
  raised, another explanation for the move, another way to do the trade:
  wait, a lower limit entry, a wider stop, half the size, no trade). Code
  removes repeats and sorts them: ideas that need data go to the research,
  ideas to simulate go to the simulator, and ideas to argue become the next
  round's agenda.
- Research: each seat's answer also carries up to two open questions ("what
  would change my mind"). Code merges them with the ideas that need data,
  keeps the three most asked, and looks them up: fresh dated news, a few web
  searches and page reads (bounded per break), and the latest prices. What
  is new joins the evidence pack as numbered items marked with the round;
  undated web text stays reading, never a fact.
- Simulating: the leading plans and up to three variants run through price
  paths rebuilt from the asset's own past (simulate.py), with a recorded
  seed; the results join the pack as numbered calculations, labelled as
  past behaviour, not a prediction.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from .contract import Idea, SeatCall
from .evidence import EvidencePack
from .indicators import Bar
from .information import InfoItem, NewsItem, words_of
from .log import SEAT_NAMES
from .simulate import Plan, SimResult, seed_for, simulate

MAX_QUESTIONS = 3
MAX_IDEAS = 9
MAX_AGENDA = 5
MAX_PLANS = 2
MAX_VARIANTS = 3
SAME_TEXT = 0.6
"""Two questions or ideas sharing this share of their words are one."""
MAX_QUERY = 160


@dataclass(frozen=True, slots=True)
class Budget:
    """How much looking up one break may do."""

    searches: int
    pages: int


BUDGETS: dict[str, Budget] = {
    "fast": Budget(1, 0),
    "balanced": Budget(3, 1),
    "max": Budget(3, 2),
}


@dataclass(frozen=True, slots=True)
class Findings:
    """What a look-up found, before it is numbered into the pack."""

    facts: tuple[InfoItem, ...] = ()
    news: tuple[NewsItem, ...] = ()
    reading: tuple[InfoItem, ...] = ()
    problems: tuple[str, ...] = ()
    searched: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.facts or self.news or self.reading)

    def view(self) -> JsonObject:
        return {
            "facts": [item.view() for item in self.facts],
            "news": [story.view() for story in self.news],
            "reading": [item.view() for item in self.reading],
            "problems": list(self.problems),
            "searched": list(self.searched),
        }


type LookUp = Callable[[Sequence[str], Budget], Awaitable[Findings]]
"""Look up these questions within this budget."""


@dataclass(frozen=True, slots=True)
class Brainstorm:
    needs_data: tuple[str, ...] = ()
    simulate: tuple[str, ...] = ()
    argue: tuple[str, ...] = ()
    raw: int = 0
    """How many ideas the seats gave before repeats were removed."""

    @property
    def count(self) -> int:
        return len(self.needs_data) + len(self.simulate) + len(self.argue)

    def view(self) -> JsonObject:
        return {
            "needs_data": list(self.needs_data),
            "simulate": list(self.simulate),
            "argue": list(self.argue),
            "raw": self.raw,
        }


def _clean(text: str) -> str:
    return " ".join(text.replace("\x00", " ").split())


def _same(first: set[str], second: set[str]) -> bool:
    if not first or not second:
        return first == second
    return len(first & second) / len(first | second) >= SAME_TEXT


def _merge(groups: Sequence[tuple[int, str]]) -> list[tuple[str, int]]:
    """(seat, text) pairs → (text, how many seats said it), near-repeats
    folded into the first wording, most asked first, then first asked."""
    kept: list[tuple[str, set[str], set[int]]] = []
    for seat, raw in groups:
        text = _clean(raw)
        if not text:
            continue
        words = words_of(text)
        for _, known, seats in kept:
            if _same(words, known):
                seats.add(seat)
                break
        else:
            kept.append((text, words, {seat}))
    order = sorted(range(len(kept)), key=lambda index: (-len(kept[index][2]), index))
    return [(kept[index][0], len(kept[index][2])) for index in order]


def merge_questions(
    asked: Mapping[int, Sequence[str]], *, extra: Sequence[str] = ()
) -> list[str]:
    """The seats' open questions and the ideas that need data, merged, at
    most ``MAX_QUESTIONS``."""
    pairs = [(seat, text) for seat, texts in sorted(asked.items()) for text in texts]
    pairs += [(0, text) for text in extra]
    return [text for text, _ in _merge(pairs)][:MAX_QUESTIONS]


def sort_ideas(ideas: Mapping[int, Sequence[Idea]]) -> Brainstorm:
    """Repeats removed (across seats and kinds), at most ``MAX_IDEAS``, then
    sorted by kind."""
    pairs = [(seat, idea) for seat, found in sorted(ideas.items()) for idea in found]
    kinds: dict[str, str] = {}
    for _, idea in pairs:
        kinds.setdefault(_clean(idea.idea), idea.kind)
    merged = _merge([(seat, idea.idea) for seat, idea in pairs])[:MAX_IDEAS]
    buckets: dict[str, list[str]] = {"needs_data": [], "simulate": [], "argue": []}
    for text, _ in merged:
        buckets[kinds.get(text, "argue")].append(text)
    return Brainstorm(
        needs_data=tuple(buckets["needs_data"]),
        simulate=tuple(buckets["simulate"]),
        argue=tuple(buckets["argue"][:MAX_AGENDA]),
        raw=len(pairs),
    )


def query_for(subject: str, question: str) -> str:
    """A web search for one question, bounded and on one line."""
    text = _clean(f"{subject} {question}")
    return text[:MAX_QUERY]


def new_findings(found: Findings, pack: EvidencePack | None) -> Findings:
    """Only what the pack doesn't have yet: stories by their wording, web
    text by its link or text, prices by source, time, and value."""
    if pack is None:
        return found
    stories = {story.key for story in pack.news}
    links = {item.source_id for item in pack.reading if item.source_id}
    texts = {str(item.value) for item in pack.reading}
    facts = {(item.label, item.as_of, item.value) for item in pack.items}
    news: list[NewsItem] = []
    for story in found.news:
        if story.usable and story.key not in stories:
            stories.add(story.key)
            news.append(story)
    reading: list[InfoItem] = []
    for item in found.reading:
        if (item.source_id and item.source_id in links) or str(item.value) in texts:
            continue
        links.add(item.source_id)
        texts.add(str(item.value))
        reading.append(item)
    fresh = [
        item
        for item in found.facts
        if (item.label, item.as_of, item.value) not in facts
    ]
    missing = set(pack.missing)
    return Findings(
        facts=tuple(fresh),
        news=tuple(news),
        reading=tuple(reading),
        problems=tuple(problem for problem in found.problems if problem not in missing),
        searched=found.searched,
    )


# ---------------------------------------------------------------- simulating


def plans_from(
    calls: Mapping[int, SeatCall],
    *,
    weights: Mapping[int, float],
    cost_pct: float,
) -> list[Plan]:
    """The seats' long plans, the most confident (by track record) first,
    without repeats; at most ``MAX_PLANS``."""
    ranked = sorted(
        (
            (call.confidence * weights.get(seat, 1.0), seat, call)
            for seat, call in calls.items()
            if call.direction == "long"
            and None
            not in (
                call.entry_low,
                call.entry_high,
                call.stop_loss,
                call.take_profit,
                call.holding_days,
            )
        ),
        key=lambda found: (-found[0], found[1]),
    )
    plans: list[Plan] = []
    seen: set[tuple[float, float, float, int]] = set()
    for _, seat, call in ranked:
        entry = ((call.entry_low or 0.0) + (call.entry_high or 0.0)) / 2
        stop, target = call.stop_loss or 0.0, call.take_profit or 0.0
        days = call.holding_days or 1
        key = (round(entry, 8), round(stop, 8), round(target, 8), days)
        if key in seen or not stop < entry < target:
            continue
        seen.add(key)
        plans.append(
            Plan(
                entry=entry,
                stop=stop,
                target=target,
                holding_days=days,
                trailing_pct=call.trailing_stop_pct,
                cost_pct=cost_pct,
                label=f"the {SEAT_NAMES.get(seat, 'seat')}'s plan (entry {entry:g}, "
                f"stop {stop:g}, target {target:g}, {days} days)",
            )
        )
        if len(plans) >= MAX_PLANS:
            break
    return plans


_VARIANT_WORDS: dict[str, tuple[str, ...]] = {
    "lower": ("lower", "limit", "pullback", "dip", "cheaper", "wait", "patient"),
    "wider": ("wider", "loose", "room", "noise"),
    "trail": ("trail", "trailing", "lock"),
    "longer": ("longer", "weeks", "time", "hold"),
}


def variants(plan: Plan, *, atr: float, asked: Sequence[str] = ()) -> list[Plan]:
    """Up to ``MAX_VARIANTS`` other ways to do the leading plan, built by
    code: the ones the brainstorm asked for first."""
    if atr <= 0:
        return []
    built: dict[str, Plan] = {}
    lower = plan.entry - atr
    if lower > plan.stop:
        built["lower"] = Plan(
            entry=lower,
            stop=plan.stop,
            target=plan.target,
            holding_days=plan.holding_days,
            trailing_pct=plan.trailing_pct,
            cost_pct=plan.cost_pct,
            label=f"a limit entry 1 ATR lower ({lower:g})",
        )
    wider = plan.stop - atr
    if wider > 0:
        built["wider"] = Plan(
            entry=plan.entry,
            stop=wider,
            target=plan.target,
            holding_days=plan.holding_days,
            trailing_pct=plan.trailing_pct,
            cost_pct=plan.cost_pct,
            label=f"a stop 1 ATR wider ({wider:g})",
        )
    if not plan.trailing_pct:
        trail = round(2 * atr / plan.entry * 100, 3)
        if 0 < trail <= 50:
            built["trail"] = Plan(
                entry=plan.entry,
                stop=plan.stop,
                target=plan.target,
                holding_days=plan.holding_days,
                trailing_pct=trail,
                cost_pct=plan.cost_pct,
                label=f"a trailing stop 2 ATR ({trail:g}%) behind the best price",
            )
    longer = min(60, plan.holding_days + max(2, plan.holding_days // 2))
    if longer > plan.holding_days:
        built["longer"] = Plan(
            entry=plan.entry,
            stop=plan.stop,
            target=plan.target,
            holding_days=longer,
            trailing_pct=plan.trailing_pct,
            cost_pct=plan.cost_pct,
            label=f"holding up to {longer} days",
        )
    wanted: list[str] = []
    for idea in asked:
        words = words_of(idea)
        for name, hints in _VARIANT_WORDS.items():
            if name not in wanted and any(hint in words for hint in hints):
                wanted.append(name)
    order = [*wanted, *(name for name in _VARIANT_WORDS if name not in wanted)]
    return [built[name] for name in order if name in built][:MAX_VARIANTS]


async def run_simulations(
    plans: Sequence[Plan],
    daily: Sequence[Bar],
    *,
    now: float,
    seed_parts: Sequence[str],
) -> list[SimResult]:
    """Each plan over the same past days, with a seed from the round and the
    plan, so the same inputs always give the same numbers."""

    def run_all() -> list[SimResult]:
        found: list[SimResult] = []
        for plan in plans:
            result = simulate(
                plan, daily, now=now, seed=seed_for(*seed_parts, plan.label)
            )
            if result is not None:
                found.append(result)
        return found

    return await asyncio.to_thread(run_all)


def simulation_items(
    results: Sequence[SimResult], *, now: float, symbol: str
) -> list[InfoItem]:
    return [
        InfoItem(
            kind="calculation",
            topic="simulation",
            label="",
            value=result.lines(),
            source="FCC simulation from past price behaviour (not a prediction)",
            as_of=now,
            symbol=symbol,
            source_id=f"seed {result.seed}",
        )
        for result in results
    ]
