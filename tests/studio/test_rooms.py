"""Agents share a room with the user, hand work to each other, and finish tasks."""

import re

import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import Agent, Chat, Message
from free_claude_code.studio.rooms import completion_summary, mentioned, room_history


def speaker(system: str) -> str:
    match = re.search(r"You are (\w+), one of several AI agents", system)
    return match.group(1) if match else "?"


async def make_team(studio, *models: str) -> list[Agent]:
    names = ["Lead", "Scout", "Coder"]
    return [
        await studio.create_agent(name=names[index], model=model, tools=[])
        for index, model in enumerate(models)
    ]


def test_mentions_are_found_in_order_and_self_is_skipped():
    lead = Agent.model_validate({"name": "Lead", "model": "m"})
    scout = Agent.model_validate({"name": "Scout", "model": "m"})
    text = "@scout check this, then @Lead reviews"

    assert [agent.name for agent in mentioned(text, [lead, scout])] == ["Scout", "Lead"]
    assert [
        agent.name for agent in mentioned(text, [lead, scout], exclude=lead.id)
    ] == ["Scout"]


def test_completion_marker_is_read_anywhere_in_a_message():
    assert completion_summary("All set. TASK COMPLETE: shipped the page") == (
        "shipped the page"
    )
    assert completion_summary("task complete:") == "Done."
    assert completion_summary("still working") is None


def test_history_is_rendered_from_one_agents_point_of_view():
    lead = Agent.model_validate({"name": "Lead", "model": "m"})
    transcript = [
        Message.model_validate(
            {
                "chat_id": "c",
                "sequence": 1,
                "role": "user",
                "text": "hi",
                "author": "user",
            }
        ),
        Message.model_validate(
            {
                "chat_id": "c",
                "sequence": 2,
                "role": "assistant",
                "text": "yo",
                "author": "Scout",
            }
        ),
        Message.model_validate(
            {
                "chat_id": "c",
                "sequence": 3,
                "role": "tool",
                "text": "x",
                "author": "web_search",
            }
        ),
        Message.model_validate(
            {
                "chat_id": "c",
                "sequence": 4,
                "role": "assistant",
                "text": "hello",
                "author": "Lead",
            }
        ),
    ]

    history = room_history(lead, transcript)

    assert [turn.role for turn in history] == ["user", "assistant", "user"]
    assert history[0].content == "User: hi\n\nScout: yo"
    assert history[-1].content == "(It is your turn.)"


@pytest.mark.asyncio
async def test_an_unaddressed_message_gets_an_answer_from_everyone(make_studio):
    studio, _ = make_studio(lambda system, prompt: f"{speaker(system)} here.")
    team = await make_team(studio, "nvidia_nim/big", "local/tiny")
    room = await studio.create_room(member_ids=[agent.id for agent in team])

    outcome = await studio.room_say(room.id, "Hello team", background=False)

    assert outcome is not None
    assert outcome.speakers == ("Lead", "Scout")
    replies = [
        message.text
        for message in await studio.transcript(room.id)
        if message.role == "assistant"
    ]
    assert replies == ["Lead here.", "Scout here."]


@pytest.mark.asyncio
async def test_local_and_server_models_each_use_their_own_route(make_studio):
    studio, model = make_studio(lambda system, prompt: f"{speaker(system)} here.")
    team = await make_team(studio, "nvidia_nim/big", "local/tiny")
    room = await studio.create_room(member_ids=[agent.id for agent in team])

    await studio.room_say(room.id, "Hello", background=False)

    assert [call["model"] for call in model.calls] == ["nvidia_nim/big", "tiny"]


@pytest.mark.asyncio
async def test_a_mention_addresses_only_that_agent(make_studio):
    studio, _ = make_studio(lambda system, prompt: f"{speaker(system)} here.")
    team = await make_team(studio, "p/a", "p/b")
    room = await studio.create_room(member_ids=[agent.id for agent in team])

    outcome = await studio.room_say(room.id, "@Scout just you", background=False)

    assert outcome is not None and outcome.speakers == ("Scout",)


@pytest.mark.asyncio
async def test_agents_hand_off_and_finish_a_task(make_studio):
    def respond(system: str, prompt: str) -> str:
        who = speaker(system)
        if who == "Lead" and "Scout: " not in prompt:
            return "Plan: @Scout find the tide times."
        if who == "Scout":
            return "High tide is 06:12. @Lead over to you."
        return "TASK COMPLETE: Tide times gathered — high tide 06:12."

    studio, _ = make_studio(respond)
    team = await make_team(studio, "nvidia_nim/big", "local/tiny")
    room = await studio.create_room(member_ids=[agent.id for agent in team])

    outcome = await studio.room_start_task(
        room.id, "Find today's tides", background=False
    )

    assert outcome is not None
    assert outcome.completed is True
    assert outcome.speakers == ("Lead", "Scout", "Lead")
    assert outcome.summary == "Tide times gathered — high tide 06:12."

    stored = await studio.store.require(Chat, room.id)
    assert stored.settings["task_status"] == "done"
    assert stored.settings["goal"] == "Find today's tides"

    shared = await studio.memories("shared")
    finished = [entry for entry in shared if "Finished a team task" in entry.text]
    assert len(finished) == 1, "the team should learn the outcome exactly once"
    assert finished[0].author == "Lead, Scout"
    for agent in team:
        working = await studio.memories(agent.id, scope="working")
        assert working, f"{agent.name} kept no working memory of the room"


@pytest.mark.asyncio
async def test_endless_handoffs_stop_at_the_turn_limit(make_studio):
    def respond(system: str, prompt: str) -> str:
        return "@Scout your turn" if speaker(system) == "Lead" else "@Lead no, yours"

    studio, _ = make_studio(respond)
    team = await make_team(studio, "p/a", "p/b")
    room = await studio.create_room(member_ids=[agent.id for agent in team])

    outcome = await studio.room_say(room.id, "@Lead go", background=False)

    assert outcome is not None
    assert outcome.turns == 8
    kinds = [message.data.get("kind") for message in await studio.transcript(room.id)]
    assert "turn_limit" in kinds


@pytest.mark.asyncio
async def test_a_running_task_gets_one_status_nudge(make_studio):
    studio, _model = make_studio(lambda system, prompt: "Working on it.")
    team = await make_team(studio, "p/a", "p/b")
    room = await studio.create_room(member_ids=[agent.id for agent in team])

    outcome = await studio.room_start_task(room.id, "Write a haiku", background=False)

    assert outcome is not None
    assert outcome.speakers == ("Lead", "Lead")
    kinds = [message.data.get("kind") for message in await studio.transcript(room.id)]
    assert kinds.count("nudge") == 1


@pytest.mark.asyncio
async def test_stop_halts_the_room_between_turns(make_studio):
    holder: dict[str, str] = {}

    async def respond(system: str, prompt: str) -> str:
        await studio.room_stop(holder["room"])
        return f"{speaker(system)}: @Scout continue"

    studio, _ = make_studio(respond)
    team = await make_team(studio, "p/a", "p/b")
    room = await studio.create_room(member_ids=[agent.id for agent in team])
    holder["room"] = room.id

    outcome = await studio.room_say(room.id, "@Lead start", background=False)

    assert outcome is not None
    assert outcome.stopped is True
    assert outcome.speakers == ("Lead",)


@pytest.mark.asyncio
async def test_a_room_needs_agents(make_studio):
    studio, _ = make_studio([])
    with pytest.raises(Exception, match="at least one agent"):
        await studio.room_members(
            (
                await studio.create_room(
                    member_ids=[(await studio.create_agent(name="Solo")).id]
                )
            ).id,
            [],
        )


@pytest.mark.asyncio
async def test_send_on_a_room_runs_the_room(make_studio):
    studio, _ = make_studio([LLMReply(text="On it.")])
    agent = await studio.create_agent(name="Lead", tools=[])
    room = await studio.create_room(member_ids=[agent.id])

    result = await studio.send(room.id, "Hello")

    assert result.text == "On it."
