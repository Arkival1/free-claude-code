"""Lore and real pictures of a show, movie, or game, from its Fandom wiki.

Fandom wikis (breakingbad.fandom.com, starwars.fandom.com, ...) hold the
deepest lore there is, and their pictures are stills from the show, named
for what they show ('1x01 - Walt teaching chemistry.jpg'). Wikipedia fills
in when a show has no wiki. Both answer the MediaWiki API; nothing here
needs a key.
"""

import html
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

USER_AGENT = "FCCStudio-ContentFarm/1.0 (local app; one user)"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
MIN_WIDTH = 480
_SKIP_FILES = re.compile(
    r"(logo|icon|favicon|wordmark|signature|flag|symbol|placeholder|\.svg$|\.gif$)",
    re.I,
)
_TAGS = re.compile(r"<[^>]+>")
_REFS = re.compile(r"\[\d+\]|\[citation needed\]|\[edit\]", re.I)
_DROP = re.compile(
    r"<(script|style|table|aside|figure|sup)[^>]*>.*?</\1>", re.I | re.DOTALL
)


@dataclass(frozen=True, slots=True)
class WikiImage:
    url: str
    title: str
    """The file's name without 'File:' and its extension: what it shows."""
    width: int
    height: int
    page: str
    credit: str


def wiki_slug(show: str) -> str:
    """'Breaking Bad' → 'breakingbad', the usual Fandom address."""
    return re.sub(r"[^a-z0-9]+", "", show.lower().removeprefix("the "))


def api_for(link: str) -> str:
    """The API address of a wiki link someone pasted."""
    parts = urlsplit(link.strip() if "://" in link else f"https://{link.strip()}")
    if not parts.netloc:
        return ""
    language = ""
    path = parts.path.strip("/").split("/")
    # breakingbad.fandom.com/es/wiki/... keeps its language.
    if path and len(path[0]) == 2 and path[0] != "wiki":
        language = f"/{path[0]}"
    return f"https://{parts.netloc}{language}/api.php"


def plain(fragment: str) -> str:
    text = _DROP.sub(" ", fragment)
    text = re.sub(r"</(p|li|h[1-6]|div)>", "\n", text, flags=re.I)
    text = html.unescape(_TAGS.sub(" ", text))
    text = _REFS.sub("", text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if len(line.split()) >= 4)


class Fandom:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._wikis: dict[str, str] = {}
        self._cache: dict[tuple[str, ...], object] = {}

    async def _get(self, api: str, params: dict[str, str | int]) -> dict:
        key = (api, *(f"{k}={v}" for k, v in sorted(params.items())))
        if key in self._cache:
            cached = self._cache[key]
            return cached if isinstance(cached, dict) else {}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=10.0),
            transport=self._transport,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            try:
                response = await client.get(
                    api, params={**params, "format": "json", "formatversion": 2}
                )
            except httpx.HTTPError:
                return {}
        if response.status_code >= 400:
            return {}
        try:
            body = response.json()
        except ValueError:
            return {}
        if isinstance(body, dict):
            if len(self._cache) > 400:
                self._cache.clear()
            self._cache[key] = body
            return body
        return {}

    async def wiki_for(self, show: str, link: str = "") -> str:
        """The API of the show's Fandom wiki, else Wikipedia's."""
        cache_key = f"{show.lower()}|{link}"
        if cache_key in self._wikis:
            return self._wikis[cache_key]
        candidates = [api_for(link)] if link else []
        slug = wiki_slug(show)
        if slug:
            candidates.append(f"https://{slug}.fandom.com/api.php")
            words = re.sub(r"[^a-z0-9 ]+", "", show.lower()).split()
            if len(words) > 1:
                candidates.append(f"https://{words[0]}.fandom.com/api.php")
        found = WIKIPEDIA
        for api in candidates:
            if not api:
                continue
            body = await self._get(api, {"action": "query", "meta": "siteinfo"})
            general = body.get("query", {}).get("general", {}) if body else {}
            if general:
                found = api
                break
        self._wikis[cache_key] = found
        return found

    async def search(self, api: str, query: str, *, limit: int = 5) -> list[str]:
        body = await self._get(
            api,
            {"action": "query", "list": "search", "srsearch": query, "srlimit": limit},
        )
        rows = body.get("query", {}).get("search", []) if body else []
        return [str(row.get("title")) for row in rows if row.get("title")]

    async def page_text(self, api: str, title: str, *, limit: int = 14_000) -> str:
        body = await self._get(
            api,
            {"action": "parse", "page": title, "prop": "text", "redirects": 1},
        )
        parsed = body.get("parse", {}) if body else {}
        text = parsed.get("text", "") if isinstance(parsed, dict) else ""
        if isinstance(text, dict):
            text = text.get("*", "")
        return plain(str(text))[:limit]

    async def page_images(
        self, api: str, title: str, *, limit: int = 30
    ) -> list[WikiImage]:
        """Pictures on a wiki page, big enough for a video."""
        body = await self._get(
            api,
            {
                "action": "query",
                "titles": title,
                "generator": "images",
                "gimlimit": min(50, limit * 2),
                "prop": "imageinfo",
                "iiprop": "url|size|mime",
                "redirects": 1,
            },
        )
        pages = body.get("query", {}).get("pages", []) if body else []
        site = urlsplit(api).netloc
        found: list[WikiImage] = []
        for page in pages if isinstance(pages, list) else []:
            name = str(page.get("title", "")).removeprefix("File:")
            info = (page.get("imageinfo") or [{}])[0]
            url = str(info.get("url") or "")
            width = int(info.get("width") or 0)
            if (
                not url.startswith("https://")
                or _SKIP_FILES.search(name)
                or width < MIN_WIDTH
                or str(info.get("mime", ""))
                not in {"image/jpeg", "image/png", "image/webp"}
            ):
                continue
            found.append(
                WikiImage(
                    url=url,
                    title=re.sub(r"\.\w{3,4}$", "", name).replace("_", " "),
                    width=width,
                    height=int(info.get("height") or 0),
                    page=title,
                    credit=f"Image: {site} ({title})",
                )
            )
        return found[:limit]

    async def lore(
        self, show: str, topic: str, *, link: str = "", chars: int = 5_000
    ) -> str:
        """What the wiki says about a topic in a show, as plain text."""
        api = await self.wiki_for(show, link)
        query = topic if api != WIKIPEDIA else f"{show} {topic}"
        titles = await self.search(api, query, limit=3)
        parts: list[str] = []
        for title in titles[:2]:
            text = await self.page_text(api, title, limit=chars)
            if text:
                parts.append(f"From the wiki page '{title}':\n{text}")
        return "\n\n".join(parts)[:chars]

    async def pictures(
        self, show: str, topic: str, *, link: str = "", limit: int = 30
    ) -> list[WikiImage]:
        """Real pictures for a topic: from the best pages the wiki finds."""
        api = await self.wiki_for(show, link)
        query = topic if api != WIKIPEDIA else f"{show} {topic}"
        found: list[WikiImage] = []
        for title in await self.search(api, query, limit=3):
            found += await self.page_images(api, title, limit=limit)
            if len(found) >= limit:
                break
        seen: dict[str, WikiImage] = {}
        for image in found:
            seen.setdefault(image.url, image)
        return list(seen.values())[:limit]
