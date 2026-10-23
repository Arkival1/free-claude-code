"""Models on this PC get time to read a long agent prompt before answering."""

import json

import httpx
import pytest

from free_claude_code.config.provider_catalog import PROVIDER_CATALOG
from free_claude_code.providers.runtime.config import (
    LOCAL_READ_TIMEOUT,
    build_provider_config,
)
from free_claude_code.studio.llm import ChatMessage, ProxyLLM, StudioLLMError, ToolCall
from free_claude_code.studio.service import (
    LOCAL_MODEL_SECONDS,
    SERVER_MODEL_SECONDS,
    _on_this_pc,
    _proxy_timeout,
)


def test_local_models_get_minutes_and_servers_keep_their_limit():
    assert _proxy_timeout("llamacpp/qwen3-4b") == LOCAL_MODEL_SECONDS
    assert _proxy_timeout("lmstudio/some-model") == LOCAL_MODEL_SECONDS
    assert _proxy_timeout("nvidia_nim/meta/llama-3.3-70b") == SERVER_MODEL_SECONDS
    assert LOCAL_MODEL_SECONDS >= 900


def test_the_proxy_waits_longer_for_a_model_on_this_pc(studio_settings):
    settings = studio_settings()
    local = build_provider_config(PROVIDER_CATALOG["llamacpp"], settings)
    assert local.http_read_timeout >= LOCAL_READ_TIMEOUT
    server = build_provider_config(PROVIDER_CATALOG["lmstudio"], settings)
    assert server.http_read_timeout >= LOCAL_READ_TIMEOUT


@pytest.mark.asyncio
async def test_a_timeout_says_so_instead_of_nothing():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    client = ProxyLLM(
        base_url="http://proxy.test",
        default_model="llamacpp/qwen3-4b",
        transport=httpx.MockTransport(slow),
        timeout_for=_proxy_timeout,
    )
    with pytest.raises(StudioLLMError, match=r"took longer than 1800 s.*ReadTimeout"):
        await client.complete([ChatMessage(role="user", content="hi")])


def _events(*events: dict) -> bytes:
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()


STREAMED = _events(
    {
        "type": "message_start",
        "message": {"model": "qwen3-4b", "usage": {"input_tokens": 9}},
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "Writing "},
    },
    {"type": "ping"},
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "the page."},
    },
    {"type": "content_block_stop", "index": 0},
    {
        "type": "content_block_start",
        "index": 1,
        "content_block": {
            "type": "tool_use",
            "id": "tu_1",
            "name": "write_file",
            "input": {},
        },
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": '{"path": "index'},
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {
            "type": "input_json_delta",
            "partial_json": '.html", "content": "<h1>Hi</h1>"}',
        },
    },
    {"type": "content_block_stop", "index": 1},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use"},
        "usage": {"output_tokens": 40},
    },
    {"type": "message_stop"},
)


@pytest.mark.asyncio
async def test_a_model_on_this_pc_streams_so_a_long_page_is_not_cut_off():
    # The limit is then the longest silence, not the whole reply.
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        if not sent[-1].get("stream"):
            return httpx.Response(200, json={"content": []})
        return httpx.Response(
            200, content=STREAMED, headers={"content-type": "text/event-stream"}
        )

    client = ProxyLLM(
        base_url="http://proxy.test",
        default_model="llamacpp/qwen3-4b",
        transport=httpx.MockTransport(handler),
        timeout_for=_proxy_timeout,
        stream_for=_on_this_pc,
    )
    reply = await client.complete([ChatMessage(role="user", content="build it")])

    assert sent[0]["stream"] is True
    assert reply.text == "Writing the page."
    assert reply.tool_calls == (
        ToolCall(
            id="tu_1",
            name="write_file",
            arguments={"path": "index.html", "content": "<h1>Hi</h1>"},
        ),
    )
    assert reply.stop_reason == "tool_use"
    assert reply.usage == {"input_tokens": 9, "output_tokens": 40}
    assert reply.model == "qwen3-4b"

    # Server models answer all at once, as before.
    await client.complete(
        [ChatMessage(role="user", content="hi")], model="nvidia_nim/m"
    )
    assert "stream" not in sent[1]


@pytest.mark.asyncio
async def test_a_streamed_call_reports_silence_errors_and_plain_answers():
    def silent(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    def broken(request: httpx.Request) -> httpx.Response:
        body = _events(
            {"type": "message_start", "message": {"model": "m"}},
            {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}},
        )
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    def whole(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": "All at once."}]}
        )

    def client_for(handler) -> ProxyLLM:
        return ProxyLLM(
            base_url="http://proxy.test",
            default_model="llamacpp/qwen3-4b",
            transport=httpx.MockTransport(handler),
            timeout_for=_proxy_timeout,
            stream_for=_on_this_pc,
        )

    hello = [ChatMessage(role="user", content="hi")]
    with pytest.raises(StudioLLMError, match=r"sent nothing for 1800 s.*ReadTimeout"):
        await client_for(silent).complete(hello)
    with pytest.raises(StudioLLMError, match="failed mid-reply: busy"):
        await client_for(broken).complete(hello)
    assert (await client_for(whole).complete(hello)).text == "All at once."
    assert _on_this_pc("lmstudio/some-model") and not _on_this_pc("nvidia_nim/m")


@pytest.mark.asyncio
async def test_a_server_model_streams_too_so_a_whole_site_is_not_cut_off(make_studio):
    # A server model writing a whole website takes minutes; the limit is the
    # longest silence, so it isn't cut off while words are still coming.
    from free_claude_code.studio.service import _streams

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, content=STREAMED, headers={"content-type": "text/event-stream"}
        )

    client = ProxyLLM(
        base_url="http://proxy.test",
        default_model="nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b",
        transport=httpx.MockTransport(handler),
        timeout_for=_proxy_timeout,
        stream_for=_streams,
    )
    await client.complete([ChatMessage(role="user", content="build the site")])
    assert sent[0]["stream"] is True
    studio, _ = make_studio([])
    router = studio._build_router(studio.settings)
    assert router._proxy._stream_for("nvidia_nim/x") is True


@pytest.mark.asyncio
async def test_a_reply_may_wait_its_turn_but_not_go_quiet_once_it_starts(
    monkeypatch,
):
    # FCC's proxy queues a request while the provider's few slots are busy
    # and sends nothing until the model starts: that wait isn't a dead
    # model. Once the reply flows, a long silence still is.
    import asyncio

    from free_claude_code.studio import llm

    monkeypatch.setattr(llm, "REPLY_START_SECONDS", 2.0)

    async def queued(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.5)  # longer than the silence limit
        return httpx.Response(
            200, content=STREAMED, headers={"content-type": "text/event-stream"}
        )

    async def stalls(request: httpx.Request) -> httpx.Response:
        async def body():
            cut = STREAMED.index(b"\n\n") + 2  # one whole event first
            yield STREAMED[:cut]
            await asyncio.sleep(0.6)
            yield STREAMED[cut:]

        return httpx.Response(
            200, content=body(), headers={"content-type": "text/event-stream"}
        )

    def client_for(handler) -> ProxyLLM:
        return ProxyLLM(
            base_url="http://proxy.test",
            default_model="nvidia_nim/m",
            transport=httpx.MockTransport(handler),
            timeout_for=lambda model: 0.2,
            stream_for=lambda model: True,
        )

    hello = [ChatMessage(role="user", content="hi")]
    assert (await client_for(queued).complete(hello)).text
    with pytest.raises(StudioLLMError, match="sent nothing for"):
        await client_for(stalls).complete(hello)


@pytest.mark.asyncio
async def test_the_reply_start_wait_is_set_and_errors_name_the_real_limit(
    monkeypatch,
):
    import asyncio

    from free_claude_code.studio import llm

    limits: list[dict] = []

    def records(request: httpx.Request) -> httpx.Response:
        limits.append(request.extensions["timeout"])
        return httpx.Response(
            200, content=STREAMED, headers={"content-type": "text/event-stream"}
        )

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("", request=request)

    async def slow_json(request: httpx.Request) -> httpx.Response:
        async def body():
            await asyncio.sleep(0.6)
            yield b'{"content": [{"type": "text", "text": "late"}]}'

        return httpx.Response(
            200, content=body(), headers={"content-type": "application/json"}
        )

    def client_for(handler, seconds: float) -> ProxyLLM:
        return ProxyLLM(
            base_url="http://proxy.test",
            default_model="nvidia_nim/m",
            transport=httpx.MockTransport(handler),
            timeout_for=lambda model: seconds,
            stream_for=lambda model: True,
        )

    hello = [ChatMessage(role="user", content="hi")]
    await client_for(records, 420).complete(hello)
    assert limits[0]["read"] == llm.REPLY_START_SECONDS
    assert limits[0]["connect"] == 420
    with pytest.raises(StudioLLMError, match=r"for 420 s \(ConnectTimeout\)"):
        await client_for(unreachable, 420).complete(hello)
    with pytest.raises(StudioLLMError, match="sent nothing for"):
        await client_for(slow_json, 0.2).complete(hello)
