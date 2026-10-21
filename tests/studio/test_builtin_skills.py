"""FCC's own skills: the website design engineer and the app developer
engineer come with the app, reach the right agents on every task, and the
checks hold the work to them."""

import pytest

from free_claude_code.studio.extensions import BUILTIN_ID, ExtensionError
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import AgentRun
from free_claude_code.studio.polish import polish_notes


@pytest.mark.asyncio
async def test_the_skills_install_refresh_and_keep_the_owners_switch(make_studio):
    studio, _ = make_studio([])
    library = studio._extensions
    built = await library.install_builtin()
    assert built is not None and built.origin == "builtin" and built.enabled
    names = {skill.name for skill in built.skills}
    assert names == {"web-design-engineer", "app-developer-engineer"}
    built.enabled = False
    await library.save(built)
    again = await library.install_builtin()
    assert again is not None and again.enabled is False
    text = await library.skill_text(again, again.skills[0])
    assert "Before finishing" in text
    with pytest.raises(ExtensionError, match="turn them off"):
        await library.remove(BUILTIN_ID)


async def task_prompt(make_studio, role: str, goal: str, *, off: bool = False) -> str:
    def respond(system: str, prompt: str) -> object:
        return LLMReply(text="Done.")

    studio, model = make_studio(respond)
    if off:
        built = await studio._builtin_skills()
        assert built is not None
        built.enabled = False
        await studio._extensions.save(built)
    agent = await studio.create_agent(
        name=f"The {role}", role=role, model="nvidia_nim/test-model", tools=()
    )
    run = await studio.start_task(agent_id=agent.id, goal=goal)
    job = studio._run_jobs.get(run.id)
    if job is not None:
        await job
    finished = await studio._store.require(AgentRun, run.id)
    assert finished.status == "succeeded"
    return "\n".join(str(call["studio_note"]) for call in model.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "goal", "web", "app"),
    [
        ("builder", "Make a bakery website", True, False),
        ("builder", "Build a budget tracker app", True, True),
        ("coder", "Fix the login function", False, True),
        ("developer", "Add a settings page with a form", True, True),
        ("tester", "Test the shopping cart", False, True),
        ("assistant", "Make a bakery website", False, False),
    ],
)
async def test_each_agent_gets_its_skills_on_every_task(
    make_studio, role, goal, web, app
):
    prompt = await task_prompt(make_studio, role, goal)
    assert ("# Website design engineer" in prompt) is web
    assert ("# App developer engineer" in prompt) is app


@pytest.mark.asyncio
async def test_turned_off_skills_reach_no_one(make_studio):
    prompt = await task_prompt(make_studio, "builder", "Make a site", off=True)
    assert "# Website design engineer" not in prompt


PAGE = """<!doctype html><html><head><title>x</title>
<meta name="viewport" content="width=device-width"></head><body>
<header><h1>One</h1></header><main><h1>Two</h1><h4>Jump</h4>
<a href="https://x.example" target="_blank">site</a>
<a href="/prices">click here</a></main></body></html>"""
CSS = ":root { --a: #fff; } body { font-family: Inter; line-height: 1.6; } a { transition: color .2s; }"


@pytest.mark.parametrize(
    "wanted",
    [
        "has 2 <h1> headlines",
        "jumps from h1 to h4",
        "add lang to <html>",
        'without rel="noopener"',
        "just says 'click here'",
        "prefers-reduced-motion",
    ],
)
def test_the_checks_hold_pages_to_the_design_skill(wanted):
    notes = polish_notes({"index.html": PAGE, "styles.css": CSS})
    assert any(wanted in note for note in notes), notes


def test_a_page_that_follows_the_skill_gets_none_of_those_notes():
    good = (
        PAGE.replace("<html>", '<html lang="en">')
        .replace("<h1>Two</h1><h4>Jump</h4>", "<h2>Two</h2><h3>Jump</h3>")
        .replace('target="_blank">', 'target="_blank" rel="noopener">')
        .replace("click here", "See our prices")
    )
    css = CSS + " @media (prefers-reduced-motion: reduce) { * { transition: none; } }"
    notes = polish_notes({"index.html": good, "styles.css": css})
    for wanted in (
        "<h1> headlines",
        "jumps from",
        "add lang",
        "noopener",
        "click here",
        "reduced-motion",
    ):
        assert not any(wanted in note for note in notes), notes


@pytest.mark.asyncio
async def test_a_file_that_cant_be_removed_doesnt_stop_the_refresh(
    make_studio, monkeypatch
):
    import shutil

    studio, _ = make_studio([])
    library = studio._extensions
    await library.install_builtin()
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)  # a Windows lock
    again = await library.install_builtin()
    assert again is not None and len(again.skills) == 2


@pytest.mark.asyncio
async def test_two_installs_at_once_both_see_the_skills(make_studio):
    import asyncio

    studio, _ = make_studio([])
    first, second = await asyncio.gather(
        studio._builtin_skills(), studio._builtin_skills()
    )
    assert first is not None and second is not None
    assert len(first.skills) == len(second.skills) == 2
    agent = await studio.create_agent(name="B", role="builder", model="m/x", tools=())
    brief = await studio._skill_brief(agent, "Build a budget app")
    assert "# Website design engineer" in brief and "# App developer engineer" in brief
    assert len(brief) < 8_000  # about 2,000 tokens a task, both skills included


def test_hidden_markup_raises_no_false_notes():
    page = (
        '<!doctype html><html lang="en"><body><main><h1>One</h1>'
        "<!-- <h1>Old</h1> <h4>x</h4> -->"
        "<template><h1>T</h1><h5>t</h5></template>"
        "<script>const s = '<h1>s</h1>';</script></main></body></html>"
    )
    notes = polish_notes({"index.html": page, "styles.css": "body { color: #000; }"})
    for wanted in ("<h1> headlines", "jumps from", "add lang"):
        assert not any(wanted in note for note in notes), notes


@pytest.mark.asyncio
async def test_a_failed_install_is_tried_again_on_next_use(make_studio, monkeypatch):
    import shutil

    studio, _ = make_studio([])
    real = shutil.copytree
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("locked")
        return real(*args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", flaky)
    assert await studio._builtin_skills() is None or not studio._builtin_checked
    again = await studio._builtin_skills()
    assert again is not None and len(again.skills) == 2 and studio._builtin_checked
