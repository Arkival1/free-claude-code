"""FCC Phone on an iPhone-sized screen: its own agents, memory, free brains, and PC link."""

import json
from collections.abc import Callable

from playwright.sync_api import Page, Route, ViewportSize, expect

IPHONE_12_PRO = ViewportSize(width=390, height=844)
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"
CORS = {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"}


def open_phone(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size(IPHONE_12_PRO)
    page.goto(f"{admin_base_url}/phone/")
    expect(page.locator(".tabs")).to_be_visible()


def fake_gemini(page: Page, answer: Callable[[dict], dict]) -> list[dict]:
    """Serve Gemini's model list and chat replies; record every chat request."""
    seen: list[dict] = []

    def handle(route: Route) -> None:
        url = route.request.url
        if url.endswith("/models"):
            assert route.request.headers["authorization"] == "Bearer test-gemini-key"
            route.fulfill(
                headers=CORS,
                body=json.dumps(
                    {
                        "data": [
                            {"id": "models/text-embedding-004"},
                            {"id": "models/gemini-2.0-flash"},
                            {"id": "models/gemini-2.5-flash"},
                            {"id": "models/gemini-2.5-flash-lite"},
                            {"id": "models/gemini-2.5-pro"},
                        ]
                    }
                ),
            )
            return
        body = json.loads(route.request.post_data or "{}")
        seen.append(body)
        route.fulfill(
            headers=CORS, body=json.dumps({"choices": [{"message": answer(body)}]})
        )

    page.route(f"{GEMINI}/**", handle)
    return seen


def tool_call(name: str, arguments: dict) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": f"call_{name}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def use_gemini(page: Page) -> None:
    page.locator('.tab[data-route="settings"]').click()
    page.get_by_label("Google Gemini key").fill("test-gemini-key")
    page.get_by_role("button", name="Save Google Gemini").click()
    expect(page.get_by_text("using gemini-2.5-flash")).to_be_visible()
    expect(page.get_by_label("Google Gemini model")).to_have_value("gemini-2.5-flash")


def test_the_phone_app_runs_on_its_own(page: Page, admin_base_url: str) -> None:
    open_phone(page, admin_base_url)
    expect(page.get_by_role("heading", name="Start here")).to_be_visible()
    expect(page.locator("#subtitle")).to_contain_text("Pick a free brain")
    assert page.evaluate("() => document.documentElement.scrollWidth - innerWidth") <= 0
    manifest = page.request.get(f"{admin_base_url}/phone/manifest.webmanifest")
    assert manifest.ok and manifest.json()["display"] == "standalone"
    assert page.request.get(f"{admin_base_url}/phone/sw.js").ok
    assert page.evaluate("() => window.fccPhone.calculate('15% of 240 + 2^3')") == 44
    assert page.evaluate("() => window.fccPhone.calculate('sqrt(81) * (2 + 1)')") == 27
    assert (
        page.evaluate(
            "() => window.fccPhone.bestModel('openrouter', ["
            "{id: 'a:free', context_length: 8000},"
            "{id: 'b:free', context_length: 128000, supported_parameters: ['tools']},"
            "{id: 'c', context_length: 1000000}])"
        )
        == "b:free"
    )


def test_an_agent_remembers_with_a_free_brain(page: Page, admin_base_url: str) -> None:
    def answer(body: dict) -> dict:
        last = body["messages"][-1]
        if last["role"] == "user" and "gym" in last["content"]:
            return tool_call(
                "remember", {"text": "The user's gym days are Monday and Thursday."}
            )
        if last["role"] == "user" and "weather" in last["content"]:
            return tool_call("weather", {"place": "Oslo", "days": 2})
        if last["role"] == "tool":
            return {
                "role": "assistant",
                "content": f"Done. ({last['content'].splitlines()[0]})",
            }
        return {"role": "assistant", "content": "Hello!"}

    seen = fake_gemini(page, answer)
    page.route(
        "https://geocoding-api.open-meteo.com/**",
        lambda route: route.fulfill(
            headers=CORS,
            body=json.dumps(
                {
                    "results": [
                        {
                            "name": "Oslo",
                            "country": "Norway",
                            "latitude": 59.9,
                            "longitude": 10.7,
                        }
                    ]
                }
            ),
        ),
    )
    page.route(
        "https://api.open-meteo.com/**",
        lambda route: route.fulfill(
            headers=CORS,
            body=json.dumps(
                {
                    "current": {
                        "temperature_2m": 4.2,
                        "apparent_temperature": 1.0,
                        "relative_humidity_2m": 80,
                        "weather_code": 61,
                        "wind_speed_10m": 12,
                    },
                    "daily": {
                        "time": ["2026-09-27", "2026-09-28"],
                        "weather_code": [61, 3],
                        "temperature_2m_max": [7, 9],
                        "temperature_2m_min": [2, 3],
                        "precipitation_probability_max": [70, 20],
                    },
                }
            ),
        ),
    )
    open_phone(page, admin_base_url)
    use_gemini(page)
    expect(page.locator("#subtitle")).to_contain_text(
        "Jarvis · Google Gemini · gemini-2.5-flash"
    )

    page.locator('.tab[data-route="chat"]').click()
    expect(page.get_by_role("heading", name="Start here")).to_have_count(0)
    page.get_by_label("Message").fill("Remember my gym days are Monday and Thursday")
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".msg.tool")).to_contain_text("remember: Saved to memory")
    expect(page.locator(".msg.assistant").last).to_contain_text("Done.")
    expect(page.locator(".typing")).to_have_count(0)

    first = seen[0]
    assert first["model"] == "gemini-2.5-flash"
    assert first["messages"][0]["role"] == "system"
    assert "You are Jarvis, the user's main AI." in first["messages"][0]["content"]
    assert [tool["function"]["name"] for tool in first["tools"]] == [
        "remember",
        "recall",
        "calculate",
        "weather",
        "wikipedia",
    ]
    after_tool = seen[1]["messages"]
    assert after_tool[-2]["tool_calls"][0]["function"]["name"] == "remember"
    assert after_tool[-1] == {
        "role": "tool",
        "tool_call_id": "call_remember",
        "content": "Saved to memory: The user's gym days are Monday and Thursday.",
    }

    page.get_by_label("Message").fill("What's the weather in Oslo?")
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".msg.assistant").last).to_contain_text(
        "Weather in Oslo, Norway: now 4°C (feels like 1°C), light rain"
    )

    page.locator('.tab[data-route="memory"]').click()
    here = page.locator(".card", has=page.get_by_role("heading", name="On this phone"))
    expect(
        here.get_by_text("The user's gym days are Monday and Thursday.", exact=True)
    ).to_be_visible()

    page.reload()
    page.locator('.tab[data-route="chat"]').click()
    expect(page.locator(".msg.user").first).to_contain_text("gym days")
    page.get_by_label("Message").fill("hi again")
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".msg.assistant").last).to_contain_text("Hello!")
    assert "gym days are Monday" in seen[-1]["messages"][0]["content"], (
        "what it remembers rides on every message"
    )


def test_agents_can_be_added_and_deleted(page: Page, admin_base_url: str) -> None:
    open_phone(page, admin_base_url)
    page.locator('.tab[data-route="agents"]').click()
    page.get_by_role("button", name="Coach", exact=True).click()
    sheet = page.locator(".sheet-panel")
    expect(sheet.get_by_label("Name")).to_have_value("Coach")
    sheet.get_by_role("button", name="Create agent").click()
    expect(page.get_by_role("button", name="Chat with Coach")).to_be_visible()
    expect(page.get_by_role("button", name="Edit Jarvis")).to_be_visible()

    page.get_by_role("button", name="Edit Jarvis").click()
    expect(sheet.get_by_role("button", name="Delete")).to_have_count(0)
    sheet.get_by_label("Close").click()

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Edit Coach").click()
    sheet.get_by_role("button", name="Delete").click()
    expect(page.get_by_role("button", name="Chat with Coach")).to_have_count(0)


def test_the_phone_pairs_with_the_pc_and_shares_memory(
    page: Page, admin_base_url: str
) -> None:
    assert page.request.post(
        f"{admin_base_url}/studio/api/memory/shared",
        data={"text": "The user's car is a blue Corolla."},
    ).ok
    code = page.request.post(f"{admin_base_url}/studio/api/phones/code").json()["code"]
    open_phone(page, admin_base_url)
    page.locator('.tab[data-route="memory"]').click()
    page.get_by_label("New memory").fill("Mum's birthday is 12 March.")
    page.get_by_role("button", name="Add").click()

    page.locator('.tab[data-route="settings"]').click()
    page.get_by_label("PC address").fill(admin_base_url)
    page.get_by_label("Pairing code").fill(code.lower())
    page.get_by_role("button", name="Pair", exact=True).click()
    expect(page.get_by_role("heading", name="My PC")).to_be_visible()
    expect(page.locator("#link-pill")).to_have_text("PC ✓")
    expect(page.get_by_label("Let cloud brains see PC memories")).not_to_be_checked()

    shared = page.request.get(f"{admin_base_url}/studio/api/memory/shared").json()
    phone_rows = [row for row in shared["memories"] if "phone" in row["tags"]]
    assert [row["text"] for row in phone_rows] == ["Mum's birthday is 12 March."]
    assert phone_rows[0]["author"] == "Jarvis (phone)"

    page.locator('.tab[data-route="memory"]').click()
    expect(page.get_by_text("The user's car is a blue Corolla.")).to_be_visible()
    expect(page.get_by_text("Kept private")).to_be_visible()
    expect(page.get_by_text("on your PC")).to_be_visible()

    # With no key at all, Jarvis on the phone can think with the PC's AI.
    page.locator('.tab[data-route="settings"]').click()
    page.get_by_label("Default brain").select_option("pc")
    page.locator('.tab[data-route="chat"]').click()
    page.get_by_label("Message").fill("hello from the phone")
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".msg.assistant").last).to_contain_text("Jarvis (")
    expect(page.locator(".msg.assistant").last).to_contain_text("is on it.")

    phones = page.request.get(f"{admin_base_url}/studio/api/phones").json()["phones"]
    assert phones[0]["name"] in {"Phone", "iPhone"} and phones[0]["memories_in"] == 1


def test_the_pc_makes_pairing_codes(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size(IPHONE_12_PRO)
    page.goto(f"{admin_base_url}/studio#more")
    phone = page.locator(".card", has=page.get_by_role("heading", name="FCC Phone"))
    expect(phone).to_contain_text("Add to Home Screen")
    expect(phone).to_contain_text("No phone paired yet.")
    phone.get_by_role("button", name="Make a pairing code").click()
    expect(phone.locator(".pair-code strong")).to_have_text(
        __import__("re").compile(r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
    )
    expect(phone).to_contain_text("It works once")
