from pathlib import Path

from fastapi.testclient import TestClient

from free_claude_code.application.orb.sites import SiteStore
from free_claude_code.core.version import package_version
from tests.api.support import create_test_app


def client_for(tmp_path: Path, origin: str | None = None):
    app = create_test_app()
    app.state.site_store = SiteStore(tmp_path)
    headers = {"origin": origin} if origin else {}
    return TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000), headers=headers
    )


def test_site_studio_end_to_end(tmp_path):
    c = client_for(tmp_path)
    page = c.get("/orb/sites")
    assert (
        page.status_code == 200
        and f"/orb/assets/{package_version()}/sites.js" in page.text
    )
    assert c.get(f"/orb/assets/{package_version()}/sites.css").status_code == 200
    lib = c.get("/orb/api/sites/library").json()
    assert "restaurant" in lib["starters"] and "menu" in lib["sections"]
    made = c.post(
        "/orb/api/sites", json={"name": "Luigi Trattoria", "kind": "restaurant"}
    ).json()
    assert made["slug"] == "luigi-trattoria"
    assert c.get("/orb/api/sites").json()["sites"][0]["slug"] == "luigi-trattoria"
    edit = c.post(
        "/orb/api/sites/luigi-trattoria/section",
        json={"action": "edit", "which": "hero", "fields": {"title": "Ciao!"}},
    )
    assert edit.json()["fields"]["title"] == "Ciao!"
    assert (
        c.post(
            "/orb/api/sites/luigi-trattoria/section",
            json={"action": "add", "kind": "nope"},
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/orb/api/sites/luigi-trattoria/theme",
            json={"font": "Classic Serif", "radius": 3},
        ).json()["radius"]
        == 3
    )
    made_palette = c.post(
        "/orb/api/sites/palette",
        json={"base": "#2d5a3d", "harmony": "triadic", "apply_to": "luigi-trattoria"},
    ).json()
    assert made_palette["name"].startswith("Original")
    preview = c.get("/orb/site/luigi-trattoria")
    assert (
        "Ciao!" in preview.text
        and "default-src 'none'" in preview.headers["content-security-policy"]
    )
    spec = c.get("/orb/api/sites/luigi-trattoria").json()
    assert isinstance(spec["theme"]["palette"], dict)
    spec["sections"] = spec["sections"][:2]
    assert (
        len(
            c.put("/orb/api/sites/luigi-trattoria", json={"spec": spec}).json()[
                "sections"
            ]
        )
        == 2
    )
    assert (
        "<html" in c.post("/orb/api/sites/render", json={"spec": spec}).json()["html"]
    )
    out = c.post("/orb/api/sites/luigi-trattoria/export").json()
    assert Path(out["file"]).is_file()
    bad = c.post(
        "/orb/api/sites/library",
        json={
            "kind": "palette",
            "name": "X",
            "data": {"bg": "#ffffff", "text": "#000000", "primary": "#ff0000"},
            "source_url": "https://example.org",
            "licence": "All rights reserved",
        },
    )
    assert bad.status_code == 400 and "free licence" in bad.json()["detail"]
    assert c.get("/orb/api/sites/missing").status_code == 400
    feed = c.get("/orb/api/activity").json()["feed"]
    assert any("Luigi Trattoria" in f["text"] for f in feed)


def test_site_studio_is_local_only(tmp_path):
    evil = client_for(tmp_path, origin="https://evil.example")
    assert evil.post("/orb/api/sites", json={"name": "x"}).status_code == 403
    assert evil.get("/orb/sites").status_code == 403
