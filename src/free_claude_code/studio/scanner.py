"""The bug scanner: looks for things in FCC that are broken or not working,
in a different way each round, and keeps what it finds for the owner.

It only reads. It calls FCC's own GET routes (never a POST or DELETE), loads
pages in a hidden browser, reads the server log, checks the records for
broken links, and checks FCC's own files. Each round picks the next way of
scanning and a fresh random sample, so an endless scan keeps finding new
corners. A finding is kept once (by its fingerprint) and counted each time
it comes back; the owner decides what to send to the Changer.

Content Farm is left out (the owner's rule), and so is anything that would
download, sync, stream, or reach a broker.
"""

import asyncio
import contextlib
import hashlib
import json
import random
import re
import shutil
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from loguru import logger

from free_claude_code.core.json_types import JsonObject

from .models import (
    Agent,
    Chat,
    Course,
    LoraJob,
    ScanFinding,
    SiteProject,
    TuneJob,
    now_ms,
)
from .store import StudioStore

MODES = ("routes", "records", "odd_inputs", "pages", "logs", "data", "files")
"""The ways of scanning, in the order an endless scan takes them."""
MODE_NOTES = {
    "routes": "Calls FCC's read-only routes and looks for crashes and slow answers.",
    "records": "Calls each page's routes with real and missing ids.",
    "odd_inputs": "Sends odd values (empty, huge, emoji, negative) to read-only routes.",
    "pages": "Opens Studio's pages in a hidden browser and catches script errors.",
    "logs": "Reads the server log for errors and crashes.",
    "data": "Checks the saved records for broken links and stuck jobs.",
    "files": "Checks FCC's own files: code that won't load, data that won't read, libraries that changed.",
}
SKIP_WORDS = (
    "farm",
    "download",
    "export",
    "sync",
    "refresh",
    "stream",
    "events",
    "live",
    "watch",
    "worker",
    "oauth",
    "login",
    "callback",
    "broker",
    "quote",
    "notebook",
    "files/",
    "voice",
    "audio",
    "photo",
    "image",
    "video",
    "screenshot",
    "search",
    "fetch",
    "probe",
    "environment",
    "archive",
)
"""Routes the scanner never calls: Content Farm, and anything that downloads,
syncs, streams, reaches the internet or a broker, or serves big files."""
SKIP_PREFIXES = (
    "/studio/api/models",
    "/studio/api/team-models",
    "/studio/api/engine",
    "/studio/api/trading",
    "/studio/api/trade",
    "/studio/api/desk",
    "/studio/api/ops",
    "/studio/api/phone",
    "/studio/api/starters",
    "/studio/api/connectors",
    "/studio/api/mcp",
    "/studio/api/repos",
    "/studio/api/github",
    "/studio/api/providers",
    "/studio/api/lora/environment",
    "/studio/api/lab/chat",
    "/studio/api/tutor",
    "/studio/api/connect",
    "/studio/api/extensions",
    "/studio/api/claw",
    "/studio/api/subagents",
    "/studio/api/relay",
    "/studio/api/commands",
    "/studio/api/changer",
)
"""Whole areas left out: they reach LM Studio or Ollama, the model providers,
the trading desk or its brokers, connected services, or the phone."""
ODD_VALUES = (
    "",
    " ",
    "0",
    "-1",
    "99999999999",
    "x" * 5000,
    "😀🎮",
    "../..",
    "null",
    "%00",
)
MAX_CALLS = 60
MAX_BODY = 5_000_000
"""The probe reads at most this much of an answer; longer ones aren't judged as JSON."""
CALL_SECONDS = 15.0
SLOW_SECONDS = 5.0
LOG_TAIL_BYTES = 2_000_000
STUCK_MS = 2 * 60 * 60 * 1000
MAX_FINDINGS = 500
PAGES = (
    "home", "hq", "agents", "ideas", "chats", "lab", "trade", "ops", "learn",
    "tutor", "changer", "models", "engine", "tune", "connectors", "more",
)  # fmt: skip
"""Studio's pages by their address, Content Farm left out."""

type Get = Callable[[str], Awaitable[tuple[int, str, float]]]
"""Calls one GET path on FCC and returns (status, body, seconds)."""
type PageCheck = Callable[[str, bool], Awaitable[list[str]]]
"""Opens one Studio page (phone size or not) and returns its problems."""


class ScanError(ValueError):
    """A scan FCC can't start; the message says why."""


@dataclass(frozen=True, slots=True)
class Route:
    path: str
    query: tuple[str, ...] = ()


@dataclass(slots=True)
class Probe:
    """What a scan reaches FCC through (built by the HTTP layer)."""

    get: Get
    routes: Sequence[Route]
    page: PageCheck | None = None
    log_path: Path | None = None
    package: Path | None = None
    vendor: Path | None = None


type Severity = Literal["high", "medium", "low"]


@dataclass(slots=True)
class Found:
    mode: str
    severity: Severity
    title: str
    detail: str
    where: str

    @property
    def key(self) -> str:
        normal = re.sub(r"\d+", "#", f"{self.mode}|{self.where}|{self.title}")
        return hashlib.sha1(normal.encode()).hexdigest()[:16]


@dataclass(slots=True)
class ScanState:
    running: bool = False
    endless: bool = False
    rounds: int = 0
    mode: str = ""
    last_round_at: int = 0
    last_new: int = 0
    interval_s: int = 600
    message: str = ""
    history: list[JsonObject] = field(default_factory=list)


def skipped(path: str) -> bool:
    lowered = path.casefold()
    return (
        not lowered.startswith("/studio/api/")
        or lowered.startswith(SKIP_PREFIXES)
        or any(word in lowered for word in SKIP_WORDS)
    )


class Scanner:
    def __init__(self, store: StudioStore) -> None:
        self._store = store
        self.state = ScanState()
        self._task: asyncio.Task[None] | None = None
        self._probe: Probe | None = None
        self._wake = asyncio.Event()
        self._stopping = False

    # ------------------------------------------------------------- control

    def start(
        self,
        probe: Probe,
        *,
        modes: Sequence[str] = (),
        endless: bool = False,
        interval_s: int = 600,
        spawn: Callable[[Awaitable[None]], object],
    ) -> ScanState:
        wanted = [mode for mode in modes if mode in MODES] or list(MODES)
        if any(mode not in MODES for mode in modes):
            raise ScanError(f"Scan ways: {', '.join(MODES)}.")
        if self.state.running:
            raise ScanError("A scan is already running: stop it first.")
        self._probe = probe
        self.state.running = True
        self.state.endless = endless
        self.state.interval_s = max(60, min(24 * 3600, int(interval_s)))
        self.state.message = "Scanning…"
        self._wake = asyncio.Event()
        self._stopping = False
        spawn(self._loop(wanted))
        return self.state

    def stop(self) -> ScanState:
        self._stopping = True
        self.state.endless = False
        self._wake.set()
        self.state.message = "Stopping after this round."
        return self.state

    async def _loop(self, modes: list[str]) -> None:
        try:
            while True:
                for mode in modes:
                    await self.run_round(mode)
                    if self._stopping:
                        return  # the owner pressed Stop: this round was the last
                    if not self.state.endless:
                        if mode == modes[-1]:
                            return
                        continue
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._wake.wait(), timeout=self.state.interval_s
                        )
                    if not self.state.endless:
                        return
        finally:
            self.state.running = False
            self.state.message = (
                f"Stopped after {self.state.rounds} rounds."
                if self.state.rounds
                else "Stopped."
            )

    # -------------------------------------------------------------- rounds

    async def run_round(self, mode: str) -> list[ScanFinding]:
        """One round of one way of scanning; returns the new findings."""
        probe = self._probe
        if probe is None:
            raise ScanError("Start a scan first.")
        self.state.mode = mode
        seed = self.state.rounds
        rng = random.Random(seed)
        started = time.monotonic()
        try:
            found = await getattr(self, f"_scan_{mode}")(probe, rng)
        except Exception as error:  # a scan that breaks is itself a finding
            logger.warning("Studio scanner {} failed: {}", mode, error)
            found = [
                Found(
                    mode,
                    "medium",
                    f"The {mode} scan itself failed",
                    f"{type(error).__name__}: {error}",
                    "scanner",
                )
            ]
        problem = ""
        try:
            new = await self._keep(found)
        except Exception as error:  # an endless scan carries on after this
            logger.warning("Studio scanner couldn't save its findings: {}", error)
            new = []
            problem = f" Couldn't save this round's findings: {error}"
        self.state.rounds += 1
        self.state.last_round_at = now_ms()
        self.state.last_new = len(new)
        entry: JsonObject = {
            "mode": mode,
            "found": len(found),
            "new": len(new),
            "seconds": round(time.monotonic() - started, 1),
            "at": self.state.last_round_at,
        }
        self.state.history = [entry, *self.state.history][:20]
        self.state.message = (
            f"Round {self.state.rounds} ({mode}): {len(found)} problems, "
            f"{len(new)} new.{problem}"
        )
        return new

    async def _keep(self, found: list[Found]) -> list[ScanFinding]:
        new: list[ScanFinding] = []
        for item in found:
            existing = await self._store.get(ScanFinding, item.key)
            if existing is not None:
                await self._store.put(
                    existing.model_copy(
                        update={
                            "count": existing.count + 1,
                            "last_seen": now_ms(),
                            "detail": item.detail[:4000],
                            # A fixed one that comes back is news again.
                            "status": "new"
                            if existing.status == "fixed"
                            else existing.status,
                        }
                    )
                )
                continue
            finding = ScanFinding(
                id=item.key,
                mode=item.mode,
                severity=item.severity,
                title=item.title[:300],
                detail=item.detail[:4000],
                place=item.where[:300],
            )
            await self._store.put(finding)
            new.append(finding)
        return new

    async def _call(self, probe: Probe, path: str) -> tuple[int, str, float]:
        try:
            return await asyncio.wait_for(probe.get(path), timeout=CALL_SECONDS)
        except TimeoutError:
            return 0, "", CALL_SECONDS

    def _judge(
        self, mode: str, path: str, status: int, body: str, seconds: float
    ) -> list[Found]:
        where = path.split("?")[0]
        if status == 0:
            return [Found(mode, "medium", "No answer in 15 seconds", path, where)]
        if status >= 500:
            return [
                Found(
                    mode,
                    "high",
                    f"Crashed with {status}",
                    f"GET {path}\n{body[:1500]}",
                    where,
                )
            ]
        found: list[Found] = []
        if seconds > SLOW_SECONDS:
            found.append(
                Found(mode, "low", f"Slow: {seconds:.1f} s", f"GET {path}", where)
            )
        if status == 200 and body[:1] in ("{", "[") and len(body) < MAX_BODY:
            try:
                json.loads(body)
            except ValueError:
                found.append(
                    Found(mode, "medium", "Broken JSON in the answer", path, where)
                )
        return found

    async def _scan_routes(self, probe: Probe, rng: random.Random) -> list[Found]:
        plain = [route for route in probe.routes if "{" not in route.path]
        rng.shuffle(plain)
        found: list[Found] = []
        for route in plain[:MAX_CALLS]:
            status, body, seconds = await self._call(probe, route.path)
            found += self._judge("routes", route.path, status, body, seconds)
        return found

    async def _ids(self) -> dict[str, list[str]]:
        rows: dict[str, list[str]] = {}
        for name, model in (
            ("agent", Agent),
            ("chat", Chat),
            ("course", Course),
            ("site", SiteProject),
            ("job", LoraJob),
        ):
            records = await self._store.find(model, order_by="updated_at DESC", limit=5)
            rows[name] = [record.id for record in records]
        return rows

    async def _scan_records(self, probe: Probe, rng: random.Random) -> list[Found]:
        ids = await self._ids()
        found: list[Found] = []
        calls = 0
        routes = [route for route in probe.routes if route.path.count("{") == 1]
        rng.shuffle(routes)
        for route in routes:
            name = re.search(r"\{(\w+)\}", route.path)
            if name is None:
                continue
            kind = name.group(1).removesuffix("_id")
            real = ids.get(kind, [])
            choices = [*real[:2], "missing-id-0000"]
            for value in choices:
                path = route.path.replace(name.group(0), value)
                status, body, seconds = await self._call(probe, path)
                found += self._judge("records", path, status, body, seconds)
                if value.startswith("missing") and status == 200:
                    found.append(
                        Found(
                            "records",
                            "low",
                            "Answers 200 for an id that doesn't exist",
                            f"GET {path}\n{body[:500]}",
                            route.path,
                        )
                    )
                calls += 1
                if calls >= MAX_CALLS:
                    return found
        return found

    async def _scan_odd_inputs(self, probe: Probe, rng: random.Random) -> list[Found]:
        with_query = [
            route for route in probe.routes if route.query and "{" not in route.path
        ]
        rng.shuffle(with_query)
        found: list[Found] = []
        for route in with_query[: MAX_CALLS // 3]:
            for value in rng.sample(ODD_VALUES, 3):
                name = rng.choice(route.query)
                path = f"{route.path}?{name}={quote(value)}"
                status, body, seconds = await self._call(probe, path)
                found += self._judge("odd_inputs", path, status, body, seconds)
        return found

    async def _scan_pages(self, probe: Probe, rng: random.Random) -> list[Found]:
        if probe.page is None:
            return []
        pages = list(PAGES)
        rng.shuffle(pages)
        phone = rng.random() < 0.5
        found: list[Found] = []
        size = "phone" if phone else "PC"
        for page in pages[:6]:
            found.extend(
                Found(
                    "pages",
                    "high" if "error" in problem.casefold() else "medium",
                    problem[:200],
                    f"Page #{page} ({size} size): {problem}",
                    f"#{page}",
                )
                for problem in await probe.page(page, phone)
            )
        return found

    async def _scan_logs(self, probe: Probe, rng: random.Random) -> list[Found]:
        del rng
        path = probe.log_path
        if path is None or not path.is_file():
            return []
        with path.open("rb") as handle:
            size = path.stat().st_size
            handle.seek(max(0, size - LOG_TAIL_BYTES))
            text = handle.read().decode("utf-8", "replace")
        found: dict[str, Found] = {}
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if not re.search(r"\| (ERROR|CRITICAL) \||Traceback \(most recent", line):
                continue
            message = line.split(" - ", 1)[-1].strip()
            title = re.sub(r"\s+", " ", message)[:160]
            detail = "\n".join(lines[index : index + 12])
            item = Found(
                "logs",
                "high" if "CRITICAL" in line else "medium",
                title,
                detail,
                "server.log",
            )
            found.setdefault(item.key, item)
        return list(found.values())

    async def _scan_data(self, probe: Probe, rng: random.Random) -> list[Found]:
        del probe, rng
        found: list[Found] = []
        agent_ids = {agent.id for agent in await self._store.find(Agent)}
        found.extend(
            Found(
                "data",
                "medium",
                f"A class points at a missing agent ({field_name})",
                f"Class {course.topic!r} ({course.id})",
                f"course.{field_name}",
            )
            for course in await self._store.find(Course)
            for field_name in ("teacher_agent_id", "student_agent_id")
            if getattr(course, field_name) not in agent_ids
        )
        found.extend(
            Found(
                "data",
                "low",
                "A chat points at a missing agent",
                f"Chat {chat.title!r} ({chat.id})",
                "chat.agent_id",
            )
            for chat in await self._store.find(Chat)
            if chat.agent_id and chat.agent_id not in agent_ids
        )
        now = now_ms()
        running = [
            *(
                ("LoRA job", job)
                for job in await self._store.find(LoraJob, where={"status": "running"})
            ),
            *(
                ("tuning job", job)
                for job in await self._store.find(TuneJob, where={"status": "running"})
            ),
        ]
        found.extend(
            Found(
                "data",
                "medium",
                f"A {label} says running but hasn't moved for hours",
                f"{label} {job.id}, last change "
                f"{(now - job.updated_at) // 60000} minutes ago",
                f"{type(job).__name__}.status",
            )
            for label, job in running
            if now - job.updated_at > STUCK_MS
        )
        return found

    async def _scan_files(self, probe: Probe, rng: random.Random) -> list[Found]:
        found: list[Found] = []
        if probe.package is not None:
            sources = sorted(probe.package.rglob("*.py"))
            rng.shuffle(sources)
            for source in sources[:400]:
                try:
                    compile(source.read_text(encoding="utf-8"), str(source), "exec")
                except (SyntaxError, UnicodeDecodeError, ValueError) as error:
                    found.append(
                        Found(
                            "files",
                            "high",
                            "Python file won't load",
                            f"{source}: {error}",
                            source.name,
                        )
                    )
            node = shutil.which("node") or ""
            scripts = sorted((probe.package / "api" / "studio_static").glob("*.js"))
            for script in scripts if node else []:
                checked = await asyncio.create_subprocess_exec(
                    node,
                    "--check",
                    str(script),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, error = await checked.communicate()
                if checked.returncode:
                    found.append(
                        Found(
                            "files",
                            "high",
                            "Page script has a syntax error",
                            error.decode("utf-8", "replace")[:1500],
                            script.name,
                        )
                    )
        if probe.vendor is not None and probe.package is not None:
            found += _library_checks(probe.vendor, probe.package)
        disk = shutil.disk_usage(probe.package or Path.home())
        if disk.free < 2 * 1024**3:
            found.append(
                Found(
                    "files",
                    "medium",
                    "Less than 2 GB free on the disk",
                    f"{disk.free / 1024**3:.1f} GB free",
                    "disk",
                )
            )
        return found


LIBRARIES = (
    ("tabler", "studio/ui_kit/tabler.zip"),
    ("swe-bench", "studio/bug_library/bugs.json.gz"),
    ("startbootstrap", "studio/site_layouts/layouts.zip"),
    ("kenney", "studio/game_library/kenney-core-1.zip"),
    ("kenney", "studio/game_library/kenney-core-2.zip"),
)
"""FCC's shipped libraries and the vendor folder that records their checksum."""


def _library_checks(vendor: Path, package: Path) -> list[Found]:
    found: list[Found] = []
    for folder, relative in LIBRARIES:
        sums = vendor / folder / "SHA256SUMS"
        target = package / relative
        if not sums.is_file():
            continue
        if not target.is_file():
            found.append(
                Found(
                    "files",
                    "high",
                    "A shipped library is missing",
                    str(target),
                    target.name,
                )
            )
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if f"{digest}  {target.name}" not in sums.read_text(encoding="utf-8"):
            found.append(
                Found(
                    "files",
                    "high",
                    "A shipped library doesn't match its recorded checksum",
                    f"{target} vs {sums}",
                    target.name,
                )
            )
    return found


def finding_view(finding: ScanFinding) -> JsonObject:
    return finding.model_dump()


def changer_request(finding: ScanFinding) -> str:
    """What the owner sends the Changer for one finding."""
    return (
        f"The bug scanner found this ({finding.severity}, seen {finding.count} "
        f"times, way: {finding.mode}).\n\n{finding.title}\nWhere: "
        f"{finding.place}\n\n{finding.detail}\n\nFind the real cause, fix it, and "
        "add a test that fails without the fix."
    )


__all__ = [
    "MAX_FINDINGS",
    "MODES",
    "MODE_NOTES",
    "Probe",
    "Route",
    "ScanError",
    "Scanner",
    "changer_request",
    "finding_view",
    "skipped",
]
