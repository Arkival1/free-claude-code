"""The Content Farm's media library: your clips and pictures, by show.

Upload clips and photos, or link a folder on this PC (a clip library can be
huge, so linked files stay where they are). Every file gets tags from its
name and folders, so 'Breaking Bad/S1/walt teaching.mp4' is found for a
scene about Walt teaching. Mark gameplay or footage as a background to play
under a whole short. Songs go here too, for beat edits.
"""

import re
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path

import anyio

from free_claude_code.core.json_types import JsonObject

from ..memory import keywords
from ..models import FarmAsset, now_ms
from ..store import StudioStore
from .render import pillow_ready, probe, snapshot

IMAGE_TYPES = {".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image"}
VIDEO_TYPES = {
    ".mp4": "video",
    ".mov": "video",
    ".mkv": "video",
    ".webm": "video",
    ".m4v": "video",
    ".avi": "video",
}
AUDIO_TYPES = {
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".ogg": "audio",
    ".flac": "audio",
    ".aac": "audio",
    ".opus": "audio",
}
MEDIA_TYPES = {**IMAGE_TYPES, **VIDEO_TYPES, **AUDIO_TYPES}
MAX_LINKED = 5_000
"""Files read from one linked folder."""
MAX_UPLOAD = 4 * 1024 * 1024 * 1024
_SPLIT = re.compile(r"[\s_\-.()\[\],]+")
_EPISODE = re.compile(r"^s?\d{1,2}[ex]\d{1,3}$", re.I)


class LibraryError(ValueError):
    """Something the library can't do, said plainly."""


def name_tags(*parts: str) -> tuple[str, ...]:
    """Search words from a file's name and folders: 'S1/walt_teaching.mp4'."""
    words: dict[str, None] = {}
    for part in parts:
        for word in _SPLIT.split(Path(part).stem if "." in part else part):
            word = word.strip().lower()
            if len(word) >= 3 or _EPISODE.match(word):
                words.setdefault(word, None)
    return tuple(words)[:24]


def kind_of(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "")


def asset_view(asset: FarmAsset) -> JsonObject:
    view: JsonObject = asset.model_dump()
    view["tags"] = list(asset.tags)
    view["thumb_url"] = f"/studio/api/farm/media/{asset.id}/thumb"
    view["file_url"] = f"/studio/api/farm/media/{asset.id}/file"
    return view


def word_score(asset: FarmAsset, words: Sequence[str]) -> float:
    """How many of a scene's words the asset's name, tags, and note have."""
    haystack = " ".join((asset.name, " ".join(asset.tags), asset.note)).lower()
    points = sum(2.0 if f" {word} " in f" {haystack} " else 0.0 for word in words)
    return points + sum(0.5 for word in words if word in haystack)


def score(asset: FarmAsset, words: Sequence[str], show: str = "") -> float:
    """How well an asset fits a scene's words (and its show): an unnamed clip
    of the right show still fits a little, as filler."""
    points = word_score(asset, words)
    if show and asset.show and show.lower() in asset.show.lower():
        points += 1.0
    return points


class MediaLibrary:
    def __init__(self, store: StudioStore, root: Path) -> None:
        self._store = store
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    async def assets(self, *, show: str = "", kind: str = "") -> list[FarmAsset]:
        found = list(await self._store.find(FarmAsset, order_by="created_at DESC"))
        if kind:
            found = [asset for asset in found if asset.kind == kind]
        if show:
            wanted = show.lower()
            found = [
                asset
                for asset in found
                if not asset.show or wanted in asset.show.lower()
            ]
        return found

    async def asset(self, asset_id: str) -> FarmAsset:
        found = await self._store.get(FarmAsset, asset_id)
        if found is None:
            raise LibraryError("That clip or picture isn't in the library any more.")
        return found

    def path(self, asset: FarmAsset) -> Path:
        if asset.path:
            return Path(asset.path)
        return self._root / "files" / asset.file

    def thumb_path(self, asset: FarmAsset) -> Path:
        return self._root / "thumbs" / f"{asset.id}.jpg"

    async def thumb(self, asset: FarmAsset) -> Path | None:
        """A small still of the asset, made once."""
        out = self.thumb_path(asset)
        if out.is_file():
            return out
        source = self.path(asset)
        if not source.is_file():
            return None

        if asset.kind == "audio":
            return None

        def make() -> bool:
            if asset.kind == "video":
                return snapshot(source, out, at=min(2.0, asset.duration / 3 or 1.0))
            if not pillow_ready():
                return False
            from PIL import Image, ImageOps

            out.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(source) as opened:
                small = ImageOps.exif_transpose(opened).convert("RGB")
                small.thumbnail((360, 360))
                small.save(out, "JPEG", quality=82)
            return True

        try:
            made = await anyio.to_thread.run_sync(make)
        except OSError, ValueError:
            return None
        return out if made and out.is_file() else None

    async def add_file(
        self,
        source: Path,
        *,
        name: str,
        tags: Iterable[str] = (),
        note: str = "",
        show: str = "",
        background: bool = False,
        move: bool = False,
        source_kind: str = "upload",
        credit: str = "",
    ) -> FarmAsset:
        """Keep a file in the library (an upload, or a downloaded picture)."""
        clean_name = Path(name).name.strip() or source.name
        kind = kind_of(Path(clean_name)) or kind_of(source)
        if not kind:
            raise LibraryError(
                "Send a picture (JPG, PNG, WebP), a clip (MP4, MOV, MKV, WebM), "
                "or a song (MP3, WAV, M4A, OGG, FLAC)."
            )
        asset = FarmAsset(
            name=Path(clean_name).stem[:120],
            kind=kind,
            tags=tuple(dict.fromkeys((*_tags(tags), *name_tags(clean_name))))[:30],
            note=note[:1_000],
            show=show[:120],
            background=background,
            source=source_kind,
            credit=credit[:300],
        )
        suffix = Path(clean_name).suffix.lower() or source.suffix.lower()
        target = self._root / "files" / f"{asset.id}{suffix}"

        def keep() -> int:
            target.parent.mkdir(parents=True, exist_ok=True)
            if move:
                shutil.move(source, target)
            else:
                shutil.copyfile(source, target)
            return target.stat().st_size

        size = await anyio.to_thread.run_sync(keep)
        asset = asset.model_copy(update={"file": target.name, "size": size})
        return await self._store.put(await self._measured(asset))

    def incoming(self, name: str) -> Path:
        """Where an upload is written while it streams in."""
        folder = self._root / "incoming"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{now_ms()}-{Path(name).name or 'upload'}"

    async def link_folder(
        self, folder: str, *, show: str = "", background: bool = False
    ) -> list[FarmAsset]:
        """Add every clip and picture in a folder on this PC, in place."""
        root = Path(folder.strip().strip('"')).expanduser()
        if not root.is_dir():
            raise LibraryError(f"There's no folder at {root}.")
        known = {asset.path for asset in await self.assets() if asset.path}

        def walk() -> list[Path]:
            found: list[Path] = []
            for path in sorted(root.rglob("*")):
                if path.is_file() and kind_of(path) and str(path) not in known:
                    found.append(path)
                    if len(found) >= MAX_LINKED:
                        break
            return found

        files = await anyio.to_thread.run_sync(walk)
        added: list[FarmAsset] = []
        for path in files:
            relative = path.relative_to(root)
            asset = FarmAsset(
                name=path.stem[:120],
                kind=kind_of(path),
                path=str(path),
                tags=name_tags(*relative.parts, root.name),
                show=show[:120] or root.name[:120],
                background=background,
                source="folder",
                size=path.stat().st_size,
            )
            added.append(await self._measured(asset))
        if added:
            await self._store.put_many(added)
        return added

    async def _measured(self, asset: FarmAsset) -> FarmAsset:
        path = self.path(asset)
        if asset.kind in {"video", "audio"}:
            seconds, width, height = await anyio.to_thread.run_sync(lambda: probe(path))
            return asset.model_copy(
                update={"duration": round(seconds, 2), "width": width, "height": height}
            )
        if pillow_ready():
            try:
                from PIL import Image

                def measure() -> tuple[int, int]:
                    with Image.open(path) as opened:
                        return opened.size

                width, height = await anyio.to_thread.run_sync(measure)
                return asset.model_copy(update={"width": width, "height": height})
            except OSError, ValueError:
                pass
        return asset

    async def edit(self, asset_id: str, fields: JsonObject) -> FarmAsset:
        asset = await self.asset(asset_id)
        update: JsonObject = {"updated_at": now_ms()}
        if "tags" in fields:
            raw = fields.get("tags")
            items = raw if isinstance(raw, list) else str(raw or "").split(",")
            update["tags"] = list(_tags(str(item) for item in items))
        for key, limit in (("note", 1_000), ("show", 120), ("name", 120)):
            if key in fields:
                update[key] = str(fields.get(key) or "")[:limit]
        if "background" in fields:
            update["background"] = bool(fields.get("background"))
        changed = asset.model_copy(update=update)
        return await self._store.put(FarmAsset.model_validate(changed.model_dump()))

    async def delete(self, asset_id: str) -> bool:
        asset = await self.asset(asset_id)
        if not asset.path and asset.file:
            (self._root / "files" / asset.file).unlink(missing_ok=True)
        self.thumb_path(asset).unlink(missing_ok=True)
        return await self._store.delete(FarmAsset, asset.id)

    async def best(
        self,
        words: Sequence[str],
        *,
        show: str = "",
        kinds: Iterable[str] = ("image", "video"),
        used: set[str] | None = None,
        limit: int = 5,
    ) -> list[FarmAsset]:
        """The library's best fits for a scene, unused ones first."""
        allowed = set(kinds)
        pool = [
            asset
            for asset in await self.assets()
            if asset.kind in allowed and not asset.background
        ]
        scored = [(score(asset, words, show), asset) for asset in pool]
        scored = [item for item in scored if item[0] > 0]
        taken = used or set()
        scored.sort(key=lambda item: (item[1].id in taken, -item[0]))
        return [asset for _, asset in scored[:limit]]


def _tags(items: Iterable[str]) -> tuple[str, ...]:
    out: dict[str, None] = {}
    for item in items:
        word = " ".join(str(item).lower().strip(" #").split())[:40]
        if word:
            out.setdefault(word, None)
    return tuple(out)[:30]


def scene_words(text: str, extra: str = "") -> tuple[str, ...]:
    """The words a scene is matched by: names first, then other terms."""
    names = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", text)
    words: dict[str, None] = {}
    for name in names:
        for part in keywords(name):
            words.setdefault(part, None)
    for word in (*keywords(text, limit=24), *keywords(extra, limit=6)):
        words.setdefault(word, None)
    return tuple(words)[:32]
