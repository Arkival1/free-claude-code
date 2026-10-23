"""The Builder's 3D starters work in a real browser: the 3D draws, the kit's
numbers count, the dashboard fills in, and reduced motion gets the flat view."""

from pathlib import Path

import httpx
from playwright.sync_api import Page, expect

from free_claude_code.studio.templates import template_files, template_libraries


def make_project(base_url: str, tmp_path: Path, template: str) -> str:
    """A project made from a starter, as start_project leaves it."""
    site = httpx.post(f"{base_url}/studio/api/sites", json={"name": template}).json()
    folder = tmp_path / "studio" / "sites" / site["id"]
    for path, text in template_files(template, "Orbit Labs").items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_text(text, encoding="utf-8")
    for path, source in template_libraries(template).items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(source.read_bytes())
    return f"{base_url}/studio/sites/{site['id']}/index.html"


def test_the_3d_landing_page_draws_and_counts(
    page: Page, admin_base_url: str, tmp_path: Path
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(make_project(admin_base_url, tmp_path, "3d-landing"))
    expect(page.locator(".hero-3d")).to_have_class("hero-3d has-3d")
    page.locator("#numbers").scroll_into_view_if_needed()
    expect(page.locator('[data-count="98"]')).to_have_text("98%", timeout=5000)
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Menu").click()
    expect(page.locator("#menu")).to_be_visible()
    assert errors == []


def test_the_3d_dashboard_fills_in_and_moves(
    page: Page, admin_base_url: str, tmp_path: Path
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(make_project(admin_base_url, tmp_path, "3d-dashboard"))
    expect(page.locator("#kpis .stat")).to_have_count(4)
    expect(page.locator("#dash-3d canvas")).to_have_count(1)
    expect(page.locator("#mode")).to_have_text("Demo data")
    expect(page.locator("#log li").first).to_be_visible()
    page.evaluate(
        """() => window.dashboard.push({ kpis: [{ id: "orders", label: "Orders", value: 7 }],
             events: [{ text: "Real order", service: "api" }] })"""
    )
    expect(page.locator("#mode")).to_have_text("Live")
    expect(page.locator("#log")).to_contain_text("Real order")
    assert errors == []


def test_reduced_motion_gets_the_flat_views(
    page: Page, admin_base_url: str, tmp_path: Path
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(make_project(admin_base_url, tmp_path, "3d-landing"))
    expect(page.locator(".hero-3d")).to_have_class("hero-3d no-3d")
    page.goto(make_project(admin_base_url, tmp_path, "3d-dashboard"))
    expect(page.locator("#services-flat .service-row")).to_have_count(5)
    expect(page.locator("#dash-3d canvas")).to_have_count(0)


def test_the_3d_shop_turns_shows_its_products_and_takes_an_order(
    page: Page, admin_base_url: str, tmp_path: Path
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 1280, "height": 900})
    # Count animation frames asked for, to prove only one drawing loop runs.
    page.add_init_script(
        """window.__frames = 0; const raf = window.requestAnimationFrame.bind(window);
        window.requestAnimationFrame = (cb) => { window.__frames += 1; return raf(cb); };"""
    )
    page.goto(make_project(admin_base_url, tmp_path, "3d-shop"))
    stage = page.locator("#stage")
    expect(stage.locator("canvas")).to_have_count(1)
    expect(page.locator("#fallback")).to_have_count(0)
    page.wait_for_timeout(1000)
    before = page.evaluate("window.__frames")
    page.wait_for_timeout(1000)
    assert page.evaluate("window.__frames") - before <= 75, "one loop, not two"
    # The card photos are rendered from the 3D models.
    expect(page.locator(".card")).to_have_count(4)
    page.wait_for_function(
        "[...document.querySelectorAll('.card img')]"
        ".every((img) => img.src.startsWith('data:image/png'))"
    )
    # Drag turns the peel; a tap on a loaf names it.
    box = stage.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.5)
    page.mouse.down()
    page.mouse.move(
        box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.5, steps=8
    )
    page.mouse.up()
    page.wait_for_timeout(1200)
    tapped = False
    for x, y in ((0.45, 0.5), (0.5, 0.45), (0.4, 0.55), (0.55, 0.5)):
        page.mouse.click(box["x"] + box["width"] * x, box["y"] + box["height"] * y)
        if page.locator("#tag").is_visible():
            tapped = True
            break
    assert tapped, "a tap on the board names a loaf"
    expect(page.locator("#tag")).to_contain_text("$")
    # The order goes to the shop's form service when there is one.
    page.route(
        "**/order-test", lambda route: route.fulfill(status=200, body='{"ok": true}')
    )
    page.evaluate("document.getElementById('order').dataset.endpoint = '/order-test'")
    page.get_by_role("button", name="Reserve it").click()
    expect(page.locator("#err")).to_contain_text("Add your name")
    page.fill("#name", "Sam")
    page.fill("#qty", "2")
    page.get_by_role("button", name="Reserve it").click()
    expect(page.locator("#done")).to_contain_text("Reserved: 2")
    expect(page.locator("#done")).to_contain_text("Country sourdough for Sam")
    # Without clipboard access, Copy number selects the number instead.
    page.evaluate(
        "Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })"
    )
    page.get_by_role("button", name="Copy number").click()
    expect(page.locator("#copyNote")).to_contain_text("Selected")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") == 0
    assert errors == []
