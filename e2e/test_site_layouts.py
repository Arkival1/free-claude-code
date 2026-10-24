"""A Start Bootstrap layout works offline in Studio's preview: Bootstrap's
menu opens from the project's own copy and nothing loads from a CDN."""

from pathlib import Path

import httpx
from playwright.sync_api import Page, expect

from free_claude_code.studio.site_layouts import layout, layout_files


def make_layout(base_url: str, tmp_path: Path, name: str) -> str:
    site = httpx.post(f"{base_url}/studio/api/sites", json={"name": name}).json()
    folder = tmp_path / "studio" / "sites" / site["id"]
    for path, data in layout_files(layout(name)).items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(data)
    return f"{base_url}/studio/sites/{site['id']}/index.html"


def test_a_layout_runs_from_its_own_files(
    page: Page, admin_base_url: str, tmp_path: Path
) -> None:
    errors: list[str] = []
    outside: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda request: (
            outside.append(request.url)
            if not request.url.startswith(("http://127.0.0.1", "data:"))
            and "fonts.g" not in request.url
            else None
        ),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(make_layout(admin_base_url, tmp_path, "agency"))
    expect(page.locator("#mainNav")).to_be_visible()
    # Bootstrap's script (from vendor/) opens the phone menu.
    page.locator(".navbar-toggler").click()
    expect(page.locator("#navbarResponsive")).to_be_visible()
    # Font Awesome (from vendor/) turned the icon tags into drawings.
    expect(page.locator("svg.svg-inline--fa").first).to_be_attached()
    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") == 0
    assert outside == [] and errors == []
