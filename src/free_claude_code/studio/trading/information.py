"""What the desk knows before it decides, and how far each piece can be trusted.

Every price, number, headline, and account figure the seats see is one of
these items, and each carries where it came from, when it was true, whether
the source is real time or delayed, and a data-quality status. Items are
facts (a price, a volume, an announcement date, a balance), calculations
(an average, a volatility, a position size), or opinions (a seat's view):
the three are never mixed up, and an opinion is never shown as a fact.

Nothing here fetches anything; providers fill these in and quality.py
judges them.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from free_claude_code.core.json_types import JsonObject

type DataStatus = Literal[
    "ok",
    "delayed",
    "stale",
    "missing",
    "conflict",
    "duplicate",
    "unknown_source",
    "undated",
    "invalid",
]
"""ok and delayed items can be used (delayed only where the rules allow it);
the rest are kept for the record but never reach a seat as a fact."""

type InfoKind = Literal["fact", "calculation", "opinion"]
type SourceKind = Literal[
    "broker", "exchange", "official", "reputable", "aggregator", "search", "social"
]
type Sentiment = Literal["positive", "negative", "neutral", "unclear"]
type Judgement = Literal["yes", "no", "unknown"]

USABLE: frozenset[str] = frozenset({"ok", "delayed"})

ASSET_CLASS: dict[str, str] = {
    "asx": "equity",
    "us": "equity",
    "crypto": "crypto",
    "dex": "crypto",
    "index": "index",
}
EXCHANGE_TZ: dict[str, str] = {
    "asx": "Australia/Sydney",
    "us": "America/New_York",
    "crypto": "UTC",
    "dex": "UTC",
    "index": "UTC",
}

PROVIDER_DELAY_MINUTES: dict[tuple[str, str], int] = {
    ("Yahoo Finance", "asx"): 20,
}
"""Delays a provider publishes for its free data. Yahoo marks ASX prices as
delayed 20 minutes; its US share and crypto prices are near real time."""

SOURCE_RANK: dict[str, int] = {
    "broker": 6,
    "exchange": 5,
    "official": 4,
    "reputable": 3,
    "aggregator": 2,
    "search": 1,
    "social": 0,
}
"""Which source wins a disagreement (then the most recent of equals)."""


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    """One source's latest price for one symbol, exactly as it reported it."""

    provider: str
    symbol: str
    exchange: str
    asset_class: str
    currency: str
    timestamp: float | None
    """Unix seconds the price was true (the exchange's time, not ours); None
    when the source gives no time, which the quality checks treat as stale."""
    received_at: float
    exchange_tz: str
    realtime: bool
    delayed_minutes: int
    last: float | None
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    source_kind: SourceKind = "aggregator"
    notes: tuple[str, ...] = ()
    volume_unit: str = ""
    """What ``volume`` counts: "coins, 24 hours", "USD, 24 hours", or
    "shares, today" (sources differ)."""

    @property
    def mid(self) -> float | None:
        if self.bid and self.ask and self.ask >= self.bid > 0:
            return (self.bid + self.ask) / 2
        return self.last

    @property
    def spread_pct(self) -> float | None:
        """(ask - bid) / mid, in percent; None without both sides."""
        if not self.bid or not self.ask or self.ask < self.bid:
            return None
        mid = (self.bid + self.ask) / 2
        return (self.ask - self.bid) / mid * 100 if mid > 0 else None

    def age_s(self, now: float) -> float | None:
        if self.timestamp is None:
            return None
        return max(0.0, now - self.timestamp)

    def view(self, now: float | None = None) -> JsonObject:
        found: JsonObject = {
            "provider": self.provider,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "asset_class": self.asset_class,
            "currency": self.currency,
            "timestamp": self.timestamp,
            "received_at": self.received_at,
            "exchange_tz": self.exchange_tz,
            "realtime": self.realtime,
            "delayed_minutes": self.delayed_minutes,
            "last": self.last,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "volume_unit": self.volume_unit,
            "spread_pct": round(self.spread_pct, 4)
            if self.spread_pct is not None
            else None,
            "source_kind": self.source_kind,
            "notes": list(self.notes),
        }
        if now is not None:
            age = self.age_s(now)
            found["age_s"] = round(age, 1) if age is not None else None
        return found


@dataclass(frozen=True, slots=True)
class VenueStatus:
    """Whether an exchange trades a symbol right now, as it reports it."""

    venue: str
    symbol: str
    listed: bool
    status: str = ""
    trading_disabled: bool = False
    cancel_only: bool = False
    limit_only: bool = False
    post_only: bool = False
    auction: bool = False
    message: str = ""

    @property
    def stopped(self) -> bool:
        """Listed, but not taking normal orders (disabled, cancel-only, or
        not online): a coin being delisted or halted looks like this."""
        return self.listed and (
            self.trading_disabled
            or self.cancel_only
            or self.status not in {"online", ""}
        )

    @property
    def restricted(self) -> bool:
        """Listed and trading, but only with limit or post-only orders, or in
        an auction: a thin or protected market."""
        return (
            self.listed
            and not self.stopped
            and (self.limit_only or self.post_only or self.auction)
        )

    def view(self) -> JsonObject:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "listed": self.listed,
            "status": self.status,
            "trading_disabled": self.trading_disabled,
            "cancel_only": self.cancel_only,
            "limit_only": self.limit_only,
            "post_only": self.post_only,
            "auction": self.auction,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class InfoItem:
    """One fact, calculation, or opinion, with its provenance."""

    kind: InfoKind
    topic: str
    """price, volume, volatility, trend, levels, index, sector, announcement,
    earnings, dividend, rates, calendar, crypto, portfolio, cash, risk,
    trades, base_rate, or quality."""
    label: str
    value: float | int | str | bool | None
    source: str
    """The provider, or "FCC calculation" for plain-code arithmetic."""
    as_of: float | None
    """Unix seconds the value was true; None when the source doesn't say."""
    unit: str = ""
    source_id: str = ""
    """A link, a document key, or the inputs a calculation used."""
    symbol: str = ""
    currency: str = ""
    realtime: bool | None = None
    status: DataStatus = "ok"
    note: str = ""
    ref: str = ""
    """Its number in the evidence pack (F1, C4, ...), set when the pack is built."""

    @property
    def usable(self) -> bool:
        return self.status in USABLE

    def with_ref(self, ref: str) -> InfoItem:
        return InfoItem(
            self.kind,
            self.topic,
            self.label,
            self.value,
            self.source,
            self.as_of,
            self.unit,
            self.source_id,
            self.symbol,
            self.currency,
            self.realtime,
            self.status,
            self.note,
            ref,
        )

    def text(self) -> str:
        value = self.value
        if isinstance(value, float):
            shown = f"{value:,.6g}"
        else:
            shown = "unknown" if value is None else str(value)
        unit = f" {self.unit}" if self.unit else ""
        flag = "" if self.status == "ok" else f" [{self.status}]"
        lead = f"{self.label}: " if self.label else ""
        return f"{lead}{shown}{unit}{flag}"

    def view(self) -> JsonObject:
        return {
            "ref": self.ref,
            "kind": self.kind,
            "topic": self.topic,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "source_id": self.source_id,
            "symbol": self.symbol,
            "currency": self.currency,
            "as_of": self.as_of,
            "realtime": self.realtime,
            "status": self.status,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class NewsItem:
    """One headline or announcement, judged in plain code (not by a model)."""

    headline: str
    source: str
    """The publisher (ASX, Reuters, ...) or the provider when unknown."""
    source_kind: SourceKind
    url: str
    published_at: float | None
    """Unix seconds; None when the source gives no publication time."""
    fetched_at: float
    symbol: str
    sentiment: Sentiment = "unclear"
    confirmed: bool = False
    priced_in: Judgement = "unknown"
    material: Judgement = "unknown"
    price_sensitive: bool | None = None
    """ASX's own price-sensitive flag, where the exchange gives it."""
    status: DataStatus = "ok"
    note: str = ""
    duplicates: int = 0
    """How many copies of the same story were folded into this one."""
    also_from: tuple[tuple[str, SourceKind], ...] = ()
    """The publishers (and their kinds) of the copies folded into this one."""
    document: str = ""
    """The source's own id for it (an ASX document key), when it gives one."""
    ref: str = ""

    @property
    def key(self) -> str:
        return news_key(self.headline)

    @property
    def usable(self) -> bool:
        return self.status in USABLE

    def text(self) -> str:
        when = _iso(self.published_at) if self.published_at is not None else "undated"
        flags = [
            self.sentiment,
            "confirmed" if self.confirmed else "unconfirmed",
            f"material: {self.material}",
            f"priced in: {self.priced_in}",
        ]
        if self.price_sensitive:
            flags.append("ASX price-sensitive")
        return f'"{self.headline}" ({self.source}, {when}; {", ".join(flags)})'

    def view(self) -> JsonObject:
        return {
            "ref": self.ref,
            "headline": self.headline,
            "source": self.source,
            "source_kind": self.source_kind,
            "url": self.url,
            "published_at": self.published_at,
            "fetched_at": self.fetched_at,
            "symbol": self.symbol,
            "sentiment": self.sentiment,
            "confirmed": self.confirmed,
            "priced_in": self.priced_in,
            "material": self.material,
            "price_sensitive": self.price_sensitive,
            "status": self.status,
            "note": self.note,
            "duplicates": self.duplicates,
            "also_from": [
                {"source": source, "kind": kind} for source, kind in self.also_from
            ],
            "document": self.document,
        }


@dataclass(frozen=True, slots=True)
class Conflict:
    """Two sources disagree: both are shown, one is preferred, and why."""

    kind: Literal["price", "news", "seat", "data"]
    subject: str
    items: tuple[JsonObject, ...]
    """Each side: its source, value, and timestamp."""
    preferred: str
    """The source used, or "none" when the trade should not go ahead."""
    reason: str
    confidence_penalty: float = 0.0
    """Taken off the final confidence (0-100 points)."""
    size_factor: float = 1.0
    blocking: bool = False

    def view(self) -> JsonObject:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "items": list(self.items),
            "preferred": self.preferred,
            "reason": self.reason,
            "confidence_penalty": self.confidence_penalty,
            "size_factor": self.size_factor,
            "blocking": self.blocking,
        }

    def line(self) -> str:
        sides = "; ".join(
            f"{item.get('source')}: {item.get('value')} ({item.get('when', '?')})"
            for item in self.items
        )
        action = "blocks the trade" if self.blocking else f"uses {self.preferred}"
        return f"{self.kind} conflict on {self.subject}: {sides} — {action} ({self.reason})"


_WORDS = re.compile(r"[a-z0-9]+")


def news_key(headline: str) -> str:
    """The same story told twice reads the same once punctuation, case, and
    the trailing "- Publisher" are gone."""
    text = headline.lower()
    text = re.sub(r"\s[-\u2013|]\s[^-\u2013|]{2,40}$", "", text)
    words = _WORDS.findall(text)
    return hashlib.sha1(" ".join(words).encode()).hexdigest()[:16]


def words_of(text: str) -> set[str]:
    return {word for word in _WORDS.findall(text.lower()) if len(word) > 2}


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def iso(seconds: float | None) -> str:
    return _iso(seconds) if seconds is not None else "unknown"


def seconds_from_iso(value: object) -> float | None:
    """Unix seconds from an ISO 8601 time (any fraction of a second, Z or an
    offset); None when it's missing or unreadable, never a guess."""
    if not isinstance(value, str) or not value:
        return None
    try:
        found = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return found.timestamp() if found.tzinfo is not None else None


@dataclass(slots=True)
class Refs:
    """Hands out evidence numbers: F (facts), C (calculations), N (news)."""

    counts: dict[str, int] = field(default_factory=dict)

    def next(self, prefix: str) -> str:
        self.counts[prefix] = self.counts.get(prefix, 0) + 1
        return f"{prefix}{self.counts[prefix]}"
