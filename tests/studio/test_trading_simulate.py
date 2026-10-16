"""Simulations from past price behaviour: reproducible, never reading the
future, honest about stops that gap, and silent when history is too short."""

import math
import random

import pytest

from free_claude_code.studio.trading.indicators import Bar
from free_claude_code.studio.trading.simulate import (
    MIN_DAYS,
    Plan,
    past_days,
    seed_for,
    simulate,
)

DAY = 86_400
NOW = 1_800_000_000.0


def history(
    count: int = 400,
    *,
    drift: float = 0.0,
    swing: float = 0.02,
    gap_every: int = 0,
    gap: float = -0.15,
    seed: int = 7,
) -> list[Bar]:
    """Made-up daily candles ending yesterday."""
    rng = random.Random(seed)
    price = 100.0
    bars: list[Bar] = []
    for index in range(count):
        jump = gap if gap_every and index % gap_every == 0 and index else 0.0
        opened = price * math.exp(jump)
        move = drift + rng.uniform(-swing, swing)
        close = opened * math.exp(move)
        high = max(opened, close) * (1 + swing / 2)
        low = min(opened, close) * (1 - swing / 2)
        bars.append(
            Bar(
                t=int(NOW - (count - index) * DAY),
                o=opened,
                h=high,
                l=low,
                c=close,
                v=1.0,
            )
        )
        price = close
    return bars


PLAN = Plan(entry=100.0, stop=95.0, target=110.0, holding_days=10)


def test_the_same_seed_gives_the_same_answer():
    first = simulate(PLAN, history(), now=NOW, seed=11)
    again = simulate(PLAN, history(), now=NOW, seed=11)
    other = simulate(PLAN, history(), now=NOW, seed=12)
    assert first is not None and again is not None and other is not None
    assert first == again
    assert first.view() != other.view()
    total = first.p_stop_first + first.p_target_first + first.p_time_exit
    assert total == pytest.approx(1.0)
    assert "not a prediction" in first.lines() and "seed 11" in first.lines()
    assert seed_for("trd_1", "plan") == seed_for("trd_1", "plan")
    assert seed_for("trd_1", "plan") != seed_for("trd_2", "plan")


def test_candles_after_now_are_never_used():
    past = history()
    future = [
        *past,
        Bar(t=int(NOW + DAY), o=100.0, h=100.0, l=1.0, c=1.0, v=1.0),
        Bar(t=int(NOW), o=100.0, h=300.0, l=100.0, c=300.0, v=1.0),
    ]
    assert len(past_days(future, now=NOW)) == len(past_days(past, now=NOW))
    assert simulate(PLAN, future, now=NOW, seed=3) == simulate(
        PLAN, past, now=NOW, seed=3
    )


def test_rising_and_falling_histories_point_the_right_way():
    rising = simulate(PLAN, history(drift=0.02), now=NOW, seed=5)
    falling = simulate(PLAN, history(drift=-0.02), now=NOW, seed=5)
    assert rising is not None and falling is not None
    assert rising.p_target_first > 0.8 > falling.p_target_first
    assert falling.p_stop_first > 0.8
    assert rising.median_pct > 0 > falling.median_pct
    assert falling.dip_95pct <= falling.dip_median_pct <= 0


def test_stops_can_gap_past_their_price():
    gappy = simulate(PLAN, history(gap_every=10, gap=-0.15), now=NOW, seed=9)
    assert gappy is not None
    assert gappy.gapped_stops > 0
    # A 15% gap through a 5% stop loses about 15%, not 5%.
    assert gappy.worst_5pct < -10
    assert gappy.tail_mean_pct <= gappy.worst_5pct


def test_costs_and_short_trades():
    cheap = simulate(PLAN, history(), now=NOW, seed=4)
    costly = simulate(
        Plan(entry=100.0, stop=95.0, target=110.0, holding_days=10, cost_pct=1.0),
        history(),
        now=NOW,
        seed=4,
    )
    assert cheap is not None and costly is not None
    assert costly.mean_pct == pytest.approx(cheap.mean_pct - 1.0)
    short = simulate(
        Plan(entry=100.0, stop=105.0, target=90.0, holding_days=10, side="short"),
        history(drift=-0.02),
        now=NOW,
        seed=4,
    )
    assert short is not None and short.p_target_first > 0.8 and short.median_pct > 0


def test_a_trailing_stop_locks_in_gains():
    plain = simulate(
        Plan(entry=100.0, stop=90.0, target=200.0, holding_days=30),
        history(drift=0.004, swing=0.03),
        now=NOW,
        seed=8,
    )
    trailing = simulate(
        Plan(entry=100.0, stop=90.0, target=200.0, holding_days=30, trailing_pct=5.0),
        history(drift=0.004, swing=0.03),
        now=NOW,
        seed=8,
    )
    assert plain is not None and trailing is not None
    assert trailing.p_stop_first > plain.p_stop_first
    assert trailing.worst_5pct >= plain.worst_5pct


def test_too_little_history_or_a_broken_plan_says_nothing():
    assert simulate(PLAN, history(MIN_DAYS - 5), now=NOW, seed=1) is None
    assert (
        simulate(
            Plan(entry=100.0, stop=105.0, target=110.0, holding_days=5),
            history(),
            now=NOW,
            seed=1,
        )
        is None
    )
