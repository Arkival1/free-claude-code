"""Cartoon heads: drawn from a character's look, or cut from a picture.

A drawn head is a big face with white eyes that look around, eyebrows and
eyelids that show the feeling, a mouth that opens with the words, and hair
or headwear (a wrap, a crown, a cap...). A picture (a drawing, a photo, a
character from a show) has its plain background cut away from the corners
in; it bobs and tilts when its character talks. Heads are drawn at twice
the size and shrunk, so their lines are smooth, and kept for reuse.
"""

import functools
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FEELINGS = ("neutral", "happy", "sad", "angry", "surprised", "scared", "smug")
HAIR = ("short", "afro", "long", "bald", "bun", "braids", "spiky", "curly")
WEAR = ("none", "wrap", "crown", "turban", "cap", "hood", "helmet", "headband", "hat")
AGES = ("kid", "adult", "old")
IRISES = ((92, 58, 32), (70, 44, 26), (58, 98, 140), (76, 110, 64), (120, 84, 40))
SKINS = ("#f2c9a0", "#e0ac7e", "#c68a5a", "#9b6a43", "#7a4f30", "#5a3a22")
HAIR_COLOURS = (
    "#1d1a18",
    "#3b2416",
    "#6b3f1f",
    "#b8742e",
    "#d9b25f",
    "#9a9a9a",
    "#e7e2d8",
)
WEAR_COLOURS = (
    "#3fa9f5",
    "#e94b6a",
    "#f2c037",
    "#4caf50",
    "#8e5bd8",
    "#ffffff",
    "#ff8a3d",
)


def colour(
    value: str, default: tuple[int, int, int] = (200, 160, 120)
) -> tuple[int, int, int]:
    text = (value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError, IndexError:
        return default


def shade(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    """Darker below 1, lighter above."""
    red, green, blue = rgb
    if amount <= 1:
        return (
            max(0, int(red * amount)),
            max(0, int(green * amount)),
            max(0, int(blue * amount)),
        )
    lift = amount - 1
    return (
        min(255, int(red + (255 - red) * lift)),
        min(255, int(green + (255 - green) * lift)),
        min(255, int(blue + (255 - blue) * lift)),
    )


@dataclass(frozen=True, slots=True)
class Look:
    """How a character looks. Any field left out is chosen from the name."""

    name: str
    skin: str = ""
    hair: str = ""
    hair_colour: str = ""
    wear: str = ""
    wear_colour: str = ""
    age: str = "adult"
    beard: bool = False
    earrings: bool = False
    glasses: bool = False
    head_image: Path | None = field(default=None, compare=False)
    sprites: Any = field(default=None, compare=False)
    """Painted cut-out pictures (an aiart.Sprites) drawn instead of a body."""

    def filled(self) -> Look:
        """Every blank chosen from the name, so a character always looks the same."""
        rng = random.Random(self.name.lower())
        return Look(
            name=self.name,
            skin=self.skin or rng.choice(SKINS),
            hair=self.hair if self.hair in HAIR else rng.choice(HAIR[:5]),
            hair_colour=self.hair_colour or rng.choice(HAIR_COLOURS[:5]),
            wear=self.wear if self.wear in WEAR else "none",
            wear_colour=self.wear_colour or rng.choice(WEAR_COLOURS),
            age=self.age if self.age in AGES else "adult",
            beard=self.beard,
            earrings=self.earrings,
            glasses=self.glasses,
            head_image=self.head_image,
            sprites=self.sprites,
        )


SCALE = 2
"""Heads are drawn this many times bigger, then shrunk smooth."""


def head(
    look: Look,
    height: int,
    *,
    feeling: str = "neutral",
    mouth: float = 0.0,
    gaze: float = 0.0,
    blink: bool = False,
) -> Any:
    """A head image (RGBA), `height` pixels tall, facing right."""
    filled = look.filled()
    mouth_step = round(max(0.0, min(1.0, mouth)) * 3) / 3
    gaze_step = round(max(-1.0, min(1.0, gaze)) * 2) / 2
    if filled.head_image is not None:
        return _picture_head(str(filled.head_image), height)
    return _drawn_head(
        filled,
        height,
        feeling if feeling in FEELINGS else "neutral",
        mouth_step,
        gaze_step,
        blink,
    )


@functools.lru_cache(maxsize=512)
def _drawn_head(
    look: Look, height: int, feeling: str, mouth: float, gaze: float, blink: bool
) -> Any:
    from PIL import Image, ImageDraw

    big = height * SCALE
    width = int(big * 0.92)
    canvas = Image.new("RGBA", (int(width * 1.5), int(big * 1.35)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    cx = canvas.width / 2
    top = big * 0.3
    kid = look.age == "kid"
    old = look.age == "old"
    face_w = width * (0.86 if kid else 0.8)
    face_h = big * (0.86 if kid else 0.9)
    left, right = cx - face_w / 2, cx + face_w / 2
    bottom = top + face_h
    skin = colour(look.skin)
    line = shade(skin, 0.45)
    stroke = max(2, big // 52)
    hair = colour(look.hair_colour, (40, 30, 25))
    wear = colour(look.wear_colour, (60, 160, 240))
    iris = random.Random(f"eyes{look.name.lower()}").choice(IRISES)

    # Hair behind the face.
    if look.hair == "afro":
        draw.ellipse(
            (
                left - face_w * 0.18,
                top - face_h * 0.28,
                right + face_w * 0.18,
                top + face_h * 0.62,
            ),
            fill=hair,
        )
    elif look.hair == "long":
        draw.rounded_rectangle(
            (
                left - face_w * 0.08,
                top + face_h * 0.05,
                right + face_w * 0.08,
                bottom + face_h * 0.18,
            ),
            radius=int(face_w * 0.3),
            fill=hair,
        )
    elif look.hair == "braids":
        for side in (left - face_w * 0.04, right - face_w * 0.06):
            for row in range(5):
                y = top + face_h * (0.25 + row * 0.15)
                draw.ellipse(
                    (side, y, side + face_w * 0.1, y + face_h * 0.14),
                    fill=hair,
                    outline=shade(hair, 0.6),
                )
    # Ears.
    ear_y = top + face_h * 0.42
    for x in (left - face_w * 0.05, right - face_w * 0.07):
        draw.ellipse(
            (x, ear_y, x + face_w * 0.12, ear_y + face_h * 0.18),
            fill=skin,
            outline=line,
            width=stroke,
        )
    if look.earrings:
        for x in (left - face_w * 0.02, right - face_w * 0.04):
            draw.ellipse(
                (x, ear_y + face_h * 0.16, x + face_w * 0.08, ear_y + face_h * 0.27),
                outline=(230, 180, 40),
                width=stroke * 2,
            )
    # The face, lit from the front-right: shade on the far side and under the
    # chin, a soft shine on the forehead, warm cheeks.
    draw.ellipse((left, top, right, bottom), fill=skin, outline=line, width=stroke)
    _light_face(canvas, (left, top, right, bottom), skin, blush=not look.beard)
    draw.ellipse((left, top, right, bottom), outline=line, width=stroke)
    for x in (left - face_w * 0.05, right - face_w * 0.07):
        draw.arc(
            (
                x + face_w * 0.03,
                ear_y + face_h * 0.04,
                x + face_w * 0.09,
                ear_y + face_h * 0.14,
            ),
            90,
            270 if x < cx else 450,
            fill=shade(skin, 0.7),
            width=stroke,
        )
    if look.beard:
        beard_colour = (200, 200, 200) if old else hair
        draw.chord(
            (
                left + face_w * 0.06,
                top + face_h * 0.45,
                right - face_w * 0.06,
                bottom + face_h * 0.06,
            ),
            0,
            180,
            fill=beard_colour,
        )
    # Eyes.
    eye_y = top + face_h * (0.42 if kid else 0.4)
    eye_w = face_w * (0.25 if kid else 0.22)
    eye_h = face_h * (0.2 if kid else 0.15)
    if feeling in {"surprised", "scared"}:
        eye_h *= 1.3
    gaps = (cx - face_w * 0.27, cx + face_w * 0.05)
    for number, x in enumerate(gaps):
        box = (x, eye_y, x + eye_w, eye_y + eye_h)
        if blink:
            draw.line(
                (box[0], eye_y + eye_h / 2, box[2], eye_y + eye_h / 2),
                fill=line,
                width=stroke,
            )
            continue
        draw.ellipse(box, fill=(255, 255, 255), outline=(20, 20, 20), width=stroke)
        pupil = eye_h * (0.62 if feeling != "scared" else 0.4)
        px = x + eye_w / 2 + gaze * eye_w * 0.2 - pupil / 2
        py = eye_y + eye_h / 2 - pupil / 2 + (eye_h * 0.08 if feeling == "sad" else 0)
        # A coloured iris, a dark pupil, and two catch-lights.
        draw.ellipse(
            (px, py, px + pupil, py + pupil),
            fill=iris,
            outline=shade(iris, 0.45),
            width=max(1, stroke // 2),
        )
        core = pupil * 0.5
        cxp, cyp = px + pupil / 2, py + pupil / 2
        draw.ellipse(
            (cxp - core / 2, cyp - core / 2, cxp + core / 2, cyp + core / 2),
            fill=(12, 10, 12),
        )
        draw.ellipse(
            (px + pupil * 0.18, py + pupil * 0.12, px + pupil * 0.46, py + pupil * 0.4),
            fill=(255, 255, 255),
        )
        draw.ellipse(
            (px + pupil * 0.6, py + pupil * 0.6, px + pupil * 0.74, py + pupil * 0.74),
            fill=(255, 255, 255),
        )
        # Lids: heavy when sad, sleepy when old or smug, low and angled when angry.
        lid = {"sad": 0.38, "smug": 0.45, "angry": 0.3}.get(
            feeling, 0.22 if old else 0.0
        )
        if lid:
            draw.chord(
                (box[0] - 2, box[1] - 2, box[2] + 2, box[3] + eye_h * 0.1),
                180,
                360,
                fill=skin,
            )
            draw.rectangle(
                (box[0] - 2, box[1] - 2, box[2] + 2, box[1] + eye_h * lid), fill=skin
            )
            draw.line(
                (box[0], box[1] + eye_h * lid, box[2], box[1] + eye_h * lid),
                fill=line,
                width=stroke,
            )
        # Brows.
        brow_y = eye_y - eye_h * 0.45
        inner, outer = (box[2], box[0]) if number == 0 else (box[0], box[2])
        tilt = {"angry": 0.35, "sad": -0.35, "scared": -0.3, "surprised": -0.15}.get(
            feeling, 0.0
        )
        draw.line(
            (outer, brow_y, inner, brow_y + eye_h * tilt),
            fill=shade(hair, 0.8),
            width=stroke * 3,
        )
    if look.glasses:
        for x in gaps:
            draw.rounded_rectangle(
                (x - 4, eye_y - 4, x + eye_w + 4, eye_y + eye_h + 4),
                radius=8,
                outline=(30, 30, 30),
                width=stroke * 2,
            )
        draw.line(
            (gaps[0] + eye_w + 4, eye_y + eye_h / 2, gaps[1] - 4, eye_y + eye_h / 2),
            fill=(30, 30, 30),
            width=stroke * 2,
        )
    # Nose: a big, rounded caricature nose with a nostril.
    nose_y = eye_y + eye_h * 1.25
    draw.ellipse(
        (
            cx - face_w * 0.01,
            nose_y - face_h * 0.03,
            cx + face_w * 0.19,
            nose_y + face_h * 0.12,
        ),
        fill=shade(skin, 0.9),
    )
    draw.ellipse(
        (
            cx + face_w * 0.07,
            nose_y + face_h * 0.06,
            cx + face_w * 0.12,
            nose_y + face_h * 0.095,
        ),
        fill=shade(skin, 0.5),
    )
    draw.arc(
        (
            cx + face_w * 0.02,
            nose_y - face_h * 0.04,
            cx + face_w * 0.16,
            nose_y + face_h * 0.1,
        ),
        300,
        120,
        fill=line,
        width=stroke,
    )
    if old:
        for row in range(3):
            y = top + face_h * (0.18 + row * 0.05)
            draw.arc(
                (cx - face_w * 0.2, y, cx + face_w * 0.2, y + face_h * 0.08),
                200,
                340,
                fill=shade(skin, 0.7),
                width=stroke,
            )
        for x in gaps:
            draw.arc(
                (x, eye_y + eye_h * 0.9, x + eye_w, eye_y + eye_h * 1.5),
                20,
                160,
                fill=shade(skin, 0.7),
                width=stroke,
            )
    # Mouth.
    mouth_x = cx + face_w * 0.02
    mouth_y = top + face_h * (0.74 if kid else 0.72)
    mouth_w = face_w * 0.32
    if mouth > 0:
        opening = face_h * (0.05 + 0.13 * mouth)
        box = (
            mouth_x - mouth_w / 2,
            mouth_y - opening / 3,
            mouth_x + mouth_w / 2,
            mouth_y + opening,
        )
        draw.ellipse(box, fill=(70, 15, 20), outline=line, width=stroke)
        draw.chord(
            (
                box[0] + mouth_w * 0.2,
                box[1] + opening * 0.6,
                box[2] - mouth_w * 0.2,
                box[3] + opening * 0.2,
            ),
            180,
            360,
            fill=(220, 90, 100),
        )
        draw.rectangle(
            (
                box[0] + mouth_w * 0.2,
                box[1] + 2,
                box[2] - mouth_w * 0.2,
                box[1] + opening * 0.2,
            ),
            fill=(255, 255, 255),
        )
    elif feeling in {"happy", "smug"}:
        draw.chord(
            (
                mouth_x - mouth_w / 2,
                mouth_y - face_h * 0.06,
                mouth_x + mouth_w / 2,
                mouth_y + face_h * 0.08,
            ),
            0,
            180,
            fill=(255, 255, 255),
            outline=line,
            width=stroke,
        )
    elif feeling in {"sad", "scared"}:
        draw.arc(
            (
                mouth_x - mouth_w / 2.5,
                mouth_y,
                mouth_x + mouth_w / 2.5,
                mouth_y + face_h * 0.1,
            ),
            200,
            340,
            fill=line,
            width=stroke * 2,
        )
    elif feeling == "surprised":
        draw.ellipse(
            (
                mouth_x - mouth_w / 5,
                mouth_y - face_h * 0.02,
                mouth_x + mouth_w / 5,
                mouth_y + face_h * 0.08,
            ),
            fill=(70, 15, 20),
            outline=line,
            width=stroke,
        )
    elif feeling == "angry":
        draw.line(
            (
                mouth_x - mouth_w / 2.5,
                mouth_y + face_h * 0.03,
                mouth_x + mouth_w / 2.5,
                mouth_y + face_h * 0.01,
            ),
            fill=line,
            width=stroke * 2,
        )
    else:
        draw.arc(
            (
                mouth_x - mouth_w / 2.5,
                mouth_y - face_h * 0.06,
                mouth_x + mouth_w / 2.5,
                mouth_y + face_h * 0.04,
            ),
            20,
            160,
            fill=line,
            width=stroke * 2,
        )
    # Hair on top, or headwear.
    _top_of_head(draw, look, left, right, top, face_w, face_h, hair, wear, stroke)
    small = canvas.resize(
        (canvas.width // SCALE, canvas.height // SCALE), Image.Resampling.LANCZOS
    )
    return small.crop(small.getbbox() or (0, 0, small.width, small.height))


def _light_face(
    canvas: Any,
    box: tuple[float, float, float, float],
    skin: tuple[int, int, int],
    *,
    blush: bool,
) -> None:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    left, top, right, bottom = box
    w, h = right - left, bottom - top
    face = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(face).ellipse(box, fill=255)

    def wash(
        colour: tuple[int, int, int],
        shapes: list[tuple[float, float, float, float]],
        strength: int,
        blur: float,
    ) -> None:
        mask = Image.new("L", canvas.size, 0)
        draw = ImageDraw.Draw(mask)
        for shape in shapes:
            draw.ellipse(shape, fill=strength)
        mask = ImageChops.multiply(mask.filter(ImageFilter.GaussianBlur(blur)), face)
        canvas.paste(Image.new("RGBA", canvas.size, (*colour, 255)), (0, 0), mask)

    wash(
        shade(skin, 0.72),
        [
            (left - w * 0.5, top - h * 0.1, left + w * 0.38, bottom + h * 0.1),
            (left, bottom - h * 0.16, right, bottom + h * 0.3),
        ],
        130,
        w * 0.07,
    )
    wash(
        shade(skin, 1.3),
        [(left + w * 0.52, top + h * 0.07, left + w * 0.86, top + h * 0.3)],
        90,
        w * 0.05,
    )
    if blush:
        wash(
            (225, 120, 110),
            [
                (left + w * 0.12, top + h * 0.56, left + w * 0.32, top + h * 0.68),
                (left + w * 0.68, top + h * 0.56, left + w * 0.88, top + h * 0.68),
            ],
            70,
            w * 0.03,
        )


def _top_of_head(
    draw: Any,
    look: Look,
    left: float,
    right: float,
    top: float,
    w: float,
    h: float,
    hair: tuple[int, int, int],
    wear: tuple[int, int, int],
    stroke: int,
) -> None:
    cx = (left + right) / 2
    outline = shade(wear, 0.55)
    if look.wear == "wrap":
        draw.chord(
            (left - w * 0.05, top - h * 0.25, right + w * 0.05, top + h * 0.5),
            180,
            360,
            fill=wear,
            outline=outline,
            width=stroke,
        )
        draw.ellipse(
            (cx - w * 0.3, top - h * 0.38, cx + w * 0.35, top + h * 0.05),
            fill=wear,
            outline=outline,
            width=stroke,
        )
        rng = random.Random(look.name)
        light = shade(wear, 1.5)
        for _ in range(14):
            x = rng.uniform(left + w * 0.05, right - w * 0.05)
            y = rng.uniform(top - h * 0.3, top + h * 0.12)
            r = w * 0.03
            draw.ellipse((x - r, y - r, x + r, y + r), fill=light)
    elif look.wear == "crown":
        cloth = (245, 242, 235)
        draw.chord(
            (left - w * 0.06, top - h * 0.12, right + w * 0.06, top + h * 0.55),
            180,
            360,
            fill=cloth,
            outline=(170, 160, 150),
            width=stroke,
        )
        draw.rectangle(
            (left - w * 0.06, top + h * 0.2, left + w * 0.06, top + h * 0.95),
            fill=cloth,
        )
        draw.rectangle(
            (right - w * 0.06, top + h * 0.2, right + w * 0.06, top + h * 0.95),
            fill=cloth,
        )
        gold = (236, 184, 40)
        base_y = top + h * 0.02
        draw.rectangle(
            (left + w * 0.1, base_y, right - w * 0.1, base_y + h * 0.1),
            fill=gold,
            outline=shade(gold, 0.6),
            width=stroke,
        )
        for n in range(5):
            x = left + w * 0.1 + n * (w * 0.8 - w * 0.0) / 4.4
            draw.polygon(
                [
                    (x, base_y),
                    (x + w * 0.09, base_y - h * 0.16),
                    (x + w * 0.18, base_y),
                ],
                fill=gold,
                outline=shade(gold, 0.6),
            )
    elif look.wear == "turban":
        draw.ellipse(
            (left - w * 0.06, top - h * 0.32, right + w * 0.06, top + h * 0.32),
            fill=wear,
            outline=outline,
            width=stroke,
        )
        for n in range(3):
            draw.arc(
                (
                    left,
                    top - h * 0.25 + n * h * 0.12,
                    right,
                    top + h * 0.2 + n * h * 0.12,
                ),
                190,
                350,
                fill=outline,
                width=stroke,
            )
    elif look.wear == "cap":
        draw.chord(
            (left, top - h * 0.12, right, top + h * 0.45),
            180,
            360,
            fill=wear,
            outline=outline,
            width=stroke,
        )
        draw.ellipse(
            (cx, top + h * 0.12, right + w * 0.35, top + h * 0.24),
            fill=shade(wear, 0.8),
            outline=outline,
            width=stroke,
        )
    elif look.wear == "hood":
        draw.chord(
            (left - w * 0.12, top - h * 0.12, right + w * 0.12, top + h * 1.1),
            160,
            380,
            fill=wear,
            outline=outline,
            width=stroke * 2,
        )
    elif look.wear == "helmet":
        metal = (170, 175, 185)
        draw.chord(
            (left - w * 0.04, top - h * 0.1, right + w * 0.04, top + h * 0.6),
            180,
            360,
            fill=metal,
            outline=(90, 95, 105),
            width=stroke,
        )
        draw.rectangle((cx - w * 0.04, top - h * 0.24, cx + w * 0.04, top), fill=wear)
    elif look.wear == "headband":
        _hair_top(draw, look, left, right, top, w, h, hair, stroke)
        draw.rectangle(
            (left + w * 0.02, top + h * 0.12, right - w * 0.02, top + h * 0.2),
            fill=wear,
        )
    elif look.wear == "hat":
        draw.rectangle(
            (left + w * 0.12, top - h * 0.35, right - w * 0.12, top + h * 0.08),
            fill=wear,
            outline=outline,
            width=stroke,
        )
        draw.ellipse(
            (left - w * 0.2, top + h * 0.02, right + w * 0.2, top + h * 0.16),
            fill=wear,
            outline=outline,
            width=stroke,
        )
    else:
        _hair_top(draw, look, left, right, top, w, h, hair, stroke)


def _hair_top(
    draw: Any,
    look: Look,
    left: float,
    right: float,
    top: float,
    w: float,
    h: float,
    hair: tuple[int, int, int],
    stroke: int,
) -> None:
    """Hair on top of the head: a shape that follows the skull, inked round,
    with strands and a shine where the light catches it."""
    cx = (left + right) / 2
    ink = shade(hair, 0.45) if sum(hair) > 120 else (8, 6, 6)
    lit = shade(hair, 1.45) if sum(hair) > 90 else (86, 80, 92)
    rng = random.Random(f"hair{look.name}")
    if look.hair == "bald":
        draw.arc(
            (left + w * 0.5, top + h * 0.04, right - w * 0.08, top + h * 0.3),
            200,
            280,
            fill=shade(colour(look.skin), 1.35),
            width=stroke * 2,
        )
        if look.age == "old":
            for x0 in (left - w * 0.02, right - w * 0.16):
                draw.chord(
                    (x0, top + h * 0.22, x0 + w * 0.18, top + h * 0.48),
                    90 if x0 < cx else 270,
                    270 if x0 < cx else 450,
                    fill=(225, 225, 225),
                    outline=(150, 150, 150),
                    width=stroke,
                )
        return
    if look.hair == "spiky":
        points = [(left - w * 0.02, top + h * 0.32)]
        for n in range(8):
            x = left + (n + 0.5) * w / 8
            points += [
                (x - w * 0.02, top - h * rng.uniform(0.14, 0.24)),
                (x + w / 16, top + h * 0.06),
            ]
        points += [(right + w * 0.02, top + h * 0.32)]
        draw.polygon(points, fill=hair, outline=ink, width=stroke)
        for n in range(4):
            x = left + (n + 1.2) * w / 5.5
            draw.line(
                (x, top + h * 0.02, x + w * 0.05, top - h * 0.1), fill=lit, width=stroke
            )
        return
    if look.hair == "bun":
        bun = (cx - w * 0.18, top - h * 0.3, cx + w * 0.18, top + h * 0.04)
        draw.ellipse(bun, fill=hair, outline=ink, width=stroke)
        draw.arc(
            (
                bun[0] + w * 0.05,
                bun[1] + h * 0.04,
                bun[2] - w * 0.08,
                bun[3] - h * 0.08,
            ),
            200,
            300,
            fill=lit,
            width=stroke,
        )
    if look.hair == "curly":
        for n in range(10):
            x = left - w * 0.02 + n * w / 9
            y = top + h * rng.uniform(-0.1, -0.04)
            r = w * rng.uniform(0.075, 0.095)
            draw.ellipse(
                (x - r, y - r, x + r, y + r), fill=hair, outline=ink, width=stroke
            )
    # The cap of hair: the top of the skull, down to a curved hairline that
    # rises over the forehead and comes down to the temples.
    rx, ry = w / 2 + w * 0.03, h / 2 + h * 0.05
    cy = top + h / 2
    crown = [
        (cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
        for a in range(195, 346, 5)
    ]
    hairline = []
    for n in range(13):
        u = n / 12
        x = right + w * 0.015 - u * (w * 1.03)
        dip = 0.05 * math.exp(-(((u - 0.62) / 0.12) ** 2))  # the side part
        y = top + h * (0.33 - 0.2 * math.sin(math.pi * u) + dip)
        hairline.append((x, y))
    draw.polygon([*crown, *hairline], fill=hair, outline=ink, width=stroke)
    # Strands sweeping from the crown down to the hairline, and a shine.
    strand = shade(hair, 0.7) if sum(hair) > 120 else (48, 44, 50)
    crown_at = (cx - w * 0.06, top + h * 0.02)
    for x, y in hairline[1:-1:2]:
        mid = (
            crown_at[0]
            + (x - crown_at[0]) * 0.55
            + (w * 0.04 if x < crown_at[0] else -w * 0.04),
            crown_at[1] + (y - crown_at[1]) * 0.45,
        )
        draw.line(
            [
                (
                    crown_at[0] + (x - crown_at[0]) * 0.18,
                    crown_at[1] + (y - crown_at[1]) * 0.18 + h * 0.03,
                ),
                mid,
                (
                    crown_at[0] + (x - crown_at[0]) * 0.85,
                    crown_at[1] + (y - crown_at[1]) * 0.85,
                ),
            ],
            fill=strand,
            width=max(1, stroke // 2 + 1),
            joint="curve",
        )
    draw.arc(
        (left + w * 0.3, top + h * 0.0, right - w * 0.08, top + h * 0.3),
        215,
        285,
        fill=lit,
        width=stroke * 2,
    )


@functools.lru_cache(maxsize=64)
def _picture_head(path: str, height: int) -> Any:
    """A picture's subject with its plain background cut away, `height` tall."""
    from PIL import Image, ImageOps

    with Image.open(path) as opened:
        picture = ImageOps.exif_transpose(opened).convert("RGBA")
    if picture.getchannel("A").getextrema()[0] == 255:
        picture = cut_background(picture)
    box = picture.getbbox()
    if box:
        picture = picture.crop(box)
    ratio = height / max(1, picture.height)
    return picture.resize(
        (max(1, int(picture.width * ratio)), height), Image.Resampling.LANCZOS
    )


def cut_background(picture: Any, tolerance: int = 40) -> Any:
    """Clear the background from each corner inward (flat backgrounds: a
    white page, a green screen, a plain wall)."""
    from PIL import ImageDraw

    work = picture.convert("RGBA")
    width, height = work.size
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        r, g, b, a = work.getpixel(corner)
        if a == 0:
            continue
        ImageDraw.floodfill(work, corner, (r, g, b, 0), thresh=tolerance)
    # Also clear anything the fill made transparent-coloured but left opaque.
    return work


def mouth_open(at: float, speaking: bool) -> float:
    """How open a speaking mouth is: syllables are about 5 a second."""
    if not speaking:
        return 0.0
    wave = (
        math.sin(at * 2 * math.pi * 5.2) * 0.5 + math.sin(at * 2 * math.pi * 3.1) * 0.5
    )
    return max(0.0, wave)
