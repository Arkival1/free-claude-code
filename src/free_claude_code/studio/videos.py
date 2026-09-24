"""Turn YouTube transcripts into notes the agents can use and look back at."""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from loguru import logger

from .llm import ChatMessage, StudioLLMError, StudioModelRouter
from .memory import keywords
from .models import VideoNote, now_ms
from .platforms import PlatformPage, PlatformReader, youtube_id
from .research import excerpt, relevance
from .store import StudioStore

CHUNK_CHARS = 7_000
MAX_CHUNKS = 8
"""About an hour of speech is read in full; longer videos keep each part's
most telling sentences, so every part still fits a small local model."""
PASSAGE_SECONDS = 45
VIDEO_TAGS = ("video", "youtube")
_HEADINGS = {
    "summary": "summary",
    "key points": "points",
    "steps": "steps",
    "names": "names",
    "tools and names": "names",
    "watch out": "cautions",
    "cautions": "cautions",
}
_HEADING = re.compile(r"^\s*#*\s*\**\s*([A-Za-z ]+?)\s*\**\s*:\s*(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")

DIGEST_PROMPT = (
    "You turn a video transcript into notes other AI agents will work from. "
    "Write only what the video says; never invent. Use exactly these headings, "
    "each on its own line, with short bullet lines under the ones that are "
    "lists:\n"
    "SUMMARY: two or three sentences on what the video teaches.\n"
    "KEY POINTS:\n- the facts, tips, and claims that matter (up to 8)\n"
    "STEPS:\n1. the how-to steps in order, if the video shows any\n"
    "NAMES:\n- tools, products, commands, settings, or people it names\n"
    "WATCH OUT:\n- warnings, mistakes, and limits it mentions\n"
    "Leave a heading empty when the video has nothing for it."
)
CHUNK_PROMPT = (
    "Here is one part of a long video transcript. List its important facts, "
    "steps, names, and warnings as short bullet lines. Write only what it says."
)


class VideoError(ValueError):
    """Raised when a video cannot be studied."""


@dataclass(frozen=True, slots=True)
class Digest:
    """What a video teaches, sorted for an agent."""

    summary: str
    points: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    cautions: tuple[str, ...] = ()


def clock(seconds: int) -> str:
    """Show a position in a video as m:ss or h:mm:ss."""
    hours, rest = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def at(url: str, seconds: int) -> str:
    """A link that starts the video at a moment."""
    return f"{url}&t={max(0, seconds)}s"


def parse_digest(text: str) -> Digest:
    """Read the model's notes back into their sections."""
    sections: dict[str, list[str]] = {name: [] for name in set(_HEADINGS.values())}
    current = "summary"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _HEADING.match(line)
        if heading and heading.group(1).strip().lower() in _HEADINGS:
            current = _HEADINGS[heading.group(1).strip().lower()]
            line = heading.group(2).strip()
            if not line:
                continue
        item = _BULLET.sub("", line).strip()
        if item and item.lower() not in {"none", "n/a", "-"}:
            sections[current].append(item)
    return Digest(
        summary=" ".join(sections["summary"])[:900],
        points=tuple(sections["points"][:10]),
        steps=tuple(sections["steps"][:15]),
        names=tuple(sections["names"][:15]),
        cautions=tuple(sections["cautions"][:8]),
    )


def plain_digest(title: str, transcript: str, description: str = "") -> Digest:
    """Notes without a model: the most telling sentences of the transcript."""
    terms = keywords(f"{title} {description}") or keywords(transcript, limit=8)
    lead = excerpt(description or transcript, terms, size=320)
    body = excerpt(transcript, terms, size=1_400)
    points = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", body)
        if len(sentence.strip()) > 30
    ]
    return Digest(summary=lead, points=tuple(points[:6]))


def render_note(note: VideoNote) -> str:
    """The notes an agent reads, with the link to watch."""
    lines = [f"Video notes: {note.title}", f"Link: {note.url}"]
    if note.focus:
        lines.append(f"Studied for: {note.focus}")
    if note.summary:
        lines += ["", f"Summary: {note.summary}"]
    for label, items in (
        ("Key points", note.points),
        ("Steps", note.steps),
        ("Names", note.names),
        ("Watch out", note.cautions),
    ):
        if items:
            numbered = label == "Steps"
            lines += ["", f"{label}:"]
            lines += [
                f"{index}. {item}" if numbered else f"- {item}"
                for index, item in enumerate(items, start=1)
            ]
    minutes = clock(note.segments[-1][0]) if note.segments else "?"
    lines += [
        "",
        f"Transcript: {len(note.segments)} lines, about {minutes} long. Ask "
        f"video_notes with id {note.id} and a query to read the exact parts.",
    ]
    return "\n".join(lines)


def memory_line(note: VideoNote) -> str:
    """The short entry the team's memory keeps for a studied video."""
    points = "; ".join(note.points[:4])
    return (
        f"Video notes: {note.title} ({note.url}). {note.summary[:320]}"
        + (f" Key points: {points}." if points else "")
        + f" Full notes and transcript: video_notes id {note.id}."
    )


def passages(note: VideoNote, query: str, *, limit: int = 4) -> list[tuple[int, str]]:
    """The parts of the transcript about a query, with where they start."""
    if not note.segments:
        return []
    windows: list[tuple[int, str]] = []
    start, words = note.segments[0][0], []
    for second, text in note.segments:
        if second - start >= PASSAGE_SECONDS and words:
            windows.append((start, " ".join(words)))
            start, words = second, []
        words.append(text)
    if words:
        windows.append((start, " ".join(words)))
    terms = keywords(query)
    if not terms:
        return windows[:limit]
    scored = [
        (relevance(text, terms), index) for index, (_, text) in enumerate(windows)
    ]
    best = sorted(
        (pair for pair in scored if pair[0] > 0), key=lambda pair: (-pair[0], pair[1])
    )
    return [windows[index] for _, index in sorted(best[:limit], key=lambda p: p[1])]


class VideoStudy:
    """Study videos into notes, keep them, and find them again."""

    def __init__(
        self,
        *,
        store: StudioStore,
        reader: PlatformReader,
        router: StudioModelRouter,
        model: Callable[[], Awaitable[str]],
        remember: Callable[[VideoNote], Awaitable[str]],
        lock: asyncio.Lock | None = None,
    ) -> None:
        self._store = store
        self._reader = reader
        self._router = router
        self._model = model
        self._remember = remember
        self._lock = lock or asyncio.Lock()

    async def note(self, note_id: str) -> VideoNote | None:
        return await self._store.get(VideoNote, note_id)

    async def delete(self, note_id: str) -> bool:
        return await self._store.delete(VideoNote, note_id)

    async def find_by_video(self, video_id: str) -> VideoNote | None:
        found = await self._store.find(VideoNote, where={"video_id": video_id})
        return found[0] if found else None

    async def study(
        self,
        url: str,
        *,
        focus: str = "",
        source: str = "agent",
        studied_by: str = "",
        page: PlatformPage | None = None,
    ) -> VideoNote:
        """Read a video's transcript and turn it into notes for the team."""
        video = youtube_id(url)
        if video is None:
            raise VideoError("That is not a YouTube video link.")
        known = await self.find_by_video(video)
        if known is not None and (not focus or focus == known.focus):
            return known
        if page is None:
            page = await self._reader.youtube_video(url)
        if not page.transcript or not page.segments:
            raise VideoError(
                page.note or "This video has no transcript YouTube would share."
            )
        # One study at a time, so a local model is not asked for several at once.
        async with self._lock:
            digest = await self._digest(page, focus)
        fields: dict[str, object] = {
            "video_id": video,
            "url": page.url,
            "title": page.title,
            "summary": digest.summary,
            "points": digest.points,
            "steps": digest.steps,
            "names": digest.names,
            "cautions": digest.cautions,
            "focus": focus,
            "source": source if source in {"research", "user", "agent"} else "agent",
            "studied_by": studied_by,
            "segments": page.segments,
        }
        if known is not None:
            fields |= {"id": known.id, "created_at": known.created_at}
        note = VideoNote.model_validate(fields)
        memory_id = await self._remember(note)
        note = note.model_copy(update={"memory_id": memory_id, "updated_at": now_ms()})
        await self._store.put(note)
        return note

    async def notes(self, query: str = "", *, limit: int = 8) -> list[VideoNote]:
        """Studied videos, best match for a query first, else newest first."""
        every = list(await self._store.find(VideoNote, order_by="updated_at DESC"))
        terms = keywords(query)
        if not terms:
            return every[:limit]
        scored = []
        for note in every:
            head = f"{note.title} {note.summary} {' '.join(note.points)} {' '.join(note.names)}"
            fit = 2 * relevance(head, terms) + relevance(
                " ".join(text for _, text in note.segments), terms
            )
            if fit > 0:
                scored.append((fit, note))
        scored.sort(key=lambda pair: -pair[0])
        return [note for _, note in scored[:limit]]

    async def _digest(self, page: PlatformPage, focus: str) -> Digest:
        transcript = " ".join(text for _, text in page.segments)
        description = _description(page.text)
        try:
            model = await self._model()
            chunks = _chunks(transcript, keywords(f"{page.title} {focus}"))
            if len(chunks) > 1:
                parts = [
                    await self._ask(model, CHUNK_PROMPT, chunk, max_tokens=500)
                    for chunk in chunks
                ]
                material = "\n\n".join(
                    f"Notes on part {index}:\n{part}"
                    for index, part in enumerate(parts, start=1)
                )
            else:
                material = f"Transcript:\n{transcript}"
            aim = f"\nThe team wants to know about: {focus}" if focus else ""
            text = await self._ask(
                model,
                DIGEST_PROMPT,
                f"Video: {page.title}{aim}\nDescription: {description[:600]}\n\n"
                f"{material}",
                max_tokens=900,
            )
            digest = parse_digest(text)
            if digest.summary or digest.points:
                return digest
        except StudioLLMError as error:
            logger.info("Studio: video notes fell back to plain notes: {}", error)
        return plain_digest(page.title, transcript, description)

    async def _ask(
        self, model: str, system: str, prompt: str, *, max_tokens: int
    ) -> str:
        reply = await self._router.complete(
            [ChatMessage.user(prompt)],
            model=model,
            system=system,
            temperature=0.1,
            max_tokens=max_tokens,
        )
        return reply.text.strip()


def _chunks(transcript: str, terms: Sequence[str] = ()) -> list[str]:
    if len(transcript) <= CHUNK_CHARS:
        return [transcript]
    size = max(CHUNK_CHARS, -(-len(transcript) // MAX_CHUNKS))
    parts = [
        transcript[start : start + size] for start in range(0, len(transcript), size)
    ]
    return [
        part if len(part) <= CHUNK_CHARS else excerpt(part, terms, size=CHUNK_CHARS)
        for part in parts[:MAX_CHUNKS]
    ]


def _description(text: str) -> str:
    if "Description:" not in text:
        return ""
    after = text.split("Description:", 1)[1]
    return after.split("\nTranscript:", 1)[0].strip()


def studied(notes: Sequence[VideoNote]) -> str:
    """A short list of studied videos for an agent."""
    if not notes:
        return "No videos have been studied yet."
    return "\n".join(
        f"- {note.id}: {note.title} ({note.url}) — {note.summary[:160]}"
        for note in notes
    )
