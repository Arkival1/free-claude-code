"""Godot 4 for FCC's game makers: the engine (downloaded once, kept in the
Repo vault), Godot's own demo projects to learn from, and starters.

- Godot 4.7.2 (MIT): `engine.GodotEngine` downloads the editor for this PC
  from Godot's GitHub release, checks it against Godot's SHA-512 list,
  keeps it in the Repo vault, and runs it headless to check projects, record
  frames and export games.
- 133 official demo projects (MIT, `godotengine/godot-demo-projects`): their
  GDScript, scenes, resources, shaders and READMEs in `demos.json.gz`; art
  and sound are listed by name only.
- Starters in `starters/`: platformer-2d and rpg-topdown (Kenney art, CC0,
  from FCC's game library) and third-person-3d (shapes only).
See `vendor/godot/`.
"""

import gzip
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .. import game_library

HERE = Path(__file__).resolve().parent
DEMOS = HERE / "demos.json.gz"
STARTERS = HERE / "starters"
MAX_RESULTS = 15
MAX_SHOW = 12_000
"""Most characters of demo code shown in one go."""
STARTER_ART: dict[str, dict[str, tuple[str, str]]] = {
    "platformer-2d": {
        "assets/tiles.png": ("pixel-platformer", "Tilemap/tilemap_packed.png"),
        "assets/characters.png": (
            "pixel-platformer",
            "Tilemap/tilemap-characters_packed.png",
        ),
        "assets/LICENSE-kenney.txt": ("pixel-platformer", "License.txt"),
    },
    "rpg-topdown": {
        "assets/tiles.png": ("tiny-town", "Tilemap/tilemap_packed.png"),
        "assets/characters.png": ("tiny-dungeon", "Tilemap/tilemap_packed.png"),
        "assets/LICENSE-kenney.txt": ("tiny-town", "License.txt"),
    },
    "third-person-3d": {},
}
"""Each starter's art: project path -> (Kenney pack, file in the pack)."""
STARTER_NOTES = {
    "platformer-2d": "A 2D platformer: run, variable jump, coyote time, coins, "
    "spikes, an enemy you can stomp, a finish flag; the level is a text map.",
    "rpg-topdown": "A top-down RPG village: walk, talk to people (E), a fetch "
    "quest with a key and a chest; the map is a text map.",
    "third-person-3d": "A 3D third-person game: mouse-look camera on a spring "
    "arm, walk, run, jump, orbs to collect, sun, sky and shadows.",
}
STARTER_TITLE = "Game Name"


class GodotLibraryError(ValueError):
    """A demo or starter the library doesn't have; the message says why."""


@dataclass(frozen=True, slots=True)
class Demo:
    id: str
    title: str
    about: str
    area: str
    files: dict[str, str]
    assets: tuple[str, ...]


@cache
def _demos() -> tuple[str, tuple[Demo, ...]]:
    payload = json.loads(gzip.decompress(DEMOS.read_bytes()))
    demos = tuple(
        Demo(
            id=str(row["id"]),
            title=str(row["title"]),
            about=str(row["about"]),
            area=str(row["area"]),
            files={str(path): str(text) for path, text in row["files"].items()},
            assets=tuple(str(name) for name in row["assets"]),
        )
        for row in payload["demos"]
    )
    return str(payload["commit"]), demos


def demos() -> tuple[Demo, ...]:
    return _demos()[1]


def demos_commit() -> str:
    return _demos()[0]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def find_demos(query: str, count: int = 8) -> list[Demo]:
    """Demos whose title, area or code match the words; titles count most."""
    words = _words(query)
    if not words:
        raise GodotLibraryError(
            "Say what the game needs, e.g. 'platformer jump', 'tilemap', 'ragdoll'."
        )
    scored: list[tuple[int, str, Demo]] = []
    for item in demos():
        head = set(_words(f"{item.id} {item.title} {item.area}"))
        about = item.about.casefold()
        code = " ".join(item.files).casefold()
        score = 0
        for word in words:
            if word in head or any(part.startswith(word) for part in head):
                score += 4
            elif word in about:
                score += 2
            elif word in code or any(
                word in text.casefold() for text in item.files.values()
            ):
                score += 1
        if score >= len(words):
            scored.append((-score, item.id, item))
    scored.sort(key=lambda row: row[:2])
    return [row[2] for row in scored[: max(1, min(MAX_RESULTS, count))]]


def demo(demo_id: object) -> Demo:
    wanted = str(demo_id or "").strip().strip("/")
    for item in demos():
        if item.id == wanted:
            return item
    raise GodotLibraryError(
        f"No demo called {demo_id!r}. Use an id from action demos, e.g. '2d/platformer'."
    )


def starter_names() -> tuple[str, ...]:
    return tuple(STARTER_ART)


def starter_files(name: str, title: str = "") -> dict[str, bytes]:
    """A starter's files and its Kenney art, ready to copy into a project."""
    if name not in STARTER_ART:
        raise GodotLibraryError(
            f"No starter called {name!r}. Starters: {', '.join(STARTER_ART)}."
        )
    folder = STARTERS / name
    files: dict[str, bytes] = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            if path.name == "project.godot" and title.strip():
                safe = re.sub(r'["\\\n\r]', "", title.strip())[:60]
                data = data.replace(f'"{STARTER_TITLE}"'.encode(), f'"{safe}"'.encode())
            files[path.relative_to(folder).as_posix()] = data
    by_pack: dict[str, list[tuple[str, str]]] = {}
    for target, (pack, source) in STARTER_ART[name].items():
        by_pack.setdefault(pack, []).append((target, source))
    for pack, wanted in by_pack.items():
        found = game_library.read_files(
            game_library.pack(pack), [source for _, source in wanted], None
        )
        for target, source in wanted:
            files[target] = found[source]
    return files


godot_demo = demo
godot_starter_files = starter_files
