"""The Changer team's shared notebook: every agent on an update (the Changer,
its reviewers, helpers, team agents, Aider) reads the goal and the notes
before each step and adds to them; FCC keeps the notebook, so a switch of
model or API loses nothing, and the HQ shows the update as it goes."""

import httpx
import pytest

from free_claude_code.studio.changer import Changer
from free_claude_code.studio.llm import LLMReply, ToolCall
from free_claude_code.studio.models import AgentRun, ChangeNote, ChangeProject
from free_claude_code.studio.tools import ToolContext
from tests.api.support import create_test_app
from tests.studio.test_changer import make_app

PLAN = {
    "summary": "Show the copy's file count on the Changer page.",
    "milestones": [
        {"title": "Add the count route", "status": "done"},
        {"title": "Show it on the page"},
        {"title": "Tests"},
    ],
}


async def project_for(studio, *, status: str = "building") -> ChangeProject:
    project = ChangeProject(
        request="Show how many files the copy has",
        status=status,
        plan=PLAN,
        milestone=1,
    )
    await studio._store.put(project)
    return project


async def notes_seen(studio, model, agent_name: str, model_id: str) -> str:
    agent = await studio.create_agent(
        name=agent_name, role="agent", model=model_id, tools=()
    )
    run = await studio.start_task(agent_id=agent.id, goal="BUILD milestone 2")
    job = studio._run_jobs.get(run.id)
    if job is not None:
        await job
    return str(model.calls[-1]["studio_note"])


def done(system: str, prompt: str) -> object:
    return LLMReply(text="Done.")


@pytest.mark.asyncio
async def test_every_step_reads_the_goal_plan_and_notes(make_studio):
    studio, model = make_studio(done)
    project = await project_for(studio)
    await studio.add_change_note(
        "Changer Planner", "The count lives in changer.py tree()", project=project
    )
    await studio.add_change_note("Owner", "Keep the old colours", kind="lesson")
    note = await notes_seen(studio, model, "Changer", "nvidia_nim/test-model")
    assert "CHANGER NOTEBOOK" in note
    assert "GOAL (the owner's words; keep to it): Show how many files" in note
    assert "Milestone 1 [done]: Add the count route" in note
    assert "Milestone 2 [NOW]: Show it on the page" in note
    assert "Milestone 3 [to do]: Tests" in note
    assert "[Changer Planner, finding] The count lives in changer.py tree()" in note
    assert "Lessons from earlier updates:" in note and "Keep the old colours" in note


@pytest.mark.asyncio
async def test_the_notebook_survives_a_switch_of_model(make_studio):
    studio, model = make_studio(done)
    project = await project_for(studio)
    await studio.add_change_note(
        "Changer", "route added in studio_routes.py", project=project
    )
    first = await notes_seen(studio, model, "Changer", "nvidia_nim/test-model")
    changer = next(a for a in await studio.agents() if a.name == "Changer")
    await studio._store.put(changer.model_copy(update={"model": "freellmapi/auto"}))
    run = await studio.start_task(agent_id=changer.id, goal="BUILD milestone 2")
    job = studio._run_jobs.get(run.id)
    if job is not None:
        await job
    second = str(model.calls[-1]["studio_note"])
    assert model.calls[-1]["model"] == "freellmapi/auto"
    assert "route added in studio_routes.py" in first
    assert "route added in studio_routes.py" in second


@pytest.mark.asyncio
async def test_agents_off_the_update_dont_get_the_notebook(make_studio):
    studio, model = make_studio(done)
    await project_for(studio)
    note = await notes_seen(studio, model, "Builder Bob", "nvidia_nim/test-model")
    assert "CHANGER NOTEBOOK" not in note


@pytest.mark.asyncio
async def test_notes_skip_repeats_and_lessons_are_capped(make_studio, monkeypatch):
    studio, _ = make_studio([])
    project = await project_for(studio)
    first = await studio.add_change_note("Changer", "same  text", project=project)
    again = await studio.add_change_note("Tester", "same text", project=project)
    assert first is not None and again is not None and first.id == again.id
    assert await studio.add_change_note("Changer", "   ", project=project) is None
    monkeypatch.setattr("free_claude_code.studio.service.MAX_LESSONS", 3)
    for number in range(5):
        await studio.add_change_note("Changer", f"lesson {number}", kind="lesson")
    lessons = await studio.change_notes("")
    assert [n.text for n in lessons] == ["lesson 2", "lesson 3", "lesson 4"]


@pytest.mark.asyncio
async def test_the_notebook_keeps_the_goal_when_notes_run_long(
    make_studio, monkeypatch
):
    studio, model = make_studio(done)
    monkeypatch.setattr("free_claude_code.studio.service.NOTEBOOK_CHARS", 1500)
    project = await project_for(studio)
    for number in range(16):
        await studio.add_change_note(
            "Changer", f"note {number} " + "x" * 200, project=project
        )
    note = await notes_seen(studio, model, "Changer", "nvidia_nim/test-model")
    assert "GOAL (the owner's words" in note and "Milestone 2 [NOW]" in note
    assert "note 15" in note and "note 0 " not in note


@pytest.mark.asyncio
async def test_agents_write_notes_with_the_changer_tool(make_studio, tmp_path):
    studio, _ = make_studio([])
    studio._changer = Changer(
        tmp_path / "changer",
        source=make_app(tmp_path / "fcc"),
        import_check="print('ok')",
    )
    copy = await studio.changer_fresh_copy()
    project = await project_for(studio)
    context = ToolContext(
        agent_id="a", chat_id="c", site_id=copy.id, agent_name="Changer Reviewer"
    )

    def call(**arguments) -> ToolCall:
        return ToolCall(
            id="1", name="fcc_changer", arguments={"action": "note", **arguments}
        )

    written = await studio._changer_tool(
        call(text="tests live in tests/studio", kind="odd"), context
    )
    assert not written.failed and "finding" in written.text
    lesson = await studio._changer_tool(
        call(text="run ruff first", kind="lesson"), context
    )
    assert not lesson.failed
    empty = await studio._changer_tool(call(text=" "), context)
    assert empty.failed
    notes = await studio.change_notes(project.id)
    assert [(n.author, n.kind, n.text) for n in notes] == [
        ("Changer Reviewer", "finding", "tests live in tests/studio")
    ]
    assert [n.text for n in await studio.change_notes("")] == ["run ruff first"]


@pytest.mark.asyncio
async def test_each_step_leaves_a_note_by_itself(make_studio):
    def reply(system: str, prompt: str) -> object:
        return LLMReply(text="Added the count route and its test.")

    studio, _ = make_studio(reply)
    project = await project_for(studio)
    changer = await studio._changer_agent()
    await studio._changer_step(
        project, changer, "BUILD milestone 2", kind="build", milestone=1
    )
    notes = await studio.change_notes(project.id)
    assert notes[-1].author == "Changer" and notes[-1].kind == "done"
    assert (
        notes[-1].text
        == "build step (milestone 2): Added the count route and its test."
    )
    run = (await studio._store.find(AgentRun, order_by="created_at DESC", limit=1))[0]
    assert run.status == "succeeded"


@pytest.mark.asyncio
async def test_the_owner_writes_to_the_team_and_sees_it_on_the_page(
    make_studio, tmp_path
):
    studio, _ = make_studio([])
    studio._changer = Changer(
        tmp_path / "changer",
        source=make_app(tmp_path / "fcc"),
        import_check="print('ok')",
    )
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        none_yet = await client.post("/studio/api/changer/notes", json={"text": "hi"})
        assert none_yet.status_code == 400
        kept = await client.post(
            "/studio/api/changer/notes",
            json={"text": "Never touch farm.js", "lesson": True},
        )
        assert kept.status_code == 200 and kept.json()["kind"] == "lesson"
        project = await project_for(studio, status="paused")
        sent = await client.post("/studio/api/changer/notes", json={"text": "Use blue"})
        assert sent.status_code == 200 and sent.json()["author"] == "Owner"
        view = (await client.get("/studio/api/changer")).json()
        assert [n["text"] for n in view["project"]["notebook"]] == ["Use blue"]
        assert [n["text"] for n in view["lessons"]] == ["Never touch farm.js"]
        project_note = (await studio.change_notes(project.id))[0]
        wrong = await client.delete(f"/studio/api/changer/lessons/{project_note.id}")
        assert wrong.status_code == 404
        forgot = await client.delete(f"/studio/api/changer/lessons/{kept.json()['id']}")
        assert forgot.status_code == 200
        assert await studio._store.get(ChangeNote, kept.json()["id"]) is None


@pytest.mark.asyncio
async def test_the_hq_shows_the_update_and_its_notes(make_studio):
    studio, _ = make_studio([])
    assert (await studio.hq())["changer"] is None
    project = await project_for(studio)
    await studio.add_change_note(
        "Aider", "Changed studio.js", kind="done", project=project
    )
    shown = (await studio.hq())["changer"]
    assert shown["request"] == "Show how many files the copy has"
    assert (shown["milestone"], shown["milestones"]) == (2, 3)
    assert shown["title"] == "Show it on the page"
    assert shown["notes"][-1]["author"] == "Aider"
    assert shown["working"] == []


@pytest.mark.asyncio
async def test_the_whole_team_switches_model_and_keeps_its_notebook(make_studio):
    studio, _ = make_studio([])
    project = await project_for(studio, status="paused")
    await studio.add_change_note(
        "Changer", "half way through the route", project=project
    )
    switched = await studio.changer_team_model("freellmapi/auto:coding")
    assert switched["team"] == [
        "Changer",
        "Changer Planner",
        "Changer Reviewer",
        "Changer Security",
    ]
    models = {a.name: a.model for a in await studio.agents()}
    assert {models[name] for name in switched["team"]} == {"freellmapi/auto:coding"}
    assert not studio.runs_on_this_pc("freellmapi/auto:coding")
    assert "half way through the route" in await studio._notebook_text()
    from free_claude_code.studio import StudioError

    with pytest.raises(StudioError, match="Give the model"):
        await studio.changer_team_model("  ")


@pytest.mark.asyncio
async def test_the_team_isnt_switched_mid_job(make_studio):
    studio, _ = make_studio([])
    await project_for(studio, status="building")
    from free_claude_code.studio import StudioError

    with pytest.raises(StudioError, match="pause it"):
        await studio.changer_team_model("freellmapi/auto")


@pytest.mark.asyncio
async def test_a_finished_update_takes_no_notes_and_its_goal_isnt_pinned(make_studio):
    studio, _ = make_studio([])
    project = await project_for(studio, status="done")
    assert await studio.add_change_note("Aider", "late change") is None
    assert await studio.change_notes(project.id) == []
    text = await studio._notebook_text()
    assert "GOAL" not in text and "Show it on the page" not in text
    kept = await studio.add_change_note("Changer", "Run ruff first", kind="lesson")
    assert kept is not None
    assert "Run ruff first" in await studio._notebook_text()


@pytest.mark.asyncio
async def test_the_team_isnt_switched_while_a_reviewer_is_still_working(make_studio):
    studio, _ = make_studio([])
    await project_for(studio, status="paused")
    reviewer = await studio._changer_reviewer(security=False)
    await studio._store.put(
        AgentRun(agent_id=reviewer.id, chat_id="c", goal="REVIEW", status="running")
    )
    from free_claude_code.studio import StudioError

    with pytest.raises(StudioError, match="pause it"):
        await studio.changer_team_model("freellmapi/auto")


@pytest.mark.asyncio
async def test_a_repeat_with_another_kind_is_kept(make_studio):
    studio, _ = make_studio([])
    project = await project_for(studio)
    first = await studio.add_change_note("Changer", "route added", project=project)
    done = await studio.add_change_note(
        "Changer", "route added", kind="done", project=project
    )
    assert first is not None and done is not None
    assert first.id != done.id and done.kind == "done"


@pytest.mark.asyncio
async def test_a_long_notebook_drops_whole_lines_and_keeps_the_goal(
    make_studio, monkeypatch
):
    studio, _ = make_studio([])
    monkeypatch.setattr("free_claude_code.studio.service.NOTEBOOK_CHARS", 1500)
    monkeypatch.setattr("free_claude_code.studio.service.LESSONS_SHOWN", 20)
    await project_for(studio)
    for number in range(20):
        await studio.add_change_note(
            "Changer", f"lesson {number} " + "y" * 150, kind="lesson"
        )
    text = await studio._notebook_text()
    assert len(text) <= 1500
    assert "GOAL (the owner's words" in text and "Milestone 3 [to do]" in text
    assert all(
        line.startswith(("- ", "GOAL", "Plan", "CHANGER", "Lessons"))
        for line in text.splitlines()
    )
    assert "lesson 19" in text and "lesson 0 " not in text
