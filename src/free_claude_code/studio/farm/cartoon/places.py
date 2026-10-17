"""The places, painted: layered depth, inked shapes, light and shade.

Each place is painted back to front: the sky, far hills or walls in hazy
colours, the middle distance, then the near ground and its props, each
shape inked and shaded with light from the upper left. Characters stand on
the ground line near the bottom, so the busy detail stays behind and around them.
Places are painted twice the size and shrunk, so every line is smooth.
"""

import math
import random
from collections.abc import Callable
from itertools import pairwise
from typing import Any

from .art import (
    Colour,
    blob,
    cloud,
    darker,
    glow,
    gradient,
    hills,
    ink_of,
    leafy_tree,
    lighter,
    mix,
    noise,
    pine,
    shape,
)

HORIZON = 0.66
"""Where the far ground meets the sky, as a share of the height."""
FLOOR = 0.68
"""Where an indoor back wall meets the floor."""


class Painter:
    """One place being painted: the canvas, its size, and a pen size."""

    def __init__(self, canvas: Any, rng: random.Random) -> None:
        from PIL import ImageDraw

        self.canvas = canvas
        self.draw = ImageDraw.Draw(canvas, "RGBA")
        self.w, self.h = canvas.size
        self.u = self.h / 720
        self.line = max(1.5, 2.2 * self.u)
        self.rng = rng

    def x(self, share: float) -> float:
        return self.w * share

    def y(self, share: float) -> float:
        return self.h * share

    def sky(self, top: Colour, bottom: Colour, *, until: float = HORIZON) -> None:
        self.canvas.paste(
            gradient((self.w, int(self.y(until)) + 2), top, bottom), (0, 0)
        )

    def ground(self, near: Colour, far: Colour, *, start: float = HORIZON) -> None:
        y0 = int(self.y(start))
        self.canvas.paste(gradient((self.w, self.h - y0), far, near), (0, y0))

    def clouds(
        self, count: int, colour: Colour = (255, 255, 255), *, high: float = 0.35
    ) -> None:
        for _ in range(count):
            cloud(
                self.draw,
                self.rng.uniform(-0.05, 0.95) * self.w,
                self.rng.uniform(0.06, high) * self.h,
                self.rng.uniform(0.1, 0.2) * self.w,
                colour,
                self.rng,
            )

    def tufts(self, colour: Colour, count: int, *, top: float = 0.72) -> None:
        """Grass tufts scattered over the near ground, bigger nearer."""
        for _ in range(count):
            x = self.rng.uniform(0, self.w)
            y = self.rng.uniform(self.y(top), self.h)
            size = (8 + 14 * (y - self.y(top)) / (self.h - self.y(top) + 1)) * self.u
            for lean in (-0.5, 0.0, 0.45):
                self.draw.line(
                    (x, y, x + lean * size, y - size),
                    fill=darker(colour, 0.2 + self.rng.random() * 0.15),
                    width=max(1, round(self.u * 1.6)),
                )

    def stones(self, colour: Colour, count: int, *, top: float = 0.75) -> None:
        for _ in range(count):
            x = self.rng.uniform(0, self.w)
            y = self.rng.uniform(self.y(top), self.h)
            r = self.rng.uniform(5, 13) * self.u * (0.6 + (y / self.h))
            blob(
                self.draw,
                (x - r * 1.4, y - r, x + r * 1.4, y + r * 0.5),
                colour,
                line=self.line * 0.8,
            )
            self.draw.ellipse(
                (x - r * 0.9, y - r * 0.8, x - r * 0.1, y - r * 0.3),
                fill=lighter(colour, 0.25),
            )


# ----------------------------------------------------------------- outdoors


def _savanna(p: Painter) -> None:
    p.sky((246, 170, 92), (255, 226, 168))
    glow(p.canvas, (p.x(0.72), p.y(0.42)), p.y(0.11), (255, 236, 170), 255)
    p.draw.ellipse(
        (p.x(0.72) - p.y(0.08), p.y(0.34), p.x(0.72) + p.y(0.08), p.y(0.5)),
        fill=(255, 214, 120),
    )
    hills(p.draw, p.w, p.y(0.6), p.y(0.06), (196, 140, 130), p.rng, bottom=p.h, bumps=2)
    hills(p.draw, p.w, p.y(0.66), p.y(0.03), (214, 162, 98), p.rng, bottom=p.h, bumps=4)
    p.ground((206, 152, 70), (226, 182, 96), start=0.68)
    for n in range(7):  # Bands of darker grass give the plain depth.
        y = p.y(0.7 + n * 0.04)
        p.draw.rectangle((0, y, p.w, y + p.u * (2 + n)), fill=(188, 132, 58, 70))
    for x, height in ((0.16, 0.36), (0.86, 0.3), (0.55, 0.16)):
        _acacia(p, p.x(x), p.y(0.72 if height < 0.2 else 0.84), p.y(height))
    for n in range(5):  # Birds far off.
        bx, by = p.x(0.2 + n * 0.05), p.y(0.2 + (n % 2) * 0.03)
        p.draw.arc(
            (bx, by, bx + 10 * p.u, by + 6 * p.u),
            200,
            340,
            fill=(90, 60, 50),
            width=max(1, round(p.u * 1.5)),
        )
        p.draw.arc(
            (bx + 9 * p.u, by, bx + 19 * p.u, by + 6 * p.u),
            200,
            340,
            fill=(90, 60, 50),
            width=max(1, round(p.u * 1.5)),
        )
    p.tufts((206, 152, 70), 90)


def _acacia(p: Painter, x: float, ground: float, height: float) -> None:
    bark = (92, 62, 40)
    trunk = [
        (x - height * 0.04, ground),
        (x - height * 0.01, ground - height * 0.6),
        (x + height * 0.03, ground - height * 0.6),
        (x + height * 0.05, ground),
    ]
    shape(p.draw, trunk, bark, line=p.line)
    for side in (-1, 1):
        p.draw.line(
            (
                x,
                ground - height * 0.5,
                x + side * height * 0.22,
                ground - height * 0.78,
            ),
            fill=ink_of(bark),
            width=max(2, round(height * 0.035)),
        )
    crown = (
        x - height * 0.42,
        ground - height * 0.98,
        x + height * 0.42,
        ground - height * 0.72,
    )
    leaf = (92, 122, 52)
    blob(p.draw, crown, leaf, line=p.line)
    p.draw.ellipse(
        (
            crown[0] + height * 0.06,
            crown[1] + height * 0.02,
            crown[2] - height * 0.18,
            crown[1] + height * 0.12,
        ),
        fill=lighter(leaf, 0.2),
    )
    p.draw.chord(
        (
            crown[0] + p.line,
            crown[1] + height * 0.12,
            crown[2] - p.line,
            crown[3] - p.line,
        ),
        0,
        180,
        fill=darker(leaf, 0.2),
    )


def _desert(p: Painter) -> None:
    p.sky((112, 170, 222), (250, 218, 170))
    glow(p.canvas, (p.x(0.18), p.y(0.18)), p.y(0.07), (255, 250, 220), 230)
    for base, rise, colour in (
        (0.6, 0.06, (226, 176, 120)),
        (0.68, 0.05, (236, 190, 128)),
        (0.78, 0.04, (242, 202, 140)),
    ):
        line = hills(
            p.draw, p.w, p.y(base), p.y(rise), colour, p.rng, bottom=p.h, bumps=2
        )
        # Wind-swept ripples below each crest, and the crest catching the sun.
        for depth in (0.015, 0.03):
            p.draw.line(
                [(x, y + p.y(depth)) for x, y in line],
                fill=darker(colour, 0.1),
                width=max(1, round(p.u * 1.5)),
            )
        p.draw.line(line, fill=lighter(colour, 0.3), width=max(2, round(p.u * 3)))
    for x, s in ((0.12, 1.0), (0.84, 0.75), (0.6, 0.45)):
        _cactus(p, p.x(x), p.y(0.86 if s > 0.6 else 0.76), p.y(0.26 * s))
    p.stones((176, 136, 100), 10, top=0.8)


def _cactus(p: Painter, x: float, ground: float, height: float) -> None:
    green = (88, 150, 92)
    w = height * 0.13
    edge = ink_of(green)
    pen = round(p.line)
    for side, at, up in ((-1, 0.55, 0.3), (1, 0.4, 0.25)):
        # Each arm: out from the trunk, then up, drawn behind the trunk.
        arm_x = x + side * w * 2.4
        low, high = min(x, arm_x), max(x, arm_x)
        y = ground - height * at
        p.draw.rounded_rectangle(
            (low - w * 0.6, y - w * 0.6, high + w * 0.6, y + w * 0.6),
            radius=w * 0.6,
            fill=green,
            outline=edge,
            width=pen,
        )
        p.draw.rounded_rectangle(
            (
                arm_x - w * 0.6,
                ground - height * (at + up),
                arm_x + w * 0.6,
                y + w * 0.6,
            ),
            radius=w * 0.6,
            fill=green,
            outline=edge,
            width=pen,
        )
        p.draw.rectangle(
            (low + w * 0.2, y - w * 0.6 + pen, high - w * 0.2, y + w * 0.6 - pen),
            fill=green,
        )
    p.draw.rounded_rectangle(
        (x - w, ground - height, x + w, ground),
        radius=w,
        fill=green,
        outline=edge,
        width=pen,
    )
    p.draw.rectangle(
        (x + w * 0.35, ground - height + w, x + w - pen, ground - pen),
        fill=darker(green, 0.15),
    )
    for n in range(3):
        sx = x - w * 0.5 + n * w * 0.5
        p.draw.line(
            (sx, ground - height * 0.95, sx, ground - p.u * 4),
            fill=darker(green, 0.25),
            width=max(1, round(p.u)),
        )


def _forest(p: Painter) -> None:
    p.sky((150, 196, 170), (206, 228, 196), until=0.75)
    for depth, (shade_, size, count, base) in enumerate(
        ((0.55, 0.42, 9, 0.66), (0.3, 0.55, 7, 0.74), (0.0, 0.72, 4, 0.86))
    ):
        leaf = mix((64, 128, 70), (170, 206, 176), shade_)
        bark = mix((86, 60, 42), (170, 196, 170), shade_)
        if depth == 0:
            hills(
                p.draw,
                p.w,
                p.y(0.68),
                p.y(0.03),
                mix((70, 120, 70), (170, 206, 176), 0.5),
                p.rng,
                bottom=p.h,
            )
        for n in range(count):
            x = p.x((n + p.rng.uniform(0.1, 0.9)) / count)
            if depth == 2 and 0.25 < x / p.w < 0.75:
                continue  # Keep the middle open for the characters.
            leafy_tree(p.draw, x, p.y(base), p.y(size), leaf, bark, p.rng, line=p.line)
        if depth == 0:
            p.ground((76, 132, 62), (112, 164, 90), start=0.7)
    # Light falling through the leaves.
    for n in range(5):
        x = p.x(0.1 + n * 0.2)
        p.draw.polygon(
            [(x, 0), (x + p.x(0.05), 0), (x + p.x(0.13), p.h), (x + p.x(0.06), p.h)],
            fill=(255, 250, 210, 26),
        )
    for n in range(14):  # Ferns and mushrooms on the floor.
        x, y = p.rng.uniform(0, p.w), p.rng.uniform(p.y(0.88), p.h)
        if n % 4 == 0:
            cap = (196, 62, 52)
            p.draw.rectangle(
                (x - 3 * p.u, y - 10 * p.u, x + 3 * p.u, y),
                fill=(240, 232, 214),
                outline=(90, 70, 60),
            )
            p.draw.chord(
                (x - 10 * p.u, y - 20 * p.u, x + 10 * p.u, y - 2 * p.u),
                180,
                360,
                fill=cap,
                outline=ink_of(cap),
                width=round(p.line),
            )
            p.draw.ellipse(
                (x - 4 * p.u, y - 16 * p.u, x, y - 12 * p.u), fill=(255, 255, 255)
            )
        else:
            for k in range(5):
                angle = math.radians(-150 + k * 30)
                p.draw.line(
                    (
                        x,
                        y,
                        x + math.cos(angle) * 26 * p.u,
                        y + math.sin(angle) * 22 * p.u,
                    ),
                    fill=(58, 112, 52),
                    width=max(2, round(3 * p.u)),
                )
    p.tufts((86, 150, 70), 80, top=0.8)


def _village(p: Painter) -> None:
    p.sky((126, 186, 236), (214, 234, 246))
    p.clouds(4)
    hills(p.draw, p.w, p.y(0.58), p.y(0.05), (150, 176, 140), p.rng, bottom=p.h)
    p.ground((214, 168, 112), (226, 186, 132), start=0.66)
    # A path curving through.
    p.draw.polygon(
        [
            (p.x(0.4), p.y(0.66)),
            (p.x(0.52), p.y(0.66)),
            (p.x(0.8), p.h),
            (p.x(0.2), p.h),
        ],
        fill=(232, 198, 150),
    )
    huts = [(0.08, 0.6, 0.15), (0.3, 0.64, 0.1), (0.68, 0.63, 0.11), (0.9, 0.62, 0.16)]
    for x, base, size in huts:
        _round_hut(p, p.x(x), p.y(base) + p.y(size) * 0.9, p.y(size * 2))
    _palm(p, p.x(0.55), p.y(0.66), p.y(0.36))
    _stall(p, p.x(0.2), p.y(0.86), p.y(0.2))
    for x in (0.74, 0.79):  # Clay pots by the path.
        pot = (176, 98, 60)
        cx, cy = p.x(x), p.y(0.86)
        blob(
            p.draw, (cx - 18 * p.u, cy - 30 * p.u, cx + 18 * p.u, cy), pot, line=p.line
        )
        p.draw.rectangle(
            (cx - 9 * p.u, cy - 36 * p.u, cx + 9 * p.u, cy - 27 * p.u),
            fill=darker(pot, 0.1),
            outline=ink_of(pot),
            width=round(p.line),
        )
        p.draw.arc(
            (cx - 12 * p.u, cy - 24 * p.u, cx + 6 * p.u, cy - 8 * p.u),
            180,
            260,
            fill=lighter(pot, 0.35),
            width=round(p.line),
        )
    p.stones((168, 136, 104), 8)


def _round_hut(p: Painter, x: float, ground: float, height: float) -> None:
    wall = (198, 140, 92)
    half = height * 0.42
    body = (x - half, ground - height * 0.55, x + half, ground)
    p.draw.rectangle(body, fill=wall, outline=ink_of(wall), width=round(p.line))
    p.draw.rectangle(
        (x + half * 0.35, body[1], x + half, ground), fill=darker(wall, 0.15)
    )
    door = (x - half * 0.25, ground - height * 0.38, x + half * 0.2, ground)
    p.draw.rounded_rectangle(
        door,
        radius=half * 0.2,
        fill=(70, 46, 32),
        outline=ink_of(wall),
        width=round(p.line),
    )
    thatch = (196, 160, 82)
    roof = [
        (x - half * 1.3, body[1] + height * 0.04),
        (x, ground - height * 1.08),
        (x + half * 1.3, body[1] + height * 0.04),
    ]
    shape(p.draw, roof, thatch, line=p.line)
    p.draw.polygon(
        [
            (x, ground - height * 1.08),
            (x + half * 1.3, body[1] + height * 0.04),
            (x + half * 0.2, body[1] + height * 0.04),
        ],
        fill=darker(thatch, 0.18),
    )
    for n in range(7):  # Straw lines.
        t = (n + 0.5) / 7
        p.draw.line(
            (
                x,
                ground - height * 1.06,
                x - half * 1.3 + t * half * 2.6,
                body[1] + height * 0.03,
            ),
            fill=darker(thatch, 0.3),
            width=max(1, round(p.u)),
        )


def _palm(p: Painter, x: float, ground: float, height: float) -> None:
    bark = (140, 104, 66)
    points = []
    for n in range(9):
        t = n / 8
        points.append((x + math.sin(t * 1.4) * height * 0.12, ground - t * height))
    for (x1, y1), (x2, y2) in pairwise(points):
        shape(
            p.draw,
            [
                (x1 - height * 0.03, y1),
                (x2 - height * 0.025, y2),
                (x2 + height * 0.025, y2),
                (x1 + height * 0.03, y1),
            ],
            bark,
            line=p.line * 0.8,
        )
    top = points[-1]
    leaf = (62, 140, 72)
    for angle in (-160, -125, -90, -55, -20, 15, 200):
        a = math.radians(angle)
        tip = (
            top[0] + math.cos(a) * height * 0.38,
            top[1] + math.sin(a) * height * 0.22 + height * 0.1,
        )
        mid = (
            top[0] + math.cos(a) * height * 0.2,
            top[1] + math.sin(a) * height * 0.2 - height * 0.04,
        )
        shape(
            p.draw,
            [
                top,
                (mid[0], mid[1] - height * 0.03),
                tip,
                (mid[0], mid[1] + height * 0.03),
            ],
            leaf,
            line=p.line * 0.8,
        )
    for n in range(3):
        blob(
            p.draw,
            (
                top[0] - 9 * p.u + n * 7 * p.u,
                top[1] + 2 * p.u,
                top[0] + 3 * p.u + n * 7 * p.u,
                top[1] + 14 * p.u,
            ),
            (110, 76, 40),
            line=p.line * 0.6,
        )


def _stall(p: Painter, x: float, ground: float, height: float) -> None:
    wood = (128, 88, 56)
    for side in (-1, 1):
        p.draw.rectangle(
            (
                x + side * height * 0.6 - 4 * p.u,
                ground - height,
                x + side * height * 0.6 + 4 * p.u,
                ground,
            ),
            fill=wood,
            outline=ink_of(wood),
        )
    table = (
        x - height * 0.7,
        ground - height * 0.4,
        x + height * 0.7,
        ground - height * 0.3,
    )
    shape(
        p.draw,
        [
            (table[0], table[1]),
            (table[2], table[1]),
            (table[2], table[3]),
            (table[0], table[3]),
        ],
        wood,
        line=p.line,
    )
    for n, fruit in enumerate(
        ((230, 140, 40), (200, 50, 50), (240, 200, 60), (120, 170, 60))
    ):
        cx = table[0] + height * (0.2 + n * 0.32)
        blob(
            p.draw,
            (cx - 12 * p.u, table[1] - 20 * p.u, cx + 12 * p.u, table[1] + 2 * p.u),
            fruit,
            line=p.line * 0.8,
        )
    stripes = ((214, 62, 62), (250, 240, 220))
    awning_top, awning_bottom = ground - height * 1.05, ground - height * 0.85
    n_stripes = 8
    for n in range(n_stripes):
        x1 = x - height * 0.8 + n * height * 1.6 / n_stripes
        x2 = x1 + height * 1.6 / n_stripes
        p.draw.polygon(
            [
                (x1, awning_top),
                (x2, awning_top),
                (x2 + 2 * p.u, awning_bottom),
                (x1 + 2 * p.u, awning_bottom),
            ],
            fill=stripes[n % 2],
        )
    p.draw.rectangle(
        (x - height * 0.8, awning_top, x + height * 0.8, awning_bottom),
        outline=ink_of(stripes[0]),
        width=round(p.line),
    )


def _city(p: Painter, *, night: bool = False) -> None:
    if night:
        p.sky((22, 26, 60), (80, 70, 120))
    else:
        p.sky((120, 180, 232), (232, 214, 196))
        p.clouds(3)
    for layer, (tint, base, tall) in enumerate(((0.55, 0.66, 0.38), (0.25, 0.7, 0.32))):
        x = -p.x(0.02)
        while x < p.w:
            bw = p.x(p.rng.uniform(0.06, 0.12))
            bh = p.y(p.rng.uniform(0.15, tall))
            colour = mix(
                (92, 104, 132), (190, 206, 226) if not night else (60, 64, 104), tint
            )
            box = (x, p.y(base) - bh, x + bw, p.y(base))
            p.draw.rectangle(
                box,
                fill=colour,
                outline=ink_of(colour) if layer else None,
                width=round(p.line),
            )
            if layer:
                p.draw.rectangle(
                    (box[2] - bw * 0.25, box[1], box[2], box[3]),
                    fill=darker(colour, 0.12),
                )
            for wy in range(
                int(box[1] + 10 * p.u), int(box[3] - 10 * p.u), int(18 * p.u)
            ):
                for wx in range(
                    int(box[0] + 8 * p.u), int(box[2] - 12 * p.u), int(16 * p.u)
                ):
                    lit = p.rng.random() < (0.55 if night else 0.2)
                    fill = (
                        (255, 220, 120)
                        if lit and night
                        else (lighter(colour, 0.35) if lit else darker(colour, 0.15))
                    )
                    p.draw.rectangle((wx, wy, wx + 8 * p.u, wy + 10 * p.u), fill=fill)
            x += bw + p.x(0.005)
    p.ground((126, 126, 132), (150, 150, 158), start=0.7)
    p.draw.rectangle(
        (0, p.y(0.7), p.w, p.y(0.74)), fill=(186, 182, 176), outline=(110, 108, 106)
    )
    for n in range(12):  # Pavement slabs.
        x = p.x(n / 12)
        p.draw.line(
            (x, p.y(0.74), x - p.x(0.04), p.h),
            fill=(112, 112, 118),
            width=max(1, round(p.u * 1.5)),
        )
    for x in (0.1, 0.9):
        _lamp(p, p.x(x), p.y(0.9), p.y(0.42), lit=night)


def _lamp(p: Painter, x: float, ground: float, height: float, *, lit: bool) -> None:
    metal = (54, 60, 70)
    p.draw.rectangle(
        (x - 4 * p.u, ground - height, x + 4 * p.u, ground),
        fill=metal,
        outline=ink_of(metal),
    )
    head = (x - 16 * p.u, ground - height - 22 * p.u, x + 16 * p.u, ground - height)
    shape(
        p.draw,
        [
            (head[0], head[3]),
            (head[0] + 6 * p.u, head[1]),
            (head[2] - 6 * p.u, head[1]),
            (head[2], head[3]),
        ],
        metal,
        line=p.line,
    )
    if lit:
        glow(p.canvas, (x, ground - height + 6 * p.u), 60 * p.u, (255, 220, 140), 150)
    p.draw.ellipse(
        (
            x - 8 * p.u,
            ground - height - 4 * p.u,
            x + 8 * p.u,
            ground - height + 10 * p.u,
        ),
        fill=(255, 236, 170) if lit else (230, 230, 210),
    )


def _street(p: Painter) -> None:
    p.sky((132, 190, 236), (228, 222, 210))
    p.clouds(3)
    vanish = (p.x(0.5), p.y(0.6))
    for side in (-1, 1):
        x = p.x(0.5) + side * p.x(0.08)
        for n in range(5):  # Shopfronts getting nearer.
            far = 1 - n / 5
            width = p.x(0.06 + 0.06 * (1 - far))
            height = p.y(0.18 + 0.3 * (1 - far))
            colour = (
                (196, 120, 96),
                (118, 150, 186),
                (210, 178, 110),
                (140, 170, 120),
                (186, 140, 170),
            )[(n + (side > 0)) % 5]
            x2 = x + side * width
            box = (
                min(x, x2),
                vanish[1] + p.y(0.06 * (1 - far)) - height,
                max(x, x2),
                vanish[1] + p.y(0.06 * (1 - far)) + p.y(0.1 * (1 - far)),
            )
            p.draw.rectangle(
                box, fill=colour, outline=ink_of(colour), width=round(p.line)
            )
            window = (
                box[0] + (box[2] - box[0]) * 0.15,
                box[1] + (box[3] - box[1]) * 0.15,
                box[2] - (box[2] - box[0]) * 0.15,
                box[1] + (box[3] - box[1]) * 0.45,
            )
            p.draw.rectangle(
                window,
                fill=(186, 220, 240),
                outline=ink_of(colour),
                width=round(p.line * 0.8),
            )
            p.draw.line(
                (window[0], window[1], window[2], window[3]),
                fill=(240, 250, 255),
                width=max(1, round(p.u)),
            )
            awning = (
                box[0],
                box[1] + (box[3] - box[1]) * 0.5,
                box[2],
                box[1] + (box[3] - box[1]) * 0.58,
            )
            p.draw.rectangle(awning, fill=darker(colour, 0.25))
            x = x2
    road = [
        (p.x(0.44), p.y(0.66)),
        (p.x(0.56), p.y(0.66)),
        (p.x(1.1), p.h),
        (p.x(-0.1), p.h),
    ]
    p.draw.polygon(road, fill=(96, 98, 106))
    for n in range(6):  # The middle line, closer stripes bigger.
        t0, t1 = (n / 6) ** 1.6, ((n + 0.5) / 6) ** 1.6
        y0, y1 = p.y(0.66) + (p.h - p.y(0.66)) * t0, p.y(0.66) + (p.h - p.y(0.66)) * t1
        half0, half1 = p.u * (1 + 5 * t0), p.u * (1 + 5 * t1)
        p.draw.polygon(
            [
                (p.x(0.5) - half0, y0),
                (p.x(0.5) + half0, y0),
                (p.x(0.5) + half1, y1),
                (p.x(0.5) - half1, y1),
            ],
            fill=(244, 222, 120),
        )
    for side in (0.08, 0.92):
        _lamp(p, p.x(side), p.y(0.92), p.y(0.4), lit=False)


def _night(p: Painter) -> None:
    p.sky((12, 18, 48), (52, 58, 110), until=0.7)
    for _ in range(160):
        x, y = p.rng.uniform(0, p.w), p.rng.uniform(0, p.y(0.55))
        r = p.rng.choice((0.8, 1.0, 1.4, 2.2)) * p.u
        p.draw.ellipse(
            (x - r, y - r, x + r, y + r), fill=(255, 250, 230, p.rng.randint(120, 255))
        )
    moon = (p.x(0.78), p.y(0.2))
    glow(p.canvas, moon, p.y(0.12), (190, 200, 255), 150)
    r = p.y(0.07)
    p.draw.ellipse(
        (moon[0] - r, moon[1] - r, moon[0] + r, moon[1] + r),
        fill=(246, 240, 214),
        outline=(200, 190, 160),
        width=round(p.line),
    )
    for dx, dy, cr in ((-0.3, -0.2, 0.22), (0.25, 0.15, 0.16), (-0.05, 0.4, 0.12)):
        p.draw.ellipse(
            (
                moon[0] + dx * r - cr * r,
                moon[1] + dy * r - cr * r,
                moon[0] + dx * r + cr * r,
                moon[1] + dy * r + cr * r,
            ),
            fill=(222, 214, 186),
        )
    hills(p.draw, p.w, p.y(0.62), p.y(0.06), (34, 44, 82), p.rng, bottom=p.h, bumps=2)
    for n in range(6):
        pine(
            p.draw,
            p.x(0.05 + n * 0.18 + p.rng.uniform(-0.03, 0.03)),
            p.y(0.68),
            p.y(p.rng.uniform(0.2, 0.3)),
            (24, 40, 58),
            line=p.line,
        )
    p.ground((28, 44, 52), (40, 58, 74), start=0.68)
    _round_hut(p, p.x(0.86), p.y(0.84), p.y(0.3))
    p.draw.rounded_rectangle(
        (p.x(0.845), p.y(0.74), p.x(0.875), p.y(0.84)),
        radius=4 * p.u,
        fill=(255, 200, 100),
    )
    glow(p.canvas, (p.x(0.86), p.y(0.8)), p.y(0.06), (255, 190, 90), 110)
    for _ in range(18):  # Fireflies.
        x, y = p.rng.uniform(0, p.w), p.rng.uniform(p.y(0.6), p.y(0.88))
        glow(p.canvas, (x, y), 5 * p.u, (230, 255, 140), 200)


def _beach(p: Painter) -> None:
    p.sky((96, 176, 236), (210, 236, 248), until=0.6)
    p.clouds(3, high=0.3)
    glow(p.canvas, (p.x(0.2), p.y(0.16)), p.y(0.08), (255, 248, 210), 230)
    p.canvas.paste(
        gradient((p.w, int(p.y(0.12))), (52, 140, 196), (92, 186, 210)),
        (0, int(p.y(0.58))),
    )
    for n in range(10):  # Sparkle and wave lines on the sea.
        y = p.y(0.6 + n * 0.01)
        for _ in range(6):
            x = p.rng.uniform(0, p.w)
            p.draw.line(
                (x, y, x + p.x(0.04), y),
                fill=(230, 248, 255, 160),
                width=max(1, round(p.u)),
            )
    p.ground((236, 208, 150), (226, 196, 140), start=0.7)
    foam = [(p.w * n / 40, p.y(0.7) + math.sin(n * 0.9) * 4 * p.u) for n in range(41)]
    p.draw.polygon([*foam, (p.w, p.y(0.68)), (0, p.y(0.68))], fill=(120, 196, 214))
    p.draw.line(foam, fill=(250, 252, 255), width=max(2, round(p.u * 4)))
    _palm(p, p.x(0.1), p.y(0.86), p.y(0.5))
    _palm(p, p.x(0.92), p.y(0.84), p.y(0.42))
    umbrella = (232, 80, 72)
    ux, uy = p.x(0.72), p.y(0.86)
    p.draw.line(
        (ux, uy, ux - 6 * p.u, uy - p.y(0.24)),
        fill=(90, 70, 60),
        width=max(2, round(p.u * 4)),
    )
    p.draw.chord(
        (ux - p.y(0.14), uy - p.y(0.32), ux + p.y(0.12), uy - p.y(0.16)),
        180,
        360,
        fill=umbrella,
        outline=ink_of(umbrella),
        width=round(p.line),
    )
    for n in range(4):
        p.draw.line(
            (
                ux - 6 * p.u,
                uy - p.y(0.32),
                ux - p.y(0.14) + n * p.y(0.087),
                uy - p.y(0.24),
            ),
            fill=(250, 240, 230),
            width=max(1, round(p.u * 2)),
        )
    for _ in range(10):  # Shells.
        x, y = p.rng.uniform(0, p.w), p.rng.uniform(p.y(0.78), p.h)
        p.draw.chord(
            (x - 7 * p.u, y - 7 * p.u, x + 7 * p.u, y + 5 * p.u),
            180,
            360,
            fill=(250, 220, 206),
            outline=(190, 150, 140),
        )


def _snow(p: Painter) -> None:
    p.sky((170, 196, 226), (232, 238, 246))
    hills(
        p.draw, p.w, p.y(0.56), p.y(0.07), (206, 218, 236), p.rng, bottom=p.h, bumps=2
    )
    for n in range(8):
        pine(
            p.draw,
            p.x(n / 7 + p.rng.uniform(-0.03, 0.03)),
            p.y(0.66),
            p.y(p.rng.uniform(0.16, 0.24)),
            (70, 110, 110),
            line=p.line,
            snow=True,
        )
    p.ground((244, 248, 252), (226, 234, 246), start=0.66)
    for n in range(5):  # Blue shadows in the snow.
        x = p.rng.uniform(0, p.w)
        p.draw.ellipse(
            (x - p.x(0.12), p.y(0.78 + n * 0.03), x + p.x(0.12), p.y(0.81 + n * 0.03)),
            fill=(196, 212, 236, 120),
        )
    for x in (0.08, 0.93):
        pine(
            p.draw, p.x(x), p.y(0.92), p.y(0.48), (56, 100, 96), line=p.line, snow=True
        )
    for _ in range(220):  # Falling snow.
        x, y = p.rng.uniform(0, p.w), p.rng.uniform(0, p.h)
        r = p.rng.uniform(1, 3.4) * p.u
        p.draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 220))


def _space(p: Painter) -> None:
    p.sky((8, 6, 24), (34, 22, 64), until=1.0)
    for colour, x, y, r in (
        ((140, 60, 170), 0.25, 0.3, 0.3),
        ((40, 90, 170), 0.7, 0.2, 0.25),
        ((180, 70, 110), 0.55, 0.45, 0.18),
    ):
        glow(p.canvas, (p.x(x), p.y(y)), p.y(r), colour, 90)
    for _ in range(260):
        x, y = p.rng.uniform(0, p.w), p.rng.uniform(0, p.y(0.75))
        r = p.rng.choice((0.7, 1.0, 1.0, 1.6, 2.4)) * p.u
        p.draw.ellipse(
            (x - r, y - r, x + r, y + r), fill=(255, 255, 255, p.rng.randint(110, 255))
        )
    planet = (p.x(0.78), p.y(0.26))
    r = p.y(0.14)
    p.draw.ellipse(
        (
            planet[0] - r * 1.9,
            planet[1] - r * 0.35,
            planet[0] + r * 1.9,
            planet[1] + r * 0.35,
        ),
        outline=(220, 196, 150),
        width=max(2, round(p.u * 5)),
    )
    blob(
        p.draw,
        (planet[0] - r, planet[1] - r, planet[0] + r, planet[1] + r),
        (226, 150, 96),
        line=p.line,
    )
    for n in range(3):
        p.draw.chord(
            (
                planet[0] - r + 2,
                planet[1] - r * 0.6 + n * r * 0.4,
                planet[0] + r - 2,
                planet[1] - r * 0.3 + n * r * 0.4,
            ),
            0,
            360,
            fill=(196, 120, 80),
        )
    p.draw.chord(
        (planet[0] - r, planet[1] - r, planet[0] + r, planet[1] + r),
        300,
        120,
        fill=(150, 86, 66),
    )
    p.draw.arc(
        (
            planet[0] - r * 1.9,
            planet[1] - r * 0.35,
            planet[0] + r * 1.9,
            planet[1] + r * 0.35,
        ),
        0,
        180,
        fill=(236, 214, 170),
        width=max(2, round(p.u * 5)),
    )
    surface = (150, 146, 156)
    hills(p.draw, p.w, p.y(0.74), p.y(0.03), surface, p.rng, bottom=p.h, bumps=3)
    for _ in range(9):  # Craters.
        x, y = p.rng.uniform(0, p.w), p.rng.uniform(p.y(0.8), p.h)
        r = p.rng.uniform(14, 34) * p.u
        p.draw.ellipse(
            (x - r, y - r * 0.3, x + r, y + r * 0.3),
            fill=darker(surface, 0.25),
            outline=lighter(surface, 0.25),
            width=round(p.line),
        )


def _sky(p: Painter) -> None:
    p.sky((86, 156, 236), (196, 226, 250), until=1.0)
    glow(p.canvas, (p.x(0.8), p.y(0.14)), p.y(0.1), (255, 250, 220), 220)
    p.clouds(7, high=0.7)
    # A long cloud bank to stand on.
    for n in range(14):
        x = p.x(n / 13)
        r = p.y(p.rng.uniform(0.1, 0.16))
        p.draw.ellipse(
            (x - r * 1.4, p.y(0.86) - r, x + r * 1.4, p.y(0.86) + r),
            fill=(214, 224, 244),
        )
    p.draw.rectangle((0, p.y(0.88), p.w, p.h), fill=(214, 224, 244))
    for n in range(14):
        x = p.x(n / 13) + p.x(0.03)
        r = p.y(p.rng.uniform(0.08, 0.12))
        p.draw.ellipse(
            (x - r * 1.3, p.y(0.84) - r, x + r * 1.3, p.y(0.84) + r * 0.6),
            fill=(250, 252, 255),
        )


def _battlefield(p: Painter) -> None:
    p.sky((96, 70, 74), (226, 140, 86))
    glow(p.canvas, (p.x(0.5), p.y(0.55)), p.y(0.2), (255, 170, 90), 140)
    castle = (64, 52, 60)
    base = p.y(0.62)
    p.draw.rectangle((p.x(0.62), base - p.y(0.14), p.x(0.86), base), fill=castle)
    for n in range(4):
        tx = p.x(0.6 + n * 0.08)
        p.draw.rectangle((tx, base - p.y(0.22), tx + p.x(0.035), base), fill=castle)
        for k in range(3):
            p.draw.rectangle(
                (
                    tx + k * p.x(0.013),
                    base - p.y(0.245),
                    tx + k * p.x(0.013) + p.x(0.008),
                    base - p.y(0.22),
                ),
                fill=castle,
            )
    hills(p.draw, p.w, p.y(0.64), p.y(0.04), (92, 70, 64), p.rng, bottom=p.h)
    p.ground((110, 86, 66), (128, 100, 74), start=0.68)
    for n in range(5):  # Smoke rising.
        x = p.x(0.1 + n * 0.2 + p.rng.uniform(-0.04, 0.04))
        for k in range(6):
            r = p.y(0.03 + k * 0.012)
            glow(
                p.canvas,
                (x + k * p.x(0.01), p.y(0.66) - k * p.y(0.06)),
                r,
                (70, 64, 70),
                90 - k * 10,
            )
    for x in (0.18, 0.82):  # Banners on poles.
        pole = (80, 60, 44)
        p.draw.line(
            (p.x(x), p.y(0.88), p.x(x), p.y(0.5)),
            fill=pole,
            width=max(2, round(p.u * 4)),
        )
        flag = (176, 40, 44) if x < 0.5 else (40, 70, 150)
        shape(
            p.draw,
            [
                (p.x(x), p.y(0.5)),
                (p.x(x) + p.x(0.07), p.y(0.52)),
                (p.x(x) + p.x(0.05), p.y(0.56)),
                (p.x(x) + p.x(0.07), p.y(0.6)),
                (p.x(x), p.y(0.6)),
            ],
            flag,
            line=p.line,
        )
    for n in range(8):  # A broken fence.
        x = p.x(0.3 + n * 0.05)
        lean = p.rng.uniform(-0.3, 0.3)
        p.draw.line(
            (x, p.y(0.76), x + lean * p.y(0.05), p.y(0.7)),
            fill=(70, 52, 40),
            width=max(2, round(p.u * 5)),
        )
    p.stones((96, 84, 80), 12)


# ------------------------------------------------------------------ indoors


def _room_shell(
    p: Painter, wall: Colour, floor: Colour, *, boards: bool = True
) -> None:
    p.canvas.paste(
        gradient((p.w, int(p.y(FLOOR)) + 1), lighter(wall, 0.08), darker(wall, 0.08)),
        (0, 0),
    )
    p.canvas.paste(
        gradient((p.w, p.h - int(p.y(FLOOR))), darker(floor, 0.1), floor),
        (0, int(p.y(FLOOR))),
    )
    p.draw.rectangle(
        (0, p.y(FLOOR) - p.y(0.05), p.w, p.y(FLOOR)),
        fill=darker(wall, 0.22),
        outline=ink_of(wall),
        width=round(p.line),
    )
    if boards:
        vanish = p.x(0.5)
        for n in range(-10, 11):  # Floorboards running towards the back wall.
            x_back = vanish + n * p.x(0.06)
            x_front = vanish + n * p.x(0.16)
            p.draw.line(
                (x_back, p.y(FLOOR), x_front, p.h),
                fill=darker(floor, 0.18),
                width=max(1, round(p.u * 1.5)),
            )
        for n in range(1, 6):
            y = p.y(FLOOR) + (p.h - p.y(FLOOR)) * (n / 6) ** 1.5
            p.draw.line(
                (0, y, p.w, y), fill=darker(floor, 0.1), width=max(1, round(p.u))
            )


def _window(
    p: Painter,
    box: tuple[float, float, float, float],
    frame: Colour,
    *,
    night: bool = False,
) -> None:
    p.draw.rectangle(box, fill=frame, outline=ink_of(frame), width=round(p.line))
    inner = (box[0] + 10 * p.u, box[1] + 10 * p.u, box[2] - 10 * p.u, box[3] - 10 * p.u)
    p.canvas.paste(
        gradient(
            (int(inner[2] - inner[0]), int(inner[3] - inner[1])),
            (110, 176, 230) if not night else (20, 30, 70),
            (200, 230, 246) if not night else (60, 60, 110),
        ),
        (int(inner[0]), int(inner[1])),
    )
    p.draw.line(
        ((inner[0] + inner[2]) / 2, inner[1], (inner[0] + inner[2]) / 2, inner[3]),
        fill=frame,
        width=max(2, round(6 * p.u)),
    )
    p.draw.line(
        (inner[0], (inner[1] + inner[3]) / 2, inner[2], (inner[1] + inner[3]) / 2),
        fill=frame,
        width=max(2, round(6 * p.u)),
    )
    p.draw.line(
        (
            inner[0] + 6 * p.u,
            inner[3] - 6 * p.u,
            inner[0] + (inner[2] - inner[0]) * 0.4,
            inner[1] + 6 * p.u,
        ),
        fill=(255, 255, 255, 120),
        width=max(2, round(4 * p.u)),
    )


def _room(p: Painter) -> None:
    wall, floor = (214, 196, 168), (166, 114, 74)
    _room_shell(p, wall, floor)
    for n in range(24):  # Wallpaper stripes.
        x = p.x(n / 24)
        p.draw.rectangle(
            (x, 0, x + p.x(0.012), p.y(FLOOR) - p.y(0.05)),
            fill=(*darker(wall, 0.06), 255),
        )
    _window(p, (p.x(0.12), p.y(0.12), p.x(0.32), p.y(0.46)), (240, 236, 226))
    curtain = (176, 60, 72)
    for side in (-1, 1):
        x = p.x(0.12) if side < 0 else p.x(0.32)
        shape(
            p.draw,
            [
                (x - side * p.x(0.01), p.y(0.08)),
                (x + side * p.x(0.035), p.y(0.08)),
                (x + side * p.x(0.02), p.y(0.5)),
                (x - side * p.x(0.02), p.y(0.52)),
            ],
            curtain,
            line=p.line,
        )
    p.draw.rectangle((p.x(0.1), p.y(0.07), p.x(0.34), p.y(0.085)), fill=(110, 80, 60))
    frame = (150, 104, 54)
    p.draw.rectangle(
        (p.x(0.46), p.y(0.16), p.x(0.58), p.y(0.32)),
        fill=frame,
        outline=ink_of(frame),
        width=round(p.line),
    )
    p.canvas.paste(
        gradient((int(p.x(0.1)), int(p.y(0.13))), (120, 170, 210), (110, 150, 90)),
        (int(p.x(0.47)), int(p.y(0.175))),
    )
    # A bookshelf with books.
    shelf = (120, 82, 52)
    box = (p.x(0.74), p.y(0.18), p.x(0.94), p.y(FLOOR))
    p.draw.rectangle(box, fill=shelf, outline=ink_of(shelf), width=round(p.line))
    for row in range(4):
        y_top = box[1] + (box[3] - box[1]) * row / 4 + 6 * p.u
        y_bottom = box[1] + (box[3] - box[1]) * (row + 1) / 4
        p.draw.rectangle(
            (box[0] + 6 * p.u, y_bottom - 6 * p.u, box[2] - 6 * p.u, y_bottom),
            fill=darker(shelf, 0.2),
        )
        x = box[0] + 8 * p.u
        while x < box[2] - 18 * p.u:
            bw = p.rng.uniform(8, 16) * p.u
            bh = (y_bottom - y_top) * p.rng.uniform(0.6, 0.9)
            colour = p.rng.choice(
                (
                    (170, 50, 50),
                    (50, 90, 150),
                    (60, 130, 80),
                    (210, 170, 60),
                    (110, 70, 140),
                )
            )
            p.draw.rectangle(
                (x, y_bottom - 6 * p.u - bh, x + bw, y_bottom - 6 * p.u),
                fill=colour,
                outline=ink_of(colour),
            )
            x += bw + p.u
    rug = (150, 60, 66)
    p.draw.ellipse(
        (p.x(0.25), p.y(0.8), p.x(0.75), p.y(0.98)),
        fill=rug,
        outline=ink_of(rug),
        width=round(p.line),
    )
    p.draw.ellipse(
        (p.x(0.3), p.y(0.83), p.x(0.7), p.y(0.95)),
        outline=(226, 186, 110),
        width=max(2, round(p.u * 3)),
    )


def _classroom(p: Painter) -> None:
    wall, floor = (210, 222, 196), (176, 136, 96)
    _room_shell(p, wall, floor)
    board = (46, 92, 70)
    box = (p.x(0.3), p.y(0.12), p.x(0.7), p.y(0.46))
    p.draw.rectangle(
        (box[0] - 10 * p.u, box[1] - 10 * p.u, box[2] + 10 * p.u, box[3] + 10 * p.u),
        fill=(150, 104, 60),
        outline=ink_of((150, 104, 60)),
        width=round(p.line),
    )
    p.draw.rectangle(box, fill=board)
    chalk = (236, 240, 230)
    from PIL import ImageFont

    p.draw.text(
        (box[0] + 24 * p.u, box[1] + 16 * p.u),
        "A B C   1 + 2 = 3",
        fill=chalk,
        font=ImageFont.load_default(size=round(34 * p.u)),
    )
    for n in range(4):  # Chalk scribbles.
        y = box[1] + p.y(0.1 + n * 0.06)
        p.draw.line(
            (
                box[0] + 24 * p.u,
                y,
                box[0] + p.x(0.1 + 0.05 * (n % 3)),
                y + p.rng.uniform(-3, 3) * p.u,
            ),
            fill=chalk,
            width=max(1, round(p.u * 2)),
        )
    p.draw.ellipse(
        (box[2] - p.x(0.1), box[1] + p.y(0.08), box[2] - p.x(0.04), box[1] + p.y(0.2)),
        outline=chalk,
        width=max(1, round(p.u * 2)),
    )
    letters = ((220, 80, 80), (80, 140, 220), (240, 190, 60), (90, 170, 100))
    for n in range(14):  # An alphabet strip above.
        x = p.x(0.06 + n * 0.065)
        colour = letters[n % 4]
        p.draw.rectangle(
            (x, p.y(0.03), x + p.x(0.05), p.y(0.08)),
            fill=colour,
            outline=ink_of(colour),
        )
    _window(p, (p.x(0.04), p.y(0.16), p.x(0.2), p.y(0.42)), (240, 236, 226))
    clock = (p.x(0.84), p.y(0.2))
    blob(
        p.draw,
        (
            clock[0] - 30 * p.u,
            clock[1] - 30 * p.u,
            clock[0] + 30 * p.u,
            clock[1] + 30 * p.u,
        ),
        (250, 248, 240),
        line=p.line * 1.5,
    )
    p.draw.line(
        (clock[0], clock[1], clock[0], clock[1] - 20 * p.u),
        fill=(30, 30, 30),
        width=max(2, round(p.u * 3)),
    )
    p.draw.line(
        (clock[0], clock[1], clock[0] + 14 * p.u, clock[1] + 6 * p.u),
        fill=(30, 30, 30),
        width=max(2, round(p.u * 3)),
    )
    desk = (196, 150, 96)
    for x in (0.08, 0.92):  # Desks at the sides, out of the middle.
        top = (p.x(x) - p.x(0.07), p.y(0.74), p.x(x) + p.x(0.07), p.y(0.78))
        shape(
            p.draw,
            [(top[0], top[1]), (top[2], top[1]), (top[2], top[3]), (top[0], top[3])],
            desk,
            line=p.line,
        )
        for leg in (top[0] + 8 * p.u, top[2] - 12 * p.u):
            p.draw.rectangle(
                (leg, top[3], leg + 6 * p.u, p.y(0.9)),
                fill=(90, 90, 100),
                outline=(50, 50, 60),
            )


def _hut(p: Painter) -> None:
    wall, floor = (176, 122, 80), (140, 96, 62)
    _room_shell(p, wall, floor, boards=False)
    for _ in range(90):  # Mud texture.
        x, y = p.rng.uniform(0, p.w), p.rng.uniform(0, p.y(FLOOR) - p.y(0.06))
        r = p.rng.uniform(4, 14) * p.u
        p.draw.ellipse(
            (x - r, y - r * 0.6, x + r, y + r * 0.6),
            fill=(*p.rng.choice((darker(wall, 0.08), lighter(wall, 0.08))), 160),
        )
    beam = (98, 66, 42)
    for n in range(4):  # Roof beams and straw above.
        y = p.y(0.02 + n * 0.045)
        p.draw.rectangle((0, y, p.w, y + p.y(0.02)), fill=beam, outline=ink_of(beam))
    for _ in range(120):
        x = p.rng.uniform(0, p.w)
        p.draw.line(
            (x, 0, x + p.rng.uniform(-10, 10) * p.u, p.y(0.18)),
            fill=(196, 160, 90, 150),
            width=max(1, round(p.u)),
        )
    door = (p.x(0.06), p.y(0.24), p.x(0.2), p.y(FLOOR))
    p.canvas.paste(
        gradient(
            (int(door[2] - door[0]), int(door[3] - door[1])),
            (250, 220, 160),
            (226, 186, 120),
        ),
        (int(door[0]), int(door[1])),
    )
    p.draw.rectangle(door, outline=ink_of(wall), width=round(p.line * 1.5))
    for x, s, colour in (
        (0.78, 1.0, (166, 86, 50)),
        (0.86, 0.75, (190, 110, 64)),
        (0.92, 0.6, (150, 80, 50)),
    ):  # Clay pots.
        cx, cy, r = p.x(x), p.y(FLOOR + 0.02), p.y(0.08 * s)
        blob(p.draw, (cx - r, cy - r * 1.6, cx + r, cy), colour, line=p.line)
        p.draw.arc(
            (cx - r * 0.7, cy - r * 1.4, cx, cy - r * 0.4),
            180,
            260,
            fill=lighter(colour, 0.35),
            width=max(1, round(p.line)),
        )
    mat = (206, 170, 96)
    p.draw.polygon(
        [
            (p.x(0.3), p.y(0.78)),
            (p.x(0.7), p.y(0.78)),
            (p.x(0.76), p.y(0.95)),
            (p.x(0.24), p.y(0.95)),
        ],
        fill=mat,
        outline=ink_of(mat),
    )
    for n in range(8):
        y = p.y(0.78 + n * 0.021)
        p.draw.line(
            (p.x(0.3) - n * p.x(0.0075), y, p.x(0.7) + n * p.x(0.0075), y),
            fill=darker(mat, 0.2),
            width=max(1, round(p.u)),
        )
    # A cooking fire glowing in the corner.
    fire = (p.x(0.62), p.y(FLOOR + 0.01))
    glow(p.canvas, (fire[0], fire[1] - p.y(0.06)), p.y(0.12), (255, 160, 70), 130)
    for dx, h, colour in (
        (-0.012, 0.1, (238, 92, 40)),
        (0.01, 0.12, (250, 160, 50)),
        (0.0, 0.07, (255, 230, 120)),
    ):
        x = fire[0] + p.x(dx)
        p.draw.polygon(
            [
                (x - p.x(0.018), fire[1]),
                (x, fire[1] - p.y(h)),
                (x + p.x(0.018), fire[1]),
            ],
            fill=colour,
        )
    for side in (-1, 1):
        p.draw.line(
            (
                fire[0] - side * p.x(0.03),
                fire[1] + 4 * p.u,
                fire[0] + side * p.x(0.03),
                fire[1] - 4 * p.u,
            ),
            fill=(80, 50, 30),
            width=max(2, round(p.u * 6)),
        )


def _palace(p: Painter) -> None:
    wall, floor = (150, 72, 80), (210, 196, 176)
    _room_shell(p, wall, floor, boards=False)
    # A marble floor of tiles running back, and a red carpet up the middle.
    for n in range(-14, 15):
        p.draw.line(
            (p.x(0.5) + n * p.x(0.05), p.y(FLOOR), p.x(0.5) + n * p.x(0.15), p.h),
            fill=darker(floor, 0.18),
            width=max(1, round(p.u * 1.5)),
        )
    for n in range(1, 7):
        y = p.y(FLOOR) + (p.h - p.y(FLOOR)) * (n / 7) ** 1.5
        p.draw.line(
            (0, y, p.w, y), fill=darker(floor, 0.14), width=max(1, round(p.u * 1.5))
        )
    carpet = (176, 30, 44)
    p.draw.polygon(
        [
            (p.x(0.44), p.y(FLOOR)),
            (p.x(0.56), p.y(FLOOR)),
            (p.x(0.66), p.h),
            (p.x(0.34), p.h),
        ],
        fill=carpet,
    )
    for side in (0.445, 0.555):
        p.draw.line(
            (p.x(side), p.y(FLOOR), p.x(0.5 + (side - 0.5) * 3.0), p.h),
            fill=(226, 180, 60),
            width=max(2, round(p.u * 3)),
        )
    # Arches in the back wall.
    for n in range(3):
        cx = p.x(0.2 + n * 0.3)
        arch = (cx - p.x(0.07), p.y(0.16), cx + p.x(0.07), p.y(FLOOR) - p.y(0.05))
        p.draw.rectangle(
            (arch[0], arch[1] + p.y(0.07), arch[2], arch[3]), fill=darker(wall, 0.35)
        )
        p.draw.ellipse(
            (arch[0], arch[1], arch[2], arch[1] + p.y(0.14)), fill=darker(wall, 0.35)
        )
        p.draw.arc(
            (arch[0], arch[1], arch[2], arch[1] + p.y(0.14)),
            180,
            360,
            fill=(226, 186, 90),
            width=max(2, round(p.u * 4)),
        )
    # Columns: a shaft with fluting, a capital and a base, shaded on the right.
    stone = (232, 220, 196)
    for x in (0.05, 0.35, 0.65, 0.95):
        cx = p.x(x)
        half = p.x(0.022)
        shaft = (cx - half, p.y(0.08), cx + half, p.y(FLOOR) - p.y(0.02))
        p.draw.rectangle(shaft, fill=stone, outline=ink_of(stone), width=round(p.line))
        p.draw.rectangle(
            (cx + half * 0.3, shaft[1], cx + half, shaft[3]), fill=darker(stone, 0.18)
        )
        for k in (-0.5, 0.0, 0.5):
            p.draw.line(
                (cx + k * half, shaft[1] + 6 * p.u, cx + k * half, shaft[3] - 6 * p.u),
                fill=darker(stone, 0.25),
                width=max(1, round(p.u)),
            )
        for y0, grow in ((0.05, 1.6), (FLOOR - 0.04, 1.5)):
            p.draw.rectangle(
                (cx - half * grow, p.y(y0), cx + half * grow, p.y(y0 + 0.035)),
                fill=stone,
                outline=ink_of(stone),
                width=round(p.line),
            )
    # Banners hanging between the columns.
    for x in (0.2, 0.8):
        cx = p.x(x)
        banner = (226, 176, 52)
        shape(
            p.draw,
            [
                (cx - p.x(0.03), p.y(0.04)),
                (cx + p.x(0.03), p.y(0.04)),
                (cx + p.x(0.03), p.y(0.26)),
                (cx, p.y(0.22)),
                (cx - p.x(0.03), p.y(0.26)),
            ],
            banner,
            line=p.line,
        )
        p.draw.ellipse(
            (cx - p.x(0.012), p.y(0.1), cx + p.x(0.012), p.y(0.14)), fill=(176, 30, 44)
        )
    # The throne on its steps, at the back in the middle.
    gold = (226, 176, 52)
    cx = p.x(0.5)
    for n, half in enumerate((0.1, 0.08, 0.06)):
        y = p.y(FLOOR) - p.y(0.02) * n
        p.draw.rectangle(
            (cx - p.x(half), y - p.y(0.02), cx + p.x(half), y),
            fill=lighter(floor, 0.1),
            outline=ink_of(floor),
        )
    back = (cx - p.x(0.04), p.y(0.3), cx + p.x(0.04), p.y(FLOOR) - p.y(0.06))
    shape(
        p.draw,
        [
            (back[0], back[3]),
            (back[0], back[1] + p.y(0.04)),
            (cx, back[1]),
            (back[2], back[1] + p.y(0.04)),
            (back[2], back[3]),
        ],
        gold,
        line=p.line,
    )
    p.draw.rectangle(
        (
            back[0] + p.x(0.01),
            back[1] + p.y(0.06),
            back[2] - p.x(0.01),
            back[3] - p.y(0.06),
        ),
        fill=carpet,
    )
    # Torches with their glow.
    for x in (0.12, 0.88):
        tx, ty = p.x(x), p.y(0.36)
        glow(p.canvas, (tx, ty - p.y(0.03)), p.y(0.07), (255, 170, 80), 140)
        p.draw.polygon(
            [(tx - p.x(0.008), ty), (tx, ty - p.y(0.06)), (tx + p.x(0.008), ty)],
            fill=(255, 190, 70),
        )
        p.draw.rectangle(
            (tx - p.x(0.004), ty, tx + p.x(0.004), ty + p.y(0.06)), fill=(90, 60, 40)
        )


PAINTERS: dict[str, Callable[[Painter], None]] = {
    "savanna": _savanna,
    "desert": _desert,
    "forest": _forest,
    "village": _village,
    "city": _city,
    "street": _street,
    "night": _night,
    "beach": _beach,
    "snow": _snow,
    "space": _space,
    "sky": _sky,
    "battlefield": _battlefield,
    "room": _room,
    "classroom": _classroom,
    "hut": _hut,
    "palace": _palace,
}


def paint_place(key: str, width: int, height: int, seed: int = 0) -> Any:
    """A place painted at width x height (RGB)."""
    from PIL import Image, ImageChops, ImageDraw

    big = 2 if width <= 2000 else 1
    canvas = Image.new("RGB", (width * big, height * big), (200, 200, 200))
    painter = Painter(canvas, random.Random(f"{key}{seed}"))
    PAINTERS.get(key, _hut)(painter)
    picture = canvas.reduce(big) if big > 1 else canvas
    # A fine paper grain, and a soft darkening towards the edges.
    grain = noise(picture.size, seed + len(key), strength=7)
    picture = ImageChops.overlay(picture, Image.merge("RGB", (grain, grain, grain)))
    edge = Image.new("L", picture.size, 0)
    ImageDraw.Draw(edge).ellipse(
        (
            -picture.width * 0.15,
            -picture.height * 0.2,
            picture.width * 1.15,
            picture.height * 1.25,
        ),
        fill=255,
    )
    from PIL import ImageFilter

    edge = edge.filter(ImageFilter.GaussianBlur(picture.height * 0.12))
    shadow = Image.new("RGB", picture.size, (20, 16, 26))
    return Image.composite(picture, shadow, edge.point(lambda v: 150 + v * 105 // 255))
