"""Long conversations keep running notes, so nothing is forgotten."""

from itertools import pairwise

import pytest

from free_claude_code.studio.convo_notes import NOTES_HEADER, transcript_lines
from free_claude_code.studio.llm import LLMReply, StudioLLMError
from free_claude_code.studio.models import ChatNotes

NOTES = "Goal:\n- Build a snake game for Sam\nFacts:\n- Sam's favourite colour is teal"


def keeper_calls(model):
    return [c for c in model.calls if "running notes" in str(c["system"])]


def jarvis_calls(model):
    return [c for c in model.calls if "the user's main AI" in str(c["system"])]


async def long_chat(studio, turns: int = 35):
    chat = await studio.main_chat()
    await studio.store.append_message(
        chat_id=chat.id,
        role="user",
        text="My name is Sam and my favourite colour is teal.",
        author="user",
    )
    await studio.store.append_message(
        chat_id=chat.id,
        role="tool",
        text="Builder is working on it in the background.",
        author="ask_agent",
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
async def test_messages_leaving_view_are_folded_into_notes(make_studio):
    def respond(system: str, prompt: str):
        if "running notes" in system:
            return LLMReply(text=NOTES)
        return LLMReply(text="Sure.")

    studio, model = make_studio(respond)
    await studio.ensure_defaults()
    chat = await long_chat(studio)

    await studio.main_say("what's next?", background=False)
    await studio.wait_for_background()
    await studio.main_say("and after that?", background=False)

    written = keeper_calls(model)[0]["prompt"]
    assert "User: My name is Sam and my favourite colour is teal." in written
    assert "(tool ask_agent): Builder is working on it" in written
    saved = await studio.store.require(ChatNotes, chat.id)
    assert saved.text == NOTES
    assert saved.until > 0
    first = jarvis_calls(model)[-1]["messages"][0].content
    assert first.startswith(f"{NOTES_HEADER}\n{NOTES}")
    sent = "\n".join(m.content for m in jarvis_calls(model)[-1]["messages"])
    assert "My name is Sam" not in sent, "the old message is now in the notes"


@pytest.mark.asyncio
async def test_without_notes_nothing_leaves_the_view(make_studio):
    def respond(system: str, prompt: str):
        if "running notes" in system:
            raise StudioLLMError("LM Studio is not running")
        return LLMReply(text="Sure.")

    studio, model = make_studio(respond)
    await studio.ensure_defaults()
    chat = await long_chat(studio)

    await studio.main_say("what's next?", background=False)
    await studio.wait_for_background()
    await studio.main_say("and after that?", background=False)

    assert await studio.store.get(ChatNotes, chat.id) is None
    sent = "\n".join(m.content for m in jarvis_calls(model)[-1]["messages"])
    assert "My name is Sam" in sent, "kept in view until notes can be written"


@pytest.mark.asyncio
async def test_agent_reports_stay_in_the_conversation(make_studio):
    studio, model = make_studio(lambda system, prompt: LLMReply(text="Noted."))
    await studio.ensure_defaults()
    chat = await studio.main_chat()
    await studio.store.append_message(
        chat_id=chat.id, role="user", text="have Builder make a game", author="user"
    )
    await studio.store.append_message(
        chat_id=chat.id,
        role="tool",
        text="Builder is working on it in the background.",
        author="ask_agent",
    )
    await studio.store.append_message(
        chat_id=chat.id, role="assistant", text="Builder's on it.", author="Jarvis"
    )
    await studio.store.append_message(
        chat_id=chat.id,
        role="event",
        text="Builder finished in the background (succeeded): Snake game ready.",
        author="Builder",
        data={"kind": "background_done"},
    )

    await studio.main_say("how did it go?", background=False)

    messages = jarvis_calls(model)[-1]["messages"]
    roles = [m.role for m in messages]
    assert all(a != b for a, b in pairwise(roles)), "turns alternate"
    first, reply, latest = messages[0], messages[1], messages[2]
    assert "(Studio: ask_agent said) Builder is working on it" in first.content
    assert reply.content == "Builder's on it."
    assert "(Studio update) Builder finished in the background" in latest.content
    assert latest.content.endswith("how did it go?")


def test_the_note_keeper_reads_labelled_lines():
    from free_claude_code.studio.models import Message

    lines = transcript_lines(
        [
            Message(chat_id="c", sequence=1, role="user", text="hi", author="user"),
            Message(
                chat_id="c", sequence=2, role="assistant", text="hey", author="Jarvis"
            ),
            Message(
                chat_id="c", sequence=3, role="tool", text="x" * 900, author="research"
            ),
            Message(
                chat_id="c", sequence=4, role="event", text="done", author="Builder"
            ),
        ]
    )

    assert lines.splitlines()[:2] == ["User: hi", "Jarvis: hey"]
    assert lines.splitlines()[2].startswith("(tool research): xxx")
    assert len(lines.splitlines()[2]) < 450
    assert lines.splitlines()[3] == "(update): done"
