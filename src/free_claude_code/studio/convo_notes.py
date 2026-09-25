"""Running notes on a long conversation, so nothing is lost when old messages
leave an agent's view."""

from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from loguru import logger

from .llm import ChatMessage, StudioLLMError, StudioModelRouter
from .models import ChatNotes, Message
from .store import StudioStore

NOTES_HEADER = "Notes on the earlier part of this conversation (kept by Studio):"
MAX_NOTES_CHARS = 3_600
MAX_LINE_CHARS = 400
NOTES_PROMPT = (
    "You keep the running notes of a conversation between the user and {name}, "
    "so {name} never loses track once older messages are out of view. Update "
    "the notes with the new messages: keep everything that still matters and "
    "fold in what is new. Keep who the user is and what they want, decisions "
    "made, facts, names, numbers, links, files and projects, what each agent "
    "was asked and what it reported, promises {name} made, and open questions "
    "and next steps. Drop small talk. Write short bullet points under these "
    "headings, leaving out empty ones: Goal, Timeline (one line per thing that "
    "happened, oldest first, with the message number like #12), Decisions, "
    "Facts, Work in progress, Open questions. Keep exact names, numbers, "
    "links, file names, and the user's own words where they matter. Stay under "
    "400 words. Write only the notes."
)

type Spawn = Callable[[Coroutine[Any, Any, None]], object]


def transcript_lines(messages: Sequence[Message]) -> str:
    """The messages as short labelled lines for the note keeper to read."""
    lines: list[str] = []
    for message in messages:
        text = " ".join(message.text.split())[:MAX_LINE_CHARS]
        if not text:
            continue
        number = f"#{message.sequence} "
        if message.role == "user":
            lines.append(f"{number}User: {text}")
        elif message.role == "assistant":
            lines.append(f"{number}{message.author or 'Assistant'}: {text}")
        elif message.role == "tool":
            lines.append(f"{number}(tool {message.author}): {text}")
        elif message.role == "event":
            lines.append(f"{number}(update): {text}")
    return "\n".join(lines)


class NotesKeeper:
    """Writes each conversation's running notes, one conversation at a time."""

    def __init__(
        self,
        *,
        store: StudioStore,
        router: StudioModelRouter,
        spawn: Spawn | None = None,
    ) -> None:
        self._store = store
        self._router = router
        self._spawn = spawn
        self._busy: set[str] = set()

    async def get(self, chat_id: str) -> ChatNotes:
        """A conversation's notes (empty when none are written yet)."""
        return await self._store.get(ChatNotes, chat_id) or ChatNotes(id=chat_id)

    def keep_up(self, chat_id: str, until: int, *, model: str, name: str) -> None:
        """Make sure the notes cover every message up to ``until``."""
        if chat_id in self._busy:
            return
        if self._spawn is not None:
            self._spawn(self._update(chat_id, until, model=model, name=name))

    async def update_now(
        self, chat_id: str, until: int, *, model: str, name: str
    ) -> None:
        await self._update(chat_id, until, model=model, name=name)

    async def _update(self, chat_id: str, until: int, *, model: str, name: str) -> None:
        if chat_id in self._busy:
            return
        self._busy.add(chat_id)
        try:
            current = await self.get(chat_id)
            if until <= current.until:
                return
            leaving = [
                message
                for message in await self._store.transcript(
                    chat_id, after=current.until
                )
                if message.sequence <= until
            ]
            lines = transcript_lines(leaving)
            written = current.text
            if lines:
                try:
                    written = await self._write(name, written, lines, model=model)
                except StudioLLMError as error:
                    # Without a model the messages simply stay in view.
                    logger.info("Studio: conversation notes not updated: {}", error)
                    return
            await self._store.put(
                ChatNotes(id=chat_id, text=written[:MAX_NOTES_CHARS], until=until)
            )
        finally:
            self._busy.discard(chat_id)

    async def _write(self, name: str, notes: str, lines: str, *, model: str) -> str:
        prompt = (
            f"Current notes:\n{notes or '(none yet)'}\n\n"
            f"New messages to fold in:\n{lines}"
        )
        reply = await self._router.complete(
            [ChatMessage.user(prompt)],
            model=model,
            system=NOTES_PROMPT.format(name=name),
            temperature=0.1,
            max_tokens=600,
        )
        text = reply.text.strip()
        if not text:
            raise StudioLLMError("The model wrote empty notes.")
        return text
