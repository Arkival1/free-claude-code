"""Agents run commands in their project only as the user allows."""

import asyncio
import os
import sys

import pytest

from free_claude_code.studio.commands import execute, scrubbed_environment
from free_claude_code.studio.models import CommandRequest
from tests.studio.conftest import tool_reply

PYTHON = f'"{sys.executable}"'


def test_credentials_never_reach_agent_commands():
    env = scrubbed_environment(
        {"PATH": "/bin", "OPENROUTER_API_KEY": "k", "HF_TOKEN": "t", "DB_PASSWORD": "p"}
    )
    assert env == {"PATH": "/bin"}


@pytest.mark.asyncio
async def test_execute_reports_output_and_exit_codes(tmp_path):
    code, output, timed_out = await execute(
        f'{PYTHON} -c "print(6 * 7)"', cwd=tmp_path, timeout=30
    )
    assert (code, output.strip(), timed_out) == (0, "42", False)

    code, _, _ = await execute(
        f'{PYTHON} -c "raise SystemExit(3)"', cwd=tmp_path, timeout=30
    )
    assert code == 3


@pytest.mark.asyncio
async def test_execute_stops_commands_that_run_too_long(tmp_path):
    code, _, timed_out = await execute(
        f'{PYTHON} -c "import time; time.sleep(30)"', cwd=tmp_path, timeout=0.5
    )
    assert timed_out is True
    assert code != 0


@pytest.mark.asyncio
async def test_execute_hides_credentials_from_the_command(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    _, output, _ = await execute(
        f"{PYTHON} -c \"import os; print(os.environ.get('OPENROUTER_API_KEY'))\"",
        cwd=tmp_path,
        timeout=30,
    )
    assert output.strip() == "None"


async def builder_in_project(studio):
    agent = await studio.create_agent(name="Maker")
    site = await studio.create_site(name="App")
    chat = await studio.create_chat(agent_id=agent.id, site_id=site.id)
    return agent, site, chat


@pytest.mark.asyncio
async def test_commands_are_not_offered_when_off(make_studio):
    studio, model = make_studio(["Done."])
    _, _, chat = await builder_in_project(studio)

    await studio.send(chat.id, "build it")

    assert "run_command" not in model.calls[0]["tools"]


@pytest.mark.asyncio
async def test_auto_mode_runs_in_the_project_folder(make_studio):
    studio, model = make_studio(
        [
            tool_reply(
                "run_command",
                {
                    "command": f"{PYTHON} -c \"import pathlib; pathlib.Path('built.txt').write_text('ok')\""
                },
            ),
            tool_reply("finish", {"summary": "Built."}),
        ],
        STUDIO_AGENT_COMMANDS="auto",
    )
    _, site, chat = await builder_in_project(studio)

    result = await studio.send(chat.id, "build it")

    assert result.text == "Built."
    assert "run_command" in model.calls[0]["tools"]
    assert "run_command" in str(model.calls[0]["system"])
    assert (studio.workspace.directory(site.id) / "built.txt").read_text() == "ok"
    ran = await studio.store.find(CommandRequest)
    assert [(item.status, item.exit_code) for item in ran] == [("ran", 0)]


@pytest.mark.asyncio
async def test_ask_mode_waits_for_approval(make_studio):
    studio, model = make_studio(
        [
            tool_reply("run_command", {"command": f"{PYTHON} -c \"print('hello')\""}),
            tool_reply("finish", {"summary": "Ran it."}),
        ],
        STUDIO_AGENT_COMMANDS="ask",
    )
    _, _, chat = await builder_in_project(studio)

    turn = asyncio.create_task(studio.send(chat.id, "say hello"))
    for _ in range(100):
        pending = await studio.pending_commands()
        if pending:
            break
        await asyncio.sleep(0.02)
    assert len(pending) == 1 and "hello" in pending[0].command
    approval = [
        message
        for message in await studio.transcript(chat.id)
        if message.data.get("kind") == "approval"
    ]
    assert approval and approval[0].data["request_id"] == pending[0].id

    await studio.decide_command(pending[0].id, approve=True)
    result = await turn

    assert result.text == "Ran it."
    tool_output = model.calls[1]["messages"][-1].content
    assert "exit code 0" in tool_output and "hello" in tool_output


@pytest.mark.asyncio
async def test_a_denied_command_is_reported_to_the_agent(make_studio):
    studio, model = make_studio(
        [
            tool_reply("run_command", {"command": "rm -rf /"}),
            tool_reply("finish", {"summary": "Okay, skipped."}),
        ],
        STUDIO_AGENT_COMMANDS="ask",
    )
    _, _, chat = await builder_in_project(studio)

    turn = asyncio.create_task(studio.send(chat.id, "clean up"))
    for _ in range(100):
        pending = await studio.pending_commands()
        if pending:
            break
        await asyncio.sleep(0.02)
    await studio.decide_command(pending[0].id, approve=False)
    await turn

    assert "denied" in model.calls[1]["messages"][-1].content
    stored = await studio.store.require(CommandRequest, pending[0].id)
    assert stored.status == "denied"


@pytest.mark.asyncio
async def test_deciding_twice_or_late_is_refused(make_studio):
    studio, _ = make_studio([])
    orphan = CommandRequest.model_validate(
        {"agent_id": "a", "chat_id": "c", "site_id": "s", "command": "ls"}
    )
    await studio.store.put(orphan)

    with pytest.raises(Exception, match="expired"):
        await studio.decide_command(orphan.id, approve=True)
    with pytest.raises(Exception, match="already expired"):
        await studio.decide_command(orphan.id, approve=True)
    assert await studio.pending_commands() == ()


@pytest.mark.asyncio
async def test_projects_accept_app_source_files_and_skip_dependencies(make_studio):
    studio, _ = make_studio([])
    site = await studio.create_site(name="App")
    for path in (
        "src/main.py",
        "web/App.tsx",
        "package.json",
        "Dockerfile",
        ".gitignore",
    ):
        await studio.workspace.write(site.id, path, "x")
    modules = studio.workspace.directory(site.id) / "node_modules" / "left-pad"
    modules.mkdir(parents=True)
    (modules / "index.js").write_text("module.exports = 1", encoding="utf-8")

    listed = {item.path for item in await studio.workspace.files(site.id)}

    assert {
        "src/main.py",
        "web/App.tsx",
        "package.json",
        "Dockerfile",
        ".gitignore",
    } <= listed
    assert not any(path.startswith("node_modules") for path in listed)
    await studio.delete_site(site.id)
    assert not studio.workspace.directory(site.id).exists()


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shell")
@pytest.mark.asyncio
async def test_a_room_can_work_inside_a_project(make_studio):
    studio, _ = make_studio([tool_reply("list_files", {}), "Files look good."])
    agent = await studio.create_agent(name="Lead", tools=["list_files"])
    site = await studio.create_site(name="Team app")
    room = await studio.create_room(member_ids=[agent.id], site_id=site.id)

    await studio.room_say(room.id, "@Lead check the files", background=False)

    tool_rows = [m for m in await studio.transcript(room.id) if m.role == "tool"]
    assert tool_rows and "index.html" in tool_rows[0].text
