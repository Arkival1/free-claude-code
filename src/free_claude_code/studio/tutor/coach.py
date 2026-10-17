"""The maths tutor: questions, marking, progress, practice tests and help.

Questions and answers come from ``topics`` (worked out in code). A model
only explains: it is given the right answer and working and told not to
change them, and its words are labelled as the AI's.
"""

import random
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping

from loguru import logger

from free_claude_code.core.json_types import JsonObject, JsonValue

from ..models import TutorAttempt
from ..store import StudioStore
from .pathway import pathway
from .topics import BY_ID, STAGES, TOPICS, Question, fmt, make_question

Think = Callable[[str, str], Awaitable[str]]
"""Ask a model: (system, prompt) → reply text."""

WINDOW = 10
"""Mastery is the share right of the last 10 answers on a topic."""
STRONG_RUN = 5
STRONG_SHARE = 0.8
"""A topic is strong at 4 or more right of the last 5."""
TEST_SIZE = 10
MAX_SEED = 10**9
MAX_GIVEN = 80
MAX_ASK = 1000
STAGE_TITLES = dict(STAGES)

_SYSTEM = (
    "You are a patient maths tutor for an electrical apprentice in Sydney, "
    "NSW, Australia, working towards the Certificate III in "
    "Electrotechnology Electrician (UEE30820) and an electrician's licence. "
    "Use plain, short sentences and Australian terms. "
)
_EXPLAIN = _SYSTEM + (
    "The correct answer and working below were calculated exactly in code: "
    "never change them or give a different answer. If the student gave an "
    "answer, say kindly where they most likely went wrong. Then explain the "
    "working in your own words and finish with one tip to remember it. "
    "At most 180 words."
)
_ASK = _SYSTEM + (
    "Answer the maths question, showing each step with the units. If it "
    "needs a value from an Australian Standard (AS/NZS 3000 or 3008), say "
    "which table to look in instead of quoting a number. If it isn't about "
    "maths for electrical work, answer briefly and steer back. At most 250 "
    "words."
)

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?")
_FRACTION = re.compile(r"([-+]?\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)(?![\d.])")


class TutorError(ValueError):
    """A request the tutor can't serve (unknown topic, bad question id)."""


def parse_answer(text: str) -> float | None:
    """A typed answer as a number: 12.5, 1,200, $32.20, 3/4, 85%, 1.2e3, 4.7×10^3."""
    cleaned = text.strip().lower()
    if "=" in cleaned:
        cleaned = cleaned.rsplit("=", 1)[1]
    for dash in ("−", "–"):
        cleaned = cleaned.replace(dash, "-")
    for gone in (",", "$", " "):
        cleaned = cleaned.replace(gone, "")
    for times in ("×10^", "x10^", "*10^"):
        cleaned = cleaned.replace(times, "e")
    fraction = _FRACTION.match(cleaned)
    if fraction:
        bottom = float(fraction.group(2))
        return float(fraction.group(1)) / bottom if bottom else None
    number = _NUMBER.match(cleaned)
    if not number:
        return None
    try:
        value = float(number.group(0))
    except ValueError:
        return None
    return value if abs(value) < 1e15 else None


def rebuild(question_id: str) -> Question:
    """The question an id names (``topic:seed``), made again exactly."""
    topic_id, _, seed = question_id.partition(":")
    if topic_id not in BY_ID or not seed.isdigit() or int(seed) >= MAX_SEED:
        raise TutorError("That question isn't one the tutor knows.")
    return make_question(topic_id, int(seed))


def question_view(question: Question, *, hint: bool = True) -> JsonObject:
    topic = BY_ID[question.topic]
    view: JsonObject = {
        "id": question.id,
        "topic": topic.id,
        "topic_title": topic.title,
        "prompt": question.prompt,
        "unit": question.unit,
        "places": question.places,
    }
    if hint:
        view["hint"] = question.hint
    return view


def _fresh(topic_id: str) -> Question:
    return make_question(topic_id, random.SystemRandom().randrange(MAX_SEED))


class Tutor:
    def __init__(self, store: StudioStore, *, think: Think | None = None) -> None:
        self._store = store
        self._think = think

    def overview(self) -> JsonObject:
        """The licence path, the stages and every topic's lesson."""
        return {
            "pathway": pathway(),
            "stages": [{"id": stage, "title": title} for stage, title in STAGES],
            "topics": [
                {
                    "id": topic.id,
                    "stage": topic.stage,
                    "title": topic.title,
                    "why": topic.why,
                    "lesson": topic.lesson,
                    "formulas": list(topic.formulas),
                }
                for topic in TOPICS
            ],
        }

    def question(self, topic_id: str) -> JsonObject:
        if topic_id not in BY_ID:
            raise TutorError("Pick a topic from the list.")
        return question_view(_fresh(topic_id))

    async def check(self, question_id: str, given: str) -> JsonObject:
        """Mark one answer (in code) and keep the attempt."""
        question = rebuild(question_id)
        value = parse_answer(given)
        if value is None:
            return {
                "understood": False,
                "message": "Type a number, like 12.5, 1,200, 3/4 or 4.7×10^3.",
            }
        correct = question.accepts(value)
        await self._store.put(
            TutorAttempt(
                topic=question.topic,
                question_id=question.id,
                given=given.strip()[:MAX_GIVEN],
                correct=correct,
            )
        )
        return {
            "understood": True,
            "correct": correct,
            "given": fmt(value, max(question.places, 4)),
            "answer": question.shown(),
            "steps": list(question.steps),
        }

    def test(self, stage: str) -> JsonObject:
        """A practice test: 10 questions spread over a stage (or every stage)."""
        if stage != "all" and stage not in STAGE_TITLES:
            raise TutorError("Pick a stage for the test.")
        topics = [topic.id for topic in TOPICS if stage in ("all", topic.stage)]
        chooser = random.SystemRandom()
        chosen: list[str] = []
        while len(chosen) < TEST_SIZE:
            batch = topics[:]
            chooser.shuffle(batch)
            chosen.extend(batch[: TEST_SIZE - len(chosen)])
        return {
            "test_id": f"{stage}:{secrets.token_hex(6)}",
            "stage": stage,
            "title": STAGE_TITLES.get(stage, "Everything"),
            "questions": [question_view(_fresh(topic), hint=False) for topic in chosen],
        }

    async def mark(self, test_id: str, answers: Mapping[str, str]) -> JsonObject:
        """Mark a whole practice test once; every answer is kept."""
        stage, _, token = test_id.partition(":")
        if (stage != "all" and stage not in STAGE_TITLES) or not re.fullmatch(
            r"[0-9a-f]{12}", token
        ):
            raise TutorError("That test isn't one the tutor set.")
        if not answers or len(answers) > TEST_SIZE:
            raise TutorError(f"A test has up to {TEST_SIZE} answers.")
        if await self._store.count(TutorAttempt, where={"test_id": test_id}):
            raise TutorError("That test has already been marked.")
        marked = [
            (rebuild(question_id), given) for question_id, given in answers.items()
        ]
        attempts: list[TutorAttempt] = []
        results: list[JsonValue] = []
        for question, typed in marked:
            given = str(typed).strip()[:MAX_GIVEN]
            value = parse_answer(given) if given else None
            correct = value is not None and question.accepts(value)
            attempts.append(
                TutorAttempt(
                    topic=question.topic,
                    question_id=question.id,
                    given=given,
                    correct=correct,
                    test_id=test_id,
                )
            )
            results.append(
                {
                    **question_view(question, hint=False),
                    "given": given,
                    "correct": correct,
                    "answer": question.shown(),
                    "steps": list(question.steps),
                }
            )
        await self._store.put_many(attempts)
        score = sum(attempt.correct for attempt in attempts)
        share = score / len(attempts)
        weak = sorted(
            {BY_ID[a.topic].title for a in attempts if not a.correct},
        )
        return {
            "test_id": test_id,
            "score": score,
            "total": len(attempts),
            "percent": round(share * 100),
            "results": results,
            "advice": (
                "Strong result. Try the next stage."
                if share >= STRONG_SHARE
                else "Practise these topics, then try again: " + ", ".join(weak) + "."
            ),
        }

    async def progress(self) -> JsonObject:
        """How each topic is going, and what to practise next."""
        attempts = await self._store.find(
            TutorAttempt, order_by="created_at DESC", limit=5000
        )
        by_topic: dict[str, list[bool]] = {}
        for attempt in attempts:
            by_topic.setdefault(attempt.topic, []).append(attempt.correct)
        topics: list[JsonValue] = []
        suggested = ""
        for topic in TOPICS:
            marks = by_topic.get(topic.id, [])
            recent = marks[:WINDOW]
            run = marks[:STRONG_RUN]
            strong = len(run) == STRONG_RUN and sum(run) / STRONG_RUN >= STRONG_SHARE
            if not strong and not suggested:
                suggested = topic.id
            topics.append(
                {
                    "id": topic.id,
                    "answered": len(marks),
                    "mastery": round(100 * sum(recent) / len(recent))
                    if recent
                    else None,
                    "strong": strong,
                }
            )
        tests: dict[str, list[bool]] = {}
        for attempt in attempts:
            if attempt.test_id:
                tests.setdefault(attempt.test_id, []).append(attempt.correct)
        latest = {attempt.test_id: attempt.created_at for attempt in reversed(attempts)}
        return {
            "topics": topics,
            "suggested": suggested,
            "answered": len(attempts),
            "right": sum(attempt.correct for attempt in attempts),
            "tests": [
                {
                    "stage": test_id.partition(":")[0],
                    "score": sum(marks),
                    "total": len(marks),
                    "at": latest[test_id],
                }
                for test_id, marks in list(tests.items())[:8]
            ],
        }

    async def explain(self, question_id: str, given: str = "") -> JsonObject:
        """The worked answer, plus the AI's explanation in plain words."""
        question = rebuild(question_id)
        working: JsonObject = {
            "answer": question.shown(),
            "steps": list(question.steps),
            "explanation": "",
        }
        if self._think is None:
            return working
        lines = [
            f"Question: {question.prompt}",
            f"Correct answer: {question.shown()}",
            "Working:",
            *(f"- {step}" for step in question.steps),
        ]
        if given.strip():
            lines.append(f"The student answered: {given.strip()[:MAX_GIVEN]}")
        try:
            reply = await self._think(_EXPLAIN, "\n".join(lines))
        except Exception as error:
            logger.warning("Tutor explanation failed: {}", type(error).__name__)
            working["note"] = "The AI couldn't be reached, so here is the working."
            return working
        working["explanation"] = reply.strip()
        return working

    async def ask(self, text: str) -> JsonObject:
        """Any maths question, answered by the AI (labelled as its answer)."""
        asked = text.strip()
        if not asked:
            raise TutorError("Type a question.")
        if len(asked) > MAX_ASK:
            raise TutorError(f"Keep questions under {MAX_ASK} characters.")
        if self._think is None:
            raise TutorError("No AI model is set up to answer questions.")
        try:
            reply = await self._think(_ASK, asked)
        except Exception as error:
            logger.warning("Tutor question failed: {}", type(error).__name__)
            raise TutorError("The AI couldn't be reached. Try again.") from error
        return {"answer": reply.strip()}
