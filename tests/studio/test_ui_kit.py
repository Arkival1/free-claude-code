"""The app kit: Tabler and its 5,184 icons, the app-kit starter, the tool."""

import hashlib
from pathlib import Path

import pytest

from free_claude_code.studio import ui_kit
from free_claude_code.studio.models import Agent
from free_claude_code.studio.project_check import check_project

from .test_builder_images import builder_in_project, run

ROOT = Path(__file__).resolve().parents[2]


def test_the_kit_ships_with_its_checksum_and_licences():
    digest = hashlib.sha256(ui_kit.DATA.read_bytes()).hexdigest()
    assert f"{digest}  tabler.zip" in (ROOT / "vendor/tabler/SHA256SUMS").read_text()
    assert ui_kit.DATA.stat().st_size < 25 * 1024 * 1024
    files = ui_kit.kit_files()
    assert b"MIT License" in files["vendor/tabler/LICENSE"]
    assert b"MIT License" in files["vendor/tabler-icons/LICENSE"]
    assert b"Tabler v1.7.1" in files["vendor/tabler/tabler.min.css"]
    assert len(ui_kit.icons()) == 5184


def test_icons_are_found_by_words_and_copied_as_svg():
    found = ui_kit.find_icons("coin", 5)
    assert found and found[0][0] == "coin"
    assert ui_kit.find_icons("game pad")[0][0].startswith("device-gamepad")
    svg = ui_kit.icon_file("coin").decode()
    assert svg.startswith("<svg") and 'stroke="currentColor"' in svg
    with pytest.raises(ui_kit.UiKitError, match="No icon"):
        ui_kit.icon_file("../../secret")
    with pytest.raises(ui_kit.UiKitError, match="Say what"):
        ui_kit.find_icons("  ")


def test_the_starter_is_a_working_project():
    files = ui_kit.starter_files("Sky <Hop>")
    assert {"index.html", "app.js", "styles.css", "assets/icons.svg"} <= set(files)
    page = files["index.html"].decode()
    assert "Sky &lt;Hop&gt;" in page and "App Name" not in page
    assert 'href="vendor/tabler/tabler.min.css"' in page
    texts = {
        path: data.decode()
        for path, data in files.items()
        if path.endswith((".html", ".css", ".js")) and not path.startswith("vendor/")
    }
    assert check_project(texts, others=[p for p in files if p not in texts]) == []


@pytest.mark.asyncio
async def test_agents_start_apps_and_copy_icons(make_studio):
    studio, _ = make_studio([])
    site, context = await builder_in_project(studio)
    started = await run(studio, context, "ui_kit", action="app", title="Sky Hop")
    assert not started.failed, started.text
    paths = {item.path for item in await studio.workspace.files(site.id)}
    assert {"index.html", "app.js", "vendor/tabler/tabler.min.css"} <= paths
    icons = await run(studio, context, "ui_kit", action="icons", query="sword")
    assert icons.data["icons"]
    used = await run(
        studio, context, "ui_kit", action="use_icons", names=icons.data["icons"][:2]
    )
    assert not used.failed
    paths = {item.path for item in await studio.workspace.files(site.id)}
    assert f"assets/icons/{icons.data['icons'][0]}.svg" in paths
    wrong = await run(studio, context, "ui_kit", action="use_icons", names=["nope-x"])
    assert wrong.failed


@pytest.mark.asyncio
async def test_builders_and_coders_get_the_kit(make_studio):
    studio, _ = make_studio([])
    agents = await studio.ensure_defaults()
    for name in ("Builder", "Coder"):
        agent = next(item for item in agents if item.name == name)
        assert "ui_kit" in agent.tools, name
        await studio._store.put(
            agent.model_copy(
                update={"tools": tuple(t for t in agent.tools if t != "ui_kit")}
            )
        )
    await studio.ensure_defaults()
    for name in ("Builder", "Coder"):
        agent = next(item for item in agents if item.name == name)
        upgraded = await studio._store.get(Agent, agent.id)
        assert upgraded is not None and "ui_kit" in upgraded.tools, name
