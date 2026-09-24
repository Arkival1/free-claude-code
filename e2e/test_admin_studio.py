"""The Admin Studio page: where Studio's own settings are edited."""

from playwright.sync_api import Page, expect


def test_studio_settings_have_their_own_page(page: Page, admin_base_url: str) -> None:
    page.goto(f"{admin_base_url}/admin")
    expect(page.locator("#messageArea")).to_have_text("")

    page.get_by_role("button", name="Studio", exact=True).click()
    expect(page).to_have_url(f"{admin_base_url}/admin/studio")
    expect(page.locator("#pageTitle")).to_have_text("Studio")
    expect(page.get_by_role("link", name="open Studio")).to_have_attribute(
        "href", "/studio"
    )

    main_model = page.locator("#field-STUDIO_MAIN_AGENT_MODEL")
    main_model.fill("local/qwen3.5-4b-instruct")
    main_model.press("Escape")
    page.locator("#field-STUDIO_UI_THEME").select_option("hud")
    expect(page.locator("#field-STUDIO_LOCAL_BASE_URL")).to_have_value(
        "http://localhost:1234/v1"
    )
    page.get_by_role("button", name="Apply", exact=True).click()
    expect(page.locator("#dirtyState")).to_have_text("No changes")

    page.reload()
    expect(page.locator("#pageTitle")).to_have_text("Studio")
    expect(page.locator("#field-STUDIO_MAIN_AGENT_MODEL")).to_have_value(
        "local/qwen3.5-4b-instruct"
    )
    expect(page.locator("#field-STUDIO_UI_THEME")).to_have_value("hud")
