"""Headlines judged in plain code: who said it, when, whether it matters, and
whether the price has already moved on it.

- Source: official (the exchange, a regulator, a central bank), reputable
  news, aggregators, search results, or social media. Social-media claims are
  never treated as confirmed, whoever repeats them.
- Confirmed: official sources are; a reputable outlet's story is once another
  independent reputable or official source tells the same story within two
  days; everything else is unconfirmed.
- Sentiment: positive, negative, neutral (routine filings), or unclear (mixed
  or no clear words). Keyword-based and labelled as such; the Researcher adds
  its own reading as an opinion.
- Material: the exchange's price-sensitive flag, or words like results,
  guidance, takeover, capital raising, trading halt; routine filings are not.
- Priced in: compared with the price since publication (a move of an ATR in
  the story's direction, or a story days old, has likely been absorbed).
- Dated: a story with no publication time, from the future, or older than
  the cut-off never becomes a fact.
- Duplicates: the same story from several places is kept once (the most
  reliable source, the earliest time), with a count.

Nothing here can make the desk trade; news only informs the seats and the
checks, and the desk never trades on a headline alone.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from .indicators import Bar
from .information import (
    SOURCE_RANK,
    Copy,
    DataStatus,
    Judgement,
    NewsItem,
    Sentiment,
    SourceKind,
    words_of,
)

MAX_AGE_DAYS = 14.0
FUTURE_SLACK_S = 300.0
CONFIRM_WINDOW_S = 2 * 86_400.0
SAME_STORY = 0.8
"""Shared-word share (Jaccard) at which two headlines tell the same story."""

OFFICIAL_HOSTS = (
    "asx.com.au",
    "markitdigital.com",
    "sec.gov",
    "federalreserve.gov",
    "rba.gov.au",
    "abs.gov.au",
    "bls.gov",
    "asic.gov.au",
)
REPUTABLE_HOSTS = (
    "reuters.com",
    "bloomberg.com",
    "afr.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "marketwatch.com",
    "abc.net.au",
    "smh.com.au",
    "theaustralian.com.au",
    "apnews.com",
    "barrons.com",
    "coindesk.com",
    "theblock.co",
    "nytimes.com",
    "economist.com",
    "theguardian.com",
    "bbc.co.uk",
    "bbc.com",
)
AGGREGATOR_HOSTS = (
    "finance.yahoo.com",
    "yahoo.com",
    "investing.com",
    "marketscreener.com",
    "benzinga.com",
    "seekingalpha.com",
    "fool.com",
    "fool.com.au",
    "news.google.com",
    "msn.com",
    "marketindex.com.au",
)
SOCIAL_HOSTS = (
    "reddit.com",
    "x.com",
    "twitter.com",
    "stocktwits.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "t.me",
    "telegram.org",
    "discord.com",
    "discord.gg",
    "facebook.com",
    "instagram.com",
    "hotcopper.com.au",
    "medium.com",
    "substack.com",
)

_POSITIVE = (
    "beat",
    "beats",
    "record",
    "surge",
    "surges",
    "soar",
    "soars",
    "jump",
    "jumps",
    "rally",
    "rallies",
    "upgrade",
    "upgraded",
    "outperform",
    "raises guidance",
    "raised guidance",
    "gain",
    "gains",
    "approval",
    "approved",
    "wins",
    "awarded",
    "partnership",
    "buyback",
    "strong",
    "growth",
    "expands",
    "breakthrough",
    "all-time high",
    "profit up",
    "higher",
    "rises",
    "climbs",
)
_NEGATIVE = (
    "miss",
    "misses",
    "missed",
    "plunge",
    "plunges",
    "fall",
    "falls",
    "drop",
    "drops",
    "slump",
    "slumps",
    "downgrade",
    "downgraded",
    "cuts guidance",
    "cut guidance",
    "warns",
    "warning",
    "loss",
    "losses",
    "lawsuit",
    "sued",
    "probe",
    "investigation",
    "recall",
    "halt",
    "halted",
    "suspended",
    "suspension",
    "delist",
    "delisted",
    "bankruptcy",
    "administration",
    "default",
    "hack",
    "hacked",
    "exploit",
    "breach",
    "fraud",
    "layoffs",
    "resigns",
    "weak",
    "decline",
    "declines",
    "lower",
    "tumble",
    "tumbles",
    "crash",
    "sinks",
)
_MATERIAL = (
    "results",
    "earnings",
    "profit",
    "revenue",
    "guidance",
    "outlook",
    "acquisition",
    "acquire",
    "takeover",
    "merger",
    "scheme",
    "capital raising",
    "placement",
    "entitlement offer",
    "trading halt",
    "suspension",
    "dividend",
    "buyback",
    "downgrade",
    "upgrade",
    "lawsuit",
    "investigation",
    "recall",
    "approval",
    "fda",
    "delist",
    "bankruptcy",
    "administration",
    "hack",
    "exploit",
    "listing",
    "etf",
    "resigns",
    "ceo",
    "contract",
)
_ROUTINE = (
    "appendix",
    "record date",
    "cessation of securities",
    "unquoted securities",
    "change of director",
    "director's interest",
    "cleansing notice",
    "application for quotation",
    "becoming a substantial holder",
    "ceasing to be a substantial holder",
    "change in substantial holding",
    "notification of buy-back",
    "update - notification",
)


_TURNING = frozenset(
    {
        *(word for word in _POSITIVE + _NEGATIVE if " " not in word),
        "accepted",
        "accepts",
        "rejected",
        "rejects",
        "approves",
        "denied",
        "denies",
        "not",
        "no",
        "yes",
        "up",
        "down",
        "raise",
        "raises",
        "raised",
        "cut",
        "cuts",
        "won",
        "lost",
        "loses",
        "buy",
        "sell",
        "bullish",
        "bearish",
        "rise",
        "resumes",
        "resumed",
        "above",
        "below",
    }
)
"""Words whose swap turns a story into its opposite: headlines that differ
by one of these are different stories, never copies."""


@dataclass(frozen=True, slots=True)
class RawNews:
    """A headline as a provider gave it, before any judging."""

    headline: str
    url: str
    provider: str
    """Where FCC got it: ASX announcements, Yahoo Finance RSS, web search."""
    source: str = ""
    """The publisher, when the provider names it."""
    published_at: float | None = None
    price_sensitive: bool | None = None
    official: bool = False
    """True when the provider is the exchange itself."""
    document: str = ""
    """The provider's own id for it (an ASX document key)."""


def source_kind(url: str, *, official: bool = False) -> SourceKind:
    if official:
        return "official"
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        # A malformed link (e.g. a broken IPv6 address) names no known site.
        host = ""
    host = host.lower().removeprefix("www.")

    def matches(hosts: tuple[str, ...]) -> bool:
        return any(host == known or host.endswith(f".{known}") for known in hosts)

    if matches(SOCIAL_HOSTS):
        return "social"
    if matches(OFFICIAL_HOSTS):
        return "official"
    if matches(REPUTABLE_HOSTS):
        return "reputable"
    if matches(AGGREGATOR_HOSTS):
        return "aggregator"
    return "search"


def _count(text: str, words: tuple[str, ...]) -> int:
    lowered = f" {text.lower()} "
    return sum(
        1
        for word in words
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered)
    )


def sentiment_of(headline: str) -> Sentiment:
    if _count(headline, _ROUTINE):
        return "neutral"
    good = _count(headline, _POSITIVE)
    bad = _count(headline, _NEGATIVE)
    if good > bad:
        return "positive"
    if bad > good:
        return "negative"
    return "unclear"


def material_of(headline: str, price_sensitive: bool | None) -> Judgement:
    if price_sensitive:
        return "yes"
    if _count(headline, _ROUTINE):
        return "no"
    if _count(headline, _MATERIAL):
        return "yes"
    if price_sensitive is False:
        return "no"
    return "unknown"


def priced_in(
    published_at: float | None,
    sentiment: Sentiment,
    *,
    now: float,
    bars: Sequence[Bar],
    atr: float | None,
) -> tuple[Judgement, str]:
    """Has the price already moved on this story? Uses only bars that started
    after it was published (never anything later than now)."""
    if published_at is None:
        return "unknown", "no publication time"
    age_days = (now - published_at) / 86_400
    after = [bar for bar in bars if published_at <= bar.t <= now]
    if not after or not atr or atr <= 0:
        if age_days > 3:
            return "yes", f"{age_days:.0f} days old; the market has had time"
        return "unknown", "no prices since it came out"
    move = after[-1].c - after[0].o
    in_atr = move / atr
    leaning = 1 if sentiment == "positive" else -1 if sentiment == "negative" else 0
    if leaning and in_atr * leaning >= 1.0:
        return "yes", f"price moved {in_atr:+.1f} ATR its way since publication"
    if age_days > 3:
        return "yes", f"{age_days:.0f} days old; the market has had time"
    if age_days < 2 / 24 and abs(in_atr) < 0.3:
        return "no", f"fresh, and the price has moved only {in_atr:+.1f} ATR"
    return "unknown", f"price moved {in_atr:+.1f} ATR since publication"


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def judge(
    raw: Sequence[RawNews],
    *,
    symbol: str,
    now: float,
    bars: Sequence[Bar] = (),
    atr: float | None = None,
    max_age_days: float = MAX_AGE_DAYS,
) -> list[NewsItem]:
    """Every raw headline judged, de-duplicated, and confirmed where it can be.
    Items that are undated, stale, from the future, or from no known source are
    kept (marked) for the record; only usable ones reach the seats."""
    judged: list[NewsItem] = []
    for item in raw:
        headline = " ".join(item.headline.split())[:300]
        if not headline:
            continue
        kind = source_kind(item.url, official=item.official)
        publisher = item.source or item.provider
        status: DataStatus = "ok"
        note = ""
        if not publisher and not item.url:
            status, note = "unknown_source", "no source or link"
        elif item.published_at is None:
            status, note = "undated", "the source gives no publication time"
        elif item.published_at > now + FUTURE_SLACK_S:
            status, note = "invalid", "publication time is in the future"
        elif now - item.published_at > max_age_days * 86_400:
            status, note = "stale", f"older than {max_age_days:g} days"
        sentiment = sentiment_of(headline)
        reflected: Judgement = "unknown"
        why = ""
        if status == "ok":
            reflected, why = priced_in(
                item.published_at, sentiment, now=now, bars=bars, atr=atr
            )
        judged.append(
            NewsItem(
                headline=headline,
                source=publisher,
                source_kind=kind,
                url=item.url,
                published_at=item.published_at,
                fetched_at=now,
                symbol=symbol,
                sentiment=sentiment,
                confirmed=kind == "official",
                priced_in=reflected,
                material=material_of(headline, item.price_sensitive),
                price_sensitive=item.price_sensitive,
                status=status,
                note="; ".join(part for part in (note, why) if part),
                document=item.document,
            )
        )
    return _confirm(_dedupe(judged))


def _better(a: NewsItem, b: NewsItem) -> NewsItem:
    """The more reliable of two copies; the earlier one of equals."""
    rank_a, rank_b = SOURCE_RANK[a.source_kind], SOURCE_RANK[b.source_kind]
    if rank_a != rank_b:
        return a if rank_a > rank_b else b
    if a.usable != b.usable:
        return a if a.usable else b
    if a.published_at is not None and b.published_at is not None:
        return a if a.published_at <= b.published_at else b
    return a if a.published_at is not None else b


def _same_story(a: NewsItem, b: NewsItem) -> bool:
    """Near-identical wording, and no word that turns one into the other
    ("accepted" vs "rejected", "beats" vs "misses")."""
    if a.key == b.key:
        return True
    words_a, words_b = words_of(a.headline), words_of(b.headline)
    if _jaccard(words_a, words_b) < SAME_STORY:
        return False
    return not (words_a ^ words_b) & _TURNING


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    kept: list[NewsItem] = []
    for item in items:
        for index, other in enumerate(kept):
            if not _same_story(item, other):
                continue
            best = _better(other, item)
            folded = item if best is other else other
            copies = {
                *other.also_from,
                *item.also_from,
                Copy(
                    folded.source,
                    folded.source_kind,
                    folded.published_at,
                    folded.usable,
                ),
            }
            kept[index] = replace(
                best,
                duplicates=other.duplicates + item.duplicates + 1,
                also_from=tuple(
                    sorted(
                        (copy for copy in copies if copy.source != best.source),
                        key=lambda copy: (copy.source, copy.published_at or 0.0),
                    )
                ),
            )
            break
        else:
            kept.append(item)
    return kept


def _confirm(items: list[NewsItem]) -> list[NewsItem]:
    """A story is confirmed when an independent reputable or official
    source told the same story (near-identical wording, folded in as a copy),
    and that copy was itself dated, fresh, and within two days of it. Social
    media is never confirmed, and a stale or undated copy confirms nothing."""
    found: list[NewsItem] = []
    for item in items:
        if item.confirmed or item.source_kind == "social" or not item.usable:
            found.append(item)
            continue
        retold = any(
            copy.usable
            and copy.kind in {"official", "reputable"}
            and copy.source != item.source
            and copy.published_at is not None
            and item.published_at is not None
            and abs(copy.published_at - item.published_at) <= CONFIRM_WINDOW_S
            for copy in item.also_from
        )
        found.append(replace(item, confirmed=True) if retold else item)
    return found


def _close_in_time(a: NewsItem, b: NewsItem) -> bool:
    if a.published_at is None or b.published_at is None:
        return False
    return abs(a.published_at - b.published_at) <= CONFIRM_WINDOW_S


def conflicting(items: Sequence[NewsItem]) -> list[tuple[NewsItem, NewsItem]]:
    """Usable stories about the same thing that point opposite ways."""
    usable = [
        item
        for item in items
        if item.usable and item.sentiment in {"positive", "negative"}
    ]
    pairs: list[tuple[NewsItem, NewsItem]] = []
    for index, item in enumerate(usable):
        for other in usable[index + 1 :]:
            if item.sentiment == other.sentiment or item.source == other.source:
                continue
            shared = words_of(item.headline) & words_of(other.headline)
            topical = len(shared) >= 2 and _close_in_time(item, other)
            if topical:
                pairs.append((item, other))
    return pairs
