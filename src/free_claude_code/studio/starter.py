"""Starter repos: outside repos Studio ships ready to use.

FCC keeps a copy of each one under ``vendor/repos`` (the parts Studio uses:
skills, commands, guides, lists, plugin and MCP manifests, and the licence),
with a SHA-256 checksum for every file, so they install with no download and
keep working if the original repo is deleted. A repo whose licence doesn't
allow FCC to share it is listed without a copy: Studio adds it from GitHub on
first load, and the Repo vault on the PC keeps that copy from then on.

On first load every starter repo is added like an "Add from GitHub" link, so
its skills reach every agent through the skill tool. Its MCP servers stay
switched off until the user turns each one on, and its agents join the team
only when the user adds them. Removing a starter repo sticks: it isn't added
back on the next load.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .extensions import ExtensionError

BUNDLE = Path(__file__).resolve().parents[3] / "vendor" / "repos"
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class StarterRepo:
    owner: str
    repo: str
    commit: str
    licence: str
    about: str
    file: str = ""
    """The vendored zip's name, or '' when the licence doesn't allow one."""
    sha256: str = ""
    size: int = 0
    left_out: str = ""
    """Why there is no vendored copy."""

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def source(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"

    @property
    def bundled(self) -> bool:
        return bool(self.file)

    @property
    def flag(self) -> str:
        """The one-time flag that says it was added once already."""
        return f"starter_repo:{self.full_name.lower()}"


def load_starters(folder: Path | None) -> list[StarterRepo]:
    """The starter repos listed in a bundle folder's manifest."""
    if folder is None:
        return []
    try:
        data = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return []
    rows = data.get("repos") if isinstance(data, dict) else None
    found: list[StarterRepo] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("owner") or not row.get("repo"):
            continue
        found.append(
            StarterRepo(
                owner=str(row["owner"]),
                repo=str(row["repo"]),
                commit=str(row.get("commit") or ""),
                licence=str(row.get("licence") or ""),
                about=str(row.get("about") or ""),
                file=str(row.get("file") or ""),
                sha256=str(row.get("sha256") or ""),
                size=int(row.get("size") or 0),
                left_out=str(row.get("left_out") or ""),
            )
        )
    return found


def bundled_bytes(folder: Path, starter: StarterRepo) -> bytes:
    """A starter's vendored zip, after checking it is the exact copy FCC shipped."""
    path = (folder / starter.file).resolve()
    if folder.resolve() not in path.parents or not path.is_file():
        raise ExtensionError(
            f"The copy of {starter.full_name} that came with FCC is missing."
        )
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != starter.sha256:
        raise ExtensionError(
            f"The copy of {starter.full_name} that came with FCC is damaged."
        )
    return data
