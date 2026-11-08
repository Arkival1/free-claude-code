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
    # Saved first (the look switches after the save), then opened again.
    page.wait_for_function("() => document.body.dataset.look === 'hud'")
    page.reload()
    page.wait_for_function("() => window.fccPhone && window.fccPhone.ready")
    assert page.evaluate("() => document.body.dataset.look") == "hud"


def test_jarvis_takes_off_what_is_on_the_bench_and_logs_it_plainly(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url, "lab")
    done = page.evaluate(
        """async () => {
            const shop = await import('./js/workshop.js');
            const { runTool } = await import('./js/tools.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.role === 'main');
            const ctx = { depth: 0, chain: [], built: new Set() };
            const call = (args) => runTool(jarvis, { name: 'lab', arguments: args }, ctx);
            const out = {};
            // A partial name finds the battery that is on the board.
            await shop.setBoard([{ id: '9v', count: 1 }, { id: 'led-red', count: 1 }], { powered: true });
            out.battery = await call({ action: 'remove', parts: [{ name: 'battery' }] });
            out.board = window.fccPhone.state.bench.electronics.parts.map((p) => p.id);
            out.missing = await call({ action: 'remove', parts: [{ name: 'servo' }] });
            // Two LEDs: "led" is unclear, so nothing comes off; one letter matches nothing.
            await shop.setBoard([{ id: 'aa', count: 2 }, { id: 'led-red', count: 1 }, { id: 'led-blue', count: 1 }], { powered: true });
            out.unclear = await call({ action: 'remove', parts: [{ name: 'led' }] });
            out.short = await call({ action: 'remove', parts: [{ name: 'r' }] });
            out.still = window.fccPhone.state.bench.electronics.parts.length;
            // Burner on, Jarvis empties the beaker: it starts over with the burner off.
            await shop.setBeaker([{ id: 'water', amount: 50 }], { heat: true });
            out.clean = await call({ action: 'remove', items: [{ name: 'water' }] });
            out.heat = window.fccPhone.state.bench.chemistry.heat;
            await call({ action: 'add', items: [{ name: 'vinegar', amount: 20 }] });
            await call({ action: 'add', items: [{ name: 'baking soda', amount: 2 }] });
            await call({ action: 'remove', items: [{ name: 'vinegar' }] });
            out.log = window.fccPhone.state.bench.log.map((s) => `${s.by}: ${s.text}`);
            for (let i = 0; i < 45; i += 1) shop.logStep('you', 'chemistry', `step ${i}`);
            out.kept = window.fccPhone.state.bench.log.length;
            out.last = window.fccPhone.state.bench.log.at(-1).text;
            return out;
        }"""
    )
    assert "9v" not in done["board"] and "led-red" in done["board"], done
    assert done["missing"].startswith("None of those are on the board. On it:")
    assert done["unclear"].startswith("Which one?") and "led-red" in done["unclear"]
    assert done["short"].startswith("None of those are on the board.")
    assert done["still"] == 3
    assert done["clean"] == "The beaker is clean now." and done["heat"] is False
    log = done["log"]
    assert any(
        line.startswith("Jarvis: added Vinegar") and "to the beaker" in line
        for line in log
    ), log
    assert any(line.startswith("Jarvis: took out Vinegar") for line in log), log
    assert not any(line.startswith("Jarvis: mixed") for line in log), log
    assert done["kept"] == 40 and done["last"] == "step 44"


def test_jarvis_programs_and_tests_the_board_computer(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url, "lab")
    done = page.evaluate(
        r"""async () => {
            const shop = await import('./js/workshop.js');
            const { runTool } = await import('./js/tools.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.role === 'main');
            const ctx = { depth: 0, chain: [], built: new Set() };
            const call = (args) => runTool(jarvis, { name: 'lab', arguments: args }, ctx);
            const out = {};
            out.none = await call({ action: 'run' });
            await shop.setBoard([{ id: 'usb', count: 1 }, { id: 'arduino', count: 1 }, { id: 'led-red', count: 1 }, { id: 'light-sensor', count: 1 }, { id: 'oled', count: 1 }], { powered: true });
            out.wiring = await call({ action: 'program' });
            out.saved = await call({ action: 'program', code: 'function setup() { pinMode(LED_RED, OUTPUT); }\nfunction loop() {\n  digitalWrite(LED_RED, readLight() < 30 ? HIGH : LOW);\n  display.clear();\n  display.println("Light " + readLight());\n  Serial.println("light " + readLight());\n  delay(1000);\n}' });
            out.dark = await call({ action: 'run', seconds: 3, sensors: { light: 10 } });
            out.bright = await call({ action: 'run', seconds: 3, sensors: { light: 90 } });
            out.broken = await call({ action: 'program', code: 'function loop() {\n  digitalWrite(LED_RED HIGH);\n}' });
            out.endless = await call({ action: 'program', code: 'function setup() { while (true) { digitalRead(4); } }' });
            out.program = window.fccPhone.state.bench.electronics.program;
            out.boxes = document.querySelectorAll('iframe.board-box').length;
            return out;
        }"""
    )
    assert done["none"].startswith("There's no board computer")
    assert "LED_RED = pin 13" in done["wiring"] and "LIGHT = pin A0" in done["wiring"]
    assert "Red LED (LED_RED, pin 13): on 1 time, 100% of the time" in done["dark"]
    assert "The screen shows: Light 10" in done["dark"] and "light 10" in done["dark"]
    assert "Red LED (LED_RED, pin 13): stayed off" in done["bright"]
    assert "SyntaxError" in done["broken"] and "(line 2)" in done["broken"]
    assert "endless loop" in done["endless"]
    assert "while (true)" in done["program"]
    assert done["boxes"] == 0


def test_the_board_computer_guards_every_loop_and_wires_each_sensor(
    page: Page, admin_base_url: str
) -> None:
    """Endless loops stop whatever their shape (no braces, do…while, inside
    strings or classes left alone); a program with no loop() ends after its
    setup in live mode; two sensors of one kind get two pins."""
    open_phone(page, admin_base_url, "lab")
    checked = page.evaluate(
        r"""async () => {
            const board = await import('./lab/board.js');
            const parts = [{ id: 'arduino' }, { id: 'led-red' }, { id: 'light-sensor', count: 2 }];
            const run = async (code, live = false) => (await board.runBoard(code, parts, { live, seconds: 3 }).done);
            const divided = [board.guardLoops('a = b++ / 2; while (q) {}'), board.guardLoops('a = n-- / 2;\nwhile (q) {}')];
            const guarded = board.guardLoops('const s = "while (x) {"; class A extends mix(B) { go() { while (a) b(); } } for (;;) break; do n++; while (n < 3);');
            const endless = await run('function setup() { let n = 0; while (true) n++; }');
            const doEndless = await run('function setup() { let n = 0; do n++; while (n > 0); }');
            const fine = await run('function setup() { let total = 0; for (let i = 0; i < 1000; i++) total += i; Serial.println("total " + total); }\nfunction loop() { delay(500); }');
            const live = await Promise.race([run('function setup() { digitalWrite(LED_RED, HIGH); Serial.println("set up"); }', true), new Promise((done) => setTimeout(() => done('still running'), 8000))]);
            const wire = board.wiring(parts);
            return {
                guarded,
                divided,
                endless: endless.error,
                doEndless: doEndless.error,
                fine: [fine.error, fine.state.serial.join('\n')],
                live: live === 'still running' ? live : [live.error, live.state.serial.join('\n')],
                pins: wire.wires.filter((item) => item.role === 'light').map((item) => item.pin),
            };
        }"""
    )
    assert '"while (x) {"' in checked["guarded"]
    assert "while (__tick() && (a)) b();" in checked["guarded"]
    assert "for (; __tick();) break;" in checked["guarded"]
    assert "while (__tick() && (n < 3));" in checked["guarded"]
    # x++ / 2 divides (it doesn't start a regex), so the loop after it is guarded.
    assert all("while (__tick() && (q))" in code for code in checked["divided"])
    assert "endless loop" in checked["endless"]
    assert "endless loop" in checked["doEndless"]
    assert checked["fine"][0] == "" and "total 499500" in checked["fine"][1]
    assert checked["live"] != "still running", "a setup-only live program never ended"
    assert checked["live"][0] == "" and "set up" in checked["live"][1]
    assert checked["pins"] == [14, 15]  # A0, then the next free analog pin
