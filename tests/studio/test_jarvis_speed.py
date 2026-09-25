"""Jarvis's prompt stays the same from reply to reply, so LM Studio reuses it."""

import pytest

from free_claude_code.studio.agents import HISTORY_MIN, HISTORY_STEP
from free_claude_code.studio.llm import LLMReply, ToolSpec, tool_protocol_instructions


def jarvis_calls(model):
    return [c for c in model.calls if "the user's main AI" in str(c["system"])]


@pytest.mark.asyncio
async def test_the_start_of_the_prompt_is_identical_between_replies(make_studio):
    studio, model = make_studio(lambda system, prompt: LLMReply(text="Sure."))
    await studio.ensure_defaults()

    for index in range(3):
        await studio.main_say(f"question {index}", background=False)

    first, second, third = jarvis_calls(model)
    assert first["system"] == second["system"] == third["system"]
    earlier = [(m.role, m.content) for m in second["messages"][:-1]]
    later = [(m.role, m.content) for m in third["messages"][: len(earlier)]]
    assert earlier == later, "the earlier conversation is sent unchanged"
    assert third["studio_note"].startswith("Studio's note")


@pytest.mark.asyncio
async def test_the_history_window_moves_in_steps(make_studio):
    studio, model = make_studio(lambda system, prompt: LLMReply(text="Ok."))
    await studio.ensure_defaults()
    chat = await studio.main_chat()
    for index in range(70):
        await studio.store.append_message(
            chat_id=chat.id, role="user", text=f"old {index}", author="user"
        )

    firsts = []
    for index in range(6):
        await studio.main_say(f"new {index}", background=False)
        messages = jarvis_calls(model)[-1]["messages"]
        firsts.append(messages[0].content)
        assert len(messages) >= HISTORY_MIN // 2, "never less context than before"
    assert len(set(firsts)) <= 2, "the start moves at most once in six replies"
    assert HISTORY_STEP == 20


def test_tool_arguments_are_listed_compactly():
    spec = ToolSpec(
        name="todo",
        description="The to-do list.",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list"]},
                "items": {"type": "array", "items": {"type": "string"}},
                "count": {"type": "integer", "description": "How many."},
            },
            "required": ["action"],
        },
    )

    text = tool_protocol_instructions([spec])

    assert text.endswith(
        "- todo: The to-do list. Arguments: action (one of add|list, required); "
        "items (list of text); count (whole number): How many."
    )
