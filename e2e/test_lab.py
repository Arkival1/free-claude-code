"""The Lab on the PC: mix on the bench, make products, forge, and build."""

import os
import re

from playwright.sync_api import Page, expect

SHOTS = os.environ.get("FCC_LAB_SHOTS", "")


def shot(page: Page, name: str) -> None:
    """Screenshots for the docs when FCC_LAB_SHOTS names a folder."""
    if SHOTS:
        page.wait_for_timeout(1800)
        page.screenshot(path=f"{SHOTS}/{name}.png", full_page=False)


def open_lab(page: Page, admin_base_url: str, mode: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{admin_base_url}/studio#lab")
    page.locator(f".lab-mode[data-mode='{mode}']").click()


def test_pouring_lead_nitrate_into_potassium_iodide_rains_yellow(
    page: Page, admin_base_url: str
) -> None:
    open_lab(page, admin_base_url, "bench")
    expect(page.get_by_role("heading", name="Chemical shelf")).to_be_visible()
    shelf = page.get_by_label("Search chemicals")
    shelf.fill("lead")
    page.locator(".bottle", has_text="Lead(II) nitrate").click()
    shelf.fill("potassium iodide")
    page.locator(".bottle", has_text="Potassium iodide").click()
    expect(page.locator(".content-row")).to_have_count(2)
    page.get_by_role("button", name="⚗ Mix").click()
    results = page.locator(".results")
    expect(results).to_contain_text("lead(II) iodide")
    expect(results).to_contain_text("Pb²⁺(aq) + 2I⁻(aq) → PbI₂(s)")
    expect(results).to_contain_text("golden rain")
    sediment = page.locator(".sediment")
    expect(sediment).to_have_attribute("style", re.compile(r"--ppt: ?#ffd400"))
    shot(page, "lab-bench")

    page.get_by_role("button", name="Empty").click()
    shelf.fill("vinegar")
    page.locator(".bottle", has_text="Vinegar").click()
    shelf.fill("baking soda")
    page.locator(".bottle", has_text="Baking soda").click()
    page.get_by_role("button", name="⚗ Mix").click()
    expect(results).to_contain_text("carbon dioxide")
    expect(page.locator(".bubbles span").first).to_be_attached()


def test_making_shampoo_shows_every_ingredient_and_element(
    page: Page, admin_base_url: str
) -> None:
    open_lab(page, admin_base_url, "make")
    page.get_by_label("What should the Lab make?").fill("make shampoo")
    page.get_by_role("button", name="Make it").click()
    product = page.locator(".product")
    expect(product.get_by_role("heading", name="Shampoo")).to_be_visible()
    expect(product.locator(".band")).to_have_count(11)
    expect(product.locator(".ingredients tbody tr")).to_have_count(11)
    expect(product).to_contain_text("Sodium laureth sulfate")
    expect(product).to_contain_text("C₁₆H₃₃NaO₆S")
    expect(product.locator(".element-chip", has_text="Na")).to_be_visible()
    shot(page, "lab-shampoo")
    product.locator(".ingredients tbody tr", has_text="Sodium laureth sulfate").click()
    card = page.locator(".lab-modal")
    expect(card).to_contain_text("Main cleanser")
    expect(card.locator(".element-chip")).to_have_count(5)
    card.get_by_role("button", name="Close").click()

    page.locator(".lab-mode[data-mode='made']").click()
    expect(page.locator(".made-row", has_text="Shampoo")).to_be_visible()


def test_forging_bronze_and_powering_a_flashlight(
    page: Page, admin_base_url: str
) -> None:
    open_lab(page, admin_base_url, "materials")
    page.locator(".material-chip", has_text="Copper").first.click()
    page.locator(".material-chip", has_text="Tin").first.click()
    page.get_by_label("Percent of Copper").first.fill("88")
    page.get_by_label("Percent of Copper").first.dispatch_event("change")
    page.get_by_label("Percent of Tin").last.fill("12")
    page.get_by_label("Percent of Tin").last.dispatch_event("change")
    page.get_by_role("button", name="🔥 Forge").click()
    result = page.locator(".forge-result")
    expect(result.get_by_role("heading", name="Bronze")).to_be_visible()
    expect(result).to_contain_text("Real alloy")
    result.get_by_role("button", name="Pull test").click()
    expect(result.locator(".curve")).to_be_visible()

    page.locator(".lab-mode[data-mode='tech']").click()
    page.get_by_role("button", name="LED flashlight").click()
    board = page.locator(".board")
    expect(board).to_have_class(re.compile("live"))
    expect(board.locator(".tile.led.on")).to_have_count(1)
    expect(page.locator(".build-stats")).to_contain_text("It works")
    expect(page.locator(".build-stats")).to_contain_text("82 Ω")
    shot(page, "lab-tech")

    page.locator(".lab-mode[data-mode='elements']").click()
    expect(page.locator(".ptile")).to_have_count(118)
    page.locator(".ptile", has_text="Sodium").click()
    expect(page.locator(".lab-modal")).to_contain_text("bright yellow-orange")
    shot(page, "lab-elements")
    page.get_by_role("button", name="Add to the beaker").click()
    expect(page.locator(".content-row", has_text="Sodium")).to_be_visible()


def test_the_lab_refuses_weapons(page: Page, admin_base_url: str) -> None:
    open_lab(page, admin_base_url, "make")
    page.get_by_label("What should the Lab make?").fill("a pipe bomb")
    page.get_by_role("button", name="Make it").click()
    expect(page.locator("#toast")).to_contain_text("doesn't make explosives")


def test_elephant_toothpaste_foams_over_the_top(
    page: Page, admin_base_url: str
) -> None:
    open_lab(page, admin_base_url, "make")
    page.get_by_role("button", name="Elephant toothpaste (demo)").click()
    page.get_by_role("button", name="⚗ Test it on the bench").click()
    stage = page.locator(".beaker-stage")
    expect(stage).to_have_class(re.compile("erupting"))
    expect(page.locator(".results")).to_contain_text("2H₂O₂(aq) → 2H₂O(l) + O₂↑")
    shot(page, "lab-foam")
