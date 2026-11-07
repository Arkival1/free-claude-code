"""The app kit: Tabler 1.7.1 and Tabler Icons 3.49.0 (both MIT).

Tabler is a design system for app screens (dashboards, settings, forms,
tables, menus, leaderboards, pricing, sign-in) built on Bootstrap 5, plain
CSS and JS, so nothing needs building. `tabler.zip` (see `vendor/tabler/`)
holds the kit, all 5,184 icons as data, and the app-kit starter: home,
leaderboard and settings screens for an app or game.
"""

import json
import re
import zipfile
from functools import cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "tabler.zip"
KIT_PREFIXES = ("vendor/tabler/", "vendor/tabler-icons/")
STARTER_NAME = "App Name"
MAX_ICONS = 40
SVG_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
)


class UiKitError(ValueError):
    """An icon or action the kit doesn't have; the message says why."""


@cache
def _bundle() -> dict[str, bytes]:
    with zipfile.ZipFile(DATA) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()}


@cache
def icons() -> dict[str, tuple[str, tuple[str, ...], str]]:
    """Every icon: name -> (category, tags, the SVG's inner shapes)."""
    rows = json.loads(_bundle()["icons.json"])
    return {name: (row[0], tuple(row[1]), row[2]) for name, row in rows.items()}


def kit_files() -> dict[str, bytes]:
    """Tabler's CSS, JS and both licences, at their project paths."""
    return {
        path: data for path, data in _bundle().items() if path.startswith(KIT_PREFIXES)
    }


def starter_files(title: str = "") -> dict[str, bytes]:
    """The app-kit screens, named for the app, plus the kit they load."""
    name = title.strip() or STARTER_NAME
    files = kit_files()
    for path, data in _bundle().items():
        if not path.startswith("app-kit/"):
            continue
        target = path.removeprefix("app-kit/")
        if target.endswith(".html"):
            data = data.decode("utf-8").replace(STARTER_NAME, _escape(name)).encode()
        files[target] = data
    return files


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def find_icons(query: str, count: int = 20) -> list[tuple[str, str]]:
    """Icons whose name, category or tags match every word; names count most."""
    words = _words(query)
    if not words:
        raise UiKitError("Say what the icon shows, e.g. 'coin', 'sword', 'settings'.")
    scored: list[tuple[int, int, str, str]] = []
    for name, (category, tags, _) in icons().items():
        name_words = set(_words(name))
        other = set(_words(f"{category} {' '.join(tags)}"))
        score = 0
        for word in words:
            if word in name_words:
                score += 3
            elif any(part.startswith(word) for part in name_words):
                score += 2
            elif any(part.startswith(word) for part in other):
                score += 1
            else:
                score = 0
                break
        if score:
            if "-".join(words) == name:
                score += 5  # the icon called exactly that comes first
            scored.append((-score, len(name), name, category))
    scored.sort()
    return [
        (name, category)
        for _, _, name, category in scored[: max(1, min(MAX_ICONS, count))]
    ]


def icon_file(name: str) -> bytes:
    """One icon as a standalone SVG file."""
    found = icons().get(name.strip())
    if found is None:
        raise UiKitError(f"No icon called {name!r}. Use action icons to find one.")
    return f"{SVG_HEAD}{found[2]}</svg>\n".encode()
