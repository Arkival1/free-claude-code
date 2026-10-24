"""The bug-fix library: 490 real bugs, the fix each project merged, and the
test that proves it, from SWE-bench Verified (MIT).

The bugs come from 11 Python projects (Django, sympy, Sphinx, matplotlib,
scikit-learn, astropy, xarray, pytest, requests, seaborn, Flask); each fix
and test keeps its project's own licence (BSD, MIT, Apache, Matplotlib),
recorded with the data. Pylint's are left out (GPL). See `vendor/swe-bench/`.
"""

import gzip
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "bugs.json.gz"
MAX_RESULTS = 12
MAX_TEXT = 6000
"""Longest issue, fix or test the tool shows in one go."""


class BugLibraryError(ValueError):
    """A search or bug the library can't give; the message says why."""


@dataclass(frozen=True, slots=True)
class Bug:
    id: str
    repo: str
    commit: str
    size: str
    issue: str
    hints: str
    fix: str
    test: str
    fails: tuple[str, ...]

    @property
    def title(self) -> str:
        return next(
            (line.strip() for line in self.issue.splitlines() if line.strip()), ""
        )

    @property
    def files(self) -> tuple[str, ...]:
        """The files the fix changed."""
        return tuple(re.findall(r"^\+\+\+ b/(\S+)", self.fix, re.M))


@cache
def _data() -> tuple[dict[str, str], tuple[Bug, ...]]:
    payload = json.loads(gzip.decompress(DATA.read_bytes()))
    bugs = tuple(
        Bug(
            id=str(row["id"]),
            repo=str(row["repo"]),
            commit=str(row["commit"]),
            size=str(row["size"]),
            issue=str(row["issue"]),
            hints=str(row["hints"]),
            fix=str(row["fix"]),
            test=str(row["test"]),
            fails=tuple(str(name) for name in row["fails"]),
        )
        for row in payload["bugs"]
    )
    return payload["licences"], bugs


def bugs() -> tuple[Bug, ...]:
    return _data()[1]


def licence_of(repo: str) -> str:
    return _data()[0].get(repo, "")


def projects() -> list[str]:
    return sorted({bug.repo for bug in bugs()})


def _words(text: str) -> list[str]:
    return [
        word for word in re.findall(r"[a-z0-9_]+", text.casefold()) if len(word) > 1
    ]


def find(query: str, *, repo: str = "", count: int = 8) -> list[Bug]:
    """Bugs like the one described: words in the title count most, then the
    issue, then the files and code the fix touched."""
    words = _words(query)
    if not words:
        raise BugLibraryError(
            "Describe the bug in a few words, e.g. 'timezone lost when saving'."
        )
    wanted = repo.strip().casefold()
    scored: list[tuple[int, str, Bug]] = []
    for bug in bugs():
        if wanted and wanted not in bug.repo.casefold():
            continue
        title = bug.title.casefold()
        issue = bug.issue.casefold()
        code = f"{' '.join(bug.files)} {bug.fix}".casefold()
        score = 0
        for word in words:
            if word in title:
                score += 4
            elif word in issue:
                score += 2
            elif word in code:
                score += 1
        if score >= max(2, len(words)):
            scored.append((-score, bug.id, bug))
    scored.sort(key=lambda row: row[:2])
    return [row[2] for row in scored[: max(1, min(MAX_RESULTS, count))]]


def bug(bug_id: object) -> Bug:
    wanted = str(bug_id or "").strip()
    for item in bugs():
        if item.id == wanted:
            return item
    raise BugLibraryError(f"No bug called {bug_id!r}. Use an id from action find.")


def clip(text: str, limit: int = MAX_TEXT) -> str:
    return (
        text
        if len(text) <= limit
        else f"{text[:limit]}\n... ({len(text) - limit} more characters)"
    )
