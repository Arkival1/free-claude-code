"""Update projects for the Changer: plans, milestones, checkpoints, the
security scan, and the goals each agent is given.

The service drives a project through its steps (plan → approve → each
milestone: build, check, review, screenshots → release); this module holds
the parts that are plain logic, so they can be tested on their own.
"""

import json
import re
import shutil
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from free_claude_code.core.json_types import JsonObject, JsonValue

from .changer import ChangerError, sha256, tree
from .limits import daily_limit

SIZES = ("quick", "project")
KINDS = (
    "feature",
    "bug fix",
    "security issue",
    "performance issue",
    "workflow improvement",
    "UI improvement",
    "integration",
    "refactor",
    "new product area",
)
MAX_MILESTONES = 12
MAX_SUGGESTIONS = 3
MAX_FIX_ROUNDS = 2
MAX_HELPERS = 2
QUICK_BUDGET = 400_000
PROJECT_BUDGET = 2_000_000
ACTIVE = frozenset({"planning", "building"})
WAITING = frozenset({"choose", "awaiting_plan", "awaiting_release", "paused"})
FINISHED = frozenset({"done", "cancelled", "failed"})
PROTECTED = (
    re.compile(r"(^|/)studio/trading/"),
    re.compile(r"(^|/)studio/farm/"),
    re.compile(r"(^|/)api/studio_static/farm\.(js|css)$"),
    re.compile(r"keyvault|vault\.py$|connectors\.py$|admin_security"),
    re.compile(r"(^|/)config/"),
)
"""Files whose changes always wait for the owner: the Trading Bank, Content
Farm, keys and vaults, connectors, admin security, settings."""
_PATH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


class PlanError(ValueError):
    """A plan the planner submitted that can't be used as it is."""


def _strings(raw: object, limit: int = 40) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()][:limit]


def clean_paths(raw: object) -> list[str]:
    """File paths inside the copy, tidied; anything else is refused."""
    paths = []
    for item in _strings(raw, 60):
        path = item.replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        parts = path.split("/")
        if (
            not _PATH.match(path)
            or path.startswith("/")
            or ".." in parts
            or parts[-1] in {"", "."}
        ):
            raise PlanError(f"{item!r} isn't a file path inside the copy.")
        paths.append(path)
    return paths


def read_plan(raw: Mapping[str, object]) -> JsonObject:
    """A planner's plan, checked: size, kind, summary, spec, risks, files,
    tests, milestones (1 for a quick change), or up to three suggestions for a
    vague request."""
    raw_suggestions = raw.get("suggestions")
    suggestions: list[JsonValue] = [
        {
            key: str(item.get(key, "")).strip()[:400]
            for key in ("title", "why", "value", "effort", "risk")
        }
        for item in (
            raw_suggestions[:MAX_SUGGESTIONS]
            if isinstance(raw_suggestions, list)
            else []
        )
        if isinstance(item, Mapping) and str(item.get("title", "")).strip()
    ]
    milestones: list[JsonValue] = []
    raw_milestones = raw.get("milestones")
    if isinstance(raw_milestones, list):
        for number, item in enumerate(raw_milestones[:MAX_MILESTONES], start=1):
            if not isinstance(item, Mapping):
                continue
            title = str(item.get("title", "")).strip()[:160]
            goal = str(item.get("goal", "")).strip()[:3000]
            if not title or not goal:
                raise PlanError(f"Milestone {number} needs a title and a goal.")
            milestones.append(
                {
                    "title": title,
                    "goal": goal,
                    "files": clean_paths(item.get("files")),
                    "tests": _strings(item.get("tests")),
                    "status": "waiting",
                    "review": "",
                    "checkpoint": "",
                    "fixes": 0,
                }
            )
    if not milestones and not suggestions:
        raise PlanError(
            "Give milestones to build, or up to three suggestions for a vague request."
        )
    size = str(raw.get("size", "")).strip().casefold()
    if size not in SIZES:
        size = "quick" if len(milestones) <= 1 else "project"
    if size == "quick" and len(milestones) > 1:
        size = "project"
    kind = str(raw.get("kind", "")).strip()
    return {
        "size": size,
        "kind": kind if kind in KINDS else "feature",
        "summary": str(raw.get("summary", "")).strip()[:1500],
        "spec": str(raw.get("spec", "")).strip()[:6000],
        "risks": _strings(raw.get("risks")),
        "files": clean_paths(raw.get("files")),
        "tests": _strings(raw.get("tests")),
        "milestones": milestones,
        "suggestions": suggestions if not milestones else [],
    }


def protected_files(plan: Mapping[str, object]) -> list[str]:
    """Planned files that always need the owner's approval."""
    top = plan.get("files")
    files: list[str] = [str(f) for f in top] if isinstance(top, list) else []
    milestones = plan.get("milestones")
    if isinstance(milestones, list):
        for item in milestones:
            if isinstance(item, Mapping):
                raw = item.get("files")
                if isinstance(raw, list):
                    files.extend(str(f) for f in raw)
    return sorted({f for f in files if any(p.search(f) for p in PROTECTED)})


def needs_approval(plan: Mapping[str, object]) -> bool:
    """A quick change touching nothing protected goes ahead; everything else
    waits for the owner."""
    return plan.get("size") != "quick" or bool(protected_files(plan))


def overlapping(owned: Sequence[Sequence[str]], files: Sequence[str]) -> list[str]:
    """Files a new helper would share with helpers already at work."""
    taken = {f for group in owned for f in group}
    return sorted(taken & set(files))


# ------------------------------------------------------------ checkpoints


class Checkpoints:
    """Snapshots of the copy, so Undo puts it back exactly.

    A checkpoint keeps every file that differs from the copy as first made
    (and the full list of files then), so restoring it brings back changed
    files, removes files added since, and returns the rest to the app's own
    versions.
    """

    def __init__(self, home: Path, *, source: Path | None) -> None:
        self._home = home
        self._source = source

    def save(self, target: Path, baseline: Mapping[str, str], label: str) -> JsonObject:
        stamp = int(time.time() * 1000)
        while (self._home / f"cp{stamp}").exists():
            stamp += 1  # two saves in the same millisecond get their own ids
        point = f"cp{stamp}"
        folder = self._home / point
        folder.mkdir(parents=True)
        files = tree(target)
        changed = {
            name: path
            for name, path in files.items()
            if baseline.get(name) != sha256(path)
        }
        for name, path in changed.items():
            destination = folder / "files" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.json").write_text(
            json.dumps({"files": sorted(files), "changed": sorted(changed)}),
            encoding="utf-8",
        )
        return {"id": point, "label": label, "at": int(time.time() * 1000)}

    def restore(self, target: Path, point: str) -> int:
        """Put the copy back as it was at a checkpoint; returns files touched."""
        if not re.fullmatch(r"cp\d+", point):
            raise ChangerError("That isn't a checkpoint.")
        folder = self._home / point
        try:
            index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
        except OSError, ValueError:
            raise ChangerError("That checkpoint is gone.") from None
        keep = set(index.get("files", []))
        changed = set(index.get("changed", []))
        touched = 0
        for name, path in tree(target).items():
            if name not in keep:
                path.unlink()
                touched += 1
        for name in keep:
            saved = folder / "files" / name
            original = (
                saved
                if name in changed
                else (self._source / name if self._source else None)
            )
            if original is None or not original.is_file():
                continue
            destination = target / name
            if destination.is_file() and sha256(destination) == sha256(original):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
            touched += 1
        return touched


# ------------------------------------------------------------ security scan

_SCANS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "a key or token written into the code",
        re.compile(
            r"(nvapi-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{20,}"
            r"|AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
        ),
    ),
    ("code run from text (eval/exec)", re.compile(r"\b(eval|exec)\s*\(")),
    (
        "a shell command built from text",
        re.compile(r"shell\s*=\s*True|os\.system\s*\(|os\.popen\s*\("),
    ),
    ("certificate checks turned off", re.compile(r"verify\s*=\s*False")),
    (
        "unsafe loading of data (pickle/yaml)",
        re.compile(r"pickle\.loads?\(|yaml\.load\("),
    ),
    ("a path that climbs out of its folder", re.compile(r"""["'][^"'\n]*\.\./""")),
    ("page code inserted as HTML", re.compile(r"\.innerHTML\s*=|insertAdjacentHTML")),
    (
        "a check switched off",
        re.compile(r"#\s*(type:\s*ignore|noqa)|(?i:skip.*(check|safety|guard))"),
    ),
)
_URL = re.compile(r"https?://([A-Za-z0-9.-]+)")
_CODE = frozenset(
    {".py", ".js", ".ts", ".html", ".ps1", ".sh", ".cmd", ".bat", ".json", ".toml"}
)
"""Code gets every check; any other file only the key check (a key in a
note, a settings file or a picture would still ship in the zip)."""


def scan(
    target: Path,
    files: Sequence[str],
    *,
    known_hosts: frozenset[str] = frozenset(),
    source: Path | None = None,
) -> list[str]:
    """Risky things a change added, file by file: only lines that are new
    compared with the running app count, so old code doesn't block a release."""
    hits: list[str] = []
    for name in files:
        path = target / name
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        # Code gets every check, whatever bytes it holds; any other file
        # (text or binary) still gets the key check, so no file can carry a
        # key into the zip unseen.
        code = path.suffix.lower() in _CODE
        new_lines = data.decode("utf-8", errors="replace").splitlines()
        old: set[str] = set()
        if source is not None and (source / name).is_file():
            try:
                old = set((source / name).read_text(encoding="utf-8").splitlines())
            except OSError, UnicodeDecodeError:
                old = set()
        for number, line in enumerate(new_lines, start=1):
            if line in old:
                continue
            for label, pattern in _SCANS if code else _SCANS[:1]:
                if pattern.search(line):
                    hits.append(f"{name} line {number}: {label}")
            for host in _URL.findall(line) if code else ():
                base = ".".join(host.casefold().split(".")[-2:])
                if base not in known_hosts and host.casefold() not in known_hosts:
                    hits.append(f"{name} line {number}: a new web address ({host})")
    return hits[:80]


def known_hosts(source: Path | None) -> frozenset[str]:
    """Web hosts the app already talks to (so only new ones are flagged)."""
    hosts: set[str] = {"localhost", "127.0.0.1", "example.com", "github.com"}
    if source is None:
        return frozenset(hosts)
    for path in (source / "src").rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        for host in _URL.findall(text):
            hosts.add(host.casefold())
            hosts.add(".".join(host.casefold().split(".")[-2:]))
    return frozenset(hosts)


# ------------------------------------------------------------ goals


def plan_goal(request: str, feedback: str = "") -> str:
    lines = [
        "PLAN an update to FCC (don't change any files yet).",
        f"The owner's request: {request}",
    ]
    if feedback.strip():
        lines.append(f"The owner's notes on the last plan: {feedback.strip()}")
    lines.append(
        "Read CLAUDE.md and .claude/skills/fcc-studio/SKILL.md, then search and "
        "read only the files this touches. Then call fcc_changer with action "
        "plan and: size (quick for one or two files with no safety code, else "
        "project), kind, summary, spec (for a new area: what, for whom, out of "
        "scope, acceptance criteria), risks, files, tests, and milestones (each "
        "a working, testable slice: title, goal, files it owns, tests). A quick "
        "change has one milestone. If the request is vague, give up to three "
        "suggestions instead (title, why, value, effort, risk) and no "
        "milestones. Then finish. Be quick: search for the exact words or "
        "symbols, read only those lines, and hand in the plan within about 15 "
        "steps. Tests are in tests/ (tests/studio/test_<area>.py)."
    )
    return "\n".join(lines)


def build_goal(project: Mapping[str, object], number: int) -> str:
    plan = project.get("plan") or {}
    assert isinstance(plan, Mapping)
    milestones = plan.get("milestones") or []
    assert isinstance(milestones, list)
    milestone = milestones[number]
    assert isinstance(milestone, Mapping)
    files = milestone.get("files") or []
    return "\n".join(
        [
            f"BUILD milestone {number + 1} of {len(milestones)} of an update to FCC.",
            f"The owner's request: {project.get('request', '')}",
            f"Plan: {plan.get('summary', '')}",
            *([f"Spec: {plan['spec']}"] if plan.get("spec") else []),
            f"This milestone: {milestone.get('title', '')}: {milestone.get('goal', '')}",
            f"Files it owns: {', '.join(str(f) for f in files) if isinstance(files, list) and files else 'as needed'}",
            f"Tests: {', '.join(str(t) for t in milestone.get('tests') or []) or 'add tests for the changed behaviour'} "
            "(add or change a test under tests/; fcc_changer check runs the tests "
            "related to your change).",
            "Build only this milestone, in small steps, matching the code around "
            "it. Run fcc_changer check and fix every problem. For a separate "
            "part, use fcc_changer subagent with the task and the files it owns "
            "(optionally agent: a team member's name). Don't package; finish "
            "with what you changed, the checks, and anything left.",
        ]
    )


def fix_goal(project: Mapping[str, object], number: int, problems: str) -> str:
    return "\n".join(
        [
            f"FIX milestone {number + 1} of an update to FCC.",
            f"The owner's request: {project.get('request', '')}",
            f"Problems found: {problems[:4000]}",
            "Reproduce each problem, find the cause, fix it, add a test that "
            "would have caught it, and run fcc_changer check until it passes. "
            "Finish with what you fixed.",
        ]
    )


def review_goal(
    project: Mapping[str, object], number: int, diff: str, *, security: bool
) -> str:
    focus = (
        "SECURITY review: exposed secrets, unsafe file access and path "
        "traversal, command injection, code execution, unsafe dependencies, "
        "missing authentication or broken authorisation, unsafe network "
        "requests, secrets in logs, prompt injection, weakened Trading Bank "
        "checks (the owner's no-downgrade rule)."
        if security
        else "CODE review: confirmed bugs and regressions, missing tests, "
        "front end / back end / database agreement, state and step order, "
        "retries and interrupted work, and whether it does what was asked."
    )
    return "\n".join(
        [
            f"REVIEW milestone {number + 1} of an update to FCC. You did not "
            "write it; don't edit any files.",
            f"The owner's request: {project.get('request', '')}",
            focus,
            "The change (diff, cut short if long):",
            diff[:24000],
            "Read the files you need, then call fcc_changer with action review: "
            "verdict pass or fail, and findings (each: problem, where, evidence, "
            "fix). Only confirmed problems fail it. Then finish.",
        ]
    )


def limit_note(text: str, model: str) -> str:
    """A plain note when a used-up daily allowance stopped the work ('' when
    the text isn't about one): what happened and what the owner can do."""
    if not daily_limit(text):
        return ""
    return (
        f"The model {model or 'in use'} has used up its provider's allowance "
        "for now (free keys can allow as little as 20 requests a day per "
        "model, and one Changer job needs roughly 30-80). The work so far is "
        "saved. Wait for the allowance to reset, pick another model for the "
        "Changer team on the Agents page, or use a key with more allowance, "
        "then press Resume."
    )


_FOUND_PATH = re.compile(r"\b((?:src|tests|scripts)/[A-Za-z0-9_./-]+\.\w+)")


def plan_from_findings(request: str, findings: str, target: Path) -> JsonObject | None:
    """A one-milestone plan made from findings a Planner wrote as text but
    never handed in (None when there is nothing to build on). It always
    waits for the owner's approval."""
    text = findings.strip()
    if len(text) < 80:
        return None
    files: list[str] = []
    for found in _FOUND_PATH.findall(text):
        try:
            path = clean_paths([found])[0]
        except PlanError:
            continue  # "..", absolute or odd paths never reach the plan
        if path not in files and (target / path).is_file():
            files.append(path)
    files = sorted(files)[:8]
    try:
        plan = read_plan(
            {
                "size": "project",
                "kind": "bug fix"
                if re.search(r"\bbug|fix|broken|error", request, re.I)
                else "feature",
                "summary": f"Made from the Planner's findings (it didn't hand in a plan): {request}"[
                    :1500
                ],
                "files": files,
                "milestones": [
                    {
                        "title": "Act on the Planner's findings",
                        "goal": f"The owner's request: {request}\n\nThe Planner found:\n{text}"[
                            :3000
                        ],
                        "files": files,
                    }
                ],
            }
        )
    except PlanError:
        return None
    return {**plan, "approved": False, "from_findings": True}


def hand_in_goal(goal: str, wanted: str, notes: str) -> str:
    """A follow-up for a Planner or reviewer that wrote its findings as text
    instead of handing them in."""
    what = "plan" if wanted == "plan" else "review (verdict pass or fail, findings)"
    return (
        f"HAND IN: you finished without calling fcc_changer with action "
        f"{wanted}. Call it now with your {what}, using what you already found "
        "(don't start over), then finish.\n\nWhat you found:\n"
        f"{notes.strip()[:3000]}\n\nThe job was:\n{goal}"
    )


def estimate_tokens(texts: Sequence[str]) -> int:
    """A rough token count of what an agent read and wrote (about 4
    characters a token); shown as an estimate, never as a bill."""
    return sum(len(text) for text in texts) // 4
