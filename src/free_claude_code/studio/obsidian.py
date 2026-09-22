"""Mirror Studio work into an Obsidian vault on iOS or on a computer."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import anyio.to_thread

from .models import Agent, Chat, Course, ExamQuestion, Lesson, MemoryEntry, Message

DEFAULT_FOLDER = "FCC Studio"
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
    collapsed = re.sub(r"\s+", " ", cleaned)
    return (collapsed[:64] or fallback).strip()


def candidate_vaults(home: Path) -> tuple[Path, ...]:
    """Return the usual Obsidian vault locations on iOS and on a computer."""
    return (
        home / "Library/Mobile Documents/iCloud~md~obsidian/Documents",
        home / "Documents/Obsidian",
        home / "Obsidian",
        home / "iCloud Drive/Obsidian",
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
