"""OpenAI Chat Completions on /v1/chat/completions, for the many AI tools that
speak it (Cursor, Continue, Cline, Aider, OpenCode, Open WebUI, ...)."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from free_claude_code.api.openai_chat import _events, to_messages_request
from free_claude_code.application.errors import InvalidRequestError
from free_claude_code.config.settings import Settings
from free_claude_code.core.failures import ExecutionFailure, FailureKind
from free_claude_code.providers.nvidia_nim import NvidiaNimProvider
from tests.api.support import create_test_app

CALLS: list[tuple[tuple, dict]] = []


def _sse(kind: str, data: dict) -> str:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **data})}\n\n"


async def _answer_with_a_tool(*args, **kwargs):
    CALLS.append((args, kwargs))
    yield _sse(
        "message_start",
        {
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "m",
                "usage": {"input_tokens": 12, "output_tokens": 0},
            }
        },
    )
    yield _sse(
        "content_block_start",
        {"index": 0, "content_block": {"type": "text", "text": ""}},
    )
    # A character split across two pieces must survive.
    yield _sse(
        "content_block_delta",
        {"index": 0, "delta": {"type": "text_delta", "text": "Looking up Paris ☀"}},
    )
    yield _sse("content_block_stop", {"index": 0})
    yield _sse(
        "content_block_start",
        {
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "get_weather",
                "input": {},
            },
        },
    )
    for piece in ('{"city": ', '"Paris"}'):
        yield _sse(
            "content_block_delta",
            {"index": 1, "delta": {"type": "input_json_delta", "partial_json": piece}},
        )
    yield _sse("content_block_stop", {"index": 1})
    yield _sse(
        "message_delta",
        {"delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 9}},
    )
    yield _sse("message_stop", {})


async def _busy(*args, **kwargs):
    CALLS.append((args, kwargs))
    raise ExecutionFailure(
        kind=FailureKind.RATE_LIMIT,
        status_code=429,
        message="upstream is busy",
        retryable=True,
    )
    yield "unreachable"


@pytest.fixture
def provider():
    fake = MagicMock(spec=NvidiaNimProvider)
    fake.stream_messages = _answer_with_a_tool
    return fake


@pytest.fixture
def client(provider):
    with (
        patch("free_claude_code.api.routes.resolve_provider", return_value=provider),
        TestClient(create_test_app(Settings())) as test_client,
    ):
        yield test_client


ASK = {
    "model": "claude-sonnet-4-20250514",
    "messages": [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Weather in Paris?"},
    ],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        }
    ],
}


def test_a_reply_comes_back_as_one_chat_completion(client: TestClient):
    CALLS.clear()
    response = client.post("/v1/chat/completions", json=ASK)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["object"] == "chat.completion" and body["id"].startswith("chatcmpl-")
    choice = body["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] == "Looking up Paris ☀"
    (call,) = choice["message"]["tool_calls"]
    assert call["id"] == "toolu_1" and call["function"]["name"] == "get_weather"
    assert json.loads(call["function"]["arguments"]) == {"city": "Paris"}
    assert body["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 9,
        "total_tokens": 21,
    }
    routed = CALLS[0][0][0]
    assert routed.tools[0].name == "get_weather"
    assert response.headers["x-request-id"] == response.headers["request-id"]


def test_a_streamed_reply_comes_back_as_chunks(client: TestClient):
    response = client.post(
        "/v1/chat/completions",
        json={**ASK, "stream": True, "stream_options": {"include_usage": True}},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    lines = [
        line[6:] for line in response.text.split("\n") if line.startswith("data: ")
    ]
    assert lines[-1] == "[DONE]"
    chunks = [json.loads(line) for line in lines[:-1]]
    deltas = [c["choices"][0]["delta"] for c in chunks if c["choices"]]
    assert deltas[0] == {"role": "assistant", "content": ""}
    assert "".join(d.get("content", "") for d in deltas) == "Looking up Paris ☀"
    calls = [d["tool_calls"][0] for d in deltas if "tool_calls" in d]
    assert calls[0]["id"] == "toolu_1" and calls[0]["index"] == 0
    assert calls[0]["function"]["name"] == "get_weather"
    arguments = "".join(c["function"].get("arguments", "") for c in calls)
    assert json.loads(arguments) == {"city": "Paris"}
    finishes = [c["choices"][0]["finish_reason"] for c in chunks if c["choices"]]
    assert finishes[-1] == "tool_calls"
    assert chunks[-1]["choices"] == [] and chunks[-1]["usage"]["total_tokens"] == 21


def test_a_failure_comes_back_in_openais_error_shape(client: TestClient, provider):
    provider.stream_messages = _busy
    response = client.post("/v1/chat/completions", json=ASK)
    assert response.status_code == 429
    error = response.json()["error"]
    assert "busy" in error["message"] and error["type"]

    bad = client.post("/v1/chat/completions", content=b"not json")
    assert bad.status_code == 400
    assert bad.json()["error"]["type"] == "invalid_request_error"
    empty = client.post("/v1/chat/completions", json={"model": "m", "messages": []})
    assert empty.status_code == 400 and "messages" in empty.json()["error"]["message"]


def test_probes_answer(client: TestClient):
    for response in (
        client.head("/v1/chat/completions"),
        client.options("/v1/chat/completions"),
    ):
        assert response.status_code == 204 and "POST" in response.headers["Allow"]


def test_a_conversation_with_tools_and_pictures_is_translated():
    request = to_messages_request(
        {
            "model": "llamacpp/qwen3-4b",
            "max_completion_tokens": 300,
            "stop": "END",
            "tool_choice": "required",
            "response_format": {"type": "json_object"},
            "tools": ASK["tools"],
            "messages": [
                {"role": "developer", "content": "Be brief."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is this?"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,AAAA"},
                        },
                    ],
                },
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_a",
                            "type": "function",
                            "function": {"name": "look", "arguments": '{"x": 1}'},
                        },
                        {
                            "id": "call_b",
                            "type": "function",
                            "function": {"name": "look", "arguments": "not json"},
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": "call_a", "content": "a cat"},
                {"role": "tool", "tool_call_id": "call_b", "content": "a hat"},
                {"role": "user", "content": "Thanks"},
            ],
        }
    )

    assert request.max_tokens == 300 and request.stop_sequences == ["END"]
    assert request.tool_choice == {"type": "any"}
    assert isinstance(request.system, str) and "Be brief." in request.system
    assert "JSON" in request.system
    turns = request.model_dump(exclude_none=True)["messages"]
    # Both tool results and the next user line are one user turn.
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    image = turns[0]["content"][1]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    first, second = turns[1]["content"]
    assert first["input"] == {"x": 1} and second["input"] == {"_raw": "not json"}
    results = [b for b in turns[2]["content"] if b["type"] == "tool_result"]
    assert [r["tool_use_id"] for r in results] == ["call_a", "call_b"]


@pytest.mark.parametrize(
    ("body", "words"),
    [
        ({"messages": [{"role": "user", "content": "hi"}]}, "model"),
        ({"model": "m", "messages": "hi"}, "messages"),
        (
            {"model": "m", "n": 2, "messages": [{"role": "user", "content": "hi"}]},
            "n=1",
        ),
        ({"model": "m", "messages": [{"role": "robot", "content": "hi"}]}, "role"),
        ({"model": "m", "messages": [{"role": "system", "content": "hi"}]}, "user"),
    ],
)
def test_bad_requests_say_what_is_wrong(body, words):
    with pytest.raises(InvalidRequestError, match=words):
        to_messages_request(body)


def test_events_survive_a_character_split_across_pieces():
    data = 'data: {"type": "x", "text": "☀"}\n\n'.encode()
    cut = data.index("☀".encode()) + 1

    async def pieces():
        yield data[:cut]
        yield data[cut:]

    async def collect():
        return [event async for event in _events(pieces())]

    assert asyncio.run(collect()) == [{"type": "x", "text": "☀"}]
