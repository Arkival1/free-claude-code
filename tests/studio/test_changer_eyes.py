"""The Changer's eyes and hands: it runs the tests it names, uses Studio
pages of the running copy like a person, and has the Vision Model look at
screenshots (or reads the page as text when there's no Vision Model)."""

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from free_claude_code.core.json_types import JsonValue
from free_claude_code.studio.changer import Changer, ChangerError
from free_claude_code.studio.llm import LLMReply, StudioLLMError, ToolCall
from free_claude_code.studio.models import Agent, StudioFlag
from free_claude_code.studio.page_try import PageReport, PageTryError
from free_claude_code.studio.presets import (
    _OLD_CHANGER_PROMPT_V2,
    CHANGER_PROMPT,
)
from free_claude_code.studio.tools import ToolContext
from tests.studio.test_changer import changer_for, make_app


class FakeTryer:
    """Stands in for page_try.try_url: records each visit."""

    def __init__(self, problems: tuple[str, ...] = (), broken: str = "") -> None:
        self.visits: list[dict[str, object]] = []
        self._problems = problems
        self._broken = broken

    async def __call__(self, url, steps, *, name, phone, shot) -> PageReport:
        self.visits.append({"url": url, "steps": steps, "phone": phone, "shot": shot})
        if self._broken and self._broken in url:
            raise PageTryError("Could not open the page: net::ERR_FAILED")
        if shot is not None:
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(b"png")
        return PageReport(
            page=name,
            size=(390, 800) if phone else (1280, 800),
            problems=list(self._problems),
            text="Changer page text",
            shot=shot,
            picture=b"jpeg" if shot is not None else b"",
        )


def serving_at(base: str):
    @contextlib.asynccontextmanager
    async def serving(target: Path) -> AsyncIterator[str]:
        yield base

    return serving


def eyes_for(tmp_path: Path, tryer: FakeTryer) -> tuple[Changer, Path]:
    changer, _, target = changer_for(tmp_path, tryer=tryer)
    changer.serving = serving_at("http://127.0.0.1:9")  # the copy isn't started
    return changer, target


@pytest.mark.asyncio
async def test_trying_pages_visits_each_page_at_each_size(tmp_path):
    tryer = FakeTryer()
    changer, target = eyes_for(tmp_path, tryer)
    reports = await changer.try_pages(
        target, ["changer", "#agents"], sizes=("pc", "phone"), pictures=True
    )
    assert [visit["url"] for visit in tryer.visits] == [
        "http://127.0.0.1:9/studio#changer",
        "http://127.0.0.1:9/studio#changer",
        "http://127.0.0.1:9/studio#agents",
        "http://127.0.0.1:9/studio#agents",
    ]
    assert [visit["phone"] for visit in tryer.visits] == [False, True, False, True]
    assert sorted(changer.shots()) == [
        "agents-pc.png",
        "agents-phone.png",
        "changer-pc.png",
        "changer-phone.png",
    ]
    assert all(report.picture for report in reports)


@pytest.mark.asyncio
async def test_trying_pages_checks_names_caps_them_and_reports_a_page_that_wont_open(
    tmp_path,
):
    tryer = FakeTryer(broken="lab")
    changer, target = eyes_for(tmp_path, tryer)
    with pytest.raises(ChangerError, match="isn't a Studio page name"):
        await changer.try_pages(target, ["../etc"])
    reports = await changer.try_pages(target, ["home", "lab", "trade", "learn"])
    assert len(reports) == 3, "at most three pages a time"
    assert reports[1].problems == ["Could not open the page: net::ERR_FAILED"]
    assert not any(visit["shot"] for visit in tryer.visits), "no pictures asked"


@pytest.mark.asyncio
async def test_trying_pages_needs_the_browser(tmp_path):
    changer, _, target = changer_for(tmp_path)
    with pytest.raises(ChangerError, match="Playwright"):
        await changer.try_pages(target, ["home"])


@pytest.mark.asyncio
async def test_the_changer_runs_the_tests_it_names(tmp_path):
    changer, _, target = changer_for(tmp_path)
    (target / "tests" / "test_bad.py").write_text(
        "def test_bad():\n    assert 1 == 2\n"
    )
    passed = await changer.run_tests(target, ["tests/test_x.py"])
    assert passed.passed and "Tests passed" in passed.text()
    failed = await changer.run_tests(target, ["tests/test_bad.py::test_bad"])
    assert not failed.passed and "assert 1 == 2" in failed.text()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "src/free_claude_code/studio/lab.py",
        "tests/../pyproject.toml",
        "tests/missing_test.py",
        "tests/test_nothing_here.py",
        "/etc/passwd",
    ],
)
async def test_only_test_files_in_the_copy_run(tmp_path, name):
    changer, _, target = changer_for(tmp_path)
    report = await changer.run_tests(target, [name])
    assert not report.passed and "not a test file" in report.text()


@pytest.mark.asyncio
async def test_tests_and_checks_in_the_copy_cant_reach_the_owners_home(
    tmp_path, monkeypatch
):
    owner = tmp_path / "owner-home"
    (owner / ".fcc").mkdir(parents=True)
    (owner / ".fcc" / "keys.json").write_text("secret")
    monkeypatch.setenv("HOME", str(owner))
    monkeypatch.setenv("USERPROFILE", str(owner))
    changer, _, target = changer_for(tmp_path)
    (target / "tests" / "test_peek.py").write_text(
        "import pathlib\n"
        "def test_peek():\n"
        "    assert not (pathlib.Path.home() / '.fcc' / 'keys.json').exists()\n"
    )
    ran = await changer.run_tests(target, ["tests\\test_peek.py::test_peek"])
    assert ran.passed, ran.text()
    checked = await changer.check(target)
    assert checked.passed, checked.text()
    assert "Tests passed" in checked.text()


@pytest.mark.asyncio
async def test_a_planted_ruff_in_the_copy_never_runs_with_the_owners_keys(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nvapi-secret")
    changer, _, target = changer_for(tmp_path)
    seen = tmp_path / "seen.txt"
    (target / "ruff.py").write_text(
        "import os, pathlib\n"
        f"pathlib.Path({str(seen)!r}).write_text("
        "os.environ.get('NVIDIA_NIM_API_KEY', '') + os.environ.get('HOME', ''))\n"
    )
    (target / "src/free_claude_code/studio/lab.py").write_text("X = 1\n")
    await changer.check(target)
    assert not seen.exists(), "the planted ruff.py ran"


@pytest.mark.asyncio
async def test_a_browser_crash_on_one_page_keeps_the_others(tmp_path):
    class Crashing(FakeTryer):
        async def __call__(self, url, steps, *, name, phone, shot) -> PageReport:
            if "lab" in url:
                raise RuntimeError("Target page, context or browser has been closed")
            return await super().__call__(url, steps, name=name, phone=phone, shot=shot)

    changer, target = eyes_for(tmp_path, Crashing())
    reports = await changer.try_pages(target, ["lab", "home"])
    assert "browser has been closed" in reports[0].problems[0]
    assert reports[1].passed


@pytest.mark.asyncio
async def test_content_farm_tests_are_left_out(tmp_path):
    changer, _, target = changer_for(tmp_path)
    (target / "tests" / "test_content_farm.py").write_text("def test_f():\n    pass\n")
    report = await changer.run_tests(target, ["tests/test_content_farm.py"])
    assert not report.passed and "left out" in report.text()


async def studio_with_copy(make_studio, tmp_path, respond, tryer, **settings):
    studio, model = make_studio(respond, **settings)
    studio._changer = Changer(
        tmp_path / "changer",
        source=make_app(tmp_path / "fcc"),
        import_check="print('ok')",
        tryer=tryer,
    )
    studio._changer.serving = serving_at("http://127.0.0.1:9")
    copy = await studio.changer_fresh_copy()
    context = ToolContext(agent_id="a", chat_id="c", site_id=copy.id)
    return studio, model, context


def act(action: str, **arguments: JsonValue) -> ToolCall:
    return ToolCall(
        id="1", name="fcc_changer", arguments={"action": action, **arguments}
    )


@pytest.mark.asyncio
async def test_try_uses_a_page_like_a_person_and_reports_problems(
    make_studio, tmp_path
):
    tryer = FakeTryer(problems=("Script error: x is not defined",))
    studio, _, context = await studio_with_copy(make_studio, tmp_path, [], tryer)
    steps = [{"do": "click", "target": "Start"}]
    outcome = await studio._changer_tool(
        act("try", page="changer", steps=steps), context
    )
    assert outcome.failed and "x is not defined" in outcome.text
    assert tryer.visits[0]["phone"] is True and len(tryer.visits) == 1
    steps_given = tryer.visits[0]["steps"]
    assert isinstance(steps_given, tuple) and steps_given[0].do == "click"
    pc = await studio._changer_tool(act("try", page="changer", phone=False), context)
    assert tryer.visits[-1]["phone"] is False and pc.failed
    bad = await studio._changer_tool(act("try", steps="click it"), context)
    assert bad.failed and "steps must be a list" in bad.text


@pytest.mark.asyncio
async def test_look_sends_the_pictures_to_the_vision_model(make_studio, tmp_path):
    def respond(system: str, prompt: str) -> object:
        return LLMReply(text="Picture 2: the buttons overlap on the phone.")

    tryer = FakeTryer()
    studio, model, context = await studio_with_copy(
        make_studio,
        tmp_path,
        respond,
        tryer,
        STUDIO_VISION_MODEL="nvidia_nim/vision-model",
    )
    outcome = await studio._changer_tool(
        act("look", page="changer", question="are the buttons tidy?"), context
    )
    assert not outcome.failed
    assert "buttons overlap" in outcome.text
    assert "What nvidia_nim/vision-model sees" in outcome.text
    asked = model.calls[-1]
    assert asked["model"] == "nvidia_nim/vision-model"
    message = asked["messages"][-1]
    assert len(message.images) == 2
    assert all(image.startswith("data:image/jpeg;base64,") for image in message.images)
    assert "are the buttons tidy?" in message.content
    assert outcome.data["shots"] == ["changer-pc.png", "changer-phone.png"]


@pytest.mark.asyncio
async def test_look_without_a_vision_model_reads_the_page_as_text(
    make_studio, tmp_path
):
    tryer = FakeTryer()
    studio, model, context = await studio_with_copy(make_studio, tmp_path, [], tryer)
    outcome = await studio._changer_tool(act("look", page="changer"), context)
    assert "No Vision Model answered" in outcome.text
    assert "Changer page text" in outcome.text
    assert model.calls == []


@pytest.mark.asyncio
async def test_a_vision_model_that_fails_falls_back_to_text(make_studio, tmp_path):
    def respond(system: str, prompt: str) -> object:
        raise StudioLLMError("this model doesn't take images")

    tryer = FakeTryer()
    studio, _, context = await studio_with_copy(
        make_studio, tmp_path, respond, tryer, STUDIO_VISION_MODEL="nvidia_nim/text"
    )
    outcome = await studio._changer_tool(act("look", page="home"), context)
    assert "No Vision Model answered" in outcome.text
    assert "Changer page text" in outcome.text


@pytest.mark.asyncio
async def test_the_tests_action_runs_named_tests_in_the_copy(make_studio, tmp_path):
    studio, _, context = await studio_with_copy(make_studio, tmp_path, [], None)
    outcome = await studio._changer_tool(
        act("tests", tests=["tests/test_x.py"]), context
    )
    assert not outcome.failed and "Tests passed" in outcome.text
    alone = await studio._changer_tool(act("tests", tests="tests/test_x.py"), context)
    assert not alone.failed


@pytest.mark.asyncio
async def test_the_changer_made_before_aider_gets_it_once(make_studio):
    studio, _ = make_studio([])
    old = await studio.create_agent(
        name="Changer",
        role="agent",
        model="nvidia_nim/test-model",
        system_prompt=_OLD_CHANGER_PROMPT_V2,
        tools=("read_file", "fcc_changer"),
    )
    agent = await studio._changer_agent()
    assert agent.id == old.id and "aider" in agent.tools
    assert agent.system_prompt == CHANGER_PROMPT
    assert await studio._store.get(StudioFlag, "changer_aider_v1") is not None
    # The owner takes it away again: it stays away.
    await studio._store.put(
        agent.model_copy(update={"tools": ("read_file", "fcc_changer")})
    )
    again = await studio._changer_agent()
    stored = await studio._store.require(Agent, again.id)
    assert "aider" not in stored.tools


@pytest.mark.asyncio
async def test_an_owners_own_changer_prompt_is_kept(make_studio):
    studio, _ = make_studio([])
    await studio.create_agent(
        name="Changer Reviewer",
        role="agent",
        model="nvidia_nim/test-model",
        system_prompt="My own reviewer rules.",
        tools=("read_file",),
    )
    member = await studio._changer_member("Changer Reviewer", "new", ("read_file",))
    assert member.system_prompt == "My own reviewer rules."
