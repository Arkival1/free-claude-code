"""A teacher agent runs a class for a student agent, then tests it."""

from collections.abc import Sequence

from loguru import logger

from .jsonish import clamped_score, extract_object, extract_objects
from .llm import ChatMessage, StudioLLMError, StudioModelRouter
from .memory import MemoryService
from .models import (
    Agent,
    Chat,
    Course,
    ExamQuestion,
    Lesson,
    TuneJob,
    now_ms,
)
from .store import StudioStore
from .tuning import LightTuner, TuningError

MIN_LESSONS = 2
MAX_LESSONS = 6
MIN_QUESTIONS = 3
MAX_QUESTIONS = 6

TEACHER_PROMPT = (
    "You are the teacher in a two-agent classroom. Your student is a smaller "
    "model. Teach in plain, concrete language, one idea at a time, with short "
    "worked examples. Never assume knowledge you have not taught in this class."
)
STUDENT_PROMPT = (
    "You are the student in a two-agent classroom. Answer from what you have "
    "been taught and from your own memory. If you are unsure, say what you are "
    "unsure about instead of inventing an answer."
)
PLAN_REQUEST = (
    "Plan a short class on the topic below. Reply with JSON only:\n"
    '{"lessons": [{"topic": "...", "objective": "..."}]}\n'
    f"Use between {MIN_LESSONS} and {MAX_LESSONS} lessons, ordered so each "
    "builds on the last."
)
EXAM_REQUEST = (
    "Write the end-of-class test for what you just taught. Reply with JSON "
    'only:\n{"questions": [{"prompt": "...", "rubric": "what a correct answer '
    'must contain"}]}\n'
    f"Use between {MIN_QUESTIONS} and {MAX_QUESTIONS} questions that can each "
    "be answered in a few sentences."
)
GRADE_REQUEST = (
    "Grade one student answer against your rubric. Reply with JSON only:\n"
    '{"score": <0.0-1.0>, "feedback": "<one or two sentences>"}'
)


class SchoolError(RuntimeError):
    """Raised when a class cannot be planned, taught, or graded."""


class School:
    """Own the classroom: planning, lessons, the exam, and what is learned."""

    def __init__(
        self,
        *,
        store: StudioStore,
        router: StudioModelRouter,
        memory: MemoryService,
        tuner: LightTuner,
        default_model: str,
    ) -> None:
        self._store = store
        self._router = router
        self._memory = memory
        self._tuner = tuner
        self._default_model = default_model

    async def open_course(
        self,
        *,
        topic: str,
        teacher: Agent,
        student: Agent,
        lesson_count: int = 3,
        pass_mark: float = 0.7,
    ) -> Course:
        """Create a classroom chat and its course record."""
        cleaned = topic.strip()
        if not cleaned:
            raise SchoolError("A class needs a topic.")
        chat = Chat.model_validate(
            {
                "title": f"Class: {cleaned[:48]}",
                "kind": "classroom",
                "agent_id": teacher.id,
                "partner_agent_id": student.id,
            }
        )
        await self._store.put(chat)
        course = Course.model_validate(
            {
                "topic": cleaned,
                "teacher_agent_id": teacher.id,
                "student_agent_id": student.id,
                "chat_id": chat.id,
                "lesson_total": max(MIN_LESSONS, min(MAX_LESSONS, lesson_count)),
                "pass_mark": pass_mark,
            }
        )
        await self._store.put(course)
        await self._store.put(chat.model_copy(update={"course_id": course.id}))
        await self._store.append_message(
            chat_id=chat.id,
            role="event",
            text=f"Class opened: {cleaned}",
            author=teacher.name,
            data={"kind": "course_opened", "course_id": course.id},
        )
        return course

    async def run_course(self, course_id: str, *, tune_on_pass: bool = False) -> Course:
        """Teach every lesson, run the test, and record what the student learned."""
        course = await self._store.require(Course, course_id)
        teacher = await self._store.require(Agent, course.teacher_agent_id)
        student = await self._store.require(Agent, course.student_agent_id)
        try:
            course = await self._plan(course, teacher)
            course = await self._teach(course, teacher, student)
            course = await self._examine(course, teacher, student)
            if course.passed and tune_on_pass:
                course = await self._tune_student(course, student)
            return course
        except (SchoolError, StudioLLMError, TuningError) as error:
            logger.warning("Studio class {} failed: {}", course_id, error)
            failed = (await self._store.require(Course, course_id)).model_copy(
                update={
                    "status": "failed",
                    "error": str(error),
                    "updated_at": now_ms(),
                }
            )
            await self._store.put(failed)
            await self._store.append_message(
                chat_id=failed.chat_id,
                role="event",
                text=f"Class stopped: {error}",
                author="studio",
                data={"kind": "course_failed"},
            )
            return failed

    async def _plan(self, course: Course, teacher: Agent) -> Course:
        reply = await self._router.complete(
            [
                ChatMessage.user(
                    f"Topic: {course.topic}\nLessons: {course.lesson_total}"
                )
            ],
            model=teacher.model or self._default_model,
            system=f"{TEACHER_PROMPT}\n\n{PLAN_REQUEST}",
            temperature=0.4,
            max_tokens=900,
        )
        planned = extract_objects(reply.text)
        if not planned:
            raise SchoolError("The teacher did not return a usable lesson plan.")
        lessons = [
            Lesson.model_validate(
                {
                    "course_id": course.id,
                    "ordinal": index,
                    "topic": str(item.get("topic", f"Lesson {index}")).strip(),
                    "objective": str(item.get("objective", "")).strip(),
                }
            )
            for index, item in enumerate(planned[:MAX_LESSONS], start=1)
        ]
        await self._store.put_many(lessons)
        outline = "\n".join(
            f"{lesson.ordinal}. {lesson.topic} — {lesson.objective}"
            for lesson in lessons
        )
        await self._store.append_message(
            chat_id=course.chat_id,
            role="assistant",
            text=f"Here is the plan for this class:\n\n{outline}",
            author=teacher.name,
            data={"kind": "plan", "lessons": len(lessons)},
        )
        updated = course.model_copy(
            update={
                "status": "teaching",
                "lesson_total": len(lessons),
                "updated_at": now_ms(),
            }
        )
        await self._store.put(updated)
        return updated

    async def _teach(self, course: Course, teacher: Agent, student: Agent) -> Course:
        lessons = await self._store.find(
            Lesson, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        taught = 0
        for taught, lesson in enumerate(lessons, start=1):
            await self._store.put(
                lesson.model_copy(update={"status": "teaching", "updated_at": now_ms()})
            )
            explanation = await self._say(
                course,
                teacher,
                system=TEACHER_PROMPT,
                prompt=(
                    f"Class topic: {course.topic}\n"
                    f"Lesson {lesson.ordinal}: {lesson.topic}\n"
                    f"Objective: {lesson.objective}\n\n"
                    "Teach this lesson in under 200 words, then ask the student "
                    "one question that checks understanding."
                ),
                kind="lesson",
                lesson_id=lesson.id,
            )
            answer = await self._say(
                course,
                student,
                system=await self._student_system(student, course.topic),
                prompt=(
                    f"Your teacher said:\n{explanation}\n\n"
                    "Answer the question and say in one line what you took away."
                ),
                kind="student_answer",
                lesson_id=lesson.id,
            )
            review = await self._say(
                course,
                teacher,
                system=TEACHER_PROMPT,
                prompt=(
                    f"Lesson: {lesson.topic}\nStudent answered:\n{answer}\n\n"
                    "Correct any mistake in under 120 words, then state the single "
                    "sentence the student should remember, prefixed with 'REMEMBER:'."
                ),
                kind="review",
                lesson_id=lesson.id,
            )
            takeaway = _takeaway(review) or f"{lesson.topic}: {lesson.objective}"
            if student.memory_enabled:
                await self._memory.remember(
                    student.id,
                    takeaway,
                    tags=("class", course.topic.lower()[:24]),
                    source=f"course:{course.id}",
                    chat_id=course.chat_id,
                )
            await self._store.put(
                lesson.model_copy(
                    update={
                        "status": "done",
                        "notes": takeaway,
                        "updated_at": now_ms(),
                    }
                )
            )
            course = course.model_copy(
                update={"lesson_done": taught, "updated_at": now_ms()}
            )
            await self._store.put(course)
        return course

    async def _examine(self, course: Course, teacher: Agent, student: Agent) -> Course:
        course = course.model_copy(
            update={"status": "examining", "updated_at": now_ms()}
        )
        await self._store.put(course)
        lessons = await self._store.find(
            Lesson, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        covered = "\n".join(f"- {lesson.topic}: {lesson.notes}" for lesson in lessons)
        reply = await self._router.complete(
            [ChatMessage.user(f"Topic: {course.topic}\nTaught:\n{covered}")],
            model=teacher.model or self._default_model,
            system=f"{TEACHER_PROMPT}\n\n{EXAM_REQUEST}",
            temperature=0.3,
            max_tokens=900,
        )
        drafted = extract_objects(reply.text)
        if not drafted:
            raise SchoolError("The teacher did not return a usable test.")
        questions = [
            ExamQuestion.model_validate(
                {
                    "course_id": course.id,
                    "ordinal": index,
                    "prompt": str(item.get("prompt", "")).strip(),
                    "rubric": str(item.get("rubric", "")).strip(),
                }
            )
            for index, item in enumerate(drafted[:MAX_QUESTIONS], start=1)
            if str(item.get("prompt", "")).strip()
        ]
        if not questions:
            raise SchoolError("The test had no usable questions.")
        await self._store.put_many(questions)
        await self._store.append_message(
            chat_id=course.chat_id,
            role="event",
            text=f"Test time: {len(questions)} questions.",
            author=teacher.name,
            data={"kind": "exam_started", "questions": len(questions)},
        )
        total = 0.0
        for question in questions:
            answer = await self._say(
                course,
                student,
                system=await self._student_system(student, course.topic),
                prompt=f"Test question {question.ordinal}: {question.prompt}",
                kind="exam_answer",
                question_id=question.id,
            )
            grade = await self._router.complete(
                [
                    ChatMessage.user(
                        f"Question: {question.prompt}\n"
                        f"Rubric: {question.rubric}\n"
                        f"Student answer: {answer}"
                    )
                ],
                model=teacher.model or self._default_model,
                system=f"{TEACHER_PROMPT}\n\n{GRADE_REQUEST}",
                temperature=0.0,
                max_tokens=300,
            )
            payload = extract_object(grade.text)
            score = clamped_score(payload.get("score"))
            feedback = str(payload.get("feedback", "")).strip()
            total += score
            await self._store.put(
                question.model_copy(
                    update={"answer": answer, "score": score, "feedback": feedback}
                )
            )
            await self._store.append_message(
                chat_id=course.chat_id,
                role="event",
                text=f"Q{question.ordinal}: {score:.0%} — {feedback}",
                author=teacher.name,
                data={
                    "kind": "grade",
                    "question_id": question.id,
                    "score": score,
                },
            )
        final = total / len(questions)
        passed = final >= course.pass_mark
        graded = course.model_copy(
            update={
                "status": "passed" if passed else "failed",
                "score": round(final, 4),
                "passed": passed,
                "updated_at": now_ms(),
            }
        )
        await self._store.put(graded)
        await self._store.append_message(
            chat_id=course.chat_id,
            role="assistant",
            text=(
                f"Final result: {final:.0%} "
                f"({'pass' if passed else 'below'} the {course.pass_mark:.0%} mark)."
            ),
            author=teacher.name,
            data={"kind": "result", "score": final, "passed": passed},
        )
        if passed and student.memory_enabled:
            await self._memory.remember(
                student.id,
                f"Passed the class on {course.topic} with {final:.0%}.",
                tags=("class", "result"),
                source=f"course:{course.id}",
                chat_id=course.chat_id,
            )
        return graded

    async def _tune_student(self, course: Course, student: Agent) -> Course:
        """Turn a passed class into a very light tune for the student."""
        transcript = await self._store.transcript(course.chat_id)
        pairs: list[tuple[str, str]] = []
        questions = await self._store.find(
            ExamQuestion, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        pairs.extend(
            (question.prompt, question.answer)
            for question in questions
            if question.score is not None and question.score >= course.pass_mark
        )
        lessons = await self._store.find(
            Lesson, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        pairs.extend(
            (f"What did you learn about {lesson.topic}?", lesson.notes)
            for lesson in lessons
            if lesson.notes
        )
        if len(pairs) < 2:
            logger.info("Studio class {} had too little material to tune.", course.id)
            return course
        pack = await self._tuner.create_pack(
            student, name=f"{student.name} · {course.topic[:24]}"
        )
        await self._tuner.add_samples(pack.id, pairs)
        job = await self._tuner.start(pack.id)
        updated = course.model_copy(
            update={"tune_job_id": job.id, "updated_at": now_ms()}
        )
        await self._store.put(updated)
        await self._store.append_message(
            chat_id=course.chat_id,
            role="event",
            text=f"Queued a light tune from this class ({len(pairs)} examples).",
            author="studio",
            data={"kind": "tune_queued", "job_id": job.id},
        )
        _ = transcript
        return updated

    async def pending_tune_job(self, course_id: str) -> TuneJob | None:
        """Return the tuning job a class queued, when it has one."""
        course = await self._store.require(Course, course_id)
        if course.tune_job_id is None:
            return None
        return await self._store.get(TuneJob, course.tune_job_id)

    async def _student_system(self, student: Agent, topic: str) -> str:
        parts = [STUDENT_PROMPT, student.system_prompt.strip()]
        if student.memory_enabled:
            parts.append(await self._memory.context_block(student.id, topic))
        return "\n\n".join(part for part in parts if part.strip())

    async def _say(
        self,
        course: Course,
        speaker: Agent,
        *,
        system: str,
        prompt: str,
        kind: str,
        lesson_id: str | None = None,
        question_id: str | None = None,
    ) -> str:
        reply = await self._router.complete(
            [ChatMessage.user(prompt)],
            model=speaker.model or self._default_model,
            system=system,
            temperature=0.5,
            max_tokens=700,
        )
        text = reply.text.strip() or "(no reply)"
        await self._store.append_message(
            chat_id=course.chat_id,
            role="assistant",
            text=text,
            author=speaker.name,
            data={
                "kind": kind,
                "role": speaker.role,
                "lesson_id": lesson_id,
                "question_id": question_id,
            },
        )
        return text


def _takeaway(review: str) -> str:
    """Return the sentence the teacher marked for the student to remember."""
    marker = "REMEMBER:"
    index = review.upper().find(marker)
    if index < 0:
        return ""
    return review[index + len(marker) :].strip().splitlines()[0].strip()


def student_progress(questions: Sequence[ExamQuestion]) -> float:
    """Return the mean graded score for a set of exam questions."""
    graded = [item.score for item in questions if item.score is not None]
    return sum(graded) / len(graded) if graded else 0.0
