"""Agents written for a Claude Code team with a context-manager (most of
awesome-claude-code-subagents) work on the project's files in LCC instead of
writing their request for context into one."""

import json

import pytest

from free_claude_code.studio.agents import NO_CONTEXT_MANAGER_PROMPT
from free_claude_code.studio.project_check import check_project

from .conftest import tool_reply

REQUEST = json.dumps(
    {
        "requesting_agent": "ui-designer",
        "request_type": "get_design_context",
        "payload": {"query": "Design context needed: brand guidelines."},
    },
    indent=2,
)
VOLT_PROMPT = (
    "You are a senior UI designer.\n## Communication Protocol\nAlways begin "
    "by requesting design context from the context-manager:\n" + REQUEST
)


@pytest.mark.asyncio
async def test_a_request_for_context_is_never_written_into_a_file(make_studio):
    studio, model = make_studio(
        [
            tool_reply("write_file", {"path": "app.js", "content": REQUEST}),
            tool_reply("finish", {"summary": "Asked for context."}),
        ]
    )
    await studio.ensure_defaults()
    designer = await studio.create_agent(
        name="ui-designer",
        role="agent",
        system_prompt=VOLT_PROMPT,
        tools=("write_file", "read_file", "list_files"),
        all_tools=False,
    )
    site = await studio.create_site(name="Bakery")
    await studio.workspace.write(site.id, "app.js", "console.log('menu');\n")
    chat = await studio.create_chat(agent_id=designer.id, site_id=site.id)

    await studio.send(chat.id, "Make the bakery site look better")

    assert NO_CONTEXT_MANAGER_PROMPT in str(model.calls[0]["system"])
    assert await studio.workspace.read(site.id, "app.js") == "console.log('menu');\n"
    refused = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert "LCC has no context-manager" in refused[0].text

    # LCC's own agents don't get the note.
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    builder_chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)
    await studio.send(builder_chat.id, "hi")
    assert NO_CONTEXT_MANAGER_PROMPT not in str(model.calls[-1]["system"])


def test_a_script_that_holds_json_is_a_problem():
    page = (
        "<!doctype html><html><head><title>Hi</title>"
        '<meta name="viewport" content="width=device-width"></head>'
        '<body><script src="app.js"></script></body></html>'
    )
    broken = check_project({"index.html": page, "app.js": REQUEST})
    assert any("app.js: holds a JSON object, not JavaScript" in p for p in broken)
    fine = check_project(
        {"index.html": page, "app.js": "{\n  const year = 2026;\n  run(year);\n}\n"}
    )
    assert not any("JSON object" in p for p in fine)
