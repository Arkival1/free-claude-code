"""Models on this PC get time to read a long agent prompt before answering."""

import httpx
import pytest

from free_claude_code.config.provider_catalog import PROVIDER_CATALOG
from free_claude_code.providers.runtime.config import (
    LOCAL_READ_TIMEOUT,
    build_provider_config,
)
from free_claude_code.studio.llm import ChatMessage, ProxyLLM, StudioLLMError
from free_claude_code.studio.service import (
    LOCAL_MODEL_SECONDS,
    SERVER_MODEL_SECONDS,
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
    with pytest.raises(StudioLLMError, match=r"took longer than 1200 s.*ReadTimeout"):
        await client.complete([ChatMessage(role="user", content="hi")])
