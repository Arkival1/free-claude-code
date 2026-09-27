"""Agents on this PC direct the agents on server AIs; Jarvis keeps his own memory."""

import pytest

from free_claude_code.studio.llm import LLMReply, ToolCall
from free_claude_code.studio.memory import SHARED_MEMORY_ID, server_area
from free_claude_code.studio.tools import ToolContext

from .conftest import tool_reply

LEAD = {"ask_agent", "team_status", "stop_agent", "manage_agent"}
BUILDER = "it already has five linked pages"


def is_builder(system: str) -> bool:
    """The Builder's own turns (Jarvis's roster quotes its prompt too)."""
    return BUILDER in system and "the user's main AI." not in system


def script(steps):
    """Reply to the Builder from a list; everyone else just says Done."""
    queue = iter(steps)

    def respond(system: str, prompt: str):
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Chat")
        if is_builder(system):
            return next(queue, LLMReply(text="Finished."))
        return LLMReply(text="Done: the research is in.")

    return respond


async def team(make_studio, respond=None, **settings):
    studio, model = make_studio(
        respond or script([]),
        **{
            "STUDIO_PRIVATE_MEMORY": True,
            "STUDIO_LOCAL_CONTROL": True,
            "STUDIO_MAIN_AGENT_MODEL": "local/jarvis-8b",
            **settings,
        },
    )
    await studio.ensure_defaults()
    agents = {agent.name: agent for agent in await studio.agents()}
    # The Builder and Tester think on this PC; the rest on a server AI.
    for name in ("Builder", "Tester"):
        await studio.update_agent(agents[name].id, {"model": "local/coder-7b"})
    agents = {agent.name: agent for agent in await studio.agents()}
    return studio, model, agents


def builder_calls(model):
    return [call for call in model.calls if is_builder(str(call["system"]))]


@pytest.mark.asyncio
async def test_a_local_agent_gets_to_direct_the_server_agents(make_studio):
    studio, model, agents = await team(make_studio)
    chat = await studio.create_chat(agent_id=agents["Builder"].id)

    await studio.send(chat.id, "hello")

    call = builder_calls(model)[-1]
    assert set(call["tools"]) >= LEAD
    system = str(call["system"])
    under = system.split("work under you: ")[1].split(".")[0]
    assert under.startswith("Researcher, Helper")
    assert "Tester" not in under and "Jarvis" not in under
    assert "orders from the main AI only" in system

    # A server agent gets no say over anyone.
    research = await studio.create_chat(agent_id=agents["Researcher"].id)
    await studio.send(research.id, "hello")
    assert not LEAD & set(model.calls[-1]["tools"])


@pytest.mark.asyncio
async def test_hand_offs_reach_server_agents_but_not_local_ones(make_studio):
    studio, _, agents = await team(
        make_studio,
        script(
            [
                tool_reply(
                    "ask_agent", {"agent": "Researcher", "task": "Find cafe prices."}
                ),
                tool_reply(
                    "ask_agent", {"agent": "Tester", "task": "Test it."}, call_id="c2"
                ),
                tool_reply("stop_agent", {"agent": "Tester"}, call_id="c3"),
                LLMReply(text="Finished."),
            ]
        ),
    )
    chat = await studio.create_chat(agent_id=agents["Builder"].id)

    await studio.send(chat.id, "build it")

    said = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert "Researcher" in said[0].text and not said[0].data.get("failed")
    assert said[1].data.get("failed") and "only the main AI directs" in said[1].text
    assert "Researcher, Helper" in said[1].text
    assert said[2].data.get("failed") and said[2].data["outside"] == ["Tester"]


@pytest.mark.asyncio
async def test_a_local_agent_manages_only_server_agents(make_studio):
    studio, _, agents = await team(make_studio)
    builder = agents["Builder"]
    chat = await studio.create_chat(agent_id=builder.id)
    context = ToolContext(
        agent_id=builder.id,
        chat_id=chat.id,
        agent_name="Builder",
        agent_role="builder",
        can_delegate=True,
        directs=("Researcher", "Helper"),
    )

    async def manage(**arguments):
        return await studio._toolbox().run(
            ToolCall(id="m", name="manage_agent", arguments=arguments), context
        )

    shown = await manage(action="show")
    assert "Researcher" in shown.text and "Tester" not in shown.text
    note = await manage(
        action="add_memory", agent="Researcher", text="Use metric units."
    )
    assert "Researcher's own memory area" in note.text
    area = await studio.memories(server_area(agents["Researcher"].id))
    assert [entry.author for entry in area] == ["Builder"]
    refused = await manage(action="tool_off", agent="Tester", tool="web_search")
    assert (
        refused.failed and "only the main AI manages agents on this PC" in refused.text
    )


@pytest.mark.asyncio
async def test_switching_models_moves_agents_between_the_groups(make_studio):
    studio, model, agents = await team(make_studio)
    chat = await studio.create_chat(agent_id=agents["Builder"].id)

    # The Researcher moves to this PC: the Builder no longer directs it.
    await studio.update_agent(agents["Researcher"].id, {"model": "local/qwen-7b"})
    await studio.send(chat.id, "hello")
    system = str(builder_calls(model)[-1]["system"])
    under = system.split("work under you: ")[1].split(".")[0]
    assert "Helper" in under and "Researcher" not in under

    # The Builder moves to a server AI: it directs nobody.
    await studio.update_agent(agents["Builder"].id, {"model": "nvidia_nim/test-model"})
    await studio.send(chat.id, "hello again")
    assert not LEAD & set(builder_calls(model)[-1]["tools"])


@pytest.mark.asyncio
async def test_the_setting_turns_it_off(make_studio):
    studio, model, agents = await team(make_studio, STUDIO_LOCAL_CONTROL=False)
    chat = await studio.create_chat(agent_id=agents["Builder"].id)
    await studio.send(chat.id, "hello")
    assert not LEAD & set(builder_calls(model)[-1]["tools"])


# ------------------------------------------------------------ Jarvis's memory


def jarvis_context(main, chat_id):
    return ToolContext(
        agent_id=main.id,
        chat_id=chat_id,
        agent_name=main.name,
        agent_role=main.role,
        main_memory=True,
    )


@pytest.mark.asyncio
async def test_jarvis_keeps_his_own_memory_and_reads_everyone(make_studio):
    studio, _, agents = await team(make_studio, STUDIO_SHARED_MEMORY=True)
    main = await studio.main_agent()
    chat = await studio.main_chat()
    toolbox = studio._toolbox()
    context = jarvis_context(main, chat.id)

    async def run(name, **arguments):
        return await toolbox.run(
            ToolCall(id="j", name=name, arguments=arguments), context
        )

    own = await run("remember", text="The user likes short answers.")
    assert "your memory" in own.text and not own.data["shared"]
    shared = await run("remember", text="The cafe opens at 7am.", share=True)
    assert shared.data["shared"]
    assert [e.text for e in await studio.memories(main.id)] == [
        "The user likes short answers."
    ]
    assert "The cafe opens at 7am." in [
        e.text for e in await studio.memories(SHARED_MEMORY_ID)
    ]

    # The Builder can't read Jarvis's own memory, only the team's.
    memory = studio._memory()
    builder = agents["Builder"]
    assert not await memory.recall(builder.id, "user likes short answers")
    assert await memory.recall(builder.id, "cafe opens 7am")

    # Jarvis reads every agent's memory, and says whose it is.
    await studio.remember(builder.id, "The cafe logo is a crescent moon.")
    await studio.remember(
        server_area(agents["Researcher"].id), "Cafe competitor prices noted."
    )
    found = await run("recall", query="cafe logo moon competitor prices")
    assert "(Builder) The cafe logo is a crescent moon." in found.text
    assert "(Researcher's server area) Cafe competitor prices noted." in found.text
    block = await memory.context_block(main.id, "cafe logo moon", everyone=True)
    assert "What your agents know" in block and "(Builder)" in block


@pytest.mark.asyncio
async def test_jarvis_sees_the_memory_prompt_and_his_tools(make_studio):
    studio, model, _ = await team(
        make_studio, STUDIO_SHARED_MEMORY=True, STUDIO_MAIN_OWN_MEMORY=True
    )
    chat = await studio.main_chat()
    await studio.send(chat.id, "hello")
    call = next(c for c in reversed(model.calls) if "main AI" in str(c["system"]))
    assert "Your memory is your own" in str(call["system"])


@pytest.mark.asyncio
async def test_with_the_setting_off_jarvis_shares_as_before(make_studio):
    studio, _, _ = await team(make_studio, STUDIO_SHARED_MEMORY=True)
    main = await studio.main_agent()
    chat = await studio.main_chat()
    context = ToolContext(
        agent_id=main.id, chat_id=chat.id, agent_name=main.name, agent_role=main.role
    )
    saved = await studio._toolbox().run(
        ToolCall(id="j", name="remember", arguments={"text": "Team fact."}), context
    )
    assert saved.data["shared"]


@pytest.mark.asyncio
async def test_the_app_shows_who_directs_whom(make_studio):
    studio, _, agents = await team(make_studio, STUDIO_MAIN_OWN_MEMORY=True)
    views = {agent.name: await studio.agent_view(agent) for agent in agents.values()}
    assert views["Jarvis"]["command"] == "Directs every agent"
    assert views["Jarvis"]["own_memory"] is True
    assert views["Builder"]["command"].startswith("Directs the agents on server AIs")
    assert views["Researcher"]["command"] == (
        "Takes jobs from the main AI and the agents on this PC"
    )
    assert views["Researcher"]["private"] and not views["Builder"]["private"]
