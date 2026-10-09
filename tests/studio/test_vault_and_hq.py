"""6.60: the repo vault (outside repos survive their deletion), pictures for
vision models, and the pixel HQ of the whole team."""

import json
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio.extensions import ExtensionError, ExtensionLibrary
from free_claude_code.studio.hq import STATIONS, station_for
from free_claude_code.studio.llm import (
    ChatMessage,
    _anthropic_messages,
    _openai_messages,
    _text_protocol_messages,
)
from free_claude_code.studio.vault import RepoVault, VaultError
from tests.api.support import create_test_app
from tests.studio.test_extensions import repo_zip

README = {
    "README.md": "# Tidy CSS\nTips for tidy CSS.",
    "skills/tidy/SKILL.md": "---\nname: tidy\ndescription: Tidy CSS.\n---\nKeep it tidy.",
}


def flaky_github(files: dict[str, str], state: dict[str, bool]) -> httpx.MockTransport:
    """GitHub that has the repo until state['gone'] is set."""

    def answer(request: httpx.Request) -> httpx.Response:
        if state.get("gone"):
            return httpx.Response(404)
        return httpx.Response(200, content=repo_zip(files))

    return httpx.MockTransport(answer)


# ------------------------------------------------------------ the vault


@pytest.mark.asyncio
async def test_the_vault_keeps_exact_copies_once(tmp_path: Path):
    vault = RepoVault(tmp_path / "vault")
    first = await vault.keep(
        owner="trycua",
        repo="cua",
        kind="release",
        name="driver.zip",
        data=b"abc",
        url="https://x/driver.zip",
        ref="v1",
    )
    again = await vault.keep(
        owner="trycua",
        repo="cua",
        kind="release",
        name="driver.zip",
        data=b"abc",
        url="https://x/driver.zip",
        ref="v1",
    )
    assert again.id == first.id, "the same bytes are kept once"
    assert (
        first.sha256
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert await vault.read(first) == b"abc"
    newer = await vault.keep(
        owner="trycua",
        repo="cua",
        kind="release",
        name="driver.zip",
        data=b"abcd",
        url="https://x/driver.zip",
    )
    found = await vault.latest("TryCua", "CUA", kind="release", name="driver.zip")
    assert found is not None and found.id == newer.id
    # A damaged copy is never used.
    vault.path(newer).write_bytes(b"tampered")
    found = await vault.latest("trycua", "cua", kind="release", name="driver.zip")
    assert found is not None and found.id == first.id
    with pytest.raises(VaultError, match="damaged"):
        await vault.read(newer)
    assert await vault.remove(newer.id)
    assert not vault.path(newer).exists()
    assert [item.id for item in await vault.items()] == [first.id]
    assert (
        json.loads((tmp_path / "vault" / "vault.json").read_text())[0]["sha256"]
        == first.sha256
    )


@pytest.mark.asyncio
async def test_a_repo_deleted_from_github_still_installs_from_the_vault(tmp_path: Path):
    state: dict[str, bool] = {}
    vault = RepoVault(tmp_path / "vault")
    library = ExtensionLibrary(
        tmp_path / "ext", transport=flaky_github(README, state), vault=vault
    )
    added = await library.add_github("https://github.com/owner/tidy")
    assert added.vaulted == ""
    kept = await vault.items()
    assert [(k.full_name, k.kind, k.name) for k in kept] == [
        ("owner/tidy", "source", "tidy-HEAD.zip")
    ]
    await library.remove(added.id)

    state["gone"] = True
    again = await library.add_github("owner/tidy")
    assert again.vaulted == kept[0].id
    assert [s.name for s in again.skills] == ["tidy"]
    # A repo that was never kept still says it's gone.
    with pytest.raises(ExtensionError, match="no public repo"):
        await library.add_github("owner/never-seen")


@pytest.mark.asyncio
async def test_the_vault_through_the_routes(make_studio):
    studio, _ = make_studio([])
    state: dict[str, bool] = {}
    studio._extensions._transport = flaky_github(README, state)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        added = await client.post("/studio/api/extensions", json={"url": "owner/tidy"})
        assert added.status_code == 200, added.text
        listing = (await client.get("/studio/api/vault")).json()
        assert listing["bytes"] > 0
        item = listing["items"][0]
        assert item["full_name"] == "owner/tidy" and item["kind"] == "source"
        download = await client.get(item["file_url"])
        assert download.status_code == 200 and download.content[:2] == b"PK"
        state["gone"] = True
        restored = await client.post(f"/studio/api/vault/{item['id']}/restore")
        assert restored.status_code == 200, restored.text
        assert restored.json()["vaulted"] == item["id"]
        gone = await client.delete(f"/studio/api/vault/{item['id']}")
        assert gone.json() == {"removed": True}
        missing = await client.get(f"/studio/api/vault/{item['id']}/file")
        assert missing.status_code == 404


def test_the_cua_copy_is_vendored_with_its_licence_and_checksums():
    root = Path(__file__).resolve().parents[2] / "vendor" / "cua"
    assert "MIT License" in (root / "LICENSE.md").read_text()
    sums = (root / "SHA256SUMS").read_text()
    assert "cua-driver-rs-0.34.0-windows-x86_64.zip" in sums
    import hashlib

    for line in sums.splitlines():
        digest, name = line.split()
        path = root / name if (root / name).exists() else root / "source" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name


# ------------------------------------------------------------ pictures


def test_pictures_reach_every_kind_of_model():
    url = "data:image/jpeg;base64,QUJD"
    messages = [
        ChatMessage.user("What is on screen?", (url,)),
        ChatMessage.user("And now?"),
    ]
    local = _text_protocol_messages(messages)
    assert len(local) == 1
    parts = local[0]["content"]
    assert isinstance(parts, list)
    assert parts[0] == {"type": "image_url", "image_url": {"url": url}}
    assert [p["text"] for p in parts[1:] if isinstance(p, dict)] == [
        "What is on screen?",
        "And now?",
    ]
    blocks = _anthropic_messages(messages)[0]["content"]
    assert isinstance(blocks, list) and blocks[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"},
    }
    openai = _openai_messages(messages)
    assert isinstance(openai[0]["content"], list) and openai[1]["content"] == "And now?"
    assert _text_protocol_messages([ChatMessage.user("plain")])[0]["content"] == "plain"


# ------------------------------------------------------------ the HQ


def test_agents_go_to_the_station_of_their_tool():
    assert station_for("researcher", "web_search", busy=True) == "library"
    assert station_for("builder", "run_command", busy=True) == "testbench"
    assert station_for("coder", "", busy=True) == "workshop"
    assert station_for("farm", "farm", busy=True) == "studio"
    assert station_for("tester", "test_code", busy=False) == "mailroom"
    assert station_for("coder", "", busy=False) == "mailroom"
    assert station_for("helper", "", busy=False) == "lounge"
    assert station_for("main", "", busy=False) == "desk"
    assert station_for("main", "remember", busy=True) == "archive"
    ids = [station.id for station in STATIONS]
    assert len(ids) == len(set(ids)) == 13
    assert {
        "desk",
        "approvals",
        "servers",
        "lounge",
        "library",
        "workshop",
        "testbench",
    } <= set(ids)


@pytest.mark.asyncio
async def test_the_hq_shows_who_is_where_and_you_can_talk_to_them(make_studio):
    studio, _ = make_studio(["On it: I'll look that up."])
    await studio.ensure_defaults()
    agents = {agent.name: agent for agent in await studio.agents()}
    researcher = agents["Researcher"]
    chat = await studio.create_chat(agent_id=researcher.id, title="Work")
    await studio._store.append_message(
        chat_id=chat.id,
        role="tool",
        text="Found 12 sources",
        author="web_search",
        data={"tool": "web_search"},
    )
    studio._agent_busy[researcher.id] = 1
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        hq = (await client.get("/studio/api/hq")).json()
        people = {person["name"]: person for person in hq["agents"]}
        assert people["Researcher"]["station"] == "library"
        assert (
            people["Researcher"]["busy"]
            and people["Researcher"]["tool"] == "web_search"
        )
        assert people["Builder"]["station"] == "lounge"
        assert people["Coder"]["station"] == "mailroom"
        assert people["Tester"]["station"] == "mailroom"
        main = next(person for person in hq["agents"] if person["main"])
        assert main["station"] == "desk"
        library = next(
            station for station in hq["stations"] if station["id"] == "library"
        )
        assert library["count"] == 1 and library["name"] == "Research library"
        assert (
            hq["feed"][0]["tool"] == "web_search"
            and hq["feed"][0]["agent"] == "Researcher"
        )

        studio._agent_busy.clear()
        said = await client.post(
            f"/studio/api/hq/agents/{agents['Helper'].id}/say",
            json={"text": "What's next?"},
        )
        assert said.status_code == 202, said.text
        for task in list(studio._tasks):
            await task
        messages = await studio.transcript(said.json()["chat_id"])
        assert [m.text for m in messages if m.role == "user"] == ["What's next?"]
        assert any("look that up" in m.text for m in messages if m.role == "assistant")
        empty = await client.post(
            f"/studio/api/hq/agents/{agents['Helper'].id}/say", json={"text": "  "}
        )
        assert empty.status_code == 400
        stopped = await client.post(
            f"/studio/api/hq/agents/{agents['Builder'].id}/stop"
        )
        assert stopped.json() == {"stopped": 0}


@pytest.mark.asyncio
async def test_a_team_made_before_an_update_gets_its_new_agents(make_studio):
    """The Coder and the Tester came in an update: a team made before it
    gets them in the HQ (in the mailroom), without being made again."""
    from free_claude_code.studio.models import Agent

    studio, _ = make_studio([])
    try:
        await studio.ensure_defaults()
        for agent in await studio.agents():
            if agent.name in {"Coder", "Tester"}:
                # As on a PC set up before they existed.
                await studio._store.delete(Agent, agent.id)
        assert {"Coder", "Tester"}.isdisjoint(a.name for a in await studio.agents())

        view = await studio.hq()
        where = {a["name"]: a["station"] for a in view["agents"]}
        assert where["Coder"] == "mailroom" and where["Tester"] == "mailroom"
        names = [a.name for a in await studio.agents()]
        assert names.count("Coder") == 1 and names.count("Tester") == 1
    finally:
        await studio.shutdown()


@pytest.mark.asyncio
async def test_a_starter_agent_the_user_deletes_stays_deleted(make_studio):
    studio, _ = make_studio([])
    try:
        await studio.ensure_defaults()
        tester = next(a for a in await studio.agents() if a.name == "Tester")
        await studio.delete_agent(tester.id)
        await studio.ensure_defaults()
        view = await studio.hq()
        assert "Tester" not in {a["name"] for a in view["agents"]}
        assert "Coder" in {a["name"] for a in view["agents"]}
    finally:
        await studio.shutdown()
