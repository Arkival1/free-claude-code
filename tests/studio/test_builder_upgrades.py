"""The Builder starts from good templates, edits safely, undoes, and checks JS."""

import shutil

import pytest

from free_claude_code.studio.agents import REPEAT_NOTE
from free_claude_code.studio.sites import HISTORY_DIR
from free_claude_code.studio.templates import TEMPLATES
from free_claude_code.studio.tools import loose_replace

from .conftest import tool_reply


async def builder_chat(studio, name="Shop"):
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    site = await studio.create_site(name=name)
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)
    return builder, site, chat


def tools_used(transcript):
    return [m for m in transcript if m.role == "tool"]


@pytest.mark.asyncio
async def test_a_project_starts_from_a_template_over_the_placeholders(make_studio):
    studio, model = make_studio(
        [
            tool_reply(
                "start_project", {"template": "landing", "title": "Tomato Club"}
            ),
            tool_reply("check_project", {}, call_id="c2"),
            "Started.",
        ]
    )
    builder, site, chat = await builder_chat(studio)
    assert {"start_project", "restore_file"} <= set(builder.tools)

    await studio.send(chat.id, "make a landing page")

    started, checked = tools_used(await studio.transcript(chat.id))
    assert set(started.data["written"]) == {
        "index.html",
        "styles.css",
        "app.js",
        "README.md",
    }
    assert started.data["kept"] == []
    page = await studio.workspace.read(site.id, "index.html")
    assert "<title>Tomato Club</title>" in page and "$0" in page
    assert "found no problems" in checked.text
    assert "only has placeholder files" in str(model.calls[0]["system"])


@pytest.mark.asyncio
async def test_templates_never_replace_real_work(make_studio):
    studio, _ = make_studio(
        [
            tool_reply("start_project", {"template": "website", "title": "X"}),
            "ok",
        ]
    )
    _, site, chat = await builder_chat(studio)
    await studio.workspace.write(site.id, "index.html", "<h1>Mine</h1>")

    await studio.send(chat.id, "start")

    started = tools_used(await studio.transcript(chat.id))[0]
    assert started.data["kept"] == ["index.html"]
    assert await studio.workspace.read(site.id, "index.html") == "<h1>Mine</h1>"


def test_every_template_is_listed_and_known():
    assert set(TEMPLATES) == {
        "website",
        "landing",
        "webapp",
        "game",
        "python-tool",
        "python-web",
        "node-api",
    }


@pytest.mark.asyncio
async def test_changes_can_be_undone(make_studio):
    studio, _ = make_studio(
        [
            tool_reply("restore_file", {"path": "app.js"}),
            tool_reply(
                "restore_file", {"path": "app.js", "versions_back": 1}, call_id="c2"
            ),
            "Undone.",
        ]
    )
    _, site, chat = await builder_chat(studio)
    await studio.workspace.write(site.id, "app.js", "console.log('v1');")
    await studio.workspace.write(site.id, "app.js", "console.log('v2 broken');")

    await studio.send(chat.id, "undo that")

    listed, restored = tools_used(await studio.transcript(chat.id))
    assert "app.js has 2 earlier version(s)" in listed.text
    assert "Restored app.js" in restored.text
    assert await studio.workspace.read(site.id, "app.js") == "console.log('v1');"
    paths = {row["path"] for row in await studio.site_files(site.id)}
    assert not any(path.startswith(HISTORY_DIR) for path in paths)
    await studio.workspace.delete(site.id, "app.js")
    await studio.workspace.restore(site.id, "app.js")
    assert await studio.workspace.read(site.id, "app.js") == "console.log('v1');"


@pytest.mark.asyncio
async def test_several_edits_at_once_and_loose_indentation(make_studio):
    studio, _ = make_studio(
        [
            tool_reply(
                "edit_file",
                {
                    "path": "app.py",
                    "edits": [
                        {
                            "old_text": "def a():\n  return 1",
                            "new_text": "def a():\n  return 10",
                        },
                        {"old_text": "B = 2", "new_text": "B = 20"},
                    ],
                },
            ),
            tool_reply(
                "edit_file",
                {
                    "path": "app.py",
                    "edits": [
                        {"old_text": "B = 20", "new_text": "B = 200"},
                        {"old_text": "not there", "new_text": "x"},
                    ],
                },
                call_id="c2",
            ),
            "ok",
        ]
    )
    _, site, chat = await builder_chat(studio)
    await studio.workspace.write(
        site.id, "app.py", "class K:\n    def a():\n        return 1\n\nB = 2\n"
    )

    await studio.send(chat.id, "edit")

    first, second = tools_used(await studio.transcript(chat.id))
    assert (
        "replaced 2 occurrence(s) (1 matched after adjusting indentation)" in first.text
    )
    assert second.data["failed"] is True and "No edits were saved" in second.text
    assert await studio.workspace.read(site.id, "app.py") == (
        "class K:\n    def a():\n        return 10\n\nB = 20\n"
    )


def test_loose_replace_needs_one_clear_match():
    text = "if x:\n    go()\nif y:\n    go()\n"
    assert loose_replace(text, "go()", "stop()") is None, "two places fit"
    assert loose_replace(text, "if y:\n  go()", "if y:\n  stop()") == (
        "if x:\n    go()\nif y:\n    stop()\n"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
@pytest.mark.asyncio
async def test_node_checks_javascript_syntax(make_studio):
    studio, _ = make_studio([tool_reply("check_project", {}), "ok"])
    _, site, chat = await builder_chat(studio)
    await studio.workspace.write(
        site.id, "app.js", "const re = /[(]+/g;\nconsole.log(`${re}`);\n"
    )
    await studio.workspace.write(site.id, "bad.js", "function f( {\n  return 1;\n}\n")

    await studio.send(chat.id, "check")

    checked = tools_used(await studio.transcript(chat.id))[0]
    problems = checked.data["problems"]
    assert not any(p.startswith("app.js") for p in problems)
    bad = [p for p in problems if p.startswith("bad.js")]
    assert len(bad) == 1 and "syntax error on line" in bad[0]


@pytest.mark.asyncio
async def test_builders_get_more_steps_than_other_agents(make_studio):
    studio, _ = make_studio([], STUDIO_AGENT_MAX_STEPS=5, STUDIO_BUILDER_MAX_STEPS=30)
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    helper = await studio.agent_by_name("Helper")
    assert builder is not None and helper is not None

    assert studio._steps_for(builder) == 30
    assert studio._steps_for(helper) == 5
    run = await studio.start_task(agent_id=builder.id, goal="build it")
    assert run.max_steps == 30
    await studio.shutdown()


@pytest.mark.asyncio
async def test_a_repeated_failure_gets_a_nudge(make_studio):
    studio, _ = make_studio(
        [
            tool_reply("read_file", {"path": "missing.js"}),
            tool_reply("read_file", {"path": "missing.js"}, call_id="c2"),
            "I will try something else.",
        ]
    )
    _, _, chat = await builder_chat(studio)

    await studio.send(chat.id, "read it")

    first, second = tools_used(await studio.transcript(chat.id))
    assert REPEAT_NOTE not in first.text
    assert REPEAT_NOTE in second.text


@pytest.mark.asyncio
async def test_the_builder_sees_what_is_in_the_project(make_studio):
    studio, model = make_studio(["ok"])
    _, site, chat = await builder_chat(studio)
    await studio.workspace.write(site.id, "README.md", "# Shop\nSells tomatoes.")
    await studio.workspace.write(site.id, "shop.js", "export const x = 1;")

    await studio.send(chat.id, "add a cart")

    system = str(model.calls[0]["system"])
    assert "Files already in the project (5):" in system
    assert "- shop.js (19 bytes)" in system
    assert "README.md starts:\n# Shop\nSells tomatoes." in system
