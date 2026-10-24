"""Subagents: helpers with roles that join fitting tasks on their own,
switch on and off, and show in the team like everyone else."""

import asyncio

import httpx
import pytest

from free_claude_code.studio import StudioError
from free_claude_code.studio.models import Agent, AgentRun, Message
from free_claude_code.studio.presets import CODER_TOOLS
from free_claude_code.studio.subagents import (
    HELP_PREFIX,
    MAX_HELPERS,
    fits,
    helper_goal,
    pick,
)
from tests.api.support import create_test_app

from .conftest import tool_reply


def agent(name: str, role: str, **extra: object) -> Agent:
    return Agent.model_validate({"name": name, "role": role, "model": "m", **extra})


def test_subagents_join_only_work_that_fits_their_role():
    assert fits("developer", "Build a todo app with a database")
    assert fits("researcher", "Research the best pizza ovens")
    assert fits("tester", "Fix the login bug")
    assert not fits("researcher", "hello there")
    assert not fits("nobody", "build an app")
    owner = agent("Builder", "builder")
    team = [
        agent("Dev-1", "developer", subagent=True),
        agent("Dev-2", "developer", subagent=True, active=False),
        agent("Res-1", "researcher", subagent=True),
        agent("Coder", "coder"),
        agent("Test-1", "tester", subagent=True),
    ]
    chosen = pick(team, owner, "Build an app and research the best design")
    assert [a.name for a in chosen] == ["Dev-1", "Res-1"]
    assert len(chosen) <= MAX_HELPERS
    # Help never runs away: helpers aren't helped, subagents aren't helped.
    assert pick(team, owner, f"{HELP_PREFIX}Builder is working on: build an app") == []
    assert pick(team, team[0], "Build an app") == []
    goal = helper_goal(team[4], owner, "Build an app", "Made index.html")
    assert goal.startswith(HELP_PREFIX) and "Made index.html" in goal


@pytest.mark.asyncio
async def test_subagents_are_added_switched_and_kept_out_of_the_main_team(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    dev = await studio.create_subagent(name="Dev-1", role="developer")
    assert dev.subagent and dev.active and dev.role == "developer"
    assert set(CODER_TOOLS) <= set(dev.tools) and not dev.all_tools
    with pytest.raises(StudioError, match="already an agent"):
        await studio.create_subagent(name="dev-1", role="tester")
    with pytest.raises(StudioError, match="Pick a subagent role"):
        await studio.create_subagent(name="X", role="farm")
    coder_sub = await studio.create_subagent(name="Code-2", role="coder")
    # Jarvis still hands coding to the team's own Coder, not a subagent.
    member = await studio._team_member("coder")
    assert member is not None and member.id != coder_sub.id
    off = await studio.set_subagent_active(dev.id, False)
    assert off.active is False
    assert [a.name for a in await studio.subagents()] == ["Dev-1", "Code-2"]
    builder = await studio._team_member("builder")
    assert builder is not None
    with pytest.raises(StudioError, match="isn't a subagent"):
        await studio.set_subagent_active(builder.id, False)


async def settle(studio, helpers: int) -> None:
    """Wait until the task and its helpers (the after-helpers start only once
    the task is done) have all finished; slow machines get 60 seconds."""
    for _ in range(1200):
        runs = await studio.runs()
        helping = [run for run in runs if run.goal.startswith(HELP_PREFIX)]
        if len(helping) >= helpers and all(
            run.status not in {"queued", "running"} for run in runs
        ):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("tasks didn't finish")


@pytest.mark.asyncio
async def test_matching_subagents_help_during_and_after_a_task(make_studio):
    def respond(system: str, prompt: str):
        return tool_reply("finish", {"summary": "Built it."})

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    dev = await studio.create_subagent(name="Dev-1", role="developer")
    tester = await studio.create_subagent(name="Test-1", role="tester")
    sleepy = await studio.create_subagent(name="Res-1", role="researcher")
    await studio.set_subagent_active(sleepy.id, False)
    builder = await studio._team_member("builder")
    assert builder is not None
    site = await studio.create_site(name="Todo")
    run = await studio.start_task(
        agent_id=builder.id, goal="Build a todo app", site_id=site.id
    )
    await settle(studio, helpers=2)
    runs = await studio._store.find(AgentRun)
    helping = {r.agent_id: r for r in runs if r.goal.startswith(HELP_PREFIX)}
    assert set(helping) == {dev.id, tester.id}
    assert all(r.site_id == site.id for r in helping.values())
    assert "Built it." in helping[tester.id].goal  # the tester saw the result
    events: list[str] = []
    for _ in range(600):  # the "finished" note follows the helper's last step
        events = [
            m.text
            for m in await studio._store.find(Message, where={"chat_id": run.chat_id})
            if m.role == "event"
        ]
        if sum("(subagent) finished" in text for text in events) == 2:
            break
        await asyncio.sleep(0.05)
    assert any("Dev-1 (subagent, developer) is helping Builder" in t for t in events)
    assert any("Test-1 (subagent) finished (succeeded)" in t for t in events)


@pytest.mark.asyncio
async def test_subagents_through_the_app(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        view = (await client.get("/studio/api/subagents")).json()
        assert {r["role"] for r in view["roles"]} >= {"developer", "tester"}
        assert view["subagents"] == []
        added = await client.post(
            "/studio/api/subagents", json={"name": "Dev-1", "role": "developer"}
        )
        assert added.status_code == 200 and added.json()["subagent"] is True
        agent_id = added.json()["id"]
        switched = await client.patch(
            f"/studio/api/subagents/{agent_id}", json={"active": False}
        )
        assert switched.json()["active"] is False
        bad = await client.post(
            "/studio/api/subagents", json={"name": "X", "role": "main"}
        )
        assert bad.status_code == 400
        gone = await client.delete(f"/studio/api/agents/{agent_id}")
        assert gone.status_code == 200
        assert (await client.get("/studio/api/subagents")).json()["subagents"] == []


def test_repo_agents_help_when_their_skills_fit():
    owner = agent("Builder", "builder")
    seo = agent(
        "seo-expert",
        "agent",
        subagent=True,
        description="Improves search rankings: metadata, sitemaps, keywords.",
    )
    assert pick([seo], owner, "Add a sitemap and better keywords to the site") == [seo]
    assert pick([seo], owner, "Make the buttons blue") == []
    goal = helper_goal(seo, owner, "Add a sitemap")
    assert "fits your skills" in goal and "sitemaps" in goal
    # Common words alone don't count as a skill.
    vague = agent(
        "helper-x", "agent", subagent=True, description="Helps agents with files."
    )
    assert pick([vague], owner, "help the agents write files") == []


@pytest.mark.asyncio
async def test_any_agent_can_become_a_subagent_with_its_own_model(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    chosen = await studio.create_subagent(
        name="Dev-9", role="developer", model="open_router/poolside/laguna-s-2.1:free"
    )
    assert chosen.model == "open_router/poolside/laguna-s-2.1:free"
    repo = await studio.create_agent(
        name="seo-expert", role="agent", description="Sitemaps and keywords."
    )
    made = await studio.set_subagent(repo.id, True)
    assert made.subagent and made.active
    assert "seo-expert" in [a.name for a in await studio.subagents()]
    back = await studio.set_subagent(repo.id, False)
    assert not back.subagent
    main = await studio.main_agent()
    with pytest.raises(StudioError, match="runs the team"):
        await studio.set_subagent(main.id, True)
