"""The Orb edition's page: only the orb, Jarvis's talk, his two advisers,
his approvals and the Stop button."""

import httpx
import pytest
from playwright.sync_api import Page, expect

ORB = pytest.mark.parametrize(
    "admin_base_url",
    [{"STUDIO_EDITION": "orb", "STUDIO_MAIN_AGENT_MODEL": "local/e2e-qwen"}],
    indirect=True,
)


@ORB
def test_the_orb_page_talks_to_jarvis_and_shows_his_advisers(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1280, "height": 820})
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator("#orb-canvas")).to_be_visible()
    # Nothing else of Studio: no HUD, no tab bar, no menu.
    expect(page.locator(".hud")).to_have_count(0)
    expect(page.locator(".tab-bar")).to_have_count(0)
    advisers = page.locator("#orb-advisers .orb-chip")
    expect(advisers).to_have_count(2)
    expect(advisers.first).to_contain_text("Idea Adviser")
    # PC control is on in the Orb edition: the Stop button shows.
    expect(page.locator("#pc-stop")).to_have_text("■ Stop Jarvis")

    page.locator("#orb-input").fill("hello Jarvis")
    page.locator("#orb-input").press("Enter")
    expect(page.locator(".orb-msg.you")).to_contain_text("hello Jarvis")
    expect(page.locator(".orb-msg.jarvis").first).to_be_visible(timeout=20_000)
    # All local: the status names the PC's model.
    expect(page.locator("#orb-status")).to_contain_text("e2e-qwen")


@pytest.mark.parametrize("admin_base_url", [{"STUDIO_EDITION": "orb"}], indirect=True)
def test_the_orb_asks_for_a_model_on_this_pc(page: Page, admin_base_url: str) -> None:
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator("#orb-status")).to_have_text(
        "Pick Jarvis's model on this PC (⚙)"
    )
    page.locator("#orb-input").fill("hi")
    page.locator("#orb-input").press("Enter")
    expect(page.locator(".orb-msg.failed")).to_contain_text("model on this PC first")


@ORB
def test_the_owner_gives_an_adviser_a_role_and_stops_jarvis(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator("#orb-advisers .orb-chip")).to_have_count(2)
    page.get_by_role("button", name="Jarvis and his advisers").click()
    expect(page.locator("#sheet-title")).to_have_text("Jarvis and his advisers")
    card = page.locator(".orb-card", has_text="Adviser 1")
    card.get_by_label("Name").fill("Art Director")
    card.get_by_label("Speciality and role").fill("Pixel art and colour.")
    card.get_by_role("button", name="Save adviser").click()
    expect(page.locator("#toast")).to_contain_text("Art Director saved.")
    expect(page.locator("#orb-advisers .orb-chip").first).to_contain_text(
        "Art Director"
    )
    state = httpx.get(f"{admin_base_url}/studio/api/orb").json()
    assert state["advisers"][0]["speciality"] == "Pixel art and colour."
    page.locator("[data-close-sheet]").first.click(force=True)

    page.locator("#pc-stop").click()
    expect(page.locator("#pc-stop")).to_have_text("Jarvis stopped")
    assert httpx.get(f"{admin_base_url}/studio/api/pc-control").json()["stopped"]


def test_the_full_edition_still_has_the_hud_orb(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1366, "height": 800})
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator(".hud")).to_be_visible()
    expect(page.locator(".hud-orb-canvas")).to_be_visible()
    expect(page.locator("#orb-canvas")).to_have_count(0)
