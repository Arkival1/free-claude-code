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

from .heads import shade

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


@functools.lru_cache(maxsize=48)
def stage(place: str, width: int, height: int, seed: int = 0) -> Any:
    """A place, drawn at this size (RGB). Cached: it is copied every frame."""
    from PIL import Image, ImageDraw, ImageFilter

    key = place_key(place)
    rng = random.Random(f"{key}{seed}")
    size = (width, height)
    if key in {"hut", "room", "classroom", "palace"}:
        walls = {
            "hut": (110, 88, 66),
            "room": (150, 130, 110),
            "classroom": (196, 210, 186),
            "palace": (120, 60, 70),
        }[key]
        canvas = _gradient(size, shade(walls, 1.05), shade(walls, 0.85))
        draw = ImageDraw.Draw(canvas, "RGBA")
        floor = shade(walls, 0.7) if key != "palace" else (150, 30, 40)
        draw.rectangle((0, int(height * 0.68), width, height), fill=floor)
        draw.line(
            (0, int(height * 0.68), width, int(height * 0.68)),
            fill=shade(walls, 0.55),
            width=max(2, height // 180),
        )
        for n in range(2 if key != "palace" else 0):
            x = int(width * (0.18 + n * 0.5))
            box = (x, int(height * 0.08), x + int(width * 0.11), int(height * 0.3))
            draw.rounded_rectangle(
                box,
                radius=height // 30,
                fill=(240, 220, 170),
                outline=shade(walls, 0.5),
                width=height // 90,
            )
            draw.rounded_rectangle(
                (box[0] + 8, box[1] + 8, box[2] - 8, box[3] - 8),
                radius=height // 40,
                fill=(150, 205, 235),
            )
            # A beam of light falling from the window.
            draw.polygon(
                [
                    (box[0], box[3]),
                    (box[2], box[3]),
                    (box[2] + width * 0.08, height * 0.7),
                    (box[0] + width * 0.02, height * 0.7),
                ],
                fill=(255, 245, 210, 40),
            )
        if key == "hut":
            # A mud bed with straw on it, against the back wall.
            mud = shade(walls, 0.8)
            draw.rounded_rectangle(
                (
                    int(width * 0.32),
                    int(height * 0.5),
                    int(width * 0.92),
                    int(height * 0.7),
                ),
                radius=height // 24,
                fill=mud,
                outline=shade(walls, 0.55),
                width=max(2, height // 240),
            )
            for _ in range(240):
                x = rng.uniform(width * 0.32, width * 0.86)
                y = rng.uniform(height * 0.45, height * 0.53)
                angle = rng.uniform(-0.5, 0.5)
                length = rng.uniform(width * 0.03, width * 0.08)
                draw.line(
                    (x, y, x + math.cos(angle) * length, y + math.sin(angle) * length),
                    fill=(70, 52, 38, 200),
                    width=2,
                )
        if key == "classroom":
            draw.rectangle(
                (
                    int(width * 0.32),
                    int(height * 0.12),
                    int(width * 0.68),
                    int(height * 0.42),
                ),
                fill=(40, 70, 55),
                outline=(120, 90, 60),
                width=height // 70,
            )
        if key == "palace":
            for n in range(4):
                x = int(width * (0.08 + n * 0.28))
                draw.rectangle(
                    (x, 0, x + width // 22, int(height * 0.7)),
                    fill=(225, 205, 160),
                    outline=(170, 150, 110),
                    width=3,
                )
            draw.rectangle(
                (
                    int(width * 0.42),
                    int(height * 0.3),
                    int(width * 0.58),
                    int(height * 0.7),
                ),
                fill=(220, 175, 50),
                outline=(150, 110, 20),
                width=4,
            )
            draw.rectangle(
                (int(width * 0.38), int(height * 0.68), int(width * 0.62), height),
                fill=(170, 20, 35),
            )
        return canvas
    if key in {"savanna", "desert", "beach", "snow", "battlefield"}:
        skies = {
            "savanna": ((255, 236, 170), (255, 196, 90)),
            "desert": ((255, 240, 200), (250, 210, 140)),
            "beach": ((150, 210, 250), (220, 240, 255)),
            "snow": ((190, 210, 230), (235, 240, 248)),
            "battlefield": ((150, 120, 110), (210, 170, 130)),
        }[key]
        canvas = _gradient(size, *skies)
        draw = ImageDraw.Draw(canvas, "RGBA")
        land = {
            "savanna": (238, 190, 80),
            "desert": (236, 196, 120),
            "beach": (240, 220, 170),
            "snow": (250, 252, 255),
            "battlefield": (120, 95, 70),
        }[key]
        if key == "beach":
            draw.rectangle(
                (0, int(height * 0.5), width, int(height * 0.68)), fill=(60, 150, 210)
            )
        for layer in range(3):
            y = height * (0.55 + layer * 0.12)
            points = [(0, height)]
            for step in range(13):
                x = step * width / 12
                points.append(
                    (x, y + math.sin(step * 0.9 + layer * 2 + seed) * height * 0.04)
                )
            points.append((width, height))
            draw.polygon(points, fill=shade(land, 1.0 - layer * 0.07))
        if key == "savanna":
            for x in (0.15, 0.62, 0.85):
                trunk_x = width * x
                draw.line(
                    (trunk_x, height * 0.62, trunk_x - width * 0.01, height * 0.3),
                    fill=(110, 80, 50),
                    width=width // 70,
                )
                draw.line(
                    (trunk_x, height * 0.42, trunk_x + width * 0.05, height * 0.3),
                    fill=(110, 80, 50),
                    width=width // 110,
                )
                draw.ellipse(
                    (
                        trunk_x - width * 0.1,
                        height * 0.2,
                        trunk_x + width * 0.1,
                        height * 0.33,
                    ),
                    fill=(150, 160, 70),
                )
            for _ in range(8):
                x, y = rng.uniform(0, width), rng.uniform(height * 0.62, height * 0.8)
                draw.ellipse(
                    (x, y, x + width * 0.08, y + height * 0.06), fill=(200, 170, 60)
                )
        if key == "battlefield":
            for _ in range(6):
                x, y = rng.uniform(0, width), rng.uniform(height * 0.3, height * 0.6)
                draw.ellipse(
                    (x, y, x + width * 0.2, y + height * 0.15), fill=(80, 80, 80, 70)
                )
        return canvas
    if key == "village":
        canvas = _gradient(size, (170, 215, 245), (245, 235, 215))
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.rectangle((0, int(height * 0.68), width, height), fill=(240, 205, 170))
        for n in range(5):
            x = int(width * (n * 0.22 - 0.03))
            top = int(height * rng.uniform(0.25, 0.4))
            wall = (232, 200, 160) if n % 2 else (220, 185, 145)
            draw.rectangle(
                (x, top, x + int(width * 0.18), int(height * 0.68)),
                fill=wall,
                outline=shade(wall, 0.7),
                width=3,
            )
            draw.rectangle(
                (
                    x + int(width * 0.07),
                    int(height * 0.5),
                    x + int(width * 0.11),
                    int(height * 0.68),
                ),
                fill=(90, 60, 45),
            )
        draw.rectangle(
            (
                int(width * 0.08),
                int(height * 0.52),
                int(width * 0.2),
                int(height * 0.62),
            ),
            fill=(220, 50, 120),
        )
        return canvas
    if key in {"forest"}:
        canvas = _gradient(size, (150, 200, 140), (60, 110, 60))
        draw = ImageDraw.Draw(canvas, "RGBA")
        for layer in range(3):
            for _ in range(9):
                x = rng.uniform(-0.05, 1.0) * width
                tone = (40 + layer * 20, 90 + layer * 25, 40 + layer * 15)
                draw.rectangle(
                    (x, height * 0.2, x + width * 0.025, height * 0.75),
                    fill=(80, 55, 35),
                )
                draw.ellipse(
                    (
                        x - width * 0.08,
                        height * (0.05 + layer * 0.08),
                        x + width * 0.1,
                        height * (0.4 + layer * 0.06),
                    ),
                    fill=tone,
                )
        draw.rectangle((0, int(height * 0.74), width, height), fill=(70, 120, 50))
        return canvas
    if key in {"city", "street"}:
        canvas = _gradient(size, (120, 170, 220), (220, 230, 240))
        draw = ImageDraw.Draw(canvas, "RGBA")
        for n in range(10):
            x = n * width / 9 - width * 0.05
            top = height * rng.uniform(0.1, 0.45)
            body = (rng.randint(80, 140),) * 3
            draw.rectangle((x, top, x + width * 0.1, height * 0.7), fill=body)
            for row in range(int((height * 0.7 - top) // (height * 0.06))):
                for col in range(3):
                    wx = x + width * (0.012 + col * 0.03)
                    wy = top + height * 0.02 + row * height * 0.06
                    draw.rectangle(
                        (wx, wy, wx + width * 0.015, wy + height * 0.03),
                        fill=(250, 230, 150, 200),
                    )
        draw.rectangle((0, int(height * 0.7), width, height), fill=(70, 70, 75))
        for n in range(8):
            x = n * width / 7
            draw.rectangle(
                (x, height * 0.84, x + width * 0.06, height * 0.86),
                fill=(240, 240, 240),
            )
        return canvas
    if key in {"night", "space", "sky"}:
        top, bottom = {
            "night": ((10, 15, 45), (40, 50, 100)),
            "space": ((5, 5, 15), (25, 10, 45)),
            "sky": ((90, 160, 240), (200, 230, 255)),
        }[key]
        canvas = _gradient(size, top, bottom)
        draw = ImageDraw.Draw(canvas, "RGBA")
        if key != "sky":
            for _ in range(160):
                x, y = rng.uniform(0, width), rng.uniform(0, height * 0.8)
                r = rng.uniform(0.6, 2.2)
                draw.ellipse(
                    (x - r, y - r, x + r, y + r),
                    fill=(255, 255, 255, rng.randint(120, 255)),
                )
            draw.ellipse(
                (
                    width * 0.78,
                    height * 0.08,
                    width * 0.88,
                    height * 0.08 + width * 0.1,
                ),
                fill=(245, 240, 220),
            )
        else:
            for _ in range(5):
                x, y = rng.uniform(0, width), rng.uniform(0, height * 0.6)
                draw.ellipse(
                    (x, y, x + width * 0.18, y + height * 0.1),
                    fill=(255, 255, 255, 200),
                )
        if key == "night":
            draw.rectangle((0, int(height * 0.75), width, height), fill=(25, 35, 40))
        canvas = canvas.filter(ImageFilter.SMOOTH)
        return canvas
    return Image.new("RGB", size, (120, 100, 80))


@functools.lru_cache(maxsize=16)
def picture_stage(path: str, width: int, height: int) -> Any:
    """A library picture as the place."""
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
