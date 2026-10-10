"""Team plans: one job split into steps, each owned by one agent, run in order.

The planner (the main AI's model) reads the job and the team and writes the
steps: who does what, and which steps must finish first. The coordinator then
runs every step whose inputs are ready: steps for different agents at the same
time, never two at once for one agent, and never a step for an agent that is
busy with something else (it waits for them). Each agent gets the whole plan,
its own step, and what the steps it builds on produced, and every step works
in the same project. A failed step skips the steps that need it; the others
still run. The plan is kept, so the HQ shows it live, and one cut off by
closing Studio can be resumed where it stopped.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from .models import Agent, AgentRun, Chat, PlanStep, TeamPlan, now_ms
from .orders import pick_agent
from .store import StudioStore

MAX_STEPS = 8
MAX_STEP_WORDS = 600
HANDOFF_CHARS = 1500
"""How much of a finished step's result the next agent is handed."""
RESULT_CHARS = 4000
PARALLEL_STEPS = 2
"""Steps run at once; a local model answers one at a time anyway."""
WAIT_SECONDS = 5.0
"""How often a plan waiting for a busy agent looks again."""
FINISHED = frozenset({"done", "failed", "skipped", "stopped"})
CHANGES_SHOWN = 12
"""Files named in a relay stage's changes line; the rest are counted."""

PLANNER_SYSTEM = (
    "You plan work for a team of AI agents. Split the job into as few steps as "
    "it needs: 2 or 3 for a small job, up to 6 for a big one. Each step is done "
    "by one agent from the team list, chosen by its role: finding things out "
    "goes to the researcher, writing, ideas, and planning to the helper, "
    "websites to the builder, apps and code to the coder, checking work to the "
    "tester. A step that uses another step's result lists that step's id in "
    '"needs"; steps that do not need each other run at the same time. Make '
    "each step concrete: what to find, write, make, or check, and what to hand "
    "on. The last step finishes the job. Reply with JSON only, like:\n"
    '{"steps": [{"id": "s1", "agent": "Researcher", "do": "Find ...", '
    '"needs": []}, {"id": "s2", "agent": "Builder", "do": "Build ... using '
    'what s1 found", "needs": ["s1"]}]}'
)


class PlanError(ValueError):
    """A plan couldn't be made from what the planner wrote."""


@dataclass(frozen=True, slots=True)
class Member:
    name: str
    role: str
    what: str = ""


def planner_prompt(goal: str, team: Sequence[Member], project: str = "") -> str:
    lines = [f"The job: {goal.strip()}"]
    if project:
        lines.append(f"Everyone works in the project '{project}'.")
    lines.append("The team:")
    lines += [f"- {m.name} ({m.role}){': ' + m.what if m.what else ''}" for m in team]
    return "\n".join(lines)


def parse_plan(text: str, team: Sequence[str]) -> tuple[PlanStep, ...]:
    """The steps in the planner's reply, checked: known agents only, at most
    MAX_STEPS, and a step only needs steps before it (so nothing loops)."""
    raw = _json_in(text)
    items = raw.get("steps") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise PlanError("The plan had no steps.")
    names = {name.casefold(): name for name in team}
    renamed: dict[str, str] = {}
    steps: list[PlanStep] = []
    for item in items:
        if not isinstance(item, dict) or len(steps) >= MAX_STEPS:
            continue
        agent = names.get(
            re.sub(r"^the\s+", "", str(item.get("agent", "")).strip(), flags=re.I)
            .strip()
            .casefold()
        )
        do = " ".join(str(item.get("do") or item.get("task") or "").split())
        if agent is None or not do:
            continue
        step_id = f"s{len(steps) + 1}"
        renamed[str(item.get("id") or step_id)] = step_id
        needs = item.get("needs") or ()
        if isinstance(needs, str):
            needs = [needs]
        steps.append(
            PlanStep(
                id=step_id,
                agent=agent,
                do=" ".join(do.split()[:MAX_STEP_WORDS]),
                needs=tuple(
                    dict.fromkeys(
                        renamed[str(n)]
                        for n in needs
                        if str(n) in renamed and renamed[str(n)] != step_id
                    )
                ),
            )
        )
    if not steps:
        raise PlanError("None of the plan's steps had a team member and a job.")
    return tuple(steps)


def _json_in(text: str) -> object:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except ValueError:
                continue
    raise PlanError("The planner didn't write a plan.")


def one_step_plan(goal: str, team: Sequence[Member]) -> tuple[PlanStep, ...]:
    """When there is no usable plan: the whole job to the best fit."""
    agent = pick_agent(goal, [(m.name, m.role) for m in team])
    if not agent:
        raise PlanError("There is nobody on the team to do this.")
    return (PlanStep(id="s1", agent=agent, do=goal.strip()),)


def with_step(plan: TeamPlan, step_id: str, **changes: object) -> TeamPlan:
    steps = tuple(
        step.model_copy(update=changes) if step.id == step_id else step
        for step in plan.steps
    )
    return plan.model_copy(update={"steps": steps, "updated_at": now_ms()})


def ready_steps(plan: TeamPlan) -> list[PlanStep]:
    """Waiting steps whose needed steps are all done; in a relay, all over
    (a stage that failed hands on what the stage before it made)."""
    over = {"done", "failed", "skipped"} if plan.kind == "relay" else {"done"}
    done = {step.id for step in plan.steps if step.status in over}
    return [
        step
        for step in plan.steps
        if step.status == "waiting" and all(need in done for need in step.needs)
    ]


def skip_blocked(plan: TeamPlan) -> TeamPlan:
    """Steps that need a step that can no longer finish are skipped (never in
    a relay: the next stage carries on from the work so far)."""
    if plan.kind == "relay":
        return plan
    changed = True
    while changed:
        changed = False
        lost = {
            step.id
            for step in plan.steps
            if step.status in {"failed", "skipped", "stopped"}
        }
        for step in plan.steps:
            if step.status == "waiting" and lost.intersection(step.needs):
                blocker = next(need for need in step.needs if need in lost)
                plan = with_step(
                    plan,
                    step.id,
                    status="skipped",
                    result=f"Skipped: {blocker} didn't finish.",
                    finished_at=now_ms(),
                )
                changed = True
    return plan


def file_changes(before: Mapping[str, str], after: Mapping[str, str]) -> str:
    """One line saying which project files a stage added, edited, or removed."""
    parts = [
        f"{path} (edited)"
        for path in after
        if path in before and before[path] != after[path]
    ]
    parts += [f"{path} (new)" for path in after if path not in before]
    parts += [f"{path} (removed)" for path in before if path not in after]
    if not parts:
        return "No project files changed."
    more = len(parts) - CHANGES_SHOWN
    return (
        "Files changed: "
        + ", ".join(parts[:CHANGES_SHOWN])
        + (f", and {more} more." if more > 0 else ".")
    )


def stage_name(step: PlanStep) -> str:
    return f"{step.agent} ({step.source})" if step.source else step.agent


def relay_brief(plan: TeamPlan, step: PlanStep) -> str:
    """What one stage of a relay is told: the job, the order, its own part,
    and what the stages before it reported."""
    index = next(i for i, s in enumerate(plan.steps) if s.id == step.id)
    lines = [
        f"You are stage {index + 1} of {len(plan.steps)} of a relay: the job "
        "passes from agent to agent, one at a time, and each builds on the work "
        "before it.",
        f"The job: {plan.goal}",
        "The relay:",
    ]
    for number, other in enumerate(plan.steps, 1):
        mark = "your stage" if other.id == step.id else other.status
        lines.append(f"  {number}. {stage_name(other)} [{mark}]")
    lines.append(f"Your part: {step.do}")
    before = [
        s for s in plan.steps[:index] if s.status in {"done", "failed"} and s.result
    ][-2:]
    if before:
        lines.append("What the stages before you reported:")
        for s in before:
            lines.append(f"- {stage_name(s)} [{s.status}]: {s.result[:HANDOFF_CHARS]}")
            if s.changes:
                lines.append(f"  {s.changes}")
    if index == 0:
        lines.append(
            "You go first: do the whole job. The stages after you will improve it."
        )
    else:
        lines.append(
            "Work on what is there: read the project first, keep what works, make "
            "it better your way, and fix anything broken. Don't start over or "
            "throw away the earlier stages' work: change files with edit_file "
            "rather than rewriting whole pages, and keep the page structure and "
            "the class names the stylesheet styles, so the design stays intact."
        )
    lines.append(
        "When you finish, say what you changed in your stage and anything the next "
        "stage should know. Report only your own work: don't copy the reports "
        "above, and if you changed nothing, say so."
    )
    return "\n".join(lines)


def step_brief(plan: TeamPlan, step: PlanStep) -> str:
    """What the agent doing one step is told: the job, the whole plan, its
    own step, and what the steps it builds on produced."""
    if plan.kind == "relay":
        return relay_brief(plan, step)
    lines = [
        "You are doing one step of a team plan.",
        f"The whole job: {plan.goal}",
        "The plan:",
    ]
    for other in plan.steps:
        mark = "your step" if other.id == step.id else other.status
        lines.append(f"  {other.id}. {other.agent}: {other.do} [{mark}]")
    lines.append(f"Your step ({step.id}): {step.do}")
    inputs = [s for s in plan.steps if s.id in step.needs and s.result]
    if inputs:
        lines.append("What the steps before yours produced:")
        lines += [f"- {s.id} ({s.agent}): {s.result[:HANDOFF_CHARS]}" for s in inputs]
    lines.append(
        "Do your step only; the others do theirs. When you finish, say what you "
        "made or found and anything the next steps need."
    )
    return "\n".join(lines)


def summary(plan: TeamPlan) -> str:
    done = sum(step.status == "done" for step in plan.steps)
    verdict = {
        "done": "is done",
        "failed": "finished with problems",
        "stopped": "was stopped",
        "running": "is still running",
    }[plan.status]
    what = "relay" if plan.kind == "relay" else "team plan"
    unit = "stage(s)" if plan.kind == "relay" else "step(s)"
    lines = [
        f"The {what} '{plan.goal[:120]}' {verdict}: {done} of "
        f"{len(plan.steps)} {unit} done."
    ]
    for number, step in enumerate(plan.steps, 1):
        first = step.result.strip().splitlines()[0][:160] if step.result.strip() else ""
        label = (
            f"{number}. {stage_name(step)}"
            if plan.kind == "relay"
            else f"{step.id} {step.agent}"
        )
        lines.append(
            f"- {label} [{step.status}] {step.do[:80]}"
            + (f" → {first}" if first else "")
            + (f" ({step.changes})" if step.changes else "")
        )
    last = next(
        (s for s in reversed(plan.steps) if s.status == "done" and s.result), None
    )
    if last is not None:
        lines.append(f"\nFinal result ({last.agent}):\n{last.result[:RESULT_CHARS]}")
    return "\n".join(lines)


def plan_started(plan: TeamPlan, project: str = "") -> str:
    """What the main AI tells the user when a plan starts."""
    if plan.kind == "relay":
        lines = [
            f"Relay started: the job goes through {len(plan.steps)} stages, one "
            "after another:"
        ]
        lines += [
            f"{number}. {stage_name(step)}" for number, step in enumerate(plan.steps, 1)
        ]
        if project:
            lines.append(f"Project: {project}")
        lines.append(
            "Each stage builds on the last. Watch it in the HQ; the final result "
            "comes here when the last stage is done."
        )
        return "\n".join(lines)
    lines = [f"Planned {len(plan.steps)} step(s); the team is on it:"]
    for step in plan.steps:
        after = f" (after {', '.join(step.needs)})" if step.needs else ""
        lines.append(f"{step.id}. {step.agent}: {step.do}{after}")
    if project:
        lines.append(f"Project: {project}")
    lines.append(
        "It runs in the background (watch it in the HQ) and reports here when done."
    )
    return "\n".join(lines)


class PlanHost(Protocol):
    async def agents(self) -> tuple[Agent, ...]: ...

    async def run_agent_task(
        self,
        agent: Agent,
        goal: str,
        *,
        site_id: str | None,
        parent_chat_id: str | None,
    ) -> tuple[AgentRun, Chat]: ...

    async def busy_agent_ids(self) -> set[str]: ...

    async def project_files(self, site_id: str) -> dict[str, str]:
        """Each file in the project and a hash of its bytes."""
        ...


class PlanCoordinator:
    """Runs one plan's steps in order, as many at once as is safe."""

    def __init__(
        self,
        *,
        store: StudioStore,
        host: PlanHost,
        parallel: int = PARALLEL_STEPS,
        wait_seconds: float = WAIT_SECONDS,
        finished: Callable[[TeamPlan], Awaitable[None]] | None = None,
    ) -> None:
        self._store = store
        self._host = host
        self._parallel = max(1, parallel)
        self._wait = wait_seconds
        self._finished = finished
        self._files_before: dict[str, dict[str, str]] = {}
        """Relay stage id -> the project's files when that stage started."""

    async def run(self, plan_id: str) -> TeamPlan:
        running: dict[asyncio.Future[tuple[AgentRun, Chat]], str] = {}
        try:
            while True:
                plan = await self._store.require(TeamPlan, plan_id)
                if plan.status != "running":
                    break
                plan = await self._start_ready(plan, running)
                plan = skip_blocked(plan)
                await self._store.put(plan)
                if not running:
                    if not any(step.status == "waiting" for step in plan.steps):
                        break
                    # Steps wait for an agent busy with other work.
                    await asyncio.sleep(self._wait)
                    continue
                done, _ = await asyncio.wait(
                    running, timeout=self._wait, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    await self._record(plan_id, running.pop(task), task)
            return await self._finish(plan_id)
        except asyncio.CancelledError:
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)
            plan = await self._store.require(TeamPlan, plan_id)
            for step in plan.steps:
                if step.status in {"running", "waiting"}:
                    plan = with_step(
                        plan, step.id, status="stopped", finished_at=now_ms()
                    )
            plan = plan.model_copy(update={"status": "stopped", "updated_at": now_ms()})
            plan = plan.model_copy(update={"summary": summary(plan)})
            await self._store.put(plan)
            raise

    async def _start_ready(
        self,
        plan: TeamPlan,
        running: dict[asyncio.Future[tuple[AgentRun, Chat]], str],
    ) -> TeamPlan:
        team = {
            a.name.casefold(): a for a in await self._host.agents() if not a.archived
        }
        busy = await self._host.busy_agent_ids()
        mine = {
            step.agent.casefold() for step in plan.steps if step.status == "running"
        }
        for step in ready_steps(plan):
            if len(running) >= self._parallel:
                break
            agent = team.get(step.agent.casefold())
            if agent is None:
                plan = with_step(
                    plan,
                    step.id,
                    status="failed",
                    result=f"{step.agent} isn't on the team any more.",
                    finished_at=now_ms(),
                )
                continue
            if step.agent.casefold() in mine or agent.id in busy:
                continue
            plan = with_step(plan, step.id, status="running", started_at=now_ms())
            await self._store.put(plan)
            if plan.kind == "relay" and plan.site_id:
                files = await self._project_files(plan.site_id)
                if files is not None:
                    self._files_before[step.id] = files
            task = asyncio.ensure_future(
                self._host.run_agent_task(
                    agent,
                    step_brief(plan, step),
                    site_id=plan.site_id,
                    parent_chat_id=plan.chat_id,
                )
            )
            running[task] = step.id
            mine.add(step.agent.casefold())
        return plan

    async def _record(
        self, plan_id: str, step_id: str, task: asyncio.Future[tuple[AgentRun, Chat]]
    ) -> None:
        changes = await self._changes(plan_id, step_id)
        plan = await self._store.require(TeamPlan, plan_id)
        if changes:
            plan = with_step(plan, step_id, changes=changes)
        try:
            run, _ = task.result()
        except asyncio.CancelledError:
            plan = with_step(plan, step_id, status="stopped", finished_at=now_ms())
        except Exception as error:  # a step's crash is that step's failure
            logger.warning("Studio: plan step {} crashed: {}", step_id, error)
            plan = with_step(
                plan,
                step_id,
                status="failed",
                result=f"It crashed: {error}"[:RESULT_CHARS],
                finished_at=now_ms(),
            )
        else:
            status = {"succeeded": "done", "cancelled": "stopped"}.get(
                run.status, "failed"
            )
            plan = with_step(
                plan,
                step_id,
                status=status,
                result=(run.result or run.error or "").strip()[:RESULT_CHARS],
                run_id=run.id,
                finished_at=now_ms(),
            )
        await self._store.put(plan)

    async def _project_files(self, site_id: str) -> dict[str, str] | None:
        try:
            return await self._host.project_files(site_id)
        except Exception as error:  # the relay goes on without the changes line
            logger.warning("Studio: couldn't list project {}: {}", site_id, error)
            return None

    async def _changes(self, plan_id: str, step_id: str) -> str:
        """What a relay stage changed in the project, from the files themselves,
        so a stage that only repeats the last report shows that it did nothing."""
        before = self._files_before.pop(step_id, None)
        if before is None:
            return ""
        plan = await self._store.require(TeamPlan, plan_id)
        after = await self._project_files(plan.site_id or "")
        return "" if after is None else file_changes(before, after)

    async def _finish(self, plan_id: str) -> TeamPlan:
        plan = skip_blocked(await self._store.require(TeamPlan, plan_id))
        if plan.status == "running":
            ok = all(step.status == "done" for step in plan.steps)
            plan = plan.model_copy(update={"status": "done" if ok else "failed"})
        plan = plan.model_copy(
            update={"summary": summary(plan), "updated_at": now_ms()}
        )
        await self._store.put(plan)
        if self._finished is not None:
            await self._finished(plan)
        return plan
