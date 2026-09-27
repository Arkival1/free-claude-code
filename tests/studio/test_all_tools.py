"""Every Agent Gets Every Tool: the whole toolbox, without work going in circles."""

import httpx
import pytest

from free_claude_code.studio.agents import SEALED_TOOLS, TEAM_PROMPT
from free_claude_code.studio.llm import ToolCall
from free_claude_code.studio.tools import ALL_TOOL_NAMES, MAIN_ONLY_TOOLS, ToolContext
from tests.api.support import create_test_app

TEAM_TOOLS = [name for name in ALL_TOOL_NAMES if name not in MAIN_ONLY_TOOLS]
"""Every tool but the ones only the main AI has."""


async def team(make_studio, replies=("Done.",), **settings):
    studio, model = make_studio(list(replies), STUDIO_ALL_TOOLS=True, **settings)
    await studio.ensure_defaults()
    agents = {agent.name: agent for agent in await studio.agents()}
    return studio, model, agents


def offered(call: dict) -> set[str]:
    return set(call["tools"])


@pytest.mark.asyncio
async def test_every_agent_gets_every_tool(make_studio):
    studio, model, agents = await team(make_studio, STUDIO_AGENT_COMMANDS="ask")
    for name in ("Builder", "Researcher", "Helper", "Tester"):
        chat = await studio.create_chat(agent_id=agents[name].id)
        await studio.send(chat.id, "hello")
        assert offered(model.calls[-1]) == set(TEAM_TOOLS), name
        assert TEAM_PROMPT in str(model.calls[-1]["system"])

    await studio.main_say("hello", background=False)
    assert offered(model.calls[-1]) == set(ALL_TOOL_NAMES), "Jarvis too"
    assert TEAM_PROMPT not in str(model.calls[-1]["system"])


@pytest.mark.asyncio
async def test_the_guide_keeps_its_few_tools(make_studio):
    studio, _, agents = await team(make_studio)
    guide = agents["Guide"]
    toolbox = studio._toolbox()
    assert await studio.tools_in_use(guide) == guide.tools
    assert toolbox.granted(guide.tools, role="guide") == guide.tools
    assert not toolbox.delegation_allowed("guide")
    assert "ask_agent" not in guide.tools


@pytest.mark.asyncio
async def test_commands_still_need_the_setting(make_studio):
    studio, model, agents = await team(make_studio, STUDIO_AGENT_COMMANDS="off")
    chat = await studio.create_chat(agent_id=agents["Builder"].id)
    await studio.send(chat.id, "hello")
    assert "run_command" not in offered(model.calls[-1])
    assert "write_file" in offered(model.calls[-1])


@pytest.mark.asyncio
async def test_server_agents_still_get_no_memory_tools(make_studio):
    studio, model, agents = await team(
        make_studio,
        STUDIO_PRIVATE_MEMORY=True,
        STUDIO_MAIN_AGENT_MODEL="local/jarvis-8b",
    )
    builder = agents["Builder"]
    assert await studio.is_private_from(builder)
    chat = await studio.create_chat(agent_id=builder.id)
    await studio.send(chat.id, "hello")
    assert not offered(model.calls[-1]) & SEALED_TOOLS
    assert {"weather", "calculate", "ask_agent"} <= offered(model.calls[-1])
    assert not set(await studio.tools_in_use(builder)) & SEALED_TOOLS


@pytest.mark.asyncio
async def test_turned_off_each_agent_keeps_its_own_tools(make_studio):
    studio, model = make_studio(["Done."], STUDIO_ALL_TOOLS=False)
    await studio.ensure_defaults()
    researcher = next(a for a in await studio.agents() if a.name == "Researcher")
    chat = await studio.create_chat(agent_id=researcher.id)
    await studio.send(chat.id, "hello")
    assert "ask_agent" not in offered(model.calls[-1])
    assert "weather" not in offered(model.calls[-1])
    assert await studio.tools_in_use(researcher) == researcher.tools


@pytest.mark.asyncio
async def test_agents_hand_parts_on_but_never_in_a_circle(make_studio):
    studio, _, agents = await team(make_studio, replies=("Found it.",))
    builder, researcher = agents["Builder"], agents["Researcher"]
    helper, tester = agents["Helper"], agents["Tester"]
    toolbox = studio._toolbox()

    async def ask(who, chat_id: str, worker: str):
        return await toolbox.run(
            ToolCall(
                id="c1", name="ask_agent", arguments={"agent": worker, "task": "look"}
            ),
            ToolContext(
                agent_id=who.id,
                chat_id=chat_id,
                agent_name=who.name,
                agent_role=who.role,
                can_delegate=True,
            ),
        )

    mine = await studio.create_chat(agent_id=builder.id)
    handed = await ask(builder, mine.id, "Researcher")
    assert not handed.failed and "Researcher succeeded" in handed.text

    job = await studio.create_chat(
        agent_id=researcher.id, kind="agent", parent_chat_id=mine.id
    )
    back = await ask(researcher, job.id, "Builder")
    assert back.failed and "don't hand it back" in back.text
    onward = await ask(researcher, job.id, "Helper")
    assert not onward.failed

    deeper = await studio.create_chat(
        agent_id=helper.id, kind="agent", parent_chat_id=job.id
    )
    too_far = await ask(helper, deeper.id, "Tester")
    assert too_far.failed and "handed down twice" in too_far.text

    room = await studio.create_room(member_ids=[builder.id, tester.id])
    in_room = await ask(builder, room.id, "Tester")
    assert in_room.failed and "@Name" in in_room.text


@pytest.mark.asyncio
async def test_the_agent_page_shows_every_tool(make_studio):
    studio, _, _ = await team(make_studio)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            listed = {
                agent["name"]: agent
                for agent in (await client.get("/studio/api/agents")).json()["agents"]
            }
            assert listed["Builder"]["all_tools"] is True
            assert set(listed["Builder"]["tools_in_use"]) == set(TEAM_TOOLS)
            assert listed["Guide"]["all_tools"] is False
            options = (await client.get("/studio/api/agent-options")).json()
            assert options["all_tools"] is True
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
