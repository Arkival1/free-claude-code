"""The Studio app on an iPhone-sized viewport: reachable, sized, installable."""

from playwright.sync_api import Page, ViewportSize, expect

IPHONE_VIEWPORT = ViewportSize(width=390, height=844)  # iPhone 15/16 CSS pixels
MIN_TAP_TARGET = 44.0


def open_studio(page: Page, admin_base_url: str, screen: str = "more") -> None:
    """Open one of Studio's pages (everything but the command center)."""
    page.set_viewport_size(IPHONE_VIEWPORT)
    page.goto(f"{admin_base_url}/studio#{screen}")
    expect(page.locator(".tab-bar")).to_be_visible()


def open_hud(page: Page, admin_base_url: str) -> None:
    """Open Studio's home: the main AI's command center."""
    page.set_viewport_size(IPHONE_VIEWPORT)
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator(".hud")).to_be_visible()


def test_studio_loads_on_an_iphone_viewport(page: Page, admin_base_url: str) -> None:
    open_hud(page, admin_base_url)

    expect(page.locator(".hud-name")).to_have_text("JARVIS")
    expect(page.get_by_role("button", name="ASK THE GUIDE")).to_be_visible()
    expect(page.locator(".tab-bar")).to_be_hidden()
    assert page.evaluate("document.body.dataset.ui") == "hud"

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 0, "the layout scrolls sideways on an iPhone"

    page.get_by_role("button", name="ASK THE GUIDE").click()
    expect(page.locator(".sheet-panel")).to_be_visible()


def test_every_page_wears_the_hud_look(page: Page, admin_base_url: str) -> None:
    open_studio(page, admin_base_url, "tune")

    assert page.evaluate("document.body.dataset.ui") == "page"
    background = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert background == "rgb(2, 7, 13)", background
    expect(page.get_by_role("button", name="HUD console")).to_have_count(0)
    page.locator('.tab[data-route="home"]').click()
    expect(page.locator(".hud")).to_be_visible()


def test_touch_targets_are_thumb_sized(page: Page, admin_base_url: str) -> None:
    open_studio(page, admin_base_url)

    boxes = page.evaluate(
        """() =>
            [...document.querySelectorAll('.tab, button.primary, button.secondary')]
                .filter((node) => node.offsetParent !== null)
                .map((node) => node.getBoundingClientRect().height)"""
    )

    assert boxes, "no interactive controls were rendered"
    assert min(boxes) >= MIN_TAP_TARGET


def test_home_screen_install_metadata_is_present(
    page: Page, admin_base_url: str
) -> None:
    open_studio(page, admin_base_url)

    assert page.locator('link[rel="apple-touch-icon"]').count() >= 1
    assert (
        page.locator('meta[name="apple-mobile-web-app-capable"]').get_attribute(
            "content"
        )
        == "yes"
    )
    manifest = page.request.get(f"{admin_base_url}/studio/manifest.webmanifest").json()
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/studio"


def test_tabs_navigate_without_leaving_the_app(page: Page, admin_base_url: str) -> None:
    open_studio(page, admin_base_url)

    page.locator('.tab[data-route="learn"]').click()
    expect(page.locator("#view-title")).to_have_text("Classroom")
    page.locator('.tab[data-route="more"]').click()
    expect(page.locator(".card", has_text="Install on your iPhone")).to_be_visible()
    expect(page.locator(".list-item", has_text="localhost")).to_be_visible()
    web = page.locator(".card", has_text="Internet access")
    expect(web).to_contain_text("Every agent can search the web")
    expect(web).to_contain_text("DuckDuckGo, no key needed")
    expect(web.get_by_role("button", name="Test search")).to_be_visible()

    page.get_by_label("Search settings").fill("internet")
    expect(web).to_be_visible()
    expect(page.locator(".card", has_text="Install on your iPhone")).to_be_hidden()
    page.get_by_label("Search settings").fill("")
    expect(page.locator(".card", has_text="Install on your iPhone")).to_be_visible()


def test_an_unreachable_server_shows_a_readable_screen(
    page: Page, admin_base_url: str
) -> None:
    open_studio(page, admin_base_url)
    page.route("**/studio/api/**", lambda route: route.abort())

    page.locator('.tab[data-route="chats"]').click()

    expect(
        page.locator(".card", has_text="Can't reach your Studio server")
    ).to_be_visible()
    expect(page.get_by_role("button", name="Try again")).to_be_visible()


def test_agents_answer_each_other_in_a_room(page: Page, admin_base_url: str) -> None:
    for name, model in (("Lead", "open_router/e2e-default"), ("Local", "local/tiny")):
        page.request.post(
            f"{admin_base_url}/studio/api/agents",
            data={"name": name, "model": model, "tools": []},
        )
    open_studio(page, admin_base_url)

    page.locator('.tab[data-route="chats"]').click()
    expect(page.locator(".card", has_text="Agent room")).to_be_visible()
    page.get_by_role("button", name="Open room").click()

    expect(page.locator("#view-title")).to_have_text("Lead & Local")
    expect(page.locator(".pill", has_text="local").first).to_be_visible()

    page.get_by_placeholder("Message the room — @Name to ask one agent").fill("Hi both")
    page.get_by_role("button", name="Send").click()

    expect(page.locator(".bubble.user", has_text="Hi both")).to_be_visible()
    expect(
        page.locator(
            ".bubble.assistant", has_text="Lead (open_router/e2e-default) is on it."
        )
    ).to_be_visible()
    expect(
        page.locator(".bubble.assistant", has_text="Local (tiny) is on it.")
    ).to_be_visible()


def test_a_slow_screen_never_paints_over_the_next_one(
    page: Page, admin_base_url: str
) -> None:
    def slow_overview(route) -> None:
        page.wait_for_timeout(1200)
        route.continue_()

    def is_overview(response) -> bool:
        return response.url.endswith("/studio/api/main")

    page.set_viewport_size(IPHONE_VIEWPORT)
    page.route("**/studio/api/main", slow_overview)
    page.goto(f"{admin_base_url}/studio")

    # Leave while the command center is still loading.
    page.evaluate("location.hash = 'learn'")
    expect(page.locator(".card", has_text="Open a class")).to_be_visible()

    page.wait_for_event("response", is_overview, timeout=10_000)
    page.wait_for_timeout(300)  # time for a stale paint to land, if one could

    expect(page.locator(".card", has_text="Open a class")).to_be_visible()
    expect(page.locator(".hud")).to_have_count(0)


def test_classes_default_to_a_server_teacher_and_a_local_student(
    page: Page, admin_base_url: str
) -> None:
    for name, model in (("Big", "open_router/e2e-default"), ("Small", "local/tiny")):
        page.request.post(
            f"{admin_base_url}/studio/api/agents",
            data={"name": name, "model": model, "tools": []},
        )
    page.set_viewport_size(IPHONE_VIEWPORT)
    page.goto(f"{admin_base_url}/studio#learn")
    card = page.locator(".card", has_text="Open a class")
    expect(card).to_be_visible()

    teacher = card.locator("select").nth(0)
    student = card.locator("select").nth(1)
    expect(teacher.locator("option:checked")).to_contain_text("server")
    expect(student.locator("option:checked")).to_contain_text("local")


def test_lora_job_page_shows_live_training(page: Page, admin_base_url: str) -> None:
    api = page.request
    student = api.post(
        f"{admin_base_url}/studio/api/agents",
        data={"name": "Pocket", "model": "local/tiny", "tools": []},
    ).json()
    pack = api.post(
        f"{admin_base_url}/studio/api/tuning/packs", data={"agent_id": student["id"]}
    ).json()
    api.post(
        f"{admin_base_url}/studio/api/tuning/packs/{pack['id']}/samples",
        data={"pairs": [[f"q{i}", f"a{i}"] for i in range(6)]},
    )
    job = api.post(
        f"{admin_base_url}/studio/api/lora/jobs",
        data={
            "agent_id": student["id"],
            "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
            "runner": "remote",
            "sources": ["examples"],
        },
    ).json()
    for _ in range(50):
        view = api.get(f"{admin_base_url}/studio/api/lora/jobs/{job['id']}").json()
        if view["dataset_ready"]:
            break
        page.wait_for_timeout(100)
    token = view["commands"]["bash"].split("--token ")[1].split()[0]
    worker = f"{admin_base_url}/studio/api/lora/worker/{job['id']}"
    for step, loss in enumerate((2.4, 1.7, 1.2, 0.9, 0.8), start=1):
        api.post(
            f"{worker}/progress",
            headers={"x-lora-token": token},
            data={"step": step, "total": 10, "loss": loss, "eval_loss_before": 2.2},
        )

    page.set_viewport_size(IPHONE_VIEWPORT)
    page.goto(f"{admin_base_url}/studio#lora/{job['id']}")
    expect(page.locator("#view-title")).to_have_text("LoRA training")
    expect(page.locator(".figure", has_text="before")).to_contain_text("2.200")
    chart = page.locator("svg.chart")
    expect(chart).to_be_visible()
    expect(page.locator(".chart-label")).to_have_text("0.8")

    box = chart.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2)
    expect(page.locator(".chart-tip")).to_be_visible()
    expect(page.locator(".chart-tip")).to_contain_text("step")

    page.locator(".chart-table summary").click()
    expect(page.locator(".chart-table tbody tr")).to_have_count(5)
    expect(page.locator("pre.command-block").first).to_contain_text("lora_worker.py")
    expect(page.locator("pre.command-block").first).to_contain_text("llama-quantize")
    expect(page.locator("pre.command-block").nth(1)).to_contain_text("tailscale up")
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 0
    page.screenshot(path="/tmp/claude-0/shots/lora.png", full_page=True)

    api.put(
        f"{worker}/files/adapter.zip",
        headers={"x-lora-token": token, "content-type": "application/octet-stream"},
        data=_tiny_adapter_zip(),
    )
    api.put(
        f"{worker}/files/model.gguf",
        headers={"x-lora-token": token, "content-type": "application/octet-stream"},
        data=b"GGUF" + b"\x00" * 60,
    )
    api.post(
        f"{worker}/finish",
        headers={"x-lora-token": token},
        data={
            "steps": 10,
            "eval_loss_after": 0.7,
            "model_quant": "Q4_K_M",
            "model_gb": 0.4,
        },
    )
    page.reload()
    new_model = page.locator(".card", has_text="Your new model")
    expect(new_model).to_contain_text("merged into its weights (Q4_K_M, 0.4 GB)")
    expect(new_model.get_by_role("button", name="Switch Pocket to it")).to_be_visible()
    expect(page.locator(".list-item", has_text="model.gguf")).to_be_visible()


def _tiny_adapter_zip() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("adapter_config.json", "{}")
    return buffer.getvalue()


def test_the_lora_card_offers_new_weights_for_lm_studio(
    page: Page, admin_base_url: str
) -> None:
    open_studio(page, admin_base_url, "tune")
    card = page.locator(".card", has_text="LoRA: train the weights")
    expect(card).to_be_visible()
    make = card.get_by_label("What to make")
    expect(make).to_have_value("merged")
    expect(card.get_by_label("Model file size")).to_have_value("Q4_K_M")
    card.get_by_label("Where to train").select_option("remote")
    guide = card.locator("details.guide")
    expect(guide).to_be_visible()
    expect(guide).to_contain_text("Tailscale")
    make.select_option("adapter")
    expect(card.get_by_label("Model file size")).to_be_hidden()


def test_the_hud_runs_the_main_ai_and_survives_a_reload(
    page: Page, admin_base_url: str
) -> None:
    open_hud(page, admin_base_url)

    hud = page.locator(".hud")
    expect(hud).to_be_visible()
    expect(page.locator(".tab-bar")).to_be_hidden()
    expect(page.locator(".hud-name")).to_have_text("JARVIS")
    expect(page.locator(".hud-status")).to_have_text("STANDING BY")
    expect(page.locator(".hud-agent", has_text="Builder")).to_be_visible()
    expect(page.locator(".hud-agent", has_text="Researcher")).to_be_visible()
    expect(page.locator(".hud-pill", has_text="WEB DUCKDUCKGO")).to_be_visible()

    page.get_by_label("Talk to Jarvis").fill("status report")
    page.get_by_role("button", name="SEND").click()
    expect(page.locator(".hud-line.you", has_text="status report")).to_have_count(1)
    expect(page.locator(".hud-line.ai", has_text="Jarvis")).to_contain_text("is on it")

    page.get_by_label("Tell the team to remember").fill("The user prefers dark UIs")
    page.get_by_role("button", name="SAVE").click()
    expect(
        page.locator(".hud-item", has_text="The user prefers dark UIs")
    ).to_be_visible()
    expect(page.locator(".hud-pill", has_text="SHARED MEM 1")).to_be_visible()

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 0, "the HUD scrolls sideways on an iPhone"
    heights = page.evaluate(
        """() =>
            [...document.querySelectorAll('.hud-button, .hud-send, .hud-agent')]
                .filter((node) => node.offsetParent !== null)
                .map((node) => node.getBoundingClientRect().height)"""
    )
    assert heights and min(heights) >= MIN_TAP_TARGET

    page.reload()
    expect(page.locator(".hud")).to_be_visible()
    expect(page.locator(".hud-line.you", has_text="status report")).to_be_visible()

    page.locator(".hud-nav-item", has_text="Agents").click()
    expect(page.locator(".tab-bar")).to_be_visible()
    expect(page.locator(".hud")).to_have_count(0)


def test_the_plus_button_adds_an_agent_with_a_role(
    page: Page, admin_base_url: str
) -> None:
    open_studio(page, admin_base_url)
    page.locator('.tab[data-route="agents"]').click()

    page.get_by_role("button", name="Add an agent").click()
    sheet = page.locator(".sheet-panel")
    expect(sheet.get_by_role("heading", name="New agent")).to_be_visible()
    sheet.get_by_role("button", name="Researcher", exact=True).click()
    expect(sheet.get_by_label("Role")).to_have_value("researcher")
    expect(sheet.locator('input[value="research"]')).to_be_checked()
    expect(sheet.locator('input[value="write_file"]')).to_be_checked()
    expect(sheet.locator('input[value="delete_file"]')).not_to_be_checked()
    sheet.get_by_role("button", name="Designer", exact=True).click()
    expect(sheet.get_by_label("Role")).to_have_value("builder")
    expect(sheet.locator('input[value="ask_researcher"]')).to_be_checked()
    sheet.get_by_label("Name").fill("Pixel")
    sheet.get_by_role("button", name="Create agent").click()

    expect(page.locator("#view-title")).to_have_text("Pixel")
    expect(page.locator(".kv")).to_contain_text("builder")
    expect(page.locator(".kv")).to_contain_text("research")
    teach = page.locator(".card", has_text="Teach a skill")
    expect(teach).to_be_visible()
    expect(teach.get_by_label("Link")).to_be_visible()
    expect(teach).to_contain_text("No skills yet.")
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 0


def test_the_hud_has_a_plus_button_too(page: Page, admin_base_url: str) -> None:
    open_hud(page, admin_base_url)
    expect(page.locator(".hud")).to_be_visible()

    page.locator(".hud-add").click()
    sheet = page.locator(".sheet-panel")
    sheet.get_by_label("Name").fill("Tess")
    sheet.get_by_role("button", name="Tester", exact=True).click()
    sheet.get_by_role("button", name="Create agent").click()

    expect(page.locator(".hud-agent", has_text="Tess")).to_be_visible()
    expect(page.locator(".hud")).to_be_visible()


def test_the_hud_is_a_command_center_on_a_pc(page: Page, admin_base_url: str) -> None:
    open_hud(page, admin_base_url)
    page.set_viewport_size({"width": 1440, "height": 900})

    expect(page.locator(".hud-orb canvas")).to_be_visible()
    expect(page.locator(".hud-core-name")).to_have_text("JARVIS")
    expect(page.locator(".hud-nav-item.active")).to_have_text("◈Command Center")
    expect(page.locator(".hud-gauge", has_text="CPU")).to_be_visible()
    expect(page.locator(".hud-llm", has_text="Main core")).to_be_visible()
    expect(page.locator(".hud-stat", has_text="memories")).to_be_visible()

    room = page.locator(".hud-room")
    room.get_by_role("button", name="START TEAM ROOM").click()
    expect(room.locator(".hud-room-title")).to_have_text("Team room")
    expect(room.locator(".hud-room-meta")).to_contain_text("Helper")
    room.get_by_label("Message the agent room").fill("Plan a bakery site")
    room.get_by_role("button", name="POST").click()
    expect(
        room.locator(".hud-room-line.user", has_text="Plan a bakery site")
    ).to_be_visible()
    expect(room.locator(".hud-room-line.assistant", has_text="Builder")).to_be_visible()

    page.get_by_role("button", name="Executive briefing").click()
    expect(page.locator(".hud-line.you", has_text="Executive briefing")).to_be_visible()
    expect(page.locator(".hud-line.ai").last).to_contain_text("is on it")

    page.get_by_role("button", name="Brainstorm").click()
    expect(page.get_by_label("Talk to Jarvis")).to_have_value(
        "Ask Helper for ideas on "
    )

    box = page.locator(".hud-area-room").bounding_box()
    core = page.locator(".hud-core").bounding_box()
    assert box and core and box["x"] > core["x"], "the agent room sits top right"
    assert box["y"] < 200
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 0

    page.locator(".hud-nav-item", has_text="Agents").click()
    expect(page.locator(".hud")).to_have_count(0)


FAKE_MICROPHONE = """
navigator.mediaDevices.getUserMedia = async () => {
  const ctx = new AudioContext();
  await ctx.resume();
  const tone = ctx.createOscillator();
  tone.frequency.value = 220;
  const gain = ctx.createGain();
  gain.gain.value = 0;
  const out = ctx.createMediaStreamDestination();
  tone.connect(gain).connect(out);
  tone.start();
  // Say something for 0.8 s, then fall silent, like a person finishing a turn.
  setTimeout(() => {
    gain.gain.setValueAtTime(0.5, ctx.currentTime);
    gain.gain.setValueAtTime(0, ctx.currentTime + 0.8);
  }, 400);
  window.__micOpened = (window.__micOpened || 0) + 1;
  return out.stream;
};
"""


def _silent_wav(seconds: float = 0.2, rate: int = 24000) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(seconds * rate))
    return buffer.getvalue()


def test_talk_mode_hears_you_and_answers_out_loud(
    page: Page, admin_base_url: str
) -> None:
    page.add_init_script(FAKE_MICROPHONE)
    ready = {
        "speak": "builtin",
        "listen": "builtin",
        "speak_ready": True,
        "listen_ready": True,
        "setup": {"phase": "ready", "progress": 1.0, "message": "Voice ready"},
        "builtin": {"voice": "jarvis", "effect": "jarvis", "whisper": "base.en"},
    }

    def voice_ready(route) -> None:
        response = route.fetch()
        body = response.json()
        if "systems" in body:
            body["systems"]["voice"] = ready
        route.fulfill(response=response, json=body)

    spoken: list[str] = []
    recordings: list[bytes] = []

    def speak(route) -> None:
        spoken.append(route.request.post_data_json["text"])
        route.fulfill(
            status=200, body=_silent_wav(), headers={"content-type": "audio/wav"}
        )

    def transcribe(route) -> None:
        recordings.append(route.request.post_data_buffer or b"")
        route.fulfill(status=200, json={"text": "status report"})

    page.route("**/studio/api/main**", voice_ready)
    page.route("**/studio/api/voice/speak", speak)
    page.route("**/studio/api/voice/transcribe", transcribe)

    open_hud(page, admin_base_url)
    expect(page.locator(".hud-pill", has_text="VOICE OFFLINE")).to_be_visible()

    page.get_by_role("button", name="TALK", exact=True).click()
    expect(page.locator(".hud-status")).to_contain_text("TALK MODE")
    expect(page.locator(".hud-line.you", has_text="status report")).to_be_visible(
        timeout=15000
    )
    expect(page.locator(".hud-line.ai", has_text="is on it")).to_be_visible()
    expect(page.locator(".hud-status")).to_have_text(
        "LISTENING · TALK MODE", timeout=15000
    )

    assert recordings and recordings[0][:4] == b"RIFF", "a WAV of the turn was sent"
    assert recordings[0][24:28] == (16000).to_bytes(4, "little"), "16 kHz for Whisper"
    assert any("is on it" in text for text in spoken), spoken
    assert page.evaluate("window.__micOpened") == 1, "the microphone stays open"

    page.get_by_role("button", name="END TALK").click()
    expect(page.locator(".hud-status")).to_have_text("STANDING BY")
    expect(page.get_by_role("button", name="TALK", exact=True)).to_have_attribute(
        "aria-pressed", "false"
    )


def test_choosing_jarvis_brain_from_this_pc(page: Page, admin_base_url: str) -> None:
    used: list[dict] = []

    def available(route) -> None:
        route.fulfill(
            json={
                "default_model": "nvidia_nim/x",
                "server": [],
                "local": {
                    "base_url": "http://localhost:1234/v1",
                    "reachable": True,
                    "models": ["local/qwen3.5-4b", "local/nomic-embed-text"],
                    "error": None,
                },
            }
        )

    def use(route) -> None:
        used.append(route.request.post_data_json)
        route.fulfill(json={"model": used[-1]["model"], "agents_changed": 1})

    page.route("**/studio/api/models/available", available)
    page.route("**/studio/api/models/use", use)
    page.route(
        "**/studio/api/models/pick-file",
        lambda route: route.fulfill(
            json={"picked": True, "path": "C:/m/coder.gguf", "model": "local/coder"}
        ),
    )
    open_hud(page, admin_base_url)

    page.get_by_role("button", name="CHOOSE BRAIN", exact=True).click()
    sheet = page.locator(".sheet-panel")
    expect(sheet).to_contain_text("Choose Jarvis's brain")
    expect(sheet.get_by_role("button", name="Use nomic-embed-text")).to_have_count(0)
    sheet.get_by_label("Use it for every agent too").uncheck()
    sheet.get_by_role("button", name="Use qwen3.5-4b").click()
    expect(page.locator(".toast, [role=status]").first).to_be_attached()
    assert used == [{"model": "local/qwen3.5-4b", "everyone": False}]

    page.get_by_role("button", name="CHOOSE BRAIN", exact=True).click()
    sheet.get_by_role("button", name="Find a model file on this PC…").click()
    expect(sheet).to_be_hidden()
    assert used[-1] == {"model": "local/coder", "everyone": True}


def test_watching_an_agent_work_from_the_hud(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator(".hud")).to_be_visible()
    agents = page.request.get(f"{admin_base_url}/studio/api/agents").json()["agents"]
    builder = next(agent for agent in agents if agent["name"] == "Builder")
    chat = page.request.post(
        f"{admin_base_url}/studio/api/chats", data={"agent_id": builder["id"]}
    ).json()
    page.request.post(
        f"{admin_base_url}/studio/api/chats/{chat['id']}/messages",
        data={"text": "make a landing page"},
    )

    panel = page.locator(".hud-area-team")
    expect(panel).to_contain_text("AGENTS AT WORK")
    expect(panel.locator(".hud-process")).to_contain_text("Pick an agent")
    panel.locator(".hud-agent", has_text="Builder").click()

    expect(panel.locator(".hud-agent.watched")).to_contain_text("Builder")
    process = panel.locator(".hud-process")
    expect(process.locator(".hud-process-title")).to_contain_text("Builder")
    expect(process.locator(".hud-process-head")).not_to_contain_text("null")
    expect(process.locator(".hud-step.task")).to_contain_text("make a landing page")
    expect(process.locator(".hud-step.done")).to_contain_text("is on it")

    box = panel.bounding_box()
    core = page.locator(".hud-core").bounding_box()
    assert box and core and box["x"] < core["x"], "the panel sits on the left"
    assert box["y"] > core["y"], "below the core"

    process.get_by_role("button", name="OPEN").click()
    expect(page.locator(".bubble.user", has_text="make a landing page")).to_be_visible()


def test_every_setting_is_inside_the_app(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator(".hud")).to_be_visible()

    page.locator(".hud-nav-item", has_text="Settings").click()
    expect(page.locator("#view-title")).to_have_text("Settings")
    frame = page.frame_locator("iframe.settings-frame")
    expect(frame.locator("#pageTitle")).to_have_text("Studio")
    expect(frame.locator("#field-STUDIO_MAIN_AGENT_MODEL")).to_be_visible()
    expect(frame.locator("html.embedded")).to_have_count(1)
    frame.get_by_role("button", name="Providers", exact=True).click()
    expect(frame.locator("#pageTitle")).to_have_text("Providers")
    frame.get_by_label("Search settings").fill("fast local")
    expect(
        frame.locator('.field[data-key="STUDIO_LOCAL_FAST_REPLIES"]')
    ).to_be_visible()

    page.locator('.tab[data-route="more"]').click()
    page.get_by_role("button", name="Open settings").click()
    expect(page.locator("iframe.settings-frame")).to_be_visible()


def test_a_phone_is_told_where_settings_live(page: Page, admin_base_url: str) -> None:
    page.route(
        "**/admin/api/status", lambda route: route.fulfill(status=403, body="local")
    )
    open_studio(page, admin_base_url, "settings")

    expect(page.locator(".card", has_text="Settings")).to_contain_text(
        "on the PC running Studio"
    )
    expect(page.locator("iframe")).to_have_count(0)


def test_jarvis_starts_speaking_before_his_reply_is_finished(
    page: Page, admin_base_url: str
) -> None:
    ready = {
        "speak": "builtin",
        "listen": "builtin",
        "speak_ready": True,
        "listen_ready": True,
        "setup": {"phase": "ready", "progress": 1.0, "message": "Voice ready"},
        "builtin": {"voice": "jarvis", "effect": "jarvis", "whisper": "base.en"},
    }
    state: dict = {"live": "", "final": None}

    def main(route) -> None:
        response = route.fetch()
        body = response.json()
        if "systems" in body:
            body["systems"]["voice"] = ready
            body["live"] = state["live"]
            if state["final"]:
                body["messages"] = [*body["messages"], state["final"]]
        route.fulfill(response=response, json=body)

    spoken: list[str] = []

    def speak(route) -> None:
        spoken.append(route.request.post_data_json["text"])
        route.fulfill(
            status=200, body=_silent_wav(), headers={"content-type": "audio/wav"}
        )

    def wait_for_speech(count: int) -> None:
        for _ in range(100):
            if len(spoken) >= count:
                return
            page.wait_for_timeout(100)

    page.route("**/studio/api/main**", main)
    page.route("**/studio/api/voice/speak", speak)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{admin_base_url}/studio")
    expect(page.locator(".hud-pill", has_text="VOICE OFFLINE")).to_be_visible()
    voice_button = page.get_by_role("button", name="VOICE ON")
    voice_button.click()  # a tap lets the page play sound
    page.get_by_role("button", name="VOICE OFF").click()

    state["live"] = "Good evening, sir. All systems are"
    wait_for_speech(1)
    assert spoken == ["Good evening, sir."], "the first sentence, while writing"
    expect(page.locator(".hud-line.ai.live")).to_contain_text("All systems are")

    state["live"] = ""
    state["final"] = {
        "id": "msg_final",
        "chat_id": "chat",
        "sequence": 100_000,
        "role": "assistant",
        "author": "Jarvis",
        "text": "Good evening, sir. All systems are green.",
        "data": {},
        "created_at": 0,
    }
    wait_for_speech(2)
    assert spoken == ["Good evening, sir.", "All systems are green."], "no repeats"
    expect(page.locator(".hud-line.ai.live")).to_have_count(0)
    expect(
        page.locator(".hud-line.ai", has_text="All systems are green.")
    ).to_be_visible()
