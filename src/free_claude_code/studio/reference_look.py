"""Photos and videos the owner sends, turned into a build brief.

The Vision Model (Settings, Studio) looks at a reference (a photo, or a
video as a 3x3 sheet of frames taken evenly through it) and writes what an
agent needs to build it: for a game the genre, camera, controls, characters,
moves and animations seen across the frames, level layout, HUD, physics feel
and palette; for a site or an app the sections, layout, colours, type and
parts. The agent then writes the code (Godot, HTML, an app).

ffmpeg makes the pictures small enough to send and takes the frames: from
the FCC_FFMPEG setting, imageio-ffmpeg (the studio_video extra), or PATH.
"""

import asyncio
import contextlib
import os
import re
import shutil
from pathlib import Path
from typing import Literal

Make = Literal["game", "website", "app"]
MAKES: tuple[Make, ...] = ("game", "website", "app")
MAKE_BY_NAME: dict[str, Make] = {name: name for name in MAKES}
GRID = 3
"""Frames per side of a video's sheet (3x3 = 9 frames, in time order)."""
MAX_SIDE = 1280
FRAME_WIDTH = 480
FFMPEG_SECONDS = 90.0
MAX_RAW_PHOTO_BYTES = 3_500_000
"""Without ffmpeg a photo goes as it is, up to this size."""
MAX_FOCUS = 600
INSTALL_HINT = (
    "Reading videos needs ffmpeg: run FCC's Windows installer again (it adds "
    "the studio_video extra), or put ffmpeg on PATH, or set FCC_FFMPEG."
)


class ReferenceLookError(ValueError):
    """A reference that can't be read; the message says why."""


def find_ffmpeg() -> str | None:
    chosen = os.environ.get("FCC_FFMPEG", "").strip()
    if chosen and Path(chosen).is_file():
        return chosen
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except ImportError, RuntimeError, OSError:
        pass
    return shutil.which("ffmpeg")


async def _ffmpeg(ffmpeg: str, args: list[str], data: bytes = b"") -> bytes:
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        *args,
        stdin=asyncio.subprocess.PIPE if data else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            process.communicate(data or None), FFMPEG_SECONDS
        )
    except TimeoutError:
        raise ReferenceLookError(
            f"ffmpeg took over {FFMPEG_SECONDS:.0f} seconds; try a shorter video."
        ) from None
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    if process.returncode != 0 or not out:
        detail = err.decode("utf-8", "replace").strip().splitlines()
        raise ReferenceLookError(
            "ffmpeg couldn't read it" + (f": {detail[-1][:200]}" if detail else ".")
        )
    return out


def _jpeg_out() -> list[str]:
    return [
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-q:v",
        "4",
        "pipe:1",
    ]


async def photo_picture(
    data: bytes, content_type: str, ffmpeg: str | None
) -> tuple[str, bytes]:
    """The photo as (content type, bytes) small enough for the Vision Model."""
    if ffmpeg:
        scale = f"scale='min({MAX_SIDE},iw)':-2"
        return "image/jpeg", await _ffmpeg(
            ffmpeg, ["-i", "pipe:0", "-vf", scale, *_jpeg_out()], data
        )
    if len(data) > MAX_RAW_PHOTO_BYTES:
        raise ReferenceLookError(
            "The photo is too big to send as it is. "
            + INSTALL_HINT.replace("Reading videos", "Shrinking it")
        )
    return content_type or "image/jpeg", data


def duration_of(text: str) -> float:
    """Seconds from ffmpeg's 'Duration: 00:01:02.50' line, or 0."""
    found = re.search(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)", text)
    if not found:
        return 0.0
    hours, minutes, seconds = found.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


async def _duration(ffmpeg: str, video: Path) -> float:
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-hide_banner",
        "-i",
        str(video),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(process.communicate(), FFMPEG_SECONDS)
    except TimeoutError:
        raise ReferenceLookError(
            f"ffmpeg took over {FFMPEG_SECONDS:.0f} seconds to open the video."
        ) from None
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    return duration_of(err.decode("utf-8", "replace"))


async def video_sheet(video: Path, ffmpeg: str | None) -> tuple[bytes, float]:
    """A 3x3 sheet of frames taken evenly through the video (left to right,
    top to bottom), as JPEG, and the video's length in seconds."""
    if not ffmpeg:
        raise ReferenceLookError(INSTALL_HINT)
    seconds = await _duration(ffmpeg, video)
    count = GRID * GRID
    # Frames from the middle of each ninth, so the first isn't a black fade-in.
    rate = count / seconds if seconds > 0 else 1.0
    start = (seconds / count / 2) if seconds > 0 else 0.0
    sheet = await _ffmpeg(
        ffmpeg,
        [
            "-ss",
            f"{start:.3f}",
            "-i",
            str(video),
            "-vf",
            f"fps={rate:.6f},scale={FRAME_WIDTH}:-2,tile={GRID}x{GRID}",
            *_jpeg_out(),
        ],
    )
    return sheet, seconds


_COMMON = (
    "You look at a reference the owner sent for a developer who can't see "
    "it, so they can build something like it. Only report what you can see; "
    "say 'not visible' rather than guess. Give exact-looking colours as hex "
    "codes. If it shows another company's characters, logos, names or "
    "artwork, say so in a line starting 'BELONGS TO SOMEONE ELSE:' and "
    "describe original replacements with the same feel (unless the owner's "
    "notes say the art is theirs: then it can be used as it is). End with "
    "MAKE IT OURS: 4 to 6 concrete changes that keep everything the owner "
    "likes (the feel, the mechanics, the layout) but make the result an "
    "original and not a copy: a new name and words, redrawn characters and "
    "logo, colours shifted, a few parts moved or added. For the owner's own "
    "work (their notes say it's theirs, or it is FCC itself), say 'none "
    "needed'."
)
PROMPTS: dict[Make, str] = {
    "game": _COMMON
    + " It is a game. Write, under these headings: GENRE (a few plain words, "
    "e.g. '2d platformer', 'top-down rpg', 'third-person 3d', 'racing'); "
    "VIEW AND CAMERA (2D side, top-down, isometric, 3D third/first person; "
    "how the camera follows); PLAYER (shape, size on screen, colours, "
    "outfit, what it holds); MOVES AND ANIMATIONS (each move or pose you can "
    "see, e.g. idle, run, jump, attack, and how the frames change over time); "
    "ENEMIES AND OBJECTS (each, with what it seems to do); WORLD AND LEVEL "
    "(ground, platforms, walls, background layers; for 2D, sketch the level "
    "as a small text map with # for solid, = for platforms, C coins, E "
    "enemies, P player); HUD (score, health, timers, where on screen); "
    "PHYSICS FEEL (speed, jump height in player heights, gravity, slippery or "
    "tight); ART STYLE (pixel art and its rough pixel size, hand drawn, low "
    "poly, realistic; outlines; lighting); PALETTE (hex); EFFECTS (particles, "
    "shake, flashes); SOUND IT SUGGESTS; HOW TO BUILD IT IN GODOT 4 (the "
    "scenes and nodes, e.g. CharacterBody2D, TileMapLayer, AnimatedSprite2D, "
    "Camera2D, and the order to build them).",
    "website": _COMMON
    + " It is a website or a web page. Write, under these headings: WHAT IT IS; "
    "SECTIONS (top to bottom, each with its layout: columns, image side, "
    "cards, and its words if readable); NAVIGATION; COLOURS (hex: background, "
    "text, accent, buttons); TYPE (serif or sans, weights, rough sizes, "
    "letter spacing); SPACING AND SHAPES (rounded corners, shadows, borders, "
    "how airy); IMAGES AND ICONS (what they show, style); MOTION OR STATES "
    "you can infer; PHONE LAYOUT (how it should stack); HOW TO BUILD IT "
    "(HTML structure and the CSS grid/flex for each section).",
    "app": _COMMON + " It is an app screen. Write, under these headings: WHAT IT DOES; "
    "SCREENS AND PARTS (top to bottom: bars, lists, cards, forms, buttons, "
    "tabs, each with its words if readable); NAVIGATION (tabs, back, menus); "
    "COLOURS (hex); TYPE; SPACING AND SHAPES; ICONS; STATES (empty, loading, "
    "selected) you can see or infer; DATA it shows and where it might come "
    "from; HOW TO BUILD IT (the components, their layout, and the order).",
}
VIDEO_NOTE = (
    " This picture is a sheet of {count} frames taken evenly through a "
    "{seconds:.0f}-second video, in time order left to right, top to bottom: "
    "compare them to tell how things move and animate."
)


def brief_prompt(
    make: Make, *, title: str, notes: str, focus: str, video_seconds: float = 0.0
) -> tuple[str, str]:
    """(system prompt, user prompt) for one reference."""
    system = PROMPTS[make]
    if video_seconds:
        system += VIDEO_NOTE.format(count=GRID * GRID, seconds=video_seconds)
    lines = [f"Reference: {title or 'untitled'}"]
    if notes.strip():
        lines.append(f"The owner says about it: {notes.strip()[:1500]}")
    if focus.strip():
        lines.append(f"Look most at: {focus.strip()[:MAX_FOCUS]}")
    return system, "\n".join(lines)


def genre_of(brief: str) -> str:
    """The GENRE line's words, to find matching Godot demos."""
    found = re.search(r"GENRE\W*[:\-]?\s*(.+)", brief, re.IGNORECASE)
    if not found:
        return ""
    words = re.findall(r"[a-z0-9]+", found.group(1).casefold())
    return " ".join(words[:3])


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:50] or "reference"
