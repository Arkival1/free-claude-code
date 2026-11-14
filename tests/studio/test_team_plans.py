"""Team plans: a job split into steps for the team, run in order with each
agent handed what the steps before it produced."""

import asyncio

import httpx
import pytest

from free_claude_code.studio.models import (
    Agent,
    AgentRun,
    Chat,
    PlanStep,
    TeamPlan,
)
from free_claude_code.studio.service import INTERRUPTED_PLAN_NOTE
from free_claude_code.studio.teamplan import (
    PLANNER_SYSTEM,
    PlanCoordinator,
    PlanError,
    parse_plan,
    ready_steps,
    skip_blocked,
)
from tests.api.support import create_test_app

from .conftest import tool_reply

TEAM = ["Researcher", "Builder", "Tester", "Helper"]
PLAN = (
    '{"steps": ['
    '{"id": "a", "agent": "Researcher", "do": "Find what Joe\'s Bakery sells", "needs": []},'
    '{"id": "b", "agent": "the Builder", "do": "Build the bakery page", "needs": ["a"]},'
    '{"id": "c", "agent": "Tester", "do": "Test the page", "needs": ["b"]}'
    "]}"
)


def test_a_plan_is_read_and_checked():
    steps = parse_plan(f"Here you go:\n```json\n{PLAN}\n```", TEAM)
    assert [(s.id, s.agent, s.needs) for s in steps] == [
        ("s1", "Researcher", ()),
        ("s2", "Builder", ("s1",)),
        ("s3", "Tester", ("s2",)),
    ]
    # Unknown agents are dropped, and a step can only need steps before it.
    odd = parse_plan(
        '[{"id": "x", "agent": "Wizard", "do": "magic"},'
        ' {"id": "y", "agent": "Helper", "do": "plan it", "needs": ["z", "y"]},'
        ' {"id": "z", "agent": "Builder", "do": "build", "needs": ["y"]}]',
        TEAM,
    )
    assert [(s.agent, s.needs) for s in odd] == [("Helper", ()), ("Builder", ("s1",))]
    for bad in ("no json here", '{"steps": []}', '[{"agent": "Wizard", "do": "x"}]'):
        with pytest.raises(PlanError):
            parse_plan(bad, TEAM)


def test_steps_wait_for_what_they_need_and_skip_when_it_fails():
    plan = TeamPlan(
        goal="g",
        steps=(
            PlanStep(id="s1", agent="Researcher", do="find"),
            PlanStep(id="s2", agent="Helper", do="ideas"),
            PlanStep(id="s3", agent="Builder", do="build", needs=("s1",)),
            PlanStep(id="s4", agent="Tester", do="test", needs=("s3",)),
        ),
    )
    assert [s.id for s in ready_steps(plan)] == ["s1", "s2"]
    failed = plan.model_copy(
        update={
            "steps": (
                plan.steps[0].model_copy(update={"status": "failed"}),
                *plan.steps[1:],
            )
        }
    )
    skipped = skip_blocked(failed)
    assert [s.status for s in skipped.steps] == [
        "failed",
        "waiting",
        "skipped",
        "skipped",
    ]
    assert "s1 didn't finish" in skipped.steps[2].result


def _team_replies(seen: list[str]):
    def respond(system: str, prompt: str):
        if system == PLANNER_SYSTEM:
            return PLAN
        seen.append(prompt)
        if "Your step (s1)" in prompt:
            return tool_reply(
                "finish", {"summary": "Joe's Bakery sells sourdough and rye."}
            )
        if "Your step (s2)" in prompt:
            return tool_reply("finish", {"summary": "Built index.html with prices."})
        if "Your step (s3)" in prompt:
            return tool_reply("finish", {"summary": "Verdict: works."})
        return "On it."

    return respond


@pytest.mark.asyncio
async def test_the_team_runs_a_plan_in_order_and_reports(make_studio):
    seen: list[str] = []
    studio, _ = make_studio(_team_replies(seen))
    await studio.ensure_defaults()
    chat = await studio.main_chat()

    plan = await studio.start_plan(
        "Make a website for Joe's Bakery", made_by="you", chat_id=chat.id
    )
    await asyncio.wait_for(studio.wait_for_background(), timeout=20)

    finished = await studio.plan(plan.id)
    assert finished.status == "done", finished.summary
    assert [s.status for s in finished.steps] == ["done", "done", "done"]
    # Each agent got the whole plan, its own step, and what came before it.
    builder_brief = next(p for p in seen if "Your step (s2)" in p)
    assert "The whole job: Make a website for Joe's Bakery" in builder_brief
    assert "s1 (Researcher): Joe's Bakery sells sourdough and rye." in builder_brief
    assert "s3. Tester: Test the page [waiting]" in builder_brief
    # They took turns: research, then build, then test.
    order = [p.split("Your step (")[1][:2] for p in seen if "Your step (" in p]
    assert order == ["s1", "s2", "s3"]
    # Every step worked in one project, and the plan reported where asked.
    runs = await studio.runs()
    assert finished.site_id and {r.site_id for r in runs} == {finished.site_id}
    report = (await studio.transcript(chat.id))[-1]
    assert report.data.get("kind") == "plan_finished"
    assert "3 of 3 step(s) done" in report.text and "Verdict: works." in report.text


@pytest.mark.asyncio
async def test_a_failed_step_skips_only_what_needs_it(make_studio):
    def respond(system: str, prompt: str):
        if system == PLANNER_SYSTEM:
            return (
                '{"steps": [{"agent": "Researcher", "do": "find prices"},'
                ' {"agent": "Helper", "do": "write a tagline"},'
                ' {"id": "s3", "agent": "Builder", "do": "build", "needs": ["s1"]}]}'
            )
        if "Your step (s1)" in prompt:
            raise RuntimeError("the web is down")
        return tool_reply("finish", {"summary": "Fresh bread, every day."})

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    plan = await studio.start_plan("Prices and a tagline for the bakery")
    await asyncio.wait_for(studio.wait_for_background(), timeout=20)

    finished = await studio.plan(plan.id)
    assert finished.status == "failed"
    assert [s.status for s in finished.steps] == ["failed", "done", "skipped"]
    assert "1 of 3 step(s) done" in finished.summary


class _Host:
    """A team where the Builder is busy with other work for a while."""

    def __init__(self, team: list[Agent]) -> None:
        self.team = team
        self.busy = {team[0].id}
        self.started: list[str] = []
        self.checks = 0

    async def agents(self) -> tuple[Agent, ...]:
        return tuple(self.team)

    async def busy_agent_ids(self) -> set[str]:
        self.checks += 1
        if self.checks > 2:
            self.busy.clear()
        return set(self.busy)

    async def project_files(self, site_id: str) -> dict[str, str]:
        return {}

    async def load_member(self, repo: str, name: str):
        return None

    async def unload_members(self, agent_ids) -> None:
        return None

    async def run_agent_task(self, agent, goal, *, site_id, parent_chat_id):
        self.started.append(agent.name)
        run = AgentRun(agent_id=agent.id, chat_id="c", goal=goal, status="succeeded")
        return run.model_copy(update={"result": f"{agent.name} done"}), Chat(
            title="t", agent_id=agent.id
        )


@pytest.mark.asyncio
async def test_a_step_waits_for_an_agent_busy_with_other_work(store):
    builder = Agent(name="Builder", role="builder", model="m")
    tester = Agent(name="Tester", role="tester", model="m")
    host = _Host([builder, tester])
    plan = TeamPlan(
        goal="g",
        steps=(
            PlanStep(id="s1", agent="Builder", do="build"),
            PlanStep(id="s2", agent="Tester", do="test the old page"),
        ),
    )
    await store.put(plan)

    done = await PlanCoordinator(store=store, host=host, wait_seconds=0.01).run(plan.id)

    assert done.status == "done"
    # The Tester started at once; the Builder only when its other job ended.
    assert host.started == ["Tester", "Builder"]
    assert host.checks >= 3


@pytest.mark.asyncio
async def test_a_plan_can_be_stopped_and_resumed(make_studio):
    working = asyncio.Event()

    async def respond(system: str, prompt: str):
        if system == PLANNER_SYSTEM:
            return '[{"agent": "Researcher", "do": "dig deep"}, {"agent": "Helper", "do": "sum up", "needs": ["s1"]}]'
        if "Your step (s1)" in prompt and not working.is_set():
            working.set()
            await asyncio.Event().wait()  # a slow model, mid-answer
        return tool_reply("finish", {"summary": "Done."})

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    plan = await studio.start_plan("Look into sourdough starters")
    await asyncio.wait_for(working.wait(), timeout=10)

    stopped = await studio.stop_plan(plan.id)
    assert stopped.status == "stopped"
    assert [s.status for s in stopped.steps] == ["stopped", "stopped"]

    await studio.resume_plan(plan.id)
    await asyncio.wait_for(studio.wait_for_background(), timeout=20)
    resumed = await studio.plan(plan.id)
    assert resumed.status == "done"
    assert [s.status for s in resumed.steps] == ["done", "done"]


@pytest.mark.asyncio
async def test_a_plan_cut_off_by_closing_studio_can_be_resumed(make_studio):
    studio, _ = make_studio(
        lambda system, prompt: tool_reply("finish", {"summary": "ok"})
    )
    await studio.ensure_defaults()
    plan = TeamPlan(
        goal="Old job",
        steps=(
            PlanStep(id="s1", agent="Researcher", do="find", status="done", result="x"),
            PlanStep(id="s2", agent="Helper", do="sum up", status="running"),
        ),
        created_at=studio._started_at - 1000,
    )
    await studio._store.put(plan)

    await studio.end_interrupted_runs()
    closed = await studio.plan(plan.id)
    assert closed.status == "stopped" and INTERRUPTED_PLAN_NOTE in closed.summary
    assert [s.status for s in closed.steps] == ["done", "stopped"]

    await studio.resume_plan(plan.id)
    await asyncio.wait_for(studio.wait_for_background(), timeout=20)
    resumed = await studio.plan(plan.id)
    assert [s.status for s in resumed.steps] == ["done", "done"]
    assert resumed.steps[0].result == "x", "finished steps are kept"


@pytest.mark.asyncio
async def test_get_the_team_to_starts_a_plan_from_the_main_chat(make_studio):
    seen: list[str] = []
    replies = _team_replies(seen)

    def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            return "The team is on it."
        return replies(system, prompt)

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()

    chat = await studio.main_say(
        "Jarvis, get the team to make a website for Joe's Bakery", background=False
    )
    await asyncio.wait_for(studio.wait_for_background(), timeout=20)

    (plan,) = await studio.plans()
    assert plan.goal == "make a website for Joe's Bakery"
    assert plan.chat_id == chat.id and plan.status == "done"
    started = [m for m in await studio.transcript(chat.id) if m.author == "team_plan"]
    assert started and "Planned 3 step(s)" in started[0].text


@pytest.mark.asyncio
async def test_plans_through_the_routes(make_studio):
    studio, _ = make_studio(_team_replies([]))
    await studio.ensure_defaults()
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        started = await client.post("/studio/api/plans", json={"goal": "A bakery site"})
        assert started.status_code == 202, started.text
        plan_id = started.json()["id"]
        await asyncio.wait_for(studio.wait_for_background(), timeout=20)

        listed = (await client.get("/studio/api/plans")).json()["plans"]
        assert listed[0]["id"] == plan_id and listed[0]["done_steps"] == 3
        hq = (await client.get("/studio/api/hq")).json()
        assert hq["plans"][0]["id"] == plan_id
        missing = await client.get("/studio/api/plans/pln_nope")
        assert missing.status_code == 404
        empty = await client.post("/studio/api/plans", json={"goal": ""})
        assert empty.status_code == 422


@pytest.mark.asyncio
async def test_only_the_main_ai_plans_for_the_team(make_studio):
    from free_claude_code.studio.llm import ToolCall
    from free_claude_code.studio.tools import ToolContext

    studio, _ = make_studio([])
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    context = ToolContext(
        agent_id=builder.id,
        chat_id="cht_x",
        agent_name="Builder",
        agent_role="builder",
    )
    with pytest.raises(ValueError, match="Only the main AI"):
        await studio._assistant_tool(
            ToolCall(id="t", name="team_plan", arguments={"goal": "everything"}),
            context,
        )
