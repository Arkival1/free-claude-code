"""The Studio store keeps records, transcripts, and agent memory coherent."""

import pytest

from free_claude_code.studio.memory import MemoryService, keywords
from free_claude_code.studio.models import Agent, Chat, MemoryEntry
from free_claude_code.studio.store import StudioNotFoundError


@pytest.mark.asyncio
async def test_records_round_trip_with_json_fields(store):
    agent = Agent.model_validate(
        {"name": "Builder", "model": "p/m", "tools": ("web_search", "finish")}
    )
    await store.put(agent)

    loaded = await store.require(Agent, agent.id)
    assert loaded.tools == ("web_search", "finish")
    assert loaded.memory_enabled is True


@pytest.mark.asyncio
async def test_missing_record_is_reported(store):
    with pytest.raises(StudioNotFoundError):
        await store.require(Agent, "agt_missing")


@pytest.mark.asyncio
async def test_transcript_sequences_are_gap_free(store):
    chat = Chat.model_validate({"title": "t"})
    await store.put(chat)

    for index in range(3):
        await store.append_message(chat_id=chat.id, role="user", text=f"hello {index}")

    transcript = await store.transcript(chat.id)
    assert [message.sequence for message in transcript] == [1, 2, 3]
    assert transcript[-1].text == "hello 2"

    tail = await store.transcript(chat.id, after=2)
    assert [message.sequence for message in tail] == [3]


@pytest.mark.asyncio
async def test_find_filters_and_orders(store):
    first = Chat.model_validate({"title": "a", "kind": "chat"})
    second = Chat.model_validate({"title": "b", "kind": "classroom"})
    await store.put_many([first, second])

    classrooms = await store.find(Chat, where={"kind": "classroom"})
    assert [chat.title for chat in classrooms] == ["b"]


def test_keywords_drop_stopwords_and_short_words():
    assert keywords("What is the tide table for today") == (
        "tide",
        "table",
        "today",
    )


@pytest.mark.asyncio
async def test_memory_recall_prefers_matching_entries(store):
    memory = MemoryService(store, working_limit=3, recall_limit=2)
    await memory.remember("agt_1", "Tides are driven by the moon.")
    await memory.remember("agt_1", "The user prefers metric units.")

    recalled = await memory.recall("agt_1", "how do tides work?")
    assert [entry.text for entry in recalled] == ["Tides are driven by the moon."]

    stored = await store.require(MemoryEntry, recalled[0].id)
    assert stored.hits == 1


@pytest.mark.asyncio
async def test_duplicate_memory_is_reinforced_not_repeated(store):
    memory = MemoryService(store)
    first = await memory.remember("agt_1", "Keep answers short.")
    second = await memory.remember("agt_1", "Keep answers short.")

    assert first is not None and second is not None
    assert first.id == second.id
    assert second.hits == 1
    assert len(await memory.entries("agt_1")) == 1


@pytest.mark.asyncio
async def test_working_memory_is_trimmed_and_promotable(store):
    memory = MemoryService(store, working_limit=2)
    for index in range(4):
        await memory.remember("agt_1", f"note {index}", scope="working")

    working = await memory.working("agt_1")
    assert [entry.text for entry in working] == ["note 2", "note 3"]

    promoted = await memory.promote(working[-1].id)
    assert promoted.scope == "long_term"
    assert len(await memory.entries("agt_1", scope="working")) == 1


@pytest.mark.asyncio
async def test_context_block_renders_both_scopes(store):
    memory = MemoryService(store)
    await memory.remember("agt_1", "Tides follow the moon.")
    await memory.remember("agt_1", "Currently drafting a tide page.", scope="working")

    block = await memory.context_block("agt_1", "tides")
    assert "Tides follow the moon." in block
    assert "Currently drafting a tide page." in block
