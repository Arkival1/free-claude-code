"""The game library: Phaser and its examples, Kenney's art and sound, the
download-once game vault, the phaser-game starter and the game-dev skill."""

import dataclasses
import hashlib
import io
import shutil
import subprocess
import zipfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio import game_library
from free_claude_code.studio.game_library import GameVault, Pack
from free_claude_code.studio.models import Agent
from free_claude_code.studio.project_check import check_project
from free_claude_code.studio.templates import template_files, template_libraries
from free_claude_code.studio.tools import TOOL_SPEC_BY_NAME

from .test_builder_images import builder_in_project, run

ROOT = Path(__file__).resolve().parents[2]


def sums(folder: str) -> str:
    return (ROOT / "vendor" / folder / "SHA256SUMS").read_text()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_everything_ships_with_its_checksum_and_licence():
    here = game_library.HERE
    assert f"{digest(game_library.CORE)}  kenney-core.zip" in sums("kenney")
    assert f"{digest(game_library.CATALOGUE)}  kenney-catalogue.json.gz" in sums(
        "kenney"
    )
    assert f"{digest(game_library.PHASER)}  phaser/phaser.min.js" in sums("phaser")
    assert (
        f"{digest(here / 'phaser-examples.json.gz')}  phaser-examples.json.gz"
        in sums("phaser")
    )
    assert "MIT License" in (here / "phaser" / "LICENSE.md").read_text()
    assert "Creative Commons Zero" in (ROOT / "vendor/kenney/LICENSE.txt").read_text()
    packs = game_library.packs()
    assert len(packs) == 217
    shipped = [item for item in packs if item.shipped]
    assert len(shipped) == 49
    assert all(len(item.sha256) == 64 for item in packs)
    assert all(item.url.startswith(game_library.KENNEY) for item in packs)
    # Shipped sounds are mp3 (they play on iPhones); every shipped file is in the zip.
    with zipfile.ZipFile(game_library.CORE) as bundle:
        names = set(bundle.namelist())
    for item in shipped:
        assert not any(path.endswith(".ogg") for path in item.files), item.id
        assert all(f"{item.id}/{path}" in names for path in item.files), item.id
    assert len(game_library.examples()) == 2298


def test_files_are_found_by_words_and_kind_shipped_first():
    coins = game_library.find_files("coin", count=6)
    assert coins and all("coin" in path.casefold() for _, path in coins)
    assert coins[0][0].shipped
    lasers = game_library.find_files("laser", kind="sound", count=5)
    assert lasers and all(path.endswith(".mp3") for _, path in lasers)
    # One pack can't fill every slot.
    assert len({item.id for item, _ in game_library.find_files("tile", count=12)}) > 1
    with pytest.raises(game_library.GameLibraryError, match="No kind"):
        game_library.find_files("coin", kind="smell")
    with pytest.raises(game_library.GameLibraryError, match="Say what"):
        game_library.find_files("  ")
    assert all(
        "platformer" in item.id for item in game_library.find_packs("platformer")
    )
    found = game_library.find_examples("tilemap collision", 5)
    assert found and all("tilemap" in item.id for item in found)
    assert game_library.example(found[0].id).code


def fake_pack(tmp_path: Path) -> tuple[Pack, bytes]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("PNG/ship.png", b"\x89PNG fake")
        bundle.writestr("License.txt", "CC0")
    data = buffer.getvalue()
    item = Pack(
        id="test-pack",
        name="Test Pack",
        category="2D",
        url=f"{game_library.KENNEY}test/kenney_test.zip",
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        shipped=False,
        files=("License.txt", "PNG/ship.png"),
    )
    return item, data


def test_the_vault_keeps_only_a_pack_that_matches_its_checksum(tmp_path):
    item, data = fake_pack(tmp_path)
    vault = GameVault(tmp_path / "game-vault")
    with pytest.raises(game_library.GameLibraryError, match="doesn't match"):
        vault.keep(item, data + b"tampered")
    assert not vault.has(item)
    vault.keep(item, data)
    assert vault.has(item)
    assert game_library.read_files(item, ["PNG/ship.png"], vault) == {
        "PNG/ship.png": b"\x89PNG fake"
    }


@pytest.mark.asyncio
async def test_agents_find_use_and_download_packs(make_studio, monkeypatch, tmp_path):
    studio, _ = make_studio([])
    site, context = await builder_in_project(studio)
    found = await run(studio, context, "game_assets", action="find", query="coin")
    assert not found.failed and "action use" in found.text
    pack_id, path = found.data["files"][0].split("/", 1)
    used = await run(
        studio, context, "game_assets", action="use", pack=pack_id, files=[path]
    )
    assert not used.failed, used.text
    paths = {item.path for item in await studio.workspace.files(site.id)}
    assert f"assets/{pack_id}/{path}" in paths
    assert any(item.startswith(f"assets/{pack_id}/License") for item in paths)

    # A pack that isn't on the PC downloads once, checked against its checksum.
    item, data = fake_pack(tmp_path)
    real = game_library.pack
    monkeypatch.setattr(
        "free_claude_code.studio.tools.game_pack",
        lambda wanted: item if wanted == "test-pack" else real(wanted),
    )
    early = await run(
        studio, context, "game_assets", action="use", pack="test-pack", files=["PNG"]
    )
    assert early.failed and "download it first" in early.text
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=data)

    studio._search_transport = httpx.MockTransport(handle)
    got = await run(studio, context, "game_assets", action="download", pack="test-pack")
    assert not got.failed, got.text
    assert seen == [item.url] and studio.game_vault.has(item)
    again = await run(
        studio, context, "game_assets", action="use", pack="test-pack", files=["PNG"]
    )
    assert not again.failed
    assert "assets/test-pack/PNG/ship.png" in {
        entry.path for entry in await studio.workspace.files(site.id)
    }


@pytest.mark.asyncio
async def test_agents_read_phaser_examples_without_its_art(make_studio):
    studio, _ = make_studio([])
    _, context = await builder_in_project(studio)
    found = await run(
        studio, context, "game_assets", action="examples", query="particles explode"
    )
    first = found.data["examples"][0]
    got = await run(studio, context, "game_assets", action="example", id=first)
    assert "isn't free to use" in got.text and "Phaser example" in got.text
    wrong = await run(studio, context, "game_assets", action="example", id="nope")
    assert wrong.failed


def test_the_game_starter_brings_phaser_and_kenney_art():
    files = template_files("phaser-game", "Sky Hop")
    assert set(files) == {"index.html", "styles.css", "game.js", "README.md"}
    libraries = template_libraries("phaser-game")
    assert {
        "vendor/phaser/phaser.min.js",
        "vendor/phaser/LICENSE.md",
        "assets/tiles.png",
        "assets/characters.png",
        "assets/sounds/jingle_win.mp3",
        "assets/LICENSE-kenney.txt",
    } <= set(libraries)
    assert all(source.is_file() for source in libraries.values())
    assert "<title>Sky Hop</title>" in files["index.html"]
    assert 'src="vendor/phaser/phaser.min.js"' in files["index.html"]
    assert "visibilitychange" in files["game.js"] and "data-key" in files["index.html"]
    assert check_project(files, others=list(libraries)) == []
    spec = TOOL_SPEC_BY_NAME["start_project"]
    assert "phaser-game" in spec.description


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_game_starter_script_parses(tmp_path):
    target = tmp_path / "game.js"
    target.write_text(template_files("phaser-game", "X")["game.js"], encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(target)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_builders_and_coders_get_the_game_library(make_studio):
    studio, _ = make_studio([])
    agents = await studio.ensure_defaults()
    for name in ("Builder", "Coder"):
        agent = next(item for item in agents if item.name == name)
        assert "game_assets" in agent.tools, name
        await studio._store.put(
            agent.model_copy(
                update={"tools": tuple(t for t in agent.tools if t != "game_assets")}
            )
        )
    await studio.ensure_defaults()
    for name in ("Builder", "Coder"):
        agent = next(item for item in agents if item.name == name)
        upgraded = await studio._store.get(Agent, agent.id)
        assert upgraded is not None and "game_assets" in upgraded.tools, name
    skill = ROOT / "src/free_claude_code/studio/builtin_skills/game-dev/SKILL.md"
    assert "phaser-game" in skill.read_text() and "game_assets" in skill.read_text()


@pytest.mark.asyncio
async def test_pack_files_with_spaces_land_under_safe_names(make_studio):
    studio, _ = make_studio([])
    site, context = await builder_in_project(studio)
    jingles = game_library.pack("music-jingles")
    spaced = next(path for path in jingles.files if " " in path)
    used = await run(
        studio,
        context,
        "game_assets",
        action="use",
        pack="music-jingles",
        files=[spaced],
    )
    assert not used.failed, used.text
    safe = game_library.project_path(jingles, spaced)
    assert " " not in safe and safe in used.text
    assert safe in {item.path for item in await studio.workspace.files(site.id)}
    # Every file in every pack has a name a project accepts.
    from free_claude_code.studio.sites import _SEGMENT_PATTERN

    for item in game_library.packs():
        for path in item.files:
            assert all(
                _SEGMENT_PATTERN.match(part)
                for part in game_library.project_path(item, path).split("/")
            ), (item.id, path)


@pytest.mark.asyncio
async def test_copying_art_over_a_file_keeps_the_old_one(make_studio):
    studio, _ = make_studio([])
    site, _ = await builder_in_project(studio)
    await studio.workspace.copy_library_bytes(site.id, "assets/x/a.png", b"mine")
    await studio.workspace.copy_library_bytes(site.id, "assets/x/a.png", b"kenney")
    history = list(
        (studio.workspace.directory(site.id).parent).rglob("*")
    )  # the versions folder sits beside the sites
    assert any(path.is_file() and path.read_bytes() == b"mine" for path in history)


@pytest.mark.asyncio
async def test_a_kit_text_file_that_isnt_utf8_is_copied_as_it_is(make_studio):
    studio, _ = make_studio([])
    site, _ = await builder_in_project(studio)
    toolbox = studio._toolbox()
    written, _ = await toolbox._copy_kit(
        site.id, {"notes.txt": "café".encode("latin-1")}, overwrite=True
    )
    assert written == ["notes.txt"]
    folder = studio.workspace.directory(site.id)
    assert (folder / "notes.txt").read_bytes() == "café".encode("latin-1")


def test_a_downloaded_pack_missing_a_file_says_so(tmp_path):
    item, data = fake_pack(tmp_path)
    vault = GameVault(tmp_path / "game-vault")
    vault.keep(item, data)
    lying = dataclasses.replace(item, files=(*item.files, "PNG/gone.png"))
    with pytest.raises(game_library.GameLibraryError, match="download it again"):
        game_library.read_files(lying, ["PNG/gone.png"], vault)
