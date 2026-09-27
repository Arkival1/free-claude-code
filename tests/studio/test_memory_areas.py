"""Server AIs keep their own memory area; Jarvis controls every agent."""

import httpx
import pytest

from free_claude_code.studio.llm import LLMReply, ToolCall
from free_claude_code.studio.memory import SHARED_MEMORY_ID, server_area
from free_claude_code.studio.models import MemoryEntry
from free_claude_code.studio.tools import (
    ALL_TOOL_NAMES,
    MAIN_ONLY_TOOLS,
    ToolContext,
    tool_tokens,
)
from tests.api.support import create_test_app

from .conftest import tool_reply

SECRET = "The user's dog is called Biscuit."


def answer(system: str, prompt: str):
    if "running notes" in system:
        return LLMReply(text="Goal:\n- Chat")
    if "your briefing is all it gets" in system:
        return LLMReply(text="Build the page.")
    return LLMReply(text="Done.")


async def team(make_studio, replies=answer, **settings):
    studio, model = make_studio(
        replies,
        **{
            "STUDIO_PRIVATE_MEMORY": True,
            "STUDIO_ALL_TOOLS": True,
            "STUDIO_MAIN_AGENT_MODEL": "local/jarvis-8b",
            **settings,
        },
    )
    await studio.ensure_defaults()
    await studio.remember(SHARED_MEMORY_ID, SECRET)
    agents = {agent.name: agent for agent in await studio.agents()}
    return studio, model, agents


async def jarvis_does(studio, **arguments):
    main = await studio.main_agent()
    chat = await studio.main_chat()
    return await studio._assistant_tool(
        ToolCall(id="m1", name="manage_agent", arguments=arguments),
        ToolContext(
            agent_id=main.id,
            chat_id=chat.id,
            agent_name=main.name,
            agent_role=main.role,
        ),
    )


@pytest.mark.asyncio
async def test_a_server_agent_keeps_its_own_memory_area(make_studio):
    replies = iter(
        [
            tool_reply("remember", {"text": "The bakery site uses a teal header."}),
            LLMReply(text="Saved."),
            tool_reply("recall", {"query": "bakery header dog"}),
            LLMReply(text="Teal."),
        ]
    )

    def respond(system: str, prompt: str):
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Chat")
        return next(replies)

    studio, model, agents = await team(make_studio, respond)
    builder = agents["Builder"]
    # Memories it had while it ran on this PC stay out of reach too.
    await studio.remember(builder.id, "The user's bank is Northwind.")
    chat = await studio.create_chat(agent_id=builder.id)

    await studio.send(chat.id, "remember the header colour")
    await studio.send(chat.id, "what colour is the bakery header?")

    area = await studio.memories(server_area(builder.id))
    assert "The bakery site uses a teal header." in [e.text for e in area]
    said = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert "your own memory area" in said[0].text
    assert "teal header" in said[1].text
    everything = "\n".join(
        str(call["system"]) + str(call["messages"]) for call in model.calls
    )
    assert "Biscuit" not in everything and "Northwind" not in everything
    assert "teal header" in str(model.calls[-1]["messages"]), "its note rides along"
    shared = await studio.memories(SHARED_MEMORY_ID)
    assert "teal" not in " ".join(e.text for e in shared)


@pytest.mark.asyncio
async def test_the_team_never_reads_a_server_area(make_studio):
    studio, _, agents = await team(make_studio)
    builder = agents["Builder"]
    await studio.remember(server_area(builder.id), "Scratch idea: purple buttons.")
    memory = studio._memory()
    main = await studio.main_agent()
    assert not await memory.recall(main.id, "purple buttons idea")
    assert await memory.recall(
        server_area(builder.id), "purple buttons idea", own_only=True
    )


@pytest.mark.asyncio
async def test_jarvis_controls_every_agent(make_studio):
    studio, model, agents = await team(make_studio)
    builder = agents["Builder"]

    team_view = await jarvis_does(studio, action="show")
    assert "Builder (builder)" in team_view.text
    assert "server AI, own memory area" in team_view.text
    assert "every tool" in team_view.text

    saved = await jarvis_does(
        studio, action="add_memory", agent="Builder", text="Client prefers teal."
    )
    assert "Builder's own memory area" in saved.text
    assert [e.text for e in await studio.memories(server_area(builder.id))] == [
        "Client prefers teal."
    ]
    one = await jarvis_does(studio, action="show", agent="Builder")
    assert "Client prefers teal." in one.text

    fewer = await jarvis_does(studio, action="every_tool_off", agent="Builder")
    assert "fewer tokens" in fewer.text
    assert not (await studio.agent(builder.id)).all_tools
    chat = await studio.create_chat(agent_id=builder.id)
    await studio.send(chat.id, "hello")
    assert "weather" not in model.calls[-1]["tools"]
    assert "write_file" in model.calls[-1]["tools"]

    await jarvis_does(studio, action="every_tool_on", agent="Builder")
    assert (await studio.agent(builder.id)).all_tools

    cleared = await jarvis_does(studio, action="forget", agent="Builder")
    assert cleared.text.startswith("Cleared Builder's own memory area")
    assert not await studio.memories(server_area(builder.id))


@pytest.mark.asyncio
async def test_only_jarvis_manages_the_team(make_studio):
    studio, model, agents = await team(make_studio, STUDIO_PRIVATE_MEMORY=False)
    chat = await studio.create_chat(agent_id=agents["Researcher"].id)
    await studio.send(chat.id, "hello")
    assert "manage_agent" not in model.calls[-1]["tools"]
    assert "weather" in model.calls[-1]["tools"]

    await studio.main_say("hello", background=False)
    assert "manage_agent" in model.calls[-1]["tools"]


@pytest.mark.asyncio
async def test_each_agent_can_be_chosen_for_every_tool(make_studio):
    studio, model, agents = await team(make_studio, STUDIO_PRIVATE_MEMORY=False)
    await studio.set_every_tool(agents["Builder"].id, False)

    builder = await studio.agent(agents["Builder"].id)
    chat = await studio.create_chat(agent_id=builder.id)
    await studio.send(chat.id, "hello")
    assert set(model.calls[-1]["tools"]) <= {*builder.tools, "finish"}

    chat = await studio.create_chat(agent_id=agents["Helper"].id)
    await studio.send(chat.id, "hello")
    assert set(model.calls[-1]["tools"]) == {
        name
        for name in ALL_TOOL_NAMES
        if name not in MAIN_ONLY_TOOLS and name != "run_command"
    }, "run_command waits for Agent Commands"
    with pytest.raises(Exception, match="Guide keeps its few tools"):
        await studio.set_every_tool(agents["Guide"].id, True)


@pytest.mark.asyncio
async def test_the_master_switch_still_turns_it_all_off(make_studio):
    studio, model, agents = await team(
        make_studio, STUDIO_ALL_TOOLS=False, STUDIO_PRIVATE_MEMORY=False
    )
    helper = agents["Helper"]
    assert helper.all_tools and not studio.has_every_tool(helper)
    chat = await studio.create_chat(agent_id=helper.id)
    await studio.send(chat.id, "hello")
    assert set(model.calls[-1]["tools"]) <= {*helper.tools, "finish"}


@pytest.mark.asyncio
async def test_deleting_an_agent_clears_its_memory_area(make_studio):
    studio, _, agents = await team(make_studio)
    builder = agents["Builder"]
    await studio.remember(server_area(builder.id), "A note of its own.")
    done = await studio.delete_agent(builder.id)
    assert done["memories"] >= 1
    assert not await studio._store.find(
        MemoryEntry, where={"agent_id": server_area(builder.id)}
    )


@pytest.mark.asyncio
async def test_choosing_tools_and_memory_areas_through_the_app(make_studio):
    studio, _, agents = await team(make_studio)
    builder = agents["Builder"]
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:

            async def listed() -> dict:
                rows = (await client.get("/studio/api/agents")).json()["agents"]
                return {row["name"]: row for row in rows}

            before = (await listed())["Builder"]
            assert before["all_tools"] and before["private"]
            assert before["memory_area"] == server_area(builder.id)
            assert before["every_tool_tokens"] == before["tool_tokens"]
            assert before["every_tool_tokens"] < tool_tokens(ALL_TOOL_NAMES), (
                "a server agent never gets the user's memory tools"
            )

            changed = await client.patch(
                f"/studio/api/agents/{builder.id}",
                json={"updates": {"all_tools": False}},
            )
            assert changed.status_code == 200
            after = (await listed())["Builder"]
            assert not after["all_tools"]
            assert after["tool_tokens"] < before["tool_tokens"]
            assert after["own_tool_tokens"] == after["tool_tokens"]

            area = f"/studio/api/memory/{server_area(builder.id)}"
            wrote = await client.post(area, json={"text": "Use teal."})
            assert wrote.status_code == 200
            assert [m["text"] for m in (await client.get(area)).json()["memories"]] == [
                "Use teal."
            ]
            assert (await listed())["Builder"]["memory_area_count"] == 1

            created = await client.post(
                "/studio/api/agents",
                json={"name": "Lean", "role": "helper", "all_tools": False},
            )
            assert created.json()["all_tools"] is False
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_tools_are_chosen_one_by_one(make_studio):
    studio, model, agents = await team(make_studio, STUDIO_PRIVATE_MEMORY=False)
    helper = agents["Helper"]
    await studio.set_every_tool(helper.id, False)

    saved = await studio.update_agent(
        helper.id, {"tools": ["web_search", "weather", "finish", "weather"]}
    )
    assert saved.tools == ("web_search", "weather", "finish")
    no_finish = await studio.update_agent(helper.id, {"tools": ["calculate"]})
    assert no_finish.tools == ("calculate", "finish"), "finish always stays"
    with pytest.raises(Exception, match="Unknown tools: teleport"):
        await studio.update_agent(helper.id, {"tools": ["teleport"]})

    on = await jarvis_does(studio, action="tool_on", agent="Helper", tool="weather")
    assert on.text == "Helper has weather."
    off = await jarvis_does(studio, action="tool_off", agent="Helper", tool="calculate")
    assert off.text == "Helper no longer has calculate."
    assert (await studio.agent(helper.id)).tools == ("weather", "finish")
    with pytest.raises(ValueError, match="Only the main AI has manage_agent"):
        await jarvis_does(studio, action="tool_on", agent="Helper", tool="manage_agent")

    chat = await studio.create_chat(agent_id=helper.id)
    await studio.send(chat.id, "hello")
    # Web Access "all" (the default) adds web search and fetch for everyone.
    assert set(model.calls[-1]["tools"]) == {
        "weather",
        "finish",
        "web_search",
        "web_fetch",
    }
    assert studio.agent_options()["web_for_all"] is True


@pytest.mark.asyncio
async def test_the_app_lists_every_tool_with_its_cost(make_studio):
    studio, _, _ = await team(make_studio)
    options = studio.agent_options()
    listed = [tool for group in options["tool_groups"] for tool in group["tools"]]
    names = {tool["name"] for tool in listed}
    assert names == set(ALL_TOOL_NAMES) - {"finish"}
    assert all(tool["tokens"] > 0 for tool in listed)
    flags = {tool["name"]: tool for tool in listed}
    assert flags["manage_agent"]["main_only"] and not flags["weather"]["main_only"]
    assert flags["todo"]["private"] and not flags["remember"]["private"]
    assert options["commands_enabled"] is False
