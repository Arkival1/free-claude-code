"""Business photos the user sends agents, kept on this PC with their notes.

A photo of the real shop, the team, or the food, plus what the user said
about it, is what makes a site look like the business. The app shrinks
photos before sending them; here they are checked, sized, and kept.
"""

import re
import struct
from pathlib import Path

import anyio

from .models import Photo, now_ms
from .store import StudioStore

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_NOTE = 2_000
_KINDS = {
    "jpeg": (".jpg", "image/jpeg"),
    "png": (".png", "image/png"),
    "webp": (".webp", "image/webp"),
    "gif": (".gif", "image/gif"),
}
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


class PhotoError(ValueError):
    """A photo could not be kept."""


def image_info(data: bytes) -> tuple[str, int, int]:
    """(kind, width, height) of a JPEG, PNG, WebP, or GIF, from its header."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "gif", width, height
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
        elif chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            width, height = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        else:
            width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
            height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return "webp", width, height
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in {0xD8, 0x01, 0xFF} or 0xD0 <= marker <= 0xD7:
                index += 2 if marker != 0xFF else 1
                continue
            length = struct.unpack(">H", data[index + 2 : index + 4])[0]
            if marker in _SOF:
                height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                return "jpeg", width, height
            index += 2 + length
        raise PhotoError("That JPEG looks damaged.")
    if data[4:12] in {b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"}:
        raise PhotoError(
            "That's an iPhone HEIC photo, which browsers can't show. Send it "
            "from FCC Phone (it converts it), or set the iPhone to Settings → "
            "Camera → Formats → Most Compatible."
        )
    raise PhotoError("Send a JPEG, PNG, WebP, or GIF photo.")


def clean_name(name: str) -> str:
    """A tidy file name to show and to suggest for the site."""
    stem = Path(name.replace("\\", "/")).stem
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()[:60]
    return stem or "photo"


class PhotoLibrary:
    """The user's business photos: files on disk, notes in the store."""

    def __init__(self, store: StudioStore, root: Path) -> None:
        self._store = store
        self._root = root

    def path(self, photo: Photo) -> Path:
        return self._root / photo.file

    async def add(
        self, name: str, data: bytes, *, note: str = "", chat_id: str | None = None
    ) -> Photo:
        if len(data) > MAX_PHOTO_BYTES:
            raise PhotoError("That photo is over 15 MB; send a smaller one.")
        kind, width, height = image_info(data)
        suffix, content_type = _KINDS[kind]
        photo = Photo(
            name=f"{clean_name(name)}{suffix}",
            file="",
            content_type=content_type,
            width=width,
            height=height,
            size=len(data),
            note=note.strip()[:MAX_NOTE],
            chat_id=chat_id,
        )
        photo = photo.model_copy(update={"file": f"{photo.id}{suffix}"})

        def work() -> None:
            self._root.mkdir(parents=True, exist_ok=True)
            self.path(photo).write_bytes(data)

        await anyio.to_thread.run_sync(work)
        await self._store.put(photo)
        return photo

    async def photos(self, query: str = "") -> tuple[Photo, ...]:
        """Every photo, newest first, or those whose name or note match."""
        every = await self._store.find(Photo, order_by="created_at DESC")
        words = [
            word for word in re.findall(r"[a-z0-9]+", query.lower()) if len(word) > 2
        ]
        if not words:
            return every
        return tuple(
            photo
            for photo in every
            if any(word in f"{photo.name} {photo.note}".lower() for word in words)
        )

    async def find(self, reference: str) -> Photo:
        """A photo by its id or its name (with or without the extension)."""
        wanted = reference.strip().lower()
        for photo in await self._store.find(Photo, order_by="created_at DESC"):
            if wanted in {photo.id, photo.name.lower(), Path(photo.name).stem}:
                return photo
        raise PhotoError(
            f"No business photo called {reference!r}; list_photos shows them."
        )

    async def read(self, photo: Photo) -> bytes:
        return await anyio.to_thread.run_sync(self.path(photo).read_bytes)

    async def set_note(self, photo_id: str, note: str) -> Photo:
        photo = await self._store.require(Photo, photo_id)
        updated = photo.model_copy(
            update={"note": note.strip()[:MAX_NOTE], "updated_at": now_ms()}
        )
        await self._store.put(updated)
        return updated

    async def delete(self, photo_id: str) -> bool:
        photo = await self._store.get(Photo, photo_id)
        if photo is None:
            return False
        await anyio.to_thread.run_sync(lambda: self.path(photo).unlink(missing_ok=True))
        return await self._store.delete(Photo, photo_id)


def describe(photo: Photo) -> str:
    """One line an agent reads: name, size, shape, and the user's note."""
    shape = (
        "wide"
        if photo.width > photo.height * 1.15
        else "tall"
        if photo.height > photo.width * 1.15
        else "square"
    )
    note = f" — the user says: {photo.note}" if photo.note else ""
    return f"{photo.name} ({photo.width}x{photo.height}, {shape}, id {photo.id}){note}"
