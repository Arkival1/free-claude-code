"""Server AIs never see the memory bank; the main AI briefs them instead."""

import pytest

from free_claude_code.studio.agents import SEALED_PROMPT
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.memory import SHARED_MEMORY_ID
from free_claude_code.studio.models import AgentRun

from .conftest import tool_reply

SECRET = "The user's dog is called Biscuit and the bakery colours are teal and gold."
BRIEF = "Build a one-page bakery site in teal and gold. Hand back the file list."


def everything_sent(call: dict) -> str:
    messages = call["messages"]
    said = [m.content for m in messages] if isinstance(messages, list) else []
    return "\n".join([str(call["system"]), *said])


def is_briefing(call: dict) -> bool:
    return "your briefing is all it gets" in str(call["system"])


def is_sealed(call: dict) -> bool:
    return SEALED_PROMPT in str(call["system"])


def answer(system: str, prompt: str):
    if "your briefing is all it gets" in system:
        return LLMReply(text=BRIEF)
    if "running notes" in system:
        return LLMReply(text="Goal:\n- Chat")
    return LLMReply(text="Done.")


async def team(make_studio, replies=answer, **settings):
    studio, model = make_studio(
        replies,
        **{
            "STUDIO_PRIVATE_MEMORY": True,
            "STUDIO_MAIN_AGENT_MODEL": "local/jarvis-8b",
            **settings,
        },
    )
    await studio.ensure_defaults()
    await studio.remember(SHARED_MEMORY_ID, SECRET)
    agents = {agent.name: agent for agent in await studio.agents()}
    return studio, model, agents


@pytest.mark.asyncio
async def test_a_server_agent_never_sees_memory(make_studio):
    studio, model, agents = await team(make_studio)
    builder = agents["Builder"]
    assert await studio.is_private_from(builder)
    chat = await studio.create_chat(agent_id=builder.id)

    await studio.send(chat.id, "what colours does the bakery use?")

    call = model.calls[-1]
    assert is_sealed(call)
    assert call["memory"] == ""
    assert "Biscuit" not in everything_sent(call)
    assert not {"remember", "recall", "knowledge", "conversation"} & set(call["tools"])
    assert "write_file" in call["tools"], "it keeps its working tools"


@pytest.mark.asyncio
async def test_an_agent_on_this_pc_still_uses_memory(make_studio):
    studio, model, agents = await team(make_studio)
    (builder,) = await studio.assign_models(
        {agents["Builder"].id: "local/qwen2.5-coder-7b"}
    )
    assert not await studio.is_private_from(builder)
    chat = await studio.create_chat(agent_id=builder.id)

    await studio.send(chat.id, "what colours does the bakery use?")

    call = model.calls[-1]
    assert not is_sealed(call)
    assert "teal and gold" in str(call["memory"])
    assert "recall" in call["tools"]


@pytest.mark.asyncio
async def test_other_local_runtimes_count_as_this_pc(make_studio):
    studio, _, _ = await team(make_studio)
    assert studio.runs_on_this_pc("local/qwen")
    assert studio.runs_on_this_pc("lmstudio/qwen")
    assert studio.runs_on_this_pc("ollama/llama3")
    assert not studio.runs_on_this_pc("nvidia_nim/test-model")
    assert not studio.runs_on_this_pc("open_router/some-model")


@pytest.mark.asyncio
async def test_a_server_agent_cannot_call_memory_tools_anyway(make_studio):
    replies = iter([tool_reply("recall", {"query": "dog"}), LLMReply(text="ok")])

    def respond(system: str, prompt: str):
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Chat")
        return next(replies)

    studio, _, agents = await team(make_studio, respond)
    chat = await studio.create_chat(agent_id=agents["Builder"].id)

    await studio.send(chat.id, "what is my dog called?")

    (blocked,) = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert "memory stays on their PC" in blocked.text
    assert "Biscuit" not in blocked.text


@pytest.mark.asyncio
async def test_jarvis_briefs_a_server_agent_on_its_job(make_studio):
    studio, model, agents = await team(make_studio)

    await studio.main_say(
        "Have Builder make a landing page for the bakery", background=False
    )
    await studio.wait_for_background()

    chat = await studio.main_chat()
    (briefing,) = [
        m for m in await studio.transcript(chat.id) if m.author == "briefing"
    ]
    assert briefing.text.startswith("Briefing for Builder (a server AI")
    assert BRIEF in briefing.text
    written = next(call for call in model.calls if is_briefing(call))
    assert written["model"] == "jarvis-8b", "Jarvis's own brain on this PC writes it"
    assert "teal and gold" in str(written["prompt"]), "from Jarvis's memory"
    (run,) = await studio.store.find(AgentRun, where={"agent_id": agents["Builder"].id})
    assert run.goal.startswith("The job: make a landing page for the bakery")
    assert f"Briefing from Jarvis:\n{BRIEF}" in run.goal
    builder_calls = [call for call in model.calls if is_sealed(call)]
    assert builder_calls and all(
        "Biscuit" not in everything_sent(call) for call in builder_calls
    )


@pytest.mark.asyncio
async def test_agents_on_this_pc_get_the_job_as_it_is(make_studio):
    studio, model, agents = await team(make_studio)
    await studio.assign_models({agents["Builder"].id: "local/qwen2.5-coder-7b"})

    await studio.main_say(
        "Have Builder make a landing page for the bakery", background=False
    )
    await studio.wait_for_background()

    chat = await studio.main_chat()
    assert not [m for m in await studio.transcript(chat.id) if m.author == "briefing"]
    assert not any(is_briefing(call) for call in model.calls)


@pytest.mark.asyncio
async def test_the_rule_can_be_turned_off(make_studio):
    studio, model, agents = await team(make_studio, STUDIO_PRIVATE_MEMORY=False)
    chat = await studio.create_chat(agent_id=agents["Builder"].id)

    await studio.send(chat.id, "what colours does the bakery use?")

    assert "teal and gold" in str(model.calls[-1]["memory"])


@pytest.mark.asyncio
async def test_the_app_shows_which_agents_are_kept_out(make_studio):
    studio, _, _ = await team(make_studio)

    rows = {row["name"]: row for row in (await studio.team_models())["agents"]}
    assert rows["Builder"]["private"] is True
    assert rows["Jarvis"]["private"] is False
    console = await studio.main_console()
    member = next(m for m in console["team"] if m["name"] == "Builder")
    assert member["private"] is True and member["local"] is False
    roster = await studio._runner().roster(await studio.main_agent())
    assert "Builder (" in roster and "cannot see the user's memory" in roster
