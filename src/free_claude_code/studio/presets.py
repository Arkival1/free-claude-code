"""Starter roles and tool sets for the agents the user adds."""

from free_claude_code.core.json_types import JsonObject

from .models import AGENT_ROLES
from .tools import DEFAULT_TOOL_NAMES, TOOL_SPEC_BY_NAME

RESEARCHER_TOOLS: tuple[str, ...] = (
    "research",
    "web_search",
    "web_fetch",
    "test_code",
    "write_file",
    "read_file",
    "list_files",
    "remember",
    "recall",
    "finish",
)
RESEARCHER_PROMPT = (
    "Research questions for the user and the team with the research tool, "
    "which reads at least ten sources across the web, Reddit, YouTube, Stack "
    "Overflow, GitHub, and docs. Compare what the sources say. When they "
    "contain code, try it with test_code before recommending it, and say what "
    "passed. Answer clearly, cite sources as [n] with their links, and save "
    "the key findings with remember, tagged verified or unverified, so the "
    "other agents can use them."
)
BUILDER_PROMPT = (
    "Build complete, working websites, apps, and games on your own: plan the "
    "files, write all the code, run and test it, and fix what fails. When an "
    "error resists a quick fix, use ask_researcher with the exact error, what "
    "you tried, and your stack, then apply the fix and test again. Follow the "
    "skills and tools the user taught you."
)
DESIGNER_PROMPT = (
    "Design and build polished, accessible interfaces: layout, typography, "
    "color, spacing, and responsive behavior that works on phones first. "
    "Research current design patterns when unsure, and check your pages in "
    "the project preview."
)
TESTER_PROMPT = (
    "Test projects the team built: read the code, run it and its tests, try "
    "edge cases, and report each bug with the steps to reproduce it and a "
    "suggested fix. Ask the Researcher when an error is unfamiliar."
)
ASSISTANT_PROMPT = (
    "Help the user with questions and everyday tasks, looking things up when needed."
)

TOOL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Internet", ("web_search", "web_fetch", "research")),
    ("Build files", ("write_file", "read_file", "list_files", "delete_file")),
    ("Run and test code", ("run_command", "test_code")),
    ("Ask the Researcher", ("ask_researcher",)),
    ("Memory", ("remember", "recall")),
)
_BUILD = ("write_file", "read_file", "list_files", "delete_file")
_WEB = ("web_search", "web_fetch", "research")
_MEMORY = ("remember", "recall")
PRESETS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("Builder", "builder", BUILDER_PROMPT, DEFAULT_TOOL_NAMES),
    ("Researcher", "researcher", RESEARCHER_PROMPT, RESEARCHER_TOOLS),
    (
        "Designer",
        "builder",
        DESIGNER_PROMPT,
        (*_BUILD, *_WEB, "test_code", "ask_researcher", *_MEMORY),
    ),
    (
        "Tester",
        "agent",
        TESTER_PROMPT,
        (
            "read_file",
            "list_files",
            "run_command",
            "test_code",
            *_WEB,
            "ask_researcher",
            *_MEMORY,
        ),
    ),
    ("Assistant", "assistant", ASSISTANT_PROMPT, (*_WEB, *_MEMORY)),
    ("Custom", "agent", "", DEFAULT_TOOL_NAMES),
)
ROLE_NOTES = {
    "builder": "Builds websites, apps, and games, and asks the Researcher when stuck.",
    "researcher": "Researches with ten or more sources and answers the others.",
    "agent": "A general worker with the tools you give it.",
    "assistant": "Answers questions and helps with everyday tasks.",
    "teacher": "Teaches classes to another agent.",
    "student": "Learns in classes from a teacher.",
}


def agent_options() -> JsonObject:
    """Describe roles, presets, and tools for the add-agent sheet."""
    return {
        "roles": [
            {"role": role, "note": ROLE_NOTES.get(role, "")}
            for role in AGENT_ROLES
            if role not in {"main", "guide"}
        ],
        "presets": [
            {"name": name, "role": role, "prompt": prompt, "tools": list(tools)}
            for name, role, prompt, tools in PRESETS
        ],
        "tool_groups": [
            {
                "label": label,
                "tools": [
                    {"name": tool, "description": TOOL_SPEC_BY_NAME[tool].description}
                    for tool in tools
                ],
            }
            for label, tools in TOOL_GROUPS
        ],
    }
