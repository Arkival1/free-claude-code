"""Read Reddit threads and YouTube videos the way a researcher would."""

import html as html_lib
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
MAX_VIDEO_TRANSCRIPT_CHARS = 120_000
"""A study copy keeps up to about two hours of speech; reports use less."""
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
_INITIAL_DATA = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)
_XML_CAPTION = re.compile(
    r'<text(?:[^>]*?\sstart="([0-9.]+)")?[^>]*>(.*?)</text>', re.S
)
_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")
# The Android app's player answer carries caption links that YouTube hands
# over even when the watch page is behind a consent or bot check.
_PLAYER_URL = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
_PLAYER_CLIENT = {"clientName": "ANDROID", "clientVersion": "20.10.38", "hl": "en"}
# Only videos (no channels, playlists, or shorts shelves) in YouTube search.
_VIDEOS_ONLY = "EgIQAQ%3D%3D"
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
    score: int = 0
    comments: int = 0
    transcript: bool = False
    segments: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RedditPost:
    """One Reddit search result, with the numbers that say whether it is good."""

    title: str
    url: str
    subreddit: str
    score: int = 0
    comments: int = 0
    text: str = ""
    nsfw: bool = False
    removed: bool = False

    def hit(self) -> SearchHit:
        return SearchHit(
            title=f"r/{self.subreddit}: {self.title}",
            url=self.url,
            snippet=f"{self.comments} comments. {self.text[:240]}",
        )


@dataclass(frozen=True, slots=True)
class VideoResult:
    """One YouTube search result."""

    video_id: str
    title: str
    channel: str = ""
    seconds: int | None = None
    views: int | None = None
    snippet: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    def hit(self) -> SearchHit:
        by = f" ({self.channel})" if self.channel else ""
        return SearchHit(title=f"{self.title}{by}", url=self.url, snippet=self.snippet)


def _clock_seconds(text: str) -> int | None:
    match = _CLOCK.match(text.strip())
    if not match:
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _runs(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    if "simpleText" in data:
        return str(data["simpleText"])
    runs = data.get("runs")
    return (
        "".join(str(run.get("text", "")) for run in runs if isinstance(run, dict))
        if isinstance(runs, list)
        else ""
    )


def _video_renderers(data: object) -> list[JsonObject]:
    found: list[JsonObject] = []
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            renderer = item.get("videoRenderer")
            if isinstance(renderer, dict):
                found.append(renderer)
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))
    return found


def parse_youtube_results(page: str, *, limit: int = 10) -> tuple[VideoResult, ...]:
    """Read the videos out of a YouTube search results page."""
    match = _INITIAL_DATA.search(page)
    if not match:
        return ()
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return ()
    videos: list[VideoResult] = []
    seen: set[str] = set()
    for renderer in _video_renderers(data):
        video = str(renderer.get("videoId") or "")
        if not _VIDEO_ID.match(video) or video in seen:
            continue
        seen.add(video)
        views = re.sub(r"[^0-9]", "", _runs(renderer.get("viewCountText")))
        snippets = renderer.get("detailedMetadataSnippets")
        snippet = (
            _runs(snippets[0].get("snippetText"))
            if isinstance(snippets, list) and snippets and isinstance(snippets[0], dict)
            else ""
        )
        videos.append(
            VideoResult(
                video_id=video,
                title=_runs(renderer.get("title")),
                channel=_runs(renderer.get("ownerText")),
                seconds=_clock_seconds(_runs(renderer.get("lengthText"))),
                views=int(views) if views else None,
                snippet=snippet,
            )
        )
        if len(videos) >= limit:
            break
    return tuple(videos)


def caption_segments(body: str) -> tuple[tuple[int, str], ...]:
    """Turn YouTube caption data (json3 or XML) into (second, words) lines."""
    lines: list[tuple[int, str]] = []
    try:
        events = json.loads(body).get("events") or []
    except ValueError, AttributeError:
        for start, piece in _XML_CAPTION.findall(body):
            words = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", "", piece)).split())
            if words:
                lines.append((int(float(start or 0)), words))
        return tuple(lines)
    for event in events:
        if not isinstance(event, dict):
            continue
        words = " ".join(
            "".join(
                str(segment.get("utf8", ""))
                for segment in event.get("segs") or []
                if isinstance(segment, dict)
            ).split()
        )
        if words:
            start = event.get("tStartMs")
            lines.append(
                (int(start) // 1000 if isinstance(start, int | float) else 0, words)
            )
    return tuple(lines)


def caption_text(body: str) -> str:
    """Turn YouTube caption data (json3 or XML) into plain text."""
    return " ".join(words for _, words in caption_segments(body))


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


def _int(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


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

    async def reddit_posts(
        self, query: str, *, limit: int = 15
    ) -> tuple[RedditPost, ...]:
        """Search every subreddit, keeping each thread's score and comment count."""
        body = await self._reddit_get(
            "/search",
            {
                "q": query,
                "limit": limit,
                "sort": "relevance",
                "t": "all",
                "type": "link",
            },
        )
        if not isinstance(body, dict):
            raise PlatformError("Reddit sent back something unexpected.")
        children = ((body.get("data") or {}).get("children")) or []
        posts: list[RedditPost] = []
        for child in children:
            data = child.get("data") if isinstance(child, dict) else None
            if not isinstance(data, dict):
                continue
            permalink = _field(data, "permalink")
            if not permalink.startswith("/r/"):
                continue
            text = _field(data, "selftext")
            posts.append(
                RedditPost(
                    title=_field(data, "title"),
                    url=f"https://www.reddit.com{permalink}",
                    subreddit=_field(data, "subreddit"),
                    score=_int(data.get("score")),
                    comments=_int(data.get("num_comments")),
                    text=text,
                    nsfw=bool(data.get("over_18")),
                    removed=text in {"[removed]", "[deleted]"}
                    or bool(data.get("removed_by_category")),
                )
            )
        return tuple(posts[:limit])

    async def reddit_search(
        self, query: str, *, limit: int = 6
    ) -> tuple[SearchHit, ...]:
        """Search every subreddit for threads about a query."""
        posts = await self.reddit_posts(query, limit=limit)
        return tuple(post.hit() for post in posts)

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
        said = [
            data
            for data in comments
            if isinstance(data, dict)
            and _field(data, "body").strip() not in {"", "[removed]", "[deleted]"}
        ]
        return PlatformPage(
            platform="reddit",
            url=url,
            title=title,
            text="\n".join(lines),
            score=_int(post.get("score")) if isinstance(post, dict) else 0,
            comments=max(
                len(said),
                _int(post.get("num_comments")) if isinstance(post, dict) else 0,
            ),
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

    async def youtube_results(
        self, query: str, *, limit: int = 10
    ) -> tuple[VideoResult, ...]:
        """Find videos: the YouTube API with a key, the results page without one."""
        if self._youtube_key:
            hits = await self.youtube_search(query, limit=limit)
            return tuple(
                VideoResult(
                    video_id=youtube_id(hit.url) or "",
                    title=hit.title,
                    snippet=hit.snippet,
                )
                for hit in hits
                if youtube_id(hit.url)
            )
        async with self._client(
            BROWSER_HEADERS, cookies={"CONSENT": "YES+1"}
        ) as client:
            response = await client.get(
                f"https://www.youtube.com/results?sp={_VIDEOS_ONLY}",
                params={"search_query": query, "hl": "en"},
            )
            response.raise_for_status()
            return parse_youtube_results(response.text, limit=limit)

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
            page = await client.get(f"{watch}&hl=en")
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
            segments, note = await self._transcript(client, html)
            if not segments:
                player = await self._player(client, video)
                if player is not None:
                    details = player.get("videoDetails")
                    description = description or _field(details, "shortDescription")
                    found, _ = await self._read_tracks(client, _caption_tracks(player))
                    if found:
                        segments, note = found, ""
        transcript = " ".join(words for _, words in segments)[:MAX_TRANSCRIPT_CHARS]
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
            transcript=bool(transcript),
            segments=segments,
        )

    @staticmethod
    async def _player(client: httpx.AsyncClient, video: str) -> JsonObject | None:
        """Ask YouTube's player API about a video, the way its Android app does."""
        try:
            response = await client.post(
                _PLAYER_URL,
                json={"context": {"client": _PLAYER_CLIENT}, "videoId": video},
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError, ValueError:
            return None
        return body if isinstance(body, dict) else None

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
    ) -> tuple[tuple[tuple[int, str], ...], str]:
        found = _CAPTIONS.search(html)
        if not found:
            return (), "This video has no captions YouTube would share."
        try:
            tracks = json.loads(found.group(1))
        except ValueError:
            return (), "Could not read this video's caption list."
        return await self._read_tracks(client, tracks)

    @staticmethod
    async def _read_tracks(
        client: httpx.AsyncClient, tracks: object
    ) -> tuple[tuple[tuple[int, str], ...], str]:
        if not isinstance(tracks, list) or not tracks:
            return (), "This video has no captions."
        english = [
            track
            for track in tracks
            if isinstance(track, dict)
            and str(track.get("languageCode", "")).startswith("en")
        ]
        usable = english or [track for track in tracks if isinstance(track, dict)]
        if not usable:
            return (), "This video has no captions."
        track: JsonObject = usable[0]
        base = str(track.get("baseUrl") or "")
        if not base.startswith("https://www.youtube.com/"):
            return (), "This video's captions are not readable."
        base = re.sub(r"&fmt=[^&]*", "", base)
        try:
            response = await client.get(f"{base}&fmt=json3")
            response.raise_for_status()
            segments = caption_segments(response.text)
        except httpx.HTTPError:
            return (), "YouTube would not hand over this video's captions."
        if not segments:
            return (), "This video's captions were empty."
        return _cap_segments(segments), ""


def _cap_segments(
    segments: tuple[tuple[int, str], ...],
) -> tuple[tuple[int, str], ...]:
    """Keep a long video's lines up to the transcript size limit."""
    kept: list[tuple[int, str]] = []
    used = 0
    for start, words in segments:
        used += len(words) + 1
        if used > MAX_VIDEO_TRANSCRIPT_CHARS:
            break
        kept.append((start, words))
    return tuple(kept)


def _caption_tracks(player: JsonObject) -> object:
    captions = player.get("captions")
    renderer = (
        captions.get("playerCaptionsTracklistRenderer")
        if isinstance(captions, dict)
        else None
    )
    return renderer.get("captionTracks") if isinstance(renderer, dict) else None
