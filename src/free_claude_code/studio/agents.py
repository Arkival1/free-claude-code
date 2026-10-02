"""The bounded tool loop every Studio agent runs."""

import asyncio
import json
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from dataclasses import dataclass

from loguru import logger

from .convo_notes import NOTES_HEADER, NotesKeeper
from .lab.bench import LAB_PROMPT
from .llm import (
    ChatMessage,
    LLMReply,
    StudioLLMError,
    StudioModelRouter,
    ToolCall,
    model_missing,
    unreadable_tool_call,
)
from .memory import MemoryService, server_area
from .models import Agent, AgentRun, Chat, Message, TunePack, now_ms
from .recall_messages import Found, recall_note, search
from .store import StudioStore
from .tools import (
    CHECK_PROJECT_TOOL,
    COMMAND_TOOL,
    FINISH_TOOL,
    LEAD_TOOLS,
    MAIN_ROLE,
    PARALLEL_TOOLS,
    SEALED_TOOLS,
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
LOOK_TOOLS = frozenset({"read_file", "list_files", "search_files", "polish_check"})
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
    "finish to check your work."
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
    "screen. When the user gives you a YouTube link, study it with "
    "study_video; videos the team studied before are in video_notes. "
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
        notes: NotesKeeper | None = None,
        live: MutableMapping[str, str] | None = None,
        temperature: float = 0.2,
        sealed: Callable[[Agent], Awaitable[bool]] | None = None,
        local_control: bool = False,
        main_own_memory: bool = False,
    ) -> None:
        self._store = store
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
            extra_system=LAB_PROMPT if chat.settings.get("lab") else "",
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

    async def run_task(self, agent: Agent, chat: Chat, run: AgentRun) -> AgentRun:
        """Run one autonomous goal to completion and persist its outcome."""
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
    ) -> TurnResult:
        """``alone``: a background job, so nobody is there to answer questions."""
        await self._toolbox.check_online()
        names = self._toolbox.tool_names(agent.tools, role=agent.role)
        specs = tool_specs(
            names,
            commands_enabled=self._toolbox.commands_enabled,
            shared_memory=self._toolbox.shared_memory and agent.memory_enabled,
            delegation=self._toolbox.delegation_allowed(agent.role, names)
            or context.can_delegate,
            main_memory=context.main_memory,
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
            if not reply.tool_calls:
                text = reply.text or "(no reply)"
                if prodded and not used and WEB_TOOLS & set(names):
                    # Told to start and still only talking: its model most
                    # likely can't call tools at all.
                    text = f"{text}\n\n{NO_SEARCH_NOTE.format(name=agent.name)}"
                await self._record_assistant(chat, agent, text, reply)
                return TurnResult(text=text, steps=step, tool_calls=tuple(used))
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
            outcomes = await self._run_calls(reply.tool_calls, context, sealed=sealed)
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

    async def _run_calls(
        self, calls: Sequence[ToolCall], context: ToolContext, *, sealed: bool = False
    ) -> list[ToolOutcome]:
        """Run tool calls; look-ups that change nothing run at the same time."""

        async def run(call: ToolCall) -> ToolOutcome:
            if sealed and call.name in SEALED_TOOLS:
                return ToolOutcome(
                    text=(
                        "The user's memory stays on their PC; agents on server AIs "
                        "can't read it. Work from your briefing, or say what you need."
                    ),
                    data={"tool": call.name, "private": True},
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
