"""The Orb edition: Jarvis alone on this PC, with two advisers.

Jarvis thinks on the PC's own model and works with his own hands (the PC
tools, files, the web, Godot). The two advisers are smaller models, each
with a speciality the owner gives them; they get the web and the tool list
only, never the PC. No plugins, GitHub, connectors, MCP or other agents.
"""

from .pc_control import ADVISER_TOOLS

ORB_ADVISERS = 2
ADVISER_ROLE = "assistant"
DEFAULT_ADVISERS = (
    ("Idea Adviser", "Game design and fresh ideas: what would make it fun."),
    ("Research Adviser", "Finds references, tutorials and tools on the web."),
)

# Every tool Jarvis may use in the Orb (the PC tools are handed out apart,
# only on the local model). Nothing that adds plugins, reaches GitHub or
# connectors, or hands work to other agents.
ORB_TOOLS = frozenset(
    {
        "web_search",
        "web_fetch",
        "research",
        "study_video",
        "video_notes",
        "look_reference",
        "look_page",
        "write_file",
        "read_file",
        "edit_file",
        "search_files",
        "list_files",
        "delete_file",
        "restore_file",
        "update_plan",
        "start_project",
        "list_projects",
        "check_project",
        "try_page",
        "test_code",
        "godot",
        "game_assets",
        "skill",
        "remember",
        "recall",
        "knowledge",
        "calculate",
        "todo",
        "system_status",
        "conversation",
        "finish",
        *ADVISER_TOOLS,
    }
)
