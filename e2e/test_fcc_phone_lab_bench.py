"""FCC Phone's Lab benches, shared by the user and Jarvis: each bench has a
parts menu (what's on the bench, and the stock to add from), every step at
the benches is kept, Jarvis sees what the user is working on (in his prompt
and with lab look) and builds on it (lab add and remove), and the phone opens
in the Manus-like look unless asked for the HUD."""

import re

from playwright.sync_api import Page, expect

from .test_fcc_phone import IPHONE_12_PRO, open_phone


def test_the_parts_menu_and_jarvis_share_the_bench(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_phone(page, admin_base_url, "lab")
    rooms = page.get_by_role("group", name="Rooms")
    rooms.get_by_role("button", name="Electronics").click()
    menu = page.locator(".lab-parts")
    expect(menu.get_by_role("tab", name="On the board (0)")).to_be_visible()
    # The drawers: search, add two parts; the board tab counts them.
    menu.get_by_role("tab", name=re.compile(r"^Drawers")).click()
    page.get_by_label("Search the drawers").fill("aa")
    menu.get_by_role("button", name=re.compile(r"^Add .*AA")).first.click()
    menu.get_by_role("tab", name=re.compile(r"^Drawers")).click()
    page.get_by_label("Search the drawers").fill("red led")
    menu.get_by_role("button", name=re.compile(r"^Add .*Red LED")).first.click()
    expect(menu.get_by_role("tab", name="On the board (2)")).to_be_visible()
    page.get_by_role("button", name="Power on").click()
    steps = page.locator(".lab-log")
    expect(steps).to_contain_text("added")
    expect(steps).to_contain_text("powered it")
    log = page.evaluate("() => window.fccPhone.state.bench.log")
    assert [step["by"] for step in log] == ["you"] * len(log)

    # Jarvis sees it: in his prompt, and with lab look.
    seen = page.evaluate(
        """async () => {
            const { systemPrompt } = await import('./js/agents.js');
            const { runTool } = await import('./js/tools.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.role === 'main');
            const ctx = { depth: 0, chain: [], built: new Set() };
            const call = (args) => runTool(jarvis, { name: 'lab', arguments: args }, ctx);
            return {
                prompt: systemPrompt(jarvis, 'what do you think of my circuit?'),
                look: await call({ action: 'look' }),
                added: await call({ action: 'add', parts: [{ id: 'switch', count: 1 }] }),
                removed: await call({ action: 'remove', parts: [{ id: 'led-red' }] }),
                kit: await call({ action: 'add' }),
                parts: window.fccPhone.state.bench.electronics.parts.map((p) => p.id),
                log: window.fccPhone.state.bench.log.map((s) => `${s.by}: ${s.text}`),
            };
        }"""
    )
    assert "The Lab benches right now" in seen["prompt"]
    assert "Red LED" in seen["prompt"] and "The user added" in seen["prompt"]
    assert "Electronics bench: on the board" in seen["look"]
    assert "Last steps at the benches" in seen["look"]
    assert "On the board now:" in seen["added"] and "switch" in seen["added"].lower()
    assert "led-red" not in seen["parts"] and "switch" in seen["parts"]
    # lab add with no parts or items is still the Game kit's add.
    assert "On the board" not in seen["kit"]
    assert any(line.startswith("Jarvis: added") for line in seen["log"]), seen["log"]
    assert any(line.startswith("Jarvis: took out") for line in seen["log"]), seen["log"]
    expect(steps.locator(".lab-who.ai").first).to_have_text("Jarvis")

    # Chemistry: the shelf adds a bottle; the beaker tab shows it.
    rooms.get_by_role("button", name="Chemistry").click()
    page.get_by_role("tab", name=re.compile(r"^Shelf")).click()
    page.get_by_label("Search the shelf").fill("vinegar")
    page.locator(".lab-stock").get_by_role(
        "button", name=re.compile(r"^Add Vinegar")
    ).first.click()
    expect(page.get_by_role("tab", name="In the beaker (1)")).to_be_visible()
    assert errors == [], errors


def test_the_phone_opens_in_the_manus_look_unless_asked(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size(IPHONE_12_PRO)
    page.goto(f"{admin_base_url}/phone/#lab")
    page.wait_for_function("() => window.fccPhone && window.fccPhone.ready")
    assert page.evaluate("() => document.body.dataset.look") == "playground"
    expect(page.locator("#tabs .tab")).to_have_text(
        ["+New task", "◷Tasks", "▤Files", "⚗Lab", "⋯More"]
    )
    # Picking the HUD in Settings sticks, even without ?look=hud.
    page.evaluate("location.hash = 'settings'")
    page.get_by_role("button", name="HUD").click()
    page.reload()
    page.wait_for_function("() => window.fccPhone && window.fccPhone.ready")
    assert page.evaluate("() => document.body.dataset.look") == "hud"
