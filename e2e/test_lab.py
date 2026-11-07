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


def test_a_design_shows_its_materials_checks_physics_and_is_kept(
    page: Page, admin_base_url: str
) -> None:
    open_lab(page, admin_base_url, "design")
    expect(page.get_by_role("heading", name="Add a component")).to_be_visible()
    page.get_by_role("button", name="Robot cart (steel frame)").click()
    # The frame is drawn in steel, the controller as a circuit board.
    expect(page.locator(".dtile.fin-metal", has_text="Frame")).to_be_visible()
    expect(
        page.locator(".dtile.fin-board", has_text="Controller board")
    ).to_be_visible()
    expect(page.locator(".dtile.fin-rubber", has_text="Wheels")).to_be_visible()
    page.get_by_role("button", name="⚙ Check physics").click()
    results = page.locator(".design-results")
    expect(results).to_contain_text("Would work")
    expect(results).to_contain_text("Weighs")
    expect(results).to_contain_text("Strength")
    expect(page.locator(".legend-chip", has_text="Mild steel")).to_be_visible()
    shot(page, "lab-design-physics")
    # How a part works, from its tile.
    page.locator(".dtile", has_text="Frame").locator(".dtile-face").click()
    expect(page.locator(".lab-modal")).to_contain_text("carries the load")
    page.locator(".lab-modal").get_by_role("button", name="Close").click()
    # Kept as a part, and added to the design again from Saved parts.
    page.get_by_role("button", name="Keep as a part").click()
    library = page.locator(".design-library")
    expect(library).to_contain_text("Robot cart (steel frame)")
    library.get_by_role("button", name="Add").first.click()
    expect(page.locator(".dtile.fin-group")).to_have_count(1)
    shot(page, "lab-design")


def test_a_design_is_built_in_3d_with_labels_and_parts_move(
    page: Page, admin_base_url: str
) -> None:
    open_lab(page, admin_base_url, "design")
    page.get_by_role("button", name="Robot cart (steel frame)").click()
    view = page.locator(".lab3d-host")
    expect(view.locator("canvas")).to_be_visible()
    labels = view.locator(".lab3d-label")
    expect(labels.first).to_be_visible()
    count = labels.count()
    assert count == page.locator(".dtile").count()
    expect(view.get_by_role("button", name="Show or hide the labels")).to_be_visible()
    page.get_by_role("button", name="⚙ Check physics").click()
    expect(page.locator(".design-results")).to_contain_text("Would work")
    # A label chooses its part and says what it is.
    labels.filter(has_text="Frame").first.click()
    expect(page.locator(".lab3d-info")).to_contain_text("Frame")
    expect(page.locator(".lab3d-info")).to_contain_text("steel")
    shot(page, "lab-design-3d")
    # Dragging a part pins every part where it is, ready to save.
    line = view.locator(".lab3d-lines line").nth(count - 1)
    x = float(line.get_attribute("x2") or 0)
    y = float(line.get_attribute("y2") or 0)
    box = view.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + x, box["y"] + y + 3)
    page.mouse.down()
    page.mouse.move(box["x"] + x + 60, box["y"] + y + 23, steps=6)
    page.mouse.up()
    placed = page.evaluate("() => document.querySelectorAll('.lab3d-label').length")
    assert placed == count
    view.get_by_role("button", name="Turn the chosen part a quarter").click()
    view.get_by_role("button", name="Let the view lay out every part again").click()
    expect(labels).to_have_count(count)


def test_the_motherboard_example_is_laid_out_where_it_says(
    page: Page, admin_base_url: str
) -> None:
    open_lab(page, admin_base_url, "design")
    page.get_by_role("button", name="Computer motherboard (in 3D)").click()
    view = page.locator(".lab3d-host")
    expect(view.locator(".lab3d-label")).to_have_count(18)
    expect(
        view.locator(".lab3d-label", has_text=re.compile(r"Memory slot .4"))
    ).to_be_visible()
    page.get_by_role("button", name="⚙ Check physics").click()
    expect(page.locator(".design-results")).to_contain_text("Weighs")
    page.evaluate("window.scrollTo(0, 0)")
    view.locator(".lab3d-label", has_text="CPU socket").click()
    expect(page.locator(".lab3d-info")).to_contain_text("spring contacts")
    shot(page, "lab-motherboard-3d")


def test_a_part_added_after_moving_the_board_sits_on_it_and_choices_reset(
    page: Page, admin_base_url: str
) -> None:
    open_lab(page, admin_base_url, "design")
    page.get_by_role("button", name="Robot cart (steel frame)").click()
    view = page.locator(".lab3d-host")
    expect(view.locator(".lab3d-label").first).to_be_visible()
    # The 3D layout puts a new part on top of a board that was moved.
    spot = page.evaluate(
        """() => {
          const items = [
            { index: 0, name: "Board", shape: "board", size_mm: [100, 2, 80],
              role: "structure", at_mm: [40, 5, -10], count: 1 },
            { index: 1, name: "Chip", shape: "box", size_mm: [10, 2, 10],
              role: "electronics", at_mm: null, count: 1 },
          ];
          return window.FCCLab3D.layout(items).get(1)[0];
        }"""
    )
    assert spot["y"] == 7
    assert -10 <= spot["x"] <= 90 and -50 <= spot["z"] <= 30
    # Choosing a part, then removing an earlier one, drops the choice.
    view.locator(".lab3d-label", has_text="Power switch").click()
    expect(page.locator(".lab3d-info")).to_contain_text("Power switch")
    page.get_by_role("button", name="Remove Frame").click()
    expect(page.locator(".lab3d-info")).to_be_hidden()
