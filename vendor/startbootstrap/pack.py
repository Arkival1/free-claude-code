"""Pack the Start Bootstrap layouts into FCC's layouts.zip.

    python3 -I pack.py <folder of startbootstrap-* checkouts> <libs folder> <out.zip>

Each layout's built dist/ folder goes in under its name, with big photos
shrunk (ffmpeg, longest side 1600 px) and the background video re-encoded
small. Bootstrap, Bootstrap Icons, Font Awesome, Chart.js and
simple-datatables load from the project's own vendor/ folder instead of a
CDN, and Start Bootstrap's own form service is taken out (the Builder points
each form at the business's email or a form service). Files are read as data;
nothing from the checkouts is run.
"""

import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

INFO = {
    "agency": (
        "Agency",
        "One page for a studio: services, portfolio pop-ups, timeline, team, contact form",
        "business",
    ),
    "bare": ("Bare", "A clean starting page with a nav bar", "starter"),
    "blog-home": (
        "Blog home",
        "Blog front page with a featured post, cards and a sidebar",
        "blog",
    ),
    "blog-post": ("Blog post", "A single article with comments and a sidebar", "blog"),
    "business-casual": (
        "Business Casual",
        "Multi-page small business: about, products, store hours",
        "business",
    ),
    "business-frontpage": (
        "Business Frontpage",
        "Business home with a big header, features and a testimonial",
        "business",
    ),
    "clean-blog": ("Clean Blog", "Multi-page blog: home, about, post, contact", "blog"),
    "coming-soon": (
        "Coming Soon",
        "Launch page with a video background and an email signup",
        "landing",
    ),
    "creative": (
        "Creative",
        "One page for a creative business with a photo portfolio",
        "portfolio",
    ),
    "freelancer": (
        "Freelancer",
        "One page for a freelancer: portfolio pop-ups, about, contact",
        "portfolio",
    ),
    "full-width-pics": (
        "Full Width Pics",
        "Story page with full-width photo sections",
        "story",
    ),
    "grayscale": ("Grayscale", "Dark one-page site with big photo sections", "landing"),
    "heroic-features": (
        "Heroic Features",
        "Big hero and a grid of feature cards",
        "landing",
    ),
    "landing-page": (
        "Landing Page",
        "Product landing page: hero signup, showcases, testimonials",
        "landing",
    ),
    "modern-business": (
        "Modern Business",
        "Multi-page business: home, about, pricing, FAQ, blog, portfolio, contact",
        "business",
    ),
    "new-age": ("New Age", "App landing page with a phone mock-up", "app"),
    "one-page-wonder": (
        "One Page Wonder",
        "Alternating photo-and-text sections",
        "story",
    ),
    "personal": (
        "Personal",
        "Personal site: home, resume, projects, contact",
        "personal",
    ),
    "resume": (
        "Resume",
        "CV site with a sidebar menu: experience, education, skills",
        "personal",
    ),
    "sb-admin": (
        "SB Admin",
        "Admin dashboard: sidebar, charts, data tables, login pages",
        "dashboard",
    ),
    "scrolling-nav": (
        "Scrolling Nav",
        "One page with smooth scrolling between sections",
        "starter",
    ),
    "shop-homepage": (
        "Shop Homepage",
        "Shop front with product cards, sale badges and ratings",
        "shop",
    ),
    "shop-item": ("Shop Item", "A product page with related products", "shop"),
    "simple-sidebar": (
        "Simple Sidebar",
        "Layout with a sidebar that slides open",
        "dashboard",
    ),
    "small-business": (
        "Small Business",
        "Small business home with a call-to-action and cards",
        "business",
    ),
    "stylish-portfolio": (
        "Stylish Portfolio",
        "Portfolio with a slide-out menu and a photo grid",
        "portfolio",
    ),
}
LIBS = {
    "vendor/bootstrap/bootstrap.bundle.min.js": "bootstrap.bundle.min.js",
    "vendor/bootstrap/LICENSE": "bootstrap-LICENSE",
    "vendor/bootstrap-icons/bootstrap-icons.css": "bootstrap-icons/bootstrap-icons.css",
    "vendor/bootstrap-icons/fonts/bootstrap-icons.woff2": "bootstrap-icons/fonts/bootstrap-icons.woff2",
    "vendor/bootstrap-icons/fonts/bootstrap-icons.woff": "bootstrap-icons/fonts/bootstrap-icons.woff",
    "vendor/bootstrap-icons/LICENSE.md": "bootstrap-icons-LICENSE",
    "vendor/fontawesome/all.js": "fontawesome-all.js",
    "vendor/fontawesome/LICENSE.txt": "fontawesome-LICENSE.txt",
    "vendor/chartjs/Chart.min.js": "chart.min.js",
    "vendor/simple-datatables/simple-datatables.min.js": "simple-datatables.min.js",
    "vendor/simple-datatables/style.min.css": "simple-datatables.min.css",
    "vendor/simple-datatables/LICENSE": "simple-datatables-LICENSE",
}
# Each layout's CDN address → the project's own copy.
SWAPS = (
    (
        r"https://cdn\.jsdelivr\.net/npm/bootstrap@[\d.]+/dist/js/bootstrap\.bundle\.min\.js",
        "vendor/bootstrap/bootstrap.bundle.min.js",
    ),
    (
        r"https://cdn\.jsdelivr\.net/npm/bootstrap-icons@[\d.]+/font/bootstrap-icons\.css",
        "vendor/bootstrap-icons/bootstrap-icons.css",
    ),
    (
        r"https://use\.fontawesome\.com/releases/v[\d.]+/js/all\.js",
        "vendor/fontawesome/all.js",
    ),
    (
        r"https://cdnjs\.cloudflare\.com/ajax/libs/Chart\.js/[\d.]+/Chart\.min\.js",
        "vendor/chartjs/Chart.min.js",
    ),
    (
        r"https://cdn\.jsdelivr\.net/npm/simple-datatables@[\d.]+/dist/umd/simple-datatables\.min\.js",
        "vendor/simple-datatables/simple-datatables.min.js",
    ),
    (
        r"https://cdn\.jsdelivr\.net/npm/simple-datatables@[\d.]+/dist/style\.min\.css",
        "vendor/simple-datatables/style.min.css",
    ),
)
SB_FORMS = re.compile(
    r'\s*<script src="https://cdn\.startbootstrap\.com/sb-forms-latest\.js"></script>'
)
SB_TOKEN = re.compile(r'\s*data-sb-form-api-token="[^"]*"')
BIG_PHOTO = 300_000


def shrink(path: Path, data: bytes) -> bytes:
    """Big photos to at most 1600 px; the background video to 720p, no sound."""
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png"} and len(data) > BIG_PHOTO:
        args = (
            ["-vf", "scale='min(1600,iw)':-2", "-q:v", "5"]
            if suffix != ".png"
            else ["-vf", "scale='min(1200,iw)':-2"]
        )
    elif suffix == ".mp4" and len(data) > 2_000_000:
        args = [
            "-vf",
            "scale=-2:720",
            "-c:v",
            "libx264",
            "-crf",
            "32",
            "-preset",
            "slow",
            "-an",
            "-movflags",
            "+faststart",
        ]
    else:
        return data
    with tempfile.TemporaryDirectory() as work:
        source, target = Path(work) / f"in{suffix}", Path(work) / f"out{suffix}"
        source.write_bytes(data)
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                *args,
                str(target),
            ],
            check=True,
        )
        smaller = target.read_bytes()
    return smaller if len(smaller) < len(data) else data


def main() -> None:
    checkouts, libs, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    catalogue = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for member, source in LIBS.items():
            bundle.writestr(
                zipfile.ZipInfo(member, (2024, 1, 1, 0, 0, 0)),
                (libs / source).read_bytes(),
                zipfile.ZIP_DEFLATED,
            )
        for layout, (name, about, kind) in INFO.items():
            dist = checkouts / layout / "dist"
            files, pages, libs_used = [], [], set()
            for path in sorted(p for p in dist.rglob("*") if p.is_file()):
                relative = path.relative_to(dist).as_posix()
                data = path.read_bytes()
                if path.suffix == ".html":
                    text = data.decode("utf-8")
                    for pattern, local in SWAPS:
                        if re.search(pattern, text):
                            libs_used.add(local.split("/")[1])
                        text = re.sub(pattern, local, text)
                    text = SB_TOKEN.sub("", SB_FORMS.sub("", text))
                    data = text.encode("utf-8")
                    pages.append(relative)
                else:
                    data = shrink(path, data)
                files.append(relative)
                bundle.writestr(
                    zipfile.ZipInfo(f"{layout}/{relative}", (2024, 1, 1, 0, 0, 0)),
                    data,
                    zipfile.ZIP_DEFLATED,
                )
            catalogue.append(
                {
                    "id": layout,
                    "name": name,
                    "about": about,
                    "kind": kind,
                    "pages": pages,
                    "files": files,
                    "libs": sorted(libs_used),
                }
            )
        bundle.writestr(
            zipfile.ZipInfo("catalogue.json", (2024, 1, 1, 0, 0, 0)),
            json.dumps(catalogue, indent=1),
            zipfile.ZIP_DEFLATED,
        )
    print(len(catalogue), "layouts", out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
