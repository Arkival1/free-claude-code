"""FCC Phone's Godot: the web player it ships is the one recorded in
vendor/godot-web (byte for byte, with the checksums the phone checks before
running it), the phone's starters and probe are generated from studio/godot,
and the probe runs in real Godot."""

import gzip
import hashlib
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from free_claude_code.api.studio_routes import PHONE_DIR

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "godot-web"
GODOT = PHONE_DIR / "godot"
REAL_GODOT = os.environ.get("FCC_GODOT_BIN", "")


def sums() -> dict[str, str]:
    rows = (VENDOR / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    return {line[66:]: line[:64] for line in rows if line.strip()}


def test_the_phone_ships_the_recorded_web_player_and_checks_it():
    recorded = sums()
    runner = (PHONE_DIR / "js" / "godot.js").read_text(encoding="utf-8")
    shipped = dict(re.findall(r'\["godot/([\w.]+)", "([0-9a-f]{64})"\]', runner))
    assert set(shipped) == {
        "godot.js",
        "godot.wasm.gz",
        "godot.audio.worklet.js",
        "godot.audio.position.worklet.js",
    }
    for name, digest in shipped.items():
        data = (GODOT / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest == recorded[name], name
    packed = (GODOT / "godot.wasm.gz").read_bytes()
    assert f"ENGINE_BYTES = {len(packed):_}" in runner
    engine = gzip.decompress(packed)
    assert engine[:4] == b"\0asm"
    assert (
        hashlib.sha256(engine).hexdigest()
        == recorded["godot.wasm (unpacked from godot.wasm.gz)"]
    )
    licence = (GODOT / "LICENSE.txt").read_text(encoding="utf-8")
    assert licence == (VENDOR / "LICENSE").read_text(encoding="utf-8")
    assert "Godot Engine contributors" in licence


def test_the_box_has_no_network_and_the_service_worker_keeps_the_engine():
    runner = (PHONE_DIR / "js" / "godot.js").read_text(encoding="utf-8")
    assert '"allow-scripts allow-pointer-lock"' in runner
    for rule in ("default-src 'none'", "connect-src 'none'", "worker-src 'none'"):
        assert rule in runner
    worker = (PHONE_DIR / "sw.js").read_text(encoding="utf-8")
    assert 'const GODOT_CACHE = "fcc-phone-godot-4.7.2";' in worker
    assert 'const GODOT_CACHE = "fcc-phone-godot-4.7.2";' in runner


def test_the_phone_starters_and_probe_come_from_studio_godot():
    """Run scripts/phone/build_pages.py after changing studio/godot."""
    spec = importlib.util.spec_from_file_location(
        "build_pages", ROOT / "scripts" / "phone" / "build_pages.py"
    )
    assert spec is not None and spec.loader is not None
    build_pages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_pages)
    text = (GODOT / "starters.js").read_text(encoding="utf-8")
    assert text == build_pages.godot_js()
    found = re.search(r"export const GODOT_STARTERS = (\{.*\});\n", text)
    assert found is not None
    starters = json.loads(found.group(1))
    assert set(starters) == {
        "action-3d",
        "third-person-3d",
        "platformer-2d",
        "rpg-topdown",
    }
    for starter in starters.values():
        files = starter["files"]
        # Every phone starter plays by touch on a phone.
        assert "touch.gd" in files or "touch_pad.gd" in files
        assert "emulate_mouse_from_touch=false" in files["project.godot"]
        assert 'run/main_scene="res://main.tscn"' in files["project.godot"]
        # Pictures go in as data addresses; the phone imports them.
        assert all(
            files[name].startswith("data:image/png;base64,")
            for name in files
            if name.endswith(".png")
        )
        assert not any(name.endswith(".import") for name in files)


@pytest.mark.skipif(not REAL_GODOT, reason="set FCC_GODOT_BIN to a Godot 4.7.2 program")
def test_the_probe_runs_in_real_godot(tmp_path):
    project = tmp_path / "probe"
    project.mkdir()
    for path in (
        ROOT / "src" / "free_claude_code" / "studio" / "godot" / "probe"
    ).iterdir():
        (project / path.name).write_bytes(path.read_bytes())
    played = subprocess.run(
        [REAL_GODOT, "--headless", "--path", str(project), "--quit-after", "900"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = played.stdout + played.stderr
    assert "SCRIPT ERROR" not in output, output[-3000:]
    line = next(row for row in output.splitlines() if row.startswith("FCC_PROBE "))
    report = json.loads(line[len("FCC_PROBE ") :])
    names = {item["name"]: item for item in report["items"]}
    assert report["version"].startswith("4.7.2")
    for name in ("Godot", "3D physics", "JSON", "PNG pictures", "Saving (user://)"):
        assert names[name]["status"] == "works", names[name]
    assert {item["status"] for item in report["items"]} <= {
        "works",
        "limited",
        "missing",
        "blocked",
    }
