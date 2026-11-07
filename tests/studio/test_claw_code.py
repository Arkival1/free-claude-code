"""Claw Code: kept in FCC, built on this PC, run through FCC."""

import hashlib
import sys
import zipfile
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest

from free_claude_code.cli.launchers import claw as claw_launcher
from free_claude_code.cli.launchers.runner import LaunchContext
from free_claude_code.harnesses.resources import LaunchResources
from free_claude_code.studio import StudioError
from free_claude_code.studio.claw import (
    SOURCE_ZIP,
    VENDOR,
    BuildState,
    ClawCode,
    ClawError,
    binary_name,
    terminal_command,
    unpack,
)
from tests.api.support import create_test_app


def test_claw_code_is_vendored_with_its_licence_and_checksum():
    archive = VENDOR / SOURCE_ZIP
    assert "MIT License" in (VENDOR / "LICENSE").read_text()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert f"{digest}  {SOURCE_ZIP}" in (VENDOR / "SHA256SUMS").read_text()
    names = zipfile.ZipFile(archive).namelist()
    assert "claw-code/rust/Cargo.lock" in names
    assert "claw-code/rust/crates/rusty-claude-cli/src/main.rs" in names
    assert "claw-code/LICENSE" in names
    assert not any("/target/" in name for name in names)
    readme = (VENDOR / "README.md").read_text()
    assert "08106b0c3771ef5b4a5aa176acccd460e88b7325" in readme
    assert "claw-code/" in (VENDOR.parent / "README.md").read_text()


def fake_vendor(tmp_path: Path) -> Path:
    vendor = tmp_path / "vendor"
    vendor.mkdir(parents=True)
    archive = vendor / SOURCE_ZIP
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("claw-code/rust/Cargo.toml", "[workspace]\n")
        bundle.writestr("claw-code/LICENSE", "MIT License")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (vendor / "SHA256SUMS").write_text(f"{digest}  {SOURCE_ZIP}\n")
    return vendor


def cargo_that_builds(command: Sequence[str], cwd: Path, state: BuildState) -> int:
    assert command[1:] == ("build", "--release", "--locked", "-p", "rusty-claude-cli")
    out = cwd / "target" / "release"
    out.mkdir(parents=True)
    (out / binary_name()).write_bytes(b"claw")
    state.add("Finished release")
    return 0


@pytest.mark.asyncio
async def test_claw_code_is_built_from_fccs_copy(tmp_path):
    claw = ClawCode(
        tmp_path / "root",
        vendor=fake_vendor(tmp_path),
        cargo=lambda: "cargo",
        runner=cargo_that_builds,
    )
    assert claw.status()["bundled"] and not claw.status()["built"]

    assert claw.start_build()["state"] == "building"
    await claw.wait()

    status = claw.status()
    assert status["state"] == "built" and status["built"]
    assert claw.binary.read_bytes() == b"claw"
    assert "Finished release" in claw.build_state.log


@pytest.mark.asyncio
async def test_a_build_needs_rust_and_an_undamaged_copy(tmp_path):
    vendor = fake_vendor(tmp_path)
    no_rust = ClawCode(tmp_path / "a", vendor=vendor, cargo=lambda: None)
    assert not no_rust.status()["rust"]
    with pytest.raises(ClawError, match=r"rustup\.rs"):
        no_rust.start_build()

    (vendor / SOURCE_ZIP).write_bytes(b"damaged")
    damaged = ClawCode(tmp_path / "b", vendor=vendor, cargo=lambda: "cargo")
    assert not damaged.status()["bundled"]
    with pytest.raises(ClawError, match="missing or damaged"):
        damaged.start_build()


@pytest.mark.asyncio
async def test_a_failed_build_says_so(tmp_path):
    def broken(command: Sequence[str], cwd: Path, state: BuildState) -> int:
        state.add("error[E0425]: cannot find value")
        return 101

    claw = ClawCode(
        tmp_path / "root",
        vendor=fake_vendor(tmp_path),
        cargo=lambda: "cargo",
        runner=broken,
    )
    claw.start_build()
    await claw.wait()
    status = claw.status()
    assert status["state"] == "failed" and not status["built"]
    assert "code 101" in claw.build_state.error
    assert "error[E0425]: cannot find value" in claw.build_state.log


def test_unpacking_never_writes_outside_its_folder(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../../escape.txt", "nope")
    with pytest.raises(ClawError, match="Unsafe path"):
        unpack(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_claw_opens_in_a_terminal_window(monkeypatch, tmp_path):
    launch = ["python", "-m", "free_claude_code.cli.launchers.claw"]
    monkeypatch.setattr(sys, "platform", "win32")
    assert terminal_command(launch, tmp_path) == [
        "cmd",
        "/c",
        "start",
        "Claw Code",
        "cmd",
        "/k",
        *launch,
    ]
    monkeypatch.setattr(sys, "platform", "darwin")
    mac = terminal_command(launch, tmp_path)
    assert mac[0] == "osascript" and str(tmp_path) in mac


def test_fcc_claw_connects_claw_code_to_fcc(monkeypatch, tmp_path, studio_settings):
    monkeypatch.setattr(claw_launcher, "studio_dir_path", lambda: tmp_path)
    assert claw_launcher.built_binary() in {None, claw_launcher.shutil.which("claw")}
    built = tmp_path / "claw-code" / "bin" / "claw"
    built.parent.mkdir(parents=True)
    built.write_bytes(b"claw")
    assert claw_launcher.built_binary() == str(built)

    context = LaunchContext(
        binary_path=str(built),
        settings=studio_settings(),
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="fcc-token",
        base_env={
            "ANTHROPIC_API_KEY": "sk-ant-real",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "OLLAMA_HOST": "http://127.0.0.1:11434",
            "PATH": "/usr/bin",
        },
        catalog=None,
    )
    with ExitStack() as stack:
        prepared = claw_launcher._configure(
            context, ["prompt", "hello"], LaunchResources(stack)
        )
    assert prepared.command == [str(built), "prompt", "hello"]
    assert prepared.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8082"
    assert prepared.env["ANTHROPIC_AUTH_TOKEN"] == "fcc-token"
    for gone in ("ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "OLLAMA_HOST"):
        assert gone not in prepared.env
    assert prepared.env["PATH"] == "/usr/bin"


@pytest.mark.asyncio
async def test_claw_code_through_the_routes(make_studio, tmp_path, monkeypatch):
    studio, _ = make_studio([])
    studio.claw = ClawCode(
        tmp_path / "claw",
        vendor=fake_vendor(tmp_path),
        cargo=lambda: "cargo",
        runner=cargo_that_builds,
    )
    opened: list[Path] = []
    monkeypatch.setattr(
        studio.claw, "open_terminal", lambda folder: opened.append(folder) or []
    )
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            status = (await client.get("/studio/api/claw")).json()
            assert status["bundled"] and not status["built"]
            await client.post("/studio/api/claw/build")
            await studio.claw.wait()
            assert (await client.get("/studio/api/claw")).json()["built"]
            opened_in = await client.post(
                "/studio/api/claw/open", json={"folder": str(tmp_path)}
            )
            assert opened_in.json()["opened_in"] == str(tmp_path)
            assert opened == [tmp_path]
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
    with pytest.raises(StudioError, match="no folder"):
        studio.claw = ClawCode(tmp_path / "x", vendor=fake_vendor(tmp_path / "v"))
        studio.claw.binary.parent.mkdir(parents=True)
        studio.claw.binary.write_bytes(b"claw")
        studio.open_claw(str(tmp_path / "missing"))


@pytest.mark.asyncio
async def test_only_the_pc_itself_can_build_or_open_claw_code(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    transport = httpx.ASGITransport(app=app, client=("192.168.1.20", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://pc") as client:
        try:
            assert (await client.get("/studio/api/claw")).status_code == 200
            assert (await client.post("/studio/api/claw/build")).status_code == 403
            refused = await client.post("/studio/api/claw/open", json={})
            assert refused.status_code == 403
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_a_web_page_in_the_browser_cannot_build_claw_code(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            refused = await client.post(
                "/studio/api/claw/build", headers={"origin": "https://evil.example"}
            )
            assert refused.status_code == 403
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


def test_a_hung_build_is_stopped(monkeypatch, tmp_path):
    from free_claude_code.studio import claw as claw_module

    monkeypatch.setattr(claw_module, "BUILD_TIMEOUT", 0.5)
    state = BuildState()
    code = claw_module.run_logged(
        [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, state
    )
    assert code == 1
    assert "took too long" in state.log[-1]


def test_each_linux_terminal_gets_the_command_its_way(monkeypatch, tmp_path):
    launch = ["python", "-m", "free_claude_code.cli.launchers.claw"]
    monkeypatch.setattr(sys, "platform", "linux")
    for terminal, flag in (("gnome-terminal", "--"), ("xfce4-terminal", "-x")):
        monkeypatch.setattr(
            "shutil.which",
            lambda name, t=terminal: f"/usr/bin/{t}" if name == t else None,
        )
        assert terminal_command(launch, tmp_path) == [
            f"/usr/bin/{terminal}",
            flag,
            *launch,
        ]
