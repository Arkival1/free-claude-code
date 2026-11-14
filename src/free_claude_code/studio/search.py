"""Web search for Studio agents, through a keyed search API or DuckDuckGo."""

import asyncio
import html
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from free_claude_code.application.web_tools.ports import WebToolsPort
from free_claude_code.core.json_types import JsonObject

SEARCH_PROVIDERS = ("auto", "duckduckgo", "brave", "tavily", "serper", "searxng")
KEYED_PROVIDERS = frozenset({"brave", "tavily", "serper"})
PROVIDER_LABELS = {
    "duckduckgo": "DuckDuckGo",
    "brave": "Brave Search",
    "tavily": "Tavily",
    "serper": "Serper (Google)",
    "searxng": "SearXNG",
    "wikipedia": "Wikipedia",
}
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "FCC-Studio (+https://github.com/Arkival1/free-claude-code)"
NO_RESULTS_NOTE = (
    "DuckDuckGo returned nothing; it often blocks automated searches. Add a "
    "search API key in Studio settings for reliable results."
)
MAX_SNIPPET_CHARS = 320
_TAG = re.compile(r"<[^>]+>")
_SERPER_KEY = re.compile(r"^[0-9a-f]{40}$")


class SearchError(RuntimeError):
    """Raised when no search provider could answer."""


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result an agent can read or fetch."""

    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class SearchReport:
    """The results of one search and the provider that produced them."""

    provider: str
    hits: tuple[SearchHit, ...]
    note: str = ""


def detect_provider(provider: str, api_key: str, base_url: str) -> str:
    """Resolve ``auto`` from the kind of key or address configured."""
    if provider != "auto":
        return provider
    key = api_key.strip()
    if key.startswith("tvly-"):
        return "tavily"
    if key.startswith("BSA"):
        return "brave"
    if _SERPER_KEY.match(key):
        return "serper"
    if base_url.strip():
        return "searxng"
    return "duckduckgo"


def _clean(text: object) -> str:
    plain = html.unescape(_TAG.sub("", str(text or "")))
    return " ".join(plain.split())[:MAX_SNIPPET_CHARS]


def _hits(rows: object, *, url_key: str, snippet_key: str) -> tuple[SearchHit, ...]:
    if not isinstance(rows, list):
        return ()
    hits: list[SearchHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get(url_key) or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        hits.append(
            SearchHit(
                title=_clean(row.get("title")) or url,
                url=url,
                snippet=_clean(row.get(snippet_key)),
            )
        )
    return tuple(hits)


def _says_bad_key(response: httpx.Response) -> bool:
    """Brave answers an invalid key with 422 and a token error code."""
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    code = str(error.get("code", "")) if isinstance(error, dict) else ""
    return "TOKEN" in code or "KEY" in code


def _failure(provider: str, error: Exception) -> str:
    label = PROVIDER_LABELS.get(provider, provider)
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status in {401, 403} or _says_bad_key(error.response):
            return f"{label} rejected the API key ({status})"
        if status == 429:
            return f"{label} quota or rate limit reached (429)"
        return f"{label} answered {status}"
    if isinstance(error, httpx.HTTPError):
        return f"{label} could not be reached ({type(error).__name__})"
    return f"{label} returned something unexpected ({error})"


FREE_ENOUGH = 3
"""With free search first, this many free results is enough to skip the key."""
CACHE_SECONDS = 6 * 3600
"""The same search within this long reuses its results instead of paying again."""
_SPENDING_STATUSES = frozenset({401, 402, 403, 429, 432, 433})


def _spends_key(error: Exception) -> bool:
    """A key that is refused or out of quota: skip it for the rest of the day."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in _SPENDING_STATUSES or _says_bad_key(
            error.response
        )
    return False


class SearchBudget:
    """How much of the search keys today's searches used, shared by every search."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self.daily_limit = 0
        self._clock = clock
        self._day = ""
        self._used = 0
        self._spent: set[str] = set()
        self._cache: dict[tuple[str, int], tuple[float, SearchReport]] = {}

    def _roll(self) -> None:
        day = time.strftime("%Y-%m-%d", time.localtime(self._clock()))
        if day != self._day:
            self._day, self._used, self._spent = day, 0, set()

    @property
    def used(self) -> int:
        self._roll()
        return self._used

    def spent(self) -> tuple[str, ...]:
        self._roll()
        return tuple(sorted(self._spent))

    def spent_today(self, provider: str) -> bool:
        self._roll()
        return provider in self._spent

    def mark_spent(self, provider: str) -> None:
        self._roll()
        self._spent.add(provider)

    def over_limit(self) -> bool:
        self._roll()
        return self.daily_limit > 0 and self._used >= self.daily_limit

    def count(self) -> None:
        self._roll()
        self._used += 1

    def cached(self, query: str, limit: int) -> SearchReport | None:
        found = self._cache.get((query.casefold(), limit))
        if found is None or self._clock() - found[0] > CACHE_SECONDS:
            return None
        return found[1]

    def remember(self, query: str, limit: int, report: SearchReport) -> SearchReport:
        if report.hits:
            if len(self._cache) > 500:
                self._cache.clear()
            self._cache[(query.casefold(), limit)] = (self._clock(), report)
        return report


class StudioSearch:
    """Search with the configured provider, then a backup key's service, then
    DuckDuckGo."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        base_url: str,
        fallback: WebToolsPort,
        backup_key: str = "",
        order: str = "api_first",
        budget: SearchBudget | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
        retry_delay: float = 1.0,
    ) -> None:
        self._provider = detect_provider(provider, api_key, base_url)
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._backup_key = backup_key.strip()
        # A backup only counts when its key says which keyed service it is.
        backup = detect_provider("auto", self._backup_key, "")
        self._backup = backup if backup in KEYED_PROVIDERS else ""
        self._fallback = fallback
        self._order = order
        self._budget = budget or SearchBudget()
        self._transport = transport
        self._timeout = timeout
        self._retry_delay = retry_delay

    @property
    def provider(self) -> str:
        return self._provider

    def problem(self) -> str:
        """Say why the configured provider cannot be used, or return ''."""
        if self._provider in KEYED_PROVIDERS and not self._api_key:
            return f"{PROVIDER_LABELS[self._provider]} needs an API key."
        if self._provider == "searxng" and not self._base_url:
            return "SearXNG needs its address, e.g. http://localhost:8888."
        return ""

    def status(self) -> JsonObject:
        """Describe the search setup without revealing the key."""
        return {
            "provider": self._provider,
            "label": PROVIDER_LABELS.get(self._provider, self._provider),
            "keyed": self._provider in KEYED_PROVIDERS,
            "key_set": bool(self._api_key),
            "base_url": self._base_url,
            "problem": self.problem(),
            "backup": self._backup,
            "backup_label": PROVIDER_LABELS.get(self._backup, ""),
            "backup_problem": (
                "The backup search key isn't a Tavily, Brave, or Serper key."
                if self._backup_key and not self._backup
                else ""
            ),
            "order": self._order,
            "api_today": self._budget.used,
            "api_limit": self._budget.daily_limit,
            "used_up": [
                PROVIDER_LABELS.get(name, name) for name in self._budget.spent()
            ],
        }

    async def search(self, query: str, *, limit: int = 6) -> SearchReport:
        """Return up to ``limit`` results, noting any fallback that happened.

        With the search order 'api_first' the keyed services go first and free
        search follows; with 'free_first' free search goes first and a key is
        spent only when free search finds too little. A key that runs out or
        is refused is skipped for the rest of the day, and a daily limit caps
        what the keys are used for.
        """
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("A search query is required.")
        budget = self._budget
        cached = budget.cached(cleaned, limit)
        if cached is not None:
            return cached
        if self._order == "free_first":
            free = await self._free_attempt(cleaned, limit)
            if free is not None and len(free.hits) >= min(FREE_ENOUGH, limit):
                return budget.remember(cleaned, limit, free)
        tried: list[str] = []
        keyed = (
            [(self._provider, self._api_key)] if self._provider != "duckduckgo" else []
        )
        if self._backup and self._backup_key != self._api_key:
            keyed.append((self._backup, self._backup_key))
        for index, (provider, key) in enumerate(keyed):
            label = PROVIDER_LABELS.get(provider, provider)
            if index == 0 and self.problem():
                tried.append(self.problem().rstrip("."))
                continue
            metered = provider in KEYED_PROVIDERS
            if metered and budget.spent_today(provider):
                tried.append(f"{label} is used up for today")
                continue
            if metered and budget.over_limit():
                tried.append(
                    f"the daily limit of {budget.daily_limit} API searches is reached"
                )
                continue
            try:
                hits = await self._primary(provider, key, cleaned, limit)
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
                if metered and _spends_key(error):
                    budget.mark_spent(provider)
                tried.append(_failure(provider, error))
                continue
            if metered:
                budget.count()
            used = f"the backup, {label}" if index else label
            note = f"{'; '.join(tried)}. Used {used}." if tried else ""
            return budget.remember(
                cleaned,
                limit,
                SearchReport(provider=provider, hits=hits[:limit], note=note),
            )
        note = f"{'; '.join(tried)}. Used DuckDuckGo instead." if tried else ""
        return budget.remember(
            cleaned, limit, await self._keyless(cleaned, limit, note)
        )

    async def _free_attempt(self, query: str, limit: int) -> SearchReport | None:
        """Free search, without the Wikipedia stand-in, for 'free_first'."""
        try:
            results = await self._fallback.search(query)
        except httpx.HTTPError, OSError, ValueError:
            return None
        hits = tuple(SearchHit(title=item.title, url=item.url) for item in results)
        return SearchReport(provider="duckduckgo", hits=hits[:limit]) if hits else None

    async def _keyless(self, query: str, limit: int, note: str) -> SearchReport:
        """DuckDuckGo, tried twice, then Wikipedia when it comes back empty."""
        failed: Exception | None = None
        for attempt in range(2):
            try:
                results = await self._fallback.search(query)
            except (httpx.HTTPError, OSError, ValueError) as error:
                failed = error
                break
            if results:
                hits = tuple(
                    SearchHit(title=item.title, url=item.url) for item in results
                )
                return SearchReport(provider="duckduckgo", hits=hits[:limit], note=note)
            if attempt == 0:
                await asyncio.sleep(self._retry_delay)
        try:
            wiki = await self._wikipedia(query, limit)
        except httpx.HTTPError, ValueError, TypeError, AttributeError:
            wiki = ()
        prefix = f"{note} " if note else ""
        if wiki:
            return SearchReport(
                provider="wikipedia",
                hits=wiki,
                note=f"{prefix}DuckDuckGo gave no results, so these are from "
                "Wikipedia. Add a search API key for full web search.",
            )
        if failed is not None:
            raise SearchError(
                f"{prefix}DuckDuckGo failed ({type(failed).__name__}) and "
                "Wikipedia had nothing. Set a search API key in Studio settings "
                "for reliable search."
            ) from failed
        return SearchReport(
            provider="duckduckgo", hits=(), note=f"{prefix}{NO_RESULTS_NOTE}"
        )

    async def _wikipedia(self, query: str, limit: int) -> tuple[SearchHit, ...]:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            headers={"user-agent": USER_AGENT},
        ) as client:
            response = await client.get(
                WIKIPEDIA_API,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": limit,
                    "format": "json",
                    "utf8": 1,
                },
            )
            response.raise_for_status()
            rows = (response.json().get("query") or {}).get("search") or []
        return tuple(
            SearchHit(
                title=_clean(row.get("title")),
                url="https://en.wikipedia.org/wiki/"
                + str(row.get("title", "")).replace(" ", "_"),
                snippet=_clean(row.get("snippet")),
            )
            for row in rows
            if isinstance(row, dict) and row.get("title")
        )

    async def _primary(
        self, provider: str, api_key: str, query: str, limit: int
    ) -> tuple[SearchHit, ...]:
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            match provider:
                case "brave":
                    response = await client.get(
                        "https://api.search.brave.com/res/v1/web/search",
                        params={"q": query, "count": limit},
                        headers={
                            "accept": "application/json",
                            "x-subscription-token": api_key,
                        },
                    )
                    response.raise_for_status()
                    web = response.json().get("web") or {}
                    return _hits(
                        web.get("results"), url_key="url", snippet_key="description"
                    )
                case "tavily":
                    response = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "query": query,
                            "max_results": limit,
                            "search_depth": "basic",
                        },
                        headers={"authorization": f"Bearer {api_key}"},
                    )
                    response.raise_for_status()
                    return _hits(
                        response.json().get("results"),
                        url_key="url",
                        snippet_key="content",
                    )
                case "serper":
                    response = await client.post(
                        "https://google.serper.dev/search",
                        json={"q": query, "num": limit},
                        headers={"x-api-key": api_key},
                    )
                    response.raise_for_status()
                    return _hits(
                        response.json().get("organic"),
                        url_key="link",
                        snippet_key="snippet",
                    )
                case "searxng":
                    response = await client.get(
                        f"{self._base_url}/search",
                        params={"q": query, "format": "json"},
                        headers={"accept": "application/json"},
                    )
                    response.raise_for_status()
                    return _hits(
                        response.json().get("results"),
                        url_key="url",
                        snippet_key="content",
                    )
                case _:
                    raise ValueError(f"unknown search provider {provider!r}")
