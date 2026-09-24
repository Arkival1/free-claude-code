"""The Windows desktop app scripts, checked with dry runs wherever pwsh exists."""

import shutil
import struct
import subprocess
from pathlib import Path

import pytest

WINDOWS = Path(__file__).resolve().parents[2] / "scripts" / "windows"
PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is not installed")


def dry_run(script: str, *args: str) -> str:
    assert PWSH is not None
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(WINDOWS / script), "-DryRun", *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_the_app_icon_is_a_real_icon_file():
    data = (WINDOWS / "studio.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, 1)
    size, offset = struct.unpack("<II", data[14:22])
    assert data[offset : offset + 8] == b"\x89PNG\r\n\x1a\n"
    assert offset + size == len(data)


def test_the_double_click_files_call_their_scripts():
    installer = (WINDOWS / "install-studio-app.cmd").read_text()
    assert "install-studio-app.ps1" in installer
    assert "-ExecutionPolicy Bypass" in installer


@needs_pwsh
def test_the_app_opens_studio_in_its_own_window():
    output = dry_run("studio-app.ps1")

    assert "start hidden: uv run --python cpython-3.14.0-windows-x86_64-none" in output
    assert "--extra studio_voice fcc-server" in output
    assert "--app=http://localhost:8082/studio" in output
    assert "--user-data-dir=" in output
    assert "stop the server when the window closes" in output


@needs_pwsh
def test_the_app_can_leave_the_server_running_for_a_phone():
    output = dry_run("studio-app.ps1", "-KeepServer", "-Port", "9000", "-NoVoice")

    assert "--app=http://localhost:9000/studio" in output
    assert "studio_voice" not in output
    assert "stop the server" not in output


@needs_pwsh
def test_installing_sets_up_once_and_adds_icons():
    output = dry_run("install-studio-app.ps1", "-StartWithWindows", "-NoLaunch")

    assert "uv sync --python cpython-3.14.0-windows-x86_64-none" in output
    for place in ("<Desktop>", "<Start menu>", "<Startup>"):
        assert (
            f"{place}/FCC Studio.lnk" in output or f"{place}\\FCC Studio.lnk" in output
        )
    assert "-WindowStyle Hidden -File" in output
    assert "studio-app.ps1" in output
    assert "studio.ico" in output
    assert "Opening FCC Studio" not in output


@needs_pwsh
def test_uninstalling_only_removes_icons():
    output = dry_run("install-studio-app.ps1", "-Uninstall")

    assert "uv sync" not in output
    assert output.count("Removing") == 3
    assert "memory are untouched" in output


@needs_pwsh
def test_the_browser_launcher_still_works():
    output = dry_run("start-studio.ps1", "-NoBrowser")

    assert (
        "uv sync --python cpython-3.14.0-windows-x86_64-none --extra studio_voice"
        in output
    )
    assert (
        "uv run --python cpython-3.14.0-windows-x86_64-none --extra studio_voice fcc-server"
        in output
    )
