"""Deep research: gather many sources across platforms, read them, report."""

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from urllib.parse import urlsplit, urlunsplit

import aiohttp
import httpx

from free_claude_code.application.web_tools.ports import WebFetchEgressViolation
from free_claude_code.core.web_tools import WebFetchResult

from .memory import keywords
from .platforms import (
    PlatformError,
    PlatformPage,
    PlatformReader,
    RedditPost,
    VideoResult,
    platform_of,
    youtube_id,
)
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
GENERAL_ANGLES = ("guide", "explained", "reviews")
DEV_PLATFORMS: tuple[str, ...] = ("stackoverflow", "github", "docs", "devto")
TECH_TERMS = frozenset(
    {
        "api",
        "bash",
        "bug",
        "build",
        "c#",
        "c++",
        "code",
        "coding",
        "compile",
        "css",
        "database",
        "debug",
        "deploy",
        "django",
        "docker",
        "error",
        "exception",
        "fastapi",
        "flask",
        "framework",
        "function",
        "git",
        "github",
        "golang",
        "html",
        "install",
        "java",
        "javascript",
        "js",
        "json",
        "kotlin",
        "library",
        "linux",
        "node",
        "nodejs",
        "npm",
        "php",
        "pip",
        "powershell",
        "program",
        "programming",
        "python",
        "react",
        "regex",
        "rust",
        "script",
        "sdk",
        "server",
        "sql",
        "stack",
        "swift",
        "terminal",
        "traceback",
        "typescript",
        "vite",
        "vue",
        "webpack",
    }
)
EXCERPT_CHARS = 520
LONG_EXCERPT_CHARS = 900
MIN_VIDEO_SECONDS = 60
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
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ResearchMix:
    """How many of each kind of source a research run must bring back."""

    web: int = 3
    reddit: int = 2
    youtube: int = 2


_SECTIONS = (("web", "Web"), ("reddit", "Reddit"), ("youtube", "YouTube"))


@dataclass(frozen=True, slots=True)
class ResearchReport:
    """Everything one research run found."""

    question: str
    sources: tuple[Source, ...]
    wanted: int
    notes: tuple[str, ...] = ()
    videos: tuple[PlatformPage, ...] = ()
    """Videos whose transcripts were read, kept so they can be studied."""

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
            "Cite sources as [n] and give the user the links you used. Test any "
            "code with test_code before you rely on it, and say which findings "
            "you verified."
        )
        budget = REPORT_CHARS - len(header) - len(footer) - 60
        per_source = max(160, budget // max(1, len(self.sources)))
        body: list[str] = []
        shown: set[str] = set()
        for source in self.sources:
            section = next(
                (label for key, label in _SECTIONS if key == source.platform), "More"
            )
            if section not in shown:
                shown.add(section)
                body.append(f"## {section}")
            detail = f"; {source.detail}" if source.detail else ""
            entry = f"[{source.number}] {source.title} — {source.url}{detail}"
            if section == "More":
                entry += f" ({source.platform})"
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


def is_technical(question: str) -> bool:
    """True for coding questions, which also get Stack Overflow, GitHub, and docs."""
    words = set(re.findall(r"[a-z0-9#+]+", question.lower()))
    return bool(words & TECH_TERMS)


def _term_in(term: str, text: str) -> bool:
    if term in text:
        return True
    for ending in ("ing", "es", "s"):
        if term.endswith(ending) and len(term) - len(ending) >= 3:
            return term[: -len(ending)] in text
    return False


def relevance(text: str, terms: Sequence[str]) -> float:
    """The share of the question's terms that a text mentions, 0 to 1."""
    if not terms:
        return 1.0
    lowered = text.lower()
    return sum(1 for term in terms if _term_in(term, lowered)) / len(terms)


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
    """Search the web and several platforms, then read what they found.

    Every run brings back a fixed mix unless told otherwise: at least three
    web pages, two Reddit threads that are on topic and have a real
    discussion, and two YouTube videos whose transcripts could be read, each
    with its link. The rest of the sources come from the other platforms.
    """

    def __init__(
        self,
        *,
        search: StudioSearch,
        reader: PlatformReader,
        fetch: PageFetcher,
        wanted: int = 10,
        mix: ResearchMix | None = None,
    ) -> None:
        self._search = search
        self._reader = reader
        self._fetch = fetch
        self._wanted = max(3, wanted)
        self._mix = mix or ResearchMix()
        self._videos: list[PlatformPage] = []

    async def run(
        self,
        question: str,
        *,
        platforms: Sequence[str] = (),
        mix: ResearchMix | None = None,
    ) -> ResearchReport:
        """Research one question across the chosen platforms."""
        cleaned = question.strip()
        if not cleaned:
            raise ValueError("Say what to research.")
        mix = mix or self._mix
        chosen = [name for name in platforms if name in PLATFORMS]
        if not chosen:
            chosen = ["web", "reddit", "youtube"]
            if is_technical(cleaned):
                chosen.extend(DEV_PLATFORMS)
        terms = keywords(cleaned)
        notes: list[str] = []
        others = [name for name in chosen if name not in {"web", "reddit", "youtube"}]
        # Everything is looked up at once: the three quotas and the other
        # platforms' searches.
        web_job = asyncio.ensure_future(
            self._web(cleaned, terms, mix.web, notes) if "web" in chosen else _no_web()
        )
        reddit_job = asyncio.ensure_future(
            self._reddit(cleaned, terms, mix.reddit if "reddit" in chosen else 0, notes)
        )
        youtube_job = asyncio.ensure_future(
            self._youtube(
                cleaned, terms, mix.youtube if "youtube" in chosen else 0, notes
            )
        )
        batch_jobs = [
            asyncio.ensure_future(self._find(name, cleaned, notes)) for name in others
        ]
        web = await web_job
        reddit = await reddit_job
        youtube = await youtube_job
        batches = [await job for job in batch_jobs]
        core = [*web[0], *reddit, *youtube]
        seen = {normalize_url(source.url) for source in core}
        room = max(self._wanted - len(core), len(others))
        spare = [
            [pair for pair in batch if normalize_url(pair[1].url) not in seen]
            for batch in [*batches, web[1]]
        ]
        picked = self._pick(spare, limit=room)
        for angle in EXTRA_ANGLES if others else GENERAL_ANGLES:
            if len(picked) >= room:
                break
            spare.append(
                [
                    pair
                    for pair in await self._find("web", f"{cleaned} {angle}", notes)
                    if normalize_url(pair[1].url) not in seen
                    and pair[0] not in {"reddit", "youtube"}
                ]
            )
            picked = self._pick(spare, limit=room)
        gate = asyncio.Semaphore(READ_CONCURRENCY)
        extra = await asyncio.gather(
            *(self._read(0, platform, hit, terms, gate) for platform, hit in picked)
        )
        sources = [
            replace(source, number=number)
            for number, source in enumerate([*core, *extra], start=1)
        ]
        return ResearchReport(
            question=cleaned,
            sources=tuple(sources),
            wanted=self._wanted,
            notes=tuple(dict.fromkeys(notes)),
            videos=tuple(self._videos),
        )

    # ------------------------------------------------------------------ web

    async def _web(
        self, question: str, terms: Sequence[str], need: int, notes: list[str]
    ) -> tuple[list[Source], list[tuple[str, SearchHit]]]:
        """Read the best general web pages; hand back the rest as spares."""
        found = await self._find("web", question, notes)
        pages = [pair for pair in found if pair[0] == "web"]
        spares = [pair for pair in found if pair[0] != "web"]
        if need <= 0:
            return [], found
        if len(pages) < need + 1:
            more = await self._find("web", f"{question} guide", notes)
            known = {normalize_url(hit.url) for _, hit in found}
            pages.extend(
                pair
                for pair in more
                if pair[0] == "web" and normalize_url(pair[1].url) not in known
            )
        pages = _dedupe(pages)
        pages.sort(
            key=lambda pair: -relevance(f"{pair[1].title} {pair[1].snippet}", terms)
        )
        gate = asyncio.Semaphore(READ_CONCURRENCY)
        first = pages[: need + 1]
        read = await asyncio.gather(
            *(self._read(0, "web", hit, terms, gate) for _, hit in first)
        )
        chosen = [source for source in read if source.read][:need]
        chosen += [source for source in read if not source.read][: need - len(chosen)]
        used = {normalize_url(source.url) for source in chosen}
        leftover = [pair for pair in pages if normalize_url(pair[1].url) not in used]
        return chosen, [*leftover, *spares]

    # --------------------------------------------------------------- reddit

    async def _reddit(
        self, question: str, terms: Sequence[str], need: int, notes: list[str]
    ) -> list[Source]:
        """Two threads that are about the question and have a real discussion."""
        if need <= 0:
            return []
        try:
            posts = list(await self._reader.reddit_posts(question, limit=15))
            if len(posts) < need * 3 and terms:
                posts += await self._reader.reddit_posts(" ".join(terms[:6]), limit=15)
            ranked = _rank_posts(posts, terms)
            candidates = [post.hit() for post in ranked]
        except (httpx.HTTPError, ValueError, AttributeError, PlatformError) as error:
            notes.append(f"Reddit search was unavailable ({type(error).__name__}).")
            hits = await self._site_search("reddit.com", question, notes)
            candidates = sorted(
                (hit for hit in hits if "/comments/" in hit.url),
                key=lambda hit: -relevance(f"{hit.title} {hit.snippet}", terms),
            )
        good = await self._read_until(
            "reddit",
            _dedupe_hits(candidates)[: need * 4],
            terms,
            need,
            lambda page: _good_thread(page, terms),
        )
        if len(good) < need:
            notes.append(
                f"Found {len(good)} of {need} Reddit threads that were on topic "
                "and had a real discussion."
            )
        return good

    # -------------------------------------------------------------- youtube

    async def _youtube(
        self, question: str, terms: Sequence[str], need: int, notes: list[str]
    ) -> list[Source]:
        """Two on-topic videos whose transcripts could be read."""
        if need <= 0:
            return []
        videos: list[VideoResult] = []
        try:
            videos = list(await self._reader.youtube_results(question, limit=10))
        except (httpx.HTTPError, ValueError, PlatformError) as error:
            notes.append(f"YouTube search failed ({type(error).__name__}).")
        if len(videos) < need:
            for hit in await self._site_search("youtube.com", question, notes):
                video = youtube_id(hit.url)
                if video and all(item.video_id != video for item in videos):
                    videos.append(
                        VideoResult(
                            video_id=video, title=hit.title, snippet=hit.snippet
                        )
                    )
        ranked = _rank_videos(videos, terms)
        good = await self._read_until(
            "youtube",
            [video.hit() for video in ranked[: need * 4]],
            terms,
            need,
            lambda page: page.transcript,
        )
        if len(good) < need:
            notes.append(
                f"Found {len(good)} of {need} YouTube videos with a readable "
                "transcript."
            )
        return good

    async def _read_until(
        self,
        platform: str,
        candidates: Sequence[SearchHit],
        terms: Sequence[str],
        need: int,
        good: Callable[[PlatformPage], bool],
    ) -> list[Source]:
        """Read candidates a few at a time until enough of them pass."""
        kept: list[Source] = []
        for start in range(0, len(candidates), need + 1):
            batch = candidates[start : start + need + 1]
            pages = await asyncio.gather(
                *(self._platform_page(hit) for hit in batch),
            )
            for hit, page in zip(batch, pages, strict=True):
                if page is None or not good(page) or len(kept) >= need:
                    continue
                if page.platform == "youtube" and page.transcript:
                    self._videos.append(page)
                kept.append(
                    Source(
                        number=0,
                        platform=platform,
                        title=page.title or hit.title,
                        url=page.url if platform == "youtube" else hit.url,
                        excerpt=excerpt(page.text, terms, size=LONG_EXCERPT_CHARS)
                        or hit.snippet,
                        read=True,
                        detail=_detail(page),
                    )
                )
            if len(kept) >= need:
                break
        return kept

    async def _platform_page(self, hit: SearchHit) -> PlatformPage | None:
        try:
            return await self._reader.read(hit.url)
        except httpx.HTTPError, PlatformError, ValueError, OSError:
            return None

    # --------------------------------------------------------------- common

    async def _find(
        self, platform: str, question: str, notes: list[str]
    ) -> list[tuple[str, SearchHit]]:
        try:
            if platform == "reddit":
                hits = await self._site_search("reddit.com", question, notes)
            elif platform == "youtube":
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
        try:
            report = await self._search.search(f"site:{site} {question}", limit=5)
        except (SearchError, ValueError) as error:
            notes.append(f"{site} search failed: {error}")
            return ()
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


async def _no_web() -> tuple[list[Source], list[tuple[str, SearchHit]]]:
    return [], []


def _dedupe(pairs: Sequence[tuple[str, SearchHit]]) -> list[tuple[str, SearchHit]]:
    seen: set[str] = set()
    kept: list[tuple[str, SearchHit]] = []
    for pair in pairs:
        key = normalize_url(pair[1].url)
        if key not in seen:
            seen.add(key)
            kept.append(pair)
    return kept


def _dedupe_hits(hits: Sequence[SearchHit]) -> list[SearchHit]:
    return [hit for _, hit in _dedupe([("", hit) for hit in hits])]


def _rank_posts(posts: Sequence[RedditPost], terms: Sequence[str]) -> list[RedditPost]:
    """On-topic threads with votes and replies first; NSFW and removed ones out."""
    scored: list[tuple[float, RedditPost]] = []
    for post in posts:
        if post.nsfw or post.removed:
            continue
        fit = relevance(f"{post.title} {post.text}", terms)
        if fit < 0.34:
            continue
        weight = (
            fit * 3
            + 0.6 * math.log10(max(post.score, 0) + 1)
            + 0.6 * math.log10(post.comments + 1)
        )
        scored.append((weight, post))
    scored.sort(key=lambda pair: -pair[0])
    return [post for _, post in scored]


def _good_thread(page: PlatformPage, terms: Sequence[str]) -> bool:
    """On topic, and people actually answered or voted on it."""
    discussed = page.comments >= 2 or page.score >= 5
    return discussed and relevance(page.text, terms) >= 0.5


def _rank_videos(
    videos: Sequence[VideoResult], terms: Sequence[str]
) -> list[VideoResult]:
    """On-topic, full-length videos first; the most watched break ties."""
    scored: list[tuple[float, VideoResult]] = []
    for video in videos:
        if video.seconds is not None and video.seconds < MIN_VIDEO_SECONDS:
            continue
        fit = relevance(f"{video.title} {video.snippet}", terms)
        if terms and fit == 0:
            continue
        scored.append((fit * 3 + 0.3 * math.log10((video.views or 0) + 1), video))
    scored.sort(key=lambda pair: -pair[0])
    return [video for _, video in scored]


def _detail(page: PlatformPage) -> str:
    if page.platform == "reddit":
        return f"score {page.score}, {page.comments} comments"
    if page.platform == "youtube":
        return "transcript read" if page.transcript else "no transcript"
    return ""
