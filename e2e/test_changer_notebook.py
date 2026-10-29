"""The Changer's team notebook in a real browser: the owner writes to the
team from the Changer page, keeps a lesson, and the HQ shows the update."""

import os

from playwright.sync_api import Page, expect

SHOTS = os.environ.get("FCC_LAB_SHOTS", "")


def test_the_owner_writes_to_the_team_and_the_hq_shows_the_update(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{admin_base_url}/studio#changer")
    expect(page.get_by_role("heading", name="Team notebook")).to_be_visible()
    expect(page.get_by_role("button", name="Add the helper team")).to_be_visible()
    expect(page.get_by_label("Model for the whole Changer team")).to_be_visible()

    notebook = page.locator(
        "section", has=page.get_by_role("heading", name="Team notebook")
    )
    notebook.get_by_label("Note for the Changer team").fill("Never touch farm.js")
    notebook.get_by_label("Keep as a lesson for later updates").check()
    notebook.get_by_role("button", name="Add note").click()
    expect(notebook.locator("summary")).to_contain_text(
        "Lessons kept for later updates (1)"
    )

    page.get_by_label("What should the Changer change?").fill("Add a dark mode")
    page.get_by_role("button", name="Start the change").click()
    expect(page.locator(".changer h2", has_text="Update project")).to_be_visible(
        timeout=30_000
    )
    notebook = page.locator(
        "section", has=page.get_by_role("heading", name="Team notebook")
    )
    notebook.get_by_label("Note for the Changer team").fill(
        "Use the blue from the logo"
    )
    notebook.get_by_role("button", name="Add note").click()
    expect(notebook.locator(".changer-notebook").first).to_contain_text(
        "Owner: Use the blue from the logo"
    )

    page.goto(f"{admin_base_url}/studio#hq")
    card = page.locator(".hq-changer")
    expect(card).to_be_visible(timeout=20_000)
    expect(card).to_contain_text("The Changer's update")
    expect(card).to_contain_text("Add a dark mode")
    expect(card).to_contain_text("Use the blue from the logo")

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{admin_base_url}/studio#changer")
    expect(page.get_by_role("heading", name="Team notebook")).to_be_visible()
    wide = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert wide <= 2, f"the Changer page scrolls sideways by {wide}px on a phone"
    if SHOTS:
        page.screenshot(path=f"{SHOTS}/changer-notebook-phone.png", full_page=True)
