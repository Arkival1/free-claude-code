"""The Builder's coding tools, and the Helper that supports the other agents."""

import pytest

from free_claude_code.studio.llm import LLMReply, ToolCall
from free_claude_code.studio.memory import PLAN_TAG
from free_claude_code.studio.tools import ToolContext

from .conftest import tool_reply


async def project(studio):
    site = await studio.create_site(name="Shop")
    await studio.write_site_file(
        site.id,
        "src/app.js",
        "const total = 1;\nfunction pay() {\n  return total * 2;\n}\n",
    )
    await studio.write_site_file(site.id, "src/style.css", ".pay { color: red; }\n")
    await studio.write_site_file(site.id, "notes.md", "TODO: pay button\n")
    agent = await studio.create_agent(name="Maker", role="builder")
    context = ToolContext(
        agent_id=agent.id,
        chat_id="cht_x",
        site_id=site.id,
        agent_name="Maker",
        agent_role="builder",
    )
    return site, agent, context


async def run(studio, context, name, **arguments):
    return await studio._toolbox().run(
        ToolCall(id="t", name=name, arguments=arguments), context
    )


@pytest.mark.asyncio
async def test_reading_a_numbered_section(make_studio):
    studio, _ = make_studio([])
    _, _, context = await project(studio)

    section = await run(
        studio, context, "read_file", path="src/app.js", start_line=2, max_lines=2
    )

    assert section.text == (
        "src/app.js: lines 2-3 of 4\n    2  function pay() {\n    3    return total * 2;"
    )
    whole = await run(studio, context, "read_file", path="src/app.js")
    assert whole.text.startswith("const total = 1;")


@pytest.mark.asyncio
async def test_editing_exact_text(make_studio):
    studio, _ = make_studio([])
    site, _, context = await project(studio)

    edited = await run(
        studio,
        context,
        "edit_file",
        path="src/app.js",
        old_text="total * 2",
        new_text="total * 3",
    )
    assert edited.text == "Edited src/app.js: replaced 1 occurrence(s)."
    assert "total * 3" in await studio.workspace.read(site.id, "src/app.js")

    missing = await run(
        studio, context, "edit_file", path="src/app.js", old_text="nope", new_text="x"
    )
    assert missing.failed and "was not found" in missing.text
    twice = await run(
        studio,
        context,
        "edit_file",
        path="src/app.js",
        old_text="total",
        new_text="sum",
    )
    assert twice.failed and "appears 2 times" in twice.text
    everywhere = await run(
        studio,
        context,
        "edit_file",
        path="src/app.js",
        old_text="total",
        new_text="sum",
        replace_all=True,
    )
    assert everywhere.data["replacements"] == 2
    assert "total" not in await studio.workspace.read(site.id, "src/app.js")


@pytest.mark.asyncio
async def test_searching_and_listing_by_pattern(make_studio):
    studio, _ = make_studio([])
    _, _, context = await project(studio)

    found = await run(
        studio, context, "search_files", pattern=r"pay\b", ignore_case=True
    )
    assert found.text.splitlines() == [
        "notes.md:1: TODO: pay button",
        "src/app.js:2: function pay() {",
        "src/style.css:1: .pay { color: red; }",
    ]
    only_css = await run(studio, context, "search_files", pattern="pay", glob="*.css")
    assert only_css.text == "src/style.css:1: .pay { color: red; }"
    bad = await run(studio, context, "search_files", pattern="(")
    assert bad.failed and "not a valid regular expression" in bad.text
    none = await run(studio, context, "search_files", pattern="zebra")
    assert none.text.startswith("No matches in")

    listed = await run(studio, context, "list_files", pattern="src/**/*.js")
    assert listed.data["files"] == ["src/app.js"]
    assert (await run(studio, context, "list_files", pattern="*.md")).data["files"] == [
        "notes.md"
    ]


@pytest.mark.asyncio
async def test_keeping_one_current_plan(make_studio):
    studio, _ = make_studio([])
    _, agent, context = await project(studio)

    await run(studio, context, "update_plan", steps=[{"step": "Write HTML"}])
    latest = await run(
        studio,
        context,
        "update_plan",
        steps=[
            {"step": "Write HTML", "status": "done"},
            {"step": "Add styles", "status": "in_progress"},
            {"step": "Test"},
        ],
    )

    assert latest.text == ("Plan (1/3 done):\n[x] Write HTML\n[>] Add styles\n[ ] Test")
    plans = [
        entry
        for entry in await studio.memories(agent.id, scope="working")
        if PLAN_TAG in entry.tags
    ]
    assert len(plans) == 1 and "[>] Add styles" in plans[0].text


@pytest.mark.asyncio
async def test_any_agent_can_ask_the_helper(make_studio):
    def respond(system: str, prompt: str):
        if "You support the other agents" in system:
            assert "Tester needs help: flaky login test" in prompt
            assert "Material to work from:\nTimeout after 5s" in prompt
            return LLMReply(text="1. Wait for the button. 2. Raise the timeout.")
        if prompt == "test login":
            return tool_reply(
                "ask_helper",
                {"request": "flaky login test", "material": "Timeout after 5s"},
            )
        return LLMReply(text="Stable now.")

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    helper = await studio.agent_by_name("Helper")
    assert helper is not None and helper.role == "helper"
    tester = await studio.create_agent(name="Tester", tools=["ask_helper"])
    chat = await studio.create_chat(agent_id=tester.id)

    await studio.send(chat.id, "test login")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.text == "Helper suggests: 1. Wait for the button. 2. Raise the timeout."
    assert tool.data["agent"] == "Helper"


@pytest.mark.asyncio
async def test_the_helper_does_not_ask_itself(make_studio):
    studio, _ = make_studio([tool_reply("ask_helper", {"request": "loop?"}), "ok"])
    helper = await studio.create_agent(name="H2", role="helper", tools=["ask_helper"])
    chat = await studio.create_chat(agent_id=helper.id)

    await studio.send(chat.id, "go")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert "You are the helper" in tool.text
    assert await studio.runs() == ()


@pytest.mark.asyncio
async def test_the_main_ai_knows_the_helper(make_studio):
    studio, model = make_studio(["Hello."])
    await studio.ensure_defaults()

    await studio.main_say("hi", background=False)

    system = str(model.calls[-1]["system"])
    assert "- Helper (helper," in system
    assert "ask_helper" in model.calls[-1]["tools"]
