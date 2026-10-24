"""A chat room where the user and several agents talk, hand off, and finish tasks."""

from collections.abc import Sequence
from dataclasses import dataclass

from .agents import AgentRunner
from .llm import ChatMessage
from .memory import MemoryService
from .models import Agent, Chat, Message, now_ms
from .store import StudioStore

DONE_MARKER = "TASK COMPLETE:"
DEFAULT_TURN_LIMIT = 8
MAX_NUDGES = 1
HISTORY_WINDOW = 40

ROOM_PROMPT = """You are {name}, one of several AI agents in a shared chat room with the user.
Everyone in the room: the user, {roster}.
- Speak only for yourself, in a few sentences, and address the latest message.
- To hand work to another agent, mention them as @Name and say exactly what you need.
- Do the parts of the task that fit your role and tools; do not repeat others' work.
- When the room's task is fully done, start your message with "TASK COMPLETE:" followed by a short summary of the result.
Current task: {goal}"""


class RoomError(RuntimeError):
    """Raised when a room cannot be created or driven."""


@dataclass(frozen=True, slots=True)
class RoomOutcome:
    """What one burst of room conversation produced."""

    turns: int
    speakers: tuple[str, ...]
    completed: bool = False
    stopped: bool = False
    summary: str = ""


def mentioned(text: str, members: Sequence[Agent], *, exclude: str = "") -> list[Agent]:
    """Return members @mentioned in text, in the order they appear."""
    lowered = text.lower()
    found: list[tuple[int, Agent]] = []
    for member in members:
        if member.id == exclude:
            continue
        index = lowered.find(f"@{member.name.lower()}")
        if index >= 0:
            found.append((index, member))
    return [member for _, member in sorted(found, key=lambda pair: pair[0])]


def completion_summary(text: str) -> str | None:
    """Return the summary when a message declares the task complete."""
    index = text.upper().find(DONE_MARKER)
    if index < 0:
        return None
    return text[index + len(DONE_MARKER) :].strip() or "Done."


def room_history(agent: Agent, transcript: Sequence[Message]) -> list[ChatMessage]:
    """Render the room from one agent's point of view as alternating turns."""
    turns: list[ChatMessage] = []
    for message in transcript[-HISTORY_WINDOW:]:
        if message.role == "user":
            role, text = "user", f"User: {message.text}"
        elif message.role == "assistant" and message.author == agent.name:
            role, text = "assistant", message.text
        elif message.role == "assistant":
            role, text = "user", f"{message.author}: {message.text}"
        else:
            continue
        if turns and turns[-1].role == role:
            merged = f"{turns[-1].content}\n\n{text}"
            turns[-1] = ChatMessage(role=turns[-1].role, content=merged)
        else:
            turns.append(ChatMessage(role=role, content=text))
    if not turns or turns[-1].role != "user":
        turns.append(ChatMessage.user("(It is your turn.)"))
    return turns


class RoomService:
    """Decide who speaks next and keep the room's task state."""

    def __init__(
        self,
        *,
        store: StudioStore,
        runner: AgentRunner,
        memory: MemoryService,
        turn_limit: int = DEFAULT_TURN_LIMIT,
    ) -> None:
        self._store = store
        self._runner = runner
        self._memory = memory
        self._turn_limit = max(1, turn_limit)

    async def create(
        self, *, title: str, member_ids: Sequence[str], goal: str = ""
    ) -> Chat:
        """Open a room with at least one agent in it."""
        members = [
            await self._store.require(Agent, agent_id) for agent_id in member_ids
        ]
        if not members:
            raise RoomError("A room needs at least one agent.")
        room = Chat.model_validate(
            {
                "title": title.strip() or " & ".join(agent.name for agent in members),
                "kind": "room",
                "agent_id": members[0].id,
                "member_ids": tuple(dict.fromkeys(agent.id for agent in members)),
                "settings": {
                    "goal": goal.strip(),
                    "task_status": "idle",
                    "turn_limit": self._turn_limit,
                },
            }
        )
        await self._store.put(room)
        await self._store.append_message(
            chat_id=room.id,
            role="event",
            text="Room opened with " + ", ".join(agent.name for agent in members) + ".",
            author="studio",
            data={"kind": "room_opened"},
        )
        return room

    async def members(self, room: Chat) -> list[Agent]:
        """Return the room's agents in seating order, skipping deleted ones."""
        agents: list[Agent] = []
        for agent_id in room.member_ids:
            agent = await self._store.get(Agent, agent_id)
            if agent is not None:
                agents.append(agent)
        return agents

    async def set_members(self, room_id: str, member_ids: Sequence[str]) -> Chat:
        """Replace who is in the room."""
        room = await self._room(room_id)
        for agent_id in member_ids:
            await self._store.require(Agent, agent_id)
        if not member_ids:
            raise RoomError("A room needs at least one agent.")
        updated = room.model_copy(
            update={
                "member_ids": tuple(dict.fromkeys(member_ids)),
                "agent_id": member_ids[0],
                "updated_at": now_ms(),
            }
        )
        await self._store.put(updated)
        return updated

    async def post(self, room_id: str, text: str) -> tuple[Chat, list[Agent]]:
        """Record a user message and return who should answer it."""
        room = await self._room(room_id)
        cleaned = text.strip()
        if not cleaned:
            raise RoomError("Write something first.")
        await self._store.append_message(
            chat_id=room.id, role="user", text=cleaned, author="user"
        )
        members = await self.members(room)
        addressed = mentioned(cleaned, members)
        if addressed:
            return room, addressed
        if room.settings.get("task_status") == "running" and members:
            return room, members[:1]
        return room, members

    async def start_task(self, room_id: str, goal: str) -> tuple[Chat, list[Agent]]:
        """Give the room a goal and hand it to the lead agent."""
        room = await self._room(room_id)
        cleaned = goal.strip()
        if not cleaned:
            raise RoomError("A task needs a goal.")
        room = await self._update_settings(
            room,
            goal=cleaned,
            task_status="running",
            summary="",
            stop_requested=False,
        )
        members = await self.members(room)
        roster = ", ".join(f"@{agent.name}" for agent in members)
        await self._store.append_message(
            chat_id=room.id,
            role="user",
            text=(
                f"New task for the room: {cleaned}\n"
                f"{roster} — {members[0].name} leads: plan it, hand parts off, "
                "and say TASK COMPLETE when it is done."
            ),
            author="user",
            data={"kind": "task_started"},
        )
        return room, members[:1]

    async def stop(self, room_id: str) -> Chat:
        """Ask a running conversation to stop after the current turn."""
        room = await self._room(room_id)
        status = room.settings.get("task_status")
        return await self._update_settings(
            room,
            stop_requested=True,
            task_status="stopped" if status == "running" else status,
        )

    async def converse(self, room_id: str, speakers: Sequence[Agent]) -> RoomOutcome:
        """Let agents answer in turn, following handoffs until the room settles."""
        room = await self._room(room_id)
        if room.settings.get("stop_requested"):
            room = await self._update_settings(room, stop_requested=False)
        members = await self.members(room)
        queue: list[Agent] = list(speakers)
        spoke: list[str] = []
        configured = room.settings.get("turn_limit")
        limit = (
            configured
            if isinstance(configured, int) and configured > 0
            else self._turn_limit
        )
        nudges = 0
        while len(spoke) < limit:
            room = await self._room(room_id)
            if room.settings.get("stop_requested"):
                return RoomOutcome(
                    turns=len(spoke), speakers=tuple(spoke), stopped=True
                )
            if not queue:
                if (
                    room.settings.get("task_status") != "running"
                    or nudges >= MAX_NUDGES
                ):
                    break
                nudges += 1
                await self._store.append_message(
                    chat_id=room.id,
                    role="event",
                    text="Status check: is the task done? Finish it or hand off.",
                    author="studio",
                    data={"kind": "nudge"},
                )
                queue.append(members[0])
            agent = queue.pop(0)
            text = await self._turn(room, agent, members)
            spoke.append(agent.name)
            summary = completion_summary(text) if text else None
            if summary is not None and room.settings.get("task_status") == "running":
                await self._complete(room, members, summary)
                return RoomOutcome(
                    turns=len(spoke),
                    speakers=tuple(spoke),
                    completed=True,
                    summary=summary,
                )
            for handoff in mentioned(text, members, exclude=agent.id):
                if not queue or queue[-1].id != handoff.id:
                    queue.append(handoff)
        if queue or len(spoke) >= limit:
            await self._store.append_message(
                chat_id=room.id,
                role="event",
                text=(
                    f"Paused after {len(spoke)} turns. Reply or press Continue to let "
                    "the agents keep going."
                ),
                author="studio",
                data={"kind": "turn_limit"},
            )
        return RoomOutcome(turns=len(spoke), speakers=tuple(spoke))

    async def _turn(self, room: Chat, agent: Agent, members: Sequence[Agent]) -> str:
        transcript = await self._store.transcript(room.id, limit=HISTORY_WINDOW)
        history = room_history(agent, transcript)
        roster = (
            ", ".join(
                f"@{member.name} ({member.role}, {member.model})"
                for member in members
                if member.id != agent.id
            )
            or "no other agents"
        )
        goal = (
            str(room.settings.get("goal") or "") or "none yet; just talk with the user."
        )
        prompt = ROOM_PROMPT.format(name=agent.name, roster=roster, goal=goal)
        latest = history[-1].content if history else ""
        result = await self._runner.respond(
            agent, room, history=history, query=latest, extra_system=prompt
        )
        if agent.memory_enabled and result.text:
            await self._memory.remember(
                agent.id,
                f"In room '{room.title}' I said: {result.text.strip()[:180]}",
                scope="working",
                source=f"room:{room.id}",
                chat_id=room.id,
            )
        return result.text

    async def _complete(
        self, room: Chat, members: Sequence[Agent], summary: str
    ) -> None:
        goal = str(room.settings.get("goal") or "")
        await self._update_settings(room, task_status="done", summary=summary)
        await self._store.append_message(
            chat_id=room.id,
            role="event",
            text=f"Task complete: {summary}",
            author="studio",
            data={"kind": "task_complete", "summary": summary},
        )
        text = f"Finished a team task: {goal[:120]} — {summary[:160]}"
        if self._memory.shared_enabled:
            names = ", ".join(member.name for member in members)
            await self._memory.share(
                text,
                author=names or "room",
                tags=("room", "task"),
                source=f"room:{room.id}",
                chat_id=room.id,
            )
            return
        for member in members:
            if member.memory_enabled:
                await self._memory.remember(
                    member.id,
                    text,
                    tags=("room", "task"),
                    source=f"room:{room.id}",
                    chat_id=room.id,
                )

    async def _room(self, room_id: str) -> Chat:
        room = await self._store.require(Chat, room_id)
        if room.kind != "room":
            raise RoomError("That chat is not a room.")
        return room

    async def _update_settings(self, room: Chat, **values: object) -> Chat:
        current = await self._store.require(Chat, room.id)
        updated = current.model_copy(
            update={
                "settings": {**current.settings, **values},
                "updated_at": now_ms(),
            }
        )
        await self._store.put(updated)
        return updated
