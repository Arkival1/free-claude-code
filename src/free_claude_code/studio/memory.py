"""Per-agent working and long-term memory with keyword recall."""

import math
import re
from collections.abc import Iterable, Sequence

from .models import MemoryEntry, now_ms
from .store import StudioStore

_WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9'_-]{1,}")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)
_DAY_MS = 86_400_000


def keywords(text: str, *, limit: int = 12) -> tuple[str, ...]:
    """Return the distinctive lowercase terms used for recall matching."""
    seen: dict[str, None] = {}
    for match in _WORD_PATTERN.finditer(text.lower()):
        word = match.group(0)
        if word in _STOPWORDS or len(word) < 3:
            continue
        seen.setdefault(word, None)
        if len(seen) >= limit:
            break
    return tuple(seen)


def _score(entry: MemoryEntry, terms: Sequence[str], *, now: int) -> float:
    haystack = f"{entry.text} {' '.join(entry.tags)}".lower()
    overlap = sum(1 for term in terms if term in haystack)
    if overlap == 0:
        return 0.0
    age_days = max(0.0, (now - entry.used_at) / _DAY_MS)
    recency = 1.0 / (1.0 + math.log1p(age_days))
    return overlap + 0.5 * math.log1p(entry.hits) + recency


class MemoryService:
    """Give each agent a memory it writes to and recalls from by itself."""

    def __init__(
        self,
        store: StudioStore,
        *,
        working_limit: int = 20,
        recall_limit: int = 6,
    ) -> None:
        self._store = store
        self._working_limit = max(1, working_limit)
        self._recall_limit = max(1, recall_limit)

    async def remember(
        self,
        agent_id: str,
        text: str,
        *,
        scope: str = "long_term",
        tags: Iterable[str] = (),
        source: str = "",
        chat_id: str | None = None,
    ) -> MemoryEntry | None:
        """Store one memory, ignoring blank text and exact duplicates."""
        cleaned = text.strip()
        if not cleaned:
            return None
        existing = await self._store.find(
            MemoryEntry, where={"agent_id": agent_id, "scope": scope}
        )
        normalized = cleaned.casefold()
        for entry in existing:
            if entry.text.casefold() == normalized:
                refreshed = entry.model_copy(
                    update={"hits": entry.hits + 1, "used_at": now_ms()}
                )
                await self._store.put(refreshed)
                return refreshed
        entry = MemoryEntry.model_validate(
            {
                "agent_id": agent_id,
                "scope": scope,
                "text": cleaned,
                "tags": tuple(
                    dict.fromkeys(tag.strip().lower() for tag in tags if tag.strip())
                ),
                "source": source,
                "chat_id": chat_id,
            }
        )
        await self._store.put(entry)
        if scope == "working":
            await self._trim_working(agent_id)
        return entry

    async def _trim_working(self, agent_id: str) -> None:
        entries = await self._store.find(
            MemoryEntry,
            where={"agent_id": agent_id, "scope": "working"},
            order_by="created_at DESC",
        )
        for stale in entries[self._working_limit :]:
            await self._store.delete(MemoryEntry, stale.id)

    async def working(self, agent_id: str) -> tuple[MemoryEntry, ...]:
        """Return the agent's short-term scratchpad, newest last."""
        entries = await self._store.find(
            MemoryEntry,
            where={"agent_id": agent_id, "scope": "working"},
            order_by="created_at DESC",
            limit=self._working_limit,
        )
        return tuple(reversed(entries))

    async def recall(
        self, agent_id: str, query: str, *, limit: int | None = None
    ) -> tuple[MemoryEntry, ...]:
        """Return the long-term memories most relevant to a query."""
        terms = keywords(query)
        if not terms:
            return ()
        candidates = await self._store.search_memory(agent_id, terms, limit=40)
        now = now_ms()
        ranked = sorted(
            ((entry, _score(entry, terms, now=now)) for entry in candidates),
            key=lambda pair: pair[1],
            reverse=True,
        )
        chosen = tuple(
            entry
            for entry, score in ranked[: limit or self._recall_limit]
            if score > 0.0
        )
        await self._store.touch_memories([entry.id for entry in chosen])
        return chosen

    async def context_block(self, agent_id: str, query: str) -> str:
        """Return recalled memory formatted for a system prompt, or empty text."""
        working = await self.working(agent_id)
        recalled = await self.recall(agent_id, query)
        sections: list[str] = []
        if recalled:
            lines = "\n".join(f"- {entry.text}" for entry in recalled)
            sections.append(f"What you remember about this:\n{lines}")
        if working:
            lines = "\n".join(f"- {entry.text}" for entry in working)
            sections.append(f"Your working notes right now:\n{lines}")
        return "\n\n".join(sections)

    async def entries(
        self, agent_id: str, *, scope: str | None = None
    ) -> tuple[MemoryEntry, ...]:
        """Return every memory an agent owns, newest first."""
        where: dict[str, object] = {"agent_id": agent_id}
        if scope is not None:
            where["scope"] = scope
        return await self._store.find(MemoryEntry, where=where, order_by="used_at DESC")

    async def forget(self, memory_id: str) -> bool:
        """Delete one memory."""
        return await self._store.delete(MemoryEntry, memory_id)

    async def clear(self, agent_id: str, *, scope: str | None = None) -> int:
        """Delete an agent's memories, optionally only one scope."""
        where: dict[str, object] = {"agent_id": agent_id}
        if scope is not None:
            where["scope"] = scope
        return await self._store.delete_where(MemoryEntry, where)

    async def promote(self, memory_id: str) -> MemoryEntry:
        """Move one working note into long-term memory."""
        entry = await self._store.require(MemoryEntry, memory_id)
        promoted = entry.model_copy(update={"scope": "long_term", "used_at": now_ms()})
        await self._store.put(promoted)
        return promoted
