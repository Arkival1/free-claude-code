"""The multi-round debate: rounds in order with research, brainstorming, and
simulating between them; new evidence numbered into new pack versions; the
information stress test; the Risk Guardian's review and veto; and a second
answer from the Portfolio Manager facing every check again."""

import json
import math
import re
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from free_claude_code.studio.trading.breaks import (
    MAX_QUESTIONS,
    Budget,
    Findings,
    merge_questions,
    new_findings,
    run_simulations,
    sort_ideas,
    variants,
)
from free_claude_code.studio.trading.briefing import Briefing
from free_claude_code.studio.trading.compare import compare_calls
from free_claude_code.studio.trading.config import DeskConfig, SeatConfig
from free_claude_code.studio.trading.contract import (
    EvidenceAttack,
    Idea,
    PackView,
    PMDecision,
    SeatCall,
    check_decision,
    read_checked,
)
from free_claude_code.studio.trading.data import Quote
from free_claude_code.studio.trading.debate import Debate, DebateTools
from free_claude_code.studio.trading.evidence import (
    EvidencePack,
    build_pack,
    extend_pack,
)
from free_claude_code.studio.trading.indicators import Bar, technical_brief
from free_claude_code.studio.trading.information import (
    InfoItem,
    NewsItem,
    QuoteSnapshot,
)
from free_claude_code.studio.trading.infotest import (
    ONE_ITEM_SIZE,
    WEAK_SIZE,
    check_items,
    combine,
    load_bearing,
)
from free_claude_code.studio.trading.instruments import parse_symbol
from free_claude_code.studio.trading.log import Feed
from free_claude_code.studio.trading.quality import QualityReport
from free_claude_code.studio.trading.records import TradeEvent
from free_claude_code.studio.trading.regime import UNKNOWN
from free_claude_code.studio.trading.research import ResearchPack
from free_claude_code.studio.trading.simulate import Plan

NOW = 1_800_000_000.0
DAY = 86_400


def data(value: object) -> Any:
    return value


def daily_bars(days: int = 200, *, end: float = NOW) -> list[Bar]:
    found: list[Bar] = []
    for index in range(days):
        close = 100 * (1.001**index) * (1 + 0.02 * math.sin(index / 3))
        found.append(
            Bar(
                int(end - (days - index) * DAY),
                close * 0.998,
                close * 1.012,
                close * 0.988,
                close,
                5_000_000.0,
            )
        )
    return found


def snapshot(price: float, *, at: float = NOW - 5) -> QuoteSnapshot:
    return QuoteSnapshot(
        provider="Coinbase Exchange",
        symbol="BTC",
        exchange="Coinbase",
        asset_class="crypto",
        currency="USD",
        timestamp=at,
        received_at=at,
        exchange_tz="UTC",
        realtime=True,
        delayed_minutes=0,
        last=price,
        bid=price * 0.9998,
        ask=price * 1.0002,
        source_kind="exchange",
    )


def setup(*, now: float = NOW) -> tuple[Briefing, EvidencePack]:
    daily = daily_bars(end=now)
    price = daily[-1].c
    briefing = Briefing(
        instrument=parse_symbol("BTC"),
        quote=Quote("BTC", price, "USD", now - 5, "Coinbase Exchange", stamped=True),
        tech=technical_brief(daily),
        regime=UNKNOWN,
        base=None,
        research=ResearchPack("BTC"),
        macro=ResearchPack("crypto macro"),
        lessons=(),
        records={},
        setup="",
        dex=None,
        held=None,
        tags=("uptrend",),
        beta=None,
        daily=tuple(daily),
    )
    snap = snapshot(price, at=now - 5)
    quality = QualityReport(
        "BTC", now, False, (), preferred=snap, snapshots=(snap,), sizing=snap
    )
    pack = build_pack(
        briefing=briefing, quality=quality, config=DeskConfig(), round_id="r1", now=now
    )
    return replace(briefing, evidence_text=pack.text), pack


def story(
    headline: str, *, at: float, kind: str = "official", **extra: Any
) -> NewsItem:
    values: dict[str, Any] = {
        "headline": headline,
        "source": "ASX" if kind == "official" else "Some Blog",
        "source_kind": kind,
        "url": "https://example.com/" + re.sub(r"\W+", "-", headline.lower()),
        "published_at": at,
        "fetched_at": at,
        "symbol": "BTC",
        "sentiment": "positive",
        "confirmed": kind == "official",
        "priced_in": "no",
        "material": "yes",
    }
    values.update(extra)
    return NewsItem(**values)


# ------------------------------------------------------------ scripted seats


def number_after(label: str, text: str) -> float:
    found = re.search(rf"{label} ([0-9.e+-]+)", text)
    assert found is not None, label
    return float(found.group(1).rstrip("."))


def pack_id(prompt: str) -> str:
    found = re.search(r"EVIDENCE PACK (\S+) for", prompt)
    assert found is not None
    return found.group(1)


class Script:
    """Answers every task; what each seat says can be changed per test."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str]] = []
        self.cite = ["F1", "C1"]
        self.attack: dict[int, str] = {}
        """Seat -> verdict it gives every item (default holds)."""
        self.attack_broken: set[int] = set()
        self.review = "approved"
        self.review_factor = 1.0
        self.challenges = ["clear"]
        self.stale_stamp_once = False
        self.ideas = [
            {"idea": "wait for a pullback to a lower limit", "kind": "simulate"}
        ]
        self.questions = ["Is the breakout volume real?", "is the breakout volume real"]

    def task(self, prompt: str) -> str:
        found = re.search(r"TASK: ([^.\n]+)", prompt)
        return found.group(1) if found else ""

    def plan(self, prompt: str) -> dict[str, object]:
        price = number_after("PRICE NOW", prompt)
        atr = number_after("ATR", prompt)
        return {
            "entry_low": round(price * 0.999, 6),
            "entry_high": round(price * 1.001, 6),
            "order_type": "market",
            "stop_loss": round(price - 2 * atr, 6),
            "take_profit": round(price + 5 * atr, 6),
            "holding_days": 5,
        }

    async def __call__(
        self, seat: SeatConfig, system: str, prompt: str, max_tokens: int
    ) -> str:
        task = self.task(prompt)
        self.calls.append((seat.seat, task, prompt))
        if task.startswith(
            ("Opening forecast", "Updated forecast", "Closing statement")
        ):
            stamp = pack_id(prompt)
            if self.stale_stamp_once and task.startswith("Updated forecast"):
                self.stale_stamp_once = False
                stamp = stamp.split(".")[0]
            return json.dumps(
                {
                    "symbol": "BTC",
                    "asset_class": "crypto",
                    "direction": "long",
                    "confidence": 70,
                    "p_up": 0.66,
                    "main_reason": "Uptrend [C1]",
                    "thesis": "The trend [C1] and the price [F1] agree.",
                    "prove_wrong": ["a close below the stop"],
                    "evidence": self.cite,
                    "open_questions": self.questions,
                    "ideas": self.ideas,
                    "changed": "Nothing material [F1].",
                    "data_timestamp": stamp,
                    **self.plan(prompt),
                }
            )
        if task.startswith("Cross-examine"):
            return json.dumps({"stance": "buy", "p_up": 0.65, "question": "Real?"})
        if task.startswith("Pre-mortem"):
            return json.dumps(
                {
                    "stance": "hold",
                    "p_up": 0.5,
                    "failure_story": "The breakout failed.",
                    "worst_case_pct": 6,
                    "objections": [
                        {"target": 1, "point": "Volume is thin", "blocking": True}
                    ],
                }
            )
        if task.startswith("Rebuttal"):
            return json.dumps(
                {
                    "stance": "buy",
                    "p_up": 0.66,
                    "answers": [{"point": "1", "answer": "Volume is fine."}],
                }
            )
        if task.startswith("Guardian reply"):
            return json.dumps(
                {"stance": "buy", "p_up": 0.6, "objections": [], "verdict": "proceed"}
            )
        if task.startswith("Decide"):
            return json.dumps(
                {
                    "action": "long",
                    "confidence": 70,
                    "p_up": 0.66,
                    "p_target": 0.6,
                    "rationale": "The trend and the price agree [C1].",
                    "supporting": self.cite,
                    "prove_wrong": ["a close below the stop"],
                    "size_pct": 100,
                    "answers": [],
                    "data_timestamp": pack_id(prompt),
                    **self.plan(prompt),
                }
            )
        if task.startswith("Evidence attack"):
            if seat.seat in self.attack_broken:
                return "no idea"
            listed = prompt.split("ITEMS TO TEST", 1)[1].split("TASK:", 1)[0]
            verdict = self.attack.get(seat.seat, "holds")
            return json.dumps(
                {
                    "items": [
                        {"id": ref, "verdict": verdict, "why": "checked"}
                        for ref in re.findall(r"^\[([A-Z]\d+)\]", listed, re.M)
                    ],
                    "still_buy_without_strongest": True,
                }
            )
        if task.startswith("Risk review"):
            if self.review == "broken":
                return "can't say"
            return json.dumps(
                {
                    "verdict": self.review,
                    "size_factor": self.review_factor,
                    "reasons": ["the stop sits in normal noise [C1]"],
                    "scenarios": [{"name": "exchange outage", "fall_pct": 30}],
                    "data_timestamp": pack_id(prompt),
                }
            )
        if task.startswith("Final challenge"):
            verdict = self.challenges.pop(0) if self.challenges else "clear"
            return json.dumps({"verdict": verdict, "point": "the stop is too tight"})
        return "{}"

    def tasks(self) -> list[str]:
        return [task for _, task, _ in self.calls]


async def run_debate(
    store,
    tmp_path: Path,
    script: Script,
    *,
    rounds: int = 4,
    depth: str = "balanced",
    look_up=None,
    latest=None,
    kept: list[EvidencePack] | None = None,
):
    briefing, pack = setup()
    config = DeskConfig.model_validate({"debate_rounds": rounds, "depth": depth})

    async def keep(found: EvidencePack) -> None:
        if kept is not None:
            kept.append(found)

    async def fresh() -> QuoteSnapshot | None:
        return snapshot(briefing.price, at=NOW - 1)

    debate = Debate(
        think=script,
        feed=Feed(store, tmp_path / "logs"),
        config=config,
        briefing=briefing,
        round_id="r1",
        weights={},
        tools=DebateTools(
            pack=pack,
            clock=lambda: NOW,
            look_up=look_up,
            latest=latest or fresh,
            keep_pack=keep,
        ),
    )
    return await debate.run(), pack


async def kinds(store) -> list[str]:
    return [event.kind for event in await store.find(TradeEvent, order_by="seq ASC")]


# ------------------------------------------------------------ rounds


@pytest.mark.asyncio
async def test_four_rounds_run_in_order_with_breaks_between(store, tmp_path):
    script = Script()
    kept: list[EvidencePack] = []
    result, first = await run_debate(store, tmp_path, script, kept=kept)
    seen = await kinds(store)
    rounds = [i for i, kind in enumerate(seen) if kind == "round"]
    assert len(rounds) == 4 and result.rounds == 4
    # Between each pair of rounds: brainstorm, research, simulation.
    for before, after in pairwise(rounds):
        between = seen[before:after]
        for kind in ("brainstorm", "research", "simulation"):
            assert kind in between, (kind, between)
    assert len(result.breaks) == 3
    # Every step that was there before is still there.
    for kind in (
        "opening",
        "compare",
        "cross_exam",
        "update",
        "pre_mortem",
        "rebuttal",
        "guardian_reply",
        "closing",
        "consensus",
        "decision",
        "info_test",
        "evidence_attack",
        "guardian_review",
        "final_challenge",
    ):
        assert kind in seen, kind
    tasks = script.tasks()
    assert tasks.index("Pre-mortem") > tasks.index("Updated forecast (round 2 of 4)")
    assert any(task.startswith("Updated forecast (round 3 of 4)") for task in tasks)
    assert result.decision is not None and result.decision.action == "buy"
    # Simulations joined the pack as numbered calculations; versions kept.
    assert kept and kept[-1].id == result.pack_id and result.pack_id != first.id
    assert any("not a prediction" in item.source for item in kept[-1].items)
    assert result.simulations and all(s["paths"] == 2000 for s in result.simulations)


@pytest.mark.asyncio
async def test_one_round_is_the_old_debate_with_no_breaks(store, tmp_path):
    result, _ = await run_debate(store, tmp_path, Script(), rounds=1)
    seen = await kinds(store)
    assert seen.count("round") == 1 and "research" not in seen
    for kind in ("opening", "cross_exam", "pre_mortem", "closing", "final_challenge"):
        assert kind in seen
    assert result.decision is not None and result.decision.action == "buy"


@pytest.mark.asyncio
async def test_research_arrives_as_dated_numbered_evidence(store, tmp_path):
    asked: list[list[str]] = []

    async def look_up(questions, budget: Budget) -> Findings:
        asked.append(list(questions))
        return Findings(
            news=(story("Exchange lists BTC futures", at=NOW - 3600),),
            reading=(
                InfoItem(
                    kind="opinion",
                    topic="reading",
                    label="Web search result",
                    value="<<<Volume rose on the breakout>>>",
                    source="example.com",
                    as_of=None,
                    source_id="https://example.com/a",
                    status="undated",
                ),
            ),
            searched=tuple(questions),
        )

    script = Script()
    result, first = await run_debate(store, tmp_path, script, look_up=look_up)
    # The two near-identical questions were asked once.
    assert asked and asked[0] == ["Is the breakout volume real?"]
    updates = [
        p for seat, task, p in script.calls if task.startswith("Updated forecast")
    ]
    assert updates
    later = updates[0]
    assert pack_id(later) == f"{first.id}.2"
    assert "Exchange lists BTC futures" in later and "added after round 1" in later
    found = re.search(r"\[(N\d+)\] <<<Exchange lists BTC futures>>>", later)
    assert found is not None
    # Undated web text stays reading (W), never a fact.
    assert re.search(r"\[W\d+\] Web search result: <<<Volume rose", later)
    # The same story found again later is not added twice.
    assert (
        sum(1 for b in result.breaks if any(r.startswith("N") for r in b["added"])) == 1
    )


@pytest.mark.asyncio
async def test_a_call_stamped_with_an_older_pack_is_sent_back(store, tmp_path):
    script = Script()
    script.stale_stamp_once = True
    await run_debate(store, tmp_path, script)
    updates = [p for _, task, p in script.calls if task.startswith("Updated forecast")]
    assert any(
        "older data" in prompt and "not accepted" in prompt for prompt in updates
    )


@pytest.mark.asyncio
async def test_a_guardian_veto_stops_the_buy(store, tmp_path):
    script = Script()
    script.review = "rejected"
    result, _ = await run_debate(store, tmp_path, script)
    assert result.decision is not None and result.decision.action == "hold"
    assert "vetoed" in result.blocked
    assert "Final challenge" not in script.tasks()


@pytest.mark.asyncio
async def test_an_unreadable_review_never_lets_a_buy_through(store, tmp_path):
    script = Script()
    script.review = "broken"
    result, _ = await run_debate(store, tmp_path, script)
    assert result.decision is not None and result.decision.action == "hold"
    assert "couldn't be read" in result.blocked


@pytest.mark.asyncio
async def test_approved_smaller_cuts_the_size(store, tmp_path):
    script = Script()
    script.review = "approved_smaller"
    script.review_factor = 0.5
    result, _ = await run_debate(store, tmp_path, script)
    assert result.decision is not None and result.decision.action == "buy"
    assert result.decision.size_pct == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_the_second_answer_is_challenged_again(store, tmp_path):
    script = Script()
    script.challenges = ["block", "block"]
    result, _ = await run_debate(store, tmp_path, script)
    assert script.tasks().count("Final challenge") == 2
    assert result.decision is not None and result.decision.action == "hold"
    assert "reply too" in result.blocked

    again = Script()
    again.challenges = ["block", "clear"]
    result, _ = await run_debate(store, tmp_path, again)
    tasks = again.tasks()
    decided = [task for task in tasks if task.startswith("Decide")]
    assert tasks.count("Final challenge") == 2 and len(decided) == 2
    # The reply went through the evidence attack and the review again.
    assert tasks.count("Risk review") == 2
    assert result.decision is not None and result.decision.action == "buy"


@pytest.mark.asyncio
async def test_failing_evidence_stops_the_buy_and_silence_counts_as_weak(
    store, tmp_path
):
    script = Script()
    script.attack = {2: "fails", 4: "fails"}
    result, _ = await run_debate(store, tmp_path, script)
    assert result.decision is not None and result.decision.action == "hold"
    assert "information stress test" in result.blocked

    quiet = Script()
    quiet.attack_broken = {2}
    result, _ = await run_debate(store, tmp_path, quiet)
    assert result.decision is not None and result.decision.action == "buy"
    # Both items count as weak for the silent seat: size and confidence cut.
    assert result.size_factor == pytest.approx(WEAK_SIZE**2 * ONE_ITEM_SIZE, abs=1e-4)
    assert result.decision.confidence == pytest.approx(0.70 - 0.10)


# ------------------------------------------------------------ the info test


def test_code_judges_each_item_it_rests_on():
    briefing, pack = setup()
    news = story("Old ASX filing", at=NOW - 20 * DAY)
    social = story("Moon soon", at=NOW - 3600, kind="social")
    grown = extend_pack(pack, now=NOW, round_no=1, news=(news, social))
    old_ref, social_ref = (item.ref for item in grown.news[-2:])
    checks = {
        check.ref: check
        for check in check_items(
            ["F1", "C1", old_ref, social_ref, "Z9"],
            grown,
            now=NOW,
            latest=snapshot(briefing.price * 1.03),
            tolerance_pct=0.5,
            news_max_age_s=14 * DAY,
        )
    }
    assert checks["Z9"].verdict == "fails"
    assert checks[old_ref].verdict == "fails" and "days old" in checks[old_ref].why
    assert checks[social_ref].verdict == "weak" and "social" in checks[social_ref].why
    # The price moved 3%: more than 3 tolerances, so the price fact fails.
    assert checks["F1"].verdict == "fails" and checks["F1"].hard
    assert checks["C1"].verdict == "holds"


def test_one_item_that_isnt_hard_data_halves_the_size():
    _, pack = setup()
    checks = check_items(
        ["C1"],
        pack,
        now=NOW,
        latest=None,
        tolerance_pct=0.5,
        news_max_age_s=14 * DAY,
    )
    holds = EvidenceAttack.model_validate(
        {
            "items": [{"id": "C1", "verdict": "holds"}],
            "still_buy_without_strongest": True,
        }
    )
    found = combine(checks, {2: holds, 4: holds})
    assert not found.blocked and found.rests_on_one
    assert found.size_factor == pytest.approx(ONE_ITEM_SIZE)
    # Nothing at all cited, or nothing passing code: no buy.
    assert combine([], {2: holds}).blocked


def test_load_bearing_items_are_the_managers_then_the_agreeing_seats():
    call = SeatCall.model_validate(
        {
            "symbol": "BTC",
            "asset_class": "crypto",
            "direction": "long",
            "confidence": 60,
            "p_up": 0.6,
            "main_reason": "trend",
            "thesis": "trend",
            "evidence": ["C2", "F1"],
            "data_timestamp": "x",
        }
    )
    doubt = call.model_copy(update={"direction": "no_trade", "evidence": ["N1"]})
    assert load_bearing(["F1", "C1"], {1: call, 3: doubt}) == ["F1", "C1", "C2"]


# ------------------------------------------------------------ breaks


def test_questions_and_ideas_are_bounded_and_deduplicated():
    asked = {
        1: ["Is volume real?", "What about the ETF?"],
        2: ["is VOLUME real", "Any token unlocks?"],
        3: ["What about the ETF flows?", "Is the funding rate high?"],
    }
    merged = merge_questions(asked, extra=["Is the funding rate high?"])
    assert len(merged) == MAX_QUESTIONS
    assert merged[0] == "Is volume real?"
    assert len({q.casefold() for q in merged}) == len(merged)

    storm = sort_ideas(
        {
            1: [Idea(idea="wait for a pullback", kind="simulate")],
            2: [Idea(idea="Wait for a pullback!", kind="argue")],
            4: [
                Idea(idea="an exchange hack would gap it", kind="argue"),
                Idea(idea="check the order book depth", kind="needs_data"),
            ],
        }
    )
    assert storm.raw == 4 and storm.count == 3
    assert storm.simulate == ("wait for a pullback",)
    assert storm.needs_data == ("check the order book depth",)


@pytest.mark.asyncio
async def test_simulations_repeat_exactly_and_never_read_the_future():
    daily = daily_bars()
    plan = Plan(
        entry=daily[-1].c,
        stop=daily[-1].c * 0.95,
        target=daily[-1].c * 1.1,
        holding_days=5,
    )
    first = await run_simulations([plan], daily, now=NOW, seed_parts=("r1", "1"))
    again = await run_simulations([plan], daily, now=NOW, seed_parts=("r1", "1"))
    assert first and first[0].view() == again[0].view()
    # A crash after now changes nothing.
    crash = Bar(int(NOW + DAY), 1.0, 1.0, 0.5, 0.5, 1.0)
    later = await run_simulations(
        [plan], [*daily, crash], now=NOW, seed_parts=("r1", "1")
    )
    assert later[0].view() == first[0].view()
    built = variants(plan, atr=2.0, asked=["a wider stop for the noise"])
    assert built[0].label.startswith("a stop 1 ATR wider") and len(built) == 3


def test_extending_the_pack_continues_the_numbers_and_makes_a_new_version():
    _, pack = setup()
    news = story("Exchange lists BTC futures", at=NOW - 60)
    grown = extend_pack(pack, now=NOW + 60, round_no=2, news=(news,))
    assert grown.id == f"{pack.id}.2" and grown.version == 2
    assert grown.digest != pack.digest and grown.cutoff == NOW + 60
    [added] = [ref for ref, _ in grown.added]
    assert added == "N1" and "added after round 2" in grown.line("N1")
    assert pack.refs < grown.refs
    # Old answers stamped with the first version no longer pass.
    view = PackView(grown.id, "", grown.refs)
    decision = PMDecision.model_validate(
        {
            "action": "hold",
            "confidence": 50,
            "p_up": 0.5,
            "rationale": "wait",
            "data_timestamp": pack.id,
        }
    )
    problems = check_decision(
        decision, pack=view, price=100.0, held=False, shorts_allowed=False
    )
    assert any("older data" in problem for problem in problems)
    # The same story again is not new.
    assert new_findings(Findings(news=(news,)), grown).news == ()


def test_code_compares_the_opening_calls():
    base = {
        "symbol": "BTC",
        "asset_class": "crypto",
        "confidence": 70,
        "main_reason": "trend up",
        "thesis": "trend up",
        "data_timestamp": "x",
    }
    long = SeatCall.model_validate(
        {
            **base,
            "direction": "long",
            "p_up": 0.7,
            "evidence": ["F1", "N2"],
            "entry_low": 99,
            "entry_high": 101,
            "stop_loss": 95,
            "take_profit": 110,
        }
    )
    other = long.model_copy(update={"stop_loss": 90.0, "evidence": ["F1"]})
    wait = SeatCall.model_validate(
        {**base, "direction": "no_trade", "p_up": 0.45, "evidence": ["F1"]}
    )
    lines = compare_calls({1: long, 2: other, 3: wait}, price=100.0, atr=2.0)
    text = "\n".join(lines)
    assert "Directions split" in text and "Stops differ" in text
    assert "All cite [F1]" in text and "Only the Technical Analyst cites [N2]" in text


def test_the_old_buy_rules_still_hold_in_the_new_contract():
    view = PackView("evp_x", "", frozenset({"F1", "C1"}))

    def decide(**changes: object) -> list[str]:
        raw: dict[str, object] = {
            "action": "long",
            "confidence": 70,
            "p_up": 0.66,
            "rationale": "trend and price agree",
            "supporting": ["F1"],
            "prove_wrong": ["close below 95"],
            "entry_low": 99.5,
            "entry_high": 100.5,
            "order_type": "market",
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "holding_days": 5,
            "data_timestamp": "evp_x",
        }
        raw.update(changes)
        _, problems = read_checked(
            json.dumps(raw),
            PMDecision,
            lambda d: check_decision(
                d,
                pack=view,
                price=100.0,
                held=False,
                shorts_allowed=False,
                order_types=frozenset({"market", "limit"}),
                blocking=1,
            ),
        )
        return problems

    # One blocking objection is standing and wasn't answered.
    assert any("blocking objection" in p for p in decide())
    answered = [{"point": "1", "answer": "volume is above average"}]
    assert decide(answers=answered) == []
    # A limit more than 2% over the price, a stop entry, a market order
    # whose range misses the price, and a zero size are all refused.
    assert any(
        "2% over" in p
        for p in decide(
            answers=answered,
            order_type="limit",
            entry_low=101.0,
            entry_high=102.5,
        )
    )
    assert any("not stop" in p for p in decide(answers=answered, order_type="stop"))
    assert any(
        "must include it" in p
        for p in decide(answers=answered, entry_low=97.0, entry_high=98.0)
    )
    assert any("above 0" in p for p in decide(answers=answered, size_pct=0))
