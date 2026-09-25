"""Learn mode: the main AI teaches itself a subject, lesson by lesson.

It plans a short course, researches each lesson on the web, Reddit, and
YouTube, writes its own lesson notes, quizzes itself on them, and keeps
everything in the team's memory and a knowledge library. Progress is saved
after every source read, so the HUD's bar fills as it goes.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from loguru import logger

from .llm import ChatMessage, StudioLLMError, StudioModelRouter
from .memory import keywords
from .models import Study, StudyLesson, now_ms
from .research import ResearchReport, relevance
from .store import StudioStore

LESSONS = {"quick": 4, "normal": 7, "deep": 10}
SOURCES = {"quick": 5, "normal": 7, "deep": 10}
RESEARCH_SHARE = 0.6
PROGRESS_SECONDS = 0.5
NOTES_SHARE = 0.25
REPORT_CHARS = 6_500
KNOWLEDGE_TAGS = ("knowledge", "learned")
FALLBACK_PLAN = (
    "What {topic} is and why it matters",
    "Core concepts and vocabulary of {topic}",
    "The key rules, formulas, and principles",
    "Tools, materials, and components",
    "Step-by-step: doing it in practice",
    "Worked examples and small projects",
    "Common mistakes and safety",
    "Designing and planning your own",
    "Troubleshooting and testing",
    "Advanced topics and where to go next",
)

PLAN_PROMPT = (
    "You plan a course so an AI assistant can really learn a subject, from the "
    "foundations to practical, hands-on skill. List exactly {count} lessons in "
    "order, one per line, each a short title of 3 to 8 words. Write only the "
    "list."
)
NOTES_PROMPT = (
    "You are {name}, teaching yourself {topic} well enough to explain it, "
    "solve problems, and design and build things with it. From the sources "
    "below, write your own lesson notes on: {lesson}. Use these headings: "
    "Explanation (plain words), Key concepts, Formulas and rules (with units), "
    "How to do it (numbered steps), Worked example, Common mistakes and "
    "safety, Sources (as [n] with their links). Cite sources as [n]. Keep only "
    "what the sources and sound knowledge support. Stay under 500 words."
)
QUIZ_PROMPT = (
    "Check that you understood this lesson. Write 3 questions that test real "
    "understanding, one of them applying it to a new situation, and answer "
    "each from the notes. Write each as 'Q: ...' on one line and 'A: ...' on "
    "the next."
)
GUIDE_PROMPT = (
    "You finished teaching yourself {topic}. From your lesson notes below, "
    "write a study guide: an overview, the big ideas, how the lessons connect, "
    "what you can now do with it, and what to learn next. Under 350 words."
)

type Researcher = Callable[[str, int, Callable[[str], None]], Awaitable[ResearchReport]]
type Remember = Callable[[str, tuple[str, ...], str], Awaitable[str]]


class StudyStopped(Exception):
    """Raised inside a study when the user stopped it."""


@dataclass(frozen=True, slots=True)
class LessonResult:
    notes: str
    quiz: tuple[tuple[str, str], ...]
    score: float
    sources: tuple[str, ...]


def parse_plan(text: str, *, count: int) -> list[str]:
    """Lesson titles from the model's list, without numbers or bullets."""
    titles: list[str] = []
    for raw in text.splitlines():
        line = re.sub(
            r"^\s*(?:[-*•]|\d+[.):]|lesson \d+[:.)-]?)\s*", "", raw, flags=re.I
        )
        line = line.strip().strip("*#").strip()
        if 3 <= len(line) <= 90 and line.lower() not in {t.lower() for t in titles}:
            titles.append(line)
    return titles[:count]


def parse_quiz(text: str) -> tuple[tuple[str, str], ...]:
    """(question, answer) pairs from 'Q: ... / A: ...' lines."""
    pairs: list[tuple[str, str]] = []
    question = ""
    answer: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        found_q = re.match(
            r"^(?:\*\*)?(?:Q\d*|Question \d*)[:.)]\s*(?:\*\*)?\s*(.*)", line, re.I
        )
        found_a = re.match(
            r"^(?:\*\*)?(?:A\d*|Answer \d*)[:.)]\s*(?:\*\*)?\s*(.*)", line, re.I
        )
        if found_q:
            if question and answer:
                pairs.append((question, " ".join(answer)))
            question, answer = found_q.group(1).strip(), []
        elif found_a and question:
            answer = [found_a.group(1).strip()]
        elif line and question and answer:
            answer.append(line)
    if question and answer:
        pairs.append((question, " ".join(answer)))
    return tuple(pairs[:5])


def self_check(notes: str, quiz: Sequence[tuple[str, str]]) -> float:
    """How well the answers are grounded in the notes, 0 to 1."""
    if not quiz:
        return 0.0
    marks = []
    for _, answer in quiz:
        terms = keywords(answer, limit=10)
        marks.append(1.0 if terms and relevance(notes, terms) >= 0.5 else 0.0)
    return sum(marks) / len(marks)


def source_lines(report: ResearchReport) -> tuple[str, ...]:
    return tuple(f"[{s.number}] {s.title} — {s.url}" for s in report.sources)


class LearnEngine:
    """Run one study from plan to study guide, saving progress as it goes."""

    def __init__(
        self,
        *,
        store: StudioStore,
        router: StudioModelRouter,
        model: Callable[[], Awaitable[str]],
        research: Researcher,
        remember: Remember,
        name: str = "Jarvis",
    ) -> None:
        self._store = store
        self._router = router
        self._model = model
        self._research = research
        self._remember = remember
        self._name = name

    async def run(self, study_id: str) -> Study:
        study = await self._store.require(Study, study_id)
        model = await self._model()
        count = LESSONS.get(study.depth, LESSONS["normal"])
        study = await self._save(study, step=f"Planning a course on {study.topic}")
        plan = await self._plan(study, model, count)
        study = await self._save(study, status="learning", plan=tuple(plan))
        scores: list[float] = []
        for index, title in enumerate(plan):
            result = await self._lesson(study, model, index, len(plan), title)
            scores.append(result.score)
            study = await self._save(
                await self._fresh(study),
                done=index + 1,
                progress=(index + 1) / len(plan) * 0.97,
                understanding=sum(scores) / len(scores),
            )
        study = await self._save(study, step="Writing the study guide")
        guide = await self._guide(study, model)
        memory_id = await self._remember(
            f"Learned {study.topic}: study guide. {' '.join(guide.split())[:600]} "
            f"Full lessons: knowledge study {study.id}.",
            (*KNOWLEDGE_TAGS, _tag(study.topic)),
            study.id,
        )
        return await self._save(
            await self._fresh(study),
            status="done",
            progress=1.0,
            summary=guide,
            memory_id=memory_id,
            step=f"Finished: {len(plan)} lessons on {study.topic}",
        )

    async def _plan(self, study: Study, model: str, count: int) -> list[str]:
        aim = f" Focus on: {study.focus}." if study.focus else ""
        try:
            text = await self._ask(
                model,
                PLAN_PROMPT.format(count=count),
                f"Subject: {study.topic}.{aim}",
                max_tokens=400,
            )
            plan = parse_plan(text, count=count)
        except StudioLLMError as error:
            logger.info(
                "Studio: study plan fell back to the standard course: {}", error
            )
            plan = []
        if len(plan) < max(3, count // 2):
            plan = [line.format(topic=study.topic) for line in FALLBACK_PLAN[:count]]
        return plan

    async def _lesson(
        self, study: Study, model: str, index: int, total: int, title: str
    ) -> LessonResult:
        base = index / total * 0.97
        span = 0.97 / total
        label = f"Lesson {index + 1} of {total}"
        study = await self._save(
            await self._fresh(study),
            step=f"{label}: researching {title}",
            progress=base,
        )
        report = await self._research_with_progress(
            study,
            f"{title} ({study.topic})",
            base,
            span,
            f"{label}: reading about {title}",
        )
        await self._save(
            await self._fresh(study),
            step=f"{label}: writing notes on {title}",
            progress=base + span * RESEARCH_SHARE,
        )
        notes = await self._notes(study, model, title, report)
        await self._save(
            await self._fresh(study),
            step=f"{label}: checking what I understood",
            progress=base + span * (RESEARCH_SHARE + NOTES_SHARE),
        )
        quiz: tuple[tuple[str, str], ...] = ()
        try:
            quiz = parse_quiz(
                await self._ask(
                    model, QUIZ_PROMPT, f"Lesson notes:\n{notes}", max_tokens=500
                )
            )
        except StudioLLMError as error:
            logger.info("Studio: study self-check skipped: {}", error)
        score = self_check(notes, quiz)
        lesson = StudyLesson(
            study_id=study.id,
            ordinal=index,
            title=title,
            notes=notes,
            quiz=quiz,
            score=score,
            sources=source_lines(report),
        )
        memory_id = await self._remember(
            f"Learned ({study.topic} → {title}): {' '.join(notes.split())[:500]} "
            f"Full lesson: knowledge {lesson.id}.",
            (*KNOWLEDGE_TAGS, _tag(study.topic)),
            lesson.id,
        )
        await self._store.put(lesson.model_copy(update={"memory_id": memory_id}))
        return LessonResult(notes, quiz, score, lesson.sources)

    async def _research_with_progress(
        self, study: Study, query: str, base: float, span: float, label: str
    ) -> ResearchReport:
        """Research one lesson, moving the bar a little for every source read."""
        wanted = SOURCES.get(study.depth, SOURCES["normal"])
        read: list[str] = []
        job = asyncio.ensure_future(self._research(query, wanted, read.append))
        shown = 0
        try:
            while not job.done():
                await asyncio.wait({job}, timeout=PROGRESS_SECONDS)
                if len(read) != shown:
                    shown = len(read)
                    share = min(1.0, shown / (wanted * 2)) * RESEARCH_SHARE
                    await self._save(
                        await self._fresh(study),
                        progress=base + span * share,
                        step=f"{label} (source {shown}: {read[-1][:60]})",
                    )
            return job.result()
        finally:
            if not job.done():
                job.cancel()

    async def _notes(
        self, study: Study, model: str, title: str, report: ResearchReport
    ) -> str:
        material = report.render()[:REPORT_CHARS]
        try:
            text = await self._ask(
                model,
                NOTES_PROMPT.format(name=self._name, topic=study.topic, lesson=title),
                f"Sources:\n{material}",
                max_tokens=900,
            )
        except StudioLLMError as error:
            logger.info("Studio: lesson notes fell back to the sources: {}", error)
            text = ""
        if text.strip():
            return text.strip()
        excerpts = "\n".join(
            f"- {s.excerpt[:300]} [{s.number}]" for s in report.sources if s.excerpt
        )
        return (
            f"Explanation:\n{excerpts or 'No sources could be read for this lesson.'}\n\n"
            f"Sources:\n" + "\n".join(source_lines(report))
        )

    async def _guide(self, study: Study, model: str) -> str:
        lessons = await self._store.find(
            StudyLesson, where={"study_id": study.id}, order_by="ordinal ASC"
        )
        material = "\n\n".join(
            f"Lesson {lesson.ordinal + 1}: {lesson.title}\n{lesson.notes[:700]}"
            for lesson in lessons
        )
        try:
            text = await self._ask(
                model,
                GUIDE_PROMPT.format(topic=study.topic),
                material[:REPORT_CHARS],
                max_tokens=700,
            )
            if text.strip():
                return text.strip()
        except StudioLLMError as error:
            logger.info("Studio: study guide fell back to the lesson list: {}", error)
        return "Lessons learned:\n" + "\n".join(
            f"- {lesson.title}" for lesson in lessons
        )

    async def _ask(
        self, model: str, system: str, prompt: str, *, max_tokens: int
    ) -> str:
        reply = await self._router.complete(
            [ChatMessage.user(prompt)],
            model=model,
            system=system,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return reply.text.strip()

    async def _fresh(self, study: Study) -> Study:
        current = await self._store.require(Study, study.id)
        if current.status == "cancelled":
            raise StudyStopped
        return current

    async def _save(self, study: Study, **values: object) -> Study:
        current = await self._store.get(Study, study.id)
        if current is not None and current.status == "cancelled":
            raise StudyStopped
        updated = study.model_copy(update={**values, "updated_at": now_ms()})
        await self._store.put(updated)
        return updated


def _tag(topic: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", topic.lower()))[:40] or "topic"


_LEARN = re.compile(
    r"^\s*(?:(?:hey\s+)?jarvis[,:!]?\s*)?(?:(?:can|could|would|will) you\s+|please\s+|"
    r"i (?:want|need|would like|'d like) you to\s+|go (?:and\s+)?|now\s+|"
    r"quickly\s+|briefly\s+|properly\s+|fully\s+)*"
    r"(?:learn|study|teach yourself|research and learn|master|"
    r"become an expert (?:in|on|at)|get good at)\s+"
    r"(?:(?:all |everything )?about\s+)?(?P<topic>.+)$",
    re.I | re.S,
)
_STOP_LEARNING = re.compile(
    r"\b(?:stop|cancel|quit|pause|end)\s+(?:the\s+|your\s+)?(?:learning|studying|study|lesson|course)\b",
    re.I,
)
_DEEP = re.compile(
    r"\b(in depth|in-depth|deeply|thoroughly|everything|all about|master|expert)\b",
    re.I,
)
_QUICK = re.compile(r"\b(quick(?:ly)?|the basics|briefly|a little)\b", re.I)


def parse_learn_request(text: str) -> tuple[str, str] | None:
    """('electrical engineering', 'normal') from 'Jarvis, learn electrical engineering'."""
    found = _LEARN.match(text.strip())
    if not found:
        return None
    topic = found.group("topic").strip()
    topic = re.sub(r"[\s.!?]+$", "", topic)
    topic = re.sub(
        r"^(?:the\s+)?(?:basics of|topic of|subject of)\s+", "", topic, flags=re.I
    )
    topic = re.sub(
        r"\s+(?:for me|please|in depth|in-depth|deeply|thoroughly|quickly)$",
        "",
        topic,
        flags=re.I,
    )
    if len(topic.split()) < 1 or len(topic) < 3 or len(topic) > 160:
        return None
    depth = (
        "deep" if _DEEP.search(text) else "quick" if _QUICK.search(text) else "normal"
    )
    return topic, depth


def wants_to_stop_learning(text: str) -> bool:
    return bool(_STOP_LEARNING.search(text))
