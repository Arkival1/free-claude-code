"""When the user tells Jarvis to have an agent do something, it gets done."""

import asyncio

import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import AgentRun, Chat
from free_claude_code.studio.orders import (
    Order,
    build_request,
    called_agent,
    is_job,
    is_yes,
    offered_orders,
    parse_orders,
    pick_agent,
    web_request,
)

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


@pytest.mark.parametrize(
    ("text", "task"),
    [
        ("research the best budget GPUs", "research the best budget GPUs"),
        (
            "Jarvis, go on the web and find cheap flights to Oslo",
            "find cheap flights to Oslo",
        ),
        ("can you look up reviews of the Pixel 10?", "look up reviews of the Pixel 10"),
        ("use the internet to compare phone cameras", "compare phone cameras"),
        ("google how to fix a leaky tap", "google how to fix a leaky tap"),
        ("search my notes for the bakery menu", ""),
        ("look into it", ""),
        ("learn about rust", ""),
        ("what's the weather", ""),
    ],
)
def test_research_and_web_requests_are_spotted(text, task):
    assert web_request(text, "Jarvis") == task


def test_an_order_keeps_words_that_start_like_polite_ones():
    assert parse_orders("have Builder tone down the colours", TEAM) == [
        Order("Builder", "tone down the colours")
    ]


@pytest.mark.asyncio
async def test_asking_jarvis_to_research_hands_it_to_the_researcher(make_studio):
    studio, model = make_studio(team_script())
    await studio.ensure_defaults()

    await studio.main_say(
        "go on the web and find the best rain jackets", background=False
    )
    await studio.wait_for_background()

    runs = await studio.runs()
    assert [run.goal for run in runs] == ["find the best rain jackets"]
    researcher = await studio.agent_by_name("Researcher")
    assert researcher is not None and runs[0].agent_id == researcher.id
    jarvis = next(c for c in model.calls if "the user's main AI" in str(c["system"]))
    assert "Researcher is now working on" in jarvis["studio_note"]


def test_a_go_ahead_is_told_apart_from_a_new_request():
    assert is_yes("yes")
    assert is_yes("Yeah go ahead!")
    assert is_yes("ok I'm ready", "Jarvis")
    assert is_yes("yes Jarvis do it", "Jarvis")
    assert not is_yes("yes but research boots instead")
    assert not is_yes("no")
    assert not is_yes("please")


def test_the_job_jarvis_offered_is_read_from_his_question():
    assert offered_orders(
        "Shall I have the Researcher look into rain jackets?", TEAM
    ) == [Order("Researcher", "look into rain jackets")]
    assert offered_orders("Got it. Do you want me to research rain jackets?", TEAM) == [
        Order("", "research rain jackets")
    ]
    assert offered_orders("Should I ask the Researcher to look into it?", TEAM) == []
    assert offered_orders("How are you today?", TEAM) == []


@pytest.mark.asyncio
async def test_saying_yes_to_jarvis_starts_the_job_he_offered_once(make_studio):
    def jarvis(prompt: str) -> LLMReply:
        if prompt.startswith("yes"):
            return LLMReply(text="Starting now.")
        return LLMReply(text="Are you ready for the Researcher to look into it?")

    studio, _ = make_studio(team_script(jarvis=jarvis))
    await studio.ensure_defaults()

    await studio.main_say("best rain jackets under 100 dollars", background=False)
    assert await studio.runs() == ()

    await studio.main_say("yes", background=False)
    await studio.main_say("yes go", background=False)
    await studio.wait_for_background()

    runs = await studio.runs()
    assert [run.goal for run in runs] == ["best rain jackets under 100 dollars"]
    researcher = await studio.agent_by_name("Researcher")
    assert researcher is not None and runs[0].agent_id == researcher.id


@pytest.mark.parametrize(
    ("text", "orders"),
    [
        (
            "call the researcher and find cheap tvs",
            [Order("Researcher", "find cheap tvs")],
        ),
        (
            "use the researcher to find good headphones",
            [Order("Researcher", "find good headphones")],
        ),
        ("researcher find cheap tvs", [Order("Researcher", "find cheap tvs")]),
        (
            "Jarvis can the researcher look up cheap tvs",
            [Order("Researcher", "look up cheap tvs")],
        ),
        (
            "get the researcher to find cheap flights",
            [Order("Researcher", "find cheap flights")],
        ),
        ("what can the builder do for me", []),
        ("Researcher is idle why", []),
        ("get Builder's opinion", []),
        ("jarvis call the researcher", []),
    ],
)
def test_more_ways_of_calling_an_agent(text, orders):
    assert parse_orders(text, TEAM, "Jarvis") == orders


@pytest.mark.parametrize(
    ("text", "task"),
    [
        ("find me the best gpu", "find me the best gpu"),
        ("look for cheap flights online", "look for cheap flights online"),
        ("find the bakery site", ""),
        ("look for my notes", ""),
    ],
)
def test_more_web_requests(text, task):
    assert web_request(text, "Jarvis") == task


def test_a_bare_call_names_the_agent():
    assert called_agent("Jarvis, call the researcher", TEAM, "Jarvis") == "Researcher"
    assert called_agent("can you get the Researcher?", TEAM, "Jarvis") == "Researcher"
    assert called_agent("call the researcher and find tvs", TEAM, "Jarvis") == ""
    assert is_job("cheap 4k tvs")
    assert not is_job("no thanks")
    assert not is_job("yes")


@pytest.mark.asyncio
async def test_calling_an_agent_then_saying_what_for_starts_it(make_studio):
    def jarvis(prompt: str) -> LLMReply:
        return LLMReply(text="Sure, what should the Researcher look into?")

    studio, _ = make_studio(team_script(jarvis=jarvis))
    await studio.ensure_defaults()

    await studio.main_say("Jarvis call the researcher", background=False)
    assert await studio.runs() == ()
    await studio.main_say("cheap 4k tvs under 500", background=False)
    await studio.wait_for_background()

    runs = await studio.runs()
    assert [run.goal for run in runs] == ["cheap 4k tvs under 500"]
    researcher = await studio.agent_by_name("Researcher")
    assert researcher is not None and runs[0].agent_id == researcher.id


@pytest.mark.parametrize(
    ("text", "task"),
    [
        ("make me a spider-man website", "make me a spider-man website"),
        (
            "Jarvis, build a landing page for my bakery",
            "build a landing page for my bakery",
        ),
        ("can you make a snake game", "make a snake game"),
        ("make a plan for my week", ""),
        ("write me a poem", ""),
        ("what makes a good website", ""),
    ],
)
def test_make_something_requests_are_spotted(text, task):
    assert build_request(text, "Jarvis") == task


@pytest.mark.asyncio
async def test_asking_jarvis_for_a_website_hands_it_to_the_builder(make_studio):
    studio, _ = make_studio(team_script())
    await studio.ensure_defaults()

    await studio.main_say("make me a spider-man website", background=False)
    await studio.wait_for_background()

    runs = await studio.runs()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    assert [(run.agent_id, run.goal) for run in runs] == [
        (builder.id, "make me a spider-man website")
    ]
