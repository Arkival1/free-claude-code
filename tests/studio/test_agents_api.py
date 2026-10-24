"""Other apps talk to Jarvis and the team the OpenAI way."""

import json

import httpx
import pytest

from free_claude_code.core.anthropic.task_policy import (
    allow_background_subagents,
    normalize_task_arguments,
)
from free_claude_code.studio.llm import LLMReply
from tests.api.support import create_test_app


def test_subagents_stay_in_the_foreground_unless_allowed():
    try:
        kept = {"prompt": "x", "run_in_background": True}
        normalize_task_arguments(kept)
        assert kept["run_in_background"] is False
        allow_background_subagents(True)
        free = {"prompt": "x", "run_in_background": True}
        normalize_task_arguments(free)
        assert free["run_in_background"] is True
    finally:
        allow_background_subagents(False)


def respond(system: str, prompt: str):
    if "the user's main AI" in system:
        return LLMReply(text=f"Jarvis heard: {prompt}")
    return LLMReply(text=f"Agent heard: {prompt}")


@pytest.mark.asyncio
async def test_the_team_answers_through_an_openai_style_api(make_studio):
    studio, _ = make_studio(respond)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            models = (await client.get("/studio/v1/models")).json()["data"]
            names = {model["id"] for model in models}
            assert {"jarvis", "builder", "coder", "lab", "researcher"} <= names

            reply = await client.post(
                "/studio/v1/chat/completions",
                json={
                    "model": "jarvis",
                    "messages": [
                        {"role": "system", "content": "be nice"},
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": "hello there"}],
                        },
                    ],
                },
            )
            body = reply.json()
            assert body["object"] == "chat.completion" and body["model"] == "jarvis"
            assert body["choices"][0]["message"]["content"].startswith("Jarvis heard")

            helper = await client.post(
                "/studio/v1/chat/completions",
                json={
                    "model": "Helper",
                    "messages": [{"role": "user", "content": "plan my day"}],
                },
            )
            assert (
                "Agent heard: plan my day"
                in helper.json()["choices"][0]["message"]["content"]
            )

            streamed = await client.post(
                "/studio/v1/chat/completions",
                json={
                    "model": "helper",
                    "stream": True,
                    "user": "phone",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            events = [
                line[6:]
                for line in streamed.text.splitlines()
                if line.startswith("data: ")
            ]
            assert events[-1] == "[DONE]"
            first = json.loads(events[0])
            assert first["choices"][0]["delta"]["content"].startswith("Agent heard")

            missing = await client.post(
                "/studio/v1/chat/completions",
                json={
                    "model": "nobody",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            assert missing.status_code == 404 and "Agents:" in missing.json()["detail"]
            empty = await client.post(
                "/studio/v1/chat/completions",
                json={
                    "model": "jarvis",
                    "messages": [{"role": "user", "content": " "}],
                },
            )
            assert empty.status_code == 400
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()

    chats = [c.title for c in await studio.chats()]
    assert "API · default" in chats and "API · phone" in chats
