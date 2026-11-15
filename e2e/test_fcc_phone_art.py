"""FCC Phone's game_art tool: an agent searches the 4,000 sprites, adds some
to a project, and they arrive as real PNG pictures (the 8 MB file is fetched
once and checked)."""

from playwright.sync_api import Page

from .test_fcc_phone import open_phone


def test_agents_find_and_add_game_art_to_a_project(
    page: Page, admin_base_url: str
) -> None:
    page.set_default_timeout(60_000)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_phone(page, admin_base_url)
    result = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const { jarvis } = await import('./js/state.js');
            const projects = await import('./js/projects.js');
            const agent = jarvis();
            const packs = await runTool(agent, { name: 'game_art', arguments: { action: 'packs' } }, {});
            const found = await runTool(agent, { name: 'game_art', arguments: { action: 'search', query: 'tiny dungeon' } }, {});
            const ids = [...found.matchAll(/^(a\\d+) /gm)].slice(0, 3).map((m) => m[1]);
            const project = await projects.createProject('Art test', 'you');
            const added = await runTool(agent, { name: 'game_art', arguments: { action: 'add', ids: ids.join(',') } }, { project });
            const pictures = Object.entries(project.files).filter(([path]) => path.startsWith('art/'));
            const none = await runTool(agent, { name: 'game_art', arguments: { action: 'search', query: 'zzqqxx' } }, {});
            const bad = await runTool(agent, { name: 'game_art', arguments: { action: 'add', ids: 'a99999' } }, { project });
            return { packs: packs.split('\\n').length, found: found.split('\\n')[0], ids, added, pictures: pictures.map(([path, body]) => [path, String(body).slice(0, 30)]), none, bad };
        }"""
    )
    assert result["packs"] >= 35
    assert result["found"].endswith("found (first 40):") or "found" in result["found"]
    assert len(result["ids"]) == 3
    assert result["added"].startswith("Added 3 to Art test")
    assert len(result["pictures"]) == 3
    for path, body in result["pictures"]:
        assert path.startswith("art/tiny-dungeon/") and path.endswith(".png")
        assert body.startswith("data:image/png;base64,iVBOR")
    assert result["none"].startswith("Nothing matches")
    assert result["bad"].startswith("No sprite a99999")
    assert errors == [], errors
