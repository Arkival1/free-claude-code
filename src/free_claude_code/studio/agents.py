"""The bounded tool loop every Studio agent runs."""

import asyncio
import json
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from dataclasses import dataclass

from loguru import logger

from .llm import ChatMessage, LLMReply, StudioLLMError, StudioModelRouter, ToolCall
from .memory import MemoryService
from .models import Agent, AgentRun, Chat, Message, TunePack, now_ms
from .store import StudioStore
from .tools import (
    CHECK_PROJECT_TOOL,
    COMMAND_TOOL,
    FINISH_TOOL,
    MAIN_ROLE,
    PARALLEL_TOOLS,
    AgentToolbox,
    ToolContext,
    ToolOutcome,
    tool_specs,
)
from .tuning import pack_exemplars, pack_system_text

HISTORY_MIN = 40
HISTORY_STEP = 20
WRITE_TOOLS = frozenset(
    {"write_file", "edit_file", "delete_file", "start_project", "restore_file"}
)
REPEAT_FAILURES = 2
REPEAT_NOTE = (
    "This same call has now failed more than once. Do not repeat it: read the "
    "file or output again, try a different approach, or use ask_researcher "
    "with the exact error."
)


def _call_key(call: ToolCall) -> str:
    return f"{call.name}:{json.dumps(call.arguments, sort_keys=True, default=str)}"


MEMORY_NOTE_HEADER = "Notes from your memory for this message (not from the user):"


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
    "short report of what you did."
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
    "ask the user to repeat it.\n"
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
    "message tells you the date and time.\n"
    "Use research yourself when you need to understand something first, and "
    "end that reply with the links of the sources you used; they show on "
    "screen. When the user gives you a YouTube link, study it with "
    "study_video; videos the team studied before are in video_notes. When "
    "the user asks how to do something in this app, where something is, or "
    "why something is not working, call app_help and answer with the page and "
    "button names it gives."
    "\n\nYour team:\n{roster}"
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
        live: MutableMapping[str, str] | None = None,
        temperature: float = 0.2,
    ) -> None:
        self._store = store
        self._router = router
        self._toolbox = toolbox
        self._memory = memory
        self._default_model = default_model
        self._max_steps = max(1, max_steps)
        self._builder_max_steps = max(self._max_steps, builder_max_steps)
        # Chat id -> the reply being written right now, for live display.
        self._live = live
        self._temperature = temperature

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
        skills = await self._memory.skills(agent.id)
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
            lines.append(line)
        return "\n".join(lines) or "- nobody yet; the user can add agents."

    def _context(self, agent: Agent, chat: Chat, *, site_id: str | None) -> ToolContext:
        return ToolContext(
            agent_id=agent.id,
            chat_id=chat.id,
            site_id=site_id,
            agent_name=agent.name,
            agent_role=agent.role,
        )

    async def _history(self, agent: Agent, chat: Chat) -> list[ChatMessage]:
        transcript = await self._store.transcript(
            chat.id, after=await self._history_start(chat)
        )
        history: list[ChatMessage] = []
        if agent.tune_pack_id:
            pack = await self._store.get(TunePack, agent.tune_pack_id)
            if pack is not None and pack.active:
                history.extend(pack_exemplars(pack))
        for message in transcript:
            if message.role == "user":
                history.append(ChatMessage.user(message.text))
            elif message.role == "assistant" and message.text:
                history.append(ChatMessage.assistant(message.text))
        return history

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
        note = await prepare() if prepare is not None else ""
        history = await self._history(agent, chat)
        if not history or history[-1].content != user_text:
            history.append(ChatMessage.user(user_text))
        context = self._context(agent, chat, site_id=chat.site_id)
        result = await self._loop(
            agent,
            chat,
            history=history,
            context=context,
            query=user_text,
            max_steps=self._steps_for(agent),
            turn_note=note,
        )
        if agent.memory_enabled and not result.failed and result.text:
            await self._memory.remember(
                agent.id,
                f"User asked: {user_text.strip()[:160]}",
                scope="working",
                source="chat",
                chat_id=chat.id,
            )
        return result

    async def run_task(self, agent: Agent, chat: Chat, run: AgentRun) -> AgentRun:
        """Run one autonomous goal to completion and persist its outcome."""
        started = run.model_copy(update={"status": "running", "updated_at": now_ms()})
        await self._store.put(started)
        await self._store.append_message(
            chat_id=chat.id,
            role="event",
            text=f"Agent task started: {run.goal}",
            author=agent.name,
            data={"kind": "run_started", "run_id": run.id},
        )
        context = self._context(agent, chat, site_id=run.site_id or chat.site_id)
        history = [ChatMessage.user(run.goal)]
        result = await self._loop(
            agent,
            chat,
            history=history,
            context=context,
            query=run.goal,
            max_steps=run.max_steps or self._max_steps,
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
        if agent.memory_enabled and not result.failed:
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
        context = self._context(agent, chat, site_id=chat.site_id)
        return await self._loop(
            agent,
            chat,
            history=history,
            context=context,
            query=query,
            max_steps=max_steps or self._max_steps,
            extra_system=extra_system,
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
    ) -> TurnResult:
        await self._toolbox.check_online()
        names = self._toolbox.tool_names(agent.tools, role=agent.role)
        specs = tool_specs(
            names,
            commands_enabled=self._toolbox.commands_enabled,
            shared_memory=self._toolbox.shared_memory and agent.memory_enabled,
            delegation=self._toolbox.delegation_allowed(agent.role),
        )
        # The instructions stay the same from message to message; what memory
        # recalls for this message rides on the message itself. A local
        # runtime then reuses its reading of the instructions and the whole
        # earlier conversation instead of re-reading them for every reply.
        system = await self.system_prompt(
            agent, query=query, site_id=context.site_id, with_memory=False
        )
        if extra_system:
            system = f"{system}\n\n{extra_system}"
        if agent.memory_enabled:
            history = with_memory_note(
                history, await self._memory.context_block(agent.id, query)
            )
        if turn_note:
            history = with_memory_note(history, turn_note, header=STUDIO_NOTE_HEADER)
        model = agent.model or self._default_model
        used: list[str] = []
        failures: dict[str, int] = {}
        checked = False
        for step in range(1, max_steps + 1):
            try:
                reply = await self._router.complete(
                    history,
                    model=model,
                    system=system,
                    tools=specs if names else (),
                    max_tokens=2048,
                    temperature=self._temperature,
                    on_text=self._show_live(chat.id),
                )
            except StudioLLMError as error:
                self._clear_live(chat.id)
                logger.warning("Studio agent call failed: {}", error)
                await self._store.append_message(
                    chat_id=chat.id,
                    role="event",
                    text=f"Model call failed: {error}",
                    author=agent.name,
                    data={"kind": "error"},
                )
                return TurnResult(
                    text="",
                    steps=step - 1,
                    tool_calls=tuple(used),
                    failed=True,
                    error=str(error),
                )
            self._clear_live(chat.id)
            if not reply.tool_calls:
                text = reply.text or "(no reply)"
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
            outcomes = await self._run_calls(reply.tool_calls, context)
            for call, outcome in zip(reply.tool_calls, outcomes, strict=True):
                used.append(call.name)
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
        self, calls: Sequence[ToolCall], context: ToolContext
    ) -> list[ToolOutcome]:
        """Run tool calls; look-ups that change nothing run at the same time."""
        if len(calls) > 1 and all(call.name in PARALLEL_TOOLS for call in calls):
            return list(
                await asyncio.gather(
                    *(self._toolbox.run(call, context) for call in calls)
                )
            )
        return [await self._toolbox.run(call, context) for call in calls]

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
