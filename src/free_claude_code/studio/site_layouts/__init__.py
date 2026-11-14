"""Website layouts: FCC's own designs and 26 from Start Bootstrap (MIT).

FCC's designs (`fcc_designs/`) are whole single pages written for FCC, one
per design style (minimalist, brutalist, soft premium, warm, boutique, trade,
game launch, personal), in plain HTML, CSS and a small shared script, with no
outside files at all.

Start Bootstrap's are landing pages, agencies, portfolios, blogs, shops, a
CV, a multi-page business site and an admin dashboard, each a built
Bootstrap 5 site. They ship in `layouts.zip` (see `vendor/startbootstrap/`)
with Bootstrap, its icons, Font Awesome, Chart.js and simple-datatables, so a
site made from one works offline and nothing is downloaded.
"""

import html
import json
import re
import zipfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "layouts.zip"
FCC_DESIGNS = Path(__file__).resolve().parent / "fcc_designs"
KINDS = (
    "business",
    "landing",
    "portfolio",
    "blog",
    "shop",
    "personal",
    "dashboard",
    "app",
    "story",
    "starter",
)
LIB_FILES = {
    "bootstrap": (
        "vendor/bootstrap/bootstrap.bundle.min.js",
        "vendor/bootstrap/LICENSE",
    ),
    "bootstrap-icons": (
        "vendor/bootstrap-icons/bootstrap-icons.css",
        "vendor/bootstrap-icons/fonts/bootstrap-icons.woff2",
        "vendor/bootstrap-icons/fonts/bootstrap-icons.woff",
        "vendor/bootstrap-icons/LICENSE.md",
    ),
    "fontawesome": ("vendor/fontawesome/all.js", "vendor/fontawesome/LICENSE.txt"),
    "chartjs": ("vendor/chartjs/Chart.min.js",),
    "simple-datatables": (
        "vendor/simple-datatables/simple-datatables.min.js",
        "vendor/simple-datatables/style.min.css",
        "vendor/simple-datatables/LICENSE",
    ),
}
"""The project's own copies of what a layout loads, by library."""
SAMPLE_NOTE = (
    "Its words are Start Bootstrap's samples (lorem ipsum, 'Start Bootstrap') "
    "and its pictures are sample photos or grey dummyimage.com boxes: replace "
    "every one with the business's own (find_images, then save_image), and "
    "point each form at the business (data-email or data-endpoint)."
)
FCC_NOTE = (
    "It is one of FCC's own designs: its words, prices and reviews are samples "
    "and its pictures are drawn shapes. Replace every one with the business's "
    "own (find_images, then save_image) and set the form's data-email."
)


class LayoutError(ValueError):
    """A layout the library doesn't have; the message says why."""


@dataclass(frozen=True, slots=True)
class Layout:
    id: str
    name: str
    about: str
    kind: str
    pages: tuple[str, ...]
    files: tuple[str, ...]
    libs: tuple[str, ...]
    source: str = "startbootstrap"
    """Where its files are: "fcc" (FCC's own designs) or "startbootstrap"."""
    style: str = ""
    """FCC designs: the design skill whose look it follows."""

    @property
    def note(self) -> str:
        return FCC_NOTE if self.source == "fcc" else SAMPLE_NOTE


def _strs(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def _rows(rows: list[dict[str, object]], source: str) -> list[Layout]:
    return [
        Layout(
            id=str(row["id"]),
            name=str(row["name"]),
            about=str(row["about"]),
            kind=str(row["kind"]),
            pages=_strs(row["pages"]),
            files=_strs(row["files"]),
            libs=_strs(row["libs"]),
            source=source,
            style=str(row.get("style", "")),
        )
        for row in rows
    ]


@cache
def layouts() -> tuple[Layout, ...]:
    """FCC's own designs first, then Start Bootstrap's."""
    ours = json.loads((FCC_DESIGNS / "catalogue.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(DATA) as bundle:
        theirs = json.loads(bundle.read("catalogue.json"))
    return (*_rows(ours, "fcc"), *_rows(theirs, "startbootstrap"))


def layout(layout_id: object) -> Layout:
    wanted = str(layout_id or "").strip().casefold().replace(" ", "-")
    for item in layouts():
        if wanted in {item.id, item.name.casefold().replace(" ", "-")}:
            return item
    raise LayoutError(
        f"No layout called {layout_id!r}. Layouts: "
        f"{', '.join(item.id for item in layouts())}."
    )


def find(kind: str = "") -> list[Layout]:
    """Every layout, or only one kind ('shop', 'blog', ...)."""
    kind = kind.strip().casefold()
    if kind and kind not in KINDS:
        raise LayoutError(f"No kind called {kind!r}. Kinds: {', '.join(KINDS)}.")
    return [item for item in layouts() if not kind or item.kind == kind]


def layout_files(item: Layout) -> dict[str, bytes]:
    """The layout's files at the project's root, plus its vendor/ copies."""
    if item.source == "fcc":
        folder = FCC_DESIGNS / item.id
        return {path: (folder / path).read_bytes() for path in item.files}
    wanted = {path: f"{item.id}/{path}" for path in item.files}
    wanted.update({path: path for lib in item.libs for path in LIB_FILES.get(lib, ())})
    with zipfile.ZipFile(DATA) as bundle:
        return {path: bundle.read(member) for path, member in wanted.items()}


_TITLE = re.compile(r"<title>[^<]*</title>")
_BRAND = re.compile(r"(<a class=\"navbar-brand[^\"]*\"[^>]*>\s*)Start Bootstrap")
_FCC_BRAND = re.compile(
    r"(<(\w+)[^>]*\bdata-brand(?:-text)?\b[^>]*>(?:<span[^>]*>[^<]*</span>)?)"
    r"[^<]*(</\2>)"
)


def name_layout(page: bytes, title: str) -> bytes:
    """Put the business's name in a page's title and logo.

    Only there: the sample sentences that mention Start Bootstrap stay, so
    check_project still asks for them to be rewritten.
    """
    name = html.escape(title.replace("<", "").replace(">", ""), quote=False)
    text = _TITLE.sub(lambda _: f"<title>{name}</title>", page.decode("utf-8"), count=1)
    text = _BRAND.sub(lambda found: found.group(1) + name, text)
    # FCC's designs mark their name with data-brand (logo) and data-brand-text.
    text = _FCC_BRAND.sub(lambda found: found.group(1) + name + found.group(3), text)
    return text.encode("utf-8")
