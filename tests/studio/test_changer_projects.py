"""Update projects: the Changer plans, waits for approval when it should,
builds each milestone, checks it, has a different agent review it, keeps
checkpoints, pauses on budget or a broken model, and packs a scanned zip."""

import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from free_claude_code.core.json_types import JsonObject, JsonValue
from free_claude_code.studio.changer import Changer, ChangerError
from free_claude_code.studio.changer_projects import (
    Checkpoints,
    PlanError,
    needs_approval,
    overlapping,
    protected_files,
    read_plan,
    scan,
)
from free_claude_code.studio.llm import LLMReply, ToolCall
from free_claude_code.studio.models import ChangeProject
from free_claude_code.studio.tools import ToolContext

from .conftest import tool_reply
from .test_changer import make_app

LAB = "src/free_claude_code/studio/lab.py"


def quick_plan(**extra: JsonValue) -> JsonObject:
    return {
        "action": "plan",
        "size": "quick",
        "kind": "UI improvement",
        "summary": "Make the Lab say bubbles.",
        "files": [LAB],
        "milestones": [
            {"title": "Bubbles", "goal": "Lab returns bubbles", "files": [LAB]}
        ],
        **extra,
    }


def team(
    plan: JsonObject,
    *,
    verdicts: list[str] | None = None,
    ping_fails: bool = False,
    new_text: str = "'bubbles'",
) -> Callable[[str, str], object]:
    """A scripted team: Planner, builder (the Changer) and reviewers."""
    steps: dict[str, list[object]] = {
        "planner": [tool_reply("fcc_changer", plan), LLMReply(text="Planned.")],
        "builder": [],
        "reviewer": [],
    }
    for verdict in verdicts or ["pass"]:
        steps["reviewer"] += [
            tool_reply(
                "fcc_changer",
                {
                    "action": "review",
                    "verdict": verdict,
                    "findings": []
                    if verdict == "pass"
                    else [{"problem": "returns fizz", "where": LAB}],
                },
            ),
            LLMReply(text="Reviewed."),
        ]
    builds = 0

    def respond(system: str, prompt: str) -> object:
        nonlocal builds
        if prompt == "Reply with the word OK.":
            if ping_fails:
                raise RuntimeError("no such model")
            return LLMReply(text="OK")
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Changer")
        if "Changer's Planner" in system:
            return (
                steps["planner"].pop(0) if steps["planner"] else LLMReply(text="Done.")
            )
        if "Reviewer" in system:
            return (
                steps["reviewer"].pop(0)
                if steps["reviewer"]
                else LLMReply(text="Done.")
            )
        if "You are the Changer" in system:
            builds += 1
            if builds % 2 == 1:
                return tool_reply(
                    "edit_file",
                    {"path": LAB, "old_text": "'fizz'", "new_text": new_text},
                    call_id=f"edit{builds}",
                )
            return LLMReply(text="Built and checked.")
        return LLMReply(text="Done.")

    return respond


def wire(studio, tmp_path: Path) -> Path:
    source = make_app(tmp_path / "fcc")
    studio._changer = Changer(
        tmp_path / "changer", source=source, import_check="print('ok')"
    )
    return source


async def settle(studio) -> ChangeProject:
    driver = studio._changer_driver
    if driver is not None:
        await driver
    project = await studio._change_project()
    assert project is not None
    return project


def test_plans_are_checked_and_sized():
    plan = read_plan(quick_plan())
    milestones = plan["milestones"]
    assert plan["size"] == "quick"
    assert isinstance(milestones, list) and len(milestones) == 1
    assert not needs_approval(plan)
    two = read_plan(
        {
            "size": "quick",
            "milestones": [
                {"title": "A", "goal": "a"},
                {"title": "B", "goal": "b"},
            ],
        }
    )
    assert two["size"] == "project" and needs_approval(two)
    trading = read_plan(
        quick_plan(files=["src/free_claude_code/studio/trading/desk.py"])
    )
    assert protected_files(trading) and needs_approval(trading)
    vague = read_plan({"suggestions": [{"title": "Dark mode", "why": "eyes"}] * 5})
    suggestions = vague["suggestions"]
    assert isinstance(suggestions, list) and len(suggestions) == 3
    assert not vague["milestones"]
    with pytest.raises(PlanError):
        read_plan({"milestones": [{"title": "A", "goal": "a", "files": ["../x.py"]}]})
    with pytest.raises(PlanError):
        read_plan({})
    assert overlapping([["a.py", "b.py"]], ["b.py", "c.py"]) == ["b.py"]


def test_checkpoints_put_the_copy_back_exactly(tmp_path):
    source = make_app(tmp_path / "fcc")
    changer = Changer(tmp_path / "changer", source=source, import_check="print('ok')")
    target = tmp_path / "copy"
    changer.make_copy(target)
    points = Checkpoints(tmp_path / "points", source=source)
    (target / LAB).write_text("def mix():\n    return 'one'\n")
    first = points.save(target, changer.baseline(), "one")
    (target / LAB).write_text("def mix():\n    return 'two'\n")
    (target / "src/free_claude_code/studio/new.py").write_text("X = 1\n")
    (target / "CLAUDE.md").unlink()
    assert points.restore(target, str(first["id"])) >= 3
    assert "one" in (target / LAB).read_text()
    assert not (target / "src/free_claude_code/studio/new.py").exists()
    assert (target / "CLAUDE.md").read_text() == "Rules.\n"
    with pytest.raises(ChangerError):
        points.restore(target, "../../etc")


def test_the_security_scan_flags_only_new_risky_lines(tmp_path):
    source = make_app(tmp_path / "fcc")
    copy = tmp_path / "copy"
    Changer(tmp_path / "c", source=source).make_copy(copy)
    (copy / LAB).write_text(
        "def mix():\n    return 'fizz'\n"
        "KEY = 'nvapi-abcdefghijklmnopqrstuvwxyz123456'\n"
        "eval(user_text)\n"
        "requests.get('https://evil.example.net/x', verify=False)\n"
    )
    hits = scan(copy, [LAB], known_hosts=frozenset({"github.com"}), source=source)
    joined = "\n".join(hits)
    assert "key or token" in joined and "eval/exec" in joined
    assert "certificate checks" in joined and "evil.example.net" in joined
    # The line that was already there isn't flagged.
    assert not any("line 2" in hit for hit in hits)


@pytest.mark.asyncio
async def test_a_quick_change_goes_from_request_to_a_reviewed_zip(
    make_studio, tmp_path
):
    studio, _ = make_studio(team(quick_plan()))
    source = wire(studio, tmp_path)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "awaiting_release", project.note
    assert project.size == "quick" and project.milestone == 1
    kinds = [task["kind"] for task in project.tasks]
    assert kinds == ["plan", "build", "review"]
    reviewers = {task["agent"] for task in project.tasks if task["kind"] == "review"}
    builders = {task["agent"] for task in project.tasks if task["kind"] == "build"}
    assert reviewers and not reviewers & builders  # never reviews its own work
    milestones = project.plan["milestones"]
    assert isinstance(milestones, list)
    milestone = milestones[0]
    assert isinstance(milestone, dict) and milestone["status"] == "done"
    assert len(project.checkpoints) == 2
    assert "fizz" in (source / LAB).read_text()  # the running app is untouched
    made = await studio.changer_package("")
    assert str(made["name"]).startswith("FCC-Studio-update-6.75.1-")
    done = await studio._change_project()
    assert done is not None and done.status == "done"
    with zipfile.ZipFile(studio._changer.update_file(str(made["name"]))) as archive:
        report = archive.read("fcc/_update/6.75.1/TEST-REPORT.md").decode()
    assert "Bubbles: done" in report and "Not tested" in report


@pytest.mark.asyncio
async def test_big_projects_wait_for_approval_and_reviews_send_work_back(
    make_studio, tmp_path
):
    plan = quick_plan(
        size="project",
        milestones=[
            {"title": "Bubbles", "goal": "Lab returns bubbles", "files": [LAB]}
        ],
    )
    studio, _ = make_studio(team(plan, verdicts=["fail", "pass"]))
    wire(studio, tmp_path)
    await studio.changer_start("Rework the Lab")
    project = await settle(studio)
    assert project.status == "awaiting_plan" and "Approve" in project.note
    await studio.changer_act("approve")
    project = await settle(studio)
    assert project.status == "awaiting_release", project.note
    kinds = [task["kind"] for task in project.tasks]
    assert kinds == ["plan", "build", "review", "fix", "review"]
    made = await studio.changer_package("")
    assert made["version"] == "6.76.0"  # an update project bumps the minor


@pytest.mark.asyncio
async def test_vague_requests_get_suggestions_first(make_studio, tmp_path):
    vague: JsonObject = {
        "action": "plan",
        "suggestions": [
            {"title": "Dark mode", "why": "easier at night", "value": "high"},
            {"title": "Search", "why": "find things", "value": "medium"},
        ],
    }
    studio, _ = make_studio(team(vague))
    wire(studio, tmp_path)
    await studio.changer_start("make it better")
    project = await settle(studio)
    assert project.status == "choose"
    suggestions = project.plan["suggestions"]
    assert isinstance(suggestions, list)
    assert [s["title"] for s in suggestions if isinstance(s, dict)] == [
        "Dark mode",
        "Search",
    ]


@pytest.mark.asyncio
async def test_a_broken_model_or_spent_budget_pauses_with_a_reason(
    make_studio, tmp_path
):
    studio, _ = make_studio(team(quick_plan(), ping_fails=True))
    wire(studio, tmp_path)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "paused" and "didn't answer" in project.note

    studio2, _ = make_studio(team(quick_plan(size="project")))
    wire(studio2, tmp_path / "two")
    await studio2.changer_start("Rework the Lab", budget=1)
    project = await settle(studio2)
    await studio2.changer_act("approve")
    project = await settle(studio2)
    assert project.status == "paused" and "Ran out of budget" in project.note


@pytest.mark.asyncio
async def test_a_restart_pauses_and_rollback_restores(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan()))
    wire(studio, tmp_path)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    target = await studio._changer_target()
    assert "bubbles" in (target / LAB).read_text()
    before = next(
        p for p in project.checkpoints if str(p["label"]).startswith("Before")
    )
    await studio.changer_act("rollback", checkpoint=before["id"])
    project = await studio._change_project()
    assert project is not None and project.status == "paused"
    assert "fizz" in (target / LAB).read_text()
    # An interrupted project (FCC restarted mid-build) waits to be resumed.
    await studio._save_project(project, status="building")
    studio._changer_driver = None
    view = await studio.changer_view()
    shown = view["project"]
    assert isinstance(shown, dict) and shown["status"] == "paused"
    assert "Resume" in str(shown["note"])


@pytest.mark.asyncio
async def test_secrets_block_the_zip_until_confirmed(make_studio, tmp_path):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    await studio.changer_fresh_copy()
    target = await studio._changer_target()
    (target / LAB).write_text("TOKEN = 'ghp_abcdefghijklmnopqrstuvwxyz0123'\n")
    blocked = await studio.changer_package("")
    assert blocked["blocked"] is True and blocked["hits"]
    made = await studio.changer_package("", confirm=True)
    assert "name" in made


@pytest.mark.asyncio
async def test_only_the_right_agent_submits_and_helpers_own_their_files(
    make_studio, tmp_path
):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    copy = await studio.changer_fresh_copy()
    project = ChangeProject(
        request="x",
        status="building",
        tasks=[
            {"run_id": "r1", "chat_id": "c-build", "kind": "build", "files": []},
            {"run_id": "r2", "chat_id": "c-help", "kind": "helper", "files": []},
        ],
    )
    await studio._store.put(project)
    review = await studio._changer_tool(
        ToolCall(
            id="1",
            name="fcc_changer",
            arguments={"action": "review", "verdict": "pass"},
        ),
        ToolContext(agent_id="a", chat_id="c-build", site_id=copy.id),
    )
    assert review.failed and "reviewers" in review.text
    nested = await studio._changer_tool(
        ToolCall(
            id="2", name="fcc_changer", arguments={"action": "subagent", "task": "more"}
        ),
        ToolContext(agent_id="a", chat_id="c-help", site_id=copy.id),
    )
    assert nested.failed and "builder hands parts on" in nested.text
    packed = await studio._changer_tool(
        ToolCall(id="3", name="fcc_changer", arguments={"action": "package"}),
        ToolContext(agent_id="a", chat_id="c-build", site_id=copy.id),
    )
    assert packed.failed and "release step" in packed.text


@pytest.mark.asyncio
async def test_the_driver_never_undoes_the_owners_pause_or_cancel(
    make_studio, tmp_path
):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    project = ChangeProject(request="x", status="building")
    await studio._store.put(project)
    stale = project  # the driver's old copy
    await studio._save_project(project, owner=True, status="paused")
    await studio._save_project(project, owner=True, note="Paused by you.")
    kept = await studio._save_project(stale, status="building", note="driver")
    assert kept.status == "paused" and kept.note == "Paused by you."
    noted = await studio._save_project(stale, note="All milestones are built")
    assert noted.note == "Paused by you."
    await studio._save_project(kept, owner=True, status="cancelled")
    still = await studio._save_project(stale, status="awaiting_release")
    assert still.status == "cancelled"


@pytest.mark.asyncio
async def test_finished_projects_cant_be_restarted(make_studio, tmp_path):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    for status in ("done", "cancelled", "failed", "awaiting_release"):
        await studio._store.put(ChangeProject(request=status, status=status))
        with pytest.raises(Exception, match="finished"):
            await studio.changer_act("replan", feedback="again")


@pytest.mark.asyncio
async def test_resume_of_an_unapproved_plan_waits_for_approval(make_studio, tmp_path):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    plan = read_plan(quick_plan(size="project"))
    await studio._store.put(
        ChangeProject(request="x", status="paused", plan={**plan, "approved": False})
    )
    await studio.changer_act("resume")
    project = await studio._change_project()
    assert project is not None and project.status == "awaiting_plan"


@pytest.mark.asyncio
async def test_a_reviewer_that_cant_run_pauses_instead_of_spending_fixes(
    make_studio, tmp_path, monkeypatch
):
    studio, _ = make_studio(team(quick_plan()))
    wire(studio, tmp_path)
    real = studio._changer_model_problem

    async def reviewer_down(agent):
        if "Reviewer" in agent.name:
            return f"{agent.name}'s model didn't answer"
        return await real(agent)

    monkeypatch.setattr(studio, "_changer_model_problem", reviewer_down)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "paused" and "review couldn't run" in project.note
    assert [t["kind"] for t in project.tasks] == ["plan", "build"]  # no fix round


@pytest.mark.asyncio
async def test_resume_after_needs_you_gets_a_fresh_fix_budget(make_studio, tmp_path):
    studio, _ = make_studio(
        team(quick_plan(), verdicts=["fail", "fail", "fail", "pass"])
    )
    wire(studio, tmp_path)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    assert project.status == "paused" and "still has problems" in project.note
    await studio.changer_act("resume")
    project = await settle(studio)
    assert project.status == "awaiting_release", project.note


@pytest.mark.asyncio
async def test_resume_of_an_old_plan_without_the_approved_key_builds(
    make_studio, tmp_path, monkeypatch
):
    studio, _ = make_studio([])
    wire(studio, tmp_path)
    plan = read_plan(quick_plan(size="project"))
    plan.pop("approved", None)
    await studio._store.put(ChangeProject(request="x", status="paused", plan=plan))
    driven: list[str] = []
    monkeypatch.setattr(studio, "_drive", driven.append)
    await studio.changer_act("resume")
    assert driven  # resumed straight to building, no second approval


@pytest.mark.asyncio
async def test_rolling_back_a_finished_project_keeps_it_finished(make_studio, tmp_path):
    studio, _ = make_studio(team(quick_plan()))
    wire(studio, tmp_path)
    await studio.changer_start("Make the Lab say bubbles")
    project = await settle(studio)
    before = next(
        p for p in project.checkpoints if str(p["label"]).startswith("Before")
    )
    project = await studio._save_project(project, owner=True, status="done")
    plan = project.plan
    await studio.changer_act("rollback", checkpoint=before["id"])
    project = await studio._change_project()
    assert project is not None and project.status == "done"
    assert project.plan == plan and "Resume" not in project.note
    target = await studio._changer_target()
    assert "fizz" in (target / LAB).read_text()
    with pytest.raises(Exception, match="isn't paused"):
        await studio.changer_act("resume")
