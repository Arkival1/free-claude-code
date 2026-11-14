"""Ops: the PC's load, the background lanes, and who is working."""

from playwright.sync_api import Page, expect


def test_ops_shows_the_pc_the_lanes_and_the_team(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{admin_base_url}/studio#ops")
    expect(page.locator("#view-title")).to_have_text("Ops")
    expect(page.get_by_role("heading", name="This PC")).to_be_visible()
    lanes = page.locator("#ops-lanes")
    for lane in ("Web", "Data", "Local model", "Server models", "CPU jobs"):
        expect(lanes).to_contain_text(lane)
    expect(page.locator(".ops-agent").first).to_be_visible()
    # The system pulse is drawn in 3D, or as flat bars where WebGL isn't on.
    pulse = page.locator("#ops-pulse")
    expect(pulse.locator("canvas, .ops-bar").first).to_be_visible()
    page.get_by_role("button", name="Open the Trading Bank").click()
    expect(page.locator("#view-title")).to_have_text("Trading Bank")


def test_ops_and_the_trading_bank_are_in_the_menu(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator(".hud")).to_be_visible()
    page.locator(".hud-nav-item", has_text="Ops (what the PC is doing)").click()
    expect(page.locator("#view-title")).to_have_text("Ops")
    page.goto(f"{admin_base_url}/studio")
    page.locator(".hud-nav-item", has_text="Trading Bank").click()
    expect(page.locator("#view-title")).to_have_text("Trading Bank")
