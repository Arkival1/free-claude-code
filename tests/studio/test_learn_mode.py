"""Learn mode: Jarvis teaches himself a subject while a progress bar fills."""

import asyncio

import httpx
import pytest

from free_claude_code.studio import learning
from free_claude_code.studio.learning import (
    parse_learn_request,
    parse_plan,
    parse_quiz,
    self_check,
    wants_to_stop_learning,
)
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.memory import SHARED_MEMORY_ID
from free_claude_code.studio.models import Study
from free_claude_code.studio.research import ResearchReport, Source
from tests.api.support import create_test_app

from .conftest import tool_reply

NOTES = (
    "Explanation: Ohm's law says voltage equals current times resistance.\n"
    "Formulas and rules: V = I x R, volts, amps, ohms. [1]"
)


def teacher(system: str, prompt: str):
    if "You plan a course" in system:
        return LLMReply(text="1. Ohm's law\n2. Series circuits\n- Power\n* Safety")
    if "You finished teaching yourself" in system:
        return LLMReply(text="Study guide: circuits follow Ohm's law.")
    if "teaching yourself" in system:
        return LLMReply(text=NOTES)
    if "Check that you understood" in system:
        return LLMReply(
            text="Q: What does Ohm's law say?\n"
            "A: Voltage equals current times resistance."
        )
    if "running notes" in system:
        return LLMReply(text="Goal:\n- Learn")
    return LLMReply(text="On it.")


def source(number: int, title: str) -> Source:
    return Source(
        number=number,
        platform="web",
        title=title,
        url=f"https://example.test/{number}",
        excerpt="Voltage equals current times resistance.",
        read=True,
    )


class FakeResearch:
    """Read two sources per lesson; wait on a gate when one is given."""

    def __init__(self, gate: asyncio.Event | None = None) -> None:
        self.gate = gate
        self.queries: list[str] = []

    async def __call__(self, query, wanted, on_source):
        self.queries.append(query)
        if self.gate is not None:
            await self.gate.wait()
        on_source("Ohm's law explained")
        await asyncio.sleep(0.03)
        on_source("r/AskElectronics: Ohm's law")
        await asyncio.sleep(0.03)
        return ResearchReport(
            question=query,
            sources=(source(1, "Ohm's law explained"), source(2, "Circuits")),
            wanted=wanted,
        )


async def eventually(check, *, tries: int = 500):
    for _ in range(tries):
        if await check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("never happened")


@pytest.fixture(autouse=True)
def quick_progress(monkeypatch):
    monkeypatch.setattr(learning, "PROGRESS_SECONDS", 0.01)


@pytest.mark.parametrize(
    ("text", "wanted"),
    [
        ("Jarvis, learn electrical engineering", ("electrical engineering", "normal")),
        ("learn about blueprints", ("blueprints", "normal")),
        (
            "Can you teach yourself how to make an invention?",
            ("how to make an invention", "normal"),
        ),
        (
            "I want you to learn everything about electronics",
            ("electronics", "deep"),
        ),
        ("study circuit design in depth", ("circuit design", "deep")),
        ("quickly learn the basics of soldering", ("soldering", "quick")),
    ],
)
def test_learn_requests_are_understood(text, wanted):
    assert parse_learn_request(text) == wanted


@pytest.mark.parametrize(
    "text", ["I want to learn guitar", "what did you learn?", "build me a site"]
)
def test_other_messages_are_not_learn_requests(text):
    assert parse_learn_request(text) is None


def test_stop_requests_are_understood():
    assert wants_to_stop_learning("Jarvis, stop learning")
    assert wants_to_stop_learning("cancel the study please")
    assert not wants_to_stop_learning("stop the builder")


def test_plans_and_quizzes_are_parsed():
    assert parse_plan(
        "1. Ohm's law\n2) Circuits\n- Power\nLesson 4: Safety", count=3
    ) == [
        "Ohm's law",
        "Circuits",
        "Power",
    ]
    quiz = parse_quiz(
        "**Q1:** What is V?\n**A1:** Volts.\nQ: And I?\nA: Amps,\nin amperes."
    )
    assert quiz == (("What is V?", "Volts."), ("And I?", "Amps, in amperes."))
    assert self_check(NOTES, (("q", "Voltage equals current times resistance"),)) == 1.0
    assert self_check(NOTES, (("q", "Bananas grow on tropical trees"),)) == 0.0


@pytest.mark.asyncio
async def test_a_study_runs_from_plan_to_study_guide(make_studio):
    studio, _ = make_studio(teacher)
    await studio.ensure_defaults()
    research = FakeResearch()
    studio._study_research = research
    seen: list[tuple[float, str]] = []
    real_put = studio.store.put

    async def watch(record):
        if isinstance(record, Study):
            seen.append((record.progress, record.step))
        return await real_put(record)

    studio.store.put = watch

    study = await studio.start_study("electrical engineering", depth="quick")
    await studio.wait_for_background()

    study, lessons = await studio.study_detail(study.id)
    assert study.status == "done" and study.progress == 1.0
    assert study.plan == ("Ohm's law", "Series circuits", "Power", "Safety")
    assert study.understanding == 1.0 and study.summary.startswith("Study guide")
    assert [lesson.title for lesson in lessons] == list(study.plan)
    assert lessons[0].notes == NOTES and lessons[0].quiz
    assert lessons[0].sources[0].startswith("[1] Ohm's law explained — https://")
    progress = [value for value, _ in seen]
    assert progress == sorted(progress), "the bar only ever moves forward"
    assert any("source 2: r/AskElectronics" in step for _, step in seen)
    assert research.queries[0] == "Ohm's law (electrical engineering)"

    remembered = await studio.memories(SHARED_MEMORY_ID)
    learned = [entry for entry in remembered if "learned" in entry.tags]
    assert len(learned) == 5, "one per lesson plus the study guide"
    assert any(lessons[0].id in entry.text for entry in learned)
    chat = await studio.main_chat()
    last = (await studio.transcript(chat.id))[-1]
    assert last.text.startswith("I finished learning electrical engineering: 4 lessons")


@pytest.mark.asyncio
async def test_telling_jarvis_to_learn_starts_a_study(make_studio):
    studio, model = make_studio(teacher)
    await studio.ensure_defaults()
    studio._study_research = FakeResearch()

    await studio.main_say(
        "Jarvis, learn electrical engineering in depth", background=False
    )

    (study,) = await studio.studies()
    assert (study.topic, study.depth) == ("electrical engineering", "deep")
    chat = await studio.main_chat()
    started = [m for m in await studio.transcript(chat.id) if m.author == "learn"]
    assert started and started[0].text.startswith("Started learning")
    jarvis = [c for c in model.calls if "the user's main AI" in str(c["system"])]
    assert "Do not start it again" in str(jarvis[-1]["studio_note"])
    await studio.wait_for_background()
    assert (await studio.study_detail(study.id))[0].status == "done"


@pytest.mark.asyncio
async def test_stop_learning_keeps_one_study_at_a_time(make_studio):
    studio, _ = make_studio(teacher)
    await studio.ensure_defaults()
    studio._study_research = FakeResearch(gate=asyncio.Event())

    study = await studio.start_study("blueprints")

    async def researching():
        current = await studio.store.get(Study, study.id)
        return current is not None and "researching" in current.step

    await eventually(researching)
    console = await studio.main_console()
    assert console["learning"][0]["topic"] == "blueprints"
    with pytest.raises(Exception, match="Already learning blueprints"):
        await studio.start_study("welding")

    await studio.main_say("stop learning", background=False)
    await studio.wait_for_background()

    stopped, lessons = await studio.study_detail(study.id)
    assert stopped.status == "cancelled" and lessons == ()
    chat = await studio.main_chat()
    assert any(
        "Stopped learning blueprints" in m.text
        for m in await studio.transcript(chat.id)
    )


@pytest.mark.asyncio
async def test_agents_read_what_was_learned(make_studio):
    wanted: dict[str, str] = {}
    script = iter(
        [
            lambda: tool_reply("knowledge", {"query": "ohm law voltage"}),
            lambda: tool_reply("knowledge", {"id": wanted["lesson"]}, call_id="c2"),
            lambda: tool_reply("knowledge", {"id": wanted["study"]}, call_id="c3"),
            lambda: LLMReply(text="V = I x R."),
        ]
    )

    def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            return next(script)()
        return teacher(system, prompt)

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    studio._study_research = FakeResearch()
    study = await studio.start_study("electrical engineering", depth="quick")
    await studio.wait_for_background()
    _, lessons = await studio.study_detail(study.id)
    wanted.update(lesson=lessons[0].id, study=study.id)

    await studio.main_say("what is ohm's law?", background=False)

    chat = await studio.main_chat()
    found, lesson, whole = [
        m for m in await studio.transcript(chat.id) if m.role == "tool"
    ][-3:]
    assert f"{lessons[0].id}: electrical engineering → Ohm's law" in found.text
    assert lesson.text.startswith("Lesson 1 of electrical engineering: Ohm's law")
    assert "Self-check:\nQ: What does Ohm's law say?" in lesson.text
    assert "Study guide: circuits follow Ohm's law." in whole.text
    main = await studio.main_agent()
    assert {"learn", "knowledge"} <= set(main.tools)


@pytest.mark.asyncio
async def test_studies_through_the_routes(make_studio):
    studio, _ = make_studio(teacher)
    await studio.ensure_defaults()
    gate = asyncio.Event()
    studio._study_research = FakeResearch(gate=gate)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            made = await client.post(
                "/studio/api/studies",
                json={"topic": "PCB design", "focus": "blueprints", "depth": "quick"},
            )
            assert made.status_code == 200
            study_id = made.json()["id"]
            again = await client.post("/studio/api/studies", json={"topic": "Welding"})
            assert again.status_code == 400
            listed = (await client.get("/studio/api/studies")).json()["studies"]
            assert [s["topic"] for s in listed] == ["PCB design"]
            stopped = await client.post(f"/studio/api/studies/{study_id}/stop")
            assert stopped.json()["status"] == "cancelled"
            detail = (await client.get(f"/studio/api/studies/{study_id}")).json()
            assert detail["study"]["focus"] == "blueprints"
            assert detail["lessons"] == []
            gone = await client.delete(f"/studio/api/studies/{study_id}")
            assert gone.json() == {"deleted": True}
            missing = await client.get(f"/studio/api/studies/{study_id}")
            assert missing.status_code == 404
        finally:
            gate.set()
            await studio.shutdown()
            await app.state.services.admin.close()
