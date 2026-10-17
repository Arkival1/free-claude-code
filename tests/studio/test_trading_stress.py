"""The investment stress test: scenarios from the asset's own history (never
the future), the size cut to fit the owner's limit, blocks when even the
smallest size or the whole account breaks it, and the Guardian's extra
scenarios bounded."""

from dataclasses import replace
from typing import Any

import pytest

from free_claude_code.studio.trading.indicators import Bar
from free_claude_code.studio.trading.stress import (
    Holding,
    StressInput,
    stress_test,
    worst_day,
    worst_gap,
    worst_run,
)

DAY = 86_400
NOW = 1_800_000_000.0


def candles(closes: list[float], *, opens: list[float] | None = None) -> list[Bar]:
    count = len(closes)
    return [
        Bar(
            t=int(NOW - (count - index) * DAY),
            o=(opens[index] if opens else close),
            h=max(close, opens[index] if opens else close),
            l=min(close, opens[index] if opens else close),
            c=close,
            v=1.0,
        )
        for index, close in enumerate(closes)
    ]


def calm(count: int = 300, price: float = 100.0) -> list[Bar]:
    return candles([price * (1.001 if index % 2 else 0.999) for index in range(count)])


BASE = StressInput(
    symbol="AAPL",
    market="us",
    side="long",
    qty=10.0,
    entry=100.0,
    stop=95.0,
    fx=1.5,
    equity=100_000.0,
    atr=2.0,
    daily=calm(),
)


def given(**changes: Any) -> StressInput:
    return replace(BASE, **changes)


def run(test: StressInput, trade: float = 3.0, account: float = 12.0):
    return stress_test(test, now=NOW, trade_limit_pct=trade, account_limit_pct=account)


def test_history_is_read_only_up_to_now():
    past = candles([100, 90, 99, 100, 101, 102, 80, 100])
    later = [*past, Bar(t=int(NOW + DAY), o=100, h=100, l=1, c=1, v=1)]
    assert worst_day(later, NOW) == worst_day(past, NOW) == pytest.approx(80 / 102 - 1)
    assert worst_run(past, NOW, 2) == pytest.approx(80 / 101 - 1)
    gaps = candles([100, 100, 100], opens=[100, 85, 100])
    assert worst_gap(gaps, NOW) == pytest.approx(-0.15)


def test_a_calm_small_trade_passes_with_every_scenario_listed():
    report = run(given())
    names = {item.name for item in report.scenarios}
    assert {
        "Worst day on record",
        "Worst five days, stop not filled",
        "Gap through the stop (worst on record)",
        "Volatility doubles at the stop",
        "Market crash",
        "Market crash across the whole account",
        "Liquidity shock at the stop",
    } <= names
    assert not report.blocked and report.max_qty == report.qty == 10.0
    assert report.size_factor == 1.0
    crash = next(item for item in report.scenarios if item.name == "Market crash")
    # At least -10% for shares, times beta 1: 10 x 100 x 1.5 x 10% = 150.
    assert crash.loss == pytest.approx(150.0) and crash.source == "floor"
    assert all(item.loss >= 0 for item in report.scenarios)
    assert "Limits:" in report.lines()


def test_a_trade_over_the_limit_is_cut_to_fit_or_blocked():
    # A position worth 30,000 of a 100,000 account. The worst day on record
    # opened 40% down, so the stop at 95 would fill at 57: 12.9% of the
    # account, over the 3% limit, so the size is cut to fit.
    wild = candles([100.0] * 100 + [60.0] + [100.0] * 100)
    report = run(given(qty=200.0, daily=wild))
    worst = report.worst_trade
    assert worst is not None and worst.name == "Gap through the stop (worst on record)"
    assert worst.pct_of_equity == pytest.approx(12.9)
    assert report.max_qty == pytest.approx(200.0 * 3 / 12.9)
    assert report.size_factor == pytest.approx(3 / 12.9)
    assert not report.blocked
    assert "cut to" in " ".join(report.reasons)

    blocked = run(given(qty=200.0, daily=wild, min_qty=100.0))
    assert blocked.blocked and blocked.max_qty == 0.0 and blocked.size_factor == 0.0


def test_the_whole_account_in_a_crash():
    holdings = [
        Holding("MSFT", 60_000.0, beta=1.2),
        Holding("BTC", 20_000.0, beta=1.0, crypto=True),
    ]
    report = run(given(holdings=holdings))
    account = report.worst_account
    assert account is not None
    # MSFT 60,000 x 10% x 1.2 = 7,200; BTC 20,000 x 25% = 5,000; the trade 150.
    assert account.loss == pytest.approx(12_350.0)
    assert report.blocked and "whole account" in " ".join(report.reasons)
    relaxed = run(given(holdings=holdings), account=15.0)
    assert not relaxed.blocked


def test_the_index_history_and_beta_set_the_crash():
    index = candles([100.0] * 50 + [70.0] * 50)
    report = run(given(index_daily=index, beta=1.5))
    crash = next(item for item in report.scenarios if item.name == "Market crash")
    assert crash.source == "history"
    # -30% x 1.5 on 1,500 of value.
    assert crash.loss == pytest.approx(1_500 * 0.45)


def test_asset_specific_and_guardian_scenarios():
    report = run(
        given(
            market="crypto",
            symbol="PEPE",
            meme=True,
            guardian=[
                ("exchange delists it", 95.0),
                ("rug pull", 60.0),
                ("third", 10.0),
            ],
        )
    )
    names = [item.name for item in report.scenarios]
    assert "Meme coin halves" in names
    assert "Platform outage for a day" in names
    guardian = [item for item in report.scenarios if item.source == "guardian"]
    assert [item.name for item in guardian] == [
        "Guardian: exchange delists it",
        "Guardian: rug pull",
    ]
    # Bounded to a 90% fall at most.
    assert guardian[0].move_pct == pytest.approx(-90.0)
    assert guardian[0].loss == pytest.approx(1_500 * 0.9)

    shares = run(
        given(
            daily=candles([100.0] * 100, opens=[100.0] * 50 + [80.0] + [100.0] * 49),
            earnings_in_window=True,
            fx_daily=candles([0.66] * 50 + [0.60] * 50),
        )
    )
    names = {item.name for item in shares.scenarios}
    assert {"Results inside the holding window", "Currency move"} <= names


def test_shorts_and_liquidity():
    rising = candles([100.0] * 100 + [130.0] + [130.0] * 10)
    short = run(given(side="short", stop=105.0, daily=rising))
    names = {item.name for item in short.scenarios}
    assert "Worst day against a short" in names
    day = next(
        item for item in short.scenarios if item.name == "Worst day against a short"
    )
    assert day.loss == pytest.approx(1_500 * 0.30)
    assert not any(item.name == "Market crash" for item in short.scenarios)

    thin = run(given(spread_pct=0.4, avg_daily_turnover=10_000.0))
    shock = next(
        item for item in thin.scenarios if item.name == "Liquidity shock at the stop"
    )
    # 1,000 of a 10,000 day = 10% of the day: 1% impact + half of a 2% spread.
    per_unit = 5.0 + 95.0 * (2.0 / 2 + 10 * 0.1) / 100
    assert shock.loss == pytest.approx(10 * per_unit * 1.5)


def test_nothing_to_test_is_blocked():
    assert run(given(qty=0.0)).blocked
    assert run(given(equity=0.0)).blocked
