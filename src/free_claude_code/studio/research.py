"""Deep research: gather many sources across platforms, read them, report."""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import aiohttp
import httpx

from free_claude_code.application.web_tools.ports import WebFetchEgressViolation
from free_claude_code.core.web_tools import WebFetchResult

from .memory import keywords
from .platforms import PlatformError, PlatformReader, platform_of
from .search import SearchError, SearchHit, StudioSearch

PLATFORM_SITES: dict[str, str] = {
    "stackoverflow": "stackoverflow.com",
    "github": "github.com",
    "docs": "developer.mozilla.org",
    "devto": "dev.to",
    "hackernews": "news.ycombinator.com",
}
PLATFORMS: tuple[str, ...] = (
    "web",
    "reddit",
    "youtube",
    "stackoverflow",
    "github",
    "docs",
    "devto",
    "hackernews",
)
DEFAULT_PLATFORMS: tuple[str, ...] = (
    "web",
    "reddit",
    "youtube",
    "stackoverflow",
    "github",
    "docs",
    "devto",
)
_SITE_PLATFORMS = {site: name for name, site in PLATFORM_SITES.items()} | {
    "stackexchange.com": "stackoverflow",
    "youtube.com": "youtube",
}
EXTRA_ANGLES = ("tutorial", "best practices", "common mistakes", "examples")
EXCERPT_CHARS = 520
REPORT_CHARS = 7_600
READ_CONCURRENCY = 4
_CHUNK = re.compile(r"[^.!?\n]+[.!?]?")

type PageFetcher = Callable[[str], Awaitable[WebFetchResult]]


@dataclass(frozen=True, slots=True)
class Source:
    """One source the research read, with the part that matters."""

    number: int
    platform: str
    title: str
    url: str
    excerpt: str
    read: bool


@dataclass(frozen=True, slots=True)
class ResearchReport:
    """Everything one research run found."""

    question: str
    sources: tuple[Source, ...]
    wanted: int
    notes: tuple[str, ...] = ()

    def render(self) -> str:
        """Format the report for a model, numbered so it can cite [n]."""
        counts: dict[str, int] = {}
        for source in self.sources:
            counts[source.platform] = counts.get(source.platform, 0) + 1
        mix = ", ".join(f"{name} {count}" for name, count in counts.items())
        lines = [
            f"Research: {self.question}",
            f"Sources: {len(self.sources)} ({mix})",
        ]
        if len(self.sources) < self.wanted:
            lines.append(
                f"Found {len(self.sources)} of the {self.wanted} sources wanted; "
                "try a broader question or add a search API key."
            )
        lines.extend(f"Note: {note}" for note in self.notes)
        header = "\n".join(lines)
        footer = (
            "Cite sources as [n]. Test any code with test_code before you rely "
            "on it, and say which findings you verified."
        )
        budget = REPORT_CHARS - len(header) - len(footer)
        per_source = max(160, budget // max(1, len(self.sources)))
        body: list[str] = []
        for source in self.sources:
            entry = (
                f"[{source.number}] {source.title} — {source.url} ({source.platform})"
            )
            excerpt = source.excerpt[: per_source - len(entry)].strip()
            if excerpt:
                entry += f"\n    {excerpt}"
            body.append(entry)
        return "\n".join([header, *body, footer])


def normalize_url(url: str) -> str:
    """Compare URLs without fragments, trailing slashes, or tracking noise."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("old.")
    path = parts.path.rstrip("/") or "/"
    query = "&".join(
        piece
        for piece in parts.query.split("&")
        if piece and not piece.startswith(("utm_", "ref=", "fbclid="))
    )
    return urlunsplit(("https", host, path, query, ""))


def source_platform(url: str) -> str:
    """Name the platform a result came from, even via general web search."""
    platform = platform_of(url)
    if platform != "web":
        return platform
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for site, name in _SITE_PLATFORMS.items():
        if host == site or host.endswith(f".{site}"):
            return name
    return "web"


def _sentences(text: str) -> list[str]:
    """Split page text into sentences, dropping menus, buttons, and labels."""
    sentences: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if len(line) < 25 or len(line.split()) < 5:
            continue
        sentences.extend(
            match.group(0).strip()
            for match in _CHUNK.finditer(line)
            if len(match.group(0).strip()) > 25
        )
    return sentences


def excerpt(text: str, terms: Sequence[str], *, size: int = EXCERPT_CHARS) -> str:
    """Return the sentences that best match the question, in page order."""
    sentences = _sentences(text)
    if not sentences:
        return " ".join(text.split())[:size]
    joined = " ".join(sentences)
    if len(joined) <= size or not terms:
        return joined[:size]
    scored = [
        (sum(1 for term in terms if term in sentence.lower()), index)
        for index, sentence in enumerate(sentences)
    ]
    best = sorted(scored, key=lambda pair: (-pair[0], pair[1]))
    chosen: list[int] = []
    used = 0
    for score, index in best:
        if score == 0 and chosen:
            break
        length = len(sentences[index]) + 1
        if used + length > size and chosen:
            continue
        chosen.append(index)
        used += length
        if used >= size:
            break
    return " ".join(sentences[index] for index in sorted(chosen))[:size]


class DeepResearch:
    """Search the web and several platforms, then read what they found."""

    def __init__(
        self,
        *,
        search: StudioSearch,
        reader: PlatformReader,
        fetch: PageFetcher,
        wanted: int = 10,
    ) -> None:
        self._search = search
        self._reader = reader
        self._fetch = fetch
        self._wanted = max(3, wanted)

    async def run(
        self, question: str, *, platforms: Sequence[str] = ()
    ) -> ResearchReport:
        """Research one question across the chosen platforms."""
        cleaned = question.strip()
        if not cleaned:
            raise ValueError("Say what to research.")
        chosen = [name for name in platforms if name in PLATFORMS] or list(
            DEFAULT_PLATFORMS
        )
        notes: list[str] = []
        batches = await asyncio.gather(
            *(self._find(name, cleaned, notes) for name in chosen)
        )
        batches = list(batches)
        limit = self._wanted + 2
        picked = self._pick(batches, limit=limit)
        for angle in EXTRA_ANGLES:
            if len(picked) >= self._wanted:
                break
            batches.append(await self._find("web", f"{cleaned} {angle}", notes))
            picked = self._pick(batches, limit=limit)
        terms = keywords(cleaned)
        gate = asyncio.Semaphore(READ_CONCURRENCY)
        sources = await asyncio.gather(
            *(
                self._read(number, platform, hit, terms, gate)
                for number, (platform, hit) in enumerate(picked, start=1)
            )
        )
        return ResearchReport(
            question=cleaned,
            sources=tuple(sources),
            wanted=self._wanted,
            notes=tuple(dict.fromkeys(notes)),
        )

    async def _find(
        self, platform: str, question: str, notes: list[str]
    ) -> list[tuple[str, SearchHit]]:
        try:
            if platform == "reddit":
                try:
                    hits = await self._reader.reddit_search(question)
                except (httpx.HTTPError, ValueError, AttributeError) as error:
                    notes.append(
                        f"Reddit search was unavailable ({type(error).__name__})."
                    )
                    hits = await self._site_search("reddit.com", question, notes)
            elif platform == "youtube":
                if self._reader.youtube_search_ready:
                    try:
                        hits = await self._reader.youtube_search(question)
                    except (httpx.HTTPError, ValueError, PlatformError) as error:
                        notes.append(f"YouTube search failed ({type(error).__name__}).")
                        hits = await self._site_search("youtube.com", question, notes)
                else:
                    hits = await self._site_search("youtube.com", question, notes)
            elif platform in PLATFORM_SITES:
                hits = await self._site_search(
                    PLATFORM_SITES[platform], question, notes
                )
            else:
                report = await self._search.search(question, limit=8)
                if report.note:
                    notes.append(report.note)
                hits = report.hits
        except (SearchError, ValueError) as error:
            notes.append(f"{platform} search failed: {error}")
            return []
        return [
            (source_platform(hit.url) if platform == "web" else platform, hit)
            for hit in hits
        ]

    async def _site_search(
        self, site: str, question: str, notes: list[str]
    ) -> tuple[SearchHit, ...]:
        report = await self._search.search(f"site:{site} {question}", limit=5)
        if report.note:
            notes.append(report.note)
        return tuple(
            hit for hit in report.hits if site in (urlsplit(hit.url).hostname or "")
        )

    @staticmethod
    def _pick(
        batches: Sequence[Sequence[tuple[str, SearchHit]]], *, limit: int
    ) -> list[tuple[str, SearchHit]]:
        """Take results round-robin across platforms so no one site dominates."""
        seen: set[str] = set()
        picked: list[tuple[str, SearchHit]] = []
        depth = max((len(batch) for batch in batches), default=0)
        for index in range(depth):
            for batch in batches:
                if index >= len(batch) or len(picked) >= limit:
                    continue
                platform, hit = batch[index]
                key = normalize_url(hit.url)
                if key in seen:
                    continue
                seen.add(key)
                picked.append((platform, hit))
        return picked

    async def _read(
        self,
        number: int,
        platform: str,
        hit: SearchHit,
        terms: Sequence[str],
        gate: asyncio.Semaphore,
    ) -> Source:
        async with gate:
            try:
                if platform_of(hit.url) in {"reddit", "youtube"}:
                    page = await self._reader.read(hit.url)
                    text, title = page.text, page.title or hit.title
                else:
                    fetched = await self._fetch(hit.url)
                    text, title = fetched.data, fetched.title or hit.title
            except (
                httpx.HTTPError,
                aiohttp.ClientError,
                PlatformError,
                WebFetchEgressViolation,
                OSError,
                RuntimeError,
                ValueError,
            ):
                return Source(
                    number=number,
                    platform=platform,
                    title=hit.title,
                    url=hit.url,
                    excerpt=hit.snippet,
                    read=False,
                )
        return Source(
            number=number,
            platform=platform,
            title=title,
            url=hit.url,
            excerpt=excerpt(text, terms) or hit.snippet,
            read=True,
        )
