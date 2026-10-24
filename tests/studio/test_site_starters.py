"""The lessons and portfolio starters: complete pages that only need the
business's real content."""

import shutil
import subprocess
from typing import Any

import pytest

from free_claude_code.studio.project_check import check_project
from free_claude_code.studio.templates import (
    STARTER_TEXT,
    template_files,
    template_libraries,
)
from free_claude_code.studio.tools import TOOL_SPEC_BY_NAME

STARTERS = {"lessons": "lessons.js", "portfolio": "portfolio.js"}


@pytest.mark.parametrize("name", STARTERS)
def test_each_starter_is_complete_and_only_needs_real_content(name):
    files = template_files(name, "Sea & Co's")
    assert set(files) == {"index.html", "styles.css", STARTERS[name], "README.md"}
    assert template_libraries(name) == {}
    page = files["index.html"]
    assert "<title>Sea & Co's</title>" in page
    assert "$title" not in "".join(files.values())
    assert f'<script src="{STARTERS[name]}" defer></script>' in page
    assert '<link rel="stylesheet" href="styles.css">' in page
    # Nothing from the sample sites they were made from.
    text = "".join(files.values())
    for leftover in ("Tidepool", "Marrow", "previews", "made by Claude"):
        assert leftover not in text
    problems = check_project(files)
    assert len(problems) == 1 and "placeholder text" in problems[0], problems
    spec = TOOL_SPEC_BY_NAME["start_project"]
    parameters: Any = spec.parameters
    assert name in parameters["properties"]["template"]["enum"]
    assert name in spec.description


def test_the_sample_lines_are_flagged_until_replaced():
    files = template_files("lessons", "Swell")
    page = files["index.html"]
    for phrase in STARTER_TEXT:
        page = page.replace(phrase, "Our own words")
    files["index.html"] = page
    assert check_project(files) == []


def test_the_booking_form_always_reaches_the_school():
    files = template_files("lessons", "Swell")
    assert 'data-email="hello@yourschool.example"' in files["index.html"]
    script = files["lessons.js"]
    assert "form.dataset.endpoint" in script and "mailto:" in script
    assert "prefers-reduced-motion: reduce" in script
    assert "IntersectionObserver" in script


def test_the_portfolio_follows_the_theme():
    files = template_files("portfolio", "Studio North")
    assert "prefers-color-scheme: dark" in files["styles.css"]
    assert ':root[data-theme="dark"]' in files["styles.css"]
    # The drawings are repainted in the new colours when the theme changes.
    assert 'matchMedia("(prefers-color-scheme: dark)")' in files["portfolio.js"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
@pytest.mark.parametrize("name", STARTERS)
def test_the_starters_scripts_parse(tmp_path, name):
    target = tmp_path / STARTERS[name]
    target.write_text(template_files(name, "X")[STARTERS[name]], encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(target)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
