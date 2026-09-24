"""With no server key, agents use the model loaded on this PC instead of failing."""

import httpx
import pytest

from free_claude_code.studio import StudioService
from free_claude_code.studio.llm import LLMReply, LocalOpenAILLM, StudioModelRouter

from .conftest import OFFLINE_SEARCH


class FakeLocal:
    """A local runtime like LM Studio: several downloaded, one loaded."""

    def __init__(self, *, loaded: tuple[str, ...] | None = ("qwen-4b",)) -> None:
        self.served: tuple[str, ...] = ("tinyllama", "qwen-4b", "nomic-embed-text")
        self.loaded = loaded
        self.calls: list[str] = []

    async def list_models(self) -> tuple[str, ...]:
        return self.served

    async def loaded_models(self) -> tuple[str, ...] | None:
        return self.loaded

    async def complete(self, messages, *, system="", tools=(), **kwargs) -> LLMReply:
        self.calls.append(str(kwargs.get("model")))
        return LLMReply(text="Local here.")


class FakeServer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, messages, *, system="", tools=(), **kwargs) -> LLMReply:
        self.calls.append(str(kwargs.get("model")))
        return LLMReply(text="Server here.")


def build(tmp_path, store, web_tools, studio_settings, local=None, **overrides):
    values = {"STUDIO_DEFAULT_MODEL": None, **overrides}
    holder = {"settings": studio_settings(**values)}
    local = local or FakeLocal()
    server = FakeServer()
    studio = StudioService(
        store=store,
        web_tools=web_tools,
        settings_provider=lambda: holder["settings"],
        models_dir=tmp_path / "models",
        sites_dir=tmp_path / "sites",
        router=StudioModelRouter(proxy=server, local=local),
        search_transport=OFFLINE_SEARCH,
        voice_transport=OFFLINE_SEARCH,
    )
    return studio, local, server, holder


@pytest.mark.asyncio
async def test_jarvis_uses_the_loaded_local_model_when_the_server_has_no_key(
    tmp_path, store, web_tools, studio_settings
):
    studio, local, server, _ = build(tmp_path, store, web_tools, studio_settings)

    await studio.main_say("hello", background=False)

    assert local.calls == ["qwen-4b"], "the loaded one, not the first listed"
    assert server.calls == []
    console = await studio.main_console()
    assert console["systems"]["main_model"] == "local/qwen-4b"
    reply = [m for m in console["messages"] if m["role"] == "assistant"]
    assert reply[-1]["text"] == "Local here."


@pytest.mark.asyncio
async def test_without_a_loaded_list_the_first_chat_model_is_used(
    tmp_path, store, web_tools, studio_settings
):
    studio, local, _, _ = build(
        tmp_path, store, web_tools, studio_settings, local=FakeLocal(loaded=None)
    )

    await studio.main_say("hello", background=False)

    assert local.calls == ["tinyllama"]


@pytest.mark.asyncio
async def test_a_configured_server_model_is_left_alone(
    tmp_path, store, web_tools, studio_settings
):
    studio, local, server, _ = build(
        tmp_path, store, web_tools, studio_settings, NVIDIA_NIM_API_KEY="nvapi-x"
    )

    await studio.main_say("hello", background=False)

    assert server.calls == ["nvidia_nim/test-model"]
    assert local.calls == []


@pytest.mark.asyncio
async def test_a_local_model_that_is_not_on_this_pc_is_replaced(
    tmp_path, store, web_tools, studio_settings
):
    studio, local, _, _ = build(
        tmp_path,
        store,
        web_tools,
        studio_settings,
        STUDIO_MAIN_AGENT_MODEL="local/qwen3-0.6b",
    )

    await studio.main_say("hello", background=False)

    assert local.calls == ["qwen-4b"]
    assert await studio.effective_model("local/tinyllama") == "local/tinyllama"


@pytest.mark.asyncio
async def test_the_main_ai_model_setting_wins_after_creation(
    tmp_path, store, web_tools, studio_settings
):
    studio, local, _, holder = build(tmp_path, store, web_tools, studio_settings)
    first = await studio.main_agent()
    assert first.model == "nvidia_nim/test-model"

    holder["settings"] = studio_settings(
        STUDIO_DEFAULT_MODEL=None, STUDIO_MAIN_AGENT_MODEL="local/tinyllama"
    )
    main = await studio.main_agent()

    assert main.id == first.id and main.model == "local/tinyllama"
    assert main.local_only is True
    await studio.main_say("hi", background=False)
    assert local.calls == ["tinyllama"]


@pytest.mark.asyncio
async def test_starter_agents_follow_a_studio_default_set_later(
    tmp_path, store, web_tools, studio_settings
):
    studio, _, _, holder = build(tmp_path, store, web_tools, studio_settings)
    await studio.ensure_defaults()
    mine = await studio.create_agent(name="Mine", model="nvidia_nim/test-model")
    assert (await studio.agent_by_name("Builder")).model == "nvidia_nim/test-model"

    holder["settings"] = studio_settings(STUDIO_DEFAULT_MODEL="local/qwen-4b")
    await studio.ensure_defaults()

    for name in ("Builder", "Researcher", "Helper"):
        agent = await studio.agent_by_name(name)
        assert agent is not None and agent.model == "local/qwen-4b", name
    assert (await studio.agent(mine.id)).model == "nvidia_nim/test-model"


@pytest.mark.asyncio
async def test_lm_studio_says_which_model_is_loaded():
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v0/models"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "tinyllama", "type": "llm", "state": "not-loaded"},
                    {"id": "qwen-4b", "type": "vlm", "state": "loaded"},
                    {"id": "nomic-embed", "type": "embeddings", "state": "loaded"},
                ]
            },
        )

    lm_studio = LocalOpenAILLM(
        base_url="http://localhost:1234/v1", transport=httpx.MockTransport(answer)
    )
    assert await lm_studio.loaded_models() == ("qwen-4b",)

    other = LocalOpenAILLM(
        base_url="http://localhost:11434/v1",
        transport=httpx.MockTransport(lambda _: httpx.Response(404)),
    )
    assert await other.loaded_models() is None


@pytest.mark.asyncio
async def test_the_hud_sees_the_reply_while_it_is_written(
    tmp_path, store, web_tools, studio_settings
):
    import asyncio

    gate = asyncio.Event()

    class StreamingLocal(FakeLocal):
        async def complete_streaming(self, messages, *, on_text, **kwargs):
            on_text("Good eve")
            await gate.wait()
            on_text("Good evening, sir.")
            return LLMReply(text="Good evening, sir.")

    studio, *_ = build(
        tmp_path,
        store,
        web_tools,
        studio_settings,
        local=StreamingLocal(),
        STUDIO_MAIN_AGENT_MODEL="local/qwen-4b",
    )

    await studio.main_say("hello")
    for _ in range(100):
        console = await studio.main_console()
        if console["live"]:
            break
        await asyncio.sleep(0.01)
    assert console["live"] == "Good eve"
    main = await studio.main_agent()
    assert (await studio.agent_activity(main.id))["live"] == "Good eve"

    gate.set()
    await studio.wait_for_background()
    console = await studio.main_console()
    assert console["live"] == ""
    assert console["messages"][-1]["text"] == "Good evening, sir."
