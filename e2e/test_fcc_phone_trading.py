"""FCC Phone's Trading and Plugins screens on an iPhone 12 Pro screen, paired
with a real FCC server, and the FCC designs as phone Builder templates."""

from playwright.sync_api import Page, expect

from .test_fcc_phone import go, open_phone


def pair(page: Page, admin_base_url: str) -> None:
    code = page.request.post(f"{admin_base_url}/studio/api/phones/code").json()["code"]
    open_phone(page, admin_base_url, "settings")
    page.get_by_label("PC address").fill(admin_base_url)
    page.get_by_label("Pairing code").fill(code)
    page.get_by_role("button", name="Pair", exact=True).click()
    expect(page.get_by_role("button", name="Unpair")).to_be_visible()


def no_sideways_scroll(page: Page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def test_the_trading_card_runs_practice_from_the_phone(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_phone(page, admin_base_url, "trade")
    expect(page.get_by_role("button", name="Pair with my PC")).to_be_visible()

    pair(page, admin_base_url)
    go(page, "more")
    page.get_by_role("button", name="Trading: Your PC's Trading Bank").click()
    expect(page.get_by_role("heading", name="Desk")).to_be_visible()
    expect(page.get_by_text("Stopped · paper")).to_be_visible()
    expect(
        page.get_by_text("Real money, keys and settings are changed on the PC only.")
    ).to_be_visible()
    no_sideways_scroll(page)

    page.get_by_role("button", name="Start practice").click()
    expect(page.get_by_role("button", name="Stop")).to_be_visible()
    assert page.request.get(f"{admin_base_url}/studio/api/trading").json()["running"]
    page.get_by_role("button", name="Stop").click()
    expect(page.get_by_role("button", name="Start practice")).to_be_visible()

    page.get_by_role("button", name="Kill switch").click()
    page.get_by_role("button", name="Stop everything").click()
    expect(page.get_by_role("alert")).to_contain_text("Kill switch on")
    expect(page.get_by_role("button", name="Start practice")).to_be_disabled()
    assert page.request.post(f"{admin_base_url}/studio/api/trading/kill/release").ok
    assert errors == []


def test_plugins_and_the_design_templates(page: Page, admin_base_url: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    pair(page, admin_base_url)
    go(page, "plugins")
    expect(page.get_by_role("heading", name="How it works")).to_be_visible()
    expect(page.get_by_role("heading", name="Switched on", exact=False)).to_be_visible()
    expect(page.get_by_label("GitHub repo")).to_be_visible()
    expect(page.get_by_role("heading", name="Subagents", exact=False)).to_be_visible()
    page.get_by_label("Subagent name").fill("Checker")
    page.get_by_label("Subagent role").select_option("tester")
    page.get_by_role("button", name="Add a subagent").click()
    expect(page.get_by_label("Checker on")).to_be_checked()
    page.get_by_label("Checker on").uncheck()
    expect(page.get_by_label("Checker on")).not_to_be_checked()
    no_sideways_scroll(page)

    # With no model on the phone, agents think with the PC: nothing to download.
    assert page.evaluate("() => window.fccPhone.brainOf({brain: 'default'})") == "pc"

    files = page.evaluate(
        "() => window.fccPhone.templateFiles('cafe-warm', 'Bean There')"
    )
    assert set(files) == {"index.html", "styles.css", "app.js"}
    assert "<title>Bean There</title>" in files["index.html"]
    assert files["index.html"].count("Bean There") >= 3
    assert "https://" not in files["index.html"]
    assert errors == []


def test_leaving_settings_while_pairing_keeps_the_new_screen(
    page: Page, admin_base_url: str
) -> None:
    code = page.request.post(f"{admin_base_url}/studio/api/phones/code").json()["code"]
    open_phone(page, admin_base_url, "settings")
    page.get_by_label("PC address").fill(admin_base_url)
    page.get_by_label("Pairing code").fill(code)
    page.get_by_role("button", name="Pair", exact=True).click()
    go(page, "todos")
    expect(page.get_by_text("PC ✓")).to_be_visible()
    expect(page.get_by_role("heading", name="Add a to-do")).to_be_visible()
    expect(page.get_by_label("Default brain")).to_have_count(0)


SCREENS = (
    "home",
    "chats",
    "chat/jarvis",
    "agents",
    "agents/brains",
    "models",
    "more",
    "projects",
    "rooms",
    "learn",
    "todos",
    "memory",
    "settings",
    "help",
    "trade",
    "plugins",
    "tasks",
    "hq",
)


def test_every_screen_opens_cleanly_on_an_iphone(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    pair(page, admin_base_url)
    for screen in SCREENS:
        go(page, screen)
        page.wait_for_timeout(400)
        assert "Something went wrong" not in page.locator("#view").inner_text(), screen
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth + 1"
        ), f"{screen} scrolls sideways"
    assert errors == []


def test_tasks_start_on_the_pc(page: Page, admin_base_url: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_phone(page, admin_base_url, "tasks")
    expect(page.get_by_role("button", name="Pair with my PC")).to_be_visible()
    pair(page, admin_base_url)
    go(page, "more")
    page.get_by_role("button", name="Tasks: Give your PC's team a whole job").click()
    expect(page.get_by_role("heading", name="New task")).to_be_visible()
    page.get_by_role("button", name="Start").click()
    expect(page.get_by_text("Say what the job is first.")).to_be_visible()
    page.get_by_label("The job").fill("Research three tradie websites")
    page.get_by_role("button", name="Start").click()
    expect(page.get_by_role("heading", name="Steps")).to_be_visible()
    plans = page.request.get(f"{admin_base_url}/studio/api/plans").json()["plans"]
    assert plans[0]["goal"] == "Research three tradie websites"
    no_sideways_scroll(page)
    assert errors == []


def test_the_hq_shows_the_pc_team(page: Page, admin_base_url: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    pair(page, admin_base_url)
    go(page, "more")
    page.get_by_role("button", name="HQ: Your PC's team at work").click()
    expect(page.get_by_role("heading", name="The office")).to_be_visible()
    page.get_by_role("button", name="Jarvis:").first.click()
    expect(page.get_by_label("Message for Jarvis")).to_be_visible()
    page.get_by_label("Message for Jarvis").fill("hello from the phone HQ")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.get_by_text("Jarvis is on it, on your PC.")).to_be_visible()
    no_sideways_scroll(page)
    assert errors == []
