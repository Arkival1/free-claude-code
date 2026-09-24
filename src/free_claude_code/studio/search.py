"""Web search for Studio agents, through a keyed search API or DuckDuckGo."""

import asyncio
import html
import re
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


class StudioSearch:
    """Search with the configured provider, falling back to DuckDuckGo."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        base_url: str,
        fallback: WebToolsPort,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
        retry_delay: float = 1.0,
    ) -> None:
        self._provider = detect_provider(provider, api_key, base_url)
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._fallback = fallback
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
        }

    async def search(self, query: str, *, limit: int = 6) -> SearchReport:
        """Return up to ``limit`` results, noting any fallback that happened."""
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("A search query is required.")
        note = ""
        if self._provider != "duckduckgo":
            problem = self.problem()
            if problem:
                note = f"{problem} Used DuckDuckGo instead."
            else:
                try:
                    hits = await self._primary(cleaned, limit)
                    return SearchReport(provider=self._provider, hits=hits[:limit])
                except (
                    httpx.HTTPError,
                    ValueError,
                    TypeError,
                    AttributeError,
                ) as error:
                    note = (
                        f"{_failure(self._provider, error)}. Used DuckDuckGo instead."
                    )
        return await self._keyless(cleaned, limit, note)

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

    async def _primary(self, query: str, limit: int) -> tuple[SearchHit, ...]:
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            match self._provider:
                case "brave":
                    response = await client.get(
                        "https://api.search.brave.com/res/v1/web/search",
                        params={"q": query, "count": limit},
                        headers={
                            "accept": "application/json",
                            "x-subscription-token": self._api_key,
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
                        headers={"authorization": f"Bearer {self._api_key}"},
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
                        headers={"x-api-key": self._api_key},
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
                    raise ValueError(f"unknown search provider {self._provider!r}")
