"""FCC Phone's Playground makes games and websites: one main AI builds it
with its own hands, helpers build parts beside it, advisers advise (with the
tools to use) and check it, and it fixes what they find. It keeps their
advice in its advice book and the fixes as lessons, and the finished game
waits in the library for approval. Settings switches between the HUD and the
Playground; plugins have a master switch."""

import json
import re

from playwright.sync_api import Page, expect

from .test_fcc_phone import fake_gemini, go, open_phone, say, tool_call, use_gemini

MAKING = {"start_project", "write_file", "edit_file", "delete_file", "use_photo"}


def playground_brain(body: dict) -> dict:
    """A scripted Gemini playing the main AI, a helper, the advisers and
    their notes."""
    system = body["messages"][0]["content"]
    messages = body["messages"]
    asked = str(messages[1].get("content")) if len(messages) > 1 else ""
    tools_used = [m for m in messages if m["role"] == "tool"]
    who = system.split("You are ", 1)[-1][:20]
    if "Write down what to keep in your own mind" in system:
        return say(
            json.dumps(
                {
                    "thought": "Snake could use levels.",
                    "pattern": "Start from the game template, then make it mine.",
                    "lesson": "Show the score from the first build.",
                }
            )
        )
    if "You are a helper in the user's Playground" in system:
        if not tools_used:
            return tool_call(
                "write_file",
                {"path": "parts/art.js", "content": "export const SNAKE = '#3f3';"},
            )
        return say("Made parts/art.js: the snake's colours.")
    if "You are an adviser in the user's Playground" in system:
        if "Advise the main AI before it starts" in asked:
            return say("Use start_project with the game template, then look_at_site.")
        first_check = "Added a score" not in asked
        if "Tester" in who and first_check:
            return say("1. Add a score display (edit_file on game.js).")
        return say("LOOKS GOOD")
    if "You are the main AI in the user's Playground" in system:
        if asked.startswith("Fix what your advisers found"):
            return say("Added a score.")
        if not tools_used:
            name = re.search(r"Work in the project (.+?): start_project", asked)
            assert name, asked
            return tool_call(
                "start_project", {"name": name.group(1), "template": "game"}
            )
        if len(tools_used) == 1:
            return tool_call(
                "remember", {"text": "The user likes neon green.", "kind": "taste"}
            )
        return say("Built Snake: index.html, styles.css and game.js.")
    return say("Hi!")


def test_the_main_ai_builds_a_game_with_helpers_and_advisers(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    seen = fake_gemini(page, playground_brain)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "settings")
    page.get_by_role("button", name="Playground").click()
    go(page, "home")
    expect(
        page.get_by_role("heading", name="What do you want to make?")
    ).to_be_visible()
    expect(page.get_by_role("button", name="Make a game")).to_have_attribute(
        "aria-pressed", "true"
    )
    page.get_by_label("The task").fill("a snake game with swipe controls")
    expect(page.get_by_text("Helping (they build parts): Builder")).to_be_visible()
    expect(page.get_by_text("Advising: Tester, Researcher")).to_be_visible()
    page.get_by_role("button", name="Start task ↗").click()
    page.wait_for_function(
        "() => window.fccPhone.state.tasks[0] && window.fccPhone.state.tasks[0].status === 'done'",
        timeout=30000,
    )
    task = page.evaluate("() => window.fccPhone.state.tasks[0]")
    assert task["type"] == "game"
    stages = [(s["stage"], s["pass"], s["agent"]) for s in task["steps"]]
    assert stages == [
        ("kickoff", 0, "Tester"),
        ("kickoff", 0, "Researcher"),
        ("work", 1, "Jarvis"),
        ("help", 1, "Builder"),
        ("review", 1, "Tester"),
        ("review", 1, "Researcher"),
        ("work", 2, "Jarvis"),
        ("review", 2, "Tester"),
        ("review", 2, "Researcher"),
    ], stages
    assert all(s["status"] == "done" for s in task["steps"])
    project = page.evaluate(
        f"() => window.fccPhone.state.projects.find((p) => p.id === {json.dumps(task['project_id'])})"
    )
    # The helper's part sits beside the game; the template still went in.
    assert project["name"] == "Snake game with swipe"
    assert {"game.js", "index.html", "parts/art.js"} <= set(project["files"])
    # Each AI got only its own tools: advisers none that change things,
    # helpers no new project or hand-offs, the main AI everything.
    for call in seen:
        system = call["messages"][0]["content"]
        names = {tool["function"]["name"] for tool in call.get("tools") or []}
        if "You are an adviser in the user's Playground" in system:
            assert not names & MAKING, names
        if "You are a helper in the user's Playground" in system and names:
            assert "write_file" in names
            assert not names & {"start_project", "delete_file", "ask_agent"}
        if "You are the main AI in the user's Playground" in system and names:
            assert {"write_file", "start_project", "library", "ask_agent"} <= names
    # The advisers' tool tips and the fix reached the main AI.
    briefs = [
        str(call["messages"][1]["content"])
        for call in seen
        if "You are the main AI in the user's Playground"
        in call["messages"][0]["content"]
    ]
    assert any("Use start_project with the game template" in b for b in briefs)
    assert any(
        b.startswith("Fix what your advisers found") and "Add a score" in b
        for b in briefs
    )
    # It learns: the advice book, a lesson from the fix, and its own mind.
    memories = page.evaluate("() => window.fccPhone.state.memories")
    mine = [m for m in memories if m["agent_id"] == "jarvis"]
    advice = [m["text"] for m in mine if m["kind"] == "advice"]
    assert any(t.startswith("Tester advised (game):") for t in advice), advice
    assert any(m["kind"] == "lesson" and "Tester found" in m["text"] for m in mine)
    assert all(len(m["text"]) <= 220 for m in mine if m["kind"] != "fact")
    assert {("pattern", True), ("advice", True)} <= {
        (m["kind"], m["own"]) for m in mine
    }
    taste = [m for m in memories if m["kind"] == "taste"]
    assert taste and taste[0]["own"] is False
    # The finished game waits in the library for approval.
    library = page.evaluate("() => window.fccPhone.state.library")
    assert [(i["kind"], i["approved"], i["title"]) for i in library] == [
        ("game", False, "Snake game with swipe")
    ]
    assert "game.js" in library[0]["files"]
    assert "parts/art.js" not in library[0]["files"]
    expect(page.get_by_role("heading", name="Done", exact=True)).to_be_visible()
    expect(
        page.get_by_text("A game: Jarvis builds it · helping: Builder", exact=False)
    ).to_be_visible()
    # The prompt picks the advice that fits a new game, not the whole memory.
    prompt = page.evaluate(
        """async () => {
            const { systemPrompt } = await import('./js/agents.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.id === 'jarvis');
            return systemPrompt(jarvis, 'make a snake game with levels');
        }"""
    )
    assert "Your own notes that fit this job" in prompt and "Tester advised" in prompt
    go(page, "minds")
    jarvis_card = page.locator("section.card", has_text="Jarvis's mind")
    expect(jarvis_card.get_by_role("heading", name="Advice book")).to_be_visible()
    page.get_by_label("Search the minds").fill("score")
    expect(jarvis_card.get_by_text("Tester found", exact=False)).to_be_visible()
    expect(jarvis_card.get_by_text("Start from the game template")).to_have_count(0)
    with page.expect_download() as download:
        jarvis_card.get_by_role("button", name="Save Jarvis's mind as a file").click()
    assert download.value.suggested_filename == "jarvis-mind.md"
    assert errors == []


def test_the_library_keeps_what_you_approve_and_the_ai_reads_only_that(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_phone(page, admin_base_url)
    found = page.evaluate(
        """async () => {
            const lib = await import('./js/library.js');
            const ok = await lib.addToLibrary({kind: 'website', title: 'Calm yoga site', notes: 'Soft greens, lots of space'});
            const wait = await lib.addToLibrary({kind: 'game', title: 'Neon snake', by: 'Jarvis', approved: false});
            return {
                search: lib.useLibrary({action: 'search', query: 'yoga'}),
                none: lib.useLibrary({action: 'search', query: 'neon snake'}),
                read: lib.useLibrary({action: 'read', id: ok.id}),
                pending: lib.useLibrary({action: 'read', id: wait.id}),
            };
        }"""
    )
    assert "Calm yoga site" in found["search"]
    assert "Neon snake" not in found["none"]
    assert "Soft greens" in found["read"]
    assert "waiting for the user's approval" in found["pending"]
    go(page, "library")
    expect(page.get_by_text("Waiting for your approval (1)")).to_be_visible()
    page.get_by_role("button", name="Approve Neon snake").click()
    expect(page.get_by_text("Approved references (2)")).to_be_visible()
    page.get_by_label("Search the library").fill("yoga")
    expect(page.get_by_text("Approved references (1)")).to_be_visible()
    page.get_by_role("button", name="Games").click()
    expect(page.get_by_text("Approved references (0)")).to_be_visible()
    assert errors == []


def test_the_plugin_apis_switch_stops_every_plugin(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url, "plugins")
    switch = page.get_by_label("Plugin APIs on")
    expect(switch).to_be_checked()
    switch.uncheck()
    stopped = page.evaluate(
        """async () => {
            const { usePlugin } = await import('./js/plugins.js');
            try { return await usePlugin({action: 'find', need: 'weather'}); }
            catch (error) { return 'ERROR ' + error.message; }
        }"""
    )
    assert stopped.startswith("ERROR") and "switched off" in stopped
    switch.check()
    back = page.evaluate(
        "async () => (await import('./js/plugins.js')).usePlugin({action: 'find', need: 'weather'})"
    )
    assert "Plugins that fit" in back


def test_a_stopped_playground_task_runs_again_from_where_it_stopped(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    fake_gemini(page, playground_brain)
    open_phone(page, admin_base_url)
    use_gemini(page)
    stopped = page.evaluate(
        """async () => {
            const { startPlayground } = await import('./js/playground.js');
            const { stopTask } = await import('./js/tasks.js');
            const task = await startPlayground('a snake game with swipe controls');
            stopTask(task.id);
            return task.id;
        }"""
    )
    page.wait_for_function(
        f"() => window.fccPhone.state.tasks.find((t) => t.id === {json.dumps(stopped)}).status === 'stopped'",
        timeout=15000,
    )
    task = page.evaluate("() => window.fccPhone.state.tasks[0]")
    assert all(step["status"] not in {"done", "running"} for step in task["steps"])
    page.evaluate(
        f"async () => (await import('./js/tasks.js')).resumeTask({json.dumps(stopped)})"
    )
    page.wait_for_function(
        f"() => window.fccPhone.state.tasks.find((t) => t.id === {json.dumps(stopped)}).status === 'done'",
        timeout=30000,
    )
    assert errors == []


def test_settings_switches_between_the_hud_and_the_playground(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    tabs = page.locator("#tabs .tab")
    expect(tabs).to_have_text(["◆Home", "◌Chats", "◎Agents", "⚡Models", "⋯More"])
    go(page, "settings")
    page.get_by_role("button", name="Playground").click()
    expect(tabs).to_have_text(["+New task", "◷Tasks", "▤Files", "⋯More"])
    assert page.evaluate("() => window.fccPhone.state.settings.look") == "playground"
    page.reload()
    page.wait_for_function("() => window.fccPhone && window.fccPhone.ready")
    page.evaluate("() => window.fccPhone.ready")
    expect(tabs).to_have_text(["+New task", "◷Tasks", "▤Files", "⋯More"])
    page.locator("#tabs .tab", has_text="Files").click()
    expect(page.get_by_text("Your work, all in one place")).to_be_visible()
    go(page, "settings")
    page.get_by_role("button", name="HUD").click()
    expect(tabs).to_have_text(["◆Home", "◌Chats", "◎Agents", "⚡Models", "⋯More"])
