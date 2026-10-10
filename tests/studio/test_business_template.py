"""The multi-page business starter: five linked pages that look finished."""

import json
import re

import pytest

from free_claude_code.studio.polish import polish_notes
from free_claude_code.studio.project_check import check_project
from free_claude_code.studio.templates import STARTER_TEXT, TEMPLATES, template_files
from free_claude_code.studio.templates_business import PAGES
from free_claude_code.studio.tools import TOOL_SPEC_BY_NAME

from .conftest import tool_reply


def test_every_page_shares_the_menu_and_marks_where_you_are():
    files = template_files("business", "Cafe Luna")
    for path, name in PAGES:
        page = files[path]
        for other, _ in PAGES:
            assert f'href="{other}"' in page, (path, other)
        assert f'<a href="{path}" aria-current="page">{name}</a>' in page
        assert page.count('aria-current="page"') == 1
        assert "Cafe Luna" in page and "$" not in page.replace("$0", "")
        assert '<main id="main">' in page and 'href="#main"' in page
    assert "$0" in files["services.html"], "$$ in the template is a dollar sign"


def test_it_only_needs_real_content_and_photos():
    files = template_files("business", "Cafe Luna")
    assert polish_notes(files) == []
    problems = check_project(files)
    kinds = {
        "placeholder text"
        if "placeholder text" in problem
        else "pictures"
        if "drawn placeholders" in problem
        else "form"
        if "nowhere to send messages" in problem
        else problem
        for problem in problems
    }
    # The form needs the business's email before it can reach anyone.
    assert kinds == {"placeholder text", "pictures", "form"}

    # Filled in, it passes: no broken links, anchors, or scripts.
    finished = {}
    for path, text in files.items():
        for phrase in STARTER_TEXT:
            text = text.replace(phrase, "Real words")
        finished[path] = re.sub(r"\s*data-placeholder", "", text)
    assert check_project(finished) == []


def test_tabs_gallery_and_form_are_wired_up():
    files = template_files("business", "Cafe Luna")
    services, gallery, contact = (
        files["services.html"],
        files["gallery.html"],
        files["contact.html"],
    )
    tabs = re.findall(r'role="tab" id="(tab-\d)" aria-controls="(panel-\d)"', services)
    assert len(tabs) == 3
    for tab, panel in tabs:
        assert f'id="{panel}" aria-labelledby="{tab}"' in services
    assert services.count(" hidden>") == 2
    assert gallery.count("data-shot") == 6 and 'id="lightbox"' in gallery
    for field in ("name", "email", "phone", "date", "message"):
        assert f'id="{field}"' in contact and f'id="{field}-error"' in contact
    script = files["app.js"]
    for hook in ("[data-tabs]", "lightbox", "contact-form", "data-endpoint", ".reveal"):
        assert hook in script


def test_the_builder_is_offered_the_business_template():
    spec = TOOL_SPEC_BY_NAME["start_project"]
    offered = re.findall(r'"(\w[\w-]*)"', json.dumps(spec.parameters["properties"]))
    assert set(TEMPLATES) <= set(offered)
    assert "business" in spec.description


@pytest.mark.asyncio
async def test_start_project_writes_every_page_and_picture(make_studio):
    studio, _ = make_studio(
        [tool_reply("start_project", {"template": "business", "title": "Luna"}), "ok"]
    )
    site = await studio.create_site(name="Luna")
    builder = next(a for a in await studio.ensure_defaults() if a.name == "Builder")
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)

    await studio.send(chat.id, "Make my cafe site")

    paths = {row["path"] for row in await studio.site_files(site.id)}
    assert {path for path, _ in PAGES} <= paths
    assert {"images/hero.svg", "styles.css", "app.js"} <= paths
    hero = await studio.workspace.read(site.id, "images/hero.svg")
    assert hero.startswith("<svg")
