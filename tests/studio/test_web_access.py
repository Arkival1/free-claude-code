"""Agents reach the internet through a keyed search API or DuckDuckGo."""

import json

import httpx
import pytest

from free_claude_code.core.web_tools import WebSearchResult
from free_claude_code.studio.llm import LLMReply, StudioModelRouter
from free_claude_code.studio.search import (
    SearchError,
    StudioSearch,
    detect_provider,
)
from free_claude_code.studio.service import StudioService
from tests.api.support import create_test_app

from .conftest import RecordingWebTools, ScriptedLLM, tool_reply


class BrokenWebTools(RecordingWebTools):
    async def search(self, query: str) -> list[WebSearchResult]:
        raise httpx.ConnectError("offline")


def api_server(seen: list[httpx.Request], *, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        host = request.url.host
        if host == "api.search.brave.com":
            return httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {
                                "title": "Tide <strong>tables</strong>",
                                "url": "https://tides.test/a",
                                "description": "High tide at <b>06:12</b> &amp; 18:40",
                            },
                            {"title": "bad", "url": "javascript:alert(1)"},
                        ]
                    }
                },
            )
        if host == "api.tavily.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Tides today",
                            "url": "https://tides.test/b",
                            "content": "The next high tide is 06:12.",
                        }
                    ]
                },
            )
        if host == "google.serper.dev":
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "Serper tides",
                            "link": "https://tides.test/c",
                            "snippet": "From Google.",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Searx", "url": "https://tides.test/d", "content": "x"}
                ]
            },
        )

    return httpx.MockTransport(handler)


def searcher(provider: str, *, key: str = "", base: str = "", **kwargs) -> StudioSearch:
    return StudioSearch(
        provider=provider,
        api_key=key,
        base_url=base,
        fallback=kwargs.pop("fallback", RecordingWebTools()),
        **kwargs,
    )


def test_auto_picks_the_service_from_the_key():
    assert detect_provider("auto", "tvly-abc", "") == "tavily"
    assert detect_provider("auto", "BSAxyz", "") == "brave"
    assert detect_provider("auto", "a" * 40, "") == "serper"
    assert detect_provider("auto", "", "http://localhost:8888") == "searxng"
    assert detect_provider("auto", "", "") == "duckduckgo"
    assert detect_provider("brave", "tvly-abc", "") == "brave"


@pytest.mark.asyncio
async def test_brave_results_come_back_clean():
    seen: list[httpx.Request] = []
    search = searcher("brave", key="BSAkey", transport=api_server(seen))

    report = await search.search("tides")

    assert report.provider == "brave"
    assert report.note == ""
    assert [hit.url for hit in report.hits] == ["https://tides.test/a"]
    assert report.hits[0].title == "Tide tables"
    assert report.hits[0].snippet == "High tide at 06:12 & 18:40"
    assert seen[0].headers["x-subscription-token"] == "BSAkey"
    assert seen[0].url.params["q"] == "tides"


@pytest.mark.asyncio
async def test_tavily_serper_and_searxng_answer_too():
    seen: list[httpx.Request] = []
    transport = api_server(seen)

    tavily = await searcher("auto", key="tvly-k", transport=transport).search("q")
    serper = await searcher("serper", key="s" * 8, transport=transport).search("q")
    searx = await searcher(
        "searxng", base="http://searx.local/", transport=transport
    ).search("q")

    assert tavily.hits[0].snippet == "The next high tide is 06:12."
    assert seen[0].headers["authorization"] == "Bearer tvly-k"
    assert json.loads(seen[0].content)["query"] == "q"
    assert serper.hits[0].url == "https://tides.test/c"
    assert seen[1].headers["x-api-key"] == "s" * 8
    assert searx.hits[0].title == "Searx"
    assert str(seen[2].url).startswith("http://searx.local/search?")
    assert seen[2].url.params["format"] == "json"


@pytest.mark.asyncio
async def test_a_rejected_key_falls_back_to_duckduckgo():
    fallback = RecordingWebTools()
    search = searcher(
        "tavily",
        key="tvly-bad",
        transport=api_server([], status=401),
        fallback=fallback,
    )

    report = await search.search("tides")

    assert report.provider == "duckduckgo"
    assert "Tavily rejected the API key (401)" in report.note
    assert fallback.searches == ["tides"]
    assert report.hits[0].url == "https://example.test/tides"


@pytest.mark.asyncio
async def test_missing_key_and_dead_fallback_explain_themselves():
    missing = await searcher("brave").search("tides")
    assert missing.provider == "duckduckgo"
    assert "Brave Search needs an API key" in missing.note

    dead = searcher(
        "duckduckgo",
        fallback=BrokenWebTools(),
        transport=api_server([], status=429),
        retry_delay=0,
    )
    with pytest.raises(SearchError, match="Set a search API key"):
        await dead.search("tides")


class EmptyWebTools(RecordingWebTools):
    async def search(self, query: str) -> list[WebSearchResult]:
        self.searches.append(query)
        return []


@pytest.mark.asyncio
async def test_an_empty_duckduckgo_is_retried_then_wikipedia_answers():
    seen: list[httpx.Request] = []

    def wiki(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "query": {
                    "search": [
                        {
                            "title": "Python (programming language)",
                            "snippet": 'a <span class="match">high-level</span> language',
                        }
                    ]
                }
            },
        )

    ddg = EmptyWebTools()
    search = searcher(
        "duckduckgo",
        fallback=ddg,
        transport=httpx.MockTransport(wiki),
        retry_delay=0,
    )

    report = await search.search("python language")

    assert ddg.searches == ["python language", "python language"]
    assert report.provider == "wikipedia"
    assert report.hits[0].url == (
        "https://en.wikipedia.org/wiki/Python_(programming_language)"
    )
    assert report.hits[0].snippet == "a high-level language"
    assert "Add a search API key" in report.note
    assert seen[0].url.params["srsearch"] == "python language"
    assert "FCC-Studio" in seen[0].headers["user-agent"]

    nothing = searcher(
        "duckduckgo",
        fallback=EmptyWebTools(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        retry_delay=0,
    )
    empty = await nothing.search("zzzz")
    assert empty.hits == ()
    assert "often blocks automated searches" in empty.note


@pytest.mark.asyncio
async def test_every_agent_can_search_by_default(make_studio):
    studio, model = make_studio(
        [tool_reply("web_search", {"query": "tides"}), "High tide is 06:12."]
    )
    await studio.ensure_defaults()
    teacher = await studio.agent_by_name("Teacher")
    assert teacher is not None and teacher.tools == ()
    chat = await studio.create_chat(agent_id=teacher.id)

    await studio.send(chat.id, "when is high tide?")

    assert {"web_search", "web_fetch"} <= set(model.calls[0]["tools"])
    assert "connected to the internet" in str(model.calls[0]["system"])
    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.data["failed"] is False
    assert "Tide tables — https://example.test/tides" in tool.text


@pytest.mark.asyncio
async def test_web_access_can_be_limited_or_switched_off(make_studio):
    studio, model = make_studio(
        [tool_reply("web_search", {"query": "tides"}), "ok"], STUDIO_WEB_ACCESS="off"
    )
    builder = await studio.create_agent(name="Scout", tools=["web_search", "remember"])
    chat = await studio.create_chat(agent_id=builder.id)

    await studio.send(chat.id, "search tides")

    assert "web_search" not in model.calls[0]["tools"]
    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.text == "Web access is off in Studio settings."

    listed, listed_model = make_studio(["hi"], STUDIO_WEB_ACCESS="listed")
    plain = await listed.create_agent(name="Plain", tools=["remember"])
    await listed.send((await listed.create_chat(agent_id=plain.id)).id, "hi")
    assert "web_search" not in listed_model.calls[-1]["tools"]


@pytest.mark.asyncio
async def test_agents_search_through_the_keyed_service(
    tmp_path, store, web_tools, studio_settings
):
    seen: list[httpx.Request] = []
    settings = studio_settings(STUDIO_SEARCH_API_KEY="tvly-secret")
    model = ScriptedLLM(
        [tool_reply("web_search", {"query": "tides"}), LLMReply(text="06:12")]
    )
    studio = StudioService(
        store=store,
        web_tools=web_tools,
        settings_provider=lambda: settings,
        models_dir=tmp_path / "models",
        sites_dir=tmp_path / "sites",
        router=StudioModelRouter(proxy=model, local=model),
        search_transport=api_server(seen),
    )
    agent = await studio.create_agent(name="Scout", model="local/tiny")
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "tides?")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.data["provider"] == "tavily"
    assert "The next high tide is 06:12." in tool.text
    assert web_tools.searches == []
    assert seen[0].url.host == "api.tavily.com"


@pytest.mark.asyncio
async def test_a_researcher_joins_the_team_and_the_main_ai_knows_it(make_studio):
    studio, model = make_studio(["Hello."])
    await studio.ensure_defaults()

    researcher = await studio.agent_by_name("Researcher")
    assert researcher is not None
    assert {"web_search", "web_fetch", "remember"} <= set(researcher.tools)

    await studio.main_say("hi", background=False)
    assert "- Researcher (agent," in str(model.calls[-1]["system"])
    assert "searches the web" in str(model.calls[-1]["system"])


@pytest.mark.asyncio
async def test_web_routes_report_and_test_without_leaking_the_key(make_studio):
    studio, _ = make_studio(
        [], STUDIO_SEARCH_PROVIDER="brave", STUDIO_SEARCH_API_KEY="BSAsecret"
    )
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            status = (await client.get("/studio/api/web")).json()
            assert status["provider"] == "brave"
            assert status["key_set"] is True
            assert status["access"] == "all"
            assert "BSAsecret" not in json.dumps(status)

            console = (await client.get("/studio/api/main")).json()
            assert console["systems"]["web"]["label"] == "Brave Search"
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_search_test_route_runs_a_real_search_path(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            body = (
                await client.post("/studio/api/web/test", json={"query": "tides"})
            ).json()
            assert body["ok"] is True
            assert body["used"] == "duckduckgo"
            assert body["results"][0]["url"] == "https://example.test/tides"
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_agents_are_told_why_a_search_came_back_empty(make_studio, web_tools):
    async def nothing(query: str) -> list[WebSearchResult]:
        return []

    web_tools.search = nothing
    studio, _ = make_studio([tool_reply("web_search", {"query": "zzzz"}), "ok"])
    agent = await studio.create_agent(name="Scout")
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "search")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.text.startswith("No results for 'zzzz'.")
    assert "Try a shorter query." in tool.text


@pytest.mark.asyncio
async def test_brave_invalid_token_reads_as_a_rejected_key():
    def brave(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"error": {"code": "SUBSCRIPTION_TOKEN_INVALID", "status": 422}},
        )

    report = await searcher(
        "brave", key="BSAbad", transport=httpx.MockTransport(brave)
    ).search("tides")

    assert report.provider == "duckduckgo"
    assert report.note.startswith("Brave Search rejected the API key (422)")
