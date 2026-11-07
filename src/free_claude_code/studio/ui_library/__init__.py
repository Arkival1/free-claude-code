"""The UI library: 3,802 ready-made pieces of web design from Uiverse (MIT).

Buttons, cards, forms, inputs, toggles, checkboxes, radios, loaders,
tooltips, notifications and backgrounds, each a small block of HTML and CSS
made by a Uiverse designer. The Builder and Coder search it by kind and tag,
copy one into a site, and restyle it. The pieces ship with FCC
(`uiverse.json.gz`, see `vendor/uiverse/`), so nothing is downloaded.
"""

import gzip
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "uiverse.json.gz"
KINDS = (
    "button",
    "card",
    "checkbox",
    "form",
    "input",
    "notification",
    "background",
    "radio",
    "toggle",
    "tooltip",
    "loader",
)
MAX_RESULTS = 12
_KIND_WORDS = {
    "buttons": "button",
    "cards": "card",
    "checkboxes": "checkbox",
    "forms": "form",
    "inputs": "input",
    "notifications": "notification",
    "toast": "notification",
    "alert": "notification",
    "backgrounds": "background",
    "pattern": "background",
    "patterns": "background",
    "radios": "radio",
    "toggles": "toggle",
    "switch": "toggle",
    "switches": "toggle",
    "tooltips": "tooltip",
    "loaders": "loader",
    "spinner": "loader",
    "spinners": "loader",
}


@dataclass(frozen=True, slots=True)
class Piece:
    id: str
    kind: str
    author: str
    name: str
    tags: str
    tailwind: bool
    """Styled with Tailwind classes, not its own CSS (needs Tailwind)."""
    script: bool
    html: str

    @property
    def plain(self) -> bool:
        """Plain HTML and CSS: drops into any site as it is."""
        return not self.tailwind and not self.script


class UiLibraryError(ValueError):
    """A search or a piece the library can't give; the message says why."""


@cache
def pieces() -> tuple[Piece, ...]:
    rows = json.loads(gzip.decompress(DATA.read_bytes()))
    return tuple(Piece(**row) for row in rows)


@cache
def _by_id() -> dict[str, Piece]:
    return {piece.id: piece for piece in pieces()}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def kind_of(text: str) -> str:
    """The kind a word names ('switch' is a toggle), or ''."""
    word = text.strip().casefold()
    return word if word in KINDS else _KIND_WORDS.get(word, "")


def search(
    query: str = "",
    *,
    kind: str = "",
    count: int = 6,
    plain_only: bool = True,
) -> list[Piece]:
    """The pieces that best match the words, plain CSS first.

    Each word counts once for a tag, the name or the designer, so 'glass
    card' prefers a card tagged glass. A kind word in the query ('toggle',
    'spinner') narrows the kind when none is given.
    """
    wanted_kind = kind_of(kind) if kind else ""
    if kind and not wanted_kind:
        raise UiLibraryError(f"No kind called {kind!r}. Kinds: {', '.join(KINDS)}.")
    words = _words(query)
    if not wanted_kind:
        for word in words:
            if kind_of(word):
                wanted_kind = kind_of(word)
                break
    # Kind words choose the kind; they aren't tags to match.
    words = [word for word in words if not kind_of(word)]
    count = max(1, min(MAX_RESULTS, count))
    scored: list[tuple[int, int, str, Piece]] = []
    for piece in pieces():
        if wanted_kind and piece.kind != wanted_kind:
            continue
        if plain_only and not piece.plain:
            continue
        tags = set(_words(piece.tags))
        name = set(_words(piece.name))
        author = set(_words(piece.author))
        score = 0
        for word in words:
            if word in tags:
                score += 3
            elif any(tag.startswith(word) for tag in tags):
                score += 2
            elif word in name or word in author:
                score += 1
        if words and not score:
            continue
        # Tagged pieces first: their tags say what they are.
        scored.append((-score, -len(tags), piece.id, piece))
    scored.sort(key=lambda item: item[:3])
    return [item[3] for item in scored[:count]]


CREDIT = re.compile(r"/\*\s*From Uiverse\.io by[^*]*\*/")


def credit(item: Piece) -> str:
    """The designer's credit comment, as the piece has it."""
    found = CREDIT.search(item.html)
    return found.group(0) if found else f"/* From Uiverse.io by {item.author} */"


def piece(piece_id: object) -> Piece:
    found = _by_id().get(str(piece_id or "").strip())
    if found is None:
        raise UiLibraryError(
            f"No piece called {piece_id!r}. Use an id from a ui_library search."
        )
    return found


def summary() -> dict[str, int]:
    """How many pieces of each kind, and how many are plain CSS."""
    counts = dict.fromkeys(KINDS, 0)
    for item in pieces():
        counts[item.kind] += 1
    counts["plain"] = sum(item.plain for item in pieces())
    counts["all"] = len(pieces())
    return counts
