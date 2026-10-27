"""The tools Studio agents can call, and the sandbox that executes them."""

import asyncio
import difflib
import fnmatch
import json
import math
import re
import shutil
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import aiohttp
import anyio.to_thread
import httpx

from free_claude_code.application.web_tools.ports import (
    WebFetchEgressPolicy,
    WebFetchEgressViolation,
    WebToolsPort,
)
from free_claude_code.core.json_types import JsonObject

from .assistant_tools import calculate
from .bug_library import BugLibraryError, licence_of
from .bug_library import bug as library_bug
from .bug_library import clip as clip_bug
from .bug_library import find as find_bugs
from .commands import CommandBroker, CommandError
from .connectivity import Connectivity
from .desk import DeskBrowser, DeskError
from .desk import render as render_desk
from .game_library import KENNEY as KENNEY_ASSETS
from .game_library import KINDS as GAME_KINDS
from .game_library import MAX_PACK_BYTES as MAX_GAME_PACK_BYTES
from .game_library import GameLibraryError, GameVault
from .game_library import Pack as GamePack
from .game_library import choose as choose_game_files
from .game_library import example as game_example
from .game_library import find_examples as find_game_examples
from .game_library import find_files as find_game_files
from .game_library import find_packs as find_game_packs
from .game_library import pack as game_pack
from .game_library import project_path as game_path
from .game_library import read_files as read_game_files
from .game_library import ready as game_ready
from .godot import MAX_SHOW as GODOT_MAX_SHOW
from .godot import STARTER_NOTES as GODOT_STARTERS
from .godot import (
    GodotLibraryError,
    find_demos,
    godot_demo,
    godot_demo_art,
    godot_demo_project,
    godot_starter_files,
    untouched_starter,
)
from .godot.engine import GodotEngine, GodotError
from .ideas import ROLE_CATEGORIES, IdeaBoard, IdeaError
from .ideas import describe as describe_idea
from .images import FoundImage, ImageError, download_image, find_images
from .llm import ToolCall, ToolSpec
from .memory import SERVER_SHARED_ID, SHARED_MEMORY_ID, MemoryService
from .models import MemoryEntry
from .page_try import (
    PageReport,
    PageTryError,
    page_try_ready,
    parse_steps,
    try_page,
)
from .photos import PhotoError, PhotoLibrary
from .photos import describe as describe_photo
from .platforms import PlatformError, PlatformPage, PlatformReader, platform_of
from .polish import PICTURE_SUFFIXES, polish_notes
from .project_check import (
    CHECKED_FILES,
    REPEATED_LINES,
    check_project,
    text_lines,
)
from .research import PLATFORMS, DeepResearch, ResearchMix
from .search import SearchError, StudioSearch
from .site_layouts import KINDS as LAYOUT_KINDS
from .site_layouts import SAMPLE_NOTE as LAYOUT_SAMPLE_NOTE
from .site_layouts import LayoutError, layout_files, name_layout
from .site_layouts import find as find_layouts
from .site_layouts import layout as find_layout
from .sites import (
    IMAGE_SUFFIXES,
    MAX_FILE_BYTES,
    STARTER_STYLES,
    SiteError,
    SiteWorkspace,
    is_starter,
    tidy_html,
)
from .templates import template_files, template_libraries
from .ui_kit import UiKitError, find_icons, icon_file, kit_files, starter_files
from .ui_library import KINDS as UI_KINDS
from .ui_library import UiLibraryError
from .ui_library import credit as ui_credit
from .ui_library import piece as ui_piece
from .ui_library import search as ui_search
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
MANAGE_AGENT_TOOL = "manage_agent"
WEATHER_TOOL = "weather"
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
DESK_TOOL = "desktop_browser"
START_PROJECT_TOOL = "start_project"
POLISH_TOOL = "polish_check"
TRY_PAGE_TOOL = "try_page"
RESTORE_FILE_TOOL = "restore_file"
VIDEO_NOTES_TOOL = "video_notes"
FIND_IMAGES_TOOL = "find_images"
IDEAS_TOOL = "ideas"
MAX_LISTED_IDEAS = 12
LIST_PHOTOS_TOOL = "list_photos"
USE_PHOTO_TOOL = "use_photo"
SAVE_IMAGE_TOOL = "save_image"
LAB_TOOL = "lab"
FARM_TOOL = "farm"
CODE_TOOL = "code_and_test"
TEAM_PLAN_TOOL = "team_plan"
SKILL_TOOL = "skill"
TOOLSHED_TOOL = "toolshed"
MCP_TOOL = "mcp"
CHANGER_TOOL = "fcc_changer"
LOOK_PAGE_TOOL = "look_page"
LOOK_REFERENCE_TOOL = "look_reference"
AIDER_TOOL = "aider"
UI_LIBRARY_TOOL = "ui_library"
SITE_LAYOUTS_TOOL = "site_layouts"
UI_KIT_TOOL = "ui_kit"
BUG_LIBRARY_TOOL = "bug_library"
GODOT_TOOL = "godot"
GAME_ASSETS_TOOL = "game_assets"
MAX_EXAMPLE_CHARS = 12_000
MAX_KIT_FILES = 300
TEXT_KIT_SUFFIXES = frozenset({".html", ".css", ".js", ".svg", ".md", ".txt", ".json"})
MAX_PIECE_CHARS = 12_000
IMAGE_TOOLS = frozenset({FIND_IMAGES_TOOL, SAVE_IMAGE_TOOL})
MAX_REMEMBERED_IMAGES = 60
MAX_LISTED_PHOTOS = 30
HELPER_ROLE = "helper"
MAX_SEARCH_MATCHES = 60
MAX_READ_LINES = 400
NETWORK_TOOLS = frozenset(
    {*WEB_TOOLS, RESEARCH_TOOL, "study_video", DESK_TOOL, "weather", *IMAGE_TOOLS}
)
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
        FIND_IMAGES_TOOL,
        LIST_PHOTOS_TOOL,
        UI_LIBRARY_TOOL,
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
IMAGES_DOWN_NOTE = (
    "Image search isn't working right now: don't search again on this job. "
    "Draw the pictures instead (inline SVG illustrations, icons, or CSS "
    "gradients and shapes) and carry on building."
)
OFFLINE_NOTE = (
    "The internet looks unreachable from this computer, so web tools are paused "
    "until it is back. Carry on with recall, the project files, and what you know."
)
NOTHING_CHANGED = (
    "already holds exactly that, so nothing changed. Make a real improvement "
    "(edit_file changes one part), or finish if the work is done."
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
            "for example index.html or styles.css. For a long file, write the "
            "first part, then add the rest with append true."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Site-relative file path."},
                "content": {"type": "string", "description": "Complete file text."},
                "append": {
                    "type": "boolean",
                    "description": "Add to the end of the file instead of replacing it.",
                },
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
            "Watch a video and turn it into notes the team can use (summary, "
            "key points, steps, names, warnings), saved in video notes and in "
            "memory with its link. Works with YouTube links, other video "
            "links, and video files on this PC (give the file's path). It "
            "reads captions when there are some, and otherwise listens to the "
            "video with speech recognition on this computer. Use it when the "
            "user gives you a video, or a video matters for the task. Say "
            "what to focus on when only part of it matters; set show to true "
            "to play it in the desktop browser so the user can watch along."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The video link, or a video file's path on this PC.",
                },
                "focus": {
                    "type": "string",
                    "description": "Optional: what the team wants from it.",
                },
                "show": {
                    "type": "boolean",
                    "description": "Optional: also play it in the desktop browser.",
                },
            },
            "required": ["url"],
        },
    ),
    ToolSpec(
        name=DESK_TOOL,
        description=(
            "A real browser window on the user's desktop (their Edge or "
            "Chrome, with Studio's own profile) that you drive while they "
            "watch: research the live web and watch videos. Actions: search "
            "(query; where web or youtube), open (url), read (the page's text; "
            "part for more), links (query filters them), click (a link's "
            "number), scroll (down or up), back, play and pause (the page's "
            "video), watch (play the page's video and study it into notes; "
            "focus), buttons (the harmless buttons you may press), press "
            "(a button's words, like accept, show more or next), close. You "
            "only read and follow links: never type, sign in, or buy. Cite "
            "the pages you used by their address."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "search",
                        "open",
                        "read",
                        "links",
                        "click",
                        "scroll",
                        "back",
                        "play",
                        "pause",
                        "watch",
                        "buttons",
                        "press",
                        "close",
                    ],
                },
                "query": {
                    "type": "string",
                    "description": "search: what to look for; links: words to filter by.",
                },
                "where": {"type": "string", "enum": ["web", "youtube"]},
                "url": {"type": "string", "description": "open: the page's link."},
                "number": {
                    "type": "integer",
                    "description": "click: the link's number from read or links.",
                },
                "part": {
                    "type": "integer",
                    "description": "read: which part of a long page (1, 2, …).",
                },
                "direction": {"type": "string", "enum": ["down", "up"]},
                "text": {"type": "string", "description": "press: the button's words."},
                "focus": {
                    "type": "string",
                    "description": "watch: what the team wants from the video.",
                },
            },
            "required": ["action"],
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
        name=TRY_PAGE_TOOL,
        description=(
            "Use a web page of the project like a real user, in a hidden "
            "phone-sized browser: type into boxes, pick options, click "
            "buttons, then read what the page shows and compare it with what "
            "it should show. Reports steps that failed, values that weren't "
            "what you expected, pop-up boxes, script errors, missing files, "
            "and sideways scrolling. Reading code can't prove a page works; "
            "this can. Example steps: "
            '[{"do": "fill", "target": "Bill amount", "value": "50"}, '
            '{"do": "click", "target": "Add"}, '
            '{"do": "read", "target": "#total", "expect": "$57.50"}]'
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "string",
                    "description": "The page file (default index.html).",
                },
                "steps": {
                    "type": "array",
                    "description": (
                        "What a user does, in order. do is fill, select, "
                        "click, press, check, uncheck, wait, or read. target "
                        "is a #id, .class, or CSS selector, or a field's "
                        "label, a button's text, or text on the page. value "
                        "is what to type or pick (press: the key; wait: "
                        "milliseconds). On read, expect is what it should show."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "do": {"type": "string"},
                            "target": {"type": "string"},
                            "value": {"type": "string"},
                            "expect": {"type": "string"},
                        },
                        "required": ["do"],
                    },
                },
                "desktop": {
                    "type": "boolean",
                    "description": "A desktop-sized window instead of a phone.",
                },
            },
        },
    ),
    ToolSpec(
        name=START_PROJECT_TOOL,
        description=(
            "Start a new project from a solid, mobile-first starter instead of a "
            "blank page, then change it to fit the job. Templates: business "
            "(professional multi-page site: Home, About, Services with tabs, "
            "Gallery, Contact; for any café, shop, salon, trade, or studio), "
            "website (one page), landing, webapp (single-page app with saved "
            "state), game (canvas game loop with touch controls), 3d-landing "
            "(landing page with an interactive 3D hero, scroll reveals and "
            "counting numbers), 3d-dashboard (live dashboard with a 3D view of "
            "services and an activity log, fed by JSON), 3d-shop (shop or bakery "
            "with a 3D product scene to turn by hand and tilting product cards "
            "rendered from the 3D models), phaser-game (a Phaser browser game "
            "with Kenney art and sound, keyboard and touch; starts as a "
            "platformer), lessons (classes or lessons, e.g. a "
            "surf school: animated waves hero, lesson prices, coaches, booking "
            "form), portfolio (studio or architect: filterable project grid "
            "with detail views), python-tool, "
            "python-web (FastAPI), node-api. Existing work is never overwritten "
            "unless overwrite is set."
        ),
        parameters={
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "enum": [
                        "business",
                        "website",
                        "landing",
                        "webapp",
                        "game",
                        "3d-landing",
                        "3d-dashboard",
                        "3d-shop",
                        "lessons",
                        "portfolio",
                        "phaser-game",
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
        name=TOOLSHED_TOOL,
        description=(
            "The HQ toolshed: tools you don't have yet. action list shows what is "
            "on the shelf and what each one does; action take with tools (their "
            "names) and why picks them up for this job. They go back on the "
            "shelf when the job ends. Take only what the job needs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "take"]},
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "take: the tools' names, from list.",
                },
                "why": {
                    "type": "string",
                    "description": "take: what you need them for.",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=SKILL_TOOL,
        description=(
            "Skills and knowledge from repos added to Studio (Claude-style "
            "SKILL.md files, commands, guides, roadmaps, and lists like public "
            "APIs or free dev tools). action search with a query finds the "
            "right skill and the matching lines in every repo's text; action "
            "read with a name gives a skill's full instructions, or with repo, "
            "file and line shows that part of a repo's file; action list shows "
            "the skills (with repo: one repo's). Search first when unsure, read "
            "the one that fits the job, then follow it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "list", "read"]},
                "query": {
                    "type": "string",
                    "description": "search: what you need, e.g. 'react form validation'.",
                },
                "name": {"type": "string", "description": "read: the skill's name."},
                "repo": {
                    "type": "string",
                    "description": "read or list: the repo, e.g. public-apis/public-apis.",
                },
                "file": {
                    "type": "string",
                    "description": "read: a file in the repo, as search shows it.",
                },
                "line": {
                    "type": "integer",
                    "description": "read: show the part of the file around this line.",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=MCP_TOOL,
        description=(
            "MCP tool servers the user switched on (files, browsers, databases, "
            "and the services on the Connectors page: GitHub, Zapier for Gmail, "
            "Sheets, Calendar and Slack, email, a Discord or Slack webhook, and "
            "more). action servers lists them; tools with a server "
            "lists its tools and their arguments; call runs one tool with "
            "arguments. Look at a server's tools before calling one."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["servers", "tools", "call"]},
                "server": {"type": "string", "description": "The server's name."},
                "tool": {"type": "string", "description": "call: the tool's name."},
                "arguments": {
                    "type": "object",
                    "description": "call: the tool's arguments.",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=CODE_TOOL,
        description=(
            "Hand a coding job to the Coder and the Tester: the Coder codes it "
            "for as long as it needs (apps, games, scripts, tools, bots, HUDs), "
            "the Tester tests it, fixes small bugs, and hands the rest back, "
            "for a few rounds until it works. It runs in the background and "
            "they report here when done. Websites go to the Builder with "
            "ask_agent instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "What to code, with everything it needs.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name; a new one is made when none matches.",
                },
            },
            "required": ["goal"],
        },
    ),
    ToolSpec(
        name=TEAM_PLAN_TOOL,
        description=(
            "Plan a bigger job for the whole team and run it: the job is split "
            "into steps, each done by the agent best at it (research, then "
            "build, then test, ...), in order, with each agent handed what the "
            "steps before it produced. Steps that don't depend on each other run "
            "at the same time. It runs in the background, shows in the HQ, and "
            "reports here when done. Use it for jobs that need two or more "
            "agents; one agent's job goes to ask_agent."
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The whole job, with everything it needs.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name to work in.",
                },
                "relay": {
                    "type": "boolean",
                    "description": "true: pass the job through the relay instead: "
                    "LCC's agent for it first, then each repo's agent, one after "
                    "another, each building on the last.",
                },
            },
            "required": ["goal"],
        },
    ),
    ToolSpec(
        name=FARM_TOOL,
        description=(
            "The Content Farm: makes faceless YouTube Shorts (and TikToks, "
            "Reels) and two-hour lore or what-if videos to fall asleep to, on "
            "this PC, from idea to a finished MP4 with a voiceover, real "
            "stills and clips from the user's library or the show's fandom "
            "wiki, and word-by-word captions; animated cartoon stories with "
            "the user's own characters (kind cartoon); and music edits cut "
            "beat for beat to a song the user gave (kind edit). For a long "
            "video, set long. The user watches "
            "it on the Content Farm page. action make: make videos (count, "
            "about a topic, or the next ideas on the board) for a channel; it "
            "runs in the background and they appear in the posting queue. "
            "ideas: put new video ideas on the board. channel: add a channel "
            "(an account) for a niche. list: the channels and what is ready. "
            "queue: finished videos waiting to be posted, with their times."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["make", "ideas", "channel", "list", "queue"],
                },
                "topic": {
                    "type": "string",
                    "description": "make/ideas: what the videos are about. channel: the niche.",
                },
                "count": {"type": "integer", "description": "How many (1-10)."},
                "channel": {
                    "type": "string",
                    "description": "Which channel, by name; the newest one when empty.",
                },
                "style": {
                    "type": "string",
                    "enum": [
                        "gameplay_story",
                        "what_if",
                        "lore",
                        "facts",
                        "story",
                        "motivation",
                        "tips",
                        "ai_art",
                        "explainer",
                        "news",
                        "lore_sleep",
                        "what_if_sleep",
                        "theory_sleep",
                        "cartoon_story",
                        "beat_edit",
                    ],
                    "description": "channel: the video style.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["cartoon", "edit"],
                    "description": "make: an animated cartoon story, or a music edit cut to a song, on a channel of that kind.",
                },
                "long": {
                    "type": "boolean",
                    "description": "make: a two-hour video to fall asleep to (lore, a what-if) instead of shorts.",
                },
                "minutes": {
                    "type": "integer",
                    "description": "make, long: how long, e.g. 120 for two hours.",
                },
                "fandom": {
                    "type": "string",
                    "description": "channel: the show, movie, or game it is about.",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=LAB_TOOL,
        description=(
            "The Lab: a science sandbox with every element, a shelf of real "
            "chemicals, materials, and electronics parts, where results follow "
            "real chemistry and physics. The user watches it on the Lab page. "
            "action make: make a product or gadget from a request ('shampoo', "
            "'bath bomb', 'flashlight'); it lists every ingredient, its "
            "molecule and elements. mix: pour chemicals together (items with "
            "amounts in mL or g; heat or flame optional) and see colours, gas, "
            "solids, heat, and pH. build: power electronics parts and see what "
            "works. material: blend materials into an alloy or composite and "
            "test it. design: a piece of technology drawn in its real "
            "materials and checked against physics; give components, each "
            "{name, material (a Materials shelf id: steel, iron, copper, "
            "aluminium, stainless-steel, fr4 for circuit boards, abs, glass, "
            "wood-oak, carbon-fibre...), shape (box, plate, board, rod, "
            "cylinder, tube, sphere, wire), size_mm [w, h, d] (rods and tubes: "
            "[diameter, length]), role (structure, casing, electronics, moving, "
            "wiring, fastener), part (an electronics part id, for batteries, "
            "motors, LEDs, boards), count, carries_kg (load on a frame member), "
            "how (how it works), at_mm [x, y, z] (where it sits in the 3D "
            "view, in mm: x across and z front to back from the middle, y the "
            "height of its bottom above the floor, so parts on a 1.6 mm board "
            "sit at y 1.6), turn_deg (turned about the upright axis)}; lay it "
            "out like the real thing (a board as the base, chips, connectors "
            "and parts on it, nothing overlapping), and when changing the "
            "owner's design keep the parts and places they didn't ask to "
            "change; set wet for outdoor use. It reports weight, "
            "strength margins, heat, the electronics, rust, and how each part "
            "works. find: look up a chemical, element, material, or part "
            "(unknown chemicals are learned from PubChem). list: what has "
            "been made."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "make",
                        "mix",
                        "build",
                        "material",
                        "design",
                        "find",
                        "list",
                    ],
                },
                "request": {
                    "type": "string",
                    "description": "make: what to make. find: what to look up.",
                },
                "items": {
                    "type": "array",
                    "description": "mix: chemicals, e.g. {id: 'vinegar', amount: 50}.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "amount": {"type": "number"},
                        },
                    },
                },
                "parts": {
                    "type": "array",
                    "description": "build: parts, e.g. {id: 'aa', count: 2}. "
                    "material: materials, e.g. {id: 'copper', percent: 88}.",
                    "items": {"type": "object"},
                },
                "components": {
                    "type": "array",
                    "description": "design: the components (see design).",
                    "items": {"type": "object"},
                },
                "wet": {
                    "type": "boolean",
                    "description": "design: used outdoors or in water.",
                },
                "heat": {"type": "boolean"},
                "flame": {"type": "boolean"},
                "series": {
                    "type": "boolean",
                    "description": "build: batteries in series (default) or side by side.",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=IDEAS_TOOL,
        description=(
            "The user's ideas board: notes, photos, videos, and links of what "
            "they want (a UI, a layout, a look, an app or site they like), with "
            "what they say about each. Search it before you design or build, "
            "go in the direction it points, and make your own business-level "
            "work, not a copy. action: search (query, tag, and category narrow "
            "it; your own category is searched by default; category game holds "
            "game references), read (one idea in full), or use (put one of its "
            "photos into the project, at path). look_reference turns a photo "
            "or video into a build brief."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "read", "use"]},
                "query": {"type": "string"},
                "tag": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": ["website", "app", "game", "lab", "general"],
                    "description": "What the work is: ideas for that and general ones.",
                },
                "idea": {"type": "string", "description": "Its id or title."},
                "path": {
                    "type": "string",
                    "description": "Where use puts a photo, e.g. images/look.jpg.",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=LIST_PHOTOS_TOOL,
        description=(
            "The user's own photos of their business (the shop, team, food, "
            "work) with what they said about each: what it shows, prices, "
            "hours, anything. Use these before stock photos, and use the notes "
            "as facts for the site. query narrows the list."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    ),
    ToolSpec(
        name=USE_PHOTO_TOOL,
        description=(
            "Put one of the user's business photos into the project (for "
            "example images/shopfront.jpg), then use it with <img> and its "
            "width and height. Their own photos need no credit line."
        ),
        parameters={
            "type": "object",
            "properties": {
                "photo": {"type": "string", "description": "Its name or id."},
                "path": {
                    "type": "string",
                    "description": "Where to put it, e.g. images/shopfront.jpg.",
                },
            },
            "required": ["photo"],
        },
    ),
    ToolSpec(
        name=FIND_IMAGES_TOOL,
        description=(
            "Find real photos a website may use for free (Creative Commons, "
            "cleared for commercial use), each with its size and the credit "
            "line to show. Use it for heroes, cards, and galleries instead of "
            "empty boxes; then save the one you want with save_image."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What the photo shows, e.g. 'coffee shop interior'.",
                },
                "count": {"type": "integer", "description": "1 to 12 (default 6)."},
                "orientation": {"type": "string", "enum": ["wide", "tall", "square"]},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name=UI_LIBRARY_TOOL,
        description=(
            "FCC's library of 3,802 ready-made web design pieces from Uiverse "
            "(MIT): buttons, cards, forms, inputs, toggles, checkboxes, radios, "
            "loaders, tooltips, notifications and backgrounds, each small HTML "
            "and CSS. search finds pieces by words (e.g. 'glass card', 'neon "
            "button', 'dark login form'); get gives one piece's code. Copy it "
            "into the site, rename its classes to fit, swap its colours and "
            "fonts for the site's own, and keep its credit comment."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "get"]},
                "query": {
                    "type": "string",
                    "description": "search: what it looks like, e.g. 'animated toggle'.",
                },
                "kind": {
                    "type": "string",
                    "enum": list(UI_KINDS),
                    "description": "search: only this kind of piece.",
                },
                "count": {
                    "type": "integer",
                    "description": "search: 1 to 12 (default 6).",
                },
                "tailwind": {
                    "type": "boolean",
                    "description": "search: also show pieces that need Tailwind "
                    "(off: plain CSS only, which fits any site).",
                },
                "id": {"type": "string", "description": "get: a piece id from search."},
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=SITE_LAYOUTS_TOOL,
        description=(
            "FCC's 26 whole-website layouts from Start Bootstrap (MIT, Bootstrap "
            "5, phone-ready): agency, landing pages, portfolios, blogs, shops, a "
            "CV, a multi-page business site, an admin dashboard and more. list "
            "shows them (optionally one kind); use copies one into the project "
            "with Bootstrap and its icons in vendor/, so it works offline. Then "
            "replace every sample word, photo and form address with the "
            "business's own, and restyle it; add pieces with ui_library."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "use"]},
                "kind": {
                    "type": "string",
                    "enum": list(LAYOUT_KINDS),
                    "description": "list: only this kind of layout.",
                },
                "layout": {
                    "type": "string",
                    "description": "use: a layout id from list, e.g. 'agency'.",
                },
                "title": {
                    "type": "string",
                    "description": "use: the business's name, put where the layout says 'Start Bootstrap'.",
                },
                "overwrite": {"type": "boolean"},
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=GODOT_TOOL,
        description=(
            "Make real Godot 4 games (Godot 4.7.2, GDScript) on this PC. start "
            "begins a project from a starter: platformer-2d, rpg-topdown or "
            "third-person-3d. Write .gd scripts and .tscn scenes with "
            "write_file/edit_file. check runs Godot headless and lists every "
            "script error, missing file and warning (file and line): run it "
            "after every change and fix them all. frames plays the game for a "
            "few seconds and saves its last frame to screenshots/. export "
            "makes a Windows game the owner can play (Godot's export "
            "templates download once, about 1 GB). demos and demo search and "
            "read Godot's 133 official demo projects (MIT) for how to do "
            "things; use copies a whole demo (code, art, sound, models) into "
            "the project to build on. The godot-dev skill holds the genre book."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "start",
                        "check",
                        "frames",
                        "export",
                        "demos",
                        "demo",
                        "use",
                        "setup",
                    ],
                },
                "starter": {
                    "type": "string",
                    "enum": list(GODOT_STARTERS),
                    "description": "start: which starter.",
                },
                "title": {"type": "string", "description": "start: the game's name."},
                "query": {
                    "type": "string",
                    "description": "demos: what you need, e.g. 'tilemap', 'ragdoll'.",
                },
                "id": {
                    "type": "string",
                    "description": "demo, use: a demo id, e.g. '2d/platformer'.",
                },
                "file": {
                    "type": "string",
                    "description": "demo: one file of the demo.",
                },
                "seconds": {
                    "type": "number",
                    "description": "frames: how long to play (default 3).",
                },
                "overwrite": {"type": "boolean"},
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=BUG_LIBRARY_TOOL,
        description=(
            "FCC's bug-fix library: 490 real bugs from big Python projects "
            "(Django, pytest, sympy, Sphinx, matplotlib, scikit-learn, requests "
            "and more), each with its GitHub issue, the fix the project merged, "
            "and the test that proves the fix. Before fixing a bug, find "
            "similar ones (describe the bug or paste the error words) and "
            "read one with get: see what the real cause was, how small the fix "
            "was, and how its test fails before and passes after. Learn the "
            "pattern; write FCC's own fix and test."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["find", "get"]},
                "query": {
                    "type": "string",
                    "description": "find: the bug in words, or words from the error.",
                },
                "project": {
                    "type": "string",
                    "description": "find: only bugs from this project, e.g. 'django'.",
                },
                "id": {"type": "string", "description": "get: a bug id from find."},
                "part": {
                    "type": "string",
                    "enum": ["all", "issue", "fix", "test"],
                    "description": "get: one part only (default all).",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=UI_KIT_TOOL,
        description=(
            "FCC's app kit: Tabler (MIT, Bootstrap 5, light and dark) for app "
            "and game screens (dashboards, menus, settings, leaderboards, "
            "forms, tables, pricing, sign-in) plus 5,184 Tabler icons. app "
            "starts home, leaderboard and settings screens with the kit in "
            "vendor/tabler; add copies just the kit into a project; icons "
            "finds icons by words; use_icons copies them to assets/icons/ as "
            "SVG files. Tabler's classes follow Bootstrap 5 (card, btn, "
            "navbar, form-control, list-group, progress, badge, avatar)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["app", "add", "icons", "use_icons"],
                },
                "title": {"type": "string", "description": "app: the app's name."},
                "query": {
                    "type": "string",
                    "description": "icons: what the icon shows, e.g. 'coin'.",
                },
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "use_icons: icon names from action icons.",
                },
                "overwrite": {"type": "boolean"},
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=GAME_ASSETS_TOOL,
        description=(
            "FCC's game library: Kenney's 217 free (CC0) art and sound packs "
            "(sprites, tile sheets, characters, UI, particles, fonts, sound "
            "effects, jingles; 49 ship with FCC, the rest download once) and "
            "2,298 Phaser example programs. find searches files by words "
            "('coin', 'laser sound', 'grass tile'); packs lists packs; use "
            "copies a pack's files (paths, a folder or a word) into "
            "assets/<pack>/; download fetches a pack that isn't on this PC; "
            "examples and example find and show Phaser code for a mechanic. "
            "Read the game-dev skill for the recipes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["find", "packs", "use", "download", "examples", "example"],
                },
                "query": {
                    "type": "string",
                    "description": "find, packs, examples: plain words.",
                },
                "kind": {
                    "type": "string",
                    "enum": list(GAME_KINDS),
                    "description": "find: only sprites, sheets, sounds, fonts or 3D models.",
                },
                "pack": {"type": "string", "description": "use, download: a pack id."},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "use: file paths from find, a folder, or a word.",
                },
                "id": {
                    "type": "string",
                    "description": "example: an id from examples.",
                },
                "count": {
                    "type": "integer",
                    "description": "find, examples: how many.",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name=SAVE_IMAGE_TOOL,
        description=(
            "Download a photo (a find_images result) into the project, e.g. "
            "images/hero.jpg, so the site works offline and loads fast. Then "
            'use it with <img src="images/hero.jpg" alt="..." width height> '
            "and put its credit line in the footer."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The photo's https address."},
                "path": {
                    "type": "string",
                    "description": "Where to save it, e.g. images/hero.jpg.",
                },
            },
            "required": ["url", "path"],
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
        name=WEATHER_TOOL,
        description=(
            "The weather now and the forecast for any town or city: temperature, "
            "rain chance, wind. Use it when the user asks about the weather."
        ),
        parameters={
            "type": "object",
            "properties": {
                "place": {"type": "string", "description": "Town or city."},
                "days": {
                    "type": "integer",
                    "description": "Days of forecast, 1 to 7 (default 3).",
                },
            },
            "required": ["place"],
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
        name=MANAGE_AGENT_TOOL,
        description=(
            "Control any agent on the team. action 'show' lists every agent with "
            "its model, whether it has every tool, and its memory (for one agent, "
            "what it remembers). 'every_tool_on' or 'every_tool_off' gives an "
            "agent every tool or only its own (fewer tools uses fewer tokens); "
            "'tool_on' or 'tool_off' adds or removes one tool of its own. "
            "'add_memory' saves text into an agent's memory; for an agent on a "
            "server AI that is its own memory area, so write only what it needs, "
            "never the user's private details. 'forget' clears that memory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "show",
                        "every_tool_on",
                        "every_tool_off",
                        "tool_on",
                        "tool_off",
                        "add_memory",
                        "forget",
                    ],
                },
                "tool": {
                    "type": "string",
                    "description": "The tool, for tool_on and tool_off.",
                },
                "agent": {
                    "type": "string",
                    "description": "Agent name; leave out with show for everyone.",
                },
                "text": {
                    "type": "string",
                    "description": "What to save, for add_memory.",
                },
            },
            "required": ["action"],
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
            "Hand one task to another agent and wait for its report (set "
            "background to let it work while you carry on). Use it when a part "
            "needs another agent's tools, model, or know-how: a teammate, one "
            "of your subagents, or a repo agent (a specialist from an added "
            "repo). Name the agent; calling it makes it work and report back. "
            "For example a Coder building an app hands the UI to a design "
            "specialist, or research to the Researcher."
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
        name=LOOK_PAGE_TOOL,
        description=(
            "See a page of the project the way a visitor does: screenshots at "
            "PC and phone size go to the Vision Model, which says what looks "
            "broken or unfinished (overlaps, cut-off or faint text, broken "
            "images, crowding, sideways scrolling). Without a Vision Model you "
            "get each page's text and checks. Use it after building or "
            "changing a page; fix what it reports and look again (at most 3 "
            "rounds). steps (as for try_page) run first to reach a state."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "string",
                    "description": "The page file (default index.html).",
                },
                "steps": {"type": "array", "items": {"type": "object"}},
                "question": {
                    "type": "string",
                    "description": "What to check, e.g. 'is the menu readable on a phone'.",
                },
            },
        },
    ),
    ToolSpec(
        name=LOOK_REFERENCE_TOOL,
        description=(
            "Turn a photo or video the owner sent into a build brief: the "
            "Vision Model looks at it (a video as 9 frames taken through it) "
            "and writes, for a game, the genre, camera, player, moves and "
            "animations, enemies, level (as a text map), HUD, physics feel, "
            "art style, palette and how to build it in Godot 4; for a website "
            "or app, the sections, layout, colours, type and parts. Use it on "
            "ideas-board photos and videos (category game holds the owner's "
            "game references), business photos, or a picture or video in the "
            "project, before you build from it. The brief is saved in "
            "reference-notes/. Build it like the reference with the small "
            "differences its MAKE IT OURS list gives (new names, redrawn "
            "characters and logo, shifted colours), so it is the owner's own "
            "and not a copy; the owner's own art may be used as it is."
        ),
        parameters={
            "type": "object",
            "properties": {
                "idea": {
                    "type": "string",
                    "description": "An ideas-board photo or video (id or title).",
                },
                "photo": {
                    "type": "string",
                    "description": "Or a business photo (name or id).",
                },
                "file": {
                    "type": "string",
                    "description": "Or a picture or video in the project.",
                },
                "make": {
                    "type": "string",
                    "enum": ["game", "website", "app"],
                    "description": "What it will become (default from the reference).",
                },
                "focus": {
                    "type": "string",
                    "description": "What to look at most, e.g. 'the jump and the enemies'.",
                },
            },
        },
    ),
    ToolSpec(
        name=AIDER_TOOL,
        description=(
            "Hand a coding job to Aider, a separate coding assistant on this "
            "PC (if the owner installed it), working on the files you name in "
            "this project. It writes the change itself with your model; then "
            "read the changed files and check them (check_project, try_page, "
            "fcc_changer check) like your own work. Good for a focused edit "
            "across a few files or a stubborn bug; describe the job fully: "
            "what to change, why, and how to know it works. It follows FCC's "
            "skills (and the Changer's notebook in its copy), runs the related "
            "tests and fixes them until they pass, and checks its own syntax. "
            "architect: true for a bigger change (one model plans, another "
            "writes). repo_map: true when it must find its way around a big "
            "codebase like FCC (costs about 1k tokens a request). screenshots: "
            "true (Changer copy) or images: picture files, so a Vision Model "
            "sees the page. Runs after the owner's command approval (Agents "
            "Can Run Commands)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The whole job, as you would tell a developer.",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The files it may change or create (at most 12).",
                },
                "architect": {"type": "boolean"},
                "repo_map": {"type": "boolean"},
                "screenshots": {"type": "boolean"},
                "images": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task", "files"],
        },
    ),
    ToolSpec(
        name=CHANGER_TOOL,
        description=(
            "The Changer team's own tool, for changing FCC itself in the "
            "Changer copy. action plan (Planner): submit the plan: size (quick "
            "or project), kind, summary, spec, risks, files, tests, milestones "
            "[{title, goal, files, tests}], or suggestions [{title, why, value, "
            "effort, risk}] for a vague request. action review (reviewers): "
            "verdict pass or fail, findings [{problem, where, evidence, fix}], "
            "notes. action changes: the files changed so far. check: "
            "syntax-check every changed file and load the app from the copy; "
            "fix every problem it reports. tests: run the test files you name "
            '(tests: ["tests/studio/test_x.py"]) and read the failures. try: run '
            "the changed copy (no keys, empty data) and use a Studio page like a "
            "person (page: home, lab, trade, agents...; steps as for try_page: "
            "fill, click, read with expect); reports script errors, missing "
            "files, pop-ups and sideways scrolling; phone false for PC size. "
            "look: screenshot pages at PC and phone size and have the Vision "
            "Model say what looks wrong (question: what to check); fix it and "
            "look again. note: write in the shared notebook everyone on the "
            "update reads (text; kind finding, decision, done, next, or lesson "
            "to keep for later updates). screenshots: just pictures of pages for the owner "
            "(pages; phone true for phone size). subagent: hand a separate part to a helper "
            "that works in the same copy and reports back (task: everything it "
            "needs; files: the files it owns; agent: optional team member's "
            "name, else a helper Changer)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "plan",
                        "review",
                        "changes",
                        "check",
                        "tests",
                        "try",
                        "look",
                        "note",
                        "screenshots",
                        "subagent",
                    ],
                },
                "size": {"type": "string", "enum": ["quick", "project"]},
                "kind": {"type": "string"},
                "summary": {"type": "string"},
                "spec": {"type": "string"},
                "risks": {"type": "array", "items": {"type": "string"}},
                "files": {"type": "array", "items": {"type": "string"}},
                "tests": {"type": "array", "items": {"type": "string"}},
                "milestones": {"type": "array", "items": {"type": "object"}},
                "suggestions": {"type": "array", "items": {"type": "object"}},
                "verdict": {"type": "string", "enum": ["pass", "fail"]},
                "findings": {"type": "array", "items": {"type": "object"}},
                "notes": {"type": "string"},
                "pages": {"type": "array", "items": {"type": "string"}},
                "page": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "object"}},
                "question": {"type": "string"},
                "text": {"type": "string"},
                "phone": {"type": "boolean"},
                "task": {"type": "string"},
                "agent": {"type": "string"},
            },
            "required": ["action"],
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
ALL_TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOOL_SPECS)
"""Every tool Studio has."""
MAIN_ONLY_TOOLS = frozenset({MANAGE_AGENT_TOOL})
PRIVATE_TOOLS = frozenset(
    {"remember", "recall", "video_notes", "knowledge", "conversation", "learn", "todo"}
)
"""Tools that read the user's memory bank, so agents on server AIs lose them."""
AREA_TOOLS = frozenset({"remember", "recall"})
"""What an agent on a server AI keeps: remember and recall, in its own area and
the server agents' shared memory."""
SEALED_TOOLS = PRIVATE_TOOLS - AREA_TOOLS

"""Tools only the main AI has, even for agents given every tool: it runs the team."""
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
        MANAGE_AGENT_TOOL,
        WEATHER_TOOL,
        LAB_TOOL,
        FARM_TOOL,
        CODE_TOOL,
        TEAM_PLAN_TOOL,
        TOOLSHED_TOOL,
        CHANGER_TOOL,
    }
)
NEW_PROJECT_TOOLS = frozenset({"start_project", "site_layouts", "godot"})
"""Tools that lay a new project's files down: never on the Changer's shelf,
whose project is the copy of FCC that becomes an update zip."""
NOT_IN_THE_SHED = frozenset(
    {
        *MAIN_ONLY_TOOLS,
        *DELEGATION_TOOLS,
        AGENT_MODEL_TOOL,
        TODO_TOOL,
        SYSTEM_STATUS_TOOL,
        PROJECTS_TOOL,
        CODE_TOOL,
        TEAM_PLAN_TOOL,
        FARM_TOOL,
        LEARN_TOOL,
        "ask_helper",
        "ask_researcher",
        "list_photos",
        "use_photo",
        TOOLSHED_TOOL,
        CHANGER_TOOL,
        FINISH_TOOL,
    }
)
"""Never on the toolshed's shelf: the user's own things (to-dos, photos,
projects, this PC), running the team, and the Content Farm. Agents get these
only when the user gives them on the agent's card."""
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
    MANAGE_AGENT_TOOL,
    WEATHER_TOOL,
    STUDY_VIDEO_TOOL,
    DESK_TOOL,
    VIDEO_NOTES_TOOL,
    TODO_TOOL,
    CALCULATE_TOOL,
    PROJECTS_TOOL,
    SYSTEM_STATUS_TOOL,
    APP_HELP_TOOL,
    LIST_PHOTOS_TOOL,
    LAB_TOOL,
    FARM_TOOL,
    CODE_TOOL,
    TEAM_PLAN_TOOL,
    SKILL_TOOL,
    MCP_TOOL,
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
MAIN_REMEMBER_SPEC = ToolSpec(
    name="remember",
    description=(
        "Save one durable fact into your own memory, which only you read. "
        "Set share to true to put it in the team memory every agent reads "
        "instead (for what the whole team should know)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "share": {"type": "boolean"},
        },
        "required": ["text"],
    },
)
MAIN_RECALL_SPEC = ToolSpec(
    name="recall",
    description=(
        "Search your own memory, the team memory, and every agent's own "
        "memory; each result says whose it is."
    ),
    parameters=TOOL_SPEC_BY_NAME["recall"].parameters,
)
LEAD_TOOLS: tuple[str, ...] = (
    ASK_AGENT_TOOL,
    TEAM_STATUS_TOOL,
    STOP_AGENT_TOOL,
    MANAGE_AGENT_TOOL,
)
"""What an agent on this PC gets to direct the agents on server AIs."""


_BLOCKING_STATUSES = frozenset({401, 403, 429, 451})


def _blocked_page(call: ToolCall, error: Exception) -> str:
    """Plain words for a site that turns automated readers away."""
    status = getattr(error, "status", None)
    if status is None and isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
    if call.name != "web_fetch" or status not in _BLOCKING_STATUSES:
        return ""
    url = str(call.arguments.get("url", ""))
    site = urlparse(url).hostname or "This site"
    site = site.removeprefix("www.")
    return (
        f"{site} blocks automated reading ({status}), so that page can't be "
        "read. Use another search result instead."
    )


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything one tool call is allowed to touch."""

    agent_id: str
    chat_id: str
    site_id: str | None = None
    agent_name: str = "Agent"
    agent_role: str = "assistant"
    memory_owner: str = ""
    """Set for an agent on a server AI: the memory area it reads and writes
    instead of the user's memory."""
    can_delegate: bool = False
    directs: tuple[str, ...] | None = None
    """The agents this one may direct, by name, or None for anyone (the main
    AI): an agent on this PC directs the agents on server AIs only."""
    main_memory: bool = False
    """The main AI keeps its own memory and reads every agent's."""

    def may_direct(self, name: str) -> bool:
        return self.directs is None or name.casefold() in {
            item.casefold() for item in self.directs
        }


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


def tool_tokens(names: Sequence[str]) -> int:
    """About how many tokens these tools' descriptions add to every message."""
    specs = [TOOL_SPEC_BY_NAME[name] for name in names if name in TOOL_SPEC_BY_NAME]
    text = json.dumps(
        [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in specs
        ]
    )
    return len(text) // 4


def tool_specs(
    names: Sequence[str],
    *,
    commands_enabled: bool = False,
    shared_memory: bool = False,
    delegation: bool = False,
    main_memory: bool = False,
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
        if main_memory and name == "remember":
            spec = MAIN_REMEMBER_SPEC
        elif main_memory and name == "recall":
            spec = MAIN_RECALL_SPEC
        elif shared_memory and name == "remember":
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
        all_tools: bool = False,
        image_transport: httpx.AsyncBaseTransport | None = None,
        photos: PhotoLibrary | None = None,
        ideas: IdeaBoard | None = None,
        desk: DeskBrowser | None = None,
        page_tryer: Callable[..., Awaitable[PageReport]] = try_page,
        screen: Callable[[ToolCall, ToolContext], Awaitable[ToolOutcome | None]]
        | None = None,
        new_project: Callable[[ToolContext, str], Awaitable[str]] | None = None,
        game_vault: GameVault | None = None,
        godot: GodotEngine | None = None,
    ) -> None:
        self._godot_engine = godot
        """Godot on this PC (downloaded once into the Repo vault)."""
        self._game_vault = game_vault
        """Kenney packs downloaded on this PC, kept for good."""
        # Sees each call first and may answer it instead (Studio turns a
        # hand-off back to the mcp tool when the user named a connected service).
        self._screen = screen
        self._new_project = new_project
        """Makes a project for a chat that has none and attaches it."""
        self._desk = desk
        self._try_page_with = page_tryer
        self._web = web_tools
        self._photos = photos
        self._ideas = ideas
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
        self._all_tools = all_tools
        self._image_transport = image_transport
        self._found_images: dict[str, FoundImage] = {}

    def granted(
        self, names: Sequence[str], *, role: str, chosen: bool = True
    ) -> tuple[str, ...]:
        """The tools an agent may use: its own, or every tool when it was
        chosen for every tool and the setting allows it.

        The Guide keeps its own few: it runs on the smallest model and only
        explains the app. Only the main AI manages the team.
        """
        if not self._all_tools or not chosen or role == "guide":
            return tuple(names)
        extra = (
            name
            for name in ALL_TOOL_NAMES
            if name not in names
            and name not in {TOOLSHED_TOOL, CHANGER_TOOL}
            and (role == MAIN_ROLE or name not in MAIN_ONLY_TOOLS)
        )
        return (*names, *extra)

    def refuses_itself(self, name: str) -> bool:
        """Calls the toolbox turns down on its own, with a clearer reason than
        "not one of your tools": web tools while web access is off, and
        handing work on (only the main AI and its leads may)."""
        return name in DELEGATION_TOOLS or (
            name in NETWORK_TOOLS and not self.web_enabled
        )

    @property
    def every_tool_allowed(self) -> bool:
        """The Every Tool setting: off, agents keep to their own tools."""
        return self._all_tools

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

    def delegation_allowed(self, role: str, names: Sequence[str] = ()) -> bool:
        """The main agent hands work on; so does any agent given ask_agent
        while agents may have every tool."""
        if self._delegate is None or role == "guide":
            return False
        # Any agent given ask_agent on its card may hand work to a teammate,
        # a subagent, or a repo agent, whether or not Every Tool is on.
        return role == MAIN_ROLE or ASK_AGENT_TOOL in names

    async def run(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        """Execute one tool call, converting every failure into tool output."""
        screened = await self._screen(call, context) if self._screen else None
        if screened is not None:
            return screened
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
                case "try_page":
                    return await self._try_page(call, context)
                case "start_project":
                    return await self._start_project(call, context)
                case "restore_file":
                    return await self._restore_file(call, context)
                case "calculate":
                    return self._calculate(call)
                case "find_images":
                    return await self._find_images(call)
                case "ui_library":
                    return self._ui_library(call)
                case "site_layouts":
                    return await self._site_layouts(call, context)
                case "ui_kit":
                    return await self._ui_kit(call, context)
                case "bug_library":
                    return self._bug_library(call)
                case "godot":
                    return await self._godot(call, context)
                case "game_assets":
                    return await self._game_assets(call, context)
                case "save_image":
                    return await self._save_image(call, context)
                case "ideas":
                    return await self._ideas_tool(call, context)
                case "list_photos":
                    return await self._list_photos(call)
                case "use_photo":
                    return await self._use_photo(call, context)
                case (
                    "todo"
                    | "list_projects"
                    | "system_status"
                    | "conversation"
                    | "learn"
                    | "knowledge"
                    | "agent_model"
                    | "manage_agent"
                    | "weather"
                    | "lab"
                    | "farm"
                    | "code_and_test"
                    | "team_plan"
                    | "skill"
                    | "mcp"
                ):
                    if self._assistant is None:
                        raise ValueError(f"{call.name} is not available here.")
                    return await self._assistant(call, context)
                case "study_video":
                    return await self._study_video(call, context)
                case "desktop_browser":
                    return await self._desktop_browser(call, context)
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
            ImageError,
            PhotoError,
            DeskError,
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
            text = _blocked_page(call, error) or f"{call.name} failed: {error}"
            if call.name == "find_images":
                text += f" {IMAGES_DOWN_NOTE}"
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
            raise ValueError(
                "File content must be text. Put the file in a fenced code block "
                "right after the JSON."
            )
        if '"requesting_agent"' in content and '"request_type"' in content:
            raise ValueError(
                "That is a message for a context-manager, not file content, and "
                "LCC has no context-manager: nothing was written. Read the "
                "project's files with list_files and read_file to get the context."
            )
        appending = call.arguments.get("append") is True
        try:
            existing: str | None = await self._sites.read(site_id, path)
        except SiteError:
            existing = None
        if appending:
            before = existing or ""
            joiner = "" if not before or before.endswith("\n") else "\n"
            content = f"{before}{joiner}{content}"
        added: list[str] = []
        if not appending and path.lower().endswith((".html", ".htm")):
            content, added = tidy_html(content)
        layered = False
        if not appending and path == "styles.css":
            try:
                before = await self._sites.read(site_id, path)
            except SiteError:
                before = ""
            base = f"@layer studio-base {{\n{STARTER_STYLES}}}\n\n"
            keeps_base = before.startswith(base) and "@layer studio-base" not in content
            if keeps_base or (
                before and is_starter(path, before) and not is_starter(path, content)
            ):
                # Small models write thin stylesheets; keep the designed base
                # underneath so whatever they leave out still looks finished.
                # In a cascade layer, the project's own rules always win.
                content = f"{base}/* Project styles */\n{content}"
                layered = True
        if content == existing:
            raise ValueError(f"{path} {NOTHING_CHANGED}")
        written = await self._sites.write(site_id, path, content)
        note = f" Studio added the missing {', '.join(added)}." if added else ""
        if layered:
            note += " Studio kept its base styles underneath yours."
        return ToolOutcome(
            text=f"{'Added to' if appending else 'Wrote'} {written.path} "
            f"({written.size} bytes).{note}",
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
        if first > len(lines):
            return ToolOutcome(
                text=(
                    f"{path} has only {len(lines)} lines, so there is nothing "
                    f"from line {first}. Read from start_line 1."
                ),
                data={**data, "start_line": first, "end_line": len(lines)},
            )
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
        content = original = await self._sites.read(site_id, path)
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
            if path.lower().endswith((".html", ".htm")):
                # A small model "adds" a section by pasting what is already
                # there after its heading, so the page shows it twice.
                there = set(text_lines(content)) - set(text_lines(old))
                copied = [line for line in text_lines(new) if line in there]
                if len(copied) >= REPEATED_LINES:
                    raise ValueError(
                        f"{label}new_text repeats {len(copied)} lines already in "
                        f"{path} (like {copied[0][:80]!r}), so that part would be "
                        "on the page twice. To change text that is there, put it "
                        "in old_text; to add something, add only what is new. No "
                        "edits were saved."
                    )
            found = content.count(old)
            replace_all = edit.get("replace_all") is True
            if found == 0:
                fixed = loose_replace(content, old, new)
                if fixed is None:
                    near = closest_text(content, old)
                    hint = (
                        f" The closest part of {path} is:\n{near}\nCopy old_text "
                        "exactly from there."
                        if near
                        else " Read the file again and copy the text exactly."
                    )
                    raise ValueError(
                        f"{label}old_text was not found in {path}.{hint} No edits "
                        "were saved."
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
        if content == original:
            raise ValueError(
                f"These edits leave {path} exactly as it was, so nothing changed. "
                "Make a real improvement, or finish if the work is done."
            )
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
        template = str(call.arguments.get("template", "")).strip()
        title = str(call.arguments.get("title") or "My project").strip()[:80]
        made = ""
        if not context.site_id and self._new_project is not None:
            # A chat with no project yet: this makes one and attaches it.
            made = await self._new_project(context, title)
        site_id = made or self._require_site(context)
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
        for path, source in template_libraries(template).items():
            if path not in existing or overwrite:
                await self._sites.copy_library(site_id, path, source)
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
        if made:
            lines.insert(0, f"Made the project {title} for this chat.")
        return ToolOutcome(
            text=" ".join(lines),
            data={
                "tool": START_PROJECT_TOOL,
                "site_id": site_id,
                "template": template,
                "written": written,
                "kept": kept,
                "attached_site": made,
            },
        )

    async def _ideas_tool(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        if self._ideas is None:
            raise ValueError("The ideas board isn't available here.")
        action = str(call.arguments.get("action") or "search").strip().lower()
        try:
            if action == "read":
                idea = await self._ideas.find(str(call.arguments.get("idea") or ""))
                text = describe_idea(idea, full=True)
                if idea.kind == "photo":
                    text += " Put it in the project with action use."
                elif idea.kind == "video":
                    text += (
                        " It's a video: look_reference sees its frames (and "
                        "what the user says about it)."
                        if idea.file
                        else " It's a video link: go by what the user says "
                        "about it (and its link)."
                    )
                return ToolOutcome(
                    text=text, data={"tool": IDEAS_TOOL, "idea": idea.id}
                )
            if action == "use":
                return await self._use_idea(call, context)
        except IdeaError as error:
            raise ValueError(str(error)) from error
        query = str(call.arguments.get("query") or "").strip()
        tag = str(call.arguments.get("tag") or "").strip()
        asked = str(call.arguments.get("category") or "").strip()
        # LCC's own agents look in their own category (and general) first: a
        # website's references don't steer the Lab.
        category = asked or ROLE_CATEGORIES.get(context.agent_role, "")
        found = await self._ideas.ideas(
            query, tag=tag, category=category, with_general=True
        )
        if not found and category and not asked:
            found = await self._ideas.ideas(query, tag=tag)
        data: JsonObject = {
            "tool": IDEAS_TOOL,
            "ideas": [idea.id for idea in found[:MAX_LISTED_IDEAS]],
        }
        if not found:
            every = await self._ideas.ideas()
            text = (
                "The user hasn't added anything to the ideas board yet; use your "
                "own judgment, at a business level."
                if not every
                else f"Nothing on the ideas board matches {query or tag!r}; "
                f"{len(every)} idea(s) are there (search with no query to see them)."
            )
            return ToolOutcome(text=text, data=data)
        lines = [
            f"{n}. {describe_idea(idea)}"
            for n, idea in enumerate(found[:MAX_LISTED_IDEAS], start=1)
        ]
        if len(found) > MAX_LISTED_IDEAS:
            lines.append(
                f"…and {len(found) - MAX_LISTED_IDEAS} more; narrow with query."
            )
        lines.append(
            "Go in the direction these point, with your own business-level work."
        )
        return ToolOutcome(text="\n".join(lines), data=data)

    async def _use_idea(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        assert self._ideas is not None
        site_id = self._require_site(context)
        idea = await self._ideas.find(str(call.arguments.get("idea") or ""))
        if idea.kind != "photo":
            raise ValueError(
                f"{idea.title} is a {idea.kind}, not a photo; only photos go "
                "into a project."
            )
        suffix = Path(idea.file).suffix
        wanted = str(call.arguments.get("path") or "").strip().lstrip("/")
        name = re.sub(r"[^a-z0-9]+", "-", idea.title.lower()).strip("-")[:50] or "idea"
        path = wanted or f"images/{name}{suffix}"
        if Path(path).suffix.lower() != suffix:
            path = f"{Path(path).with_suffix('')!s}{suffix}"
        saved = await self._sites.write_image(
            site_id, path, await self._ideas.read(idea)
        )
        text = (
            f"Put {idea.title} in the project as {saved.path}. It is "
            f'{idea.width}x{idea.height}: use width="{idea.width}" '
            f'height="{idea.height}" on the <img>.'
        )
        if idea.text:
            text += f" The user says about it: {idea.text[:400]}"
        return ToolOutcome(
            text=text,
            data={
                "tool": IDEAS_TOOL,
                "site_id": site_id,
                "path": saved.path,
                "idea": idea.id,
            },
        )

    async def _list_photos(self, call: ToolCall) -> ToolOutcome:
        if self._photos is None:
            raise ValueError("Business photos aren't available here.")
        query = str(call.arguments.get("query") or "").strip()
        photos = await self._photos.photos(query)
        data: JsonObject = {
            "tool": LIST_PHOTOS_TOOL,
            "photos": [photo.id for photo in photos[:MAX_LISTED_PHOTOS]],
        }
        if not photos:
            text = (
                f"No business photos match {query!r}."
                if query
                else "The user hasn't sent any business photos yet. They can "
                "attach photos to any message. Use find_images meanwhile."
            )
            return ToolOutcome(text=text, data=data)
        lines = [
            f"{index}. {describe_photo(photo)}"
            for index, photo in enumerate(photos[:MAX_LISTED_PHOTOS], start=1)
        ]
        if len(photos) > MAX_LISTED_PHOTOS:
            lines.append(
                f"…and {len(photos) - MAX_LISTED_PHOTOS} more; narrow with query."
            )
        lines.append("Put one on the site with use_photo.")
        return ToolOutcome(text="\n".join(lines), data=data)

    async def _use_photo(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        if self._photos is None:
            raise ValueError("Business photos aren't available here.")
        site_id = self._require_site(context)
        photo = await self._photos.find(str(call.arguments.get("photo") or ""))
        suffix = Path(photo.name).suffix
        wanted = str(call.arguments.get("path") or "").strip().lstrip("/")
        path = wanted or f"images/{photo.name}"
        if Path(path).suffix.lower() != suffix:
            path = f"{Path(path).with_suffix('')!s}{suffix}"
        saved = await self._sites.write_image(
            site_id, path, await self._photos.read(photo)
        )
        text = (
            f"Put {photo.name} in the project as {saved.path}. It is "
            f'{photo.width}x{photo.height}: use width="{photo.width}" '
            f'height="{photo.height}" on the <img>.'
        )
        if photo.note:
            text += f" The user says about it: {photo.note}"
        return ToolOutcome(
            text=text,
            data={
                "tool": USE_PHOTO_TOOL,
                "site_id": site_id,
                "path": saved.path,
                "photo_id": photo.id,
            },
        )

    async def _find_images(self, call: ToolCall) -> ToolOutcome:
        query = str(call.arguments.get("query", "")).strip()
        count = _int_arg(call.arguments.get("count")) or 6
        orientation = str(call.arguments.get("orientation", "")).strip()
        found = await find_images(
            query,
            count=count,
            orientation=orientation,
            transport=self._image_transport,
        )
        data: JsonObject = {
            "tool": FIND_IMAGES_TOOL,
            "query": query,
            "images": [
                {"url": image.url, "width": image.width, "height": image.height}
                for image in found
            ],
        }
        if not found:
            return ToolOutcome(
                text=f"No free photos for {query!r}. Try fewer or plainer words.",
                data=data,
            )
        for image in found:
            self._found_images[image.url] = image
        while len(self._found_images) > MAX_REMEMBERED_IMAGES:
            self._found_images.pop(next(iter(self._found_images)))
        lines = [
            f"{index}. {image.title or 'Photo'} ({image.width}x{image.height}) "
            f"{image.url}\n   Credit: {image.credit}"
            for index, image in enumerate(found, start=1)
        ]
        lines.append(
            "Save one with save_image (url, path like images/hero.jpg), then "
            "show its credit line in the footer."
        )
        return ToolOutcome(text="\n".join(lines), data=data)

    def _ui_library(self, call: ToolCall) -> ToolOutcome:
        action = str(call.arguments.get("action", "search")).strip() or "search"
        try:
            if action == "get":
                found = ui_piece(call.arguments.get("id"))
                code = found.html
                cut = len(code) > MAX_PIECE_CHARS
                if cut:
                    # Keep the designer's credit even when its comment is
                    # past the cut.
                    code = f"{ui_credit(found)}\n{code[:MAX_PIECE_CHARS]}"
                notes = [
                    f"{found.id}: a {found.kind} by {found.author} on Uiverse "
                    f"(MIT). Tags: {found.tags or 'none'}.",
                ]
                if found.tailwind:
                    notes.append(
                        "It is styled with Tailwind classes: rewrite them as CSS "
                        "in the site's stylesheet (the site has no Tailwind)."
                    )
                if found.script:
                    notes.append("It has a script: keep it only if it works offline.")
                if cut:
                    notes.append(
                        f"[Cut at {MAX_PIECE_CHARS:,} of {len(found.html):,} "
                        "characters: the end is missing, so finish or simplify "
                        "it, or pick a shorter piece.]"
                    )
                notes.append(
                    "Put the HTML where it belongs and the CSS in the site's "
                    "stylesheet; rename classes so they don't clash, use the "
                    "site's colour and font tokens, and keep the credit comment."
                )
                return ToolOutcome(
                    text="\n".join([*notes, "", code]),
                    data={"tool": UI_LIBRARY_TOOL, "id": found.id},
                )
            if action != "search":
                raise UiLibraryError("Use action search or get.")
            query = str(call.arguments.get("query", "")).strip()
            found_list = ui_search(
                query,
                kind=str(call.arguments.get("kind", "") or ""),
                count=_int_arg(call.arguments.get("count")) or 6,
                plain_only=str(call.arguments.get("tailwind", "")).casefold()
                not in {"true", "yes", "1"},
            )
        except UiLibraryError as error:
            return ToolOutcome(
                text=str(error), data={"tool": UI_LIBRARY_TOOL}, failed=True
            )
        data: JsonObject = {
            "tool": UI_LIBRARY_TOOL,
            "query": query,
            "ids": [item.id for item in found_list],
        }
        if not found_list:
            return ToolOutcome(
                text=f"No pieces match {query!r}. Try one plain word or a kind.",
                data=data,
            )
        lines = [
            f"{index}. {item.id} ({item.kind} by {item.author}"
            f"{', Tailwind' if item.tailwind else ''}): {item.tags or 'no tags'}"
            for index, item in enumerate(found_list, start=1)
        ]
        lines.append("Get one's code with action get and its id.")
        return ToolOutcome(text="\n".join(lines), data=data)

    async def _copy_kit(
        self,
        site_id: str,
        files: dict[str, bytes],
        *,
        overwrite: bool,
        replace_starters: bool = False,
        godot: bool = False,
        untouched: Callable[[str, bytes], bool] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Put files from one of Studio's libraries into the project.

        Text goes through write (so restore_file can undo it); pictures,
        fonts, sound, video and big library scripts are copied as they are.
        The project's own work is kept unless overwrite is set; with
        replace_starters, untouched starter files the kit doesn't use go.
        godot lets the Godot demos' models, skies and import notes in;
        untouched says which other existing files may be replaced.
        """
        existing = {item.path for item in await self._sites.files(site_id)}
        written: list[str] = []
        kept: list[str] = []
        for path, data in files.items():
            suffix = Path(path).suffix.lower()
            if (
                path in existing
                and not overwrite
                and not await self._replaceable(site_id, path, untouched)
            ):
                kept.append(path)
                continue
            text = None
            if suffix in TEXT_KIT_SUFFIXES and len(data) <= MAX_FILE_BYTES:
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = None  # not UTF-8: copied as it is
            if text is not None:
                await self._sites.write(site_id, path, text)
            else:
                await self._sites.copy_library_bytes(site_id, path, data, godot=godot)
            written.append(path)
        if replace_starters:
            for path in sorted(existing - set(files)):
                if Path(path).suffix.lower() in TEXT_KIT_SUFFIXES and is_starter(
                    path, await self._sites.read(site_id, path)
                ):
                    await self._sites.delete(site_id, path)
        return written, kept

    async def _replaceable(
        self,
        site_id: str,
        path: str,
        untouched: Callable[[str, bytes], bool] | None,
    ) -> bool:
        """Whether an existing file is a placeholder a kit may replace: a web
        starter file, or one untouched says is still as a kit wrote it."""
        if Path(path).suffix.lower() in TEXT_KIT_SUFFIXES and is_starter(
            path, await self._sites.read(site_id, path)
        ):
            return True
        if untouched is None:
            return False
        try:
            current = await self._sites.read_bytes(site_id, path)
        except SiteError:
            return False
        return untouched(path, current)

    async def _site_layouts(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        action = str(call.arguments.get("action") or "list").strip() or "list"
        try:
            if action == "list":
                found = find_layouts(str(call.arguments.get("kind") or ""))
                lines = [
                    f"{item.id} ({item.kind}): {item.name}. {item.about}. Pages: "
                    f"{', '.join(item.pages)}."
                    for item in found
                ]
                lines.append("Copy one into the project with action use and its id.")
                return ToolOutcome(
                    text="\n".join(lines),
                    data={
                        "tool": SITE_LAYOUTS_TOOL,
                        "layouts": [item.id for item in found],
                    },
                )
            if action != "use":
                raise LayoutError("Use action list or use.")
            chosen = find_layout(call.arguments.get("layout"))
        except LayoutError as error:
            return ToolOutcome(
                text=str(error), data={"tool": SITE_LAYOUTS_TOOL}, failed=True
            )
        title = str(call.arguments.get("title") or "").strip()[:80]
        made = ""
        if not context.site_id and self._new_project is not None:
            made = await self._new_project(context, title or chosen.name)
        site_id = made or self._require_site(context)
        files = layout_files(chosen)
        if title:
            files = {
                path: name_layout(data, title) if path.endswith(".html") else data
                for path, data in files.items()
            }
        written, kept = await self._copy_kit(
            site_id,
            files,
            overwrite=call.arguments.get("overwrite") is True,
            replace_starters=True,
        )
        lines = [
            f"Copied the {chosen.name} layout ({len(written)} files; pages: "
            f"{', '.join(chosen.pages)}).",
            LAYOUT_SAMPLE_NOTE,
        ]
        if kept:
            lines.append(
                f"Kept your existing {', '.join(kept)} (set overwrite to replace them)."
            )
        lines.append("Then run check_project and try_page.")
        if made:
            lines.insert(0, f"Made the project {title or chosen.name} for this chat.")
        return ToolOutcome(
            text=" ".join(lines),
            data={
                "tool": SITE_LAYOUTS_TOOL,
                "site_id": site_id,
                "layout": chosen.id,
                "written": written,
                "kept": kept,
                "attached_site": made,
            },
        )

    async def _godot(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        action = str(call.arguments.get("action") or "demos").strip() or "demos"
        data: JsonObject = {"tool": GODOT_TOOL, "action": action}
        try:
            if action == "demos":
                found = find_demos(str(call.arguments.get("query") or ""), 8)
                data["demos"] = [item.id for item in found]
                lines = [
                    f"{item.id}: {item.title}. {item.about[:200]}" for item in found
                ]
                lines.append(
                    "Read one with action demo (id), then one of its files with file."
                    if found
                    else "No demo matches: try one plain word."
                )
                return ToolOutcome(text="\n".join(lines), data=data)
            if action == "demo":
                return self._godot_demo(call, data)
            if action == "use":
                return await self._godot_use(call, context, data)
            engine = self._godot_engine
            if engine is None:
                raise GodotError("Godot isn't available in this FCC.")
            if action == "setup":
                program = await engine.install()
                return ToolOutcome(text=f"Godot is ready: {program.name}.", data=data)
            if action == "start":
                return await self._godot_start(call, context, data)
            site_id = self._require_site(context)
            project = self._sites.directory(site_id)
            if action == "check":
                report = await engine.check(project)
                data.update({"passed": report.passed, "problems": report.problems})
                if report.passed:
                    text = "PASSED: Godot loaded every script and scene and ran the game with no errors."
                    if report.warnings:
                        text += " Warnings:\n" + "\n".join(report.warnings[:15])
                    return ToolOutcome(text=text, data=data)
                return ToolOutcome(
                    text=f"FAILED ({len(report.problems)}). Fix each, then check again:\n"
                    + "\n".join(report.problems[:25]),
                    data=data,
                    failed=True,
                )
            if action == "frames":
                seconds = call.arguments.get("seconds")
                length = float(seconds) if isinstance(seconds, int | float) else 3.0
                if not math.isfinite(length):
                    length = 3.0
                length = min(max(length, 0.3), 20.0)
                shot = self._godot_engine_root() / "shots" / f"{site_id}.png"
                await engine.frames(project, shot, seconds=length)
                await self._sites.copy_library_bytes(
                    site_id, "screenshots/frame.png", shot.read_bytes()
                )
                data["picture"] = "screenshots/frame.png"
                return ToolOutcome(
                    text="Saved the game's frame after "
                    f"{length:g} seconds to screenshots/frame.png.",
                    data=data,
                )
            if action == "export":
                target = self._godot_engine_root() / "exports" / site_id / "game.exe"
                made = await engine.export(project, target)
                data["export"] = str(made)
                return ToolOutcome(
                    text=f"Exported the game: {made}. The owner can run it on this PC.",
                    data=data,
                )
            raise GodotLibraryError(
                "Use action start, check, frames, export, demos, demo, use or setup."
            )
        except (GodotLibraryError, GodotError) as error:
            return ToolOutcome(text=str(error), data=data, failed=True)

    def _godot_engine_root(self) -> Path:
        assert self._godot_engine is not None
        return self._godot_engine.root

    def _godot_demo(self, call: ToolCall, data: JsonObject) -> ToolOutcome:
        item = godot_demo(call.arguments.get("id"))
        wanted = str(call.arguments.get("file") or "").strip()
        data["id"] = item.id
        if wanted:
            if wanted not in item.files:
                raise GodotLibraryError(
                    f"{item.id} has no text file {wanted!r}. Files: "
                    + ", ".join(sorted(item.files)[:40])
                )
            text = item.files[wanted]
            return ToolOutcome(
                text=f"{item.id}/{wanted} (Godot demo, MIT):\n{text[:GODOT_MAX_SHOW]}",
                data=data,
            )
        scripts = [path for path in sorted(item.files) if path.endswith(".gd")]
        shown = "\n\n".join(
            f"--- {path}\n{item.files[path][:3000]}" for path in scripts[:3]
        )
        art = godot_demo_art(item.id)
        size = sum(entry.size for entry in art)
        named = [
            entry.path for entry in art if not entry.path.endswith((".import", ".uid"))
        ]
        lines = [
            f"{item.id}: {item.title} (Godot demo, MIT). {item.about}",
            "Text files: " + ", ".join(sorted(item.files)),
            f"Art, sound and models it ships with ({len(art)} files, "
            f"{size / 1_000_000:.1f} MB): "
            + ", ".join(named[:30])
            + ". Action use copies the whole demo, art included, into the project.",
            shown[:GODOT_MAX_SHOW],
        ]
        return ToolOutcome(text="\n".join(lines), data=data)

    async def _godot_use(
        self, call: ToolCall, context: ToolContext, data: JsonObject
    ) -> ToolOutcome:
        item = godot_demo(call.arguments.get("id"))
        files = await anyio.to_thread.run_sync(godot_demo_project, item.id)
        title = str(call.arguments.get("title") or "").strip()[:80]
        made = ""
        if not context.site_id and self._new_project is not None:
            made = await self._new_project(context, title or item.title)
        site_id = made or self._require_site(context)
        written, kept = await self._copy_kit(
            site_id,
            files,
            overwrite=call.arguments.get("overwrite") is True,
            replace_starters=True,
            godot=True,
            untouched=untouched_starter,
        )
        # A starter's scenes and scripts the demo doesn't use go too, so the
        # project is the demo; changed ones stay.
        for path in sorted(
            {entry.path for entry in await self._sites.files(site_id)} - set(files)
        ):
            if Path(path).suffix.lower() in {".gd", ".tscn"} and untouched_starter(
                path, await self._sites.read_bytes(site_id, path)
            ):
                await self._sites.delete(site_id, path)
        data.update(
            {
                "id": item.id,
                "site_id": site_id,
                "written": len(written),
                "kept": kept,
                "attached_site": made,
            }
        )
        lines = [
            f"Copied Godot's {item.title} demo ({item.id}, MIT; {len(written)} "
            "files: code, scenes, art, sound and models). Keep LICENSE-godot-demos.txt "
            "and the art's own licence files and README credits, change it into "
            "the game asked for, then run action check and fix every problem.",
        ]
        if kept:
            lines.append(
                f"Kept your existing {', '.join(kept[:20])} (set overwrite to replace)."
            )
        return ToolOutcome(text=" ".join(lines), data=data)

    async def _godot_start(
        self, call: ToolCall, context: ToolContext, data: JsonObject
    ) -> ToolOutcome:
        name = str(call.arguments.get("starter") or "platformer-2d")
        title = str(call.arguments.get("title") or "").strip()[:80]
        files = godot_starter_files(name, title)
        made = ""
        if not context.site_id and self._new_project is not None:
            made = await self._new_project(context, title or "My game")
        site_id = made or self._require_site(context)
        written, kept = await self._copy_kit(
            site_id,
            files,
            overwrite=call.arguments.get("overwrite") is True,
            replace_starters=True,
        )
        data.update(
            {
                "site_id": site_id,
                "written": written,
                "kept": kept,
                "attached_site": made,
            }
        )
        lines = [
            f"Started a Godot 4 {name} game ({len(written)} files). {GODOT_STARTERS[name]}",
            "Change it into the game asked for, then run action check and fix every "
            "problem; action frames shows how it looks.",
        ]
        if kept:
            lines.append(
                f"Kept your existing {', '.join(kept)} (set overwrite to replace)."
            )
        return ToolOutcome(text=" ".join(lines), data=data)

    def _bug_library(self, call: ToolCall) -> ToolOutcome:
        action = str(call.arguments.get("action") or "find").strip() or "find"
        data: JsonObject = {"tool": BUG_LIBRARY_TOOL, "action": action}
        try:
            if action == "find":
                found = find_bugs(
                    str(call.arguments.get("query") or ""),
                    repo=str(call.arguments.get("project") or ""),
                    count=_int_arg(call.arguments.get("count")) or 8,
                )
                data["bugs"] = [item.id for item in found]
                lines = [
                    f"{item.id} ({item.size}; fix touches {', '.join(item.files) or '?'}): "
                    f"{item.title[:160]}"
                    for item in found
                ]
                lines.append(
                    "Read one with action get (id)."
                    if found
                    else "Nothing alike: try fewer or plainer words."
                )
                return ToolOutcome(text="\n".join(lines), data=data)
            if action != "get":
                raise BugLibraryError("Use action find or get.")
            item = library_bug(call.arguments.get("id"))
        except BugLibraryError as error:
            return ToolOutcome(text=str(error), data=data, failed=True)
        part = str(call.arguments.get("part") or "all")
        sections = {
            "issue": f"The issue:\n{clip_bug(item.issue)}",
            "fix": f"The fix the project merged:\n{clip_bug(item.fix)}",
            "test": (
                f"The test that proves it (fails before, passes after: "
                f"{', '.join(item.fails[:6])}):\n{clip_bug(item.test)}"
            ),
        }
        chosen = [sections[part]] if part in sections else list(sections.values())
        head = (
            f"{item.id} from {item.repo} (licence {licence_of(item.repo)}; "
            f"{item.size}). A real bug from another project, as an example only: "
            "write FCC's own fix and test."
        )
        data.update({"id": item.id, "repo": item.repo})
        return ToolOutcome(text="\n\n".join([head, *chosen]), data=data)

    async def _ui_kit(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        action = str(call.arguments.get("action") or "icons").strip() or "icons"
        data: JsonObject = {"tool": UI_KIT_TOOL, "action": action}
        try:
            if action == "icons":
                found = find_icons(
                    str(call.arguments.get("query") or ""),
                    _int_arg(call.arguments.get("count")) or 20,
                )
                data["icons"] = [name for name, _ in found]
                lines = [f"{name} ({category})" for name, category in found]
                lines.append(
                    "Copy them with action use_icons (names)."
                    if found
                    else "No icon matches: try one plain word."
                )
                return ToolOutcome(text="\n".join(lines), data=data)
            if action == "use_icons":
                raw = call.arguments.get("names")
                names = [str(item) for item in raw] if isinstance(raw, list) else []
                if not names:
                    raise UiKitError("List the icon names to copy (from action icons).")
                files = {
                    f"assets/icons/{name.strip()}.svg": icon_file(name)
                    for name in names[:40]
                }
            elif action in {"app", "add"}:
                files = (
                    starter_files(str(call.arguments.get("title") or "")[:80])
                    if action == "app"
                    else kit_files()
                )
            else:
                raise UiKitError("Use action app, add, icons or use_icons.")
        except UiKitError as error:
            return ToolOutcome(text=str(error), data=data, failed=True)
        made = ""
        if not context.site_id and self._new_project is not None and action == "app":
            made = await self._new_project(
                context, str(call.arguments.get("title") or "") or "App"
            )
        site_id = made or self._require_site(context)
        written, kept = await self._copy_kit(
            site_id,
            files,
            overwrite=call.arguments.get("overwrite") is True,
            replace_starters=action == "app",
        )
        note = {
            "app": "Started the app screens (index.html, app.js, styles.css) on "
            "Tabler. Replace the sample names and numbers with the app's own, "
            "and set --app-accent in styles.css.",
            "add": "Added Tabler: link vendor/tabler/tabler.min.css in the head "
            "and vendor/tabler/tabler.min.js before </body>.",
            "use_icons": 'Copied the icons: use <img src="assets/icons/NAME.svg" '
            'alt="" width="20" height="20">, or paste the SVG inline so it '
            "takes the text colour.",
        }[action]
        lines = [note, f"Wrote {len(written)} files."]
        if kept:
            lines.append(
                f"Kept your existing {', '.join(kept)} (set overwrite to replace)."
            )
        data.update(
            {
                "site_id": site_id,
                "written": written,
                "kept": kept,
                "attached_site": made,
            }
        )
        return ToolOutcome(text=" ".join(lines), data=data)

    async def _game_assets(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        action = str(call.arguments.get("action") or "find").strip() or "find"
        query = str(call.arguments.get("query") or "").strip()
        count = _int_arg(call.arguments.get("count"))
        data: JsonObject = {"tool": GAME_ASSETS_TOOL, "action": action}
        vault = self._game_vault
        try:
            if action == "find":
                found = find_game_files(
                    query, kind=str(call.arguments.get("kind") or ""), count=count or 10
                )
                lines = [
                    f"{index}. {item.id}: {path}"
                    + ("" if game_ready(item, vault) else " (download the pack first)")
                    for index, (item, path) in enumerate(found, start=1)
                ]
                data["files"] = [f"{item.id}/{path}" for item, path in found]
                lines.append(
                    "Copy what you need with action use (pack, files)."
                    if found
                    else f"Nothing matches {query!r}: try one plain word."
                )
                return ToolOutcome(text="\n".join(lines), data=data)
            if action == "packs":
                found = find_game_packs(
                    query, str(call.arguments.get("category") or "")
                )
                lines = [
                    f"{item.id} ({item.category}, {len(item.files)} files"
                    + (", ready" if game_ready(item, vault) else ", download first")
                    + ")"
                    for item in found[:60]
                ]
                if len(found) > 60:
                    lines.append(
                        f"…and {len(found) - 60} more: add words to narrow it."
                    )
                data["packs"] = [item.id for item in found]
                return ToolOutcome(
                    text="\n".join(lines) or "No packs match.", data=data
                )
            if action == "download":
                return await self._download_pack(game_pack(call.arguments.get("pack")))
            if action == "use":
                return await self._use_pack(call, context)
            if action == "examples":
                found_examples = find_game_examples(query, count or 8)
                lines = [f"{item.id} ({item.topic})" for item in found_examples]
                lines.append(
                    "Read one with action example and its id."
                    if found_examples
                    else f"No examples match {query!r}."
                )
                data["examples"] = [item.id for item in found_examples]
                return ToolOutcome(text="\n".join(lines), data=data)
            if action == "example":
                item = game_example(call.arguments.get("id"))
                code = item.code[:MAX_EXAMPLE_CHARS]
                note = (
                    f"Phaser example {item.id} (MIT). Its assets/... files are "
                    "Phaser's own art, which isn't free to use: load Kenney files "
                    "you copied with game_assets instead."
                )
                if len(item.code) > MAX_EXAMPLE_CHARS:
                    note += f" [Cut at {MAX_EXAMPLE_CHARS:,} characters.]"
                data["id"] = item.id
                return ToolOutcome(text=f"{note}\n\n{code}", data=data)
            raise GameLibraryError(
                "Use action find, packs, use, download, examples or example."
            )
        except GameLibraryError as error:
            return ToolOutcome(text=str(error), data=data, failed=True)

    async def _download_pack(self, item: GamePack) -> ToolOutcome:
        data: JsonObject = {
            "tool": GAME_ASSETS_TOOL,
            "action": "download",
            "pack": item.id,
        }
        if item.shipped or (self._game_vault and self._game_vault.has(item)):
            return ToolOutcome(text=f"{item.name} is already on this PC.", data=data)
        if self._game_vault is None:
            raise GameLibraryError("Packs can't be downloaded here.")
        if not item.url.startswith(KENNEY_ASSETS) or item.size > MAX_GAME_PACK_BYTES:
            raise GameLibraryError(f"{item.name} can't be downloaded safely.")
        async with httpx.AsyncClient(
            transport=self._image_transport, timeout=120.0, follow_redirects=True
        ) as client:
            try:
                response = await client.get(item.url)
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise GameLibraryError(
                    f"Couldn't download {item.name} from kenney.nl ({error})."
                ) from error
        if len(response.content) > MAX_GAME_PACK_BYTES:
            raise GameLibraryError(f"{item.name} came back too big to keep.")
        vault = self._game_vault
        await anyio.to_thread.run_sync(vault.keep, item, response.content)
        data["bytes"] = len(response.content)
        return ToolOutcome(
            text=f"Downloaded {item.name} ({len(response.content) // 1000:,} KB, "
            "checksum matches) and kept it on this PC. Now use it.",
            data=data,
        )

    async def _use_pack(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        item = game_pack(call.arguments.get("pack"))
        files = call.arguments.get("files")
        asked = (
            [files]
            if isinstance(files, str)
            else [str(entry) for entry in files]
            if isinstance(files, list)
            else []
        )
        wanted = choose_game_files(item, asked)
        if not wanted:
            raise GameLibraryError(
                f"Say which of {item.name}'s files to copy (paths from find, a "
                "folder, or a word)."
            )
        if len(wanted) > MAX_KIT_FILES:
            raise GameLibraryError(
                f"That is {len(wanted)} files: pick fewer (at most {MAX_KIT_FILES})."
            )
        licence = [path for path in item.files if path.casefold().startswith("license")]
        contents = await anyio.to_thread.run_sync(
            read_game_files, item, [*wanted, *licence[:1]], self._game_vault
        )
        site_id = self._require_site(context)
        placed = {game_path(item, path): body for path, body in contents.items()}
        written, kept = await self._copy_kit(site_id, placed, overwrite=True)
        sounds = [path for path in written if path.endswith((".mp3", ".ogg", ".wav"))]
        lines = [
            f"Copied {len(written)} files from {item.name} into assets/{item.id}/ "
            "(load them by these paths):"
        ]
        lines.extend(f"- {path}" for path in written[:25])
        if len(written) > 25:
            lines.append(f"- …and {len(written) - 25} more")
        if any(path.endswith(".ogg") for path in sounds):
            lines.append(
                ".ogg sounds play on computers but not on iPhones: prefer the "
                "shipped packs' .mp3 sounds for phone games."
            )
        lines.append(
            "Load images with this.load.image or this.load.spritesheet, sounds "
            "with this.load.audio (paths as above)."
        )
        return ToolOutcome(
            text="\n".join(lines),
            data={
                "tool": GAME_ASSETS_TOOL,
                "action": "use",
                "pack": item.id,
                "written": written,
                "kept": kept,
            },
        )

    async def _save_image(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        url = str(call.arguments.get("url", "")).strip()
        path = str(call.arguments.get("path", "")).strip().lstrip("/")
        if not path:
            raise ValueError("Say where to save it, e.g. images/hero.jpg.")
        content, suffix = await download_image(
            url,
            allow_private=self._egress.allow_private_network_targets,
            transport=self._image_transport,
        )
        stem, dot, given = path.rpartition(".")
        if not dot or f".{given.lower()}" not in IMAGE_SUFFIXES:
            path = f"{path}{suffix}"
        elif f".{given.lower()}" != suffix and not (
            suffix == ".jpg" and given.lower() == "jpeg"
        ):
            path = f"{stem}{suffix}"
        saved = await self._sites.write_image(site_id, path, content)
        found = self._found_images.get(url)
        text = f"Saved {saved.path} ({saved.size // 1000} KB)."
        data: JsonObject = {
            "tool": SAVE_IMAGE_TOOL,
            "site_id": site_id,
            "path": saved.path,
            "bytes": saved.size,
        }
        if found is not None:
            text += (
                f" It is {found.width}x{found.height}: use "
                f'width="{found.width}" height="{found.height}" on the <img> '
                "(CSS can still size it). Credit it in the footer: "
                f"{found.credit}."
            )
            data["credit"] = found.credit
        return ToolOutcome(text=text, data=data)

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
        local = self._videos.local_file(url)
        if local is not None and context.memory_owner:
            raise ValueError(
                "Videos on this PC are only watched by agents that think on "
                "this PC: ask the main AI or the Helper."
            )
        shown = ""
        if call.arguments.get("show") is True and self._desk is not None:
            try:
                if local is not None:
                    await self._desk.show_file(local, by=context.agent_name)
                else:
                    await self._desk.go(url, by=context.agent_name)
                await self._desk.video("play", by=context.agent_name)
                shown = "Playing it in the desktop browser.\n\n"
            except DeskError as error:
                shown = f"(Could not show it in the desktop browser: {error})\n\n"
        note = await self._videos.study(
            url, focus=focus, source="agent", studied_by=context.agent_name
        )
        return ToolOutcome(
            text=shown + render_note(note),
            data={
                "tool": STUDY_VIDEO_TOOL,
                "video": note.id,
                "url": note.url,
                "title": note.title,
            },
        )

    async def _desktop_browser(
        self, call: ToolCall, context: ToolContext
    ) -> ToolOutcome:
        desk = self._desk
        if desk is None:
            raise ValueError("The desktop browser is not available here.")
        args = call.arguments
        action = str(args.get("action") or "").strip().lower()
        by = context.agent_name
        part = 1
        query = ""
        match action:
            case "search":
                where = str(args.get("where") or "web")
                shot = await desk.search(
                    str(args.get("query") or ""), where=where, by=by
                )
            case "open":
                shot = await desk.go(str(args.get("url") or ""), by=by)
            case "read":
                shot = await desk.look(part=_int_arg(args.get("part")) or 0, by=by)
                part = desk.state.part
            case "links":
                shot = await desk.look(by=by)
                query = str(args.get("query") or "").strip()
            case "click":
                number = _int_arg(args.get("number")) or 0
                shot = await desk.follow(number, by=by)
            case "scroll":
                down = str(args.get("direction") or "down") != "up"
                shot = await desk.scroll(down=down, by=by)
                part = desk.state.part
            case "back":
                shot = await desk.back(by=by)
            case "play" | "pause":
                shot = await desk.video(action, by=by)
            case "buttons":
                found = await desk.buttons()
                text = (
                    "Buttons you may press: "
                    + ", ".join(f"'{label}'" for _, label in found)
                    if found
                    else "No harmless buttons to press on this page."
                )
                return ToolOutcome(
                    text=text, data={"tool": DESK_TOOL, "action": action}
                )
            case "press":
                shot = await desk.press(str(args.get("text") or ""), by=by)
            case "watch":
                return await self._desk_watch(call, context)
            case "close":
                await desk.close()
                return ToolOutcome(
                    text="Closed the desktop browser.",
                    data={"tool": DESK_TOOL, "action": action},
                )
            case _:
                raise ValueError(
                    "Pick an action: search, open, read, links, click, scroll, "
                    "back, play, pause, watch, buttons, press or close."
                )
        return ToolOutcome(
            text=render_desk(shot, part=part, query=query),
            data={
                "tool": DESK_TOOL,
                "action": action,
                "url": shot.url,
                "title": shot.title,
            },
        )

    async def _desk_watch(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        """Play the video on the page and study it into notes."""
        desk = self._desk
        if desk is None or self._videos is None:
            raise ValueError("Watching videos is not available here.")
        shot = desk.state.shot
        if shot is None:
            raise DeskError("Open a video page first (search with where youtube).")
        if not shot.video:
            shot = await desk.look(by=context.agent_name)
        if not shot.video:
            raise DeskError("This page has no video: open one first.")
        await desk.video("play", by=context.agent_name)
        focus = str(call.arguments.get("focus") or "").strip()
        note = await self._videos.study(
            shot.url, focus=focus, source="agent", studied_by=context.agent_name
        )
        return ToolOutcome(
            text="Playing it in the desktop browser.\n\n" + render_note(note),
            data={
                "tool": DESK_TOOL,
                "action": "watch",
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
        pictures = [
            item.path
            for item in await self._sites.files(site_id)
            if item.path.lower().endswith(PICTURE_SUFFIXES)
            and not item.path.startswith("lab/")
        ]
        notes = polish_notes(contents, pictures)
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

    async def _try_page(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        if self._try_page_with is try_page and not page_try_ready():
            raise ValueError(
                "Trying pages needs the desktop browser part. Run the Windows "
                "installer again, or: uv sync --extra studio_desk"
            )
        page = str(call.arguments.get("page") or "index.html")
        steps = parse_steps(call.arguments.get("steps"))
        try:
            report = await self._try_page_with(
                self._sites.directory(site_id),
                page,
                steps,
                phone=not bool(call.arguments.get("desktop")),
            )
        except PageTryError as error:
            raise ValueError(str(error)) from error
        return ToolOutcome(
            text=report.render(),
            data={
                "tool": TRY_PAGE_TOOL,
                "site_id": site_id,
                "page": report.page,
                "passed": report.passed,
                "problems": report.problems[:20],
            },
        )

    async def _check_project(self, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        contents: dict[str, str] = {}
        others: list[str] = []
        for item in await self._sites.files(site_id):
            if item.path.startswith("lab/"):
                continue
            # Libraries (three.js) are other people's tested code: they count
            # as present for links, but aren't checked line by line.
            if not item.path.endswith(CHECKED_FILES) or item.path.startswith("vendor/"):
                others.append(item.path)
                continue
            try:
                contents[item.path] = await self._sites.read(site_id, item.path)
            except SiteError, UnicodeDecodeError:
                continue
        problems = check_project(contents, others=others)
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
        if context.memory_owner:
            # An agent on a server AI: its own area, or the server team's
            # shared memory, never the memory on this PC.
            team = self._memory.shared_enabled and not private
            entry = await self._memory.remember(
                SERVER_SHARED_ID if team else context.memory_owner,
                text,
                tags=tags,
                source="tool",
                chat_id=context.chat_id,
                author=context.agent_name,
            )
            if entry is None:
                raise ValueError("Nothing to remember.")
            where = (
                "the server agents' shared memory" if team else "your own memory area"
            )
            return ToolOutcome(
                text=f"Saved to {where}: {entry.text}",
                data={"tool": "remember", "memory_id": entry.id, "shared": team},
            )
        if context.main_memory:
            private = call.arguments.get("share") is not True
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
                context.memory_owner or context.agent_id,
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
        everyone = context.main_memory and not context.memory_owner
        entries = await self._memory.recall(
            context.memory_owner or context.agent_id, query, everyone=everyone
        )
        if not entries:
            return ToolOutcome(
                text="Nothing relevant in memory.",
                data={"tool": "recall", "query": query, "hits": 0},
            )
        names = await self._memory.owner_names() if everyone else {}

        def whose(entry: MemoryEntry) -> str:
            if entry.agent_id == context.agent_id:
                return "(yours) " if everyone else ""
            if entry.agent_id == SHARED_MEMORY_ID:
                return "(team) "
            if entry.agent_id == SERVER_SHARED_ID:
                return "(server team) "
            if entry.agent_id == context.memory_owner:
                return ""
            return f"({names.get(entry.agent_id, 'an agent')}) "

        return ToolOutcome(
            text="\n".join(f"- {whose(entry)}{entry.text}" for entry in entries),
            data={"tool": "recall", "query": query, "hits": len(entries)},
        )

    async def _delegate_call(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        asked = str(call.arguments.get("agent") or "").strip().lstrip("@").strip()
        if asked and asked.casefold() == context.agent_name.casefold():
            raise ValueError(
                f"You are {context.agent_name}: do this yourself with your own tools."
            )
        if self._delegate is None or not (
            context.agent_role == MAIN_ROLE or context.can_delegate
        ):
            raise ValueError(
                "Only the main AI, and agents on this PC for agents on server "
                "AIs, can hand work to other agents here."
            )
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
                "This conversation has no project yet. Make one with "
                "start_project (a title and a template), then work in it."
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


CLOSEST_LINES = 12
"""Lines of the file shown when an edit's old_text isn't in it."""


def closest_text(content: str, old: str) -> str:
    """The part of the file most like old_text, as many lines long (up to
    CLOSEST_LINES), so a model that misremembered a line can copy the real
    one; empty when nothing is close."""
    wanted = [line.strip() for line in old.strip("\n").splitlines() if line.strip()]
    lines = content.splitlines()
    bare = [line.strip() for line in lines]
    if not wanted or not lines:
        return ""
    head = wanted[:3]
    best, score = 0, 0.0
    for start, line in enumerate(bare):
        if not line:
            continue
        window = [text for text in bare[start:] if text][: len(head)]
        ratio = sum(
            difflib.SequenceMatcher(None, want, have).ratio()
            for want, have in zip(head, window, strict=False)
        ) / len(head)
        if ratio > score:
            best, score = start, ratio
    if score < 0.6:
        return ""
    size = min(max(len(old.strip("\n").splitlines()), 1), CLOSEST_LINES)
    return "\n".join(lines[best : best + size])


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
