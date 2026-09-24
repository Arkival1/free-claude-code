"""The bounded tool loop every Studio agent runs."""

from collections.abc import Sequence
from dataclasses import dataclass

from loguru import logger

from .llm import ChatMessage, LLMReply, StudioLLMError, StudioModelRouter, ToolCall
from .memory import MemoryService
from .models import Agent, AgentRun, Chat, Message, TunePack, now_ms
from .store import StudioStore
from .tools import (
    COMMAND_TOOL,
    FINISH_TOOL,
    MAIN_ROLE,
    AgentToolbox,
    ToolContext,
    tool_specs,
)
from .tuning import pack_exemplars, pack_system_text

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
    "yourself. Hand real work to the team: ask_agent gives one agent a task "
    "and waits for its report; team_task puts several agents in a room to "
    "work on a goal together. Pass a project name when the work builds a "
    "website or app. Give each agent everything it needs in the task text, "
    "then tell the user what was done and where to find it.\n\nYour team:\n"
    "{roster}"
)
SHARED_MEMORY_PROMPT = (
    "Your team shares one memory. Save what the whole team should know with "
    "remember; it is private only when you say so."
)
_TOOL_ABILITIES = (
    ("write_file", "builds websites and apps"),
    (COMMAND_TOOL, "runs commands"),
    ("web_search", "searches the web"),
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
    ) -> None:
        self._store = store
        self._router = router
        self._toolbox = toolbox
        self._memory = memory
        self._default_model = default_model
        self._max_steps = max(1, max_steps)

    async def system_prompt(
        self, agent: Agent, *, query: str, site_id: str | None
    ) -> str:
        """Compose the agent's identity, tuning, memory, and site guidance."""
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
        if agent.memory_enabled:
            if self._toolbox.shared_memory and "remember" in agent.tools:
                parts.append(SHARED_MEMORY_PROMPT)
            parts.append(await self._memory.context_block(agent.id, query))
        if site_id:
            parts.append(SITE_PROMPT)
            if self._toolbox.commands_enabled and COMMAND_TOOL in agent.tools:
                parts.append(COMMAND_PROMPT)
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
            abilities = [
                label for tool, label in _TOOL_ABILITIES if tool in member.tools
            ]
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
        transcript = await self._store.transcript(chat.id, limit=40)
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

    async def reply(self, agent: Agent, chat: Chat, user_text: str) -> TurnResult:
        """Answer one user message, using tools when the agent asks for them."""
        await self._store.append_message(
            chat_id=chat.id, role="user", text=user_text, author="user"
        )
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
            max_steps=self._max_steps,
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
    ) -> TurnResult:
        specs = tool_specs(
            agent.tools,
            commands_enabled=self._toolbox.commands_enabled,
            shared_memory=self._toolbox.shared_memory and agent.memory_enabled,
            delegation=self._toolbox.delegation_allowed(agent.role),
        )
        system = await self.system_prompt(agent, query=query, site_id=context.site_id)
        if extra_system:
            system = f"{system}\n\n{extra_system}"
        model = agent.model or self._default_model
        used: list[str] = []
        for step in range(1, max_steps + 1):
            try:
                reply = await self._router.complete(
                    history,
                    model=model,
                    system=system,
                    tools=specs if agent.tools else (),
                    max_tokens=2048,
                )
            except StudioLLMError as error:
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
            if not reply.tool_calls:
                text = reply.text or "(no reply)"
                await self._record_assistant(chat, agent, text, reply)
                return TurnResult(text=text, steps=step, tool_calls=tuple(used))
            finish = self._finish_call(reply.tool_calls)
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
            for call in reply.tool_calls:
                used.append(call.name)
                outcome = await self._toolbox.run(call, context)
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

    @staticmethod
    def _finish_call(calls: Sequence[ToolCall]) -> ToolCall | None:
        return next((call for call in calls if call.name == FINISH_TOOL), None)
