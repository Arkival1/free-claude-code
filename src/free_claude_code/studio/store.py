"""Transaction-owned SQLite persistence for every Studio record."""

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import closing
from pathlib import Path

import anyio.to_thread

from .models import (
    Agent,
    AgentRun,
    Chat,
    Course,
    ExamQuestion,
    Lesson,
    MemoryEntry,
    Message,
    ModelAsset,
    Record,
    SiteProject,
    TuneJob,
    TunePack,
    TuneSample,
    now_ms,
)

_JSON_FIELDS = frozenset(
    {"tools", "tags", "settings", "data", "exemplars", "style_rules", "metrics"}
)

TABLES: Mapping[type[Record], str] = {
    Agent: "studio_agents",
    Chat: "studio_chats",
    Message: "studio_messages",
    MemoryEntry: "studio_memories",
    ModelAsset: "studio_assets",
    TunePack: "studio_tune_packs",
    TuneSample: "studio_tune_samples",
    TuneJob: "studio_tune_jobs",
    AgentRun: "studio_agent_runs",
    SiteProject: "studio_sites",
    Course: "studio_courses",
    Lesson: "studio_lessons",
    ExamQuestion: "studio_exam_questions",
}

_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("studio_messages_chat", "studio_messages", "chat_id, sequence"),
    ("studio_memories_agent", "studio_memories", "agent_id, scope"),
    ("studio_tune_samples_pack", "studio_tune_samples", "pack_id, split"),
    ("studio_tune_jobs_agent", "studio_tune_jobs", "agent_id, created_at"),
    ("studio_lessons_course", "studio_lessons", "course_id, ordinal"),
    ("studio_exam_questions_course", "studio_exam_questions", "course_id, ordinal"),
    ("studio_chats_kind", "studio_chats", "kind, updated_at"),
)


class StudioStoreError(RuntimeError):
    """Raised when persisted Studio state cannot satisfy a request."""


class StudioNotFoundError(StudioStoreError):
    """Raised when a requested record does not exist."""


def _table(model: type[Record]) -> str:
    table = TABLES.get(model)
    if table is None:
        raise StudioStoreError(f"{model.__name__} is not a persisted Studio record.")
    return table


def _encode(record: Record) -> dict[str, object]:
    values = record.model_dump()
    for key in values.keys() & _JSON_FIELDS:
        values[key] = json.dumps(values[key], separators=(",", ":"))
    return values


def _decode[T: Record](model: type[T], row: sqlite3.Row) -> T:
    values: dict[str, object] = {key: row[key] for key in model.model_fields}
    for key in values.keys() & _JSON_FIELDS:
        raw = values[key]
        values[key] = json.loads(raw) if isinstance(raw, str) else raw
    return model.model_validate(values)


def _schema(model: type[Record]) -> str:
    columns = ", ".join(
        "id TEXT PRIMARY KEY" if name == "id" else name for name in model.model_fields
    )
    return f"CREATE TABLE IF NOT EXISTS {_table(model)} ({columns})"


class StudioStore:
    """A small typed repository over one SQLite database file."""

    def __init__(self, database_path: Path) -> None:
        self._path = database_path
        self._ready = False

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, isolation_level=None, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _prepare(self) -> None:
        if self._ready:
            return
        with closing(self._connect()) as connection:
            for model in TABLES:
                connection.execute(_schema(model))
                self._migrate(connection, model)
            for name, table, columns in _INDEXES:
                connection.execute(
                    f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"
                )
        self._ready = True

    def _migrate(self, connection: sqlite3.Connection, model: type[Record]) -> None:
        """Add columns introduced after a database was first created."""
        table = _table(model)
        existing = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name in model.model_fields:
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name}")

    def _run[T](self, work: Callable[[sqlite3.Connection], T]) -> T:
        self._prepare()
        with closing(self._connect()) as connection:
            return work(connection)

    async def _call[T](self, work: Callable[[sqlite3.Connection], T]) -> T:
        return await anyio.to_thread.run_sync(lambda: self._run(work))

    async def put[T: Record](self, record: T) -> T:
        """Insert or replace one record and return it unchanged."""
        table = _table(type(record))
        values = _encode(record)
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)

        def work(connection: sqlite3.Connection) -> T:
            connection.execute(
                f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )
            return record

        return await self._call(work)

    async def put_many(self, records: Sequence[Record]) -> int:
        """Insert or replace many records of the same type in one transaction."""
        if not records:
            return 0
        model = type(records[0])
        if any(type(record) is not model for record in records):
            raise StudioStoreError("put_many needs records of one type.")
        table = _table(model)
        rows = [_encode(record) for record in records]
        columns = ",".join(rows[0])
        placeholders = ",".join("?" for _ in rows[0])

        def work(connection: sqlite3.Connection) -> int:
            connection.executemany(
                f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})",
                [tuple(row.values()) for row in rows],
            )
            return len(rows)

        return await self._call(work)

    async def get[T: Record](self, model: type[T], record_id: str) -> T | None:
        """Return one record by identifier, or None when it is absent."""
        table = _table(model)

        def work(connection: sqlite3.Connection) -> T | None:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ?", (record_id,)
            ).fetchone()
            return None if row is None else _decode(model, row)

        return await self._call(work)

    async def require[T: Record](self, model: type[T], record_id: str) -> T:
        """Return one record by identifier or raise ``StudioNotFoundError``."""
        record = await self.get(model, record_id)
        if record is None:
            raise StudioNotFoundError(f"{model.__name__} '{record_id}' was not found.")
        return record

    async def find[T: Record](
        self,
        model: type[T],
        *,
        where: Mapping[str, object] | None = None,
        order_by: str = "created_at ASC",
        limit: int | None = None,
    ) -> tuple[T, ...]:
        """Return records matching an equality filter in a stable order."""
        table = _table(model)
        criteria = dict(where or {})
        for key in criteria:
            if key not in model.model_fields:
                raise StudioStoreError(f"Unknown filter column '{key}'.")
        clause = (
            " WHERE " + " AND ".join(f"{key} IS ?" for key in criteria)
            if criteria
            else ""
        )
        tail = f" LIMIT {int(limit)}" if limit is not None else ""
        sql = f"SELECT * FROM {table}{clause} ORDER BY {order_by}{tail}"

        def work(connection: sqlite3.Connection) -> tuple[T, ...]:
            rows = connection.execute(sql, tuple(criteria.values())).fetchall()
            return tuple(_decode(model, row) for row in rows)

        return await self._call(work)

    async def delete(self, model: type[Record], record_id: str) -> bool:
        """Delete one record, returning whether a row was removed."""
        table = _table(model)

        def work(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE id = ?", (record_id,)
            )
            return cursor.rowcount > 0

        return await self._call(work)

    async def delete_where(
        self, model: type[Record], where: Mapping[str, object]
    ) -> int:
        """Delete every record matching an equality filter."""
        table = _table(model)
        if not where:
            raise StudioStoreError("Refusing to delete without a filter.")
        for key in where:
            if key not in model.model_fields:
                raise StudioStoreError(f"Unknown filter column '{key}'.")
        clause = " AND ".join(f"{key} IS ?" for key in where)

        def work(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE {clause}", tuple(where.values())
            )
            return cursor.rowcount

        return await self._call(work)

    async def append_message(
        self,
        *,
        chat_id: str,
        role: str,
        text: str,
        author: str = "",
        data: Mapping[str, object] | None = None,
    ) -> Message:
        """Append one transcript entry with a gap-free per-chat sequence."""

        def work(connection: sqlite3.Connection) -> Message:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next"
                " FROM studio_messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            message = Message.model_validate(
                {
                    "chat_id": chat_id,
                    "sequence": int(row["next"]),
                    "role": role,
                    "author": author,
                    "text": text,
                    "data": dict(data or {}),
                }
            )
            values = _encode(message)
            connection.execute(
                "INSERT INTO studio_messages"
                f" ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
                tuple(values.values()),
            )
            connection.execute(
                "UPDATE studio_chats SET updated_at = ? WHERE id = ?",
                (now_ms(), chat_id),
            )
            return message

        return await self._call(work)

    async def transcript(
        self, chat_id: str, *, limit: int | None = None, after: int = 0
    ) -> tuple[Message, ...]:
        """Return a chat transcript in order, optionally only its recent tail."""

        def work(connection: sqlite3.Connection) -> tuple[Message, ...]:
            if limit is None:
                rows = connection.execute(
                    "SELECT * FROM studio_messages"
                    " WHERE chat_id = ? AND sequence > ? ORDER BY sequence ASC",
                    (chat_id, after),
                ).fetchall()
            else:
                rows = list(
                    reversed(
                        connection.execute(
                            "SELECT * FROM studio_messages"
                            " WHERE chat_id = ? AND sequence > ?"
                            " ORDER BY sequence DESC LIMIT ?",
                            (chat_id, after, int(limit)),
                        ).fetchall()
                    )
                )
            return tuple(_decode(Message, row) for row in rows)

        return await self._call(work)

    async def search_memory(
        self, agent_id: str, terms: Iterable[str], *, limit: int = 8
    ) -> tuple[MemoryEntry, ...]:
        """Return long-lived memories whose text matches any search term."""
        patterns = [f"%{term.lower()}%" for term in terms if term.strip()]
        if not patterns:
            return ()
        clause = " OR ".join("LOWER(text) LIKE ?" for _ in patterns)

        def work(connection: sqlite3.Connection) -> tuple[MemoryEntry, ...]:
            rows = connection.execute(
                "SELECT * FROM studio_memories"
                f" WHERE agent_id = ? AND ({clause})"
                " ORDER BY hits DESC, used_at DESC LIMIT ?",
                (agent_id, *patterns, int(limit)),
            ).fetchall()
            return tuple(_decode(MemoryEntry, row) for row in rows)

        return await self._call(work)

    async def touch_memories(self, memory_ids: Sequence[str]) -> None:
        """Record that memories were recalled, so useful ones rank higher."""
        if not memory_ids:
            return
        stamp = now_ms()

        def work(connection: sqlite3.Connection) -> None:
            connection.executemany(
                "UPDATE studio_memories SET hits = hits + 1, used_at = ? WHERE id = ?",
                [(stamp, memory_id) for memory_id in memory_ids],
            )

        await self._call(work)
