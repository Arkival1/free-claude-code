"""The desktop browser drives a real Chromium: read, click, scroll, play."""

import asyncio
import io
import math
import struct
import threading
import wave
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from free_claude_code.studio.desk import DeskBrowser, DeskError, playwright_opener

PAGES = {
    "/": (
        "<title>Bread search</title><h1>Results</h1>"
        '<p><a href="/starter">How to feed a starter</a></p>'
        '<p><a href="/watch">A sourdough video</a></p>'
        '<p><a href="/away" target="_blank">Opens a new tab</a></p>'
        "<button>Accept all</button><button>Buy now</button>"
        '<div style="height:3000px"></div>'
    ),
    "/starter": (
        "<title>Feeding a starter</title><main><h1>Feeding</h1>"
        "<p>Feed it flour and water the night before.</p></main>"
        '<a href="/">Back to results</a>'
    ),
    "/watch": (
        "<title>Bake sourdough</title><h1>Bake sourdough</h1>"
        '<video width="320" height="180" muted></video>'
    ),
}


PAGES["/tone"] = (
    '<title>A tone</title><video src="/tone.wav" width="320" height="40"></video>'
)


def tone(seconds: float = 3.0, rate: int = 16_000) -> bytes:
    """A short beep as a WAV file, for the video element to play."""
    frames = b"".join(
        struct.pack("<h", int(12_000 * math.sin(2 * math.pi * 440 * n / rate)))
        for n in range(int(seconds * rate))
    )
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return out.getvalue()


class Pages(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/tone.wav":
            data = tone()
            self.send_response(200)
            self.send_header("content-type", "audio/wav")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        body = PAGES.get(self.path)
        self.send_response(200 if body else 404)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write((body or "<title>Not found</title>").encode())

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def site() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Pages)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_agents_drive_a_real_browser(tmp_path, site):
    # The browser tests share a running event loop, so this one drives the
    # async browser on a thread of its own.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: asyncio.run(drive(tmp_path, site))).result(timeout=180)


async def drive(tmp_path: Path, site: str) -> None:
    desk = DeskBrowser(
        playwright_opener(tmp_path / "profile", browser="chromium", visible=False),
        allow_private=True,
    )
    try:
        shot = await desk.go(f"{site}/")
        assert shot.title == "Bread search"
        assert ("How to feed a starter", f"{site}/starter") in shot.links
        assert [label for _, label in await desk.buttons()] == ["Accept all"]
        await desk.press("accept all")
        await desk.scroll()

        starter = await desk.follow(1, by="Researcher")
        assert "flour and water the night before" in starter.text
        back = await desk.back()
        assert back.title == "Bread search"

        watch = await desk.go(f"{site}/watch")
        assert watch.video is not None and watch.video["playing"] is False
        await desk.video("play")
        with pytest.raises(DeskError, match="may not press"):
            await desk.press("Buy now")
    finally:
        await desk.close()
    assert not desk.open
    assert (tmp_path / "profile").is_dir(), "its own profile, not the user's"


def test_a_video_is_recorded_as_it_plays_when_it_cannot_be_downloaded(tmp_path, site):
    with ThreadPoolExecutor(max_workers=1) as pool:
        path, title, speed = pool.submit(
            lambda: asyncio.run(record(tmp_path, site))
        ).result(timeout=180)
    assert title == "A tone" and speed == 2.0
    data = path.read_bytes()
    assert data[:4] == b"\x1a\x45\xdf\xa3", "a WebM recording of the sound"
    assert len(data) > 2_000


async def record(tmp_path: Path, site: str) -> tuple[Path, str, float]:
    desk = DeskBrowser(
        playwright_opener(tmp_path / "profile", browser="chromium", visible=False),
        allow_private=True,
    )
    try:
        return await desk.record_sound(
            f"{site}/tone", tmp_path / "sound", max_minutes=5
        )
    finally:
        await desk.close()
