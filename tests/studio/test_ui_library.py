"""The UI library: 3,802 Uiverse pieces the Builder and Coder search and copy."""

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from free_claude_code.studio import ui_library
from free_claude_code.studio.models import Agent
from free_claude_code.studio.presets import CODER_TOOLS, TOOL_GROUPS
from free_claude_code.studio.tools import TOOL_SPEC_BY_NAME

from .test_builder_images import builder_in_project, run

ROOT = Path(__file__).resolve().parents[2]


def test_the_whole_library_ships_with_fcc_and_matches_its_checksum():
    counts = ui_library.summary()
    assert counts["all"] == 3802
    assert counts["button"] == 1231 and counts["loader"] == 718
    assert counts["plain"] > 3000
    sums = (ROOT / "vendor" / "uiverse" / "SHA256SUMS").read_text()
    digest = hashlib.sha256(ui_library.DATA.read_bytes()).hexdigest()
    assert f"{digest}  uiverse.json.gz" in sums
    assert "MIT License" in (ROOT / "vendor" / "uiverse" / "LICENSE").read_text()
    # Every piece keeps its designer's credit.
    rows = json.loads(gzip.decompress(ui_library.DATA.read_bytes()))
    assert all("Uiverse.io" in row["html"] for row in rows)


def test_search_matches_tags_and_kind_words_plain_css_first():
    cards = ui_library.search("glass card", count=4)
    assert len(cards) == 4
    assert all(piece.kind == "card" and piece.plain for piece in cards)
    assert all("glass" in piece.tags.casefold() for piece in cards)
    # 'switch' means a toggle; 'spinner' a loader.
    assert {piece.kind for piece in ui_library.search("switch")} == {"toggle"}
    assert {piece.kind for piece in ui_library.search("spinner")} == {"loader"}
    assert ui_library.search("zzqx qwvb") == []
    # Kind words choose the kind and aren't tags to match.
    mixed = ui_library.search("toggle card")
    assert mixed and {piece.kind for piece in mixed} == {"toggle"}
    assert len(ui_library.search("button", count=99)) == ui_library.MAX_RESULTS
    with_tailwind = ui_library.search("", kind="card", count=12, plain_only=False)
    assert all(piece.kind == "card" for piece in with_tailwind)
    with pytest.raises(ui_library.UiLibraryError, match="No kind"):
        ui_library.search("x", kind="sofa")
    with pytest.raises(ui_library.UiLibraryError, match="No piece"):
        ui_library.piece("card/nobody_here-1")


@pytest.mark.asyncio
async def test_agents_search_and_get_a_piece_with_its_credit(make_studio):
    studio, _ = make_studio([])
    _, context = await builder_in_project(studio)
    found = await run(studio, context, "ui_library", action="search", query="neon")
    assert not found.failed, found.text
    first = found.data["ids"][0]
    assert f"1. {first} (" in found.text and "action get" in found.text

    got = await run(studio, context, "ui_library", action="get", id=first)
    assert not got.failed
    assert "From Uiverse.io by" in got.text and "credit comment" in got.text
    assert ui_library.piece(first).html in got.text

    toggles = await run(
        studio, context, "ui_library", action="search", query="dark", kind="toggle"
    )
    assert all(item.startswith("toggle/") for item in toggles.data["ids"])
    wrong = await run(studio, context, "ui_library", action="get", id="nope")
    assert wrong.failed and "No piece" in wrong.text
    odd = await run(studio, context, "ui_library", action="paint")
    assert odd.failed


@pytest.mark.asyncio
async def test_a_tailwind_piece_says_to_rewrite_it_as_css(make_studio):
    studio, _ = make_studio([])
    _, context = await builder_in_project(studio)
    tailwind = next(piece for piece in ui_library.pieces() if piece.tailwind)
    got = await run(studio, context, "ui_library", action="get", id=tailwind.id)
    assert "Tailwind classes" in got.text


@pytest.mark.asyncio
async def test_the_builder_coder_and_saved_agents_get_the_library(make_studio):
    studio, _ = make_studio([])
    agents = await studio.ensure_defaults()
    builder = next(agent for agent in agents if agent.name == "Builder")
    assert "ui_library" in builder.tools and "ui_library" in CODER_TOOLS
    # A Builder saved before the library is upgraded in place.
    await studio._store.put(
        builder.model_copy(
            update={"tools": tuple(t for t in builder.tools if t != "ui_library")}
        )
    )
    await studio.ensure_defaults()
    upgraded = await studio._store.get(Agent, builder.id)
    assert upgraded is not None and "ui_library" in upgraded.tools
    grouped = {tool for _, tools in TOOL_GROUPS for tool in tools}
    assert "ui_library" in grouped
    assert "3,802" in TOOL_SPEC_BY_NAME["ui_library"].description


@pytest.mark.asyncio
async def test_a_long_piece_is_cut_but_keeps_its_credit(make_studio):
    studio, _ = make_studio([])
    _, context = await builder_in_project(studio)
    long = next(
        piece
        for piece in ui_library.pieces()
        if len(piece.html) > 20_000 and "Uiverse.io" not in piece.html[:12_000]
    )
    got = await run(studio, context, "ui_library", action="get", id=long.id)
    assert ui_library.credit(long) in got.text
    assert "Cut at 12,000" in got.text and "the end is missing" in got.text


@pytest.mark.asyncio
async def test_model_arguments_in_other_shapes_still_work(make_studio):
    studio, _ = make_studio([])
    _, context = await builder_in_project(studio)
    two = await run(
        studio, context, "ui_library", action="search", query="card", count="2"
    )
    assert len(two.data["ids"]) == 2
    tailwind = await run(
        studio,
        context,
        "ui_library",
        action="search",
        kind="card",
        tailwind="true",
        count=12,
    )
    assert not tailwind.failed
    default = await run(studio, context, "ui_library", query="loader")
    assert not default.failed and default.data["ids"]
    missing = await run(studio, context, "ui_library", action="get", id=None)
    assert missing.failed and "No piece" in missing.text


@pytest.mark.asyncio
async def test_a_saved_designer_gets_the_library(make_studio):
    studio, _ = make_studio([])
    agents = await studio.ensure_defaults()
    designer = Agent(
        id="agt_designer",
        name="Designer",
        role="builder",
        model=agents[0].model,
        system_prompt="Design pages.",
        tools=("write_file", "read_file"),
    )
    await studio._store.put(designer)
    await studio.ensure_defaults()
    upgraded = await studio._store.get(Agent, designer.id)
    assert upgraded is not None
    assert "ui_library" in upgraded.tools and upgraded.role == "builder"


@pytest.mark.asyncio
async def test_the_owners_own_agent_called_developer_is_left_alone(make_studio):
    studio, _ = make_studio([])
    agents = await studio.ensure_defaults()
    mine = Agent(
        id="agt_mine",
        name="Developer",
        role="agent",
        model=agents[0].model,
        tools=("read_file",),
    )
    await studio._store.put(mine)
    await studio.ensure_defaults()
    kept = await studio._store.get(Agent, mine.id)
    assert kept is not None
    assert kept.tools == ("read_file",) and kept.role == "agent"
