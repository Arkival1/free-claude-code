"""The Trading Bank's plain-code parts: charts, hours, symbols, sizing, limits,
the ledger, base rates, forecast scoring, and reading messy model answers."""

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from free_claude_code.studio.trading.brokers.base import Rules, fingerprint, masked
from free_claude_code.studio.trading.config import DeskConfig, RiskLimits
from free_claude_code.studio.trading.forecasts import (
    due_at,
    score,
    track_record,
    weighted,
)
from free_claude_code.studio.trading.indicators import (
    Bar,
    atr,
    correlation,
    ema,
    rsi,
    setup_score,
    sma,
    technical_brief,
)
from free_claude_code.studio.trading.instruments import (
    SymbolError,
    parse_symbol,
    universe,
)
from free_claude_code.studio.trading.ledger import build_ledger, tax_csv
from free_claude_code.studio.trading.patterns import base_rates
from free_claude_code.studio.trading.records import TradeForecast, TradeOrder
from free_claude_code.studio.trading.regime import read_regime
from free_claude_code.studio.trading.risk import Exposure, risk_gate, size_position
from free_claude_code.studio.trading.seats import (
    Decision,
    Forecast,
    Objection,
    PreMortem,
    probability,
    read_model,
)
from free_claude_code.studio.trading.sessions import (
    last_close,
    new_york_offset,
    session,
    sydney_offset,
)


def data(value: object) -> Any:
    return value


def series(
    count: int, *, start: float = 100.0, drift: float = 0.002, wave: float = 2.0
) -> list[Bar]:
    bars: list[Bar] = []
    for index in range(count):
        trend = start * (1 + drift) ** index
        price = trend * (1 + math.sin(index / 4) * wave / 100)
        bars.append(
            Bar(
                t=1_700_000_000 + index * 86_400,
                o=price * 0.995,
                h=price * 1.01,
                l=price * 0.99,
                c=price,
                v=1_000_000 + (index % 7) * 50_000,
            )
        )
    return bars


# ------------------------------------------------------------ chart maths


def test_averages_and_strength_match_hand_worked_values():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert sma(values, 3) == [None, None, 2.0, 3.0, 4.0]
    assert ema(values, 3)[2] == 2.0
    assert ema(values, 3)[3] == pytest.approx(3.0)
    rising = [float(n) for n in range(30)]
    assert rsi(rising)[-1] == 100.0
    flat = [10.0] * 30
    assert rsi(flat)[-1] == 50.0
    choppy = [10.0, 11.0] * 20
    assert 40 < (rsi(choppy)[-1] or 0) < 60


def test_true_range_and_atr():
    bars = [Bar(t=i, o=10, h=11, l=9, c=10) for i in range(20)]
    assert atr(bars)[-1] == pytest.approx(2.0)
    assert atr(bars)[12] is None


def test_the_chart_brief_reads_an_uptrend():
    brief = technical_brief(series(260))
    assert brief.trend == "up"
    assert brief.sma200 is not None and brief.price > brief.sma200
    assert brief.atr_pct is not None and brief.atr_pct > 0
    score_value, tags = setup_score(brief)
    assert "uptrend" in tags
    assert score_value > 0
    assert "Trend up" in brief.lines()
    view = data(brief.view())
    assert view["trend"] == "up"


def test_correlation_of_identical_and_opposite_moves():
    a = [0.01, -0.02, 0.03, 0.0, 0.01, -0.01, 0.02, -0.03, 0.01, 0.02, 0.0]
    assert correlation(a, a) == pytest.approx(1.0)
    assert correlation(a, [-x for x in a]) == pytest.approx(-1.0)
    assert correlation(a[:5], a[:5]) is None


# ------------------------------------------------------------ hours


def test_daylight_saving_in_sydney_and_new_york():
    assert sydney_offset(datetime(2026, 1, 15, tzinfo=UTC)) == 11
    assert sydney_offset(datetime(2026, 6, 15, tzinfo=UTC)) == 10
    # 2026: summer time ends Sunday 5 April 03:00 (Sat 4 April 16:00 UTC).
    assert sydney_offset(datetime(2026, 4, 4, 15, 59, tzinfo=UTC)) == 11
    assert sydney_offset(datetime(2026, 4, 4, 16, 0, tzinfo=UTC)) == 10
    # It starts Sunday 4 October 02:00 (Sat 3 October 16:00 UTC).
    assert sydney_offset(datetime(2026, 10, 3, 16, 0, tzinfo=UTC)) == 11
    assert new_york_offset(datetime(2026, 7, 1, tzinfo=UTC)) == -4
    assert new_york_offset(datetime(2026, 12, 1, tzinfo=UTC)) == -5
    # 2026: 8 March 02:00 EST is 07:00 UTC.
    assert new_york_offset(datetime(2026, 3, 8, 6, 59, tzinfo=UTC)) == -5
    assert new_york_offset(datetime(2026, 3, 8, 7, 0, tzinfo=UTC)) == -4


def test_market_sessions():
    # Tuesday 13 Oct 2026, 01:00 UTC is 12:00 in Sydney (summer time).
    noon_sydney = datetime(2026, 10, 13, 1, 0, tzinfo=UTC)
    asx = session("asx", noon_sydney)
    assert asx.open and asx.local.startswith("Tue 12:00")
    assert asx.closes_at == datetime(2026, 10, 13, 5, 0, tzinfo=UTC)
    us = session("us", noon_sydney)
    assert not us.open
    # 13 Oct 2026 09:30 New York (EDT) is 13:30 UTC.
    assert us.opens_at == datetime(2026, 10, 13, 13, 30, tzinfo=UTC)
    saturday = datetime(2026, 10, 17, 2, 0, tzinfo=UTC)
    assert not session("asx", saturday).open
    assert session("asx", saturday).opens_at == datetime(
        2026, 10, 18, 23, 0, tzinfo=UTC
    )
    assert session("crypto", saturday).open
    assert last_close("asx", noon_sydney) == datetime(2026, 10, 12, 5, 0, tzinfo=UTC)
    assert last_close("crypto", noon_sydney, crypto_hour_utc=14) == datetime(
        2026, 10, 12, 14, 0, tzinfo=UTC
    )


# ------------------------------------------------------------ symbols


def test_symbols_are_read_however_they_are_written():
    assert parse_symbol("bhp.ax").market == "asx"
    assert parse_symbol("ASX:CBA").symbol == "CBA.AX"
    assert parse_symbol("AAPL").market == "us"
    assert parse_symbol("BTC").market == "crypto"
    assert parse_symbol("BTC-AUD").symbol == "BTC"
    assert parse_symbol("doge").meme
    assert parse_symbol("US:OP").market == "us"
    dex = parse_symbol("sol:So11111111111111111111111111111111111111112")
    assert dex.market == "dex" and not dex.tradable
    assert dex.address == "So11111111111111111111111111111111111111112"
    assert parse_symbol("^AXJO").market == "index"
    with pytest.raises(SymbolError):
        parse_symbol("")
    with pytest.raises(SymbolError):
        parse_symbol("not a symbol!!")
    found = universe(
        {"asx": True, "us": False, "crypto": True, "meme": False}, ["NVDA", "PEPE"]
    )
    symbols = [item.symbol for item in found]
    assert "BHP.AX" in symbols and "BTC" in symbols
    assert "NVDA" not in symbols and "PEPE" not in symbols


# ------------------------------------------------------------ sizing and limits


def test_positions_are_sized_by_the_risk_at_the_stop():
    limits = RiskLimits(
        risk_per_trade_pct=1.0, max_position_pct=50, max_order_value=100_000
    )
    sizing = size_position(
        equity=10_000,
        price=100,
        stop=95,
        fx=1.0,
        limits=limits,
        rules=Rules(tradable=True),
    )
    # $100 of risk at $5 a share is 20 shares.
    assert sizing.qty == pytest.approx(20)
    assert sizing.at_risk == pytest.approx(100)
    assert sizing.bound_by == "risk"
    capped = size_position(
        equity=10_000,
        price=100,
        stop=99.9,
        fx=1.0,
        limits=RiskLimits(max_position_pct=10),
    )
    assert capped.bound_by == "position cap" and capped.value == pytest.approx(1000)
    whole = size_position(
        equity=10_000,
        price=33,
        stop=30,
        fx=1.0,
        limits=limits,
        rules=Rules(tradable=True, fractional=False),
    )
    assert whole.qty == 33.0
    meme = size_position(
        equity=10_000,
        price=1,
        stop=0.5,
        fx=1.0,
        limits=RiskLimits(meme_position_pct=1),
        meme=True,
    )
    assert meme.value <= 100.0001
    half = size_position(
        equity=10_000, price=100, stop=95, fx=1.0, limits=limits, regime_scale=0.5
    )
    assert half.qty == pytest.approx(10)
    assert (
        size_position(equity=10_000, price=100, stop=101, fx=1, limits=limits).qty == 0
    )


def test_platform_rules_round_down():
    assert Rules(tradable=True, qty_step=0.001).fit(1.23456) == 1.234
    assert Rules(tradable=True, qty_step=0.25).fit(1.9) == 1.75
    assert Rules(tradable=True, fractional=False).fit(9.99) == 9
    assert Rules(tradable=True, min_qty=1).fit(0.5) == 0
    assert Rules(tradable=True).fit(0.123456789) == 0.12345678
    assert masked("U1234567") == "••••4567"
    assert fingerprint("alpaca", "1") != fingerprint("alpaca", "2")


def gate(**overrides: Any):
    values: dict[str, Any] = {
        "symbol": "BHP.AX",
        "side": "buy",
        "qty": 10,
        "price": 45.0,
        "stop": 43.0,
        "take_profit": 50.0,
        "value": 450.0,
        "meme": False,
        "confidence": 0.7,
        "consensus": 0.62,
        "limits": RiskLimits(),
        "equity": 10_000.0,
        "positions": [],
        "held_qty": 0.0,
        "trades_today": 0,
        "day_change_pct": 0.0,
        "last_trade_ms": {},
        "open_order_symbols": [],
        "now_ms": 10_000_000,
    }
    values.update(overrides)
    return risk_gate(**values)


def test_every_hard_limit_blocks():
    assert gate().allowed
    assert not gate(stop=None).allowed
    assert not gate(stop=46.0).allowed
    assert not gate(take_profit=44.0).allowed
    assert not gate(value=5_000.0).allowed
    assert not gate(limits=RiskLimits(deny=["BHP.AX"])).allowed
    assert not gate(limits=RiskLimits(allow=["CBA.AX"])).allowed
    assert not gate(trades_today=6).allowed
    assert not gate(day_change_pct=-3.5).allowed
    assert not gate(last_trade_ms={"BHP.AX": 10_000_000 - 60_000}).allowed
    assert gate(last_trade_ms={"BHP.AX": 10_000_000 - 2 * 3_600_000}).allowed
    assert not gate(confidence=0.4).allowed
    assert not gate(consensus=0.5).allowed
    assert not gate(open_order_symbols=["BHP.AX"]).allowed
    full = [Exposure(f"S{n}", 100.0) for n in range(5)]
    assert not gate(positions=full).allowed
    assert not gate(positions=[Exposure("BHP.AX", 900.0)]).allowed
    meme = gate(
        symbol="PEPE",
        meme=True,
        value=90.0,
        positions=[Exposure("DOGE", 450.0, meme=True)],
    )
    assert not meme.allowed and "Meme coins would be" in " ".join(meme.reasons)
    # Selling only checks there's enough held.
    assert gate(side="sell", stop=None, held_qty=10).allowed
    assert not gate(side="sell", held_qty=5).allowed


# ------------------------------------------------------------ the ledger


def filled(
    side: str, qty: float, price: float, at: int, *, fees: float = 5.0
) -> TradeOrder:
    return TradeOrder(
        client_id=f"c{at}",
        symbol="CBA.AX",
        side="buy" if side == "buy" else "sell",
        qty=qty,
        filled_qty=qty,
        fill_price=price,
        fees=fees,
        fx_rate=1.0,
        status="filled",
        updated_at=at,
    )


def test_the_ledger_matches_first_in_first_out_for_tax():
    day = 86_400_000
    orders = [
        filled("buy", 10, 100.0, 0),
        filled("buy", 10, 120.0, 100 * day),
        filled("sell", 15, 130.0, 400 * day),
    ]
    ledger = build_ledger(orders)
    assert len(ledger.disposals) == 2
    first, second = ledger.disposals
    assert first.qty == 10 and first.cost_base == pytest.approx(1005.0)
    assert first.discount_eligible
    assert second.qty == 5 and second.cost_base == pytest.approx(602.5)
    assert not second.discount_eligible
    assert ledger.realised == pytest.approx(15 * 130 - 5 - 1005 - 602.5)
    text = tax_csv(ledger)
    assert text.splitlines()[0].startswith("Asset,Quantity,Acquired (UTC)")
    assert "CBA.AX,10" in text and ",yes" in text and ",no" in text


# ------------------------------------------------------------ base rates and regime


def test_base_rates_count_similar_days():
    bars = series(500, drift=0.001, wave=3.0)
    found = base_rates(bars)
    assert found is not None
    assert found.samples >= 15
    assert set(found.win_rate) == {1, 5, 20}
    assert 0 <= found.win_rate[5] <= 1
    assert found.target_first is not None
    assert "similar days" in found.lines()
    assert base_rates(bars[:40]) is None


def test_the_regime_reads_trend_and_volatility():
    up = read_regime("asx", series(260))
    assert up.trend == "up" and up.risk_scale == 1.0
    down = read_regime("asx", series(260, start=300, drift=-0.003))
    assert down.trend == "down" and down.risk_scale == 0.75
    vix = [Bar(t=0, o=30, h=31, l=29, c=32)]
    wild = read_regime("us", series(260), vix)
    assert wild.volatility == "high" and wild.risk_scale == 0.5
    assert read_regime("us", series(20)).trend == "range"


# ------------------------------------------------------------ forecasts


def forecast(
    p_up: float, *, seat: int = 1, hit: bool | None = None, brier: float | None = None
) -> TradeForecast:
    return TradeForecast(
        seat=seat,
        symbol="BTC",
        market="crypto",
        p_up=p_up,
        entry_price=100.0,
        due_at=1_700_000_000_000 + 5 * 86_400_000,
        created_at=1_700_000_000_000,
        target=104.0,
        stop=98.0,
        status="scored" if brier is not None else "open",
        hit=hit,
        brier=brier,
        scored_at=1 if brier is not None else None,
    )


def test_forecasts_are_scored_when_due():
    bars = [
        Bar(t=1_700_000_000 + day * 86_400, o=100, h=100 + day, l=99, c=100 + day)
        for day in range(8)
    ]
    found = score(forecast(0.7), bars)
    assert found is not None
    assert found.hit and found.outcome_move == pytest.approx(5.0)
    assert found.brier == pytest.approx(0.09)
    assert found.target_first is True
    falling = [
        Bar(t=1_700_000_000 + day * 86_400, o=100, h=100.5, l=100 - day, c=100 - day)
        for day in range(8)
    ]
    lost = score(forecast(0.7), falling)
    assert lost is not None and not lost.hit and lost.target_first is False
    assert score(forecast(0.7), bars[:3]) is None
    assert due_at(0, 5, "crypto") == 5 * 86_400_000
    assert due_at(0, 5, "asx") == 7 * 86_400_000


def test_track_records_become_weights_after_twenty_forecasts():
    good = [forecast(0.8, hit=True, brier=0.04) for _ in range(25)]
    record = track_record(1, good)
    assert record.scored == 25 and record.weight == 2.0
    few = track_record(1, good[:10])
    assert few.weight == 1.0
    bad = [forecast(0.9, seat=2, hit=False, brier=0.81) for _ in range(25)]
    poor = track_record(2, bad)
    assert poor.weight == 0.5
    assert poor.overconfident_above is not None
    assert "overconfident" in poor.line()
    chance, buying = weighted({1: (0.8, "buy"), 2: (0.2, "sell")}, {1: 2.0, 2: 0.5})
    assert chance == pytest.approx((2 * 0.8 + 0.5 * 0.2) / 2.5)
    assert buying == pytest.approx(0.8)


# ------------------------------------------------------------ model answers


def test_messy_model_answers_are_read():
    found = read_model(
        "<think>hmm</think>Sure!\n```json\n{'stance': 'Bullish', 'p_up': '64%', "
        "'horizon_days': '5 days', 'confidence': 70, reasons: 'trend up',}\n```",
        Forecast,
    )
    assert found is not None
    assert found.stance == "buy" and found.p_up == 0.64
    assert found.horizon_days == 5 and found.confidence == 0.7
    assert found.reasons == ["trend up"]
    assert probability("0.3") == 0.3 and probability(None) == 0.5
    pm = read_model(
        '{"action": "BUY", "stop_loss": "$95.50", "take_profit": 110, "size_pct": 0.5}',
        Decision,
    )
    assert pm is not None and pm.action == "buy"
    assert pm.stop_loss == 95.5 and pm.size_pct == 50.0
    attack = read_model(
        '{"failure_story": "x", "objections": [{"target": "Researcher", "point": "old news",'
        ' "blocking": "yes"}, {"point": ""}], "verdict": "Block it"}',
        PreMortem,
    )
    assert attack is not None and attack.verdict == "block"
    assert attack.objections == [Objection(target=2, point="old news", blocking=True)]
    assert read_model("no json at all", Forecast) is None


def test_desk_settings_keep_the_guardian_and_manager_on():
    config = DeskConfig.model_validate(
        {
            "seats": [{"seat": 4, "name": "Risk Guardian", "on": False}],
            "watchlist": "bhp.ax, aapl bhp.ax",
        }
    )
    assert config.seat(4).on and config.seat(5).on
    assert config.watchlist == ["BHP.AX", "AAPL"]
    assert len(config.seats) == 5
    with pytest.raises(ValueError):
        DeskConfig.model_validate({"risk": {"max_position_pct": 500}})
