"""try_page: agents use a project's web page like a user, not just read it."""

from pathlib import Path

import pytest

from free_claude_code.studio.page_try import (
    MAX_STEPS,
    PageReport,
    Step,
    _same,
    page_path,
    parse_steps,
)
from free_claude_code.studio.presets import CODER_TOOLS, TESTER_PROMPT, TESTER_TOOLS

from .conftest import tool_reply


def test_steps_are_checked_before_the_browser_opens():
    steps = parse_steps(
        [
            {"do": "Fill", "target": "Bill", "value": 50},
            {"do": "read", "target": "#total", "expect": "$57.50"},
            {"do": "press"},
        ]
    )
    assert steps == (
        Step("fill", "Bill", "50"),
        Step("read", "#total", "", "$57.50"),
        Step("press"),
    )
    assert parse_steps(None) == ()
    for bad, words in (
        ("click it", "must be a list"),
        ([{"do": "hover", "target": "a"}], "do must be one of"),
        ([{"do": "click"}], "needs a target"),
        (["click"], "must be an object"),
        ([{"do": "wait"}] * (MAX_STEPS + 1), "at most"),
    ):
        with pytest.raises(ValueError, match=words):
            parse_steps(bad)


def test_only_pages_inside_the_project_can_be_tried(tmp_path: Path):
    (tmp_path / "index.html").write_text("<p>hi</p>")
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "index.html").write_text("<p>shop</p>")
    assert page_path(tmp_path, "") == (tmp_path / "index.html").resolve()
    assert page_path(tmp_path, "/shop") == (tmp_path / "shop/index.html").resolve()
    with pytest.raises(ValueError, match="inside the project"):
        page_path(tmp_path, "../secret.html")
    with pytest.raises(ValueError, match=r"no about\.html"):
        page_path(tmp_path, "about.html")


def test_expected_values_match_loosely():
    assert _same("Tip: $15.21", "$15.21")
    assert _same("  Hello   World ", "hello world")
    assert not _same("$0.00", "$15.21")


def test_a_report_says_what_failed():
    report = PageReport(page="index.html", size=(390, 800))
    report.lines.append("1. fill Bill = '50'")
    assert report.render().startswith("PASSED: tried index.html at 390x800.")
    report.problems.append("Step 2: #tip shows '$0.00', expected '$7.50'.")
    text = report.render()
    assert text.startswith("FAILED (1)") and "expected '$7.50'" in text


@pytest.mark.asyncio
async def test_the_tester_tries_the_page_through_the_tool(make_studio):
    steps = [{"do": "read", "target": "#tip", "expect": "$7.50"}]
    studio, _ = make_studio(
        [tool_reply("try_page", {"steps": steps, "desktop": True}), "Tried."]
    )
    seen: list[tuple[Path, str, tuple[Step, ...], bool]] = []

    async def fake(folder: Path, page: str, steps, *, phone: bool) -> PageReport:
        seen.append((folder, page, tuple(steps), phone))
        report = PageReport(page=page, size=(1280, 800))
        report.problems.append("Step 1: #tip shows '$0.00', expected '$7.50'.")
        return report

    studio._page_tryer = fake
    await studio.ensure_defaults()
    tester = await studio.agent_by_name("Tester")
    assert tester is not None and "try_page" in tester.tools
    site = await studio.create_site(name="Tips")
    await studio.workspace.write(site.id, "index.html", "<p id=tip>$0.00</p>")
    chat = await studio.create_chat(agent_id=tester.id, site_id=site.id)

    await studio.send(chat.id, "test it")

    assert seen == [
        (
            studio.workspace.directory(site.id),
            "index.html",
            (Step("read", "#tip", "", "$7.50"),),
            False,
        )
    ]
    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert tool.text.startswith("FAILED (1)")
    assert tool.data["passed"] is False and tool.data["page"] == "index.html"


def test_the_coder_and_tester_have_it_and_the_tester_is_told_to_use_it():
    assert "try_page" in TESTER_TOOLS and "try_page" in CODER_TOOLS
    assert "try_page" in TESTER_PROMPT and "expect" in TESTER_PROMPT
