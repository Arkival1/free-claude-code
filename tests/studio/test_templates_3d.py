"""The Builder's 3D starters: a 3D landing page and a live 3D dashboard on
the FCC web kit, with three.js copied in byte for byte."""

import hashlib
import json
import re
import shutil
from typing import Any

import pytest

from free_claude_code.studio.project_check import check_project
from free_claude_code.studio.sites import MAX_FILE_BYTES
from free_claude_code.studio.templates import template_files, template_libraries
from free_claude_code.studio.templates_3d import PLACEHOLDER_3D
from free_claude_code.studio.tools import TOOL_SPEC_BY_NAME

from .conftest import tool_reply

THREE_D = ("3d-landing", "3d-dashboard")


@pytest.mark.parametrize("name", THREE_D)
def test_each_3d_starter_is_complete_and_only_needs_real_content(name):
    files = template_files(name, "Orbit Labs")
    assert {
        "index.html",
        "styles.css",
        "fcc-kit.css",
        "fcc-kit.js",
        "README.md",
    } <= set(files)
    assert "MIT License" in files["vendor/three/LICENSE"]
    page = files["index.html"]
    assert "<title>Orbit Labs</title>" in page
    assert "$title" not in "".join(files.values())
    # three.js comes from the project's own copy, through the import map.
    mapped = re.search(r'<script type="importmap">(.*?)</script>', page, re.S)
    assert mapped is not None
    imports = json.loads(mapped.group(1))
    assert imports["imports"]["three"] == "./vendor/three/three.module.js"
    assert page.index('type="importmap"') < page.index('type="module"')
    libraries = template_libraries(name)
    assert set(libraries) == {
        "vendor/three/three.module.js",
        "vendor/three/three.core.js",
        "vendor/three/OrbitControls.js",
    }
    assert all(source.is_file() for source in libraries.values())
    problems = check_project(
        {path: text for path, text in files.items() if not path.startswith("vendor/")},
        others=[*libraries, "vendor/three/LICENSE"],
    )
    # A fresh starter is a start: its placeholder lines (and, on the landing
    # page, the contact form's address) are all that's left to fill in.
    assert problems and "placeholder text" in problems[0], problems
    assert all("placeholder text" in p or "nowhere to send" in p for p in problems)


def test_the_dashboard_reads_json_and_says_how_to_connect_real_data():
    files = template_files("3d-dashboard", "Ops Board")
    data = json.loads(files["data.json"])
    assert {"kpis", "services", "links", "events"} <= set(data)
    assert 'data-source="data.json"' in files["index.html"]
    assert "window.dashboard" in files["dashboard.js"]
    assert "data-demo" in files["README.md"]


def test_the_kit_respects_reduced_motion_and_both_themes():
    kit = template_files("3d-landing", "X")["fcc-kit.css"]
    assert "prefers-reduced-motion: reduce" in kit
    assert ':root[data-theme="light"]' in kit and "prefers-color-scheme: light" in kit
    scene = template_files("3d-landing", "X")["scene.js"]
    assert "IntersectionObserver" in scene and "devicePixelRatio || 1, 1.5" in scene


def test_placeholders_are_known_and_the_builder_is_offered_the_starters():
    for phrase in ("Say what you offer in one line", "Say what this dashboard watches"):
        assert any(phrase in line for line in PLACEHOLDER_3D)
    spec = TOOL_SPEC_BY_NAME["start_project"]
    parameters: Any = spec.parameters
    assert set(THREE_D) <= set(parameters["properties"]["template"]["enum"])
    assert "3d-dashboard" in spec.description


@pytest.mark.asyncio
async def test_start_project_copies_three_byte_for_byte(make_studio):
    studio, _ = make_studio(
        [
            tool_reply("start_project", {"template": "3d-landing", "title": "Nova"}),
            tool_reply("check_project", {}, call_id="c2"),
            "ok",
        ]
    )
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    site = await studio.create_site(name="Nova")
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)

    await studio.send(chat.id, "make a 3D landing page")

    tools = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    started, checked = tools[0], tools[1]
    assert "vendor/three/three.core.js" in started.data["written"]
    for path, source in template_libraries("3d-landing").items():
        copied = studio.workspace.resolve(site.id, path).read_bytes()
        assert (
            hashlib.sha256(copied).digest()
            == hashlib.sha256(source.read_bytes()).digest()
        )
    # three.js is bigger than an agent may write, and isn't checked line by line.
    core = studio.workspace.resolve(site.id, "vendor/three/three.core.js")
    assert core.stat().st_size > MAX_FILE_BYTES
    assert checked.data["checked"] == 6
    assert not any("vendor/" in problem for problem in checked.data["problems"])


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
@pytest.mark.parametrize("name", THREE_D)
def test_the_starters_scripts_parse(tmp_path, name):
    import subprocess

    for path, text in template_files(name, "X").items():
        if not path.endswith(".js") or path.startswith("vendor/"):
            continue
        target = tmp_path / (
            path.replace("/", "_") + (".mjs" if "import " in text else "")
        )
        target.write_text(text, encoding="utf-8")
        result = subprocess.run(
            ["node", "--check", str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (path, result.stderr)
