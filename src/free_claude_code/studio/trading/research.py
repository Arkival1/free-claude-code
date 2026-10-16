"""The Researcher's and the Macro seat's notes: news, results, and events.

Searches go through Studio's own search setup (and count against its daily
budget), the best pages are read for the sentences that matter, and the notes
are kept for 45 minutes a symbol (a day for the macro calendar), so a busy
desk doesn't search the same thing twice.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from loguru import logger

from free_claude_code.core.json_types import JsonObject

from ..research import excerpt
from ..search import SearchError, StudioSearch
from .instruments import Instrument

SYMBOL_SECONDS = 45 * 60.0
MACRO_SECONDS = 24 * 3600.0
PAGES_READ = 2
EXCERPT_SIZE = 700

ReadPage = Callable[[str], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class Headline:
    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class ResearchPack:
    subject: str
    headlines: tuple[Headline, ...] = ()
    excerpts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    """Why something is missing, e.g. no search set up."""
    at: float = field(default=0.0)

    def titles(self) -> frozenset[str]:
        return frozenset(item.title.casefold() for item in self.headlines)

    def lines(self) -> str:
        if not self.headlines and not self.excerpts:
            return "No news found" + (
                f" ({'; '.join(self.notes)})" if self.notes else "."
            )
        rows = [
            f"- {item.title}" + (f": {item.snippet[:180]}" if item.snippet else "")
            for item in self.headlines[:8]
        ]
        rows.extend(f'- From a page: "{text}"' for text in self.excerpts)
        return "\n".join(rows)

    def view(self) -> JsonObject:
        return {
            "subject": self.subject,
            "headlines": [
                {"title": item.title, "url": item.url, "snippet": item.snippet}
                for item in self.headlines
            ],
            "excerpts": list(self.excerpts),
            "notes": list(self.notes),
        }


def _queries(instrument: Instrument) -> list[str]:
    code = instrument.code
    if instrument.market == "asx":
        return [f"{code} ASX shares news", f"{code} ASX announcement results date"]
    if instrument.market == "us":
        return [f"{code} stock news today", f"{code} next earnings date"]
    if instrument.market == "dex":
        return [f"{instrument.address} token", f"{instrument.chain} meme coin news"]
    if instrument.meme:
        return [f"{code} meme coin news", f"{code} crypto price why"]
    return [f"{code} crypto news today"]


MACRO_QUERIES: dict[str, list[str]] = {
    "asx": [
        "RBA cash rate decision next meeting date",
        "ASX 200 market outlook this week",
    ],
    "us": ["FOMC next meeting date", "US CPI release date this month stock market"],
    "crypto": ["crypto market news today bitcoin", "crypto token unlocks this week"],
}


class DeskResearch:
    def __init__(
        self,
        *,
        search: Callable[[], StudioSearch | None],
        read_page: ReadPage | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._search = search
        self._read_page = read_page
        self._clock = clock
        self._kept: dict[str, tuple[float, ResearchPack]] = {}

    async def gather(self, instrument: Instrument) -> ResearchPack:
        """News and facts for one symbol (kept 45 minutes)."""
        return await self._kept_or(
            f"symbol:{instrument.symbol}",
            SYMBOL_SECONDS,
            lambda: self._look(instrument.symbol, _queries(instrument), read=True),
        )

    async def macro(self, market: str) -> ResearchPack:
        """The market's calendar and mood (kept a day)."""
        key = "crypto" if market in {"crypto", "dex"} else market
        return await self._kept_or(
            f"macro:{key}",
            MACRO_SECONDS,
            lambda: self._look(f"{key} macro", MACRO_QUERIES.get(key, []), read=False),
        )

    async def fresh_titles(self, instrument: Instrument) -> frozenset[str] | None:
        """Headlines right now, for the cooling-off check (not kept); None
        when nothing can be searched."""
        searcher = self._search()
        if searcher is None or searcher.problem():
            return None
        try:
            report = await searcher.search(_queries(instrument)[0], limit=6)
        except SearchError:
            return None
        return frozenset(hit.title.casefold() for hit in report.hits)

    async def _kept_or(
        self,
        key: str,
        seconds: float,
        load: Callable[[], Awaitable[ResearchPack]],
    ) -> ResearchPack:
        now = self._clock()
        found = self._kept.get(key)
        if found is not None and now - found[0] < seconds:
            return found[1]
        pack = await load()
        self._kept[key] = (now, pack)
        return pack

    async def _look(
        self, subject: str, queries: list[str], *, read: bool
    ) -> ResearchPack:
        searcher = self._search()
        if searcher is None:
            return ResearchPack(
                subject, notes=("web search isn't set up",), at=time.time()
            )
        problem = searcher.problem()
        notes: list[str] = [problem] if problem else []
        headlines: dict[str, Headline] = {}
        for query in queries:
            try:
                report = await searcher.search(query, limit=6)
            except SearchError as error:
                notes.append(str(error))
                continue
            for hit in report.hits:
                headlines.setdefault(
                    hit.url, Headline(hit.title, hit.url, " ".join(hit.snippet.split()))
                )
        excerpts: list[str] = []
        if read and self._read_page is not None and headlines:
            terms = [word.lower() for word in subject.replace(".", " ").split()]
            pages = await asyncio.gather(
                *(
                    self._page(item.url)
                    for item in list(headlines.values())[:PAGES_READ]
                )
            )
            excerpts = [
                excerpt(text, terms, size=EXCERPT_SIZE)
                for text in pages
                if text.strip()
            ]
        return ResearchPack(
            subject,
            tuple(headlines.values())[:10],
            tuple(text for text in excerpts if text),
            tuple(notes),
            at=time.time(),
        )

    async def _page(self, url: str) -> str:
        if self._read_page is None:
            return ""
        try:
            return await asyncio.wait_for(self._read_page(url), timeout=20.0)
        except Exception as error:
            logger.info("Trading: couldn't read {}: {}", url, error)
            return ""
