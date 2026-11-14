"""The information stress test: before any buy, the evidence it rests on is
attacked, in code and by two seats.

1. Code lists the load-bearing evidence: the numbers the Portfolio Manager
   cites in support of the buy, then those the seats that agree with it
   cite, without repeats.
2. Code checks each one: is it in the pack, is it usable, how old is it,
   who said it, was it confirmed, does another dated story contradict it,
   and does a price still match the latest price. Each item holds, is weak,
   or fails, with the reason.
3. The Researcher and the Risk Guardian each attack the same list (a checked
   answer: holds, weak, or fails, and why), and say whether they would still
   buy without the strongest item. A seat that gives no usable answer counts
   as "weak" on every item, and an item a seat leaves out counts as weak for
   that seat: silence never passes anything.
4. Code decides. Any load-bearing item that fails, by code or by every seat
   that judged it (at least two), stops the buy. If code finds that nothing
   holds, the buy stops too. Each weak item cuts the size and the
   confidence. A buy resting on a single item that isn't exchange, broker,
   or official data is halved.

This can only stop or shrink a trade, never make one bigger.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from free_claude_code.core.json_types import JsonObject

from .contract import EvidenceAttack, SeatCall
from .evidence import EvidencePack
from .information import InfoItem, NewsItem, QuoteSnapshot
from .news import conflicting

type Verdict = Literal["holds", "weak", "fails"]

MAX_ITEMS = 20
WEAK_SIZE = 0.85
"""Each weak load-bearing item leaves this share of the size."""
WEAK_CONFIDENCE = 0.05
"""Each weak load-bearing item takes this off the confidence (0-1)."""
ONE_ITEM_SIZE = 0.5
"""A buy resting on one item that isn't hard data is halved."""
FAILS_TIMES_TOLERANCE = 3.0
"""A cited price this many tolerances from the latest price fails."""
HARD_SOURCES = ("(exchange)", "(broker)", "(official)")
_SILENT = frozenset({"no usable answer", "not judged"})


@dataclass(frozen=True, slots=True)
class ItemCheck:
    """FCC's own verdict on one item."""

    ref: str
    verdict: Verdict
    why: str
    hard: bool = False
    """Exchange, broker, or official data (not a calculation or a story)."""

    def view(self) -> JsonObject:
        return {
            "ref": self.ref,
            "verdict": self.verdict,
            "why": self.why,
            "hard": self.hard,
        }


@dataclass(frozen=True, slots=True)
class ItemResult:
    ref: str
    verdict: Verdict
    code: ItemCheck
    seats: tuple[tuple[int, Verdict, str], ...]
    """Each attacking seat's verdict and reason ("no answer" when silent)."""

    def line(self) -> str:
        said = "; ".join(
            f"seat {seat} {verdict}" + (f" ({why})" if why else "")
            for seat, verdict, why in self.seats
        )
        return (
            f"[{self.ref}] {self.verdict}: code says {self.code.verdict} "
            f"({self.code.why})" + (f"; {said}" if said else "")
        )

    def view(self) -> JsonObject:
        return {
            "ref": self.ref,
            "verdict": self.verdict,
            "code": self.code.view(),
            "seats": [
                {"seat": seat, "verdict": verdict, "why": why}
                for seat, verdict, why in self.seats
            ],
        }


@dataclass(frozen=True, slots=True)
class InfoStress:
    items: tuple[ItemResult, ...]
    blocked: bool
    reasons: tuple[str, ...]
    size_factor: float
    confidence_cut: float
    rests_on_one: bool

    def lines(self) -> str:
        head = (
            "Information stress test: the buy stops (" + "; ".join(self.reasons) + ")."
            if self.blocked
            else f"Information stress test: size x{self.size_factor:.2f}, "
            f"confidence -{self.confidence_cut:.2f}"
            + (f" ({'; '.join(self.reasons)})" if self.reasons else "")
            + "."
        )
        return "\n".join([head, *(item.line() for item in self.items)])

    def view(self) -> JsonObject:
        return {
            "items": [item.view() for item in self.items],
            "blocked": self.blocked,
            "reasons": list(self.reasons),
            "size_factor": round(self.size_factor, 4),
            "confidence_cut": round(self.confidence_cut, 4),
            "rests_on_one": self.rests_on_one,
        }


def load_bearing(
    supporting: Sequence[str],
    calls: Mapping[int, SeatCall],
    *,
    direction: str = "long",
) -> list[str]:
    """The Portfolio Manager's supporting items first, then those the seats
    that agree with the trade cite; no repeats, at most ``MAX_ITEMS``."""
    found: dict[str, None] = {}
    for ref in supporting:
        found.setdefault(ref, None)
    for _, call in sorted(calls.items()):
        if call.direction != direction:
            continue
        for ref in call.evidence:
            found.setdefault(ref, None)
    return list(found)[:MAX_ITEMS]


def check_items(
    refs: Sequence[str],
    pack: EvidencePack,
    *,
    now: float,
    latest: QuoteSnapshot | None,
    tolerance_pct: float,
    news_max_age_s: float,
    direction: str = "long",
) -> list[ItemCheck]:
    """FCC's own verdict on each item, from what the pack says about it and
    the latest price."""
    against = {
        story.ref: other.ref
        for first, second in conflicting(pack.news)
        for story, other in ((first, second), (second, first))
    }
    found: list[ItemCheck] = []
    for ref in refs:
        item = pack.find(ref)
        if item is None:
            found.append(ItemCheck(ref, "fails", "it isn't in the evidence pack"))
        elif isinstance(item, NewsItem):
            found.append(
                _story(
                    item,
                    now=now,
                    max_age_s=news_max_age_s,
                    against=against.get(item.ref),
                    direction=direction,
                )
            )
        else:
            found.append(_item(item, latest=latest, tolerance_pct=tolerance_pct))
    return found


def _story(
    story: NewsItem,
    *,
    now: float,
    max_age_s: float,
    against: str | None,
    direction: str,
) -> ItemCheck:
    hard = story.source_kind in {"official", "exchange"}
    if not story.usable:
        return ItemCheck(story.ref, "fails", f"set aside as {story.status}", hard)
    if story.published_at is None:
        return ItemCheck(story.ref, "fails", "it has no date", hard)
    age = now - story.published_at
    if age > max_age_s:
        return ItemCheck(
            story.ref,
            "fails",
            f"{age / 86_400:.1f} days old (the limit is {max_age_s / 86_400:g})",
            hard,
        )
    problems: list[str] = []
    if story.source_kind == "social":
        problems.append("social media")
    elif not story.confirmed and not hard:
        problems.append("not confirmed by a second reputable source")
    if story.priced_in == "yes":
        problems.append("already priced in")
    if (direction == "long" and story.sentiment == "negative") or (
        direction == "short" and story.sentiment == "positive"
    ):
        problems.append(f"it reads {story.sentiment} for this trade")
    if against is not None:
        problems.append(f"[{against}] points the other way")
    if problems:
        return ItemCheck(story.ref, "weak", "; ".join(problems), hard)
    return ItemCheck(story.ref, "holds", "dated, usable, and not contradicted", hard)


def _item(
    item: InfoItem, *, latest: QuoteSnapshot | None, tolerance_pct: float
) -> ItemCheck:
    hard = item.kind == "fact" and any(tag in item.source for tag in HARD_SOURCES)
    if item.kind == "opinion":
        what = "undated web text" if item.ref.startswith("W") else "an opinion"
        return ItemCheck(item.ref, "weak", f"{what}, not a fact")
    if not item.usable:
        return ItemCheck(item.ref, "fails", f"marked {item.status}", hard)
    if (
        item.kind == "fact"
        and item.topic == "price"
        and isinstance(item.value, int | float)
        and not isinstance(item.value, bool)
    ):
        if latest is None or not latest.last:
            return ItemCheck(item.ref, "weak", "the price couldn't be read again", hard)
        if item.unit and latest.currency and item.unit != latest.currency:
            return ItemCheck(
                item.ref,
                "weak",
                f"in {item.unit}; the latest price is in {latest.currency}",
                hard,
            )
        moved = abs(float(item.value) / latest.last - 1) * 100
        if moved > tolerance_pct * FAILS_TIMES_TOLERANCE:
            return ItemCheck(
                item.ref,
                "fails",
                f"the price has moved {moved:.2f}% since (more than "
                f"{tolerance_pct * FAILS_TIMES_TOLERANCE:g}%)",
                hard,
            )
        if moved > tolerance_pct:
            return ItemCheck(
                item.ref, "weak", f"the price has moved {moved:.2f}% since", hard
            )
        return ItemCheck(
            item.ref,
            "holds",
            f"within {tolerance_pct:g}% of the latest price ({latest.provider})",
            hard,
        )
    if item.kind == "fact" and item.as_of is None:
        return ItemCheck(item.ref, "weak", "its time isn't given", hard)
    if item.realtime is False or item.status == "delayed":
        return ItemCheck(item.ref, "weak", "delayed data", hard)
    if item.kind == "calculation":
        return ItemCheck(item.ref, "holds", "FCC's own arithmetic on dated facts")
    return ItemCheck(item.ref, "holds", "dated and usable", hard)


def combine(
    checks: Sequence[ItemCheck],
    attacks: Mapping[int, EvidenceAttack | None],
) -> InfoStress:
    """Code's verdicts plus the seats' attacks: the stricter wins, a silent
    seat counts as "weak", and only every judging seat (two or more) saying
    "fails" can fail an item that code let through."""
    results: list[ItemResult] = []
    for check in checks:
        said: list[tuple[int, Verdict, str]] = []
        for seat, attack in sorted(attacks.items()):
            if attack is None:
                said.append((seat, "weak", "no usable answer"))
                continue
            mine = next((item for item in attack.items if item.id == check.ref), None)
            if mine is None:
                said.append((seat, "weak", "not judged"))
            else:
                said.append((seat, mine.verdict, mine.why))
        verdict: Verdict = check.verdict
        judged = [found for _, found, why in said if why not in _SILENT]
        if (
            verdict != "fails"
            and len(judged) >= 2
            and all(found == "fails" for found in judged)
        ):
            verdict = "fails"
        elif verdict == "holds" and any(found != "holds" for _, found, _ in said):
            verdict = "weak"
        results.append(ItemResult(check.ref, verdict, check, tuple(said)))

    reasons: list[str] = []
    failed = [item for item in results if item.verdict == "fails"]
    for item in failed:
        why = (
            item.code.why
            if item.code.verdict == "fails"
            else "; ".join(why for _, _, why in item.seats if why)
        )
        reasons.append(f"[{item.ref}] fails: {why}")
    if checks and not any(check.verdict == "holds" for check in checks):
        reasons.append("none of the evidence it cites passes FCC's own checks")
    if not checks:
        reasons.append("it cites no evidence")
    blocked = bool(reasons)
    weak = [item for item in results if item.verdict == "weak"]
    holding = [item for item in results if item.verdict == "holds"]
    without_strongest = [
        attack.still_buy_without_strongest
        for attack in attacks.values()
        if attack is not None
    ]
    rests_on_one = len(holding) <= 1 or (
        bool(without_strongest) and not any(without_strongest)
    )
    size = WEAK_SIZE ** len(weak)
    cut = WEAK_CONFIDENCE * len(weak)
    notes: list[str] = []
    if weak:
        notes.append(f"{len(weak)} weak item(s)")
    if rests_on_one and not any(item.code.hard for item in holding):
        size *= ONE_ITEM_SIZE
        notes.append(
            "it rests on one item that isn't exchange, broker, or official data"
        )
    if blocked:
        return InfoStress(tuple(results), True, tuple(reasons), 0.0, cut, rests_on_one)
    return InfoStress(
        tuple(results), False, tuple(notes), round(size, 4), cut, rests_on_one
    )
