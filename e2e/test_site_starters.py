"""The lessons and portfolio starters work in a real browser: the waves draw,
bookings are priced and sent, the projects filter and open, and nothing
scrolls sideways on a phone."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Browser, Page, expect

from e2e.test_3d_templates import make_project


def test_the_lessons_site_draws_waves_and_books(
    page: Page, admin_base_url: str, tmp_path: Path
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(make_project(admin_base_url, tmp_path, "lessons"))
    expect(page.locator("h1")).to_contain_text("first morning")
    expect(page.locator(".logo")).to_have_text("Orbit Labs")
    # The waves are drawn: the canvas is no longer blank.
    page.wait_for_function(
        """(() => { const c = document.getElementById('waves');
        const d = c.getContext('2d').getImageData(c.width / 2, c.height - 4, 1, 1).data;
        return d[3] > 0; })()"""
    )
    # A lesson button picks the lesson; the booking goes to the form service.
    page.locator('[data-lesson="Three-day course"]').click()
    expect(page.locator("#lesson")).to_have_value("Three-day course")
    page.route(
        "**/booking-test", lambda route: route.fulfill(status=200, body='{"ok": true}')
    )
    page.evaluate(
        "document.getElementById('booking').dataset.endpoint = '/booking-test'"
    )
    page.get_by_role("button", name="Book it").click()
    expect(page.locator("#err")).to_contain_text("Add your name")
    page.fill("#name", "Sam")
    page.fill("#people", "2")
    page.get_by_role("button", name="Book it").click()
    expect(page.locator("#done")).to_contain_text("Booked: Three-day course for 2")
    expect(page.locator("#done")).to_contain_text("$398.00")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") == 0
    assert errors == []


@pytest.mark.parametrize("zone", ["America/New_York", "Australia/Sydney"])
def test_the_booking_day_is_the_visitors_own_tomorrow(
    browser: Browser, admin_base_url: str, tmp_path: Path, zone: str
) -> None:
    # Dates read as UTC gave Sydney mornings today and New York evenings the
    # day after tomorrow, and showed the wrong weekday west of UTC.
    context = browser.new_context(timezone_id=zone)
    page = context.new_page()
    page.goto(make_project(admin_base_url, tmp_path, "lessons"))
    tomorrow = (datetime.now(ZoneInfo(zone)) + timedelta(days=1)).date()
    expect(page.locator("#date")).to_have_value(tomorrow.isoformat())
    assert page.get_attribute("#date", "min") == tomorrow.isoformat()
    page.route(
        "**/booking-test", lambda route: route.fulfill(status=200, body='{"ok": true}')
    )
    page.evaluate(
        "document.getElementById('booking').dataset.endpoint = '/booking-test'"
    )
    page.fill("#name", "Sam")
    page.get_by_role("button", name="Book it").click()
    expect(page.locator("#done")).to_contain_text(
        f"{tomorrow:%A} {tomorrow.day} {tomorrow:%B}"
    )
    # After the booking the form is ready for the next one.
    expect(page.locator("#date")).to_have_value(tomorrow.isoformat())
    expect(page.get_by_role("button", name="Book it")).to_be_enabled()
    context.close()


def test_the_portfolio_filters_and_opens_projects(
    page: Page, admin_base_url: str, tmp_path: Path
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(make_project(admin_base_url, tmp_path, "portfolio"))
    projects = page.locator("#grid .project")
    expect(projects).to_have_count(6)
    expect(projects.first.locator("svg")).to_have_count(1)
    page.get_by_role("button", name="Homes").click()
    expect(page.locator("#grid .project:visible")).to_have_count(2)
    expect(page.get_by_role("button", name="Homes")).to_have_attribute(
        "aria-pressed", "true"
    )
    page.locator("#grid .project:visible").first.click()
    dialog = page.locator("#detail")
    expect(dialog).to_be_visible()
    expect(dialog.locator("#dFacts")).to_contain_text("NatHERS")
    page.get_by_role("button", name="Close").click()
    expect(dialog).to_be_hidden()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") == 0
    assert errors == []
