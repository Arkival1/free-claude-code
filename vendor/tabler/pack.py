"""Build studio/ui_kit/tabler.zip from Tabler's release files.

Run with the downloaded release files in one folder (untrusted data: this
only reads them):

    python -I vendor/tabler/pack.py <folder>

The folder holds tabler.min.css and tabler.min.js (@tabler/core 1.7.1 dist),
nodes-outline.json and icons.json (@tabler/icons 3.49.0), LICENSE-core and
LICENSE-icons. The zip gets the kit, every icon (outline style) as data, the
app-kit starter from vendor/tabler/app-kit, and both licences.
"""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "src/free_claude_code/studio/ui_kit/tabler.zip"
STARTER_ICONS = (
    "device-gamepad-2",
    "home",
    "trophy",
    "settings",
    "player-play",
    "coin",
    "heart",
    "star",
)
STAMP = (2026, 10, 24, 0, 0, 0)
"""Fixed file times, so the zip (and its checksum) only changes with its content."""


def svg(nodes: list) -> str:
    parts = "".join(
        f"<{tag} " + " ".join(f'{key}="{value}"' for key, value in attrs.items()) + "/>"
        for tag, attrs in nodes
    )
    return parts


def main(source: Path) -> None:
    nodes = json.loads((source / "nodes-outline.json").read_text(encoding="utf-8"))
    meta = json.loads((source / "icons.json").read_text(encoding="utf-8"))
    icons = {
        name: [
            str(meta.get(name, {}).get("category", "")),
            [str(tag) for tag in meta.get(name, {}).get("tags", [])][:12],
            svg(parts),
        ]
        for name, parts in sorted(nodes.items())
    }
    sprite = "".join(
        f'<symbol id="{name}" viewBox="0 0 24 24">{icons[name][2]}</symbol>'
        for name in STARTER_ICONS
    )
    files = {
        "vendor/tabler/tabler.min.css": (source / "tabler.min.css").read_bytes(),
        "vendor/tabler/tabler.min.js": (source / "tabler.min.js").read_bytes(),
        "vendor/tabler/LICENSE": (source / "LICENSE-core").read_bytes(),
        "vendor/tabler-icons/LICENSE": (source / "LICENSE-icons").read_bytes(),
        "icons.json": json.dumps(icons, separators=(",", ":")).encode(),
        "app-kit/assets/icons.svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">'
            f"{sprite}</svg>"
        ).encode(),
    }
    for path in sorted((HERE / "app-kit").glob("*")):
        files[f"app-kit/{path.name}"] = path.read_bytes()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, files[name])
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    (HERE / "SHA256SUMS").write_text(f"{digest}  tabler.zip\n", encoding="utf-8")
    print(OUT, OUT.stat().st_size, digest)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
