"""FCC Phone's files: served by the PC, and copied into docs/ for GitHub Pages."""

import json
from pathlib import Path

import httpx
import pytest

from free_claude_code.api.studio_routes import PHONE_DIR
from tests.api.support import create_test_app

DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_the_pages_copy_matches_the_app():
    """Run scripts/phone/build_pages.py after changing the phone app."""
    source = {path.name: path.read_bytes() for path in PHONE_DIR.iterdir()}
    published = {path.name: path.read_bytes() for path in (DOCS / "phone").iterdir()}
    assert published == source
    assert (DOCS / ".nojekyll").exists()
    assert "url=phone/" in (DOCS / "index.html").read_text()


def test_the_app_installs_as_its_own_home_screen_app():
    manifest = json.loads((PHONE_DIR / "manifest.webmanifest").read_text())
    assert manifest["name"] == "FCC Phone" and manifest["display"] == "standalone"
    assert manifest["start_url"] == "./" and manifest["scope"] == "./"
    page = (PHONE_DIR / "index.html").read_text()
    assert '<link rel="apple-touch-icon" sizes="180x180" href="icon-180.png" />' in page
    assert 'content="FCC Phone"' in page
    # Every link is relative, so it works at /phone/ and on GitHub Pages alike.
    assert 'href="/' not in page and 'src="/' not in page
    worker = (PHONE_DIR / "sw.js").read_text()
    for name in ("phone.js", "phone.css", "icon-180.png", "manifest.webmanifest"):
        assert f'"{name}"' in worker


@pytest.mark.asyncio
async def test_the_pc_serves_the_phone_app(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            moved = await client.get("/phone")
            assert moved.status_code == 307 and moved.headers["location"] == "/phone/"
            page = await client.get("/phone/")
            assert page.status_code == 200 and "FCC Phone" in page.text
            script = await client.get("/phone/phone.js")
            assert script.headers["content-type"].startswith("text/javascript")
            manifest = await client.get("/phone/manifest.webmanifest")
            assert manifest.headers["content-type"] == "application/manifest+json"
            for bad in ("/phone/secret.txt", "/phone/..%2Fstudio_static%2Fstudio.js"):
                assert (await client.get(bad)).status_code == 404
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
