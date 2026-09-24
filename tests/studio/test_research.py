"""Deep research across platforms, code testing, and agents helping each other."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from free_claude_code.core.web_tools import WebFetchResult
from free_claude_code.studio.llm import LLMReply, StudioModelRouter
from free_claude_code.studio.models import Agent, AgentRun, Chat
from free_claude_code.studio.platforms import PlatformReader, platform_of, youtube_id
from free_claude_code.studio.research import (
    DeepResearch,
    excerpt,
    normalize_url,
    source_platform,
)
from free_claude_code.studio.search import StudioSearch
from free_claude_code.studio.service import StudioService
from tests.api.support import create_test_app

from .conftest import RecordingWebTools, ScriptedLLM, tool_reply

WATCH_HTML = (
    '<html><head><meta name="title" content="CSS Grid in 10 minutes"></head>'
    '<script>var ytInitialPlayerResponse = {"captions":{"playerCaptionsTracklistRenderer":'
    '{"captionTracks":[{"baseUrl":"https://www.youtube.com/api/timedtext?v=abcdefghijk'
    '&lang=en","languageCode":"en"}]}},"videoDetails":{"shortDescription":'
    '"Learn grid\\nfast"}};</script></html>'
)


def platform_server(seen: list[httpx.Request]):
    """Answer the search APIs and platform endpoints research talks to."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        host = request.url.host
        if host == "api.tavily.com":
            query = json.loads(request.content)["query"]
            site = (
                query.split()[0].removeprefix("site:")
                if query.startswith("site:")
                else ""
            )
            base = site or "blog.example"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": f"{base} result {n}",
                            "url": f"https://{base}/{query.replace(' ', '-')}/{n}",
                            "content": f"snippet {n}",
                        }
                        for n in range(3)
                    ]
                },
            )
        if request.url.path == "/search.json":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "permalink": f"/r/webdev/comments/abc{n}/grid_tips/",
                                    "title": f"Grid tips {n}",
                                    "subreddit": "webdev",
                                    "num_comments": 12,
                                    "selftext": "How do you learn grid?",
                                }
                            }
                            for n in range(2)
                        ]
                    }
                },
            )
        if host == "www.reddit.com" and request.url.path.endswith(".json"):
            return httpx.Response(
                200,
                json=[
                    {
                        "data": {
                            "children": [
                                {
                                    "data": {
                                        "title": "Grid tips",
                                        "subreddit": "webdev",
                                        "selftext": "What helped you learn CSS grid?",
                                        "score": 40,
                                    }
                                }
                            ]
                        }
                    },
                    {
                        "data": {
                            "children": [
                                {
                                    "kind": "t1",
                                    "data": {"body": "Grid Garden!", "score": 9},
                                },
                                {
                                    "kind": "t1",
                                    "data": {
                                        "body": "Use grid-template-areas.",
                                        "score": 30,
                                    },
                                },
                                {"kind": "more", "data": {}},
                            ]
                        }
                    },
                ],
            )
        if host == "www.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": {"videoId": "abcdefghijk"},
                            "snippet": {
                                "title": "CSS Grid in 10 minutes",
                                "channelTitle": "DevChannel",
                                "description": "grid basics",
                            },
                        }
                    ]
                },
            )
        if request.url.path == "/watch":
            return httpx.Response(200, text=WATCH_HTML)
        if request.url.path == "/api/timedtext":
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "segs": [
                                {"utf8": "Grid has rows "},
                                {"utf8": "and columns."},
                            ]
                        },
                        {"segs": [{"utf8": " Use fr units."}]},
                    ]
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


class PageFetcher:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def __call__(self, url: str) -> WebFetchResult:
        self.urls.append(url)
        if "broken" in url:
            raise ValueError("unreadable")
        return WebFetchResult(
            url=url,
            title=f"Page {url}",
            media_type="text/html",
            data=(
                "Welcome to the site. Cookies are used here. " * 12
                + "CSS grid lays out rows and columns in two dimensions. "
                + "Subscribe to our weekly newsletter for more tips. " * 12
            ),
        )


def test_links_are_recognised():
    assert platform_of("https://old.reddit.com/r/webdev/comments/x/y/") == "reddit"
    assert platform_of("https://youtu.be/abcdefghijk") == "youtube"
    assert platform_of("https://developer.mozilla.org/en-US/") == "web"
    for url in (
        "https://www.youtube.com/watch?v=abcdefghijk&t=10",
        "https://youtu.be/abcdefghijk",
        "https://www.youtube.com/shorts/abcdefghijk",
        "https://m.youtube.com/embed/abcdefghijk",
    ):
        assert youtube_id(url) == "abcdefghijk"
    assert youtube_id("https://www.youtube.com/@channel") is None
    assert normalize_url("http://www.Example.com/a/?utm_source=x#top") == (
        "https://example.com/a"
    )


def test_excerpts_skip_menus_and_label_known_sites():
    page = "\n".join(
        [
            "Home",
            "Book About Contacts GitHub",
            "NameError: name 'random' is not defined in Python [Solved]",
            "The error occurs when we use the random module without importing it first.",
            "Subscribe",
        ]
    )
    picked = excerpt(page, ["random", "import"], size=90)
    assert picked.startswith("The error occurs when we use the random module")
    assert "Contacts" not in picked
    assert source_platform("https://stackoverflow.com/questions/1") == "stackoverflow"
    assert source_platform("https://superuser.stackexchange.com/q/1") == "stackoverflow"
    assert source_platform("https://docs.github.com/x") == "github"
    assert source_platform("https://bobbyhadz.com/blog") == "web"


def test_excerpts_keep_the_sentences_that_answer_the_question():
    text = (
        "Welcome to our blog. We use cookies. CSS grid lays out rows and columns. "
        "Sign up for the newsletter. " * 20
    )
    picked = excerpt(text, ["grid", "columns"], size=120)
    assert "CSS grid lays out rows and columns." in picked
    assert "newsletter" not in picked


@pytest.mark.asyncio
async def test_reddit_threads_and_youtube_transcripts_are_readable():
    seen: list[httpx.Request] = []
    reader = PlatformReader(youtube_api_key="yt-key", transport=platform_server(seen))

    thread = await reader.read(
        "https://old.reddit.com/r/webdev/comments/abc/grid_tips/?x=1"
    )
    assert thread.title == "Grid tips"
    assert "What helped you learn CSS grid?" in thread.text
    lines = thread.text.splitlines()
    assert lines.index("- (30) Use grid-template-areas.") < lines.index(
        "- (9) Grid Garden!"
    )
    assert seen[0].url.path == "/r/webdev/comments/abc/grid_tips.json"
    assert "FCC-Studio" in seen[0].headers["user-agent"]

    video = await reader.read("https://youtu.be/abcdefghijk")
    assert video.title == "CSS Grid in 10 minutes"
    assert "Learn grid\nfast" in video.text
    assert "Grid has rows and columns. Use fr units." in video.text
    assert video.note == ""

    found = await reader.youtube_search("css grid")
    assert found[0].url == "https://www.youtube.com/watch?v=abcdefghijk"
    assert "DevChannel" in found[0].title
    search_request = next(r for r in seen if r.url.host == "www.googleapis.com")
    assert parse_qs(search_request.url.query.decode())["key"] == ["yt-key"]


@pytest.mark.asyncio
async def test_a_video_without_captions_still_gives_its_description():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='<meta name="title" content="Talk"><script>{"shortDescription":"About it"}</script>',
        )

    reader = PlatformReader(transport=httpx.MockTransport(handler))
    video = await reader.youtube_video("https://www.youtube.com/watch?v=abcdefghijk")

    assert video.text.startswith("Talk")
    assert "About it" in video.text
    assert "no captions" in video.note


@pytest.mark.asyncio
async def test_research_reads_ten_sources_across_platforms():
    seen: list[httpx.Request] = []
    transport = platform_server(seen)
    fetch = PageFetcher()
    engine = DeepResearch(
        search=StudioSearch(
            provider="tavily",
            api_key="tvly-k",
            base_url="",
            fallback=RecordingWebTools(),
            transport=transport,
        ),
        reader=PlatformReader(youtube_api_key="yt", transport=transport),
        fetch=fetch,
        wanted=10,
    )

    report = await engine.run("how to learn css grid")

    assert len(report.sources) >= 10
    platforms = {source.platform for source in report.sources}
    assert {
        "web",
        "reddit",
        "youtube",
        "stackoverflow",
        "github",
        "docs",
        "devto",
    } <= platforms
    assert len({normalize_url(source.url) for source in report.sources}) == len(
        report.sources
    )
    assert all(source.read for source in report.sources)
    reddit = next(source for source in report.sources if source.platform == "reddit")
    assert "grid" in reddit.excerpt.lower()
    web = next(source for source in report.sources if source.platform == "web")
    assert web.excerpt == "CSS grid lays out rows and columns in two dimensions."
    rendered = report.render()
    assert rendered.startswith("Research: how to learn css grid")
    assert "[1] " in rendered and "[10] " in rendered
    assert "Test any code with test_code" in rendered
    assert len(rendered) <= 7_700
    queries = [
        json.loads(request.content)["query"]
        for request in seen
        if request.url.host == "api.tavily.com"
    ]
    assert "site:stackoverflow.com how to learn css grid" in queries
    assert "site:developer.mozilla.org how to learn css grid" in queries


@pytest.mark.asyncio
async def test_research_says_when_it_found_too_few_sources():
    engine = DeepResearch(
        search=StudioSearch(
            provider="duckduckgo",
            api_key="",
            base_url="",
            fallback=RecordingWebTools(),
            retry_delay=0,
        ),
        reader=PlatformReader(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ),
        fetch=PageFetcher(),
        wanted=10,
    )

    report = await engine.run("tides", platforms=["web", "reddit"])

    assert len(report.sources) == 2
    assert "Found 2 of the 10 sources wanted" in report.render()
    assert any("Reddit search was unavailable" in note for note in report.notes)


@pytest.mark.asyncio
async def test_agents_test_code_before_trusting_it(make_studio):
    studio, _ = make_studio(
        [
            tool_reply("test_code", {"language": "python", "code": "print(6 * 7)"}),
            tool_reply(
                "test_code",
                {"language": "python", "code": "raise SystemExit(3)"},
                call_id="call_2",
            ),
            "The first snippet works; the second fails.",
        ],
        STUDIO_AGENT_COMMANDS="auto",
    )
    agent = await studio.create_agent(name="Checker", role="researcher")
    site = await studio.create_site(name="Lab")
    chat = await studio.create_chat(agent_id=agent.id, site_id=site.id)

    await studio.send(chat.id, "check these")

    tools = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert tools[0].text.startswith("PASSED")
    assert "42" in tools[0].text
    assert tools[0].data["passed"] is True
    assert tools[1].text.startswith("FAILED")
    assert tools[1].data["failed"] is True
    files = {row["path"] for row in await studio.site_files(site.id)}
    assert sum(path.startswith("lab/test_") for path in files) == 2


@pytest.mark.asyncio
async def test_code_testing_explains_when_commands_are_off(make_studio):
    studio, _ = make_studio(
        [tool_reply("test_code", {"language": "python", "code": "print(1)"}), "ok"]
    )
    agent = await studio.create_agent(name="Checker")
    site = await studio.create_site(name="Lab")
    chat = await studio.create_chat(agent_id=agent.id, site_id=site.id)

    await studio.send(chat.id, "check")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert "Agents Can Run Commands" in tool.text
    assert tool.data["failed"] is True


@pytest.mark.asyncio
async def test_the_builder_asks_the_researcher_when_it_is_stuck(make_studio):
    def respond(system: str, prompt: str):
        if "Research questions for the user and the team" in system:
            if prompt.startswith("Builder asks:"):
                return LLMReply(text="Add `display: grid` to the parent [1].")
            return LLMReply(text="?")
        if "You support the other agents" in system:
            assert prompt.startswith("Builder needs help: Why do my cards not line up?")
            assert "What Builder is working on: fix the layout" in prompt
            assert "Add `display: grid` to the parent [1]." in prompt
            return LLMReply(text="1. Put display: grid on .cards. 2. Reload and check.")
        if prompt == "fix the layout":
            return tool_reply(
                "ask_researcher", {"question": "Why do my cards not line up?"}
            )
        return LLMReply(text="Fixed it with the team's plan.")

    studio, model = make_studio(respond)
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None and builder.role == "builder"
    chat = await studio.create_chat(agent_id=builder.id)

    result = await studio.send(chat.id, "fix the layout")

    assert result.text == "Fixed it with the team's plan."
    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.text == (
        "Researcher found: Add `display: grid` to the parent [1].\n\n"
        "Helper's plan: 1. Put display: grid on .cards. 2. Reload and check."
    )
    run = await studio.store.require(AgentRun, str(tool.data["run_id"]))
    lab = await studio.site(str(run.site_id))
    assert lab.name == "Research lab"
    sub = await studio.store.require(Chat, run.chat_id)
    assert sub.parent_chat_id == chat.id
    helped = await studio.store.require(AgentRun, str(tool.data["helper_run_id"]))
    assert helped.status == "succeeded"
    builder_call = next(
        call for call in model.calls if call["prompt"] == "fix the layout"
    )
    for tool_name in ("ask_researcher", "research", "edit_file", "ask_helper"):
        assert tool_name in builder_call["tools"]


@pytest.mark.asyncio
async def test_research_comes_back_raw_when_the_helper_pipeline_is_off(make_studio):
    def respond(system: str, prompt: str):
        if "Research questions for the user and the team" in system:
            return LLMReply(text="Use flexbox [2].")
        if prompt == "fix it":
            return tool_reply("ask_researcher", {"question": "how?"})
        return LLMReply(text="done")

    studio, _ = make_studio(respond, STUDIO_HELPER_PIPELINE=False)
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    chat = await studio.create_chat(agent_id=builder.id)

    await studio.send(chat.id, "fix it")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.text == "Researcher answered: Use flexbox [2]."


@pytest.mark.asyncio
async def test_the_researcher_cannot_consult_itself(make_studio):
    studio, _ = make_studio([tool_reply("ask_researcher", {"question": "loop?"}), "ok"])
    researcher = await studio.create_agent(
        name="R2", role="researcher", tools=["ask_researcher"]
    )
    chat = await studio.create_chat(agent_id=researcher.id)

    await studio.send(chat.id, "go")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert "use research instead" in tool.text
    assert await studio.runs() == ()


@pytest.mark.asyncio
async def test_the_main_ai_can_leave_the_builder_working_in_the_background(
    make_studio,
):
    def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            if "background" in prompt:
                return LLMReply(text="Builder is on it; I'll tell you when it's done.")
            return tool_reply(
                "ask_agent",
                {
                    "agent": "Builder",
                    "task": "Build a snake game",
                    "project": "Snake",
                    "background": True,
                },
            )
        return tool_reply("finish", {"summary": "Snake game ready."})

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()

    chat = await studio.main_say("make me a snake game", background=False)
    first = await studio.transcript(chat.id)
    handoff = next(m for m in first if m.role == "tool")
    assert handoff.data["background"] is True
    assert handoff.text.startswith("Builder is working on it in the background")
    # Jarvis answered without waiting for the build to finish.
    replies = [m.text for m in first if m.role == "assistant"]
    assert replies == ["Builder is on it; I'll tell you when it's done."]

    await studio.wait_for_background()
    after = await studio.transcript(chat.id)
    done = [m for m in after if (m.data or {}).get("kind") == "background_done"]
    assert [m.text for m in done] == [
        "Builder finished in the background (succeeded): Snake game ready."
    ]
    console = await studio.main_console()
    kinds = [(m["data"] or {}).get("kind") for m in console["messages"]]
    assert "background_done" in kinds


@pytest.mark.asyncio
async def test_new_agents_get_a_role_and_tools(make_studio):
    studio, _ = make_studio([])

    designer = await studio.create_agent(
        name="Pixel",
        role="builder",
        tools=["write_file", "research", "ask_researcher"],
        description="Designs pages.",
    )
    assert designer.role == "builder"
    assert designer.tools == ("write_file", "research", "ask_researcher")
    assert designer.description == "Designs pages."

    for bad_role in ("boss", "main", "guide"):
        with pytest.raises(Exception, match="Pick a role"):
            await studio.create_agent(name="X", role=bad_role)
    with pytest.raises(Exception, match="Unknown tools: fly"):
        await studio.create_agent(name="X", role="agent", tools=["fly"])

    options = studio.agent_options()
    roles = [row["role"] for row in options["roles"]]
    assert "researcher" in roles and "builder" in roles and "main" not in roles
    presets = {row["name"]: row for row in options["presets"]}
    assert {
        "Builder",
        "Researcher",
        "Designer",
        "Tester",
        "Assistant",
        "Custom",
    } <= set(presets)
    assert "research" in presets["Researcher"]["tools"]
    groups = {group["label"] for group in options["tool_groups"]}
    assert "Internet" in groups and "Ask teammates" in groups
    assert "Helper" in presets and "search_files" in presets["Helper"]["tools"]


@pytest.mark.asyncio
async def test_older_starter_agents_get_the_new_tools(make_studio):
    studio, _ = make_studio([])
    await studio.store.put(
        Agent.model_validate(
            {
                "name": "Builder",
                "role": "agent",
                "model": "m",
                "tools": ["write_file", "finish"],
            }
        )
    )

    await studio.ensure_defaults()

    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    assert builder.role == "builder"
    assert builder.tools[:2] == ("write_file", "finish")
    assert {"research", "test_code", "ask_researcher"} <= set(builder.tools)
    main = await studio.main_agent()
    assert "research" in main.tools


@pytest.mark.asyncio
async def test_teaching_a_skill_from_a_link(make_studio, web_tools):
    def respond(system: str, prompt: str):
        if "turning material into a skill" in system:
            assert "High tide is at 06:12" in prompt
            assert "use the tide API" in prompt
            return LLMReply(text="Use npm create vite@latest for new apps.")
        return LLMReply(text="ok")

    studio, model = make_studio(respond)
    builder = await studio.create_agent(name="Maker", role="builder")

    entry = await studio.teach_agent(
        builder.id, url="https://example.test/vite", text="use the tide API"
    )

    assert entry.text == (
        "Use npm create vite@latest for new apps.\nSource: https://example.test/vite"
    )
    assert "skill" in entry.tags
    assert web_tools.fetches == ["https://example.test/vite"]
    assert [skill.id for skill in await studio.skills(builder.id)] == [entry.id]

    chat = await studio.create_chat(agent_id=builder.id)
    await studio.send(chat.id, "make an app")
    system = str(model.calls[-1]["system"])
    assert "Skills the user taught you" in system
    assert "npm create vite@latest" in system


@pytest.mark.asyncio
async def test_teaching_needs_something_to_teach(make_studio):
    studio, _ = make_studio([])
    agent = await studio.create_agent(name="Maker")
    with pytest.raises(Exception, match="Give a link"):
        await studio.teach_agent(agent.id)


@pytest.mark.asyncio
async def test_research_through_an_agent_and_the_routes(
    tmp_path, store, web_tools, studio_settings
):
    seen: list[httpx.Request] = []
    settings = studio_settings(
        STUDIO_SEARCH_API_KEY="tvly-k", STUDIO_YOUTUBE_API_KEY="yt"
    )
    model = ScriptedLLM(
        [
            tool_reply("research", {"question": "css grid"}),
            LLMReply(text="Use grid-template-areas [3]."),
        ]
    )

    async def fetch(url, *, egress):
        return WebFetchResult(
            url=url, title="Doc", media_type="text/html", data="css grid text"
        )

    web_tools.fetch = fetch
    studio = StudioService(
        store=store,
        web_tools=web_tools,
        settings_provider=lambda: settings,
        models_dir=tmp_path / "models",
        sites_dir=tmp_path / "sites",
        router=StudioModelRouter(proxy=model, local=model),
        search_transport=platform_server(seen),
    )
    agent = await studio.create_agent(name="Scout", role="researcher")
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "research css grid")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.author == "research"
    sources = tool.data["sources"]
    assert isinstance(sources, list) and len(sources) >= 10
    assert tool.data["wanted"] == 10

    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            options = (await client.get("/studio/api/agent-options")).json()
            assert options["presets"][0]["name"] == "Builder"
            made = await client.post(
                "/studio/api/agents",
                json={"name": "Tess", "role": "agent", "tools": ["test_code"]},
            )
            assert made.status_code == 200
            bad = await client.post(
                "/studio/api/agents", json={"name": "Bad", "role": "boss"}
            )
            assert bad.status_code == 400
            taught = await client.post(
                f"/studio/api/agents/{agent.id}/teach", json={"text": "Prefer MDN."}
            )
            assert taught.status_code == 200
            skills = (await client.get(f"/studio/api/agents/{agent.id}/skills")).json()
            assert len(skills["skills"]) == 1
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_reddit_app_credentials_use_the_official_api():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "data": {
                                "permalink": "/r/css/comments/z/grid/",
                                "title": "Grid",
                            }
                        }
                    ]
                }
            },
        )

    reader = PlatformReader(
        reddit_client_id="app-id-unique",
        reddit_client_secret="shh",
        transport=httpx.MockTransport(handler),
    )

    first = await reader.reddit_search("grid")
    await reader.reddit_search("grid again")

    assert first[0].url == "https://www.reddit.com/r/css/comments/z/grid/"
    token_calls = [r for r in seen if r.url.path == "/api/v1/access_token"]
    assert len(token_calls) == 1, "the app token is reused until it expires"
    search = [r for r in seen if r.url.host == "oauth.reddit.com"]
    assert len(search) == 2
    assert search[0].url.path == "/search"
    assert search[0].headers["authorization"] == "bearer tok"
    assert token_calls[0].headers["authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_a_blocked_watch_page_still_names_the_video():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oembed":
            return httpx.Response(
                200, json={"title": "Flexbox crash course", "author_name": "Traversy"}
            )
        return httpx.Response(200, text="<html>Before you continue</html>")

    reader = PlatformReader(transport=httpx.MockTransport(handler))
    video = await reader.youtube_video("https://youtu.be/abcdefghijk")

    assert video.title == "Flexbox crash course (Traversy)"
    assert "no captions" in video.note


@pytest.mark.asyncio
async def test_web_status_reports_reddit_and_youtube_modes(make_studio):
    studio, _ = make_studio(
        [],
        STUDIO_REDDIT_CLIENT_ID="id",
        STUDIO_REDDIT_CLIENT_SECRET="secret",
        STUDIO_RESEARCH_SOURCES=12,
    )
    status = studio.web_status()
    assert status["reddit"] == "official API"
    assert status["youtube"] == "web search"
    assert status["sources"] == 12
    assert "secret" not in json.dumps(status)
