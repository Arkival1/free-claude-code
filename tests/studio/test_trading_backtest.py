"""The backtest replays the desk's rules on closed daily candles only, never
reads ahead, fills at the next open, and says what it is."""

import math
from dataclasses import replace

from free_claude_code.core.json_types import JsonObject
from free_claude_code.studio.trading.backtest import (
    DAY_S,
    LABEL,
    Settings,
    closed_only,
    run,
)
from free_claude_code.studio.trading.indicators import Bar

START = 1_700_006_400 - 1_700_006_400 % DAY_S
RULES = Settings(market="us", min_score=1.0)


def climb(days: int, *, start: float = 100.0) -> list[Bar]:
    """A rising price with a volume spike every fifth day (breakouts)."""
    bars: list[Bar] = []
    price = start
    for day in range(days):
        price *= 1.004 + 0.006 * math.sin(day / 3)
        volume = 3_000_000.0 if day % 5 == 0 else 1_000_000.0
        bars.append(
            Bar(
                START + day * DAY_S,
                price * 0.995,
                price * 1.01,
                price * 0.99,
                price,
                volume,
            )
        )
    return bars


def after(bars: list[Bar]) -> float:
    """A time after every candle has closed."""
    return bars[-1].t + 2 * DAY_S


def test_a_candle_still_forming_is_left_out():
    bars = climb(5)
    assert closed_only(bars, bars[-1].t + DAY_S / 2) == bars[:-1]
    assert closed_only(bars, after(bars)) == bars


def test_too_little_history_is_said_not_guessed():
    bars = climb(20)
    result = run({"AAA": bars}, bars, RULES, now=after(bars))
    assert "Not enough" in str(result["error"]) and result["label"] == LABEL


def test_trades_fill_at_the_next_open_and_results_are_labelled():
    bars = climb(200)
    result = run({"AAA": bars}, bars, RULES, now=after(bars))
    assert result["label"] == LABEL
    trades = result["trades"]
    assert isinstance(trades, list) and trades
    opens = {bar.t // DAY_S: bar.o for bar in bars}
    for trade in trades:
        assert isinstance(trade, dict)
        day = trade["entry_day"]
        assert isinstance(day, int)
        # Bought at that day's open plus costs, never at the decision's close.
        entry = trade["entry"]
        assert isinstance(entry, float) and entry > opens[day]
    metrics = result["metrics"]
    assert isinstance(metrics, dict) and metrics["trades"] == len(trades)
    assert "max_drawdown_pct" in metrics and "fees" in metrics


def test_later_prices_never_change_earlier_decisions():
    bars = climb(220)
    short = run({"AAA": bars[:160]}, bars[:160], RULES, now=after(bars[:160]))
    # The same history, then a collapse the desk couldn't have known about.
    wild = bars[:160] + [
        replace(bar, o=bar.o * 0.3, h=bar.h * 0.3, l=bar.l * 0.3, c=bar.c * 0.3)
        for bar in bars[160:]
    ]
    long = run({"AAA": wild}, wild, RULES, now=after(wild))
    cut = bars[159].t // DAY_S

    def before_cut(result: JsonObject) -> list[object]:
        trades = result["trades"]
        assert isinstance(trades, list)
        return [
            trade
            for trade in trades
            if isinstance(trade, dict)
            and isinstance(trade["exit_day"], int)
            and trade["exit_day"] < cut
        ]

    assert before_cut(short)
    assert before_cut(short) == before_cut(long)


def test_a_gap_through_the_stop_fills_at_the_open_and_halts_dont_trade():
    bars = climb(140)
    first = run({"AAA": bars}, bars, RULES, now=after(bars))
    trades = first["trades"]
    assert isinstance(trades, list) and trades
    trade = trades[0]
    assert isinstance(trade, dict)
    entry_day = trade["entry_day"]
    assert isinstance(entry_day, int)
    at = next(i for i, bar in enumerate(bars) if bar.t // DAY_S == entry_day)
    # The day after the entry opens 40% lower: the sale is at that open.
    gapped = list(bars)
    hit = gapped[at + 1]
    gapped[at + 1] = replace(
        hit, o=hit.o * 0.6, h=hit.o * 0.61, l=hit.o * 0.55, c=hit.o * 0.6
    )
    result = run({"AAA": gapped}, gapped, RULES, now=after(gapped))
    trades = result["trades"]
    assert isinstance(trades, list)
    first_trade = trades[0]
    assert isinstance(first_trade, dict)
    assert first_trade["reason"] == "gapped through the stop"
    exit_price = first_trade["exit"]
    assert isinstance(exit_price, float) and exit_price < hit.o * 0.6
    # A day with no volume (halted) can't sell, even through the stop.
    halted = list(gapped)
    halted[at + 1] = replace(halted[at + 1], v=0.0)
    stuck = run({"AAA": halted}, halted, RULES, now=after(halted))
    stuck_trades = stuck["trades"]
    assert isinstance(stuck_trades, list)
    assert all(
        isinstance(t, dict) and t["exit_day"] != halted[at + 1].t // DAY_S
        for t in stuck_trades
    )
