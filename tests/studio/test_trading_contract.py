"""The seats' answer contract: answers are checked in code, refused when
they don't add up (never quietly changed), sent back once with the
problems, and left out when the second answer fails too."""

import json
from typing import Any

import pytest

from free_claude_code.studio.trading.config import SeatConfig
from free_claude_code.studio.trading.contract import (
    PROMPT_VERSION,
    EvidenceAttack,
    GuardianReview,
    PackView,
    PMDecision,
    SeatCall,
    ask_checked,
    check_attack,
    check_call,
    check_decision,
    check_review,
    read_checked,
)
from free_claude_code.studio.trading.instruments import parse_symbol

PACK = PackView(
    "evp_abc",
    "2026-10-14 15:00 UTC",
    frozenset({"F1", "F2", "C1", "N1", "R1", "O1", "W1"}),
)
BTC = parse_symbol("BTC")


def data(value: object) -> Any:
    return value


def call(**changes: object) -> dict[str, object]:
    found: dict[str, object] = {
        "symbol": "BTC",
        "asset_class": "crypto",
        "direction": "long",
        "confidence": 70,
        "p_up": 0.64,
        "main_reason": "Uptrend with rising volume [C1]",
        "thesis": "The trend and volume agree; the ETF story [N1] is not priced in.",
        "prove_wrong": ["a daily close below 95"],
        "evidence": ["F1", "[c1]", "N1"],
        "entry_low": 99.5,
        "entry_high": 100.5,
        "order_type": "limit",
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "holding_days": 5,
        "data_timestamp": "evp_abc",
    }
    found.update(changes)
    return found


def checked(raw: dict[str, object], *, held: bool = False, price: float = 100.0):
    return read_checked(
        json.dumps(raw),
        SeatCall,
        lambda found: check_call(
            found, instrument=BTC, pack=PACK, price=price, held=held
        ),
    )


def test_a_good_call_stands_and_references_are_tidied():
    found, problems = checked(call())
    assert problems == [] and found is not None
    assert found.evidence == ["F1", "C1", "N1"]
    assert found.direction == "long" and found.order_type == "limit"
    # "buy" is the same as "long"; "no trade" is a valid answer.
    assert checked(call(direction="buy"))[0] is not None
    found, problems = checked(
        call(
            direction="no trade",
            evidence=[],
            prove_wrong=[],
            entry_low=None,
            entry_high=None,
            stop_loss=None,
            take_profit=None,
        )
    )
    assert problems == [] and found is not None and found.direction == "no_trade"


def test_unknown_words_are_refused_not_turned_into_hold():
    found, problems = checked(call(direction="moon"))
    assert found is None and any("direction" in problem for problem in problems)
    found, problems = checked(call(order_type="whatever"))
    assert found is None and any("order_type" in problem for problem in problems)
    found, problems = checked(call(stop_loss="about 95"))
    assert found is None and any("stop_loss" in problem for problem in problems)
    found, problems = read_checked("I think we should buy.", SeatCall, lambda _: [])
    assert found is None and problems == ["the reply had no JSON object"]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"data_timestamp": "yesterday"}, "older data"),
        ({"evidence": ["F1", "F9"]}, "isn't in the pack: F9"),
        ({"evidence": ["O1", "W1"]}, "only on opinions"),
        ({"evidence": []}, "must cite evidence"),
        ({"prove_wrong": []}, "prove the call wrong"),
        ({"p_up": 0.4}, "p_up above 0.5"),
        ({"stop_loss": 101.0}, "stop (101) must be below"),
        ({"take_profit": 100.0}, "target (100) must be above"),
        (
            {"entry_low": 120.0, "entry_high": 121.0, "take_profit": 130.0},
            "from the price",
        ),
        ({"entry_low": 101.0, "entry_high": 100.0}, "entry_low is above entry_high"),
        ({"stop_loss": None}, "needs stop_loss"),
        ({"symbol": "ETH"}, "symbol must be BTC"),
        ({"asset_class": "equity"}, "asset_class must be crypto"),
        ({"direction": "sell"}, "only for something we hold"),
        ({"facts": [{"claim": "ETF approved", "ref": "N7"}]}, "facts names evidence"),
    ],
)
def test_calls_that_dont_add_up_are_refused(changes, expected):
    found, problems = checked(call(**changes))
    assert found is None
    assert any(expected in problem for problem in problems), problems


def test_shorts_and_sells():
    short = call(
        direction="short",
        p_up=0.3,
        entry_low=99.5,
        entry_high=100.5,
        stop_loss=105.0,
        take_profit=90.0,
    )
    found, problems = checked(short)
    assert problems == [] and found is not None
    found, problems = checked(
        call(
            direction="sell",
            entry_low=None,
            entry_high=None,
            stop_loss=None,
            take_profit=None,
        ),
        held=True,
    )
    assert problems == [] and found is not None and found.direction == "sell"


def decision(**changes: object) -> dict[str, object]:
    found: dict[str, object] = {
        "action": "long",
        "confidence": 68,
        "p_up": 0.63,
        "p_target": 0.55,
        "rationale": "Trend and news agree.",
        "supporting": ["C1", "N1"],
        "opposing": ["R1"],
        "prove_wrong": ["close below 95"],
        "entry_low": 99.5,
        "entry_high": 100.5,
        "order_type": "market",
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "holding_days": 5,
        "size_pct": 80,
        "data_timestamp": "pack evp_abc",
    }
    found.update(changes)
    return found


def decide(raw: dict[str, object], **extra: Any):
    options: dict[str, Any] = {
        "pack": PACK,
        "price": 100.0,
        "held": False,
        "shorts_allowed": False,
    }
    options.update(extra)
    return read_checked(
        json.dumps(raw), PMDecision, lambda found: check_decision(found, **options)
    )


def test_the_managers_decision_is_checked():
    found, problems = decide(decision())
    assert problems == [] and found is not None and found.size_pct == 80
    found, problems = decide(decision(action="no_trade", supporting=[], prove_wrong=[]))
    assert problems == [] and found is not None
    found, problems = decide(
        decision(action="short", stop_loss=105.0, take_profit=90.0)
    )
    assert found is None and any("shorts are switched off" in p for p in problems)
    found, problems = decide(decision(supporting=["W1"]))
    assert found is None and any("only on opinions" in p for p in problems)
    found, problems = decide(decision(size_pct=150))
    assert found is None


def test_the_guardians_review_and_scenarios_are_bounded():
    def review(**changes: object):
        raw: dict[str, object] = {
            "verdict": "approved smaller",
            "size_factor": 0.5,
            "reasons": ["the stop sits inside normal noise [C1]"],
            "evidence": ["C1"],
            "scenarios": [{"name": "exchange delists it", "fall_pct": 80}],
            "data_timestamp": "evp_abc",
        }
        raw.update(changes)
        return read_checked(
            json.dumps(raw),
            GuardianReview,
            lambda found: check_review(found, pack=PACK),
        )

    found, problems = review()
    assert problems == [] and found is not None and found.verdict == "approved_smaller"
    assert found.scenarios[0].fall_pct == 80
    assert review(verdict="veto")[0] is not None
    found, problems = review(size_factor=1.0)
    assert found is None and any("size_factor below 1" in p for p in problems)
    found, problems = review(scenarios=[{"name": "total wipeout", "fall_pct": 100}])
    assert found is None
    found, problems = review(scenarios=[{"name": "a", "fall_pct": 10}] * 3)
    assert found is None
    found, problems = review(reasons=[])
    assert found is None


def test_the_evidence_attack_only_judges_what_was_asked():
    def attack(items: list[dict[str, object]]):
        raw = {"items": items, "still_buy_without_strongest": False}
        return read_checked(
            json.dumps(raw),
            EvidenceAttack,
            lambda found: check_attack(found, wanted=["C1", "N1"]),
        )

    found, problems = attack(
        [
            {"id": "N1", "verdict": "fails", "why": "9 days old"},
            {"id": "[C1]", "verdict": "holds"},
        ]
    )
    assert problems == [] and found is not None
    found, problems = attack([{"id": "F2", "verdict": "holds"}])
    assert found is None and any("only judge the listed items" in p for p in problems)
    found, problems = attack([{"id": "N1", "verdict": "weak", "why": ""}])
    assert found is None and any("say why for N1" in p for p in problems)


@pytest.mark.asyncio
async def test_one_repair_then_the_seat_is_left_out():
    seat = SeatConfig(seat=1, name="Analyst", model="qwen-3.5-4b")
    prompts: list[str] = []

    def answering(*replies: str):
        async def think(
            seat_: SeatConfig, system: str, prompt: str, max_tokens: int
        ) -> str:
            prompts.append(prompt)
            return replies[len(prompts) - 1]

        return think

    def check(found: SeatCall) -> list[str]:
        return check_call(found, instrument=BTC, pack=PACK, price=100.0, held=False)

    good = json.dumps(call())
    bad = json.dumps(call(stop_loss=101.0))

    first = await ask_checked(
        answering(good),
        seat,
        "TASK",
        SeatCall,
        check=check,
        keys="...",
        max_tokens=100,
        clock=lambda: 5.0,
    )
    assert first.value is not None and not first.repaired and first.problems == ()
    assert first.model_name == "qwen-3.5-4b" and first.prompt_version == PROMPT_VERSION
    assert first.at == 5.0

    prompts.clear()
    fixed = await ask_checked(
        answering(bad, good),
        seat,
        "TASK",
        SeatCall,
        check=check,
        keys="...",
        max_tokens=100,
    )
    assert fixed.value is not None and fixed.repaired
    assert "must be below" in prompts[1] and "not accepted" in prompts[1]
    assert any("must be below" in problem for problem in fixed.problems)

    prompts.clear()
    dropped = await ask_checked(
        answering(bad, "still no"),
        seat,
        "TASK",
        SeatCall,
        check=check,
        keys="...",
        max_tokens=100,
    )
    assert dropped.ignored and dropped.repaired and len(prompts) == 2
    assert data(dropped.view())["ignored"] is True
