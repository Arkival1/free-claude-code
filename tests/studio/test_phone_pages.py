"""FCC Phone's files: served by the PC, and copied into docs/ for GitHub Pages."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from free_claude_code.api.studio_routes import PHONE_DIR
from tests.api.support import create_test_app

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def test_the_pages_copy_matches_the_app():
    """Run scripts/phone/build_pages.py after changing the phone app."""

    def files(root: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    assert files(DOCS / "phone") == files(PHONE_DIR)
    assert (DOCS / ".nojekyll").exists()
    assert "url=phone/" in (DOCS / "index.html").read_text()


def test_the_phone_has_the_pcs_web_templates():
    """Run scripts/phone/build_pages.py after changing studio/templates.py."""
    spec = importlib.util.spec_from_file_location(
        "build_pages", ROOT / "scripts" / "phone" / "build_pages.py"
    )
    assert spec is not None and spec.loader is not None
    build_pages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_pages)
    written = (PHONE_DIR / "js" / "templates.js").read_text(encoding="utf-8")
    assert written == build_pages.templates_js()
    assert '"landing"' in written and '"python-web"' not in written


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
    # FCC Linux's system packs (linux/fs/) are kept by js/linuxfiles.js, not
    # the worker (so they aren't stored twice); the worker lets them through.
    shipped = [
        str(path.relative_to(PHONE_DIR))
        for path in PHONE_DIR.rglob("*")
        if path.is_file()
        and path.suffix != ".txt"
        and path.name != "sw.js"
        and not str(path.relative_to(PHONE_DIR)).startswith("linux/fs/")
    ]
    assert '"/linux/fs/"' in worker
    for name in shipped:
        assert f'"{name}"' in worker, f"sw.js must cache {name} for offline use"


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
            script = await client.get("/phone/js/app.js")
            assert script.headers["content-type"].startswith("text/javascript")
            engine = await client.get("/phone/vendor/wllama.min.js")
            assert engine.status_code == 200 and "Wllama" in engine.text
            manifest = await client.get("/phone/manifest.webmanifest")
            assert manifest.headers["content-type"] == "application/manifest+json"
            # Godot's web player, gzipped as shipped (the phone unpacks it).
            godot = await client.get("/phone/godot/godot.wasm.gz")
            assert godot.headers["content-type"] == "application/gzip"
            assert godot.content[:2] == b"\x1f\x8b"
            for bad in (
                "/phone/secret.txt",
                "/phone/..%2Fstudio_static%2Fstudio.js",
                "/phone/../studio_static/studio.js",
                "/phone/js/../../phone_link.py",
            ):
                assert (await client.get(bad)).status_code == 404
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


def test_the_phone_carries_three_byte_for_byte_with_its_licence():
    """The Game Lab's engine on the phone is the vendored three.js r186."""
    import hashlib

    root = Path(__file__).resolve().parents[2] / "vendor" / "three"
    sums: dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        sums[name] = digest
    for name in ("three.module.js", "three.core.js"):
        digest = hashlib.sha256(
            (PHONE_DIR / "vendor" / "three" / name).read_bytes()
        ).hexdigest()
        assert sums[f"build/{name}"] == digest, name
    assert (
        "The MIT License"
        in (PHONE_DIR / "vendor" / "three" / "LICENSE.txt").read_text()
    )
    page = (PHONE_DIR / "index.html").read_text()
    assert '"three": "./vendor/three/three.module.js"' in page


def test_the_phone_lab_runs_on_the_pc_labs_tables_and_build_your_own_x():
    """Run scripts/phone/build_pages.py after changing studio/lab or the
    build-your-own-x copy; the phone's benches use the PC Lab's own tables."""
    spec = importlib.util.spec_from_file_location(
        "build_pages", ROOT / "scripts" / "phone" / "build_pages.py"
    )
    assert spec is not None and spec.loader is not None
    build_pages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_pages)
    lab = PHONE_DIR / "lab"
    assert (lab / "science-data.js").read_text(
        encoding="utf-8"
    ) == build_pages.science_js()
    assert (lab / "tutorials-data.js").read_text(
        encoding="utf-8"
    ) == build_pages.tutorials_js()
    data = build_pages.science_data()
    assert len(data["chemicals"]) > 100 and len(data["parts"]) > 40
    rows = build_pages.tutorial_rows(
        "## Tutorials\n#### Build your own `Git`\n"
        "* [**Python**: _Write yourself a Git!_](https://wyag.thb.lt/)\n"
        "* [**C**: _Chess Engine In C_](https://youtube.com/x) [video]\n"
        "## Contribute\n* [**C**: _not a tutorial_](https://x)\n"
    )
    assert rows == [
        ["Git", "Python", "Write yourself a Git!", "https://wyag.thb.lt/", ""],
        ["Git", "C", "Chess Engine In C", "https://youtube.com/x", "video"],
    ]
