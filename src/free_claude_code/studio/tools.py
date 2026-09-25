"""The tools Studio agents can call, and the sandbox that executes them."""

import asyncio
import fnmatch
import re
import shutil
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import aiohttp
import httpx

from free_claude_code.application.web_tools.ports import (
    WebFetchEgressPolicy,
    WebFetchEgressViolation,
    WebToolsPort,
)
from free_claude_code.core.json_types import JsonObject

from .assistant_tools import calculate
from .commands import CommandBroker, CommandError
from .connectivity import Connectivity
from .llm import ToolCall, ToolSpec
from .memory import SHARED_MEMORY_ID, MemoryService
from .platforms import PlatformError, PlatformPage, PlatformReader, platform_of
from .polish import polish_notes
from .project_check import CHECKED_FILES, check_project
from .research import PLATFORMS, DeepResearch, ResearchMix
from .search import SearchError, StudioSearch
from .sites import SiteError, SiteWorkspace, is_starter
from .templates import template_files
from .videos import VideoStudy, at, clock, passages, render_note, studied

FINISH_TOOL = "finish"
COMMAND_TOOL = "run_command"
ASK_AGENT_TOOL = "ask_agent"
TEAM_TASK_TOOL = "team_task"
TODO_TOOL = "todo"
CONVERSATION_TOOL = "conversation"
LEARN_TOOL = "learn"
KNOWLEDGE_TOOL = "knowledge"
AGENT_MODEL_TOOL = "agent_model"
CALCULATE_TOOL = "calculate"
PROJECTS_TOOL = "list_projects"
SYSTEM_STATUS_TOOL = "system_status"
TEAM_STATUS_TOOL = "team_status"
STOP_AGENT_TOOL = "stop_agent"
DELEGATION_TOOLS = frozenset(
    {ASK_AGENT_TOOL, TEAM_TASK_TOOL, TEAM_STATUS_TOOL, STOP_AGENT_TOOL}
)
WEB_TOOLS: tuple[str, ...] = ("web_search", "web_fetch")
RESEARCH_TOOL = "research"
TEST_CODE_TOOL = "test_code"
ASK_RESEARCHER_TOOL = "ask_researcher"
ASK_HELPER_TOOL = "ask_helper"
APP_HELP_TOOL = "app_help"
CHECK_PROJECT_TOOL = "check_project"
STUDY_VIDEO_TOOL = "study_video"
START_PROJECT_TOOL = "start_project"
POLISH_TOOL = "polish_check"
RESTORE_FILE_TOOL = "restore_file"
VIDEO_NOTES_TOOL = "video_notes"
HELPER_ROLE = "helper"
MAX_SEARCH_MATCHES = 60
MAX_READ_LINES = 400
NETWORK_TOOLS = frozenset({*WEB_TOOLS, RESEARCH_TOOL, "study_video"})
# Look-ups that change nothing, so several asked for at once run together.
PARALLEL_TOOLS = frozenset(
    {
        *WEB_TOOLS,
        RESEARCH_TOOL,
        "read_file",
        "list_files",
        "search_files",
        "recall",
        ASK_RESEARCHER_TOOL,
        ASK_HELPER_TOOL,
        APP_HELP_TOOL,
        CHECK_PROJECT_TOOL,
        VIDEO_NOTES_TOOL,
        TEAM_STATUS_TOOL,
        CALCULATE_TOOL,
        PROJECTS_TOOL,
        SYSTEM_STATUS_TOOL,
        POLISH_TOOL,
        CONVERSATION_TOOL,
        KNOWLEDGE_TOOL,
    }
)
RESEARCHER_ROLE = "researcher"
TEST_LANGUAGES = {
    "python": "py",
    "py": "py",
    "javascript": "js",
    "js": "js",
    "node": "js",
    "html": "html",
    "css": "css",
}
MAIN_ROLE = "main"
OFFLINE_NOTE = (
    "The internet looks unreachable from this computer, so web tools are paused "
    "until it is back. Carry on with recall, the project files, and what you know."
)
MAX_FETCH_CHARS = 6_000
OVERVIEW_FILES = 40
MAX_SEARCH_RESULTS = 6

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="web_search",
        description="Search the web and return result titles and URLs.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."}
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="web_fetch",
        description="Fetch one web page and return its readable text.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute http(s) URL."}
            },
            "required": ["url"],
        },
    ),
    ToolSpec(
        name="write_file",
        description=(
            "Create or replace one file in the website workspace, "
            "for example index.html or styles.css."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Site-relative file path."},
                "content": {"type": "string", "description": "Complete file text."},
            },
            "required": ["path", "content"],
        },
    ),
    ToolSpec(
        name="read_file",
        description=(
            "Read one file in the project. Give start_line (and max_lines) to read "
            "a numbered section, which is what you need before edit_file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "description": "1-based line."},
                "max_lines": {"type": "integer"},
            },
            "required": ["path"],
        },
    ),
    ToolSpec(
        name="edit_file",
        description=(
            "Change part of a file without rewriting it: replace old_text, which "
            "must appear exactly once (copy it from read_file), with new_text. "
            "Set replace_all to change every occurrence. To make several changes "
            "to one file at once, pass edits: a list of {old_text, new_text}. "
            "Small indentation differences in old_text are tolerated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "replace_all": {"type": "boolean"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"},
                            "replace_all": {"type": "boolean"},
                        },
                        "required": ["old_text", "new_text"],
                    },
                },
            },
            "required": ["path"],
        },
    ),
    ToolSpec(
        name="search_files",
        description=(
            "Search the project's files for a regular expression and get "
            "path:line matches, like grep. Narrow it with glob, e.g. *.js."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "glob": {"type": "string"},
                "ignore_case": {"type": "boolean"},
            },
            "required": ["pattern"],
        },
    ),
    ToolSpec(
        name="list_files",
        description=(
            "List the files in the project. Give pattern, e.g. src/**/*.ts or "
            "*.css, to list only matching files."
        ),
        parameters={
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
        },
    ),
    ToolSpec(
        name="update_plan",
        description=(
            "Write down or update your step-by-step plan for this task, with each "
            "step pending, in_progress, or done. Keep one step in progress."
        ),
        parameters={
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done"],
                            },
                        },
                        "required": ["step"],
                    },
                }
            },
            "required": ["steps"],
        },
    ),
    ToolSpec(
        name="delete_file",
        description="Delete one file from the project workspace.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    ToolSpec(
        name=COMMAND_TOOL,
        description=(
            "Run one short, non-interactive shell command in the project folder: "
            "install packages, build, run tests or a script. It has a time limit, "
            "so never start servers or watchers that keep running."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "e.g. npm install, npm run build, python -m pytest",
                }
            },
            "required": ["command"],
        },
    ),
    ToolSpec(
        name=RESEARCH_TOOL,
        description=(
            "Research a question in depth from ten or more sources: at least 3 "
            "web pages, 2 on-topic Reddit threads, and 2 YouTube transcripts, plus "
            "Stack Overflow, GitHub, MDN, and dev.to for coding. Returns the "
            "useful parts, numbered with links to cite. For how-to, best "
            "practice, reviews, and errors. Set web, reddit, or youtube only when "
            "the user asks for a different number."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "What to find out."},
                "platforms": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(PLATFORMS)},
                    "description": "Optional: only these platforms.",
                },
                "web": {"type": "integer", "description": "Web pages (default 3)."},
                "reddit": {
                    "type": "integer",
                    "description": "Reddit threads (default 2; 0 for none).",
                },
                "youtube": {
                    "type": "integer",
                    "description": "YouTube videos (default 2; 0 for none).",
                },
            },
            "required": ["question"],
        },
    ),
    ToolSpec(
        name=CHECK_PROJECT_TOOL,
        description=(
            "Check the whole project for mistakes without running it: links, "
            "images, scripts, and stylesheets that point at missing files, "
            "#anchors with no matching id, unbalanced brackets in JavaScript and "
            "CSS, Python syntax errors, invalid JSON, and pages missing a title, "
            "a mobile viewport, or image alt text. Run it before you finish and "
            "fix what it reports."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name=STUDY_VIDEO_TOOL,
        description=(
            "Study a YouTube video: read its transcript and turn it into notes "
            "the team can use (summary, key points, steps, names, warnings), "
            "saved in video notes and in memory with its link. Use it when the "
            "user gives you a video, or a video matters for the task. Say what "
            "to focus on when only part of it matters."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The YouTube link."},
                "focus": {
                    "type": "string",
                    "description": "Optional: what the team wants from it.",
                },
            },
            "required": ["url"],
        },
    ),
    ToolSpec(
        name=VIDEO_NOTES_TOOL,
        description=(
            "Look at videos the team already studied. With a query, finds the "
            "matching videos and the exact transcript parts about it, each with "
            "a link to that moment. With an id (from memory or a list), reads "
            "that video's full notes. With neither, lists the latest videos."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for."},
                "id": {"type": "string", "description": "A video notes id."},
            },
        },
    ),
    ToolSpec(
        name=POLISH_TOOL,
        description=(
            "A designer's once-over of the web pages once they work: text "
            "contrast, phone layouts, hover and focus states, font sizes, a "
            "consistent color palette, content width, structure, smooth "
            "transitions, image sizes, and a favicon. Returns what would make "
            "the project look finished."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name=START_PROJECT_TOOL,
        description=(
            "Start a new project from a solid, mobile-first starter instead of a "
            "blank page, then change it to fit the job. Templates: website, "
            "landing, webapp (single-page app with saved state), game (canvas "
            "game loop with touch controls), python-tool, python-web (FastAPI), "
            "node-api. Existing work is never overwritten unless overwrite is set."
        ),
        parameters={
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "enum": [
                        "website",
                        "landing",
                        "webapp",
                        "game",
                        "python-tool",
                        "python-web",
                        "node-api",
                    ],
                },
                "title": {"type": "string", "description": "The project's name."},
                "overwrite": {"type": "boolean"},
            },
            "required": ["template", "title"],
        },
    ),
    ToolSpec(
        name=RESTORE_FILE_TOOL,
        description=(
            "Undo changes to a file: put back an earlier version (1 = the version "
            "before the last change). Every write, edit, and delete keeps the "
            "last ten versions. Without versions_back, lists the saved versions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "versions_back": {"type": "integer"},
            },
            "required": ["path"],
        },
    ),
    ToolSpec(
        name=CONVERSATION_TOOL,
        description=(
            "Every message of this conversation and your earlier ones is kept "
            "word for word. Search it with query (scope all to include earlier "
            "conversations), or read messages by number with from and to (for "
            "example the ones around a search hit). Use it whenever you need "
            "an exact detail from earlier or the user mentions something you "
            "cannot see."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to look for."},
                "from": {"type": "integer", "description": "First message number."},
                "to": {"type": "integer", "description": "Last message number."},
                "scope": {"type": "string", "enum": ["this", "all"]},
            },
        },
    ),
    ToolSpec(
        name=LEARN_TOOL,
        description=(
            "Teach yourself a subject in the background: plan a course, research "
            "each lesson on the web, Reddit, and YouTube, write lesson notes, "
            "quiz yourself, and keep it all in memory and the knowledge library. "
            "A progress bar fills on the HUD. depth: quick (4 lessons), normal "
            "(7), or deep (10). Use it when the user wants you to learn something."
        ),
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What to learn."},
                "focus": {
                    "type": "string",
                    "description": "Optional: the angle that matters.",
                },
                "depth": {"type": "string", "enum": ["quick", "normal", "deep"]},
            },
            "required": ["topic"],
        },
    ),
    ToolSpec(
        name=AGENT_MODEL_TOOL,
        description=(
            "Team brains: see which AI model each agent thinks with, or give one "
            "agent a different model. With no agent, lists every agent's model "
            "and the models on this PC. With agent and model, switches that "
            "agent (a short name such as 'qwen coder' is enough). Use it when "
            "the user wants agents on different models."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "Agent name, or 'yourself'.",
                },
                "model": {
                    "type": "string",
                    "description": "The model to switch to.",
                },
            },
        },
    ),
    ToolSpec(
        name=KNOWLEDGE_TOOL,
        description=(
            "The knowledge library of subjects the team taught itself: search "
            "lessons with query, or read a full lesson (notes, formulas, steps, "
            "self-check, sources) or a study guide by id. Use it before answering "
            "or building from something that was learned."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "id": {"type": "string", "description": "A lesson or study id."},
            },
        },
    ),
    ToolSpec(
        name=CALCULATE_TOOL,
        description=(
            "Work out arithmetic exactly instead of in your head: + - * / // % "
            "** and brackets, '15% of 80', sqrt, round, min, max, log, pi."
        ),
        parameters={
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    ),
    ToolSpec(
        name=TODO_TOOL,
        description=(
            "The user's to-do list and reminders. action add (text, and due for "
            "a reminder such as 'in 20 minutes', 'tomorrow 9am', 'at 17:30'), "
            "list, done (id), or remove (id). Due reminders are announced on the "
            "HUD."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list", "done", "remove"]},
                "text": {"type": "string"},
                "due": {"type": "string"},
                "id": {"type": "string"},
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=PROJECTS_TOOL,
        description=(
            "List the user's projects (websites and apps the team built) with "
            "their file counts, when they last changed, and preview links. Add a "
            "query to find one."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    ),
    ToolSpec(
        name=SYSTEM_STATUS_TOOL,
        description=(
            "How this PC is doing: CPU, memory, and disk use, whether LM Studio "
            "is running and which models it serves, the internet connection, "
            "and the voice."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name=TEST_CODE_TOOL,
        description=(
            "Try out a code snippet before relying on it: saves it in the "
            "project's lab folder and runs it (python or javascript), returning "
            "the output and exit code. HTML and CSS are saved for preview."
        ),
        parameters={
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "html", "css"],
                },
                "code": {"type": "string"},
            },
            "required": ["language", "code"],
        },
    ),
    ToolSpec(
        name=ASK_HELPER_TOOL,
        description=(
            "Ask the team's Helper to think with you: it filters material (like "
            "research findings or an error log) against your task, brainstorms "
            "ways to succeed, and returns concrete next steps."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "What you are trying to do and where you are stuck.",
                },
                "material": {
                    "type": "string",
                    "description": "Optional findings, logs, or notes to work from.",
                },
            },
            "required": ["request"],
        },
    ),
    ToolSpec(
        name=ASK_RESEARCHER_TOOL,
        description=(
            "Ask the team's Researcher to look something up and report back, "
            "for example how to fix an error you are stuck on. Include the "
            "exact error, what you tried, and your stack."
        ),
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    ),
    ToolSpec(
        name="remember",
        description="Save one durable fact into your own memory.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["text"],
        },
    ),
    ToolSpec(
        name=ASK_AGENT_TOOL,
        description=(
            "Hand one task to another agent on your team and wait for its report. "
            "Use it for work that needs that agent's tools or model, like "
            "researching or building a website or app."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "The agent's name."},
                "task": {
                    "type": "string",
                    "description": "Everything the agent needs to do the task.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional project to work in, by name; a new one is "
                        "created when no project has that name."
                    ),
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "True to let the agent work in the background and "
                        "report when done, instead of waiting for it."
                    ),
                },
            },
            "required": ["agent", "task"],
        },
    ),
    ToolSpec(
        name=TEAM_STATUS_TOOL,
        description=(
            "See what every agent is doing right now and what it last finished, "
            "with results, plus commands waiting for the user. Use it before "
            "answering questions about progress, and to follow up on work."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name=STOP_AGENT_TOOL,
        description="Stop an agent's background work when the user asks you to.",
        parameters={
            "type": "object",
            "properties": {"agent": {"type": "string", "description": "Agent name."}},
            "required": ["agent"],
        },
    ),
    ToolSpec(
        name=TEAM_TASK_TOOL,
        description=(
            "Put several agents in a room to work on one goal together, handing "
            "parts to each other, and wait for their result."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Agent names; the first one leads.",
                },
                "goal": {"type": "string"},
                "project": {
                    "type": "string",
                    "description": "Optional project to work in, by name.",
                },
            },
            "required": ["agents", "goal"],
        },
    ),
    ToolSpec(
        name="recall",
        description="Search your own memory for something you learned before.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    ToolSpec(
        name=APP_HELP_TOOL,
        description=(
            "Look up how FCC Studio works: which page and button does something, "
            "how to set it up, and what is wrong with this install right now. Use "
            "it when the user asks how to do something in the app or why "
            "something is not working."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The user's question about the app.",
                }
            },
            "required": ["question"],
        },
    ),
    ToolSpec(
        name=FINISH_TOOL,
        description="Finish the task and report the result to the user.",
        parameters={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    ),
)

TOOL_SPEC_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}
DEFAULT_TOOL_NAMES: tuple[str, ...] = tuple(
    spec.name
    for spec in TOOL_SPECS
    if spec.name not in DELEGATION_TOOLS
    and spec.name
    not in {
        APP_HELP_TOOL,
        TODO_TOOL,
        PROJECTS_TOOL,
        SYSTEM_STATUS_TOOL,
        LEARN_TOOL,
        AGENT_MODEL_TOOL,
    }
)
MAIN_TOOL_NAMES: tuple[str, ...] = (
    ASK_AGENT_TOOL,
    TEAM_TASK_TOOL,
    TEAM_STATUS_TOOL,
    STOP_AGENT_TOOL,
    RESEARCH_TOOL,
    ASK_HELPER_TOOL,
    "web_search",
    "web_fetch",
    "remember",
    "recall",
    CONVERSATION_TOOL,
    LEARN_TOOL,
    KNOWLEDGE_TOOL,
    AGENT_MODEL_TOOL,
    STUDY_VIDEO_TOOL,
    VIDEO_NOTES_TOOL,
    TODO_TOOL,
    CALCULATE_TOOL,
    PROJECTS_TOOL,
    SYSTEM_STATUS_TOOL,
    APP_HELP_TOOL,
    FINISH_TOOL,
)
SHARED_REMEMBER_SPEC = ToolSpec(
    name="remember",
    description=(
        "Save one durable fact into the team's shared memory, where every agent "
        "can recall it. Set private to true to keep it to yourself."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "private": {"type": "boolean"},
        },
        "required": ["text"],
    },
)
SHARED_RECALL_SPEC = ToolSpec(
    name="recall",
    description="Search your own memory and the team's shared memory.",
    parameters=TOOL_SPEC_BY_NAME["recall"].parameters,
)


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything one tool call is allowed to touch."""

    agent_id: str
    chat_id: str
    site_id: str | None = None
    agent_name: str = "Agent"
    agent_role: str = "assistant"


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """The rendered result of one tool call plus structured transcript data."""

    text: str
    data: JsonObject
    failed: bool = False


class TeamDelegate(Protocol):
    """Lets the main agent hand work to the rest of the team."""

    async def ask_agent(
        self,
        context: ToolContext,
        *,
        agent: str,
        task: str,
        project: str,
        background: bool = False,
    ) -> ToolOutcome:
        """Run one task on another agent and report its result."""
        ...

    async def consult(self, context: ToolContext, *, question: str) -> ToolOutcome:
        """Ask the team's Researcher a question and wait for its answer."""
        ...

    async def status(self, context: ToolContext) -> ToolOutcome:
        """Report what the team is doing."""
        ...

    async def stop(self, context: ToolContext, *, agent: str) -> ToolOutcome:
        """Stop an agent's background work."""
        ...

    async def help(
        self, context: ToolContext, *, request: str, material: str
    ) -> ToolOutcome:
        """Ask the team's Helper to turn material into a plan for a task."""
        ...

    async def team_task(
        self,
        context: ToolContext,
        *,
        agents: Sequence[str],
        goal: str,
        project: str,
    ) -> ToolOutcome:
        """Run one goal with several agents in a room and report the result."""
        ...


def tool_specs(
    names: Sequence[str],
    *,
    commands_enabled: bool = False,
    shared_memory: bool = False,
    delegation: bool = False,
) -> tuple[ToolSpec, ...]:
    """Return the specs for named tools, always including ``finish``."""
    chosen: list[ToolSpec] = []
    for name in names:
        spec = TOOL_SPEC_BY_NAME.get(name)
        if spec is None:
            continue
        if name == COMMAND_TOOL and not commands_enabled:
            continue
        if name in DELEGATION_TOOLS and not delegation:
            continue
        if shared_memory and name == "remember":
            spec = SHARED_REMEMBER_SPEC
        elif shared_memory and name == "recall":
            spec = SHARED_RECALL_SPEC
        chosen.append(spec)
    if all(spec.name != FINISH_TOOL for spec in chosen):
        chosen.append(TOOL_SPEC_BY_NAME[FINISH_TOOL])
    return tuple(chosen)


class AgentToolbox:
    """Execute agent tool calls against the web, a site, and agent memory."""

    def __init__(
        self,
        *,
        web_tools: WebToolsPort,
        sites: SiteWorkspace,
        memory: MemoryService,
        egress: WebFetchEgressPolicy,
        commands: CommandBroker | None = None,
        command_policy: str = "off",
        command_timeout: float = 120.0,
        delegate: TeamDelegate | None = None,
        searcher: StudioSearch | None = None,
        web_access: str = "all",
        reader: PlatformReader | None = None,
        research_sources: int = 10,
        research_mix: ResearchMix | None = None,
        connectivity: Connectivity | None = None,
        app_help: Callable[[str], Awaitable[str]] | None = None,
        videos: VideoStudy | None = None,
        study_later: Callable[[PlatformPage], None] | None = None,
        assistant: Callable[[ToolCall, ToolContext], Awaitable[ToolOutcome]]
        | None = None,
    ) -> None:
        self._web = web_tools
        self._sites = sites
        self._memory = memory
        self._egress = egress
        self._commands = commands
        self._command_policy = command_policy
        self._command_timeout = command_timeout
        self._delegate = delegate
        self._searcher = searcher
        self._web_access = web_access
        self._reader = reader or PlatformReader()
        self._research_sources = research_sources
        self._research_mix = research_mix or ResearchMix()
        self._connectivity = connectivity
        self._app_help = app_help
        self._videos = videos
        self._study_later = study_later
        self._assistant = assistant

    @property
    def commands_enabled(self) -> bool:
        return self._commands is not None and self._command_policy in {"ask", "auto"}

    @property
    def shared_memory(self) -> bool:
        return self._memory.shared_enabled

    @property
    def web_enabled(self) -> bool:
        return self._web_access != "off"

    @property
    def online(self) -> bool:
        """Whether this computer could reach the internet at the last check."""
        return self._connectivity is None or self._connectivity.online

    async def check_online(self) -> bool:
        """Refresh the internet check (cached) before an agent's turn."""
        if self._connectivity is None:
            return True
        return await self._connectivity.check()

    def web_paused(self, names: Sequence[str], *, role: str) -> bool:
        """True when the agent would have web tools but the internet is down."""
        if self.online or not self.web_enabled:
            return False
        return (self._web_access == "all" and role != "guide") or any(
            name in NETWORK_TOOLS for name in names
        )

    def tool_names(self, names: Sequence[str], *, role: str) -> tuple[str, ...]:
        """Apply web access and the internet connection to an agent's tools.

        Web tools are offered whenever the setting allows them and the
        computer is online, and left out while it is offline.
        """
        reachable = self.web_enabled and self.online
        chosen = [name for name in names if reachable or name not in NETWORK_TOOLS]
        if reachable and self._web_access == "all" and role != "guide":
            chosen.extend(name for name in WEB_TOOLS if name not in chosen)
        return tuple(chosen)

    def delegation_allowed(self, role: str) -> bool:
        """Only the main agent may hand work to other agents."""
        return self._delegate is not None and role == MAIN_ROLE

    async def run(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        """Execute one tool call, converting every failure into tool output."""
        if call.name in NETWORK_TOOLS and not self.web_enabled:
            return ToolOutcome(
                text="Web access is off in Studio settings.",
                data={"tool": call.name},
                failed=True,
            )
        try:
            match call.name:
                case "web_search":
                    return await self._web_search(call)
                case "web_fetch":
                    return await self._web_fetch(call)
                case "write_file":
                    return await self._write_file(call, context)
                case "read_file":
                    return await self._read_file(call, context)
                case "edit_file":
                    return await self._edit_file(call, context)
                case "search_files":
                    return await self._search_files(call, context)
                case "list_files":
                    return await self._list_files(call, context)
                case "update_plan":
                    return await self._update_plan(call, context)
                case "ask_helper":
                    return await self._ask_helper(call, context)
                case "delete_file":
                    return await self._delete_file(call, context)
                case "run_command":
                    return await self._run_command(call, context)
                case "remember":
                    return await self._remember(call, context)
                case "recall":
                    return await self._recall(call, context)
                case "ask_agent" | "team_task" | "team_status" | "stop_agent":
                    return await self._delegate_call(call, context)
                case "research":
                    return await self._research(call)
                case "test_code":
                    return await self._test_code(call, context)
                case "ask_researcher":
                    return await self._consult(call, context)
                case "app_help":
                    return await self._app_help_call(call)
                case "check_project":
                    return await self._check_project(context)
                case "polish_check":
                    return await self._polish_check(context)
                case "start_project":
                    return await self._start_project(call, context)
                case "restore_file":
                    return await self._restore_file(call, context)
                case "calculate":
                    return self._calculate(call)
                case (
                    "todo"
                    | "list_projects"
                    | "system_status"
                    | "conversation"
                    | "learn"
                    | "knowledge"
                    | "agent_model"
                ):
                    if self._assistant is None:
                        raise ValueError(f"{call.name} is not available here.")
                    return await self._assistant(call, context)
                case "study_video":
                    return await self._study_video(call, context)
                case "video_notes":
                    return await self._video_notes(call)
                case _:
                    return ToolOutcome(
                        text=f"Unknown tool '{call.name}'.",
                        data={"tool": call.name},
                        failed=True,
                    )
        except (
            SiteError,
            WebFetchEgressViolation,
            CommandError,
            SearchError,
            PlatformError,
            httpx.HTTPError,
            aiohttp.ClientError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            text = f"{call.name} failed: {error}"
            if call.name in NETWORK_TOOLS and _connection_lost(error):
                if self._connectivity is not None:
                    self._connectivity.mark_offline(str(error))
                text += f" {OFFLINE_NOTE}"
            return ToolOutcome(
                text=text,
                data={"tool": call.name, "error": str(error)},
                failed=True,
            )

    async def _web_search(self, call: ToolCall) -> ToolOutcome:
        query = str(call.arguments.get("query", "")).strip()
        if not query:
            raise ValueError("A search query is required.")
        if self._searcher is not None:
            report = await self._searcher.search(query, limit=MAX_SEARCH_RESULTS)
            provider, note = report.provider, report.note
            hits = [(hit.title, hit.url, hit.snippet) for hit in report.hits]
        else:
            results = (await self._web.search(query))[:MAX_SEARCH_RESULTS]
            provider, note = "web", ""
            hits = [(result.title, result.url, "") for result in results]
        data: JsonObject = {
            "tool": "web_search",
            "query": query,
            "provider": provider,
            "results": [{"title": title, "url": url} for title, url, _ in hits],
        }
        if note:
            data["note"] = note
        if not hits:
            text = f"No results for {query!r}."
            if note:
                text += f" {note}"
            return ToolOutcome(text=f"{text} Try a shorter query.", data=data)
        lines: list[str] = [f"Note: {note}"] if note else []
        for index, (title, url, snippet) in enumerate(hits, start=1):
            lines.append(f"{index}. {title} — {url}")
            if snippet:
                lines.append(f"   {snippet}")
        lines.append("Read a page in full with web_fetch.")
        return ToolOutcome(text="\n".join(lines), data=data)

    async def _web_fetch(self, call: ToolCall) -> ToolOutcome:
        url = str(call.arguments.get("url", "")).strip()
        if not url:
            raise ValueError("A URL is required.")
        if platform_of(url) != "web":
            page = await self._reader.read(url)
            if page.transcript and self._study_later is not None:
                self._study_later(page)
            body = page.text[:MAX_FETCH_CHARS]
            note = f"\n\n({page.note})" if page.note else ""
            return ToolOutcome(
                text=f"{page.title}\n{page.url}\n\n{body}{note}",
                data={
                    "tool": "web_fetch",
                    "url": page.url,
                    "title": page.title,
                    "platform": page.platform,
                    "chars": len(body),
                },
            )
        result = await self._web.fetch(url, egress=self._egress)
        body = result.data[:MAX_FETCH_CHARS]
        return ToolOutcome(
            text=f"{result.title}\n{result.url}\n\n{body}",
            data={
                "tool": "web_fetch",
                "url": result.url,
                "title": result.title,
                "chars": len(body),
            },
        )

    async def _write_file(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        path = str(call.arguments.get("path", ""))
        content = call.arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("File content must be text.")
        written = await self._sites.write(site_id, path, content)
        return ToolOutcome(
            text=f"Wrote {written.path} ({written.size} bytes).",
            data={
                "tool": "write_file",
                "site_id": site_id,
                "path": written.path,
                "size": written.size,
            },
        )

    async def _read_file(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        path = str(call.arguments.get("path", ""))
        content = await self._sites.read(site_id, path)
        start = _int_arg(call.arguments.get("start_line"))
        limit = _int_arg(call.arguments.get("max_lines"))
        data: JsonObject = {"tool": "read_file", "site_id": site_id, "path": path}
        if start is None and limit is None:
            text = content[:MAX_FETCH_CHARS]
            if len(content) > MAX_FETCH_CHARS:
                text += "\n[... cut; read further with start_line]"
            return ToolOutcome(text=text, data=data)
        lines = content.splitlines()
        first = max(1, start or 1)
        count = max(1, min(MAX_READ_LINES, limit or MAX_READ_LINES))
        shown = lines[first - 1 : first - 1 + count]
        numbered = "\n".join(
            f"{number:>5}  {line}" for number, line in enumerate(shown, start=first)
        )
        last = first + len(shown) - 1
        header = f"{path}: lines {first}-{last} of {len(lines)}"
        return ToolOutcome(
            text=f"{header}\n{numbered}"[: MAX_FETCH_CHARS * 2],
            data={**data, "start_line": first, "end_line": last},
        )

    async def _edit_file(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        path = str(call.arguments.get("path", ""))
        raw = call.arguments.get("edits")
        edits = (
            [item for item in raw if isinstance(item, dict)]
            if isinstance(raw, list) and raw
            else [call.arguments]
        )
        content = await self._sites.read(site_id, path)
        changed = 0
        loose = 0
        for number, edit in enumerate(edits, start=1):
            label = f"Edit {number}: " if len(edits) > 1 else ""
            old = edit.get("old_text")
            new = edit.get("new_text")
            if not isinstance(old, str) or not old:
                raise ValueError(f"{label}give old_text: the exact text to replace.")
            if not isinstance(new, str):
                raise ValueError(f"{label}give new_text: what to put in its place.")
            found = content.count(old)
            replace_all = edit.get("replace_all") is True
            if found == 0:
                fixed = loose_replace(content, old, new)
                if fixed is None:
                    raise ValueError(
                        f"{label}old_text was not found in {path}. Read the file "
                        "again and copy the text exactly. No edits were saved."
                    )
                content = fixed
                changed += 1
                loose += 1
                continue
            if found > 1 and not replace_all:
                raise ValueError(
                    f"{label}old_text appears {found} times in {path}. Include more "
                    "surrounding lines so it is unique, or set replace_all. No "
                    "edits were saved."
                )
            content = (
                content.replace(old, new)
                if replace_all
                else content.replace(old, new, 1)
            )
            changed += found if replace_all else 1
        written = await self._sites.write(site_id, path, content)
        note = f" ({loose} matched after adjusting indentation)" if loose else ""
        return ToolOutcome(
            text=f"Edited {written.path}: replaced {changed} occurrence(s){note}.",
            data={
                "tool": "edit_file",
                "site_id": site_id,
                "path": written.path,
                "replacements": changed,
                "edits": len(edits),
            },
        )

    async def _node_syntax(
        self,
        node: str,
        site_id: str,
        contents: dict[str, str],
        problems: list[str],
    ) -> list[str]:
        """Let Node parse each script (without running it): its verdict replaces
        the bracket guess for that file."""
        for path in contents:
            if not path.endswith((".js", ".mjs", ".cjs")):
                continue
            verdict = await _node_check(node, self._sites.resolve(site_id, path))
            if verdict is None:
                continue
            guesses = (f"{path}: unexpected '", f"{path}: '")
            problems = [p for p in problems if not p.startswith(guesses)]
            if verdict:
                problems.append(f"{path}: {verdict}")
        return problems

    async def _start_project(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        template = str(call.arguments.get("template", "")).strip()
        title = str(call.arguments.get("title") or "My project").strip()[:80]
        overwrite = call.arguments.get("overwrite") is True
        files = template_files(template, title)
        existing = {item.path for item in await self._sites.files(site_id)}
        written: list[str] = []
        kept: list[str] = []
        for path, text in files.items():
            if path in existing and not overwrite:
                current = await self._sites.read(site_id, path)
                if not is_starter(path, current):
                    kept.append(path)
                    continue
            await self._sites.write(site_id, path, text)
            written.append(path)
        lines = [
            f"Started a {template} project: wrote {', '.join(written) or 'nothing'}."
        ]
        if kept:
            lines.append(
                f"Kept your existing {', '.join(kept)} (set overwrite to replace them)."
            )
        lines.append(
            "Now read the files, change them to fit the task, and run check_project."
        )
        return ToolOutcome(
            text=" ".join(lines),
            data={
                "tool": START_PROJECT_TOOL,
                "site_id": site_id,
                "template": template,
                "written": written,
                "kept": kept,
            },
        )

    async def _restore_file(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        path = str(call.arguments.get("path", "")).strip()
        back = _int_arg(call.arguments.get("versions_back"))
        saved = await self._sites.versions(site_id, path)
        if back is None:
            if not saved:
                text = f"{path} has no earlier versions."
            else:
                now = time.time()
                text = f"{path} has {len(saved)} earlier version(s): " + ", ".join(
                    f"{index} ({max(0, round((now - stamp / 1_000_000) / 60))} min ago)"
                    for index, stamp in enumerate(saved, start=1)
                )
            return ToolOutcome(
                text=text,
                data={"tool": RESTORE_FILE_TOOL, "path": path, "versions": len(saved)},
            )
        restored = await self._sites.restore(site_id, path, back=back)
        return ToolOutcome(
            text=(
                f"Restored {restored.path} to the version from {back} change(s) ago. "
                "The version it replaced is kept, so this can be undone too."
            ),
            data={
                "tool": RESTORE_FILE_TOOL,
                "site_id": site_id,
                "path": restored.path,
                "versions_back": back,
            },
        )

    async def _search_files(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        raw = str(call.arguments.get("pattern", ""))
        if not raw:
            raise ValueError("Give a pattern to search for.")
        flags = re.IGNORECASE if call.arguments.get("ignore_case") is True else 0
        try:
            pattern = re.compile(raw, flags)
        except re.error as error:
            raise ValueError(
                f"That pattern is not a valid regular expression: {error}"
            ) from error
        glob = str(call.arguments.get("glob") or "").strip()
        matches: list[str] = []
        searched = 0
        for item in await self._sites.files(site_id):
            if glob and not _glob_match(item.path, glob):
                continue
            if not _is_text(item.content_type):
                continue
            try:
                content = await self._sites.read(site_id, item.path)
            except SiteError:
                continue
            searched += 1
            for number, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{item.path}:{number}: {line.strip()[:200]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        break
            if len(matches) >= MAX_SEARCH_MATCHES:
                break
        text = "\n".join(matches) or f"No matches in {searched} file(s)."
        if len(matches) >= MAX_SEARCH_MATCHES:
            text += "\n[more matches not shown; narrow the pattern or glob]"
        return ToolOutcome(
            text=text,
            data={"tool": "search_files", "matches": len(matches), "files": searched},
        )

    async def _list_files(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        pattern = str(call.arguments.get("pattern") or "").strip()
        files = [
            item
            for item in await self._sites.files(site_id)
            if not pattern or _glob_match(item.path, pattern)
        ]
        listing = "\n".join(f"{item.path} ({item.size} bytes)" for item in files)
        empty = f"No files match {pattern}." if pattern else "The site is empty."
        return ToolOutcome(
            text=listing or empty,
            data={
                "tool": "list_files",
                "site_id": site_id,
                "files": [item.path for item in files],
            },
        )

    async def _update_plan(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        raw = call.arguments.get("steps")
        if not isinstance(raw, list) or not raw:
            raise ValueError("Give the plan as a list of steps.")
        marks = {"done": "[x]", "in_progress": "[>]", "pending": "[ ]"}
        lines: list[str] = []
        for item in raw[:20]:
            if isinstance(item, dict):
                step = str(item.get("step", "")).strip()
                status = str(item.get("status") or "pending")
            else:
                step, status = str(item).strip(), "pending"
            if step:
                lines.append(f"{marks.get(status, '[ ]')} {step}")
        if not lines:
            raise ValueError("The plan has no steps.")
        plan = "\n".join(lines)
        await self._memory.replace_plan(context.agent_id, plan, chat_id=context.chat_id)
        done = sum(1 for line in lines if line.startswith("[x]"))
        return ToolOutcome(
            text=f"Plan ({done}/{len(lines)} done):\n{plan}",
            data={"tool": "update_plan", "steps": len(lines), "done": done},
        )

    async def _ask_helper(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        if self._delegate is None:
            raise ValueError("There is no team to ask.")
        if context.agent_role == HELPER_ROLE:
            raise ValueError("You are the helper; think it through yourself.")
        request = str(call.arguments.get("request", "")).strip()
        if not request:
            raise ValueError("Say what you need help with.")
        material = str(call.arguments.get("material") or "").strip()
        return await self._delegate.help(context, request=request, material=material)

    @staticmethod
    def _calculate(call: ToolCall) -> ToolOutcome:
        expression = str(call.arguments.get("expression", "")).strip()
        if not expression:
            raise ValueError("Give the expression to work out.")
        result = calculate(expression)
        shown = f"{result:,.10g}" if isinstance(result, float) else f"{result:,}"
        return ToolOutcome(
            text=f"{expression} = {shown}",
            data={"tool": CALCULATE_TOOL, "expression": expression, "result": result},
        )

    async def _study_video(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        if self._videos is None:
            raise ValueError("Video notes are not available here.")
        url = str(call.arguments.get("url", "")).strip()
        focus = str(call.arguments.get("focus") or "").strip()
        note = await self._videos.study(
            url, focus=focus, source="agent", studied_by=context.agent_name
        )
        return ToolOutcome(
            text=render_note(note),
            data={
                "tool": STUDY_VIDEO_TOOL,
                "video": note.id,
                "url": note.url,
                "title": note.title,
            },
        )

    async def _video_notes(self, call: ToolCall) -> ToolOutcome:
        if self._videos is None:
            raise ValueError("Video notes are not available here.")
        query = str(call.arguments.get("query") or "").strip()
        wanted = str(call.arguments.get("id") or "").strip()
        if wanted:
            note = await self._videos.note(wanted)
            if note is None:
                raise ValueError(f"No video notes with id {wanted}.")
            found = [note]
        else:
            found = await self._videos.notes(query)
        if not found or not (wanted or query):
            return ToolOutcome(
                text=studied(found),
                data={"tool": VIDEO_NOTES_TOOL, "videos": [n.id for n in found]},
            )
        best = found[0]
        parts = [render_note(best)]
        if query:
            moments = passages(best, query)
            if moments:
                parts.append(f"Transcript parts about '{query}':")
                parts.extend(
                    f"[{clock(start)}] {at(best.url, start)}\n{text}"
                    for start, text in moments
                )
        if len(found) > 1:
            parts.append("Other videos that match:\n" + studied(found[1:]))
        return ToolOutcome(
            text="\n\n".join(parts),
            data={"tool": VIDEO_NOTES_TOOL, "videos": [n.id for n in found]},
        )

    async def project_overview(self, site_id: str) -> str:
        """What is already in a project, so an agent starts with the lay of the land."""
        try:
            files = [
                item
                for item in await self._sites.files(site_id)
                if not item.path.startswith("lab/")
            ]
        except SiteError:
            return ""
        if not files:
            return "The project is empty: start it with start_project or write_file."
        paths = {item.path for item in files}
        if paths <= {"index.html", "styles.css", "app.js"}:
            placeholders = True
            for path in paths:
                if not is_starter(path, await self._sites.read(site_id, path)):
                    placeholders = False
                    break
            if placeholders:
                return (
                    "The project only has placeholder files: start it with "
                    "start_project (it may replace them) or write_file."
                )
        shown = files[:OVERVIEW_FILES]
        lines = [f"Files already in the project ({len(files)}):"]
        lines += [f"- {item.path} ({item.size} bytes)" for item in shown]
        if len(files) > len(shown):
            lines.append(f"- … and {len(files) - len(shown)} more (list_files)")
        readme = next(
            (item.path for item in files if item.path.lower() == "readme.md"), None
        )
        if readme:
            try:
                text = await self._sites.read(site_id, readme)
            except SiteError:
                text = ""
            if text.strip():
                lines.append(f"README.md starts:\n{text.strip()[:500]}")
        lines.append(
            "Read the files you will change before changing them; build on what "
            "is here instead of starting over."
        )
        return "\n".join(lines)

    async def _project_texts(
        self, site_id: str, suffixes: tuple[str, ...]
    ) -> dict[str, str]:
        contents: dict[str, str] = {}
        for item in await self._sites.files(site_id):
            if item.path.startswith("lab/") or not item.path.endswith(suffixes):
                continue
            try:
                contents[item.path] = await self._sites.read(site_id, item.path)
            except SiteError, UnicodeDecodeError:
                continue
        return contents

    async def _polish_check(self, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        contents = await self._project_texts(site_id, (".html", ".htm", ".css"))
        notes = polish_notes(contents)
        if not contents:
            text = "There are no web pages to polish in this project."
        elif notes:
            text = f"{len(notes)} polish suggestion(s):\n" + "\n".join(
                f"- {note}" for note in notes
            )
        else:
            text = "The pages look finished: nothing to polish."
        return ToolOutcome(
            text=text, data={"tool": POLISH_TOOL, "site_id": site_id, "notes": notes}
        )

    async def _check_project(self, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        contents: dict[str, str] = {}
        for item in await self._sites.files(site_id):
            if item.path.startswith("lab/") or not item.path.endswith(CHECKED_FILES):
                continue
            try:
                contents[item.path] = await self._sites.read(site_id, item.path)
            except SiteError, UnicodeDecodeError:
                continue
        problems = check_project(contents)
        node = shutil.which("node")
        if node:
            problems = await self._node_syntax(node, site_id, contents, problems)
        text = (
            f"Checked {len(contents)} files; found {len(problems)} problem(s):\n"
            + "\n".join(f"- {problem}" for problem in problems)
            if problems
            else f"Checked {len(contents)} files; found no problems."
        )
        return ToolOutcome(
            text=text,
            data={
                "tool": CHECK_PROJECT_TOOL,
                "site_id": site_id,
                "checked": len(contents),
                "problems": problems,
            },
        )

    async def _app_help_call(self, call: ToolCall) -> ToolOutcome:
        if self._app_help is None:
            raise ValueError("App help is not available here.")
        question = str(call.arguments.get("question", "")).strip()
        if not question:
            raise ValueError("Say what the user asked about the app.")
        return ToolOutcome(
            text=await self._app_help(question),
            data={"tool": APP_HELP_TOOL, "question": question},
        )

    async def _delete_file(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        path = str(call.arguments.get("path", ""))
        deleted = await self._sites.delete(site_id, path)
        return ToolOutcome(
            text=f"Deleted {path}." if deleted else f"{path} did not exist.",
            data={"tool": "delete_file", "site_id": site_id, "path": path},
        )

    async def _run_command(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        if not self.commands_enabled or self._commands is None:
            raise CommandError("Running commands is turned off in Studio settings.")
        result = await self._commands.request(
            agent_id=context.agent_id,
            agent_name=context.agent_name,
            chat_id=context.chat_id,
            site_id=site_id,
            command=str(call.arguments.get("command", "")),
            cwd=self._sites.directory(site_id),
            policy=self._command_policy,
            timeout=self._command_timeout,
        )
        request = result.request
        return ToolOutcome(
            text=result.text,
            data={
                "tool": COMMAND_TOOL,
                "request_id": request.id,
                "status": request.status,
                "exit_code": request.exit_code,
            },
            failed=request.status != "ran" or (request.exit_code or 0) != 0,
        )

    async def _remember(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        text = str(call.arguments.get("text", ""))
        raw_tags = call.arguments.get("tags")
        tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []
        private = call.arguments.get("private") is True
        shared = self._memory.shared_enabled and not private
        if shared:
            entry = await self._memory.share(
                text,
                author=context.agent_name,
                tags=tags,
                source="tool",
                chat_id=context.chat_id,
            )
        else:
            entry = await self._memory.remember(
                context.agent_id,
                text,
                tags=tags,
                source="tool",
                chat_id=context.chat_id,
            )
        if entry is None:
            raise ValueError("Nothing to remember.")
        where = "team memory" if shared else "your memory"
        return ToolOutcome(
            text=f"Saved to {where}: {entry.text}",
            data={"tool": "remember", "memory_id": entry.id, "shared": shared},
        )

    async def _recall(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        query = str(call.arguments.get("query", ""))
        entries = await self._memory.recall(context.agent_id, query)
        if not entries:
            return ToolOutcome(
                text="Nothing relevant in memory.",
                data={"tool": "recall", "query": query, "hits": 0},
            )
        return ToolOutcome(
            text="\n".join(
                f"- {'(team) ' if entry.agent_id == SHARED_MEMORY_ID else ''}"
                f"{entry.text}"
                for entry in entries
            ),
            data={"tool": "recall", "query": query, "hits": len(entries)},
        )

    async def _delegate_call(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        if self._delegate is None or not self.delegation_allowed(context.agent_role):
            raise ValueError("Only the main agent can hand work to other agents.")
        project = str(call.arguments.get("project") or "").strip()
        if call.name == TEAM_STATUS_TOOL:
            return await self._delegate.status(context)
        if call.name == STOP_AGENT_TOOL:
            agent = str(call.arguments.get("agent", "")).strip()
            if not agent:
                raise ValueError("Say which agent to stop.")
            return await self._delegate.stop(context, agent=agent)
        if call.name == ASK_AGENT_TOOL:
            agent = str(call.arguments.get("agent", "")).strip()
            task = str(call.arguments.get("task", "")).strip()
            if not agent or not task:
                raise ValueError("Say which agent and what the task is.")
            return await self._delegate.ask_agent(
                context,
                agent=agent,
                task=task,
                project=project,
                background=call.arguments.get("background") is True,
            )
        raw_agents = call.arguments.get("agents")
        if isinstance(raw_agents, str):
            raw_agents = [part for part in raw_agents.split(",") if part.strip()]
        agents = (
            [str(item).strip() for item in raw_agents if str(item).strip()]
            if isinstance(raw_agents, list)
            else []
        )
        goal = str(call.arguments.get("goal", "")).strip()
        if not agents or not goal:
            raise ValueError("Name the agents and the goal.")
        return await self._delegate.team_task(
            context, agents=agents, goal=goal, project=project
        )

    async def _research(self, call: ToolCall) -> ToolOutcome:
        if self._searcher is None:
            raise ValueError("Web search is not set up.")
        question = str(call.arguments.get("question", "")).strip()
        raw = call.arguments.get("platforms")
        platforms = [str(item) for item in raw] if isinstance(raw, list) else []
        base = self._research_mix
        mix = ResearchMix(
            web=_count_arg(call.arguments.get("web"), base.web, top=10),
            reddit=_count_arg(call.arguments.get("reddit"), base.reddit, top=6),
            youtube=_count_arg(call.arguments.get("youtube"), base.youtube, top=6),
        )
        engine = DeepResearch(
            search=self._searcher,
            reader=self._reader,
            fetch=lambda url: self._web.fetch(url, egress=self._egress),
            wanted=self._research_sources,
            mix=mix,
        )
        report = await engine.run(question, platforms=platforms)
        text = report.render()
        if self._study_later is not None and report.videos:
            for page in report.videos:
                self._study_later(page)
            text += (
                f"\n{len(report.videos)} video(s) are being turned into video notes "
                "for the team; look at them later with video_notes."
            )
        return ToolOutcome(
            text=text,
            data={
                "tool": RESEARCH_TOOL,
                "question": report.question,
                "sources": [
                    {
                        "n": source.number,
                        "title": source.title,
                        "url": source.url,
                        "platform": source.platform,
                        "read": source.read,
                        "detail": source.detail,
                    }
                    for source in report.sources
                ],
                "wanted": report.wanted,
            },
            failed=not report.sources,
        )

    async def _test_code(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        language = str(call.arguments.get("language", "")).strip().lower()
        code = call.arguments.get("code")
        suffix = TEST_LANGUAGES.get(language)
        if suffix is None:
            raise ValueError("test_code runs python or javascript, or saves html/css.")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("Give the code to test.")
        path = f"lab/test_{time.time_ns() // 1_000_000}.{suffix}"
        await self._sites.write(site_id, path, code)
        if suffix in {"html", "css"}:
            return ToolOutcome(
                text=f"Saved {path}. Open the project preview to check it.",
                data={"tool": TEST_CODE_TOOL, "path": path, "ran": False},
            )
        if not self.commands_enabled or self._commands is None:
            raise CommandError(
                "Testing code needs Agents Can Run Commands set to Ask or Auto "
                f"in Studio settings. The snippet is saved as {path}."
            )
        runner = f'"{sys.executable}"' if suffix == "py" else "node"
        result = await self._commands.request(
            agent_id=context.agent_id,
            agent_name=context.agent_name,
            chat_id=context.chat_id,
            site_id=site_id,
            command=f"{runner} {path}",
            cwd=self._sites.directory(site_id),
            policy=self._command_policy,
            timeout=self._command_timeout,
        )
        request = result.request
        passed = request.status == "ran" and (request.exit_code or 0) == 0
        verdict = "PASSED" if passed else "FAILED"
        return ToolOutcome(
            text=f"{verdict} ({path})\n{result.text}",
            data={
                "tool": TEST_CODE_TOOL,
                "path": path,
                "ran": request.status == "ran",
                "passed": passed,
                "exit_code": request.exit_code,
                "request_id": request.id,
            },
            failed=not passed,
        )

    async def _consult(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        if self._delegate is None:
            raise ValueError("There is no team to ask.")
        if context.agent_role == RESEARCHER_ROLE:
            raise ValueError("You are the researcher; use research instead.")
        question = str(call.arguments.get("question", "")).strip()
        if not question:
            raise ValueError("Say what the researcher should find out.")
        return await self._delegate.consult(context, question=question)

    def _require_site(self, context: ToolContext) -> str:
        if not context.site_id:
            raise ValueError(
                "This conversation has no project workspace. Attach a project first."
            )
        return context.site_id


async def _node_check(node: str, path: Path) -> str | None:
    """'' when Node parses the file, the syntax error when it does not, and
    None when Node could not give an answer."""
    try:
        process = await asyncio.create_subprocess_exec(
            node,
            "--check",
            str(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, raw = await asyncio.wait_for(process.communicate(), timeout=15)
    except OSError, TimeoutError:
        return None
    if process.returncode == 0:
        return ""
    error = raw.decode("utf-8", errors="replace")
    if "outside a module" in error or "ERR_" in error:
        return None
    line = re.search(rf"{re.escape(path.name)}:(\d+)", error)
    message = next(
        (row.strip() for row in error.splitlines() if "Error:" in row), "syntax error"
    )
    where = f" on line {line.group(1)}" if line else ""
    return f"syntax error{where}: {message}."


def loose_replace(content: str, old: str, new: str) -> str | None:
    """Replace old with new when they differ only in indentation or trailing
    spaces, re-indenting new to match; None unless exactly one place fits."""
    wanted = [line.strip() for line in old.strip("\n").splitlines()]
    if not any(wanted):
        return None
    lines = content.splitlines(keepends=True)
    bare = [line.strip() for line in lines]
    size = len(wanted)
    hits = [
        start
        for start in range(len(lines) - size + 1)
        if bare[start : start + size] == wanted
    ]
    if len(hits) != 1:
        return None
    start = hits[0]
    old_lines = old.strip("\n").splitlines()
    # How each indentation in old_text maps onto the file's real indentation.
    levels: dict[int, str] = {}
    for written, actual in zip(old_lines, lines[start : start + size], strict=False):
        if written.strip():
            levels.setdefault(len(_indent(written)), _indent(actual))
    known = sorted(levels)
    scale = 1.0
    if len(known) >= 2:
        low, high = known[0], known[1]
        scale = (len(levels[high]) - len(levels[low])) / (high - low)
    replacement: list[str] = []
    for line in new.strip("\n").splitlines():
        if not line.strip():
            replacement.append("")
            continue
        width = len(_indent(line))
        base = max((level for level in known if level <= width), default=known[0])
        extra = round(max(0, width - base) * scale)
        pad = "\t" if "\t" in levels[base] else " "
        replacement.append(levels[base] + pad * extra + line.lstrip())
    ending = "\n" if lines[start + size - 1].endswith("\n") else ""
    body = "\n".join(replacement) + ending if replacement else ""
    return "".join(lines[:start]) + body + "".join(lines[start + size :])


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _count_arg(value: object, default: int, *, top: int) -> int:
    """A source count the agent asked for, or the default when it did not."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        number = int(value)
    except ValueError:
        return default
    return max(0, min(top, number))


def _int_arg(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _glob_match(path: str, pattern: str) -> bool:
    """Match a project path the way people expect globs to behave."""
    name = path.rsplit("/", 1)[-1]
    if "/" not in pattern:
        return fnmatch.fnmatch(name, pattern)
    if fnmatch.fnmatch(path, pattern):
        return True
    # Let "src/**/*.ts" also match files directly in src/.
    return "**/" in pattern and fnmatch.fnmatch(path, pattern.replace("**/", ""))


def _is_text(content_type: str) -> bool:
    kind = content_type.split(";", 1)[0].strip()
    return kind.startswith("text/") or kind in {
        "application/json",
        "application/javascript",
        "application/xml",
        "image/svg+xml",
        "application/toml",
        "application/x-yaml",
    }


def _connection_lost(error: BaseException) -> bool:
    """Whether a web tool failed because the internet could not be reached."""
    if isinstance(error, httpx.TransportError | aiohttp.ClientConnectionError):
        return not isinstance(error, httpx.UnsupportedProtocol)
    return isinstance(error, ConnectionError | TimeoutError)
