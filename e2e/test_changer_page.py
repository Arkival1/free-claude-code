"""The Changer on the PC: the page, a fresh copy of FCC, and a check."""

import os

from playwright.sync_api import Page, expect

SHOTS = os.environ.get("FCC_LAB_SHOTS", "")


def test_the_changer_copies_fcc_and_checks_it(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{admin_base_url}/studio#changer")
    expect(page.locator("#view-title")).to_have_text("The Changer")
    expect(page.get_by_label("What should the Changer change?")).to_be_visible()
    expect(page.locator(".changer")).not_to_contain_text("null")

    page.evaluate("fetch('/studio/api/changer/fresh', {method: 'POST'})")
    expect(page.locator(".changer")).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="Changes in the copy")).to_be_visible(
        timeout=20_000
    )
    expect(page.locator(".changer")).to_contain_text("Nothing changed in the copy yet.")
    page.get_by_role("button", name="Check").click()
    expect(page.locator(".changer-check")).to_contain_text(
        "Checks passed", timeout=60_000
    )
    if SHOTS:
        page.screenshot(path=f"{SHOTS}/changer.png", full_page=True)
