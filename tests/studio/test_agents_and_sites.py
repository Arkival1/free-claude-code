"""Agents search the web, build a site, and stop inside their step budget."""

import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.sites import SiteError, SiteWorkspace
from tests.studio.conftest import tool_reply


@pytest.mark.asyncio
async def test_agent_searches_then_writes_a_page(make_studio, web_tools):
    page = "<!doctype html><title>Tides</title><h1>Tides</h1>"
    studio, _ = make_studio(
        [
            tool_reply("web_search", {"query": "tide times"}),
            tool_reply("write_file", {"path": "index.html", "content": page}),
            tool_reply("finish", {"summary": "Built a tide page from one source."}),
        ]
    )
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    site = await studio.create_site(name="Tides")
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)

    result = await studio.send(chat.id, "Build a tide page")

    assert not result.failed
    assert result.text == "Built a tide page from one source."
    assert web_tools.searches == ["tide times"]
    assert await studio.workspace.read(site.id, "index.html") == page

    transcript = await studio.transcript(chat.id)
    roles = [message.role for message in transcript]
    assert roles[0] == "user"
    assert "tool" in roles
    assert transcript[-1].role == "assistant"


@pytest.mark.asyncio
async def test_agent_reports_tool_failures_without_crashing(make_studio):
    studio, _ = make_studio(
        [
            tool_reply("write_file", {"path": "../escape.html", "content": "x"}),
            tool_reply("finish", {"summary": "Could not write outside the site."}),
        ]
    )
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    site = await studio.create_site(name="Guarded")
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)

    result = await studio.send(chat.id, "try to escape")

    assert not result.failed
    tool_messages = [
        message
        for message in await studio.transcript(chat.id)
        if message.role == "tool"
    ]
    assert tool_messages and tool_messages[0].data["failed"] is True


@pytest.mark.asyncio
async def test_agent_stops_at_the_step_budget(make_studio):
    studio, _ = make_studio(
        lambda system, prompt: tool_reply("list_files", {}),
        STUDIO_AGENT_MAX_STEPS=3,
    )
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    site = await studio.create_site(name="Looping")
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)

    result = await studio.send(chat.id, "loop forever")

    assert result.failed
    assert result.error == "step_limit"
    assert result.steps == 3


@pytest.mark.asyncio
async def test_plain_reply_needs_no_tools(make_studio):
    studio, model = make_studio(
        [LLMReply(text="Hello there.")], STUDIO_WEB_ACCESS="listed"
    )
    await studio.ensure_defaults()
    agent = await studio.create_agent(name="Plain", tools=[])
    chat = await studio.create_chat(agent_id=agent.id)

    result = await studio.send(chat.id, "hi")

    assert result.text == "Hello there."
    assert model.calls[0]["tools"] == []


@pytest.mark.asyncio
async def test_memory_context_reaches_the_prompt(make_studio):
    studio, model = make_studio([LLMReply(text="Metric it is.")])
    agent = await studio.create_agent(name="Rememberer", tools=[])
    await studio.remember(agent.id, "The user prefers metric units.")
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "What units should you use?")

    assert "prefers metric units" in str(model.calls[0]["system"])


@pytest.mark.asyncio
async def test_agent_task_runs_to_completion(make_studio):
    studio, _ = make_studio(
        [
            tool_reply("web_fetch", {"url": "https://example.test/tides"}),
            tool_reply("finish", {"summary": "Read the source."}),
        ]
    )
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    run = await studio.start_task(agent_id=builder.id, goal="Research tides")
    await studio.wait_for_background()  # the API returns before work finishes

    finished = await studio.run(run.id)
    assert finished.status == "succeeded"
    assert finished.result == "Read the source."


def test_site_paths_reject_traversal_and_unknown_types(tmp_path):
    workspace = SiteWorkspace(tmp_path)

    with pytest.raises(SiteError):
        workspace.resolve("site_1", "../secrets.html")
    with pytest.raises(SiteError):
        workspace.resolve("site_1", "notes.exe")
    with pytest.raises(SiteError):
        workspace.resolve("site_1", "")

    assert workspace.resolve("site_1", "css/styles.css").name == "styles.css"


@pytest.mark.asyncio
async def test_site_scaffold_and_archive(tmp_path):
    workspace = SiteWorkspace(tmp_path)
    await workspace.scaffold("site_1", "Tide Times")

    files = {item.path for item in await workspace.files("site_1")}
    assert files == {"index.html", "styles.css", "app.js"}
    assert "Tide Times" in await workspace.read("site_1", "index.html")

    archive = await workspace.archive("site_1")
    assert archive.startswith(b"PK")


@pytest.mark.asyncio
async def test_site_rejects_oversized_files(tmp_path):
    workspace = SiteWorkspace(tmp_path)
    with pytest.raises(SiteError):
        await workspace.write("site_1", "index.html", "x" * 600_000)


@pytest.mark.parametrize(
    "name", ["con.html", "NUL.css", "com1.js", "lpt9.txt", "page..html."]
)
def test_windows_reserved_names_are_refused(tmp_path, name):
    with pytest.raises(SiteError):
        SiteWorkspace(tmp_path).resolve("site_1", name)


def test_ordinary_names_that_start_like_reserved_ones_are_fine(tmp_path):
    workspace = SiteWorkspace(tmp_path)
    assert workspace.resolve("site_1", "console.html").name == "console.html"
    assert workspace.resolve("site_1", "contact.html").name == "contact.html"
