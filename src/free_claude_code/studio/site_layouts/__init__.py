"""Website layouts: 26 whole-page layouts from Start Bootstrap (MIT).

Landing pages, agencies, portfolios, blogs, shops, a CV, a multi-page
business site and an admin dashboard, each a built Bootstrap 5 site. They
ship in `layouts.zip` (see `vendor/startbootstrap/`) with Bootstrap, its
icons, Font Awesome, Chart.js and simple-datatables, so a site made from one
works offline and nothing is downloaded.
"""

import html
import json
import re
import zipfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "layouts.zip"
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


@cache
def layouts() -> tuple[Layout, ...]:
    with zipfile.ZipFile(DATA) as bundle:
        rows = json.loads(bundle.read("catalogue.json"))
    return tuple(
        Layout(
            id=row["id"],
            name=row["name"],
            about=row["about"],
            kind=row["kind"],
            pages=tuple(row["pages"]),
            files=tuple(row["files"]),
            libs=tuple(row["libs"]),
        )
        for row in rows
    )


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
    wanted = {path: f"{item.id}/{path}" for path in item.files}
    wanted.update({path: path for lib in item.libs for path in LIB_FILES.get(lib, ())})
    with zipfile.ZipFile(DATA) as bundle:
        return {path: bundle.read(member) for path, member in wanted.items()}


_TITLE = re.compile(r"<title>[^<]*</title>")
_BRAND = re.compile(r"(<a class=\"navbar-brand[^\"]*\"[^>]*>\s*)Start Bootstrap")


def name_layout(page: bytes, title: str) -> bytes:
    """Put the business's name in a page's title and logo.

    Only there: the sample sentences that mention Start Bootstrap stay, so
    check_project still asks for them to be rewritten.
    """
    name = html.escape(title.replace("<", "").replace(">", ""), quote=False)
    text = _TITLE.sub(lambda _: f"<title>{name}</title>", page.decode("utf-8"), count=1)
    return _BRAND.sub(lambda found: found.group(1) + name, text).encode("utf-8")
