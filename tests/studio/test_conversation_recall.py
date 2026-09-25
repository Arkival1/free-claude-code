"""Jarvis sees every earlier message word for word when it matters."""

import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.recall_messages import RECALL_HEADER

from .conftest import tool_reply


def jarvis_calls(model):
    return [c for c in model.calls if "the user's main AI" in str(c["system"])]


def answer(system: str, prompt: str):
    if "running notes" in system:
        return LLMReply(text="Goal:\n- Chat")
    return LLMReply(text="Sure.")


async def long_chat(studio, first: str, turns: int = 35):
    chat = await studio.main_chat()
    await studio.store.append_message(
        chat_id=chat.id, role="user", text=first, author="user"
    )
    for index in range(turns):
        await studio.store.append_message(
            chat_id=chat.id, role="user", text=f"small talk {index}", author="user"
        )
        await studio.store.append_message(
            chat_id=chat.id, role="assistant", text=f"reply {index}", author="Jarvis"
        )
    return chat


@pytest.mark.asyncio
async def test_matching_earlier_messages_come_back_word_for_word(make_studio):
    studio, model = make_studio(answer)
    await studio.ensure_defaults()
    await long_chat(
        studio, "The bakery site should use teal and gold, with a serif logo."
    )
    await studio.main_say("warm up", background=False)
    await studio.wait_for_background()

    await studio.main_say(
        "what colours did we pick for the bakery site?", background=False
    )

    note = jarvis_calls(model)[-1]["studio_note"]
    assert RECALL_HEADER in note
    assert "#1 (" in note and "User: The bakery site should use teal and gold" in note
    sent = "\n".join(m.content for m in jarvis_calls(model)[-1]["messages"][:-1])
    assert "teal and gold" not in sent, "it is out of view, so only the recall has it"


@pytest.mark.asyncio
async def test_messages_in_view_are_not_repeated(make_studio):
    studio, model = make_studio(answer)
    await studio.ensure_defaults()
    chat = await studio.main_chat()
    await studio.store.append_message(
        chat_id=chat.id, role="user", text="The bakery uses teal.", author="user"
    )

    await studio.main_say("what colour is the bakery?", background=False)

    assert RECALL_HEADER not in jarvis_calls(model)[-1]["studio_note"]


@pytest.mark.asyncio
async def test_earlier_conversations_are_searched_too(make_studio):
    studio, model = make_studio(answer)
    await studio.ensure_defaults()
    main = await studio.main_agent()
    old = await studio.create_chat(agent_id=main.id, title="Old talk")
    await studio.store.append_message(
        chat_id=old.id, role="user", text="My dog is called Biscuit.", author="user"
    )
    await studio.store.put(old.model_copy(update={"updated_at": 1}))

    await studio.main_say("what is my dog called?", background=False)

    note = jarvis_calls(model)[-1]["studio_note"]
    assert "in an earlier conversation" in note and "Biscuit" in note


@pytest.mark.asyncio
async def test_the_conversation_tool_searches_and_reads_every_message(make_studio):
    replies = iter(
        [
            tool_reply("conversation", {"query": "bakery colours teal"}),
            tool_reply("conversation", {"from": 1, "to": 3}, call_id="c2"),
            tool_reply("conversation", {}, call_id="c3"),
            LLMReply(text="Teal and gold."),
        ]
    )

    def respond(system: str, prompt: str):
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Chat")
        return next(replies)

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    chat = await long_chat(studio, "The bakery colours are teal and gold.", turns=5)

    await studio.main_say("remind me of the bakery colours", background=False)

    searched, read, counted = [
        m for m in await studio.transcript(chat.id) if m.role == "tool"
    ][-3:]
    assert searched.text.startswith("#1 (")
    assert "The bakery colours are teal and gold." in searched.text
    assert read.text.splitlines()[0].startswith("#1 (")
    assert "#3 (" in read.text and "#4 (" not in read.text
    assert counted.text.startswith("This conversation has ")
    main = await studio.main_agent()
    assert "conversation" in main.tools
