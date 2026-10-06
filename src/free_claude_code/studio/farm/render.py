"""Turn pictures, clips, a voice, and timed words into an MP4.

Pillow draws every frame: the picture slowly zooming (the "Ken Burns" move)
or a muted clip playing, the hook in big letters at the start, captions that
light up word by word, and a thin progress bar. Shorts are vertical 9:16 and
can run over a looping background video (gameplay, say); long videos are
16:9, calmer, darker, and marked with chapter titles. ffmpeg (shipped by the
imageio-ffmpeg package, or one on PATH) reads the clips and turns the frames
and the voice into an H.264 MP4 that YouTube, Instagram, and TikTok all take.
"""

import contextlib
import functools
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .timing import Chunk

SIZES = {
    "720p": (720, 1280),
    "1080p": (1080, 1920),
    "720p-wide": (1280, 720),
    "1080p-wide": (1920, 1080),
}
FPS = 30
ZOOM = 0.12
"""How far the picture moves in over one scene."""
FADE = 0.22
"""Seconds two pictures blend when the scene changes."""
HOOK_SECONDS = 2.6
CHAPTER_SECONDS = 4.0
"""How long a long video shows each chapter's title."""
KEEP_PICTURES = 3
"""Pictures kept sized in memory at once: a two-hour video has hundreds."""


class RenderError(RuntimeError):
    """The video could not be made."""


@dataclass(frozen=True, slots=True)
class Look:
    name: str
    fonts: tuple[str, ...]
    upper: bool
    fill: tuple[int, int, int]
    active: tuple[int, int, int]
    stroke: tuple[int, int, int]
    accent: tuple[int, int, int]
    size: float
    """Caption height, as a share of the video's width."""
    pill: bool = False
    glow: bool = False
    bars: bool = False


_HEAVY = (
    "impact.ttf",
    "Impact.ttf",
    "seguibl.ttf",
    "arialbd.ttf",
    "Arial Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
    "FreeSansBold.ttf",
)
_SANS = (
    "segoeuib.ttf",
    "seguisb.ttf",
    "arialbd.ttf",
    "Arial Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
    "FreeSansBold.ttf",
)
_SERIF = (
    "georgiab.ttf",
    "Georgia Bold.ttf",
    "timesbd.ttf",
    "DejaVuSerif-Bold.ttf",
    "LiberationSerif-Bold.ttf",
    "FreeSerifBold.ttf",
)
LOOK_STYLES: dict[str, Look] = {
    "bold": Look(
        "bold",
        _HEAVY,
        True,
        (255, 255, 255),
        (255, 225, 77),
        (0, 0, 0),
        (255, 225, 77),
        0.092,
    ),
    "clean": Look(
        "clean",
        _SANS,
        False,
        (20, 20, 24),
        (37, 99, 235),
        (255, 255, 255),
        (37, 99, 235),
        0.07,
        pill=True,
    ),
    "neon": Look(
        "neon",
        _HEAVY,
        True,
        (255, 255, 255),
        (255, 64, 200),
        (0, 230, 255),
        (0, 230, 255),
        0.088,
        glow=True,
    ),
    "cinema": Look(
        "cinema",
        _SERIF,
        False,
        (245, 240, 230),
        (240, 190, 80),
        (0, 0, 0),
        (240, 190, 80),
        0.064,
        bars=True,
    ),
}
PALETTES = (
    ((18, 24, 64), (122, 40, 160)),
    ((10, 50, 60), (20, 160, 140)),
    ((60, 16, 30), (230, 90, 60)),
    ((12, 18, 30), (60, 110, 200)),
    ((40, 10, 60), (240, 80, 150)),
    ((20, 30, 20), (140, 190, 60)),
)


@dataclass(frozen=True, slots=True)
class Shot:
    """One scene on screen: its picture or clip, and when it shows."""

    image: Path | None
    start: float
    length: float
    label: str = ""
    """Big words on screen for this scene, if any."""
    show: str = ""
    """What the picture shows, written on an art card when there's no photo."""
    clip: Path | None = None
    """A video clip to play (muted) instead of a picture."""
    clip_start: float = 0.0
    """Where in the clip to start, in seconds."""


@dataclass(frozen=True, slots=True)
class Plan:
    shots: tuple[Shot, ...]
    chunks: tuple[Chunk, ...]
    hook: str
    duration: float
    look: str = "bold"
    size: str = "720p"
    handle: str = ""
    seed: int = 0
    music: Path | None = field(default=None)
    fps: int = FPS
    captions: bool = True
    fade: float = FADE
    progress_bar: bool = True
    background: Path | None = None
    """A video looping under the whole short (gameplay); pictures then show
    as a card at the top."""
    dim: float = 0.0
    """How much darker every frame is (0 to 1): calm, for sleep videos."""
    chapters: tuple[tuple[float, str], ...] = ()
    """(start, title) for each chapter of a long video."""

    @property
    def frame_size(self) -> tuple[int, int]:
        return SIZES.get(self.size, SIZES["720p"])

    @property
    def wide(self) -> bool:
        width, height = self.frame_size
        return width > height


# ------------------------------------------------------------- the tools


def pillow_ready() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


@functools.cache
def find_ffmpeg() -> str | None:
    """ffmpeg from the FCC_FFMPEG setting, imageio-ffmpeg, or PATH."""
    chosen = os.environ.get("FCC_FFMPEG", "").strip()
    if chosen and Path(chosen).is_file():
        return chosen
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except ImportError, RuntimeError, OSError:
        pass
    return shutil.which("ffmpeg")


def video_tools() -> tuple[bool, str]:
    """Whether videos can be made here, and if not, what to install."""
    if not pillow_ready():
        return False, "Install the studio_video extra (Pillow and ffmpeg)."
    if find_ffmpeg() is None:
        return False, "Install the studio_video extra, or put ffmpeg on PATH."
    return True, ""


@functools.cache
def _has_x264(ffmpeg: str) -> bool:
    try:
        listed = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except OSError, subprocess.SubprocessError:
        return False
    return "libx264" in listed.stdout


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
"""Keep a console window from flashing up on Windows."""


# ------------------------------------------------------------- the fonts


def _font_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"]
    dirs += [
        Path.home() / "Library/Fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
    ]
    return [folder for folder in dirs if folder.is_dir()]


@functools.cache
def _font_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for folder in _font_dirs():
        try:
            for path in folder.rglob("*"):
                if path.suffix.lower() in {".ttf", ".otf"}:
                    index.setdefault(path.name.lower(), str(path))
        except OSError:
            continue
    return index


@functools.cache
def _font(names: tuple[str, ...], size: int) -> Any:
    from PIL import ImageFont

    index = _font_index()
    for name in names:
        path = index.get(name.lower())
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


# ------------------------------------------------------------- pictures


def art_card(text: str, size: tuple[int, int], seed: int) -> Any:
    """A picture when there is none: a soft gradient with glowing circles."""
    from PIL import Image, ImageDraw, ImageFilter

    width, height = size
    rng = random.Random(seed)
    top, bottom = PALETTES[rng.randrange(len(PALETTES))]
    base = Image.new("RGB", (1, 256))
    for y in range(256):
        mix = y / 255
        base.putpixel(
            (0, y),
            tuple(round(a + (b - a) * mix) for a, b in zip(top, bottom, strict=True)),
        )
    card = base.resize((width, height))
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for _ in range(9):
        radius = rng.randint(width // 10, width // 3)
        x, y = rng.randint(0, width), rng.randint(0, height)
        tone = (*(min(255, c + 80) for c in bottom), rng.randint(30, 80))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=tone)
    glow = glow.filter(ImageFilter.GaussianBlur(width // 18))
    card.paste(glow, (0, 0), glow)
    words = " ".join(text.split()[:5]).upper()
    if words:
        font = _font(_HEAVY, max(24, width // 9))
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        lines = _wrap(words, font, int(width * 0.8))
        _draw_lines(
            layer,
            lines,
            font,
            centre_y=int(height * 0.43),
            fill=(255, 255, 255, 70),
        )
        card.paste(layer, (0, 0), layer)
    return card


def _fit(image: Any, size: tuple[int, int]) -> Any:
    """Fill the frame: tall pictures are cropped, wide ones float over a blur."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    width, height = size
    image = ImageOps.exif_transpose(image).convert("RGB")
    ratio = image.width / max(1, image.height)
    if ratio <= (width / height) * 1.35:
        return ImageOps.fit(image, size, Image.Resampling.LANCZOS)
    back = ImageOps.fit(image, size, Image.Resampling.BILINEAR)
    back = back.filter(ImageFilter.GaussianBlur(width // 24))
    back = ImageEnhance.Brightness(back).enhance(0.55)
    front = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
    back.paste(front, ((width - front.width) // 2, (height - front.height) // 2))
    return back


def _load(shot: Shot, size: tuple[int, int], seed: int) -> Any:
    from PIL import Image, UnidentifiedImageError

    if shot.image is not None and shot.image.is_file():
        try:
            with Image.open(shot.image) as opened:
                return _fit(opened, size)
        except OSError, UnidentifiedImageError, ValueError:
            pass
    return art_card(shot.show or shot.label, size, seed)


# ------------------------------------------------------------- text


def _wrap(text: str, font: Any, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and font.getlength(trial) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _draw_lines(
    layer: Any,
    lines: Sequence[str],
    font: Any,
    *,
    centre_y: int,
    fill: tuple[int, ...],
    stroke: tuple[int, ...] | None = None,
    stroke_width: int = 0,
) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(layer)
    ascent, descent = font.getmetrics()
    line_height = int((ascent + descent) * 1.08)
    top = centre_y - line_height * len(lines) // 2
    for row, line in enumerate(lines):
        width = font.getlength(line)
        draw.text(
            ((layer.width - width) / 2, top + row * line_height),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke,
        )


@dataclass(slots=True)
class _Painter:
    """Draws the words on top of each frame, caching what repeats."""

    look: Look
    size: tuple[int, int]
    cache: dict[tuple[object, ...], tuple[Any, tuple[int, int]]] = field(
        default_factory=dict
    )

    @property
    def wide(self) -> bool:
        return self.size[0] > self.size[1]

    def _font(self, scale: float = 1.0) -> Any:
        # Wide videos size words by their height, like a 9:16 frame of it.
        base = self.size[1] * 0.75 if self.wide else self.size[0]
        return _font(self.look.fonts, max(14, int(base * self.look.size * scale)))

    def caption(
        self, chunk_id: int, chunk: Chunk, active: int
    ) -> tuple[Any, tuple[int, int]]:
        key = ("caption", chunk_id, active)
        if key not in self.cache:
            self.cache[key] = self._caption(chunk, active)
        return self.cache[key]

    def _caption(self, chunk: Chunk, active: int) -> tuple[Any, tuple[int, int]]:
        from PIL import Image, ImageDraw, ImageFilter

        look = self.look
        width, height = self.size
        font = self._font()
        words = [w.text.upper() if look.upper else w.text for w in chunk.words]
        space = font.getlength(" ")
        limit = width * 0.86
        rows: list[list[int]] = [[]]
        used = 0.0
        for index, word in enumerate(words):
            need = font.getlength(word) + (space if rows[-1] else 0)
            if rows[-1] and used + need > limit:
                rows.append([])
                used = 0.0
                need = font.getlength(word)
            rows[-1].append(index)
            used += need
        ascent, descent = font.getmetrics()
        line_height = int((ascent + descent) * 1.12)
        pad = int(line_height * 0.35)
        box_h = line_height * len(rows) + pad * 2
        layer = Image.new("RGBA", (width, box_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        stroke_width = 0 if look.pill else max(2, int(font.size * 0.09))
        for row_no, row in enumerate(rows):
            text_width = sum(font.getlength(words[i]) for i in row) + space * (
                len(row) - 1
            )
            x = (width - text_width) / 2
            y = pad + row_no * line_height
            if look.pill:
                draw.rounded_rectangle(
                    (x - pad, y - pad * 0.4, x + text_width + pad, y + line_height),
                    radius=pad,
                    fill=(255, 255, 255, 235),
                )
            for index in row:
                colour = look.active if index == active else look.fill
                draw.text(
                    (x, y),
                    words[index],
                    font=font,
                    fill=(*colour, 255),
                    stroke_width=stroke_width,
                    stroke_fill=(*look.stroke, 255),
                )
                x += font.getlength(words[index]) + space
        if look.glow:
            halo = layer.filter(ImageFilter.GaussianBlur(max(4, font.size // 6)))
            glowing = Image.new("RGBA", layer.size, (*look.stroke, 0))
            glowing.putalpha(halo.getchannel("A"))
            glowing.alpha_composite(layer)
            layer = glowing
        return layer, (0, int(height * (0.84 if self.wide else 0.62)) - box_h // 2)

    def banner(self, text: str, *, big: bool) -> tuple[Any, tuple[int, int]]:
        """The hook at the start, or a scene's big words, on a bright box."""
        key = ("banner", text, big)
        if key not in self.cache:
            self.cache[key] = self._banner(text, big)
        return self.cache[key]

    def _banner(self, text: str, big: bool) -> tuple[Any, tuple[int, int]]:
        from PIL import Image, ImageDraw

        look = self.look
        width, height = self.size
        font = self._font(1.05 if big else 0.8)
        words = text.upper() if look.upper else text
        lines = _wrap(words, font, int(width * 0.8))[:4]
        ascent, descent = font.getmetrics()
        line_height = int((ascent + descent) * 1.1)
        pad = int(line_height * 0.4)
        box_w = int(max(font.getlength(line) for line in lines) + pad * 2)
        box_h = line_height * len(lines) + pad * 2
        layer = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        draw.rounded_rectangle(
            (0, 0, box_w - 1, box_h - 1), radius=pad, fill=(*look.accent, 240)
        )
        ink = (12, 12, 16, 255) if sum(look.accent) > 380 else (255, 255, 255, 255)
        for row, line in enumerate(lines):
            draw.text(
                ((box_w - font.getlength(line)) / 2, pad + row * line_height),
                line,
                font=font,
                fill=ink,
            )
        if self.wide:
            return layer, ((width - box_w) // 2, (height - box_h) // 2)
        top = int(height * (0.2 if big else 0.16))
        return layer, ((width - box_w) // 2, top)

    def frame_overlay(self, handle: str, dim: float = 0.0) -> Any:
        """What every frame has: shade at the bottom, the handle, bars."""
        key = ("overlay", handle, dim)
        if key not in self.cache:
            self.cache[key] = (self._frame_overlay(handle, dim), (0, 0))
        return self.cache[key][0]

    def _frame_overlay(self, handle: str, dim: float) -> Any:
        from PIL import Image, ImageDraw

        width, height = self.size
        shade = Image.new("L", (1, 256))
        floor = int(255 * min(0.9, max(0.0, dim)))
        for y in range(256):
            gradient = max(0, int((y - (150 if self.wide else 110)) * 1.25))
            shade.putpixel((0, y), min(255, floor + gradient * (255 - floor) // 255))
        alpha = shade.resize((width, height))
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        layer.putalpha(alpha)
        draw = ImageDraw.Draw(layer)
        if self.look.bars:
            bar = int(height * 0.075)
            draw.rectangle((0, 0, width, bar), fill=(0, 0, 0, 255))
            draw.rectangle((0, height - bar, width, height), fill=(0, 0, 0, 255))
        if handle:
            font = _font(_SANS, max(12, (height if self.wide else width) // 30))
            label = handle if handle.startswith("@") else f"@{handle}"
            spot = (
                (width - font.getlength(label) - width * 0.03, height * 0.92)
                if self.wide
                else ((width - font.getlength(label)) / 2, height * 0.88)
            )
            draw.text(spot, label, font=font, fill=(255, 255, 255, 150))
        return layer

    def card(self, image: Any, index: int) -> tuple[Any, tuple[int, int]]:
        """A scene's picture as a card at the top, over a background video."""
        key = ("card", index)
        if key not in self.cache:
            from PIL import Image, ImageDraw, ImageOps

            width, height = self.size
            box = (int(width * 0.86), int(height * 0.3))
            picture = ImageOps.fit(image, box, Image.Resampling.BILINEAR)
            mask = Image.new("L", box, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, box[0] - 1, box[1] - 1), radius=box[0] // 18, fill=255
            )
            layer = Image.new("RGBA", box, (0, 0, 0, 0))
            layer.paste(picture, (0, 0), mask)
            self.cache[key] = (layer, ((width - box[0]) // 2, int(height * 0.08)))
        return self.cache[key]


# ------------------------------------------------------------- the video


def _ease(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def _moving(
    base: Any, size: tuple[int, int], progress: float, way: int, zoom: float = ZOOM
) -> Any:
    """The picture at one moment of its slow zoom and drift."""
    from PIL import Image

    scale = 1 + zoom * (_ease(progress) if way % 2 == 0 else 1 - _ease(progress))
    crop_w, crop_h = base.width / scale, base.height / scale
    drift = (way % 3 - 1) * (base.width - crop_w) * 0.5 * _ease(progress)
    left = (base.width - crop_w) / 2 + drift
    top = (base.height - crop_h) / 2
    return base.resize(
        size,
        Image.Resampling.BILINEAR,
        box=(left, top, left + crop_w, top + crop_h),
    )


def _paste(frame: Any, item: tuple[Any, tuple[int, int]]) -> None:
    layer, at = item
    frame.paste(layer, at, layer)


def _active(chunks: Sequence[Chunk], at: float) -> tuple[int, int] | None:
    for number, chunk in enumerate(chunks):
        if chunk.start - 0.05 <= at < chunk.end + 0.12:
            for index, word in enumerate(chunk.words):
                if at < word.end:
                    return number, index
            return number, len(chunk.words) - 1
    return None


class _ClipReader:
    """Frames of a muted clip, sized to the video, read one at a time."""

    def __init__(
        self,
        ffmpeg: str,
        path: Path,
        *,
        start: float,
        length: float,
        size: tuple[int, int],
        fps: int,
    ) -> None:
        width, height = size
        self._size = size
        self._bytes = width * height * 3
        self._last: Any = None
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, start):.3f}",
            "-stream_loop",
            "-1",
            "-i",
            str(path),
            "-t",
            f"{length + 1:.3f}",
            "-an",
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},format=rgb24",
            "-f",
            "rawvideo",
            "-",
        ]
        try:
            self._process: subprocess.Popen[bytes] | None = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
        except OSError:
            self._process = None

    def next(self) -> Any:
        from PIL import Image

        process = self._process
        if process is not None and process.stdout is not None:
            data = process.stdout.read(self._bytes)
            if len(data) == self._bytes:
                self._last = Image.frombytes("RGB", self._size, data)
                return self._last
            self.close()
        if self._last is None:
            self._last = Image.new("RGB", self._size, (8, 10, 14))
        return self._last

    @property
    def last(self) -> Any:
        return self._last

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        with contextlib.suppress(OSError):
            if process.stdout is not None:
                process.stdout.close()
        with contextlib.suppress(OSError):
            process.kill()
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            process.wait(timeout=10)


class Frames:
    """What each moment of a video looks like, drawn in order.

    Pictures are sized once and kept only while they're on screen; clips are
    read as they play. Frames must be asked for in time order (they are when
    the video is written), since a clip only moves forward.
    """

    def __init__(self, plan: Plan, ffmpeg: str | None) -> None:
        self.plan = plan
        self._ffmpeg = ffmpeg
        self.size = plan.frame_size
        width, height = self.size
        zoom = ZOOM * (0.6 if plan.wide else 1.0)
        self._zoom = zoom
        self._roomy = (round(width * (1 + zoom)), round(height * (1 + zoom)))
        self.painter = _Painter(
            LOOK_STYLES.get(plan.look, LOOK_STYLES["bold"]), self.size
        )
        self._pictures: dict[int, Any] = {}
        self._clips: dict[int, _ClipReader] = {}
        self._background: _ClipReader | None = None
        if plan.background is not None and plan.background.is_file() and ffmpeg:
            self._background = _ClipReader(
                ffmpeg,
                plan.background,
                start=0.0,
                length=plan.duration,
                size=self.size,
                fps=plan.fps,
            )

    def close(self) -> None:
        for reader in self._clips.values():
            reader.close()
        self._clips.clear()
        if self._background is not None:
            self._background.close()

    def _picture(self, index: int) -> Any:
        from PIL import Image

        if index not in self._pictures:
            shot = self.plan.shots[index]
            base = _load(shot, self._roomy, self.plan.seed + index)
            if base.size != self._roomy:
                base = base.resize(self._roomy, Image.Resampling.LANCZOS)
            self._pictures[index] = base
            for old in [key for key in self._pictures if key < index - KEEP_PICTURES]:
                del self._pictures[old]
        return self._pictures[index]

    def _clip_frame(self, index: int) -> Any:
        shot = self.plan.shots[index]
        reader = self._clips.get(index)
        if reader is None:
            assert shot.clip is not None and self._ffmpeg is not None
            reader = _ClipReader(
                self._ffmpeg,
                shot.clip,
                start=shot.clip_start,
                length=shot.length,
                size=self.size,
                fps=self.plan.fps,
            )
            self._clips[index] = reader
            for old in [key for key in self._clips if key < index - 1]:
                self._clips.pop(old).close()
        return reader.next()

    def _scene(self, index: int, at: float, *, moving: bool = True) -> Any:
        shot = self.plan.shots[index]
        if shot.clip is not None and self._ffmpeg is not None:
            reader = self._clips.get(index)
            if not moving and reader is not None and reader.last is not None:
                return reader.last
            return self._clip_frame(index)
        progress = (at - shot.start) / max(0.1, shot.length)
        return _moving(
            self._picture(index),
            self.size,
            progress,
            index + self.plan.seed,
            self._zoom,
        )

    def draw(self, at: float) -> Any:
        """The whole picture at one moment of the video."""
        from PIL import Image, ImageDraw

        plan = self.plan
        index = 0
        for number, shot in enumerate(plan.shots):
            if at >= shot.start:
                index = number
        shot = plan.shots[index]
        if self._background is not None:
            frame = self._background.next().copy()
            if shot.image is not None or shot.clip is not None:
                _paste(frame, self.painter.card(self._picture(index), index))
        else:
            frame = self._scene(index, at)
            if index > 0 and at - shot.start < plan.fade:
                before = self._scene(index - 1, at, moving=False)
                frame = Image.blend(before, frame, (at - shot.start) / plan.fade)
            elif frame is self._clips.get(index, _NO_READER).last:
                frame = frame.copy()
        overlay = self.painter.frame_overlay(plan.handle, plan.dim)
        frame.paste(overlay, (0, 0), overlay)
        title = _chapter_at(plan.chapters, at)
        if title:
            _paste(frame, self.painter.banner(title, big=True))
        elif at < HOOK_SECONDS and plan.hook:
            _paste(frame, self.painter.banner(plan.hook, big=True))
        elif shot.label:
            _paste(frame, self.painter.banner(shot.label, big=False))
        if plan.captions:
            showing = _active(plan.chunks, at)
            if showing is not None:
                chunk_id, word = showing
                _paste(
                    frame,
                    self.painter.caption(chunk_id, plan.chunks[chunk_id], word),
                )
        if plan.progress_bar:
            width, height = self.size
            done = int(width * min(1.0, at / max(0.1, plan.duration)))
            bar = max(4, height // 240)
            ImageDraw.Draw(frame).rectangle(
                (0, height - bar, done, height), fill=self.painter.look.accent
            )
        return frame


class _NoReader:
    last = None


_NO_READER: Any = _NoReader()


def _chapter_at(chapters: Sequence[tuple[float, str]], at: float) -> str:
    for start, title in chapters:
        if start <= at < start + CHAPTER_SECONDS:
            return title
    return ""


def draw_frame(plan: Plan, at: float) -> Any:
    """One frame on its own (a cover, a preview)."""
    index = 0
    for number, shot in enumerate(plan.shots):
        if at >= shot.start:
            index = number
    shot = plan.shots[index]
    if shot.clip is not None:
        # Start the clip at this moment rather than at the scene's start.
        moved = replace(shot, clip_start=shot.clip_start + max(0.0, at - shot.start))
        plan = replace(
            plan,
            shots=tuple(moved if n == index else s for n, s in enumerate(plan.shots)),
        )
    frames = Frames(plan, find_ffmpeg())
    try:
        return frames.draw(at)
    finally:
        frames.close()


def render(
    plan: Plan,
    *,
    audio: Path,
    out: Path,
    cover: Path,
    progress: Callable[[float], None] = lambda _: None,
    stopped: Callable[[], bool] = lambda: False,
) -> None:
    """Write the MP4 and a cover picture (runs on a thread: it is slow)."""
    ready, why = video_tools()
    if not ready:
        raise RenderError(why)
    if not plan.shots:
        raise RenderError("The script has no scenes.")
    cover.parent.mkdir(parents=True, exist_ok=True)
    draw_frame(plan, min(0.8, plan.duration / 3)).save(cover, "JPEG", quality=88)
    frames = Frames(plan, find_ffmpeg())
    encode(
        frames.draw,
        size=plan.frame_size,
        fps=plan.fps,
        duration=plan.duration,
        audio=audio,
        out=out,
        music=plan.music,
        progress=progress,
        stopped=stopped,
        close=frames.close,
    )


def encode(
    draw: Callable[[float], Any],
    *,
    size: tuple[int, int],
    fps: int,
    duration: float,
    audio: Path,
    out: Path,
    music: Path | None = None,
    music_volume: float = 0.16,
    progress: Callable[[float], None] = lambda _: None,
    stopped: Callable[[], bool] = lambda: False,
    close: Callable[[], None] = lambda: None,
) -> None:
    """Draw every frame in order and have ffmpeg write them, with the sound
    (and quiet music under it), into an MP4."""
    ready, why = video_tools()
    if not ready:
        close()
        raise RenderError(why)
    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None
    width, height = size
    video = (
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]
        if _has_x264(ffmpeg)
        else ["-c:v", "mpeg4", "-q:v", "3"]
    )
    inputs = ["-i", str(audio)]
    mixing: list[str] = ["-map", "0:v", "-map", "1:a"]
    if music is not None and music.is_file():
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        mixing = [
            "-filter_complex",
            f"[2:a]volume={music_volume:.2f}[m];[1:a][m]amix=inputs=2:duration=first[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
        ]
    partial = out.with_suffix(".part.mp4")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        *inputs,
        *mixing,
        *video,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(partial),
    ]
    frames_total = max(1, round(duration * fps))
    was_stopped = False
    # ffmpeg's complaints go to a file: a pipe nobody reads while the frames
    # are written could fill up and stall both sides.
    with tempfile.TemporaryFile() as log:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log,
                creationflags=_NO_WINDOW,
            )
        except OSError as error:
            close()
            raise RenderError(f"ffmpeg would not start: {error}") from error
        assert process.stdin is not None
        try:
            for number in range(frames_total):
                frame = draw(number / fps)
                process.stdin.write(frame.tobytes())
                if number % 15 == 0:
                    progress(number / frames_total)
                    if stopped():
                        was_stopped = True
                        break
        except BrokenPipeError, OSError:
            pass
        finally:
            close()
            with contextlib.suppress(OSError):
                process.stdin.close()
            if was_stopped:
                process.kill()
            try:
                process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        log.seek(0)
        errors = log.read()[-2_000:]
    if was_stopped:
        partial.unlink(missing_ok=True)
        raise RenderError("Stopped.")
    if process.returncode != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        detail = (errors or b"").decode("utf-8", "replace").strip()[-400:]
        raise RenderError(f"ffmpeg could not make the video: {detail or 'no reason'}")
    partial.replace(out)
    progress(1.0)


def probe(path: Path) -> tuple[float, int, int]:
    """A video's length in seconds and its size, read from ffmpeg's report."""
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return 0.0, 0, 0
    try:
        report = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            creationflags=_NO_WINDOW,
        ).stderr
    except OSError, subprocess.SubprocessError:
        return 0.0, 0, 0
    seconds = 0.0
    found = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", report)
    if found:
        hours, minutes, rest = found.groups()
        seconds = int(hours) * 3600 + int(minutes) * 60 + float(rest)
    size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", report)
    width, height = (int(size.group(1)), int(size.group(2))) if size else (0, 0)
    return seconds, width, height


def snapshot(path: Path, out: Path, *, at: float = 1.0, width: int = 360) -> bool:
    """A still from a video, for its thumbnail."""
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        done = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{at:.2f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                f"scale={width}:-2",
                str(out),
            ],
            capture_output=True,
            timeout=60,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except OSError, subprocess.SubprocessError:
        return False
    return done.returncode == 0 and out.is_file()


def thumbnail(
    source: Path, title: str, out: Path, *, size: tuple[int, int] = (1280, 720)
) -> bool:
    """A YouTube thumbnail: the cover, darkened at the left, with a big title."""
    if not pillow_ready() or not source.is_file():
        return False
    from PIL import Image, ImageDraw, ImageOps

    with Image.open(source) as opened:
        picture = ImageOps.fit(opened.convert("RGB"), size, Image.Resampling.LANCZOS)
    width, height = size
    shade = Image.new("L", (256, 1))
    for x in range(256):
        shade.putpixel((x, 0), max(0, 210 - x))
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.putalpha(shade.resize(size))
    picture.paste(layer, (0, 0), layer)
    font = _font(_HEAVY, height // 9)
    words = " ".join(title.upper().split())
    lines = _wrap(words, font, int(width * 0.55))[:4]
    draw = ImageDraw.Draw(picture)
    ascent, descent = font.getmetrics()
    line_height = int((ascent + descent) * 1.05)
    top = (height - line_height * len(lines)) // 2
    for row, line in enumerate(lines):
        draw.text(
            (width * 0.05, top + row * line_height),
            line,
            font=font,
            fill=(255, 225, 77) if row == 0 else (255, 255, 255),
            stroke_width=max(3, height // 120),
            stroke_fill=(0, 0, 0),
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    picture.save(out, "JPEG", quality=90)
    return True
