"""Build the Godot demos' art, sound and models into studio/godot/art/.

    python -I vendor/godot/pack_art.py <godot-demo-projects checkout>

Reads (never runs) the checkout at the commit recorded in demos.json.gz.
Every file of every GDScript demo that isn't already in demos.json.gz (the
code) goes into parts `demo-art-NN.zip`, each under 23 MB so every release
part stays under 25 MB. A file too big for one part is split into chunks
across parts. `art.json.gz` lists each file's SHA-256 and where its bytes
are; `SHA256SUMS` in this folder holds every part's checksum.
"""

import gzip
import hashlib
import json
import sys
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "src/free_claude_code/studio/godot/art"
TEXT = {".gd", ".tscn", ".tres", ".gdshader", ".cfg", ".md"}
# Dotfiles (.gitignore, .editorconfig, ...) are skipped too.
SKIP_SUFFIXES = {".csproj", ".sln"}  # C# project files; FCC uses GDScript
PART_BYTES = 22 * 1024 * 1024
CHUNK = 16 * 1024 * 1024
STAMP = (2026, 10, 24, 0, 0, 0)


def art_files(root: Path) -> list[tuple[str, str, Path]]:
    found = []
    for project in sorted(root.rglob("project.godot")):
        folder = project.parent
        demo_id = folder.relative_to(root).as_posix()
        if demo_id.startswith(("mono/", ".")) or demo_id == ".":
            continue
        for path in sorted(folder.rglob("*")):
            if (
                not path.is_file()
                or ".godot" in path.parts
                or "screenshots" in path.parts
            ):
                continue
            if (
                path.name == "project.godot"
                or path.suffix in TEXT
                or path.name.startswith(".")
                or path.suffix in SKIP_SUFFIXES
            ):
                continue
            nested = path.parent
            while nested != folder and not (nested / "project.godot").is_file():
                nested = nested.parent
            if nested != folder:
                continue  # belongs to a demo inside this one
            found.append((demo_id, path.relative_to(folder).as_posix(), path))
    return found


def main(root: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("demo-art-*.zip"):
        old.unlink()
    manifest: dict[str, list[dict[str, object]]] = {}
    parts: list[zipfile.ZipFile] = []
    part_size = [0]

    def current() -> tuple[str, zipfile.ZipFile]:
        if not parts:
            parts.append(
                zipfile.ZipFile(OUT / "demo-art-01.zip", "w", zipfile.ZIP_DEFLATED)
            )
        return f"demo-art-{len(parts):02d}.zip", parts[-1]

    def put(member: str, data: bytes) -> str:
        packed = len(zlib.compress(data, 9))
        if parts and part_size[0] + packed > PART_BYTES:
            parts[-1].close()
            parts.append(
                zipfile.ZipFile(
                    OUT / f"demo-art-{len(parts) + 1:02d}.zip",
                    "w",
                    zipfile.ZIP_DEFLATED,
                )
            )
            part_size[0] = 0
        name, bundle = current()
        info = zipfile.ZipInfo(member, STAMP)
        info.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(info, data, compresslevel=9)
        part_size[0] += packed
        return name

    for demo_id, relative, path in art_files(root):
        data = path.read_bytes()
        member = f"{demo_id}/{relative}"
        pieces = [data[i : i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
        where = [
            {
                "zip": put(f"{member}.{index}" if len(pieces) > 1 else member, piece),
                "member": f"{member}.{index}" if len(pieces) > 1 else member,
            }
            for index, piece in enumerate(pieces)
        ]
        manifest.setdefault(demo_id, []).append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "at": where,
            }
        )
    if parts:
        parts[-1].close()
    data = gzip.compress(json.dumps(manifest, separators=(",", ":")).encode(), mtime=0)
    (OUT / "art.json.gz").write_bytes(data)
    sums = HERE / "SHA256SUMS"
    keep = [
        line
        for line in (sums.read_text().splitlines() if sums.is_file() else [])
        if not (line.endswith("art.json.gz") or "demo-art-" in line)
    ]
    keep.append(f"{hashlib.sha256(data).hexdigest()}  art.json.gz")
    keep.extend(
        f"{hashlib.sha256(part.read_bytes()).hexdigest()}  {part.name}"
        for part in sorted(OUT.glob("demo-art-*.zip"))
    )
    sums.write_text("\n".join(keep) + "\n", encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT.glob("demo-art-*.zip"))
    print(
        sum(len(v) for v in manifest.values()),
        "files in",
        len(list(OUT.glob("demo-art-*.zip"))),
        "parts,",
        total // 1_000_000,
        "MB",
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
