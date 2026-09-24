"""The main AI runs the team, and every agent shares one team memory."""

import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.memory import SHARED_MEMORY_ID, MemoryService
from free_claude_code.studio.models import AgentRun, Chat, SiteProject
from free_claude_code.studio.tools import (
    ASK_AGENT_TOOL,
    MAIN_TOOL_NAMES,
    TEAM_TASK_TOOL,
    tool_specs,
)

from .conftest import tool_reply

TASK = "Build a landing page for the bakery"


def _is_main(system: str) -> bool:
    return "the user's main AI" in system


@pytest.mark.asyncio
async def test_agents_share_what_they_learn(make_studio):
    def respond(system: str, prompt: str):
        if prompt == "learn it":
            return tool_reply(
                "remember", {"text": "The bakery opens at 7am", "tags": ["hours"]}
            )
        if prompt == "keep it quiet":
            return tool_reply(
                "remember", {"text": "My scratch idea about fonts", "private": True}
            )
        if prompt.startswith("Saved to"):
            return LLMReply(text="Noted.")
        return LLMReply(text="ok")

    studio, model = make_studio(respond)
    scout = await studio.create_agent(name="Scout")
    writer = await studio.create_agent(name="Writer")

    chat = await studio.create_chat(agent_id=scout.id)
    await studio.send(chat.id, "learn it")
    await studio.send(chat.id, "keep it quiet")

    shared = await studio.memories(SHARED_MEMORY_ID)
    assert [entry.text for entry in shared] == ["The bakery opens at 7am"]
    assert shared[0].author == "Scout"
    private = [
        entry.text for entry in await studio.memories(scout.id, scope="long_term")
    ]
    assert private == ["My scratch idea about fonts"]

    other = await studio.create_chat(agent_id=writer.id)
    await studio.send(other.id, "When does the bakery open?")
    system = model.calls[-1]["system"]
    assert "What the team knows (shared memory):" in system
    assert "The bakery opens at 7am (from Scout)" in system
    assert "scratch idea" not in system


@pytest.mark.asyncio
async def test_shared_memory_can_be_turned_off(make_studio):
    studio, model = make_studio(
        [tool_reply("remember", {"text": "Blue is the brand color"}), "Noted."],
        STUDIO_SHARED_MEMORY=False,
    )
    scout = await studio.create_agent(name="Scout")
    chat = await studio.create_chat(agent_id=scout.id)

    await studio.send(chat.id, "remember the color")

    assert await studio.memories(SHARED_MEMORY_ID) == ()
    kept = await studio.memories(scout.id, scope="long_term")
    assert [entry.text for entry in kept] == ["Blue is the brand color"]
    remember = next(spec for spec in tool_specs(scout.tools) if spec.name == "remember")
    assert "private" not in str(remember.parameters)
    assert "private" not in str(model.calls[0]["system"])


@pytest.mark.asyncio
async def test_recall_searches_own_and_team_memory(store):
    memory = MemoryService(store, shared=True)
    await memory.remember("agt_a", "Deploy with docker compose up")
    await memory.share("Deploy target is the home server", author="Builder")
    await memory.remember("agt_b", "Deploy secrets live in the vault")

    found = {entry.text for entry in await memory.recall("agt_a", "deploy plan")}

    assert found == {
        "Deploy with docker compose up",
        "Deploy target is the home server",
    }
    alone = MemoryService(store, shared=False)
    assert {entry.text for entry in await alone.recall("agt_a", "deploy")} == {
        "Deploy with docker compose up"
    }
    assert await alone.share("ignored", author="x") is None


@pytest.mark.asyncio
async def test_the_main_ai_is_created_with_the_team(make_studio):
    studio, _ = make_studio(STUDIO_MAIN_AGENT_NAME="Friday")

    created = await studio.ensure_defaults()
    again = await studio.ensure_defaults()

    main = next(agent for agent in created if agent.role == "main")
    assert main.name == "Friday"
    assert main.tools == MAIN_TOOL_NAMES
    assert again == ()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    assert ASK_AGENT_TOOL not in builder.tools
    assert (await studio.main_agent()).id == main.id


@pytest.mark.asyncio
async def test_main_ai_hands_a_build_to_an_agent(make_studio):
    def respond(system: str, prompt: str):
        if _is_main(system):
            if prompt.startswith("Builder succeeded"):
                return LLMReply(text="Done. The bakery page is ready.")
            return tool_reply(
                ASK_AGENT_TOOL,
                {"agent": "@builder", "task": TASK, "project": "Bakery"},
            )
        if prompt == TASK:
            return tool_reply(
                "write_file", {"path": "index.html", "content": "<h1>Bakery</h1>"}
            )
        return tool_reply("finish", {"summary": "Built index.html"})

    studio, model = make_studio(respond)
    await studio.ensure_defaults()

    chat = await studio.main_say("Make the bakery a landing page", background=False)

    transcript = await studio.transcript(chat.id)
    assert transcript[-1].text == "Done. The bakery page is ready."
    handoff = next(message for message in transcript if message.role == "tool")
    assert handoff.author == ASK_AGENT_TOOL
    assert handoff.text.startswith("Builder succeeded after 2 steps: Built index.html")
    assert "Project: Bakery" in handoff.text

    run = await studio.store.require(AgentRun, str(handoff.data["run_id"]))
    assert run.status == "succeeded"
    sub_chat = await studio.store.require(Chat, run.chat_id)
    assert sub_chat.parent_chat_id == chat.id
    site = await studio.store.require(SiteProject, str(run.site_id))
    assert site.name == "Bakery"
    assert site.file_count >= 1
    assert "<h1>Bakery</h1>" in await studio.workspace.read(site.id, "index.html")

    main_call = next(call for call in model.calls if _is_main(str(call["system"])))
    assert "- Builder (agent," in str(main_call["system"])
    assert ASK_AGENT_TOOL in main_call["tools"]
    builder_calls = [call for call in model.calls if not _is_main(str(call["system"]))]
    assert all(ASK_AGENT_TOOL not in call["tools"] for call in builder_calls)

    shared = [entry.text for entry in await studio.memories(SHARED_MEMORY_ID)]
    assert any(text.startswith("Builder completed: " + TASK) for text in shared)


@pytest.mark.asyncio
async def test_main_ai_gives_build_work_a_project_when_it_forgets(make_studio):
    def respond(system: str, prompt: str):
        if _is_main(system):
            if "succeeded" in prompt:
                return LLMReply(text="All set.")
            return tool_reply(ASK_AGENT_TOOL, {"agent": "Builder", "task": TASK})
        return tool_reply("finish", {"summary": "ok"})

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()

    await studio.main_say("bakery page please", background=False)

    sites = await studio.sites()
    assert [site.name for site in sites] == ["Build a landing page for"]


@pytest.mark.asyncio
async def test_main_ai_runs_a_team_task_in_a_room(make_studio):
    def respond(system: str, prompt: str):
        if _is_main(system):
            if prompt.startswith("Team ("):
                return LLMReply(text="The team finished.")
            return tool_reply(
                TEAM_TASK_TOOL,
                {"agents": ["Builder", "Teacher"], "goal": "Plan the menu"},
            )
        if "@Teacher" in system and "Plan the menu" in prompt:
            return LLMReply(text="@Teacher please check the plan")
        return LLMReply(text="Looks good. TASK COMPLETE: menu planned")

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()

    chat = await studio.main_say("plan the menu with the team", background=False)

    transcript = await studio.transcript(chat.id)
    handoff = next(message for message in transcript if message.role == "tool")
    assert handoff.author == TEAM_TASK_TOOL
    assert "Done: menu planned" in handoff.text
    assert handoff.data["completed"] is True
    room = await studio.store.require(Chat, str(handoff.data["room_id"]))
    assert room.kind == "room"
    assert transcript[-1].text == "The team finished."


@pytest.mark.asyncio
async def test_only_the_main_ai_can_hand_off_work(make_studio):
    studio, _ = make_studio(
        [tool_reply(ASK_AGENT_TOOL, {"agent": "Builder", "task": "x"}), "fine"]
    )
    await studio.ensure_defaults()
    rogue = await studio.create_agent(
        name="Rogue", tools=[ASK_AGENT_TOOL, "web_search"]
    )
    chat = await studio.create_chat(agent_id=rogue.id)

    await studio.send(chat.id, "delegate please")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.data["failed"] is True
    assert "Only the main agent" in tool.text
    assert await studio.runs() == ()


@pytest.mark.asyncio
async def test_unknown_agent_names_list_the_team(make_studio):
    def respond(system: str, prompt: str):
        if "No agent called" in prompt:
            return LLMReply(text="I could not find them.")
        return tool_reply(ASK_AGENT_TOOL, {"agent": "Nobody", "task": "x"})

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()

    chat = await studio.main_say("ask nobody", background=False)

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.data["failed"] is True
    assert "No agent called 'Nobody'" in tool.text
    assert "Builder" in tool.text
    assert "Guide" not in tool.text


@pytest.mark.asyncio
async def test_main_console_reports_the_team_and_systems(make_studio):
    studio, _ = make_studio(["Hello. All systems are up."])

    await studio.main_say("status report")
    await studio.wait_for_background()
    console = await studio.main_console()

    assert console["agent"]["role"] == "main"
    assert console["thinking"] is False
    texts = [message["text"] for message in console["messages"]]
    assert texts == ["status report", "Hello. All systems are up."]
    names = {member["name"] for member in console["team"]}
    assert {"Builder", "Guide", "Teacher", "Student"} <= names
    assert console["agent"]["name"] not in names
    assert console["systems"]["local"]["reachable"] in {True, False}
    assert console["memory"]["enabled"] is True

    later = await studio.main_console(after=console["messages"][-1]["sequence"])
    assert later["messages"] == []

    fresh = await studio.main_chat(fresh=True)
    assert fresh.id != console["chat"]["id"]
    assert (await studio.main_console())["chat"]["id"] == fresh.id
