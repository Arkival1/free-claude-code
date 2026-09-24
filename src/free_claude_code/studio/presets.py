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
    "search_files",
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
    "files with update_plan, write the code, and change existing files with "
    "edit_file after reading them; find things with search_files and "
    "list_files. Run and test your work with run_command and test_code, and "
    "fix what fails. When an error resists a quick fix, use ask_researcher "
    "with the exact error, what you tried, and your stack (the Helper turns "
    "the findings into a plan), or ask_helper to think a problem through. "
    "Follow the skills and tools the user taught you."
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
HELPER_TOOLS: tuple[str, ...] = (
    "recall",
    "remember",
    "read_file",
    "list_files",
    "search_files",
    "web_search",
    "web_fetch",
    "update_plan",
    "finish",
)
HELPER_PROMPT = (
    "You support the other agents. When an agent brings you a goal and "
    "material, such as the Researcher's findings, an error log, or notes: "
    "1) keep only what is relevant, reliable, and doable with this team's "
    "tools and the user's setup, and drop the rest; 2) brainstorm two or three "
    "ways to reach the goal; 3) pick the best one and say why in one line; "
    "4) give numbered, concrete next steps the agent can take now, with "
    "commands or code patterns when they help; 5) name anything to test or "
    "verify first. Be brief and practical, fit the plan to the size of the "
    "task, and save patterns that will help again with remember."
)
ASSISTANT_PROMPT = (
    "Help the user with questions and everyday tasks, looking things up when needed."
)

TOOL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Internet", ("web_search", "web_fetch", "research")),
    (
        "Code and files",
        (
            "read_file",
            "write_file",
            "edit_file",
            "search_files",
            "list_files",
            "delete_file",
            "update_plan",
        ),
    ),
    ("Run and test code", ("run_command", "test_code")),
    ("Ask teammates", ("ask_researcher", "ask_helper")),
    ("Memory", ("remember", "recall")),
)
_BUILD = (
    "write_file",
    "read_file",
    "edit_file",
    "search_files",
    "list_files",
    "delete_file",
    "update_plan",
)
_WEB = ("web_search", "web_fetch", "research")
_MEMORY = ("remember", "recall")
PRESETS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("Builder", "builder", BUILDER_PROMPT, DEFAULT_TOOL_NAMES),
    ("Researcher", "researcher", RESEARCHER_PROMPT, RESEARCHER_TOOLS),
    ("Helper", "helper", HELPER_PROMPT, HELPER_TOOLS),
    (
        "Designer",
        "builder",
        DESIGNER_PROMPT,
        (*_BUILD, *_WEB, "test_code", "ask_researcher", "ask_helper", *_MEMORY),
    ),
    (
        "Tester",
        "agent",
        TESTER_PROMPT,
        (
            "read_file",
            "list_files",
            "search_files",
            "run_command",
            "test_code",
            *_WEB,
            "ask_researcher",
            "ask_helper",
            *_MEMORY,
        ),
    ),
    ("Assistant", "assistant", ASSISTANT_PROMPT, (*_WEB, *_MEMORY)),
    ("Custom", "agent", "", DEFAULT_TOOL_NAMES),
)
ROLE_NOTES = {
    "builder": "Builds websites, apps, and games, and asks the Researcher when stuck.",
    "researcher": "Researches with ten or more sources and answers the others.",
    "helper": "Filters findings, brainstorms, and turns them into next steps for the others.",
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
