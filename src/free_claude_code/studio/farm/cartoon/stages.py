"""Painted places for the cartoon, and the wood board it sits on.

Each place is drawn flat, like a cartoon background: a hut with light
coming through the windows, a savanna with flat-topped trees, a sandy
village, a palace hall, a forest, a city, a night sky, and more. A place
can also be any picture from the media library. Shorts show the cartoon in
a 16:9 panel on a textured board (wood, by default) with the series title
in a white box above it.
"""

import functools
import math
import random
from pathlib import Path
from typing import Any

from .places import paint_place

PLACES = (
    "hut",
    "room",
    "savanna",
    "desert",
    "village",
    "palace",
    "forest",
    "city",
    "street",
    "night",
    "classroom",
    "beach",
    "battlefield",
    "snow",
    "space",
    "sky",
)
TEXTURES = ("wood", "paper", "dark", "brick", "none")
GROUND = 0.9
"""Where feet stand, as a share of the stage's height."""


def _gradient(
    size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Any:
    from PIL import Image

    strip = Image.new("RGB", (1, 256))
    for y in range(256):
        mix = y / 255
        strip.putpixel(
            (0, y),
            tuple(round(a + (b - a) * mix) for a, b in zip(top, bottom, strict=True)),
        )
    return strip.resize(size)


def place_key(place: str) -> str:
    text = (place or "").strip().lower()
    aliases = {
        "house": "hut",
        "home": "hut",
        "inside": "room",
        "office": "room",
        "bedroom": "room",
        "desert": "desert",
        "plains": "savanna",
        "field": "savanna",
        "market": "village",
        "town": "village",
        "castle": "palace",
        "throne": "palace",
        "court": "palace",
        "woods": "forest",
        "jungle": "forest",
        "school": "classroom",
        "road": "street",
        "war": "battlefield",
        "battle": "battlefield",
        "ocean": "beach",
        "sea": "beach",
        "moon": "space",
        "stars": "night",
    }
    for word in text.replace("_", " ").split():
        if word in PLACES:
            return word
        if word in aliases:
            return aliases[word]
    return "hut"


@functools.lru_cache(maxsize=12)
def stage(place: str, width: int, height: int, seed: int = 0) -> Any:
    """A place, painted at this size (RGB). Cached: copied every frame."""
    return paint_place(place_key(place), width, height, seed)


def picture_stage(path: str, width: int, height: int) -> Any:
    """A library picture as the place (kept, until the file changes)."""
    return _fitted_picture(path, Path(path).stat().st_mtime_ns, width, height)


@functools.lru_cache(maxsize=6)
def _fitted_picture(path: str, _changed: int, width: int, height: int) -> Any:
    from PIL import Image, ImageOps

    with Image.open(path) as opened:
        return ImageOps.fit(
            ImageOps.exif_transpose(opened).convert("RGB"),
            (width, height),
            Image.Resampling.LANCZOS,
        )


def stage_for(
    place: str, width: int, height: int, *, picture: Path | None = None, seed: int = 0
) -> Any:
    if picture is not None and picture.is_file():
        try:
            return picture_stage(str(picture), width, height)
        except OSError:
            pass
    return stage(place, width, height, seed)


@functools.lru_cache(maxsize=8)
def board(texture: str, width: int, height: int) -> Any:
    """The textured board a panel sits on: planks of wood, by default."""
    from PIL import Image, ImageDraw, ImageFilter

    if texture == "none":
        return Image.new("RGB", (width, height), (0, 0, 0))
    if texture == "dark":
        return _gradient((width, height), (20, 22, 30), (5, 6, 10))
    if texture == "paper":
        base = _gradient((width, height), (245, 238, 220), (230, 220, 195))
        draw = ImageDraw.Draw(base, "RGBA")
        rng = random.Random(7)
        for _ in range(2_000):
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            draw.point((x, y), fill=(120, 100, 70, rng.randint(10, 40)))
        return base
    if texture == "brick":
        base = Image.new("RGB", (width, height), (150, 70, 50))
        draw = ImageDraw.Draw(base)
        row = height // 24
        for y in range(0, height, row):
            offset = (y // row) % 2 * row
            for x in range(-offset, width, row * 2):
                draw.rectangle(
                    (x + 2, y + 2, x + row * 2 - 2, y + row - 2),
                    fill=(165 + (x * 7 + y) % 25, 75, 55),
                )
        return base
    # Wood: planks of warm brown, with wavy grain.
    scale = 4
    small = Image.new("RGB", (width // scale, height // scale))
    pixels = small.load()
    assert pixels is not None
    rng = random.Random(11)
    plank = max(8, small.height // 11)
    tones = [rng.uniform(0.85, 1.12) for _ in range(small.height // plank + 2)]
    knots = [
        (rng.uniform(0, small.width), rng.uniform(0, small.height), rng.uniform(4, 9))
        for _ in range(10)
    ]
    for y in range(small.height):
        board_no = y // plank
        tone = tones[board_no]
        for x in range(small.width):
            wave = math.sin(x * 0.045 + board_no * 1.7) * 2.2
            warp = sum(
                (r * 2.5) / (1 + ((x - kx) ** 2 + (y - ky) ** 2) / (r * r * 3))
                for kx, ky, r in knots
            )
            grain = (
                math.sin(
                    (y + wave + warp) * 0.42 + math.sin(x * 0.011 + board_no) * 2.5
                )
                * 0.5
                + 0.5
            )
            fine = math.sin((y + wave * 0.5) * 2.3 + x * 0.002) * 0.5 + 0.5
            value = (0.74 + 0.18 * grain + 0.08 * fine) * tone
            edge = 0.6 if y % plank in (0, 1) else 1.0
            pixels[x, y] = (
                int(min(255, 138 * value * edge)),
                int(min(255, 88 * value * edge)),
                int(min(255, 42 * value * edge)),
            )
    return small.resize((width, height), Image.Resampling.BICUBIC).filter(
        ImageFilter.SMOOTH_MORE
    )


def panel_box(width: int, height: int) -> tuple[int, int, int, int]:
    """Where the 16:9 cartoon sits on a 9:16 frame: a little above the middle."""
    panel_h = round(width * 9 / 16)
    top = round(height * 0.37)
    return 0, top, width, top + panel_h


@functools.lru_cache(maxsize=8)
def title_box(title: str, width: int) -> Any:
    """The series title in a white rounded box (RGBA)."""
    from PIL import Image, ImageDraw

    from ..render import _SANS, _font

    font = _font(_SANS, max(14, width // 26))
    text_w = font.getlength(title)
    ascent, descent = font.getmetrics()
    pad_x, pad_y = width * 0.03, (ascent + descent) * 0.35
    box = (int(text_w + pad_x * 2), int(ascent + descent + pad_y * 2))
    layer = Image.new("RGBA", box, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle(
        (0, 0, box[0] - 1, box[1] - 1),
        radius=int(pad_y * 1.4),
        fill=(255, 255, 255, 250),
        outline=(210, 210, 210),
        width=2,
    )
    draw.text((pad_x, pad_y - descent * 0.2), title, font=font, fill=(20, 20, 20))
    return layer
