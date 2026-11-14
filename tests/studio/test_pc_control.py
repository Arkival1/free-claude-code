"""Jarvis's PC: only the main AI on the local model gets the PC tools; the
owner's level decides what runs, asks or is refused; Stop is a latch that
kills what's running; some places are never touched at any level."""

import asyncio
import sys
import time
from pathlib import Path

import pytest

from free_claude_code.studio.llm import LOCAL_MODEL_PREFIX
from free_claude_code.studio.pc_control import ADVISER_TOOLS, PC_TOOLS, PcControl
from free_claude_code.studio.playground import ADVISER_PROMPT, REFLECT_PROMPT
from free_claude_code.studio.tools import ToolContext

from .conftest import tool_reply


def control(tmp_path: Path, level: str = "full") -> PcControl:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    pc = PcControl(
        data_root=tmp_path / "data", protected=(tmp_path / "fcc",), home=home
    )
    pc.set_level(level)
    return pc


def verdict(pc: PcControl, tool: str, **arguments: object) -> str:
    return pc.decide(tool, arguments).verdict


def test_each_level_runs_asks_or_refuses(tmp_path: Path) -> None:
    pc = control(tmp_path, "off")
    assert verdict(pc, "pc_files", action="read", path="a.txt") == "deny"
    pc.set_level("look")
    assert verdict(pc, "pc_files", action="list", path=".") == "auto"
    assert verdict(pc, "pc_files", action="write", path="a.txt", content="x") == "deny"
    assert verdict(pc, "pc_run", command="dir") == "deny"
    pc.set_level("ask")
    assert verdict(pc, "pc_files", action="write", path="a.txt", content="x") == "ask"
    assert verdict(pc, "pc_run", command="dir") == "ask"
    pc.set_level("full")
    assert verdict(pc, "pc_files", action="write", path="a.txt", content="x") == "auto"
    assert verdict(pc, "pc_run", command="git status") == "auto"
    # Risky steps ask even at full.
    assert verdict(pc, "pc_files", action="delete", path="a.txt") == "ask"
    assert verdict(pc, "pc_files", action="move", path="a.txt", to="b.txt") == "ask"
    for risky in (
        "del notes.txt",
        "winget install godot",
        "pip install x",
        "setup.exe",
        "run.ps1",
        # Programs that run other code ask too, whatever they're told to do.
        "python -c \"import shutil; shutil.rmtree('Documents')\"",
        "py game.py",
        "node -e \"require('fs').rmSync('x', {recursive: true})\"",
        "powershell -Command Remove-Item x",
        "cmd /c rd x",
        "wsl rm -rf x",
        "Stop-Process -Id 4242",
        "taskkill /PID 4242",
        "dir ..\\..\\free-claude-code",
        "r^m x",
        "start calc",
        "& .\\tool",
        ". .\\setup",
        ".\\tool --go",
        "Invoke-Item x",
        "explorer .",
        "wmic process call create calc",
        "sc create svc binPath= x",
    ):
        assert verdict(pc, "pc_run", command=risky) == "ask", risky
    # Plain reading and git still run on their own.
    for plain in (
        "dir",
        "git status",
        "git log --oneline -5",
        "type notes.txt",
        "dir && git status",
    ):
        assert verdict(pc, "pc_run", command=plain) == "auto", plain
    # Writing a file Windows runs, or into a Startup folder, asks at Full.
    for path in ("go.bat", "x.ps1", "link.lnk", "Startup/notes.txt"):
        assert (
            verdict(pc, "pc_files", action="write", path=path, content="x") == "ask"
        ), path
    assert (
        verdict(pc, "pc_files", action="write", path="game.gd", content="x") == "auto"
    )


def test_some_things_are_never_allowed_at_any_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_TEST_DATA", str(tmp_path / "data"))
    pc = control(tmp_path, "full")
    for command in (
        "format c:",
        "diskpart",
        "shutdown /s /t 0",
        "reg add HKLM\\Software\\X /v Y",
        "Set-MpPreference -DisableRealtimeMonitoring $true",
        "net user hacker pw /add",
        "rd /s /q C:\\",
        "taskkill /f /im python.exe",
        f"type {Path.home() / '.fcc' / 'keys.json'}",
        f"dir {tmp_path / 'data'}",
        'copy "Login Data" x',
        # Escapes and variables don't hide a never-allowed command.
        "f^ormat c:",
        '"format" c:',
        "shut`down /s",
        "type %USERPROFILE%\\.fcc\\keys.json",
        "Get-Content $env:FCC_TEST_DATA\\pc-control.json",
        # Encoded PowerShell can't be read, so it never runs.
        "powershell -enc ZQBjAGgAbwAgAGgAaQA=",
        "pwsh -EncodedCommand ZQBjAGgAbwA=",
    ):
        assert verdict(pc, "pc_run", command=command) == "deny", command
    for path in (
        tmp_path / "data" / "pc-control.json",  # FCC's data and keys
        tmp_path / "fcc" / "studio" / "pc_control.py",  # FCC's own code
        tmp_path / "home" / "AppData" / "Chrome" / "Login Data",
        tmp_path / "home" / ".ssh" / "id_rsa",
        tmp_path / "elsewhere" / "file.txt",  # outside Jarvis's folders
    ):
        assert verdict(pc, "pc_files", action="read", path=str(path)) == "deny", path


def test_stop_is_a_latch_that_survives_a_restart(tmp_path: Path) -> None:
    pc = control(tmp_path, "full")
    asyncio.run(pc.stop())
    assert not pc.active
    assert "Stop" in pc.decide("pc_files", {"action": "list", "path": "."}).reason
    again = PcControl(
        data_root=tmp_path / "data",
        protected=(tmp_path / "fcc",),
        home=tmp_path / "home",
    )
    assert again.stopped and again.level == "full" and not again.active
    again.resume()
    assert again.active
    assert [row["text"] for row in again.recent()][-2:] == [
        "STOP (killed 0 running)",
        "resumed",
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX sleep")
def test_stop_kills_a_running_command(tmp_path: Path) -> None:
    pc = control(tmp_path, "full")

    async def scenario() -> tuple[str, float]:
        started = time.monotonic()
        job = asyncio.create_task(pc.execute("sleep 30", cwd=tmp_path, timeout=60))
        await asyncio.sleep(0.3)
        assert pc.state()["running"] == 1
        await pc.stop()
        _, text, _ = await job
        return text, time.monotonic() - started

    text, took = asyncio.run(scenario())
    assert took < 10 and "Stopped by the owner" in text


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX sleep")
def test_stop_while_a_command_is_starting_still_kills_it(tmp_path: Path) -> None:
    pc = control(tmp_path, "full")

    async def scenario() -> tuple[str, float]:
        started = time.monotonic()
        # Stop lands before the new process is tracked.
        job = asyncio.create_task(pc.execute("sleep 30", cwd=tmp_path, timeout=60))
        await pc.stop()
        _, text, _ = await job
        return text, time.monotonic() - started

    text, took = asyncio.run(scenario())
    assert took < 10 and "Stopped by the owner" in text


def test_file_actions_work_in_jarvis_folders(tmp_path: Path) -> None:
    pc = control(tmp_path, "full")
    home = tmp_path / "home"
    assert "Wrote" in pc.files(
        {"action": "write", "path": "games/notes.txt", "content": "hello"}
    )
    assert (
        pc.files({"action": "read", "path": str(home / "games" / "notes.txt")})
        == "hello"
    )
    pc.files({"action": "append", "path": "games/notes.txt", "content": " world"})
    assert "notes.txt (11 bytes)" in pc.files({"action": "list", "path": "games"})
    pc.files({"action": "move", "path": "games/notes.txt", "to": "games/done.txt"})
    assert pc.files({"action": "delete", "path": "games/done.txt"}).startswith(
        "Deleted"
    )
    assert not (home / "games" / "done.txt").exists()


# ── who gets the PC: the main AI, on the local model, working, never advisers ──


def turns(fake) -> list:
    """Jarvis's own turns (not the router's who-answers call)."""
    return [call for call in fake.calls if "Studio agent" in str(call["system"])]


def pc_home(tmp_path: Path) -> Path:
    """Jarvis's folder for the agent tests: beside the test folder, which is
    FCC's data folder there (and so never his)."""
    home = tmp_path.with_name(f"{tmp_path.name}-pchome")
    home.mkdir(exist_ok=True)
    return home


def hands_script(tmp_path: Path):
    """Jarvis writes a note on the PC when he has the tools; advisers approve.
    The fake model records the offered tools before it answers (box[0])."""
    note = pc_home(tmp_path) / "jarvis-note.txt"
    box: list = []

    def respond(system: str, prompt: str):
        tools = box[0].calls[-1]["tools"] if box else []
        if system == REFLECT_PROMPT:
            return "{}"
        if ADVISER_PROMPT in system:
            return tool_reply("finish", {"summary": "LOOKS GOOD"})
        if "pc_files" in tools and not note.exists():
            return tool_reply(
                "pc_files",
                {"action": "write", "path": str(note), "content": "made by Jarvis"},
            )
        return tool_reply("finish", {"summary": "Done."})

    return respond, note, box


async def pc_studio(
    make_studio, tmp_path: Path, respond, model: str, level: str = "full", box=None
):
    studio, fake = make_studio(
        respond, STUDIO_PC_CONTROL=True, STUDIO_MAIN_AGENT_MODEL=model
    )
    if box is not None:
        box.append(fake)
    await studio.ensure_defaults()
    studio.pc_control.set_roots([str(pc_home(tmp_path))])
    studio.pc_control.set_level(level)
    return studio, fake


@pytest.mark.asyncio
async def test_only_jarvis_on_the_local_model_gets_the_pc(
    make_studio, tmp_path: Path
) -> None:
    respond, note, box = hands_script(tmp_path)
    studio, fake = await pc_studio(
        make_studio, tmp_path, respond, f"{LOCAL_MODEL_PREFIX}qwen3.5-4b", box=box
    )
    main = await studio.main_agent()
    chat = await studio.create_chat(agent_id=main.id)
    await studio.send(chat.id, "leave me a note on the PC")
    offered = set(turns(fake)[0]["tools"])
    assert offered >= PC_TOOLS
    # Working alone with his advisers: he hands work to nobody.
    assert not {"ask_agent", "team_task", "manage_agent"} & offered
    assert note.read_text() == "made by Jarvis"
    assert any("pc_files" in row["text"] for row in studio.pc_control.recent())


@pytest.mark.asyncio
async def test_jarvis_on_an_api_model_never_gets_the_pc(
    make_studio, tmp_path: Path
) -> None:
    respond, note, box = hands_script(tmp_path)
    studio, fake = await pc_studio(
        make_studio,
        tmp_path,
        respond,
        "nvidia_nim/meta/llama-3.3-70b-instruct",
        box=box,
    )
    main = await studio.main_agent()
    chat = await studio.create_chat(agent_id=main.id)
    await studio.send(chat.id, "leave me a note on the PC")
    assert turns(fake) and all(not PC_TOOLS & set(c["tools"]) for c in turns(fake))
    assert not note.exists()


@pytest.mark.asyncio
async def test_off_or_stopped_means_no_pc_tools(make_studio, tmp_path: Path) -> None:
    respond, note, box = hands_script(tmp_path)
    studio, fake = await pc_studio(
        make_studio,
        tmp_path,
        respond,
        f"{LOCAL_MODEL_PREFIX}qwen",
        level="off",
        box=box,
    )
    main = await studio.main_agent()
    chat = await studio.create_chat(agent_id=main.id)
    await studio.send(chat.id, "hello")
    assert not PC_TOOLS & set(turns(fake)[-1]["tools"])
    studio.pc_control.set_level("full")
    await studio.pc_control.stop()
    await studio.send(chat.id, "hello again")
    assert not PC_TOOLS & set(turns(fake)[-1]["tools"])
    assert not note.exists()


@pytest.mark.asyncio
async def test_advisers_get_only_the_web_even_on_the_local_model(
    make_studio, tmp_path: Path
) -> None:
    respond, _note, box = hands_script(tmp_path)
    studio, fake = await pc_studio(
        make_studio, tmp_path, respond, f"{LOCAL_MODEL_PREFIX}qwen", box=box
    )
    # One adviser on an API model, one switched to the local model.
    agents = [a for a in await studio.agents() if a.role != "main"]
    await studio.update_agent(agents[0].id, {"model": f"{LOCAL_MODEL_PREFIX}qwen"})
    job = await studio.start_playground(
        "Make a tiny game", advisers=[agents[0].id, agents[1].id]
    )
    await asyncio.wait_for(studio.wait_for_background(), timeout=30)
    done = await studio.playground_job(job.id)
    assert done.status == "done", done.summary
    advising = [c for c in fake.calls if ADVISER_PROMPT in str(c["system"])]
    assert advising
    for call in advising:
        offered = set(call["tools"]) - {"finish"}
        assert offered <= ADVISER_TOOLS, offered
        assert not PC_TOOLS & offered


@pytest.mark.asyncio
async def test_a_pc_call_from_anyone_else_is_refused_when_it_runs(
    make_studio, tmp_path: Path
) -> None:
    """Checked again at the call, not only when tools are handed out."""
    respond, note, box = hands_script(tmp_path)
    studio, _ = await pc_studio(
        make_studio, tmp_path, respond, f"{LOCAL_MODEL_PREFIX}qwen", box=box
    )
    toolbox = studio._toolbox()
    from free_claude_code.studio.llm import ToolCall

    outcome = await toolbox.run(
        ToolCall(
            id="x",
            name="pc_files",
            arguments={"action": "write", "path": str(note), "content": "no"},
        ),
        ToolContext(agent_id="a", chat_id="c", agent_name="Researcher", pc_hands=False),
    )
    assert outcome.failed and "only Jarvis" in outcome.text
    assert not note.exists()


@pytest.mark.asyncio
async def test_the_routes_show_and_stop_and_only_this_pc_changes_the_level(
    make_studio, tmp_path: Path
) -> None:
    respond, _, box = hands_script(tmp_path)
    studio, _ = await pc_studio(
        make_studio, tmp_path, respond, f"{LOCAL_MODEL_PREFIX}qwen", box=box
    )
    from free_claude_code.api import studio_routes

    state = await studio_routes.pc_control_state(studio=studio, _=None)
    assert (
        state["enabled"] is True
        and state["level"] == "full"
        and state["active"] is True
    )
    stopped = await studio_routes.pc_control_stop(studio=studio, _=None)
    assert stopped["stopped"] is True and stopped["active"] is False

    from fastapi import HTTPException
    from starlette.requests import Request

    remote = Request({"type": "http", "client": ("203.0.113.9", 5000), "headers": []})
    with pytest.raises(HTTPException):
        await studio_routes.pc_control_resume(request=remote, studio=studio, _=None)
    assert studio.pc_control.stopped


@pytest.mark.asyncio
async def test_stop_turns_down_pc_steps_waiting_for_approval(
    make_studio, tmp_path: Path
) -> None:
    respond, _, box = hands_script(tmp_path)
    studio, _ = await pc_studio(
        make_studio, tmp_path, respond, f"{LOCAL_MODEL_PREFIX}qwen", box=box
    )
    ran: list[str] = []

    async def run() -> tuple[int, str, bool]:
        ran.append("ran")
        return 0, "done", False

    async def ask(command: str):
        return await studio._commands.request(
            agent_id="a",
            agent_name="Jarvis",
            chat_id="c",
            site_id="",
            command=command,
            cwd=tmp_path,
            policy="ask",
            timeout=5,
            run=run,
        )

    pc_step = asyncio.create_task(ask("[PC] del notes.txt"))
    other = asyncio.create_task(ask("npm test"))
    while len(await studio.pending_commands()) < 2:
        await asyncio.sleep(0.01)
    await studio.stop_pc()
    result = await asyncio.wait_for(pc_step, 5)
    assert result.request.status == "denied" and not ran
    # Other agents' commands are left for the owner to decide.
    assert [r.command for r in await studio.pending_commands()] == ["npm test"]
    other.cancel()
