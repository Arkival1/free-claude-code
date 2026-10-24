"""A teacher agent runs a class for a student agent, then tests it.

The classroom is run by its owner: they tell the teacher what the student
should learn, the teacher proposes a lesson plan, and nothing is taught until
the owner confirms it. The teacher can leave the classroom to learn more (a
web search) and come back; during the test the student works while the
teacher is out, and a question it asks waits until the teacher is back.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from loguru import logger

from .jsonish import clamped_score, extract_object, extract_objects
from .llm import ChatMessage, LLMReply, StudioLLMError, StudioModelRouter
from .memory import MemoryService
from .models import (
    Agent,
    Chat,
    Course,
    ExamQuestion,
    Lesson,
    LoraJob,
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
PROPOSE_REQUEST = (
    "The owner of this classroom told you what the student AI should learn. "
    "Plan the class for them to confirm. Reply with JSON only:\n"
    '{"note": "one or two sentences to the owner", "lessons": [{"topic": '
    '"...", "objective": "what the student can do after it", "research": '
    '"web search words when you need fresh or exact facts first, else empty"}]}\n'
    f"Use between {MIN_LESSONS} and {MAX_LESSONS} lessons, ordered so each "
    "builds on the last. When a plan already exists, change it the way the "
    "owner asks and keep the rest."
)
TEST_RULES = (
    "This is a test: answer on your own. If you are truly stuck, write one "
    "line that starts with 'QUESTION FOR TEACHER:' and your question, then "
    "your best answer so far."
)
HELP_MARK = "QUESTION FOR TEACHER:"
MAX_NOTES = 3000
MAX_KNOWLEDGE = 6000
MAX_CLASS_NOTES = 1500
"""About 400 tokens: the class notes every teacher call carries."""
CLASS_NOTES_HEAD = (
    "Class notes so far (kept by FCC; if you are a new model taking over this "
    "class, carry on from here):"
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
        sealed: Callable[[Agent], Awaitable[bool]] | None = None,
        researcher: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        # Where the teacher goes when it leaves the classroom to learn more.
        self._researcher = researcher
        self._store = store
        self._router = router
        self._memory = memory
        self._tuner = tuner
        self._default_model = default_model
        # A student on a server AI learns without the user's memory.
        self._sealed = sealed

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
                course = await self._tune_student(course, teacher, student)
            return course
        except (SchoolError, StudioLLMError, TuningError) as error:
            logger.warning("Studio class {} failed: {}", course_id, error)
            failed = await self._set(course_id, status="failed", error=str(error))
            await self._store.append_message(
                chat_id=failed.chat_id,
                role="event",
                text=f"Class stopped: {error}",
                author="studio",
                data={"kind": "course_failed"},
            )
            return failed

    async def _plan(self, course: Course, teacher: Agent) -> Course:
        reply = await self._ask_teacher(
            course.id,
            teacher,
            [
                ChatMessage.user(
                    f"Topic: {course.topic}\nLessons: {course.lesson_total}"
                )
            ],
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
        return await self._set(course.id, status="teaching", lesson_total=len(lessons))

    async def _teach(self, course: Course, teacher: Agent, student: Agent) -> Course:
        lessons = await self._store.find(
            Lesson, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        taught = 0
        for taught, lesson in enumerate(lessons, start=1):
            await self._store.put(
                lesson.model_copy(update={"status": "teaching", "updated_at": now_ms()})
            )
            if lesson.research:
                await self._step_out(
                    course.id, teacher, lesson.research, f"look up {lesson.topic}"
                )
            course = await self._set(
                course.id,
                lesson_done=taught - 1,
                activity=f"Lesson {lesson.ordinal} of {len(lessons)}: {lesson.topic}",
            )
            # The latest notes, this lesson's included (_step_out kept them).
            known = course.knowledge[-MAX_NOTES:]
            explanation = await self._say(
                course,
                teacher,
                system=TEACHER_PROMPT,
                prompt=(
                    f"Class topic: {course.topic}\n"
                    f"Lesson {lesson.ordinal}: {lesson.topic}\n"
                    f"Objective: {lesson.objective}\n"
                    + (f"What you found out:\n{known}\n" if known else "")
                    + "\nTeach this lesson in under 200 words, then ask the student "
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
            course = await self._set(course.id, lesson_done=taught)
        return course

    async def _examine(self, course: Course, teacher: Agent, student: Agent) -> Course:
        course = await self._set(course.id, status="examining")
        questions = await self._draft_exam(course, teacher)
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
            score, feedback = await self._grade_one(teacher, question, answer)
            total += score
            await self._store.put(
                question.model_copy(
                    update={
                        "answer": answer,
                        "score": score,
                        "feedback": feedback,
                        "state": "graded",
                    }
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
        return await self._record_result(
            course, teacher, student, total / len(questions)
        )

    async def _draft_exam(self, course: Course, teacher: Agent) -> list[ExamQuestion]:
        lessons = await self._store.find(
            Lesson, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        covered = "\n".join(f"- {lesson.topic}: {lesson.notes}" for lesson in lessons)
        reply = await self._ask_teacher(
            course.id,
            teacher,
            [ChatMessage.user(f"Topic: {course.topic}\nTaught:\n{covered}")],
            system=f"{TEACHER_PROMPT}\n\n{EXAM_REQUEST}",
            temperature=0.3,
            max_tokens=900,
        )
        drafted = extract_objects(reply.text)
        if not drafted:
            raise SchoolError("The teacher did not return a usable test.")
        # A class run again gets a fresh test: old questions don't count.
        await self._store.delete_where(ExamQuestion, {"course_id": course.id})
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
        return questions

    async def _grade_one(
        self, teacher: Agent, question: ExamQuestion, answer: str, notes: str = ""
    ) -> tuple[float, str]:
        """The teacher's score (0-1) and feedback for one answer."""
        checked = f"\nFacts you checked: {notes[:MAX_NOTES]}" if notes else ""
        grade = await self._ask_teacher(
            question.course_id,
            teacher,
            [
                ChatMessage.user(
                    f"Question: {question.prompt}\n"
                    f"Rubric: {question.rubric}\n"
                    f"Student answer: {answer}{checked}"
                )
            ],
            system=f"{TEACHER_PROMPT}\n\n{GRADE_REQUEST}",
            temperature=0.0,
            max_tokens=300,
        )
        payload = extract_object(grade.text)
        return clamped_score(payload.get("score")), str(
            payload.get("feedback", "")
        ).strip()

    async def _record_result(
        self, course: Course, teacher: Agent, student: Agent, final: float
    ) -> Course:
        passed = final >= course.pass_mark
        graded = await self._set(
            course.id,
            status="passed" if passed else "failed",
            score=round(final, 4),
            passed=passed,
            activity="Class finished.",
        )
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

    # ------------------------------------------------------------ the owner's
    # classroom: propose, confirm, step out, a test that waits for the teacher.

    async def _set(self, course_id: str, **fields: object) -> Course:
        """Change a few fields of the latest copy of a course.

        The teacher and the student run at once during the test, so each
        change is made under the class's lock: one can't put back a stale
        copy over the other's change (e.g. the teacher coming back).
        """
        async with _course_lock(course_id):
            course = await self._store.require(Course, course_id)
            updated = course.model_copy(update={**fields, "updated_at": now_ms()})
            await self._store.put(updated)
            return updated

    async def _event(self, course: Course, author: str, text: str, kind: str) -> None:
        await self._store.append_message(
            chat_id=course.chat_id,
            role="event",
            text=text,
            author=author,
            data={"kind": kind, "course_id": course.id},
        )

    async def propose(self, course_id: str, request: str) -> Course:
        """The owner says what the student should learn; the teacher plans it."""
        wanted = request.strip()
        if not wanted:
            raise SchoolError("Tell the teacher what the student should learn.")
        course = await self._store.require(Course, course_id)
        if course.plan_confirmed:
            raise SchoolError("The plan is confirmed; open a new class to change it.")
        teacher = await self._store.require(Agent, course.teacher_agent_id)
        goal = f"{course.goal}\n{wanted}".strip() if course.goal else wanted
        await self._set(
            course_id, activity=f"{teacher.name} is writing the lesson plan."
        )
        old = await self._store.find(
            Lesson, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        current = "\n".join(
            f"{lesson.ordinal}. {lesson.topic}: {lesson.objective}" for lesson in old
        )
        reply = await self._ask_teacher(
            course.id,
            teacher,
            [
                ChatMessage.user(
                    f"Class topic: {course.topic}\n"
                    f"What the owner wants the student to learn:\n{goal}\n"
                    + (f"\nThe plan so far:\n{current}\n" if current else "")
                    + f"\nThe owner's latest message: {wanted}"
                )
            ],
            system=f"{TEACHER_PROMPT}\n\n{PROPOSE_REQUEST}",
            temperature=0.4,
            max_tokens=1200,
        )
        payload = extract_object(reply.text)
        rows = payload.get("lessons")
        planned = (
            [row for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else extract_objects(reply.text)
        )
        planned = [row for row in planned if str(row.get("topic", "")).strip()]
        if not planned:
            await self._set(course_id, activity="")
            raise SchoolError("The teacher did not return a usable lesson plan.")
        await self._set(course_id, goal=goal)
        for lesson in old:
            await self._store.delete(Lesson, lesson.id)
        lessons = [
            Lesson.model_validate(
                {
                    "course_id": course.id,
                    "ordinal": index,
                    "topic": str(row.get("topic", "")).strip()[:200],
                    "objective": str(row.get("objective", "")).strip()[:400],
                    "research": str(row.get("research", "") or "").strip()[:200],
                }
            )
            for index, row in enumerate(planned[:MAX_LESSONS], start=1)
        ]
        await self._store.put_many(lessons)
        outline = "\n".join(
            f"{lesson.ordinal}. {lesson.topic}: {lesson.objective}"
            + (f" (I'll look up: {lesson.research})" if lesson.research else "")
            for lesson in lessons
        )
        note = str(payload.get("note", "")).strip()
        await self._store.append_message(
            chat_id=course.chat_id,
            role="assistant",
            text=(
                (f"{note}\n\n" if note else "")
                + f"Lesson plan:\n{outline}\n\nConfirm it, or tell me what to change."
            ),
            author=teacher.name,
            data={"kind": "plan_proposed", "lessons": len(lessons)},
        )
        return await self._set(
            course_id,
            status="proposed",
            lesson_total=len(lessons),
            lesson_done=0,
            activity="Waiting for you to confirm the lesson plan.",
        )

    async def talk(self, course_id: str, text: str) -> Course:
        """A message from the owner to the teacher."""
        said = text.strip()
        if not said:
            raise SchoolError("Write a message for the teacher.")
        course = await self._store.require(Course, course_id)
        await self._store.append_message(
            chat_id=course.chat_id,
            role="user",
            text=said,
            author="You",
            data={"kind": "owner"},
        )
        if not course.plan_confirmed and course.status in {"planning", "proposed"}:
            return await self.propose(course_id, said)
        teacher = await self._store.require(Agent, course.teacher_agent_id)
        lessons = await self._store.find(
            Lesson, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        plan = "\n".join(
            f"{item.ordinal}. {item.topic} ({item.status})" for item in lessons
        )
        await self._say(
            course,
            teacher,
            system=(
                f"{TEACHER_PROMPT}\n\nThe owner of this classroom is talking to "
                "you. Answer them plainly and briefly about the class."
            ),
            prompt=(
                f"Class topic: {course.topic}\nGoal: {course.goal}\n"
                f"Status: {course.status}; {course.activity}\nPlan:\n{plan}\n\n"
                f"The owner says: {said}"
            ),
            kind="teacher_reply",
        )
        return await self._store.require(Course, course_id)

    async def confirm(self, course_id: str) -> Course:
        """The owner confirms the lesson plan; teaching may start."""
        course = await self._store.require(Course, course_id)
        if course.status != "proposed" or course.lesson_total < 1:
            raise SchoolError("There is no lesson plan to confirm yet.")
        teacher = await self._store.require(Agent, course.teacher_agent_id)
        course = await self._set(
            course_id,
            plan_confirmed=True,
            status="teaching",
            activity=f"{teacher.name} is starting the first lesson.",
        )
        await self._event(
            course, "You", "You confirmed the lesson plan.", "plan_confirmed"
        )
        return course

    async def run_confirmed(
        self, course_id: str, *, tune_on_pass: bool = False
    ) -> Course:
        """Teach the confirmed plan, then the test that waits for the teacher."""
        course = await self._store.require(Course, course_id)
        if not course.plan_confirmed:
            raise SchoolError("Confirm the lesson plan first.")
        teacher = await self._store.require(Agent, course.teacher_agent_id)
        student = await self._store.require(Agent, course.student_agent_id)
        try:
            course = await self._teach(course, teacher, student)
            course = await self._examine_live(course, teacher, student)
            if course.passed and tune_on_pass:
                course = await self._tune_student(course, teacher, student)
            return course
        except asyncio.CancelledError:
            # Stopped from outside (Studio shutting down): don't leave the
            # teacher marked out of the room or the class mid-test.
            await self._set(
                course_id,
                status="failed",
                error="The class was stopped.",
                teacher_present=True,
                teacher_away="",
                activity="The class stopped.",
            )
            raise
        except (SchoolError, StudioLLMError, TuningError) as error:
            logger.warning("Studio class {} failed: {}", course_id, error)
            failed = await self._set(
                course_id,
                status="failed",
                error=str(error),
                teacher_present=True,
                teacher_away="",
                activity="The class stopped.",
            )
            await self._store.append_message(
                chat_id=course.chat_id,
                role="event",
                text=f"Class stopped: {error}",
                author="studio",
                data={"kind": "course_failed"},
            )
            return failed

    async def send_out(self, course_id: str, query: str) -> Course:
        """The owner sends the teacher out to learn more about something."""
        wanted = query.strip()
        if not wanted:
            raise SchoolError("Say what the teacher should look up.")
        course = await self._store.require(Course, course_id)
        if not course.teacher_present:
            raise SchoolError("The teacher is already out of the classroom.")
        teacher = await self._store.require(Agent, course.teacher_agent_id)
        notes = await self._step_out(
            course_id, teacher, wanted, f"learn about {wanted}"
        )
        course = await self._store.require(Course, course_id)
        await self._say(
            course,
            teacher,
            system=TEACHER_PROMPT,
            prompt=(
                f"You went to learn about: {wanted}\nWhat you found:\n"
                f"{notes[:MAX_NOTES] or '(nothing new)'}\n\nTell the owner in "
                "three or four sentences what you learned and how you'll use it."
            ),
            kind="teacher_back_notes",
        )
        return await self._store.require(Course, course_id)

    async def _step_out(
        self, course_id: str, teacher: Agent, query: str, reason: str
    ) -> str:
        """The teacher leaves the classroom to learn more, then comes back."""
        course = await self._set(
            course_id,
            teacher_present=False,
            teacher_away=reason,
            activity=f"{teacher.name} left the classroom to {reason}.",
        )
        await self._event(
            course,
            teacher.name,
            f"{teacher.name} left the classroom to {reason}.",
            "teacher_left",
        )
        notes = ""
        if self._researcher is not None:
            try:
                notes = (await self._researcher(query)).strip()[:MAX_NOTES]
            except Exception as error:  # a failed search mustn't end the class
                logger.warning("Studio class research failed: {}", error)
        course = await self._store.require(Course, course_id)
        knowledge = course.knowledge
        if notes:
            knowledge = f"{knowledge}\n[{query}] {notes}".strip()[-MAX_KNOWLEDGE:]
        course = await self._set(
            course_id,
            teacher_present=True,
            teacher_away="",
            knowledge=knowledge,
            activity=f"{teacher.name} is back in the classroom.",
        )
        await self._event(
            course,
            teacher.name,
            f"{teacher.name} is back"
            + (f" with notes on {query}." if notes else " (found nothing new)."),
            "teacher_back",
        )
        return notes

    async def _examine_live(
        self, course: Course, teacher: Agent, student: Agent
    ) -> Course:
        """The test: the student works while the teacher is out checking facts;
        a question waits until the teacher is back; then the teacher grades."""
        course = await self._set(
            course.id, status="examining", activity="The teacher is writing the test."
        )
        questions = await self._draft_exam(course, teacher)
        back = asyncio.Event()

        async def teacher_side() -> str:
            rubrics = "; ".join(question.rubric for question in questions)[:160]
            try:
                return await self._step_out(
                    course.id,
                    teacher,
                    f"{course.topic} {rubrics}".strip(),
                    "check the facts for marking the test",
                )
            finally:
                back.set()  # a waiting student never hangs

        async def student_side() -> None:
            for question in questions:
                await self._set(
                    course.id,
                    activity=f"{student.name} is on question {question.ordinal} of "
                    f"{len(questions)}.",
                )
                await self._store.put(question.model_copy(update={"state": "working"}))
                system = await self._student_system(student, course.topic)
                answer = await self._say(
                    course,
                    student,
                    system=f"{system}\n\n{TEST_RULES}",
                    prompt=f"Test question {question.ordinal}: {question.prompt}",
                    kind="exam_answer",
                    question_id=question.id,
                )
                asked = help_request(answer)
                if asked:
                    away = not back.is_set()
                    await self._store.put(
                        question.model_copy(
                            update={"state": "waiting", "help_request": asked}
                        )
                    )
                    if away:
                        await self._set(
                            course.id,
                            activity=f"{student.name} is waiting for the teacher to "
                            "come back.",
                        )
                        await self._event(
                            course,
                            student.name,
                            f"{student.name} is waiting for {teacher.name}: {asked}",
                            "student_waiting",
                        )
                    await back.wait()
                    reply = await self._say(
                        course,
                        teacher,
                        system=TEACHER_PROMPT,
                        prompt=(
                            f"During the test on {course.topic}, your student asks: "
                            f"{asked}\nHelp in two or three sentences without "
                            f"giving the answer to this question away: "
                            f"{question.prompt}"
                        ),
                        kind="teacher_help",
                        question_id=question.id,
                    )
                    answer = await self._say(
                        course,
                        student,
                        system=system,
                        prompt=(
                            f"Test question {question.ordinal}: {question.prompt}\n"
                            f"Your teacher answered your question: {reply}\n"
                            "Give your final answer now."
                        ),
                        kind="exam_answer",
                        question_id=question.id,
                    )
                    question = question.model_copy(
                        update={"help_request": asked, "help_reply": reply}
                    )
                await self._store.put(
                    question.model_copy(update={"answer": answer, "state": "answered"})
                )

        sides = (
            asyncio.create_task(teacher_side()),
            asyncio.create_task(student_side()),
        )
        try:
            notes, _ = await asyncio.gather(*sides)
        except BaseException:
            # One side failed: stop the other so it can't write to a class
            # that has already stopped.
            for side in sides:
                side.cancel()
            await asyncio.gather(*sides, return_exceptions=True)
            raise
        await self._set(course.id, activity=f"{teacher.name} is marking the test.")
        total = 0.0
        answered = await self._store.find(
            ExamQuestion, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        for question in answered:
            score, feedback = await self._grade_one(
                teacher, question, question.answer, notes
            )
            total += score
            await self._store.put(
                question.model_copy(
                    update={"score": score, "feedback": feedback, "state": "graded"}
                )
            )
            await self._store.append_message(
                chat_id=course.chat_id,
                role="event",
                text=f"Q{question.ordinal}: {score:.0%} — {feedback}",
                author=teacher.name,
                data={"kind": "grade", "question_id": question.id, "score": score},
            )
        return await self._record_result(
            course, teacher, student, total / len(answered)
        )

    async def _tune_student(
        self, course: Course, teacher: Agent, student: Agent
    ) -> Course:
        """Turn a passed class into a very light tune the teacher coaches."""
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
            student,
            name=f"{student.name} · {course.topic[:24]}",
            teacher_model=teacher.model or self._default_model,
            opted_in=True,
        )
        await self._tuner.add_samples(pack.id, pairs)
        job = await self._tuner.start(pack.id)
        updated = await self._set(course.id, tune_job_id=job.id)
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
        private = self._sealed is not None and await self._sealed(student)
        if student.memory_enabled and not private:
            parts.append(await self._memory.context_block(student.id, topic))
        return "\n\n".join(part for part in parts if part.strip())

    async def class_notes(self, course: Course) -> str:
        """The class so far in a few lines: what a new teacher model needs.

        Built from the records (no model call), and short, so every teacher
        call can carry it: when an API gives the teacher a different model
        mid-class, the new one picks up where the last one stopped.
        """
        lessons = await self._store.find(
            Lesson, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        questions = await self._store.find(
            ExamQuestion, where={"course_id": course.id}, order_by="ordinal ASC"
        )
        lines = [f"Class: {course.topic} (status: {course.status})"]
        if course.goal:
            lines.append(f"The owner wants: {_clip(course.goal, 300)}")
        if lessons:
            lines.append(
                "Plan "
                + ("(confirmed):" if course.plan_confirmed else "(not confirmed):")
            )
            for lesson in lessons:
                learned = (
                    f" - learned: {_clip(lesson.notes, 140)}" if lesson.notes else ""
                )
                lines.append(
                    f"{lesson.ordinal}. {_clip(lesson.topic, 80)} [{lesson.status}]{learned}"
                )
        graded = [item for item in questions if item.score is not None]
        if graded:
            weak = [item for item in graded if (item.score or 0) < course.pass_mark]
            lines.append(
                f"Test: {len(graded)}/{len(questions)} graded, average "
                f"{student_progress(graded):.0%}"
                + (
                    "; weak on: "
                    + "; ".join(_clip(item.prompt, 60) for item in weak[:3])
                    if weak
                    else ""
                )
            )
        elif questions:
            lines.append(f"Test: {len(questions)} questions, being answered")
        if course.knowledge:
            lines.append(f"Looked up earlier: {_clip(course.knowledge, 400)}")
        if course.tune_job_id:
            job = (
                await self._store.get(LoraJob, course.tune_job_id)
                if course.tune_job_id.startswith("lora")
                else None
            )
            state = f"{job.status}; {_clip(job.message, 120)}" if job else "tuning"
            lines.append(f"Training the student on this class: {state}")
        return _clip("\n".join(lines), MAX_CLASS_NOTES)

    async def _ask_teacher(
        self,
        course_id: str,
        teacher: Agent,
        messages: list[ChatMessage],
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMReply:
        """One teacher call, carrying the class notes; notices a model switch."""
        course = await self._store.require(Course, course_id)
        notes = await self.class_notes(course)
        reply = await self._router.complete(
            messages,
            model=teacher.model or self._default_model,
            system=f"{system}\n\n{CLASS_NOTES_HEAD}\n{notes}",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        served = reply.model.strip()
        if served:
            current = await self._store.require(Course, course_id)
            if current.teacher_model and current.teacher_model != served:
                await self._event(
                    current,
                    "studio",
                    f"The teacher's API switched models ({current.teacher_model} "
                    f"to {served}). The new model got the class notes: the plan, "
                    "what the student learned, the grades and the training.",
                    "teacher_handover",
                )
            if current.teacher_model != served:
                await self._set(course_id, teacher_model=served)
        return reply

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
        if speaker.id == course.teacher_agent_id:
            reply = await self._ask_teacher(
                course.id,
                speaker,
                [ChatMessage.user(prompt)],
                system=system,
                temperature=0.5,
                max_tokens=700,
            )
        else:
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


_COURSE_LOCKS: dict[str, asyncio.Lock] = {}


def _course_lock(course_id: str) -> asyncio.Lock:
    return _COURSE_LOCKS.setdefault(course_id, asyncio.Lock())


def _clip(text: str, limit: int) -> str:
    flat = text.strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "\u2026"


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


def help_request(answer: str) -> str:
    """The question a student asked its teacher in a test answer, if any."""
    for line in answer.splitlines():
        stripped = line.strip().lstrip("*_ ").strip()
        if stripped.upper().startswith(HELP_MARK):
            return stripped[len(HELP_MARK) :].strip(" *_:")[:400]
    return ""
