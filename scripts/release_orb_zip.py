"""Build the Orb edition's download: FCC-Orb-<version>.zip.

    python scripts/release_orb_zip.py OUT_DIR

The Orb is Jarvis alone on the owner's PC with two advisers (see
``studio/orb.py``). It ships FCC's code and Studio's own files, marked as the
Orb edition (``config/EDITION``), and leaves out what the Orb never uses:
the phone app and FCC Linux, the starter repos, the Godot demo art, the
website layouts, the image engine source, tests and the GitHub Pages site.
It unpacks into the same ``fcc/`` folder as the full download.
"""

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = "src/free_claude_code/config/EDITION"
LEFT_OUT = (
    "tests/",
    "e2e/",
    "smoke/",
    "docs/",
    ".claude/",
    ".github/",
    "plans/",
    "src/free_claude_code/api/phone_static/",
    "src/free_claude_code/studio/godot/art/",
    "src/free_claude_code/studio/site_layouts/layouts.zip",
    # Libraries for tools the Orb doesn't have, and the README's pictures.
    "src/free_claude_code/studio/ui_library/uiverse.json.gz",
    "src/free_claude_code/studio/bug_library/bugs.json.gz",
    "src/free_claude_code/studio/ui_kit/tabler.zip",
    "src/free_claude_code/studio/godot/demos.json.gz",
    "src/free_claude_code/studio/game_library/phaser-examples.json.gz",
    # Owner: no bundled game data, Godot starters or Godot kit in the Orb.
    "src/free_claude_code/studio/godot/kit/",
    "src/free_claude_code/studio/godot/starters/",
    "src/free_claude_code/studio/game_library/kenney-",
    "assets/",
    "vendor/repos/",
    "vendor/cua/",
    "vendor/stable-diffusion-cpp/",
    "vendor/fcc-linux/",
    "vendor/v86/",
    "vendor/web-llm/",
    "vendor/godot-web/",
    "vendor/xterm/",
    "vendor/pocketpal-ai/",
)
VENDOR_KEEP_BYTES = 512 * 1024
"""Licences and notes stay; vendor's big source copies don't."""


def kept(path: str) -> bool:
    if path.startswith(LEFT_OUT) or path == MARK:
        return False
    if path.startswith("vendor/"):
        file = ROOT / path
        return file.is_file() and file.stat().st_size <= VENDOR_KEEP_BYTES
    return True


def build(out: Path) -> Path:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout.decode()
    files = sorted(path for path in listed.split("\0") if path and kept(path))
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"FCC-Orb-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zip_:
        for path in files:
            source = ROOT / path
            if source.is_file():
                zip_.write(source, f"fcc/{path}")
        zip_.writestr(f"fcc/{MARK}", "orb\n")
    return target


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/release_orb_zip.py OUT_DIR")
    target = build(Path(sys.argv[1]))
    print(f"{target} {target.stat().st_size / 1_048_576:.1f} MB")


if __name__ == "__main__":
    main()
