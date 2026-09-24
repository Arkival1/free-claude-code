"""When the user tells Jarvis to have an agent do something, it gets done."""

import asyncio

import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import AgentRun, Chat
from free_claude_code.studio.orders import Order, parse_orders, pick_agent

from .conftest import tool_reply

TEAM = ["Builder", "Researcher", "Helper", "Pixel Bot"]


@pytest.mark.parametrize(
    ("text", "orders"),
    [
        ("have Builder make a snake game", [Order("Builder", "make a snake game")]),
        (
            "Can you ask the Researcher to look into cheap GPUs and have Builder "
            "make a landing page",
            [
                Order("Researcher", "look into cheap GPUs"),
                Order("Builder", "make a landing page"),
            ],
        ),
        ("@Helper plan my week", [Order("Helper", "plan my week")]),
        (
            "Builder, fix the menu. Researcher: find the best fertilizer",
            [
                Order("Builder", "fix the menu"),
                Order("Researcher", "find the best fertilizer"),
            ],
        ),
        (
            "get an agent to research budget laptops",
            [Order("", "research budget laptops")],
        ),
        (
            "I need Pixel Bot to design a logo please",
            [Order("Pixel Bot", "design a logo")],
        ),
        ("stop Builder", [Order("Builder", "", stop=True)]),
        ("tell the builder to stop", [Order("Builder", "", stop=True)]),
        (
            "let the Researcher know I like short answers",
            [Order("Researcher", "The user wants you to know: I like short answers")],
        ),
        ("tell me about the Builder", []),
        ("what is Builder doing?", []),
        ("can you make Builder better?", []),
        ("I want Builder's opinion", []),
        ("how are you?", []),
    ],
)
def test_orders_are_read_from_what_the_user_says(text, orders):
    assert parse_orders(text, TEAM) == orders


def test_an_open_job_goes_to_the_right_agent():
    team = [("Builder", "builder"), ("Researcher", "researcher"), ("Helper", "helper")]
    assert pick_agent("research budget laptops", team) == "Researcher"
    assert pick_agent("build a todo app", team) == "Builder"
    assert pick_agent("brainstorm party ideas", team) == "Helper"


def team_script(builder_gate: asyncio.Event | None = None, jarvis=None):
    async def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            if jarvis is not None:
                return jarvis(prompt)
            return LLMReply(text="On it.")
        if builder_gate is not None and "Build complete, working websites" in system:
            await builder_gate.wait()
        return tool_reply("finish", {"summary": "All done."})

    return respond


@pytest.mark.asyncio
async def test_telling_jarvis_to_have_an_agent_do_something_starts_it(make_studio):
    studio, model = make_studio(team_script())
    await studio.ensure_defaults()

    chat = await studio.main_say("have Builder make a snake game", background=False)

    runs = await studio.runs()
    assert [run.goal for run in runs] == ["make a snake game"]
    builder = await studio.agent_by_name("Builder")
    assert builder is not None and runs[0].agent_id == builder.id
    sub = await studio.store.require(Chat, runs[0].chat_id)
    assert sub.parent_chat_id == chat.id
    handed = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert handed[0].author == "ask_agent" and handed[0].data["order"] is True
    jarvis = next(c for c in model.calls if "the user's main AI" in str(c["system"]))
    assert "Builder is now working on: make a snake game" in jarvis["studio_note"]
    assert jarvis["prompt"] == "have Builder make a snake game"
    assert "team_status" in jarvis["tools"] and "stop_agent" in jarvis["tools"]

    await studio.wait_for_background()
    done = await studio.store.require(AgentRun, runs[0].id)
    assert done.status == "succeeded"
    kinds = [(m.data or {}).get("kind") for m in await studio.transcript(chat.id)]
    assert "background_done" in kinds


@pytest.mark.asyncio
async def test_an_open_order_and_two_orders_in_one_message(make_studio):
    studio, _ = make_studio(team_script())
    await studio.ensure_defaults()

    await studio.main_say(
        "get an agent to research budget laptops and have Helper plan my week",
        background=False,
    )
    await studio.wait_for_background()

    names = {
        (await studio.agent(run.agent_id)).name: run.goal for run in await studio.runs()
    }
    assert names == {"Researcher": "research budget laptops", "Helper": "plan my week"}


@pytest.mark.asyncio
async def test_jarvis_does_not_hand_out_the_same_job_twice(make_studio):
    gate = asyncio.Event()

    def jarvis(prompt: str):
        if prompt.startswith("Builder is already working"):
            return LLMReply(text="Builder's on it.")
        return tool_reply(
            "ask_agent",
            {"agent": "Builder", "task": "make a snake game", "background": True},
        )

    studio, _ = make_studio(team_script(gate, jarvis))
    await studio.ensure_defaults()

    chat = await studio.main_say("have Builder make a snake game", background=False)

    assert len(await studio.runs()) == 1
    tools = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert tools[-1].data["duplicate"] is True
    gate.set()
    await studio.wait_for_background()


@pytest.mark.asyncio
async def test_stop_builder_stops_its_work(make_studio):
    gate = asyncio.Event()
    studio, _ = make_studio(team_script(gate))
    await studio.ensure_defaults()
    await studio.main_say("have Builder make a snake game", background=False)
    for _ in range(100):
        if (await studio.runs())[0].status == "running":
            break
        await asyncio.sleep(0.01)

    chat = await studio.main_say("stop Builder", background=False)

    run = (await studio.runs())[0]
    assert run.status == "cancelled" and run.error == "Stopped by the user."
    stopped = [m for m in await studio.transcript(chat.id) if m.author == "stop_agent"]
    assert stopped[-1].text == "Stopped Builder: 'make a snake game'"


@pytest.mark.asyncio
async def test_jarvis_can_check_on_the_team(make_studio):
    gate = asyncio.Event()

    def jarvis(prompt: str):
        if prompt.startswith("- Builder"):
            return LLMReply(text="Builder is busy with the snake game.")
        if prompt == "what is everyone doing?":
            return tool_reply("team_status", {})
        return LLMReply(text="On it.")

    studio, _ = make_studio(team_script(gate, jarvis))
    await studio.ensure_defaults()
    await studio.main_say("have Builder make a snake game", background=False)

    chat = await studio.main_say("what is everyone doing?", background=False)

    status = next(
        m for m in await studio.transcript(chat.id) if m.author == "team_status"
    )
    assert "- Builder (builder, working): on step" in status.text
    assert "'make a snake game'" in status.text
    assert "- Researcher (researcher, free)" in status.text
    assert "Jarvis" not in status.text and "Guide" not in status.text
    gate.set()
    await studio.wait_for_background()
    after = await studio.team_report()
    assert "Last task succeeded" in after and "All done." in after
