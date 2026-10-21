"""The Changer: an AI inside FCC that changes a copy of FCC and packs update
zips, never touching the running app."""

import hashlib
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.core.json_types import JsonObject
from free_claude_code.studio.changer import (
    Changer,
    ChangerError,
    bump_lock,
    bump_version,
    tree,
)
from tests.api.support import create_test_app

PYPROJECT = '[project]\nname = "free-claude-code"\nversion = "6.75.0"\n'
LOCK = (
    '[[package]]\nname = "aiohttp"\nversion = "6.75.0"\n\n'
    '[[package]]\nname = "free-claude-code"\nversion = "6.75.0"\n'
)
FAKE_SERVER = (
    "import http.server, os, pathlib\n"
    "pathlib.Path('seen-home.txt').write_text(os.environ.get('HOME', '') + '|' + "
    "str(any('KEY' in name for name in os.environ)))\n"
    "http.server.HTTPServer(('127.0.0.1', int(os.environ['PORT'])), "
    "http.server.SimpleHTTPRequestHandler).serve_forever()\n"
)


def make_app(root: Path) -> Path:
    package = root / "src" / "free_claude_code"
    (package / "studio").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "studio" / "lab.py").write_text("def mix():\n    return 'fizz'\n")
    (package / "studio" / "page.js").write_text("const a = 1;\n")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "junk.pyc").write_bytes(b"\0")
    (root / "scripts").mkdir()
    (root / "scripts" / "start.ps1").write_text("uv run fcc-server\n")
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "uv.lock").write_text(LOCK)
    (root / "CLAUDE.md").write_text("Rules.\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("left out of the copy\n")
    return root


def changer_for(tmp_path: Path, **options) -> tuple[Changer, Path, Path]:
    source = make_app(tmp_path / "fcc")
    target = tmp_path / "copy"
    changer = Changer(
        tmp_path / "changer", source=source, import_check="print('ok')", **options
    )
    changer.make_copy(target)
    return changer, source, target


def test_the_copy_holds_the_code_but_not_caches_tests_or_data(tmp_path):
    changer, _, target = changer_for(tmp_path)
    copied = set(tree(target))
    assert "src/free_claude_code/studio/lab.py" in copied
    assert "scripts/start.ps1" in copied and "pyproject.toml" in copied
    assert not any("__pycache__" in name or name.startswith("tests") for name in copied)
    assert changer.changes(target) == {"changed": [], "added": [], "deleted": []}


def test_changes_and_diffs_are_against_the_running_app(tmp_path):
    changer, source, target = changer_for(tmp_path)
    lab = target / "src/free_claude_code/studio/lab.py"
    lab.write_text("def mix():\n    return 'bubbles'\n")
    (target / "src/free_claude_code/studio/new.py").write_text("X = 1\n")
    (target / "CLAUDE.md").unlink()
    assert changer.changes(target) == {
        "changed": ["src/free_claude_code/studio/lab.py"],
        "added": ["src/free_claude_code/studio/new.py"],
        "deleted": ["CLAUDE.md"],
    }
    diff = changer.diff(target, "src/free_claude_code/studio/lab.py")
    assert "-    return 'fizz'" in diff and "+    return 'bubbles'" in diff
    # The running app is never touched.
    assert "fizz" in (source / "src/free_claude_code/studio/lab.py").read_text()
    with pytest.raises(ChangerError):
        changer.diff(target, "../outside.py")


@pytest.mark.asyncio
async def test_checks_catch_broken_python_and_json(tmp_path):
    changer, _, target = changer_for(tmp_path)
    good = await changer.check(target)
    assert good.passed and "Nothing has changed" in good.text()
    (target / "src/free_claude_code/studio/lab.py").write_text("def mix(:\n")
    (target / "src/free_claude_code/studio/data.json").write_text("{nope")
    bad = await changer.check(target)
    assert not bad.passed
    assert any("lab.py line 1" in problem for problem in bad.problems)
    assert any("data.json" in problem for problem in bad.problems)
    broken = Changer(
        tmp_path / "changer",
        source=tmp_path / "fcc",
        import_check="raise SystemExit('cannot import the app')",
    )
    report = await broken.check(target)
    assert any("doesn't load" in problem for problem in report.problems)


def test_versions_go_up_one_patch():
    text, old, new = bump_version(PYPROJECT)
    assert (old, new) == ("6.75.0", "6.75.1") and 'version = "6.75.1"' in text
    lock = bump_lock(LOCK, old, new)
    assert 'name = "free-claude-code"\nversion = "6.75.1"' in lock
    assert 'name = "aiohttp"\nversion = "6.75.0"' in lock
    with pytest.raises(ChangerError):
        bump_version("[project]\n")


def test_an_update_zip_carries_only_the_changes_and_a_rollback_undoes_it(tmp_path):
    changer, _, target = changer_for(tmp_path)
    with pytest.raises(ChangerError, match="Nothing has changed"):
        changer.package(target, "")
    (target / "src/free_claude_code/studio/lab.py").write_text(
        "def mix():\n    return 'bubbles'\n"
    )
    (target / "src/free_claude_code/studio/new.py").write_text("X = 1\n")
    made = changer.package(
        target, "The Lab fizzes with bubbles now.", report="# Test report\nok\n"
    )
    assert made["version"] == "6.75.1"
    assert str(made["name"]).startswith("FCC-Studio-update-6.75.1-")
    update = changer.update_file(str(made["name"]))
    papers = "fcc/_update/6.75.1/"
    with zipfile.ZipFile(update) as archive:
        names = set(archive.namelist())
        changelog = archive.read(papers + "CHANGELOG.md").decode()
        manifest = json.loads(archive.read(papers + "MANIFEST.json"))
        sums = archive.read(papers + "SHA256SUMS.txt").decode()
        lab = archive.read("fcc/src/free_claude_code/studio/lab.py")
    assert names == {
        "fcc/src/free_claude_code/studio/lab.py",
        "fcc/src/free_claude_code/studio/new.py",
        "fcc/pyproject.toml",
        "fcc/uv.lock",
        papers + "CHANGELOG.md",
        papers + "UPDATE_INSTRUCTIONS.md",
        papers + "MANIFEST.json",
        papers + "SHA256SUMS.txt",
        papers + "TEST-REPORT.md",
    }
    assert "6.75.0 -> 6.75.1" in changelog and "bubbles now" in changelog
    assert manifest["from"] == "6.75.0" and manifest["to"] == "6.75.1"
    assert (
        hashlib.sha256(lab).hexdigest() + "  src/free_claude_code/studio/lab.py" in sums
    )
    assert str(made["backup"]).endswith("-rollback.zip")
    with zipfile.ZipFile(changer.update_file(str(made["backup"]))) as archive:
        assert "fizz" in archive.read("fcc/src/free_claude_code/studio/lab.py").decode()
        assert "new.py" in archive.read("fcc/FCC-UNDO.txt").decode()
    assert [row["name"] for row in changer.updates()] == [made["name"]]
    with pytest.raises(ChangerError):
        changer.update_file("../../etc/passwd")
    project = changer.package(target, "A bigger one.", minor=True)
    assert project["version"] == "6.76.0"


@pytest.mark.asyncio
async def test_screenshots_run_the_copy_with_no_keys_and_empty_data(
    tmp_path, monkeypatch
):
    taken: list[tuple[str, str]] = []

    async def shooter(pages, folder: Path, *, size):
        folder.mkdir(parents=True, exist_ok=True)
        for name, url in pages:
            taken.append((name, url))
            async with httpx.AsyncClient(trust_env=False) as client:
                assert (await client.get(url.split("#")[0])).status_code < 500
            (folder / f"{name}.png").write_bytes(b"png")
        return [folder / f"{name}.png" for name, _ in pages], []

    monkeypatch.setenv("FAKE_API_KEY", "secret")
    changer, _, target = changer_for(tmp_path, shooter=shooter, serve_copy=FAKE_SERVER)
    result = await changer.screenshots(target, ["lab", "trade"])
    assert result["shots"] == ["lab.png", "trade.png"]
    assert [name for name, _ in taken] == ["lab", "trade"]
    assert taken[0][1].endswith("/studio#lab")
    home, saw_key = (target / "seen-home.txt").read_text().split("|")
    assert "fcc-changer-" in home and saw_key == "False"
    assert not Path(home).exists()
    assert changer.shots() == ["lab.png", "trade.png"]
    with pytest.raises(ChangerError):
        await changer.screenshots(target, ["../etc"])


@pytest.mark.asyncio
async def test_the_changer_tool_works_only_in_its_copy(make_studio, tmp_path):
    studio, _ = make_studio([])
    studio._changer = Changer(
        tmp_path / "changer",
        source=make_app(tmp_path / "fcc"),
        import_check="print('ok')",
    )
    from free_claude_code.studio.llm import ToolCall
    from free_claude_code.studio.tools import ToolContext

    outcome = await studio._changer_tool(
        ToolCall(id="1", name="fcc_changer", arguments={"action": "check"}),
        ToolContext(agent_id="a", chat_id="c", site_id="site_other"),
    )
    assert outcome.failed and "only in the Changer copy" in outcome.text


@pytest.mark.asyncio
async def test_the_changer_through_the_app(make_studio, tmp_path):
    studio, _ = make_studio([])
    studio._changer = Changer(
        tmp_path / "changer",
        source=make_app(tmp_path / "fcc"),
        import_check="print('ok')",
    )
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        view: JsonObject = (await client.get("/studio/api/changer")).json()
        assert view["ready"] is True and view["copy"] is None
        fresh = await client.post("/studio/api/changer/fresh")
        assert fresh.status_code == 200 and fresh.json()["files"] > 0
        nothing = await client.post("/studio/api/changer/package", json={"note": ""})
        assert nothing.status_code == 400
        checked = (await client.post("/studio/api/changer/check")).json()
        assert checked["passed"] is True
        missing = await client.get("/studio/api/changer/updates/nope.zip")
        assert missing.status_code == 404
        empty = await client.post("/studio/api/changer/start", json={"request": " "})
        assert empty.status_code == 400
