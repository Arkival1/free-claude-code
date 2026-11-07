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
    expect(tabs).to_have_text(["+New task", "◷Tasks", "▤Files", "⚗Lab", "⋯More"])
    assert page.evaluate("() => window.fccPhone.state.settings.look") == "playground"
    page.reload()
    page.wait_for_function("() => window.fccPhone && window.fccPhone.ready")
    page.evaluate("() => window.fccPhone.ready")
    expect(tabs).to_have_text(["+New task", "◷Tasks", "▤Files", "⚗Lab", "⋯More"])
    page.locator("#tabs .tab", has_text="Files").click()
    expect(page.get_by_text("Your work, all in one place")).to_be_visible()
    go(page, "settings")
    page.get_by_role("button", name="HUD").click()
    expect(tabs).to_have_text(["◆Home", "◌Chats", "◎Agents", "⚡Models", "⋯More"])


def test_only_a_plain_looks_good_approves_and_helpers_stay_in_parts(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    verdicts = page.evaluate(
        """async () => {
            const { approves } = await import('./js/playground.js');
            return ['LOOKS GOOD', 'Looks good.', '**Looks good** to me!', 'LOOKS GOOD\\n1. Add a score.',
                    'Looks good. Fix the score.', 'LOOKS GOOD, however the score is missing.',
                    'It looks good', '1. Add a score'].map((text) => [text, approves(text)]);
        }"""
    )
    assert [ok for _, ok in verdicts] == [
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    ], verdicts
    wrote = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const { createProject } = await import('./js/projects.js');
            const project = await createProject('Parts test');
            const builder = window.fccPhone.state.agents.find((a) => a.id === 'builder');
            const ctx = { project, depth: 0, chain: [], built: new Set(), tools: ['write_file', 'edit_file'], partsOnly: true };
            const main = await runTool(builder, { name: 'write_file', arguments: { path: 'game.js', content: 'x' } }, ctx);
            const part = await runTool(builder, { name: 'write_file', arguments: { path: 'parts/art.js', content: 'y' } }, ctx);
            return { main, part, files: Object.keys(project.files) };
        }"""
    )
    assert "only under parts/" in wrote["main"] and wrote["files"] == ["parts/art.js"]


def test_a_full_library_never_drops_an_approved_reference(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    result = page.evaluate(
        """async () => {
            const lib = await import('./js/library.js');
            const state = window.fccPhone.state;
            state.library = [];
            const first = await lib.addToLibrary({ kind: 'note', title: 'First approved' });
            await lib.addToLibrary({ kind: 'game', title: 'Old waiting', approved: false });
            for (let i = 0; i < 298; i += 1) await lib.addToLibrary({ kind: 'note', title: `Note ${i}` });
            await lib.addToLibrary({ kind: 'game', title: 'New waiting', approved: false });
            const kept = state.library.some((item) => item.id === first.id);
            const dropped = !state.library.some((item) => item.title === 'Old waiting');
            await lib.removeFromLibrary(state.library.find((item) => item.title === 'New waiting').id);
            await lib.addToLibrary({ kind: 'note', title: 'Fits again' });
            let full = '';
            try { await lib.addToLibrary({ kind: 'note', title: 'One too many' }); } catch (error) { full = error.message; }
            return { kept, dropped, size: state.library.length, full };
        }"""
    )
    assert result["kept"] and result["dropped"] and result["size"] == 300
    assert "full" in result["full"]


def test_a_helper_that_cannot_finish_is_named_in_the_result(
    page: Page, admin_base_url: str
) -> None:
    fake_gemini(page, playground_brain)
    open_phone(page, admin_base_url)
    use_gemini(page)
    # The Builder (the helper) thinks with Groq, which has no key, and the
    # fallback is off: its part can't be built.
    page.evaluate(
        """async () => {
            const state = window.fccPhone.state;
            state.settings.fallback = false;
            state.agents.find((a) => a.id === 'builder').brain = 'groq';
            const { startPlayground } = await import('./js/playground.js');
            await startPlayground('a snake game with swipe controls', { advisers: 'none' });
        }"""
    )
    page.wait_for_function(
        "() => window.fccPhone.state.tasks[0].status === 'done'", timeout=30000
    )
    task = page.evaluate("() => window.fccPhone.state.tasks[0]")
    help_step = next(s for s in task["steps"] if s["stage"] == "help")
    assert help_step["status"] == "failed"
    assert "Builder couldn't finish its part" in task["summary"]


def website_brain(body: dict) -> dict:
    system = body["messages"][0]["content"]
    messages = body["messages"]
    asked = str(messages[1].get("content")) if len(messages) > 1 else ""
    tools_used = [m for m in messages if m["role"] == "tool"]
    if "Write down what to keep in your own mind" in system:
        return say(json.dumps({"pattern": "Content first, then the layout."}))
    if "You are a helper in the user's Playground" in system:
        if not tools_used:
            return tool_call(
                "write_file",
                {
                    "path": "parts/content.md",
                    "content": "# Calm Yoga\nClasses at 7am and 6pm. $20 a class.",
                },
            )
        return say("Wrote parts/content.md: the studio's real text.")
    if "You are an adviser in the user's Playground" in system:
        if "Advise the main AI before it starts" in asked:
            return say("Use the landing template; check with look_at_site.")
        return say("LOOKS GOOD")
    if "You are the main AI in the user's Playground" in system:
        if not tools_used:
            name = re.search(r"Work in the project (.+?): start_project", asked)
            assert name, asked
            return tool_call(
                "start_project", {"name": name.group(1), "template": "landing"}
            )
        if len(tools_used) == 1:
            return tool_call("read_file", {"path": "parts/content.md"})
        if len(tools_used) == 2:
            # The page in the studio's own words (FCC's check won't call the
            # site finished while the template's placeholder text is there).
            return tool_call(
                "write_file",
                {
                    "path": "index.html",
                    "content": (
                        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width, initial-scale=1">'
                        "<title>Calm Yoga</title></head><body><main><h1>Calm Yoga</h1>"
                        "<p>Classes at 7am and 6pm. $20 a class.</p></main></body></html>"
                    ),
                },
            )
        return say("Built the landing page with the studio's classes and prices.")
    return say("Hi!")


def test_the_main_ai_builds_a_website_with_a_helper_and_advisers(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    seen = fake_gemini(page, website_brain)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "settings")
    page.get_by_role("button", name="Playground").click()
    go(page, "home")
    page.get_by_role("button", name="Make a website").click()
    page.get_by_label("The task").fill("a calm yoga studio site with class times")
    expect(page.get_by_text("Helping (they build parts): Researcher")).to_be_visible()
    page.get_by_role("button", name="Start task ↗").click()
    page.wait_for_function(
        "() => window.fccPhone.state.tasks[0] && window.fccPhone.state.tasks[0].status === 'done'",
        timeout=30000,
    )
    task = page.evaluate("() => window.fccPhone.state.tasks[0]")
    assert task["type"] == "website"
    assert [(s["stage"], s["agent"]) for s in task["steps"]][:4] == [
        ("kickoff", "Tester"),
        ("kickoff", "Helper"),
        ("work", "Jarvis"),
        ("help", "Researcher"),
    ]
    project = page.evaluate(
        f"() => window.fccPhone.state.projects.find((p) => p.id === {json.dumps(task['project_id'])})"
    )
    assert {"index.html", "parts/content.md"} <= set(project["files"])
    # The main AI read the helper's part, and worked to the website steps.
    briefs = [
        call
        for call in seen
        if "You are the main AI in the user's Playground"
        in call["messages"][0]["content"]
    ]
    assert any(
        m["role"] == "tool" and "Classes at 7am" in str(m.get("content"))
        for call in briefs
        for m in call["messages"]
    )
    assert any(
        "Website engineering" in call["messages"][0]["content"] for call in briefs
    )
    library = page.evaluate("() => window.fccPhone.state.library")
    assert library[0]["kind"] == "website" and library[0]["approved"] is False
    assert errors == []


def lazy_brain(body: dict) -> dict:
    """The main AI starts a site from the template and calls it done without
    replacing the template's text (small models do)."""
    system = body["messages"][0]["content"]
    messages = body["messages"]
    asked = str(messages[1].get("content")) if len(messages) > 1 else ""
    tools_used = [m for m in messages if m["role"] == "tool"]
    if "Write down what to keep in your own mind" in system:
        return say(json.dumps({"pattern": "Replace the template's text."}))
    if "You are the main AI in the user's Playground" in system:
        if not tools_used and "Work in the project" in asked:
            name = re.search(r"Work in the project (.+?): start_project", asked)
            assert name, asked
            return tool_call(
                "start_project", {"name": name.group(1), "template": "landing"}
            )
        return say("All done, the site is finished.")
    return say("Hi!")


def test_a_site_that_fails_fccs_check_is_not_called_done(
    page: Page, admin_base_url: str
) -> None:
    """Found by CodeRabbit: with no advisers, FCC's own check decides. The
    main AI gets the check's findings and tries again; still failing after
    every try, the task says it isn't finished and nothing waits in the
    library as if it were."""
    seen = fake_gemini(page, lazy_brain)
    open_phone(page, admin_base_url)
    use_gemini(page)
    page.evaluate(
        """async () => {
            window.fccPhone.state.library = [];
            const { startPlayground } = await import('./js/playground.js');
            await startPlayground('a calm yoga studio site', { type: 'website', helpers: 0, advisers: 'none' });
        }"""
    )
    page.wait_for_function(
        "() => window.fccPhone.state.tasks[0] && ['done', 'failed'].includes(window.fccPhone.state.tasks[0].status)",
        timeout=30000,
    )
    task = page.evaluate("() => window.fccPhone.state.tasks[0]")
    assert task["status"] == "failed", task["summary"]
    assert task["summary"].startswith("Not finished: FCC's own check still finds")
    work = [s for s in task["steps"] if s["stage"] == "work"]
    assert len(work) == 3
    assert "FCC's own check" in work[0]["result"].split("\n")[0] + work[0]["result"]
    # The second try was told what FCC's check found.
    assert any(
        "FCC's own check: index.html still has the template's placeholder line"
        in str(call["messages"][1].get("content"))
        for call in seen
        if "You are the main AI in the user's Playground"
        in call["messages"][0]["content"]
    )
    assert page.evaluate("() => window.fccPhone.state.library.length") == 0
