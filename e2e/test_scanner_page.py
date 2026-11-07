"""The bug scanner page: scan once, read a finding, mark it."""

import os

from playwright.sync_api import Page, expect

SHOTS = os.environ.get("FCC_LAB_SHOTS", "")


def test_scan_read_and_mark(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{admin_base_url}/studio#scan")
    expect(page.locator("#view-title")).to_have_text("Bug scanner")
    for way in ("pages", "logs", "files"):
        page.locator(f"input[name=scan-mode][value={way}]").uncheck()
    page.get_by_role("button", name="Scan once").click()
    expect(page.locator(".scan-history li").first).to_be_visible(timeout=30_000)
    expect(page.get_by_role("button", name="Scan endlessly")).to_be_visible(
        timeout=30_000
    )
    items = page.locator(".scan-item")
    if items.count():
        items.first.locator(".scan-summary").click()
        expect(page.get_by_role("button", name="Send to the Changer")).to_be_visible()
    if SHOTS:
        page.screenshot(path=f"{SHOTS}/scanner.png", full_page=True)
    if items.count():
        page.get_by_role("button", name="Seen").click()
        expect(items.first.locator(".pill.good")).to_have_count(0)
