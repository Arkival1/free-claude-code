"""Mirror Studio work into an Obsidian vault on iOS or on a computer."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import anyio.to_thread

from .models import Agent, Chat, Course, ExamQuestion, Lesson, MemoryEntry, Message
from .sites import is_windows_reserved

DEFAULT_FOLDER = "FCC Studio"
MEMORY_FOLDER = "Memory"
MEMORY_MARKER = "fcc_memory_id"
KIND_MARKER = "fcc_kind"
SCOPE_FOLDERS = {"working": "Working memory", "long_term": "Long-term memory"}
FOLDER_SCOPES = {folder: scope for scope, folder in SCOPE_FOLDERS.items()}
_FOOTER_PREFIX = "Belongs to "
_UNSAFE = re.compile(r"[^A-Za-z0-9 ._-]+")


class ObsidianError(RuntimeError):
    """Raised when the configured vault cannot be written."""


@dataclass(frozen=True, slots=True)
class VaultStatus:
    """What the UI shows about the configured vault."""

    configured: bool
    path: str
    exists: bool
    writable: bool
    note_count: int
    candidates: tuple[str, ...]


def note_name(title: str, *, fallback: str = "note") -> str:
    """Return a safe Obsidian note filename stem."""
    cleaned = _UNSAFE.sub(" ", title).strip()
    collapsed = re.sub(r"\s+", " ", cleaned)[:64].rstrip(" .")
    name = collapsed or fallback
    if is_windows_reserved(name):
        name = f"{name} note"
    return name


def candidate_vaults(home: Path) -> tuple[Path, ...]:
    """Return the usual Obsidian vault locations on iOS and on a computer."""
    return (
        home / "Library/Mobile Documents/iCloud~md~obsidian/Documents",
        home / "Documents/Obsidian",
        home / "Documents/Obsidian Vault",
        home / "OneDrive/Documents/Obsidian",
        home / "OneDrive/Documents/Obsidian Vault",
        home / "Obsidian",
        home / "Obsidian Vault",
        home / "iCloud Drive/Obsidian",
        home / "iCloudDrive/iCloud~md~obsidian",
    )


def frontmatter(values: dict[str, object]) -> str:
    """Render YAML frontmatter for one note."""
    lines = ["---"]
    for key, value in values.items():
        if isinstance(value, list | tuple):
            rendered = ", ".join(str(item) for item in value)
            lines.append(f"{key}: [{rendered}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class MirrorResult:
    """What one memory mirror wrote and removed."""

    notes_written: int
    notes_removed: int
    agents: int


@dataclass(frozen=True, slots=True)
class MemoryEdit:
    """A memory note the user changed inside Obsidian."""

    memory_id: str
    text: str
    scope: str


def _parse_note(body: str) -> tuple[dict[str, str], str]:
    """Split a note into flat frontmatter values and its body."""
    if not body.startswith("---\n"):
        return {}, body
    end = body.find("\n---", 4)
    if end < 0:
        return {}, body
    values: dict[str, str] = {}
    for line in body[4:end].splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values, body[end + 4 :].lstrip("\n")


def _memory_body(body: str) -> str:
    """Return the memory text, without the link footer Studio adds."""
    lines = body.rstrip().splitlines()
    while lines and (not lines[-1].strip() or lines[-1].startswith(_FOOTER_PREFIX)):
        lines.pop()
    return "\n".join(lines).strip()


def _stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ObsidianVault:
    """Write Studio notes into a vault folder the user already syncs."""

    def __init__(self, root: Path | None, *, folder: str = DEFAULT_FOLDER) -> None:
        self._root = root
        self._folder = folder.strip("/") or DEFAULT_FOLDER

    @property
    def configured(self) -> bool:
        return self._root is not None

    @property
    def base(self) -> Path:
        if self._root is None:
            raise ObsidianError("No Obsidian vault is configured yet.")
        return self._root / self._folder

    async def status(self, *, home: Path | None = None) -> VaultStatus:
        """Describe the vault for the settings screen."""
        candidates = tuple(
            str(path) for path in candidate_vaults(home or Path.home()) if path.is_dir()
        )
        if self._root is None:
            return VaultStatus(False, "", False, False, 0, candidates)

        def work() -> VaultStatus:
            exists = self._root is not None and self._root.is_dir()
            writable = False
            notes = 0
            if exists:
                try:
                    self.base.mkdir(parents=True, exist_ok=True)
                    probe = self.base / ".fcc-write-test"
                    probe.write_text("", encoding="utf-8")
                    probe.unlink()
                    writable = True
                    notes = sum(1 for _ in self.base.rglob("*.md"))
                except OSError:
                    writable = False
            return VaultStatus(
                True, str(self._root), exists, writable, notes, candidates
            )

        return await anyio.to_thread.run_sync(work)

    async def _write(self, relative: str, body: str) -> Path:
        base = self.base

        def work() -> Path:
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            return target

        try:
            return await anyio.to_thread.run_sync(work)
        except OSError as error:
            raise ObsidianError(f"Could not write to the vault: {error}") from error

    async def export_chat(
        self, chat: Chat, messages: Sequence[Message], *, agent: Agent | None = None
    ) -> Path:
        """Write one conversation as a dated note."""
        header = frontmatter(
            {
                "title": chat.title,
                "type": f"fcc-{chat.kind}",
                "agent": agent.name if agent else "",
                "chat_id": chat.id,
                "tags": ["fcc-studio", chat.kind],
            }
        )
        lines = [header, "", f"# {chat.title}", ""]
        for message in messages:
            speaker = message.author or message.role
            lines.append(f"**{speaker}**")
            lines.append("")
            lines.append(message.text)
            lines.append("")
        return await self._write(f"Chats/{note_name(chat.title)}.md", "\n".join(lines))

    async def export_memory(self, agent: Agent, entries: Sequence[MemoryEntry]) -> Path:
        """Write one agent's memory as a single browsable note."""
        header = frontmatter(
            {
                "title": f"{agent.name} memory",
                "type": "fcc-memory",
                "agent_id": agent.id,
                "tags": ["fcc-studio", "memory"],
            }
        )
        long_term = [item for item in entries if item.scope == "long_term"]
        working = [item for item in entries if item.scope == "working"]
        lines = [header, "", f"# {agent.name} memory", "", "## Long term", ""]
        lines.extend(f"- {item.text}" for item in long_term)
        lines.extend(["", "## Working notes", ""])
        lines.extend(f"- {item.text}" for item in working)
        return await self._write(
            f"Agents/{note_name(agent.name)} memory.md", "\n".join(lines)
        )

    async def export_course(
        self,
        course: Course,
        *,
        lessons: Sequence[Lesson],
        questions: Sequence[ExamQuestion],
        teacher: Agent | None = None,
        student: Agent | None = None,
    ) -> Path:
        """Write a class, its lessons, and its test results as one note."""
        header = frontmatter(
            {
                "title": f"Class: {course.topic}",
                "type": "fcc-class",
                "status": course.status,
                "score": f"{course.score:.2f}" if course.score is not None else "",
                "teacher": teacher.name if teacher else "",
                "student": student.name if student else "",
                "tags": ["fcc-studio", "class"],
            }
        )
        lines = [header, "", f"# Class: {course.topic}", "", "## Lessons", ""]
        for lesson in lessons:
            lines.append(f"### {lesson.ordinal}. {lesson.topic}")
            lines.append("")
            lines.append(lesson.objective)
            if lesson.notes:
                lines.append("")
                lines.append(f"> {lesson.notes}")
            lines.append("")
        lines.extend(["## Test", ""])
        for question in questions:
            score = "—" if question.score is None else f"{question.score:.0%}"
            lines.append(f"**Q{question.ordinal} ({score})** {question.prompt}")
            lines.append("")
            lines.append(question.answer)
            if question.feedback:
                lines.append("")
                lines.append(f"> {question.feedback}")
            lines.append("")
        return await self._write(
            f"Classes/{note_name(course.topic)}.md", "\n".join(lines)
        )

    def _memory_root(self) -> Path:
        return self.base / MEMORY_FOLDER

    def _link(self, relative: str, label: str) -> str:
        """Return a vault-relative wikilink that survives duplicate note names."""
        return f"[[{self._folder}/{MEMORY_FOLDER}/{relative}|{label}]]"

    async def mirror_memory(
        self,
        agents: Sequence[Agent],
        entries: Mapping[str, Sequence[MemoryEntry]],
    ) -> MirrorResult:
        """Write each agent's memory as linked notes and prune stale ones.

        Only files Studio wrote (they carry a Studio frontmatter marker) are
        ever removed, so the user's own notes in the folder are left alone.
        """
        root = self._memory_root()
        planned: dict[Path, str] = {}
        memory_texts: dict[Path, str] = {}
        index_lines = [
            frontmatter({KIND_MARKER: "index", "tags": ["fcc-studio", "memory"]}),
            "",
            "# Agent memory",
            "",
            "Every agent's working notes and long-term memories. Edit a memory "
            "note here and pull it back into Studio; move it between the "
            "Working and Long-term folders to change its scope.",
            "",
        ]
        for agent in agents:
            folder = note_name(agent.name, fallback=agent.id)
            own = list(entries.get(agent.id, ()))
            hub_lines = [
                frontmatter(
                    {
                        KIND_MARKER: "agent",
                        "fcc_agent_id": agent.id,
                        "role": agent.role,
                        "model": agent.model,
                        "tags": ["fcc-studio", "agent"],
                    }
                ),
                "",
                f"# {agent.name}",
                "",
                f"{agent.role} · `{agent.model}`",
                "",
            ]
            for scope, scope_folder in SCOPE_FOLDERS.items():
                hub_lines.extend([f"## {scope_folder}", ""])
                scoped = [entry for entry in own if entry.scope == scope]
                if not scoped:
                    hub_lines.extend(["_Nothing yet._", ""])
                for entry in scoped:
                    stem = f"{note_name(entry.text[:48], fallback='memory')} ({entry.id[-8:]})"
                    relative = f"{folder}/{scope_folder}/{stem}"
                    hub_lines.append(f"- {self._link(relative, entry.text[:80])}")
                    tags = ["fcc-memory", *entry.tags]
                    memory_texts[root / f"{relative}.md"] = entry.text
                    planned[root / f"{relative}.md"] = "\n".join(
                        [
                            frontmatter(
                                {
                                    MEMORY_MARKER: entry.id,
                                    "agent": agent.name,
                                    "scope": entry.scope,
                                    "hits": entry.hits,
                                    "source": entry.source or "unknown",
                                    "created": _stamp(entry.created_at),
                                    "tags": tags,
                                }
                            ),
                            "",
                            entry.text,
                            "",
                            f"{_FOOTER_PREFIX}{self._link(f'{folder}/{folder}', agent.name)}",
                            "",
                        ]
                    )
                hub_lines.append("")
            planned[root / folder / f"{folder}.md"] = "\n".join(hub_lines)
            index_lines.append(
                f"- {self._link(f'{folder}/{folder}', agent.name)} — "
                f"{sum(1 for entry in own if entry.scope == 'long_term')} long-term, "
                f"{sum(1 for entry in own if entry.scope == 'working')} working"
            )
        planned[root / "Memory index.md"] = "\n".join([*index_lines, ""])

        def work() -> MirrorResult:
            written = 0
            for path, body in planned.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                existing = path.read_text(encoding="utf-8") if path.is_file() else None
                if existing == body:
                    continue
                expected = memory_texts.get(path)
                if (
                    existing is not None
                    and expected is not None
                    and _memory_body(_parse_note(existing)[1]) != expected
                ):
                    # Edited in Obsidian after this sync's pull: keep the
                    # user's words; the next sync brings them into Studio.
                    continue
                path.write_text(body, encoding="utf-8")
                written += 1
            removed = 0
            for path in sorted(root.rglob("*.md")):
                if path in planned:
                    continue
                values, _ = _parse_note(
                    path.read_text(encoding="utf-8", errors="replace")
                )
                if MEMORY_MARKER in values or KIND_MARKER in values:
                    path.unlink()
                    removed += 1
            for directory in sorted(
                (item for item in root.rglob("*") if item.is_dir()), reverse=True
            ):
                if not any(directory.iterdir()):
                    directory.rmdir()
            return MirrorResult(written, removed, len(agents))

        try:
            return await anyio.to_thread.run_sync(work)
        except OSError as error:
            raise ObsidianError(f"Could not mirror memory: {error}") from error

    async def memory_edits(
        self, current: Mapping[str, MemoryEntry]
    ) -> tuple[MemoryEdit, ...]:
        """Return memory notes whose text or folder differs from Studio's copy."""
        root = self._memory_root()

        def work() -> tuple[MemoryEdit, ...]:
            if not root.is_dir():
                return ()
            edits: list[MemoryEdit] = []
            for path in sorted(root.rglob("*.md")):
                values, body = _parse_note(
                    path.read_text(encoding="utf-8", errors="replace")
                )
                memory_id = values.get(MEMORY_MARKER)
                if not memory_id or memory_id not in current:
                    continue
                entry = current[memory_id]
                text = _memory_body(body)
                scope = FOLDER_SCOPES.get(path.parent.name, entry.scope)
                if text and (text != entry.text or scope != entry.scope):
                    edits.append(MemoryEdit(memory_id, text, scope))
            return tuple(edits)

        return await anyio.to_thread.run_sync(work)

    async def import_notes(self, *, subfolder: str = "Inbox") -> tuple[str, ...]:
        """Read notes the user dropped in the vault so agents can remember them."""
        base = self.base / subfolder

        def work() -> tuple[str, ...]:
            if not base.is_dir():
                return ()
            return tuple(
                path.read_text(encoding="utf-8", errors="replace")
                for path in sorted(base.glob("*.md"))
            )

        return await anyio.to_thread.run_sync(work)
