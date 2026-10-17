"""Subagents: helpers the owner adds, each with a role, that join other
agents' tasks on their own when the task fits their role.

A researcher subagent joins while the work runs and reports what it finds; a
developer or coder takes a separate part of the job; a tester or reviewer
comes in after the task finishes and checks it. Subagents never call more
subagents, so help never runs away.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .models import Agent

MAX_HELPERS = 2
"""At most this many subagents join one task."""
HELP_PREFIX = "Subagent help: "
"""How a helper's task starts, so it is never helped in turn."""


@dataclass(frozen=True, slots=True)
class HelperRole:
    role: str
    title: str
    when: str
    """'during' joins while the task runs; 'after' when it has finished."""
    words: tuple[str, ...]
    part: str


HELPER_ROLES: tuple[HelperRole, ...] = (
    HelperRole(
        "developer",
        "Developer",
        "during",
        (
            "app",
            "code",
            "program",
            "script",
            "api",
            "backend",
            "back end",
            "frontend",
            "database",
            "bug",
            "fix",
            "feature",
            "game",
            "bot",
            "function",
            "server",
            "build",
        ),
        "Take a separate part of the job the other agent hasn't started (a "
        "module, a feature, a fix) and build it completely. Write your own "
        "files; don't rewrite the files it is writing.",
    ),
    HelperRole(
        "coder",
        "Coder",
        "during",
        (
            "code",
            "script",
            "app",
            "bug",
            "fix",
            "function",
            "game",
            "bot",
            "tool",
            "program",
        ),
        "Take a separate piece of the code (a helper module, a script, a "
        "fix) and write it completely in your own files.",
    ),
    HelperRole(
        "researcher",
        "Researcher",
        "during",
        (
            "research",
            "find",
            "compare",
            "look up",
            "best",
            "latest",
            "news",
            "price",
            "how to",
            "which",
            "website",
            "business",
            "plan",
        ),
        "Research what the job needs (facts, examples, libraries, good "
        "designs) and report the useful findings with their sources. Don't "
        "edit the project's files.",
    ),
    HelperRole(
        "builder",
        "Builder",
        "during",
        (
            "website",
            "site",
            "page",
            "landing",
            "design",
            "layout",
            "style",
            "html",
            "css",
            "shop",
            "portfolio",
        ),
        "Take the look and the pages: layout, styles, and the pages the "
        "other agent hasn't started. Write your own files.",
    ),
    HelperRole(
        "tester",
        "Tester",
        "after",
        (
            "app",
            "website",
            "site",
            "code",
            "script",
            "game",
            "build",
            "fix",
            "feature",
            "page",
            "bug",
        ),
        "The other agent has finished. Test what it made: open the pages, "
        "run the code, try the buttons. Fix small bugs yourself and report "
        "anything bigger.",
    ),
    HelperRole(
        "helper",
        "Reviewer",
        "after",
        ("plan", "write", "report", "app", "website", "code", "design"),
        "The other agent has finished. Review the result against the request: "
        "what is missing, what is wrong, what would make it better. Fix small "
        "things and list the rest.",
    ),
)
BY_ROLE = {role.role: role for role in HELPER_ROLES}
SUBAGENT_ROLES: tuple[str, ...] = tuple(BY_ROLE)


def fits(role: str, goal: str) -> bool:
    """Whether a task's goal is the kind of work this role helps with."""
    helper = BY_ROLE.get(role)
    if helper is None:
        return False
    text = goal.casefold()
    return any(re.search(rf"\b{re.escape(word)}", text) for word in helper.words)


def is_help(goal: str) -> bool:
    return goal.startswith(HELP_PREFIX)


def pick(subagents: Sequence[Agent], owner: Agent, goal: str) -> list[Agent]:
    """The switched-on subagents that fit this task, at most MAX_HELPERS,
    never the agent doing the task and never for a helper's own task."""
    if owner.subagent or is_help(goal):
        return []
    chosen = [
        agent
        for agent in subagents
        if agent.subagent
        and agent.active
        and not agent.archived
        and agent.id != owner.id
        and fits(agent.role, goal)
    ]
    return chosen[:MAX_HELPERS]


def helper_goal(helper: Agent, owner: Agent, goal: str, result: str = "") -> str:
    role = BY_ROLE[helper.role]
    lines = [
        f"{HELP_PREFIX}{owner.name} ({owner.role}) is working on: {goal}",
        f"Your part, as the {role.title}: {role.part}",
    ]
    if result.strip():
        lines.append(
            f"What {owner.name} reported when it finished: {result.strip()[:1500]}"
        )
    lines.append("Finish with a short report of exactly what you did.")
    return "\n".join(lines)


def when(role: str) -> str:
    helper = BY_ROLE.get(role)
    return helper.when if helper else "during"
