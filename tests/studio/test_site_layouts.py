"""Website layouts: 26 Start Bootstrap sites the Builder starts from."""

import hashlib
from pathlib import Path

import pytest

from free_claude_code.studio import site_layouts
from free_claude_code.studio.models import Agent
from free_claude_code.studio.project_check import check_project
from free_claude_code.studio.tools import TOOL_SPEC_BY_NAME

from .test_builder_images import builder_in_project, run

ROOT = Path(__file__).resolve().parents[2]


def test_all_26_layouts_ship_with_their_libraries_and_checksum():
    found = site_layouts.layouts()
    assert len([item for item in found if item.source == "startbootstrap"]) == 26
    assert {item.kind for item in found} <= set(site_layouts.KINDS)
    sums = (ROOT / "vendor" / "startbootstrap" / "SHA256SUMS").read_text()
    digest = hashlib.sha256(site_layouts.DATA.read_bytes()).hexdigest()
    assert f"{digest}  layouts.zip" in sums
    agency = site_layouts.layout_files(site_layouts.layout("agency"))
    assert "index.html" in agency and "vendor/bootstrap/LICENSE" in agency
    page = agency["index.html"].decode()
    # Offline: the libraries come from the project, and no outside form service.
    assert 'src="vendor/bootstrap/bootstrap.bundle.min.js"' in page
    assert "cdn.jsdelivr.net" not in page and "use.fontawesome.com" not in page
    assert "sb-forms" not in page and "data-sb-form-api-token" not in page
    # Only the dashboard brings its charts and tables.
    admin = site_layouts.layout_files(site_layouts.layout("SB Admin"))
    assert "vendor/chartjs/Chart.min.js" in admin
    assert "vendor/chartjs/Chart.min.js" not in agency


def test_layouts_are_found_by_kind_and_name():
    shops = site_layouts.find("shop")
    assert {item.id for item in shops} == {
        "boutique-shop",
        "shop-homepage",
        "shop-item",
    }
    assert site_layouts.layout("Modern Business").id == "modern-business"
    with pytest.raises(site_layouts.LayoutError, match="No layout"):
        site_layouts.layout("myspace")
    with pytest.raises(site_layouts.LayoutError, match="No kind"):
        site_layouts.find("castle")


@pytest.mark.asyncio
async def test_using_a_layout_fills_the_project_and_flags_its_samples(make_studio):
    studio, _ = make_studio([])
    site, context = await builder_in_project(studio)
    listed = await run(studio, context, "site_layouts", action="list", kind="blog")
    assert "clean-blog (blog)" in listed.text and "Pages:" in listed.text

    used = await run(
        studio,
        context,
        "site_layouts",
        action="use",
        layout="landing-page",
        title="Swell & Co",
    )
    assert not used.failed, used.text
    assert "replace every one" in used.text
    paths = {item.path for item in await studio.workspace.files(site.id)}
    assert {
        "index.html",
        "css/styles.css",
        "vendor/bootstrap/bootstrap.bundle.min.js",
    } <= paths
    assert any(path.startswith("assets/img/") for path in paths)
    # The untouched starter files the layout doesn't use are gone.
    assert "app.js" not in paths
    page = await studio.workspace.read(site.id, "index.html")
    assert "<title>Swell &amp; Co" in page and ">Swell &amp; Co</a>" in page
    files = {
        path: await studio.workspace.read(site.id, path)
        for path in ("index.html", "css/styles.css")
    }
    problems = check_project(files)
    assert any("placeholder text" in problem for problem in problems)


@pytest.mark.asyncio
async def test_a_layout_keeps_the_owners_own_work(make_studio):
    studio, _ = make_studio([])
    site, context = await builder_in_project(studio)
    await studio.workspace.write(site.id, "index.html", "<h1>Mine</h1>")
    used = await run(studio, context, "site_layouts", action="use", layout="bare")
    assert used.data["kept"] == ["index.html"]
    assert await studio.workspace.read(site.id, "index.html") == "<h1>Mine</h1>"
    wrong = await run(studio, context, "site_layouts", action="use", layout="nope")
    assert wrong.failed and "No layout" in wrong.text


@pytest.mark.asyncio
async def test_website_agents_get_the_layouts(make_studio):
    studio, _ = make_studio([])
    agents = await studio.ensure_defaults()
    builder = next(agent for agent in agents if agent.name == "Builder")
    assert "site_layouts" in builder.tools
    await studio._store.put(
        builder.model_copy(
            update={"tools": tuple(t for t in builder.tools if t != "site_layouts")}
        )
    )
    await studio.ensure_defaults()
    upgraded = await studio._store.get(Agent, builder.id)
    assert upgraded is not None and "site_layouts" in upgraded.tools
    description = TOOL_SPEC_BY_NAME["site_layouts"].description
    assert (
        "8 of FCC's own designs" in description
        and "26 from Start Bootstrap" in description
    )


def test_fccs_own_designs_are_whole_offline_pages():
    ours = [item for item in site_layouts.layouts() if item.source == "fcc"]
    assert len(ours) == 8
    ids = [item.id for item in site_layouts.layouts()]
    assert len(ids) == len(set(ids))  # no FCC design shadows a Start Bootstrap one
    for item in ours:
        assert item.kind in site_layouts.KINDS and item.style
        assert item.note == site_layouts.FCC_NOTE
        files = site_layouts.layout_files(item)
        assert set(files) == {"index.html", "styles.css", "app.js"}
        page = files["index.html"].decode()
        # Offline: no outside scripts, styles, fonts or pictures.
        assert "http://" not in page and "https://" not in page, item.id
        assert 'href="styles.css"' in page and 'src="app.js"' in page
        assert '<meta name="viewport"' in page and 'lang="en"' in page
        css = files["styles.css"].decode()
        assert ":root" in css and "@media" in css and "url(http" not in css
        # Every field is labelled and every form names where it goes.
        assert page.count("<input") + page.count("<textarea") <= page.count("<label")
        assert "data-email=" in page


def test_a_fcc_design_takes_the_business_name_everywhere():
    for item in (layout for layout in site_layouts.layouts() if layout.source == "fcc"):
        page = site_layouts.layout_files(item)["index.html"]
        named = site_layouts.name_layout(page, "Sparky & Co").decode()
        assert "<title>Sparky &amp; Co</title>" in named, item.id
        assert named.count("Sparky &amp; Co") >= 3, item.id  # title, logo, footer
        # Decorations inside the logo (an icon span) stay.
        if 'class="bolt"' in page.decode():
            assert 'class="bolt"' in named
