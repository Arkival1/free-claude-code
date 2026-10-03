"""Jarvis's playbook: notes that teach a small model when and how to use tools."""

import httpx
import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.playbook import (
    LEARNED_KEEP,
    STARTERS,
    Playbook,
    guide_text,
    score,
)
from tests.api.support import create_test_app

from .conftest import tool_reply


def jarvis_script(*steps):
    replies = iter(steps)

    def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            return next(replies)
        return LLMReply(text="ok")

    return respond


@pytest.mark.asyncio
async def test_starting_notes_are_written_once_and_edits_are_kept(tmp_path):
    book = Playbook(tmp_path / "Playbook")
    notes = await book.notes()

    assert {note.tool for note in notes} == {"rules"} | {s.tool for s in STARTERS}
    todo = tmp_path / "Playbook" / "todo.md"
    todo.write_text(todo.read_text().replace("remind me,", "nag me,"))
    (tmp_path / "Playbook" / "weather.md").unlink()

    again = {note.tool: note for note in await book.notes()}
    assert "nag me" in again["todo"].when, "the user's edit stays"
    assert "weather" not in again, "a note the user deleted stays deleted"


@pytest.mark.parametrize(
    ("said", "tool"),
    [
        ("remind me to take the bins out tomorrow 8am", "todo"),
        ("what's 17% of 2400", "calculate"),
        ("what is 12*7", "calculate"),
        ("how is my pc doing", "system_status"),
        ("is the researcher done yet", "team_status"),
        ("give the builder every tool", "manage_agent"),
        ("which model is the builder using", "agent_model"),
        ("what's the weather in london", "weather"),
        ("make soap in the lab", "lab"),
    ],
)
@pytest.mark.asyncio
async def test_the_matching_note_comes_first(tmp_path, said, tool):
    notes = await Playbook(tmp_path / "Playbook").notes()
    best = max(
        (note for note in notes if note.tool != "rules"), key=lambda n: score(n, said)
    )
    assert best.tool == tool
    guide = guide_text(notes, said)
    assert f"({tool})" in guide and "# Rules" in guide


@pytest.mark.asyncio
async def test_small_talk_gets_only_the_rules(tmp_path):
    notes = await Playbook(tmp_path / "Playbook").notes()
    guide = guide_text(notes, "hello jarvis how are you")
    assert "# Rules" in guide and "## Examples" not in guide
    assert "Examples" not in guide_text(notes, "remind me at 5", rules_only=True)


@pytest.mark.asyncio
async def test_the_rules_are_never_cut_mid_sentence(tmp_path):
    notes = await Playbook(tmp_path / "Playbook").notes()
    guide = guide_text(notes, "what's 15% of 80 and remind me later")
    assert "If a tool failed, say what failed." in guide
    assert len(guide) <= 3_000


@pytest.mark.asyncio
async def test_a_call_that_worked_is_learned_and_matches_next_time(tmp_path):
    book = Playbook(tmp_path / "Playbook")
    await book.notes()
    note = tmp_path / "Playbook" / "todo.md"
    note.write_text(note.read_text().replace("## Tips", "## Tips\n- My own tip."))

    assert await book.learn(
        "todo",
        "Put water the plants on for 6pm",
        {"action": "add", "text": "Water the plants", "due": "at 18:00"},
    )
    assert not await book.learn(
        "todo",
        "Put water the plants on for 6pm",
        {"action": "add", "text": "Water the plants", "due": "at 18:00"},
    ), "the same example twice is kept once"
    assert not await book.learn("finish", "done", {"summary": "x"})

    todo = await book.read("todo")
    assert "- My own tip." in todo.text, "everything above Learned stays"
    assert todo.learned[-1][0] == "Put water the plants on for 6pm"
    assert score(todo, "put water the plants on") >= 3
    guide = guide_text(await book.notes(), "put water the plants on for 8pm")
    assert "Worked before:" in guide

    for number in range(LEARNED_KEEP + 3):
        await book.learn("todo", f"reminder number {number}", {"action": "list"})
    assert len((await book.read("todo")).learned) == LEARNED_KEEP


@pytest.mark.asyncio
async def test_long_arguments_are_shortened_in_examples(tmp_path):
    book = Playbook(tmp_path / "Playbook")
    await book.learn(
        "ask_agent",
        "build my bakery site",
        {"agent": "Builder", "task": "x" * 2_000},
    )
    _, call = (await book.read("ask_agent")).learned[-1]
    assert len(call) < 300 and call.endswith('…"}}')


@pytest.mark.asyncio
async def test_a_new_vault_starts_with_what_was_learned(tmp_path):
    home = Playbook(tmp_path / "playbook")
    await home.learn(
        "todo", "remind me to stretch", {"action": "add", "text": "Stretch"}
    )

    vault = Playbook(tmp_path / "vault" / "Playbook", seed_from=tmp_path / "playbook")
    todo = await vault.read("todo")
    assert todo.learned[-1][0] == "remind me to stretch"


@pytest.mark.asyncio
async def test_saving_and_resetting_a_note(tmp_path):
    book = Playbook(tmp_path / "Playbook")
    saved = await book.save("weather", "# Weather\n\nWhen the user says: brolly\n")
    assert saved.tool == "weather" and saved.when == ("brolly",)
    assert saved.text.startswith("---\n"), "Studio's header is put back"
    reset = await book.reset("weather")
    assert "forecast" in reset.when


@pytest.mark.asyncio
async def test_jarvis_gets_the_matching_note_and_learns_what_worked(
    make_studio, tmp_path
):
    studio, model = make_studio(
        jarvis_script(
            tool_reply(
                "todo", {"action": "add", "text": "Feed the cat", "due": "at 19:00"}
            ),
            LLMReply(text="Added."),
        )
    )
    await studio.ensure_defaults()

    await studio.main_say("remind me to feed the cat at 7pm", background=False)

    note = model.calls[0]["studio_note"]
    assert "Your playbook" in note
    assert '"tool": "todo"' in note, "the to-do example rides on the message"
    learned = (tmp_path / "playbook" / "todo.md").read_text()
    assert "User: remind me to feed the cat at 7pm" in learned


@pytest.mark.asyncio
async def test_no_tool_examples_when_studio_already_did_the_job(make_studio):
    studio, model = make_studio(jarvis_script(LLMReply(text="On it.")))
    await studio.ensure_defaults()

    await studio.main_say("make soap in the lab", background=False)

    note = model.calls[0]["studio_note"]
    assert "Studio already did this in the Lab" in note
    assert "# Rules" in note and '"tool": "lab"' not in note


@pytest.mark.asyncio
async def test_the_playbook_can_be_turned_off(make_studio, tmp_path):
    studio, model = make_studio(
        jarvis_script(
            tool_reply("todo", {"action": "list"}),
            LLMReply(text="Here."),
        ),
        STUDIO_JARVIS_PLAYBOOK=False,
    )
    await studio.ensure_defaults()

    await studio.main_say("what's on my list", background=False)

    assert "Your playbook" not in model.calls[0]["studio_note"]
    assert not (tmp_path / "playbook").exists()


@pytest.mark.asyncio
async def test_the_playbook_through_the_routes(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            book = (await client.get("/studio/api/playbook")).json()
            assert book["enabled"] is True and book["in_vault"] is False
            tools = {note["tool"] for note in book["notes"]}
            assert {"rules", "todo", "ask_agent"} <= tools

            saved = await client.put(
                "/studio/api/playbook/todo",
                json={"text": "# To-do\n\nWhen the user says: jot down\n"},
            )
            assert saved.status_code == 200 and saved.json()["when"] == ["jot down"]
            empty = await client.put("/studio/api/playbook/todo", json={"text": " "})
            assert empty.status_code == 400
            missing = await client.put(
                "/studio/api/playbook/nothing", json={"text": "x"}
            )
            assert missing.status_code == 400

            reset = await client.post("/studio/api/playbook/todo/reset")
            assert "remind me" in reset.json()["when"]
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
