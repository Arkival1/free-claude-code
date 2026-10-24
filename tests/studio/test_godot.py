"""Godot 4 in FCC: the engine (downloaded once, SHA-512 checked, kept in the
Repo vault), the demo library, the starters, and the godot tool."""

import hashlib
import io
import os
import shutil
import zipfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio import godot
from free_claude_code.studio.godot import engine as godot_engine
from free_claude_code.studio.godot.engine import (
    GodotEngine,
    GodotError,
    Report,
    read_lines,
)
from free_claude_code.studio.vault import RepoVault

from .test_builder_images import builder_in_project, run

ROOT = Path(__file__).resolve().parents[2]
REAL_GODOT = os.environ.get("FCC_GODOT_BIN", "")


def test_the_library_ships_with_its_checksum_and_licences():
    digest = hashlib.sha256(godot.DEMOS.read_bytes()).hexdigest()
    assert f"{digest}  demos.json.gz" in (ROOT / "vendor/godot/SHA256SUMS").read_text()
    for licence in ("LICENSE", "LICENSE-demos.md"):
        text = (ROOT / "vendor/godot" / licence).read_text()
        assert "Permission is hereby granted" in text
    sums = (ROOT / "vendor/godot/SHA512-SUMS.txt").read_text()
    for name, sha in godot_engine.BUILDS.values():
        assert f"{sha}  {name}" in sums
    assert f"{godot_engine.TEMPLATES[1]}  {godot_engine.TEMPLATES[0]}" in sums
    assert len(godot.demos()) == 133
    assert not any(item.id.startswith("mono/") for item in godot.demos())


def test_demos_are_found_by_words_and_read():
    found = godot.find_demos("platformer jump")
    assert found and found[0].id in {
        "2d/platformer",
        "2d/physics_platformer",
        "3d/platformer",
    }
    item = godot.demo("3d/ragdoll_physics")
    assert "project.godot" in item.files and any(p.endswith(".gd") for p in item.files)
    with pytest.raises(godot.GodotLibraryError, match="No demo"):
        godot.demo("nope")
    with pytest.raises(godot.GodotLibraryError, match="Say what"):
        godot.find_demos(" ")


@pytest.mark.parametrize("name", godot.starter_names())
def test_every_starter_comes_with_its_art_and_name(name):
    files = godot.starter_files(name, 'Sky "Hop"')
    assert {"project.godot", "main.tscn", "main.gd", "player.gd"} <= set(files)
    assert b'config/name="Sky Hop"' in files["project.godot"]
    for target in godot.STARTER_ART[name]:
        assert files[target]
    with pytest.raises(godot.GodotLibraryError, match="No starter"):
        godot.starter_files("mmo")


def test_godot_lines_become_problems_and_warnings():
    output = (
        'SCRIPT ERROR: Parse Error: Identifier "x" not declared.\n'
        "   at: GDScript::reload (res://player.gd:3)\n"
        "WARNING: The variable 'y' is never used.\n"
        'ERROR: Couldn\'t find the given section "preset.0" and key "include_filter"\n'
    )
    problems, warnings = read_lines(output)
    assert problems == [
        'SCRIPT ERROR: Parse Error: Identifier "x" not declared. (at: GDScript::reload (res://player.gd:3))'
    ]
    assert warnings and "never used" in warnings[0]


def fake_release(tmp_path: Path) -> tuple[bytes, str]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("Godot_v4.7.2-stable_linux.x86_64", b"#!/bin/sh\necho godot\n")
    data = buffer.getvalue()
    return data, hashlib.sha512(data).hexdigest()


@pytest.mark.asyncio
async def test_godot_downloads_once_and_comes_back_from_the_vault(
    tmp_path, monkeypatch
):
    data, digest = fake_release(tmp_path)
    monkeypatch.setitem(
        godot_engine.BUILDS, "linux", ("Godot_v4.7.2-stable_linux.x86_64.zip", digest)
    )
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=data)

    vault = RepoVault(tmp_path / "vault")
    engine = GodotEngine(
        tmp_path / "godot",
        vault=vault,
        transport=httpx.MockTransport(handle),
        platform="linux",
    )
    program = await engine.install()
    assert program.is_file() and os.access(program, os.X_OK)
    assert seen and "4.7.2-stable" in seen[0]
    kept = await vault.items()
    assert kept and kept[0].repo == "godot"

    # GitHub has deleted the release: the vault's copy is used.
    shutil.rmtree(tmp_path / "godot")
    gone = GodotEngine(
        tmp_path / "godot",
        vault=vault,
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
        platform="linux",
    )
    assert (await gone.install()).is_file()


@pytest.mark.asyncio
async def test_a_download_that_doesnt_match_godots_checksum_is_refused(tmp_path):
    data, _ = fake_release(tmp_path)
    engine = GodotEngine(
        tmp_path / "godot",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=data)
        ),
        platform="linux",
    )
    with pytest.raises(GodotError, match="checksum"):
        await engine.install()
    assert engine.binary() is None


@pytest.mark.asyncio
async def test_agents_start_a_godot_game_and_read_demos(make_studio):
    studio, _ = make_studio([])
    site, context = await builder_in_project(studio)
    started = await run(
        studio, context, "godot", action="start", starter="rpg-topdown", title="Village"
    )
    assert not started.failed, started.text
    paths = {item.path for item in await studio.workspace.files(site.id)}
    assert {"project.godot", "main.gd", "assets/tiles.png"} <= paths
    found = await run(studio, context, "godot", action="demos", query="tilemap")
    assert not found.failed and found.data["demos"]
    shown = await run(
        studio, context, "godot", action="demo", id=found.data["demos"][0]
    )
    assert "Godot demo, MIT" in shown.text
    missing = await run(
        studio, context, "godot", action="demo", id="2d/platformer", file="x.gd"
    )
    assert missing.failed and "Files:" in missing.text


@pytest.mark.asyncio
async def test_check_reports_every_problem_for_the_agent_to_fix(
    make_studio, monkeypatch
):
    studio, _ = make_studio([])
    _, context = await builder_in_project(studio)
    await run(studio, context, "godot", action="start", starter="platformer-2d")

    async def check(project, *, frames=300):
        assert (project / "project.godot").is_file()
        return Report(
            passed=False, problems=["SCRIPT ERROR: Parse Error (res://player.gd:3)"]
        )

    monkeypatch.setattr(studio.godot, "check", check)
    checked = await run(studio, context, "godot", action="check")
    assert checked.failed and "player.gd:3" in checked.text


@pytest.mark.asyncio
async def test_builders_and_coders_get_godot(make_studio):
    studio, _ = make_studio([])
    agents = await studio.ensure_defaults()
    for name in ("Builder", "Coder"):
        agent = next(item for item in agents if item.name == name)
        assert "godot" in agent.tools, name


@pytest.mark.skipif(not REAL_GODOT, reason="set FCC_GODOT_BIN to a Godot 4.7.2 program")
@pytest.mark.asyncio
@pytest.mark.parametrize("name", godot.starter_names())
async def test_every_starter_runs_in_real_godot(tmp_path, name):
    root = tmp_path / "godot"
    (root / godot_engine.VERSION).mkdir(parents=True)
    shutil.copy(REAL_GODOT, root / godot_engine.VERSION / Path(REAL_GODOT).name)
    project = tmp_path / name
    for path, data in godot.starter_files(name, "Test").items():
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_bytes(data)
    report = await GodotEngine(root, platform="linux").check(project)
    assert report.passed, report.problems


@pytest.mark.asyncio
async def test_two_agents_installing_at_once_download_once(tmp_path, monkeypatch):
    import asyncio

    data, digest = fake_release(tmp_path)
    monkeypatch.setitem(
        godot_engine.BUILDS, "linux", ("Godot_v4.7.2-stable_linux.x86_64.zip", digest)
    )
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=data)

    engine = GodotEngine(
        tmp_path / "godot", transport=httpx.MockTransport(handle), platform="linux"
    )
    first, second = await asyncio.gather(engine.install(), engine.install())
    assert first == second and first.is_file() and len(calls) == 1


@pytest.mark.asyncio
async def test_a_damaged_vault_copy_falls_back_to_github(tmp_path, monkeypatch):
    data, digest = fake_release(tmp_path)
    name = "Godot_v4.7.2-stable_linux.x86_64.zip"
    monkeypatch.setitem(godot_engine.BUILDS, "linux", (name, digest))
    vault = RepoVault(tmp_path / "vault")
    damaged = tmp_path / name
    damaged.write_bytes(b"not godot")
    await vault.keep_file(
        owner="godotengine", repo="godot", kind="release", path=damaged, url="x"
    )
    engine = GodotEngine(
        tmp_path / "godot",
        vault=vault,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=data)
        ),
        platform="linux",
    )
    assert (await engine.install()).is_file()


@pytest.mark.asyncio
async def test_a_step_that_doesnt_finish_fails_the_check(tmp_path, monkeypatch):
    engine = GodotEngine(tmp_path / "godot", platform="linux")
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n")
    program = tmp_path / "godot-program"
    program.write_text("")

    async def install():
        return program

    async def fake_run(args, *, cwd, timeout):
        if "--import" in args:
            return godot_engine.TIMED_OUT, "Godot was stopped after 120 seconds."
        return 0, ""

    monkeypatch.setattr(engine, "install", install)
    monkeypatch.setattr(engine, "_run", fake_run)
    report = await engine.check(project)
    assert (
        not report.passed
        and "Importing the project didn't finish" in report.problems[0]
    )


@pytest.mark.asyncio
async def test_export_without_a_preset_downloads_nothing(tmp_path):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing should be downloaded")

    engine = GodotEngine(
        tmp_path / "godot", transport=httpx.MockTransport(refuse), platform="windows"
    )
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n")
    with pytest.raises(GodotError, match='no "Windows Desktop" export preset'):
        await engine.export(project, tmp_path / "out" / "game.exe")


def test_unpacks_are_whole_or_nothing_and_stay_in_their_folder(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as bundle:
        bundle.writestr("../escaped.txt", b"x")
    with pytest.raises(GodotError, match="outside"):
        godot_engine._unpack(evil, tmp_path / "engine")
    with pytest.raises(GodotError, match="outside"):
        godot_engine._unpack_templates(evil, tmp_path / "templates")
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "templates" / "version.txt").exists()
    good = tmp_path / "good.tpz"
    with zipfile.ZipFile(good, "w") as bundle:
        bundle.writestr("templates/version.txt", b"4.7.2.stable")
        bundle.writestr("templates/windows_release_x86_64.exe", b"exe")
    godot_engine._unpack_templates(good, tmp_path / "templates")
    assert (tmp_path / "templates" / "version.txt").is_file()


@pytest.mark.asyncio
async def test_a_step_that_crashes_without_saying_why_fails_the_check(
    tmp_path, monkeypatch
):
    engine = GodotEngine(tmp_path / "godot", platform="linux")
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n")

    async def install():
        return tmp_path / "godot-program"

    async def fake_run(args, *, cwd, timeout):
        return (1, "") if "--script" in args else (0, "")

    monkeypatch.setattr(engine, "install", install)
    monkeypatch.setattr(engine, "_run", fake_run)
    report = await engine.check(project)
    assert not report.passed and "stopped with code 1" in report.problems[0]
    assert engine.state == "ready"


@pytest.mark.asyncio
async def test_a_failed_install_says_so_and_leaves_no_files(tmp_path):
    engine = GodotEngine(
        tmp_path / "godot",
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
        platform="linux",
    )
    with pytest.raises(GodotError, match="404"):
        await engine.install()
    assert engine.state == "failed"
    assert not any((tmp_path / "godot").glob("*.zip*"))


@pytest.mark.asyncio
async def test_frames_clamps_any_length_and_resets_after_errors(tmp_path, monkeypatch):
    engine = GodotEngine(tmp_path / "godot", platform="windows")
    asked: list[list[str]] = []

    async def install():
        return tmp_path / "godot-program"

    async def fake_run(args, *, cwd, timeout):
        asked.append(list(args))
        raise GodotError("Godot couldn't start: missing")

    monkeypatch.setattr(engine, "install", install)
    monkeypatch.setattr(engine, "_run", fake_run)
    for seconds in (1e308, -1e308, float("nan")):
        with pytest.raises(GodotError):
            await engine.frames(tmp_path, tmp_path / "shot.png", seconds=seconds)
        assert engine.state == "failed"
    counts = [int(args[args.index("--quit-after") + 1]) for args in asked]
    assert counts == [600, 9, 90]
