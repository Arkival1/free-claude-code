"""Agents answer sooner without changing what they say or do."""

import asyncio

import pytest

from free_claude_code.application.web_tools.ports import WebFetchResult
from free_claude_code.studio.llm import LLMReply, ToolCall


def two_fetches() -> LLMReply:
    return LLMReply(
        text="",
        tool_calls=(
            ToolCall(id="a", name="web_fetch", arguments={"url": "https://a.test"}),
            ToolCall(id="b", name="web_fetch", arguments={"url": "https://b.test"}),
        ),
        stop_reason="tool_use",
    )


@pytest.mark.asyncio
async def test_independent_look_ups_run_at_the_same_time(make_studio, monkeypatch):
    studio, model = make_studio([two_fetches(), "Both read."])
    running = 0
    most = 0

    async def fetch(url, *, egress):
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.05)
        running -= 1
        return WebFetchResult(
            url=url, title=url, media_type="text/plain", data=f"page {url}"
        )

    monkeypatch.setattr(studio._web_tools, "fetch", fetch)
    agent = await studio.create_agent(name="Reader", tools=["web_fetch"])
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "read both")

    assert most == 2, "the two pages were read together"
    tools = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert "a.test" in tools[0].text and "b.test" in tools[1].text, "order kept"
    fed_back = model.calls[1]["messages"][-2:]
    assert [message.tool_call_id for message in fed_back] == ["a", "b"]


@pytest.mark.asyncio
async def test_anything_that_changes_files_still_runs_one_at_a_time(make_studio):
    reply = LLMReply(
        text="",
        tool_calls=(
            ToolCall(
                id="w",
                name="write_file",
                arguments={"path": "a.txt", "content": "one"},
            ),
            ToolCall(id="r", name="read_file", arguments={"path": "a.txt"}),
        ),
        stop_reason="tool_use",
    )
    studio, _ = make_studio([reply, "Done."])
    site = await studio.create_site(name="Notes")
    agent = await studio.create_agent(name="Writer", tools=["write_file", "read_file"])
    chat = await studio.create_chat(agent_id=agent.id, site_id=site.id)

    await studio.send(chat.id, "write then read")

    tools = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert tools[1].text.endswith("one"), "the read saw the write"


@pytest.mark.asyncio
async def test_instructions_stay_word_for_word_the_same_between_messages(make_studio):
    studio, model = make_studio(["First.", "Second."])
    agent = await studio.create_agent(name="Steady", tools=[])
    await studio.remember(agent.id, "The user likes tea.")
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "hello")
    await studio.remember(agent.id, "The user also likes cake.")
    await studio.send(chat.id, "what do I like?")

    first, second = model.calls
    assert first["system"] == second["system"]
    assert "likes cake" in second["memory"]
    earlier = second["messages"][0]
    assert earlier.content == "hello", "earlier messages are sent as they were"


@pytest.mark.asyncio
async def test_the_temperature_setting_reaches_every_agent(make_studio):
    studio, model = make_studio(["Warm."], STUDIO_AGENT_TEMPERATURE=0.7)
    agent = await studio.create_agent(name="Warm", tools=[])
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "hi")

    assert model.calls[0]["temperature"] == 0.7
