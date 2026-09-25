"""Jarvis's everyday tools and the Helper's upgrades."""

from datetime import datetime

import httpx
import pytest

from free_claude_code.studio.assistant_tools import (
    CalculationError,
    calculate,
    describe_time,
    parse_when,
)
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import Agent, TodoItem, now_ms
from free_claude_code.studio.presets import HELPER_PROMPT, PROMPT_UPGRADES
from tests.api.support import create_test_app

from .conftest import tool_reply

NOW = datetime(2026, 9, 25, 14, 5)


@pytest.mark.parametrize(
    ("expression", "result"),
    [
        ("2+2*3", 8),
        ("15% of 80", 12),
        ("sqrt(16) + 2^3", 12),
        ("1,000 * 3", 3000),
        ("(4.5 * 3) - 1", 12.5),
    ],
)
def test_sums_are_worked_out_exactly(expression, result):
    assert calculate(expression) == result


@pytest.mark.parametrize(
    "bad", ["__import__('os')", "open('x')", "9**99999", "1/0", "x"]
)
def test_only_arithmetic_is_calculated(bad):
    with pytest.raises(CalculationError):
        calculate(bad)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("in 20 minutes", "today 14:25"),
        ("in an hour", "today 15:05"),
        ("tomorrow 9am", "tomorrow 09:00"),
        ("at 17:30", "today 17:30"),
        ("5pm", "today 17:00"),
        ("tonight", "today 20:00"),
        ("2026-10-01 14:00", "Thu 1 Oct 14:00"),
    ],
)
def test_reminder_times_are_understood(text, shown):
    assert describe_time(parse_when(text, now=NOW), now=NOW) == shown


def test_an_unreadable_time_says_how_to_write_one():
    with pytest.raises(ValueError, match="in 20 minutes"):
        parse_when("whenever", now=NOW)


def jarvis_script(*steps):
    replies = iter(steps)

    def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            return next(replies)
        return LLMReply(text="ok")

    return respond


@pytest.mark.asyncio
async def test_jarvis_keeps_the_to_do_list(make_studio):
    studio, model = make_studio(
        jarvis_script(
            tool_reply(
                "todo", {"action": "add", "text": "Call Sam", "due": "in 20 minutes"}
            ),
            tool_reply("todo", {"action": "add", "text": "Buy milk"}, call_id="c2"),
            tool_reply("todo", {"action": "list"}, call_id="c3"),
            tool_reply("todo", {"action": "done", "id": "milk"}, call_id="c4"),
            LLMReply(text="Done."),
        )
    )
    await studio.ensure_defaults()

    chat = await studio.main_say("remind me to call Sam and add milk", background=False)

    tools = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert tools[0].text.startswith("Added to the to-do list: Call Sam. Reminder today")
    listed = tools[2].text
    assert listed.index("Call Sam") < listed.index("Buy milk"), "reminders first"
    assert tools[3].text == "Marked done: Buy milk."
    assert [item.text for item in await studio.todos()] == ["Call Sam"]
    jarvis = model.calls[0]
    assert jarvis["studio_note"].count("Now: ") == 1
    for name in ("todo", "calculate", "list_projects", "system_status"):
        assert name in jarvis["tools"]


@pytest.mark.asyncio
async def test_due_reminders_are_announced_once(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    await studio.store.put(TodoItem(text="Stretch", due_at=now_ms() - 1_000))
    await studio.store.put(TodoItem(text="Later", due_at=now_ms() + 3_600_000))

    console = await studio.main_console()
    studio._reminders_checked = -1e9
    again = await studio.main_console()

    said = [
        m["text"]
        for m in again["messages"]
        if (m["data"] or {}).get("kind") == "reminder"
    ]
    assert said == ["Reminder: Stretch"]
    assert console["messages"][-1]["author"] == "Jarvis"


@pytest.mark.asyncio
async def test_jarvis_finds_projects_does_sums_and_checks_the_pc(make_studio):
    studio, _ = make_studio(
        jarvis_script(
            tool_reply("list_projects", {"query": "bakery"}),
            tool_reply("calculate", {"expression": "12 * 4.5"}, call_id="c2"),
            tool_reply("system_status", {}, call_id="c3"),
            LLMReply(text="All set."),
        )
    )
    await studio.ensure_defaults()
    site = await studio.create_site(name="Bakery site")
    await studio.create_site(name="Snake game")

    chat = await studio.main_say("where is the bakery site?", background=False)

    found, summed, system = [
        m for m in await studio.transcript(chat.id) if m.role == "tool"
    ]
    assert found.text.startswith("- Bakery site: ")
    assert f"/studio/sites/{site.id}/index.html" in found.text
    assert "Snake" not in found.text
    assert summed.text == "12 * 4.5 = 54"
    assert "CPU" in system.text and "LM Studio:" in system.text


@pytest.mark.asyncio
async def test_the_helper_plans_sums_and_reviews(make_studio):
    studio, model = make_studio(
        [
            tool_reply("calculate", {"expression": "3 * 45 + 20"}),
            tool_reply(
                "todo", {"action": "add", "text": "Book the hall"}, call_id="c2"
            ),
            "Best approach: ...",
        ]
    )
    await studio.ensure_defaults()
    helper = await studio.agent_by_name("Helper")
    assert helper is not None
    assert {"calculate", "todo", "check_project"} <= set(helper.tools)
    chat = await studio.create_chat(agent_id=helper.id)

    await studio.send(chat.id, "plan a party for 45 people at 3 pounds each plus 20")

    tools = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert tools[0].text == "3 * 45 + 20 = 155"
    assert tools[1].text.startswith("Added to the to-do list: Book the hall.")
    assert "Best approach:" in str(model.calls[0]["system"])
    assert "Backup:" in str(model.calls[0]["system"])


@pytest.mark.asyncio
async def test_an_unedited_helper_is_upgraded(make_studio):
    studio, _ = make_studio([])
    old = next(old for old, new in PROMPT_UPGRADES.items() if new == HELPER_PROMPT)
    await studio.store.put(
        Agent.model_validate(
            {"name": "Helper", "role": "helper", "model": "m", "system_prompt": old}
        )
    )

    await studio.ensure_defaults()

    helper = await studio.agent_by_name("Helper")
    assert helper is not None and helper.system_prompt == HELPER_PROMPT
    assert "calculate" in helper.tools and "todo" in helper.tools


@pytest.mark.asyncio
async def test_to_dos_through_the_routes(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            made = await client.post(
                "/studio/api/todos",
                json={"text": "Water plants", "due": "tomorrow 8am"},
            )
            assert made.status_code == 200 and made.json()["due_at"]
            plain = await client.post("/studio/api/todos", json={"text": "Read"})
            bad = await client.post(
                "/studio/api/todos", json={"text": "X", "due": "whenever"}
            )
            assert bad.status_code == 400
            listed = (await client.get("/studio/api/todos")).json()["todos"]
            assert [item["text"] for item in listed] == ["Water plants", "Read"]
            done = await client.post(f"/studio/api/todos/{plain.json()['id']}/done")
            assert done.json()["done"] is True
            gone = await client.delete(f"/studio/api/todos/{made.json()['id']}")
            assert gone.json() == {"deleted": True}
            assert (await client.get("/studio/api/todos")).json()["todos"] == []
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
