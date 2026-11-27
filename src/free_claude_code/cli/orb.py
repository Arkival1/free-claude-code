"""``fcc-orb``: open the JARVIS Orb window, starting FCC in the background first."""

import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

from free_claude_code.application.orb.ears import LocalEars
from free_claude_code.application.orb.voice import JarvisVoice
from free_claude_code.cli.local_http import open_local_request
from free_claude_code.config.loader import get_settings
from free_claude_code.config.paths import config_dir_path
from free_claude_code.config.server_urls import local_proxy_root_url

_DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
START_TIMEOUT_SECONDS = 90.0


def orb_url(root: str) -> str:
    return f"{root.rstrip('/')}/orb"


def server_is_up(root: str, *, timeout: float = 1.5) -> bool:
    """True when an FCC server answers its local status endpoint."""
    try:
        with open_local_request(
            Request(f"{root.rstrip('/')}/admin/api/status"), timeout=timeout
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError, URLError, ValueError:
        return False
    return isinstance(payload, dict) and payload.get("status") in {
        "running",
        "stopping",
    }


def background_server_command() -> list[str]:
    """Prefer the tray app (so FCC keeps running); fall back to the plain server."""
    bin_dir = Path(sys.executable).parent
    for name in ("fcc-desktop", "fcc-server"):
        for candidate in (bin_dir / f"{name}.exe", bin_dir / name):
            if candidate.is_file():
                return [str(candidate)]
        found = shutil.which(name)
        if found:
            return [found]
    return [
        sys.executable,
        "-c",
        "from free_claude_code.cli.entrypoints import serve; serve()",
    ]


def start_background_server(popen: Callable[..., object] = subprocess.Popen) -> None:
    env = {**os.environ, "FCC_OPEN_BROWSER": "false"}
    extra: dict[str, object] = {}
    if os.name == "nt":
        extra["creationflags"] = _DETACHED
    else:
        extra["start_new_session"] = True
    popen(
        background_server_command(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        **extra,
    )


def app_window_browsers() -> list[Path]:
    """Chromium browsers that can show a page as a chrome-less app window."""
    roots = [
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    names = [
        Path("Microsoft/Edge/Application/msedge.exe"),
        Path("Google/Chrome/Application/chrome.exe"),
        Path("BraveSoftware/Brave-Browser/Application/brave.exe"),
    ]
    return [Path(root) / name for name in names for root in roots if root]


def open_orb_window(
    url: str,
    *,
    popen: Callable[..., object] = subprocess.Popen,
    browsers: Sequence[Path] | None = None,
) -> str:
    """Open the orb as its own small window; fall back to the default browser."""
    for browser in browsers if browsers is not None else app_window_browsers():
        if browser.is_file():
            popen([str(browser), f"--app={url}", "--window-size=520,640"])
            return str(browser)
    webbrowser.open(url)
    return "default browser"


def prepare(root: Path | None = None) -> bool:
    """Download JARVIS's offline voice and ears now, so the orb never needs the
    internet afterwards. Progress goes to <config>/orb_prepare.log."""
    base = root or config_dir_path()
    base.mkdir(parents=True, exist_ok=True)
    log = base / "orb_prepare.log"
    voice = JarvisVoice(base / "orb_voice")
    ears = LocalEars(base / "orb_ears")
    voice.start_download()
    ears.start_download()
    voice.wait()
    ears.wait()
    lines = [
        "Voice: " + ("ready" if voice.files_ready() else voice.error or "not ready"),
        "Ears: " + ("ready" if ears.ready() else ears.error or "not ready"),
    ]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return voice.files_ready() and ears.ready()


def launch(argv: Sequence[str] | None = None) -> None:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if "--prepare" in args:
        raise SystemExit(0 if prepare() else 1)
    root = local_proxy_root_url(get_settings())
    url = orb_url(root)
    if "--url" in args:
        print(url)
        return
    if not server_is_up(root):
        start_background_server()
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while not server_is_up(root):
            if time.monotonic() > deadline:
                print(f"FCC did not start in time. Open {url} later.", file=sys.stderr)
                raise SystemExit(1)
            time.sleep(0.5)
    open_orb_window(url)
