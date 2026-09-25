"""The Builder polishes its pages, and the Tester checks the team's work."""

import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import Agent
from free_claude_code.studio.orders import pick_agent
from free_claude_code.studio.polish import contrast, polish_notes
from free_claude_code.studio.presets import PROMPT_UPGRADES, TESTER_PROMPT
from free_claude_code.studio.templates import TEMPLATES, template_files

from .conftest import tool_reply

PLAIN_PAGE = "<html><body><p>Hi</p><img src='a.png' alt='A'></body></html>"
PLAIN_CSS = "body { color: #777777; background: #888888; font-size: 12px; }\na { color: #123456; }"


def test_contrast_follows_the_wcag_formula():
    assert round(contrast("#ffffff", "#000000"), 1) == 21.0
    assert contrast("#777777", "#888888") < 1.5


def test_a_plain_page_gets_a_designers_notes():
    notes = "\n".join(polish_notes({"index.html": PLAIN_PAGE, "style.css": PLAIN_CSS}))

    for expected in (
        "contrast of 1.3:1",
        "Nothing adapts to screen size",
        ":focus-visible",
        ":hover state",
        "only 12px",
        "max-width",
        "line-height",
        "no <h1>",
        "header, nav, main, and footer",
        "width and height",
        "favicon",
    ):
        assert expected in notes, expected


def test_every_web_template_already_looks_finished():
    for name in ("website", "landing", "webapp", "game"):
        assert polish_notes(template_files(name, "Shop")) == [], name
    assert set(TEMPLATES) >= {"website", "game"}


def test_projects_without_pages_have_nothing_to_polish():
    assert polish_notes({"main.py": "print(1)"}) == []


@pytest.mark.asyncio
async def test_the_builder_runs_the_polish_check(make_studio):
    studio, _ = make_studio([tool_reply("polish_check", {}), "Polished."])
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None and "polish_check" in builder.tools
    assert "Then polish: run polish_check" in builder.system_prompt
    site = await studio.create_site(name="Plain")
    await studio.workspace.write(site.id, "index.html", PLAIN_PAGE)
    await studio.workspace.write(site.id, "styles.css", PLAIN_CSS)
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)

    await studio.send(chat.id, "make it look good")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    assert "polish suggestion(s):" in tool.text
    assert tool.data["notes"]


@pytest.mark.asyncio
async def test_the_tester_is_on_the_starter_team(make_studio):
    studio, _ = make_studio([])

    await studio.ensure_defaults()

    tester = await studio.agent_by_name("Tester")
    assert tester is not None and tester.role == "tester"
    assert {"check_project", "polish_check", "run_command", "test_code"} <= set(
        tester.tools
    )
    assert "write_file" not in tester.tools
    assert tester.system_prompt == TESTER_PROMPT


@pytest.mark.asyncio
async def test_a_tester_made_from_the_old_preset_is_upgraded(make_studio):
    studio, _ = make_studio([])
    old = next(old for old, new in PROMPT_UPGRADES.items() if new == TESTER_PROMPT)
    await studio.store.put(
        Agent.model_validate(
            {
                "name": "Tester",
                "role": "agent",
                "model": "m",
                "system_prompt": old,
                "tools": ["read_file"],
            }
        )
    )

    await studio.ensure_defaults()

    tester = await studio.agent_by_name("Tester")
    assert tester is not None
    assert tester.role == "tester" and tester.system_prompt == TESTER_PROMPT
    assert "polish_check" in tester.tools


def test_checking_jobs_go_to_the_tester():
    team = [
        ("Builder", "builder"),
        ("Researcher", "researcher"),
        ("Helper", "helper"),
        ("Tester", "tester"),
    ]
    assert pick_agent("check the snake game for bugs", team) == "Tester"
    assert pick_agent("review my site", team) == "Tester"
    assert pick_agent("build a timer", team) == "Builder"


@pytest.mark.asyncio
async def test_have_tester_check_a_project_by_name(make_studio):
    def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            return LLMReply(text="On it.")
        return tool_reply("finish", {"summary": "Verdict: works."})

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    site = await studio.create_site(name="Snake game")

    await studio.main_say(
        "get an agent to check the snake game for bugs", background=False
    )
    await studio.wait_for_background()

    run = (await studio.runs())[0]
    assert (await studio.agent(run.agent_id)).name == "Tester"
    assert run.site_id == site.id, "the project named in the task"
    assert run.result == "Verdict: works."


@pytest.mark.asyncio
async def test_spoken_pieces_are_reused(make_studio, monkeypatch):
    studio, _ = make_studio([])
    rendered: list[str] = []

    class Voice:
        def speech_ready(self) -> bool:
            return True

        async def speak(self, text: str) -> bytes:
            rendered.append(text)
            return b"RIFF"

    monkeypatch.setattr(studio, "voice_engines", lambda: ("builtin", "browser"))
    monkeypatch.setattr(studio, "local_voice", lambda: Voice())

    first = await studio.speak("Good evening.")
    again = await studio.speak("Good evening.")
    other = await studio.speak("All systems online.")

    assert first.audio == again.audio == other.audio == b"RIFF"
    assert rendered == ["Good evening.", "All systems online."]
