"""The maths tutor on the PC: a lesson, a question marked, a practice test."""

import os

from playwright.sync_api import Page, expect

SHOTS = os.environ.get("FCC_LAB_SHOTS", "")


def test_practise_a_topic_and_mark_a_test(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{admin_base_url}/studio#learn")
    page.get_by_role("button", name="Open the maths tutor").click()
    expect(page.locator("#view-title")).to_have_text("Maths tutor")

    page.get_by_role("button", name="DC circuits (year 1)").click()
    page.locator(".tutor-topic[data-topic='ohms']").click()
    expect(page.locator(".tutor-lesson")).to_contain_text("Ohm")
    prompt = page.locator(".tutor-prompt")
    expect(prompt).not_to_be_empty()
    answer = page.get_by_label("Your answer")
    answer.fill("123456")
    page.get_by_role("button", name="Check").click()
    expect(page.locator(".tutor-verdict")).to_contain_text("the answer is")
    expect(page.locator(".tutor-steps li").first).to_be_visible()
    expect(page.locator(".tutor-summary")).to_contain_text("0 / 1")
    expect(page.locator(".tutor-topic[data-topic='ohms']")).to_contain_text(
        "0% of the last 1"
    )
    if SHOTS:
        page.screenshot(path=f"{SHOTS}/tutor-practice.png")

    page.get_by_role("tab", name="Practice test").click()
    page.get_by_role("button", name="Start a test").click()
    expect(page.locator(".tutor-test li")).to_have_count(10)
    page.get_by_role("button", name="Mark my test").click()
    expect(page.get_by_role("heading", name="Score: 0 / 10 (0%)")).to_be_visible()

    page.get_by_role("tab", name="Licence path").click()
    expect(page.locator(".tutor-path")).to_contain_text("UEE30820")
    expect(page.get_by_role("link", name="NSW Government", exact=False)).to_be_visible()
    if SHOTS:
        page.screenshot(path=f"{SHOTS}/tutor-path.png")
