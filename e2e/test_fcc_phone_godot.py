"""FCC Phone's Godot: real Godot 4.7.2 (its web player) runs a project's game
on the phone in a sealed box. A starter plays and checks clean; a broken
script is reported with its file and line; a game with an endless loop is
refused before it runs; the box has no internet and no way into the page; a
game that wants too much memory is told no in its box; the probe lists what
Godot can do here; and the AI makes and checks a Godot game with the tool."""

import json

import pytest
from playwright.sync_api import ConsoleMessage, Page, Route, expect

from .test_fcc_phone import go, open_phone

GODOT_WAIT = 150_000
SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node"]
script = ExtResource("1")
"""


@pytest.fixture
def browser_context_args(browser_context_args: dict) -> dict:
    """A touch screen, like the phone: games show touch controls and never
    take the mouse (on a computer they do, until Esc)."""
    return {**browser_context_args, "has_touch": True}


def project_files(main: str) -> dict[str, str]:
    return {
        "project.godot": 'config_version=5\n\n[application]\n\nconfig/name="Test"\n'
        'run/main_scene="res://main.tscn"\n',
        "main.tscn": SCENE,
        "main.gd": main,
    }


def run_in_box(page: Page, files: dict[str, str], until: str = "^DONE") -> dict:
    """Run files in the box (as a check) until a line matches `until`."""
    return page.evaluate(
        """async ([files, until]) => {
            const godot = await import('./js/godot.js');
            const run = godot.runGodot({ name: 'Test', files }, { mode: 'check', seconds: 60, untilPrint: new RegExp(until) });
            const sandbox = run.frame && run.frame.getAttribute('sandbox');
            const policy = run.frame && run.frame.srcdoc.match(/Content-Security-Policy" content="([^"]*)"/)[1];
            const result = await run.done;
            return { ...result, sandbox, policy, report: godot.describeRun(result), boxes: document.querySelectorAll('iframe.godot-box').length };
        }""",
        [files, until],
    )


def watch_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def console_error(message: ConsoleMessage) -> None:
        if message.type == "error" and "fonts.g" not in message.text:
            errors.append(message.text)

    page.on("console", console_error)
    return errors


def test_a_godot_starter_checks_clean_and_plays_full_screen(
    page: Page, admin_base_url: str
) -> None:
    page.set_default_timeout(GODOT_WAIT)
    errors = watch_errors(page)
    open_phone(page, admin_base_url)
    go(page, "projects")
    page.get_by_role("button", name="Third-person (3D)").click()
    expect(page.get_by_role("heading", name="Godot third-person game")).to_be_visible()
    expect(page.get_by_text("Godot game ·")).to_be_visible()
    project = page.evaluate(
        "() => window.fccPhone.state.projects.find((p) => p.name === 'Godot third-person game')"
    )
    assert 'config/name="Godot third-person game"' in project["files"]["project.godot"]
    assert {"main.gd", "main.tscn", "player.gd"} <= set(project["files"])

    page.get_by_role("button", name="Check it").click()
    report = page.locator(".godot-report")
    expect(report).to_contain_text("No errors", timeout=GODOT_WAIT)
    expect(report).to_contain_text("its first frame came after")
    expect(page.locator("iframe.godot-box")).to_have_count(0)

    page.get_by_role("button", name="Play Godot third-person game").click()
    box = page.locator(".godot-layer iframe.godot-box")
    expect(box).to_have_attribute("sandbox", "allow-scripts allow-pointer-lock")
    expect(page.locator(".godot-layer .godot-status")).to_be_hidden(timeout=GODOT_WAIT)
    page.get_by_role("button", name="Close the game").click()
    # Software drawing here makes each frame slow, so the click waits its turn.
    expect(page.locator(".godot-layer")).to_have_count(0, timeout=GODOT_WAIT)
    assert errors == [], errors


def test_godot_check_names_the_broken_line_and_refuses_endless_loops(
    page: Page, admin_base_url: str
) -> None:
    page.set_default_timeout(GODOT_WAIT)
    open_phone(page, admin_base_url)
    broken = project_files(
        'extends Node\n\n\nfunc _ready() -> void:\n\tvar score: int = "ten" + 1\n\tprint(score)\n'
    )
    endless = project_files(
        "extends Node\n\n\nfunc _ready() -> void:\n\twhile true:\n\t\tprint('again')\n"
    )
    checked = page.evaluate(
        """async ([broken, endless]) => {
            const { runTool } = await import('./js/tools.js');
            const projects = await import('./js/projects.js');
            const tester = window.fccPhone.state.agents.find((a) => a.id === 'tester');
            const out = {};
            for (const [name, files] of [['Broken game', broken], ['Endless game', endless]]) {
                const project = await projects.createProject(name, 'you');
                for (const [path, body] of Object.entries(files)) await projects.writeFile(project, path, body, 'you');
                const ctx = { project, depth: 0, chain: [], built: new Set() };
                out[name] = {
                    check: await runTool(tester, { name: 'godot', arguments: { action: 'check' } }, ctx),
                    project: await runTool(tester, { name: 'check_project', arguments: {} }, ctx),
                };
            }
            return out;
        }""",
        [broken, endless],
    )
    broken_check = checked["Broken game"]["check"]
    assert "Errors (" in broken_check, broken_check
    assert "res://main.gd:5" in broken_check
    assert "Parse Error" in broken_check
    endless_check = checked["Endless game"]["check"]
    assert "didn't run" in endless_check
    assert "main.gd:5 has a while true loop" in endless_check
    assert "would freeze the phone" in checked["Endless game"]["project"]
    expect(page.locator("iframe.godot-box")).to_have_count(0)


def test_the_godot_box_has_no_internet_no_page_access_and_a_memory_cap(
    page: Page, admin_base_url: str
) -> None:
    page.set_default_timeout(GODOT_WAIT)
    hits: list[str] = []

    def count(route: Route) -> None:
        hits.append(route.request.url)
        route.fulfill(body="reached")

    page.route("**/godot-net-probe*", count)
    open_phone(page, admin_base_url)
    url = f"{admin_base_url}/godot-net-probe"
    main = (
        "extends Node\n\n\nfunc _ready() -> void:\n"
        "\tvar request := HTTPRequest.new()\n"
        "\trequest.timeout = 3.0\n"
        "\tadd_child(request)\n"
        f"\tvar error := request.request({json.dumps(url)})\n"
        "\tif error != OK:\n"
        '\t\tprint("NET start-error %d" % error)\n'
        "\telse:\n"
        "\t\tvar answer: Array = await request.request_completed\n"
        '\t\tprint("NET %d %d" % [answer[0], answer[1]])\n'
        '\tvar value: Variant = JavaScriptBridge.eval("parent.document.title", true)\n'
        '\tprint("JS %s" % [value])\n'
        "\tvar big := PackedByteArray()\n"
        '\tprint("BIG %d" % big.resize(1536 * 1024 * 1024))\n'
        '\tprint("DONE")\n'
    )
    result = run_in_box(page, project_files(main))
    assert result["sandbox"] == "allow-scripts allow-pointer-lock"
    assert "connect-src 'none'" in result["policy"]
    assert "default-src 'none'" in result["policy"]
    lines = result["prints"]
    net = next(line for line in lines if line.startswith("NET"))
    # RESULT_SUCCESS is 0: anything else means the request never got through.
    assert net != "NET 0 200", lines
    assert "JS <null>" in lines, lines
    assert any(line.startswith("BIG") and line != "BIG 0" for line in lines), lines
    assert "DONE" in lines
    assert "said no" in result["memory"]
    assert "JavaScriptBridge.eval" in result["report"]
    assert hits == []
    assert result["boxes"] == 0
    # The page is still fine afterwards.
    go(page, "projects")
    expect(page.get_by_role("heading", name="Godot games")).to_be_visible()


def test_the_probe_lists_what_godot_can_do_on_the_phone(
    page: Page, admin_base_url: str
) -> None:
    page.set_default_timeout(GODOT_WAIT)
    open_phone(page, admin_base_url)
    go(page, "projects")
    page.get_by_role("button", name="What can Godot do on this phone?").click()
    sheet = page.locator("#sheet")
    expect(page.locator("#sheet-title")).to_contain_text(
        "Godot here:", timeout=GODOT_WAIT
    )
    for words in (
        "Works (",
        "Missing (",
        "Blocked on purpose (FCC's box)",
        "Internet from the game",
        "3D physics",
        "Thread support",
        "GDExtension (native add-ons)",
        "Memory cap",
    ):
        expect(sheet).to_contain_text(words)
    expect(page.locator(".godot-layer")).to_have_count(0)
    told = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.id === 'jarvis');
            return runTool(jarvis, { name: 'godot', arguments: { action: 'probe' } }, { depth: 0, chain: [], built: new Set() });
        }"""
    )
    assert told.startswith("What Godot 4.7.2 can do on this phone")


def test_the_ai_starts_and_checks_a_godot_game_with_the_tool(
    page: Page, admin_base_url: str
) -> None:
    page.set_default_timeout(GODOT_WAIT)
    open_phone(page, admin_base_url)
    result = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const builder = window.fccPhone.state.agents.find((a) => a.id === 'builder');
            const ctx = { depth: 0, chain: [], built: new Set() };
            const call = (name, args) => runTool(builder, { name, arguments: args }, ctx);
            const out = { tools: builder.tools.includes('godot') };
            out.guide = await call('godot', { action: 'guide' });
            out.starters = await call('godot', { action: 'starters' });
            await call('start_project', { name: 'Ember Duel' });
            out.start = await call('godot', { action: 'start', starter: 'third-person-3d' });
            out.again = await call('godot', { action: 'start', starter: 'action-3d' });
            out.bad = await call('godot', { action: 'start', starter: 'nope' });
            await call('edit_file', { path: 'main.gd', find: 'extends Node3D', replace: 'extends Node3D\\n# Ember Duel' });
            out.check = await call('godot', { action: 'check', seconds: 4 });
            out.files = Object.keys(ctx.project.files).sort();
            return out;
        }"""
    )
    assert result["tools"]
    assert "Compatibility renderer" in result["guide"]
    assert "action-3d:" in result["starters"]
    assert "Put the third-person-3d starter in Ember Duel" in result["start"]
    assert "already has files" in result["again"]
    assert "starter is one of" in result["bad"]
    assert "No errors" in result["check"], result["check"]
    assert {"project.godot", "main.gd", "main.tscn"} <= set(result["files"])
