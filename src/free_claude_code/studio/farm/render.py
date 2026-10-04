"""Turn pictures, a voice, and timed words into a vertical MP4.

Pillow draws every frame: the picture slowly zooming (the "Ken Burns" move),
the hook in big letters at the start, captions that light up word by word,
and a thin progress bar. ffmpeg (shipped by the imageio-ffmpeg package, or
one on PATH) turns the frames and the voice into an H.264 MP4 that
Instagram, TikTok, and YouTube all take.
"""

import contextlib
import functools
import os
import random
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .timing import Chunk

SIZES = {"720p": (720, 1280), "1080p": (1080, 1920)}
FPS = 30
ZOOM = 0.12
"""How far the picture moves in over one scene."""
FADE = 0.22
"""Seconds two pictures blend when the scene changes."""
HOOK_SECONDS = 2.6


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
    """One scene on screen: its picture and when it shows."""

    image: Path | None
    start: float
    length: float
    label: str = ""
    """Big words on screen for this scene, if any."""
    show: str = ""
    """What the picture shows, written on an art card when there's no photo."""


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

    if shot.image is not None:
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

    def _font(self, scale: float = 1.0) -> Any:
        return _font(
            self.look.fonts, max(14, int(self.size[0] * self.look.size * scale))
        )

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
        return layer, (0, int(height * 0.62) - box_h // 2)

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
        top = int(height * (0.2 if big else 0.16))
        return layer, ((width - box_w) // 2, top)

    def frame_overlay(self, handle: str) -> Any:
        """What every frame has: shade at the bottom, the handle, bars."""
        key = ("overlay", handle)
        if key not in self.cache:
            self.cache[key] = (self._frame_overlay(handle), (0, 0))
        return self.cache[key][0]

    def _frame_overlay(self, handle: str) -> Any:
        from PIL import Image, ImageDraw

        width, height = self.size
        shade = Image.new("L", (1, 256))
        for y in range(256):
            shade.putpixel((0, y), max(0, int((y - 110) * 1.25)))
        alpha = shade.resize((width, height))
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        layer.putalpha(alpha)
        draw = ImageDraw.Draw(layer)
        if self.look.bars:
            bar = int(height * 0.075)
            draw.rectangle((0, 0, width, bar), fill=(0, 0, 0, 255))
            draw.rectangle((0, height - bar, width, height), fill=(0, 0, 0, 255))
        if handle:
            font = _font(_SANS, max(12, width // 30))
            label = handle if handle.startswith("@") else f"@{handle}"
            draw.text(
                ((width - font.getlength(label)) / 2, height * 0.88),
                label,
                font=font,
                fill=(255, 255, 255, 150),
            )
        return layer


# ------------------------------------------------------------- the video


def _ease(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def _moving(base: Any, size: tuple[int, int], progress: float, way: int) -> Any:
    """The picture at one moment of its slow zoom and drift."""
    from PIL import Image

    zoom = 1 + ZOOM * (_ease(progress) if way % 2 == 0 else 1 - _ease(progress))
    crop_w, crop_h = base.width / zoom, base.height / zoom
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


def draw_frame(
    plan: Plan,
    bases: Sequence[Any],
    painter: _Painter,
    at: float,
) -> Any:
    """The whole picture at one moment of the video."""
    from PIL import Image, ImageDraw

    size = SIZES.get(plan.size, SIZES["720p"])
    index = 0
    for number, shot in enumerate(plan.shots):
        if at >= shot.start:
            index = number
    shot = plan.shots[index]
    progress = (at - shot.start) / max(0.1, shot.length)
    frame = _moving(bases[index], size, progress, index + plan.seed)
    if index > 0 and at - shot.start < FADE:
        previous = plan.shots[index - 1]
        before = _moving(
            bases[index - 1],
            size,
            (at - previous.start) / max(0.1, previous.length),
            index - 1 + plan.seed,
        )
        frame = Image.blend(before, frame, (at - shot.start) / FADE)
    overlay = painter.frame_overlay(plan.handle)
    frame.paste(overlay, (0, 0), overlay)
    if at < HOOK_SECONDS and plan.hook:
        _paste(frame, painter.banner(plan.hook, big=True))
    elif shot.label:
        _paste(frame, painter.banner(shot.label, big=False))
    showing = _active(plan.chunks, at)
    if showing is not None:
        chunk_id, word = showing
        _paste(frame, painter.caption(chunk_id, plan.chunks[chunk_id], word))
    width, height = size
    done = int(width * min(1.0, at / max(0.1, plan.duration)))
    bar = max(4, height // 240)
    ImageDraw.Draw(frame).rectangle(
        (0, height - bar, done, height), fill=painter.look.accent
    )
    return frame


def prepare(plan: Plan) -> tuple[list[Any], _Painter]:
    """Each scene's picture, sized once, and the word painter."""
    from PIL import Image

    width, height = SIZES.get(plan.size, SIZES["720p"])
    roomy = (round(width * (1 + ZOOM)), round(height * (1 + ZOOM)))
    bases = [
        _load(shot, roomy, plan.seed + number) for number, shot in enumerate(plan.shots)
    ]
    bases = [
        base if base.size == roomy else base.resize(roomy, Image.Resampling.LANCZOS)
        for base in bases
    ]
    painter = _Painter(LOOK_STYLES.get(plan.look, LOOK_STYLES["bold"]), (width, height))
    return bases, painter


def render(
    plan: Plan,
    *,
    audio: Path,
    out: Path,
    cover: Path,
    progress: Callable[[float], None] = lambda _: None,
) -> None:
    """Write the MP4 and a cover picture (runs on a thread: it is slow)."""
    ready, why = video_tools()
    if not ready:
        raise RenderError(why)
    if not plan.shots:
        raise RenderError("The script has no scenes.")
    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None
    bases, painter = prepare(plan)
    width, height = SIZES.get(plan.size, SIZES["720p"])
    cover.parent.mkdir(parents=True, exist_ok=True)
    draw_frame(plan, bases, painter, min(0.8, plan.duration / 3)).save(
        cover, "JPEG", quality=88
    )
    video = (
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]
        if _has_x264(ffmpeg)
        else ["-c:v", "mpeg4", "-q:v", "3"]
    )
    inputs = ["-i", str(audio)]
    mixing: list[str] = ["-map", "0:v", "-map", "1:a"]
    if plan.music is not None and plan.music.is_file():
        inputs += ["-stream_loop", "-1", "-i", str(plan.music)]
        mixing = [
            "-filter_complex",
            "[2:a]volume=0.16[m];[1:a][m]amix=inputs=2:duration=first[a]",
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
        str(FPS),
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
    frames = max(1, round(plan.duration * FPS))
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
            raise RenderError(f"ffmpeg would not start: {error}") from error
        assert process.stdin is not None
        try:
            for number in range(frames):
                frame = draw_frame(plan, bases, painter, number / FPS)
                process.stdin.write(frame.tobytes())
                if number % 15 == 0:
                    progress(number / frames)
        except BrokenPipeError, OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                process.stdin.close()
            try:
                process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        log.seek(0)
        errors = log.read()[-2_000:]
    if process.returncode != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        detail = (errors or b"").decode("utf-8", "replace").strip()[-400:]
        raise RenderError(f"ffmpeg could not make the video: {detail or 'no reason'}")
    partial.replace(out)
    progress(1.0)
