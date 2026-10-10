"""The relay: one job passed through LCC's agent and then each repo, one
after another, each building on the last."""

import asyncio

import httpx
import pytest

from free_claude_code.studio.models import AgentRun, PlanStep, TeamPlan
from free_claude_code.studio.relay import (
    RelaySettings,
    RelayStage,
    RelayStore,
    arranged,
    job_kinds,
)
from free_claude_code.studio.starter import BUNDLE
from free_claude_code.studio.teamplan import ready_steps, skip_blocked, step_brief
from tests.api.support import create_test_app
from tests.studio.conftest import tool_reply

BAKERY = "make a website for my bakery"
FIRST_FIVE = [
    "VoltAgent/awesome-claude-code-subagents",
    "OpenHands/software-agent-sdk",
    "FoundationAgents/MetaGPT",
    "AI4Finance-Foundation/FinRobot",
    "crewAIInc/crewAI",
]


def finish_every_stage(seen: list[str] | None = None):
    def respond(system: str, prompt: str):
        if "You are stage" in prompt:
            if seen is not None:
                seen.append(prompt)
            stage = prompt.split("You are stage ")[1].split(" ")[0]
            return tool_reply("finish", {"summary": f"Stage {stage} improved it."})
        return "ok"

    return respond


async def with_repos(make_studio, respond, **settings):
    studio, model = make_studio(respond, **settings)
    studio._starter_folder = BUNDLE
    await studio.ensure_defaults()
    await studio.ensure_starters()
    return studio, model


def test_a_message_says_what_kind_of_job_it_is():
    assert job_kinds(BAKERY) == {"site"}
    assert job_kinds("build a snake game") == {"game"}
    assert job_kinds("make a todo list app") == {"app"}
    assert job_kinds("write a blog post about sourdough") == {"writing"}
    assert "security" in job_kinds("check my site for security problems")
    assert job_kinds("what time is it") == set()


def test_new_repos_join_the_relay_in_their_place(tmp_path):
    installed = ["leonxlnx/taste-skill", *reversed(FIRST_FIVE), "usestrix/strix"]
    fresh = arranged(RelaySettings(), installed)
    assert [s.repo for s in fresh.stages][:5] == FIRST_FIVE
    assert [s.mode for s in fresh.stages][:6] == ["always"] * 5 + ["fits"]

    store = RelayStore(tmp_path / "relay.json")
    store.save(
        RelaySettings(
            on=False,
            first="Builder",
            stages=[RelayStage("usestrix/strix", "off"), RelayStage("gone/repo")],
        )
    )
    saved = arranged(store.load(), [*installed, "someone/new-repo"])
    assert saved.on is False and saved.first == "Builder"
    assert saved.stages[0] == RelayStage("usestrix/strix", "off")
    assert "gone/repo" not in [s.repo for s in saved.stages]
    assert saved.stages[-1] == RelayStage("someone/new-repo", "fits")


def test_a_failed_stage_hands_on_and_nothing_is_skipped():
    steps = (
        PlanStep(id="s1", agent="Builder", do="x", status="done", result="Made it."),
        PlanStep(
            id="s2", agent="frontend-developer", do="y", needs=("s1",), status="failed"
        ),
        PlanStep(id="s3", agent="OpenHands Engineer", do="z", needs=("s2",)),
    )
    relay = TeamPlan(goal=BAKERY, kind="relay", steps=steps)
    assert [s.id for s in ready_steps(skip_blocked(relay))] == ["s3"]
    brief = step_brief(relay, steps[2])
    assert brief.startswith("You are stage 3 of 3 of a relay")
    assert "- Builder [done]: Made it." in brief
    assert "Don't start over" in brief

    plan = relay.model_copy(update={"kind": "plan"})
    assert skip_blocked(plan).steps[2].status == "skipped"


@pytest.mark.asyncio
async def test_a_website_goes_through_lcc_then_each_repo_in_turn(make_studio):
    seen: list[str] = []
    studio, _ = await with_repos(make_studio, finish_every_stage(seen))

    plan = await studio.start_relay(BAKERY, chat_id=(await studio.main_chat()).id)

    assert plan.kind == "relay"
    stages = [(s.agent, s.source) for s in plan.steps]
    assert stages == [
        ("Builder", ""),
        ("frontend-developer", "VoltAgent/awesome-claude-code-subagents"),
        ("OpenHands Engineer", "OpenHands/software-agent-sdk"),
        ("MetaGPT Product Manager", "FoundationAgents/MetaGPT"),
        ("Financial Analyst", "AI4Finance-Foundation/FinRobot"),
        ("crewAI Content Writer", "crewAIInc/crewAI"),
        ("Builder", "leonxlnx/taste-skill"),
    ]
    assert [s.needs for s in plan.steps[1:]] == [(f"s{n}",) for n in range(1, 7)]
    assert "design-taste-frontend" in plan.steps[-1].do
    assert plan.site_id, "every stage works in one project"

    await asyncio.wait_for(studio.wait_for_background(), timeout=60)
    done = await studio.plan(plan.id)
    assert done.status == "done"
    assert [s.status for s in done.steps] == ["done"] * 7
    # One at a time, in order, each told what the stage before it did.
    assert [p.split("You are stage ")[1].split(" ")[0] for p in seen] == [
        str(n) for n in range(1, 8)
    ]
    assert (
        "- frontend-developer (VoltAgent/awesome-claude-code-subagents) [done]: Stage 2 improved it."
        in seen[2]
    )
    starts = [s.started_at for s in done.steps]
    finishes = [s.finished_at for s in done.steps]
    assert all(starts[n + 1] >= finishes[n] for n in range(6))
    runs = await studio.store.find(AgentRun)
    assert {run.site_id for run in runs} == {plan.site_id}
    assert (
        "The relay 'make a website for my bakery' is done: 7 of 7 stage(s) done."
        in done.summary
    )

    # The repo agents joined the team once and are used again next time.
    team = [a.name for a in await studio.agents()]
    assert team.count("frontend-developer") == 1
    again = await studio.start_relay("make a website for my gym")
    await asyncio.wait_for(studio.wait_for_background(), timeout=60)
    assert [a.name for a in await studio.agents()].count("frontend-developer") == 1
    assert (await studio.plan(again.id)).status == "done"


@pytest.mark.asyncio
async def test_a_stage_that_fails_doesnt_stop_the_relay(make_studio):
    def respond(system: str, prompt: str):
        if "You are stage" in prompt and "OpenHands agent" in system:
            raise RuntimeError("the model fell over")
        return finish_every_stage()(system, prompt)

    studio, _ = await with_repos(make_studio, respond)
    plan = await studio.start_relay("make a todo list app")
    await asyncio.wait_for(studio.wait_for_background(), timeout=60)
    done = await studio.plan(plan.id)
    statuses = {s.agent: s.status for s in done.steps}
    assert statuses["OpenHands Engineer"] == "failed"
    assert statuses["MetaGPT QA Engineer"] == "done"
    assert done.steps[-1].status == "done"
    assert done.steps[0].agent == "Coder"


@pytest.mark.asyncio
async def test_the_relay_order_and_switches_are_kept(make_studio):
    studio, _ = await with_repos(make_studio, finish_every_stage())
    view = await studio.relay_view()
    assert view["on"] is True and "Builder" in view["team"]
    assert [s["repo"] for s in view["stages"]][:5] == FIRST_FIVE
    volt = view["stages"][0]
    assert len(volt["agents"]) >= 150 and volt["mode"] == "always"

    # The page sends the whole list: two repos first, the rest switched off.
    front = [
        {
            "repo": "crewAIInc/crewAI",
            "mode": "always",
            "agent": "crewAI Content Editor",
        },
        {
            "repo": "VoltAgent/awesome-claude-code-subagents",
            "mode": "always",
            "agent": "ui-designer",
        },
    ]
    rest = [
        {"repo": s["repo"], "mode": "off"}
        for s in view["stages"]
        if s["repo"] not in {f["repo"] for f in front}
    ]
    stages = front + rest
    saved = await studio.save_relay({"stages": stages, "first": "Helper"})
    assert [s["repo"] for s in saved["stages"]] == [s["repo"] for s in stages]
    plan = await studio.start_relay(BAKERY)
    assert [s.agent for s in plan.steps] == [
        "Helper",
        "crewAI Content Editor",
        "ui-designer",
    ]
    await studio.stop_plan(plan.id)

    with pytest.raises(Exception, match="has no agent or skill"):
        await studio.save_relay(
            {"stages": [{"repo": "crewAIInc/crewAI", "agent": "Wizard"}]}
        )
    with pytest.raises(Exception, match="No repo called"):
        await studio.save_relay({"stages": [{"repo": "nobody/nothing"}]})
    with pytest.raises(Exception, match="No LCC agent"):
        await studio.save_relay({"first": "frontend-developer"})


@pytest.mark.asyncio
async def test_jarvis_sends_new_websites_through_the_relay_while_it_is_on(make_studio):
    studio, _ = await with_repos(make_studio, finish_every_stage())

    await studio.main_say(BAKERY, background=False)
    relays = await studio.plans()
    assert [p.kind for p in relays] == ["relay"] and relays[0].goal == BAKERY
    await studio.stop_plan(relays[0].id)

    await studio.save_relay({"on": False})
    await studio.main_say("make a website for my gym", background=False)
    assert len(await studio.plans()) == 1, "off: the Builder takes it the usual way"
    await studio.main_say("relay: make a website for my gym", background=False)
    newest = (await studio.plans())[0]
    assert newest.kind == "relay" and newest.goal == "make a website for my gym"
    await studio.stop_plan(newest.id)


@pytest.mark.asyncio
async def test_without_repos_a_website_goes_the_usual_way(make_studio):
    studio, _ = make_studio(finish_every_stage())
    await studio.ensure_defaults()
    await studio.main_say(BAKERY, background=False)
    assert await studio.plans() == ()
    with pytest.raises(Exception, match="No repo in the relay"):
        await studio.start_relay(BAKERY)


@pytest.mark.asyncio
async def test_the_relay_routes(make_studio):
    studio, _ = await with_repos(make_studio, finish_every_stage())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    ) as client:
        view = (await client.get("/studio/api/relay")).json()
        assert view["stages"][0]["repo"] == FIRST_FIVE[0]
        off = await client.put("/studio/api/relay", json={"on": False})
        assert off.status_code == 200 and off.json()["on"] is False
        bad = await client.put("/studio/api/relay", json={"first": "Nobody"})
        assert bad.status_code == 400
        started = await client.post("/studio/api/relay", json={"goal": BAKERY})
        assert started.status_code == 202
        assert started.json()["kind"] == "relay" and len(started.json()["steps"]) == 7
        await studio.stop_plan(started.json()["id"])

        # Other AI tools start one through LCC's MCP server.
        call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "lcc_relay",
                "arguments": {"goal": "build a snake game"},
            },
        }
        answer = (await client.post("/mcp", json=call)).json()["result"]
        text = answer["content"][0]["text"]
        assert not answer["isError"] and "stage(s), in order:" in text
        assert "1. Coder" in text and "game-developer (VoltAgent/" in text
        await studio.stop_plan(text.split("Relay ")[1].split(" ")[0])
