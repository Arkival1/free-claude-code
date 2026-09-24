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
    expect(page.locator("#field-STUDIO_UI_THEME")).to_have_count(0)
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


def test_one_search_box_finds_settings_on_every_page(
    page: Page, admin_base_url: str
) -> None:
    page.goto(f"{admin_base_url}/admin")
    expect(page.locator("#messageArea")).to_have_text("")
    search = page.get_by_label("Search settings")

    search.fill("main ai model")
    expect(page.locator("#pageTitle")).to_have_text("Search")
    expect(page.locator("#field-STUDIO_MAIN_AGENT_MODEL")).to_be_visible()
    expect(page.locator("#field-STUDIO_DEFAULT_MODEL")).to_be_hidden()
    expect(page.locator("#searchSummary")).to_contain_text("1 setting")
    expect(page.locator("#providerGroups")).to_be_hidden()

    search.fill("web search")
    expect(page.locator("#field-STUDIO_SEARCH_API_KEY")).to_be_visible()
    search.fill("progress timeout")  # an advanced field, shown when it matches
    expect(page.locator("#field-PROVIDER_PROGRESS_TIMEOUT")).to_be_visible()
    search.fill("zzzz-nothing")
    expect(page.locator("#searchSummary")).to_contain_text("No settings match")

    search.press("Escape")
    expect(search).to_have_value("")
    expect(page.locator("#pageTitle")).to_have_text("Providers")
    expect(page.locator("#providerGroups")).to_be_visible()

    search.fill("voice")
    page.get_by_role("button", name="Studio", exact=True).click()
    expect(search).to_have_value("")
    expect(page.locator("#pageTitle")).to_have_text("Studio")
