"""AI-painted art for the cartoon: places and characters from the image engine.

A place is painted once from the screenplay's own words ("a rooftop over the
city at night") and kept. A character is painted once, full body, on a plain
background and cut out; their talking mouth and their feelings are the same
picture changed a little (img2img), so they look the same in every shot. A
talking mouth only takes the changed mouth from its picture, so nothing else
flickers while they speak. Everything is kept on disk by what it was made
from, so the next video reuses it.
"""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLACE_SIZE = (1344, 768)
"""Wide pictures for places (SDXL's 16:9-ish size)."""
SPRITE_SIZE = (832, 1216)
"""Tall pictures for characters, standing full height."""
FEELINGS = ("happy", "angry", "sad", "scared", "surprised")
FEELING_WORDS = {
    "happy": "big happy smile",
    "angry": "angry, furrowed brows, clenched teeth",
    "sad": "sad, teary eyes, frown",
    "scared": "scared, wide eyes, worried",
    "surprised": "surprised, open mouth, raised eyebrows",
}
TALK_WORDS = "open mouth, talking"
VARIANT_STRENGTH = 0.42
TALK_STRENGTH = 0.32
PLACE_TAIL = (
    "no humans, scenery, wide establishing shot, animation background art, "
    "vibrant colors, colorful, rich saturated palette, clean lines"
)
SPRITE_TAIL = (
    "solo, full body, standing, three-quarter view, simple background, "
    "plain white background, character turnaround"
)


class ArtError(RuntimeError):
    """A picture couldn't be painted (the engine is missing or failed)."""


type Paint = Callable[
    [str, tuple[int, int], int, Path, Path | None, float], Awaitable[Path]
]
"""paint(prompt, size, seed, out, start_from, strength) -> the picture."""


def _key(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def _words(text: str, limit: int = 300) -> str:
    return " ".join(re.sub(r"[<>{}\[\]]", " ", text or "").split())[:limit]


def character_prompt(name: str, description: str, details: str = "") -> str:
    """What to paint for a character: who they are and how they look."""
    about = _words(description) or _words(name)
    extra = _words(details, 200)
    return ", ".join(x for x in (about, extra, SPRITE_TAIL) if x)


def place_prompt(place: str) -> str:
    return f"{_words(place, 200)}, {PLACE_TAIL}"


@dataclass(frozen=True, slots=True)
class Sprites:
    """A character's cut-out pictures (RGBA PNGs)."""

    base: Path
    talk: Path | None = None
    feelings: tuple[tuple[str, Path], ...] = ()

    def for_feeling(self, feeling: str) -> Path:
        return dict(self.feelings).get(feeling, self.base)


class ArtBook:
    """Where painted places and characters are kept, and how they are made."""

    def __init__(self, folder: Path, style: str, paint: Paint) -> None:
        self.folder = folder / style
        self._paint = paint

    async def place(self, place: str, seed: int = 7) -> Path:
        prompt = place_prompt(place)
        out = self.folder / "places" / f"{_key(prompt, str(seed))}.png"
        if not out.is_file():
            await self._paint(prompt, PLACE_SIZE, seed, out, None, 1.0)
            polish(out, colour=1.0)
        return out

    async def character(
        self,
        name: str,
        description: str,
        details: str = "",
        *,
        feelings: tuple[str, ...] = FEELINGS,
        report: Callable[[str], Awaitable[None]] | None = None,
    ) -> Sprites:
        prompt = character_prompt(name, description, details)
        seed = int(_key(name.lower())[:6], 16) % 100_000
        folder = self.folder / "characters" / _key(prompt, str(seed))
        painted = folder / "painted.png"
        if not painted.is_file():
            if report:
                await report(f"Painting {name}")
            await self._paint(prompt, SPRITE_SIZE, seed, painted, None, 1.0)
            polish(painted)
        base = folder / "base.png"
        if not base.is_file():
            cut_out(painted, base)
        talk = folder / "talk.png"
        if not talk.is_file():
            if report:
                await report(f"Painting {name} talking")
            changed = folder / "talk-painted.png"
            await self._paint(
                f"{prompt}, {TALK_WORDS}",
                SPRITE_SIZE,
                seed,
                changed,
                painted,
                TALK_STRENGTH,
            )
            polish(changed)
            mouth_only(painted, changed, base, talk)
        kept: list[tuple[str, Path]] = []
        for feeling in feelings:
            out = folder / f"{feeling}.png"
            if not out.is_file():
                if report:
                    await report(f"Painting {name} ({feeling})")
                changed = folder / f"{feeling}-painted.png"
                await self._paint(
                    f"{prompt}, {FEELING_WORDS[feeling]}",
                    SPRITE_SIZE,
                    seed,
                    changed,
                    painted,
                    VARIANT_STRENGTH,
                )
                polish(changed)
                cut_out(changed, out)
            kept.append((feeling, out))
        (folder / "about.json").write_text(
            json.dumps({"name": name, "prompt": prompt, "seed": seed}), encoding="utf-8"
        )
        return Sprites(base=base, talk=talk, feelings=tuple(kept))


def polish(path: Path, colour: float = 1.18) -> Path:
    """Crisper ink and fuller colour, as on TV: fast painting (few steps,
    a squeezed model) comes out a little washed and soft. Places, painted
    with the full recipe, only need the crisper ink (colour=1)."""
    from PIL import Image, ImageEnhance, ImageFilter

    with Image.open(path) as opened:
        picture = opened.convert("RGB")
    if colour != 1:
        picture = ImageEnhance.Color(picture).enhance(colour)
    picture = ImageEnhance.Contrast(picture).enhance(1.08)
    picture = picture.filter(
        ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2)
    )
    picture.save(path)
    return path


# ------------------------------------------------------------- cutting out


def cut_out(painted: Path, out: Path) -> Path:
    """The character with the plain background around them made clear.

    The background is whatever flat colour touches the picture's edge; it
    is cleared from the edges inward (so white eyes and teeth stay), and
    the cut edge is softened by a pixel."""
    from PIL import Image, ImageFilter

    with Image.open(painted) as opened:
        picture = opened.convert("RGB")
    keep = _subject(picture)
    alpha = Image.fromarray(keep.astype("uint8") * 255)
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    cut = picture.convert("RGBA")
    cut.putalpha(alpha)
    cut = cut.crop(_box(keep, picture.size))
    out.parent.mkdir(parents=True, exist_ok=True)
    cut.save(out)
    return out


def _subject(picture: Any, tolerance: int = 28) -> Any:
    """True where the character is: everything but the edge-touching
    background colour."""
    import numpy as np

    pixels = np.asarray(picture).astype(np.int16)
    border = np.concatenate(
        [pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]]
    ).reshape(-1, 3)
    background = np.median(border, axis=0)
    close = np.abs(pixels - background).max(axis=2) <= tolerance
    return ~_touching_edge(close)


def _box(keep: Any, size: tuple[int, int]) -> tuple[int, int, int, int]:
    import numpy as np

    rows = np.where(keep.any(axis=1))[0]
    cols = np.where(keep.any(axis=0))[0]
    if rows.size == 0:
        return (0, 0, *size)
    return (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)


def _touching_edge(mask: Any) -> Any:
    """The parts of a True/False mask connected to the picture's edge."""
    import numpy as np
    from PIL import Image, ImageDraw

    # A copy: an image made from an array shares it read-only.
    work = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8)).copy()
    width, height = work.size
    edge = [(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
    edge += [(0, y) for y in range(height)] + [(width - 1, y) for y in range(height)]
    pixels = work.load()
    assert pixels is not None
    for point in edge:
        if pixels[point] == 255:
            ImageDraw.floodfill(work, point, 128, thresh=0)
    return np.asarray(work) == 128


def mouth_only(painted: Path, talking: Path, base: Path, out: Path) -> Path:
    """The base cut-out with only the mouth taken from the talking picture.

    The mouth is the biggest change in the face (the top quarter of the
    character); everything else stays the base picture's, so swapping
    between the two while speaking moves only the mouth."""
    import numpy as np
    from PIL import Image, ImageFilter

    with Image.open(painted) as a, Image.open(talking) as b, Image.open(base) as c:
        before = a.convert("RGB")
        after = b.convert("RGB").resize(before.size)
        cut = c.convert("RGBA")
    keep = _subject(before)
    box = _box(keep, before.size)
    diff = np.abs(np.asarray(before, np.int16) - np.asarray(after, np.int16)).max(
        axis=2
    )
    face = np.zeros_like(keep)
    top, bottom = box[1], box[3]
    face[top : top + max(1, (bottom - top) // 4)] = True
    region = _biggest_blob((diff > 40) & face & keep)
    if region is None:
        cut.save(out)
        return out
    mask = Image.fromarray((region * 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
    merged = before.copy()
    merged.paste(after, (0, 0), mask)
    result = merged.crop(box).convert("RGBA")
    result.putalpha(cut.getchannel("A"))
    result.save(out)
    return out


def _biggest_blob(mask: Any) -> Any:
    """The changed area without its specks (a pixel or two of noise)."""
    import numpy as np
    from PIL import Image, ImageFilter

    work = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8))
    work = work.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    cleaned = np.asarray(work) > 128
    return cleaned if cleaned.sum() >= 30 else None
