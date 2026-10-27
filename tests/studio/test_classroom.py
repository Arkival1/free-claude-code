"""The owner's classroom: the owner says what the student should learn, the
teacher proposes a plan and waits for it to be confirmed, leaves the
classroom to learn more, and a student's test question waits for it."""

import asyncio
import json

import httpx
import pytest

from free_claude_code.studio import StudioError
from free_claude_code.studio.llm import LLMReply, StudioLLMError
from free_claude_code.studio.models import Course, ExamQuestion, Lesson, LoraJob
from free_claude_code.studio.school import SchoolError, help_request
from tests.api.support import create_test_app

PLAN = {
    "note": "Here's a two-lesson plan for Ohm's law.",
    "lessons": [
        {
            "topic": "Volts, amps and ohms",
            "objective": "Name the units",
            "research": "",
        },
        {
            "topic": "Using V = I x R",
            "objective": "Solve for any one",
            "research": "ohm's law worked examples",
        },
    ],
}


def owners_class_model():
    def respond(system: str, prompt: str) -> LLMReply:
        if "Plan the class for them to confirm" in system:
            lessons = list(PLAN["lessons"])
            if "three lessons" in prompt:
                lessons.append(
                    {"topic": "Power", "objective": "P = V x I", "research": ""}
                )
            plan = {"note": PLAN["note"], "lessons": lessons}
            return LLMReply(text=json.dumps(plan))
        if "Write the end-of-class test" in system:
            return LLMReply(
                text=json.dumps(
                    {
                        "questions": [
                            {
                                "prompt": "What is the unit of current?",
                                "rubric": "Amps",
                            },
                            {"prompt": "What is V if I=2 and R=5?", "rubric": "10 V"},
                        ]
                    }
                )
            )
        if "Grade one student answer" in system:
            return LLMReply(text=json.dumps({"score": 0.9, "feedback": "Right."}))
        if "Correct any mistake" in prompt:
            return LLMReply(text="Good. REMEMBER: V equals I times R.")
        if "your student asks" in prompt:
            return LLMReply(text="Multiply the current by the resistance.")
        if "QUESTION FOR TEACHER" in system and "V if I=2" in prompt:
            return LLMReply(
                text="QUESTION FOR TEACHER: do I multiply or divide?\nMaybe 2.5 V."
            )
        if "Your teacher answered your question" in prompt:
            return LLMReply(text="10 V.")
        if "You are the student" in system:
            return LLMReply(text="Amps.")
        if "owner of this classroom is talking" in system:
            return LLMReply(text="We're on lesson one; all is going well.")
        return LLMReply(text="Volts push, amps flow, ohms resist.")

    return respond


def test_a_student_question_is_read_from_its_answer():
    assert help_request("QUESTION FOR TEACHER: why?\nguess") == "why?"
    assert help_request("**Question for teacher:** is it 5?") == "is it 5?"
    assert help_request("Just an answer.") == ""


@pytest.mark.asyncio
async def test_the_owner_plans_confirms_and_the_test_waits_for_the_teacher(
    make_studio, monkeypatch
):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    school = studio._school()

    # Nothing is taught before the owner confirms the plan.
    with pytest.raises(SchoolError, match="no lesson plan"):
        await school.confirm(course.id)
    proposed = await school.talk(course.id, "Teach it the maths an apprentice needs")
    assert proposed.status == "proposed" and proposed.lesson_total == 2
    assert "apprentice" in proposed.goal
    changed = await school.talk(course.id, "Make it three lessons please")
    assert changed.lesson_total == 3 and changed.status == "proposed"
    lessons = await studio._store.find(Lesson, where={"course_id": course.id})
    assert len(lessons) == 3  # the old plan was replaced, not added to
    with pytest.raises(SchoolError, match="Confirm the lesson plan"):
        await school.run_confirmed(course.id)

    # While the teacher is out checking facts for marking, the student asks;
    # its question waits until the teacher is back.
    seen: list[str] = []

    async def research(query: str) -> str:
        seen.append(query)
        if "marking" not in query and "worked examples" in query:
            return "V = I x R; 2 A through 5 ohms is 10 V."
        for _ in range(200):
            waiting = await studio._store.find(
                ExamQuestion, where={"course_id": course.id, "state": "waiting"}
            )
            if waiting:
                current = await studio._store.require(Course, course.id)
                assert current.teacher_present is False
                break
            await asyncio.sleep(0.01)
        return "Current is measured in amps."

    monkeypatch.setattr(studio, "_class_research", research)
    school = studio._school()
    await school.confirm(course.id)
    finished = await school.run_confirmed(course.id)

    assert finished.status == "passed" and finished.teacher_present is True
    assert "ohm's law worked examples" in seen[0]
    assert "10 V" in finished.knowledge
    questions = await studio._store.find(
        ExamQuestion, where={"course_id": course.id}, order_by="ordinal ASC"
    )
    assert all(item.state == "graded" for item in questions)
    asked = questions[1]
    assert asked.help_request == "do I multiply or divide?"
    assert "Multiply" in asked.help_reply and asked.answer == "10 V."
    kinds = [
        message.data.get("kind")
        for message in await studio._store.transcript(course.chat_id)
    ]
    assert kinds.index("teacher_left") < kinds.index("student_waiting")
    assert kinds.index("student_waiting") < kinds.index("teacher_help")
    assert "plan_confirmed" in kinds and "result" in kinds


@pytest.mark.asyncio
async def test_the_classroom_routes(make_studio, monkeypatch):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)

    async def research(query: str) -> str:
        return f"Notes on {query}."

    monkeypatch.setattr(studio, "_class_research", research)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    ) as client:
        made = await client.post(
            "/studio/api/school/courses", json={"topic": "Ohm's law", "start": False}
        )
        course_id = made.json()["id"]
        talk = await client.post(
            f"/studio/api/school/courses/{course_id}/talk", json={"text": "Teach V=IR"}
        )
        assert talk.status_code == 200
        await studio.wait_for_background()
        detail = (await client.get(f"/studio/api/school/courses/{course_id}")).json()
        assert detail["course"]["status"] == "proposed" and len(detail["lessons"]) == 2
        assert detail["busy"] is False
        empty = await client.post(
            f"/studio/api/school/courses/{course_id}/talk", json={"text": "  "}
        )
        assert empty.status_code == 400

        out = await client.post(
            f"/studio/api/school/courses/{course_id}/send-out",
            json={"query": "resistor colour codes"},
        )
        assert out.status_code == 200
        await studio.wait_for_background()
        detail = (await client.get(f"/studio/api/school/courses/{course_id}")).json()
        assert "resistor colour codes" in detail["course"]["knowledge"]
        assert any(m["data"].get("kind") == "teacher_back" for m in detail["messages"])

        confirmed = await client.post(f"/studio/api/school/courses/{course_id}/confirm")
        assert confirmed.status_code == 200 and confirmed.json()["plan_confirmed"]
        # While the class runs, the teacher answers on the side; sending it
        # out again has to wait.
        side = await client.post(
            f"/studio/api/school/courses/{course_id}/talk",
            json={"text": "How's it going?"},
        )
        assert side.status_code == 200
        busy = await client.post(
            f"/studio/api/school/courses/{course_id}/send-out",
            json={"query": "more"},
        )
        assert busy.status_code == 400 and "busy" in busy.json()["detail"]
        await studio.wait_for_background()
        detail = (await client.get(f"/studio/api/school/courses/{course_id}")).json()
        assert detail["course"]["status"] == "passed"
        again = await client.post(f"/studio/api/school/courses/{course_id}/confirm")
        assert again.status_code == 400


@pytest.mark.asyncio
async def test_a_new_teacher_model_gets_the_class_notes(make_studio):
    """An API that rotates models (FreeLLMAPI, NVIDIA) mid-class: the next
    model is handed what the class covered, in a few hundred tokens."""
    base = owners_class_model()
    served = iter(["model-a"] + ["model-b"] * 50)
    systems: list[str] = []

    def respond(system: str, prompt: str) -> LLMReply:
        systems.append(system)
        reply = base(system, prompt)
        return LLMReply(text=reply.text, model=next(served))

    studio, _ = make_studio(respond, STUDIO_TEACHER_ENABLED=True)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    school = studio._school()
    await school.talk(course.id, "Teach it the maths an apprentice needs")
    await school.talk(course.id, "Make it three lessons please")
    notes = await school.class_notes(await studio._store.require(Course, course.id))
    assert "apprentice" in notes and "Using V = I x R" in notes
    assert len(notes) <= 1500
    # The teacher's prompts carry the notes, and the switch is shown.
    assert "Class notes so far" in systems[-1]
    kinds = [
        message.data.get("kind")
        for message in await studio._store.transcript(course.chat_id)
    ]
    assert kinds.count("teacher_handover") == 1
    current = await studio._store.require(Course, course.id)
    assert current.teacher_model == "model-b"


@pytest.mark.asyncio
async def test_the_owner_can_ask_the_teacher_while_the_class_runs(make_studio):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    await studio._school().talk(course.id, "Teach V=IR")
    await studio._school().confirm(course.id)
    studio._class_busy.add(course.id)  # as if the class were running
    await studio.class_talk(course.id, "How is the student doing?")
    await studio.wait_for_background()
    replies = [
        message
        for message in await studio._store.transcript(course.chat_id)
        if message.data.get("kind") == "teacher_reply"
    ]
    assert replies and "going well" in replies[-1].text


@pytest.mark.asyncio
async def test_the_teacher_trains_the_student_here_or_on_a_notebook(
    make_studio, monkeypatch
):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)

    async def still_preparing(job_id: str) -> None:
        del job_id  # the training set is built later; the notebook is ready now

    monkeypatch.setattr(studio.lora, "_prepare", still_preparing)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    ) as client:
        made = await client.post(
            "/studio/api/school/courses", json={"topic": "Ohm's law", "start": False}
        )
        course_id = made.json()["id"]
        early = await client.post(
            f"/studio/api/school/courses/{course_id}/train", json={"where": "kaggle"}
        )
        assert early.status_code == 400 and "passes" in early.json()["detail"]
        course = await studio._store.require(Course, course_id)
        await studio._store.put(course.model_copy(update={"status": "passed"}))
        await studio._store.put(
            Lesson(course_id=course_id, ordinal=1, topic="Volts", status="done")
        )
        trained = await client.post(
            f"/studio/api/school/courses/{course_id}/train", json={"where": "kaggle"}
        )
        assert trained.status_code == 200, trained.text
        job = trained.json()
        assert job["runner"] == "remote" and job["base_model"] == "Qwen/Qwen3-8B"
        assert "worker_token" not in job
        notebook = await client.get(job["notebook_url"])
        assert notebook.status_code == 200
        cells = notebook.json()["cells"]
        assert notebook.json()["metadata"]["kaggle"]["accelerator"] == "gpu"
        assert any("lora_worker.py" in cell["source"] for cell in cells)
        assert any("UserSecretsClient" in cell["source"] for cell in cells)
        detail = (await client.get(f"/studio/api/school/courses/{course_id}")).json()
        assert detail["training"]["id"] == job["id"]
        assert detail["training"]["in_use"] is False
        kinds = [m["data"].get("kind") for m in detail["messages"]]
        assert "training" in kinds
        lessons = job["topics"]
        assert lessons == ["Volts"]


@pytest.mark.asyncio
async def test_the_teacher_notebook_serves_a_model_behind_its_own_key(make_studio):
    studio, _ = make_studio([])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    ) as client:
        got = await client.get("/studio/api/school/teacher-notebook?target=colab")
        assert got.status_code == 200
        assert "fcc-teacher-colab.ipynb" in got.headers["content-disposition"]
        book = got.json()
        assert book["nbformat"] == 4 and book["metadata"]["colab"]["gpuType"] == "T4"
        code = "\n".join(cell["source"] for cell in book["cells"])
        assert "secrets.token_urlsafe" in code and "--api_key" in code
        assert "trycloudflare" in code and "notebook/teacher" in code
        bad = await client.get(
            '/studio/api/school/teacher-notebook?file=x.gguf"; rm -rf /'
        )
        assert bad.status_code == 400
        wrong = await client.get("/studio/api/school/teacher-notebook?target=aws")
        assert wrong.status_code == 400


@pytest.mark.asyncio
async def test_the_owner_routes_never_teach_an_unconfirmed_plan(make_studio):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    ) as client:
        made = await client.post(
            "/studio/api/school/courses", json={"topic": "Ohm's law", "start": True}
        )
        course_id = made.json()["id"]
        await studio.wait_for_background()
        course = await studio._store.require(Course, course_id)
        assert course.status == "proposed" and course.lesson_done == 0
        start = await client.post(f"/studio/api/school/courses/{course_id}/start")
        assert start.status_code == 400 and "Confirm" in start.json()["detail"]
        await studio.wait_for_background()
        still = await studio._store.require(Course, course_id)
        assert still.status == "proposed" and still.lesson_done == 0


@pytest.mark.asyncio
async def test_a_student_failing_mid_test_stops_the_teacher_too(
    make_studio, monkeypatch
):
    base = owners_class_model()

    def respond(system: str, prompt: str) -> LLMReply:
        if "QUESTION FOR TEACHER" in system:
            raise StudioLLMError("the student's model went away")
        return base(system, prompt)

    studio, _ = make_studio(respond, STUDIO_TEACHER_ENABLED=True)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    school = studio._school()
    await school.talk(course.id, "Teach V=IR")
    await school.confirm(course.id)
    out_for_good = asyncio.Event()

    async def research(query: str) -> str:
        if "marking" in query or "Amps" in query:
            await out_for_good.wait()  # would hang without the cancel
        return "notes"

    monkeypatch.setattr(studio, "_class_research", research)
    failed = await asyncio.wait_for(school.run_confirmed(course.id), timeout=5)
    assert failed.status == "failed" and failed.teacher_present is True
    kinds = [
        message.data.get("kind")
        for message in await studio._store.transcript(course.chat_id)
    ]
    assert kinds[-1] == "course_failed"


@pytest.mark.asyncio
async def test_a_class_trains_its_student_once_at_a_time(make_studio, monkeypatch):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    await studio._store.put(course.model_copy(update={"status": "passed"}))

    async def stays_queued(job_id: str) -> None:
        """Preparation does nothing, so the job stays queued (the real one
        failed at once for want of examples, and the test raced it)."""

    monkeypatch.setattr(studio.lora, "_prepare", stays_queued)
    first = await studio.class_train(course.id, "colab")
    assert first.status == "queued"
    with pytest.raises(StudioError, match="already being trained"):
        await studio.class_train(course.id, "kaggle")
    # A job that ended (failed or done) doesn't block training again.
    await studio._store.put(first.model_copy(update={"status": "failed"}))
    again = await studio.class_train(course.id, "kaggle")
    assert again.id != first.id


def test_the_notebooks_are_valid_python_and_refuse_odd_names():
    import ast

    from free_claude_code.studio import notebook

    for target in notebook.TARGETS:
        book = notebook.teacher_notebook(target)
        for cell in book["cells"]:
            if cell["cell_type"] == "code":
                source = "\n".join(
                    line
                    for line in cell["source"].splitlines()
                    if not line.startswith("!")
                )
                ast.parse(source)
    for bad in ('x"; import os; os.system("rm -rf /") #', "a$b", "two\nlines"):
        with pytest.raises(notebook.NotebookError):
            notebook.teacher_notebook(file=f"{bad}.gguf")
        with pytest.raises(notebook.NotebookError):
            notebook.teacher_notebook(repo=bad)


@pytest.mark.asyncio
async def test_running_a_class_again_marks_only_the_new_test(make_studio):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    school = studio._school()
    await school.talk(course.id, "Teach V=IR")
    await school.confirm(course.id)
    await school.run_confirmed(course.id)
    again = await school.run_confirmed(course.id)
    questions = await studio._store.find(ExamQuestion, where={"course_id": course.id})
    assert len(questions) == 2 and again.score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_a_failed_plan_doesnt_repeat_the_owners_words(make_studio):
    base = owners_class_model()
    calls = {"plans": 0}

    def respond(system: str, prompt: str) -> LLMReply:
        if "Plan the class for them to confirm" in system:
            calls["plans"] += 1
            if calls["plans"] == 1:
                return LLMReply(text="Sorry, no plan.")
        return base(system, prompt)

    studio, _ = make_studio(respond, STUDIO_TEACHER_ENABLED=True)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    school = studio._school()
    with pytest.raises(SchoolError, match="usable lesson plan"):
        await school.talk(course.id, "Teach V=IR")
    failed = await studio._store.require(Course, course.id)
    assert failed.goal == "" and failed.activity == ""
    planned = await school.talk(course.id, "Teach V=IR")
    assert planned.goal == "Teach V=IR"


@pytest.mark.asyncio
async def test_a_class_stopped_from_outside_brings_the_teacher_back(
    make_studio, monkeypatch
):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    school = studio._school()
    await school.talk(course.id, "Teach V=IR")
    await school.confirm(course.id)
    out = asyncio.Event()

    async def research(query: str) -> str:
        out.set()
        await asyncio.Event().wait()  # the teacher is out when Studio stops
        return ""

    monkeypatch.setattr(studio, "_class_research", research)
    running = asyncio.create_task(studio._school().run_confirmed(course.id))
    await asyncio.wait_for(out.wait(), timeout=5)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    stopped = await studio._store.require(Course, course.id)
    assert stopped.teacher_present is True and stopped.status == "failed"


@pytest.mark.asyncio
async def test_two_quick_train_presses_make_one_job(make_studio, monkeypatch):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)

    async def still_preparing(job_id: str) -> None:
        del job_id

    monkeypatch.setattr(studio.lora, "_prepare", still_preparing)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    await studio._store.put(course.model_copy(update={"status": "passed"}))
    results = await asyncio.gather(
        studio.class_train(course.id, "kaggle"),
        studio.class_train(course.id, "kaggle"),
        return_exceptions=True,
    )
    assert sum(isinstance(item, StudioError) for item in results) == 1
    assert len(await studio._store.find(LoraJob)) == 1


@pytest.mark.asyncio
async def test_the_teacher_hands_over_the_trained_model_once(make_studio, monkeypatch):
    studio, _ = make_studio(owners_class_model(), STUDIO_TEACHER_ENABLED=True)

    async def still_preparing(job_id: str) -> None:
        del job_id

    monkeypatch.setattr(studio.lora, "_prepare", still_preparing)
    course = await studio.open_class(topic="Ohm's law", lesson_count=2)
    await studio._store.put(course.model_copy(update={"status": "passed"}))
    job = await studio.class_train(course.id, "pc")
    folder = studio.lora.job_dir(job.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "model.gguf").write_bytes(b"GGUF")
    (folder / "train.jsonl").write_text("{}\n")
    await studio._store.put(job.model_copy(update={"status": "succeeded"}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    ) as client:
        for _ in range(2):  # the page polls; the teacher says it once
            detail = (
                await client.get(f"/studio/api/school/courses/{course.id}")
            ).json()
        assert detail["training"]["files"] == ["model.gguf"]
        done = [
            m
            for m in detail["messages"]
            if m["data"].get("kind", "").startswith("training_done")
        ]
        assert len(done) == 1 and "Download the trained model" in done[0]["text"]
        got = await client.get(f"/studio/api/lora/jobs/{job.id}/files/model.gguf")
        assert got.status_code == 200 and got.content == b"GGUF"
