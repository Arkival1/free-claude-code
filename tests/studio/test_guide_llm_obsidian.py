"""The guide, the wire formats, and the Obsidian mirror."""

import json
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio.guide import (
    GuideAssistant,
    GuideState,
    knowledge_text,
    match_topics,
    offline_answer,
)
from free_claude_code.studio.llm import (
    ChatMessage,
    LocalOpenAILLM,
    ProxyLLM,
    StudioLLMError,
    StudioModelRouter,
    ToolCall,
    ToolSpec,
    parse_tool_directive,
    tool_protocol_instructions,
)
from free_claude_code.studio.models import Agent, Chat, Course, ExamQuestion, Lesson
from free_claude_code.studio.obsidian import ObsidianVault, candidate_vaults, note_name
from tests.studio.conftest import ScriptedLLM

TOOLS = (
    ToolSpec(
        name="web_search",
        description="Search the web.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    ),
)


def test_local_model_references_route_to_the_local_client():
    proxy = ScriptedLLM(["proxy"])
    local = ScriptedLLM(["local"])
    router = StudioModelRouter(proxy=proxy, local=local)

    assert router.client_for("local/qwen3-0.6b") == (local, "qwen3-0.6b")
    assert router.client_for("groq/llama-3.3") == (proxy, "groq/llama-3.3")


def test_text_tool_protocol_round_trip():
    instructions = tool_protocol_instructions(TOOLS)
    assert "web_search" in instructions

    call, final = parse_tool_directive(
        '{"tool": "web_search", "arguments": {"query": "tides"}}'
    )
    assert call is not None and call.name == "web_search"
    assert call.arguments == {"query": "tides"}
    assert final is None

    call, final = parse_tool_directive('Sure.\n```json\n{"final": "All done"}\n```')
    assert call is None and final == "All done"

    assert parse_tool_directive("just prose") == (None, None)


@pytest.mark.asyncio
async def test_proxy_client_speaks_anthropic_messages():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode("utf-8")
        captured["key"] = request.headers.get("x-api-key", "")
        return httpx.Response(
            200,
            json={
                "model": "test",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "Looking that up."},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "web_search",
                        "input": {"query": "tides"},
                    },
                ],
                "usage": {"input_tokens": 12},
            },
        )

    client = ProxyLLM(
        base_url="http://127.0.0.1:8082",
        token="secret",
        default_model="p/m",
        transport=httpx.MockTransport(handler),
    )
    reply = await client.complete(
        [ChatMessage.user("when is high tide?")],
        system="be brief",
        tools=TOOLS,
    )

    assert captured["path"] == "/v1/messages"
    assert captured["key"] == "secret"
    assert '"input_schema"' in captured["body"]
    assert reply.text == "Looking that up."
    assert reply.tool_calls == (
        ToolCall(id="tu_1", name="web_search", arguments={"query": "tides"}),
    )
    assert reply.usage == {"input_tokens": 12}


@pytest.mark.asyncio
async def test_local_client_falls_back_to_the_text_protocol():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "tiny",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"tool": "web_search", "arguments": {"query": "tides"}}',
                        },
                    }
                ],
            },
        )

    client = LocalOpenAILLM(
        base_url="http://127.0.0.1:1234/v1",
        transport=httpx.MockTransport(handler),
    )
    reply = await client.complete([ChatMessage.user("find tides")], tools=TOOLS)

    assert reply.stop_reason == "tool_use"
    assert reply.tool_calls[0].name == "web_search"


@pytest.mark.asyncio
async def test_local_client_sends_tool_history_as_plain_turns():
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "tiny",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"final": "ok"}'},
                    }
                ],
            },
        )

    client = LocalOpenAILLM(
        base_url="http://127.0.0.1:1234/v1",
        transport=httpx.MockTransport(handler),
    )
    call = ToolCall(id="t1", name="web_search", arguments={"query": "tides"})
    reply = await client.complete(
        [
            ChatMessage.user("find tides"),
            ChatMessage(role="assistant", content="", tool_calls=(call,)),
            ChatMessage(role="tool", content="High tide 06:12", tool_call_id="t1"),
            ChatMessage.user("and the low tide?"),
        ],
        system="Be brief.",
        tools=TOOLS,
    )

    assert reply.text == "ok"
    wire = sent[0]["messages"]
    assert isinstance(wire, list)
    assert [turn["role"] for turn in wire] == ["system", "user", "assistant", "user"]
    assert wire[2]["content"] == (
        '{"tool": "web_search", "arguments": {"query": "tides"}}'
    )
    assert wire[3]["content"] == (
        "Result of web_search:\nHigh tide 06:12\n\nand the low tide?"
    )
    assert all("tool_calls" not in turn for turn in wire)


@pytest.mark.asyncio
async def test_unreachable_endpoints_raise_a_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = LocalOpenAILLM(
        base_url="http://127.0.0.1:1234/v1",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(StudioLLMError, match="500"):
        await client.complete([ChatMessage.user("hi")])


def test_guide_matches_questions_to_topics():
    assert "Light tuning" in [
        topic.title for topic in match_topics("how do I fine-tune on my iphone?")
    ]
    assert "Teacher and student" in [
        topic.title for topic in match_topics("can one ai teach another ai?")
    ]
    assert match_topics("zzzz") == ()


def test_guide_answers_offline_before_any_model_exists():
    answer = offline_answer("how do local models work?", GuideState())

    assert answer.offline is True
    assert "local/" in answer.text or "Models tab" in answer.text
    assert answer.route == "/studio#models"
    assert "Obsidian" in knowledge_text()


@pytest.mark.asyncio
async def test_guide_uses_the_small_model_when_it_is_ready(make_studio):
    studio, model = make_studio(["Tap Models, then Get on the first row."])
    state_ready = GuideState(guide_model="local/tiny", guide_model_ready=True)
    guide = GuideAssistant(router=studio._router, model="local/tiny")

    answer = await guide.answer("how do I download a model?", state_ready)

    assert answer.offline is False
    assert answer.text == "Tap Models, then Get on the first row."
    assert "This install right now" in str(model.calls[0]["system"])


@pytest.mark.asyncio
async def test_guide_answers_offline_when_the_model_is_missing(make_studio):
    studio, model = make_studio(["never reached"])
    guide = GuideAssistant(router=studio._router, model="local/tiny")

    answer = await guide.answer("how do I install this on my iphone?", GuideState())

    assert answer.offline is True
    assert model.calls == []


def test_vault_note_names_are_safe():
    assert note_name("Class: Tides / Part 2") == "Class Tides Part 2"
    assert note_name("///") == "note"
    assert any(
        "iCloud~md~obsidian" in str(path) for path in candidate_vaults(Path("/home/x"))
    )


@pytest.mark.asyncio
async def test_vault_writes_chats_classes_and_memory(tmp_path, store):
    vault = ObsidianVault(tmp_path / "vault", folder="FCC Studio")
    agent = Agent.model_validate({"name": "Student", "model": "m"})
    chat = Chat.model_validate({"title": "Tide chat"})
    await store.put(agent)
    await store.put(chat)
    await store.append_message(
        chat_id=chat.id, role="user", text="When is high tide?", author="user"
    )
    messages = await store.transcript(chat.id)

    chat_note = await vault.export_chat(chat, messages, agent=agent)
    assert "type: fcc-chat" in chat_note.read_text(encoding="utf-8")
    assert "When is high tide?" in chat_note.read_text(encoding="utf-8")

    course = Course.model_validate(
        {
            "topic": "Tides",
            "teacher_agent_id": "t",
            "student_agent_id": agent.id,
            "chat_id": chat.id,
            "score": 0.9,
            "status": "passed",
        }
    )
    lesson = Lesson.model_validate(
        {"course_id": course.id, "ordinal": 1, "topic": "Moon", "notes": "It pulls."}
    )
    question = ExamQuestion.model_validate(
        {
            "course_id": course.id,
            "ordinal": 1,
            "prompt": "What causes tides?",
            "answer": "The moon.",
            "score": 0.9,
        }
    )
    class_note = await vault.export_course(
        course, lessons=[lesson], questions=[question], student=agent
    )
    body = class_note.read_text(encoding="utf-8")
    assert "# Class: Tides" in body
    assert "90%" in body

    status = await vault.status()
    assert status.configured and status.writable
    assert status.note_count >= 2


@pytest.mark.asyncio
async def test_vault_inbox_notes_import_into_memory(tmp_path, make_studio):
    inbox = tmp_path / "vault/FCC Studio/Inbox"
    inbox.mkdir(parents=True)
    (inbox / "notes.md").write_text(
        "# Research\n- Tides are caused by the moon\n- short\n", encoding="utf-8"
    )
    studio, _ = make_studio([], STUDIO_OBSIDIAN_VAULT=str(tmp_path / "vault"))
    agent = await studio.create_agent(name="Reader", tools=[])

    imported = await studio.import_vault_notes(agent.id)

    texts = [entry.text for entry in await studio.memories(agent.id)]
    assert imported >= 1
    assert "Tides are caused by the moon" in texts
    assert "short" not in texts


@pytest.mark.asyncio
async def test_unconfigured_vault_is_reported_not_raised(make_studio):
    studio, _ = make_studio([])
    status = await studio.vault_status()
    assert status.configured is False
    assert status.path == ""


def test_note_names_survive_windows():
    assert note_name("CON") == "CON note"
    assert note_name("Trailing dots...") == "Trailing dots"
    assert any("OneDrive" in str(path) for path in candidate_vaults(Path("C:/Users/x")))
