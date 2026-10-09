"""Painted characters on the stage: cut-out pictures that act.

A painted character is one picture per feeling (and one with the mouth
open). They act the way cut-out animation does: they breathe, bob as they
walk, lean in to punch, shake when scared, jump, and tip over when they
fall; while speaking, the mouth picture swaps in on the syllables.
"""

import functools
import math
from pathlib import Path
from typing import Any

from .aiart import Sprites
from .heads import mouth_open

SPRITE_HEIGHT = 1.08
"""A painted character's height against a drawn one's (hair stands up)."""


@functools.lru_cache(maxsize=96)
def _sized(path: str, height: int, flip: bool, angle: int) -> Any:
    from PIL import Image

    with Image.open(path) as opened:
        picture = opened.convert("RGBA")
    ratio = height / max(1, picture.height)
    picture = picture.resize(
        (max(1, round(picture.width * ratio)), max(1, height)),
        Image.Resampling.LANCZOS,
    )
    if flip:
        picture = picture.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if angle:
        picture = picture.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    return picture


def picture_for(sprites: Sprites, feeling: str, speaking: bool, t: float) -> Path:
    """Which picture shows now: the feeling's, or the open mouth on a syllable."""
    if speaking and sprites.talk is not None and feeling in {"", "neutral"}:
        return sprites.talk if mouth_open(t, True) > 0.45 else sprites.base
    return sprites.for_feeling(feeling)


def draw_sprite(
    canvas: Any,
    sprites: Sprites,
    *,
    action: str,
    feeling: str,
    speaking: bool,
    x: float,
    facing: int,
    t: float,
    ground: float,
    height: float,
    lift: float = 0.0,
    tip: float = 0.0,
    sink: float = 0.0,
    seed: int = 0,
) -> tuple[float, float]:
    """Draw the character with feet on `ground` at x (pixels); returns
    where their face is, for the camera."""
    from PIL import ImageDraw

    tall = height * SPRITE_HEIGHT * (1 - sink * 0.8)
    breathe = 1 + 0.012 * math.sin(t * 2 * math.pi * 0.45 + seed)
    bob = 0.0
    lean = 0.0
    shift = 0.0
    if action in {"walk", "walk_in", "walk_out", "run"}:
        speed = 2.6 if action == "run" else 1.7
        bob = abs(math.sin(t * math.pi * speed)) * height * 0.025
        lean = (7 if action == "run" else 3) * facing
    elif action == "punch":
        lunge = max(0.0, math.sin(t * 2 * math.pi * 1.4))
        shift = facing * lunge * height * 0.08
        lean = facing * lunge * 6
    elif action in {"scared", "cry"}:
        shift = math.sin(t * 60) * height * 0.006
    elif action in {"dance", "cheer"}:
        lean = math.sin(t * 2 * math.pi * 1.2) * 6
        bob = abs(math.sin(t * 2 * math.pi * 1.2)) * height * 0.03
    elif speaking:
        lean = math.sin(t * 2 * math.pi * 0.7 + seed) * 1.5
    angle = round((lean + tip * facing) / 2) * 2
    picture = _sized(
        str(picture_for(sprites, feeling, speaking, t)),
        max(8, round(tall * breathe)),
        facing < 0,
        -angle,
    )
    feet = ground - lift * height - bob
    left = x + shift - picture.width / 2
    top = feet - picture.height
    if tip:
        # Lying down: rest on the ground, not half under it.
        top = ground - picture.height * 0.6
    shadow = height * (0.4 if tip else 0.2)
    ImageDraw.Draw(canvas, "RGBA").ellipse(
        (x - shadow, ground - height * 0.02, x + shadow, ground + height * 0.02),
        fill=(0, 0, 0, 70),
    )
    canvas.paste(picture, (round(left), round(top)), picture)
    return x + shift, top + picture.height * 0.12
