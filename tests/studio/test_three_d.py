"""Studio's 3D views: three.js kept byte for byte, scripts sent compressed
with the right types, and the Ops page's one light reading."""

import gzip
import hashlib
from pathlib import Path
from typing import Any

import httpx
import pytest

from free_claude_code.api.studio_routes import STATIC_DIR
from free_claude_code.core.version import package_version
from tests.api.support import create_test_app

ROOT = Path(__file__).resolve().parents[2]
SERVED = {
    "build/three.module.js": "three.module.js",
    "build/three.core.js": "three.core.js",
    "examples/jsm/controls/OrbitControls.js": "three-orbit.js",
}


def data(value: object) -> Any:
    return value


def test_three_is_vendored_with_its_licence_and_checksums():
    root = ROOT / "vendor" / "three"
    assert "The MIT License" in (root / "LICENSE").read_text()
    readme = (root / "README.md").read_text()
    assert "three@0.186.1" in readme and "9b4a2ac29c63" in readme
    sums: dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        sums[name] = digest
    assert "three-0.186.1.tgz" in sums
    for upstream, served in SERVED.items():
        digest = hashlib.sha256((STATIC_DIR / served).read_bytes()).hexdigest()
        assert sums[upstream] == digest, served
    assert "three/" in (ROOT / "vendor" / "README.md").read_text()


def test_the_page_maps_three_to_studios_copy():
    page = (STATIC_DIR / "index.html").read_text()
    assert '"three": "/studio/assets/__FCC_VERSION__/three.module.js"' in page
    assert page.index('type="importmap"') < page.index("<script src=")
    assert "from './three.core.js'" in (STATIC_DIR / "three.module.js").read_text()


@pytest.mark.asyncio
async def test_scripts_go_compressed_with_their_types(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    version = package_version()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            core = await client.get(f"/studio/assets/{version}/three.core.js")
            assert core.status_code == 200
            assert core.headers["content-encoding"] == "gzip"
            assert core.headers["content-type"].startswith("text/javascript")
            assert core.content == (STATIC_DIR / "three.core.js").read_bytes()
            assert int(core.headers["content-length"]) < len(core.content) / 3

            again = await client.get(
                f"/studio/assets/{version}/three.core.js",
                headers={"if-none-match": core.headers["etag"]},
            )
            assert again.status_code == 304

            plain = await client.get(
                f"/studio/assets/{version}/trade3d.js",
                headers={"accept-encoding": "identity"},
            )
            assert "content-encoding" not in plain.headers
            assert plain.headers["content-type"].startswith("text/javascript")
            assert "FCCTradeArena" in plain.text

            icon = await client.get(f"/studio/assets/{version}/icon-180.png")
            assert "content-encoding" not in icon.headers
            for name in ("fcc3d.js", "ops3d.js", "three-orbit.js", "ops.js", "ops.css"):
                found = await client.get(f"/studio/assets/{version}/{name}")
                assert found.status_code == 200, name
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


def test_compressed_bytes_are_real_gzip():
    from free_claude_code.api.studio_routes import _gzipped

    path = STATIC_DIR / "ops.css"
    body, etag = _gzipped(path, path.stat().st_mtime_ns)
    assert gzip.decompress(body) == path.read_bytes()
    assert etag.startswith('"') and etag.endswith('"')


@pytest.mark.asyncio
async def test_the_ops_page_reads_the_whole_pc_at_once(make_studio):
    studio, _ = make_studio([], STUDIO_LOW_POWER=True)
    await studio.ensure_defaults()
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            ops = data((await client.get("/studio/api/ops")).json())
            assert {"cpu", "memory", "cores", "gpus"} <= set(ops["machine"])
            lanes = {lane["name"]: lane for lane in ops["workers"]["lanes"]}
            assert {"web", "data", "model_local", "model_server", "cpu"} <= set(lanes)
            assert lanes["model_local"]["limit"] == 1
            assert ops["workers"]["low_power"] is True and ops["low_power"] is True
            assert ops["agents"] and all("busy" in agent for agent in ops["agents"])
            assert set(ops["turns"]) == {"working", "waiting"}
            assert ops["trading"]["mode"] == "paper"

            desk = data((await client.get("/studio/api/trading")).json())
            assert desk["low_power"] is True
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
