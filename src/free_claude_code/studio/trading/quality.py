"""Is what the desk knows good enough to trade on?

Plain code, run before every debate. Each check records what it measured and
the limit it was held to:

- the symbol is tradable and its market is open (with no trade since the
  open, the market is treated as closed for a holiday, or the symbol halted);
- there is a price, it is fresh for its market, and it is real time (delayed
  prices are allowed in paper only, and labelled);
- a bid and ask exist (required live; paper assumes a spread and says so)
  and the spread is inside the limit;
- independent sources agree on the price (a big gap blocks: it is often a
  different coin or share sharing the ticker);
- there is trading volume and enough daily turnover;
- the daily candles are recent and not full of gaps;
- headlines carry valid dates, and stories that contradict each other are
  shown side by side;
- the live account was read recently; a meme coin has its liquidity facts.

A failing critical check means no new trade, with the reason recorded; held
positions are still watched and managed. Warnings lower the data-quality
score and the size. Missing information is reported as missing, never filled
in.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

from free_claude_code.core.json_types import JsonObject

from .config import DataQualityLimits
from .indicators import Bar
from .information import (
    SOURCE_RANK,
    Conflict,
    NewsItem,
    QuoteSnapshot,
    VenueStatus,
    fence,
    iso,
)
from .instruments import Instrument
from .news import conflicting
from .sessions import new_york_offset, session, sydney_offset

MIN_DAILY_BARS = 30
LIQUIDITY_BARS = 20
COMPARE_WINDOW_S = 180.0
"""Two real-time prices are compared only when taken this close together."""


def profile_of(instrument: Instrument) -> str:
    """The rule set an instrument trades under: us, asx, crypto, or meme."""
    return "meme" if instrument.meme else instrument.market


@dataclass(frozen=True, slots=True)
class QualityCheck:
    name: str
    label: str
    ok: bool
    critical: bool
    measured: float | str | None = None
    limit: float | str | None = None
    unit: str = ""
    detail: str = ""

    @property
    def level(self) -> str:
        if self.ok:
            return "ok"
        return "blocking" if self.critical else "warning"

    def line(self) -> str:
        return f"{self.label}: {self.detail}" if self.detail else self.label

    def view(self) -> JsonObject:
        return {
            "name": self.name,
            "label": self.label,
            "ok": self.ok,
            "critical": self.critical,
            "level": self.level,
            "measured": self.measured,
            "limit": self.limit,
            "unit": self.unit,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class QualityReport:
    symbol: str
    at: float
    live: bool
    checks: tuple[QualityCheck, ...]
    preferred: QuoteSnapshot | None = None
    """The price the desk works from: the most reliable fresh source."""
    snapshots: tuple[QuoteSnapshot, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    news: tuple[NewsItem, ...] = field(default=(), repr=False)
    sizing: QuoteSnapshot | None = None
    """The price the order would be sized and priced from."""

    def with_check(self, check: QualityCheck) -> QualityReport:
        return replace(self, checks=(*self.checks, check))

    @property
    def blocking(self) -> tuple[QualityCheck, ...]:
        return tuple(check for check in self.checks if check.level == "blocking")

    @property
    def warnings(self) -> tuple[QualityCheck, ...]:
        return tuple(check for check in self.checks if check.level == "warning")

    @property
    def ok(self) -> bool:
        return not self.blocking

    @property
    def score(self) -> int:
        """0-100: how much the data can be trusted (used in the scorecard)."""
        penalty = 30 * len(self.blocking) + 10 * len(self.warnings)
        penalty += sum(
            conflict.confidence_penalty
            for conflict in self.conflicts
            if not conflict.blocking
        )
        return max(0, min(100, round(100 - penalty)))

    @property
    def size_factor(self) -> float:
        """What warnings and conflicts leave of the normal size."""
        if self.blocking:
            return 0.0
        factor = 0.9 ** len(self.warnings)
        for conflict in self.conflicts:
            factor = min(factor, conflict.size_factor)
        return round(max(0.25, factor), 3)

    def summary(self) -> str:
        if self.blocking:
            return "Data not good enough: " + "; ".join(
                check.line() for check in self.blocking
            )
        if self.warnings:
            return "Data usable with warnings: " + "; ".join(
                check.line() for check in self.warnings
            )
        return "Data checks passed."

    def view(self) -> JsonObject:
        return {
            "symbol": self.symbol,
            "at": self.at,
            "live": self.live,
            "ok": self.ok,
            "score": self.score,
            "size_factor": self.size_factor,
            "summary": self.summary(),
            "checks": [check.view() for check in self.checks],
            "preferred": self.preferred.view(self.at)
            if self.preferred is not None
            else None,
            "snapshots": [snapshot.view(self.at) for snapshot in self.snapshots],
            "conflicts": [conflict.view() for conflict in self.conflicts],
            "sizing": self.sizing.view(self.at) if self.sizing is not None else None,
        }


def assess(
    instrument: Instrument,
    *,
    now: float,
    snapshots: Sequence[QuoteSnapshot],
    daily: Sequence[Bar],
    limits: DataQualityLimits,
    live: bool,
    news: Sequence[NewsItem] = (),
    account_at: float | None = None,
    meme_facts: bool | None = None,
    meme_facts_note: str = "",
    venue: VenueStatus | None = None,
    sizing: QuoteSnapshot | None = None,
    platform: QuoteSnapshot | None = None,
    platform_name: str = "",
) -> QualityReport:
    """Every check for one symbol at ``now`` (Unix seconds).

    ``account_at`` is when the live account was last read (paper needs none);
    ``meme_facts`` is False when a meme coin's liquidity facts are missing
    (``meme_facts_note`` says why, when the source failed); ``venue`` is
    whether Coinbase trades the coin right now; ``sizing`` is the price the
    order would be sized and priced from; ``platform`` is the live trading
    platform's own quote (live only, named ``platform_name``).
    """
    profile = profile_of(instrument)
    checks: list[QualityCheck] = []
    conflicts: list[Conflict] = []

    checks.append(
        QualityCheck(
            "symbol",
            "Symbol tradable",
            instrument.tradable,
            True,
            measured=instrument.market,
            detail=""
            if instrument.tradable
            else f"{instrument.symbol} is a {instrument.market} symbol; "
            "it can be researched but not traded",
        )
    )

    moment = datetime.fromtimestamp(now, tz=UTC)
    market = session(instrument.market, moment)
    checks.append(
        QualityCheck(
            "market_open",
            "Market open",
            market.open,
            True,
            measured=market.local,
            detail=""
            if market.open
            else f"closed; opens {iso(market.opens_at.timestamp())}"
            if market.opens_at is not None
            else "closed",
        )
    )

    priced = [snap for snap in snapshots if snap.last]
    preferred = _preferred(priced, now, limits, profile)
    checks.append(
        QualityCheck(
            "price",
            "Price available",
            preferred is not None,
            True,
            measured=len(priced),
            detail=""
            if preferred is not None
            else "no source had a price"
            + (
                f" (asked {', '.join(s.provider for s in snapshots)})"
                if snapshots
                else ""
            ),
        )
    )

    if preferred is not None:
        checks.append(_fresh(preferred, now, limits, profile))
        checks.extend(_realtime(preferred, live, limits))
        if (
            market.open
            and market.opens_at is not None
            and instrument.market != "crypto"
        ):
            checks.append(_traded_since_open(preferred, now, market.opens_at, limits))
        if any("halt" in note.lower() for note in preferred.notes):
            checks.append(
                QualityCheck(
                    "halt",
                    "Not halted",
                    False,
                    True,
                    detail=f"{preferred.provider} marks it halted",
                )
            )

    checks.extend(_bid_ask(priced, preferred, now, live, limits, profile))

    price_conflicts = _price_conflicts(priced, preferred, limits, profile)
    conflicts.extend(price_conflicts)
    if price_conflicts:
        worst = next((c for c in price_conflicts if c.blocking), price_conflicts[0])
        gap = max(_gap_pct(c) for c in price_conflicts)
        checks.append(
            QualityCheck(
                "sources_agree",
                "Sources agree on the price",
                False,
                any(c.blocking for c in price_conflicts),
                measured=round(gap, 3),
                limit=limits.conflict_pct.get(profile, 1.0),
                unit="%",
                detail=worst.line(),
            )
        )
    elif len(priced) > 1:
        checks.append(
            QualityCheck(
                "sources_agree",
                "Sources agree on the price",
                True,
                True,
                measured=len(priced),
                limit=limits.conflict_pct.get(profile, 1.0),
                unit="%",
            )
        )

    if sizing is not None:
        checks.extend(_sizing(sizing, preferred, now, live, limits, profile))

    if live:
        checks.append(_platform(platform, platform_name, now, limits, profile))

    checks.extend(_bars(instrument, daily, now, limits, profile, preferred))

    news_checks, news_conflicts = _news(news)
    checks.extend(news_checks)
    conflicts.extend(news_conflicts)

    if live:
        age = None if account_at is None else max(0.0, now - account_at)
        synced = age is not None and age <= limits.account_max_age_s
        checks.append(
            QualityCheck(
                "account",
                "Account in sync",
                synced,
                True,
                measured=round(age, 1) if age is not None else None,
                limit=limits.account_max_age_s,
                unit="s",
                detail=""
                if synced
                else "the broker account hasn't been read"
                if age is None
                else f"last read {age:.0f} s ago",
            )
        )

    if venue is not None:
        checks.append(_venue(venue))

    if meme_facts is False:
        checks.append(
            QualityCheck(
                "meme_facts",
                "Meme-coin liquidity known",
                False,
                True,
                detail=f"DexScreener couldn't be read ({fence(meme_facts_note, limit=200)})"
                if meme_facts_note
                else "DexScreener has no trading pair with liquidity facts for it",
            )
        )

    return QualityReport(
        symbol=instrument.symbol,
        at=now,
        live=live,
        checks=tuple(checks),
        preferred=preferred,
        snapshots=tuple(snapshots),
        conflicts=tuple(conflicts),
        news=tuple(news),
        sizing=sizing,
    )


def failed_report(symbol: str, *, now: float, live: bool, error: str) -> QualityReport:
    """The checks themselves broke: nothing can be trusted, so new buys are
    blocked (held positions are still reviewed)."""
    return QualityReport(
        symbol=symbol,
        at=now,
        live=live,
        checks=(
            QualityCheck(
                "checks_ran",
                "Data checks ran",
                False,
                True,
                detail=f"the data checks failed ({fence(error, limit=200)})",
            ),
        ),
    )


def _sizing(
    sizing: QuoteSnapshot,
    preferred: QuoteSnapshot | None,
    now: float,
    live: bool,
    limits: DataQualityLimits,
    profile: str,
) -> list[QualityCheck]:
    """The price the order is sized and priced from must pass the same
    freshness and delay rules, and agree with the most reliable fresh price
    (whatever their times), or the order would rest on a different price
    than the one checked."""
    found: list[QualityCheck] = [
        replace(
            _fresh(sizing, now, limits, profile),
            name="order_price_fresh",
            label="Order price fresh",
        )
    ]
    found.extend(
        replace(check, name="order_price_realtime", label="Order price real time")
        for check in _realtime(sizing, live, limits)
    )
    if (
        preferred is not None
        and preferred.last
        and sizing.last
        and preferred.currency == sizing.currency
        and (preferred.provider, preferred.timestamp)
        != (sizing.provider, sizing.timestamp)
        and preferred.delayed_minutes == sizing.delayed_minutes
    ):
        tolerance = limits.conflict_pct.get(profile, 1.0)
        gap = abs(sizing.last - preferred.last) / min(sizing.last, preferred.last) * 100
        found.append(
            QualityCheck(
                "order_price_agrees",
                "Order price agrees with the best source",
                gap <= tolerance,
                True,
                measured=round(gap, 3),
                limit=tolerance,
                unit="%",
                detail=""
                if gap <= tolerance
                else f"the order would be priced at {sizing.last:g} "
                f"({sizing.provider}) but {preferred.provider} says "
                f"{preferred.last:g}",
            )
        )
    return found


def _platform(
    platform: QuoteSnapshot | None,
    name: str,
    now: float,
    limits: DataQualityLimits,
    profile: str,
) -> QualityCheck:
    """Live: the platform that would take the order must itself give a valid
    bid and ask, as the order check will demand. Another exchange's book
    doesn't count."""
    label = f"Bid and ask on {name or 'the trading platform'}"
    if platform is None:
        return QualityCheck(
            "platform_book",
            label,
            False,
            True,
            detail="the trading platform gave no price",
        )
    if platform.spread_pct is None:
        crossed = bool(platform.bid and platform.ask and platform.ask < platform.bid)
        return QualityCheck(
            "platform_book",
            label,
            False,
            True,
            detail="its bid is above its ask (a broken book)"
            if crossed
            else "it gave no valid bid and ask",
        )
    if platform.in_future(now):
        return QualityCheck(
            "platform_book",
            label,
            False,
            True,
            detail="its price time is in the future (a clock is wrong)",
        )
    spread = platform.spread_pct
    limit = limits.spread_pct.get(profile, 1.0)
    return QualityCheck(
        "platform_book",
        label,
        spread <= limit,
        True,
        measured=round(spread, 4),
        limit=limit,
        unit="%",
        detail=""
        if spread <= limit
        else f"its spread {spread:.3f}% is over {limit:g}%",
    )


def _venue(venue: VenueStatus) -> QualityCheck:
    """An exchange that has stopped trading a coin (disabled, cancel-only,
    offline, delisted) is a strong warning sign, so it blocks; limit-only or
    an auction is a thin or protected market, so it warns. A coin the
    exchange doesn't list is fine."""
    name = f"Trading on {venue.venue}"
    if not venue.listed:
        return QualityCheck(
            "venue",
            name,
            True,
            False,
            measured="not listed",
            detail=f"{venue.venue} doesn't list it",
        )
    if venue.stopped:
        flags = [
            label
            for label, on in (
                (f"status {venue.status}", venue.status != "online"),
                ("trading disabled", venue.trading_disabled),
                ("cancel only", venue.cancel_only),
            )
            if on
        ]
        return QualityCheck(
            "venue",
            name,
            False,
            True,
            measured=", ".join(flags),
            limit="online",
            detail=f"{venue.venue} has stopped normal trading ({', '.join(flags)})"
            + (f": {fence(venue.message, limit=200)}" if venue.message else ""),
        )
    if venue.restricted:
        flags = [
            label
            for label, on in (
                ("limit orders only", venue.limit_only),
                ("post only", venue.post_only),
                ("auction", venue.auction),
            )
            if on
        ]
        return QualityCheck(
            "venue",
            name,
            False,
            False,
            measured=", ".join(flags),
            limit="online",
            detail=f"{venue.venue} is in a restricted state ({', '.join(flags)})",
        )
    return QualityCheck("venue", name, True, True, measured="online")


def is_fresh(
    snap: QuoteSnapshot,
    *,
    now: float,
    limits: DataQualityLimits,
    profile: str,
) -> bool:
    """It has its own time, isn't timed ahead of FCC's clock, and is within
    the age limit for its market (plus any published delay)."""
    age = snap.age_s(now)
    return (
        age is not None
        and not snap.in_future(now)
        and age <= _age_limit(snap, limits, profile)
    )


def bid_ask_source(
    snapshots: Sequence[QuoteSnapshot],
    preferred: QuoteSnapshot | None,
    *,
    now: float,
    limits: DataQualityLimits,
    profile: str,
) -> QuoteSnapshot | None:
    """The fresh quote whose bid and ask are used: the preferred source when
    it has a fresh book, else the most reliable fresh one; None when no
    fresh source gave both sides."""
    quoted = [
        snap
        for snap in snapshots
        if snap.spread_pct is not None
        and is_fresh(snap, now=now, limits=limits, profile=profile)
    ]
    if not quoted:
        return None
    if preferred is not None and preferred in quoted:
        return preferred
    return max(quoted, key=lambda snap: SOURCE_RANK.get(snap.source_kind, 0))


def freshest(
    snapshots: Sequence[QuoteSnapshot],
    *,
    now: float,
    limits: DataQualityLimits,
    profile: str,
) -> QuoteSnapshot | None:
    """The most reliable price that is fresh right now, or None when no
    source has a fresh one (never an old price passed off as current)."""
    priced = [snap for snap in snapshots if snap.last]
    best = _preferred(priced, now, limits, profile)
    if best is None or not is_fresh(best, now=now, limits=limits, profile=profile):
        return None
    return best


def _age_limit(snap: QuoteSnapshot, limits: DataQualityLimits, profile: str) -> float:
    if snap.delayed_minutes:
        return snap.delayed_minutes * 60 + limits.delayed_grace_s
    if profile in {"crypto", "meme"}:
        return limits.crypto_quote_age_s
    return limits.share_quote_age_s


def _preferred(
    priced: Sequence[QuoteSnapshot],
    now: float,
    limits: DataQualityLimits,
    profile: str,
) -> QuoteSnapshot | None:
    """The most reliable source among the fresh ones; if none is fresh, the
    most recent (which the freshness check then fails)."""
    if not priced:
        return None

    candidates = [
        snap
        for snap in priced
        if is_fresh(snap, now=now, limits=limits, profile=profile)
    ] or list(priced)

    def middle(snap: QuoteSnapshot) -> float:
        """How far a price sits from the middle of the others in its
        currency: among equally reliable sources, the one the rest agree
        with wins, so a single odd price is never the one used."""
        values = sorted(
            other.last
            for other in candidates
            if other.last and other.currency == snap.currency
        )
        if not values or not snap.last:
            return 0.0
        median = values[len(values) // 2]
        if len(values) % 2 == 0:
            median = (values[len(values) // 2 - 1] + median) / 2
        return abs(snap.last - median) / median if median else 0.0

    return max(
        candidates,
        key=lambda snap: (
            snap.realtime,
            SOURCE_RANK.get(snap.source_kind, 0),
            snap.stamped,
            -middle(snap),
            snap.timestamp or 0.0,
        ),
    )


def _fresh(
    snap: QuoteSnapshot, now: float, limits: DataQualityLimits, profile: str
) -> QualityCheck:
    age = snap.age_s(now)
    limit = _age_limit(snap, limits, profile)
    future = snap.in_future(now)
    ok = age is not None and age <= limit and not future
    if future and snap.timestamp is not None:
        detail = (
            f"{snap.provider}'s price is timed {_duration(snap.timestamp - now)} "
            "in the future (a clock is wrong), so its age is unknown"
        )
    elif age is None:
        detail = f"{snap.provider} gave no time for its price"
    elif ok:
        detail = ""
    else:
        detail = f"{snap.provider}'s price is {_duration(age)} old (limit {_duration(limit)})"
    return QualityCheck(
        "fresh",
        "Price fresh",
        ok,
        True,
        measured=round(age, 1) if age is not None else None,
        limit=limit,
        unit="s",
        detail=detail,
    )


def _realtime(
    snap: QuoteSnapshot, live: bool, limits: DataQualityLimits
) -> list[QualityCheck]:
    if not snap.delayed_minutes:
        return []
    allowed = not live and limits.allow_delayed_in_paper
    detail = f"{snap.provider} is {snap.delayed_minutes} min delayed" + (
        "; paper only" if allowed else "; live trading needs real-time prices"
    )
    return [
        QualityCheck(
            "realtime",
            "Real-time price",
            False,
            not allowed,
            measured=snap.delayed_minutes,
            limit=0,
            unit="min",
            detail=detail,
        )
    ]


def _traded_since_open(
    snap: QuoteSnapshot,
    now: float,
    opened: datetime,
    limits: DataQualityLimits,
) -> QualityCheck:
    """A session open long enough with no trade at all since the open is a
    public holiday, or a halted symbol."""
    since_open = now - opened.timestamp()
    grace = limits.open_grace_minutes * 60 + snap.delayed_minutes * 60
    if since_open < grace or snap.timestamp is None:
        return QualityCheck("traded_today", "Trading today", True, True)
    traded = snap.timestamp >= opened.timestamp()
    return QualityCheck(
        "traded_today",
        "Trading today",
        traded,
        True,
        measured=iso(snap.timestamp),
        limit=iso(opened.timestamp()),
        detail=""
        if traded
        else f"no trade since the open {_duration(since_open)} ago "
        "(a public holiday, or the symbol is halted)",
    )


def _bid_ask(
    priced: Sequence[QuoteSnapshot],
    preferred: QuoteSnapshot | None,
    now: float,
    live: bool,
    limits: DataQualityLimits,
    profile: str,
) -> list[QualityCheck]:
    best = bid_ask_source(priced, preferred, now=now, limits=limits, profile=profile)
    if best is None:
        return [
            QualityCheck(
                "bid_ask",
                "Bid and ask",
                False,
                live,
                detail="no fresh bid/ask from any source"
                + ("" if live else "; paper fills assume a spread"),
            )
        ]
    spread = best.spread_pct or 0.0
    limit = limits.spread_pct.get(profile, 1.0)
    ok = spread <= limit
    return [
        QualityCheck("bid_ask", "Bid and ask", True, live, measured=best.provider),
        QualityCheck(
            "spread",
            "Spread acceptable",
            ok,
            True,
            measured=round(spread, 4),
            limit=limit,
            unit="%",
            detail=""
            if ok
            else f"{best.provider} spread {spread:.3f}% is over {limit:g}%",
        ),
    ]


def _price_conflicts(
    priced: Sequence[QuoteSnapshot],
    preferred: QuoteSnapshot | None,
    limits: DataQualityLimits,
    profile: str,
) -> list[Conflict]:
    """Real-time sources taken close together that disagree beyond the
    tolerance; delayed sources are never compared with real-time ones."""
    tolerance = limits.conflict_pct.get(profile, 1.0)
    found: list[Conflict] = []
    for index, first in enumerate(priced):
        for second in priced[index + 1 :]:
            if first.delayed_minutes != second.delayed_minutes:
                continue
            if first.currency != second.currency:
                continue
            if first.timestamp is None or second.timestamp is None:
                continue
            # A price timed only by when FCC received it is always compared:
            # its own time is unknown, so other sources are its check.
            both_stamped = first.stamped and second.stamped
            if (
                both_stamped
                and abs(first.timestamp - second.timestamp) > COMPARE_WINDOW_S
            ):
                continue
            a, b = first.last or 0.0, second.last or 0.0
            low = min(a, b)
            if low <= 0:
                continue
            gap = abs(a - b) / low * 100
            if gap <= tolerance:
                continue
            better = _more_reliable(first, second, preferred)
            blocking = gap > 3 * tolerance
            found.append(
                Conflict(
                    kind="price",
                    subject=first.symbol,
                    items=tuple(
                        {
                            "source": snap.provider,
                            "value": snap.last,
                            "when": iso(snap.timestamp),
                            "kind": snap.source_kind,
                        }
                        for snap in (first, second)
                    ),
                    preferred="none" if blocking else better.provider,
                    reason=f"{gap:.2f}% apart (tolerance {tolerance:g}%)"
                    + ("; possibly a different instrument" if blocking else ""),
                    confidence_penalty=0.0 if blocking else 10.0,
                    size_factor=0.0 if blocking else 0.5,
                    blocking=blocking,
                )
            )
    return found


def _more_reliable(
    first: QuoteSnapshot, second: QuoteSnapshot, preferred: QuoteSnapshot | None
) -> QuoteSnapshot:
    if preferred is first or preferred is second:
        return preferred
    return max(
        (first, second),
        key=lambda snap: (SOURCE_RANK.get(snap.source_kind, 0), snap.timestamp or 0),
    )


def _gap_pct(conflict: Conflict) -> float:
    values = [
        float(value)
        for item in conflict.items
        if isinstance(value := item.get("value"), int | float)
    ]
    if len(values) < 2 or min(values) <= 0:
        return 0.0
    return (max(values) - min(values)) / min(values) * 100


def _local_day(stamp: float, market: str) -> date:
    moment = datetime.fromtimestamp(stamp, tz=UTC)
    if market == "asx":
        moment += timedelta(hours=sydney_offset(moment))
    elif market == "us":
        moment += timedelta(hours=new_york_offset(moment))
    return moment.date()


def _bars(
    instrument: Instrument,
    daily: Sequence[Bar],
    now: float,
    limits: DataQualityLimits,
    profile: str,
    preferred: QuoteSnapshot | None,
) -> list[QualityCheck]:
    market = instrument.market
    checks: list[QualityCheck] = []
    enough = len(daily) >= MIN_DAILY_BARS
    checks.append(
        QualityCheck(
            "history",
            "Enough price history",
            enough,
            True,
            measured=len(daily),
            limit=MIN_DAILY_BARS,
            unit="days",
            detail="" if enough else f"only {len(daily)} daily candles",
        )
    )
    if not daily:
        return checks

    days = sorted({_local_day(bar.t, market) for bar in daily})
    today = _local_day(now, market)
    age_days = (today - days[-1]).days
    max_age = limits.bars_max_age_days.get(profile, 5.0)
    checks.append(
        QualityCheck(
            "bars_recent",
            "Candles up to date",
            age_days <= max_age,
            True,
            measured=age_days,
            limit=max_age,
            unit="days",
            detail=""
            if age_days <= max_age
            else f"the last daily candle is from {days[-1].isoformat()}",
        )
    )

    span = (days[-1] - days[0]).days + 1
    every_day = market == "crypto"
    expected = (
        span
        if every_day
        else sum(
            1
            for offset in range(span)
            if (days[0] + timedelta(days=offset)).weekday() < 5
        )
    )
    missing = max(0.0, (1 - len(days) / expected) * 100) if expected else 0.0
    block = missing > limits.missing_bars_block_pct
    warn = missing > limits.missing_bars_warn_pct
    checks.append(
        QualityCheck(
            "candles_complete",
            "Candles complete",
            not warn,
            block,
            measured=round(missing, 1),
            limit=limits.missing_bars_block_pct
            if block
            else limits.missing_bars_warn_pct,
            unit="%",
            detail=""
            if not warn
            else f"{missing:.0f}% of expected trading days have no candle"
            + ("" if every_day else " (public holidays explain a few)"),
        )
    )

    recent = list(daily[-LIQUIDITY_BARS:])
    traded = [bar for bar in recent if bar.v > 0]
    snapshot_volume = preferred.volume if preferred is not None else None
    has_volume = bool(traded) or bool(snapshot_volume)
    checks.append(
        QualityCheck(
            "volume",
            "Volume reported",
            has_volume,
            market != "crypto",
            measured=len(traded),
            limit=1,
            unit="days",
            detail=""
            if has_volume
            else "no trading volume in the recent candles (halted, or not reported)",
        )
    )
    minimum = limits.min_daily_value.get(profile, 0.0)
    currency = instrument.currency or ""
    if not traded:
        # No turnover figures means the liquidity is unknown, not fine.
        checks.append(
            QualityCheck(
                "liquidity",
                "Enough daily turnover",
                False,
                True,
                limit=minimum,
                unit=currency,
                detail="no turnover figures in the recent candles, so it's unknown",
            )
        )
        return checks
    value = sum(daily_turnover(bar, market) for bar in recent) / len(recent)
    checks.append(
        QualityCheck(
            "liquidity",
            "Enough daily turnover",
            value >= minimum,
            True,
            measured=round(value),
            limit=minimum,
            unit=currency,
            detail=""
            if value >= minimum
            else f"average {value:,.0f} {currency} a day is under {minimum:,.0f}",
        )
    )
    return checks


def daily_turnover(bar: Bar, market: str) -> float:
    """One day's trading in money. A coin's daily volume from Yahoo,
    CoinGecko, and Coinbase (converted) is already in dollars; a share's is
    in shares, so it is multiplied by the close."""
    return bar.v if market == "crypto" else bar.c * bar.v


def _news(news: Sequence[NewsItem]) -> tuple[list[QualityCheck], list[Conflict]]:
    if not news:
        return [
            QualityCheck(
                "news",
                "Dated news found",
                False,
                False,
                measured=0,
                detail="no dated headlines; the seats are told news is missing",
            )
        ], []
    usable = [item for item in news if item.usable]
    undated = sum(1 for item in news if item.status == "undated")
    invalid = sum(1 for item in news if item.status == "invalid")
    stale = sum(1 for item in news if item.status == "stale")
    folded = sum(item.duplicates for item in news)
    checks = [
        QualityCheck(
            "news",
            "Dated news found",
            bool(usable),
            False,
            measured=len(usable),
            detail=(
                f"{len(usable)} usable"
                + (f", {undated} undated (not facts)" if undated else "")
                + (f", {stale} too old" if stale else "")
                + (f", {folded} duplicates folded" if folded else "")
            ),
        )
    ]
    if invalid:
        checks.append(
            QualityCheck(
                "news_dates",
                "News dates valid",
                False,
                False,
                measured=invalid,
                detail=f"{invalid} headline(s) dated in the future were set aside",
            )
        )
    conflicts = [
        Conflict(
            kind="news",
            subject=first.symbol,
            items=tuple(
                {
                    "source": fence(item.source, limit=60),
                    "value": f"{item.sentiment}: {fence(item.headline, limit=160)}",
                    "when": iso(item.published_at),
                    "kind": item.source_kind,
                }
                for item in (first, second)
            ),
            preferred=fence(_newer_reliable(first, second).source, limit=60),
            reason="stories point opposite ways; confidence and size are cut",
            confidence_penalty=10.0,
            size_factor=0.75,
        )
        for first, second in conflicting(usable)
    ]
    if conflicts:
        checks.append(
            QualityCheck(
                "news_agree",
                "News consistent",
                False,
                False,
                measured=len(conflicts),
                detail=conflicts[0].line(),
            )
        )
    return checks, conflicts


def _newer_reliable(first: NewsItem, second: NewsItem) -> NewsItem:
    return max(
        (first, second),
        key=lambda item: (
            SOURCE_RANK.get(item.source_kind, 0),
            item.confirmed,
            item.published_at or 0.0,
        ),
    )


def _duration(seconds: float) -> str:
    if seconds < 120:
        return f"{seconds:.0f} s"
    if seconds < 7200:
        return f"{seconds / 60:.0f} min"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86_400:.1f} days"
