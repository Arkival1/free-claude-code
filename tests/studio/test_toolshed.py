"""6.63: repo agents go to the HQ toolshed for the tools a job needs, and an
agent only ever uses tools it has."""

import pytest

from free_claude_code.core.json_types import JsonObject
from free_claude_code.studio.hq import station_for
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import Agent, StudioFlag
from free_claude_code.studio.service import TOOLSHED_FLAG
from free_claude_code.studio.starter import BUNDLE
from free_claude_code.studio.tools import NOT_IN_THE_SHED, SEALED_TOOLS
from tests.studio.conftest import tool_reply


def scripted(*steps: LLMReply):
    """Replies for the repo agent, in order; everyone else just answers."""
    queue = list(steps)

    def answer(system: str, prompt: str) -> LLMReply:
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Chat")
        if "You inventory design-system debt" in system and queue:
            return queue.pop(0)
        return LLMReply(text="Done.")

    return answer


async def auditor_chat(make_studio, *steps: LLMReply, **settings):
    studio, model = make_studio(
        scripted(*steps),
        **{"STUDIO_PRIVATE_MEMORY": True, "STUDIO_ALL_TOOLS": True, **settings},
    )
    studio._starter_folder = BUNDLE
    await studio.ensure_defaults()
    await studio.ensure_starters()
    extension = next(
        e for e in await studio.extensions() if e.name == "paperclipai/paperclip"
    )
    auditor = await studio.add_extension_agent(extension.id, "token-auditor")
    chat = await studio.create_chat(agent_id=auditor.id)
    return studio, model, auditor, chat


def tool_messages(transcript) -> list:
    return [m for m in transcript if m.role == "tool"]


@pytest.mark.asyncio
async def test_an_agent_cannot_use_a_tool_it_was_not_given(make_studio):
    studio, model, auditor, chat = await auditor_chat(
        make_studio, tool_reply("calculate", {"expression": "6*7"})
    )
    assert "calculate" not in await studio.tools_in_use(auditor)

    await studio.send(chat.id, "work something out")

    assert "calculate" not in model.calls[0]["tools"]
    [refused] = tool_messages(await studio.transcript(chat.id))
    assert refused.data["not_yours"] is True and refused.data["failed"] is True
    assert "isn't one of your tools" in refused.text
    assert "Take it from the toolshed" in refused.text


@pytest.mark.asyncio
async def test_a_repo_agent_takes_what_the_job_needs_from_the_toolshed(make_studio):
    studio, model, auditor, chat = await auditor_chat(
        make_studio,
        tool_reply("toolshed", {"action": "list"}),
        tool_reply(
            "toolshed",
            {"action": "take", "tools": ["calculate", "todo"], "why": "maths"},
        ),
        tool_reply("calculate", {"expression": "13 + 14 + 15"}),
        LLMReply(text="The three sizes add up to 42."),
    )
    assert "toolshed" in await studio.tools_in_use(auditor)

    await studio.send(chat.id, "add up the three spacing sizes")

    listed, took, used = tool_messages(await studio.transcript(chat.id))
    shelf = listed.data["shelf"]
    assert isinstance(shelf, list) and "calculate" in shelf
    # The user's own things, running the team, and memory stay off the shelf.
    assert not set(shelf) & NOT_IN_THE_SHED
    assert not set(shelf) & SEALED_TOOLS
    assert "Took calculate from the toolshed" in took.text
    assert "Not on the shelf: todo" in took.text
    assert took.data["taken"] == ["calculate"]
    assert used.author == "calculate" and "42" in used.text and not used.data["failed"]
    agent_calls = [c for c in model.calls if "debt" in str(c["system"])]
    assert "calculate" not in agent_calls[1]["tools"]
    assert "calculate" in agent_calls[2]["tools"], "in hand from the next step"
    assert "go to the toolshed" in str(agent_calls[0]["system"])
    assert station_for("agent", "toolshed", True) == "toolshed"

    # Taken for that job only: it went back on the shelf.
    await studio.send(chat.id, "hello again")
    assert "calculate" not in model.calls[-1]["tools"]


@pytest.mark.asyncio
async def test_the_toolshed_is_locked_when_every_tool_is_off(make_studio):
    studio, _, _, chat = await auditor_chat(
        make_studio,
        tool_reply("toolshed", {"action": "take", "tools": ["calculate"]}),
        STUDIO_ALL_TOOLS=False,
    )

    await studio.send(chat.id, "work it out")

    [locked] = tool_messages(await studio.transcript(chat.id))
    assert "The toolshed is locked" in locked.text and locked.data["failed"]


@pytest.mark.asyncio
async def test_repo_agents_already_on_the_team_get_the_toolshed(make_studio):
    studio, _, auditor, _ = await auditor_chat(make_studio)
    update: JsonObject = {"tools": [t for t in auditor.tools if t != "toolshed"]}
    await studio.update_agent(auditor.id, update)
    await studio._store.delete(StudioFlag, TOOLSHED_FLAG)
    studio._starters_checked = False

    await studio.ensure_starters()

    fixed = await studio._store.require(Agent, auditor.id)
    assert "toolshed" in fixed.tools and fixed.all_tools is False


@pytest.mark.asyncio
async def test_the_changer_and_subagents_reach_every_tool_through_the_toolshed(
    make_studio,
):
    from free_claude_code.studio.service import SUBAGENT_TOOLSHED_FLAG

    studio, _ = make_studio([], STUDIO_ALL_TOOLS=True)
    changer = await studio._changer_agent()
    assert "toolshed" in changer.tools
    shed = studio._runner()._toolshed(changer, changer.tools, sealed=False)
    assert "skill" in changer.tools and "mcp" in shed.shelf
    # The Changer's project is the copy of FCC: nothing lays a new project there.
    assert not {"start_project", "site_layouts", "godot"} & set(shed.shelf)
    helper = await studio.create_subagent(name="Dev-1", role="developer")
    assert "toolshed" in helper.tools
    helper_shed = studio._runner()._toolshed(helper, helper.tools, sealed=False)
    assert "start_project" in helper_shed.shelf or "start_project" in helper.tools
    assert not set(NOT_IN_THE_SHED) & set(helper_shed.shelf)
    # Subagents made before this release get it once.
    await studio.update_agent(
        helper.id, {"tools": [t for t in helper.tools if t != "toolshed"]}
    )
    await studio._store.delete(StudioFlag, SUBAGENT_TOOLSHED_FLAG)
    await studio.ensure_defaults()
    assert "toolshed" in (await studio._store.require(Agent, helper.id)).tools


@pytest.mark.asyncio
async def test_a_toolshed_the_owner_takes_off_the_changer_stays_off(make_studio):
    studio, _ = make_studio([])
    changer = await studio._changer_agent()
    await studio._store.put(
        changer.model_copy(
            update={"tools": tuple(t for t in changer.tools if t != "toolshed")}
        )
    )
    assert "toolshed" not in (await studio._changer_agent()).tools
