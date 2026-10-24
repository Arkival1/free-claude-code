"""The bug-fix library: 490 real bugs, fixes and tests for the Changer."""

import hashlib
from pathlib import Path

import pytest

from free_claude_code.studio import bug_library
from free_claude_code.studio.models import Agent, StudioFlag
from free_claude_code.studio.presets import CHANGER_READER_TOOLS, CHANGER_TOOLS
from free_claude_code.studio.service import CHANGER_AGENT_NAME
from free_claude_code.studio.tools import ToolContext

from .test_builder_images import run

ROOT = Path(__file__).resolve().parents[2]


def test_the_library_ships_with_its_checksum_and_licences():
    digest = hashlib.sha256(bug_library.DATA.read_bytes()).hexdigest()
    assert (
        f"{digest}  bugs.json.gz" in (ROOT / "vendor/swe-bench/SHA256SUMS").read_text()
    )
    assert "MIT License" in (ROOT / "vendor/swe-bench/LICENSE").read_text()
    bugs = bug_library.bugs()
    assert len(bugs) == 490
    assert not any(item.repo == "pylint-dev/pylint" for item in bugs)
    assert all(bug_library.licence_of(item.repo) for item in bugs)
    assert all(item.fix.startswith("diff --git") and item.fails for item in bugs)


def test_bugs_are_found_by_their_description():
    found = bug_library.find("timezone conversion", repo="django")
    assert found and all(item.repo == "django/django" for item in found)
    assert any("time" in item.title.casefold() for item in found)
    assert bug_library.bug(found[0].id).files
    with pytest.raises(bug_library.BugLibraryError, match="Describe"):
        bug_library.find(" ")
    with pytest.raises(bug_library.BugLibraryError, match="No bug"):
        bug_library.bug("nope")


@pytest.mark.asyncio
async def test_the_changer_reads_a_bug_and_its_test(make_studio):
    studio, _ = make_studio([])
    assert "bug_library" in CHANGER_TOOLS and "bug_library" in CHANGER_READER_TOOLS
    context = ToolContext(agent_id="a", chat_id="c")
    found = await run(
        studio, context, "bug_library", action="find", query="unicode filename"
    )
    assert not found.failed and found.data["bugs"]
    got = await run(
        studio, context, "bug_library", action="get", id=found.data["bugs"][0]
    )
    assert "The fix the project merged" in got.text and "licence" in got.text
    test_only = await run(
        studio,
        context,
        "bug_library",
        action="get",
        id=found.data["bugs"][0],
        part="test",
    )
    assert "fails before" in test_only.text and "The issue" not in test_only.text


@pytest.mark.asyncio
async def test_an_existing_changer_gets_the_library_once(make_studio):
    studio, _ = make_studio([])
    changer = await studio._changer_agent()
    stripped = changer.model_copy(
        update={"tools": tuple(t for t in changer.tools if t != "bug_library")}
    )
    await studio._store.put(stripped)
    again = await studio._changer_agent()
    assert "bug_library" not in again.tools  # a new Changer already had it: flag set
    await studio._store.delete(StudioFlag, "changer_bug_library_v1")
    upgraded = await studio._changer_agent()
    assert "bug_library" in upgraded.tools
    saved = await studio._store.get(Agent, upgraded.id)
    assert saved is not None and saved.name == CHANGER_AGENT_NAME
