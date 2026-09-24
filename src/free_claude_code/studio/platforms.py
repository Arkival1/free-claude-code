"""Read Reddit threads and YouTube videos the way a researcher would."""

import json
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx

from free_claude_code.core.json_types import JsonObject

from .search import SearchHit

USER_AGENT = "FCC-Studio research agent (+https://github.com/Arkival1/free-claude-code)"
BROWSER_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (compatible; FCC-Studio/1.0; "
        "+https://github.com/Arkival1/free-claude-code)"
    ),
    "accept-language": "en-US,en;q=0.9",
}
MAX_COMMENTS = 12
MAX_TRANSCRIPT_CHARS = 20_000
_REDDIT_HOSTS = frozenset(
    {
        "reddit.com",
        "www.reddit.com",
        "old.reddit.com",
        "new.reddit.com",
        "np.reddit.com",
    }
)
_YOUTUBE_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
)
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CAPTIONS = re.compile(r'"captionTracks":(\[.*?\])')
_DESCRIPTION = re.compile(r'"shortDescription":"((?:[^"\\]|\\.)*)"')
_TITLE = re.compile(r'<meta name="title" content="([^"]*)"')
_REDDIT_TOKENS: dict[str, tuple[str, float]] = {}
"""App-only Reddit tokens by client id, with their expiry time."""


class PlatformError(RuntimeError):
    """Raised when a platform page cannot be read."""


@dataclass(frozen=True, slots=True)
class PlatformPage:
    """Readable text from one platform page."""

    platform: str
    url: str
    title: str
    text: str
    note: str = ""


def platform_of(url: str) -> str:
    """Return ``reddit``, ``youtube``, or ``web`` for a URL."""
    host = (urlsplit(url).hostname or "").lower()
    if host in _REDDIT_HOSTS:
        return "reddit"
    if host in _YOUTUBE_HOSTS:
        return "youtube"
    return "web"


def youtube_id(url: str) -> str | None:
    """Pull the video id out of any common YouTube link."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    candidate = ""
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        if parts.path == "/watch":
            candidate = parse_qs(parts.query).get("v", [""])[0]
        else:
            pieces = [piece for piece in parts.path.split("/") if piece]
            if len(pieces) >= 2 and pieces[0] in {"shorts", "embed", "live", "v"}:
                candidate = pieces[1]
    return candidate if _VIDEO_ID.match(candidate) else None


def _reddit_path(url: str) -> str:
    parts = urlsplit(url)
    if "/comments/" not in parts.path:
        raise PlatformError("That Reddit link is not a thread.")
    return parts.path.rstrip("/").removesuffix(".json")


def _field(data: object, key: str) -> str:
    return str(data.get(key) or "") if isinstance(data, dict) else ""


class PlatformReader:
    """Search and read Reddit and YouTube without a browser."""

    def __init__(
        self,
        *,
        youtube_api_key: str = "",
        reddit_client_id: str = "",
        reddit_client_secret: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._youtube_key = youtube_api_key.strip()
        self._reddit_id = reddit_client_id.strip()
        self._reddit_secret = reddit_client_secret.strip()
        self._transport = transport
        self._timeout = timeout

    @property
    def youtube_search_ready(self) -> bool:
        return bool(self._youtube_key)

    @property
    def reddit_app_ready(self) -> bool:
        return bool(self._reddit_id and self._reddit_secret)

    async def _reddit_get(self, path: str, params: dict[str, str | int]) -> object:
        """GET a Reddit listing, through the official API when an app is set."""
        headers = {"user-agent": USER_AGENT}
        if self.reddit_app_ready:
            headers["authorization"] = f"bearer {await self._reddit_token()}"
            url = f"https://oauth.reddit.com{path}"
        else:
            url = f"https://www.reddit.com{path}.json"
        async with self._client(headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def _reddit_token(self) -> str:
        cached = _REDDIT_TOKENS.get(self._reddit_id)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]
        async with self._client({"user-agent": USER_AGENT}) as client:
            response = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(self._reddit_id, self._reddit_secret),
            )
            response.raise_for_status()
            body = response.json()
        token = str(body.get("access_token") or "")
        if not token:
            raise PlatformError("Reddit did not accept the app credentials.")
        lifetime = float(body.get("expires_in") or 3600)
        _REDDIT_TOKENS[self._reddit_id] = (token, time.monotonic() + lifetime - 60)
        return token

    def _client(
        self, headers: dict[str, str], *, cookies: dict[str, str] | None = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            headers=headers,
            cookies=cookies,
            follow_redirects=True,
        )

    async def read(self, url: str) -> PlatformPage:
        """Read a Reddit thread or a YouTube video's transcript."""
        match platform_of(url):
            case "reddit":
                return await self.reddit_thread(url)
            case "youtube":
                return await self.youtube_video(url)
            case _:
                raise PlatformError("Not a Reddit or YouTube link.")

    # ---------------------------------------------------------------- reddit

    async def reddit_search(
        self, query: str, *, limit: int = 6
    ) -> tuple[SearchHit, ...]:
        """Search every subreddit for threads about a query."""
        body = await self._reddit_get(
            "/search", {"q": query, "limit": limit, "sort": "relevance", "t": "all"}
        )
        if not isinstance(body, dict):
            raise PlatformError("Reddit sent back something unexpected.")
        children = ((body.get("data") or {}).get("children")) or []
        hits: list[SearchHit] = []
        for child in children:
            data = child.get("data") if isinstance(child, dict) else None
            permalink = _field(data, "permalink")
            if not permalink.startswith("/r/"):
                continue
            subreddit = _field(data, "subreddit")
            comments = data.get("num_comments", 0) if isinstance(data, dict) else 0
            hits.append(
                SearchHit(
                    title=f"r/{subreddit}: {_field(data, 'title')}",
                    url=f"https://www.reddit.com{permalink}",
                    snippet=f"{comments} comments. {_field(data, 'selftext')[:240]}",
                )
            )
        return tuple(hits[:limit])

    async def reddit_thread(self, url: str) -> PlatformPage:
        """Read a thread's post and its top comments."""
        body = await self._reddit_get(
            _reddit_path(url), {"limit": 40, "depth": 1, "sort": "top"}
        )
        if not isinstance(body, list) or len(body) < 2:
            raise PlatformError("Reddit sent back something unexpected.")
        posts = (body[0].get("data") or {}).get("children") or []
        post = posts[0].get("data") if posts else {}
        title = _field(post, "title")
        lines = [
            f"r/{_field(post, 'subreddit')} · {title} "
            f"(score {post.get('score', 0) if isinstance(post, dict) else 0})",
        ]
        if _field(post, "selftext"):
            lines.extend(["", _field(post, "selftext")])
        comments = [
            child.get("data")
            for child in (body[1].get("data") or {}).get("children") or []
            if isinstance(child, dict) and child.get("kind") == "t1"
        ]
        comments.sort(
            key=lambda data: data.get("score", 0) if isinstance(data, dict) else 0,
            reverse=True,
        )
        if comments:
            lines.extend(["", "Top comments:"])
            lines.extend(
                f"- ({data.get('score', 0)}) {_field(data, 'body').strip()}"
                for data in comments[:MAX_COMMENTS]
                if isinstance(data, dict) and _field(data, "body").strip()
            )
        return PlatformPage(
            platform="reddit", url=url, title=title, text="\n".join(lines)
        )

    # --------------------------------------------------------------- youtube

    async def youtube_search(
        self, query: str, *, limit: int = 5
    ) -> tuple[SearchHit, ...]:
        """Search YouTube with the Data API; needs a YouTube API key."""
        if not self._youtube_key:
            raise PlatformError("YouTube search needs a YouTube API key.")
        async with self._client({"accept": "application/json"}) as client:
            response = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "type": "video",
                    "maxResults": limit,
                    "q": query,
                    "key": self._youtube_key,
                },
            )
            response.raise_for_status()
            items = response.json().get("items") or []
        hits: list[SearchHit] = []
        for item in items:
            video = _field(
                item.get("id") if isinstance(item, dict) else None, "videoId"
            )
            snippet = item.get("snippet") if isinstance(item, dict) else None
            if not _VIDEO_ID.match(video):
                continue
            hits.append(
                SearchHit(
                    title=f"{_field(snippet, 'title')} ({_field(snippet, 'channelTitle')})",
                    url=f"https://www.youtube.com/watch?v={video}",
                    snippet=_field(snippet, "description")[:240],
                )
            )
        return tuple(hits[:limit])

    async def youtube_video(self, url: str) -> PlatformPage:
        """Read a video's title, description, and transcript when it has one."""
        video = youtube_id(url)
        if video is None:
            raise PlatformError("That YouTube link has no video id.")
        watch = f"https://www.youtube.com/watch?v={video}"
        # The consent cookie skips the EU cookie wall that hides the page.
        async with self._client(
            BROWSER_HEADERS, cookies={"CONSENT": "YES+1"}
        ) as client:
            page = await client.get(watch, params={"hl": "en"})
            page.raise_for_status()
            html = page.text
            title_match = _TITLE.search(html)
            title = title_match.group(1) if title_match else f"YouTube video {video}"
            description = ""
            described = _DESCRIPTION.search(html)
            if described:
                try:
                    description = json.loads(f'"{described.group(1)}"')
                except ValueError:
                    description = ""
            if not title_match:
                title = await self._oembed_title(client, watch) or title
            transcript, note = await self._transcript(client, html)
        parts = [title]
        if description:
            parts.extend(["", "Description:", description[:2_000]])
        if transcript:
            parts.extend(["", "Transcript:", transcript])
        return PlatformPage(
            platform="youtube",
            url=watch,
            title=title,
            text="\n".join(parts),
            note=note,
        )

    @staticmethod
    async def _oembed_title(client: httpx.AsyncClient, watch: str) -> str:
        """Ask YouTube's public oEmbed endpoint for the title and channel."""
        try:
            response = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": watch, "format": "json"},
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError, ValueError:
            return ""
        title = _field(body, "title")
        author = _field(body, "author_name")
        return f"{title} ({author})" if title and author else title

    async def _transcript(
        self, client: httpx.AsyncClient, html: str
    ) -> tuple[str, str]:
        found = _CAPTIONS.search(html)
        if not found:
            return "", "This video has no captions YouTube would share."
        try:
            tracks = json.loads(found.group(1))
        except ValueError:
            return "", "Could not read this video's caption list."
        if not isinstance(tracks, list) or not tracks:
            return "", "This video has no captions."
        english = [
            track
            for track in tracks
            if isinstance(track, dict)
            and str(track.get("languageCode", "")).startswith("en")
        ]
        usable = english or [track for track in tracks if isinstance(track, dict)]
        if not usable:
            return "", "This video has no captions."
        track: JsonObject = usable[0]
        base = str(track.get("baseUrl") or "")
        if not base.startswith("https://www.youtube.com/"):
            return "", "This video's captions are not readable."
        try:
            response = await client.get(f"{base}&fmt=json3")
            response.raise_for_status()
            events = response.json().get("events") or []
        except httpx.HTTPError, ValueError:
            return "", "YouTube would not hand over this video's captions."
        words = [
            str(segment.get("utf8", ""))
            for event in events
            if isinstance(event, dict)
            for segment in event.get("segs") or []
            if isinstance(segment, dict)
        ]
        text = " ".join("".join(words).split())
        if not text:
            return "", "This video's captions were empty."
        return text[:MAX_TRANSCRIPT_CHARS], ""
