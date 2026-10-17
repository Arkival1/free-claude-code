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


async def settle(studio) -> None:
    for _ in range(200):
        runs = await studio.runs()
        if runs and all(run.status not in {"queued", "running"} for run in runs):
            # Helpers that start after the task need a moment to be queued.
            await asyncio.sleep(0.05)
            runs = await studio.runs()
            if all(run.status not in {"queued", "running"} for run in runs):
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
    await settle(studio)
    runs = await studio._store.find(AgentRun)
    helping = {r.agent_id: r for r in runs if r.goal.startswith(HELP_PREFIX)}
    assert set(helping) == {dev.id, tester.id}
    assert all(r.site_id == site.id for r in helping.values())
    assert "Built it." in helping[tester.id].goal  # the tester saw the result
    events = [
        m.text
        for m in await studio._store.find(Message, where={"chat_id": run.chat_id})
        if m.role == "event"
    ]
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
