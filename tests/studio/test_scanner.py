"""The bug scanner: rounds of read-only checks, in different ways, kept as
findings for the owner."""

import asyncio
import dataclasses
import hashlib

import httpx
import pytest

from free_claude_code.studio.models import Agent, Course, ScanFinding
from free_claude_code.studio.scanner import MODES, Probe, Route, Scanner, skipped
from tests.api.support import create_test_app


def fake_probe(**overrides) -> Probe:
    async def get(path: str) -> tuple[int, str, float]:
        if path.startswith("/studio/api/broken"):
            return 500, "Traceback: boom", 0.1
        if path.startswith("/studio/api/slow"):
            return 200, "{}", 7.5
        if path.startswith("/studio/api/odd") and "%F0" in path:
            return 500, "UnicodeError", 0.1
        return 200, "{}", 0.01

    probe = Probe(
        get=get,
        routes=[
            Route("/studio/api/broken"),
            Route("/studio/api/slow"),
            Route("/studio/api/fine"),
            Route("/studio/api/odd", ("q",)),
            Route("/studio/api/agents/{agent_id}"),
        ],
    )
    return dataclasses.replace(probe, **overrides)


def test_the_scanner_never_calls_risky_routes():
    assert skipped("/studio/api/farm/posts")  # Content Farm is left out
    assert skipped("/studio/api/trade/broker/quote")
    assert skipped("/studio/api/models/download")
    assert skipped("/admin/api/providers")
    assert not skipped("/studio/api/agents")


@pytest.mark.asyncio
async def test_a_round_finds_crashes_and_slow_answers_once(store):
    scanner = Scanner(store)
    scanner._probe = fake_probe()
    first = await scanner.run_round("routes")
    titles = {item.title for item in first}
    assert "Crashed with 500" in titles and any(t.startswith("Slow") for t in titles)
    again = await scanner.run_round("routes")
    assert again == []  # the same problems aren't news twice
    crash = next(item for item in first if item.title == "Crashed with 500")
    kept = await store.require(ScanFinding, crash.id)
    assert kept.count == 2 and kept.severity == "high"


@pytest.mark.asyncio
async def test_odd_inputs_and_missing_ids_are_tried(store):
    scanner = Scanner(store)
    scanner._probe = fake_probe()
    await store.put(Agent(name="Builder", model="local/x"))
    rounds = [await scanner.run_round("odd_inputs") for _ in range(4)]
    assert any(item.mode == "odd_inputs" for found in rounds for item in found)
    records = await scanner.run_round("records")
    assert any("doesn't exist" in item.title for item in records)


@pytest.mark.asyncio
async def test_broken_links_stuck_jobs_logs_and_files_are_found(store, tmp_path):
    scanner = Scanner(store)
    log = tmp_path / "server.log"
    log.write_text(
        "2026-10-24 | INFO | all good\n"
        "2026-10-24 | ERROR | free_claude_code.x:y:1 - Studio thing failed: boom\n"
    )
    package = tmp_path / "pkg"
    (package / "studio" / "ui_kit").mkdir(parents=True)
    (package / "broken.py").write_text("def nope(:\n")
    (package / "studio/ui_kit/tabler.zip").write_bytes(b"changed")
    vendor = tmp_path / "vendor"
    (vendor / "tabler").mkdir(parents=True)
    (vendor / "tabler/SHA256SUMS").write_text(
        f"{hashlib.sha256(b'original').hexdigest()}  tabler.zip\n"
    )
    scanner._probe = fake_probe(log_path=log, package=package, vendor=vendor)
    await store.put(
        Course(
            topic="Ohm", teacher_agent_id="gone", student_agent_id="gone", chat_id="c"
        )
    )
    data = await scanner.run_round("data")
    assert any("missing agent" in item.title for item in data)
    logs = await scanner.run_round("logs")
    assert logs and "Studio thing failed" in logs[0].title
    files = await scanner.run_round("files")
    titles = {item.title for item in files}
    assert "Python file won't load" in titles
    assert "A shipped library doesn't match its recorded checksum" in titles


@pytest.mark.asyncio
async def test_an_endless_scan_keeps_going_until_stopped(store):
    scanner = Scanner(store)
    tasks: list[asyncio.Task[None]] = []

    def spawn(work):
        tasks.append(asyncio.ensure_future(work))

    scanner.start(
        fake_probe(), modes=["routes"], endless=True, interval_s=60, spawn=spawn
    )
    for _ in range(100):
        if scanner.state.rounds:
            break
        await asyncio.sleep(0.01)
    assert scanner.state.running and scanner.state.rounds >= 1
    scanner.stop()
    await asyncio.wait_for(tasks[0], timeout=5)
    assert not scanner.state.running


@pytest.mark.asyncio
async def test_scanning_fcc_itself_through_its_routes(make_studio, monkeypatch):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    ) as client:
        started = await client.post(
            "/studio/api/scanner/start",
            json={"modes": ["routes", "records", "data", "files"]},
        )
        assert started.status_code == 200, started.text
        await studio.wait_for_background()
        overview = (await client.get("/studio/api/scanner")).json()
        assert overview["rounds"] == 4 and not overview["running"]
        assert {mode["id"] for mode in overview["modes"]} == set(MODES)
        crashes = [f for f in overview["findings"] if f["severity"] == "high"]
        assert crashes == [], crashes
        bad = await client.post(
            "/studio/api/scanner/start", json={"modes": ["telepathy"]}
        )
        assert bad.status_code == 400


@pytest.mark.asyncio
async def test_the_owner_marks_and_sends_findings(make_studio, monkeypatch):
    studio, _ = make_studio([])
    finding = ScanFinding(id="abc", mode="routes", title="Crashed with 500", detail="x")
    await studio._store.put(finding)
    sent: list[str] = []

    async def changer_start(request: str, *, budget: int = 0):
        sent.append(request)
        return {"project": {"id": "chg_1"}}

    monkeypatch.setattr(studio, "changer_start", changer_start)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    ) as client:
        to_changer = await client.post("/studio/api/scanner/findings/abc/changer")
        assert to_changer.status_code == 200
        assert "Crashed with 500" in sent[0] and "add a test" in sent[0]
        kept = await studio._store.require(ScanFinding, "abc")
        assert kept.status == "sent" and kept.changer_project == "chg_1"
        dismissed = await client.post(
            "/studio/api/scanner/findings/abc", json={"status": "dismissed"}
        )
        assert dismissed.json()["status"] == "dismissed"
        overview = (await client.get("/studio/api/scanner")).json()
        assert overview["findings"] == [] and overview["closed"] == 1


def test_areas_that_reach_runtimes_providers_or_brokers_are_never_scanned():
    from free_claude_code.studio.scanner import SKIP_PREFIXES

    for path in (
        "/studio/api/models/available",
        "/studio/api/team-models/suggest",
        "/studio/api/engine",
        "/studio/api/trading/feed",
        "/studio/api/ops",
        "/studio/api/desk",
        "/studio/api/phone/hello",
        "/studio/api/starters",
        "/studio/api/lab/chat",
        "/studio/api/tutor/question",
        "/studio/api/connect",
        "/studio/api/extensions",
        "/studio/api/claw",
        "/studio/api/subagents",
        "/studio/api/relay",
        "/studio/api/commands/pending",
        "/studio/api/sites/abc/archive",
        "/studio/api/changer/diff",
    ):
        assert skipped(path), path
    assert all(prefix.startswith("/studio/api/") for prefix in SKIP_PREFIXES)


def test_an_empty_answer_isnt_broken_json(store):
    scanner = Scanner(store)
    assert scanner._judge("routes", "/studio/api/x", 200, "", 0.01) == []
    assert scanner._judge("routes", "/studio/api/x", 200, "{oops", 0.01)


@pytest.mark.asyncio
async def test_stop_ends_after_the_round_it_is_on(store):
    scanner = Scanner(store)
    tasks: list[asyncio.Task[None]] = []
    gate = asyncio.Event()
    calls: list[str] = []

    async def get(path: str) -> tuple[int, str, float]:
        calls.append(path)
        await gate.wait()
        return 200, "{}", 0.01

    probe = fake_probe(get=get)
    scanner.start(
        probe,
        endless=True,
        interval_s=60,
        spawn=lambda w: tasks.append(asyncio.ensure_future(w)),
    )
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.01)
    scanner.stop()
    gate.set()
    await asyncio.wait_for(tasks[0], timeout=5)
    assert scanner.state.rounds == 1 and not scanner.state.running


@pytest.mark.asyncio
async def test_a_round_that_cant_save_doesnt_end_the_scan(store, monkeypatch):
    scanner = Scanner(store)
    scanner._probe = fake_probe()

    async def broken(item):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "put", broken)
    assert await scanner.run_round("routes") == []
    assert "Couldn't save" in scanner.state.message and scanner.state.rounds == 1


@pytest.mark.asyncio
async def test_duplicates_mode_flags_two_agents_sharing_a_name(store):
    scanner = Scanner(store)
    scanner._probe = fake_probe()
    await store.put(Agent(name="Aria", model="local/x"))
    await store.put(Agent(name="aria", model="local/y"))  # same name, different case
    await store.put(Agent(name="Solo", model="local/z"))

    found = await scanner.run_round("duplicates")
    titles = [item.title for item in found]
    assert any("share the name 'aria'" in t for t in titles)
    assert all("Solo" not in t for t in titles)  # a unique name is not flagged
    # the title uses the folded name, so the finding keeps one key, not the
    # store's order, and doesn't re-appear as new.
    assert any("share the name 'aria'" in item.title for item in found)
    again = await scanner.run_round("duplicates")
    assert again == []  # not news twice


@pytest.mark.asyncio
async def test_duplicates_mode_keeps_digit_names_and_kinds_apart(store):
    from free_claude_code.studio.models import Course, SiteProject

    scanner = Scanner(store)
    scanner._probe = fake_probe()
    # Names that differ only by a digit must be separate findings, not merged.
    for name in ("bot1", "bot1", "bot2", "bot2"):
        await store.put(Agent(name=name, model="local/x"))
    await store.put(SiteProject(name="Shop", slug="shop-1"))
    await store.put(SiteProject(name="Shop", slug="shop-2"))
    await store.put(
        Course(topic="Ohm", chat_id="c1", teacher_agent_id="t", student_agent_id="s")
    )
    await store.put(
        Course(topic="Ohm", chat_id="c2", teacher_agent_id="t", student_agent_id="s")
    )

    found = await scanner.run_round("duplicates")
    keys = {item.id for item in found}
    assert len(keys) == len(found)  # no two findings share a key
    titles = " ".join(item.title for item in found)
    assert "'bot1'" in titles and "'bot2'" in titles  # digit names kept apart
    assert any("projects share the name 'shop'" in i.title for i in found)
    assert any("classes share the name 'ohm'" in i.title for i in found)


@pytest.mark.asyncio
async def test_duplicates_mode_ignores_archived_agents(store):
    scanner = Scanner(store)
    scanner._probe = fake_probe()
    await store.put(Agent(name="Twin", model="local/x"))
    await store.put(Agent(name="Twin", model="local/y", archived=True))

    found = await scanner.run_round("duplicates")
    assert not any("Twin" in i.title or "twin" in i.title for i in found)
