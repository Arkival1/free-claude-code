"""The Orb edition: Jarvis alone with two advisers, on this PC's model, with
no plugins, GitHub, connectors or other agents."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from free_claude_code.config import edition
from free_claude_code.studio.llm import LOCAL_MODEL_PREFIX, ToolCall
from free_claude_code.studio.orb import ORB_TOOLS
from free_claude_code.studio.pc_control import ADVISER_TOOLS, PC_TOOLS
from free_claude_code.studio.playground import ADVISER_PROMPT, REFLECT_PROMPT
from free_claude_code.studio.tools import ToolContext

from .conftest import tool_reply
from .test_pc_control import pc_home, turns

LOCAL = f"{LOCAL_MODEL_PREFIX}qwen3.5-9b"


def respond(system: str, prompt: str):
    if system == REFLECT_PROMPT:
        return "{}"
    if ADVISER_PROMPT in system:
        return tool_reply("finish", {"summary": "Add a double jump."})
    return tool_reply("finish", {"summary": "Done."})


def plain(value: object) -> Any:
    """A route's JSON as plain Python, for reading in asserts."""
    return json.loads(json.dumps(value))


async def orb_studio(make_studio, tmp_path: Path):
    studio, fake = make_studio(
        respond,
        STUDIO_EDITION="orb",
        STUDIO_MAIN_AGENT_MODEL=LOCAL,
        # Turns wait a few seconds at each model switch; not what's tested.
        STUDIO_LOCAL_MODEL_TURNS=False,
    )
    await studio.ensure_defaults()
    studio.pc_control.set_roots([str(pc_home(tmp_path))])
    studio.pc_control.set_level("full")
    return studio, fake


def test_the_orb_download_is_marked_orb(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(edition, "_MARK", tmp_path / "EDITION")
    assert edition.packaged_edition() == "full"
    (tmp_path / "EDITION").write_text("orb\n")
    assert edition.packaged_edition() == "orb"
    (tmp_path / "EDITION").write_text("something else")
    assert edition.packaged_edition() == "full"


def test_the_orb_has_no_plugin_github_or_team_tools() -> None:
    for tool in (
        "mcp",
        "aider",
        "fcc_changer",
        "ask_agent",
        "team_task",
        "team_plan",
        "manage_agent",
        "code_and_test",
        "farm",
        "site_layouts",
    ):
        assert tool not in ORB_TOOLS, tool
    assert ADVISER_TOOLS <= ORB_TOOLS
    assert not PC_TOOLS & ORB_TOOLS


@pytest.mark.asyncio
async def test_jarvis_talks_with_his_hands_and_only_orb_tools(
    make_studio, tmp_path: Path
) -> None:
    studio, fake = await orb_studio(make_studio, tmp_path)
    assert studio.orb and studio.pc_enabled
    from free_claude_code.api import studio_routes

    state = plain(await studio_routes.orb_state(studio=studio, _=None))
    assert state["edition"] == "orb" and state["pc"]["enabled"] is True
    assert [a["name"] for a in state["advisers"]] == [
        "Idea Adviser",
        "Research Adviser",
    ]
    # Advisers start on Jarvis's model: nothing to swap until the owner says.
    assert {a["model"] for a in state["advisers"]} == {LOCAL}
    reply = await studio_routes.orb_say(
        studio_routes.OrbSayBody(text="hi Jarvis"), studio=studio, _=None
    )
    assert reply["reply"] == "Done."
    offered = set(turns(fake)[-1]["tools"])
    assert offered >= PC_TOOLS
    assert offered - PC_TOOLS <= ORB_TOOLS, offered - PC_TOOLS - ORB_TOOLS
    # The same chat every time.
    again = plain(await studio_routes.orb_state(studio=studio, _=None))
    assert again["chat_id"] == state["chat_id"]


@pytest.mark.asyncio
async def test_advisers_get_their_speciality_and_the_web_only(
    make_studio, tmp_path: Path
) -> None:
    studio, fake = await orb_studio(make_studio, tmp_path)
    state = plain(
        await studio.orb_set_adviser(
            0,
            name="Art Director",
            speciality="Pixel art and colour for 2D games.",
            model=f"{LOCAL_MODEL_PREFIX}qwen3-1.7b",
        )
    )
    first = state["advisers"][0]
    assert first["name"] == "Art Director"
    assert first["model"] == f"{LOCAL_MODEL_PREFIX}qwen3-1.7b"
    job = await studio.orb_ask_advisers("Make a tiny platformer")
    await asyncio.wait_for(studio.wait_for_background(), timeout=30)
    done = await studio.playground_job(job.id)
    assert done.status == "done", done.summary
    assert set(done.advisers) == {a["id"] for a in state["advisers"]}
    advising = [c for c in fake.calls if ADVISER_PROMPT in str(c["system"])]
    assert advising
    assert any("Pixel art and colour" in str(c["system"]) for c in advising)
    for call in advising:
        offered = set(call["tools"]) - {"finish"}
        assert offered <= ADVISER_TOOLS, offered


@pytest.mark.asyncio
async def test_no_starter_repos_and_other_tools_refused(
    make_studio, tmp_path: Path
) -> None:
    studio, _ = await orb_studio(make_studio, tmp_path)
    assert await studio.ensure_starters() == []
    outcome = await studio._toolbox().run(
        ToolCall(id="x", name="ask_agent", arguments={"agent": "Builder"}),
        ToolContext(agent_id="a", chat_id="c", agent_name="Jarvis"),
    )
    assert outcome.failed and "Orb edition" in outcome.text


@pytest.mark.asyncio
async def test_the_full_edition_is_unchanged(make_studio) -> None:
    studio, _ = make_studio(respond)
    assert not studio.orb and not studio.pc_enabled
    assert studio._toolbox().only_tools is None
