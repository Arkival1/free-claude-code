"""Build studio/godot/demos.json.gz from Godot's official demo projects.

    python -I vendor/godot/pack_demos.py <godot-demo-projects checkout>

Reads (never runs) the checkout. Keeps each demo's GDScript, scenes,
resources, shaders, project file and README; lists its other files (art,
sound, models) by name. The C# copies (mono/) are left out: FCC's agents
write GDScript.
"""

import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "src/free_claude_code/studio/godot/demos.json.gz"
TEXT = {".gd", ".tscn", ".tres", ".gdshader", ".cfg", ".md"}
MAX_FILE = 120_000


def main(root: Path) -> None:
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    demos = []
    for project in sorted(root.rglob("project.godot")):
        folder = project.parent
        demo_id = folder.relative_to(root).as_posix()
        if demo_id.startswith(("mono/", ".")) or demo_id == ".":
            continue
        readme = folder / "README.md"
        lines = (
            readme.read_text(encoding="utf-8").splitlines() if readme.is_file() else []
        )
        title = lines[0].lstrip("#> ").strip() if lines else demo_id
        about = " ".join(
            line.strip()
            for line in lines[1:8]
            if line.strip()
            and not line.startswith(("#", "!", ">", "Language", "Renderer"))
        )[:400]
        files: dict[str, str] = {}
        assets: list[str] = []
        for path in sorted(folder.rglob("*")):
            if (
                not path.is_file()
                or ".godot" in path.parts
                or "screenshots" in path.parts
            ):
                continue
            relative = path.relative_to(folder).as_posix()
            if path.name == "project.godot" or path.suffix in TEXT:
                text = path.read_text(encoding="utf-8", errors="replace")
                files[relative] = text[:MAX_FILE]
            elif path.suffix != ".import":
                assets.append(relative)
        demos.append(
            {
                "id": demo_id,
                "title": title,
                "about": about,
                "area": demo_id.split("/")[0],
                "files": files,
                "assets": assets[:400],
            }
        )
    payload = {"commit": commit, "demos": demos}
    data = gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0)
    OUT.write_bytes(data)
    sums = HERE / "SHA256SUMS"
    lines = [
        line
        for line in (sums.read_text().splitlines() if sums.is_file() else [])
        if not line.endswith("demos.json.gz")
    ]
    lines.append(f"{hashlib.sha256(data).hexdigest()}  demos.json.gz")
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(len(demos), OUT.stat().st_size, commit)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
