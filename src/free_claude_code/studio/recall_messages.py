"""Find the exact earlier messages that matter, word for word."""

from collections.abc import Sequence
from dataclasses import dataclass

from .memory import keywords
from .models import Message, now_ms
from .research import relevance

RECALL_HEADER = (
    "Earlier messages that match what the user just said (exact words, kept "
    "by Studio, not from the user):"
)
MAX_RECALLED = 6
MAX_RECALL_CHARS = 2_400
MAX_MESSAGE_CHARS = 700


@dataclass(frozen=True, slots=True)
class Found:
    """One earlier message and which conversation it came from."""

    message: Message
    earlier_chat: bool = False


def _ago(ms: int) -> str:
    minutes = max(0, (now_ms() - ms) // 60_000)
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} h ago" if hours < 48 else f"{hours // 24} days ago"


def speaker(message: Message) -> str:
    if message.role == "user":
        return "User"
    if message.role == "tool":
        return f"(tool {message.author})"
    if message.role == "event":
        return "(update)"
    return message.author or "Assistant"


def line(message: Message, *, limit: int = MAX_MESSAGE_CHARS, where: str = "") -> str:
    """'#12 (3 h ago) User: ...' for one message."""
    text = " ".join(message.text.split())
    if len(text) > limit:
        text = f"{text[:limit]}…"
    return f"#{message.sequence}{where} ({_ago(message.created_at)}) {speaker(message)}: {text}"


def search(
    messages: Sequence[Found], query: str, *, limit: int = MAX_RECALLED
) -> list[Found]:
    """The messages that best match a query, in the order they were said."""
    terms = keywords(query)
    if not terms:
        return []
    scored: list[tuple[float, int, Found]] = []
    for index, found in enumerate(messages):
        text = found.message.text
        if not text.strip():
            continue
        fit = relevance(text, terms)
        # A single shared word is only a match when the question is short.
        if fit <= 0 or (len(terms) >= 3 and fit < 0.34):
            continue
        weight = fit + (0.1 if found.message.role == "user" else 0.0)
        scored.append((weight, index, found))
    best = sorted(scored, key=lambda item: (-item[0], -item[1]))[:limit]
    return [found for _, _, found in sorted(best, key=lambda item: item[1])]


def recall_note(found: Sequence[Found]) -> str:
    """The matching messages as a note for the latest user message."""
    lines: list[str] = []
    used = 0
    for item in found:
        where = " in an earlier conversation" if item.earlier_chat else ""
        text = line(item.message, where=where)
        if used + len(text) > MAX_RECALL_CHARS:
            break
        lines.append(text)
        used += len(text)
    if not lines:
        return ""
    return f"{RECALL_HEADER}\n" + "\n".join(lines)
