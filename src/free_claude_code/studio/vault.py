"""The repo vault: a copy of every repo and release Studio downloads.

GitHub repos get deleted, renamed, or made private, and releases get
withdrawn. Whatever Studio fetches from GitHub (a repo added from a link, a
tool's release such as the Cua Driver) is first kept here, byte for byte,
with its SHA-256. When the original is gone, Studio installs from the copy,
and the user can download or restore any copy from the vault card.
"""

import hashlib
import json
import re
import secrets
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


class RepoVault:
    def __init__(self, folder: Path) -> None:
        self._folder = folder

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
            return path.is_file() and sha256(path.read_bytes()) == item.sha256

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
