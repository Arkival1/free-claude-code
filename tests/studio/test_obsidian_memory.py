"""Agent memory lives in Obsidian as linked notes, and edits flow back."""

from pathlib import Path

import pytest

from free_claude_code.studio.models import MemoryEntry


async def seeded(make_studio, tmp_path: Path, **settings):
    vault = tmp_path / "vault"
    vault.mkdir()
    studio, _model = make_studio([], STUDIO_OBSIDIAN_VAULT=str(vault), **settings)
    agent = await studio.create_agent(name="Scout", model="local/tiny", tools=[])
    kept = await studio.remember(agent.id, "Tides follow the moon.")
    note = await studio.remember(agent.id, "Drafting a tide page.", scope="working")
    assert kept is not None and note is not None
    return studio, agent, kept, note, vault / "FCC Studio" / "Memory"


@pytest.mark.asyncio
async def test_memory_is_mirrored_as_a_linked_structure(make_studio, tmp_path):
    studio, _agent, kept, _note, root = await seeded(make_studio, tmp_path)

    result = await studio.sync_memory_structure()

    assert result["agents"] == 1
    hub = root / "Scout" / "Scout.md"
    assert hub.is_file()
    hub_text = hub.read_text(encoding="utf-8")
    assert "## Working memory" in hub_text and "## Long-term memory" in hub_text
    assert "[[FCC Studio/Memory/Scout/Long-term memory/" in hub_text

    long_term = list((root / "Scout" / "Long-term memory").glob("*.md"))
    working = list((root / "Scout" / "Working memory").glob("*.md"))
    assert len(long_term) == 1 and len(working) == 1
    body = long_term[0].read_text(encoding="utf-8")
    assert f"fcc_memory_id: {kept.id}" in body
    assert "Tides follow the moon." in body
    assert "Belongs to [[FCC Studio/Memory/Scout/Scout|Scout]]" in body

    index = (root / "Memory index.md").read_text(encoding="utf-8")
    assert "Scout" in index and "1 long-term, 1 working" in index


@pytest.mark.asyncio
async def test_edits_made_in_obsidian_come_back(make_studio, tmp_path):
    studio, _agent, kept, _note, root = await seeded(make_studio, tmp_path)
    await studio.sync_memory_structure()
    path = next((root / "Scout" / "Long-term memory").glob("*.md"))
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Tides follow the moon.", "Tides follow the moon and the sun."
        ),
        encoding="utf-8",
    )

    assert await studio.pull_memory_edits() == 1
    updated = await studio.store.require(MemoryEntry, kept.id)
    assert updated.text == "Tides follow the moon and the sun."


@pytest.mark.asyncio
async def test_moving_a_note_between_folders_changes_its_scope(make_studio, tmp_path):
    studio, _agent, _kept, note, root = await seeded(make_studio, tmp_path)
    await studio.sync_memory_structure()
    source = next((root / "Scout" / "Working memory").glob("*.md"))
    target = root / "Scout" / "Long-term memory" / source.name
    source.rename(target)

    result = await studio.sync_memory_structure()

    assert result["pulled"] == 1
    assert (await studio.store.require(MemoryEntry, note.id)).scope == "long_term"
    assert len(list((root / "Scout" / "Long-term memory").glob("*.md"))) == 2
    assert not (root / "Scout" / "Working memory").exists()


@pytest.mark.asyncio
async def test_forgotten_memories_are_pruned_but_user_notes_are_kept(
    make_studio, tmp_path
):
    studio, _agent, kept, _note, root = await seeded(make_studio, tmp_path)
    await studio.sync_memory_structure()
    mine = root / "Scout" / "my own thoughts.md"
    mine.write_text("# Not from Studio\n", encoding="utf-8")

    await studio.forget(kept.id)
    result = await studio.sync_memory_structure()

    assert result["removed"] == 1
    assert not list((root / "Scout").glob("Long-term memory/*.md"))
    assert mine.is_file()


@pytest.mark.asyncio
async def test_auto_sync_mirrors_after_agents_write(make_studio, tmp_path):
    studio, agent, _kept, _note, root = await seeded(
        make_studio, tmp_path, STUDIO_OBSIDIAN_MEMORY_SYNC=True
    )

    await studio.remember(agent.id, "Metric units, always.")

    notes = list((root / "Scout" / "Long-term memory").glob("*.md"))
    assert len(notes) == 2


@pytest.mark.asyncio
async def test_without_a_vault_sync_reports_clearly(make_studio):
    studio, _ = make_studio([])
    with pytest.raises(Exception, match="No Obsidian vault"):
        await studio.sync_memory_structure()


@pytest.mark.asyncio
async def test_an_edit_made_mid_sync_is_never_overwritten(make_studio, tmp_path):
    studio, agent, kept, _note, root = await seeded(make_studio, tmp_path)
    await studio.sync_memory_structure()
    path = next((root / "Scout" / "Long-term memory").glob("*.md"))
    edited = path.read_text(encoding="utf-8").replace("the moon", "the Moon, per me")
    path.write_text(edited, encoding="utf-8")

    # A push that races ahead of the pull must leave the user's words alone...
    entries = {agent.id: list(await studio.memories(agent.id))}
    await studio._vault().mirror_memory([agent], entries)
    assert path.read_text(encoding="utf-8") == edited

    # ...and the next full sync brings them into Studio.
    await studio.sync_memory_structure()
    assert (await studio.store.require(MemoryEntry, kept.id)).text == (
        "Tides follow the Moon, per me."
    )


@pytest.mark.asyncio
async def test_team_memory_gets_its_own_hub_and_edits_come_back(make_studio, tmp_path):
    studio, _agent, _kept, _note, root = await seeded(make_studio, tmp_path)
    shared = await studio.remember("shared", "Ship on Fridays.")
    assert shared is not None

    result = await studio.sync_memory_structure()

    assert result["agents"] == 2
    hub = root / "Team memory" / "Team memory.md"
    assert hub.is_file()
    path = next((root / "Team memory" / "Long-term memory").glob("*.md"))
    assert "Ship on Fridays." in path.read_text(encoding="utf-8")
    path.write_text(
        path.read_text(encoding="utf-8").replace("Fridays", "Thursdays"),
        encoding="utf-8",
    )
    assert await studio.pull_memory_edits() == 1
    updated = await studio.store.require(MemoryEntry, shared.id)
    assert updated.text == "Ship on Thursdays."
