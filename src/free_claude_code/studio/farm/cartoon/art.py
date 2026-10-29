"""Drawing tools for the cartoon: inked outlines, cel shading, soft light.

Everything here draws onto Pillow images. Shapes are drawn with a dark ink
outline first and their colour on top, so every edge reads clearly; big
pictures (places) are drawn larger and shrunk, so lines stay smooth.
"""

import math
import random
from collections.abc import Sequence
from typing import Any

Colour = tuple[int, int, int]
Point = tuple[float, float]
INK = (34, 26, 30)


def mix(a: Colour, b: Colour, amount: float) -> Colour:
    """a moved `amount` of the way to b."""
    amount = max(0.0, min(1.0, amount))
    return (
        round(a[0] + (b[0] - a[0]) * amount),
        round(a[1] + (b[1] - a[1]) * amount),
        round(a[2] + (b[2] - a[2]) * amount),
    )


def darker(colour: Colour, amount: float = 0.25) -> Colour:
    """Shadow tone: darker and a little cooler, the way paint shades."""
    return mix(colour, (30, 30, 60), amount)


def lighter(colour: Colour, amount: float = 0.25) -> Colour:
    """Lit tone: lighter and a little warmer."""
    return mix(colour, (255, 248, 225), amount)


def ink_of(colour: Colour) -> Colour:
    """An outline that belongs to the colour: its own very dark tone."""
    return mix(colour, INK, 0.78)


def gradient(size: tuple[int, int], top: Colour, bottom: Colour) -> Any:
    """A vertical blend (RGB)."""
    from PIL import Image

    height = size[1]
    strip = Image.new("RGB", (1, max(1, height)))
    for y in range(height):
        strip.putpixel((0, y), mix(top, bottom, y / max(1, height - 1)))
    return strip.resize(size)


def glow(
    canvas: Any, centre: Point, radius: float, colour: Colour, strength: int
) -> None:
    """A soft round light (sun, lamp, fire) added onto the canvas."""
    from PIL import Image, ImageDraw, ImageFilter

    box = (
        int(centre[0] - radius * 2),
        int(centre[1] - radius * 2),
        int(centre[0] + radius * 2),
        int(centre[1] + radius * 2),
    )
    w, h = box[2] - box[0], box[3] - box[1]
    if w <= 0 or h <= 0:
        return
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse(
        (w / 2 - radius, h / 2 - radius, w / 2 + radius, h / 2 + radius),
        fill=strength,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(radius * 0.6))
    canvas.paste(Image.new("RGB", (w, h), colour), box[:2], mask)


def shape(
    draw: Any,
    points: Sequence[Point],
    fill: Colour,
    *,
    line: float,
    ink: Colour | None = None,
) -> None:
    """A filled polygon with an inked outline."""
    draw.polygon(
        list(points), fill=fill, outline=ink or ink_of(fill), width=max(1, round(line))
    )


def blob(
    draw: Any,
    box: tuple[float, float, float, float],
    fill: Colour,
    *,
    line: float,
    ink: Colour | None = None,
) -> None:
    """A filled ellipse with an inked outline."""
    draw.ellipse(box, fill=fill, outline=ink or ink_of(fill), width=max(1, round(line)))


def noise(size: tuple[int, int], seed: int, strength: int = 10) -> Any:
    """A fine paper grain to lay over a painted picture (L mode, around 128)."""
    from PIL import Image, ImageFilter

    rng = random.Random(seed)
    small = Image.new("L", (max(1, size[0] // 3), max(1, size[1] // 3)))
    small.putdata(
        [
            128 + rng.randint(-strength, strength)
            for _ in range(small.width * small.height)
        ]
    )
    return small.resize(size).filter(ImageFilter.GaussianBlur(1))


def cloud(
    draw: Any, x: float, y: float, w: float, colour: Colour, rng: random.Random
) -> None:
    """A soft cartoon cloud: puffs with a shaded underside."""
    under = darker(colour, 0.12)
    puffs = [
        (x + w * fx, y + w * fy, w * fr)
        for fx, fy, fr in (
            (0.0, 0.05, 0.22),
            (0.22, -0.08, 0.28),
            (0.48, -0.02, 0.24),
            (0.7, 0.06, 0.18),
            (0.35, 0.1, 0.22),
        )
    ]
    for px, py, r in puffs:
        r *= rng.uniform(0.9, 1.1)
        draw.ellipse(
            (px - r, py - r * 0.8 + r * 0.25, px + r, py + r * 0.8 + r * 0.25),
            fill=under,
        )
    for px, py, r in puffs:
        draw.ellipse((px - r, py - r * 0.8, px + r, py + r * 0.75), fill=colour)


def hills(
    draw: Any,
    width: int,
    base: float,
    rise: float,
    colour: Colour,
    rng: random.Random,
    *,
    bottom: float,
    bumps: int = 3,
) -> list[Point]:
    """A rolling hill line across the picture, filled down to `bottom`."""
    phases = [rng.uniform(0, math.tau) for _ in range(3)]
    points: list[Point] = []
    steps = 64
    for n in range(steps + 1):
        x = width * n / steps
        t = n / steps
        y = base - rise * (
            0.55 * math.sin(t * math.pi * bumps + phases[0])
            + 0.3 * math.sin(t * math.pi * bumps * 2.3 + phases[1])
            + 0.15 * math.sin(t * math.pi * bumps * 5.1 + phases[2])
        )
        points.append((x, y))
    draw.polygon([*points, (width, bottom), (0, bottom)], fill=colour)
    return points


def leafy_tree(
    draw: Any,
    x: float,
    ground: float,
    height: float,
    leaf: Colour,
    bark: Colour,
    rng: random.Random,
    *,
    line: float,
) -> None:
    """A broadleaf tree: a tapered trunk with bark lines, and a crown of leaf
    clumps lit from the upper left, darker underneath."""
    trunk_w = height * 0.09
    top = ground - height * 0.55
    trunk = [
        (x - trunk_w * 0.7, ground),
        (x - trunk_w * 0.35, top),
        (x + trunk_w * 0.35, top),
        (x + trunk_w * 0.7, ground),
    ]
    shape(draw, trunk, bark, line=line)
    for _ in range(4):
        bx = x + rng.uniform(-trunk_w * 0.35, trunk_w * 0.35)
        by = rng.uniform(top + height * 0.08, ground - height * 0.05)
        draw.line(
            (bx, by, bx + rng.uniform(-2, 2), by + height * 0.06),
            fill=darker(bark, 0.35),
            width=max(1, round(line * 0.7)),
        )
    crown_y = ground - height * 0.72
    r = height * 0.24
    clumps = [
        (
            x + rng.uniform(-r * 0.9, r * 0.9),
            crown_y + rng.uniform(-r * 0.6, r * 0.5),
            r * rng.uniform(0.55, 0.8),
        )
        for _ in range(7)
    ]
    edge = ink_of(leaf)
    for cx, cy, cr in clumps:
        draw.ellipse(
            (cx - cr - line, cy - cr - line, cx + cr + line, cy + cr + line), fill=edge
        )
    for cx, cy, cr in clumps:
        draw.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=darker(leaf, 0.18))
    for cx, cy, cr in clumps:
        draw.ellipse((cx - cr * 0.9, cy - cr, cx + cr * 0.7, cy + cr * 0.6), fill=leaf)
    for cx, cy, cr in clumps[:4]:
        draw.ellipse(
            (cx - cr * 0.55, cy - cr * 0.75, cx + cr * 0.05, cy - cr * 0.2),
            fill=lighter(leaf, 0.22),
        )


def pine(
    draw: Any,
    x: float,
    ground: float,
    height: float,
    leaf: Colour,
    *,
    line: float,
    snow: bool = False,
) -> None:
    """A pine: stacked needle tiers, each shaded on its right."""
    trunk = (96, 64, 42)
    draw.rectangle(
        (x - height * 0.03, ground - height * 0.12, x + height * 0.03, ground),
        fill=trunk,
        outline=ink_of(trunk),
        width=max(1, round(line)),
    )
    tiers = 4
    for n in range(tiers):
        bottom = ground - height * (0.1 + n * 0.2)
        half = height * (0.3 - n * 0.055)
        peak = bottom - height * 0.34
        shape(
            draw, [(x - half, bottom), (x, peak), (x + half, bottom)], leaf, line=line
        )
        draw.polygon(
            [
                (x, peak + line),
                (x + half - line, bottom - line),
                (x + line, bottom - line),
            ],
            fill=darker(leaf, 0.2),
        )
        if snow:
            draw.polygon(
                [
                    (x - half * 0.55, bottom - height * 0.12),
                    (x, peak),
                    (x + half * 0.5, bottom - height * 0.13),
                ],
                fill=(245, 248, 255),
            )
