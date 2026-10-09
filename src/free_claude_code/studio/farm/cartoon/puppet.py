"""Stick bodies under big heads, and what they can do.

A body is a few black lines (a torso, two arms, two legs, each in two
parts) joined at angles. An action sets the angles over time: walking
swings the legs, talking waves a hand and bobs the head, falling tips the
whole body over until it lies flat. Bodies are drawn at twice the size and
shrunk, so the lines stay smooth.
"""

import functools
import math
from dataclasses import dataclass
from typing import Any

from .heads import Look, head, mouth_open

ACTIONS = (
    "stand",
    "talk",
    "walk_in",
    "walk_out",
    "walk",
    "run",
    "point",
    "wave",
    "jump",
    "cheer",
    "cry",
    "kneel",
    "sit",
    "fall",
    "lie",
    "crawl",
    "punch",
    "scared",
    "dance",
    "think",
    "laugh",
    "bow",
)
FEEL_OF = {
    "cry": "sad",
    "cheer": "happy",
    "laugh": "happy",
    "dance": "happy",
    "scared": "scared",
    "punch": "angry",
    "fall": "surprised",
}


@dataclass(frozen=True, slots=True)
class Pose:
    """Angles in degrees from straight down; positive swings forward."""

    torso: float = 0.0
    arm_l: tuple[float, float] = (12.0, 6.0)
    arm_r: tuple[float, float] = (-12.0, -6.0)
    leg_l: tuple[float, float] = (6.0, 0.0)
    leg_r: tuple[float, float] = (-6.0, 0.0)
    lift: float = 0.0
    """How far off the ground, in body heights."""
    tip: float = 0.0
    """The whole body turned over (90 = lying on its back)."""
    head_tilt: float = 0.0
    sink: float = 0.0
    """Knees bent: the hips drop this much, in body heights."""


def _ease(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def pose_for(action: str, t: float, length: float) -> Pose:
    """The pose of an action at t seconds into a shot `length` long."""
    swing = math.sin(t * 2 * math.pi * 1.6)
    breathe = math.sin(t * 2 * math.pi * 0.5) * 0.004
    if action in {"walk", "walk_in", "walk_out", "run"}:
        speed = 2.6 if action == "run" else 1.6
        swing = math.sin(t * 2 * math.pi * speed)
        big = 38 if action == "run" else 26
        return Pose(
            torso=8 if action == "run" else 3,
            arm_l=(-swing * big, -swing * big * 0.4 + 20),
            arm_r=(swing * big, swing * big * 0.4 + 20),
            leg_l=(swing * big, max(0.0, -swing) * big * 1.1 * -1),
            leg_r=(-swing * big, max(0.0, swing) * big * 1.1 * -1),
            lift=abs(swing) * (0.03 if action == "run" else 0.012),
        )
    if action == "talk":
        return Pose(
            arm_r=(-20 - 25 * max(0.0, swing), -60 - 30 * swing),
            lift=breathe,
            head_tilt=math.sin(t * 2 * math.pi * 1.3) * 4,
        )
    if action == "point":
        return Pose(arm_r=(-95, -95), arm_l=(10, 5), lift=breathe)
    if action == "wave":
        return Pose(arm_r=(-150, -150 + 35 * swing), lift=breathe)
    if action == "cheer":
        bounce = abs(math.sin(t * 2 * math.pi * 1.8))
        return Pose(arm_l=(120, 140), arm_r=(-120, -140), lift=bounce * 0.04)
    if action == "laugh":
        return Pose(
            arm_l=(30, 120),
            arm_r=(-30, -120),
            torso=-6 + 4 * swing,
            head_tilt=-10 + 4 * swing,
        )
    if action == "jump":
        phase = (t * 1.4) % 1.0
        up = math.sin(phase * math.pi)
        return Pose(
            arm_l=(150 * up, 150 * up),
            arm_r=(-150 * up, -150 * up),
            leg_l=(20 * up, -40 * up),
            leg_r=(-20 * up, -40 * up),
            lift=up * 0.18,
        )
    if action == "cry":
        return Pose(
            arm_l=(-40, -150), arm_r=(40, 150), torso=12, head_tilt=14 + 2 * swing
        )
    if action == "kneel":
        return Pose(
            leg_l=(85, -170),
            leg_r=(80, -170),
            sink=0.2,
            arm_l=(20, 10),
            arm_r=(-10, -5),
            torso=4,
        )
    if action == "sit":
        return Pose(
            leg_l=(85, -85), leg_r=(80, -80), sink=0.2, arm_l=(30, 40), arm_r=(-30, -40)
        )
    if action == "bow":
        return Pose(torso=45, arm_l=(30, 10), arm_r=(-20, -10), head_tilt=20)
    if action == "fall":
        over = _ease(t / 0.7)
        return Pose(
            tip=-90 * over,
            arm_l=(60 * over, 20),
            arm_r=(-60 * over, -20),
            leg_l=(15 * over, 0),
            leg_r=(-15 * over, 0),
        )
    if action == "lie":
        return Pose(
            tip=-90,
            arm_l=(40, 10),
            arm_r=(-30, -10),
            leg_l=(10, 0),
            leg_r=(-6, 0),
            head_tilt=math.sin(t) * 3,
        )
    if action == "crawl":
        step = math.sin(t * 2 * math.pi * 1.2)
        return Pose(
            tip=-80,
            arm_l=(80 + 25 * step, -40),
            arm_r=(80 - 25 * step, -40),
            leg_l=(-20 - 20 * step, 60),
            leg_r=(-20 + 20 * step, 60),
            lift=0.02,
            head_tilt=-60,
        )
    if action == "punch":
        hit = max(0.0, math.sin(t * 2 * math.pi * 1.8))
        return Pose(
            torso=10 * hit,
            arm_r=(-90 * hit - 20, -90 * hit - 30),
            arm_l=(40, 120),
            leg_l=(20, 0),
            leg_r=(-15, 0),
        )
    if action == "scared":
        shake = math.sin(t * 2 * math.pi * 9) * 2
        return Pose(
            arm_l=(60, 150),
            arm_r=(-60, -150),
            torso=-6 + shake,
            head_tilt=shake * 2,
            leg_l=(10 + shake, 0),
            leg_r=(-10 + shake, 0),
        )
    if action == "dance":
        return Pose(
            arm_l=(120 * max(0.0, swing), 40),
            arm_r=(-120 * max(0.0, -swing), -40),
            torso=8 * swing,
            leg_l=(15 * swing, 0),
            leg_r=(-15 * swing, 0),
            lift=abs(swing) * 0.02,
        )
    if action == "think":
        return Pose(arm_r=(-30, -150), arm_l=(30, 100), head_tilt=8, lift=breathe)
    return Pose(lift=breathe, head_tilt=math.sin(t * 2 * math.pi * 0.3) * 2)


@dataclass(frozen=True, slots=True)
class Placed:
    """A character in a shot: who, what they do, and where."""

    look: Look
    action: str
    x: float
    """Where they stand, 0 (left) to 1 (right)."""
    facing: int = 1
    """1 faces right, -1 faces left."""
    feeling: str = ""
    speaking: bool = False
    from_x: float | None = None
    """Where a walk starts."""


def where(placed: Placed, t: float, length: float) -> float:
    """Where the character is now, moving across the shot when walking."""
    if placed.action == "walk_in":
        start = (
            placed.from_x
            if placed.from_x is not None
            else (-0.15 if placed.facing > 0 else 1.15)
        )
        return start + (placed.x - start) * _ease(min(1.0, t / max(0.8, length * 0.6)))
    if placed.action == "walk_out":
        end = 1.2 if placed.facing > 0 else -0.2
        return placed.x + (end - placed.x) * _ease(min(1.0, t / max(0.8, length * 0.8)))
    if placed.action in {"walk", "run"} and placed.from_x is not None:
        return placed.from_x + (placed.x - placed.from_x) * _ease(
            min(1.0, t / max(0.8, length))
        )
    if placed.action == "crawl":
        return placed.x + 0.02 * placed.facing * t
    return placed.x


def _point(
    origin: tuple[float, float], angle: float, length: float
) -> tuple[float, float]:
    radians = math.radians(angle)
    return origin[0] + math.sin(radians) * length, origin[1] + math.cos(
        radians
    ) * length


def _turn(
    point: tuple[float, float], pivot: tuple[float, float], degrees: float
) -> tuple[float, float]:
    """A point turned about a pivot, counterclockwise on screen (y is down)."""
    radians = math.radians(degrees)
    cos, sin = math.cos(radians), math.sin(radians)
    dx, dy = point[0] - pivot[0], point[1] - pivot[1]
    return pivot[0] + dx * cos + dy * sin, pivot[1] - dx * sin + dy * cos


@functools.lru_cache(maxsize=768)
def _posed_head(
    look: Look,
    height: int,
    feeling: str,
    mouth: float,
    blink: bool,
    flip: bool,
    angle: int,
    gaze: float = 0.5,
) -> Any:
    """A head facing the right way and turned, kept: turning is the slow part."""
    from PIL import Image

    picture = head(look, height, feeling=feeling, mouth=mouth, gaze=gaze, blink=blink)
    if flip:
        picture = picture.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if angle:
        picture = picture.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    return picture


def draw_figure(
    canvas: Any,
    placed: Placed,
    *,
    t: float,
    length: float,
    ground: float,
    height: float,
    view: tuple[float, float, float, float] | None = None,
) -> None:
    """Draw one character on the stage canvas (RGB), feet on `ground`; only
    the part inside `view` (what the camera sees) is drawn.

    The joints are worked out (and turned over, for a fall) as points; the
    lines are drawn twice the size into a small mask and shrunk, so they
    stay smooth, and the head is pasted on top.
    """
    from PIL import Image, ImageDraw

    pose = pose_for(placed.action, t, length)
    if placed.look.sprites is not None:
        from .sprite import draw_sprite

        draw_sprite(
            canvas,
            placed.look.sprites,
            action=placed.action,
            feeling=placed.feeling or FEEL_OF.get(placed.action, ""),
            speaking=placed.speaking,
            x=where(placed, t, length) * canvas.width,
            facing=placed.facing,
            t=t,
            ground=ground,
            height=height,
            lift=pose.lift,
            tip=pose.tip,
            sink=pose.sink,
            seed=sum(map(ord, placed.look.name)) % 97,
        )
        return
    kid = placed.look.filled().age == "kid"
    body = height * (0.78 if kid else 1.0)
    face = placed.facing
    head_h = max(8, int(body * (0.52 if kid else 0.46)))
    width = max(1.5, body * 0.026)
    x0 = where(placed, t, length) * canvas.width
    pivot = (x0, ground)
    foot_y = ground - pose.lift * body
    hip = (x0, foot_y - body * (0.4 - pose.sink))
    torso_len = body * 0.27
    neck = _point(hip, 180 - pose.torso * face, torso_len)
    shoulder = _point(hip, 180 - pose.torso * face, torso_len * 0.86)
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = [(hip, neck)]
    for upper, lower in (pose.arm_l, pose.arm_r):
        elbow = _point(shoulder, upper * face, body * 0.15)
        hand = _point(elbow, lower * face, body * 0.15)
        segments += [(shoulder, elbow), (elbow, hand)]
    for upper, lower in (pose.leg_l, pose.leg_r):
        knee = _point(hip, upper * face, body * 0.2)
        foot = _point(knee, (upper + lower) * face, body * 0.2)
        segments += [(hip, knee), (knee, foot)]
    feeling = placed.feeling or FEEL_OF.get(placed.action, "neutral")
    tilt = pose.head_tilt * -face
    if placed.speaking and placed.look.head_image is not None:
        # A picture head can't open its mouth: it bobs instead.
        tilt += math.sin(t * 2 * math.pi * 2.6) * 4
    mouth = round(mouth_open(t, placed.speaking) * 3) / 3
    # Each character blinks and glances around on their own rhythm.
    seed = sum(map(ord, placed.look.name)) % 97
    blink = ((t + seed * 0.37) % 3.7) < 0.12
    gaze = (
        0.5
        if placed.speaking
        else (
            1.0
            if math.sin(t * 0.55 + seed) > 0.6
            else 0.5
            if math.sin(t * 0.55 + seed) > -0.7
            else 0.0
        )
    )
    upright = _posed_head(placed.look, head_h, feeling, mouth, blink, face < 0, 0, gaze)
    # The middle of the head, above the neck and a little forward.
    head_at = (neck[0] + face * upright.width * 0.04, neck[1] - upright.height * 0.44)
    turn = pose.tip * face
    drop = 0.0
    if turn:
        segments = [(_turn(a, pivot, turn), _turn(b, pivot, turn)) for a, b in segments]
        head_at = _turn(head_at, pivot, turn)
        # Lying down, the body rests on the ground, not half under it.
        drop = body * 0.1 * min(1.0, abs(pose.tip) / 90)
        segments = [((a[0], a[1] - drop), (b[0], b[1] - drop)) for a, b in segments]
        head_at = (head_at[0], head_at[1] - drop)
    # A soft shadow on the ground under them.
    shadow_w = body * (0.5 if turn else 0.24)
    shadow_x = x0 + (face * body * 0.25 if turn else 0.0)
    ImageDraw.Draw(canvas, "RGBA").ellipse(
        (
            shadow_x - shadow_w,
            ground - body * 0.025,
            shadow_x + shadow_w,
            ground + body * 0.025,
        ),
        fill=(0, 0, 0, 55),
    )
    # The lines, into a mask just big enough for them.
    xs = [x for seg in segments for x, _ in seg]
    ys = [y for seg in segments for _, y in seg]
    pad = width * 2
    left, top = int(min(xs) - pad), int(min(ys) - pad)
    right, bottom = int(max(xs) + pad), int(max(ys) + pad)
    if view is not None:
        left, top = max(left, int(view[0]) - 4), max(top, int(view[1]) - 4)
        right = max(left + 1, min(right, int(view[2]) + 4))
        bottom = max(top + 1, min(bottom, int(view[3]) + 4))
    big = 2
    mask = Image.new("L", ((right - left + 1) * big, (bottom - top + 1) * big), 0)
    draw = ImageDraw.Draw(mask)
    line = max(2, round(width * big))
    for start, end in segments:
        a = ((start[0] - left) * big, (start[1] - top) * big)
        b = ((end[0] - left) * big, (end[1] - top) * big)
        draw.line((a, b), fill=255, width=line)
        for x, y in (a, b):
            r = line / 2
            draw.ellipse((x - r, y - r, x + r, y + r), fill=255)
    # Round hands at the ends of the arms, shoes at the ends of the legs.
    for index in (2, 4):
        x, y = (
            (segments[index][1][0] - left) * big,
            (segments[index][1][1] - top) * big,
        )
        r = line * 1.15
        draw.ellipse((x - r, y - r, x + r, y + r), fill=255)
    for index in (6, 8):
        x, y = (
            (segments[index][1][0] - left) * big,
            (segments[index][1][1] - top) * big,
        )
        r = line * 1.05
        toe = face * line * 1.6
        draw.ellipse(
            (min(x - r, x + toe), y - r * 0.8, max(x + r, x + toe), y + r * 0.8),
            fill=255,
        )
    mask = mask.reduce(big)
    canvas.paste((12, 12, 12), (left, top, left + mask.width, top + mask.height), mask)
    angle = round((tilt + turn) / 2) * 2
    picture = (
        _posed_head(placed.look, head_h, feeling, mouth, blink, face < 0, angle, gaze)
        if angle
        else upright
    )
    canvas.paste(
        picture,
        (int(head_at[0] - picture.width / 2), int(head_at[1] - picture.height / 2)),
        picture,
    )
    if placed.action == "cry":
        draw = ImageDraw.Draw(canvas)
        drop_r = max(1.5, width * 0.8)
        for n in range(3):
            drop_y = head_at[1] + head_h * 0.1 + ((t * 60 + n * 20) % (body * 0.1))
            for side in (-0.15, 0.15):
                x = head_at[0] + head_h * side
                draw.ellipse(
                    (x - drop_r, drop_y, x + drop_r, drop_y + drop_r * 2.4),
                    fill=(90, 170, 255),
                )


def head_box(
    placed: Placed,
    t: float,
    length: float,
    *,
    canvas: tuple[int, int],
    ground: float,
    height: float,
) -> tuple[float, float]:
    """Roughly where the character's face is on the stage, for close-ups."""
    pose = pose_for(placed.action, t, length)
    x = where(placed, t, length) * canvas[0]
    if pose.tip:
        return x + placed.facing * height * 0.45, ground - height * 0.1
    if placed.look.sprites is not None:
        from .sprite import SPRITE_HEIGHT

        return x, ground - height * SPRITE_HEIGHT * (
            0.86 - pose.sink
        ) - pose.lift * height
    kid = placed.look.filled().age == "kid"
    body = height * (0.78 if kid else 1.0)
    return x, ground - body * (0.95 - pose.sink) - pose.lift * body
