"""FCC Phone on an iPhone 12 Pro screen: the command center, team, models, and PC link."""

import json
import re
import struct
from collections.abc import Callable

from playwright.sync_api import Page, Route, ViewportSize, expect

IPHONE_12_PRO = ViewportSize(width=390, height=844)
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"
CORS = {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"}


def open_phone(page: Page, admin_base_url: str, route: str = "home") -> None:
    page.set_viewport_size(IPHONE_12_PRO)
    page.goto(f"{admin_base_url}/phone/#{route}")
    expect(page.locator(".tabs")).to_be_visible()
    # Wait for saved data to load, so a test's changes aren't loaded over.
    page.wait_for_function("() => window.fccPhone && window.fccPhone.ready")
    page.evaluate("() => window.fccPhone.ready")


def go(page: Page, route: str) -> None:
    page.evaluate(f"location.hash = {json.dumps(route)}")


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


def say(text: str) -> dict:
    return {"role": "assistant", "content": text}


BAKERY = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<title>Sunrise Bakery</title><link rel='stylesheet' href='style.css'></head>"
    "<body><header><h1>Sunrise Bakery</h1></header><main><p>Fresh bread daily.</p></main></body></html>"
)


def team_brain(body: dict) -> dict:
    """A scripted Gemini that plays every agent by reading its instructions."""
    system = body["messages"][0]["content"]
    last = body["messages"][-1]
    said = last.get("content") or ""
    if "You plan short courses" in system:
        return say('["What stars are", "Planets"]')
    if "You write clear study notes" in system:
        return say("Stars are huge balls of hot gas.\nKey idea: fusion powers them.")
    if "in a group chat" in system:
        found = re.search(r"You are (\w+)", system)
        name = found.group(1) if found else "Agent"
        if "The room's goal" in system:
            return say("TASK COMPLETE: the plan is ready.")
        return say(f"Hello from {name}.")
    if "You are Builder" in system:
        if last["role"] == "user":
            return tool_call("write_file", {"path": "index.html", "content": BAKERY})
        if "Wrote index.html" in said:
            return tool_call(
                "write_file", {"path": "style.css", "content": "h1 { color: teal; }"}
            )
        if "Wrote style.css" in said:
            return tool_call("check_project", {})
        return say("Built index.html and style.css for Sunrise Bakery.")
    if last["role"] == "tool":
        return say(f"Done. ({said.splitlines()[0]})")
    if "gym" in said:
        return tool_call(
            "remember", {"text": "The user's gym days are Monday and Thursday."}
        )
    if "weather" in said:
        return tool_call("weather", {"place": "Oslo", "days": 2})
    if "bakery" in said:
        return tool_call(
            "ask_agent",
            {
                "agent": "Builder",
                "task": "Make a one-page site for Sunrise Bakery.",
                "project": "Sunrise Bakery",
            },
        )
    return say("Hi!")


def fake_gemini(page: Page, answer: Callable[[dict], dict] = team_brain) -> list[dict]:
    seen: list[dict] = []

    def handle(route: Route) -> None:
        if route.request.url.endswith("/models"):
            route.fulfill(
                headers=CORS,
                body=json.dumps(
                    {
                        "data": [
                            {"id": "models/text-embedding-004"},
                            {"id": "models/gemini-2.0-flash"},
                            {"id": "models/gemini-2.5-flash"},
                            {"id": "models/gemini-2.5-flash-lite"},
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
    page.route(
        "https://en.wikipedia.org/**",
        lambda route: route.fulfill(
            headers=CORS,
            body=json.dumps(
                {"query": {"search": [{"title": "Star"}]}}
                if "api.php" in route.request.url
                else {
                    "title": "Star",
                    "extract": "A star is a luminous ball of gas.",
                    "content_urls": {
                        "mobile": {"page": "https://en.m.wikipedia.org/wiki/Star"}
                    },
                }
            ),
        ),
    )
    return seen


def use_gemini(page: Page) -> None:
    go(page, "settings")
    page.get_by_label("Google Gemini key").fill("test-gemini-key")
    page.get_by_role("button", name="Save Google Gemini").click()
    expect(page.get_by_text("using gemini-2.5-flash")).to_be_visible()


def fake_gguf(*, tools: bool) -> bytes:
    def text(value: str) -> bytes:
        raw = value.encode()
        return struct.pack("<Q", len(raw)) + raw

    template = "{% if tools %}<tool_call>{% endif %}" if tools else "{{ messages }}"
    pairs = [
        ("general.architecture", 8, text("qwen2")),
        ("general.name", 8, text("Tiny Coder")),
        ("general.size_label", 8, text("1.5B")),
        ("qwen2.block_count", 4, struct.pack("<I", 28)),
        ("qwen2.context_length", 4, struct.pack("<I", 32768)),
        ("qwen2.embedding_length", 4, struct.pack("<I", 1536)),
        ("qwen2.attention.head_count", 4, struct.pack("<I", 12)),
        ("qwen2.attention.head_count_kv", 4, struct.pack("<I", 2)),
        ("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 8, 2) + text("a") + text("b")),
        ("tokenizer.chat_template", 8, text(template)),
    ]
    header = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, len(pairs))
    return header + b"".join(
        text(key) + struct.pack("<I", kind) + value for key, kind, value in pairs
    )


# --------------------------------------------------------------------- tests


def test_home_is_the_jarvis_command_center(page: Page, admin_base_url: str) -> None:
    open_phone(page, admin_base_url)
    expect(page.locator(".hud-title")).to_have_text("JARVIS")
    expect(page.locator(".orb-canvas")).to_be_visible()
    expect(page.locator(".hud-chips")).to_contain_text("CORE NOT SET")
    team = page.locator(".hud-agent")
    expect(team).to_have_count(5)
    for name in ("Jarvis", "Builder", "Researcher", "Helper", "Tester"):
        expect(team.filter(has_text=name)).to_contain_text("READY")
    expect(page.locator(".hud-log")).to_contain_text("needs a brain")
    assert page.evaluate("() => document.documentElement.scrollWidth - innerWidth") <= 0

    page.get_by_role("button", name="Model control Models on this phone").click()
    expect(page.locator("#title")).to_have_text("Models")
    expect(page.get_by_role("button", name="Download Qwen3 0.6B")).to_be_visible()
    assert page.evaluate("() => window.fccPhone.calculate('15% of 240 + 2^3')") == 44
    assert page.evaluate("() => window.fccPhone.calculate('sqrt(81) * (2 + 1)')") == 27
    problems = page.evaluate(
        "() => window.fccPhone.checkProject({name: 'x', files: {'index.html': '<p><img src=a.png>'}})"
    )
    assert any("DOCTYPE" in p for p in problems) and any("a.png" in p for p in problems)
    bundled = page.evaluate(
        "() => window.fccPhone.bundle({files: {'index.html': "
        '\'<link rel="stylesheet" href="s.css"><script src="a.js"></script>\', '
        "'s.css': 'h1{}', 'a.js': 'x=1'}})"
    )
    assert "<style>" in bundled and "x=1" in bundled


def test_jarvis_remembers_checks_the_weather_and_runs_the_builder(
    page: Page, admin_base_url: str
) -> None:
    seen = fake_gemini(page)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "home")
    expect(page.locator(".hud-chips")).to_contain_text("CORE GEMINI")

    talk = page.get_by_label("Message Jarvis")
    talk.fill("Remember my gym days are Monday and Thursday")
    talk.press("Enter")
    expect(page.locator(".hud-line.assistant").last).to_contain_text(
        "Done. (Saved to your own memory"
    )
    first = seen[0]
    assert first["model"] == "gemini-2.5-flash"
    assert "You are Jarvis, the user's main AI." in first["messages"][0]["content"]
    assert {tool["function"]["name"] for tool in first["tools"]} >= {
        "remember",
        "ask_agent",
        "todo",
        "learn",
    }

    talk.fill("What's the weather in Oslo?")
    talk.press("Enter")
    expect(page.locator(".hud-line.assistant").last).to_contain_text(
        "Weather in Oslo, Norway: now 4°C"
    )

    talk.fill("Have Builder make a page for my bakery")
    talk.press("Enter")
    expect(page.locator(".hud-line.assistant").last).to_contain_text(
        "Builder finished", timeout=15000
    )
    expect(page.locator(".hud-feed")).to_contain_text("Wrote Sunrise Bakery/index.html")
    builder_calls = [
        call for call in seen if "You are Builder" in call["messages"][0]["content"]
    ]
    assert "write_file" in {
        tool["function"]["name"] for tool in builder_calls[0]["tools"]
    }

    go(page, "projects")
    page.get_by_role("button", name="Open Sunrise Bakery").click()
    preview = page.frame_locator("iframe.preview")
    expect(preview.locator("h1")).to_have_text("Sunrise Bakery")
    files = page.locator(
        ".card", has=page.get_by_role("heading", name=re.compile(r"Files$"))
    )
    expect(files).to_contain_text("style.css")
    color = preview.locator("h1").evaluate("el => getComputedStyle(el).color")
    assert color == "rgb(0, 128, 128)", "the stylesheet is inlined into the preview"
    page.get_by_role("button", name="Open full screen").click()
    expect(page.frame_locator("iframe.preview-full").locator("h1")).to_have_text(
        "Sunrise Bakery"
    )
    page.get_by_role("button", name="Close full screen").click()

    go(page, "memory")
    expect(
        page.get_by_text("The user's gym days are Monday and Thursday.", exact=True)
    ).to_be_visible()


def test_each_agent_has_its_own_brain_and_tools(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url, "agents")
    expect(page.locator(".card", has_text="Your phone team")).to_contain_text("Helper")
    page.get_by_role("button", name="Edit Helper").click()
    sheet = page.locator(".sheet-panel")
    expect(sheet.get_by_label("weather for Helper")).to_be_checked()
    read = sheet.get_by_label("read_file for Helper")
    expect(read).not_to_be_checked()
    expect(sheet.get_by_label("team_status for Helper")).to_have_count(0)
    expect(sheet.get_by_label("web_search for Helper")).to_be_disabled()
    sheet.get_by_label("Every tool for Helper").check()
    expect(read).to_be_checked()
    expect(read).to_be_disabled()
    expect(sheet.locator(".tool-count")).to_contain_text("Every tool")
    sheet.get_by_role("button", name="Save").click()
    expect(page.locator(".item", has_text="Helper")).to_contain_text("every tool")

    page.get_by_role("button", name="Coach").click()
    expect(sheet.get_by_label("Name")).to_have_value("Coach")
    sheet.get_by_role("button", name="Create agent").click()
    expect(page.get_by_role("button", name="Edit Coach")).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Edit Coach").click()
    sheet.get_by_role("button", name="Delete").click()
    expect(page.get_by_role("button", name="Edit Coach")).to_have_count(0)

    go(page, "agents/brains")
    page.get_by_label("Brain for Builder").select_option("gemini")
    page.get_by_role("button", name="Save").click()
    expect(page.locator(".item", has_text="Builder")).to_contain_text("Google Gemini")


def test_models_can_be_added_from_files(page: Page, admin_base_url: str) -> None:
    open_phone(page, admin_base_url, "models")
    chooser = page.get_by_label("Choose a model file")
    chooser.set_input_files(
        files=[
            {
                "name": "notes.txt",
                "mimeType": "text/plain",
                "buffer": b"hello there, not a model" * 4,
            }
        ]
    )
    expect(page.get_by_role("status").last).to_have_text(
        "This isn't a GGUF model file."
    )

    chooser.set_input_files(
        files=[
            {
                "name": "tiny-coder-1.5b-q4_k_m.gguf",
                "mimeType": "application/octet-stream",
                "buffer": fake_gguf(tools=True),
            }
        ]
    )
    expect(
        page.get_by_text("tiny-coder-1.5b-q4_k_m added. It can use tools.")
    ).to_be_visible()
    row = page.locator(".model", has_text="tiny-coder-1.5b-q4_k_m")
    for badge in ("Tools", "1.5B", "from Files", "Needs about"):
        expect(row).to_contain_text(badge)
    expect(row.locator(".pill.gold", has_text="default")).to_be_visible()
    page.reload()
    expect(page.locator(".model", has_text="tiny-coder-1.5b-q4_k_m")).to_be_visible()

    go(page, "agents/brains")
    page.get_by_label("Brain for Jarvis").select_option("local")
    expect(page.get_by_label("Phone model for Jarvis")).to_contain_text(
        "tiny-coder-1.5b-q4_k_m"
    )

    go(page, "models")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete tiny-coder-1.5b-q4_k_m").click()
    expect(page.locator(".model", has_text="tiny-coder-1.5b-q4_k_m")).to_have_count(0)


def test_rooms_learning_and_reminders(page: Page, admin_base_url: str) -> None:
    fake_gemini(page)
    open_phone(page, admin_base_url)
    use_gemini(page)

    go(page, "rooms")
    for name in ("Builder", "Tester"):
        page.get_by_label(f"{name} in the room").uncheck()
    page.get_by_role("button", name="Open the room").click()
    page.get_by_label("Message the room").fill("hello team")
    page.get_by_role("button", name="Send").click()
    expect(
        page.locator(".msg.assistant", has_text="Hello from Researcher.")
    ).to_be_visible()
    expect(
        page.locator(".msg.assistant", has_text="Hello from Helper.")
    ).to_be_visible()
    page.get_by_label("Room goal").fill("Plan a picnic")
    page.get_by_role("button", name="Start task").click()
    expect(page.locator(".msg.assistant").last).to_contain_text("TASK COMPLETE")

    go(page, "learn")
    page.get_by_label("Subject").fill("astronomy")
    page.get_by_label("How deep").select_option("quick")
    page.get_by_role("button", name="Start learning").click()
    study = page.get_by_role("button", name="Open astronomy")
    expect(study).to_contain_text("done", timeout=15000)
    study.click()
    expect(page.locator(".card", has_text="Lesson 1: What stars are")).to_contain_text(
        "huge balls of hot gas"
    )
    go(page, "memory")
    expect(page.locator(".card", has_text="On this phone")).to_contain_text(
        "Learned (astronomy"
    )

    go(page, "todos")
    page.get_by_label("To-do", exact=True).fill("Call Sam")
    page.get_by_label("Reminder").fill("in 0 minutes")
    page.get_by_role("button", name="Add").click()
    expect(page.locator(".item", has_text="Call Sam")).to_contain_text("reminder")
    page.evaluate("() => window.fccPhone.checkReminders()")
    expect(page.locator("#toast")).to_have_text("Reminder: Call Sam")


def test_the_phone_pairs_with_the_pc(page: Page, admin_base_url: str) -> None:
    assert page.request.post(
        f"{admin_base_url}/studio/api/memory/shared",
        data={"text": "The user's car is a blue Corolla."},
    ).ok
    code = page.request.post(f"{admin_base_url}/studio/api/phones/code").json()["code"]
    open_phone(page, admin_base_url, "memory")
    page.get_by_label("New memory").fill("Mum's birthday is 12 March.")
    page.get_by_role("button", name="Add").click()

    go(page, "settings")
    page.get_by_label("PC address").fill(admin_base_url)
    page.get_by_label("Pairing code").fill(code.lower())
    page.get_by_role("button", name="Pair", exact=True).click()
    expect(page.get_by_role("heading", name="My PC")).to_be_visible()
    expect(page.get_by_label("Let cloud brains see PC memories")).not_to_be_checked()

    shared = page.request.get(f"{admin_base_url}/studio/api/memory/shared").json()
    from_phone = [row for row in shared["memories"] if "phone" in row["tags"]]
    assert [row["text"] for row in from_phone] == ["Mum's birthday is 12 March."]

    go(page, "memory")
    expect(page.get_by_text("The user's car is a blue Corolla.")).to_be_visible()
    expect(page.get_by_text("Kept private")).to_be_visible()

    go(page, "settings")
    page.get_by_label("Default brain").select_option("pc")
    go(page, "chat/jarvis")
    page.get_by_label("Message").fill("hello from the phone")
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".msg.assistant").last).to_contain_text("is on it.")

    go(page, "agents")
    page.get_by_role("button", name="Edit Researcher").click()
    expect(
        page.locator(".sheet-panel").get_by_label("web_search for Researcher")
    ).to_be_enabled()


def test_a_backup_can_be_saved(page: Page, admin_base_url: str) -> None:
    open_phone(page, admin_base_url, "settings")
    with page.expect_download() as download:
        page.get_by_role("button", name="Save a backup").click()
    with open(download.value.path()) as handle:
        saved = json.load(handle)
    assert saved["app"] == "FCC Phone" and len(saved["agents"]) == 5
    assert "keys" not in saved["settings"] and "pc" not in saved["settings"]
