"""The Studio app on an iPhone-sized viewport: reachable, sized, installable."""

from playwright.sync_api import Page, ViewportSize, expect

IPHONE_VIEWPORT = ViewportSize(width=390, height=844)  # iPhone 15/16 CSS pixels
MIN_TAP_TARGET = 44.0


def open_studio(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size(IPHONE_VIEWPORT)
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator(".tab-bar")).to_be_visible()


def test_studio_loads_on_an_iphone_viewport(page: Page, admin_base_url: str) -> None:
    open_studio(page, admin_base_url)

    expect(page.locator("#view-title")).to_have_text("Studio")
    expect(page.get_by_role("button", name="Ask the guide")).to_be_visible()
    expect(page.locator(".card", has_text="Welcome")).to_be_visible()

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 0, "the layout scrolls sideways on an iPhone"


def test_touch_targets_are_thumb_sized(page: Page, admin_base_url: str) -> None:
    open_studio(page, admin_base_url)

    boxes = page.evaluate(
        """() =>
            [...document.querySelectorAll('.tab, button.primary, button.secondary')]
                .filter((node) => node.offsetParent !== null)
                .map((node) => node.getBoundingClientRect().height)"""
    )

    assert boxes, "no interactive controls were rendered"
    assert min(boxes) >= MIN_TAP_TARGET


def test_home_screen_install_metadata_is_present(
    page: Page, admin_base_url: str
) -> None:
    open_studio(page, admin_base_url)

    assert page.locator('link[rel="apple-touch-icon"]').count() >= 1
    assert (
        page.locator('meta[name="apple-mobile-web-app-capable"]').get_attribute(
            "content"
        )
        == "yes"
    )
    manifest = page.request.get(f"{admin_base_url}/studio/manifest.webmanifest").json()
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/studio"


def test_tabs_navigate_without_leaving_the_app(page: Page, admin_base_url: str) -> None:
    open_studio(page, admin_base_url)

    page.locator('.tab[data-route="learn"]').click()
    expect(page.locator("#view-title")).to_have_text("Classroom")
    page.locator('.tab[data-route="more"]').click()
    expect(page.locator(".card", has_text="Install on your iPhone")).to_be_visible()
    expect(page.locator(".list-item", has_text="localhost")).to_be_visible()


def test_an_unreachable_server_shows_a_readable_screen(
    page: Page, admin_base_url: str
) -> None:
    open_studio(page, admin_base_url)
    page.route("**/studio/api/**", lambda route: route.abort())

    page.locator('.tab[data-route="chats"]').click()

    expect(
        page.locator(".card", has_text="Can't reach your Studio server")
    ).to_be_visible()
    expect(page.get_by_role("button", name="Try again")).to_be_visible()
