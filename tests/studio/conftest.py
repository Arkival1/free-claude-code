"""Explicit doubles for Studio tests: no network, no real models."""

import inspect
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest

from free_claude_code.application.web_tools.ports import WebFetchEgressPolicy
from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject
from free_claude_code.core.web_tools import WebFetchResult, WebSearchResult
from free_claude_code.studio.llm import (
    ChatMessage,
    LLMReply,
    StudioModelRouter,
    ToolCall,
    ToolSpec,
)
from free_claude_code.studio.service import StudioService
from free_claude_code.studio.store import StudioStore

OFFLINE_SEARCH = httpx.MockTransport(
    lambda request: httpx.Response(503, json={"error": "tests stay offline"})
)
"""Answers every search API call, so no Studio test reaches the network."""


class ScriptedLLM:
    """Return queued replies in order and record every call it received."""

    def __init__(
        self,
        replies: Sequence[LLMReply | str] | Callable[[str, str], object],
    ) -> None:
        self._scripted = replies
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str = "",
        tools: Sequence[ToolSpec] = (),
        temperature: float = 0.2,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> LLMReply:
        last = messages[-1].content if messages else ""
        self.calls.append(
            {
                "system": system,
                "prompt": last,
                "model": model,
                "tools": [tool.name for tool in tools],
                "messages": list(messages),
            }
        )
        if callable(self._scripted):
            reply = self._scripted(system, last)
            if inspect.isawaitable(reply):
                reply = await reply
        elif self._scripted:
            index = min(len(self.calls) - 1, len(self._scripted) - 1)
            reply = self._scripted[index]
        else:
            reply = "(empty)"
        return reply if isinstance(reply, LLMReply) else LLMReply(text=str(reply))


class RecordingWebTools:
    """Serve canned search and fetch results without leaving the process."""

    def __init__(self) -> None:
        self.searches: list[str] = []
        self.fetches: list[str] = []

    async def search(self, query: str) -> list[WebSearchResult]:
        self.searches.append(query)
        return [
            WebSearchResult(title="Tide tables", url="https://example.test/tides"),
            WebSearchResult(title="Moon phases", url="https://example.test/moon"),
        ]

    async def fetch(self, url: str, *, egress: WebFetchEgressPolicy) -> WebFetchResult:
        self.fetches.append(url)
        return WebFetchResult(
            url=url,
            title="Tide tables",
            media_type="text/html",
            data="High tide is at 06:12 and 18:40.",
        )


def tool_reply(name: str, arguments: JsonObject, *, call_id: str = "call_1"):
    """Build a reply that asks for one tool call."""
    return LLMReply(
        tool_calls=(ToolCall(id=call_id, name=name, arguments=arguments),),
        stop_reason="tool_use",
    )


@pytest.fixture
def studio_settings() -> Callable[..., Settings]:
    def build(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "MODEL": "nvidia_nim/test-model",
            "STUDIO_ENABLED": True,
            "STUDIO_DEFAULT_MODEL": "nvidia_nim/test-model",
        }
        values.update(overrides)
        return Settings.model_validate(values)

    return build


@pytest.fixture
def store(tmp_path: Path) -> StudioStore:
    return StudioStore(tmp_path / "studio.db")


@pytest.fixture
def web_tools() -> RecordingWebTools:
    return RecordingWebTools()


@pytest.fixture
def make_studio(tmp_path, store, web_tools, studio_settings):
    """Build a Studio service driven by a scripted model."""

    def build(
        replies: Sequence[LLMReply | str] | Callable[[str, str], object] = (),
        **settings_overrides: object,
    ) -> tuple[StudioService, ScriptedLLM]:
        model = ScriptedLLM(replies)
        settings = studio_settings(**settings_overrides)
        service = StudioService(
            store=store,
            web_tools=web_tools,
            settings_provider=lambda: settings,
            models_dir=tmp_path / "models",
            sites_dir=tmp_path / "sites",
            router=StudioModelRouter(proxy=model, local=model),
            search_transport=OFFLINE_SEARCH,
            voice_transport=OFFLINE_SEARCH,
        )
        return service, model

    return build
