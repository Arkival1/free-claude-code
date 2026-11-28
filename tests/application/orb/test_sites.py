import json

import pytest

from free_claude_code.application.orb.sites import (
    SiteError,
    SiteStore,
    original_palette,
    render_site,
)
from free_claude_code.application.orb.sites.library import (
    PALETTES,
    SECTION_KINDS,
    STARTERS,
)
from free_claude_code.application.orb.sites.palette import HARMONIES, contrast


def test_every_starter_renders_every_section():
    store_spec = {"theme": {}, "sections": []}
    for starter in STARTERS.values():
        page = render_site({"name": "X", **starter})
        assert page.startswith("<!doctype html>") and "<script" not in page
    for kind, info in SECTION_KINDS.items():
        for variant in info["variants"]:
            store_spec["sections"] = [{"kind": kind, "variant": variant, "fields": {}}]
            assert "Traceback" not in render_site(store_spec)


def test_text_is_escaped_and_links_are_safe():
    spec = {
        "name": "<b>x</b>",
        "theme": {},
        "sections": [
            {
                "kind": "hero",
                "variant": "split",
                "fields": {
                    "title": "<script>alert(1)</script>",
                    "button": "Go",
                    "button_link": "javascript:alert(1)",
                    "image_url": "javascript:x",
                },
            },
            {
                "kind": "footer",
                "variant": "simple",
                "fields": {
                    "text": "A&B",
                    "links": [
                        ["Bad", "data:text/html,hi"],
                        ["Ok", "https://ok.example"],
                    ],
                },
            },
        ],
    }
    page = render_site(spec)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "javascript:" not in page and "data:text/html" not in page
    assert 'href="https://ok.example"' in page and "A&amp;B" in page


@pytest.mark.parametrize("harmony", HARMONIES)
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_original_palettes_stay_readable(harmony, mode):
    for base in ("#2d5a3d", "#ffcc00", "#1d6fa5", "#c2412d", "#777777"):
        p = original_palette(base, harmony, mode)
        assert contrast(p["text"], p["bg"]) >= 7
        assert contrast(p["muted"], p["bg"]) >= 4.5
        assert contrast(p["primary"], p["bg"]) >= 3
        assert contrast(p["on_primary"], p["primary"]) >= 3
    with pytest.raises(ValueError):
        original_palette("red")


def test_built_in_palettes_have_readable_text():
    for name, p in PALETTES.items():
        assert contrast(p["text"], p["bg"]) >= 7, name
        assert contrast(p["on_primary"], p["primary"]) >= 3, name


def test_store_create_edit_clean_and_export(tmp_path):
    store = SiteStore(tmp_path)
    spec = store.create("Rosa's Pizzeria", "restaurant", "Wood-fired pizza")
    assert (
        spec["slug"] == "rosa-s-pizzeria"
        and spec["sections"][0]["fields"]["brand"] == "Rosa's Pizzeria"
    )
    assert (
        next(s for s in spec["sections"] if s["kind"] == "hero")["fields"]["subtitle"]
        == "Wood-fired pizza"
    )
    with pytest.raises(SiteError, match="already exists"):
        store.create("Rosa's Pizzeria")
    with pytest.raises(SiteError, match="reserved"):
        store.create("Library")
    store.edit_section(
        "rosa-s-pizzeria",
        "menu",
        {"items": [["Pizza", "Margherita", "9.50", "", "extra column"]]},
    )
    assert store.get("rosa-s-pizzeria")["sections"][3]["fields"]["items"] == [
        ["Pizza", "Margherita", "9.50", ""]
    ]
    added = store.add_section("rosa-s-pizzeria", "services")
    assert (
        store.get("rosa-s-pizzeria")["sections"][added["index"] + 1]["kind"] == "footer"
    )
    store.remove_section("rosa-s-pizzeria", "gallery")
    with pytest.raises(SiteError, match="This site has"):
        store.edit_section("rosa-s-pizzeria", "gallery", {})
    theme = store.set_theme(
        "rosa-s-pizzeria", radius=999, font="Not A Font", palette="Graphite"
    )
    assert (
        theme["radius"] == 40
        and theme["font"] == "Editorial"
        and theme["palette"] == "Graphite"
    )
    messy = store.clean(
        {
            "sections": [
                {"kind": "hack"},
                {"kind": "hero", "variant": "weird", "fields": {"title": 5}},
            ]
        }
    )
    assert [s["kind"] for s in messy["sections"]] == ["hero"] and messy["sections"][0][
        "variant"
    ] == "centered"
    out = store.export("rosa-s-pizzeria")
    assert (
        (tmp_path / "export" / "rosa-s-pizzeria" / "index.html")
        .read_text()
        .startswith("<!doctype html>")
    )
    assert out["html"].count("<section") >= 5
    assert [s["slug"] for s in store.sites()] == ["rosa-s-pizzeria"]


def test_only_free_licence_designs_are_accepted(tmp_path):
    store = SiteStore(tmp_path)
    palette = {"bg": "#ffffff", "text": "#111111", "primary": "#2a7f6f"}
    for bad in ("All rights reserved", "CC-BY-NC", "", "proprietary"):
        with pytest.raises(SiteError, match="free licence"):
            store.add_design("palette", "X", palette, "https://example.org", bad)
    with pytest.raises(SiteError, match="source_url"):
        store.add_design("palette", "X", palette, "not a url", "CC0")
    with pytest.raises(SiteError, match="hex colours"):
        store.add_design("palette", "X", {"bg": "red"}, "https://example.org", "MIT")
    store.add_design("palette", "Sea Glass", palette, "https://example.org/p", "cc0")
    store.add_design(
        "preset",
        "Cafe Lite",
        {"sections": ["nav", "hero", "menu", "evil", "footer"], "theme": {"radius": 4}},
        "https://example.org/l",
        "MIT",
    )
    lib = store.library()
    assert (
        "Sea Glass" in lib["palettes"]
        and lib["credits"]["palettes:Sea Glass"]["licence"] == "CC0"
    )
    spec = store.create("Cafe Two", "restaurant", preset="Cafe Lite")
    assert [s["kind"] for s in spec["sections"]] == [
        "nav",
        "hero",
        "menu",
        "footer",
    ] and spec["theme"]["radius"] == 4
    assert (
        json.loads((tmp_path / "library.json").read_text())["presets"]["Cafe Lite"][
            "sections"
        ][-1]
        == "footer"
    )
