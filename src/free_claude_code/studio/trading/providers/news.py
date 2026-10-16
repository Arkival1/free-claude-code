"""Dated news for one symbol, straight from where it was published.

- ASX announcements: the exchange's own company announcements, with the
  exchange's price-sensitive flag and the time each was released (official).
- Yahoo Finance RSS: headlines for a share or coin, each with its
  publication time (an aggregator, so its stories are unconfirmed until a
  reputable or official source tells them too).

Web-search results carry no dates, so they are passed on as undated and never
become facts. Everything here is read as data: nothing in a headline is ever
followed as an instruction.
"""

import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from loguru import logger

from ...resilience import HostLimit, ServiceError, Web
from ...search import SearchHit
from ..information import seconds_from_iso
from ..instruments import Instrument
from ..news import RawNews

ASX_API = "https://asx.api.markitdigital.com/asx-research/1.0/companies"
ASX_PAGE = "https://www.asx.com.au/markets/trade-our-cash-market/announcements"
YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
LIMITS: dict[str, HostLimit] = {
    "asx.api.markitdigital.com": HostLimit(1.0, 2),
    "feeds.finance.yahoo.com": HostLimit(1.0, 2),
}
MAX_ITEMS = 20
MAX_RSS_BYTES = 512_000


class NewsFeeds:
    def __init__(self, web: Web, *, wall: Callable[[], float] = time.time) -> None:
        self._web = web
        self._wall = wall

    async def asx(self, code: str, *, count: int = MAX_ITEMS) -> list[RawNews]:
        """The company's latest ASX announcements, newest first."""
        body = await self._web.get_json(
            f"{ASX_API}/{code.lower()}/announcements",
            params={"count": count},
            what="ASX announcements",
        )
        data = body.get("data") if isinstance(body, dict) else None
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ServiceError(f"ASX sent no announcements for {code}.")
        found: list[RawNews] = []
        for item in items[:count]:
            if not isinstance(item, dict):
                continue
            headline = item.get("headline")
            if not isinstance(headline, str) or not headline.strip():
                continue
            sensitive = item.get("isPriceSensitive")
            link = item.get("url")
            found.append(
                RawNews(
                    headline=headline,
                    url=link
                    if isinstance(link, str) and link.startswith("https://")
                    else f"{ASX_PAGE}.{code.lower()}",
                    provider="ASX announcements",
                    source="ASX",
                    published_at=seconds_from_iso(item.get("date")),
                    price_sensitive=sensitive if isinstance(sensitive, bool) else None,
                    official=True,
                    document=str(item.get("documentKey") or ""),
                )
            )
        return found

    async def yahoo(self, symbol: str) -> list[RawNews]:
        """Yahoo Finance's headlines for a share (BHP.AX, AAPL) or coin (BTC-USD)."""
        response = await self._web.request(
            "GET",
            YAHOO_RSS,
            params={"s": symbol, "region": "US", "lang": "en-US"},
            headers={"accept": "application/rss+xml, application/xml"},
            what="Yahoo Finance news",
        )
        return parse_rss(response.content[:MAX_RSS_BYTES], provider="Yahoo Finance")

    async def for_instrument(
        self, instrument: Instrument
    ) -> tuple[list[RawNews], list[str]]:
        """Every dated feed that covers this symbol, and what failed (so a
        missing feed is said, not hidden)."""
        found: list[RawNews] = []
        problems: list[str] = []
        if instrument.market == "asx":
            try:
                found.extend(await self.asx(instrument.code))
            except ServiceError as error:
                problems.append(f"ASX announcements: {error}")
        if instrument.yahoo and instrument.market in {"asx", "us", "crypto"}:
            try:
                found.extend(await self.yahoo(instrument.yahoo))
            except ServiceError as error:
                problems.append(f"Yahoo Finance news: {error}")
        for problem in problems:
            logger.info("Trading: {} ({})", problem, instrument.symbol)
        return found, problems


def parse_rss(body: bytes, *, provider: str) -> list[RawNews]:
    """Items from an RSS 2.0 feed; an item with no title is skipped and one
    with no readable date is kept as undated."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ServiceError(f"{provider} sent news that isn't RSS ({error}).") from error
    found: list[RawNews] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        found.append(
            RawNews(
                headline=title,
                url=link if link.startswith(("https://", "http://")) else "",
                provider=provider,
                source=source or provider,
                published_at=_rfc822_seconds(item.findtext("pubDate")),
            )
        )
        if len(found) >= MAX_ITEMS:
            break
    return found


def from_search(hits: list[SearchHit]) -> list[RawNews]:
    """Web-search results: kept for reading, but undated, so never facts."""
    return [
        RawNews(headline=hit.title, url=hit.url, provider="web search")
        for hit in hits
        if hit.title.strip()
    ]


def _rfc822_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        found = parsedate_to_datetime(value.strip())
    except TypeError, ValueError, OverflowError:
        # A date that can't be read (or a year in the far future) is undated.
        return None
    if found.tzinfo is None:
        return None
    return found.timestamp()
