"""What the desk knows and how far it trusts it: dated price snapshots,
headlines judged in plain code, and the data-quality checks that stop a new
trade on stale, missing, conflicting, or thin data."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from free_claude_code.studio.resilience import ServiceError, Web
from free_claude_code.studio.search import SearchHit
from free_claude_code.studio.trading.config import DataQualityLimits
from free_claude_code.studio.trading.data import (
    Quote,
    quote_snapshot,
    yahoo_snapshot,
)
from free_claude_code.studio.trading.indicators import Bar
from free_claude_code.studio.trading.information import (
    NewsItem,
    QuoteSnapshot,
    news_key,
    seconds_from_iso,
)
from free_claude_code.studio.trading.instruments import (
    SymbolError,
    parse_symbol,
)
from free_claude_code.studio.trading.news import (
    RawNews,
    conflicting,
    judge,
    material_of,
    priced_in,
    sentiment_of,
    source_kind,
)
from free_claude_code.studio.trading.precheck import _quote_quality
from free_claude_code.studio.trading.providers.news import (
    NewsFeeds,
    from_search,
    parse_rss,
)
from free_claude_code.studio.trading.providers.orderbook import OrderBooks
from free_claude_code.studio.trading.quality import assess

DAY = 86_400.0
# A Wednesday: 11:00 in New York, 02:00 Thursday in Sydney (ASX shut).
US_OPEN = datetime(2026, 10, 14, 15, 0, tzinfo=UTC).timestamp()
# 13:00 in Sydney on a Wednesday: the ASX is trading.
ASX_OPEN = datetime(2026, 10, 14, 2, 0, tzinfo=UTC).timestamp()
SATURDAY = datetime(2026, 10, 17, 2, 0, tzinfo=UTC).timestamp()
LIMITS = DataQualityLimits()


def data(value: object) -> Any:
    return value


def daily(
    now: float,
    *,
    count: int = 60,
    price: float = 100.0,
    volume: float = 50_000_000.0,
    every: int = 1,
) -> list[Bar]:
    """One candle a day up to yesterday (``every`` > 1 leaves gaps)."""
    return [
        Bar(
            t=int(now - (count - index) * DAY),
            o=price,
            h=price,
            l=price,
            c=price,
            v=volume,
        )
        for index in range(count)
        if index % every == 0 or index == count - 1
    ]


def snap(
    now: float,
    *,
    provider: str = "Coinbase Exchange",
    symbol: str = "BTC",
    last: float | None = 100.0,
    bid: float | None = 99.99,
    ask: float | None = 100.01,
    age: float | None = 5.0,
    kind: str = "exchange",
    delayed: int = 0,
    currency: str = "USD",
    notes: tuple[str, ...] = (),
    volume: float | None = 1000.0,
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
        volume=volume,
        source_kind=data(kind),
        notes=notes,
    )


def dated_news(now: float, symbol: str = "BTC") -> list[NewsItem]:
    return judge(
        [
            RawNews(
                headline="Bitcoin ETF approval expected this week",
                url="https://www.reuters.com/markets/bitcoin-etf",
                provider="Yahoo Finance",
                source="Reuters",
                published_at=now - 3600,
            )
        ],
        symbol=symbol,
        now=now,
    )


def checks(report) -> dict[str, str]:
    return {check.name: check.level for check in report.checks}


# ------------------------------------------------------------ information


def test_a_snapshot_says_its_spread_and_never_guesses_its_age():
    found = snap(US_OPEN, bid=99.0, ask=101.0)
    assert found.mid == 100.0
    assert found.spread_pct == pytest.approx(2.0)
    assert found.age_s(US_OPEN) == 5.0
    untimed = snap(US_OPEN, age=None)
    assert untimed.age_s(US_OPEN) is None
    assert untimed.view(US_OPEN)["age_s"] is None
    one_sided = snap(US_OPEN, bid=None)
    assert one_sided.spread_pct is None and one_sided.mid == 100.0


def test_the_same_story_reads_the_same_without_its_publisher():
    assert news_key("BHP lifts copper output - Reuters") == news_key(
        "BHP lifts copper output"
    )
    assert news_key("BHP lifts copper output") != news_key("BHP cuts copper output")
    assert seconds_from_iso("2026-10-16T09:30:58.108242196Z") == pytest.approx(
        datetime(2026, 10, 16, 9, 30, 58, 108242, tzinfo=UTC).timestamp()
    )
    assert seconds_from_iso("2026-10-16T09:30:58") is None
    assert seconds_from_iso("soon") is None


def test_yahoo_and_broker_quotes_become_honest_snapshots():
    asx = parse_symbol("BHP.AX")
    meta: dict[str, object] = {
        "regularMarketPrice": 45.1,
        "regularMarketTime": ASX_OPEN - 1200,
        "regularMarketVolume": 2_000_000,
        "exchangeName": "ASX",
        "exchangeTimezoneName": "Australia/Sydney",
        "currency": "AUD",
    }
    found = yahoo_snapshot(asx, meta, [], received=ASX_OPEN)
    assert found is not None
    assert found.delayed_minutes == 20 and not found.realtime
    assert found.exchange == "ASX" and found.currency == "AUD"
    assert found.bid is None and found.ask is None
    assert found.timestamp == ASX_OPEN - 1200

    no_time = yahoo_snapshot(asx, {"regularMarketPrice": 45.1}, [], received=ASX_OPEN)
    assert no_time is not None and no_time.timestamp is None

    halted = Quote("BHP.AX", 45.0, "AUD", 0.0, "IBKR", note="halted")
    broker = quote_snapshot(halted, asx, received=ASX_OPEN)
    assert broker.timestamp is None
    assert "halted" in broker.notes and broker.source_kind == "broker"


# ------------------------------------------------------------ news


def test_headlines_are_sorted_by_source_sentiment_and_weight():
    assert source_kind("https://www.reuters.com/x") == "reputable"
    assert source_kind("https://finance.yahoo.com/news/x") == "aggregator"
    assert source_kind("https://www.reddit.com/r/stocks") == "social"
    assert source_kind("https://example.blog/post") == "search"
    assert source_kind("", official=True) == "official"

    assert sentiment_of("Apple beats estimates, raises guidance") == "positive"
    assert sentiment_of("Miner plunges after guidance cut warning") == "negative"
    assert sentiment_of("Dividend record date notice") == "neutral"
    assert sentiment_of("Company holds annual meeting") == "unclear"

    assert material_of("Half-year results and outlook", None) == "yes"
    assert material_of("Change of director's interest notice", None) == "no"
    assert material_of("Anything at all", True) == "yes"
    assert material_of("Company newsletter", None) == "unknown"


def test_priced_in_uses_only_prices_after_publication():
    now = US_OPEN
    published = now - 6 * 3600
    before = [Bar(t=int(published - 3600), o=90, h=200, l=80, c=200, v=1)]
    after = [
        Bar(t=int(published + 600), o=100, h=101, l=99, c=100, v=1),
        Bar(t=int(now - 600), o=104, h=105, l=103, c=104, v=1),
    ]
    judged, why = priced_in(
        published, "positive", now=now, bars=before + after, atr=2.0
    )
    assert judged == "yes" and "+2.0 ATR" in why
    later = [Bar(t=int(now + 600), o=100, h=300, l=100, c=300, v=1)]
    judged, _ = priced_in(published, "positive", now=now, bars=later, atr=2.0)
    assert judged == "unknown"
    assert priced_in(None, "positive", now=now, bars=after, atr=2.0)[0] == "unknown"
    assert priced_in(now - 5 * DAY, "negative", now=now, bars=(), atr=None)[0] == "yes"


def test_bad_dates_and_unknown_sources_never_become_facts():
    now = US_OPEN
    judged = judge(
        [
            RawNews("Undated rumour about BTC", "https://example.blog/a", "web search"),
            RawNews(
                "Story from the future",
                "https://www.reuters.com/f",
                "Yahoo Finance",
                "Reuters",
                published_at=now + DAY,
            ),
            RawNews(
                "Very old story",
                "https://www.reuters.com/o",
                "Yahoo Finance",
                "Reuters",
                published_at=now - 30 * DAY,
            ),
            RawNews("Nobody said this", "", ""),
        ],
        symbol="BTC",
        now=now,
    )
    status = {item.headline: item.status for item in judged}
    assert status == {
        "Undated rumour about BTC": "undated",
        "Story from the future": "invalid",
        "Very old story": "stale",
        "Nobody said this": "unknown_source",
    }
    assert not any(item.usable for item in judged)
    # A stale story isn't mislabelled as having no publication time.
    old = next(item for item in judged if item.status == "stale")
    assert "no publication time" not in old.note
    assert [
        item.status
        for item in judge(
            from_search(
                [SearchHit(title="BTC rallies", url="https://x.example/a", snippet="")]
            ),
            symbol="BTC",
            now=now,
        )
    ] == ["undated"]


def test_duplicates_fold_and_confirmation_needs_an_independent_source():
    now = US_OPEN
    story = "Rio Tinto agrees takeover of lithium miner"
    judged = judge(
        [
            RawNews(
                story,
                "https://finance.yahoo.com/a",
                "Yahoo Finance",
                "Yahoo Finance",
                now - 7200,
            ),
            RawNews(
                story + " - Reuters",
                "https://www.reuters.com/a",
                "Yahoo Finance",
                "Reuters",
                now - 7000,
            ),
            RawNews(
                story,
                "https://www.reuters.com/b",
                "Yahoo Finance",
                "Reuters",
                now - 6000,
            ),
        ],
        symbol="RIO.AX",
        now=now,
    )
    assert len(judged) == 1
    [kept] = judged
    assert kept.source == "Reuters" and kept.source_kind == "reputable"
    assert kept.duplicates == 2
    # Only Yahoo (an aggregator) and Reuters itself told it: not confirmed.
    assert not kept.confirmed
    assert any(
        copy.source == "Yahoo Finance" and copy.kind == "aggregator"
        for copy in kept.also_from
    )

    confirmed = judge(
        [
            RawNews(
                story,
                "https://www.reuters.com/a",
                "Yahoo Finance",
                "Reuters",
                now - 7000,
            ),
            RawNews(story, "https://www.afr.com/a", "Yahoo Finance", "AFR", now - 6000),
        ],
        symbol="RIO.AX",
        now=now,
    )
    assert len(confirmed) == 1 and confirmed[0].confirmed

    social = judge(
        [
            RawNews(story, "https://www.reddit.com/r/asx", "web", "reddit", now - 600),
            RawNews(story, "https://x.com/someone", "web", "x", now - 500),
        ],
        symbol="RIO.AX",
        now=now,
    )
    assert all(not item.confirmed for item in social)

    official = judge(
        [RawNews("Trading halt", "", "ASX announcements", "ASX", now - 60, True, True)],
        symbol="RIO.AX",
        now=now,
    )
    assert official[0].confirmed and official[0].material == "yes"


def test_opposite_stories_are_shown_side_by_side():
    now = US_OPEN
    judged = judge(
        [
            RawNews(
                "Tesla deliveries beat forecasts",
                "https://www.reuters.com/a",
                "y",
                "Reuters",
                now - 3600,
            ),
            RawNews(
                "Tesla deliveries miss forecasts",
                "https://www.cnbc.com/b",
                "y",
                "CNBC",
                now - 3000,
            ),
        ],
        symbol="TSLA",
        now=now,
    )
    pairs = conflicting(judged)
    assert len(pairs) == 1
    report = assess(
        parse_symbol("TSLA"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN, symbol="TSLA")],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
        news=judged,
    )
    news_conflicts = [c for c in report.conflicts if c.kind == "news"]
    assert news_conflicts and not news_conflicts[0].blocking
    # Publisher names come from the feed, so they are shown as fenced data.
    sources = {item["source"] for item in news_conflicts[0].items}
    assert sources == {"<<<Reuters>>>", "<<<CNBC>>>"}
    assert report.ok and report.size_factor <= 0.75
    assert checks(report)["news_agree"] == "warning"


# ------------------------------------------------------------ providers


@pytest.mark.asyncio
async def test_exchange_feeds_give_real_bid_and_ask():
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.exchange.coinbase.com":
            assert request.url.path == "/products/BTC-USD/ticker"
            return httpx.Response(
                200,
                json={
                    "ask": "100.02",
                    "bid": "100.00",
                    "price": "100.01",
                    "volume": "5000",
                    "time": "2026-10-16T09:30:58.108242196Z",
                },
            )
        if request.url.host == "api.kraken.com":
            pair = request.url.params["pair"]
            if pair != "XBTUSD":
                return httpx.Response(
                    200, json={"error": ["EQuery:Unknown asset pair"]}
                )
            if request.url.path.endswith("/Spread"):
                return httpx.Response(
                    200,
                    json={
                        "error": [],
                        "result": {
                            "XXBTZUSD": [
                                [1_799_999_990, "99.97", "100.04"],
                                [1_799_999_995, "99.98", "100.03"],
                            ],
                            "last": 1_799_999_995,
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "error": [],
                    "result": {
                        "XXBTZUSD": {
                            "a": ["100.03", "1", "1.000"],
                            "b": ["99.99", "1", "1.000"],
                            "c": ["100.00", "0.1"],
                            "v": ["10", "250.5"],
                        }
                    },
                },
            )
        return httpx.Response(404)

    web = Web(transport=httpx.MockTransport(answer), attempts=1)
    books = OrderBooks(web, wall=lambda: 1_800_000_000.0)
    try:
        coinbase, kraken = await books.snapshots("BTC")
        assert coinbase.provider == "Coinbase Exchange"
        assert coinbase.bid == 100.0 and coinbase.ask == 100.02
        assert coinbase.timestamp == pytest.approx(
            datetime(2026, 10, 16, 9, 30, 58, 108242, tzinfo=UTC).timestamp()
        )
        assert kraken.provider == "Kraken" and kraken.volume == 250.5
        assert kraken.received_at == 1_800_000_000.0
        # Kraken's bid and ask come from its spread feed, with their time.
        assert kraken.timestamp == 1_799_999_995 and kraken.stamped
        assert kraken.bid == 99.98 and kraken.ask == 100.03
        with pytest.raises(ServiceError):
            await books.kraken("NOPE")
    finally:
        await web.aclose()


RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>Apple unveils new chip</title>
<link>https://finance.yahoo.com/news/apple-chip</link>
<pubDate>Thu, 15 Oct 2026 18:00:14 +0000</pubDate></item>
<item><title>Undated item</title><link>https://finance.yahoo.com/news/x</link>
<pubDate>sometime</pubDate></item>
<item><title></title><link>https://finance.yahoo.com/news/empty</link></item>
</channel></rss>"""


@pytest.mark.asyncio
async def test_dated_news_feeds_and_what_failed():
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.host == "asx.api.markitdigital.com":
            assert request.url.path.endswith("/companies/bhp/announcements")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [
                            {
                                "date": "2026-10-14T05:31:59.000Z",
                                "documentKey": "2924-1",
                                "headline": "Quarterly activities report",
                                "isPriceSensitive": True,
                                "url": "",
                            },
                            {"headline": "", "date": "2026-10-14T05:31:59.000Z"},
                        ]
                    }
                },
            )
        if request.url.host == "feeds.finance.yahoo.com":
            if request.url.params["s"] == "BHP.AX":
                return httpx.Response(503, text="down")
            return httpx.Response(200, content=RSS)
        return httpx.Response(404)

    web = Web(transport=httpx.MockTransport(answer), attempts=1)
    feeds = NewsFeeds(web)
    try:
        found, problems = await feeds.for_instrument(parse_symbol("BHP.AX"))
        assert [item.headline for item in found] == ["Quarterly activities report"]
        [asx] = found
        assert asx.official and asx.price_sensitive and asx.document == "2924-1"
        assert asx.published_at == seconds_from_iso("2026-10-14T05:31:59.000Z")
        assert asx.url.startswith("https://www.asx.com.au/")
        assert len(problems) == 1 and "Yahoo Finance news" in problems[0]

        apple, problems = await feeds.for_instrument(parse_symbol("AAPL"))
        assert not problems
        assert [item.headline for item in apple] == [
            "Apple unveils new chip",
            "Undated item",
        ]
        assert apple[0].published_at is not None and apple[1].published_at is None
    finally:
        await web.aclose()
    with pytest.raises(ServiceError):
        parse_rss(b"<html>not rss", provider="Yahoo Finance")


# ------------------------------------------------------------ quality checks


def test_good_data_passes_with_its_sources_recorded():
    btc = parse_symbol("BTC")
    report = assess(
        btc,
        now=US_OPEN,
        snapshots=[
            snap(US_OPEN),
            snap(US_OPEN, provider="Kraken", last=100.02),
            snap(
                US_OPEN, provider="Yahoo Finance", kind="aggregator", bid=None, ask=None
            ),
        ],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
        news=dated_news(US_OPEN),
    )
    assert report.ok and not report.warnings, report.summary()
    assert report.score == 100 and report.size_factor == 1.0
    assert report.preferred is not None
    assert report.preferred.source_kind == "exchange"
    view = data(report.view())
    assert view["ok"] is True and len(view["snapshots"]) == 3
    assert json.dumps(view)


def test_stale_or_untimed_prices_block_a_new_trade():
    btc = parse_symbol("BTC")
    stale = assess(
        btc,
        now=US_OPEN,
        snapshots=[snap(US_OPEN, age=600)],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
    )
    assert checks(stale)["fresh"] == "blocking"
    assert not stale.ok and "old" in stale.summary()

    untimed = assess(
        btc,
        now=US_OPEN,
        snapshots=[snap(US_OPEN, age=None)],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
    )
    assert checks(untimed)["fresh"] == "blocking"

    nothing = assess(
        btc, now=US_OPEN, snapshots=[], daily=daily(US_OPEN), limits=LIMITS, live=False
    )
    assert checks(nothing)["price"] == "blocking" and nothing.score <= 50


def test_delayed_prices_are_paper_only_and_labelled():
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
    )
    paper = assess(
        bhp,
        now=ASX_OPEN,
        snapshots=[yahoo],
        daily=daily(ASX_OPEN, price=45.0),
        limits=LIMITS,
        live=False,
        news=dated_news(ASX_OPEN, "BHP.AX"),
    )
    assert paper.ok, paper.summary()
    levels = checks(paper)
    assert levels["fresh"] == "ok" and levels["realtime"] == "warning"
    assert levels["bid_ask"] == "warning"
    assert paper.size_factor < 1.0

    live = assess(
        bhp,
        now=ASX_OPEN,
        snapshots=[yahoo],
        daily=daily(ASX_OPEN, price=45.0),
        limits=LIMITS,
        live=True,
        account_at=ASX_OPEN - 10,
    )
    levels = checks(live)
    assert levels["realtime"] == "blocking" and levels["bid_ask"] == "blocking"
    assert not live.ok

    strict = assess(
        bhp,
        now=ASX_OPEN,
        snapshots=[yahoo],
        daily=daily(ASX_OPEN, price=45.0),
        limits=LIMITS.model_copy(update={"allow_delayed_in_paper": False}),
        live=False,
    )
    assert checks(strict)["realtime"] == "blocking"


def test_a_wide_spread_blocks():
    report = assess(
        parse_symbol("BTC"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN, bid=99.0, ask=101.0)],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
    )
    spread = next(check for check in report.checks if check.name == "spread")
    assert spread.level == "blocking"
    assert spread.measured == pytest.approx(2.0) and spread.limit == 0.5


def test_sources_that_disagree_are_shown_and_a_big_gap_blocks():
    btc = parse_symbol("BTC")
    small = assess(
        btc,
        now=US_OPEN,
        snapshots=[
            snap(US_OPEN),
            snap(
                US_OPEN,
                provider="Yahoo Finance",
                kind="aggregator",
                last=101.0,
                bid=None,
                ask=None,
            ),
        ],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
    )
    assert small.ok and checks(small)["sources_agree"] == "warning"
    [conflict] = small.conflicts
    assert conflict.preferred == "Coinbase Exchange" and conflict.size_factor == 0.5
    assert {item["source"] for item in conflict.items} == {
        "Coinbase Exchange",
        "Yahoo Finance",
    }
    assert all(item["when"] != "unknown" for item in conflict.items)

    # A different coin sharing the ticker shows up as a huge gap.
    wrong = assess(
        btc,
        now=US_OPEN,
        snapshots=[
            snap(US_OPEN),
            snap(
                US_OPEN,
                provider="Yahoo Finance",
                kind="aggregator",
                last=0.03,
                bid=None,
                ask=None,
            ),
        ],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
    )
    assert checks(wrong)["sources_agree"] == "blocking" and not wrong.ok
    assert wrong.conflicts[0].blocking and wrong.conflicts[0].preferred == "none"

    # Delayed and real-time prices, or different currencies, aren't compared.
    apart = assess(
        btc,
        now=US_OPEN,
        snapshots=[
            snap(US_OPEN),
            snap(US_OPEN, provider="Yahoo", delayed=20, last=90.0, age=1300),
            snap(
                US_OPEN,
                provider="AUD broker",
                kind="broker",
                currency="AUD",
                last=150.0,
            ),
        ],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
    )
    assert not apart.conflicts


def test_symbols_markets_and_holidays():
    with pytest.raises(SymbolError):
        parse_symbol("not a symbol!")
    index = assess(
        parse_symbol("^AXJO"),
        now=ASX_OPEN,
        snapshots=[snap(ASX_OPEN, symbol="^AXJO")],
        daily=daily(ASX_OPEN),
        limits=LIMITS,
        live=False,
    )
    assert checks(index)["symbol"] == "blocking"

    bhp = parse_symbol("BHP.AX")
    asx_quote = snap(ASX_OPEN, symbol="BHP.AX", kind="broker", currency="AUD")
    weekend = assess(
        bhp,
        now=SATURDAY,
        snapshots=[asx_quote],
        daily=daily(SATURDAY),
        limits=LIMITS,
        live=False,
    )
    assert checks(weekend)["market_open"] == "blocking"

    # Three hours into a weekday session and the last trade was yesterday:
    # a public holiday, or the symbol is halted.
    yesterday = snap(ASX_OPEN, symbol="BHP.AX", kind="broker", currency="AUD", age=DAY)
    holiday = assess(
        bhp,
        now=ASX_OPEN,
        snapshots=[yesterday],
        daily=daily(ASX_OPEN),
        limits=LIMITS,
        live=False,
    )
    assert checks(holiday)["traded_today"] == "blocking"
    assert "holiday" in holiday.summary()

    halted = assess(
        bhp,
        now=ASX_OPEN,
        snapshots=[
            snap(
                ASX_OPEN,
                symbol="BHP.AX",
                kind="broker",
                currency="AUD",
                notes=("halted",),
            )
        ],
        daily=daily(ASX_OPEN),
        limits=LIMITS,
        live=False,
    )
    assert checks(halted)["halt"] == "blocking"


def test_thin_trading_and_gappy_candles():
    aapl = parse_symbol("AAPL")
    quote = snap(US_OPEN, symbol="AAPL", kind="broker")
    thin = assess(
        aapl,
        now=US_OPEN,
        snapshots=[quote],
        daily=daily(US_OPEN, volume=100.0),
        limits=LIMITS,
        live=False,
    )
    assert checks(thin)["liquidity"] == "blocking"

    silent = assess(
        aapl,
        now=US_OPEN,
        snapshots=[snap(US_OPEN, symbol="AAPL", kind="broker", volume=None)],
        daily=daily(US_OPEN, volume=0.0),
        limits=LIMITS,
        live=False,
    )
    assert checks(silent)["volume"] == "blocking"

    gappy = assess(
        parse_symbol("BTC"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN)],
        daily=daily(US_OPEN, count=90, every=2),
        limits=LIMITS,
        live=False,
    )
    assert checks(gappy)["candles_complete"] == "blocking"

    short = assess(
        parse_symbol("BTC"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN)],
        daily=daily(US_OPEN, count=10),
        limits=LIMITS,
        live=False,
    )
    assert checks(short)["history"] == "blocking"

    old = assess(
        parse_symbol("BTC"),
        now=US_OPEN + 10 * DAY,
        snapshots=[snap(US_OPEN + 10 * DAY)],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
    )
    assert checks(old)["bars_recent"] == "blocking"


def test_news_dates_live_accounts_and_meme_facts():
    btc = parse_symbol("BTC")
    future = judge(
        [
            RawNews(
                "Odd story", "https://www.reuters.com/x", "y", "Reuters", US_OPEN + DAY
            )
        ],
        symbol="BTC",
        now=US_OPEN,
    )
    report = assess(
        btc,
        now=US_OPEN,
        snapshots=[snap(US_OPEN)],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
        news=future,
    )
    levels = checks(report)
    assert levels["news"] == "warning" and levels["news_dates"] == "warning"
    assert report.ok

    unsynced = assess(
        btc,
        now=US_OPEN,
        snapshots=[snap(US_OPEN)],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=True,
        account_at=None,
    )
    assert checks(unsynced)["account"] == "blocking"
    synced = assess(
        btc,
        now=US_OPEN,
        snapshots=[snap(US_OPEN)],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=True,
        account_at=US_OPEN - 30,
        platform=snap(US_OPEN, provider="Kraken", kind="broker"),
        platform_name="Kraken",
        news=dated_news(US_OPEN),
    )
    assert synced.ok, synced.summary()

    meme = assess(
        parse_symbol("DOGE"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN, symbol="DOGE")],
        daily=daily(US_OPEN),
        limits=LIMITS,
        live=False,
        meme_facts=False,
    )
    assert checks(meme)["meme_facts"] == "blocking"


def test_order_time_checks_block_buys_but_never_a_protective_sell():
    now = 1_800_000_000.0
    fresh = Quote("BTC", 100.0, "USD", now - 5, "Kraken", 99.99, 100.01)
    assert all(
        item.ok
        for item in _quote_quality(
            fresh, buying=True, live=True, now=now, max_age_s=60, spread_limit_pct=0.5
        )
    )
    wide = Quote("BTC", 100.0, "USD", now - 5, "Kraken", 99.0, 101.0)
    [_, spread] = _quote_quality(
        wide, buying=True, live=True, now=now, max_age_s=60, spread_limit_pct=0.5
    )
    assert not spread.ok and spread.blocking
    stale = Quote("BTC", 100.0, "USD", now - 600, "Kraken", 99.99, 100.01)
    [age, _] = _quote_quality(
        stale, buying=True, live=True, now=now, max_age_s=60, spread_limit_pct=0.5
    )
    assert not age.ok and age.blocking
    halted = Quote("BHP.AX", 45.0, "AUD", 0.0, "IBKR", note="halted")
    found = _quote_quality(
        halted, buying=True, live=True, now=now, max_age_s=300, spread_limit_pct=1.0
    )
    assert {item.name for item in found if not item.ok and item.blocking} == {
        "Not halted",
        "Price fresh",
        "Spread acceptable",
    }
    selling = _quote_quality(
        halted, buying=False, live=True, now=now, max_age_s=300, spread_limit_pct=1.0
    )
    assert all(item.ok or not item.blocking for item in selling)
    paper = _quote_quality(
        Quote("BTC", 100.0, "USD", now - 5, "Yahoo Finance"),
        buying=True,
        live=False,
        now=now,
        max_age_s=60,
        spread_limit_pct=0.5,
    )
    assert all(item.ok or not item.blocking for item in paper)


# ------------------------------------------------------------ follow-ups


def test_coin_turnover_is_already_in_dollars_and_unknown_turnover_blocks():
    # A $0.00001 meme coin trading $50M a day: Yahoo's coin volume is in
    # dollars, so it is not multiplied by the price again.
    cheap = assess(
        parse_symbol("PEPE"),
        now=US_OPEN,
        snapshots=[
            snap(
                US_OPEN, symbol="PEPE", last=0.00001, bid=0.0000099999, ask=0.0000100001
            )
        ],
        daily=daily(US_OPEN, price=0.00001, volume=50_000_000.0),
        limits=LIMITS,
        live=False,
    )
    turnover = next(check for check in cheap.checks if check.name == "liquidity")
    assert turnover.ok and turnover.measured == 50_000_000

    # A share's volume is in shares: turnover is volume times the close.
    shares = assess(
        parse_symbol("AAPL"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN, symbol="AAPL", kind="broker")],
        daily=daily(US_OPEN, price=200.0, volume=50_000.0),
        limits=LIMITS,
        live=False,
    )
    turnover = next(check for check in shares.checks if check.name == "liquidity")
    assert turnover.measured == 10_000_000 and turnover.ok

    # No turnover figures at all: unknown liquidity blocks (coins too).
    silent = assess(
        parse_symbol("BTC"),
        now=US_OPEN,
        snapshots=[snap(US_OPEN, volume=None)],
        daily=daily(US_OPEN, volume=0.0),
        limits=LIMITS,
        live=False,
    )
    levels = checks(silent)
    assert levels["volume"] == "warning" and levels["liquidity"] == "blocking"
    assert "unknown" in silent.summary()


def test_an_exchange_that_stopped_trading_a_coin_blocks():
    from free_claude_code.studio.trading.information import VenueStatus

    def run(venue: VenueStatus) -> str:
        report = assess(
            parse_symbol("BTC"),
            now=US_OPEN,
            snapshots=[snap(US_OPEN)],
            daily=daily(US_OPEN),
            limits=LIMITS,
            live=False,
            venue=venue,
        )
        return checks(report)["venue"]

    assert run(VenueStatus("Coinbase", "BTC", True, "online")) == "ok"
    assert run(VenueStatus("Coinbase", "BTC", False)) == "ok"
    assert run(VenueStatus("Coinbase", "BTC", True, "delisted")) == "blocking"
    assert (
        run(VenueStatus("Coinbase", "BTC", True, "online", trading_disabled=True))
        == "blocking"
    )
    assert (
        run(VenueStatus("Coinbase", "BTC", True, "online", cancel_only=True))
        == "blocking"
    )
    assert (
        run(VenueStatus("Coinbase", "BTC", True, "online", limit_only=True))
        == "warning"
    )


@pytest.mark.asyncio
async def test_coinbase_tells_whether_a_coin_trades_and_its_history():
    def answer(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/products/BTC-USD":
            return httpx.Response(
                200,
                json={
                    "id": "BTC-USD",
                    "status": "online",
                    "trading_disabled": False,
                    "cancel_only": False,
                    "limit_only": False,
                    "post_only": False,
                    "auction_mode": False,
                    "status_message": "",
                },
            )
        if path == "/products/OLD-USD":
            return httpx.Response(
                200,
                json={"id": "OLD-USD", "status": "delisted", "trading_disabled": True},
            )
        if path == "/products/BTC-USD/candles":
            assert request.url.params["granularity"] == "86400"
            # Newest first, as Coinbase sends them: [t, low, high, open, close, volume].
            return httpx.Response(
                200,
                json=[
                    [1_792_108_800, 81_000, 82_800, 81_500, 82_000, 2.0],
                    [1_792_022_400, 79_000, 82_000, 79_500, 81_500, 3.0],
                    ["bad row"],
                ],
            )
        return httpx.Response(404, json={"message": "NotFound"})

    web = Web(transport=httpx.MockTransport(answer), attempts=1)
    books = OrderBooks(web)
    try:
        btc = await books.coinbase_status("BTC")
        assert btc.listed and not btc.stopped and not btc.restricted
        old = await books.coinbase_status("OLD")
        assert old.stopped
        missing = await books.coinbase_status("NOPE")
        assert not missing.listed and not missing.stopped
        bars = await books.coinbase_daily("BTC")
        assert [bar.t for bar in bars] == [1_792_022_400, 1_792_108_800]
        # Volume in coins becomes dollars, like the other coin sources.
        assert bars[-1].v == 2.0 * 82_000 and bars[-1].c == 82_000
    finally:
        await web.aclose()


@pytest.mark.asyncio
async def test_coin_history_falls_back_to_coinbase_and_outages_are_not_remembered():
    from free_claude_code.studio.trading.data import MarketData

    yahoo_up = {"value": False}

    def answer(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host.endswith("finance.yahoo.com"):
            if not yahoo_up["value"]:
                return httpx.Response(503, text="down")
            return httpx.Response(
                200,
                json={
                    "chart": {
                        "result": [
                            {
                                "meta": {"regularMarketPrice": 100.0},
                                "timestamp": [1_792_108_800],
                                "indicators": {
                                    "quote": [
                                        {
                                            "open": [99.0],
                                            "high": [101.0],
                                            "low": [98.0],
                                            "close": [100.0],
                                            "volume": [5.0],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                },
            )
        if host == "api.exchange.coinbase.com" and path.endswith("/candles"):
            if path.startswith("/products/BTC-USD"):
                return httpx.Response(
                    200, json=[[1_792_108_800, 81_000, 82_800, 81_500, 82_000, 2.0]]
                )
            return httpx.Response(404, json={"message": "NotFound"})
        if host == "api.coingecko.com":
            return httpx.Response(503, text="down")
        return httpx.Response(404, json={"message": "NotFound"})

    web = Web(transport=httpx.MockTransport(answer), attempts=1)
    data_ = MarketData(web)
    try:
        btc = await data_.bars(parse_symbol("BTC"), "1d")
        assert [bar.c for bar in btc] == [82_000]

        # Nothing anywhere: the empty answer isn't kept, so once Yahoo is
        # back the next call gets real bars.
        eth = parse_symbol("ETH")
        assert await data_.bars(eth, "1d") == []
        yahoo_up["value"] = True
        assert [bar.c for bar in await data_.bars(eth, "1d")] == [100.0]

        assert await data_.venue_status(parse_symbol("AAPL")) is None
    finally:
        await web.aclose()


def make_briefing(symbol: str, price: float, volume: float):
    from free_claude_code.studio.trading.briefing import Briefing
    from free_claude_code.studio.trading.indicators import technical_brief
    from free_claude_code.studio.trading.regime import UNKNOWN
    from free_claude_code.studio.trading.research import ResearchPack

    bars = [
        Bar(
            t=int(US_OPEN - (300 - index) * DAY),
            o=price,
            h=price * 1.02,
            l=price * 0.98,
            c=price,
            v=volume,
        )
        for index in range(300)
    ]
    instrument = parse_symbol(symbol)
    return Briefing(
        instrument=instrument,
        quote=Quote(instrument.symbol, price, instrument.currency, US_OPEN, "test"),
        tech=technical_brief(bars),
        regime=UNKNOWN,
        base=None,
        research=ResearchPack(instrument.symbol),
        macro=ResearchPack("macro"),
        lessons=(),
        records={},
        setup="",
        dex=None,
        held=None,
        tags=(),
        beta=None,
        daily=tuple(bars),
    )


def adv_of(symbol: str, price: float, volume: float, qty: float) -> tuple[float, bool]:
    from free_claude_code.studio.trading.assessment import Holdings, risk_report
    from free_claude_code.studio.trading.config import DeskConfig
    from free_claude_code.studio.trading.risk import Sizing
    from free_claude_code.studio.trading.seats import Decision

    briefing = make_briefing(symbol, price, volume)
    report = risk_report(
        decision=Decision(
            action="buy",
            stop_loss=price * 0.95,
            take_profit=price * 1.15,
            p_up=0.65,
            p_target=0.6,
            confidence=0.7,
        ),
        briefing=briefing,
        sizing=Sizing(
            qty=qty, value=qty * price, at_risk=qty * price * 0.05, bound_by="risk"
        ),
        rules=None,
        holdings=Holdings(equity=1_000_000.0, positions=[], bars={}, sectors={}),
        closing={},
        weights={},
        fx=1.0,
        config=DeskConfig(),
        earnings="",
        events=[],
        now_ms=int(US_OPEN * 1000),
    )
    assert report.adv_pct is not None
    blocked = any("of a day's volume" in reason for reason in report.blockers)
    return report.adv_pct, blocked


def test_order_size_against_daily_volume_only_got_stricter():
    # An $16,000 BTC order against $1M a day: the old figure (coins against
    # dollars) said 0.00002%; the order's value says 1.6%, over the 1% limit.
    adv, blocked = adv_of("BTC", 80_000.0, 1_000_000.0, 0.2)
    assert adv == pytest.approx(1.6) and blocked
    # A cheap coin the old figure already stopped stays stopped.
    adv, blocked = adv_of("SHIB", 0.0001, 1_000_000.0, 1_000_000.0)
    assert adv == pytest.approx(100.0) and blocked
    # Shares are unchanged: shares ordered against shares traded.
    adv, blocked = adv_of("AAPL", 200.0, 1_000_000.0, 50.0)
    assert adv == pytest.approx(0.005) and not blocked
