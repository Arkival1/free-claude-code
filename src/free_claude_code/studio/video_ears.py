"""Watch a video on this PC: hear what it says with Whisper, offline.

When a video has no captions to read (or is not on YouTube, or is a file on
this PC), Studio listens to it instead: yt-dlp fetches just the sound of a
web video, and faster-whisper, the same speech recognition the main AI's
ears use, writes down what is said with the time it is said. Nothing is
sent anywhere: the sound and the words stay on this computer.
"""

import asyncio
import contextlib
import hashlib
import importlib.util
import shutil
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from loguru import logger

from .desk import is_private_host

MEDIA_SUFFIXES = frozenset(
    {
        ".mp4",
        ".m4v",
        ".mkv",
        ".webm",
        ".mov",
        ".avi",
        ".wmv",
        ".flv",
        ".mpg",
        ".mpeg",
        ".3gp",
        ".ts",
        ".mp3",
        ".m4a",
        ".aac",
        ".wav",
        ".ogg",
        ".opus",
        ".flac",
        ".wma",
    }
)
MAX_DOWNLOAD_BYTES = 600 * 1024 * 1024
LINE_SECONDS = 12
"""Whisper's short pieces are joined into lines about this long, like captions."""

Hear = Callable[[Path, int], tuple[list[tuple[float, str]], float]]
"""Turn a sound or video file into (start seconds, words) pieces and its
length; refuses files longer than the minutes given. Runs on a thread."""
Fetch = Callable[[str, Path, int], tuple[Path, str]]
"""Download a web video's sound into a folder: the file and the title."""
Record = Callable[[str, Path, int], Awaitable[tuple[Path, str, float]]]
"""Record a web video's sound as it plays (in the desktop browser), for
when it cannot be downloaded: the recording, the title, and the speed it
played at."""


class VideoEarsError(ValueError):
    """Raised when a video cannot be listened to."""


class VideoTooLong(VideoEarsError):
    """Raised for a video longer than agents may listen to."""


def ytdlp_ready() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None


@dataclass(frozen=True, slots=True)
class Heard:
    """What a video says, line by line, with when each line starts."""

    key: str
    url: str
    title: str
    segments: tuple[tuple[int, str], ...]
    seconds: int = 0


def local_media(target: str, home: Path) -> Path | None:
    """A video or sound file in the user's folders, or None when the target
    is not a file path (a web link, say)."""
    text = target.strip().strip('"').strip("'")
    if not text:
        return None
    if text.lower().startswith("file:"):
        text = unquote(urlparse(text).path)
        if len(text) > 2 and text[0] == "/" and text[2] == ":":
            text = text[1:]  # file:///C:/Users/... on Windows
    elif "://" in text:
        return None
    looks_like_path = (
        text.startswith(("/", "~", "\\"))
        or (len(text) > 2 and text[1] == ":" and text[2] in "\\/")
        or Path(text).suffix.lower() in MEDIA_SUFFIXES
    )
    if not looks_like_path:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = home / path
    path = path.resolve()
    if path.suffix.lower() not in MEDIA_SUFFIXES:
        raise VideoEarsError(f"{path.name} is not a video or sound file.")
    if not path.is_relative_to(home.resolve()):
        raise VideoEarsError(
            "Agents only watch videos in your own folders (Videos, Downloads, "
            "Desktop, Documents, …)."
        )
    if not path.is_file():
        raise VideoEarsError(f"There is no video at {path}.")
    return path


def file_key(path: Path) -> str:
    """The same file gives the same key until it changes."""
    stat = path.stat()
    raw = f"{path}:{stat.st_size}:{stat.st_mtime_ns}"
    return "file-" + hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def link_key(url: str) -> str:
    return "web-" + hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:16]


def join_lines(
    pieces: Sequence[tuple[float, str]], *, every: int = LINE_SECONDS
) -> tuple[tuple[int, str], ...]:
    """Join Whisper's pieces into caption-sized lines that keep their start."""
    lines: list[tuple[int, str]] = []
    start: int | None = None
    words: list[str] = []
    for at, text in pieces:
        text = text.strip()
        if not text:
            continue
        if start is None:
            start = int(at)
        words.append(text)
        if at - start >= every or text.endswith((".", "?", "!")):
            lines.append((start, " ".join(words)))
            start, words = None, []
    if words and start is not None:
        lines.append((start, " ".join(words)))
    return tuple(lines)


def ytdlp_fetch(url: str, folder: Path, max_minutes: int) -> tuple[Path, str]:
    """Download only the sound of a web video with yt-dlp (runs on a thread)."""
    if not ytdlp_ready():
        raise VideoEarsError(
            "Listening to web videos needs yt-dlp. Run the Windows installer "
            "again (it adds it), or run: uv sync --extra studio_desk"
        )
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    options: dict[str, Any] = {
        "format": "bestaudio/best[height<=360]/best",
        "outtmpl": str(folder / "sound.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "max_filesize": MAX_DOWNLOAD_BYTES,
        "restrictfilenames": True,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict):
                raise VideoEarsError("That link has no video to listen to.")
            if info.get("_type") == "playlist":
                raise VideoEarsError("That is a playlist: give one video's link.")
            length = int(info.get("duration") or 0)
            if length > max_minutes * 60:
                raise VideoTooLong(
                    f"The video is {length // 60} minutes long; agents listen to "
                    f"videos up to {max_minutes} minutes (Settings)."
                )
            ydl.process_ie_result(info, download=True)
    except DownloadError as error:
        raise VideoEarsError(f"Could not get the video's sound: {error}") from error
    found = sorted(folder.glob("sound.*"))
    if not found:
        raise VideoEarsError("Could not get the video's sound.")
    return found[0], str(info.get("title") or "")


class VideoEars:
    """Listen to web videos and video files with Whisper on this PC."""

    def __init__(
        self,
        *,
        hear: Hear,
        work: Path,
        home: Path,
        max_minutes: int = 120,
        fetch: Fetch = ytdlp_fetch,
        allow_private: bool = False,
        ready: Callable[[], bool] = lambda: True,
        record: Record | None = None,
    ) -> None:
        self._record = record
        self._hear = hear
        self._work = work
        self._home = home
        self._max_minutes = max_minutes
        self._fetch = fetch
        self._allow_private = allow_private
        self._ready = ready
        self._lock = asyncio.Lock()

    @property
    def home(self) -> Path:
        return self._home

    def local_file(self, target: str) -> Path | None:
        return local_media(target, self._home)

    def key_for(self, target: str) -> str:
        path = self.local_file(target)
        return file_key(path) if path is not None else link_key(target.strip())

    async def listen(self, target: str) -> Heard:
        """Hear a video file on this PC or a web video, one at a time."""
        if not self._ready():
            raise VideoEarsError(
                "Listening needs the speech recognition part: run the Windows "
                "installer again, or run: uv sync --extra studio_voice"
            )
        path = self.local_file(target)
        async with self._lock:
            if path is not None:
                pieces, length = await self._heard(path)
                return Heard(
                    key=file_key(path),
                    url=str(path),
                    title=path.stem.replace("_", " "),
                    segments=join_lines(pieces),
                    seconds=int(length),
                )
            return await self._listen_link(target.strip())

    async def _heard(self, path: Path) -> tuple[list[tuple[float, str]], float]:
        try:
            pieces, length = await asyncio.to_thread(
                self._hear, path, self._max_minutes
            )
        except VideoEarsError:
            raise
        except Exception as error:  # Whisper and its decoder raise many kinds
            raise VideoEarsError(f"Could not listen to it: {error}") from error
        if not any(text.strip() for _, text in pieces):
            raise VideoEarsError("No speech was heard in that video.")
        return pieces, length

    async def _listen_link(self, url: str) -> Heard:
        if urlparse(url).scheme not in {"http", "https"}:
            raise VideoEarsError("Give a video link (http or https) or a video file.")
        if not self._allow_private and is_private_host(url):
            raise VideoEarsError("Agents do not open links on this PC or home network.")
        self._work.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="listen-", dir=self._work))
        speed = 1.0
        try:
            try:
                sound, title = await asyncio.to_thread(
                    self._fetch, url, folder, self._max_minutes
                )
            except VideoTooLong:
                raise
            except VideoEarsError as error:
                if self._record is None:
                    raise
                logger.info("Studio: recording {} in the browser: {}", url, error)
                sound, title, speed = await self._record(url, folder, self._max_minutes)
            pieces, length = await self._heard(sound)
            if speed != 1:
                # Played faster to save time: put the times back on the video's clock.
                pieces = [(at * speed, text) for at, text in pieces]
                length *= speed
        finally:
            with contextlib.suppress(OSError):
                shutil.rmtree(folder)
        return Heard(
            key=link_key(url),
            url=url,
            title=title or urlparse(url).netloc,
            segments=join_lines(pieces),
            seconds=int(length),
        )
