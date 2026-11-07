"""A website's contact form never throws a customer's message away.

Before, a form with no form service said "Thank you! We'll reply within one
working day." and dropped the message, so a business lost every lead."""

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route

from free_claude_code.studio.templates import template_files


def site(tmp_path: Path, template: str, **swap: str) -> str:
    for name, text in template_files(template, "Fade Kings").items():
        for old, new in swap.items():
            text = text.replace(old, new)
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    page = "contact.html" if template == "business" else "index.html"
    return (tmp_path / page).as_uri()


def fill(page: Page) -> None:
    page.fill("#contact-form [name=name]", "Sam")
    page.fill("#contact-form [name=email]", "sam@example.org")
    page.fill("#contact-form textarea", "Can I book a fade for Saturday?")


@pytest.mark.parametrize("template", ["business", "website"])
def test_without_a_form_service_the_email_app_opens_with_the_message(
    page: Page, tmp_path, template
):
    url = site(
        tmp_path, template, **{'data-email=""': 'data-email="book@fadekings.test"'}
    )
    page.goto(url)
    fill(page)
    with page.expect_request(
        lambda r: r.url.startswith("mailto:"), timeout=3000
    ) as mail:
        page.click("#contact-form [type=submit]")
    href = mail.value.url
    assert href.startswith("mailto:book@fadekings.test?subject=")
    assert "Can%20I%20book%20a%20fade" in href and "sam%40example.org" in href
    status = page.locator("#contact-form [role=status]").inner_text()
    assert "email app is opening" in status and "Thank you" not in status
    # The message stays in the form in case the visitor cancels the email.
    assert page.input_value("#contact-form textarea").startswith("Can I book")


def test_with_a_form_service_the_message_is_sent(page: Page, tmp_path):
    url = site(
        tmp_path,
        "business",
        **{'data-endpoint=""': 'data-endpoint="https://forms.example.test/f/abc"'},
    )
    sent: list[str] = []

    def answer(route: Route) -> None:
        sent.append(route.request.post_data or "")
        route.fulfill(status=200, body=json.dumps({"ok": True}))

    page.route("https://forms.example.test/**", answer)
    page.goto(url)
    fill(page)
    page.click("#contact-form [type=submit]")
    status = page.locator("#contact-form [role=status]")
    status.filter(has_text="Thank you").wait_for(timeout=3000)
    assert sent and "Can I book a fade" in sent[0]


def test_with_no_address_at_all_it_says_so(page: Page, tmp_path):
    url = site(tmp_path, "landing")
    page.goto(url)
    page.fill("#contact-form [name=email]", "sam@example.org")
    page.click("#contact-form [type=submit]")
    status = page.locator("#contact-form [role=status]").inner_text()
    assert "isn't connected yet" in status and "on the list" not in status
