"""The Trading Bank page: the desk strip, the seat ring, the tabs, and setup."""

from playwright.sync_api import Page, expect


def test_the_trading_bank_opens_on_paper_with_every_tab(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{admin_base_url}/studio#trade")
    expect(page.locator("#view-title")).to_have_text("Trading Bank")
    expect(page.locator(".mode-badge strong")).to_have_text("PRACTICE")
    expect(page.locator(".trade-strip")).to_contain_text("10,000.00")
    expect(page.locator(".tab[data-route='trade']")).to_have_attribute(
        "aria-current", "page"
    )
    # The seats are drawn in 3D, or as the flat ring where WebGL isn't on.
    expect(
        page.locator("#trade-arena canvas, #trade-arena .ring-seat").first
    ).to_be_visible()

    page.locator(".trade-tab", has_text="Debate").click()
    expect(page.locator("#trade-feed")).to_be_visible()
    page.locator(".trade-tab", has_text="Risk").click()
    expect(page.get_by_role("heading", name="Risk assessment period")).to_be_visible()
    page.locator(".trade-tab", has_text="Orders").click()
    expect(page.get_by_role("heading", name="Results")).to_be_visible()
    page.locator(".trade-tab", has_text="Debriefs").click()
    expect(page.get_by_role("heading", name="Leaderboard")).to_be_visible()
    page.locator(".trade-tab", has_text="Setup").click()
    expect(page.get_by_role("heading", name="Mode and platform")).to_be_visible()
    expect(page.locator("details.broker").first).to_be_visible()
    expect(page.locator(".seat-row")).to_have_count(5)

    page.locator(".trade-tab", has_text="Desk").click()
    page.get_by_role("button", name="Start", exact=True).click()
    expect(page.get_by_role("button", name="Stop", exact=True)).to_be_visible()
    page.get_by_role("button", name="Stop", exact=True).click()
    expect(page.get_by_role("button", name="Start", exact=True)).to_be_visible()


def test_the_trading_page_fits_an_iphone(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{admin_base_url}/studio#trade")
    expect(page.locator(".trade-strip")).to_be_visible()
    last = page.locator(".tab-bar .tab").last.bounding_box()
    assert last is not None and last["x"] + last["width"] <= 375, "a tab is off-screen"
    clipped = page.evaluate(
        "() => [...document.querySelectorAll('.tab-label')]"
        ".filter((n) => n.scrollWidth > n.clientWidth + 0.5).map((n) => n.textContent)"
    )
    assert clipped == [], f"tab names cut off: {clipped}"
    for tab in ("Desk", "Setup"):
        page.locator(".trade-tab", has_text=tab).click()
        page.wait_for_timeout(200)
        wide = page.evaluate(
            "() => document.documentElement.scrollWidth > window.innerWidth + 1"
        )
        assert not wide, f"the {tab} tab scrolls sideways on an iPhone"


def test_the_pc_page_shows_health_decisions_learning_and_backtests(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(f"{admin_base_url}/studio#trade")
    expect(page.get_by_role("heading", name="Engine")).to_be_visible()
    page.locator(".trade-tab", has_text="Orders").click()
    expect(page.get_by_role("heading", name="Decision records")).to_be_visible()
    page.get_by_role("button", name="Search", exact=True).click()
    expect(page.locator(".decision-list")).to_contain_text("No decisions match")
    page.locator(".trade-tab", has_text="Debriefs").click()
    expect(
        page.get_by_role("heading", name="Learning: every seat counts the same")
    ).to_be_visible()
    expect(page.get_by_role("heading", name="Backtest")).to_be_visible()
    page.locator(".trade-tab", has_text="Setup").click()
    expect(page.get_by_label("Practice coin prices")).to_have_value("exchanges")
