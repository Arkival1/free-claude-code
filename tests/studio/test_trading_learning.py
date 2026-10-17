"""Controlled learning: weights move only on enough evidence, in small
steps, within bounds, and only when they beat the current ones on
forecasts held back from working them out."""

import random

from free_claude_code.studio.trading.learning import (
    HIGHEST,
    LOWEST,
    MAX_CHANGE,
    check,
    propose,
    trade_results,
    windows,
    worse_than_before,
)
from free_claude_code.studio.trading.records import TradeForecast

DAY_MS = 86_400_000
NOW = 1_800_000_000_000


def history(rounds: int, *, good: int = 1, seed: int = 7) -> list[TradeForecast]:
    """Seat ``good`` reads the market well; the others guess."""
    rng = random.Random(seed)
    made: list[TradeForecast] = []
    for number in range(rounds):
        rose = rng.random() < 0.5
        move = 2.0 if rose else -2.0
        created = NOW - (rounds - number) * DAY_MS // 4
        for seat in range(1, 6):
            if seat == good:
                p_up = 0.8 if rose else 0.2
            else:
                p_up = rng.choice([0.3, 0.5, 0.7])
            hit = (p_up > 0.5) == rose if p_up != 0.5 else False
            made.append(
                TradeForecast(
                    round_id=f"r{number}",
                    seat=seat,
                    symbol="BTC",
                    market="crypto",
                    regime="bull_trend",
                    p_up=p_up,
                    status="scored",
                    outcome_move=move,
                    hit=hit,
                    brier=(p_up - (1.0 if rose else 0.0)) ** 2,
                    created_at=created,
                    scored_at=created + DAY_MS,
                )
            )
    return made


EQUAL = dict.fromkeys(range(1, 6), 1.0)


def test_too_little_evidence_changes_nothing():
    proposal = propose(history(30), EQUAL, now_ms=NOW)
    assert not proposal.accepted and proposal.weights == EQUAL
    assert "50 scored" in proposal.reason


def test_a_good_seat_gains_at_most_ten_percent_and_only_if_it_tests_better():
    proposal = propose(history(200), EQUAL, now_ms=NOW)
    assert proposal.accepted, proposal.reason
    assert proposal.weights[1] == 1.0 + MAX_CHANGE
    assert all(LOWEST <= w <= HIGHEST for w in proposal.weights.values())
    assert all(abs(w - 1.0) <= MAX_CHANGE + 1e-9 for w in proposal.weights.values())
    assert proposal.proposed.brier is not None and proposal.current.brier is not None
    assert proposal.proposed.brier < proposal.current.brier


def test_weights_never_leave_their_bounds():
    high = dict.fromkeys(range(1, 6), HIGHEST)
    proposal = propose(history(200), high, now_ms=NOW)
    assert all(LOWEST <= w <= HIGHEST for w in proposal.weights.values())


def test_a_version_that_does_worse_than_the_one_before_is_rolled_back():
    forecasts = history(200)
    trusting_a_guesser = {1: 0.5, 2: 2.0, 3: 1.0, 4: 1.0, 5: 1.0}
    assert worse_than_before(forecasts, trusting_a_guesser, EQUAL, since_ms=0)
    assert worse_than_before(forecasts, EQUAL, EQUAL, since_ms=0) == ""


def test_reports_by_window_market_regime_and_trade():
    forecasts = history(120)
    report = windows(forecasts)
    seat_one = report["1"]
    assert isinstance(seat_one, dict)
    overall, markets, regimes = (
        seat_one["all"],
        seat_one["markets"],
        seat_one["regimes"],
    )
    assert isinstance(overall, dict) and set(overall) == {"10", "50", "100"}
    assert isinstance(markets, dict) and "crypto" in markets
    assert isinstance(regimes, dict) and "bull_trend" in regimes
    results = trade_results(forecasts, {"r1": 25.0})
    seat_result = results["1"]
    assert isinstance(seat_result, dict)
    assert seat_result["trades"] == 1 and seat_result["matched"] in {0, 1}
    assert check([], EQUAL).calls == 0
