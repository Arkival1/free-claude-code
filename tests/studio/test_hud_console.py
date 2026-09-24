"""What the command-center HUD shows beside the conversation."""

import asyncio

import pytest

from free_claude_code.studio import system_monitor
from free_claude_code.studio.memory import SHARED_MEMORY_ID

from .conftest import tool_reply


@pytest.mark.asyncio
async def test_the_console_has_a_room_timeline_and_insights(make_studio):
    studio, _ = make_studio(lambda system, prompt: "On it.")
    await studio.ensure_defaults()
    await studio.remember(SHARED_MEMORY_ID, "The user likes gold")

    empty = await studio.main_console()
    assert empty["room"] is None
    assert empty["timeline"] == []

    room = await studio.create_room(title="Team room")
    await studio.room_say(room.id, "Plan a bakery site", background=False)
    await studio.room_start_task(room.id, "Ship the bakery site", background=False)
    console = await studio.main_console()

    snapshot = console["room"]
    assert snapshot["id"] == room.id and snapshot["title"] == "Team room"
    assert {"Builder", "Researcher", "Helper"} <= set(snapshot["members"])
    assert "Jarvis" not in snapshot["members"]
    assert any(m["text"] == "Plan a bakery site" for m in snapshot["messages"])
    assert snapshot["goal"] == "Ship the bakery site"

    mission = next(item for item in console["timeline"] if item["kind"] == "room")
    assert mission["title"] == "Ship the bakery site"
    assert mission["route"] == f"room/{room.id}"

    insights = console["insights"]
    assert insights["shared"] == 1
    assert insights["memories"] >= 1
    assert insights["conversations"] >= 2

    monitor = console["monitor"]
    assert monitor["cores"] >= 1
    assert set(monitor) == {"cpu", "cores", "memory", "memory_gb", "disk", "disk_gb"}


def test_the_monitor_measures_a_folder_that_does_not_exist_yet(tmp_path):
    reading = system_monitor.sample(tmp_path / "models" / "not-yet")

    disk = reading["disk"]
    assert isinstance(disk, float) and 0 <= disk <= 100
    assert reading["disk_gb"]


def test_cpu_use_is_measured_between_readings():
    system_monitor.cpu_percent()
    second = system_monitor.cpu_percent()

    assert second is None or 0 <= second <= 100


@pytest.mark.asyncio
async def test_watching_one_agent_work(make_studio):
    gate = asyncio.Event()

    async def slow_reply(system, prompt):
        await gate.wait()
        return "Page ready."

    replies = iter(
        [
            tool_reply("write_file", {"path": "index.html", "content": "<h1>Hi</h1>"}),
        ]
    )

    def respond(system, prompt):
        try:
            return next(replies)
        except StopIteration:
            return slow_reply(system, prompt)

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    chat = await studio.create_chat(agent_id=builder.id)

    turn = asyncio.create_task(studio.send(chat.id, "make a page"))
    for _ in range(100):
        watching = await studio.agent_activity(builder.id)
        tools = [step["tool"] for step in watching["messages"]]
        if watching["agent"]["busy"] and "write_file" in tools:
            break
        await asyncio.sleep(0.01)
    assert watching["agent"]["busy"] is True
    assert watching["chat"]["id"] == chat.id
    steps = watching["messages"]
    assert steps[0]["role"] == "user" and steps[0]["text"] == "make a page"
    assert any(step["tool"] == "write_file" for step in steps)
    console = await studio.main_console()
    assert next(m for m in console["team"] if m["name"] == "Builder")["busy"] is True

    gate.set()
    await turn
    done = await studio.agent_activity(builder.id)
    assert done["agent"]["busy"] is False
    newer = await studio.agent_activity(builder.id, after=steps[-1]["sequence"])
    assert [m["text"] for m in newer["messages"]][-1] == "Page ready."


@pytest.mark.asyncio
async def test_watching_an_agent_in_a_room_shows_only_its_part(make_studio):
    studio, _ = make_studio(lambda system, prompt: "On it.")
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    room = await studio.create_room(title="Team room")
    await studio.room_say(room.id, "Plan the bakery site", background=False)

    watching = await studio.agent_activity(builder.id)

    assert watching["chat"]["id"] == room.id
    authors = {
        step["author"] for step in watching["messages"] if step["role"] != "user"
    }
    assert authors == {"Builder"}
