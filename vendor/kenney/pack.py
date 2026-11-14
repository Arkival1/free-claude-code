"""Build FCC's Kenney catalogue and core zip from the downloaded packs.

    python3 -I pack.py <folder of pack zips> <sizes.tsv> <out folder>

sizes.tsv rows: id, category, size, download address (from kenney.nl). For
every pack the catalogue records its name, category, address, SHA-256 and
the files a game uses (PNG sprites at their normal size, tile sheets,
sounds, fonts, glTF models), leaving out vector copies, double-size copies
and other engines' project files. Packs in CORE also go into kenney-core.zip,
their .ogg sounds as .mp3 (ffmpeg) so they play on iPhones too. The zips are
read as data; nothing in them is run.
"""

import gzip
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

CORE = (
    # platformers
    "pixel-platformer",
    "new-platformer-pack",
    "platformer-characters",
    "toon-characters",
    "abstract-platformer",
    "background-elements-remastered",
    "jumper-pack",
    # top-down, RPG and dungeon
    "tiny-dungeon",
    "tiny-town",
    "tiny-farm",
    "micro-roguelike",
    "roguelike-characters",
    "1-bit-pack",
    "top-down-shooter",
    "top-down-tanks-remastered",
    "tower-defense-top-down",
    "sokoban",
    "rpg-urban-pack",
    # space and arcade
    "space-shooter-remastered",
    "space-shooter-extension",
    "simple-space",
    "pixel-shmup",
    "tappy-plane",
    "shooting-gallery",
    "racing-pack",
    # puzzle, cards and board
    "puzzle-pack-1",
    "playing-cards-pack",
    "board-game-icons",
    "boardgame-pack",
    "physics-assets",
    # UI, icons, effects, input
    "ui-pack",
    "pixel-ui-pack",
    "ui-pack-adventure",
    "game-icons",
    "emotes-pack",
    "mobile-controls",
    "input-prompts-pixel",
    "particle-pack",
    "smoke-particles",
    "kenney-fonts",
    # sound
    "interface-sounds",
    "impact-sounds",
    "music-jingles",
    "rpg-audio",
    "sci-fi-sounds",
    "digital-audio",
    "casino-audio",
    "ui-audio",
    "voiceover-pack",
)
SKIP = re.compile(
    r"(^|/)(vector|vectors|svg|unity|unity samples|construct( 3)?|godot|gamemaker|game maker|"
    r"source|sources|backup|spine|double|double size|retina|large|@2x|x2|"
    r"png \(black background\)|black background|spritesheet|spritesheets|tiles \(double\))(/|$)",
    re.IGNORECASE,
)
KEEP = {".png", ".ogg", ".wav", ".mp3", ".ttf", ".otf", ".glb", ".gltf"}
PARTICLE_SIDE = 128


def usable(name: str) -> bool:
    path = name.replace("\\", "/")
    if path.endswith("/") or SKIP.search(path.rsplit("/", 1)[0] if "/" in path else ""):
        return False
    lowered = Path(path).name.casefold()
    if (
        lowered.startswith(("preview", "sample", "._"))
        or "/__macosx" in path.casefold()
    ):
        return False
    if lowered.startswith("license") and lowered.endswith(".txt"):
        return True
    if lowered.startswith("tilesheet") and lowered.endswith(".txt"):
        return True
    return Path(lowered).suffix in KEEP


def ffmpeg(data: bytes, suffix: str, out_suffix: str, args: list[str]) -> bytes:
    with tempfile.TemporaryDirectory() as work:
        source, target = Path(work) / f"in{suffix}", Path(work) / f"out{out_suffix}"
        source.write_bytes(data)
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                *args,
                str(target),
            ],
            check=True,
        )
        return target.read_bytes()


def name_of(pack_id: str) -> str:
    return (
        " ".join(
            part.capitalize() if not part.isdigit() else part
            for part in pack_id.split("-")
        )
        .replace("Ui ", "UI ")
        .replace("Rpg", "RPG")
    )


def main() -> None:
    zips, sizes, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    rows = []
    total_files = 0
    with zipfile.ZipFile(
        out / "kenney-core.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as core:
        for line in sizes.read_text().splitlines():
            pack_id, category, _size, url = line.split("\t")
            archive = zips / f"{pack_id}.zip"
            if url == "-" or not archive.is_file():
                continue
            data = archive.read_bytes()
            shipped = pack_id in CORE
            files: list[str] = []
            with zipfile.ZipFile(archive) as bundle:
                for info in bundle.infolist():
                    name = info.filename.replace("\\", "/")
                    if info.is_dir() or not usable(name):
                        continue
                    if not shipped:
                        files.append(name)
                        continue
                    body = bundle.read(info)
                    suffix = Path(name).suffix.lower()
                    if suffix in {".ogg", ".wav"}:
                        body = ffmpeg(body, suffix, ".mp3", ["-ac", "1", "-b:a", "80k"])
                        name = name[: -len(suffix)] + ".mp3"
                    elif (
                        pack_id in {"particle-pack", "smoke-particles"}
                        and suffix == ".png"
                    ):
                        body = ffmpeg(
                            body, suffix, ".png", ["-vf", f"scale={PARTICLE_SIDE}:-1"]
                        )
                    files.append(name)
                    core.writestr(
                        zipfile.ZipInfo(f"{pack_id}/{name}", (2024, 1, 1, 0, 0, 0)),
                        body,
                        zipfile.ZIP_DEFLATED,
                    )
            total_files += len(files)
            rows.append(
                {
                    "id": pack_id,
                    "name": name_of(pack_id),
                    "category": category,
                    "url": url,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                    "shipped": shipped,
                    "files": sorted(files),
                }
            )
    blob = gzip.compress(
        json.dumps(rows, separators=(",", ":")).encode(), mtime=0, compresslevel=9
    )
    (out / "kenney-catalogue.json.gz").write_bytes(blob)
    shipped = [row for row in rows if row["shipped"]]
    print(
        len(rows),
        "packs;",
        len(shipped),
        "shipped;",
        total_files,
        "files;",
        (out / "kenney-core.zip").stat().st_size,
        "bytes core",
    )
    missing = sorted(set(CORE) - {row["id"] for row in shipped})
    if missing:
        print("core packs not found:", missing)


if __name__ == "__main__":
    main()
