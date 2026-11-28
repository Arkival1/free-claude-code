"""Download a YouTube video's audio on this PC, for JARVIS's video notes.

Uses yt-dlp (audio only, no conversion) with the Deno runtime that ships with
FCC for YouTube's JavaScript checks. Files are kept in FCC's config folder and
reused, so a video is only downloaded once.
"""

import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

AUDIO_EXTS = ("m4a", "webm", "opus", "mp3")
MAX_BYTES = 600 * 1024 * 1024
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


class YouTubeError(RuntimeError):
    """The audio could not be downloaded; the message says why in plain words."""


def video_id(url: str) -> str:
    """The 11-character id of a single YouTube video link, or YouTubeError."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError as exc:
        raise YouTubeError("That is not a YouTube link.") from exc
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or host not in _HOSTS:
        raise YouTubeError("Only YouTube video links can be downloaded.")
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
    elif parts.path.startswith(("/shorts/", "/live/", "/embed/")):
        candidate = parts.path.split("/")[2]
    else:
        candidate = (parse_qs(parts.query).get("v") or [""])[0]
    if not _VIDEO_ID.fullmatch(candidate):
        raise YouTubeError("That link has no single YouTube video in it.")
    return candidate


def _deno_path() -> str | None:
    try:
        import deno

        return str(deno.find_deno_bin())
    except ImportError, OSError, RuntimeError:
        return None


def _default_ydl(options: dict[str, Any]) -> Any:
    import yt_dlp

    return yt_dlp.YoutubeDL(options)


def plain_error(message: str) -> str:
    low = message.lower()
    if "not a bot" in low or "sign in to confirm" in low:
        return (
            "YouTube asked to confirm you are not a bot. Open the video once in your "
            "browser, wait a minute, then try again (or use the ytmp3 route)."
        )
    if (
        "private video" in low
        or "members-only" in low
        or ("age" in low and "confirm" in low)
    ):
        return "This video is private, members-only or age-restricted, so it cannot be downloaded."
    if "max_filesize" in low or "larger than max" in low:
        return "This video's audio is too big (over 600 MB)."
    if "unavailable" in low:
        return "YouTube says this video is unavailable."
    return "YouTube download failed: " + message.replace("ERROR: ", "")[:300]


class YouTubeAudio:
    def __init__(
        self, root: Path, *, ydl_factory: Callable[[dict[str, Any]], Any] = _default_ydl
    ) -> None:
        self.root = root
        self._factory = ydl_factory
        self._lock = threading.Lock()

    def existing(self, vid: str) -> Path | None:
        for ext in AUDIO_EXTS:
            path = self.root / f"{vid}.{ext}"
            if path.is_file() and path.stat().st_size > 0:
                return path
        return None

    def download(self, url: str) -> dict[str, Any]:
        vid = video_id(url)
        canonical = f"https://www.youtube.com/watch?v={vid}"
        with self._lock:  # one download at a time keeps YouTube happy
            self.root.mkdir(parents=True, exist_ok=True)
            found = self.existing(vid)
            title, duration = "", 0
            if found is None:
                options: dict[str, Any] = {
                    "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "noprogress": True,
                    "outtmpl": str(self.root / "%(id)s.%(ext)s"),
                    "max_filesize": MAX_BYTES,
                    "postprocessors": [],
                }
                deno_bin = _deno_path()
                if deno_bin:
                    options["js_runtimes"] = {"deno": {"path": deno_bin}}
                try:
                    with self._factory(options) as ydl:
                        info = ydl.extract_info(canonical, download=True) or {}
                except Exception as exc:  # yt-dlp raises many error types
                    raise YouTubeError(plain_error(str(exc))) from exc
                title = str(info.get("title") or "")[:200]
                duration = int(info.get("duration") or 0)
                found = self.existing(vid)
                if found is None:
                    raise YouTubeError("YouTube gave no audio file for this video.")
            return {
                "video_id": vid,
                "url": canonical,
                "path": found,
                "ext": found.suffix.lstrip("."),
                "bytes": found.stat().st_size,
                "title": title,
                "duration": duration,
            }
