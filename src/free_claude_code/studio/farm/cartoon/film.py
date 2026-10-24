"""The cartoon, filmed into a video's frames.

A tall short (9:16) shows the 16:9 cartoon as a panel a little above the
middle, on a textured board (wooden planks, by default), with the series
title in a white box above it and the narration one word at a time on the
panel, like the big storytime cartoon accounts. A wide video is the cartoon
on its own. Cartoons move "on twos" (15 drawings a second, each shown twice),
as hand-made animation does: it looks right and halves the drawing.
"""

import bisect
from dataclasses import dataclass
from typing import Any

from ..timing import Word
from .scene import CartoonShot, paint
from .stages import board, panel_box, title_box

DRAWINGS_PER_SECOND = 15


@dataclass(frozen=True, slots=True)
class Scene:
    shot: CartoonShot
    start: float
    length: float


@dataclass(frozen=True, slots=True)
class Film:
    scenes: tuple[Scene, ...]
    words: tuple[Word, ...]
    duration: float
    size: tuple[int, int]
    title: str = ""
    texture: str = "wood"
    captions: bool = True
    fps: int = 30

    @property
    def tall(self) -> bool:
        return self.size[1] > self.size[0]


class CartoonFrames:
    """Frames of a cartoon, drawn in any order (a drawing is kept for its
    second frame)."""

    def __init__(self, film: Film) -> None:
        self.film = film
        width, height = film.size
        if film.tall:
            left, top, right, bottom = panel_box(width, height)
            self._panel = (left, top, right - left, bottom - top)
        else:
            self._panel = (0, 0, width, height)
        self._starts = [scene.start for scene in film.scenes]
        self._word_starts = [word.start for word in film.words]
        self._kept: tuple[tuple[int, int], Any] | None = None
        self._captions: dict[str, Any] = {}

    def close(self) -> None:
        self._kept = None

    def _cartoon(self, at: float) -> Any:
        index = max(0, bisect.bisect_right(self._starts, at) - 1)
        scene = self.film.scenes[index]
        drawing = int((at - scene.start) * DRAWINGS_PER_SECOND)
        key = (index, drawing)
        if self._kept is None or self._kept[0] != key:
            _, _, width, height = self._panel
            picture = paint(
                scene.shot, drawing / DRAWINGS_PER_SECOND, scene.length, (width, height)
            )
            self._kept = (key, picture)
        return self._kept[1]

    def _word(self, at: float) -> str:
        place = bisect.bisect_right(self._word_starts, at) - 1
        if place < 0:
            return ""
        word = self.film.words[place]
        following = (
            self.film.words[place + 1].start
            if place + 1 < len(self.film.words)
            else word.end + 0.3
        )
        return word.text if at < max(word.end, following) else ""

    def _caption(self, text: str) -> Any:
        if text not in self._captions:
            from PIL import Image, ImageDraw

            from ..render import _HEAVY, _font

            _, _, _, height = self._panel
            font = _font(
                _HEAVY, max(16, int(height * (0.1 if self.film.tall else 0.085)))
            )
            shown = text.upper().strip("\"'")
            stroke = max(2, font.size // 8)
            box = (
                int(font.getlength(shown) + stroke * 4),
                int(sum(font.getmetrics()) + stroke * 4),
            )
            layer = Image.new("RGBA", box, (0, 0, 0, 0))
            ImageDraw.Draw(layer).text(
                (stroke * 2, stroke * 2),
                shown,
                font=font,
                fill=(255, 255, 255),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0),
            )
            if len(self._captions) > 400:
                self._captions.clear()
            self._captions[text] = layer
        return self._captions[text]

    def draw(self, at: float) -> Any:
        film = self.film
        width, height = film.size
        left, top, panel_w, panel_h = self._panel
        cartoon = self._cartoon(at)
        if film.tall:
            frame = board(film.texture, width, height).copy()
            frame.paste(cartoon, (left, top))
            if film.title:
                label = title_box(film.title, width)
                frame.paste(
                    label,
                    (
                        (width - label.width) // 2,
                        max(0, top - label.height - height // 90),
                    ),
                    label,
                )
        else:
            frame = cartoon.copy()
        if film.captions:
            word = self._word(at)
            if word:
                layer = self._caption(word)
                x = left + (panel_w - layer.width) // 2
                y = top + int(panel_h * 0.8) - layer.height // 2
                frame.paste(layer, (x, y), layer)
        return frame
