"""FCC Linux in FCC Phone: the files the phone ships are the ones recorded in
vendor/ (v86, xterm.js, FCC Linux), with the checksums js/linux.js checks."""

import hashlib
import json
import re
from pathlib import Path

from free_claude_code.api.studio_routes import PHONE_DIR

ROOT = Path(__file__).resolve().parents[2]


def recorded(name: str) -> dict[str, str]:
    rows = (
        (ROOT / "vendor" / name / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    )
    return {line[66:].split(" ")[0]: line[:64] for line in rows if line.strip()}


def test_the_phone_ships_the_recorded_linux_files_and_checks_them():
    runner = (PHONE_DIR / "js" / "linux.js").read_text(encoding="utf-8")
    shipped = dict(re.findall(r'\["linux/([\w.-]+)", "([0-9a-f]{64})"\]', runner))
    sums = {**recorded("v86"), **recorded("xterm"), **recorded("fcc-linux")}
    assert set(shipped) == {
        "libv86.js",
        "v86.wasm",
        "seabios.bin",
        "vgabios.bin",
        "xterm.js",
        "xterm.css",
        "fcc-linux.kernel",
        "fcc-linux.initrd",
    }
    for name, digest in shipped.items():
        data = (PHONE_DIR / "linux" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest == sums[name], name
    # The box: no network, and only its own scripts.
    assert "connect-src 'none'" in runner and '"allow-scripts"' in runner
    worker = (PHONE_DIR / "sw.js").read_text(encoding="utf-8")
    assert 'const LINUX_CACHE = "fcc-phone-linux-1.0";' in worker


def test_fcc_linux_says_what_is_inside():
    contents = json.loads((PHONE_DIR / "linux" / "fcc-linux.json").read_text("utf-8"))
    assert contents == json.loads(
        (ROOT / "vendor" / "fcc-linux" / "contents.json").read_text("utf-8")
    )
    added = {item["name"] for item in contents["added"]}
    assert {
        "python3",
        "lua5.4",
        "bash",
        "nano",
        "tmux",
        "sqlite",
        "htop",
        "lynx",
    } <= added
    assert "busybox" in contents["base_packages"]
    assert contents["initrd"]["sha256"] == recorded("fcc-linux")["fcc-linux.initrd"]
