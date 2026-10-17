"""The Connectors page: connect a service, keep its token hidden, and see how
other AI tools use LCC."""

from playwright.sync_api import Page, expect

DISCORD = "https://discord.com/api/webhooks/123/secret-part"


def test_a_webhook_is_connected_and_its_address_stays_hidden(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{admin_base_url}/studio#more")
    page.get_by_role("button", name="Open connectors").click()
    expect(page.locator("#view-title")).to_have_text("Connectors")

    github = page.locator("[data-connector='github']")
    expect(github.locator(".pill")).to_have_text("not connected")
    github.get_by_role("button", name="Connect").click()
    expect(github).to_contain_text("GitHub needs Token.")

    webhook = page.locator("[data-connector='webhook']")
    webhook.get_by_label("Webhook address").fill(DISCORD)
    webhook.get_by_role("button", name="Connect").click()
    webhook = page.locator("[data-connector='webhook']")
    expect(webhook.locator(".pill")).to_have_text("connected")
    expect(webhook.get_by_role("button", name="Test")).to_be_visible()
    # The saved address comes back as dots, never as itself.
    expect(webhook.get_by_label("Webhook address")).to_have_value("••••••")
    assert "secret-part" not in page.content()

    harness = page.locator(".card", has_text="Use LCC from other AI tools")
    expect(harness).to_contain_text(
        f"claude mcp add --transport http lcc {admin_base_url}/mcp"
    )
    expect(harness).to_contain_text(f"{admin_base_url}/v1")

    webhook.get_by_role("button", name="Disconnect").click()
    expect(page.locator("[data-connector='webhook'] .pill")).to_have_text(
        "not connected"
    )
