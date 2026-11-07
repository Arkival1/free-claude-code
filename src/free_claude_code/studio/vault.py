"""The repo vault: a copy of every repo and release Studio downloads.

GitHub repos get deleted, renamed, or made private, and releases get
withdrawn. Whatever Studio fetches from GitHub (a repo added from a link, a
tool's release such as the Cua Driver) is first kept here, byte for byte,
with its SHA-256. When the original is gone, Studio installs from the copy,
and the user can download or restore any copy from the vault card.
"""

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import anyio.to_thread

from free_claude_code.core.json_types import JsonObject

INDEX = "vault.json"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class VaultError(ValueError):
    """Something the vault can't do, said plainly."""


@dataclass(slots=True)
class VaultItem:
    id: str
    owner: str
    repo: str
    kind: str
    """source (a repo's files) or release (a published download)."""
    name: str
    """The file's name, e.g. 'cua-driver-rs-0.34.0-windows-x86_64.zip'."""
    ref: str
    """The branch, tag, or commit it came from ('' for the default branch)."""
    url: str
    sha256: str
    size: int
    saved_at: int
    file: str
    """Where it is inside the vault folder."""

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def _safe(text: str) -> str:
    return _SAFE.sub("-", text).strip("-.") or "file"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _link_or_copy(source: Path, target: Path) -> None:
    partial = target.with_name(target.name + ".part")
    partial.unlink(missing_ok=True)
    try:
        os.link(source, partial)
    except OSError:
        shutil.copyfile(source, partial)
    partial.replace(target)


class RepoVault:
    def __init__(self, folder: Path) -> None:
        self._folder = folder
        # Keeps can run at once (an engine download and the voice setup);
        # the index is read and rewritten by one at a time.
        self._index_lock = threading.Lock()

    @property
    def folder(self) -> Path:
        return self._folder

    def _read(self) -> list[VaultItem]:
        index = self._folder / INDEX
        if not index.is_file():
            return []
        try:
            raw = json.loads(index.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return []
        items: list[VaultItem] = []
        for row in raw if isinstance(raw, list) else []:
            if isinstance(row, dict):
                try:
                    items.append(VaultItem(**{k: row[k] for k in VaultItem.__slots__}))
                except KeyError, TypeError:
                    continue
        return items

    def _write(self, items: list[VaultItem]) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        index = self._folder / INDEX
        partial = index.with_suffix(".part")
        partial.write_text(
            json.dumps([item.to_json() for item in items], indent=2), encoding="utf-8"
        )
        partial.replace(index)

    def path(self, item: VaultItem) -> Path:
        path = (self._folder / item.file).resolve()
        if self._folder.resolve() not in path.parents:
            raise VaultError("That vault entry points outside the vault.")
        return path

    async def keep(
        self,
        *,
        owner: str,
        repo: str,
        kind: str,
        name: str,
        data: bytes,
        url: str,
        ref: str = "",
    ) -> VaultItem:
        """Keep a copy; the same bytes kept twice are stored once."""
        digest = sha256(data)

        def work() -> VaultItem:
            with self._index_lock:
                return locked()

        def locked() -> VaultItem:
            items = self._read()
            for item in items:
                if (
                    item.sha256 == digest
                    and item.full_name.lower() == f"{owner}/{repo}".lower()
                ):
                    return item
            folder = f"{_safe(owner)}__{_safe(repo)}"
            stamp = time.strftime("%Y%m%d-%H%M%S")
            file = f"{folder}/{stamp}-{digest[:8]}-{_safe(name)}"
            target = self._folder / file
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            partial.write_bytes(data)
            partial.replace(target)
            item = VaultItem(
                id=f"vlt_{secrets.token_hex(5)}",
                owner=owner,
                repo=repo,
                kind=kind,
                name=name,
                ref=ref,
                url=url,
                sha256=digest,
                size=len(data),
                saved_at=int(time.time() * 1000),
                file=file,
            )
            self._write([*items, item])
            return item

        return await anyio.to_thread.run_sync(work)

    async def keep_file(
        self,
        *,
        owner: str,
        repo: str,
        kind: str,
        path: Path,
        url: str,
        ref: str = "",
    ) -> VaultItem:
        """Keep a big downloaded file (an engine build, a voice model) without
        reading it all into memory. The vault's copy is a hard link when the
        disk allows it, so it takes no extra space; otherwise a copy."""

        def work() -> VaultItem:
            digest = _file_sha256(path)
            with self._index_lock:
                return locked(digest)

        def locked(digest: str) -> VaultItem:
            items = self._read()
            for item in items:
                if (
                    item.sha256 == digest
                    and item.full_name.lower() == f"{owner}/{repo}".lower()
                    and self.path(item).is_file()
                ):
                    return item
            folder = f"{_safe(owner)}__{_safe(repo)}"
            stamp = time.strftime("%Y%m%d-%H%M%S")
            file = f"{folder}/{stamp}-{digest[:8]}-{_safe(path.name)}"
            target = self._folder / file
            target.parent.mkdir(parents=True, exist_ok=True)
            _link_or_copy(path, target)
            item = VaultItem(
                id=f"vlt_{secrets.token_hex(5)}",
                owner=owner,
                repo=repo,
                kind=kind,
                name=path.name,
                ref=ref,
                url=url,
                sha256=digest,
                size=path.stat().st_size,
                saved_at=int(time.time() * 1000),
                file=file,
            )
            self._write([*items, item])
            return item

        return await anyio.to_thread.run_sync(work)

    def has(self, owner: str, repo: str, *, name: str, size: int) -> bool:
        """Whether a file of this name and size is kept (a quick look that
        doesn't read it, to skip keeping a big file twice)."""
        return any(
            item.full_name.lower() == f"{owner}/{repo}".lower()
            and item.name == name
            and item.size == size
            and self.path(item).is_file()
            for item in self._read()
        )

    async def restore_file(self, item: VaultItem, target: Path) -> Path:
        """Put a kept file back at target (linked when the disk allows),
        after checking it is still the exact bytes that were kept."""

        def work() -> Path:
            source = self.path(item)
            if not source.is_file() or _file_sha256(source) != item.sha256:
                raise VaultError(f"The vault copy of {item.name} is damaged.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)
            _link_or_copy(source, target)
            return target

        return await anyio.to_thread.run_sync(work)

    async def items(self) -> list[VaultItem]:
        found = await anyio.to_thread.run_sync(self._read)
        return sorted(found, key=lambda item: -item.saved_at)

    async def item(self, item_id: str) -> VaultItem:
        for item in await self.items():
            if item.id == item_id:
                return item
        raise VaultError("That copy isn't in the vault any more.")

    async def latest(
        self, owner: str, repo: str, *, kind: str = "source", name: str = ""
    ) -> VaultItem | None:
        """The newest copy of a repo (or of one release file) that is still
        on disk and still matches its checksum."""
        for item in await self.items():
            if item.full_name.lower() != f"{owner}/{repo}".lower() or item.kind != kind:
                continue
            if name and item.name != name:
                continue
            if await self.intact(item):
                return item
        return None

    async def intact(self, item: VaultItem) -> bool:
        def work() -> bool:
            path = self.path(item)
            return path.is_file() and _file_sha256(path) == item.sha256

        return await anyio.to_thread.run_sync(work)

    async def read(self, item: VaultItem) -> bytes:
        def work() -> bytes:
            data = self.path(item).read_bytes()
            if sha256(data) != item.sha256:
                raise VaultError(f"The vault copy of {item.name} is damaged.")
            return data

        return await anyio.to_thread.run_sync(work)

    async def remove(self, item_id: str) -> bool:
        def work() -> bool:
            with self._index_lock:
                return locked()

        def locked() -> bool:
            items = self._read()
            kept = [item for item in items if item.id != item_id]
            if len(kept) == len(items):
                return False
            for item in items:
                if item.id == item_id:
                    self.path(item).unlink(missing_ok=True)
            self._write(kept)
            return True

        return await anyio.to_thread.run_sync(work)


def item_view(item: VaultItem) -> JsonObject:
    view: JsonObject = {
        **asdict(item),
        "full_name": item.full_name,
        "file_url": f"/studio/api/vault/{item.id}/file",
    }
    return view
