"""The phone Builder's website tools: templates, photos, looking at the site, polish, undo."""

import io
import json
import zipfile

from playwright.sync_api import Page, Route, expect

from e2e.test_fcc_phone import (
    CORS,
    fake_gemini,
    go,
    open_phone,
    say,
    tool_call,
    use_gemini,
)
from free_claude_code.studio.polish import polish_notes
from free_claude_code.studio.templates import template_files

PHOTO = "https://live.staticflickr.com/1/cafe_b.jpg"
PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)

BAD_PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width">
<title>Bad</title><style>body{background:#fff;color:#111;margin:0}
.wide{width:900px;height:20px;background:#eee}.tiny{font-size:9px}.faint{color:#ddd}
.icon{display:inline-block;width:20px;height:20px}</style></head>
<body><h1>Bad page</h1><div class="wide">too wide</div>
<p class="tiny">fine print</p><p class="faint">pale words</p>
<button class="icon">x</button><img src="missing-photo.png" alt="gone">
<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
 alt="dot" width="200" height="50">
<script>undefinedFunction()</script></body></html>"""


def openverse(page: Page, seen: list[str] | None = None) -> None:
    def handle(route: Route) -> None:
        if seen is not None:
            seen.append(route.request.url)
        route.fulfill(
            headers=CORS,
            body=json.dumps(
                {
                    "results": [
                        {
                            "url": PHOTO,
                            "width": 1024,
                            "height": 683,
                            "title": "Cafe",
                            "creator": "Ana",
                            "license": "by",
                            "license_version": "2.0",
                        },
                        {"url": "http://insecure.example/x.jpg", "license": "by"},
                    ]
                }
            ),
        )

    page.route("https://api.openverse.org/**", handle)
    page.route(
        "https://live.staticflickr.com/**",
        lambda route: route.fulfill(body=PIXEL, headers={"Content-Type": "image/png"}),
    )


def test_templates_and_polish_match_the_pc(page: Page, admin_base_url: str) -> None:
    open_phone(page, admin_base_url)
    for name in ("business", "website", "landing", "webapp", "game"):
        files = page.evaluate(
            "([name]) => window.fccPhone.templateFiles(name, 'Cafe Luna')", [name]
        )
        assert files == template_files(name, "Cafe Luna"), name

    samples = [
        {"index.html": "<h1>Hi</h1>", "styles.css": "body{color:#111}"},
        {
            "index.html": "<header></header><img src=a.jpg><p>x</p>",
            "styles.css": (
                "body{color:#777;background:#888;font-size:11px}a{color:#123}"
                "button{color:#234}.x{color:#345;background:#456}"
            ),
        },
        template_files("landing", "Cafe Luna"),
        template_files("website", "Cafe Luna"),
        template_files("business", "Cafe Luna"),
        {
            "about.htm": "<style>:root{--ink:#eee;--bg:#fff}body{color:var(--ink);background:var(--bg)}</style>"
        },
        {"index.html": "<main>no styles</main>"},
    ]
    for files in samples:
        phone = page.evaluate("(files) => window.fccPhone.polishNotes(files)", files)
        assert phone == polish_notes(files), files


def test_look_at_site_sees_what_a_visitor_would(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    report = page.evaluate(
        """async (html) => window.fccPhone.describeLook(
            await window.fccPhone.lookAtSite({name: 'Bad', files: {'index.html': html}}))""",
        BAD_PAGE,
    )
    assert report.startswith("Looked at the site:"), report
    phone, computer = report.split("Computer (1280px wide):")
    assert "Scrolls sideways" in phone and "div.wide (900px wide)" in phone
    assert "Scrolls sideways" not in computer
    assert "Broken picture: missing-photo.png" in phone
    assert "Stretched picture: data:image/png" in phone and "200x50" in phone
    assert "Script error:" in phone and "undefinedFunction" in phone
    assert 'Tiny text: "fine print" at 9px' in phone
    assert '"pale words"' in phone and "Hard to read" in phone
    assert 'Small tap targets: "x" (20x20)' in phone
    assert "Small tap targets" not in computer, "tap size only matters on phones"
    assert 'heading "Bad page"' in phone

    # Starter templates look right, including a game that saves its best score.
    for name in ("landing", "game", "business"):
        clean = page.evaluate(
            """async ([name]) => window.fccPhone.describeLook(
                await window.fccPhone.lookAtSite({name: 'Cafe', files: window.fccPhone.templateFiles(name, 'Cafe')}))""",
            [name],
        )
        for problem in (
            "Scrolls sideways",
            "Script error",
            "Broken picture",
            "Tiny text",
            "Small tap targets",
            "Hard to read",
            "Stretched picture",
        ):
            assert problem not in clean, (name, clean)
    assert (
        page.evaluate(
            "() => window.fccPhone.lookAtSite({name: 'x', files: {'a.css': ''}})"
        )
        is None
    )


def test_photos_come_from_openverse_with_credits(
    page: Page, admin_base_url: str
) -> None:
    seen: list[str] = []
    openverse(page, seen)
    open_phone(page, admin_base_url)
    found = page.evaluate("() => window.fccPhone.findImages('  cafe  ', 3, 'wide')")
    assert found == [
        {
            "url": PHOTO,
            "width": 1024,
            "height": 683,
            "title": "Cafe",
            "credit": "Photo by Ana, CC BY 2.0",
        }
    ]
    assert "q=cafe" in seen[0] and "license_type=commercial" in seen[0]
    assert "aspect_ratio=wide" in seen[0] and "page_size=3" in seen[0]


def builder_brain(body: dict) -> dict:
    """A scripted Builder that uses the website tools in order."""
    system = body["messages"][0]["content"]
    last = body["messages"][-1]
    said = last.get("content") or ""
    if "You are Builder" not in system:
        return say("Hi!")
    if last["role"] == "user":
        return tool_call("start_project", {"name": "Cafe Luna", "template": "landing"})
    if said.startswith("Started Cafe Luna from the landing template"):
        return tool_call("find_images", {"query": "cafe", "orientation": "wide"})
    if said.startswith("1. Cafe (1024x683)"):
        return tool_call(
            "edit_file",
            {
                "path": "index.html",
                "find": "<main",
                "replace": f'<img src="{PHOTO}" alt="The cafe" width="1024" height="683">\n  <main',
            },
        )
    if said.startswith("Changed index.html"):
        return tool_call(
            "write_file", {"path": "styles.css", "content": "body { width: 2000px; }"}
        )
    if said.startswith("Wrote styles.css"):
        return tool_call("look_at_site", {})
    if said.startswith("Looked at the site") and "Scrolls sideways" in said:
        return tool_call("restore_file", {"path": "styles.css", "versions_back": 1})
    if said.startswith("Restored styles.css"):
        return tool_call("polish_check", {})
    if "polish suggestion" in said or "look finished" in said:
        return tool_call("check_project", {})
    return say("Built Cafe Luna from the landing template with a real photo.")


def test_the_builder_builds_with_templates_photos_and_a_look(
    page: Page, admin_base_url: str
) -> None:
    seen = fake_gemini(page, builder_brain)
    openverse(page)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "chat/builder")
    message = page.get_by_label("Message", exact=True)
    message.fill("Make a site for my cafe, Cafe Luna")
    message.press("Enter")
    expect(page.locator(".messages")).to_contain_text(
        "Built Cafe Luna from the landing template", timeout=20000
    )

    tools = {tool["function"]["name"] for tool in seen[0]["tools"]}
    assert {"find_images", "look_at_site", "polish_check", "restore_file"} <= tools
    start = next(
        t for t in seen[0]["tools"] if t["function"]["name"] == "start_project"
    )
    assert start["function"]["parameters"]["properties"]["template"]["enum"] == [
        "business",
        "website",
        "landing",
        "webapp",
        "game",
    ]
    results = [
        m["content"] for call in seen for m in call["messages"] if m["role"] == "tool"
    ]
    assert any("Credit: Photo by Ana, CC BY 2.0" in text for text in results)
    assert any("Scrolls sideways" in text for text in results)
    assert any(
        text.startswith("Problems in Cafe Luna") or "passed every check" in text
        for text in results
    )

    project = page.evaluate("() => window.fccPhone.state.projects[0]")
    assert project["name"] == "Cafe Luna"
    assert set(template_files("landing", "Cafe Luna")) <= set(project["files"])
    assert PHOTO in project["files"]["index.html"]
    assert (
        project["files"]["styles.css"]
        == template_files("landing", "Cafe Luna")["styles.css"]
    )
    assert len(project["history"]["styles.css"]) == 1

    go(page, "projects")
    page.get_by_role("button", name="Open Cafe Luna").click()
    preview = page.frame_locator("iframe.preview")
    expect(preview.locator("img[alt='The cafe']")).to_be_visible()
    # Drawn in its own shape, not squashed to the height attribute.
    drawn, real = preview.locator("img[alt='The cafe']").evaluate(
        "img => [img.width / img.height, img.naturalWidth / img.naturalHeight]"
    )
    assert abs(drawn - real) < 0.05


def test_older_phone_agents_get_the_new_tools_once(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    old_prompt = (
        "You build complete, good-looking websites and small apps as files in a "
        "project. Start a project with start_project if there is none, then write "
        "every file in full with write_file (index.html first, then style.css and "
        "script.js). Make pages mobile-friendly, with real content, a clear layout, "
        "and working buttons. Check your work with check_project and fix what it "
        "finds. Finish by saying what you built and which files."
    )
    upgraded = page.evaluate(
        """(prompt) => window.fccPhone.upgradeAgent({
            id: 'builder', name: 'Builder', role: 'builder', instructions: prompt,
            tools: ['write_file', 'check_project']})""",
        old_prompt,
    )
    assert upgraded["tools"] == [
        "write_file",
        "check_project",
        "restore_file",
        "find_images",
        "polish_check",
        "look_at_site",
        "list_photos",
        "use_photo",
    ]
    assert "find_images" in upgraded["instructions"]
    assert "list_photos" in upgraded["instructions"]
    assert upgraded["toolsVersion"] == 3

    # A tool the user turned off afterwards stays off; an edited prompt stays.
    again = page.evaluate(
        """() => window.fccPhone.upgradeAgent({
            id: 'b', name: 'B', role: 'builder', instructions: 'Mine',
            tools: ['write_file'], toolsVersion: 3})"""
    )
    assert again["tools"] == ["write_file"] and again["instructions"] == "Mine"
    builder = page.evaluate(
        "() => window.fccPhone.state.agents.find((a) => a.id === 'builder')"
    )
    assert {"find_images", "look_at_site", "polish_check", "restore_file"} <= set(
        builder["tools"]
    )


def test_no_screen_shows_a_stray_null(page: Page, admin_base_url: str) -> None:
    fake_gemini(page)
    open_phone(page, admin_base_url)
    use_gemini(page)
    stray = """() => {
        const walker = document.createTreeWalker(document.getElementById('view'), NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) if (walker.currentNode.textContent.trim() === 'null') return true;
        return false;
    }"""
    for route in (
        "home",
        "chats",
        "chat/builder",
        "agents",
        "models",
        "more",
        "projects",
        "rooms",
        "learn",
        "todos",
        "memory",
        "settings",
        "help",
    ):
        go(page, route)
        page.wait_for_timeout(150)
        assert not page.evaluate(stray), route


def test_a_multi_page_site_works_in_the_preview(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    project_id = page.evaluate(
        """() => {
            const files = window.fccPhone.templateFiles('business', 'Cafe Luna');
            const project = {id: 'p1', name: 'Cafe Luna', slug: 'cafe-luna', files,
                created_at: Date.now(), updated_at: Date.now(), by: 'you'};
            window.fccPhone.state.projects.unshift(project);
            return project.id;
        }"""
    )
    go(page, f"projects/{project_id}")
    preview = page.frame_locator("iframe.preview")
    expect(preview.locator("h1")).to_have_text("Cafe Luna")
    # The drawn pictures are inlined, so they show in the sandbox.
    shown = preview.locator(".hero-media").evaluate("img => img.naturalWidth")
    assert shown > 0

    # Menu links move between the project's pages.
    preview.get_by_role("link", name="Services", exact=True).first.click()
    expect(preview.locator("h1")).to_have_text("Services and prices")
    expect(page.get_by_label("Page")).to_have_value("services.html")
    preview.get_by_role("tab", name="Classics").click()
    expect(preview.locator("#panel-2")).to_be_visible()
    expect(preview.locator("#panel-1")).to_be_hidden()
    page.get_by_label("Page").select_option("gallery.html")
    preview.get_by_role("button", name="Open picture 3").click()
    expect(preview.locator("#lightbox")).to_be_visible()
    preview.get_by_role("button", name="Next picture").click()
    expect(preview.locator("#lightbox figcaption")).to_have_text("Picture 4")
    preview.get_by_role("button", name="Close").click()

    # A phone-sized visitor gets the menu button, and the form checks itself.
    # (The app's top bar can cover part of the frame, so the form uses keys.)
    page.get_by_label("Page").select_option("contact.html")
    preview.get_by_role("button", name="Send message").press("Enter")
    expect(preview.locator("#name-error")).to_have_text("Please fill this in.")
    preview.get_by_label("Name").fill("Sam")
    preview.get_by_label("Email").fill("sam@example.org")
    preview.get_by_label("Message").fill("A table for two, please.")
    preview.get_by_role("button", name="Send message").press("Enter")
    expect(preview.locator("#form-status")).to_contain_text("Thank you!")

    page.get_by_role("button", name="Open full screen").click()
    full = page.frame_locator("iframe.preview-full")
    expect(full.locator("h1")).to_have_text("Contact and booking")
    full.get_by_role("button", name="Open menu").click()
    full.get_by_role("link", name="About", exact=True).first.click()
    expect(full.locator("h1")).to_have_text("Our story")
    page.get_by_role("button", name="Close full screen").click()

    # Every file, pictures included, saves as one zip.
    raw = page.evaluate(
        """async () => [...new Uint8Array(await window.fccPhone.zipProject(
            window.fccPhone.state.projects[0]).arrayBuffer())]"""
    )
    with zipfile.ZipFile(io.BytesIO(bytes(raw))) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert {"cafe-luna/index.html", "cafe-luna/images/hero.svg"} <= names
        expected = template_files("business", "Cafe Luna")["about.html"]
        assert archive.read("cafe-luna/about.html").decode() == expected
    expect(page.get_by_role("button", name="Save all files (.zip)")).to_be_visible()


def test_look_at_site_checks_every_page(page: Page, admin_base_url: str) -> None:
    open_phone(page, admin_base_url)
    report = page.evaluate(
        """async () => window.fccPhone.describeLook(await window.fccPhone.lookAtSite(
            {name: 'Cafe', files: window.fccPhone.templateFiles('business', 'Cafe')}))"""
    )
    for name in ("index", "about", "services", "gallery", "contact"):
        assert f"{name}.html, Phone (390px wide):" in report, report
    assert "index.html, Computer (1280px wide):" in report
    assert report.startswith("Looked at the site: it looks right"), report


def test_a_finished_app_comes_to_the_chat_ready_to_download(
    page: Page, admin_base_url: str
) -> None:
    fake_gemini(page)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "home")
    talk = page.get_by_label("Message Jarvis")
    talk.fill("Have Builder make a page for my bakery")
    talk.press("Enter")

    # Jarvis handed the job down, so the app comes back to Jarvis too.
    card = page.locator(".hud-line.download-card")
    expect(card).to_contain_text("Sunrise Bakery", timeout=15000)
    expect(card).to_contain_text("sunrise-bakery.zip · 2 files")
    with page.expect_download() as waiting:
        card.get_by_role("button", name="Download Sunrise Bakery").click()
    assert waiting.value.suggested_filename == "sunrise-bakery.zip"
    with zipfile.ZipFile(io.BytesIO(waiting.value.path().read_bytes())) as archive:
        names = archive.namelist()
    assert any(name.endswith("index.html") for name in names)
    assert any(name.endswith("style.css") for name in names)

    go(page, "chat/builder")
    builder_card = page.locator(".messages .download-card")
    expect(builder_card).to_have_count(1)
    box = builder_card.bounding_box()
    assert box is not None and box["width"] <= 390, "fits the phone"
    builder_card.get_by_role("button", name="Open").click()
    expect(page.frame_locator("iframe.preview").locator("h1")).to_have_text(
        "Sunrise Bakery"
    )
