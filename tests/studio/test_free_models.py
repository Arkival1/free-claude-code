"""The free AI services the brain pickers offer."""

import httpx
import pytest

from free_claude_code.config.settings import Settings
from free_claude_code.studio.free_models import free_services
from tests.api.support import create_test_app


def by_id(services):
    return {str(service["id"]): service for service in services}


def test_freellmapi_choices_are_there_before_it_is_set_up():
    found = by_id(free_services(Settings.model_construct(), []))
    router = found["freellmapi"]
    assert router["ready"] is False
    assert [m["id"] for m in router["models"]] == [
        "freellmapi/auto",
        "freellmapi/auto:coding",
        "freellmapi/auto:smartest",
        "freellmapi/auto:fast",
    ]
    assert "paste the key" in str(router["setup"])
    assert found["groq"]["key_url"] == "https://console.groq.com/keys"


def test_ready_services_offer_their_listed_models():
    settings = Settings.model_construct(
        open_router_api_key="k", freellmapi_api_key="u", nvidia_nim_api_key="n"
    )
    listed = [
        "open_router/qwen/qwen3-coder:free",
        "open_router/openai/gpt-5",
        "freellmapi/gemini-2.5-flash",
        "freellmapi/auto",
        "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b",
    ]
    found = by_id(free_services(settings, listed))
    assert found["open_router"]["ready"] is True
    assert [m["id"] for m in found["open_router"]["models"]] == [
        "open_router/qwen/qwen3-coder:free"
    ]
    ids = [m["id"] for m in found["freellmapi"]["models"]]
    assert (
        ids.count("freellmapi/auto") == 1 and ids[-1] == "freellmapi/gemini-2.5-flash"
    )
    assert found["nvidia_nim"]["models"][0]["id"].startswith("nvidia_nim/")
    assert found["groq"]["ready"] is False and found["groq"]["models"] == []


@pytest.mark.asyncio
async def test_the_pickers_get_the_list_from_the_app(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/studio/api/models/free")
    assert response.status_code == 200
    names = [service["id"] for service in response.json()["services"]]
    assert names[0] == "freellmapi" and "groq" in names


def test_omniroute_and_the_free_list_providers_are_offered():
    found = by_id(free_services(Settings.model_construct(), []))
    assert [m["id"] for m in found["omniroute"]["models"]] == ["omniroute/auto"]
    for provider in (
        "kilo",
        "cohere",
        "zai_api",
        "cloudflare",
        "huggingface",
        "llm7",
        "ollama_cloud",
    ):
        assert provider in found and found[provider]["key_url"]
    kilo = by_id(
        free_services(
            Settings.model_construct(kilo_api_key="k"),
            [
                "kilo/nvidia/nemotron-3-ultra-550b-a55b:free",
                "kilo/anthropic/claude-opus",
            ],
        )
    )["kilo"]
    assert [m["id"] for m in kilo["models"]] == [
        "kilo/nvidia/nemotron-3-ultra-550b-a55b:free"
    ]


def test_cloudflare_is_ready_only_with_its_account_id_too():
    token_only = Settings.model_construct(cloudflare_api_token="t")
    assert not by_id(free_services(token_only, []))["cloudflare"]["ready"]
    both = Settings.model_construct(cloudflare_api_token="t", cloudflare_account_id="a")
    assert by_id(free_services(both, []))["cloudflare"]["ready"]
