"""The decision layer: the investment stress test on top of the original
cases (never weaker), the regime's six labels and its tighten-only policy,
the scorecard, seat and data conflicts, and every rule of the engine."""

import math
from typing import Any

import pytest

from free_claude_code.studio.trading.conflicts import (
    applied,
    data_conflicts,
    seat_conflicts,
)
from free_claude_code.studio.trading.engine import BuyFacts, blockers, buy_rules
from free_claude_code.studio.trading.indicators import Bar
from free_claude_code.studio.trading.regime import Regime, policy_for
from free_claude_code.studio.trading.scorecard import TradeFacts, score_trade
from free_claude_code.studio.trading.seats import Forecast
from free_claude_code.studio.trading.stress import (
    Holding,
    StressInput,
    stress_test,
)

NOW = 1_800_000_000.0
DAY = 86_400


def data(value: object) -> Any:
    return value


def history(*, wild: float, days: int = 400, start: float = 100.0) -> list[Bar]:
    found: list[Bar] = []
    price = start
    for index in range(days):
        swing = wild * math.sin(index * 1.7) + (wild * 2 if index % 97 == 0 else 0)
        opened = price * (1 - swing / 3)
        close = price * (1 - swing)
        found.append(
            Bar(
                int(NOW - (days - index) * DAY),
                opened,
                max(opened, close) * 1.01,
                min(opened, close) * 0.99,
                close,
                1_000_000.0,
            )
        )
        price = close * (1 + wild / 10)
    return found


def original_cases(
    *,
    qty: float,
    entry: float,
    stop: float,
    atr: float,
    fx: float,
    market: str,
    meme: bool,
    beta: float,
) -> list[tuple[str, float]]:
    """The original stress cases from the risk report, worked out the same
    way (assessment.py)."""
    unit = qty * fx
    value = qty * entry * fx
    cases = [(f"{move} ATR drop", unit * atr * move) for move in (1, 2, 3)]
    if market in {"us", "asx"}:
        cases.append(
            ("Gap through the stop overnight", unit * (entry - (stop - atr)) * 1.002)
        )
    else:
        crash = 0.30 if meme else 0.15
        cases.append((f"{crash:.0%} flash crash", value * crash))
    cases.append(("Index falls 3%", value * 0.03 * max(0.0, beta)))
    return cases


SETUPS = [
    # (market, meme, wild, qty, equity, beta, fx)
    ("us", False, 0.01, 10, 10_000, 1.0, 1.5),
    ("us", False, 0.05, 200, 10_000, 1.4, 1.5),
    ("asx", False, 0.02, 50, 50_000, 0.6, 1.0),
    ("asx", False, 0.08, 1_000, 20_000, 1.0, 1.0),
    ("crypto", False, 0.03, 0.5, 10_000, 0.5, 1.5),
    ("crypto", False, 0.10, 5, 100_000, 1.0, 1.5),
    ("crypto", True, 0.15, 10_000, 10_000, 2.0, 1.5),
    ("crypto", True, 0.02, 1, 1_000_000, 0.2, 1.5),
]


@pytest.mark.parametrize("setup", SETUPS)
def test_the_stress_test_is_never_weaker_than_the_original(setup):
    market, meme, wild, qty, equity, beta, fx = setup
    daily = history(wild=wild)
    entry = daily[-1].c
    atr = entry * wild * 1.5
    stop = entry - 2 * atr
    original = original_cases(
        qty=qty,
        entry=entry,
        stop=stop,
        atr=atr,
        fx=fx,
        market=market,
        meme=meme,
        beta=beta,
    )
    report = stress_test(
        StressInput(
            symbol="X",
            market=market,
            side="long",
            qty=qty,
            entry=entry,
            stop=stop,
            fx=fx,
            equity=equity,
            atr=atr,
            daily=daily,
            index_daily=history(wild=wild / 2),
            beta=beta,
            meme=meme,
            spread_pct=0.1,
            avg_daily_turnover=1_000_000.0 * entry,
            holdings=(Holding("Y", equity * 0.2, 1.0, market == "crypto"),),
            extra=original,
        ),
        now=NOW,
        trade_limit_pct=3.0,
        account_limit_pct=12.0,
    )
    shown = {(item.name, round(item.loss, 6)) for item in report.scenarios}
    # 1. Every original case appears, worked out exactly as before.
    for name, loss in original:
        assert (name, round(max(0.0, loss), 6)) in shown
    # 2. The new worst case is never smaller than the original worst case.
    worst = report.worst_trade
    assert worst is not None and worst.loss >= max(loss for _, loss in original) - 1e-9
    # 3. The size can only stay or shrink; a breach shrinks or blocks.
    assert report.max_qty <= qty + 1e-9
    original_worst_pct = max(loss for _, loss in original) / equity * 100
    if original_worst_pct > 3.0:
        assert report.blocked or report.max_qty < qty


def test_the_regime_has_six_labels_and_an_extreme_flag():
    def regime(trend: str, vol: str, change: float | None = 2.0, vix=None, market="us"):
        return Regime(market, trend, vol, change, vix, 1.0)

    assert regime("up", "normal").kind == "bull_trend"
    assert regime("down", "normal").kind == "bear_trend"
    assert regime("range", "normal").kind == "sideways"
    assert regime("up", "high").kind == "high_volatility"
    assert regime("range", "low").kind == "low_volatility"
    assert Regime("unknown", "range", "normal", None, None, 1.0).kind == "unclear"
    assert regime("down", "high", vix=40.0).extreme
    assert regime("down", "high", change=-20.0).extreme
    assert not regime("down", "high", change=-20.0, market="crypto").extreme
    assert regime("down", "high", change=-35.0, market="crypto").extreme


def test_the_regime_policy_only_ever_tightens():
    for trend in ("up", "down", "range"):
        for vol in ("low", "normal", "high"):
            for change in (5.0, -40.0):
                policy = policy_for(Regime("us", trend, vol, change, None, 1.0))
                assert policy.size_factor <= 1.0
                assert policy.confidence_add >= 0.0
                assert policy.trades_factor <= 1.0
                assert policy.stop_atr_factor >= 1.0
    crash = policy_for(Regime("us", "down", "high", -25.0, 45.0, 0.5))
    assert crash.extreme and not crash.allow_new_trades


def facts(**changes: Any) -> BuyFacts:
    values: dict[str, Any] = {
        "data_ok": True,
        "data_summary": "Data checks passed.",
        "stop_atr": 2.0,
        "min_stop_atr": 1.0,
        "reward_risk": 2.5,
        "min_reward_risk": 1.5,
        "confidence": 0.7,
        "min_confidence": 0.6,
        "consensus": 0.66,
        "min_consensus": 0.55,
        "trades_today": 0,
        "max_trades_per_day": 6,
        "objections_left": 1,
        "answered": 1,
        "stress_blocked": False,
        "stress_reasons": (),
        "stress_worst_pct": 2.0,
        "stress_limit_pct": 3.0,
        "info_blocked": False,
        "conflicts_blocking": False,
        "conflict_reasons": (),
    }
    values.update(changes)
    return BuyFacts(**values)


CALM = policy_for(Regime("us", "up", "normal", 3.0, 15.0, 1.0))
WILD = policy_for(Regime("us", "up", "high", 3.0, 28.0, 0.5))


def test_every_rule_is_checked_with_its_measure_and_limit():
    checks = buy_rules(facts(), CALM)
    assert checks and all(check.passed for check in checks)
    assert blockers(checks) == []
    names = {check.rule for check in checks}
    assert "Stop far enough from the entry" in names
    assert "Every standing blocking objection answered" in names


@pytest.mark.parametrize(
    ("changes", "policy", "rule"),
    [
        ({"stop_atr": 0.6}, CALM, "Stop far enough"),
        # A wild market wants the stop 1.5 ATR away.
        ({"stop_atr": 1.2}, WILD, "Stop far enough"),
        ({"stop_atr": None}, CALM, "Stop far enough"),
        ({"confidence": 0.62}, WILD, "Confidence"),
        ({"trades_today": 3}, WILD, "Trades today"),
        ({"trades_today": None}, CALM, "Trades today"),
        ({"answered": 0}, CALM, "blocking objection"),
        ({"stress_blocked": True}, CALM, "Investment stress test"),
        ({"stress_blocked": None}, CALM, "Investment stress test"),
        ({"info_blocked": None}, CALM, "Information stress test"),
        ({"conflicts_blocking": True}, CALM, "No conflict"),
        ({"data_ok": False}, CALM, "Data good enough"),
        ({}, policy_for(Regime("us", "down", "high", -30.0, 50.0, 0.5)), "mood allows"),
    ],
)
def test_a_failing_rule_blocks_the_buy(changes, policy, rule):
    found = blockers(buy_rules(facts(**changes), policy))
    assert any(rule in line for line in found), found


def trade(**changes: Any) -> TradeFacts:
    values: dict[str, Any] = {
        "consensus": 0.66,
        "buy_share": 1.0,
        "quality_score": 90,
        "reward_risk": 2.5,
        "stop_atr": 2.0,
        "trend": "up",
        "price": 100.0,
        "sma50": 95.0,
        "sma200": 90.0,
        "rsi": 60.0,
        "held_up": 2,
        "tested": 2,
        "regime_kind": "bull_trend",
        "regime_extreme": False,
        "events_in_window": 0,
        "stress_worst_pct": 1.5,
        "stress_limit_pct": 3.0,
        "max_correlation": 0.2,
        "correlation_limit": 0.8,
        "position_pct": 5.0,
        "position_cap_pct": 10.0,
        "spread_pct": 0.05,
        "spread_limit_pct": 0.5,
        "adv_pct": 0.01,
        "adv_limit_pct": 1.0,
        "base_target_first": None,
    }
    values.update(changes)
    return TradeFacts(**values)


def test_the_scorecard_marks_seven_categories_and_weighs_confidence():
    card = score_trade(trade())
    assert [item.name for item in card.categories] == [
        "data_quality",
        "technical_setup",
        "research_evidence",
        "macro",
        "risk_quality",
        "portfolio_fit",
        "execution_quality",
    ]
    assert all(0 <= item.score <= 100 and item.why for item in card.categories)
    parts = dict(card.parts)
    expected = (
        30 * parts["agreement"]
        + 20 * parts["data"]
        + 20 * parts["reward_risk"]
        + 15 * parts["history"]
        + 15 * parts["execution"]
    ) / 100
    assert card.confidence == pytest.approx(expected, abs=1e-4)
    # Weaker inputs never raise it.
    assert score_trade(trade(reward_risk=1.5)).confidence < card.confidence
    assert score_trade(trade(quality_score=40)).confidence < card.confidence
    assert (
        score_trade(trade(buy_share=0.4, consensus=0.56)).confidence < card.confidence
    )


def test_confident_opposing_seats_cut_and_a_mismatched_history_blocks():
    closing = {
        1: Forecast(stance="buy", p_up=0.7, confidence=0.8),
        3: Forecast(stance="avoid", p_up=0.4, confidence=0.75),
        4: Forecast(stance="sell", p_up=0.35, confidence=0.9),
    }
    found = seat_conflicts("BTC", closing, buying=True)
    assert len(found) == 2 and all(item.kind == "seat" for item in found)
    penalty, size, blocking = applied(found)
    assert penalty == 10.0 and size == pytest.approx(0.5625) and not blocking
    assert seat_conflicts("BTC", closing, buying=False) == []

    daily = [Bar(int(NOW - DAY), 100.0, 101.0, 99.0, 100.0)]
    assert data_conflicts("BHP.AX", "asx", daily, 101.0, source="Yahoo") == []
    [wrong] = data_conflicts("BHP.AX", "asx", daily, 160.0, source="Yahoo")
    assert wrong.blocking and wrong.kind == "data"
    assert applied([wrong])[2]
