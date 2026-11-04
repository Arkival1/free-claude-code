"""FCC Phone's Playground: one main AI does the work with its own hands, up to
two advisers advise before it starts and check it after (it fixes what they
find), each AI keeps its own thoughts, patterns and lessons, and the user's
taste is shared. Settings switches between the HUD and the Playground."""

import json

from playwright.sync_api import Page, expect

from .test_fcc_phone import fake_gemini, go, open_phone, say, tool_call, use_gemini

MAKING = {"start_project", "write_file", "edit_file", "delete_file", "use_photo"}


def playground_brain(body: dict) -> dict:
    """A scripted Gemini playing the main AI, the advisers and their notes."""
    system = body["messages"][0]["content"]
    messages = body["messages"]
    asked = str(messages[1].get("content")) if len(messages) > 1 else ""
    tools_used = [m for m in messages if m["role"] == "tool"]
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
    if "You are an adviser in the user's Playground" in system:
        if "Advise the main AI before it starts" in asked:
            return say("Keep the controls to swipes; one clear goal.")
        first_check = "Fix what your advisers found" not in asked and (
            "Added a score" not in asked
        )
        if "Tester" in system.split("You are ")[1][:20] and first_check:
            return say("1. Add a score display.")
        return say("LOOKS GOOD")
    if "You are the main AI in the user's Playground" in system:
        if asked.startswith("Fix what your advisers found"):
            return say("Added a score.")
        if not tools_used:
            return tool_call("start_project", {"name": "Snake", "template": "game"})
        if len(tools_used) == 1:
            return tool_call(
                "remember", {"text": "The user likes neon green.", "kind": "taste"}
            )
        return say("Built Snake: index.html, styles.css and game.js.")
    return say("Hi!")


def test_the_main_ai_does_the_work_and_the_advisers_advise(
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
        page.get_by_role("heading", name="What do you want to get done?")
    ).to_be_visible()
    page.get_by_label("The task").fill("Make a snake game")
    expect(page.get_by_text("Advising: Tester", exact=False)).to_be_visible()
    page.get_by_role("button", name="Start task ↗").click()
    page.wait_for_function(
        "() => window.fccPhone.state.tasks[0] && window.fccPhone.state.tasks[0].status === 'done'",
        timeout=30000,
    )
    task = page.evaluate("() => window.fccPhone.state.tasks[0]")
    stages = [(s["stage"], s["pass"], s["agent"]) for s in task["steps"]]
    assert stages == [
        ("kickoff", 0, "Tester"),
        ("kickoff", 0, "Researcher"),
        ("work", 1, "Jarvis"),
        ("review", 1, "Tester"),
        ("review", 1, "Researcher"),
        ("work", 2, "Jarvis"),
        ("review", 2, "Tester"),
        ("review", 2, "Researcher"),
    ], stages
    project = page.evaluate(
        "() => window.fccPhone.state.projects.find((p) => p.name === 'Snake')"
    )
    assert project and "game.js" in project["files"]
    assert task["project_id"] == project["id"]
    # The advisers' note went to the main AI for its fix.
    briefs = [
        str(call["messages"][1]["content"])
        for call in seen
        if "You are the main AI in the user's Playground"
        in call["messages"][0]["content"]
    ]
    assert any(
        brief.startswith("Fix what your advisers found") and "Add a score" in brief
        for brief in briefs
    )
    # Advisers only advise: no tool that changes anything; the main AI has hands.
    for call in seen:
        system = call["messages"][0]["content"]
        names = {tool["function"]["name"] for tool in call.get("tools") or []}
        if "You are an adviser in the user's Playground" in system:
            assert not names & MAKING, names
        if "You are the main AI in the user's Playground" in system and names:
            assert {"write_file", "start_project", "ask_agent"} <= names
    # Each AI keeps its own mind; the user's taste is shared with every AI.
    memories = page.evaluate("() => window.fccPhone.state.memories")
    jarvis_mind = {(m["kind"], m["own"]) for m in memories if m["agent_id"] == "jarvis"}
    assert {("pattern", True), ("lesson", True), ("thought", True)} <= jarvis_mind
    assert any(m["agent_id"] == "tester" and m["kind"] == "lesson" for m in memories)
    taste = [m for m in memories if m["kind"] == "taste"]
    assert taste and taste[0]["own"] is False and "neon green" in taste[0]["text"]
    prompt = page.evaluate(
        """async () => {
            const { systemPrompt } = await import('./js/agents.js');
            const builder = window.fccPhone.state.agents.find((a) => a.id === 'builder');
            const jarvis = window.fccPhone.state.agents.find((a) => a.id === 'jarvis');
            return [systemPrompt(builder, 'hi'), systemPrompt(jarvis, 'hi')];
        }"""
    )
    assert "The user's taste" in prompt[0] and "neon green" in prompt[0]
    assert "Start from the game template" in prompt[1]  # Jarvis's own pattern
    assert "Start from the game template" not in prompt[0]  # not the Builder's
    expect(page.get_by_role("heading", name="Done", exact=True)).to_be_visible()
    expect(
        page.get_by_text("Jarvis does the work · advising: Tester, Researcher")
    ).to_be_visible()
    go(page, "minds")
    jarvis_card = page.locator("section.card", has_text="Jarvis's mind")
    expect(
        jarvis_card.get_by_text("Start from the game template, then make it mine.")
    ).to_be_visible()
    assert errors == []


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
            const task = await startPlayground('Make a snake game');
            stopTask(task.id);
            return task.id;
        }"""
    )
    page.wait_for_function(
        f"() => window.fccPhone.state.tasks.find((t) => t.id === {json.dumps(stopped)}).status === 'stopped'",
        timeout=15000,
    )
    task = page.evaluate("() => window.fccPhone.state.tasks[0]")
    assert all(step["status"] != "done" for step in task["steps"])
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
