"""One cartoon shot: a place, the characters in it, and the camera.

The stage is drawn at 1280x720 and filmed: a wide shot shows it all, a
medium or close shot follows one character's face, a push creeps in, a pan
slides across. Characters stand where they're put (left, middle, right) and
face whoever is in the middle of the scene.
"""

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .puppet import Placed, draw_figure, head_box
from .stages import GROUND, stage_for

STAGE = (1280, 720)
FIGURE = 0.66
"""A grown-up's height, head to feet, as a share of the stage's height."""
CAMERAS = ("wide", "medium", "close", "push", "pan")
SPOTS = {
    "far left": 0.12,
    "left": 0.25,
    "center left": 0.38,
    "centre left": 0.38,
    "middle": 0.5,
    "center": 0.5,
    "centre": 0.5,
    "center right": 0.62,
    "centre right": 0.62,
    "right": 0.75,
    "far right": 0.88,
}


@dataclass(frozen=True, slots=True)
class CartoonShot:
    place: str
    actors: tuple[Placed, ...]
    camera: str = "wide"
    focus: str = ""
    """Whose face the camera follows in a medium or close shot."""
    picture: Path | None = field(default=None, compare=False)
    """A library picture for the place, instead of a drawn one."""
    shake: bool = False
    seed: int = 0


def spread(count: int) -> list[float]:
    """Where `count` characters stand when nobody said."""
    return {
        0: [],
        1: [0.5],
        2: [0.32, 0.68],
        3: [0.2, 0.5, 0.8],
        4: [0.14, 0.38, 0.62, 0.86],
    }.get(count, [0.1 + 0.8 * n / max(1, count - 1) for n in range(count)])


def spot(value: object, default: float) -> float:
    if isinstance(value, int | float):
        return max(0.05, min(0.95, float(value)))
    text = " ".join(str(value or "").lower().replace("-", " ").split())
    return SPOTS.get(text, default)


def paint(shot: CartoonShot, t: float, length: float, size: tuple[int, int]) -> Any:
    """The shot at t seconds, filmed at `size` (RGB)."""
    from PIL import Image

    width, height = STAGE
    canvas = stage_for(
        shot.place, width, height, picture=shot.picture, seed=shot.seed
    ).copy()
    ground = height * GROUND
    body = height * FIGURE
    # Characters further back (higher on screen) are drawn first.
    for placed in sorted(
        shot.actors, key=lambda p: p.action in {"lie", "fall", "crawl"}
    ):
        draw_figure(canvas, placed, t=t, length=length, ground=ground, height=body)
    zoom, cx, cy = _camera(shot, t, length, ground, body)
    crop_w, crop_h = width / zoom, height / zoom
    if shot.shake:
        rng = random.Random(int(t * 30))
        cx += rng.uniform(-1, 1) * width * 0.01
        cy += rng.uniform(-1, 1) * height * 0.01
    left = min(max(0.0, cx - crop_w / 2), width - crop_w)
    top = min(max(0.0, cy - crop_h / 2), height - crop_h)
    return canvas.resize(
        size, Image.Resampling.BILINEAR, box=(left, top, left + crop_w, top + crop_h)
    )


def _camera(
    shot: CartoonShot, t: float, length: float, ground: float, body: float
) -> tuple[float, float, float]:
    width, height = STAGE
    progress = min(1.0, t / max(0.5, length))
    kind = shot.camera if shot.camera in CAMERAS else "wide"
    if kind in {"medium", "close"}:
        target = next(
            (p for p in shot.actors if p.look.name.lower() == shot.focus.lower()), None
        )
        target = (
            target
            or next((p for p in shot.actors if p.speaking), None)
            or (shot.actors[0] if shot.actors else None)
        )
        if target is not None:
            x, y = head_box(target, t, length, canvas=STAGE, ground=ground, height=body)
            zoom = 2.3 if kind == "close" else 1.55
            # A slow creep in keeps a close-up alive; it opens with a quick
            # snap in, and the camera breathes a little, as if hand-held.
            zoom *= 1 + 0.05 * progress + 0.07 * max(0.0, 1 - t / 0.25)
            drift_x = math.sin(t * 0.9 + shot.seed) * body * 0.012
            drift_y = math.cos(t * 0.7 + shot.seed) * body * 0.008
            return (
                zoom,
                x + drift_x,
                y + drift_y + (body * 0.05 if kind == "close" else body * 0.32),
            )
    if kind == "push":
        return 1.0 + 0.3 * progress, width / 2, height * 0.55
    if kind == "pan":
        return 1.3, width * (0.38 + 0.24 * progress), height * 0.55
    return 1.0 + 0.03 * math.sin(progress * math.pi), width / 2, height / 2
