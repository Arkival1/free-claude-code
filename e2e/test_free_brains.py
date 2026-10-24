"""Free AI services are ready in the brain pickers: FreeLLMAPI's choices,
OpenRouter's free models and the free-tier providers, or how to add a key."""

from playwright.sync_api import Page, expect

from e2e.test_studio_iphone import open_hud

FREE = {
    "services": [
        {
            "id": "freellmapi",
            "name": "FreeLLMAPI (on this PC)",
            "about": "Runs on your PC.",
            "ready": True,
            "models": [
                {"id": "freellmapi/auto", "note": "any"},
                {"id": "freellmapi/auto:coding", "note": "code"},
            ],
            "key_url": "http://localhost:3001",
            "setup": "Admin, Providers, FreeLLMAPI (on this PC): paste the key.",
        },
        {
            "id": "groq",
            "name": "Groq",
            "about": "Free and very fast.",
            "ready": False,
            "models": [],
            "key_url": "https://console.groq.com/keys",
            "setup": "Admin, Providers, Groq: paste the key.",
        },
    ]
}


def test_a_free_service_is_one_click_from_jarvis_brain(
    page: Page, admin_base_url: str
) -> None:
    used: list[dict] = []
    page.route("**/studio/api/models/free", lambda route: route.fulfill(json=FREE))

    def use(route) -> None:
        used.append(route.request.post_data_json)
        route.fulfill(json={"model": used[-1]["model"], "agents_changed": 1})

    page.route("**/studio/api/models/use", use)
    open_hud(page, admin_base_url)
    page.get_by_role("button", name="CHOOSE BRAIN", exact=True).click()
    sheet = page.locator(".sheet-panel")
    expect(sheet).to_contain_text("Or a free AI service")
    groq = sheet.locator(".free-service", has_text="Groq")
    expect(groq).to_contain_text("Needs a key")
    expect(groq.get_by_role("link", name="Get a free key")).to_have_attribute(
        "href", "https://console.groq.com/keys"
    )
    sheet.get_by_role("button", name="Use freellmapi/auto:coding").click()
    expect(sheet).to_be_hidden()
    assert used == [{"model": "freellmapi/auto:coding", "everyone": False}]
    wide = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert wide <= 2


def test_team_brains_always_offer_freellmapi(page: Page, admin_base_url: str) -> None:
    page.route("**/studio/api/models/free", lambda route: route.fulfill(json=FREE))
    open_hud(page, admin_base_url)
    page.get_by_role("button", name="Team brains A model for each agent").click()
    sheet = page.locator(".sheet-panel")
    builder = sheet.get_by_label("Model for Builder")
    builder.select_option("freellmapi/auto:smartest")
    expect(builder).to_have_value("freellmapi/auto:smartest")
    sheet.get_by_text("Free AI services: which are ready").click()
    expect(sheet.locator(".free-service", has_text="Groq")).to_contain_text(
        "Needs a key"
    )
    # A ready service's button fills in the agent last tapped.
    researcher = sheet.get_by_label("Model for Researcher")
    researcher.focus()
    sheet.get_by_role("button", name="Use freellmapi/auto:coding").click()
    expect(researcher).to_have_value("freellmapi/auto:coding")
    expect(sheet).to_contain_text("Researcher will use freellmapi/auto:coding")


def test_listed_freellmapi_models_stay_pickable(
    page: Page, admin_base_url: str
) -> None:
    def team(route) -> None:
        body = route.fetch().json()
        body["server"] = [*body.get("server", []), "freellmapi/gemini-2.5-flash"]
        route.fulfill(json=body)

    page.route("**/studio/api/team-models", team)
    page.route("**/studio/api/models/free", lambda route: route.fulfill(json=FREE))
    open_hud(page, admin_base_url)
    page.get_by_role("button", name="Team brains A model for each agent").click()
    sheet = page.locator(".sheet-panel")
    builder = sheet.get_by_label("Model for Builder")
    builder.select_option("freellmapi/gemini-2.5-flash")
    expect(builder).to_have_value("freellmapi/gemini-2.5-flash")
    expect(builder.locator("option", has_text="(not found)")).to_have_count(0)
    # Nothing tapped yet: the button says what to do instead of guessing.
    sheet.get_by_text("Free AI services: which are ready").click()
    sheet.get_by_role("button", name="Use freellmapi/auto", exact=True).click()
    expect(sheet).to_contain_text("Tap an agent's model list above first")
