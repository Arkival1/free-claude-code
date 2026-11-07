"""Print the pytest command for the tests a change touches.

Looks at the files changed against a base (default: HEAD, plus uncommitted
changes), then picks:
- changed test files themselves;
- tests that name a changed module (e.g. ``studio.changer_projects``);
- for big shared files (service.py, store.py, models.py, routes), tests that
  name a function the diff touched;
- e2e tests for a changed page script (``studio_static/<page>.js``).
Content Farm tests are always left out (owner's rule).

Usage: python3 .claude/skills/fcc-engineer/scripts/related_tests.py [base]
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SHARED = {"service.py", "store.py", "models.py", "studio_routes.py", "tools.py"}
LEFT_OUT = re.compile(r"content_farm|cartoon_paint")
TEST_DIRS = ("tests", "e2e")
MAX_NAMES = 25


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


def changed_files(base: str) -> list[str]:
    names = set(git("diff", "--name-only", base).split())
    names |= set(git("ls-files", "--others", "--exclude-standard").split())
    return sorted(names)


def touched_names(base: str, path: str) -> set[str]:
    """Functions the diff of a shared file touched (hunk headers and defs)."""
    names: set[str] = set()
    for line in git("diff", "-U0", base, "--", path).splitlines():
        found = re.search(r"def (\w+)", line)
        if found and (line.startswith("@@") or line[:1] in "+-"):
            names.add(found.group(1))
    return {n for n in names if len(n) > 4 and n not in {"__init__", "build"}}


def test_files() -> dict[str, str]:
    files = {}
    for folder in TEST_DIRS:
        for path in (ROOT / folder).rglob("test_*.py"):
            relative = path.relative_to(ROOT).as_posix()
            if not LEFT_OUT.search(relative):
                files[relative] = path.read_text(encoding="utf-8", errors="replace")
    return files


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    changed = changed_files(base)
    tests = test_files()
    picked: set[str] = {c for c in changed if c in tests}
    words: set[str] = set()
    for name in changed:
        path = Path(name)
        if not name.startswith("src/"):
            continue
        if path.suffix == ".py":
            if path.name in SHARED:
                words |= set(sorted(touched_names(base, name))[:MAX_NAMES])
            else:
                module = ".".join(path.with_suffix("").parts[2:])
                words.add(module)
        elif path.suffix in {".js", ".css"} and "static" in name:
            words.add(path.stem)
            picked |= {t for t in tests if t == f"e2e/test_{path.stem}_page.py"}
    for test, text in tests.items():
        if any(word in text for word in words):
            picked.add(test)
    unit = sorted(t for t in picked if t.startswith("tests/"))
    browser = sorted(t for t in picked if t.startswith("e2e/"))
    if not unit and not browser:
        print("No related tests found; run the area's tests by hand.")
        return
    if unit:
        print("uv run pytest -q " + " ".join(unit))
    if browser:
        print("uv run pytest -q " + " ".join(browser) + "   # browser, run apart")


if __name__ == "__main__":
    main()
