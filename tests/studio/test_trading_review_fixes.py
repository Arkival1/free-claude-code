"""Fixes from the stage 1 review: prices keep their real time (or say they
have none), the price an order is sized from passes the same checks, the
live platform's own book is required, future times and crossed books are
refused, a contradicting or stale copy can't confirm a story, coins fall
back to live exchange prices, and a failed source is never remembered as
"nothing"."""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from free_claude_code.studio.resilience import Web
from free_claude_code.studio.trading.brokers.ibkr import IbkrBroker
from free_claude_code.studio.trading.config import DataQualityLimits
from free_claude_code.studio.trading.data import (
    MarketData,
    Quote,
    quote_snapshot,
    sizing_snapshot,
)
from free_claude_code.studio.trading.indicators import Bar
from free_claude_code.studio.trading.information import QuoteSnapshot
from free_claude_code.studio.trading.instruments import parse_symbol
from free_claude_code.studio.trading.news import RawNews, judge, source_kind
from free_claude_code.studio.trading.precheck import _quote_quality
from free_claude_code.studio.trading.providers.news import parse_rss
from free_claude_code.studio.trading.quality import assess, failed_report
from tests.studio.test_trading_brokers import Recorder, market_data

DAY = 86_400.0
US_OPEN = datetime(2026, 10, 14, 15, 0, tzinfo=UTC).timestamp()
ASX_OPEN = datetime(2026, 10, 14, 2, 0, tzinfo=UTC).timestamp()
LIMITS = DataQualityLimits()


def data(value: object) -> Any:
    return value


def daily(now: float, *, price: float = 100.0) -> list[Bar]:
    return [
        Bar(
            t=int(now - (60 - index) * DAY),
            o=price,
            h=price,
            l=price,
            c=price,
            v=50_000_000.0,
        )
        for index in range(60)
    ]


def snap(
    now: float,
    *,
    provider: str = "Coinbase Exchange",
    symbol: str = "BTC",
    last: float = 100.0,
    bid: float | None = 99.99,
    ask: float | None = 100.01,
    age: float | None = 5.0,
    kind: str = "exchange",
    delayed: int = 0,
    currency: str = "USD",
    stamped: bool = True,
) -> QuoteSnapshot:
    return QuoteSnapshot(
        provider=provider,
        symbol=symbol,
        exchange=provider,
        asset_class="crypto",
        currency=currency,
        timestamp=now - age if age is not None else None,
        received_at=now,
        exchange_tz="UTC",
        realtime=delayed == 0,
        delayed_minutes=delayed,
        last=last,
        bid=bid,
        ask=ask,
        volume=1000.0,
        source_kind=data(kind),
        stamped=stamped,
    )


def levels(report) -> dict[str, str]:
    return {check.name: check.level for check in report.checks}


# ------------------------------------------------------------ 1. real times


def ibkr_with(row: dict[str, object]) -> IbkrBroker:
    platform = Recorder(
        {
            "POST /v1/api/iserver/auth/status": {
                "authenticated": True,
                "connected": True,
            },
            "POST /v1/api/tickle": {},
            "GET /v1/api/trsrv/stocks": {
                "BHP": [
                    {
                        "assetClass": "STK",
                        "contracts": [
                            {"conid": 4036812, "exchange": "ASX", "isUS": False}
                        ],
                    }
                ]
            },
            "GET /v1/api/iserver/marketdata/snapshot": [row],
        }
    )
    return IbkrBroker(
        {"gateway": "https://localhost:5000"}, market_data(), platform.transport()
    )


@pytest.mark.asyncio
async def test_ibkr_prices_keep_their_own_time_only_when_live():
    bhp = parse_symbol("BHP.AX")
    live = ibkr_with(
        {
            "31": "45.10",
            "84": "45.09",
            "86": "45.11",
            "6509": "RpB",
            "_updated": 1_792_000_000_123,
        }
    )
    quote = await live.quote(bhp)
    assert quote is not None and quote.stamped and quote.note == ""
    assert quote.at == pytest.approx(1_792_000_000.123)
    await live.aclose()

    for flag, note in (
        ("D", "delayed"),
        ("Z", "frozen"),
        ("N", "not subscribed"),
        ("", "not said to be live"),
    ):
        broker = ibkr_with(
            {
                "31": "45.10",
                "84": "45.09",
                "86": "45.11",
                "6509": flag,
                "_updated": 1_792_000_000_123,
            }
        )
        found = await broker.quote(bhp)
        assert found is not None and found.note == note, flag
        # No time means no freshness: it can never pass as a live price.
        assert found.at == 0.0 and not found.stamped
        await broker.aclose()


def test_a_price_without_its_own_time_is_always_cross_checked():
    now = US_OPEN
    venue = quote_snapshot(
        Quote("BTC", 105.0, "USD", now - 2, "Swyftx", 104.9, 105.1),
        parse_symbol("BTC"),
        received=now,
    )
    assert not venue.stamped and any("time received" in note for note in venue.notes)
    # Coinbase's time-stamped price is 10 minutes away from the receive time,
    # but the venue's price is still compared with it, and 5% apart blocks.
    coinbase = snap(now, age=600, last=100.0)
    report = assess(
        parse_symbol("BTC"),
        now=now,
        snapshots=[venue, coinbase, snap(now, provider="Kraken", last=100.0)],
        daily=daily(now),
        limits=LIMITS,
        live=False,
    )
    assert levels(report)["sources_agree"] == "blocking"


@pytest.mark.asyncio
async def test_yahoo_without_a_time_is_unknown_and_coins_fall_back_to_live_exchange_prices():
    def answer(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host.endswith("finance.yahoo.com"):
            if "AAPL" in path:
                return httpx.Response(
                    200,
                    json={
                        "chart": {
                            "result": [
                                {
                                    "meta": {
                                        "regularMarketPrice": 200.0,
                                        "currency": "USD",
                                    }
                                }
                            ]
                        }
                    },
                )
            return httpx.Response(503, text="down")
        if host == "api.exchange.coinbase.com" and path.endswith("/ticker"):
            return httpx.Response(
                200,
                json={
                    "price": "101.5",
                    "bid": "101.4",
                    "ask": "101.6",
                    "volume": "5",
                    "time": "2026-10-16T09:30:58Z",
                },
            )
        return httpx.Response(404, json={"message": "NotFound"})

    market = MarketData(Web(transport=httpx.MockTransport(answer), attempts=1))
    aapl = await market.quote(parse_symbol("AAPL"))
    assert aapl.price == 200.0 and aapl.at == 0.0 and not aapl.stamped
    coin = await market.quote(parse_symbol("BTC"))
    assert coin.source == "Coinbase Exchange" and coin.stamped
    assert coin.at == datetime(2026, 10, 16, 9, 30, 58, tzinfo=UTC).timestamp()
    assert coin.bid == 101.4 and coin.ask == 101.6


# ------------------------------------------------------------ 2. the order's price


def test_the_price_an_order_is_sized_from_faces_the_same_checks():
    bhp = parse_symbol("BHP.AX")
    yahoo = snap(
        ASX_OPEN,
        provider="Yahoo Finance",
        symbol="BHP.AX",
        kind="aggregator",
        bid=None,
        ask=None,
        delayed=20,
        age=21 * 60,
        currency="AUD",
        last=45.0,
    )
    ibkr = snap(
        ASX_OPEN,
        provider="IBKR",
        symbol="BHP.AX",
        kind="broker",
        currency="AUD",
        last=45.4,
        bid=45.39,
        ask=45.41,
    )
    live = assess(
        bhp,
        now=ASX_OPEN,
        snapshots=[ibkr, yahoo],
        daily=daily(ASX_OPEN, price=45.0),
        limits=LIMITS,
        live=True,
        account_at=ASX_OPEN - 10,
        sizing=yahoo,
        platform=ibkr,
        platform_name="IBKR",
    )
    found = levels(live)
    # Live: the delayed Yahoo price can't be what the order is sized from.
    assert found["order_price_realtime"] == "blocking"
    assert not live.ok and live.sizing is yahoo

    # Sized from IBKR's own live price instead, everything agrees.
    fixed = assess(
        bhp,
        now=ASX_OPEN,
        snapshots=[ibkr, yahoo],
        daily=daily(ASX_OPEN, price=45.0),
        limits=LIMITS,
        live=True,
        account_at=ASX_OPEN - 10,
        sizing=ibkr,
        platform=ibkr,
        platform_name="IBKR",
    )
    assert (
        "order_price_realtime" not in levels(fixed)
        and levels(fixed)["order_price_fresh"] == "ok"
    )

    # A sizing price that disagrees with the best source blocks.
    off = assess(
        parse_symbol("BTC"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN), snap(US_OPEN, provider="Kraken")],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
        sizing=snap(
            US_OPEN,
            provider="Yahoo Finance",
            kind="aggregator",
            last=102.0,
            bid=None,
            ask=None,
        ),
    )
    assert levels(off)["order_price_agrees"] == "blocking"

    # A day-old candle used as a price fails freshness before any debate.
    stale = sizing_snapshot(
        Quote("BTC", 100.0, "USD", US_OPEN - DAY, "Coinbase Exchange", stamped=True),
        parse_symbol("BTC"),
        received=US_OPEN,
    )
    report = assess(
        parse_symbol("BTC"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN)],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
        sizing=stale,
    )
    assert levels(report)["order_price_fresh"] == "blocking"


# ------------------------------------------------------------ 3. broken feeds


def test_broken_feed_fields_are_undated_or_unknown_never_a_crash():
    rss = b"""<rss><channel>
<item><title>Far future</title><link>https://[broken</link>
<pubDate>Mon, 01 Jan 99999999999 00:00:00 +0000</pubDate></item>
</channel></rss>"""
    [item] = parse_rss(rss, provider="Yahoo Finance")
    assert item.published_at is None
    assert source_kind("https://[broken") == "search"
    [judged] = judge([RawNews("Odd", "https://[x", "web")], symbol="BTC", now=US_OPEN)
    assert judged.source_kind == "search" and judged.status == "undated"
    broken = failed_report("BTC", now=US_OPEN, live=False, error="RuntimeError: boom")
    assert not broken.ok and "boom" in broken.summary()


# ------------------------------------------------------------ 5. the platform's book


def test_live_needs_the_trading_platforms_own_bid_and_ask():
    def run(platform: QuoteSnapshot | None) -> str:
        report = assess(
            parse_symbol("BTC"),
            now=US_OPEN,
            snapshots=[snap(US_OPEN), snap(US_OPEN, provider="Kraken")],
            daily=daily(US_OPEN),
            limits=LIMITS,
            live=True,
            account_at=US_OPEN - 5,
            platform=platform,
            platform_name="Swyftx",
        )
        check = next(item for item in report.checks if item.name == "platform_book")
        assert check.label == "Bid and ask on Swyftx"
        return f"{check.level}: {check.detail}"

    assert run(None).startswith("blocking: the trading platform gave no price")
    assert run(
        snap(US_OPEN, provider="Swyftx", kind="broker", bid=None, ask=None)
    ).startswith("blocking: it gave no valid bid and ask")
    assert "broken book" in run(
        snap(US_OPEN, provider="Swyftx", kind="broker", bid=100.5, ask=100.0)
    )
    assert run(snap(US_OPEN, provider="Swyftx", kind="broker")).startswith("ok")


# ------------------------------------------------------------ 6 and 8. clocks and books


def test_future_times_and_crossed_books_are_refused():
    ahead = assess(
        parse_symbol("BTC"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN, age=-600)],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
    )
    fresh = next(check for check in ahead.checks if check.name == "fresh")
    assert fresh.level == "blocking" and "in the future" in fresh.detail

    now = 1_800_000_000.0
    future = Quote(
        "BTC", 100.0, "USD", now + 600, "Kraken", 99.99, 100.01, stamped=True
    )
    [age, _] = _quote_quality(
        future, buying=True, live=True, now=now, max_age_s=60, spread_limit_pct=0.5
    )
    assert not age.ok and age.blocking and "future" in age.detail

    crossed = Quote("BTC", 100.0, "USD", now - 5, "Kraken", 100.5, 100.0, stamped=True)
    assert crossed.crossed and crossed.spread_pct is None
    [_, spread] = _quote_quality(
        crossed, buying=True, live=False, now=now, max_age_s=60, spread_limit_pct=0.5
    )
    assert not spread.ok and spread.blocking and "broken book" in spread.detail


# ------------------------------------------------------------ 7. confirmation


def test_a_contradicting_or_stale_copy_never_confirms_a_story():
    now = US_OPEN
    opposite = judge(
        [
            RawNews(
                "Acme takeover bid rejected by the board today",
                "https://finance.yahoo.com/a",
                "y",
                "Yahoo Finance",
                now - 3600,
            ),
            RawNews(
                "Acme takeover bid accepted by the board today",
                "https://www.reuters.com/a",
                "y",
                "Reuters",
                now - 3000,
            ),
        ],
        symbol="ACM",
        now=now,
    )
    assert len(opposite) == 2 and not any(item.confirmed for item in opposite)

    story = "Acme beats guidance and lifts its dividend for the full year"
    stale_copy = judge(
        [
            RawNews(story, "https://www.cnbc.com/a", "y", "CNBC", now - 3600),
            RawNews(story, "https://www.reuters.com/a", "y", "Reuters", now - 30 * DAY),
        ],
        symbol="ACM",
        now=now,
    )
    [kept] = stale_copy
    assert kept.source == "CNBC" and not kept.confirmed
    assert [copy.usable for copy in kept.also_from] == [False]

    fresh_copy = judge(
        [
            RawNews(story, "https://www.cnbc.com/a", "y", "CNBC", now - 3600),
            RawNews(story, "https://www.reuters.com/a", "y", "Reuters", now - 1800),
        ],
        symbol="ACM",
        now=now,
    )
    assert fresh_copy[0].confirmed


# ------------------------------------------------------------ 10. failures aren't answers


@pytest.mark.asyncio
async def test_a_dexscreener_failure_is_asked_again_and_said_plainly():
    calls = {"count": 0}

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.dexscreener.com":
            calls["count"] += 1
            if calls["count"] == 1:
                return httpx.Response(503, text="down")
            return httpx.Response(200, json={"pairs": []})
        return httpx.Response(404)

    market = MarketData(Web(transport=httpx.MockTransport(answer), attempts=1))
    pepe = parse_symbol("PEPE")
    assert await market.dex_facts(pepe) is None
    assert market.dex_error(pepe)
    report = assess(
        pepe,
        now=US_OPEN,
        snapshots=[snap(US_OPEN, symbol="PEPE")],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
        meme_facts=False,
        meme_facts_note=market.dex_error(pepe),
    )
    meme = next(check for check in report.checks if check.name == "meme_facts")
    assert "couldn't be read" in meme.detail
    # The failure wasn't kept: the next call asks again and gets an answer.
    assert await market.dex_facts(pepe) is None
    assert calls["count"] >= 2 and market.dex_error(pepe) == ""
    calls_before = calls["count"]
    # A real answer ("no pair") is kept.
    assert await market.dex_facts(pepe) is None
    assert calls["count"] == calls_before
