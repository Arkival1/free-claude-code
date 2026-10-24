"""The desktop browser: a real browser window on this PC that agents drive.

Agents research in it and play videos in it while the user watches. It is
the user's own Edge or Chrome, started with a separate Studio profile, so
it never sees the user's passwords, cookies or open tabs. Agents only read
pages, follow links, scroll, go back, play or pause a video, and press a
few harmless buttons (cookie banners, "show more", "next"); they never
type into pages, sign in, buy anything, or download files.
"""

import asyncio
import base64
import contextlib
import importlib.util
import ipaddress
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus, urlparse

from loguru import logger

PART_CHARS = 5_000
"""How much page text one read shows, so a small local model keeps up."""
SHOWN_LINKS = 30
RECORD_RATE = 2.0
"""Videos recorded in the window play at double speed: half the wait, and
speech recognition still follows."""
RECORD_POLL = 2.0
RECORD_GRACE = 60.0
MAX_LINKS = 400
BROWSERS = {
    "auto": ("msedge", "chrome", ""),
    "edge": ("msedge",),
    "chrome": ("chrome",),
    "chromium": ("",),
}
SEARCHES = {
    "web": "https://duckduckgo.com/?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
}
SAFE_BUTTONS = (
    "accept",
    "agree",
    "allow",
    "reject",
    "decline",
    "consent",
    "got it",
    "ok",
    "no thanks",
    "not now",
    "close",
    "dismiss",
    "skip",
    "play",
    "pause",
    "more",
    "show more",
    "read more",
    "load more",
    "see more",
    "expand",
    "next",
    "continue",
    "transcript",
)
"""Words a button may say for an agent to press it."""
UNSAFE_BUTTONS = re.compile(
    r"\b(buy|pay|order|checkout|cart|purchase|donat|subscri|sign|log ?in|"
    r"log ?out|register|join|delete|remove|send|post|submit|upload|download|"
    r"install|share|report|block|unfollow|follow|like|dislike|comment|reply|"
    r"password|account|card)",
    re.IGNORECASE,
)
_SNAPSHOT_JS = """
() => {
  const seen = new Set();
  const links = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href;
    if (!/^https?:/i.test(href) || seen.has(href)) continue;
    const box = a.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) continue;
    const text = (a.innerText || a.getAttribute('aria-label') || a.title || '')
      .replace(/\\s+/g, ' ').trim();
    if (!text) continue;
    seen.add(href);
    links.push([text.slice(0, 120), href]);
    if (links.length >= MAX_LINKS) break;
  }
  const video = document.querySelector('video');
  return {
    title: document.title || '',
    url: location.href,
    text: document.body ? document.body.innerText : '',
    links,
    video: video ? {
      playing: !video.paused && !video.ended,
      at: Math.floor(video.currentTime || 0),
      length: Math.floor(video.duration || 0),
    } : null,
  };
}
""".replace("MAX_LINKS", str(MAX_LINKS))
_VIDEO_JS = """
(action) => {
  const video = document.querySelector('video');
  if (!video) return false;
  if (action === 'pause') { video.pause(); return true; }
  video.muted = false;
  const started = video.play();
  if (started && started.catch) started.catch(() => {});
  return true;
}
"""
_RECORD_START_JS = """
async (rate) => {
  const video = document.querySelector('video');
  if (!video) return { error: 'This page has no video.' };
  const capture = video.captureStream || video.mozCaptureStream;
  if (!capture) return { error: 'This browser cannot listen to the video.' };
  if (video.currentTime > 1 && !video.ended) video.currentTime = 0;
  video.playbackRate = rate;
  video.muted = false;
  try {
    await video.play();
  } catch (error) {
    return { error: 'The video would not play: ' + error.message };
  }
  const stream = capture.call(video);
  for (let i = 0; i < 50 && !stream.getAudioTracks().length; i++) {
    await new Promise((done) => setTimeout(done, 100));
  }
  const tracks = stream.getAudioTracks();
  if (!tracks.length) return { error: 'The video has no sound.' };
  const recorder = new MediaRecorder(new MediaStream(tracks));
  window.__fccChunks = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size) window.__fccChunks.push(event.data);
  };
  recorder.start(4000);
  window.__fccRecorder = recorder;
  const length = Number.isFinite(video.duration) ? video.duration : 0;
  return { length, title: document.title || '' };
}
"""
_RECORD_STATE_JS = """
() => {
  const video = document.querySelector('video');
  if (!video || !window.__fccRecorder) return null;
  return { at: video.currentTime || 0, ended: video.ended, paused: video.paused };
}
"""
_RECORD_FINISH_JS = """
async () => {
  const recorder = window.__fccRecorder;
  if (!recorder) return '';
  if (recorder.state !== 'inactive') {
    await new Promise((done) => {
      recorder.onstop = done;
      recorder.stop();
    });
  }
  const video = document.querySelector('video');
  if (video) video.playbackRate = 1;
  const blob = new Blob(window.__fccChunks || [], { type: 'audio/webm' });
  window.__fccChunks = [];
  window.__fccRecorder = null;
  if (!blob.size) return '';
  const data = await new Promise((done) => {
    const reader = new FileReader();
    reader.onload = () => done(String(reader.result));
    reader.readAsDataURL(blob);
  });
  return data.split(',')[1] || '';
}
"""
_BUTTONS_JS = """
() => Array.from(document.querySelectorAll(
  'button, [role=button], input[type=button]'
)).map((el, index) => {
  const box = el.getBoundingClientRect();
  const text = (el.innerText || el.value || el.getAttribute('aria-label') || '')
    .replace(/\\s+/g, ' ').trim();
  const visible = box.width > 0 && box.height > 0 && !el.disabled;
  return [index, text.slice(0, 80), visible];
}).filter(([, text, visible]) => text && visible)
"""
_PRESS_JS = """
(index) => {
  const el = Array.from(document.querySelectorAll(
    'button, [role=button], input[type=button]'
  ))[index];
  if (!el) return false;
  el.click();
  return true;
}
"""


class DeskError(RuntimeError):
    """Raised when the desktop browser cannot do what an agent asked."""


def desk_package_ready() -> bool:
    """Whether Playwright, which drives the browser, is installed."""
    return importlib.util.find_spec("playwright") is not None


INSTALL_HINT = (
    "The desktop browser part is not installed. Run the Windows installer "
    "again (it adds it), or run: uv sync --extra studio_desk"
)


@dataclass(frozen=True, slots=True)
class PageShot:
    """What the browser shows: the page's address, title, text and links."""

    url: str
    title: str
    text: str
    links: tuple[tuple[str, str], ...] = ()
    video: dict[str, Any] | None = None


class DeskPage(Protocol):
    """The one browser tab agents drive (a real one, or a stand-in in tests)."""

    async def goto(self, url: str) -> None: ...

    async def back(self) -> bool: ...

    async def snapshot(self) -> PageShot: ...

    async def scroll(self, down: bool) -> None: ...

    async def video(self, action: str) -> bool: ...

    async def buttons(self) -> list[tuple[int, str]]: ...

    async def press(self, index: int) -> bool: ...

    async def start_recording(self, rate: float) -> dict[str, Any]: ...

    async def recording_state(self) -> dict[str, Any] | None: ...

    async def finish_recording(self) -> bytes: ...

    async def close(self) -> None: ...


Opener = Callable[[], Awaitable[DeskPage]]


def is_private_host(url: str) -> bool:
    """A link to this PC or the home network, which agents may not open."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return True
    if host == "localhost" or host.endswith((".localhost", ".local", ".lan")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_global


def safe_button(text: str) -> bool:
    """A button an agent may press: harmless words, nothing that buys, signs
    in, posts or deletes."""
    words = text.casefold().strip()
    if not words or len(words) > 60 or UNSAFE_BUTTONS.search(words):
        return False
    return any(
        words == safe or words.startswith(f"{safe} ") or words.endswith(f" {safe}")
        for safe in SAFE_BUTTONS
    )


def clean_text(text: str) -> str:
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    kept: list[str] = []
    for line in lines:
        if line or (kept and kept[-1]):
            kept.append(line)
    return "\n".join(kept).strip()


@dataclass(slots=True)
class DeskState:
    """Where the agents are in the browser, so link numbers and parts mean
    the same thing from one call to the next."""

    shot: PageShot | None = None
    part: int = 1
    used_by: str = ""
    history: list[str] = field(default_factory=list)


class DeskBrowser:
    """Drive one visible browser window on this PC for the agents."""

    def __init__(
        self,
        opener: Opener,
        *,
        allow_private: bool = False,
    ) -> None:
        self._opener = opener
        self._allow_private = allow_private
        self._page: DeskPage | None = None
        self._shown_file = ""
        self._lock = asyncio.Lock()
        self.state = DeskState()

    @property
    def open(self) -> bool:
        return self._page is not None

    async def _tab(self) -> DeskPage:
        if self._page is None:
            self._page = await self._opener()
        return self._page

    def _check(self, url: str) -> str:
        url = url.strip()
        if not url:
            raise DeskError("Give the link to open.")
        if "://" not in url:
            url = f"https://{url}"
        if urlparse(url).scheme not in {"http", "https"}:
            raise DeskError("The desktop browser only opens http and https links.")
        if not self._allow_private and is_private_host(url):
            raise DeskError(
                "The desktop browser does not open pages on this PC or the "
                "home network."
            )
        return url

    async def go(self, url: str, *, by: str = "") -> PageShot:
        """Open a page in the window."""
        url = self._check(url)
        async with self._lock:
            page = await self._tab()
            await page.goto(url)
            return await self._look(page, by=by)

    async def show_file(self, path: Path, *, by: str = "") -> PageShot:
        """Play a video file from this PC in the window (the browser's own
        player; only checked video files are opened this way)."""
        async with self._lock:
            page = await self._tab()
            self._shown_file = path.as_uri()
            await page.goto(self._shown_file)
            return await self._look(page, by=by)

    async def search(self, query: str, *, where: str = "web", by: str = "") -> PageShot:
        query = query.strip()
        if not query:
            raise DeskError("Say what to search for.")
        pattern = SEARCHES.get(where, SEARCHES["web"])
        return await self.go(pattern.format(quote_plus(query)), by=by)

    async def look(self, *, part: int = 0, by: str = "") -> PageShot:
        """Read the page again (it may have changed), at a part of its text."""
        async with self._lock:
            page = self._require()
            shot = await self._look(page, by=by)
            if part > 0:
                self.state.part = min(part, parts_of(shot.text))
            return shot

    async def follow(self, number: int, *, by: str = "") -> PageShot:
        """Open link number N from the last look at the page."""
        shot = self.state.shot
        if shot is None:
            raise DeskError("Open a page first.")
        if not 1 <= number <= len(shot.links):
            raise DeskError(
                f"There is no link {number}: the page has {len(shot.links)}."
            )
        return await self.go(shot.links[number - 1][1], by=by)

    async def scroll(self, *, down: bool = True, by: str = "") -> PageShot:
        """Scroll the window and move on to the next (or last) part of the text."""
        async with self._lock:
            page = self._require()
            await page.scroll(down)
            shot = await self._look(page, by=by, keep_part=True)
            last = parts_of(shot.text)
            self.state.part = (
                min(last, self.state.part + 1) if down else max(1, self.state.part - 1)
            )
            return shot

    async def back(self, *, by: str = "") -> PageShot:
        async with self._lock:
            page = self._require()
            if not await page.back():
                raise DeskError("There is no page to go back to.")
            return await self._look(page, by=by)

    async def video(self, action: str, *, by: str = "") -> PageShot:
        """Play or pause the video on the page."""
        async with self._lock:
            page = self._require()
            if not await page.video("pause" if action == "pause" else "play"):
                raise DeskError("This page has no video to play.")
            await asyncio.sleep(0.5)
            return await self._look(page, by=by, keep_part=True)

    async def buttons(self) -> list[tuple[int, str]]:
        async with self._lock:
            page = self._require()
            return [
                (index, text)
                for index, text in await page.buttons()
                if safe_button(text)
            ]

    async def press(self, text: str, *, by: str = "") -> PageShot:
        """Press a harmless button by what it says."""
        wanted = text.casefold().strip()
        if not safe_button(wanted):
            raise DeskError(
                f"Agents may not press '{text}'. They only press harmless "
                "buttons, like accept, close, show more, next or play."
            )
        async with self._lock:
            page = self._require()
            found = [
                index
                for index, label in await page.buttons()
                if label.casefold().strip() == wanted
            ] or [
                index
                for index, label in await page.buttons()
                if wanted in label.casefold() and safe_button(label)
            ]
            if not found or not await page.press(found[0]):
                raise DeskError(f"No '{text}' button on this page.")
            await asyncio.sleep(0.8)
            return await self._look(page, by=by, keep_part=True)

    async def record_sound(
        self,
        url: str,
        folder: Path,
        *,
        max_minutes: int,
        rate: float = RECORD_RATE,
        by: str = "",
    ) -> tuple[Path, str, float]:
        """Play a video in the window and record its sound as it plays, for
        when the sound cannot be downloaded: the recording, the title, and
        the speed it played at. Takes the video's length divided by that
        speed."""
        url = self._check(url)
        async with self._lock:
            page = await self._tab()
            current = self.state.shot.url if self.state.shot else ""
            if current != url:
                await page.goto(url)
                await self._look(page, by=by)
            started = await page.start_recording(rate)
            if started.get("error"):
                raise DeskError(str(started["error"]))
            length = float(started.get("length") or 0)
            cap = max_minutes * 60
            if length > cap:
                await page.finish_recording()
                raise DeskError(
                    f"The video is {int(length) // 60} minutes long; agents listen "
                    f"to videos up to {max_minutes} minutes (Settings)."
                )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + (length or cap) / rate + RECORD_GRACE
            while loop.time() < deadline:
                await asyncio.sleep(RECORD_POLL)
                state = await page.recording_state()
                if state is None or state.get("ended"):
                    break
                if length and float(state.get("at") or 0) >= length - 0.5:
                    break
                if state.get("paused"):
                    await page.video("play")
            sound = await page.finish_recording()
            if not sound:
                raise DeskError("Nothing was heard while the video played.")
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "sound.webm"
            path.write_bytes(sound)
            self.state.used_by = by
            return path, str(started.get("title") or ""), rate

    async def close(self) -> None:
        async with self._lock:
            page, self._page = self._page, None
            self.state = DeskState()
            if page is not None:
                with contextlib.suppress(Exception):
                    await page.close()

    def _allowed(self, url: str) -> bool:
        """Where the window may stay: web pages (not this PC or the home
        network), a blank tab, and the one video file an agent showed."""
        scheme = urlparse(url).scheme
        if scheme == "about" or (self._shown_file and url == self._shown_file):
            return True
        if scheme not in {"http", "https"}:
            return False
        return self._allow_private or not is_private_host(url)

    def _require(self) -> DeskPage:
        if self._page is None:
            raise DeskError("The desktop browser is closed: open a page first.")
        return self._page

    async def _look(
        self, page: DeskPage, *, by: str, keep_part: bool = False
    ) -> PageShot:
        shot = await page.snapshot()
        if not self._allowed(shot.url):
            await page.goto("about:blank")
            raise DeskError(
                "That page led somewhere agents may not go (this PC or the "
                "home network): closed it."
            )
        shot = PageShot(
            url=shot.url,
            title=shot.title,
            text=clean_text(shot.text),
            links=shot.links,
            video=shot.video,
        )
        moved = self.state.shot is None or self.state.shot.url != shot.url
        if moved:
            self.state.history = [*self.state.history[-19:], shot.url]
        if moved or not keep_part:
            self.state.part = 1
        self.state.shot = shot
        self.state.used_by = by
        return shot


def parts_of(text: str) -> int:
    return max(1, -(-len(text) // PART_CHARS))


def render(shot: PageShot, *, part: int = 1, query: str = "") -> str:
    """The page as an agent reads it: title, text part, and numbered links."""
    total = parts_of(shot.text)
    part = min(max(1, part), total)
    body = shot.text[(part - 1) * PART_CHARS : part * PART_CHARS]
    lines = [
        f"Desktop browser: {shot.title or '(no title)'}",
        f"Address: {shot.url}",
    ]
    if shot.video:
        state = "playing" if shot.video.get("playing") else "paused"
        lines.append(
            f"Video on this page: {state} at {shot.video.get('at', 0)}s of "
            f"{shot.video.get('length', 0)}s. Use watch to study it."
        )
    lines += ["", f"Page text (part {part} of {total}):", body or "(no text)"]
    if part < total:
        lines.append(f"[More: read with part {part + 1}, or scroll down.]")
    links = list(enumerate(shot.links, start=1))
    if query:
        terms = [term for term in query.casefold().split() if term]
        links = [
            item
            for item in links
            if all(term in f"{item[1][0]} {item[1][1]}".casefold() for term in terms)
        ]
    if links:
        lines += ["", "Links (click one by its number):"]
        lines += [f"{n}. {text} — {url}" for n, (text, url) in links[:SHOWN_LINKS]]
        if len(links) > SHOWN_LINKS:
            lines.append(
                f"…and {len(links) - SHOWN_LINKS} more: use links with a query."
            )
    elif query:
        lines += ["", f"No links match '{query}'."]
    return "\n".join(lines)


class PlaywrightPage:
    """The real thing: a tab in a visible Edge or Chrome window."""

    def __init__(self, playwright: Any, context: Any, page: Any) -> None:
        self._playwright = playwright
        self._context = context
        self._page = page

    async def goto(self, url: str) -> None:
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as error:  # Playwright raises its own error kinds
            raise DeskError(f"Could not open {url}: {_short(error)}") from error
        with contextlib.suppress(Exception):
            await self._page.wait_for_load_state("networkidle", timeout=4_000)

    async def back(self) -> bool:
        try:
            response = await self._page.go_back(
                wait_until="domcontentloaded", timeout=20_000
            )
        except Exception as error:
            raise DeskError(f"Could not go back: {_short(error)}") from error
        return response is not None

    async def snapshot(self) -> PageShot:
        try:
            data = await self._page.evaluate(_SNAPSHOT_JS)
        except Exception as error:
            raise DeskError(f"Could not read the page: {_short(error)}") from error
        links = tuple(
            (str(text), str(url))
            for text, url in data.get("links", [])
            if isinstance(text, str) and isinstance(url, str)
        )
        video = data.get("video")
        return PageShot(
            url=str(data.get("url", "")),
            title=str(data.get("title", "")),
            text=str(data.get("text", "")),
            links=links,
            video=video if isinstance(video, dict) else None,
        )

    async def scroll(self, down: bool) -> None:
        with contextlib.suppress(Exception):
            await self._page.mouse.wheel(0, 900 if down else -900)
            await asyncio.sleep(0.4)

    async def video(self, action: str) -> bool:
        try:
            return bool(await self._page.evaluate(_VIDEO_JS, action))
        except Exception:
            return False

    async def buttons(self) -> list[tuple[int, str]]:
        try:
            found = await self._page.evaluate(_BUTTONS_JS)
        except Exception:
            return []
        return [(int(index), str(text)) for index, text, _ in found]

    async def press(self, index: int) -> bool:
        try:
            return bool(await self._page.evaluate(_PRESS_JS, index))
        except Exception:
            return False

    async def start_recording(self, rate: float) -> dict[str, Any]:
        try:
            started = await self._page.evaluate(_RECORD_START_JS, rate)
        except Exception as error:
            raise DeskError(
                f"Could not listen to the video: {_short(error)}"
            ) from error
        return started if isinstance(started, dict) else {"error": "No video."}

    async def recording_state(self) -> dict[str, Any] | None:
        try:
            state = await self._page.evaluate(_RECORD_STATE_JS)
        except Exception:
            return None
        return state if isinstance(state, dict) else None

    async def finish_recording(self) -> bytes:
        try:
            data = await self._page.evaluate(_RECORD_FINISH_JS)
        except Exception:
            return b""
        try:
            return base64.b64decode(str(data or ""))
        except ValueError:
            return b""

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._context.close()
        with contextlib.suppress(Exception):
            await self._playwright.stop()


def _short(error: BaseException) -> str:
    return (
        str(error).strip().splitlines()[0][:200]
        if str(error).strip()
        else type(error).__name__
    )


def playwright_opener(
    profile: Path,
    *,
    browser: str = "auto",
    visible: bool = True,
) -> Opener:
    """Start the user's Edge or Chrome with Studio's own profile folder."""

    async def open_tab() -> DeskPage:
        if not desk_package_ready():
            raise DeskError(INSTALL_HINT)
        from playwright.async_api import async_playwright

        profile.mkdir(parents=True, exist_ok=True)
        runner = await async_playwright().start()
        errors: list[str] = []
        for channel in _channels(browser):
            try:
                context = await runner.chromium.launch_persistent_context(
                    str(profile),
                    channel=channel or None,
                    headless=not visible,
                    accept_downloads=False,
                    no_viewport=True,
                    args=["--autoplay-policy=no-user-gesture-required"],
                )
            except Exception as error:  # a missing browser raises Error
                errors.append(f"{channel or 'chromium'}: {_short(error)}")
                continue
            logger.info("Studio: desktop browser opened ({})", channel or "chromium")
            context.on("page", _close_extra_tabs(context))
            page = context.pages[0] if context.pages else await context.new_page()
            return PlaywrightPage(runner, context, page)
        await runner.stop()
        raise DeskError(
            "Could not start Edge or Chrome for the desktop browser. "
            + "; ".join(errors)
        )

    return open_tab


def _channels(browser: str) -> Sequence[str]:
    return BROWSERS.get(browser, BROWSERS["auto"])


def _close_extra_tabs(context: Any) -> Callable[[Any], None]:
    """Pop-ups and new tabs a page opens are closed: agents use one tab."""

    def closer(page: Any) -> None:
        if len(context.pages) > 1:
            asyncio.ensure_future(page.close())

    return closer
