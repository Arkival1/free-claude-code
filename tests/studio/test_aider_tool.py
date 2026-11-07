"""Aider as a helper: one job in one project folder, none of the owner's keys,
nothing left behind, and only after the owner's command setting allows it."""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from free_claude_code.core.json_types import JsonValue
from free_claude_code.studio.aider import (
    AiderError,
    AiderJob,
    aider_command,
    aider_env,
    job_files,
    run_aider,
)
from free_claude_code.studio.llm import ToolCall
from free_claude_code.studio.models import CommandRequest
from free_claude_code.studio.tools import ToolContext

FAKE_AIDER = """#!{python}
import json, os, pathlib, sys, time
args = sys.argv[1:]
files = args[args.index("--") + 1:]
message = pathlib.Path(args[args.index("--message-file") + 1]).read_text()
if "sleep" in message:
    time.sleep(30)
for name in files:
    path = pathlib.Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text() if path.exists() else ""
    path.write_text(old + "# edited by aider\\n")
cache = pathlib.Path(".aider.tags.cache.v4")
cache.mkdir(exist_ok=True)
(cache / "tags").write_text("x")
pathlib.Path(".aider.chat.history.md").write_text("chat")
print(json.dumps({{
    "home": os.environ.get("HOME"),
    "keys": sorted(n for n in os.environ if "KEY" in n.upper() and n != "OPENAI_API_KEY"),
    "aider_vars": sorted(n for n in os.environ if n.startswith("AIDER_")),
    "base": os.environ.get("OPENAI_API_BASE"),
    "key": os.environ.get("OPENAI_API_KEY"),
    "cwd": os.getcwd(),
    "args": args,
    "first": message.splitlines()[0],
    "read": {{
        pathlib.Path(args[i + 1]).name: pathlib.Path(args[i + 1]).read_bytes()[:40].decode("utf-8", "replace")
        for i, a in enumerate(args) if a == "--read"
    }},
    "pythonpath": os.environ.get("PYTHONPATH", ""),
}}))
"""


def fake_aider(folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "aider"
    path.write_text(FAKE_AIDER.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def job_for(folder: Path, files: tuple[str, ...], message: str = "Fix it") -> AiderJob:
    return AiderJob(
        folder=folder,
        message=message,
        files=files,
        model="nvidia_nim/test-model",
        base_url="http://127.0.0.1:8082/v1",
        api_key="fcc",
    )


def seen(output: str) -> dict[str, object]:
    line = next(text for text in output.splitlines() if text.startswith("{"))
    return json.loads(line)


@pytest.mark.parametrize(
    "bad",
    ["../outside.py", "/etc/passwd", ".git/config", ".venv/lib/x.py", "src"],
)
def test_aider_only_gets_files_inside_the_project(tmp_path, bad):
    (tmp_path / "src").mkdir()
    with pytest.raises(AiderError):
        job_files(tmp_path, [bad])


def test_aider_file_names_are_cleaned_and_capped(tmp_path):
    assert job_files(tmp_path, ["./app.py", "app.py", ".env.example"]) == (
        "app.py",
        ".env.example",
    )
    with pytest.raises(AiderError, match="at most"):
        job_files(tmp_path, [f"f{n}.py" for n in range(13)])
    with pytest.raises(AiderError, match="Name the files"):
        job_files(tmp_path, [" "])


def test_the_command_turns_off_git_shell_links_and_extras(tmp_path):
    job = job_for(tmp_path / "project", ("a.py",))
    command = aider_command("aider", job, tmp_path / "scratch")
    for flag in (
        "--no-git",
        "--no-auto-commits",
        "--no-suggest-shell-commands",
        "--no-detect-urls",
        "--no-analytics",
        "--no-check-update",
        "--no-auto-test",
        "--yes-always",
    ):
        assert flag in command
    assert command[command.index("--model") + 1] == "openai/nvidia_nim/test-model"
    # The files come last, after "--", so a name can't pass as a flag.
    assert command[-2:] == ["--", "a.py"]
    history = command[command.index("--chat-history-file") + 1]
    assert history.startswith(str(tmp_path / "scratch"))


def test_aider_gets_no_keys_and_none_of_the_owners_aider_settings(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nvapi-secret")
    monkeypatch.setenv("AIDER_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    env = aider_env(job_for(tmp_path, ("a.py",)), tmp_path / "scratch")
    assert "NVIDIA_NIM_API_KEY" not in env and "AIDER_MODEL" not in env
    assert env["OPENAI_API_BASE"] == "http://127.0.0.1:8082/v1"
    assert env["OPENAI_API_KEY"] == "fcc"
    assert env["HOME"] == str(tmp_path / "scratch")


@pytest.mark.asyncio
async def test_a_job_changes_its_files_and_leaves_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("x = 1\n")
    (project / "other.py").write_text("y = 2\n")
    aider = fake_aider(tmp_path / "bin")
    result = await run_aider(
        job_for(project, ("app.py", "new/util.py")), aider=aider, timeout=60
    )
    assert result.code == 0, result.output
    assert result.changed == ["app.py"] and result.added == ["new/util.py"]
    assert (project / "other.py").read_text() == "y = 2\n"
    assert not any(path.name.startswith(".aider") for path in project.iterdir())
    facts = seen(result.output)
    assert facts["keys"] == [] and facts["aider_vars"] == []
    assert facts["cwd"] == str(project.resolve())
    assert facts["home"] != os.environ.get("HOME")
    assert "Do this job in the files listed" in str(facts["first"])


@pytest.mark.asyncio
async def test_a_job_that_runs_too_long_is_stopped(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    aider = fake_aider(tmp_path / "bin")
    result = await run_aider(
        job_for(project, ("a.py",), message="sleep"), aider=aider, timeout=1
    )
    assert result.timed_out and result.code != 0
    assert "Stopped after 1 seconds" in result.output


async def project_for(studio):
    agent = await studio.create_agent(name="Maker", model="nvidia_nim/test-model")
    site = await studio.create_site(name="App")
    chat = await studio.create_chat(agent_id=agent.id, site_id=site.id)
    folder = studio.workspace.directory(site.id)
    (folder / "app.py").write_text("x = 1\n")
    return agent, site, chat


def call(
    files: list[JsonValue] | None = None, task: str = "Add a docstring"
) -> ToolCall:
    chosen: list[JsonValue] = ["app.py"] if files is None else files
    return ToolCall(id="1", name="aider", arguments={"task": task, "files": chosen})


@pytest.mark.asyncio
async def test_aider_waits_for_the_owners_command_setting(make_studio):
    studio, _ = make_studio([])
    agent, site, chat = await project_for(studio)
    outcome = await studio._aider_tool(
        call(), ToolContext(agent_id=agent.id, chat_id=chat.id, site_id=site.id)
    )
    assert outcome.failed and "Agents Can Run Commands" in outcome.text


@pytest.mark.asyncio
async def test_aider_says_how_to_install_it(make_studio, monkeypatch):
    studio, _ = make_studio([], STUDIO_AGENT_COMMANDS="auto")
    monkeypatch.setattr("free_claude_code.studio.service.find_aider", lambda: None)
    agent, site, chat = await project_for(studio)
    outcome = await studio._aider_tool(
        call(), ToolContext(agent_id=agent.id, chat_id=chat.id, site_id=site.id)
    )
    assert outcome.failed and "uv tool install aider-chat" in outcome.text


@pytest.mark.asyncio
async def test_aider_needs_a_project(make_studio):
    studio, _ = make_studio([], STUDIO_AGENT_COMMANDS="auto")
    outcome = await studio._aider_tool(
        call(), ToolContext(agent_id="a", chat_id="c", site_id=None)
    )
    assert outcome.failed and "project" in outcome.text


@pytest.mark.asyncio
async def test_aider_does_a_job_in_the_project_through_fcc(
    make_studio, tmp_path, monkeypatch
):
    studio, _ = make_studio([], STUDIO_AGENT_COMMANDS="auto", PORT=8099)
    aider = fake_aider(tmp_path / "bin")
    monkeypatch.setattr("free_claude_code.studio.service.find_aider", lambda: aider)
    agent, site, chat = await project_for(studio)
    outcome = await studio._aider_tool(
        call(), ToolContext(agent_id=agent.id, chat_id=chat.id, site_id=site.id)
    )
    assert not outcome.failed, outcome.text
    assert outcome.data["changed"] == ["app.py"]
    folder = studio.workspace.directory(site.id)
    assert "# edited by aider" in (folder / "app.py").read_text()
    facts = seen(outcome.text)
    # A server model goes through FCC's own address, never a provider's.
    assert facts["base"] == "http://127.0.0.1:8099/v1"
    assert facts["key"] == "fcc"
    ran = await studio.store.find(CommandRequest)
    assert [item.status for item in ran] == ["ran"]
    assert ran[0].command.startswith("aider --model openai/nvidia_nim/test-model")


@pytest.mark.asyncio
async def test_aider_rejects_a_file_outside_the_project(make_studio, monkeypatch):
    studio, _ = make_studio([], STUDIO_AGENT_COMMANDS="auto")
    monkeypatch.setattr("free_claude_code.studio.service.find_aider", lambda: "aider")
    agent, site, chat = await project_for(studio)
    outcome = await studio._aider_tool(
        call(["../../secrets.txt"]),
        ToolContext(agent_id=agent.id, chat_id=chat.id, site_id=site.id),
    )
    assert outcome.failed and "inside the project" in outcome.text
    assert await studio.store.find(CommandRequest) == ()


def test_a_local_model_talks_to_the_model_server_on_this_pc(make_studio, tmp_path):
    studio, _ = make_studio([], STUDIO_LOCAL_BASE_URL="http://localhost:1234/v1")
    job = studio._aider_job(tmp_path, "Fix it", ("a.py",), "local/qwen3-4b")
    assert job.model == "qwen3-4b" and job.base_url == "http://localhost:1234/v1"
    assert job.edit_format == "whole"
    server = studio._aider_job(tmp_path, "Fix it", ("a.py",), "nvidia_nim/x")
    assert server.edit_format == "diff" and server.base_url.endswith("/v1")


def test_the_command_carries_skills_tests_lint_architect_and_map(tmp_path):
    from dataclasses import replace

    job = replace(
        job_for(tmp_path / "project", ("a.py",)),
        reading=(("fcc-skills.md", "# Debugging"),),
        pictures=(tmp_path / "shot.png",),
        test_command="python -m pytest -q -x",
        editor_model="lmstudio/qwen3-4b",
        map_tokens=1024,
    )
    command = aider_command("aider", job, tmp_path / "scratch")
    reads = [command[i + 1] for i, part in enumerate(command) if part == "--read"]
    assert reads == [
        str(tmp_path / "scratch" / "read" / "fcc-skills.md"),
        str(tmp_path / "scratch" / "read" / "1-shot.png"),
    ]
    assert command[command.index("--test-cmd") + 1] == "python -m pytest -q -x"
    assert "--auto-test" in command and "--auto-lint" in command
    assert "--architect" in command and "--edit-format" not in command
    assert command[command.index("--editor-model") + 1] == "openai/lmstudio/qwen3-4b"
    assert command[command.index("--weak-model") + 1] == "openai/lmstudio/qwen3-4b"
    assert command[command.index("--map-tokens") + 1] == "1024"
    plain = aider_command("aider", job_for(tmp_path, ("a.py",)), tmp_path / "s")
    assert "--no-auto-test" in plain and "--test-cmd" not in plain
    assert "--architect" not in plain and plain[plain.index("--map-tokens") + 1] == "0"


@pytest.mark.asyncio
async def test_aider_reads_its_skills_and_pictures_without_touching_the_project(
    tmp_path,
):
    from dataclasses import replace

    project = tmp_path / "project"
    project.mkdir()
    picture = tmp_path / "home-pc.png"
    picture.write_bytes(b"\x89PNG fake")
    job = replace(
        job_for(project, ("app.py",)),
        reading=(
            ("fcc-skills.md", "# Vibe coding"),
            ("changer-notebook.md", "GOAL: x"),
        ),
        pictures=(picture,),
        env=(("PYTHONPATH", "/copy/src"),),
    )
    result = await run_aider(job, aider=fake_aider(tmp_path / "bin"), timeout=60)
    facts = seen(result.output)
    read = facts["read"]
    assert isinstance(read, dict)
    assert read["fcc-skills.md"] == "# Vibe coding"
    assert read["changer-notebook.md"] == "GOAL: x"
    assert read["1-home-pc.png"].startswith("\ufffdPNG")
    assert facts["pythonpath"] == "/copy/src"
    assert sorted(p.name for p in project.iterdir()) == ["app.py"]


async def copy_studio(make_studio, tmp_path, **settings):
    from free_claude_code.studio.changer import Changer
    from tests.studio.test_changer import make_app

    studio, _ = make_studio([], STUDIO_AGENT_COMMANDS="auto", **settings)
    studio._changer = Changer(
        tmp_path / "changer",
        source=make_app(tmp_path / "fcc"),
        import_check="print('ok')",
    )
    copy = await studio.changer_fresh_copy()
    changer = await studio._changer_agent()
    return studio, copy, changer


@pytest.mark.asyncio
async def test_in_the_changer_copy_aider_gets_the_notebook_and_related_tests(
    make_studio, tmp_path
):
    from free_claude_code.studio.models import ChangeProject

    studio, copy, changer = await copy_studio(make_studio, tmp_path)
    await studio._store.put(
        ChangeProject(request="Make lab fizz louder", status="building")
    )
    folder = studio.workspace.directory(copy.id)
    (folder / "tests" / "test_lab.py").write_text(
        "from free_claude_code.studio.lab import mix\n\n"
        "def test_mix():\n    assert mix() == 'fizz'\n"
    )
    job = await studio._aider_extras(
        studio._aider_job(
            folder, "Fix mix()", ("src/free_claude_code/studio/lab.py",), changer.model
        ),
        changer,
        {"repo_map": True},
        in_copy=True,
    )
    names = [name for name, _ in job.reading]
    assert names == ["fcc-skills.md", "changer-notebook.md"]
    notebook = dict(job.reading)["changer-notebook.md"]
    assert "GOAL (the owner's words; keep to it): Make lab fizz louder" in notebook
    assert "-m pytest -q -x" in job.test_command
    assert job.test_command.endswith("tests/test_lab.py")
    assert job.read_paths == ("tests/test_lab.py",)
    assert job.map_tokens == 1024
    assert dict(job.env)["PYTHONPATH"] == str(folder / "src")


@pytest.mark.asyncio
async def test_aider_in_the_copy_writes_what_it_changed_in_the_notebook(
    make_studio, tmp_path, monkeypatch
):
    from free_claude_code.studio.models import ChangeProject

    studio, copy, changer = await copy_studio(make_studio, tmp_path)
    project = ChangeProject(request="Louder fizz", status="building")
    await studio._store.put(project)
    aider = fake_aider(tmp_path / "bin")
    monkeypatch.setattr("free_claude_code.studio.service.find_aider", lambda: aider)
    outcome = await studio._aider_tool(
        ToolCall(
            id="1",
            name="aider",
            arguments={
                "task": "Make it louder",
                "files": ["src/free_claude_code/studio/lab.py"],
            },
        ),
        ToolContext(
            agent_id=changer.id, chat_id="c", site_id=copy.id, agent_name="Changer"
        ),
    )
    assert not outcome.failed, outcome.text
    notes = await studio.change_notes(project.id)
    assert notes[-1].author == "Aider"
    assert "src/free_claude_code/studio/lab.py" in notes[-1].text


@pytest.mark.asyncio
async def test_architect_mode_keeps_both_models_on_one_address(make_studio, tmp_path):
    studio, _ = make_studio([], STUDIO_AIDER_EDITOR_MODEL="local/qwen3-4b")
    agent = await studio.create_agent(
        name="Coder", role="coder", model="nvidia_nim/big"
    )

    async def extras(model: str):
        return await studio._aider_extras(
            studio._aider_job(tmp_path, "x", ("a.py",), model),
            agent,
            {"architect": True},
            in_copy=False,
        )

    server = await extras("nvidia_nim/big")
    # A local editor can't sit behind FCC's address with a server planner.
    assert server.editor_model == "nvidia_nim/big"
    local = await extras("local/qwen3-8b")
    assert (local.model, local.editor_model) == ("qwen3-8b", "qwen3-4b")


@pytest.mark.asyncio
async def test_screenshots_need_a_vision_model_and_it_plans(make_studio, tmp_path):
    from free_claude_code.studio.aider import AiderError

    (tmp_path / "shot.png").write_bytes(b"png")
    blind, _ = make_studio([])
    agent = await blind.create_agent(name="Coder", role="coder", model="nvidia_nim/big")
    base = blind._aider_job(tmp_path, "x", ("a.py",), "nvidia_nim/big")
    with pytest.raises(AiderError, match="Vision Model"):
        await blind._aider_extras(base, agent, {"images": ["shot.png"]}, in_copy=False)
    seeing, _ = make_studio([], STUDIO_VISION_MODEL="nvidia_nim/vl")
    job = await seeing._aider_extras(
        base, agent, {"images": ["shot.png"]}, in_copy=False
    )
    assert (job.model, job.editor_model) == ("nvidia_nim/vl", "nvidia_nim/big")
    assert job.pictures == ((tmp_path / "shot.png").resolve(),)
    with pytest.raises(AiderError, match="picture file"):
        await seeing._aider_extras(base, agent, {"images": ["../x.png"]}, in_copy=False)


@pytest.mark.parametrize(
    ("files", "wanted"),
    [
        ({"tests/test_a.py": "def test_a(): pass\n"}, "-m pytest -q -x"),
        ({"tests/conftest.py": "import pytest\n"}, ""),
        ({"test_b.py": "def test_b(): pass\n"}, "-m pytest -q -x"),
        (
            {"package.json": '{"scripts": {"test": "node test.js"}}'},
            "npm test --silent",
        ),
        ({"package.json": '{"scripts": {}}'}, ""),
        ({"index.html": "<h1>x</h1>"}, ""),
    ],
)
def test_fcc_picks_the_projects_test_command(make_studio, tmp_path, files, wanted):
    studio, _ = make_studio([])
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    command, reads, _ = studio._aider_tests(tmp_path, ["a.py"], in_copy=False)
    assert (wanted in command) if wanted else command == ""
    if "pytest" in command:
        assert reads and all(name.endswith(".py") for name in reads)


@pytest.mark.asyncio
async def test_a_test_file_with_shell_characters_never_reaches_the_command(
    make_studio, tmp_path
):
    studio, copy, _ = await copy_studio(make_studio, tmp_path)
    folder = studio.workspace.directory(copy.id)
    plain = folder / "tests" / "test_lab.py"
    hostile = folder / "tests" / "test_a;touch pwned $(id).py"
    for path in (plain, hostile):
        path.write_text(
            "from free_claude_code.studio.lab import mix\n\n"
            "def test_mix():\n    assert mix()\n"
        )
    command, reads, skipped = studio._aider_tests(
        folder,
        ["src/free_claude_code/studio/lab.py", hostile.relative_to(folder).as_posix()],
        in_copy=True,
    )
    assert "tests/test_lab.py" in command
    assert ";" not in command and "$(" not in command and "pwned" not in command
    assert reads == ("tests/test_lab.py",)
    assert skipped == ("tests/test_a;touch pwned $(id).py",)


@pytest.mark.asyncio
async def test_skipped_test_files_are_named_in_the_notebook(make_studio, tmp_path):
    from free_claude_code.studio.models import ChangeProject

    studio, copy, changer = await copy_studio(make_studio, tmp_path)
    project = ChangeProject(request="Louder fizz", status="building")
    await studio._store.put(project)
    folder = studio.workspace.directory(copy.id)
    odd = folder / "tests" / "test_my$lab.py"
    odd.write_text("from free_claude_code.studio.lab import mix\n")
    await studio._aider_extras(
        studio._aider_job(
            folder,
            "x",
            ("src/free_claude_code/studio/lab.py", "tests/test_my$lab.py"),
            changer.model,
        ),
        changer,
        {},
        in_copy=True,
    )
    notes = await studio.change_notes(project.id)
    assert any("tests/test_my$lab.py" in n.text and n.author == "FCC" for n in notes)


@pytest.mark.asyncio
async def test_two_pictures_with_one_name_both_reach_aider(tmp_path):
    from dataclasses import replace

    project = tmp_path / "project"
    (project / "a").mkdir(parents=True)
    (project / "b").mkdir()
    (project / "a" / "shot.png").write_bytes(b"first")
    (project / "b" / "shot.png").write_bytes(b"second")
    job = replace(
        job_for(project, ("app.py",)),
        pictures=(project / "a" / "shot.png", project / "b" / "shot.png"),
    )
    command = aider_command("aider", job, tmp_path / "scratch")
    assert "--model-metadata-file" in command
    result = await run_aider(job, aider=fake_aider(tmp_path / "bin"), timeout=60)
    read = seen(result.output)["read"]
    assert isinstance(read, dict)
    assert read["1-shot.png"] == "first" and read["2-shot.png"] == "second"
