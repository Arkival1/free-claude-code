"""Local models answer sooner: a reusable prompt start and no hidden thinking."""

import json

import httpx
import pytest

from free_claude_code.studio.llm import (
    NO_THINK_SWITCH,
    ChatMessage,
    LocalOpenAILLM,
    ToolSpec,
    strip_thinking,
)

TOOL = ToolSpec(
    name="recall",
    description="Search memory.",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
)


def runtime(sent: list[dict], content: str = "Hello.") -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}], "model": "m"},
        )

    return httpx.MockTransport(answer)


@pytest.mark.asyncio
async def test_the_prompt_starts_with_what_never_changes():
    sent: list[dict] = []
    llm = LocalOpenAILLM(base_url="http://localhost:1234/v1", transport=runtime(sent))

    for memory in ("remembers A", "remembers B"):
        await llm.complete(
            [ChatMessage(role="user", content="hi")],
            system=f"You are Jarvis.\n\n{memory}",
            tools=(TOOL,),
        )

    first, second = (body["messages"][0]["content"] for body in sent)
    assert first.startswith("You can use tools.")
    assert first.endswith(NO_THINK_SWITCH)
    shared = len(first.split("remembers")[0])
    assert first[:shared] == second[:shared], "only the end differs between turns"
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent[0]["cache_prompt"] is True


@pytest.mark.asyncio
async def test_thinking_can_be_left_on():
    sent: list[dict] = []
    llm = LocalOpenAILLM(
        base_url="http://localhost:1234/v1", transport=runtime(sent), fast=lambda: False
    )

    await llm.complete([ChatMessage(role="user", content="hi")], system="Be brief.")

    assert "chat_template_kwargs" not in sent[0]
    assert NO_THINK_SWITCH not in sent[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_a_reasoning_models_thinking_never_reaches_the_user():
    sent: list[dict] = []
    llm = LocalOpenAILLM(
        base_url="http://localhost:1234/v1",
        transport=runtime(sent, "<think>The user greets me.</think>\n\nHello there."),
    )

    reply = await llm.complete([ChatMessage(role="user", content="hi")])

    assert reply.text == "Hello there."


def test_thinking_is_stripped_in_every_shape():
    assert strip_thinking("<think>a\nb</think>Answer") == "Answer"
    assert strip_thinking("opened in the prompt</think>\nAnswer") == "Answer"
    assert strip_thinking("<think>ran out of tokens") == ""
    assert strip_thinking("Plain answer.") == "Plain answer."
