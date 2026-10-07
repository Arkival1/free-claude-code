"""The HQ: the whole team as a little pixel office.

Every part of the agentic workflow is a station: Jarvis's command desk,
the research library, the code workshop, the test bench, the Lab, the video
studio, the memory archive, the classroom, the model room, the approval
desk, the toolshed, the mailroom, and the break room. Each agent walks to
the station of the tool it is using now, and back to the break room when
it has nothing to do. The page polls one snapshot; this module only maps
what the team is doing onto the map.
"""

from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject


@dataclass(frozen=True, slots=True)
class Station:
    id: str
    name: str
    what: str
    route: str = ""
    """The app page this station opens, if any."""


STATIONS: tuple[Station, ...] = (
    Station(
        "desk",
        "Command desk",
        "Jarvis takes your requests and hands out the work.",
        "home",
    ),
    Station(
        "library",
        "Research library",
        "Web searches, pages read, and deep research with sources.",
        "agents",
    ),
    Station(
        "workshop",
        "Code workshop",
        "Websites, apps, games, and files being written.",
        "agents",
    ),
    Station(
        "testbench",
        "Test bench",
        "Code and tests running, projects checked, bugs found.",
        "agents",
    ),
    Station(
        "lab",
        "Science lab",
        "Mixing chemicals, making products, building circuits.",
        "lab",
    ),
    Station(
        "studio",
        "Video studio",
        "The Content Farm: scripts, voices, cartoons, edits, renders.",
        "farm",
    ),
    Station(
        "archive",
        "Memory archive",
        "Remembering, recalling, notes, and what the team knows.",
        "more",
    ),
    Station(
        "school",
        "Classroom",
        "Learn mode and classes between teacher and student.",
        "learn",
    ),
    Station(
        "servers", "Model room", "The AI models: on this PC and on servers.", "engine"
    ),
    Station("approvals", "Approval desk", "Commands waiting for your yes.", ""),
    Station(
        "toolshed",
        "Toolshed",
        "Skills and MCP servers from GitHub; repo agents pick up tools here.",
        "more",
    ),
    Station(
        "mailroom",
        "Mailroom",
        "To-dos, reminders, and jobs passed between agents.",
        "more",
    ),
    Station("lounge", "Break room", "Agents with nothing to do right now.", "agents"),
)
STATION_BY_ID = {station.id: station for station in STATIONS}

TOOL_STATION: dict[str, str] = {
    **dict.fromkeys(
        (
            "web_search",
            "web_fetch",
            "research",
            "ask_researcher",
            "find_images",
            "weather",
            "desktop_browser",
        ),
        "library",
    ),
    **dict.fromkeys(
        (
            "start_project",
            "write_file",
            "edit_file",
            "read_file",
            "list_files",
            "search_files",
            "delete_file",
            "restore_file",
            "update_plan",
            "save_image",
            "use_photo",
            "list_photos",
        ),
        "workshop",
    ),
    **dict.fromkeys(
        ("run_command", "test_code", "check_project", "polish_check", "code_and_test"),
        "testbench",
    ),
    "lab": "lab",
    "farm": "studio",
    **dict.fromkeys(
        (
            "remember",
            "recall",
            "knowledge",
            "conversation",
            "video_notes",
            "study_video",
        ),
        "archive",
    ),
    "learn": "school",
    **dict.fromkeys(("skill", "mcp", "toolshed"), "toolshed"),
    **dict.fromkeys(
        ("todo", "ask_agent", "team_task", "ask_helper", "team_status", "stop_agent"),
        "mailroom",
    ),
    **dict.fromkeys(("agent_model", "manage_agent", "system_status"), "servers"),
}
ROLE_HOME: dict[str, str] = {
    "main": "desk",
    "guide": "desk",
    "researcher": "library",
    "builder": "workshop",
    "coder": "workshop",
    "tester": "testbench",
    "lab": "lab",
    "farm": "studio",
    "teacher": "school",
    "student": "school",
    "helper": "mailroom",
    "assistant": "mailroom",
}


def station_for(role: str, tool: str, busy: bool) -> str:
    """Where an agent is: the station of its tool while it works, its own
    station when the tool has none, and the break room when idle (Jarvis
    stays at his desk)."""
    if role == "main":
        return TOOL_STATION.get(tool, "desk") if busy and tool else "desk"
    if not busy:
        return "lounge"
    return TOOL_STATION.get(tool) or ROLE_HOME.get(role, "workshop")


def stations_view(counts: dict[str, int], notes: dict[str, str]) -> list[JsonObject]:
    return [
        {
            "id": station.id,
            "name": station.name,
            "what": station.what,
            "route": station.route,
            "count": counts.get(station.id, 0),
            "note": notes.get(station.id, ""),
        }
        for station in STATIONS
    ]
