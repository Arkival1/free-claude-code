"""When each market trades: the ASX in Sydney, the US in New York, crypto always.

Windows Python has no time zone data without an extra package, so the two
daylight-saving rules that matter are written out here:
- New York: second Sunday of March 02:00 to first Sunday of November 02:00.
- Sydney: first Sunday of October 02:00 to first Sunday of April 03:00.
Public holidays are not known; on one the market looks open, the platform
refuses the order, and the desk logs why.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from free_claude_code.core.json_types import JsonObject

type Offset = Callable[[datetime], int]

ASX_HOURS = (time(10, 0), time(16, 0))
US_HOURS = (time(9, 30), time(16, 0))


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def new_york_offset(when: datetime) -> int:
    """New York's hours from UTC at a moment (-4 in summer, -5 in winter)."""
    year = when.astimezone(UTC).year
    starts = datetime.combine(_nth_sunday(year, 3, 2), time(7, 0), tzinfo=UTC)
    ends = datetime.combine(_nth_sunday(year, 11, 1), time(6, 0), tzinfo=UTC)
    return -4 if starts <= when < ends else -5


def sydney_offset(when: datetime) -> int:
    """Sydney's hours from UTC at a moment (+11 in summer, +10 in winter)."""
    year = when.astimezone(UTC).year
    # Both changes happen at 16:00 UTC on the Saturday before the Sunday.
    summer_ends = datetime.combine(
        _nth_sunday(year, 4, 1) - timedelta(days=1), time(16, 0), tzinfo=UTC
    )
    summer_starts = datetime.combine(
        _nth_sunday(year, 10, 1) - timedelta(days=1), time(16, 0), tzinfo=UTC
    )
    return 10 if summer_ends <= when < summer_starts else 11


@dataclass(frozen=True, slots=True)
class Session:
    """Whether a market is trading now, and its next open and close (UTC)."""

    market: str
    open: bool
    opens_at: datetime | None
    closes_at: datetime | None
    local: str
    """The market's own clock, e.g. 'Tue 10:42 Sydney'."""

    def view(self) -> JsonObject:
        return {
            "market": self.market,
            "open": self.open,
            "opens_at": _ms(self.opens_at),
            "closes_at": _ms(self.closes_at),
            "local": self.local,
        }


def _ms(when: datetime | None) -> int | None:
    return int(when.timestamp() * 1000) if when is not None else None


def _zone(market: str) -> tuple[tuple[time, time], Offset, str] | None:
    if market == "asx":
        return ASX_HOURS, sydney_offset, "Sydney"
    if market == "us":
        return US_HOURS, new_york_offset, "New York"
    return None


def session(market: str, now: datetime | None = None) -> Session:
    """The market's session at ``now`` (UTC); crypto never closes."""
    now = now or datetime.now(UTC)
    zone = _zone(market)
    if zone is None:
        return Session(market, True, None, None, "24/7")
    (opening, closing), offset_of, city = zone
    local = now + timedelta(hours=offset_of(now))
    label = f"{local:%a %H:%M} {city}"
    today = local.date()
    if today.weekday() < 5:
        open_today = _utc(today, opening, offset_of)
        close_today = _utc(today, closing, offset_of)
        if open_today <= now < close_today:
            return Session(market, True, open_today, close_today, label)
        if now < open_today:
            return Session(market, False, open_today, close_today, label)
    day = _next_weekday(today)
    return Session(
        market,
        False,
        _utc(day, opening, offset_of),
        _utc(day, closing, offset_of),
        label,
    )


def last_close(market: str, now: datetime, *, crypto_hour_utc: int = 14) -> datetime:
    """The most recent session close at or before ``now`` (UTC).

    Crypto never closes, so its "close" is a set hour each day, for the
    daily debrief.
    """
    zone = _zone(market)
    if zone is None:
        today = datetime.combine(now.date(), time(crypto_hour_utc), tzinfo=UTC)
        return today if today <= now else today - timedelta(days=1)
    (_, closing), offset_of, _ = zone
    local_day = (now + timedelta(hours=offset_of(now))).date()
    for back in range(8):
        day = local_day - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        closed = _utc(day, closing, offset_of)
        if closed <= now:
            return closed
    return now - timedelta(days=7)


def _utc(day: date, at: time, offset_of: Offset) -> datetime:
    """A local wall-clock time on a weekday, as UTC.

    The clocks change on a weekend night, far from trading hours, so the
    offset read at the wall-clock time is the one in force all that day.
    """
    wall = datetime.combine(day, at, tzinfo=UTC)
    return wall - timedelta(hours=offset_of(wall))


def _next_weekday(day: date) -> date:
    following = day + timedelta(days=1)
    while following.weekday() >= 5:
        following += timedelta(days=1)
    return following
