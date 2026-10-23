"""The game library: Phaser, its example code, and Kenney's art and sound.

- Phaser 3.90.0 (MIT) in `phaser/`, copied into game projects.
- 2,298 Phaser examples (MIT code; Phaser's example art is not free to
  share, so it is left out) in `phaser-examples.json.gz`.
- Kenney's 217 asset packs (CC0, public domain): every pack is listed in
  `kenney-catalogue.json.gz` with its files and checksum. The core packs ship
  inside FCC (`kenney-core.zip`, sounds as mp3); any other pack is
  downloaded once from kenney.nl, checked against its recorded SHA-256, and
  kept in the PC's game vault for good.
See `vendor/kenney/` and `vendor/phaser/`.
"""

import gzip
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE / "kenney-core.zip"
CATALOGUE = HERE / "kenney-catalogue.json.gz"
EXAMPLES = HERE / "phaser-examples.json.gz"
PHASER = HERE / "phaser" / "phaser.min.js"
KINDS = ("sprite", "sound", "font", "model", "sheet")
MAX_RESULTS = 15
MAX_PACK_BYTES = 80_000_000
KENNEY = "https://kenney.nl/media/pages/assets/"


class GameLibraryError(ValueError):
    """A pack, file or example the library can't give; the message says why."""


@dataclass(frozen=True, slots=True)
class Pack:
    id: str
    name: str
    category: str
    url: str
    sha256: str
    size: int
    shipped: bool
    files: tuple[str, ...]
    """Usable files: sprites, sheets, sounds, fonts, 3D models."""


@dataclass(frozen=True, slots=True)
class Example:
    id: str
    topic: str
    title: str
    code: str


def kind_of(path: str) -> str:
    lowered = path.casefold()
    suffix = Path(lowered).suffix
    if suffix in {".mp3", ".ogg", ".wav"}:
        return "sound"
    if suffix in {".ttf", ".otf"}:
        return "font"
    if suffix in {".glb", ".gltf"}:
        return "model"
    if "tilemap" in lowered or "tilesheet" in lowered or "spritesheet" in lowered:
        return "sheet"
    return "sprite"


@cache
def packs() -> tuple[Pack, ...]:
    rows = json.loads(gzip.decompress(CATALOGUE.read_bytes()))
    return tuple(
        Pack(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            url=row["url"],
            sha256=row["sha256"],
            size=row["size"],
            shipped=row["shipped"],
            files=tuple(row["files"]),
        )
        for row in rows
    )


def pack(pack_id: object) -> Pack:
    wanted = str(pack_id or "").strip().casefold().replace(" ", "-")
    for item in packs():
        if wanted in {item.id, item.name.casefold().replace(" ", "-")}:
            return item
    raise GameLibraryError(f"No pack called {pack_id!r}. Use action packs to see them.")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def find_packs(query: str = "", category: str = "") -> list[Pack]:
    words = _words(query)
    found = []
    for item in packs():
        if category and item.category.casefold() != category.casefold():
            continue
        name = set(_words(f"{item.id} {item.name} {item.category}"))
        if words and not all(
            any(part.startswith(word) for part in name) for word in words
        ):
            continue
        found.append(item)
    return sorted(found, key=lambda item: (not item.shipped, item.id))


def find_files(
    query: str, *, kind: str = "", count: int = 10
) -> list[tuple[Pack, str]]:
    """Files whose pack and path match every word; shipped packs first."""
    if kind and kind not in KINDS:
        raise GameLibraryError(f"No kind called {kind!r}. Kinds: {', '.join(KINDS)}.")
    words = _words(query)
    if not words:
        raise GameLibraryError("Say what you need, e.g. 'coin', 'laser sound'.")
    count = max(1, min(MAX_RESULTS, count))
    scored: list[tuple[int, bool, str, Pack, str]] = []
    for item in packs():
        pack_words = set(_words(f"{item.id} {item.name}"))
        for path in item.files:
            if kind and kind_of(path) != kind:
                continue
            path_words = set(_words(path))
            score = 0
            for word in words:
                if word in path_words:
                    score += 3
                elif any(part.startswith(word) for part in path_words):
                    score += 2
                elif any(part.startswith(word) for part in pack_words):
                    score += 1
                else:
                    score = -1
                    break
            if score > 0:
                scored.append(
                    (-score, not item.shipped, f"{item.id}/{path}", item, path)
                )
    scored.sort(key=lambda row: row[:3])
    # One pack shouldn't fill every slot: at most a third each.
    per_pack: dict[str, int] = {}
    chosen: list[tuple[Pack, str]] = []
    for _, _, _, item, path in scored:
        if per_pack.get(item.id, 0) >= max(3, count // 3):
            continue
        per_pack[item.id] = per_pack.get(item.id, 0) + 1
        chosen.append((item, path))
        if len(chosen) >= count:
            break
    return chosen


class GameVault:
    """The packs downloaded on this PC: kept for good, checked by SHA-256."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def path(self, item: Pack) -> Path:
        return self.folder / f"{item.id}.zip"

    def has(self, item: Pack) -> bool:
        return self.path(item).is_file()

    def keep(self, item: Pack, data: bytes) -> Path:
        digest = hashlib.sha256(data).hexdigest()
        if digest != item.sha256:
            raise GameLibraryError(
                f"{item.name} from kenney.nl doesn't match the checksum FCC "
                "recorded, so it wasn't kept."
            )
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.path(item)
        partial = target.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(target)
        return target


def ready(item: Pack, vault: GameVault | None) -> bool:
    return item.shipped or (vault is not None and vault.has(item))


def read_files(
    item: Pack, wanted: list[str], vault: GameVault | None
) -> dict[str, bytes]:
    """The pack's files by their catalogue path (from FCC or the vault)."""
    unknown = [path for path in wanted if path not in item.files]
    if unknown:
        raise GameLibraryError(
            f"{item.name} has no {unknown[0]!r}. Use action find or packs."
        )
    if item.shipped:
        with zipfile.ZipFile(CORE) as bundle:
            return {path: bundle.read(f"{item.id}/{path}") for path in wanted}
    if vault is None or not vault.has(item):
        raise GameLibraryError(
            f"{item.name} isn't on this PC yet: download it first (action "
            "download), then use it."
        )
    with zipfile.ZipFile(vault.path(item)) as bundle:
        names = {name.replace("\\", "/"): name for name in bundle.namelist()}
        missing = [path for path in wanted if path not in names]
        if missing:
            raise GameLibraryError(
                f"The downloaded {item.name} has no {missing[0]!r}; download it again."
            )
        return {path: bundle.read(names[path]) for path in wanted}


def choose(item: Pack, files: list[str] | str) -> list[str]:
    """Paths named exactly, or every file under a folder or matching a word."""
    asked = [files] if isinstance(files, str) else list(files)
    chosen: list[str] = []
    for want in (str(entry).strip().strip("/") for entry in asked):
        if not want:
            continue
        if want in item.files:
            chosen.append(want)
            continue
        under = [path for path in item.files if path.startswith(f"{want}/")]
        if not under:
            lowered = want.casefold()
            under = [path for path in item.files if lowered in path.casefold()]
        chosen.extend(under)
    return list(dict.fromkeys(chosen))


def project_path(item: Pack, path: str) -> str:
    """Where a pack file goes in a project: assets/<pack>/..., each name made
    safe for a project ('8-Bit jingles' becomes '8-Bit-jingles')."""
    parts = [
        re.sub(r"[^A-Za-z0-9._-]+", "-", part.replace("\u00d7", "x")).strip("-")
        or "file"
        for part in path.split("/")
    ]
    return "/".join(["assets", item.id, *parts])


@cache
def examples() -> tuple[Example, ...]:
    rows = json.loads(gzip.decompress(EXAMPLES.read_bytes()))
    return tuple(Example(**row) for row in rows)


def find_examples(query: str, count: int = 8) -> list[Example]:
    """Examples whose name, topic or code match the words; names count most."""
    words = _words(query)
    if not words:
        raise GameLibraryError("Say what the code should do, e.g. 'tilemap collision'.")
    scored: list[tuple[int, str, Example]] = []
    for item in examples():
        head = set(_words(f"{item.topic} {item.title}"))
        code = item.code.casefold()
        score = 0
        for word in words:
            if word in head:
                score += 4
            elif any(part.startswith(word) for part in head):
                score += 2
            elif word in code:
                score += 1
        if score >= len(words):
            scored.append((-score, item.id, item))
    scored.sort(key=lambda row: row[:2])
    return [row[2] for row in scored[: max(1, min(MAX_RESULTS, count))]]


def example(example_id: object) -> Example:
    wanted = str(example_id or "").strip().removesuffix(".js")
    for item in examples():
        if item.id == wanted:
            return item
    raise GameLibraryError(
        f"No example called {example_id!r}. Use an id from action examples."
    )
