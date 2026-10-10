"""The bounded tool loop every Studio agent runs."""

import asyncio
import functools
import json
import re
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Concatenate

from loguru import logger

from free_claude_code.core.json_types import JsonObject

from .call_guard import guarded
from .convo_notes import NOTES_HEADER, NotesKeeper
from .farm.requests import farm_job
from .lab.bench import LAB_PROMPT
from .lab.requests import lab_job
from .llm import (
    THINKING_ONLY,
    ChatMessage,
    LLMReply,
    StudioLLMError,
    StudioModelRouter,
    ToolCall,
    ToolSpec,
    model_missing,
    unreadable_tool_call,
)
from .memory import MemoryService, server_area
from .models import Agent, AgentRun, Chat, Message, TunePack, now_ms
from .recall_messages import Found, recall_note, search
from .store import StudioStore
from .team_models import model_label
from .tools import (
    CHECK_PROJECT_TOOL,
    COMMAND_TOOL,
    FINISH_TOOL,
    LEAD_TOOLS,
    MAIN_ROLE,
    NOT_IN_THE_SHED,
    PARALLEL_TOOLS,
    SEALED_TOOLS,
    TOOL_SPEC_BY_NAME,
    TOOLSHED_TOOL,
    AgentToolbox,
    ToolContext,
    ToolOutcome,
    tool_specs,
)
from .tuning import pack_exemplars, pack_system_text

HISTORY_MIN = 40
HISTORY_STEP = 20
MAX_UNNOTED = 60
"""How far past its usual start the view may reach while notes catch up."""
TOOL_CONTEXT_CHARS = 300
EARLIER_CHATS = 5
EARLIER_CHAT_MESSAGES = 400


def _trim(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= TOOL_CONTEXT_CHARS else f"{flat[:TOOL_CONTEXT_CHARS]}…"


WRITE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "delete_file",
        "start_project",
        "restore_file",
        "save_image",
        "use_photo",
    }
)
CONTENT_WRITES = frozenset({"write_file", "edit_file"})
"""Writes that put content in a file (starting a template does not)."""
WRITE_NOTE = (
    "(Studio) Nothing is built yet: the files still hold the starter template. "
    "Write the real page now with write_file (path index.html), using what the "
    "task and the team shared, then finish."
)
_FENCE = re.compile(r"```(html|css|javascript|js)[^\n]*\n(.*?)```", re.S | re.I)
_FENCE_PATHS = {
    "html": "index.html",
    "css": "styles.css",
    "javascript": "app.js",
    "js": "app.js",
}


def fenced_files(text: str) -> list[tuple[str, str]]:
    """Whole files a reply pasted in fenced blocks: a full page (index.html),
    a stylesheet (styles.css), or a script (app.js)."""
    found: dict[str, str] = {}
    for match in _FENCE.finditer(text):
        kind, body = match.group(1).lower(), match.group(2).strip()
        if kind == "html" and not re.search(r"<(?:!doctype|html|body)\b", body, re.I):
            continue  # A snippet, not a page.
        if len(body) < 40:
            continue
        found[_FENCE_PATHS[kind]] = body + "\n"
    return list(found.items())


REPEAT_FAILURES = 2
REPEAT_NOTE = (
    "This same call has now failed more than once. Do not repeat it: read the "
    "file or output again, try a different approach, or use ask_researcher "
    "with the exact error."
)

RETRY_UNREADABLE = 2
"""How many times a garbled tool call is sent back before the reply stands."""
START_NOTE = (
    "(Studio) Nobody can answer questions during this job, and the user has "
    "already said go. Don't ask; start now with your tools, then report what "
    "you found."
)
WEB_TOOLS = frozenset({"web_search", "web_fetch", "research"})
FALLBACK_NOTE = (
    "{name}'s model ({model}) failed, so {name} is doing this job with {used} "
    "instead. Fix {name}'s model in Team brains (Test checks it). Error: {error}"
)
FOLLOW_UP_STEPS = 4
"""Turns the main AI may take to digest a teammate's report."""
EMPTY_NOTE = (
    "(Studio) Your reply came back empty. Answer now in plain words, and keep "
    "any thinking short."
)


def empty_reply_note(agent: str, model: str, stop_reason: str) -> str:
    """Say why an agent's answer is blank instead of showing nothing."""
    if stop_reason == THINKING_ONLY:
        why = (
            "it spent its whole reply thinking and never answered. Pick a model "
            "that doesn't think first (an 'instruct' model) in Team brains"
        )
    elif stop_reason in {"length", "max_tokens"}:
        why = (
            "it ran out of room before answering. In LM Studio, load the model "
            "with a bigger Context Length (8192 or more)"
        )
    else:
        why = (
            "the model sent back an empty answer twice. Check the model is "
            "loaded in LM Studio, or pick another in Team brains"
        )
    return f"(Studio: {agent} got no answer from {model_label(model)}: {why}.)"


_CALLED_TOOL = re.compile(r'"(?:tool|name)"\s*:\s*"([\w-]+)"')


def garbled_call_note(agent: str, text: str, names: Sequence[str]) -> str:
    """What to say instead of a tool call that was cut off or garbled."""
    found = _CALLED_TOOL.search(text)
    tool = found.group(1) if found else "a tool"
    if tool in WRITE_TOOLS and tool not in names:
        return (
            f"(Studio: {agent} tried to write files itself ({tool}), which it "
            "can't do. Ask the Builder instead, e.g. 'have Builder make ...'.)"
        )
    return (
        f"(Studio: {agent} tried to use {tool}, but its reply was cut off or "
        "garbled, so nothing ran. Ask again. If it keeps happening, in LM Studio "
        "load the model with a bigger Context Length (8192 or more), or give "
        "this agent another model in Team brains.)"
    )


SWAPPED_NOTE = (
    "{model} isn't available for your key, so {name} used {used}, which works. "
    "Pick {name}'s model in Team brains (Test checks one) to change it."
)
SEARCHED_FOR_YOU_NOTE = (
    "(Studio) You didn't search, so Studio ran {tool} for you. Write your "
    "report from these results only, and cite the links:\n\n{results}"
)
NO_SEARCH_NOTE = (
    "(Studio: {name} never searched the web for this, so this answer is not "
    "researched. Its model may not support tools; pick another in Team brains.)"
)
UNREADABLE_NOTE = (
    "(Studio) That tool call could not be read, so nothing happened. Reply with "
    "one valid JSON tool call. For write_file, leave content out of the JSON "
    "and put the whole file in a fenced code block right after it."
)
CUT_OFF_NOTE = (
    "(Studio) Your reply hit the length limit and was cut off, so nothing was "
    "written. Write big files in parts: write_file with the first part, then "
    "write_file with append true for each next part."
)
LOOK_TOOLS = frozenset(
    {"read_file", "list_files", "search_files", "polish_check", "try_page"}
)
"""Look-ups that return the same thing until a file changes."""
SEEN_NOTE = (
    "(Studio) You already did exactly this and nothing has changed since, so "
    "the result is the same as before. Do not repeat it: write your changes "
    "now with write_file or edit_file."
)
IDLE_STEPS = 4
IDLE_NOTE = (
    "(Studio) You have looked around for {steps} steps without changing any "
    "file. You have what you need: write the files for the task now. For a "
    "page, rewrite index.html completely with write_file, with real content "
    "for this job."
)
HISTORY_BUDGET = 36_000
"""Characters of earlier tool output kept in full before older ones shrink."""
KEEP_RECENT = 6
REPLY_TOKENS = 2048
BUILD_REPLY_TOKENS = 4096
"""Builders write whole files in one reply, so they get more room."""


def model_missing_hint(error: str, model: str, agent: str) -> str:
    """Plain words for 'this provider won't run that model for your key'."""
    if not model_missing(error):
        return ""
    return (
        f"{agent} can't use {model}: the provider lists it, but it doesn't run "
        "it for your key (it may be retired or need other access). Open Team "
        f"brains and give {agent} another model, such as one your other agents "
        "already use."
    )


def _search_for(goal: str, names: Sequence[str]) -> ToolCall:
    """The search Studio runs for a Researcher that didn't run one: the job
    itself, without the briefing that follows it."""
    job = goal.strip()
    if job.startswith("The job: "):
        job = job[len("The job: ") :].split("\n\nBriefing from ", 1)[0]
    job = " ".join(job.split())[:300]
    if "research" in names:
        return ToolCall(
            id="studio-research", name="research", arguments={"question": job}
        )
    return ToolCall(id="studio-search", name="web_search", arguments={"query": job})


LAB_DONE_NOTE = (
    "(Studio) You answered without using the Lab, so Studio ran the job in the "
    "Lab for you. Here is what the Lab did:\n{result}\n\nNow report it to "
    "the team in plain words: what was made or seen, the ingredients or parts "
    "and what each does, and anything that failed."
)


def _lab_call_for(goal: str) -> ToolCall | None:
    """The lab call a Lab job asks for ('In the Lab, make shampoo.')."""
    job_text = goal.split("\n\nBriefing from ")[0].removeprefix("The job: ").strip()
    job = lab_job(job_text, in_lab=True)
    if job is None:
        return None
    arguments: JsonObject = {"action": job.action, "request": job.request}
    if job.action == "mix":
        arguments |= {"items": list(job.items), "heat": job.heat, "flame": job.flame}
    return ToolCall(id="studio-lab", name="lab", arguments=arguments)


FARM_PROMPT = (
    "You are in the Content Farm with the user, on the page where they watch "
    "their faceless short videos get made. For videos, ideas, and channels, "
    "use the farm tool: make (count, topic, channel) starts videos in the "
    "background, ideas fills the idea board, channel adds an account for a "
    "niche, list and queue show what is there. Then tell the user briefly "
    "what is on the way. Give honest advice on hooks, niches, and posting "
    "times when asked. Never make fake reviews or copy other people's videos."
)


def _place_prompt(chat: Chat) -> str:
    """The Lab's or the Content Farm's note, in their own chats."""
    if chat.settings.get("lab"):
        return LAB_PROMPT
    if chat.settings.get("farm"):
        return FARM_PROMPT
    return ""


FARM_DONE_NOTE = (
    "(Studio) You answered without using the Content Farm, so Studio ran the "
    "job on the farm for you. Here is what the farm did:\n{result}\n\nNow "
    "report it to the team in plain words: what is being made or was planned."
)


def _farm_call_for(goal: str) -> ToolCall | None:
    """The farm call a Farm job asks for ('Make 3 videos about cats in the
    Content Farm.')."""
    job_text = goal.split("\n\nBriefing from ")[0].removeprefix("The job: ").strip()
    job = farm_job(job_text.split("\n", 1)[0], in_farm=True)
    if job is None:
        return None
    arguments: JsonObject = {
        "action": job.action,
        "topic": job.topic,
        "count": job.count,
    }
    if job.channel:
        arguments["channel"] = job.channel
    if job.kind:
        arguments["kind"] = job.kind
    if job.long:
        arguments["long"] = True
        if job.minutes:
            arguments["minutes"] = job.minutes
    return ToolCall(id="studio-farm", name="farm", arguments=arguments)


_OWN_PLACE: dict[str, Callable[[str], ToolCall | None]] = {
    "lab": _lab_call_for,
    "farm": _farm_call_for,
}


def _call_key(call: ToolCall) -> str:
    return f"{call.name}:{json.dumps(call.arguments, sort_keys=True, default=str)}"


def _context_full(error: StudioLLMError) -> bool:
    text = str(error).lower()
    return "context" in text and any(
        word in text for word in ("exceed", "too long", "overflow", "maximum", "length")
    )


def compact_history(
    history: list[ChatMessage], *, budget: int = HISTORY_BUDGET
) -> list[ChatMessage]:
    """Shrink older tool output and written file text once history grows.

    The newest messages stay whole; older file reads and the text of files
    already written shrink to a line, so a long build never overflows the
    model's context. The files themselves are always there to read again.
    """

    def size(messages: list[ChatMessage]) -> int:
        return sum(
            len(m.content)
            + sum(len(json.dumps(c.arguments, default=str)) for c in m.tool_calls)
            for m in messages
        )

    if size(history) <= budget:
        return history
    kept = list(history)
    for index in range(1, max(1, len(kept) - KEEP_RECENT)):
        message = kept[index]
        if message.role == "tool" and len(message.content) > 400:
            kept[index] = ChatMessage(
                role="tool",
                content=f"{message.content[:300]}\n[... older result shortened; "
                "read the file again if you need it]",
                tool_call_id=message.tool_call_id,
            )
        elif message.tool_calls:
            kept[index] = ChatMessage(
                role=message.role,
                content=message.content[:1_000],
                tool_calls=tuple(
                    ToolCall(
                        id=call.id,
                        name=call.name,
                        arguments={
                            key: (
                                "[written to the file; read it for the text]"
                                if isinstance(value, str) and len(value) > 400
                                else value
                            )
                            for key, value in call.arguments.items()
                        },
                    )
                    for call in message.tool_calls
                ),
            )
        if size(kept) <= budget:
            break
    return kept


MEMORY_NOTE_HEADER = "Notes from your memory for this message (not from the user):"
SEALED_PROMPT = (
    "You run on an outside server, so the user's memory, notes, Obsidian "
    "vault, and earlier conversations stay on their PC and are not shared "
    "with you. You have your own memory area instead: remember saves to it "
    "and recall reads it, and nothing else is in it. The task you are given "
    "is your briefing: work from it, your own memory, the project files, and "
    "the web. If something you need is missing, say exactly what, and the "
    "user's main AI will fill it in."
)


STUDIO_NOTE_HEADER = "Studio's note for this message (not from the user):"


def with_memory_note(
    history: list[ChatMessage], note: str, *, header: str = MEMORY_NOTE_HEADER
) -> list[ChatMessage]:
    """Put this message's recalled memory on the newest user message.

    Keeping it out of the instructions lets the instructions and the earlier
    conversation stay word-for-word the same between messages.
    """
    if not note.strip():
        return history
    for index in range(len(history) - 1, -1, -1):
        message = history[index]
        if message.role == "user":
            marked = f"{header}\n{note}\n\n---\n{message.content}"
            return [
                *history[:index],
                ChatMessage.user(marked),
                *history[index + 1 :],
            ]
    return history


AGENT_BASE_PROMPT = (
    "You are a Studio agent running inside Free Claude Code on the user's own "
    "machine. Work in small, verifiable steps. Prefer calling a tool over "
    "guessing. When you have finished the task, call the finish tool with a "
    "short report of what you did. If the conversation starts with Studio's "
    "notes on its earlier part, treat them as what was said: keep to the "
    "decisions and facts in them."
)
SITE_PROMPT = (
    "You have a project workspace. Build complete, working websites and apps: "
    "real file structure, all the code, a README. Read files back before you "
    "finish to check your work. When you finish, Studio hands the user a "
    "Download card for the project (a .zip of every file), so say it is ready "
    "to download; don't paste the whole code into the chat."
)
COMMAND_PROMPT = (
    "You can run shell commands in the project with run_command: install "
    "packages, build, and run tests or scripts, then read the output and fix "
    "what fails. Commands must finish on their own; never start dev servers or "
    "watchers. The user may have to approve each command."
)
MAIN_PROMPT = (
    "You are {name}, the user's main AI. You run a team of agents on this "
    "machine and talk with the user through a voice-friendly console, so keep "
    "replies short, clear, and easy to read aloud. Answer simple questions "
    "yourself; hand real work to the team.\n"
    "How you run the team:\n"
    "- When the user tells you to have an agent do something, it gets done: "
    "Studio hands those orders out the moment the user speaks and tells you "
    "in a note. Confirm who is doing what; never redo the work yourself or "
    "ask the user to repeat it. When the user asks for research or for "
    "anything on the web, give it to the Researcher right away; never ask "
    "whether they are ready or want you to go ahead.\n"
    "- For a bigger goal, think first: split it into parts and give each part "
    "to the agent whose job it is (Researcher to find out, Builder to make, "
    "Helper to plan, Tester to check). When the Builder finishes something "
    "bigger than a page, have the Tester check it and give its fixes back to "
    "the Builder. Use ask_agent with background=true for parts that can "
    "run at the same time so you keep talking, and team_task when agents "
    "must work on it together in one room. Put everything the agent needs in "
    "the task text, and pass a project name when the work builds a website "
    "or app.\n"
    "- Use team_status before you answer anything about progress, and to "
    "follow up on work you handed out; use stop_agent when the user wants "
    "something stopped. When an agent reports back here, tell the user what "
    "it did and where to find it, and hand out the next step if there is one.\n"
    "Your own tools: todo keeps the user's to-do list and reminders (you "
    "announce them when due), calculate does any arithmetic exactly, "
    "list_projects finds the user's projects with their links, and "
    "system_status tells how this PC and LM Studio are doing. The note on each "
    "message tells you the date and time. When the user wants you to learn a "
    "subject, learn starts a study with a progress bar on the HUD; what you "
    "learned is in knowledge (and memory), so check it before answering or "
    "designing from that subject. weather gives the weather now and the next "
    "days for any town. Files the user attaches arrive in the message as "
    "[Attached file: name] blocks; read them before answering. Photos they "
    "attach go to Business photos with their words as the note ([Business "
    "photo: name] lines); list_photos shows them all, and when a site is "
    "being built, tell the Builder to use them. "
    "Each agent can think with its own AI model; "
    "agent_model shows who uses which and switches one when the user asks. "
    "You control every agent with manage_agent: show the team or one agent "
    "and what it remembers, give an agent every tool or only its own (fewer "
    "tools cost fewer tokens), and add to or clear an agent's memory. Agents "
    "on server AIs have their own memory area and never see the user's "
    "memory; save there only what their job needs.\n"
    "Use research yourself when you need to understand something first, and "
    "end that reply with the links of the sources you used; they show on "
    "screen. When the user gives you a video (a YouTube or other link, or a "
    "video file on this PC), watch it with study_video; videos the team "
    "studied before are in video_notes. When the user wants something looked "
    "at live on their screen, or a video played for them, use "
    "desktop_browser: a real browser window on their desktop that you drive "
    "(search, open, read, click links by number, scroll, play, watch). "
    "Every message of your conversations is kept word for word: earlier "
    "messages that match what the user says are attached to their message, "
    "and conversation searches or reads any of them, so check it instead of "
    "guessing whenever the user refers to something from before. When "
    "the user asks how to do something in this app, where something is, or "
    "why something is not working, call app_help and answer with the page and "
    "button names it gives."
    "\n\nYour team:\n{roster}"
)
MAIN_MEMORY_PROMPT = (
    "Your memory is your own: remember saves there and the other agents "
    "can't read it. Add share: true when the whole team should know a fact. "
    "You can read every agent's memory (recall says whose each result is), "
    "leave one agent a note with manage_agent add_memory, and talk to any "
    "agent with ask_agent."
)


def lead_prompt(names: Sequence[str], *, sealed: bool) -> str:
    """What an agent learns about the server agents it directs."""
    team = ", ".join(names)
    if sealed:
        return (
            f"You may hand parts of your job to the other agents on server "
            f"AIs ({team}) with ask_agent; agents on the user's PC take "
            "orders from the main AI only."
        )
    return (
        f"The agents on server AIs work under you: {team}. Hand one a job "
        "with ask_agent: put in everything the job needs, since they can't "
        "see the user's memory, and nothing private it doesn't need. Check on "
        "them with team_status, stop one with stop_agent, and change one's "
        "tools or leave it a note with manage_agent. Agents on this PC take "
        "orders from the main AI only."
    )


TEAM_PROMPT = (
    "You have every tool Studio has. Do your own job yourself; when a separate "
    "part is better done by a teammate (the Researcher for facts, the Builder "
    "for code, the Tester to check it, the Helper to plan), hand just that "
    "part over with ask_agent and use what it reports. Never hand your job "
    "back to whoever gave it to you."
)
WEB_PROMPT = (
    "You are connected to the internet through two tools: web_search finds "
    "pages and web_fetch reads one in full. Use them for anything current, "
    "factual, or that you are unsure of, instead of guessing, and name your "
    "sources."
)
OFFLINE_PROMPT = (
    "This computer is offline right now, so your internet tools are paused; "
    "they come back on their own when the connection returns. Work from "
    "recall, your memory, the project files, and what you already know. If "
    "something really needs checking online, say so and carry on."
)
SHARED_MEMORY_PROMPT = (
    "Your team shares one memory. Save what the whole team should know with "
    "remember; it is private only when you say so."
)
_TOOL_ABILITIES = (
    ("write_file", "builds websites and apps"),
    (COMMAND_TOOL, "runs commands"),
    ("research", "does deep research across ten or more sources"),
    ("ask_researcher", "asks the Researcher when stuck"),
    ("ask_helper", "asks the Helper for a plan"),
)


@dataclass(frozen=True, slots=True)
class TurnResult:
    """What one agent turn produced."""

    text: str
    steps: int
    tool_calls: tuple[str, ...] = ()
    failed: bool = False
    error: str | None = None


TOOLSHED_PROMPT = (
    "You start with a small set of tools. When the job needs one you don't "
    "have, go to the toolshed: toolshed action list shows what is on the "
    "shelf, and action take picks up what you need for this job."
)
CONTEXT_MANAGER = re.compile(r"context[- ]manager|requesting_agent", re.IGNORECASE)
"""Instructions written for a Claude Code team with a context-manager agent
(most of awesome-claude-code-subagents)."""
NO_CONTEXT_MANAGER_PROMPT = (
    "In LCC there is no context-manager to ask or to notify. Where your "
    "instructions say to request context from it, read the project's files "
    "instead (list_files, read_file); where they say to report to it, say "
    "what you did in your final answer. Never write those JSON messages into "
    "a project file."
)


@dataclass(slots=True)
class Toolshed:
    """The HQ toolshed for one job: tools an agent may pick up and keep until
    the job ends. Nothing on the shelf reads the user's own things or runs
    the team; those come only from the agent's card."""

    shelf: tuple[str, ...]
    locked: bool = False
    taken: list[str] = field(default_factory=list)

    def answer(self, call: ToolCall) -> ToolOutcome:
        action = str(call.arguments.get("action") or "list").lower()
        if self.locked:
            return ToolOutcome(
                text=(
                    "The toolshed is locked: Every Tool is off in Studio settings, "
                    "so work with the tools you have."
                ),
                data={"tool": TOOLSHED_TOOL, "locked": True},
                failed=True,
            )
        here = [name for name in self.shelf if name not in self.taken]
        if action != "take":
            lines = [
                f"- {name}: {TOOL_SPEC_BY_NAME[name].description.split('. ')[0]}"
                for name in here
            ]
            return ToolOutcome(
                text=(
                    "On the shelf (take what the job needs):\n" + "\n".join(lines)
                    if lines
                    else "The shelf is empty: you have every tool you may take."
                ),
                data={"tool": TOOLSHED_TOOL, "action": "list", "shelf": here},
            )
        raw = call.arguments.get("tools")
        wanted = [str(item).strip() for item in raw] if isinstance(raw, list) else []
        if not wanted and isinstance(raw, str):
            wanted = [item.strip() for item in raw.split(",")]
        picked = [name for name in dict.fromkeys(wanted) if name in here]
        refused = [name for name in wanted if name and name not in here]
        self.taken.extend(picked)
        parts = []
        if picked:
            parts.append(f"Took {', '.join(picked)} from the toolshed for this job.")
        if refused:
            parts.append(
                f"Not on the shelf: {', '.join(refused)}. (The user's own things "
                "and running the team never are; the user can give those on your "
                "card.)"
            )
        return ToolOutcome(
            text=" ".join(parts) or "Say which tools to take (see action list).",
            data={
                "tool": TOOLSHED_TOOL,
                "action": "take",
                "taken": picked,
                "why": str(call.arguments.get("why") or "")[:300],
            },
            failed=not picked,
        )


def _offers_downloads[**P](
    turn: Callable[Concatenate[AgentRunner, Agent, Chat, P], Awaitable[TurnResult]],
) -> Callable[Concatenate[AgentRunner, Agent, Chat, P], Awaitable[TurnResult]]:
    """After a turn, hand the user a download of each app it built or changed."""

    @functools.wraps(turn)
    async def run(
        runner: AgentRunner, agent: Agent, chat: Chat, *args: P.args, **kwargs: P.kwargs
    ) -> TurnResult:
        before = await runner._last_sequence(chat.id)
        result = await turn(runner, agent, chat, *args, **kwargs)
        if runner._built is not None and not result.failed:
            changed = await runner._apps_changed(chat.id, after=before)
            if changed:
                await runner._built(chat, changed)
        return result

    return run


class AgentRunner:
    """Drive one agent turn or one autonomous task to completion."""

    def __init__(
        self,
        *,
        store: StudioStore,
        router: StudioModelRouter,
        toolbox: AgentToolbox,
        memory: MemoryService,
        default_model: str,
        max_steps: int = 12,
        builder_max_steps: int = 40,
        coder_max_steps: int = 80,
        notes: NotesKeeper | None = None,
        live: MutableMapping[str, str] | None = None,
        temperature: float = 0.2,
        sealed: Callable[[Agent], Awaitable[bool]] | None = None,
        local_control: bool = False,
        main_own_memory: bool = False,
        learned: Callable[[str, ToolCall], Awaitable[None]] | None = None,
        built: Callable[[Chat, frozenset[str]], Awaitable[None]] | None = None,
    ) -> None:
        self._store = store
        # Hands the user a download of each app a turn built or changed.
        self._built = built
        # The main AI's calls that worked, so its playbook keeps the example.
        self._learned = learned
        # Agents on this PC direct the agents on server AIs.
        self._local_control = local_control
        # The main AI keeps its own memory and reads every agent's.
        self._main_own_memory = main_own_memory
        # Says which agents think on a server, and so must not see memory.
        self._sealed = sealed
        self._router = router
        self._toolbox = toolbox
        self._memory = memory
        self._default_model = default_model
        self._max_steps = max(1, max_steps)
        self._builder_max_steps = max(self._max_steps, builder_max_steps)
        self._coder_max_steps = max(self._max_steps, coder_max_steps)
        self._notes = notes
        # Chat id -> the reply being written right now, for live display.
        self._live = live
        self._temperature = temperature

    async def _private_view(
        self, agent: Agent
    ) -> tuple[Agent, bool, tuple[str, ...] | None]:
        """The agent as it may act, and whom it may direct.

        With every tool when that is on; without memory when it thinks on a
        server; and, on this PC, with the tools to direct the agents on
        server AIs. Who directs whom follows each agent's current model, so
        switching a model moves an agent between the two groups at once.
        """
        granted = self._toolbox.granted(
            agent.tools, role=agent.role, chosen=agent.all_tools
        )
        if granted != agent.tools:
            agent = agent.model_copy(update={"tools": granted})
        sealed = self._sealed is not None and await self._sealed(agent)
        if sealed:
            # The user's memory is out of reach; its own area stays in reach.
            agent = agent.model_copy(
                update={
                    "memory_enabled": False,
                    "tools": tuple(t for t in agent.tools if t not in SEALED_TOOLS),
                }
            )
        if agent.role == MAIN_ROLE:
            return agent, sealed, None
        if agent.role == "guide":
            return agent, sealed, ()
        free = self._toolbox.delegation_allowed(agent.role, agent.tools)
        if free and not sealed:
            # Chosen for every tool on this PC: it hands work to anyone.
            return agent, sealed, None
        servers = await self._server_team(agent)
        if sealed:
            return agent, sealed, servers if free else ()
        if not (self._local_control and servers):
            return agent, sealed, ()
        missing = tuple(tool for tool in LEAD_TOOLS if tool not in agent.tools)
        return (
            agent.model_copy(update={"tools": (*agent.tools, *missing)}),
            sealed,
            servers,
        )

    async def _server_team(self, agent: Agent) -> tuple[str, ...]:
        """The names of the other agents that think on a server AI."""
        if self._sealed is None:
            return ()
        names: list[str] = []
        for member in await self._store.find(Agent, order_by="created_at ASC"):
            if (
                member.id == agent.id
                or member.archived
                or member.role in {MAIN_ROLE, "guide"}
            ):
                continue
            if await self._sealed(member):
                names.append(member.name)
        return tuple(names)

    def _steps_for(self, agent: Agent) -> int:
        if agent.role == "coder":
            return self._coder_max_steps
        return self._builder_max_steps if agent.role == "builder" else self._max_steps

    async def system_prompt(
        self,
        agent: Agent,
        *,
        query: str,
        site_id: str | None,
        with_memory: bool = True,
    ) -> str:
        """Compose the agent's identity, tuning, memory, and site guidance.

        What stays the same from turn to turn comes first and the memory
        recalled for this message comes last, so a local runtime can reuse
        its cached reading of the start of the prompt instead of re-reading
        all of it before every reply.
        """
        parts = [AGENT_BASE_PROMPT]
        if agent.role == MAIN_ROLE:
            parts.append(
                MAIN_PROMPT.format(name=agent.name, roster=await self.roster(agent))
            )
        parts.append(agent.system_prompt.strip())
        if CONTEXT_MANAGER.search(agent.system_prompt):
            parts.append(NO_CONTEXT_MANAGER_PROMPT)
        if agent.tune_pack_id:
            pack = await self._store.get(TunePack, agent.tune_pack_id)
            if pack is not None and pack.active:
                parts.append(pack_system_text(pack))
        skills = await self._memory.skills(agent.id) if agent.memory_enabled else ()
        if skills:
            lines = "\n".join(f"- {entry.text[:900]}" for entry in skills)
            parts.append(
                f"Skills the user taught you (use them when they fit):\n{lines}"
            )
        if (
            agent.memory_enabled
            and self._toolbox.shared_memory
            and "remember" in agent.tools
        ):
            parts.append(SHARED_MEMORY_PROMPT)
        if agent.role != MAIN_ROLE and self._toolbox.delegation_allowed(
            agent.role, agent.tools
        ):
            parts.append(TEAM_PROMPT)
        if TOOLSHED_TOOL in agent.tools:
            parts.append(TOOLSHED_PROMPT)
        if "web_search" in self._toolbox.tool_names(agent.tools, role=agent.role):
            parts.append(WEB_PROMPT)
        elif self._toolbox.web_paused(agent.tools, role=agent.role):
            parts.append(OFFLINE_PROMPT)
        if site_id:
            parts.append(SITE_PROMPT)
            overview = await self._toolbox.project_overview(site_id)
            if overview:
                parts.append(overview)
            if self._toolbox.commands_enabled and COMMAND_TOOL in agent.tools:
                parts.append(COMMAND_PROMPT)
        if with_memory and agent.memory_enabled:
            parts.append(await self._memory.context_block(agent.id, query))
        return "\n\n".join(part for part in parts if part.strip())

    async def roster(self, main: Agent) -> str:
        """Describe the agents the main agent can hand work to."""
        lines: list[str] = []
        for member in await self._store.find(Agent, order_by="created_at ASC"):
            if (
                member.id == main.id
                or member.archived
                or member.role
                in {
                    MAIN_ROLE,
                    "guide",
                }
            ):
                continue
            tools = self._toolbox.tool_names(member.tools, role=member.role)
            abilities = [label for tool, label in _TOOL_ABILITIES if tool in tools]
            about = member.description or member.system_prompt or member.role
            line = f"- {member.name} ({member.role}, {member.model}): {about[:140]}"
            if abilities:
                line += f" It {', '.join(abilities)}."
            if self._sealed is not None and await self._sealed(member):
                line += (
                    " It runs on a server AI and cannot see the user's memory; "
                    "Studio sends it your briefing, so give it the whole job."
                )
            lines.append(line)
        return "\n".join(lines) or "- nobody yet; the user can add agents."

    def _context(
        self,
        agent: Agent,
        chat: Chat,
        *,
        site_id: str | None,
        sealed: bool = False,
        directs: tuple[str, ...] | None = None,
    ) -> ToolContext:
        return ToolContext(
            agent_id=agent.id,
            chat_id=chat.id,
            site_id=site_id,
            agent_name=agent.name,
            agent_role=agent.role,
            memory_owner=server_area(agent.id) if sealed else "",
            can_delegate=self._toolbox.delegation_allowed(agent.role, agent.tools)
            or bool(directs),
            directs=directs,
            main_memory=agent.role == MAIN_ROLE
            and self._main_own_memory
            and not sealed,
        )

    async def _history(self, agent: Agent, chat: Chat) -> list[ChatMessage]:
        start, notes = await self._view(chat)
        transcript = await self._store.transcript(chat.id, after=start)
        history: list[ChatMessage] = []
        if agent.tune_pack_id:
            pack = await self._store.get(TunePack, agent.tune_pack_id)
            if pack is not None and pack.active:
                history.extend(pack_exemplars(pack))
        said: list[tuple[str, str]] = []
        if notes:
            said.append(("user", f"{NOTES_HEADER}\n{notes}"))
        for message in transcript:
            text = message.text.strip()
            if not text:
                continue
            if message.role == "user":
                said.append(("user", text))
            elif message.role == "assistant":
                said.append(("assistant", text))
            elif message.role == "tool":
                # What tools and teammates reported stays in view as context.
                said.append(("user", f"(Studio: {message.author} said) {_trim(text)}"))
            elif message.role == "event" and (message.data or {}).get("kind") in (
                "background_done",
            ):
                said.append(("user", f"(Studio update) {_trim(text)}"))
        # Some chat templates need turns to alternate, so neighbours merge.
        for role, text in said:
            if history and history[-1].role == role and not history[-1].tool_calls:
                merged = f"{history[-1].content}\n\n{text}"
                history[-1] = (
                    ChatMessage.user(merged)
                    if role == "user"
                    else ChatMessage.assistant(merged)
                )
            else:
                history.append(
                    ChatMessage.user(text)
                    if role == "user"
                    else ChatMessage.assistant(text)
                )
        return history

    async def _view(self, chat: Chat) -> tuple[int, str]:
        """Where the messages in view begin, and the notes on what came before."""
        start = await self._history_start(chat)
        if self._notes is None:
            return start, ""
        kept = await self._notes.get(chat.id)
        # Messages leave the view only once the notes hold what they said.
        start = max(min(start, kept.until), start - MAX_UNNOTED)
        return start, kept.text if kept.until else ""

    async def _recall_earlier(self, agent: Agent, chat: Chat, text: str) -> str:
        """Earlier messages out of view that match what the user just said,
        from this conversation and the agent's earlier ones, word for word."""
        start, _ = await self._view(chat)
        found = [
            Found(message)
            for message in await self._store.transcript(chat.id)
            if message.sequence <= start
        ]
        if agent.id:
            earlier = await self._store.find(
                Chat,
                where={"agent_id": agent.id},
                order_by="updated_at DESC",
                limit=EARLIER_CHATS + 1,
            )
            for other in earlier:
                if other.id == chat.id:
                    continue
                found.extend(
                    Found(message, earlier_chat=True)
                    for message in await self._store.transcript(
                        other.id, limit=EARLIER_CHAT_MESSAGES
                    )
                )
        return recall_note(search(found, text))

    def _keep_notes(self, agent: Agent, chat: Chat, next_start: int) -> None:
        """Start the notes on messages that will leave the view next time."""
        if self._notes is None or next_start <= 0:
            return
        self._notes.keep_up(
            chat.id,
            next_start,
            model=agent.model or self._default_model,
            name=agent.name,
        )

    async def _history_start(self, chat: Chat) -> int:
        """Where the conversation an agent sees begins.

        The window holds the last 40 to 60 messages and its start moves in
        steps of 20, not one message at a time. The earlier conversation then
        reads the same from reply to reply, so a local runtime reuses what it
        already read instead of re-reading the whole history every time.
        """
        newest = await self._store.transcript(chat.id, limit=1)
        if not newest:
            return 0
        last = newest[0].sequence
        return max(0, (last - HISTORY_MIN) // HISTORY_STEP * HISTORY_STEP)

    async def reply(
        self,
        agent: Agent,
        chat: Chat,
        user_text: str,
        *,
        prepare: Callable[[], Awaitable[str]] | None = None,
    ) -> TurnResult:
        """Answer one user message, using tools when the agent asks for them.

        ``prepare`` runs once the message is recorded and before the model is
        asked; what it returns rides on the message as a note from Studio.
        """
        await self._store.append_message(
            chat_id=chat.id, role="user", text=user_text, author="user"
        )
        agent, sealed, directs = await self._private_view(agent)
        note = await prepare() if prepare is not None else ""
        recalled = "" if sealed else await self._recall_earlier(agent, chat, user_text)
        note = "\n\n".join(part for part in (note, recalled) if part)
        history = await self._history(agent, chat)
        if not history or not history[-1].content.endswith(user_text):
            history.append(ChatMessage.user(user_text))
        context = self._context(
            agent, chat, site_id=chat.site_id, sealed=sealed, directs=directs
        )
        result = await self._loop(
            agent,
            chat,
            history=history,
            context=context,
            query=user_text,
            max_steps=self._steps_for(agent),
            turn_note=note,
            sealed=sealed,
            extra_system=_place_prompt(chat),
            learn=agent.role == MAIN_ROLE,
            said=user_text,
        )
        self._keep_notes(agent, chat, await self._history_start(chat))
        if (agent.memory_enabled or sealed) and not result.failed and result.text:
            await self._memory.remember(
                server_area(agent.id) if sealed else agent.id,
                f"User asked: {user_text.strip()[:160]}",
                scope="working",
                source="chat",
                chat_id=chat.id,
            )
        return result

    async def follow_up(self, agent: Agent, chat: Chat, report: str) -> TurnResult:
        """Take a turn without a new user message: a teammate just reported
        back, and the agent tells the user what it means."""
        agent, sealed, directs = await self._private_view(agent)
        history = await self._history(agent, chat)
        history.append(ChatMessage.user(report))
        context = self._context(
            agent, chat, site_id=chat.site_id, sealed=sealed, directs=directs
        )
        return await self._loop(
            agent,
            chat,
            history=history,
            context=context,
            query=report[:500],
            max_steps=FOLLOW_UP_STEPS,
            sealed=sealed,
            extra_system=_place_prompt(chat),
            # Talking only: a small model must not hand the same job out again.
            talk_only=True,
        )

    async def run_task(
        self,
        agent: Agent,
        chat: Chat,
        run: AgentRun,
        *,
        note: str = "",
        fallback_model: str | None = None,
    ) -> AgentRun:
        """Run one autonomous goal to completion and persist its outcome.

        ``note`` rides along with the goal (what the team shared in the room)
        without becoming part of it.
        """
        agent, sealed, directs = await self._private_view(agent)
        started = run.model_copy(update={"status": "running", "updated_at": now_ms()})
        await self._store.put(started)
        await self._store.append_message(
            chat_id=chat.id,
            role="event",
            text=f"Agent task started: {run.goal}",
            author=agent.name,
            data={"kind": "run_started", "run_id": run.id},
        )
        context = self._context(
            agent,
            chat,
            site_id=run.site_id or chat.site_id,
            sealed=sealed,
            directs=directs,
        )
        history = [ChatMessage.user(run.goal)]
        result = await self._loop(
            agent,
            chat,
            history=history,
            context=context,
            query=run.goal,
            max_steps=run.max_steps or self._max_steps,
            sealed=sealed,
            alone=True,
            turn_note=note,
            fallback_model=fallback_model,
        )
        finished = started.model_copy(
            update={
                "status": "failed" if result.failed else "succeeded",
                "step": result.steps,
                "result": result.text,
                "error": result.error,
                "updated_at": now_ms(),
            }
        )
        await self._store.put(finished)
        await self._store.append_message(
            chat_id=chat.id,
            role="event",
            text=f"Agent task {finished.status}.",
            author=agent.name,
            data={"kind": "run_finished", "run_id": run.id, "status": finished.status},
        )
        if sealed and not result.failed:
            await self._memory.remember(
                server_area(agent.id),
                f"Finished: {run.goal.strip()[:200]}",
                tags=("task",),
                source="agent_run",
                chat_id=chat.id,
            )
        elif agent.memory_enabled and not result.failed:
            outcome = f"{agent.name} completed: {run.goal.strip()[:200]}"
            if result.text:
                outcome += f" — {result.text.strip()[:240]}"
            await self._memory.note_outcome(
                agent.id,
                outcome,
                author=agent.name,
                tags=("task",),
                source="agent_run",
                chat_id=chat.id,
            )
        return finished

    async def respond(
        self,
        agent: Agent,
        chat: Chat,
        *,
        history: list[ChatMessage],
        query: str,
        extra_system: str = "",
        max_steps: int | None = None,
    ) -> TurnResult:
        """Take one turn in an existing conversation someone else is driving."""
        agent, sealed, directs = await self._private_view(agent)
        context = self._context(
            agent, chat, site_id=chat.site_id, sealed=sealed, directs=directs
        )
        return await self._loop(
            agent,
            chat,
            history=history,
            context=context,
            query=query,
            max_steps=max_steps or self._max_steps,
            extra_system=extra_system,
            sealed=sealed,
        )

    async def _last_sequence(self, chat_id: str) -> int:
        tail = await self._store.transcript(chat_id, limit=1)
        return tail[-1].sequence if tail else 0

    async def _apps_changed(self, chat_id: str, *, after: int) -> frozenset[str]:
        """The projects this turn's own tool calls wrote to."""
        return frozenset(
            str(message.data["site_id"])
            for message in await self._store.transcript(chat_id, after=after)
            if message.role == "tool"
            and message.author in WRITE_TOOLS
            and message.data.get("site_id")
            and not message.data.get("failed")
        )

    @_offers_downloads
    async def _loop(
        self,
        agent: Agent,
        chat: Chat,
        *,
        history: list[ChatMessage],
        context: ToolContext,
        query: str,
        max_steps: int,
        extra_system: str = "",
        turn_note: str = "",
        sealed: bool = False,
        alone: bool = False,
        talk_only: bool = False,
        fallback_model: str | None = None,
        learn: bool = False,
        said: str = "",
    ) -> TurnResult:
        """``alone``: a background job, so nobody is there to answer questions.
        ``talk_only``: no tools this turn (a follow-up that only reports).
        ``learn``: calls that work go into the main AI's playbook.
        ``said``: the user's own message, which tool calls are held to."""
        await self._toolbox.check_online()
        names = (
            () if talk_only else self._toolbox.tool_names(agent.tools, role=agent.role)
        )

        def specs_for(names: tuple[str, ...]) -> tuple[ToolSpec, ...]:
            return tool_specs(
                names,
                commands_enabled=self._toolbox.commands_enabled,
                shared_memory=self._toolbox.shared_memory and agent.memory_enabled,
                delegation=self._toolbox.delegation_allowed(agent.role, names)
                or context.can_delegate,
                main_memory=context.main_memory,
            )

        specs = specs_for(names)
        shed = (
            self._toolshed(agent, names, sealed=sealed)
            if TOOLSHED_TOOL in names
            else None
        )
        # The instructions stay the same from message to message; what memory
        # recalls for this message rides on the message itself. A local
        # runtime then reuses its reading of the instructions and the whole
        # earlier conversation instead of re-reading them for every reply.
        system = await self.system_prompt(
            agent, query=query, site_id=context.site_id, with_memory=False
        )
        if sealed:
            system = f"{system}\n\n{SEALED_PROMPT}"
        if context.directs and agent.role != MAIN_ROLE:
            system = f"{system}\n\n{lead_prompt(context.directs, sealed=sealed)}"
        if context.main_memory:
            system = f"{system}\n\n{MAIN_MEMORY_PROMPT}"
        if extra_system:
            system = f"{system}\n\n{extra_system}"
        if agent.memory_enabled or sealed:
            owner = server_area(agent.id) if sealed else agent.id
            history = with_memory_note(
                history,
                await self._memory.context_block(
                    owner, query, everyone=context.main_memory
                ),
            )
        if turn_note:
            history = with_memory_note(history, turn_note, header=STUDIO_NOTE_HEADER)
        model = agent.model or self._default_model
        used: list[str] = []
        failures: dict[str, int] = {}
        checked = False
        retries = 0
        seen: set[str] = set()
        idle = 0
        squeezed = False
        prodded = False
        searched_for_it = False
        labbed = False
        pushed_to_write = False
        emptied = False
        for step in range(1, max_steps + 1):
            history = compact_history(history)
            try:
                reply = await self._router.complete(
                    history,
                    model=model,
                    system=system,
                    tools=specs if names else (),
                    max_tokens=BUILD_REPLY_TOKENS
                    if WRITE_TOOLS & set(names)
                    else REPLY_TOKENS,
                    temperature=self._temperature,
                    on_text=self._show_live(chat.id),
                )
            except StudioLLMError as error:
                self._clear_live(chat.id)
                if not squeezed and _context_full(error) and len(history) > 2:
                    # Too much for the model's context: shrink hard, try again.
                    squeezed = True
                    history = compact_history(history, budget=HISTORY_BUDGET // 3)
                    continue
                logger.warning("Studio agent call failed: {}", error)
                if fallback_model and fallback_model != model:
                    # The job still gets done: on the model that just worked
                    # for the main AI, with a note saying so.
                    await self._store.append_message(
                        chat_id=chat.id,
                        role="event",
                        text=FALLBACK_NOTE.format(
                            name=agent.name,
                            model=model_label(model),
                            used=model_label(fallback_model),
                            error=str(error)[:300],
                        ),
                        author=agent.name,
                        data={
                            "kind": "model_fallback",
                            "model": model,
                            "used": fallback_model,
                        },
                    )
                    model = fallback_model
                    fallback_model = None
                    continue
                hint = model_missing_hint(str(error), model, agent.name)
                await self._store.append_message(
                    chat_id=chat.id,
                    role="event",
                    text=(f"{hint}\n\n" if hint else "")
                    + f"Model call failed: {error}",
                    author=agent.name,
                    data={"kind": "error"},
                )
                return TurnResult(
                    text="",
                    steps=step - 1,
                    tool_calls=tuple(used),
                    failed=True,
                    error=hint or str(error),
                )
            self._clear_live(chat.id)
            if talk_only and reply.tool_calls:
                # A report back is talk only: a tool asked for anyway (a small
                # model handing the job out again) never runs.
                reply = replace(reply, tool_calls=())
            swapped = self._router.swaps.get(model)
            if swapped and swapped != model:
                await self._store.append_message(
                    chat_id=chat.id,
                    role="event",
                    text=SWAPPED_NOTE.format(
                        name=agent.name, model=model, used=swapped
                    ),
                    author=agent.name,
                    data={"kind": "model_swapped", "model": model, "used": swapped},
                )
                model = swapped
            if (
                not reply.tool_calls
                and names
                and retries < RETRY_UNREADABLE
                and step < max_steps
                and unreadable_tool_call(reply.text)
            ):
                # A small model garbled its tool call (or ran out of room);
                # say so and let it try again instead of ending the job.
                retries += 1
                cut_off = reply.stop_reason in {"length", "max_tokens"}
                history.append(ChatMessage.assistant(reply.text[:1_500]))
                history.append(
                    ChatMessage.user(CUT_OFF_NOTE if cut_off else UNREADABLE_NOTE)
                )
                continue
            if not reply.tool_calls and context.site_id and "write_file" in names:
                fenced = fenced_files(reply.text)
                if fenced:
                    # A small model often pastes the finished page in its reply
                    # instead of saving it; save it for it.
                    reply = replace(
                        reply,
                        text="",
                        tool_calls=tuple(
                            ToolCall(
                                id=f"fenced_{step}_{index}",
                                name="write_file",
                                arguments={"path": path, "content": body},
                            )
                            for index, (path, body) in enumerate(fenced)
                        ),
                    )
            if (
                not reply.tool_calls
                and alone
                and context.site_id
                and "write_file" in names
                and not CONTENT_WRITES & set(used)
                and not pushed_to_write
                and step < max_steps
            ):
                # Starting the template is not building the site: ask once for
                # the real content before the job may end.
                pushed_to_write = True
                history.append(ChatMessage.assistant(reply.text[:1_500]))
                history.append(ChatMessage.user(WRITE_NOTE))
                continue
            if (
                not reply.tool_calls
                and not checked
                and step < max_steps
                and CHECK_PROJECT_TOOL in names
                and context.site_id
                and WRITE_TOOLS & set(used)
            ):
                # Ending in plain words skips the finish tool, not the check.
                checked = True
                problems = await self._check_before_finish(chat, agent, context)
                if problems:
                    history.append(ChatMessage.assistant(reply.text[:1_500]))
                    history.append(
                        ChatMessage.user(
                            "(Studio) Not finished yet. check_project found "
                            f"problems; fix them, then finish:\n{problems}"
                        )
                    )
                    continue
            if (
                not reply.tool_calls
                and alone
                and names
                and not used
                and not prodded
                and step < max_steps
                and "?" in reply.text
            ):
                # "Shall I begin?" on a background job would come back to the
                # user as the report; tell it once to just start.
                prodded = True
                history.append(ChatMessage.assistant(reply.text[:1_500]))
                history.append(ChatMessage.user(START_NOTE))
                continue
            if (
                not reply.tool_calls
                and alone
                and agent.role == "researcher"
                and not searched_for_it
                and not WEB_TOOLS & set(used)
                and WEB_TOOLS & set(names)
                and step < max_steps
            ):
                # A Researcher's report must come from the web. When its model
                # won't call tools (or answers from what it already knows),
                # Studio does the searching and the model writes it up.
                searched_for_it = True
                call = _search_for(query, names)
                outcome = (await self._run_calls([call], context, sealed=sealed))[0]
                used.append(call.name)
                await self._store.append_message(
                    chat_id=chat.id,
                    role="tool",
                    text=outcome.text[:4_000],
                    author=call.name,
                    data={**outcome.data, "failed": outcome.failed, "by_studio": True},
                )
                history.append(ChatMessage.assistant(reply.text[:1_500]))
                history.append(
                    ChatMessage.user(
                        SEARCHED_FOR_YOU_NOTE.format(
                            tool=call.name, results=outcome.text[:12_000]
                        )
                    )
                )
                continue
            if (
                not reply.tool_calls
                and alone
                and agent.role in _OWN_PLACE
                and not labbed
                and agent.role in names
                and agent.role not in used
                and step < max_steps
            ):
                # The Lab and Farm agents' job is their own place: when the
                # model only talks, Studio runs the job and it writes it up.
                labbed = True
                call = _OWN_PLACE[agent.role](query)
                if call is not None:
                    outcome = (await self._run_calls([call], context, sealed=sealed))[0]
                    used.append(call.name)
                    await self._store.append_message(
                        chat_id=chat.id,
                        role="tool",
                        text=outcome.text[:4_000],
                        author=call.name,
                        data={
                            **outcome.data,
                            "failed": outcome.failed,
                            "by_studio": True,
                        },
                    )
                    history.append(ChatMessage.assistant(reply.text[:1_500]))
                    done_note = LAB_DONE_NOTE if agent.role == "lab" else FARM_DONE_NOTE
                    history.append(
                        ChatMessage.user(done_note.format(result=outcome.text[:6_000]))
                    )
                    continue
            if (
                not reply.tool_calls
                and not reply.text.strip()
                and not emptied
                and step < max_steps
            ):
                # An empty answer (a model that only thought, or a runtime
                # hiccup): ask once more before giving up on it.
                emptied = True
                history.append(ChatMessage.user(EMPTY_NOTE))
                continue
            if not reply.tool_calls:
                text = reply.text.strip() or empty_reply_note(
                    agent.name, model, reply.stop_reason
                )
                if unreadable_tool_call(text):
                    # Never show a half-written tool call as the answer.
                    text = garbled_call_note(agent.name, text, names)
                if prodded and not used and WEB_TOOLS & set(names):
                    # Told to start and still only talking: its model most
                    # likely can't call tools at all.
                    text = f"{text}\n\n{NO_SEARCH_NOTE.format(name=agent.name)}"
                await self._record_assistant(chat, agent, text, reply)
                return TurnResult(text=text, steps=step, tool_calls=tuple(used))
            if said:
                reply = replace(
                    reply, tool_calls=tuple(guarded(c, said) for c in reply.tool_calls)
                )
            finish = self._finish_call(reply.tool_calls)
            if (
                finish is not None
                and not checked
                and step < max_steps
                and CHECK_PROJECT_TOOL in names
                and context.site_id
                and WRITE_TOOLS & set(used)
            ):
                checked = True
                problems = await self._check_before_finish(chat, agent, context)
                if problems:
                    history.append(
                        ChatMessage(
                            role="assistant",
                            content=reply.text,
                            tool_calls=reply.tool_calls,
                        )
                    )
                    history.extend(
                        ChatMessage(
                            role="tool",
                            tool_call_id=call.id,
                            content=(
                                "Not finished yet. check_project found problems; "
                                f"fix them, then finish:\n{problems}"
                                if call is finish
                                else "Skipped: fix the project problems first."
                            ),
                        )
                        for call in reply.tool_calls
                    )
                    continue
            if finish is not None:
                summary = str(finish.arguments.get("summary", "")) or reply.text
                await self._record_assistant(chat, agent, summary, reply)
                used.append(FINISH_TOOL)
                return TurnResult(text=summary, steps=step, tool_calls=tuple(used))
            history.append(
                ChatMessage(
                    role="assistant", content=reply.text, tool_calls=reply.tool_calls
                )
            )
            if reply.text:
                await self._store.append_message(
                    chat_id=chat.id,
                    role="assistant",
                    text=reply.text,
                    author=agent.name,
                    data={"partial": True},
                )
            outcomes = await self._run_calls(
                reply.tool_calls,
                context,
                sealed=sealed,
                offered=frozenset(spec.name for spec in specs),
                shed=shed,
            )
            if shed is not None and set(shed.taken) - set(names):
                # Tools taken from the toolshed are in hand from the next step.
                names = tuple(dict.fromkeys((*names, *shed.taken)))
                specs = specs_for(names)
            wrote = any(
                call.name in WRITE_TOOLS and not outcome.failed
                for call, outcome in zip(reply.tool_calls, outcomes, strict=True)
            )
            if wrote:
                seen.clear()
                idle = 0
            elif context.site_id and WRITE_TOOLS & set(names):
                idle += 1
            for call, outcome in zip(reply.tool_calls, outcomes, strict=True):
                used.append(call.name)
                if learn and self._learned is not None and not outcome.failed:
                    await self._learned(query, call)
                if call.name in LOOK_TOOLS and not outcome.failed:
                    key = _call_key(call)
                    if key in seen:
                        # The same look-up again: the answer has not changed.
                        outcome = ToolOutcome(text=SEEN_NOTE, data=outcome.data)
                    seen.add(key)
                if outcome.failed:
                    key = _call_key(call)
                    failures[key] = failures.get(key, 0) + 1
                    if failures[key] >= REPEAT_FAILURES:
                        outcome = ToolOutcome(
                            text=f"{outcome.text}\n\n{REPEAT_NOTE}",
                            data=outcome.data,
                            failed=True,
                        )
                await self._store.append_message(
                    chat_id=chat.id,
                    role="tool",
                    text=outcome.text[:4_000],
                    author=call.name,
                    data={**outcome.data, "failed": outcome.failed},
                )
                history.append(
                    ChatMessage(
                        role="tool",
                        content=outcome.text[:8_000],
                        tool_call_id=call.id,
                    )
                )
            if idle >= IDLE_STEPS and history and history[-1].role == "tool":
                idle = 0
                last = history[-1]
                history[-1] = ChatMessage(
                    role="tool",
                    content=f"{last.content}\n\n{IDLE_NOTE.format(steps=IDLE_STEPS)}",
                    tool_call_id=last.tool_call_id,
                )
        message = (
            f"Stopped after {max_steps} steps without finishing. "
            "Ask again with a narrower goal."
        )
        await self._store.append_message(
            chat_id=chat.id,
            role="event",
            text=message,
            author=agent.name,
            data={"kind": "step_limit"},
        )
        return TurnResult(
            text=message,
            steps=max_steps,
            tool_calls=tuple(used),
            failed=True,
            error="step_limit",
        )

    def _toolshed(
        self, agent: Agent, names: Sequence[str], *, sealed: bool
    ) -> Toolshed:
        """What this agent may pick up for one job."""
        if not self._toolbox.every_tool_allowed:
            return Toolshed(shelf=(), locked=True)
        candidates = [
            name
            for name in TOOL_SPEC_BY_NAME
            if name not in names
            and name not in NOT_IN_THE_SHED
            and not (sealed and name in SEALED_TOOLS)
            and not (name == COMMAND_TOOL and not self._toolbox.commands_enabled)
        ]
        return Toolshed(shelf=self._toolbox.tool_names(candidates, role=agent.role))

    async def _run_calls(
        self,
        calls: Sequence[ToolCall],
        context: ToolContext,
        *,
        sealed: bool = False,
        offered: frozenset[str] | None = None,
        shed: Toolshed | None = None,
    ) -> list[ToolOutcome]:
        """Run tool calls; look-ups that change nothing run at the same time.

        ``offered``: the tools the agent was given this step; a call to any
        other tool is refused, so an agent only ever uses tools it has."""

        async def run(call: ToolCall) -> ToolOutcome:
            if call.name == TOOLSHED_TOOL and shed is not None:
                return shed.answer(call)
            if sealed and call.name in SEALED_TOOLS:
                return ToolOutcome(
                    text=(
                        "The user's memory stays on their PC; agents on server AIs "
                        "can't read it. Work from your briefing, or say what you need."
                    ),
                    data={"tool": call.name, "private": True},
                    failed=True,
                )
            if (
                offered is not None
                and call.name not in offered
                and not self._toolbox.refuses_itself(call.name)
            ):
                where = (
                    " Take it from the toolshed first (toolshed, action take)."
                    if shed is not None and call.name in shed.shelf
                    else ""
                )
                return ToolOutcome(
                    text=f"{call.name} isn't one of your tools for this job.{where}",
                    data={"tool": call.name, "not_yours": True},
                    failed=True,
                )
            return await self._toolbox.run(call, context)

        if len(calls) > 1 and all(call.name in PARALLEL_TOOLS for call in calls):
            return list(await asyncio.gather(*(run(call) for call in calls)))
        return [await run(call) for call in calls]

    def _show_live(self, chat_id: str) -> Callable[[str], None] | None:
        live = self._live
        if live is None:
            return None

        def show(text: str) -> None:
            live[chat_id] = text

        return show

    def _clear_live(self, chat_id: str) -> None:
        if self._live is not None:
            self._live.pop(chat_id, None)

    async def _record_assistant(
        self, chat: Chat, agent: Agent, text: str, reply: LLMReply
    ) -> Message:
        return await self._store.append_message(
            chat_id=chat.id,
            role="assistant",
            text=text,
            author=agent.name,
            data={"model": reply.model or agent.model, "usage": dict(reply.usage)},
        )

    async def _check_before_finish(
        self, chat: Chat, agent: Agent, context: ToolContext
    ) -> str:
        """Check a builder's project before it may finish; return any problems."""
        outcome = await self._toolbox.run(
            ToolCall(id="finish-check", name=CHECK_PROJECT_TOOL, arguments={}),
            context,
        )
        problems = outcome.data.get("problems")
        if outcome.failed or not isinstance(problems, list) or not problems:
            return ""
        await self._store.append_message(
            chat_id=chat.id,
            role="tool",
            text=outcome.text[:4_000],
            author=CHECK_PROJECT_TOOL,
            data={**outcome.data, "failed": False, "before_finish": True},
        )
        return outcome.text

    @staticmethod
    def _finish_call(calls: Sequence[ToolCall]) -> ToolCall | None:
        return next((call for call in calls if call.name == FINISH_TOOL), None)
