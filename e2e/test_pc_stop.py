"""Jarvis's PC: the red Stop on every page, and the PC panel."""

import httpx
import pytest
from playwright.sync_api import Page, expect

PC_ON = pytest.mark.parametrize(
    "admin_base_url", [{"STUDIO_PC_CONTROL": "true"}], indirect=True
)


def test_no_stop_button_while_pc_control_is_off(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{admin_base_url}/studio#more")
    expect(page.locator("#view-title")).to_have_text("More")
    page.wait_for_timeout(300)
    expect(page.locator("#pc-guard")).to_be_hidden()


@PC_ON
def test_stop_shows_over_the_hud_and_stops_jarvis(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1366, "height": 800})
    page.goto(f"{admin_base_url}/studio")
    # The HUD hides the app bar; the Stop button still shows over it.
    expect(page.locator(".hud")).to_be_visible()
    stop = page.locator("#pc-stop")
    expect(stop).to_have_text("■ Stop Jarvis")
    stop.click()
    expect(stop).to_have_text("Jarvis stopped")
    expect(page.locator("#toast")).to_contain_text("Jarvis stopped")
    state = httpx.get(f"{admin_base_url}/studio/api/pc-control").json()
    assert state["stopped"] is True
    assert state["active"] is False

    # Tapping it again opens the panel, where the owner lets him carry on.
    stop.click()
    expect(page.locator("#sheet-title")).to_have_text("Jarvis's PC")
    expect(page.locator(".pc-log")).to_contain_text("STOP")
    page.get_by_role("button", name="Let Jarvis carry on").click()
    expect(stop).to_have_text("■ Stop Jarvis")
    expect(page.get_by_role("button", name="■ Stop Jarvis now")).to_be_visible()

    # The level and his folders are set from the same panel.
    page.get_by_label("What he may do on his own").select_option("look")
    expect(page.locator("#toast")).to_contain_text("Saved.")
    folder = page.get_by_label("His folders (one per line)")
    home = httpx.get(f"{admin_base_url}/studio/api/pc-control").json()["roots"][0]
    folder.fill(f"{home}/games")
    page.get_by_role("button", name="Save folders").click()
    expect(page.locator("#toast")).to_contain_text("Folders saved.")
    state = httpx.get(f"{admin_base_url}/studio/api/pc-control").json()
    assert state["level"] == "look"
    assert state["roots"] == [f"{home}/games"]


@PC_ON
def test_stop_button_is_on_ordinary_pages_and_the_keyboard_stops_too(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{admin_base_url}/studio#more")
    expect(page.locator("#view-title")).to_have_text("More")
    stop = page.locator("#pc-stop")
    expect(stop).to_be_visible()
    # It doesn't cover the guide button.
    guide = page.locator("#guide-button").bounding_box()
    box = stop.bounding_box()
    assert guide is not None and box is not None
    assert box["x"] + box["width"] <= guide["x"]
    page.keyboard.press("Control+Alt+Pause")
    expect(stop).to_have_text("Jarvis stopped")
