"""The More page lists every plug-in that is switched on and what it does,
including FCC's own skills and which agents follow them."""

from playwright.sync_api import Page, expect


def test_active_plugins_show_what_they_do(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{admin_base_url}/studio#more")
    active = page.locator(".card", has_text="Active plug-ins").first
    expect(active).to_be_visible()
    plugin = active.locator(".active-plugin", has_text="FCC skills")
    expect(plugin).to_contain_text("Built into FCC")
    expect(plugin).to_contain_text("web-design-engineer")
    expect(plugin).to_contain_text("Used by the Builder")
    expect(plugin).to_contain_text("app-developer-engineer")
    expect(plugin).to_contain_text("Coder, Developer and Tester")


def test_active_plugins_fit_a_phone(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{admin_base_url}/studio#more")
    active = page.locator(".card", has_text="Active plug-ins").first
    expect(active).to_be_visible()
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, width
