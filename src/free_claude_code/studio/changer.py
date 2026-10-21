"""The Changer: an AI inside FCC that changes FCC itself, safely.

It never edits the running app. It works on a copy of FCC's own files (a
Studio project), checks the copy, screenshots the copy running on a spare
port with an empty data folder (no keys, none of the owner's data), and packs
what it changed into an update zip that unzips over the fcc folder, plus a
backup zip of the files the update replaces.
"""

import ast
import asyncio
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from loguru import logger

from free_claude_code.core.json_types import JsonObject

COPY_ITEMS: tuple[str, ...] = (
    "src",
    "scripts",
    "tests",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "CLAUDE.md",
    ".claude/skills/fcc-studio/SKILL.md",
)
"""What the copy holds: the code, the launch scripts, the tests, and the map
of the app."""
TEST_SECONDS = 420.0
MAX_TEST_FILES = 12
SHARED_FILES = frozenset(
    {"service.py", "store.py", "models.py", "studio_routes.py", "tools.py"}
)
"""Files nearly every test touches: tests are picked by the functions changed."""
LEFT_OUT_TESTS = re.compile(r"content_farm|cartoon_paint")
"""Content Farm stays untouched and untested unless the owner names it."""
SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".venv",
        ".git",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
)
SKIP_SUFFIXES = frozenset({".pyc", ".pyo"})
UPDATE_PREFIX = "fcc/"
"""Release zips unpack into fcc/, so updates do too."""
MAX_UPDATES = 30
MAX_DIFF_LINES = 600
SERVER_WAIT_SECONDS = 120.0
CHECK_SECONDS = 180.0
SCREEN_PAGES: tuple[str, ...] = ("home", "lab", "trade", "learn")
PAGE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,30}(?:/[A-Za-z0-9_-]{1,60})?$")
SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
IMPORT_CHECK = (
    "import free_claude_code.api.app, free_claude_code.studio.service; "
    "print('imports ok')"
)
SERVE_COPY = "from free_claude_code.cli.entrypoints import serve; serve()"

type Shooter = Callable[..., Awaitable[tuple[list[Path], list[str]]]]
"""Screenshot pages: (pages, folder, size=...) → (pictures, problems)."""


class ChangerError(RuntimeError):
    """A Changer step that can't run (no copy, no app folder, bad page)."""


def app_root() -> Path | None:
    """The fcc folder this app runs from, when it runs from source (uv run)."""
    root = Path(__file__).resolve().parents[3]
    return root if (root / "pyproject.toml").is_file() else None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wanted(path: Path) -> bool:
    return path.suffix not in SKIP_SUFFIXES and not (SKIP_DIRS & set(path.parts))


def _changed_functions(old: str, new: str) -> tuple[set[str], bool]:
    """Names of the functions and classes in ``new`` whose lines changed, and
    whether some changed lines sit outside any of them (imports, settings)."""
    lines = {
        number
        for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
            None, old.splitlines(), new.splitlines(), autojunk=False
        ).get_opcodes()
        if tag != "equal"
        for number in range(j1 + 1, max(j2, j1 + 1) + 1)
    }
    try:
        parsed = ast.parse(new)
    except SyntaxError:
        return set(), bool(lines)
    spans = [
        (node.name, node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(parsed)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    names = {
        name for name, start, end in spans if any(start <= n <= end for n in lines)
    }
    loose = any(not any(start <= n <= end for _, start, end in spans) for n in lines)
    return names, loose


@dataclass
class PickedTests:
    """The tests a check runs for a change, and what they don't cover."""

    files: list[str] = field(default_factory=list)
    found: int = 0
    uncovered: list[str] = field(default_factory=list)


def _names_module(text: str, dotted: str) -> bool:
    """Whether a test's text uses a module, however it imports it (dotted,
    "from pkg import mod", or a bracketed import over several lines)."""
    if re.search(rf"\b{re.escape(dotted)}\b", text):
        return True
    package, _, module = dotted.rpartition(".")
    if not package:
        return False
    for found in re.finditer(
        rf"from\s+free_claude_code\.{re.escape(package)}\s+import\s+"
        r"(\([^)]*\)|[^\n]*)",
        text,
    ):
        if re.search(rf"\b{re.escape(module)}\b", found.group(1)):
            return True
    return False


def pick_tests(
    target: Path, touched: Sequence[str], source: Path | None
) -> PickedTests:
    """The test files that cover a change (so a check runs in a minute, not
    the whole suite): changed tests first, then tests using a changed module,
    and for big shared files, tests naming a changed function. Content Farm's
    are left out. Changes nothing can be matched to are named, never hidden."""
    pick = PickedTests()
    folder = target / "tests"
    if not folder.is_dir():
        return pick
    tests = {
        relative: path
        for path in sorted(folder.rglob("test_*.py"))
        if not LEFT_OUT_TESTS.search(relative := path.relative_to(target).as_posix())
    }
    changed = [name for name in touched if name in tests]
    modules: set[str] = set()
    functions: set[str] = set()
    for name in touched:
        path = Path(name)
        if not name.startswith("src/") or path.suffix != ".py":
            continue
        if path.name in SHARED_FILES:
            old = _read_text(source / name) if source else ""
            names, loose = _changed_functions(old, _read_text(target / name))
            functions |= names
            if loose:
                pick.uncovered.append(f"{name} (changes outside a function)")
            if not names and not loose:
                pick.uncovered.append(name)
        else:
            modules.add(".".join(path.with_suffix("").parts[2:]))
    modules.discard("")
    others: list[str] = []
    for name, path in tests.items():
        if name in changed or not (modules or functions):
            continue
        text = _read_text(path)
        if any(_names_module(text, m) for m in modules) or any(
            re.search(rf"\b{re.escape(f)}\b", text) for f in functions
        ):
            others.append(name)
    every = [*changed, *others]
    pick.found = len(every)
    pick.files = every[:MAX_TEST_FILES]
    return pick


def related_tests(
    target: Path, touched: Sequence[str], source: Path | None
) -> list[str]:
    """The test files a check runs for a change (see pick_tests)."""
    return pick_tests(target, touched, source).files


def tree(root: Path) -> dict[str, Path]:
    """Every file of the copied parts under ``root``, by relative path."""
    files: dict[str, Path] = {}
    for item in COPY_ITEMS:
        start = root / item
        if start.is_file():
            files[item] = start
        elif start.is_dir():
            for path in sorted(start.rglob("*")):
                relative = path.relative_to(root)
                if path.is_file() and _wanted(relative):
                    files[relative.as_posix()] = path
    return files


def bump_version(text: str, *, minor: bool = False) -> tuple[str, str, str]:
    """pyproject text with the patch number (or, for an update project, the
    minor number) raised: (text, old, new)."""
    found = re.search(r'^version = "(\d+)\.(\d+)\.(\d+)"', text, re.MULTILINE)
    if not found:
        raise ChangerError("pyproject.toml has no version line.")
    major, middle, patch = found.groups()
    old = f"{major}.{middle}.{patch}"
    new = (
        f"{major}.{int(middle) + 1}.0"
        if minor
        else f"{major}.{middle}.{int(patch) + 1}"
    )
    return text[: found.start()] + f'version = "{new}"' + text[found.end() :], old, new


def bump_lock(text: str, old: str, new: str) -> str:
    """uv.lock with FCC's own entry moved to the new version."""
    return re.sub(
        r'(name = "free-claude-code"\nversion = )"' + re.escape(old) + '"',
        rf'\1"{new}"',
        text,
        count=1,
    )


@dataclass(slots=True)
class CheckReport:
    passed: bool = True
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def fail(self, problem: str) -> None:
        self.passed = False
        self.problems.append(problem)

    def view(self) -> JsonObject:
        return {
            "passed": self.passed,
            "lines": list(self.lines),
            "problems": list(self.problems),
        }

    def text(self) -> str:
        head = "All checks passed." if self.passed else "Checks found problems:"
        return "\n".join([head, *self.problems, *self.lines])


class Changer:
    """The copy, its checks, its screenshots, and the update zips."""

    def __init__(
        self,
        home: Path,
        *,
        source: Path | None,
        python: str = sys.executable,
        shooter: Shooter | None = None,
        import_check: str = IMPORT_CHECK,
        serve_copy: str = SERVE_COPY,
    ) -> None:
        self._import_check = import_check
        self._serve_copy = serve_copy
        self._home = home
        self._source = source
        self._python = python
        self._shooter = shooter

    @property
    def source(self) -> Path | None:
        return self._source

    @property
    def home(self) -> Path:
        return self._home

    @property
    def updates_dir(self) -> Path:
        return self._home / "updates"

    @property
    def shots_dir(self) -> Path:
        return self._home / "shots"

    @property
    def _baseline_path(self) -> Path:
        return self._home / "baseline.json"

    # ------------------------------------------------------------ the copy

    def make_copy(self, target: Path) -> int:
        """Fill ``target`` with a fresh copy of the app; returns the file count."""
        if self._source is None:
            raise ChangerError(
                "FCC isn't running from its own folder, so there is nothing to copy."
            )
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        files = tree(self._source)
        hashes: dict[str, str] = {}
        for relative, path in files.items():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            hashes[relative] = sha256(path)
        self._home.mkdir(parents=True, exist_ok=True)
        self._baseline_path.write_text(
            json.dumps({"made_at": int(time.time() * 1000), "files": hashes}),
            encoding="utf-8",
        )
        return len(files)

    def baseline(self) -> dict[str, str]:
        try:
            data = json.loads(self._baseline_path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return {}
        files = data.get("files") if isinstance(data, dict) else None
        return (
            {str(k): str(v) for k, v in files.items()}
            if isinstance(files, dict)
            else {}
        )

    def made_at(self) -> int:
        try:
            data = json.loads(self._baseline_path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return 0
        return int(data.get("made_at", 0)) if isinstance(data, dict) else 0

    def changes(self, target: Path) -> dict[str, list[str]]:
        """What the copy changed since it was made."""
        before = self.baseline()
        now = tree(target) if target.is_dir() else {}
        changed = [
            name
            for name, path in now.items()
            if name in before and sha256(path) != before[name]
        ]
        added = [name for name in now if name not in before]
        deleted = [name for name in before if name not in now]
        return {
            "changed": sorted(changed),
            "added": sorted(added),
            "deleted": sorted(deleted),
        }

    def diff(self, target: Path, relative: str) -> str:
        """A unified diff of one file: the running app's copy against the change."""
        if relative not in tree(target) and relative not in self.baseline():
            raise ChangerError(f"{relative} isn't part of the copy.")
        new = _read_text(target / relative)
        old = _read_text(self._source / relative) if self._source else ""
        lines = list(
            difflib.unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=f"app/{relative}",
                tofile=f"changed/{relative}",
                lineterm="",
            )
        )
        if len(lines) > MAX_DIFF_LINES:
            lines = [
                *lines[:MAX_DIFF_LINES],
                f"... {len(lines) - MAX_DIFF_LINES} more lines",
            ]
        return "\n".join(lines)

    # ------------------------------------------------------------ checks

    async def check(self, target: Path) -> CheckReport:
        """Syntax of every changed file, then the app importing from the copy."""
        report = CheckReport()
        changes = self.changes(target)
        touched = [*changes["changed"], *changes["added"]]
        if not touched and not changes["deleted"]:
            report.lines.append("Nothing has changed in the copy yet.")
        node = shutil.which("node")
        for relative in touched:
            path = target / relative
            suffix = path.suffix.lower()
            if suffix == ".py":
                try:
                    compile(_read_text(path), relative, "exec")
                except SyntaxError as error:
                    report.fail(f"{relative} line {error.lineno}: {error.msg}")
            elif suffix == ".json":
                try:
                    json.loads(_read_text(path))
                except ValueError as error:
                    report.fail(f"{relative}: not valid JSON ({error})")
            elif suffix in {".js", ".mjs"} and node:
                code, output = await self._run([node, "--check", str(path)], target)
                if code != 0:
                    report.fail(f"{relative}: {output.strip()[:400]}")
        if touched and not node and any(n.endswith((".js", ".mjs")) for n in touched):
            report.lines.append(
                "Node isn't installed, so script files weren't syntax-checked."
            )
        ruff = await self._run([self._python, "-m", "ruff", "--version"], target)
        python_files = [str(target / n) for n in touched if n.endswith(".py")]
        if ruff[0] == 0 and python_files:
            code, output = await self._run(
                [
                    self._python,
                    "-m",
                    "ruff",
                    "check",
                    "--select",
                    "F,E9",
                    *python_files,
                ],
                target,
            )
            if code != 0:
                report.fail(
                    "Lint (undefined names, unused imports):\n" + output.strip()[-2000:]
                )
            # Tidy the changed Python files the way FCC's own checks expect
            # (the copy only; a file that won't parse is reported above).
            code, output = await self._run(
                [self._python, "-m", "ruff", "format", *python_files], target
            )
            if code == 0 and "reformatted" in output:
                report.lines.append(f"Formatted: {output.strip()[:160]}")
        code, output = await self._run(
            [self._python, "-c", self._import_check], target, env=self._copy_env(target)
        )
        if code == 0:
            report.lines.append("The app loads from the copy.")
        else:
            report.fail(
                "The app doesn't load from the copy:\n" + output.strip()[-2500:]
            )
        pick = pick_tests(target, touched, self._source)
        picked = pick.files
        if picked and not importlib.util.find_spec("pytest"):
            report.lines.append(
                "pytest isn't installed here, so the related tests didn't run."
            )
        elif picked:
            # One process (no xdist workers), so a timeout leaves nothing behind.
            serial = ["-n", "0"] if importlib.util.find_spec("xdist") else []
            code, output = await self._run(
                [
                    self._python,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    *serial,
                    *picked,
                ],
                target,
                env=self._copy_env(target),
                timeout=TEST_SECONDS,
            )
            last = output.strip().splitlines()[-1:] or [""]
            count = (
                f"{len(picked)} of {pick.found} related test files"
                if pick.found > len(picked)
                else f"{len(picked)} related test files"
            )
            if code == 0:
                report.lines.append(f"Tests passed ({count}): {last[0][:120]}")
            else:
                report.fail(
                    f"Tests failed ({count}: {', '.join(picked)}):\n"
                    + output.strip()[-2500:]
                )
        elif (
            any(n.startswith("src/") and n.endswith(".py") for n in touched)
            and (target / "tests").is_dir()
        ):
            report.lines.append(
                "No test covers the changed code yet: add one under tests/ "
                "(tests/studio/test_<area>.py)."
            )
        if pick.uncovered:
            report.lines.append(
                "Not matched to a test: " + ", ".join(pick.uncovered[:6]) + "."
            )
        return report

    async def _run(
        self,
        command: Sequence[str],
        cwd: Path,
        *,
        env: dict[str, str] | None = None,
        timeout: float = CHECK_SECONDS,
    ) -> tuple[int, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as error:
            return 127, str(error)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            return 124, f"Timed out after {int(timeout)} seconds."
        return process.returncode or 0, output.decode("utf-8", "replace")

    def _copy_env(self, target: Path, home: Path | None = None) -> dict[str, str]:
        """The environment for running the copy: its own code first, and none
        of the owner's keys; with ``home``, an empty data folder too."""
        env = {
            name: value
            for name, value in os.environ.items()
            if not any(word in name.upper() for word in SECRET_WORDS)
        }
        env["PYTHONPATH"] = str(target / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if home is not None:
            env["HOME"] = str(home)
            env["USERPROFILE"] = str(home)
        return env

    # ------------------------------------------------------------ screenshots

    async def screenshots(
        self, target: Path, pages: Sequence[str] = SCREEN_PAGES, *, phone: bool = False
    ) -> JsonObject:
        """Run the copy on a spare port with an empty data folder and
        screenshot Studio pages; the pictures replace the last set."""
        if self._shooter is None:
            raise ChangerError(
                "Screenshots need Playwright's browser; it isn't installed here."
            )
        chosen = [page.strip().lstrip("#") for page in pages if page.strip()][:8]
        for page in chosen:
            if not PAGE_NAME.match(page):
                raise ChangerError(
                    f"{page!r} isn't a Studio page name (like lab or trade)."
                )
        if not chosen:
            chosen = list(SCREEN_PAGES)
        port = _free_port()
        home = Path(tempfile.mkdtemp(prefix="fcc-changer-"))
        env = self._copy_env(target, home)
        env.update(
            {
                "HOST": "127.0.0.1",
                "PORT": str(port),
                "FCC_OPEN_BROWSER": "false",
            }
        )
        log = home / "server.log"
        with log.open("wb") as sink:
            process = await asyncio.create_subprocess_exec(
                self._python,
                "-c",
                self._serve_copy,
                cwd=str(target),
                env=env,
                stdout=sink,
                stderr=asyncio.subprocess.STDOUT,
            )
        base = f"http://127.0.0.1:{port}"
        try:
            if not await _wait_until_up(f"{base}/studio", process):
                tail = _read_text(log)[-2500:]
                raise ChangerError(
                    "The changed copy didn't start, so there's nothing to screenshot:\n"
                    + tail
                )
            if self.shots_dir.exists():
                shutil.rmtree(self.shots_dir)
            size = (390, 844) if phone else (1440, 900)
            named = [
                (page.replace("/", "-"), f"{base}/studio#{page}") for page in chosen
            ]
            taken, problems = await self._shooter(named, self.shots_dir, size=size)
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 15)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            shutil.rmtree(home, ignore_errors=True)
        return {
            "shots": [path.name for path in taken],
            "problems": problems,
            "phone": phone,
        }

    def shots(self) -> list[str]:
        if not self.shots_dir.is_dir():
            return []
        return sorted(path.name for path in self.shots_dir.glob("*.png"))

    def shot(self, name: str) -> Path:
        path = self.shots_dir / name
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.png", name) or not path.is_file():
            raise ChangerError("No such screenshot.")
        return path

    # ------------------------------------------------------------ update zips

    def package(
        self,
        target: Path,
        note: str,
        *,
        minor: bool = False,
        report: str = "",
        manifest: JsonObject | None = None,
    ) -> JsonObject:
        """Pack the changes into an update zip and a rollback zip.

        The update unzips straight over the fcc folder; its paperwork
        (changelog, instructions, manifest, checksums, test report) sits in
        fcc/_update/<version>/. The copy's version goes up (patch, or minor
        for an update project) so the PC and phone load the new pages."""
        changes = self.changes(target)
        if not changes["changed"] and not changes["added"] and not changes["deleted"]:
            raise ChangerError(
                "Nothing has changed in the copy, so there's nothing to pack."
            )
        pyproject = target / "pyproject.toml"
        lock = target / "uv.lock"
        text, old, new = bump_version(_read_text(pyproject), minor=minor)
        pyproject.write_text(text, encoding="utf-8")
        if lock.is_file():
            lock.write_text(bump_lock(_read_text(lock), old, new), encoding="utf-8")
        changes = self.changes(target)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"FCC-Studio-update-{new}-{stamp}"
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        update = self.updates_dir / f"{name}.zip"
        rollback = self.updates_dir / f"{name}-rollback.zip"
        carried = [*changes["changed"], *changes["added"]]
        papers = f"{UPDATE_PREFIX}_update/{new}/"
        sums = "".join(
            f"{sha256(target / relative)}  {relative}\n" for relative in carried
        )
        record: JsonObject = {
            "name": name,
            "from": old,
            "to": new,
            "kind": "project" if minor else "quick",
            "made_by": "the Changer",
            "made_at": stamp,
            "changed": list(changes["changed"]),
            "added": list(changes["added"]),
            "deleted": list(changes["deleted"]),
            **(manifest or {}),
        }
        with zipfile.ZipFile(update, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative in carried:
                archive.write(target / relative, UPDATE_PREFIX + relative)
            archive.writestr(
                papers + "CHANGELOG.md", _changelog(old, new, note, changes)
            )
            archive.writestr(
                papers + "UPDATE_INSTRUCTIONS.md", _instructions(name, changes)
            )
            archive.writestr(papers + "MANIFEST.json", json.dumps(record, indent=2))
            archive.writestr(papers + "SHA256SUMS.txt", sums)
            archive.writestr(
                papers + "TEST-REPORT.md",
                report.strip() or "# Test report\n\nNo checks were recorded.\n",
            )
        with zipfile.ZipFile(rollback, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative in [*changes["changed"], *changes["deleted"]]:
                original = self._source / relative if self._source else None
                if original is not None and original.is_file():
                    archive.write(original, UPDATE_PREFIX + relative)
            archive.writestr(
                UPDATE_PREFIX + "FCC-UNDO.txt",
                f"Rollback for {name}. To undo the update, close FCC, unzip this "
                "over the same folder (choose Replace), then delete these files "
                "the update added:\n" + "\n".join(changes["added"] or ["(none)"]),
            )
        self._prune()
        return {
            "name": update.name,
            "backup": rollback.name,
            "version": new,
            "changes": {key: list(value) for key, value in changes.items()},
            "note": _changelog(old, new, note, changes),
        }

    def _zips(self) -> list[Path]:
        if not self.updates_dir.is_dir():
            return []
        return sorted(
            (
                path
                for path in self.updates_dir.glob("FCC-*.zip")
                if not path.stem.endswith(("-backup", "-rollback"))
            ),
            key=lambda path: path.stat().st_mtime,
        )

    def _undo_of(self, path: Path) -> Path:
        rollback = path.with_name(path.stem + "-rollback.zip")
        return (
            rollback if rollback.exists() else path.with_name(path.stem + "-backup.zip")
        )

    def _prune(self) -> None:
        for old in self._zips()[:-MAX_UPDATES]:
            self._undo_of(old).unlink(missing_ok=True)
            old.unlink(missing_ok=True)

    def updates(self) -> list[JsonObject]:
        return [
            {
                "name": path.name,
                "backup": self._undo_of(path).name,
                "size": path.stat().st_size,
                "at": int(path.stat().st_mtime * 1000),
            }
            for path in reversed(self._zips())
        ]

    def update_file(self, name: str) -> Path:
        path = self.updates_dir / name
        if (
            not re.fullmatch(
                r"FCC-(?:Update|Studio-update)-[0-9.]+-[0-9-]+(?:-backup|-rollback)?\.zip",
                name,
            )
            or not path.is_file()
        ):
            raise ChangerError("No such update zip.")
        return path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def _block(title: str, items: list[str]) -> str:
    return f"## {title}\n\n" + ("\n".join(f"- {item}" for item in items) or "- (none)")


def _changelog(old: str, new: str, note: str, changes: dict[str, list[str]]) -> str:
    return (
        "\n\n".join(
            [
                f"# FCC {old} -> {new}",
                note.strip() or "(no note)",
                _block("Changed", changes["changed"]),
                _block("Added", changes["added"]),
                _block("Removed", changes["deleted"]),
            ]
        )
        + "\n"
    )


def _instructions(name: str, changes: dict[str, list[str]]) -> str:
    return (
        "\n\n".join(
            [
                f"# Installing {name}",
                "1. Close FCC.\n2. Unzip this into the folder that holds your fcc "
                "folder (the same place you unzipped FCC) and choose Replace.\n3. "
                "Delete the files listed under Remove by hand, if any.\n4. Start FCC.",
                _block("Remove by hand (unzipping can't delete)", changes["deleted"]),
                "## Undo\n\nClose FCC, unzip the matching -rollback.zip the same way "
                "(Replace), delete the files it lists, and start FCC.",
            ]
        )
        + "\n"
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _wait_until_up(url: str, process: asyncio.subprocess.Process) -> bool:
    deadline = time.monotonic() + SERVER_WAIT_SECONDS
    async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.returncode is not None:
                return False
            try:
                response = await client.get(url)
                if response.status_code < 500:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)
    logger.warning("The Changer's copy didn't answer within {}s", SERVER_WAIT_SECONDS)
    return False
