"""The teacher plans, teaches, tests, and grades the student agent."""

import json

import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import Course, ExamQuestion, Lesson, TunePack
from free_claude_code.studio.school import _takeaway, student_progress


def classroom_model(*, score: float = 1.0):
    """Answer as whichever classroom role the system prompt asks for."""

    def respond(system: str, prompt: str) -> LLMReply:
        if "Plan a short class" in system:
            return LLMReply(
                text=json.dumps(
                    {
                        "lessons": [
                            {"topic": "What tides are", "objective": "Define a tide"},
                            {"topic": "Why they move", "objective": "Explain the moon"},
                        ]
                    }
                )
            )
        if "Write the end-of-class test" in system:
            return LLMReply(
                text=json.dumps(
                    {
                        "questions": [
                            {"prompt": "What causes tides?", "rubric": "Mentions moon"},
                            {"prompt": "How often?", "rubric": "Twice a day"},
                        ]
                    }
                )
            )
        if "Grade one student answer" in system:
            return LLMReply(
                text=json.dumps({"score": score, "feedback": "Clear answer."})
            )
        if "Correct any mistake" in prompt:
            return LLMReply(text="Close. REMEMBER: The moon pulls the ocean.")
        if "You are the student" in system:
            return LLMReply(text="The moon pulls the water.")
        return LLMReply(text="Tides are the daily rise and fall of the sea.")

    return respond


@pytest.mark.asyncio
async def test_a_class_is_planned_taught_and_graded(make_studio):
    studio, _ = make_studio(classroom_model(), STUDIO_TEACHER_ENABLED=True)
    course = await studio.open_class(topic="Tides", lesson_count=2)

    finished = await studio.run_class(course.id)

    assert finished.status == "passed"
    assert finished.passed is True
    assert finished.score == 1.0
    assert finished.lesson_done == finished.lesson_total == 2

    lessons = await studio.store.find(Lesson, where={"course_id": course.id})
    assert [lesson.status for lesson in lessons] == ["done", "done"]
    assert all("moon" in lesson.notes.lower() for lesson in lessons)

    questions = await studio.store.find(ExamQuestion, where={"course_id": course.id})
    assert len(questions) == 2
    assert all(question.answer for question in questions)
    assert student_progress(questions) == 1.0


@pytest.mark.asyncio
async def test_the_classroom_transcript_shows_both_agents(make_studio):
    studio, _ = make_studio(classroom_model())
    course = await studio.open_class(topic="Tides", lesson_count=2)
    await studio.run_class(course.id)

    detail = await studio.course_detail(course.id)
    authors = {message["author"] for message in detail["messages"]}
    kinds = {message["data"].get("kind") for message in detail["messages"]}

    assert {"Teacher", "Student"} <= authors
    assert {"plan", "lesson", "student_answer", "review", "grade", "result"} <= kinds


@pytest.mark.asyncio
async def test_what_the_student_learns_lands_in_its_memory(make_studio):
    studio, _ = make_studio(classroom_model())
    course = await studio.open_class(topic="Tides", lesson_count=2)
    await studio.run_class(course.id)

    student = await studio.agent_by_name("Student")
    assert student is not None
    memories = [entry.text for entry in await studio.memories(student.id)]

    assert "The moon pulls the ocean." in memories
    assert any("Passed the class" in text for text in memories)


@pytest.mark.asyncio
async def test_a_weak_student_does_not_pass(make_studio):
    studio, _ = make_studio(classroom_model(score=0.2))
    course = await studio.open_class(topic="Tides", lesson_count=2)

    finished = await studio.run_class(course.id)

    assert finished.status == "failed"
    assert finished.passed is False
    assert finished.score == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_passing_with_tuning_on_queues_a_light_tune(make_studio):
    studio, _ = make_studio(classroom_model(), STUDIO_LIGHT_TUNING_ENABLED=True)
    course = await studio.open_class(topic="Tides", lesson_count=2)

    finished = await studio.run_class(course.id)

    assert finished.tune_job_id is not None
    job = await studio.job(finished.tune_job_id)
    assert job.status == "queued"
    assert job.agent_id == (await studio.agent_by_name("Student")).id


@pytest.mark.asyncio
async def test_an_unusable_plan_stops_the_class_cleanly(make_studio):
    studio, _ = make_studio([LLMReply(text="I would rather not.")])
    course = await studio.open_class(topic="Tides")

    finished = await studio.run_class(course.id)

    assert finished.status == "failed"
    assert "lesson plan" in (finished.error or "")
    stored = await studio.store.require(Course, course.id)
    assert stored.status == "failed"


def test_takeaway_reads_the_marked_sentence():
    assert _takeaway("Nice work. REMEMBER: Tides follow the moon.\nMore text") == (
        "Tides follow the moon."
    )
    assert _takeaway("No marker here") == ""


@pytest.mark.asyncio
async def test_a_server_model_teaches_a_local_model(make_studio):
    studio, model = make_studio(classroom_model(), STUDIO_LIGHT_TUNING_ENABLED=True)
    teacher = await studio.create_agent(
        name="Professor", role="teacher", model="nvidia_nim/big", tools=[]
    )
    student = await studio.create_agent(
        name="Pocket", role="student", model="local/tiny", tools=[]
    )
    course = await studio.open_class(
        topic="Tides", lesson_count=2, teacher_id=teacher.id, student_id=student.id
    )

    finished = await studio.run_class(course.id)

    assert finished.passed is True
    teacher_calls = {
        call["model"] for call in model.calls if "You are the teacher" in call["system"]
    }
    student_calls = {
        call["model"] for call in model.calls if "You are the student" in call["system"]
    }
    assert teacher_calls == {"nvidia_nim/big"}
    assert student_calls == {"tiny"}  # routed to the local runtime

    memories = [entry.text for entry in await studio.memories(student.id)]
    assert "The moon pulls the ocean." in memories

    job = await studio.job(finished.tune_job_id or "")
    pack = await studio.store.require(TunePack, job.pack_id)
    assert pack.base_model == "local/tiny"
    assert pack.teacher_model == "nvidia_nim/big"
    assert pack.opted_in is True


@pytest.mark.asyncio
async def test_an_agent_cannot_teach_itself(make_studio):
    studio, _ = make_studio([])
    solo = await studio.create_agent(name="Solo", tools=[])
    with pytest.raises(Exception, match="two different agents"):
        await studio.open_class(topic="x", teacher_id=solo.id, student_id=solo.id)
