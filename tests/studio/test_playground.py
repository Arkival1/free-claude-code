"""The Playground on the PC: one main AI does the job with its own hands,
up to two advisers advise before it starts and check it after (it fixes what
they found), each AI keeps its own thoughts, patterns and lessons, and the
owner's taste goes to every AI in the job."""

import asyncio

import httpx
import pytest

from free_claude_code.studio.llm import LOCAL_MODEL_PREFIX
from free_claude_code.studio.models import Agent, PlaygroundJob
from free_claude_code.studio.playground import (
    ADVISER_PROMPT,
    ADVISER_TOOLS,
    HANDS_PROMPT,
    HANDS_TOOLS,
    MAX_ADVISERS,
    REFLECT_PROMPT,
    advice_brief,
    check_brief,
    hands_brief,
    looks_good,
    pick_advisers,
    reflection,
)
from free_claude_code.studio.tools import LEAD_TOOLS
from tests.api.support import create_test_app

from .conftest import tool_reply

MAKING = {"start_project", "write_file", "edit_file", "delete_file", "use_photo"}


def agent(name: str, role: str, model: str = "nvidia_nim/m", **extra: object) -> Agent:
    return Agent.model_validate({"name": name, "role": role, "model": model, **extra})


def test_advisers_fit_the_job_and_server_ais_advise_first():
    team = [
        agent("Jarvis", "main", "lmstudio/qwen"),
        agent("Helper", "helper", "lmstudio/qwen"),
        agent("Researcher", "researcher"),
        agent("Tester", "tester"),
        agent("Guide", "guide"),
        agent("Old", "tester", archived=True),
        agent("Changer Planner", "helper"),
    ]

    def local(model: str) -> bool:
        return model.startswith("lmstudio/")

    jarvis = team[0].id
    build = pick_advisers("Build a bakery website", team, jarvis, is_local=local)
    assert [next(a.name for a in team if a.id == i) for i in build] == [
        "Tester",
        "Researcher",
    ]
    plan = pick_advisers("Plan my week", team, jarvis, is_local=local)
    assert [next(a.name for a in team if a.id == i) for i in plan] == [
        "Researcher",
        "Tester",
    ]
    # A team meeting brings more in; the hands, Guide, archived agents and the
    # Changer's team never advise.
    meeting = pick_advisers("Plan my week", team, jarvis, count=5, is_local=local)
    names = {next(a.name for a in team if a.id == i) for i in meeting}
    assert names == {"Researcher", "Tester", "Helper"}
    assert len(pick_advisers("x", team, jarvis)) == MAX_ADVISERS


def test_the_briefs_and_notes_read_right():
    assert "Advise the main AI before it starts" in advice_brief(
        "Make a site", "Jarvis"
    )
    check = check_brief("Make a site", "Jarvis", "Made index.html", "Bakery")
    assert "LOOKS GOOD" in check and "Made index.html" in check and "Bakery" in check
    first = hands_brief("Make a site", 1, "- Tester: big buttons")
    assert first.startswith("Make a site") and "Your advisers said" in first
    fix = hands_brief("Make a site", 2, "- Tester: add a footer", "Bakery")
    assert fix.startswith("Fix what your advisers found") and "project Bakery" in fix
    assert looks_good("looks good to me") and not looks_good("1. Add a footer")
    assert reflection('{"thought": "x", "pattern": "", "lesson": "y", "z": 1}') == {
        "thought": "x",
        "lesson": "y",
    }
    assert reflection("no json") == {}
    assert not MAKING & set(ADVISER_TOOLS)
    assert {"write_file", "start_project", "godot"} <= set(HANDS_TOOLS)


def script(calls: list[dict[str, object]], gate: asyncio.Event | None = None):
    """A scripted model: advisers advise, then ask for a footer once; the
    main AI builds, then adds the footer; everyone reflects."""

    async def respond(system: str, prompt: str):
        calls.append({"system": system, "prompt": prompt})
        if system == REFLECT_PROMPT:
            return (
                '{"thought": "Hours matter to bakeries.", '
                '"pattern": "Plan the page before writing it.", '
                '"lesson": "Put the footer in the first time."}'
            )
        if ADVISER_PROMPT in system:
            if gate is not None:
                await gate.wait()
            if "Advise the main AI before it starts" in prompt:
                return tool_reply("finish", {"summary": "Use warm colours."})
            if "Added the footer" in prompt:
                return tool_reply("finish", {"summary": "LOOKS GOOD"})
            return tool_reply("finish", {"summary": "1. Add a footer with the hours."})
        if HANDS_PROMPT in system:
            if prompt.startswith("Fix what your advisers found"):
                return tool_reply("finish", {"summary": "Added the footer."})
            if "Make a bakery page" in prompt:
                return tool_reply("start_project", {"name": "Joe's Bakery"})
            return tool_reply("finish", {"summary": "Made the page."})
        return "On it."

    return respond


@pytest.mark.asyncio
async def test_the_main_ai_does_the_work_and_fixes_what_the_advisers_found(
    make_studio,
):
    calls: list[dict[str, object]] = []
    studio, model = make_studio(script(calls))
    await studio.ensure_defaults()
    await studio.add_taste("Warm, friendly colours.")
    main = await studio.main_agent()

    job = await studio.start_playground("Make a bakery page")
    assert job.hands_id == main.id and len(job.advisers) == MAX_ADVISERS
    await asyncio.wait_for(studio.wait_for_background(), timeout=30)

    done = await studio.playground_job(job.id)
    assert done.status == "done", done.summary
    advisers = [s.agent for s in done.steps if s.stage == "kickoff"]
    assert len(advisers) == 2
    assert [(s.stage, s.try_no) for s in done.steps] == [
        ("kickoff", 0),
        ("kickoff", 0),
        ("work", 1),
        ("review", 1),
        ("review", 1),
        ("work", 2),
        ("review", 2),
        ("review", 2),
    ]
    assert all(s.status == "done" for s in done.steps)
    # The fix brief carried the advisers' note; every brief carried the taste.
    briefs = [str(c["prompt"]) for c in calls if HANDS_PROMPT in str(c["system"])]
    assert any(
        b.startswith("Fix what your advisers found") and "footer" in b for b in briefs
    )
    assert all(
        "Warm, friendly colours." in b for b in briefs if "The job" in b or "Make" in b
    )
    # The work landed in one project the job knows about.
    assert done.site_id
    # Advisers only advise: none of their calls offered a tool that changes things.
    for call in model.calls:
        tools = call["tools"]
        offered = set(tools) if isinstance(tools, list) else set()
        if ADVISER_PROMPT in str(call["system"]):
            assert not offered & MAKING, offered
        if HANDS_PROMPT in str(call["system"]) and offered:
            assert {"write_file", "start_project"} <= offered
    # Each AI kept what it learned in its own mind.
    minds = await studio.playground_minds()
    taste = minds["taste"]
    assert isinstance(taste, list) and any(
        isinstance(t, dict) and t.get("text") == "Warm, friendly colours."
        for t in taste
    )
    jarvis = next(
        m for m in minds["minds"] if isinstance(m, dict) and m["agent_id"] == main.id
    )
    assert isinstance(jarvis, dict)
    patterns = jarvis["pattern"]
    assert isinstance(patterns, list) and patterns
    assert any(
        isinstance(p, dict) and p["text"] == "Plan the page before writing it."
        for p in patterns
    )
    view = studio.playground_view(done)
    assert view["running"] is False and view["done_steps"] == 8


@pytest.mark.asyncio
async def test_a_stopped_job_runs_again_from_where_it_stopped(make_studio):
    calls: list[dict[str, object]] = []
    gate = asyncio.Event()
    studio, _ = make_studio(script(calls, gate))
    await studio.ensure_defaults()

    job = await studio.start_playground("Make a bakery page")
    for _ in range(200):
        current = await studio.playground_job(job.id)
        if any(s.status == "running" for s in current.steps):
            break
        await asyncio.sleep(0.01)
    stopped = await studio.stop_playground(job.id)
    assert stopped.status == "stopped"
    assert not any(s.status == "running" for s in stopped.steps)
    assert not studio.playground_view(stopped)["running"]

    gate.set()
    again = await studio.resume_playground(job.id)
    assert again.status == "working"
    await asyncio.wait_for(studio.wait_for_background(), timeout=30)
    finished = await studio.playground_job(job.id)
    assert finished.status == "done", finished.summary


@pytest.mark.asyncio
async def test_a_job_left_working_when_fcc_closed_shows_as_stopped(make_studio):
    studio, _ = make_studio([])
    main = await studio.main_agent()
    left = PlaygroundJob(goal="Old job", hands_id=main.id)
    await studio._store.put(left)
    listed = await studio.playground_jobs()
    assert [j.status for j in listed] == ["stopped"]
    assert "Run again" in listed[0].summary


@pytest.mark.asyncio
async def test_the_owner_can_hand_the_work_to_another_agent_with_no_advisers(
    make_studio,
):
    calls: list[dict[str, object]] = []
    studio, _ = make_studio(script(calls))
    await studio.ensure_defaults()
    builder = next(a for a in await studio.agents() if a.role == "builder")
    job = await studio.start_playground(
        "Make a bakery page", hands_id=builder.id, advisers="none"
    )
    assert job.hands_id == builder.id and job.advisers == ()
    await asyncio.wait_for(studio.wait_for_background(), timeout=30)
    done = await studio.playground_job(job.id)
    assert done.status == "done", done.summary
    assert [(s.stage, s.agent) for s in done.steps] == [("work", builder.name)]


@pytest.mark.asyncio
async def test_the_playground_routes_start_list_and_show_minds(make_studio):
    calls: list[dict[str, object]] = []
    studio, _ = make_studio(script(calls))
    await studio.ensure_defaults()
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        liked = await client.post(
            "/studio/api/playground/taste", json={"text": "Big, bold headings."}
        )
        assert liked.status_code == 201, liked.text
        empty = await client.post("/studio/api/playground", json={"goal": "  "})
        assert empty.status_code == 400
        started = await client.post(
            "/studio/api/playground",
            json={"goal": "Make a bakery page", "advisers": "meeting"},
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["id"]
        assert started.json()["meeting"] is True
        await asyncio.wait_for(studio.wait_for_background(), timeout=30)
        listed = (await client.get("/studio/api/playground")).json()["jobs"]
        assert listed[0]["id"] == job_id and listed[0]["status"] == "done"
        one = (await client.get(f"/studio/api/playground/{job_id}")).json()
        kickoff = [s for s in one["steps"] if s["stage"] == "kickoff"]
        # A team meeting: more advisers advise, but only two check the work.
        assert len(kickoff) > 2
        assert len([s for s in one["steps"] if s["stage"] == "review"]) <= 4
        minds = (await client.get("/studio/api/playground/minds")).json()
        assert any(t["text"] == "Big, bold headings." for t in minds["taste"])
        stop = await client.post(f"/studio/api/playground/{job_id}/stop")
        assert stop.status_code == 200 and stop.json()["status"] == "done"


@pytest.mark.asyncio
async def test_plain_text_answers_finish_each_turn(make_studio):
    """Small models often just answer: that counts as the turn's result."""

    def respond(system: str, prompt: str) -> str:
        if system == REFLECT_PROMPT:
            return '{"pattern": "Keep it simple."}'
        if ADVISER_PROMPT in system:
            if "Advise the main AI before it starts" in prompt:
                return "Keep it to one calm page."
            return "LOOKS GOOD"
        if HANDS_PROMPT in system:
            return "Made the page."
        return "On it."

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    job = await studio.start_playground("Build a website for a yoga studio")
    await asyncio.wait_for(studio.wait_for_background(), timeout=30)
    done = await studio.playground_job(job.id)
    assert done.status == "done", (done.summary, done.steps)
    assert [s.stage for s in done.steps] == [
        "kickoff",
        "kickoff",
        "work",
        "review",
        "review",
    ]


@pytest.mark.asyncio
async def test_an_adviser_on_this_pc_directs_nobody(make_studio):
    """With local control on, an agent on this PC's model may usually direct
    the server agents; as a Playground adviser it only advises."""
    calls: list[dict[str, object]] = []
    studio, model = make_studio(
        script(calls), STUDIO_LOCAL_CONTROL=True, STUDIO_PRIVATE_MEMORY=True
    )
    await studio.ensure_defaults()
    helper = next(a for a in await studio.agents() if a.role == "helper")
    await studio.update_agent(helper.id, {"model": f"{LOCAL_MODEL_PREFIX}qwen"})
    job = await studio.start_playground("Plan my week", advisers=[helper.id])
    await asyncio.wait_for(studio.wait_for_background(), timeout=30)
    done = await studio.playground_job(job.id)
    assert done.status == "done", done.summary
    advising = [c for c in model.calls if ADVISER_PROMPT in str(c["system"])]
    assert advising
    for call in advising:
        tools = call["tools"]
        offered = set(tools) if isinstance(tools, list) else set()
        assert not offered & set(LEAD_TOOLS), offered
