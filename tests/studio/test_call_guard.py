"""Tool calls are held to what the user actually said."""

import pytest

from free_claude_code.core.json_types import JsonValue
from free_claude_code.studio.call_guard import guarded
from free_claude_code.studio.llm import LLMReply, ToolCall

from .conftest import tool_reply


def call(name: str, **arguments: JsonValue) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=dict(arguments))


@pytest.mark.parametrize(
    "said",
    [
        "which model is the builder using",
        "which model does the builder use?",
        "what model is jarvis on",
        "tell me which model the builder uses",
        "hey jarvis, what's the builder running?",
    ],
)
def test_a_question_about_a_model_only_looks(said):
    asked = guarded(call("agent_model", agent="Builder", model="qwen"), said)
    assert asked.arguments == {"agent": "Builder"}


@pytest.mark.parametrize(
    "said",
    [
        "switch the builder to qwen",
        "can you put the builder on qwen",
        "use qwen for the builder",
        "jarvis, set the builder to qwen",
        "give the builder qwen please",
        "what is the builder on? then switch it to qwen",
        "which model is the builder using, and change it to qwen",
    ],
)
def test_asking_for_a_switch_still_switches(said):
    asked = guarded(call("agent_model", agent="Builder", model="qwen"), said)
    assert asked.arguments["model"] == "qwen"


def test_a_question_never_changes_an_agent():
    forget = call("manage_agent", action="forget", agent="Builder")
    assert guarded(forget, "what does the builder remember?").arguments == {
        "action": "show",
        "agent": "Builder",
    }
    give = call("manage_agent", action="every_tool_on", agent="Builder")
    assert guarded(give, "give the builder every tool").arguments["action"] == (
        "every_tool_on"
    )


@pytest.mark.parametrize(
    ("said", "kept"),
    [
        ("add buy eggs to my list", False),
        ("put milk on the to-do list", False),
        ("remind me to call the dentist tomorrow at 9am", True),
        ("remind me in 20 minutes to stretch", True),
        ("remind me at 5pm to stretch", True),
        ("remind me tonight to call mum", True),
    ],
)
def test_a_reminder_time_only_when_the_user_gave_one(said, kept):
    added = guarded(call("todo", action="add", text="x", due="at 9am"), said)
    assert ("due" in added.arguments) is kept


def jarvis_script(*steps):
    replies = iter(steps)

    def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            return next(replies)
        return LLMReply(text="ok")

    return respond


@pytest.mark.asyncio
async def test_jarvis_asked_which_model_changes_nothing(make_studio, tmp_path):
    studio, _ = make_studio(
        jarvis_script(
            tool_reply("agent_model", {"agent": "Builder", "model": "local/other"}),
            LLMReply(text="The Builder uses its usual model."),
        )
    )
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None

    await studio.main_say("which model is the builder using", background=False)

    after = await studio.agent_by_name("Builder")
    assert after is not None and after.model == builder.model
    learned = (tmp_path / "playbook" / "agent_model.md").read_text()
    assert '"model"' not in learned.split("## Learned", 1)[1]


@pytest.mark.asyncio
async def test_jarvis_adds_a_to_do_without_a_made_up_time(make_studio):
    studio, _ = make_studio(
        jarvis_script(
            tool_reply("todo", {"action": "add", "text": "Buy eggs", "due": "at 9am"}),
            LLMReply(text="Added."),
        )
    )
    await studio.ensure_defaults()

    await studio.main_say("add buy eggs to my list", background=False)

    [item] = await studio.todos()
    assert item.text == "Buy eggs" and item.due_at is None
