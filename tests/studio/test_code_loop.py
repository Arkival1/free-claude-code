"""The Coder and the Tester take turns until the job works."""

import asyncio

import pytest

from free_claude_code.studio.code_loop import code_and_test, verdict
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import Agent, AgentRun
from free_claude_code.studio.orders import code_request

from .conftest import tool_reply


@pytest.mark.parametrize(
    ("report", "said"),
    [
        ("Verdict: works.\nFixed: nothing.", "works"),
        ("**Verdict: works with issues**\nBugs: 1. ...", "issues"),
        ("Verdict - broken\nBugs: 1. crash on start", "broken"),
        ("All good I think", "unknown"),
    ],
)
def test_the_testers_verdict_is_read(report, said):
    assert verdict(report) == said


@pytest.mark.parametrize(
    ("said", "job"),
    [
        ("code me a snake game", "code me a snake game"),
        ("jarvis can you build a todo app in python", "build a todo app in python"),
        (
            "write a python script that renames files",
            "write a python script that renames files",
        ),
        ("make a jarvis hud", "make a jarvis hud"),
        ("make me a website for my bakery", ""),
        ("make me a sandwich", ""),
    ],
)
def test_coding_jobs_are_told_from_websites(said, job):
    assert code_request(said, "Jarvis") == job


def _agent(name: str, role: str) -> Agent:
    return Agent.model_validate({"name": name, "role": role, "model": "m"})


@pytest.mark.asyncio
async def test_the_tester_hands_bugs_back_until_it_works():
    coder, tester = _agent("Coder", "coder"), _agent("Tester", "tester")
    reports = iter(
        [
            "Verdict: broken\nBugs: 1. app.py crashes on empty input.",
            "Verdict: works\nFixed: a typo.",
        ]
    )
    seen: list[tuple[str, str]] = []

    async def run(agent: Agent, task: str) -> AgentRun:
        seen.append((agent.name, task))
        result = next(reports) if agent.role == "tester" else "Coded it."
        return AgentRun.model_validate(
            {
                "agent_id": agent.id,
                "chat_id": "c",
                "goal": task,
                "status": "succeeded",
                "result": result,
            }
        )

    outcome = await code_and_test(
        coder=coder, tester=tester, goal="a todo app", project="Todo", run=run, rounds=3
    )

    assert [name for name, _ in seen] == ["Coder", "Tester", "Coder", "Tester"]
    assert "crashes on empty input" in seen[2][1], "the bugs go back to the Coder"
    assert outcome.verdict == "works" and len(outcome.rounds) == 2
    assert "Tester says it works." in outcome.summary("Coder", "Tester")


@pytest.mark.asyncio
async def test_the_rounds_stop_at_the_limit():
    coder, tester = _agent("Coder", "coder"), _agent("Tester", "tester")
    calls: list[str] = []

    async def run(agent: Agent, task: str) -> AgentRun:
        calls.append(agent.name)
        return AgentRun.model_validate(
            {
                "agent_id": agent.id,
                "chat_id": "c",
                "goal": task,
                "status": "succeeded",
                "result": "Verdict: broken" if agent.role == "tester" else "ok",
            }
        )

    outcome = await code_and_test(
        coder=coder, tester=tester, goal="x", project="X", run=run, rounds=2
    )
    assert calls == ["Coder", "Tester", "Coder", "Tester"]
    assert outcome.verdict == "broken"


@pytest.mark.asyncio
async def test_jarvis_hands_a_coding_job_to_the_coder_and_tester(make_studio):
    def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            return LLMReply(text="The Coder is on it.")
        if "Round 1: test" in prompt:
            return tool_reply("finish", {"summary": "Verdict: works\nFixed: nothing."})
        return tool_reply("finish", {"summary": "Built snake.py; run python snake.py."})

    studio, model = make_studio(respond)
    await studio.ensure_defaults()

    chat = await studio.main_say("code me a snake game in python", background=False)
    await studio.wait_for_background()

    coder = await studio.agent_by_name("Coder")
    tester = await studio.agent_by_name("Tester")
    assert coder is not None and tester is not None
    runs = sorted(await studio.runs(), key=lambda run: run.created_at)
    assert [run.agent_id for run in runs] == [coder.id, tester.id]
    assert all(run.site_id == runs[0].site_id for run in runs), "one project"
    said = [m for m in await studio.transcript(chat.id) if m.author == "code_and_test"]
    assert said and "Tester tests it" in said[0].text
    follow_up = next(
        c for c in reversed(model.calls) if "the user's main AI" in str(c["system"])
    )
    assert "Tester says it works." in str(follow_up["prompt"])


@pytest.mark.parametrize(
    ("goal", "name"),
    [
        (
            "Make a small web app called Tip Calculator: one index.html page",
            "Tip Calculator",
        ),
        ('build a site named "Joe Bakery" with prices', "Joe Bakery"),
        ("make an app called Budgeter that tracks money", "Budgeter"),
        ("code me a snake game in python", "Snake game in python"),
    ],
)
def test_a_project_is_named_as_the_user_named_it(goal, name):
    from free_claude_code.studio.code_loop import project_name

    assert project_name(goal) == name


@pytest.mark.asyncio
async def test_stop_in_the_hq_stops_a_coding_job_mid_round(make_studio):
    """The Tester's round runs inside the Coder/Tester job; Stop must reach it
    and end the job, not let the Coder start another round."""
    testing = asyncio.Event()

    async def respond(system: str, prompt: str):
        if "Round 1: test" in prompt:
            testing.set()
            await asyncio.Event().wait()  # a slow local model, mid-answer
        return tool_reply("finish", {"summary": "Built tips.html."})

    studio, model = make_studio(respond)
    await studio.ensure_defaults()
    tester = await studio.agent_by_name("Tester")
    assert tester is not None

    await studio.start_code_loop("code me a tip calculator", parent_chat_id=None)
    await asyncio.wait_for(testing.wait(), timeout=5)
    stopped = await studio.stop_agent_work(tester.id)
    await asyncio.wait_for(studio.wait_for_background(), timeout=5)

    assert [run.status for run in stopped] == ["cancelled"]
    runs = sorted(await studio.runs(), key=lambda run: run.created_at)
    assert [run.status for run in runs] == ["succeeded", "cancelled"]
    assert not any("Round 2" in str(call["prompt"]) for call in model.calls)
