"""FCC Phone's Game Lab: the kit's textures, shaders, models and animation
live in 3D, a 3D game that starts from the starter and runs in the preview,
the lab tool the AI uses, and a download that carries its engine."""

import io
import zipfile

from playwright.sync_api import ConsoleMessage, Page, expect

from .test_fcc_phone import go, open_phone


def test_the_lab_shows_the_kit_live_and_starts_a_3d_game(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def console_error(message: ConsoleMessage) -> None:
        if message.type == "error":
            errors.append(message.text)

    page.on("console", console_error)
    open_phone(page, admin_base_url)
    go(page, "lab/game")
    expect(page.locator("section.card h2", has_text="Game Lab")).to_be_visible()
    page.wait_for_function(
        "() => document.querySelector('.lab-stage') && document.querySelector('.lab-stage').dataset.ready === 'true'",
        timeout=20000,
    )
    expect(page.locator(".lab-caption")).to_contain_text("warrior")
    for shelf, item, words in [
        ("Shaders", "fire", "Fire"),
        ("Textures", "lava", "lava"),
        ("Animation", "roll", "roll"),
        ("Models", "tower", "tower"),
    ]:
        page.locator(".lab-tabs").get_by_role("button", name=shelf, exact=True).click()
        page.get_by_role("button", name=item, exact=True).click()
        expect(page.locator(".lab-caption")).to_contain_text(words)
        page.wait_for_timeout(150)
    page.locator(".lab-tabs").get_by_role("button", name="Textures", exact=True).click()
    page.get_by_role("button", name="stone", exact=True).click()
    page.get_by_role("button", name="Save to library").click()
    library = page.evaluate("() => window.fccPhone.state.library")
    assert library[0]["title"] == "stone texture"
    assert library[0]["image"].startswith("data:image/jpeg")

    page.get_by_role("button", name="Start a 3D game").click()
    page.get_by_label("The game's name").fill("Ember Temple")
    page.get_by_role("button", name="Start it").click()
    expect(page.get_by_role("heading", name="Ember Temple")).to_be_visible()
    project = page.evaluate(
        "() => window.fccPhone.state.projects.find((p) => p.name === 'Ember Temple')"
    )
    assert {"index.html", "styles.css", "game.js", "lab/kit.js"} <= set(
        project["files"]
    )
    assert "Ember Temple" in project["files"]["index.html"]
    # The game runs in the sandboxed preview: three.js and the kit load, and
    # the game marks itself ready once its first frame is set up.
    preview = page.frame_locator("iframe.preview")
    expect(preview.locator("html[data-ready='true']")).to_have_count(1, timeout=20000)
    expect(preview.locator(".lab-button")).to_have_count(5)
    assert errors == [], errors


def test_the_lab_tool_and_a_3d_download(page: Page, admin_base_url: str) -> None:
    open_phone(page, admin_base_url)
    result = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const { createProject, forDownload, zipProject } = await import('./js/projects.js');
            const builder = window.fccPhone.state.agents.find((a) => a.id === 'builder');
            const project = await createProject('Lab tool test');
            const ctx = { project, depth: 0, chain: [], built: new Set() };
            const guide = await runTool(builder, { name: 'lab', arguments: { action: 'guide' } }, ctx);
            const list = await runTool(builder, { name: 'lab', arguments: { action: 'list' } }, ctx);
            const added = await runTool(builder, { name: 'lab', arguments: { action: 'add' } }, ctx);
            const started = await runTool(builder, { name: 'start_project', arguments: { name: 'Ash Arena', template: 'game3d' } }, ctx);
            const arena = window.fccPhone.state.projects.find((p) => p.name === 'Ash Arena');
            const saved = await forDownload(arena);
            const zip = zipProject(saved);
            const bytes = new Uint8Array(await zip.arrayBuffer());
            return {
                guide, list, added, started,
                kitInProject: Object.keys(project.files),
                zip: Array.from(bytes),
                index: saved.files['index.html'],
                tools: builder.tools,
            };
        }"""
    )
    assert "Souls-like design" in result["guide"]
    assert "makeWarrior" in result["list"] and "fireMaterial" in result["list"]
    assert result["kitInProject"] == ["lab/kit.js"]
    assert result["started"].startswith("Started Ash Arena from the game3d template")
    assert "lab" in result["tools"]
    names = zipfile.ZipFile(io.BytesIO(bytes(result["zip"]))).namelist()
    assert "ash-arena/vendor/three/three.module.js" in names
    assert "ash-arena/vendor/three/three.core.js" in names
    assert "ash-arena/lab/kit.js" in names
    assert "ash-arena/vendor/three/LICENSE.txt" in names
    assert '"three":"./vendor/three/three.module.js"' in result["index"]


def test_a_3d_job_in_the_playground_starts_from_the_game3d_template(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    kinds = page.evaluate(
        """async () => {
            const { kindOf, KINDS } = await import('./js/playground.js');
            return [kindOf('a 3D souls-like boss fight'), kindOf('a site for my cafe'), KINDS.game.engineering];
        }"""
    )
    assert kinds[0] == "game" and kinds[1] == "website"
    assert "template game3d" in kinds[2]
    go(page, "lab/game")
    page.get_by_role("button", name="Ask the AI for one").click()
    go(page, "settings")
    page.get_by_role("button", name="Playground").click()
    go(page, "tasks")
    expect(page.locator("body[data-route='tasks']")).to_have_count(1)
    page.evaluate(
        "() => { window.fccPhone.state.labAsk = 'a 3D third-person game where '; }"
    )
    go(page, "home")
    expect(page.get_by_label("The task")).to_have_value("a 3D third-person game where ")
    tabs = page.locator("#tabs .tab")
    expect(tabs).to_have_text(["+New task", "◷Tasks", "▤Files", "⚗Lab", "⋯More"])


def test_helpers_cant_swap_the_kit_and_single_quoted_imports_link(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    result = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const { createProject, linkModules } = await import('./js/projects.js');
            const builder = window.fccPhone.state.agents.find((a) => a.id === 'builder');
            const project = await createProject('Helper kit test');
            const ctx = { project, depth: 0, chain: [], built: new Set(), partsOnly: true };
            const added = await runTool(builder, { name: 'lab', arguments: { action: 'add' } }, ctx);
            const files = { 'lab/kit.js': `export const it = "it's";`, 'game.js': '' };
            const linked = linkModules(files, "import { it } from './lab/kit.js';", 'game.js');
            const url = linked.match(/'(data:[^']*)'/)[1];
            const module = await import(url);
            return { added, files: Object.keys(project.files), value: module.it };
        }"""
    )
    assert "only under parts/" in result["added"]
    assert "lab/kit.js" not in result["files"]
    assert result["value"] == "it's"
