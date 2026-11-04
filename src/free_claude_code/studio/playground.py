"""The Playground: FCC's Manus-like mode.

One main AI does the job with its own hands, thinking on this PC's model when
one is set up. Up to two advisers (usually agents on server AIs) think
alongside it, so three AIs work at once; a team meeting brings in up to five
to advise, two at a time. None of them touches the work unless the owner
hands it over. After the work the advisers check it and the main AI fixes
what they found, three tries in all. Each AI then keeps what it learned in
its own mind (memories tagged thought, pattern or lesson); the owner's taste
(tagged taste) is shared, so every AI works in the owner's image.

This module holds the rules and the words; ``StudioService`` runs the jobs.
"""

import re
from collections.abc import Callable, Sequence

from .jsonish import lenient_object
from .models import Agent, PlaygroundStep

MAX_ADVISERS = 2
"""Advisers thinking at the same time as the main AI: three AIs at once."""
MAX_MEETING = 5
"""Advisers in a team meeting (they take turns, two at a time)."""
MAX_TRIES = 3
"""The work, then up to two fixes."""
STEP_CHARS = 1500
MIND_TAGS: tuple[str, ...] = ("thought", "pattern", "lesson")
"""Memory tags that make up one AI's own mind."""
TASTE_TAG = "taste"
"""What the owner likes; shared by every AI."""
LOOKS_GOOD = re.compile(r"\blooks good\b", re.IGNORECASE)

HANDS_TOOLS: tuple[str, ...] = (
    "start_project",
    "write_file",
    "read_file",
    "edit_file",
    "search_files",
    "list_files",
    "delete_file",
    "restore_file",
    "update_plan",
    "check_project",
    "polish_check",
    "try_page",
    "look_page",
    "site_layouts",
    "ui_kit",
    "ui_library",
    "godot",
    "game_assets",
    "find_images",
    "list_photos",
    "use_photo",
    "save_image",
    "look_reference",
    "skill",
    "knowledge",
    "research",
    "web_search",
    "web_fetch",
    "study_video",
    "video_notes",
    "test_code",
    "calculate",
    "weather",
    "remember",
    "recall",
    "ideas",
)
"""The main AI's hands: every tool that makes or finds things."""

ADVISER_TOOLS: tuple[str, ...] = (
    "read_file",
    "search_files",
    "list_files",
    "check_project",
    "look_page",
    "skill",
    "knowledge",
    "research",
    "web_search",
    "web_fetch",
    "study_video",
    "video_notes",
    "calculate",
    "weather",
    "recall",
    "ideas",
)
"""Advisers look and think; nothing here changes the work."""

HANDS_PROMPT = (
    "You are the main AI in the owner's Playground, and you are the hands: you "
    "do the whole job yourself, start to finish, with your tools (research, "
    "plans, writing, code, websites, games). Your advisers only advise: weigh "
    "what they say, use what helps, and decide yourself. Work in the owner's "
    "image: their ideas and taste come first, and when they say what they "
    "like, keep it with remember (tag it taste). When a job makes files, use "
    "the current project or start_project (godot for a game in Godot), write "
    "complete files, then check_project and fix what it finds. Read a skill "
    "when a job needs depth. Finish by saying what you made and where."
)

ADVISER_PROMPT = (
    "You are an adviser in the owner's Playground. The main AI does the work "
    "with its own hands; you never change files or do the job yourself. Think "
    "it through, look things up or read the project with your tools when it "
    "helps, and give advice the main AI can act on: short, specific, the most "
    "important first."
)

REFLECT_PROMPT = (
    "You just took part in a job in the owner's Playground. Write down what to "
    "keep in your own mind, as JSON only: "
    '{"thought": "one thing you are still thinking about after this job", '
    '"pattern": "a way of working that went well and that you will use again", '
    '"lesson": "a mistake or surprise to remember next time"}. '
    "Leave a field empty when there is nothing worth keeping."
)

_MAKING = re.compile(
    r"\b(game|site|website|web|app|page|code|build|make|design|shop|landing)\b",
    re.IGNORECASE,
)


def pick_advisers(
    goal: str,
    agents: Sequence[Agent],
    hands_id: str,
    *,
    count: int = MAX_ADVISERS,
    is_local: Callable[[str], bool] | None = None,
) -> tuple[str, ...]:
    """Advisers that fit a job: testers and researchers for things to build,
    researchers and planners for the rest. Agents on server AIs come first
    (they advise; the PC's own model has the hands). The main AI is never its
    own adviser; archived agents, the Guide and the Changer's team sit out."""
    order = (
        ("tester", "reviewer", "researcher", "helper", "designer", "coder")
        if _MAKING.search(goal)
        else ("researcher", "helper", "reviewer", "tester", "designer", "coder")
    )

    def rank(agent: Agent) -> tuple[int, int]:
        local = is_local is not None and is_local(agent.model)
        role = order.index(agent.role) if agent.role in order else len(order)
        return (int(local), role)

    pool = [
        agent
        for agent in agents
        if agent.id != hands_id
        and not agent.archived
        and agent.role not in {"guide", "main"}
        and not agent.name.startswith("Changer")
    ]
    pool.sort(key=rank)
    return tuple(agent.id for agent in pool[: max(0, count)])


def advice_brief(goal: str, hands: str, project: str = "") -> str:
    """What an adviser is asked before the work starts."""
    where = f"\n\nThe project: {project}." if project else ""
    return (
        "Advise the main AI before it starts: the best approach, what would make "
        "the result great, and one thing to watch out for. At most six short "
        f"lines.\n\nThe job: {goal}\n\nThe main AI doing it: {hands}.{where}"
    )


def check_brief(goal: str, hands: str, said: str, project: str = "") -> str:
    """What an adviser is asked after the main AI says it finished."""
    where = f"\n\nThe project: {project}." if project else ""
    return (
        f"The main AI ({hands}) says it finished:\n{said[:STEP_CHARS]}\n\n"
        "Check the work against the job (read the files or run check_project when "
        "it helps). If it is good, answer exactly: LOOKS GOOD. Otherwise list what "
        f"to fix, most important first, at most five lines.\n\nThe job: {goal}{where}"
    )


def hands_brief(goal: str, try_no: int, advice: str, project: str = "") -> str:
    """The main AI's brief for one try."""
    parts = [
        goal
        if try_no == 1
        else f"Fix what your advisers found, then check again. The job: {goal}",
        f"Work in the project {project}."
        if project
        else "If the job makes files, start a project with start_project.",
    ]
    if advice:
        said = "Your advisers said" if try_no == 1 else "Your advisers found"
        parts.append(f"{said}:\n{advice}\nUse what helps; you decide.")
    return "\n\n".join(parts)


def looks_good(text: str) -> bool:
    return bool(LOOKS_GOOD.search(text))


def advice_notes(steps: Sequence[PlaygroundStep]) -> str:
    """The advisers' words, one line each, from the steps that finished."""
    return "\n".join(
        f"- {step.agent}: {step.result}"
        for step in steps
        if step.status == "done" and step.result
    )


def reflection(text: str) -> dict[str, str]:
    """An AI's notes after a job: its thought, pattern and lesson (empty
    fields left out)."""
    found = lenient_object(text)
    return {
        tag: str(found[tag]).strip()[:600]
        for tag in MIND_TAGS
        if isinstance(found.get(tag), str) and str(found[tag]).strip()
    }
