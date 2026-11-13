"""FCC Phone as PocketPal's hands: prompts out, checked replies in, FCC's own
tools do the work (with the user's approval for changes), builds land in
Projects with a sealed preview."""

import json

from playwright.sync_api import Page, expect

from .test_fcc_phone import go, open_phone

SITE = (
    "<!doctype html><html><head><meta charset='utf-8'><title>Sunrise</title></head>"
    "<body><h1>Sunrise Cafe</h1><p>Open 7am to 3pm.</p></body></html>"
)


def reply(page: Page, value: object) -> str:
    """What the Share Sheet shortcut's second script does."""
    text = value if isinstance(value, str) else json.dumps(value)
    return page.evaluate("(t) => window.fccPocketPal.reply(t)", text)


def start(page: Page, question: str, project: str = "") -> None:
    go(page, "pocketpal")
    if project:
        page.get_by_label("Project PocketPal may use").select_option(label=project)
    page.get_by_label("Ask Jarvis").fill(question)
    page.get_by_role("button", name="Start task").click()
    expect(page.locator("#prompt")).to_have_value(
        __import__("re").compile("User request")
    )


def test_a_website_from_pocketpal_lands_in_projects_with_a_sealed_preview(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_phone(page, admin_base_url)
    go(page, "more")
    page.get_by_text("PocketPal", exact=True).first.click()
    page.get_by_role("button", name="Website prompt").click()
    page.get_by_role("button", name="Start task").click()
    prompt = page.locator("#prompt").input_value()
    assert '{"artifact":' in prompt and "ONE JSON object" in prompt
    # The shortcut's first script reads the same prompt.
    assert page.evaluate("() => window.fccPocketPal.prompt()") == prompt

    # A small model wraps the JSON in a sentence: FCC takes the one object.
    said = reply(
        page,
        "Here you go! "
        + json.dumps(
            {"artifact": {"title": "Sunrise Cafe", "kind": "website", "html": SITE}}
        ),
    )
    assert "Saved Sunrise Cafe to Projects" in said
    expect(page.locator("#pocketpal-state")).to_have_text("Done")
    frame = page.locator("iframe.pocketpal-preview")
    expect(frame).to_have_attribute("sandbox", "allow-scripts")
    expect(page.frame_locator("iframe.pocketpal-preview").locator("h1")).to_have_text(
        "Sunrise Cafe"
    )
    project = page.evaluate(
        "() => window.fccPhone.state.projects.find((p) => p.name === 'Sunrise Cafe')"
    )
    assert project["files"]["index.html"] == SITE
    page.get_by_role("button", name="Open in Projects").click()
    expect(page).to_have_url(__import__("re").compile(f"#projects/{project['id']}$"))
    assert "null" not in page.locator("#view").inner_text()
    assert errors == []


def test_pocketpal_uses_fccs_tools_and_asks_before_changing_anything(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    page.evaluate(
        """async () => {
            const { createProject, writeFile } = await import('./js/projects.js');
            const p = await createProject('Bakery');
            await writeFile(p, 'index.html', '<h1>Old title</h1>', 'you');
        }"""
    )
    start(page, "Fix the bakery's title", "Bakery")
    # Reading needs the tool loaded first; not loaded yet, it's refused.
    reply(page, {"tool": "read_file", "args": {"path": "index.html"}})
    assert "Load read_file first" in page.locator("#prompt").input_value()
    reply(page, {"tool": "search_tools", "args": {"query": "file"}})
    assert "write_file" in page.locator("#prompt").input_value()
    reply(page, {"tool": "load_tool", "args": {"name": "read_file"}})
    reply(page, {"tool": "read_file", "args": {"path": "index.html"}})
    assert "Old title" in page.locator("#prompt").input_value()
    reply(page, {"tool": "load_tool", "args": {"name": "write_file"}})

    # A change waits for the user.
    said = reply(
        page,
        {
            "tool": "write_file",
            "args": {"path": "index.html", "content": "<h1>New title</h1>"},
        },
    )
    assert said == "Waiting for your approval in FCC."
    expect(
        page.get_by_text("PocketPal wants to write file.", exact=True)
    ).to_be_visible()
    files = (
        "() => window.fccPhone.state.projects.find((p) => p.name === 'Bakery').files"
    )
    assert page.evaluate(files)["index.html"] == "<h1>Old title</h1>"
    page.get_by_role("button", name="Approve").click()
    expect(page.locator("#pocketpal-state")).to_have_text("Waiting")
    assert page.evaluate(files)["index.html"] == "<h1>New title</h1>"

    # Saying no leaves the file alone and tells PocketPal.
    reply(
        page,
        {
            "tool": "write_file",
            "args": {"path": "index.html", "content": "<h1>Bad</h1>"},
        },
    )
    page.get_by_role("button", name="No").click()
    expect(page.locator("#prompt")).to_have_value(__import__("re").compile("said no"))
    assert page.evaluate(files)["index.html"] == "<h1>New title</h1>"

    reply(page, {"answer": "Changed the title to New title."})
    expect(page.get_by_text("Changed the title to New title.").first).to_be_visible()
    expect(page.locator("#pocketpal-state")).to_have_text("Done")


def test_pocketpal_gets_jarviss_long_term_memory(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    page.evaluate(
        """async () => {
            const { remember } = await import('./js/tools.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.role === 'main');
            await remember(jarvis, 'The cafe is called Sunrise and opens at 7am.');
        }"""
    )
    start(page, "Write the opening hours for my cafe")
    prompt = page.locator("#prompt").input_value()
    assert "What you remember" in prompt and "Sunrise and opens at 7am" in prompt


def test_bad_replies_are_blocked_where_the_user_can_see_why(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    start(page, "Make a game")
    said = reply(page, "Sure! I'll make a fun game for you.")
    assert "isn't one JSON reply" in said
    expect(page.locator("#pocketpal-state")).to_have_text("Blocked")
    # Only PocketPal's tool list: anything else is refused, with the reason
    # in the next prompt.
    reply(page, {"tool": "delete_file", "args": {"path": "index.html"}})
    assert "FCC blocked delete_file" in page.locator("#prompt").input_value()
    # A build must be a website or game with real HTML, under 48 KB.
    said = reply(page, {"artifact": {"title": "X", "kind": "app", "html": "<p>x</p>"}})
    assert "kind (website or game)" in said
    said = reply(
        page,
        {
            "artifact": {
                "title": "X",
                "kind": "game",
                "html": "<p>" + "x" * 50000 + "</p>",
            }
        },
    )
    assert "48 KB" in said
    # File tools need a project first.
    reply(page, {"tool": "load_tool", "args": {"name": "list_files"}})
    reply(page, {"tool": "list_files", "args": {}})
    assert "start_project first" in page.locator("#prompt").input_value()
    expect(page.locator(".pocketpal-log li.blocked").first).to_be_visible()


def test_the_reply_form_and_a_reload_keep_the_handoff_working(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    start(page, "What's 12 times 12?")
    prompt = page.locator("#prompt").input_value()
    # A shortcut that fills #reply and submits #reply-form works too.
    page.locator("#reply").fill(
        json.dumps({"tool": "load_tool", "args": {"name": "calculate"}})
    )
    page.evaluate("() => document.getElementById('reply-form').requestSubmit()")
    expect(page.locator("#prompt")).not_to_have_value(prompt)
    # iOS may reload Safari while PocketPal thinks: the task is still there.
    page.reload()
    page.wait_for_function("() => window.fccPhone && window.fccPhone.ready")
    page.evaluate("() => window.fccPhone.ready")
    go(page, "home")
    # The reply from the shortcut brings the user back to PocketPal.
    reply(page, {"tool": "calculate", "args": {"expression": "12*12"}})
    expect(page).to_have_url(__import__("re").compile("#pocketpal$"))
    assert "144" in page.locator("#prompt").input_value()
    reply(page, {"answer": "144"})
    expect(page.locator("#pocketpal-state")).to_have_text("Done")
