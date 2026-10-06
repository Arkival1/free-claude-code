"""Music edits: clips cut on the beat of a song, with the lyrics on screen.

The way fan edits are made: every cut lands on a beat, the big hits punch in
(a quick zoom), flash white, or shake. A key word of the lyrics is spelled
out huge, letter by letter, in tall thin letters in the edit's colour, while
the line being sung builds up word by word in small white letters across the
middle.
"""

import bisect
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .beats import Sung

PUNCH = 0.16
"""How far a punch zooms in, at its start."""
PUNCH_SECONDS = 0.24
FLASH_SECONDS = 0.14
SHAKE_SECONDS = 0.3
BIG_HOLD = 0.35
"""How long a big word stays after it is sung."""
_CONDENSED = (
    "BebasNeue-Regular.ttf",
    "Oswald-Regular.ttf",
    "LeagueGothic-Regular.ttf",
    "bahnschrift.ttf",
    "DejaVuSansCondensed.ttf",
    "DejaVuSans.ttf",
    "LiberationSansNarrow-Regular.ttf",
    "arial.ttf",
)
SQUEEZE = 0.66
"""Big letters are drawn this much narrower than the font: tall and thin."""


@dataclass(frozen=True, slots=True)
class EditCut:
    start: float
    end: float
    clip: Path | None = None
    image: Path | None = None
    clip_start: float = 0.0
    punch: bool = False
    flash: bool = False
    shake: bool = False


@dataclass(frozen=True, slots=True)
class EditPlan:
    cuts: tuple[EditCut, ...]
    phrases: tuple[tuple[Sung, ...], ...]
    """The lyrics, line by line, each word timed (seconds into the edit)."""
    big: tuple[Sung, ...]
    duration: float
    size: tuple[int, int]
    theme: tuple[int, int, int] = (255, 95, 200)
    fps: int = 30
    lyrics: bool = True

    @property
    def tall(self) -> bool:
        return self.size[1] > self.size[0]


# ------------------------------------------------------------------ lyrics

_LRC = re.compile(r"\[(\d{1,2}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """Timed lyric lines ('[00:12.34] words'), as many sites give them."""
    lines: list[tuple[float, str]] = []
    for raw in text.splitlines():
        stamps = list(_LRC.finditer(raw))
        if not stamps:
            continue
        words = _LRC.sub("", raw).strip()
        for stamp in stamps:
            minutes, seconds = stamp.group(1), stamp.group(2).replace(":", ".")
            lines.append((int(minutes) * 60 + float(seconds), words))
    return sorted(lines)


def is_lrc(text: str) -> bool:
    return len(parse_lrc(text)) >= 2


def lrc_phrases(text: str, *, start: float, end: float) -> list[tuple[Sung, ...]]:
    """Timed lines, cut to the part of the song in the edit, words spread
    across each line's time."""
    lines = parse_lrc(text)
    phrases: list[tuple[Sung, ...]] = []
    for number, (at, words) in enumerate(lines):
        after = lines[number + 1][0] if number + 1 < len(lines) else at + 4.0
        split = words.split()
        if not split or after <= start or at >= end:
            continue
        span = min(after - at, 0.42 * len(split) + 0.4)
        step = span / len(split)
        phrase = tuple(
            Sung(
                word,
                round(at - start + n * step, 3),
                round(at - start + (n + 1) * step, 3),
            )
            for n, word in enumerate(split)
        )
        phrases.append(tuple(w for w in phrase if 0 <= w.start < end - start))
    return [p for p in phrases if p]


def group_phrases(words: list[Sung], text: str = "") -> list[tuple[Sung, ...]]:
    """Words into sung lines: the pasted lines when the words came from
    them, else a new line after a pause or every seven words."""
    if not words:
        return []
    sizes = [len(line.split()) for line in text.splitlines() if line.split()]
    if sizes and sum(sizes) == len(words):
        out: list[tuple[Sung, ...]] = []
        at = 0
        for size in sizes:
            out.append(tuple(words[at : at + size]))
            at += size
        return out
    phrases: list[list[Sung]] = [[]]
    for word in words:
        current = phrases[-1]
        if current and (word.start - current[-1].end > 0.6 or len(current) >= 7):
            phrases.append([])
        phrases[-1].append(word)
    return [tuple(p) for p in phrases if p]


def shift(
    phrases: list[tuple[Sung, ...]], start: float, end: float
) -> list[tuple[Sung, ...]]:
    """Song-time words made edit-time, keeping only the part in the edit."""
    out: list[tuple[Sung, ...]] = []
    for phrase in phrases:
        kept = tuple(
            Sung(w.text, round(w.start - start, 3), round(w.end - start, 3))
            for w in phrase
            if start <= w.start < end
        )
        if kept:
            out.append(kept)
    return out


# ------------------------------------------------------------------ frames


def _letters(text: str, size: int, colour: tuple[int, int, int], width: int) -> Any:
    """A big word in tall, thin letters (RGBA), no wider than `width`."""
    from PIL import Image, ImageDraw

    from .render import _font

    font = _font(_CONDENSED, size)
    while font.getlength(text) * SQUEEZE > width and size > 24:
        size = int(size * 0.9)
        font = _font(_CONDENSED, size)
    left, top, right, bottom = font.getbbox(text)
    layer = Image.new(
        "RGBA", (max(1, right - left + 8), max(1, bottom - top + 8)), (0, 0, 0, 0)
    )
    ImageDraw.Draw(layer).text(
        (4 - left, 4 - top), text, font=font, fill=(*colour, 236)
    )
    return layer.resize(
        (max(1, int(layer.width * SQUEEZE)), layer.height), Image.Resampling.LANCZOS
    )


class EditFrames:
    """Frames of a music edit, drawn in time order (clips play forward)."""

    def __init__(self, plan: EditPlan, ffmpeg: str | None) -> None:
        self.plan = plan
        self._ffmpeg = ffmpeg
        self._starts = [cut.start for cut in plan.cuts]
        self._reader: tuple[int, Any] | None = None
        self._pictures: dict[int, Any] = {}
        self._cache: dict[tuple[object, ...], Any] = {}
        self._full_size: tuple[int, int] | None = None

    def close(self) -> None:
        if self._reader is not None:
            self._reader[1].close()
            self._reader = None

    def _shot(self, index: int, at: float) -> Any:
        from PIL import Image

        from .render import _ClipReader, _fit, art_card

        cut = self.plan.cuts[index]
        size = self.plan.size
        if cut.clip is not None and self._ffmpeg is not None:
            if self._reader is None or self._reader[0] != index:
                self.close()
                reader = _ClipReader(
                    self._ffmpeg,
                    cut.clip,
                    start=cut.clip_start,
                    length=cut.end - cut.start,
                    size=size,
                    fps=self.plan.fps,
                )
                self._reader = (index, reader)
            return self._reader[1].next().copy()
        if index not in self._pictures:
            picture = None
            if cut.image is not None and cut.image.is_file():
                try:
                    with Image.open(cut.image) as opened:
                        picture = _fit(opened.convert("RGB"), size)
                except OSError:
                    picture = None
            self._pictures = {
                index: picture if picture is not None else art_card("", size, index)
            }
        return self._pictures[index].copy()

    def _big(self, at: float) -> Any:
        plan = self.plan
        starts = [w.start for w in plan.big]
        place = bisect.bisect_right(starts, at) - 1
        if place < 0:
            return None
        word = plan.big[place]
        following = plan.big[place + 1].start if place + 1 < len(plan.big) else math.inf
        if at >= min(word.end + BIG_HOLD, following):
            return None
        letters = word.text
        reveal = max(0.25, min(word.end - word.start, 0.11 * len(letters)))
        shown = letters[
            : max(1, math.ceil(len(letters) * min(1.0, (at - word.start) / reveal)))
        ]
        key = ("big", place, shown)
        if key not in self._cache:
            width, height = plan.size
            size = int(height * (0.3 if plan.tall else 0.62))
            self._cache = {k: v for k, v in self._cache.items() if k[0] != "big"}
            self._cache[key] = _letters(shown, size, plan.theme, int(width * 0.94))
        return self._cache[key]

    def _line(self, at: float) -> Any:
        plan = self.plan
        for number, phrase in enumerate(plan.phrases):
            following = (
                plan.phrases[number + 1][0].start
                if number + 1 < len(plan.phrases)
                else math.inf
            )
            if phrase[0].start - 0.05 <= at < min(phrase[-1].end + 0.6, following):
                count = sum(1 for word in phrase if word.start - 0.05 <= at)
                key = ("line", number, count)
                if key not in self._cache:
                    self._cache = {
                        k: v for k, v in self._cache.items() if k[0] != "line"
                    }
                    self._cache[key] = self._line_layer(
                        " ".join(w.text for w in phrase[:count])
                    )
                return self._cache[key]
        return None

    def _line_layer(self, text: str) -> Any:
        from PIL import Image, ImageDraw, ImageFilter

        from .render import _SANS, _font, _wrap

        width, height = self.plan.size
        font = _font(
            _SANS, max(16, int((width * 0.055) if self.plan.tall else (height * 0.07)))
        )
        lines = _wrap(text, font, int(width * 0.86))[-2:]
        ascent, descent = font.getmetrics()
        line_h = int((ascent + descent) * 1.1)
        layer = Image.new("RGBA", (width, line_h * len(lines) + 12), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for row, line in enumerate(lines):
            draw.text(
                ((width - font.getlength(line)) / 2, 6 + row * line_h),
                line,
                font=font,
                fill=(0, 0, 0, 200),
            )
        shadow = layer.filter(ImageFilter.GaussianBlur(max(2, font.size // 10)))
        draw = ImageDraw.Draw(shadow)
        for row, line in enumerate(lines):
            draw.text(
                ((width - font.getlength(line)) / 2, 6 + row * line_h),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=max(1, font.size // 22),
                stroke_fill=(30, 30, 30, 255),
            )
        return shadow

    def draw(self, at: float) -> Any:
        from PIL import Image

        plan = self.plan
        width, height = plan.size
        index = max(0, bisect.bisect_right(self._starts, at) - 1)
        cut = plan.cuts[index]
        frame = self._shot(index, at)
        into = at - cut.start
        if cut.punch and into < PUNCH_SECONDS:
            ease = 1 - (1 - into / PUNCH_SECONDS) ** 2
            scale = 1 + PUNCH * (1 - ease)
            crop_w, crop_h = width / scale, height / scale
            box = (
                (width - crop_w) / 2,
                (height - crop_h) / 2,
                (width + crop_w) / 2,
                (height + crop_h) / 2,
            )
            frame = frame.resize((width, height), Image.Resampling.BILINEAR, box=box)
        if cut.shake and into < SHAKE_SECONDS:
            rng = random.Random(int(at * plan.fps))
            fade = 1 - into / SHAKE_SECONDS
            dx = int(rng.uniform(-1, 1) * width * 0.025 * fade)
            dy = int(rng.uniform(-1, 1) * height * 0.02 * fade)
            moved = frame.resize(
                (int(width * 1.06), int(height * 1.06)), Image.Resampling.BILINEAR
            )
            left = (moved.width - width) // 2 + dx
            top = (moved.height - height) // 2 + dy
            frame = moved.crop((left, top, left + width, top + height))
        if plan.lyrics:
            big = self._big(at)
            if big is not None:
                frame.paste(
                    big, ((width - big.width) // 2, (height - big.height) // 2), big
                )
            line = self._line(at)
            if line is not None:
                frame.paste(line, (0, (height - line.height) // 2), line)
        if cut.flash and into < FLASH_SECONDS:
            white = Image.new("RGB", (width, height), (255, 255, 255))
            frame = Image.blend(frame, white, 0.75 * (1 - into / FLASH_SECONDS))
        return frame
