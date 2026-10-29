"""Agents get web tools while the computer is online, and memory while it is not."""

import httpx
import pytest

from free_claude_code.studio.connectivity import (
    RECHECK_OFFLINE_SECONDS,
    RECHECK_ONLINE_SECONDS,
    Connectivity,
)
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.tools import WEB_TOOLS

from .conftest import tool_reply


class Network:
    """A switchable internet connection for the probe."""

    def __init__(self) -> None:
        self.up = True
        self.probes = 0

    def transport(self) -> httpx.MockTransport:
        def answer(request: httpx.Request) -> httpx.Response:
            self.probes += 1
            if not self.up:
                raise httpx.ConnectError("Name or service not known", request=request)
            return httpx.Response(204)

        return httpx.MockTransport(answer)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_the_check_is_cached_and_notices_changes():
    network, clock = Network(), Clock()
    link = Connectivity(transport=network.transport(), clock=clock)

    assert await link.check() is True
    network.up = False
    assert await link.check() is True, "cached while fresh"
    assert network.probes == 1

    clock.now += RECHECK_ONLINE_SECONDS
    assert await link.check() is False
    network.up = True
    clock.now += RECHECK_OFFLINE_SECONDS - 1
    assert await link.check() is False, "offline is rechecked sooner, but not yet"
    clock.now += 1
    assert await link.check() is True


@pytest.mark.asyncio
async def test_any_http_answer_counts_as_online():
    link = Connectivity(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    assert await link.check() is True


def swap_network(studio, network: Network, clock: Clock) -> None:
    studio._connectivity = Connectivity(transport=network.transport(), clock=clock)


@pytest.mark.asyncio
async def test_the_builder_searches_online_and_uses_memory_offline(make_studio):
    studio, model = make_studio(["Done.", "Done offline."])
    network, clock = Network(), Clock()
    swap_network(studio, network, clock)
    builder = await studio.create_agent(
        name="Bob", role="builder", tools=["write_file"]
    )
    chat = await studio.create_chat(agent_id=builder.id)

    await studio.send(chat.id, "build it")
    online_call = model.calls[-1]
    assert set(WEB_TOOLS) <= set(online_call["tools"])
    assert "connected to the internet" in str(online_call["system"])

    network.up = False
    clock.now += RECHECK_ONLINE_SECONDS
    await studio.send(chat.id, "keep going")
    offline_call = model.calls[-1]
    assert not set(WEB_TOOLS) & set(offline_call["tools"])
    assert "write_file" in offline_call["tools"]
    assert "offline right now" in str(offline_call["system"])
    console = await studio.main_console()
    assert console["systems"]["web"]["online"] is False

    network.up = True
    clock.now += RECHECK_OFFLINE_SECONDS
    await studio.send(chat.id, "and again")
    assert set(WEB_TOOLS) <= set(model.calls[-1]["tools"])


@pytest.mark.asyncio
async def test_a_failed_connection_pauses_web_tools_straight_away(
    make_studio, monkeypatch
):
    studio, model = make_studio(
        [tool_reply("web_fetch", {"url": "https://example.com"}), "Used memory."]
    )
    network, clock = Network(), Clock()
    swap_network(studio, network, clock)

    async def unreachable(url, *, egress):
        raise httpx.ConnectError("Network is unreachable")

    monkeypatch.setattr(studio._web_tools, "fetch", unreachable)
    agent = await studio.create_agent(name="Rae", role="builder")
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "read the page")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.data["failed"] is True
    assert "web tools are paused" in tool.text
    assert not studio._connectivity.online
    assert model.calls[-1]["tools"] == model.calls[0]["tools"], (
        "same turn keeps its list"
    )

    await studio.send(chat.id, "next")
    assert not set(WEB_TOOLS) & set(model.calls[-1]["tools"])


@pytest.mark.asyncio
async def test_web_access_off_still_wins_when_online(make_studio):
    studio, model = make_studio([LLMReply(text="ok")], STUDIO_WEB_ACCESS="off")
    agent = await studio.create_agent(name="Off", role="builder")
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "hi")

    assert not set(WEB_TOOLS) & set(model.calls[-1]["tools"])
    assert "offline right now" not in str(model.calls[-1]["system"])
