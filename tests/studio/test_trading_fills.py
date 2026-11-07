"""Practice fills: real bid and ask, slippage that grows with size, partial
fills in a thin market, and limit orders that wait and expire."""

import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio.resilience import Web
from free_claude_code.studio.store import StudioStore
from free_claude_code.studio.trading.brokers.base import OrderRequest
from free_claude_code.studio.trading.brokers.paper import PaperBroker
from free_claude_code.studio.trading.data import MarketData, Quote
from free_claude_code.studio.trading.fills import (
    MIN_SLIPPAGE_PCT,
    Conditions,
    conditions,
    next_slice,
)
from free_claude_code.studio.trading.indicators import Bar
from free_claude_code.studio.trading.information import QuoteSnapshot
from free_claude_code.studio.trading.instruments import Instrument, parse_symbol
from free_claude_code.studio.trading.records import TradePosition

DAY = 86_400


def days(count: int, *, close: float = 100.0, volume: float = 1e6) -> list[Bar]:
    """Daily candles that move 1% up and down, the last one still forming."""
    start = int(time.time()) - count * DAY
    return [
        Bar(
            start + i * DAY,
            close,
            close * 1.01,
            close * 0.99,
            close * (1.01 if i % 2 else 0.99),
            volume,
        )
        for i in range(count)
    ]


# ------------------------------------------------------------ the fill model


def test_a_buy_pays_the_live_ask_and_a_sell_gets_the_bid():
    seen = Conditions(100.0, bid=99.9, ask=100.1, book="Coinbase", turnover=1e12)
    buy = next_slice(
        side="buy", remaining=1, seen=seen, profile="crypto", market="crypto", minutes=1
    )
    sell = next_slice(
        side="sell",
        remaining=1,
        seen=seen,
        profile="crypto",
        market="crypto",
        minutes=1,
    )
    assert buy.price == pytest.approx(100.1 * (1 + MIN_SLIPPAGE_PCT / 100))
    assert sell.price == pytest.approx(99.9 * (1 - MIN_SLIPPAGE_PCT / 100))
    assert "Coinbase ask" in buy.basis and "Coinbase bid" in sell.basis


def test_with_no_live_book_an_assumed_spread_is_used_and_said():
    seen = Conditions(50.0, turnover=1e12)
    buy = next_slice(
        side="buy", remaining=1, seen=seen, profile="asx", market="asx", minutes=1
    )
    assert buy.price > 50.0 * 1.0015
    assert "assumed 0.3% spread" in buy.basis


def test_slippage_grows_with_the_orders_share_of_the_market():
    seen = Conditions(10.0, bid=10.0, ask=10.0, book="X", turnover=1e6, volatility=0.05)
    small = next_slice(
        side="buy",
        remaining=10,
        seen=seen,
        profile="crypto",
        market="crypto",
        minutes=1e6,
    )
    large = next_slice(
        side="buy",
        remaining=10_000,
        seen=seen,
        profile="crypto",
        market="crypto",
        minutes=1e6,
    )
    assert small.slippage_pct == MIN_SLIPPAGE_PCT
    # 10% of a day's turnover: 5% volatility times the square root of 0.1.
    assert large.slippage_pct == pytest.approx(100 * 0.05 * 0.1**0.5)
    # Unknown turnover is never taken as a deep market.
    blind = next_slice(
        side="buy",
        remaining=1,
        seen=Conditions(10.0),
        profile="crypto",
        market="crypto",
        minutes=1,
    )
    assert blind.slippage_pct > MIN_SLIPPAGE_PCT and blind.qty == 1


def test_a_thin_market_fills_a_bit_each_minute_in_whole_units():
    # $1,440,000 a day is $1,000 a minute; a tenth of that is $100 a minute.
    seen = Conditions(100.0, bid=100.0, ask=100.0, book="X", turnover=1_440_000)
    piece = next_slice(
        side="buy",
        remaining=50,
        seen=seen,
        profile="crypto",
        market="crypto",
        minutes=1,
    )
    assert piece.qty == pytest.approx(1.0)
    later = next_slice(
        side="buy",
        remaining=49,
        seen=seen,
        profile="crypto",
        market="crypto",
        minutes=3,
    )
    assert later.qty == pytest.approx(3.0)
    shares = next_slice(
        side="buy",
        remaining=50,
        seen=Conditions(100.0, turnover=360 * 100.0 * 5),
        profile="asx",
        market="asx",
        minutes=1,
        step=1.0,
    )
    assert shares.qty == 1.0


def test_a_limit_waits_for_the_book_and_never_fills_beyond_its_price():
    seen = Conditions(100.0, bid=99.95, ask=100.05, book="X", turnover=1e12)
    waiting = next_slice(
        side="buy",
        remaining=1,
        seen=seen,
        profile="crypto",
        market="crypto",
        minutes=1,
        limit=100.0,
    )
    assert waiting.qty == 0
    reached = next_slice(
        side="buy",
        remaining=1,
        seen=seen,
        profile="crypto",
        market="crypto",
        minutes=1,
        limit=100.06,
    )
    assert reached.qty == 1 and reached.price <= 100.06


def test_conditions_leave_out_the_forming_candle():
    bars = days(22, volume=1_000.0)
    bars[-1] = Bar(bars[-1].t, 100, 100, 100, 100, 999_999_999.0)
    found = conditions(100.0, bars, market="crypto")
    assert found.turnover == pytest.approx(1_000.0)
    assert found.volatility is not None and found.volatility > 0.01
    shares = conditions(100.0, bars, market="us")
    assert shares.turnover is not None and shares.turnover > 90_000
    # A crossed book is no book.
    assert conditions(100.0, bars, market="crypto", bid=101, ask=99).bid is None


# ------------------------------------------------------------ the practice account


class FakeMarket(MarketData):
    """Real-looking prices for the practice account, with no network."""

    def __init__(self, daily: list[Bar], snapshots: list[QuoteSnapshot]) -> None:
        super().__init__(
            Web(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
        )
        self.daily = daily
        self.books = snapshots
        self.price = 100.0

    async def quote(self, instrument: Instrument) -> Quote:
        return Quote(instrument.symbol, self.price, "USD", time.time(), "Yahoo")

    async def snapshots(self, instrument: Instrument) -> list[QuoteSnapshot]:
        return list(self.books)

    async def bars(self, instrument: Instrument, interval: str = "1d") -> list[Bar]:
        return list(self.daily)

    async def fx(self, currency: str, base: str = "AUD") -> float:
        return 1.0 if currency == base else 1.5


def book(bid: float, ask: float) -> QuoteSnapshot:
    now = time.time()
    return QuoteSnapshot(
        provider="Coinbase",
        symbol="BTC",
        exchange="Coinbase",
        asset_class="crypto",
        currency="USD",
        timestamp=now,
        received_at=now,
        exchange_tz="UTC",
        realtime=True,
        delayed_minutes=0,
        last=(bid + ask) / 2,
        bid=bid,
        ask=ask,
        source_kind="exchange",
    )


def account(tmp_path: Path, store: StudioStore, market: FakeMarket, clock: list[float]):
    return PaperBroker(
        store,
        tmp_path / "paper.json",
        market,
        starting_cash=100_000.0,
        clock=lambda: clock[0],
    )


def buy(qty: float, limit: float | None = None) -> OrderRequest:
    return OrderRequest(
        client_id="fcc-practice",
        instrument=parse_symbol("BTC"),
        side="buy",
        qty=qty,
        order_type="market" if limit is None else "limit",
        limit_price=limit,
    )


@pytest.mark.asyncio
async def test_a_practice_order_in_a_thin_market_fills_over_minutes(tmp_path, store):
    clock = [time.time()]
    market = FakeMarket(days(22, volume=1_440_000.0), [book(99.9, 100.1)])
    paper = account(tmp_path, store, market, clock)
    first = await paper.place(buy(5))
    assert first.status == "partially_filled"
    assert first.filled_qty == pytest.approx(1.0, rel=0.01)
    assert first.raw["basis"].startswith("Coinbase ask")
    assert first.fill_price is not None and first.fill_price > 100.1
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None and position.qty == pytest.approx(first.filled_qty)
    # Nothing more within the same minute's share; later minutes fill the rest.
    clock[0] += 2 * 60
    [later] = await paper.tick()
    assert later.filled_qty == pytest.approx(3.0, rel=0.02)
    clock[0] += 5 * 60
    [done] = await paper.tick()
    assert done.status == "filled" and done.filled_qty == pytest.approx(5.0)
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None and position.qty == pytest.approx(5.0)
    # One fee for the whole order, charged as it filled.
    assert done.fees == pytest.approx(
        max(1.0, 5 * done.fill_price * 1.5 * 0.001), rel=0.01
    )
    assert await paper.tick() == []


@pytest.mark.asyncio
async def test_a_practice_limit_waits_for_the_ask_and_expires_after_a_day(
    tmp_path, store
):
    clock = [time.time()]
    market = FakeMarket(days(22, volume=1e12), [book(99.9, 100.1)])
    paper = account(tmp_path, store, market, clock)
    waiting = await paper.place(buy(1, limit=100.0))
    assert waiting.status == "submitted" and waiting.filled_qty == 0
    assert [order.client_id for order in await paper.open_orders()] == ["fcc-practice"]
    clock[0] += 25 * 3600
    [expired] = await paper.tick()
    assert expired.status == "cancelled" and "Expired" in expired.note
    assert await store.get(TradePosition, "paper:BTC") is None


@pytest.mark.asyncio
async def test_practice_can_fill_on_hyperliquids_live_book(tmp_path, store):
    clock = [time.time()]
    market = FakeMarket(days(22, volume=1e12), [book(99.9, 100.1)])

    async def hyperliquid(coin: str) -> QuoteSnapshot:
        snap = book(100.4, 100.6)
        return replace(snap, provider="Hyperliquid", exchange="Hyperliquid")

    paper = PaperBroker(
        store,
        tmp_path / "paper.json",
        market,
        starting_cash=100_000.0,
        coin_book=hyperliquid,
        clock=lambda: clock[0],
    )
    filled = await paper.place(buy(1))
    assert str(filled.raw["basis"]).startswith("Hyperliquid ask")
    assert filled.fill_price is not None and filled.fill_price > 100.6
