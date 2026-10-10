"""The ideas board: the user's references for the agents to work from.

Notes, photos, videos, and links of what the user wants: a UI they like, a
layout, a colour scheme, a competitor's site, a clip of an app in use. The
agents search it before they design or build and go in that direction with
their own business-level work; they don't copy it. Files stay on this PC;
what the user wrote about each one is what a text-only model reads.
"""

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import anyio

from .models import Idea, now_ms
from .photos import PhotoError, clean_name, image_info
from .store import StudioStore

IdeaKind = Literal["note", "photo", "video", "link"]
MAX_IDEA_PHOTO_BYTES = 25 * 1024 * 1024
MAX_IDEA_VIDEO_BYTES = 200 * 1024 * 1024
MAX_TITLE = 120
MAX_TEXT = 4_000
MAX_TAGS = 12
_PHOTOS = {
    "jpeg": (".jpg", "image/jpeg"),
    "png": (".png", "image/png"),
    "webp": (".webp", "image/webp"),
    "gif": (".gif", "image/gif"),
}


class IdeaError(ValueError):
    """An idea could not be kept or found."""


def video_info(data: bytes) -> tuple[str, str]:
    """(suffix, content type) of an MP4, MOV, or WebM video, from its header."""
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm", "video/webm"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand == b"qt  ":
            return ".mov", "video/quicktime"
        if brand in {b"heic", b"heix", b"mif1", b"hevc"}:
            raise IdeaError("That's a HEIC photo, not a video; add it as a photo.")
        return ".mp4", "video/mp4"
    raise IdeaError("Add videos as MP4, MOV, or WebM.")


def clean_tags(tags: object) -> tuple[str, ...]:
    """Tags as short lower-case words: from a list or a comma-separated text."""
    items = tags if isinstance(tags, list | tuple) else str(tags or "").split(",")
    found: list[str] = []
    for item in items:
        tag = re.sub(r"[^a-z0-9 -]+", "", str(item).lower()).strip()[:30]
        if tag and tag not in found:
            found.append(tag)
    return tuple(found[:MAX_TAGS])


def clean_url(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise IdeaError("A link starts with http:// or https://.")
    return text[:2000]


class IdeaBoard:
    """The ideas board: what the user wrote in the store, files on disk."""

    def __init__(self, store: StudioStore, root: Path) -> None:
        self._store = store
        self._root = root

    def path(self, idea: Idea) -> Path:
        return self._root / idea.file

    async def add(
        self,
        *,
        title: str = "",
        text: str = "",
        url: str = "",
        tags: object = (),
        project: str = "",
        name: str = "",
        data: bytes | None = None,
    ) -> Idea:
        """Keep one idea: a file (photo or video) when data comes with it, a
        link when there is a url, else a note."""
        kind: IdeaKind = "link" if url.strip() else "note"
        suffix = content_type = ""
        width = height = 0
        if data is not None:
            if not data:
                raise IdeaError("That file is empty.")
            try:
                found, width, height = image_info(data)
            except PhotoError:
                if len(data) > MAX_IDEA_VIDEO_BYTES:
                    raise IdeaError("Add videos up to 200 MB.") from None
                suffix, content_type = video_info(data)
                kind = "video"
            else:
                if len(data) > MAX_IDEA_PHOTO_BYTES:
                    raise IdeaError("Add photos up to 25 MB.")
                suffix, content_type = _PHOTOS[found]
                kind = "photo"
        heading = " ".join(title.split())[:MAX_TITLE]
        if not heading and name:
            heading = clean_name(name).replace("-", " ")
        if not heading and kind in {"note", "link"}:
            heading = " ".join(text.split())[:60]
        if not heading:
            raise IdeaError("Give the idea a title.")
        if kind == "note" and not text.strip():
            raise IdeaError("Write the idea, add a link, or attach a photo or video.")
        idea = Idea(
            kind=kind,
            title=heading,
            text=text.strip()[:MAX_TEXT],
            url=clean_url(url),
            tags=clean_tags(tags),
            project=" ".join(project.split())[:80],
            content_type=content_type,
            width=width,
            height=height,
            size=len(data) if data is not None else 0,
        )
        if data is not None:
            idea = idea.model_copy(update={"file": f"{idea.id}{suffix}"})
            stored = idea

            def work() -> None:
                self._root.mkdir(parents=True, exist_ok=True)
                self.path(stored).write_bytes(data)

            await anyio.to_thread.run_sync(work)
        await self._store.put(idea)
        return idea

    async def ideas(
        self, query: str = "", *, kind: str = "", tag: str = "", project: str = ""
    ) -> tuple[Idea, ...]:
        """Every idea, newest first, or those that match: words in the title,
        notes, tags, link, or project, a kind, a tag, a project."""
        every = await self._store.find(Idea, order_by="created_at DESC")
        words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
        wanted_tag = tag.strip().lower()
        wanted_project = project.strip().lower()
        found = []
        for idea in every:
            if kind and idea.kind != kind:
                continue
            if wanted_tag and wanted_tag not in idea.tags:
                continue
            if wanted_project and wanted_project not in idea.project.lower():
                continue
            haystack = " ".join(
                (idea.title, idea.text, " ".join(idea.tags), idea.url, idea.project)
            ).lower()
            if words and not any(word in haystack for word in words):
                continue
            found.append(idea)
        return tuple(found)

    async def find(self, reference: str) -> Idea:
        """An idea by its id or its title."""
        wanted = " ".join(reference.split()).lower()
        for idea in await self._store.find(Idea, order_by="created_at DESC"):
            if wanted in {idea.id, idea.title.lower()}:
                return idea
        raise IdeaError(f"No idea called {reference!r}; search the ideas board.")

    async def read(self, idea: Idea) -> bytes:
        if not idea.file:
            raise IdeaError(f"{idea.title} has no file.")
        return await anyio.to_thread.run_sync(self.path(idea).read_bytes)

    async def update(self, idea_id: str, values: dict[str, object]) -> Idea:
        idea = await self._store.require(Idea, idea_id)
        changes: dict[str, object] = {"updated_at": now_ms()}
        if "title" in values:
            title = " ".join(str(values["title"] or "").split())[:MAX_TITLE]
            if not title:
                raise IdeaError("Give the idea a title.")
            changes["title"] = title
        if "text" in values:
            changes["text"] = str(values["text"] or "").strip()[:MAX_TEXT]
        if "url" in values:
            changes["url"] = clean_url(str(values["url"] or ""))
        if "tags" in values:
            changes["tags"] = clean_tags(values["tags"])
        if "project" in values:
            changes["project"] = " ".join(str(values["project"] or "").split())[:80]
        updated = idea.model_copy(update=changes)
        await self._store.put(updated)
        return updated

    async def delete(self, idea_id: str) -> bool:
        idea = await self._store.get(Idea, idea_id)
        if idea is None:
            return False
        if idea.file:
            await anyio.to_thread.run_sync(
                lambda: self.path(idea).unlink(missing_ok=True)
            )
        return await self._store.delete(Idea, idea_id)


def describe(idea: Idea, *, full: bool = False) -> str:
    """What an agent reads about one idea: its kind, title, the user's notes,
    tags, and link."""
    parts = [f"[{idea.kind}] {idea.title} (id {idea.id})"]
    if idea.kind == "photo" and idea.width:
        parts.append(f"{idea.width}x{idea.height} photo")
    if idea.project:
        parts.append(f"for {idea.project}")
    if idea.tags:
        parts.append("tags: " + ", ".join(idea.tags))
    if idea.url:
        parts.append(f"link: {idea.url}")
    notes = (
        idea.text if full else idea.text[:300] + ("…" if len(idea.text) > 300 else "")
    )
    if notes:
        parts.append(f"the user says: {notes}")
    return " — ".join(parts)
