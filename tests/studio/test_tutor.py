"""The maths tutor: questions solved in code, marking, progress, tests, help."""

import math

import httpx
import pytest

from free_claude_code.core.version import package_version
from free_claude_code.studio.models import TutorAttempt
from free_claude_code.studio.tutor.coach import (
    TEST_SIZE,
    Tutor,
    TutorError,
    parse_answer,
    rebuild,
)
from free_claude_code.studio.tutor.pathway import pathway
from free_claude_code.studio.tutor.topics import STAGES, TOPICS, make_question
from tests.api.support import create_test_app


def test_every_topic_makes_questions_it_can_mark():
    stages = {stage for stage, _ in STAGES}
    for topic in TOPICS:
        assert topic.stage in stages and topic.lesson and topic.formulas
        for seed in range(200):
            question = make_question(topic.id, seed)
            assert math.isfinite(question.answer) and question.answer != 0
            assert question.steps and question.prompt and question.hint
            assert question.accepts(question.answer)
            assert question.accepts(round(question.answer, question.places))
            assert not question.accepts(question.answer * 1.2), (topic.id, seed)


def test_a_question_id_always_makes_the_same_question():
    for topic in TOPICS:
        first = make_question(topic.id, 4242)
        assert rebuild(first.id) == first
    assert make_question("ohms", 1) != make_question("ohms", 2)


def test_answers_match_the_formulas_worked_by_hand():
    # Pinned seeds, checked against the formula independently.
    assert make_question("ohms", 7).answer == pytest.approx(230 / 22)
    assert make_question("three_power", 7).answer == pytest.approx(
        math.sqrt(3) * 400 * 32 * 0.9 / 1000
    )
    assert make_question("vdrop", 7).answer == pytest.approx(3.86 * 10 * 55 / 1000)
    assert make_question("fault_loop", 7).answer == pytest.approx(230 / (16 * 7.5))
    assert make_question("correction", 7).answer == pytest.approx(
        10 * (math.tan(math.acos(0.7)) - math.tan(math.acos(0.95)))
    )
    assert make_question("star", 7).answer == pytest.approx(415 / math.sqrt(3))
    assert make_question("motor", 7).answer == pytest.approx(3)


def test_typed_answers_are_read_as_numbers():
    cases = {
        "12.5": 12.5,
        "1,200": 1200,
        "$32.20": 32.2,
        "3/4": 0.75,
        "85%": 85,
        "1.2e3": 1200,
        "4.7\u00d710^3": 4700,
        "I = 10.5 A": 10.5,
        "\u22125": -5,
        " 0.0896 A ": 0.0896,
    }
    for text, value in cases.items():
        assert parse_answer(text) == pytest.approx(value), text
    for text in ("abc", "", "1/0", "about"):
        assert parse_answer(text) is None, text


def test_question_ids_the_tutor_did_not_make_are_refused():
    for bad in ("nope:1", "ohms:x", "ohms:-1", "ohms", "ohms:99999999999"):
        with pytest.raises(TutorError):
            rebuild(bad)


@pytest.mark.asyncio
async def test_answers_are_marked_kept_and_build_mastery(store):
    tutor = Tutor(store)
    question = tutor.question("ohms")
    assert "answer" not in question and "steps" not in question
    real = rebuild(str(question["id"]))
    unclear = await tutor.check(str(question["id"]), "no idea")
    assert unclear["understood"] is False
    assert await store.count(TutorAttempt) == 0
    wrong = await tutor.check(str(question["id"]), str(real.answer * 2))
    assert wrong["correct"] is False and wrong["answer"] == real.shown()
    assert wrong["steps"] == list(real.steps)
    for _ in range(5):
        fresh = rebuild(str(tutor.question("ohms")["id"]))
        right = await tutor.check(fresh.id, f"{fresh.answer:.{fresh.places}f}")
        assert right["correct"] is True
    progress = await tutor.progress()
    rows = progress["topics"]
    assert isinstance(rows, list)
    ohms = next(row for row in rows if isinstance(row, dict) and row["id"] == "ohms")
    assert ohms == {"id": "ohms", "answered": 6, "mastery": 83, "strong": True}
    # The first topic not yet strong is suggested next.
    assert progress["suggested"] == TOPICS[0].id
    assert progress["answered"] == 6 and progress["right"] == 5


@pytest.mark.asyncio
async def test_a_practice_test_is_marked_once(store):
    tutor = Tutor(store)
    test = tutor.test("dc")
    questions = test["questions"]
    assert isinstance(questions, list) and len(questions) == TEST_SIZE
    dc = {topic.id for topic in TOPICS if topic.stage == "dc"}
    answers: dict[str, str] = {}
    for index, row in enumerate(questions):
        assert isinstance(row, dict) and row["topic"] in dc and "hint" not in row
        question = rebuild(str(row["id"]))
        answers[question.id] = str(question.answer) if index < 7 else ""
    marked = await tutor.mark(str(test["test_id"]), answers)
    assert (marked["score"], marked["total"], marked["percent"]) == (7, 10, 70)
    assert "Practise these topics" in str(marked["advice"])
    assert await store.count(TutorAttempt, where={"test_id": test["test_id"]}) == 10
    with pytest.raises(TutorError, match="already been marked"):
        await tutor.mark(str(test["test_id"]), answers)
    with pytest.raises(TutorError):
        await tutor.mark("dc:not-a-token", answers)
    with pytest.raises(TutorError):
        tutor.test("cooking")
    progress = await tutor.progress()
    tests = progress["tests"]
    assert isinstance(tests, list) and len(tests) == 1
    row = tests[0]
    assert isinstance(row, dict)
    assert (row["stage"], row["score"], row["total"]) == ("dc", 7, 10)


@pytest.mark.asyncio
async def test_the_ai_explains_but_never_sets_the_answer(store):
    asked: list[tuple[str, str]] = []

    async def think(system: str, prompt: str) -> str:
        asked.append((system, prompt))
        return "You divided the wrong way round. Volts over ohms gives amps."

    question = make_question("ohms", 3)
    reply = await Tutor(store, think=think).explain(question.id, "0.1")
    assert reply["answer"] == question.shown()
    assert reply["steps"] == list(question.steps)
    assert str(reply["explanation"]).startswith("You divided")
    system, prompt = asked[0]
    assert "never change them" in system
    assert question.shown() in prompt and "The student answered: 0.1" in prompt

    async def broken(system: str, prompt: str) -> str:
        raise RuntimeError("offline")

    fallback = await Tutor(store, think=broken).explain(question.id)
    assert fallback["explanation"] == "" and "couldn't be reached" in str(
        fallback["note"]
    )
    alone = await Tutor(store).explain(question.id)
    assert alone["answer"] == question.shown() and alone["explanation"] == ""
    with pytest.raises(TutorError):
        await Tutor(store).ask("What is 2 + 2?")


def test_the_licence_path_points_to_official_sources():
    path = pathway()
    steps = path["steps"]
    assert isinstance(steps, list) and len(steps) == 5
    sources = path["sources"]
    assert isinstance(sources, list)
    urls = [str(source["url"]) for source in sources if isinstance(source, dict)]
    assert any(url.startswith("https://www.nsw.gov.au/") for url in urls)
    assert any(url.startswith("https://www.tafensw.edu.au/") for url in urls)
    assert "UEE30820" in str(steps)


@pytest.mark.asyncio
async def test_the_tutor_through_the_app(make_studio):
    studio, _ = make_studio(["Amps are volts divided by ohms."] * 3)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        overview = (await client.get("/studio/api/tutor")).json()
        assert len(overview["topics"]) == len(TOPICS)
        assert overview["progress"]["suggested"] == TOPICS[0].id
        question = (await client.get("/studio/api/tutor/question?topic=ohms")).json()
        real = rebuild(question["id"])
        checked = await client.post(
            "/studio/api/tutor/check",
            json={"question_id": question["id"], "answer": str(real.answer)},
        )
        assert checked.status_code == 200 and checked.json()["correct"] is True
        bad = await client.get("/studio/api/tutor/question?topic=cooking")
        assert bad.status_code == 400
        test = (await client.get("/studio/api/tutor/test?stage=all")).json()
        marked = await client.post(
            "/studio/api/tutor/test",
            json={
                "test_id": test["test_id"],
                "answers": {row["id"]: "1" for row in test["questions"]},
            },
        )
        assert marked.status_code == 200 and marked.json()["total"] == TEST_SIZE
        explained = (
            await client.post(
                "/studio/api/tutor/explain",
                json={"question_id": question["id"], "answer": "3"},
            )
        ).json()
        assert explained["answer"] == real.shown() and explained["explanation"]
        asked = await client.post(
            "/studio/api/tutor/ask", json={"question": "How do I find current?"}
        )
        assert asked.status_code == 200 and asked.json()["answer"]
        script = await client.get(f"/studio/assets/{package_version()}/tutor.js")
        assert script.status_code == 200 and "FCCTutor" in script.text
