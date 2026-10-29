"""Subagents on the PC: add one with a role, switch it off, see it in the HQ."""

import os

from playwright.sync_api import Page, expect

SHOTS = os.environ.get("FCC_LAB_SHOTS", "")


def test_add_switch_and_see_a_subagent(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{admin_base_url}/studio#agents")
    expect(page.get_by_role("heading", name="Subagents")).to_be_visible()
    page.get_by_label("Subagent name").fill("Dev-1")
    page.get_by_label("Subagent role").select_option("developer")
    expect(page.get_by_label("Subagent model")).to_be_visible()
    page.get_by_role("button", name="Add subagent").click()
    row = page.locator(".subagent-row", has_text="Dev-1")
    expect(row).to_contain_text("developer")
    expect(row.locator(".pill")).to_have_text("on")
    if SHOTS:
        page.locator(".subagents").scroll_into_view_if_needed()
        page.screenshot(path=f"{SHOTS}/subagents.png")
    page.get_by_label("Dev-1 on").uncheck()
    expect(
        page.locator(".subagent-row", has_text="Dev-1").locator(".pill")
    ).to_have_text("off")
    hq = page.request.get(f"{admin_base_url}/studio/api/hq").json()
    dev = next(person for person in hq["agents"] if person["name"] == "Dev-1")
    assert dev["subagent"] is True and dev["active"] is False
    assert dev["station"]
