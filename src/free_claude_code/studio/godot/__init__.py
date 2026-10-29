"""Godot 4 for FCC's game makers: the engine (downloaded once, kept in the
Repo vault), Godot's own demo projects to learn from, and starters.

- Godot 4.7.2 (MIT): `engine.GodotEngine` downloads the editor for this PC
  from Godot's GitHub release, checks it against Godot's SHA-512 list,
  keeps it in the Repo vault, and runs it headless to check projects, record
  frames and export games.
- 133 official demo projects (MIT, `godotengine/godot-demo-projects`): their
  GDScript, scenes, resources, shaders and READMEs in `demos.json.gz`; their
  art, sound, models and skies (and Godot's import notes for them) in
  `art/demo-art-NN.zip`, listed with SHA-256 checksums in `art/art.json.gz`,
  so `demo_project` copies a whole demo that opens and runs.
- Starters in `starters/`: platformer-2d and rpg-topdown (Kenney art, CC0,
  from FCC's game library) and third-person-3d (shapes only).
See `vendor/godot/`.
"""

import gzip
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .. import game_library

HERE = Path(__file__).resolve().parent
DEMOS = HERE / "demos.json.gz"
STARTERS = HERE / "starters"
ART = HERE / "art"
ART_MANIFEST = ART / "art.json.gz"
ART_LICENCE = ART / "LICENSE-demos.txt"
DEMO_LICENCE_NAME = "LICENSE-godot-demos.txt"
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


@dataclass(frozen=True, slots=True)
class ArtFile:
    path: str
    sha256: str
    size: int
    at: tuple[tuple[str, str], ...]
    """(part zip, member) for each chunk, in order."""


@cache
def _art() -> dict[str, tuple[ArtFile, ...]]:
    if not ART_MANIFEST.is_file():
        return {}
    payload = json.loads(gzip.decompress(ART_MANIFEST.read_bytes()))
    return {
        str(demo_id): tuple(
            ArtFile(
                path=str(row["path"]),
                sha256=str(row["sha256"]),
                size=int(row["size"]),
                at=tuple((str(at["zip"]), str(at["member"])) for at in row["at"]),
            )
            for row in rows
        )
        for demo_id, rows in payload.items()
    }


def demo_art(demo_id: object) -> tuple[ArtFile, ...]:
    """The art, sound and models a demo uses (names, sizes, checksums)."""
    return _art().get(demo(demo_id).id, ())


def demo_project(demo_id: object) -> dict[str, bytes]:
    """A whole demo, code and art, ready to copy into a project. Every art
    file is checked against its SHA-256 before it is handed out."""
    item = demo(demo_id)
    files = {path: text.encode("utf-8") for path, text in item.files.items()}
    files[DEMO_LICENCE_NAME] = ART_LICENCE.read_bytes()
    art = _art().get(item.id, ())
    by_part: dict[str, set[str]] = {}
    for entry in art:
        for part, member in entry.at:
            by_part.setdefault(part, set()).add(member)
    chunks: dict[str, bytes] = {}
    for part, members in by_part.items():
        path = ART / part
        if not path.is_file():
            raise GodotLibraryError(
                f"The Godot demo art file {part} is missing; reinstall FCC's parts."
            )
        with zipfile.ZipFile(path) as bundle:
            for member in members:
                chunks[member] = bundle.read(member)
    for entry in art:
        data = b"".join(chunks[member] for _, member in entry.at)
        if hashlib.sha256(data).hexdigest() != entry.sha256:
            raise GodotLibraryError(
                f"{item.id}/{entry.path} doesn't match its checksum; reinstall "
                "FCC's parts."
            )
        files[entry.path] = data
    return files


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


_NAME_LINE = re.compile(rb'^config/name=".*"$', re.MULTILINE)


@cache
def _starter_prints() -> frozenset[tuple[str, bytes]]:
    prints: set[tuple[str, bytes]] = set()
    for name in STARTER_ART:
        try:
            files = starter_files(name)
        except game_library.GameLibraryError:
            continue  # its Kenney pack isn't on this PC: nothing to match
        prints.update((path, _NAME_LINE.sub(b"", data)) for path, data in files.items())
    return frozenset(prints)


def untouched_starter(path: str, data: bytes) -> bool:
    """True when a project file is still exactly as a starter wrote it (its
    game name aside), so copying a demo over it loses no work."""
    return (path, _NAME_LINE.sub(b"", data)) in _starter_prints()


godot_demo = demo
godot_demo_art = demo_art
godot_demo_project = demo_project
godot_starter_files = starter_files
