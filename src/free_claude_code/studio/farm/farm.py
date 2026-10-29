"""The Content Farm: channels, an idea board, a line that makes videos, and
an editor for when the AI gets it wrong.

A channel is one account: a niche (often a show, movie, or game), a style, a
voice, and when it posts. Shorts are 9:16 and quick; long videos are calm
two-hour narrations of a show's lore or a what-if, to fall asleep to. The
farm writes each script with the team's local model (using the show's fandom
wiki), reads it with the built-in voice, picks a picture or clip for every
scene (your library first), and renders the MP4. Every scene keeps its line,
its picture, and its voice clip, so you or the AI can change one scene and
render again in a fraction of the time. Posting stays with the user: the
platforms only allow it from their own apps or business APIs.
"""

import asyncio
import concurrent.futures
import contextlib
import hashlib
import json
import re
import shutil
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import anyio
import httpx
from loguru import logger

from free_claude_code.core.json_types import JsonObject

from ..models import FarmChannel, FarmCharacter, FarmPost, now_ms
from ..store import StudioStore
from . import animated, formats, longform
from .animated import AnimatedError, Hear
from .cartoon.aiart import ArtBook, Paint
from .fandom import Fandom
from .formats import Script, style_of
from .library import LibraryError, MediaLibrary
from .media import MediaPicker
from .render import Plan, RenderError, Shot, render, thumbnail, video_tools
from .timing import (
    GAP,
    chunks,
    reading_time,
    spread_words,
    wav_length,
    write_joined,
)
from .visuals import Visuals

Think = Callable[[str, str], Awaitable[str]]
"""Ask the farm's writer (the team's local model): (system, prompt) → text."""
Speak = Callable[[str, str, float], Awaitable[bytes | None]]
"""Read a line aloud: (text, voice, speed) → WAV bytes, or None with no voice."""
Research = Callable[[str], Awaitable[str]]
"""Search the web: query → a few lines of results, or '' when offline."""

MAX_CHANNELS = 30
MAX_POSTS = 600
MAX_IDEAS = 10
MAX_EDIT_SCENES = 40
"""Scenes the AI edits at once: a long video is edited a chapter at a time."""
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_RESEARCHED = {"facts", "explainer", "news", "tips"}
ACTIVE = ("making",)
DONE = ("ready", "posted")
SHORT_SPEED = 1.08
LONG_SPEED = 0.92
"""A sleep video's voice is slower."""
LONG_GAP = 0.45


class FarmError(ValueError):
    """Something the farm can't do, said plainly."""


def whole(value: object, default: int) -> int:
    """A number from a form or a model's arguments, or the default."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return int(value)
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return default


def _text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def clean_times(raw: object) -> tuple[str, ...]:
    items = raw if isinstance(raw, list | tuple) else str(raw or "").split(",")
    times: dict[str, None] = {}
    for item in items:
        found = _TIME.match(str(item).strip())
        if found:
            times.setdefault(f"{int(found.group(1)):02d}:{found.group(2)}", None)
    return tuple(sorted(times)) or ("18:00",)


def _choice(value: object, allowed: Sequence[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def is_long(channel: FarmChannel) -> bool:
    return style_of(channel.style).long


def channel_view(
    channel: FarmChannel, counts: dict[str, int] | None = None
) -> JsonObject:
    view: JsonObject = channel.model_dump()
    view["post_times"] = list(channel.post_times)
    view["hashtags"] = list(channel.hashtags)
    view["style_label"] = style_of(channel.style).label
    view["kind"] = "long" if is_long(channel) else "short"
    view["platform_label"] = (
        "YouTube (long)"
        if is_long(channel)
        else formats.PLATFORMS.get(channel.platform, channel.platform)
    )
    view["counts"] = dict(counts or {})
    return view


def _scenes(data: JsonObject) -> list[JsonObject]:
    raw = data.get("scenes")
    return (
        [dict(item) for item in raw if isinstance(item, dict)]
        if isinstance(raw, list)
        else []
    )


def _seconds(value: object) -> float:
    try:
        return max(0.0, float(str(value or 0)))
    except ValueError:
        return 0.0


def _voice_key(voice: str, speed: float, say: str) -> str:
    return hashlib.sha1(f"{voice}|{speed}|{say}".encode()).hexdigest()[:20]


class ContentFarm:
    def __init__(
        self,
        store: StudioStore,
        root: Path,
        *,
        think: Think,
        speak: Speak,
        research: Research,
        visuals: Callable[[], Visuals],
        library: MediaLibrary | None = None,
        fandom: Fandom | None = None,
        video_size: Callable[[], str] = lambda: "720p",
        music: Callable[[], Path | None] = lambda: None,
        pexels_key: Callable[[], str] = lambda: "",
        hear: Hear | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        paint: Paint | None = None,
        paints: Callable[[], bool] = lambda: False,
        art_style: Callable[[], str] = lambda: "superhero",
    ) -> None:
        self._paint = paint
        self._paints = paints
        self._art_style = art_style
        self._store = store
        self._root = root
        self._think = think
        self._speak = speak
        self._research = research
        self._visuals = visuals
        self.library = library or MediaLibrary(store, root / "library")
        self.fandom = fandom or Fandom(transport)
        self._transport = transport
        self._video_size = video_size
        self._music = music
        self._pexels_key = pexels_key
        self._hear = hear
        self._line = asyncio.Lock()
        """One video at a time: rendering uses every core."""
        self._stopped: set[str] = set()
        self._recovered = False

    def art_book(self) -> ArtBook | None:
        """Where painted cartoon art is kept, when cartoons are painted."""
        if self._paint is None or not self._paints():
            return None
        return ArtBook(self._root / "art", self._art_style(), self._paint)

    # ------------------------------------------------------------ channels

    async def channels(self) -> list[FarmChannel]:
        return list(await self._store.find(FarmChannel, order_by="created_at"))

    async def channel(self, channel_id: str) -> FarmChannel:
        found = await self._store.get(FarmChannel, channel_id)
        if found is None:
            raise FarmError("That channel isn't on the farm any more.")
        return found

    async def find_channel(self, name: str = "") -> FarmChannel:
        """A channel by id or name; the only one, or the newest, by default."""
        channels = await self.channels()
        if not channels:
            raise FarmError(
                "There are no channels yet. Add one on the Content Farm page, "
                "or say 'make a channel about <niche>'."
            )
        wanted = name.strip().lower().lstrip("@")
        if wanted:
            for channel in channels:
                if wanted in {channel.id.lower(), channel.name.lower()}:
                    return channel
            for channel in channels:
                if (
                    wanted in channel.name.lower()
                    or wanted in channel.niche.lower()
                    or (channel.fandom and wanted in channel.fandom.lower())
                ):
                    return channel
        return channels[-1]

    async def save_channel(
        self, fields: JsonObject, channel_id: str | None = None
    ) -> FarmChannel:
        old = await self.channel(channel_id) if channel_id else None
        if old is None and len(await self.channels()) >= MAX_CHANNELS:
            raise FarmError(f"The farm holds up to {MAX_CHANNELS} channels.")
        base: JsonObject = old.model_dump() if old else {}
        merged = {**base, **{k: v for k, v in fields.items() if v is not None}}
        name = _text(merged.get("name"), 60).lstrip("@")
        niche = _text(merged.get("niche"), 160)
        fandom = _text(merged.get("fandom"), 120)
        if not name:
            name = (
                re.sub(r"[^a-z0-9]+", "", (niche or fandom).lower())[:24] or "mychannel"
            )
        style = _choice(merged.get("style"), tuple(formats.STYLE_BY_KEY), "facts")
        long = style_of(style).long
        tags = merged.get("hashtags")
        background = _text(merged.get("background"), 40)
        song = _text(merged.get("song"), 40)
        if song:
            try:
                track = await self.library.asset(song)
            except LibraryError as error:
                raise FarmError(str(error)) from error
            if track.kind not in {"audio", "video"}:
                raise FarmError(
                    "The song has to be a sound file or a video with sound."
                )
        known = {c.id for c in await self.characters()}
        raw_cast = merged.get("cast")
        cast = [
            str(item)
            for item in (raw_cast if isinstance(raw_cast, list | tuple) else [])
            if str(item) in known
        ][: animated.MAX_CAST]
        theme = _text(merged.get("theme"), 9)
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", theme):
            theme = "#ff5fc8"
        if background:
            try:
                asset = await self.library.asset(background)
            except LibraryError as error:
                raise FarmError(str(error)) from error
            if asset.kind != "video":
                raise FarmError("The background has to be a clip from the library.")
        values: JsonObject = {
            "name": name,
            "niche": niche or fandom,
            "platform": _choice(
                merged.get("platform"), tuple(formats.PLATFORMS), "youtube"
            ),
            "style": style,
            "look": _choice(
                merged.get("look") if "look" in fields or old else None,
                formats.LOOKS,
                "cinema" if long else "bold",
            ),
            "visuals": _choice(merged.get("visuals"), formats.VISUALS, "auto"),
            "voice": _text(merged.get("voice"), 40)
            or ("bm_george" if long else "am_michael"),
            "seconds": formats.clamp_seconds(whole(merged.get("seconds"), 30)),
            "posts_per_day": max(1, min(10, whole(merged.get("posts_per_day"), 1))),
            "post_times": list(clean_times(merged.get("post_times"))),
            "hashtags": list(
                formats.clean_hashtags(tags if isinstance(tags, list | str) else [])
            ),
            "call_to_action": _text(merged.get("call_to_action"), 160),
            "notes": _text(merged.get("notes"), 1_000),
            "autopilot": bool(merged.get("autopilot")),
            "fandom": fandom,
            "wiki": _text(merged.get("wiki"), 200),
            "ai_media": bool(merged.get("ai_media", True)),
            "ai_polish": bool(merged.get("ai_polish", True)),
            "background": background,
            "minutes": longform.clamp_minutes(whole(merged.get("minutes"), 120)),
            "captions": bool(merged["captions"])
            if "captions" in fields or old
            else not long,
            "cast": list(dict.fromkeys(cast)),
            "series": _text(merged.get("series"), 80),
            "texture": _choice(merged.get("texture"), formats.TEXTURES, "wood"),
            "song": song,
            "theme": theme,
            "shape": _choice(merged.get("shape"), formats.SHAPES, "tall"),
            "pace": _choice(merged.get("pace"), formats.PACES, "auto"),
        }
        if old is not None:
            channel = old.model_copy(update={**values, "updated_at": now_ms()})
            channel = FarmChannel.model_validate(channel.model_dump())
        else:
            channel = FarmChannel.model_validate(values)
        return await self._store.put(channel)

    async def delete_channel(self, channel_id: str) -> bool:
        channel = await self.channel(channel_id)
        for post in await self.posts(channel.id):
            await self.delete_post(post.id)
        return await self._store.delete(FarmChannel, channel.id)

    # ------------------------------------------------------------ characters

    async def characters(self) -> list[FarmCharacter]:
        return list(await self._store.find(FarmCharacter, order_by="created_at"))

    async def character(self, character_id: str) -> FarmCharacter:
        found = await self._store.get(FarmCharacter, character_id)
        if found is None:
            raise FarmError("That character isn't on the farm any more.")
        return found

    async def save_character(
        self, fields: JsonObject, character_id: str | None = None
    ) -> FarmCharacter:
        """Add or change a cartoon character: how they look and sound."""
        old = await self.character(character_id) if character_id else None
        if old is None and len(await self.characters()) >= 200:
            raise FarmError("The farm holds up to 200 characters.")
        try:
            values = animated.clean_character(fields, old)
        except AnimatedError as error:
            raise FarmError(str(error)) from error
        if values["head_asset"]:
            try:
                head = await self.library.asset(str(values["head_asset"]))
            except LibraryError as error:
                raise FarmError(str(error)) from error
            if head.kind != "image":
                raise FarmError("A character's head has to be a picture.")
        if old is not None:
            changed = old.model_copy(update={**values, "updated_at": now_ms()})
            return await self._store.put(
                FarmCharacter.model_validate(changed.model_dump())
            )
        return await self._store.put(FarmCharacter.model_validate(values))

    async def character_picture(self, character_id: str) -> Path:
        """How a character looks, drawn once per change."""
        character = await self.character(character_id)
        out = self._root / "characters" / f"{character.id}-{character.updated_at}.png"
        if not out.is_file():
            head = (
                await self._asset_path(character.head_asset)
                if character.head_asset
                else None
            )
            look = animated.look_of(character, head)
            for old in out.parent.glob(f"{character.id}-*.png"):
                old.unlink(missing_ok=True)
            try:
                await anyio.to_thread.run_sync(
                    lambda: animated.draw_character(look, out)
                )
            except (OSError, ValueError) as error:
                raise FarmError(f"The character couldn't be drawn: {error}") from error
        return out

    async def delete_character(self, character_id: str) -> bool:
        character = await self.character(character_id)
        for channel in await self.channels():
            if character.id in channel.cast:
                cast = [c for c in channel.cast if c != character.id]
                await self._store.put(
                    channel.model_copy(
                        update={"cast": tuple(cast), "updated_at": now_ms()}
                    )
                )
        return await self._store.delete(FarmCharacter, character.id)

    # ------------------------------------------------------------ posts

    async def posts(
        self, channel_id: str | None = None, *, status: str | None = None
    ) -> list[FarmPost]:
        where: JsonObject = {}
        if channel_id:
            where["channel_id"] = channel_id
        if status:
            where["status"] = status
        return list(
            await self._store.find(FarmPost, where=where, order_by="created_at DESC")
        )

    async def post(self, post_id: str) -> FarmPost:
        found = await self._store.get(FarmPost, post_id)
        if found is None:
            raise FarmError("That video isn't on the farm any more.")
        return found

    def folder(self, post: FarmPost) -> Path:
        return self._root / "posts" / post.id

    def file(self, post: FarmPost, name: str) -> Path:
        folder = self.folder(post).resolve()
        path = (folder / name).resolve()
        if folder not in path.parents:
            raise FarmError("No such file.")
        return path

    async def delete_post(self, post_id: str) -> bool:
        post = await self.post(post_id)
        if post.status == "making":
            self._stopped.add(post.id)
        folder = self.folder(post)
        await anyio.to_thread.run_sync(
            lambda: shutil.rmtree(folder, ignore_errors=True)
        )
        return await self._store.delete(FarmPost, post.id)

    def stop(self, post_id: str) -> None:
        """Stop a video being made; what was written and voiced is kept."""
        self._stopped.add(post_id)

    async def mark_posted(self, post_id: str, posted: bool = True) -> FarmPost:
        post = await self.post(post_id)
        if post.status not in DONE:
            raise FarmError("Only a finished video can be marked as posted.")
        return await self._update(
            post,
            status="posted" if posted else "ready",
            posted_at=now_ms() if posted else 0,
        )

    async def edit_post(self, post_id: str, fields: JsonObject) -> FarmPost:
        """Change an idea's title, or a finished video's caption or time."""
        post = await self.post(post_id)
        update: JsonObject = {}
        if "title" in fields and post.status in {"idea", "failed"}:
            title = _text(fields.get("title"), 140)
            if title:
                update["title"] = title
        data = dict(post.data)
        if "caption" in fields:
            data["caption_full"] = str(fields.get("caption") or "")[:5_000]
            update["data"] = data
        if "scheduled_at" in fields:
            update["scheduled_at"] = max(0, whole(fields.get("scheduled_at"), 0))
        return await self._update(post, **update) if update else post

    async def _update(self, post: FarmPost, **fields: object) -> FarmPost:
        fresh = await self._store.get(FarmPost, post.id)
        if fresh is None:
            raise FarmError("That video was deleted.")
        changed = fresh.model_copy(update={**fields, "updated_at": now_ms()})
        return await self._store.put(FarmPost.model_validate(changed.model_dump()))

    async def _trim(self) -> None:
        posts = await self._store.find(FarmPost, order_by="created_at DESC")
        for extra in posts[MAX_POSTS:]:
            if extra.status != "making":
                await self.delete_post(extra.id)

    async def recover(self) -> None:
        """Videos left half made when the app closed are marked failed (what
        was written and voiced is kept: Make carries on from there)."""
        if self._recovered:
            return
        self._recovered = True
        if self._line.locked():
            return
        for post in await self.posts(status="making"):
            await self._update(
                post,
                status="failed",
                error="The app closed while this was being made. Press Make to carry on.",
                stage="",
            )

    # ------------------------------------------------------------ ideas

    async def ideas(
        self,
        channel: FarmChannel,
        *,
        count: int = 5,
        topic: str = "",
        made_by: str = "You",
    ) -> list[FarmPost]:
        """New ideas on the board, written by the farm's writer."""
        count = max(1, min(MAX_IDEAS, count))
        trends = ""
        if channel.fandom:
            trends = await self.fandom.lore(
                channel.fandom, topic or channel.fandom, link=channel.wiki, chars=2_000
            )
        elif channel.style in _RESEARCHED:
            trends = await self._research(
                f"{topic or channel.niche} {datetime.now():%B %Y}"
            )
        prompt = formats.ideas_prompt(
            niche=f"{channel.niche} (this time about: {topic})"
            if topic
            else channel.niche,
            style=channel.style,
            platform=channel.platform,
            count=count,
            notes=channel.notes,
            trends=trends,
            fandom=channel.fandom,
        )
        reply = await self._think(formats.IDEAS_SYSTEM, prompt)
        titles = formats.parse_ideas(reply, count=count)
        if not titles:
            raise FarmError("The writer didn't come up with ideas; try again.")
        made = [
            FarmPost(channel_id=channel.id, title=title, made_by=made_by)
            for title in titles
        ]
        await self._store.put_many(made)
        await self._trim()
        return made

    async def add_idea(
        self, channel: FarmChannel, title: str, made_by: str = "You"
    ) -> FarmPost:
        title = _text(title, 140)
        if not title:
            raise FarmError("Say what the video is about.")
        return await self._store.put(
            FarmPost(channel_id=channel.id, title=title, made_by=made_by)
        )

    # ------------------------------------------------------------ making

    async def make(
        self,
        post_id: str,
        *,
        rewrite: bool = False,
        on_change: Callable[[FarmPost], Awaitable[None]] | None = None,
    ) -> FarmPost:
        """Write (unless the scenes are kept), voice, picture, and render one
        video. Slow: run it in the background; the post's stage and progress
        show how far it is. rewrite starts the script over."""
        post = await self.post(post_id)
        if post.status == "making":
            raise FarmError("That video is already being made.")
        channel = await self.channel(post.channel_id)
        data = dict(post.data)
        if rewrite:
            for key in ("scenes", "script", "long", "edited"):
                data.pop(key, None)
        post = await self._update(
            post,
            status="making",
            stage="Waiting for the video before it",
            progress=0,
            error="",
            data=data,
        )
        self._stopped.discard(post.id)
        async with self._line:
            try:
                post = await self._make(post, channel)
            except (FarmError, AnimatedError, LibraryError) as error:
                if not await self._store.get(FarmPost, post.id):
                    return post
                post = await self._update(
                    post, status="failed", stage="", error=str(error)
                )
            except Exception as error:
                logger.exception("Content Farm: making {} failed", post.id)
                post = await self._update(
                    post, status="failed", stage="", error=f"Something broke: {error}"
                )
            finally:
                self._stopped.discard(post.id)
        if on_change is not None:
            with contextlib.suppress(Exception):
                await on_change(post)
        return post

    def _check(self, post: FarmPost) -> None:
        if post.id in self._stopped:
            raise FarmError("Stopped. What was written and voiced is kept.")

    async def _stage(self, post: FarmPost, stage: str, progress: int) -> FarmPost:
        self._check(post)
        return await self._update(post, stage=stage, progress=progress)

    async def _make(self, post: FarmPost, channel: FarmChannel) -> FarmPost:
        ready, why = video_tools()
        if not ready:
            raise FarmError(f"Videos can't be made on this PC yet: {why}")
        kind = animated.kind_of(channel)
        if kind == "edit":
            return await animated.make_edit(self, post, channel, self._hear)
        long = is_long(channel)
        data = dict(post.data)
        if not _scenes(data):
            if kind == "cartoon":
                data = await animated.write_cartoon(self, post, channel, data)
            elif long:
                data = await self._write_long(post, channel, data)
            else:
                data = await self._write_short(post, channel, data)
            post = await self._update(post, data=data)
        scenes = _scenes(data)
        if not scenes:
            raise FarmError("The script has no scenes.")
        folder = self.folder(post)
        await anyio.to_thread.run_sync(
            lambda: folder.mkdir(parents=True, exist_ok=True)
        )
        post = await self._stage(post, "Recording the voiceover", 30 if long else 25)
        voices, lengths = await self._voice(post, channel, scenes, long)
        if kind == "cartoon":
            return await animated.finish_cartoon(
                self, post, channel, data, scenes, voices, lengths
            )
        post = await self._stage(post, "Finding pictures and clips", 52 if long else 45)
        scenes = await self._media(post, channel, scenes, lengths)
        data["scenes"] = scenes
        data.pop("edited", None)
        post = await self._update(post, data=data)
        post = await self._stage(post, "Rendering the video", 62)
        plan, audio = await self._plan(post, channel, scenes, voices, lengths, long)
        folder = self.folder(post)
        await self._render(
            post,
            lambda report, stopped: render(
                plan,
                audio=audio,
                out=folder / "video.mp4",
                cover=folder / "cover.jpg",
                progress=report,
                stopped=stopped,
            ),
        )
        return await self._finish(
            post,
            channel,
            data,
            duration=plan.duration,
            voiced=any(voices),
            long=long,
            chapters=plan.chapters,
        )

    # ---------------------------------------------------------- writing

    async def write(self, channel: FarmChannel, idea: str) -> Script:
        """A short's script, polished once by the AI when the channel says so."""
        style = style_of(channel.style)
        facts = ""
        if channel.fandom and style.fandom:
            facts = await self.fandom.lore(
                channel.fandom, idea, link=channel.wiki, chars=3_000
            )
        elif channel.style in _RESEARCHED or style.fandom:
            facts = await self._research(idea)
        prompt = formats.script_prompt(
            idea=idea,
            niche=channel.niche,
            style=channel.style,
            platform=channel.platform,
            seconds=channel.seconds,
            call_to_action=channel.call_to_action,
            notes=channel.notes,
            facts=facts,
            fandom=channel.fandom,
        )
        reply = await self._think(formats.WRITER_SYSTEM, prompt)
        script = formats.parse_script(
            reply, idea=idea, seconds=channel.seconds, channel_tags=channel.hashtags
        )
        if not script.scenes:
            raise FarmError("The writer's script was empty; try again.")
        if channel.ai_polish:
            draft = script.to_json()
            # The hook is the first scene; sent twice, an old one would come back.
            draft.pop("hook", None)
            polished = formats.parse_script(
                await self._think(
                    formats.POLISH_SYSTEM, json.dumps(draft, ensure_ascii=False)
                ),
                idea=idea,
                seconds=channel.seconds,
                channel_tags=channel.hashtags,
            )
            # A polish that lost half the script is worse than none.
            if len(polished.scenes) >= max(2, len(script.scenes) // 2) and (
                polished.words >= script.words * 0.6
            ):
                script = polished
        return script

    async def _write_short(
        self, post: FarmPost, channel: FarmChannel, data: JsonObject
    ) -> JsonObject:
        await self._stage(post, "Writing the script", 5)
        script = await self.write(channel, post.title)
        return {
            **data,
            "kind": "short",
            "script": script.to_json(),
            "scenes": [scene.to_json() for scene in script.scenes],
        }

    async def _write_long(
        self, post: FarmPost, channel: FarmChannel, data: JsonObject
    ) -> JsonObject:
        """Outline, then chapter by chapter, kept as it goes."""
        show = channel.fandom or channel.niche
        state = data.get("long") if isinstance(data.get("long"), dict) else {}
        assert isinstance(state, dict)
        chapters = (
            state.get("chapters") if isinstance(state.get("chapters"), list) else []
        )
        texts = state.get("texts") if isinstance(state.get("texts"), list) else []
        assert isinstance(chapters, list) and isinstance(texts, list)
        count = longform.chapter_count(channel.minutes)
        if not chapters:
            await self._stage(post, "Planning the chapters", 2)
            lore = await self._lore(channel, post.title, chars=3_000)
            reply = await self._think(
                longform.OUTLINE_SYSTEM,
                longform.outline_prompt(
                    title=post.title,
                    show=show,
                    style=channel.style,
                    minutes=channel.minutes,
                    notes=channel.notes,
                    lore=lore,
                ),
            )
            title, found = longform.parse_outline(reply, count=count, title=post.title)
            if len(found) < 3:
                raise FarmError("The writer's chapter plan was too short; try again.")
            chapters = list(found)
            state = {"title": title, "chapters": chapters, "texts": []}
            texts = []
            data = {**data, "kind": "long", "long": state}
            post = await self._update(post, data=data)
        words = longform.chapter_words(channel.minutes) * count // max(1, len(chapters))
        for number in range(len(texts), len(chapters)):
            chapter = chapters[number]
            assert isinstance(chapter, dict)
            post = await self._stage(
                post,
                f"Writing chapter {number + 1} of {len(chapters)}",
                2 + int(26 * number / len(chapters)),
            )
            lore = await self._lore(channel, f"{chapter.get('topic')}", chars=4_000)
            prompt = longform.chapter_prompt(
                title=str(state.get("title") or post.title),
                show=show,
                style=channel.style,
                chapter=chapter,
                number=number + 1,
                total=len(chapters),
                words=words,
                lore=lore,
                before=longform.summary(str(texts[-1])) if texts else "",
                notes=channel.notes,
            )
            text = longform.clean_narration(
                await self._think(longform.CHAPTER_SYSTEM, prompt)
            )
            if len(text.split()) < words // 2 and text:
                more = longform.clean_narration(
                    await self._think(
                        longform.CHAPTER_SYSTEM,
                        f"{prompt}\n\nIt so far:\n{text[-1_500:]}\n\nCarry on from "
                        "there, about the same length again, without repeating it.",
                    )
                )
                text = f"{text} {more}".strip()
            if not text:
                raise FarmError(f"The writer sent nothing for chapter {number + 1}.")
            texts.append(text)
            state = {**state, "texts": texts}
            data = {**data, "long": state}
            post = await self._update(post, data=data)
        scenes: list[JsonObject] = []
        for number, text in enumerate(texts):
            scenes += longform.scenes_from(str(text), chapter=number)
        tags = list(formats.clean_hashtags([], channel.hashtags))
        return {
            **data,
            "kind": "long",
            "script": {
                "title": str(state.get("title") or post.title),
                "hook": "",
                "caption": "",
                "hashtags": tags,
            },
            "scenes": scenes,
        }

    async def _lore(self, channel: FarmChannel, topic: str, *, chars: int) -> str:
        if channel.fandom:
            return await self.fandom.lore(
                channel.fandom, topic, link=channel.wiki, chars=chars
            )
        return await self._research(f"{channel.niche} {topic}")

    # ---------------------------------------------------------- voice

    async def _voice(
        self, post: FarmPost, channel: FarmChannel, scenes: list[JsonObject], long: bool
    ) -> tuple[list[Path | None], list[float]]:
        """Each scene's voice clip (kept by its words, so edits re-record only
        what changed) and how long each scene lasts."""
        speed = LONG_SPEED if long else SHORT_SPEED
        folder = self.folder(post) / "voice"
        voices: list[Path | None] = []
        lengths: list[float] = []
        silent = channel.voice == "none"
        for number, scene in enumerate(scenes):
            if number % 10 == 0:
                post = await self._stage(
                    post,
                    f"Recording the voiceover ({number + 1} of {len(scenes)})",
                    (30 if long else 25) + int(22 * number / len(scenes)),
                )
            say = str(scene.get("say") or "")
            # A cartoon character can speak in their own voice.
            voice = str(scene.get("voice") or channel.voice)
            clip = folder / f"{_voice_key(voice, speed, say)}.wav"
            if not silent and not clip.is_file():
                spoken = await self._speak(say, voice, speed)
                if spoken is None:
                    silent = True
                else:
                    folder.mkdir(parents=True, exist_ok=True)
                    await anyio.Path(clip).write_bytes(spoken)
            if not silent and clip.is_file():
                voices.append(clip)
                lengths.append(wav_length(clip.read_bytes()))
            else:
                voices.append(None)
                lengths.append(reading_time(say) * (1.25 if long else 1.0))
        if silent:
            # No voice on this PC: the whole video goes captions-only.
            lengths = [
                reading_time(str(s.get("say") or "")) * (1.25 if long else 1.0)
                for s in scenes
            ]
            voices = [None] * len(scenes)
        return voices, lengths

    # ---------------------------------------------------------- media

    def picker(self, post: FarmPost, channel: FarmChannel) -> MediaPicker:
        long = is_long(channel)
        return MediaPicker(
            library=self.library,
            fandom=self.fandom,
            visuals=self._visuals(),
            folder=self.folder(post),
            show=channel.fandom,
            niche=channel.niche,
            wiki=channel.wiki,
            mode=channel.visuals,
            allow_ai=channel.ai_media,
            prefer_clips=long,
            pexels_key=self._pexels_key(),
            transport=self._transport,
        )

    async def _media(
        self,
        post: FarmPost,
        channel: FarmChannel,
        scenes: list[JsonObject],
        lengths: list[float],
    ) -> list[JsonObject]:
        picker = self.picker(post, channel)
        long = is_long(channel)
        chapters = [
            str(chapter.get("topic") or chapter.get("title") or "")
            for chapter in _chapter_list(post.data)
        ]
        for scene in scenes:
            media = scene.get("media")
            if isinstance(media, dict):
                for key in ("asset", "url"):
                    if media.get(key):
                        picker.used.add(str(media[key]))
        for number, scene in enumerate(scenes):
            if isinstance(scene.get("media"), dict) and scene["media"]:
                continue
            if number % 5 == 0:
                post = await self._stage(
                    post,
                    f"Finding pictures and clips ({number + 1} of {len(scenes)})",
                    (52 if long else 45) + int(10 * number / len(scenes)),
                )
            chapter = whole(scene.get("chapter"), -1)
            topic = chapters[chapter] if 0 <= chapter < len(chapters) else post.title
            scene["media"] = await picker.pick(
                scene, topic=topic, length=lengths[number]
            )
        return scenes

    def media_path(self, post: FarmPost, media: JsonObject) -> Path | None:
        """Where a scene's picture or clip is on this PC."""
        if media.get("file"):
            try:
                return self.file(post, str(media["file"]))
            except FarmError:
                return None
        return None

    async def _asset_path(self, asset_id: str) -> Path | None:
        try:
            return self.library.path(await self.library.asset(asset_id))
        except ValueError:
            return None

    # ---------------------------------------------------------- render

    async def _plan(
        self,
        post: FarmPost,
        channel: FarmChannel,
        scenes: list[JsonObject],
        voices: list[Path | None],
        lengths: list[float],
        long: bool,
    ) -> tuple[Plan, Path]:
        gap = LONG_GAP if long else GAP
        shots: list[Shot] = []
        words: tuple = ()
        chapter_starts: list[tuple[float, str]] = []
        titles = _chapter_titles(post.data)
        seen_chapters: set[int] = set()
        at = 0.0
        for number, scene in enumerate(scenes):
            length = lengths[number]
            media = scene.get("media") if isinstance(scene.get("media"), dict) else {}
            assert isinstance(media, dict)
            path = self.media_path(post, media)
            if path is None and media.get("asset"):
                path = await self._asset_path(str(media["asset"]))
            kind = str(media.get("type") or "card")
            clip = (
                path if kind == "clip" and path is not None and path.is_file() else None
            )
            image = path if kind == "image" and path is not None else None
            shots.append(
                Shot(
                    image,
                    at,
                    length + gap,
                    label=str(scene.get("text") or ""),
                    show=str(scene.get("show") or ""),
                    clip=clip,
                    clip_start=_seconds(media.get("start")),
                )
            )
            chapter = whole(scene.get("chapter"), -1)
            if long and chapter >= 0 and chapter not in seen_chapters:
                seen_chapters.add(chapter)
                title = (
                    titles[chapter]
                    if chapter < len(titles)
                    else f"Chapter {chapter + 1}"
                )
                chapter_starts.append((at, title))
            words += spread_words(str(scene.get("say") or ""), at, length)
            at += length + gap
        folder = self.folder(post)
        audio = folder / "voice.wav"
        await anyio.to_thread.run_sync(
            lambda: write_joined(voices, lengths, gap, audio)
        )
        background = None
        if channel.background and not long:
            background = await self._asset_path(channel.background)
        size = self._video_size()
        script = (
            post.data.get("script") if isinstance(post.data.get("script"), dict) else {}
        )
        assert isinstance(script, dict)
        first = scenes[0]
        hook = (
            ""
            if long
            else str(first.get("text") or _hook_banner(str(first.get("say") or "")))
        )
        plan = Plan(
            shots=tuple(shots),
            chunks=chunks(words),
            hook=hook,
            duration=at,
            look=channel.look,
            size=f"{size}-wide" if long else size,
            handle=channel.name,
            seed=sum(map(ord, post.id)) % 97,
            music=self._music(),
            fps=24 if long else 30,
            captions=channel.captions,
            fade=1.2 if long else 0.22,
            progress_bar=not long,
            background=background,
            dim=0.18 if long else 0.0,
            chapters=tuple(
                (start, f"Chapter {n + 1}: {title}")
                for n, (start, title) in enumerate(chapter_starts)
            ),
        )
        return plan, audio

    async def _render(
        self,
        post: FarmPost,
        work: Callable[[Callable[[float], None], Callable[[], bool]], None],
    ) -> None:
        """Run a render on a thread: work(progress, stopped)."""
        loop = asyncio.get_running_loop()
        last = [62]
        reports: list[concurrent.futures.Future[FarmPost]] = []

        def report(share: float) -> None:
            value = 62 + int(share * 36)
            if value >= last[0] + 2:
                last[0] = value
                reports.append(
                    asyncio.run_coroutine_threadsafe(
                        self._update(post, progress=value), loop
                    )
                )

        self._check(post)
        try:
            await anyio.to_thread.run_sync(
                lambda: work(report, lambda: post.id in self._stopped)
            )
        except RenderError as error:
            raise FarmError(str(error)) from error
        finally:
            # Progress saves still on their way must land before the last one.
            for sent in reports:
                with contextlib.suppress(Exception):
                    await asyncio.wrap_future(sent)
        self._check(post)

    async def _finish(
        self,
        post: FarmPost,
        channel: FarmChannel,
        data: JsonObject,
        *,
        duration: float,
        voiced: bool,
        long: bool,
        chapters: Sequence[tuple[float, str]] = (),
    ) -> FarmPost:
        folder = self.folder(post)
        taken = [
            other.scheduled_at
            for other in await self.posts(channel.id)
            if other.scheduled_at and other.id != post.id
        ]
        scenes = _scenes(data)
        credits = sorted(
            {
                str(media.get("credit"))
                for media in (scene.get("media") for scene in scenes)
                if isinstance(media, dict) and media.get("credit")
            }
        )
        raw_script = data.get("script") if isinstance(data.get("script"), dict) else {}
        assert isinstance(raw_script, dict)
        script = formats.script_from_json({**raw_script, "scenes": scenes})
        if long:
            title = script.title or post.title
            chapter_list = [
                (start, heading.split(": ", 1)[-1]) for start, heading in chapters
            ]
            tags = list(script.hashtags) or ["#sleep", "#lore"]
            caption = longform.youtube_description(
                title=title,
                show=channel.fandom or channel.niche,
                chapters=chapter_list,
                tags=tags,
            )
            made = await anyio.to_thread.run_sync(
                lambda: thumbnail(folder / "cover.jpg", title, folder / "thumb.jpg")
            )
            extra: JsonObject = {
                "chapters": [
                    {"start": round(s, 1), "title": t} for s, t in chapter_list
                ],
                "thumb": "thumb.jpg" if made else "",
                "yt_title": title,
            }
        else:
            caption = formats.full_caption(
                script, channel.call_to_action, channel.platform
            )
            extra = {"yt_title": script.title or post.title}
        if credits:
            caption += "\n\nCredits: " + "; ".join(credits[:40])
        data = {
            **data,
            **extra,
            "video": "video.mp4",
            "cover": "cover.jpg",
            "duration": round(duration, 1),
            "voiced": voiced,
            "credits": credits,
            "caption_full": caption,
        }
        return await self._update(
            post,
            status="ready",
            stage="",
            progress=100,
            data=data,
            scheduled_at=post.scheduled_at or next_slot(channel, taken),
        )

    # ------------------------------------------------------------ editing

    async def edit_scenes(self, post_id: str, scenes: list[JsonObject]) -> FarmPost:
        """The user's own edit: new lines, words on screen, order, pictures."""
        post = await self.post(post_id)
        if post.status == "making":
            raise FarmError("Wait until it is made, or stop it, before editing.")
        old = {
            json.dumps(s.get("media"), sort_keys=True): s.get("media")
            for s in _scenes(post.data)
        }
        cleaned: list[JsonObject] = []
        for scene in scenes[:2_000]:
            say = " ".join(str(scene.get("say") or "").split())[:1_500]
            if not say:
                continue
            media = scene.get("media")
            if isinstance(media, dict):
                media = {k: v for k, v in media.items() if k != "preview"}
            key = json.dumps(media, sort_keys=True)
            item: JsonObject = {
                "say": say,
                "show": _text(scene.get("show"), 120),
                "text": _text(scene.get("text"), 40),
                # Only media the farm itself chose or saved may be kept.
                "media": old.get(key) if isinstance(media, dict) else None,
            }
            if "chapter" in scene:
                item["chapter"] = whole(scene.get("chapter"), 0)
            item.update(_shot_fields(scene))
            cleaned.append(item)
        if not cleaned:
            raise FarmError("A video needs at least one scene with words.")
        data = {**post.data, "scenes": cleaned, "edited": True}
        return await self._update(post, data=data)

    async def set_scene_media(
        self, post_id: str, index: int, choice: JsonObject
    ) -> FarmPost:
        """Put a library clip or picture, or a picture from the web, in a scene."""
        post = await self.post(post_id)
        scenes = _scenes(post.data)
        if not 0 <= index < len(scenes):
            raise FarmError("There's no such scene.")
        channel = await self.channel(post.channel_id)
        picker = self.picker(post, channel)
        if choice.get("asset_id"):
            asset = await self.library.asset(str(choice["asset_id"]))
            media = picker.from_asset(asset, length=8.0)
        elif choice.get("url"):
            saved = await picker.save_url(str(choice["url"]))
            if saved is None:
                raise FarmError("That picture couldn't be downloaded.")
            media: JsonObject | None = {
                "type": "image",
                "file": saved,
                "url": str(choice["url"]),
                "source": str(choice.get("source") or "web")[:20],
                "title": _text(choice.get("title"), 120),
                "credit": _text(choice.get("credit"), 200),
            }
        elif choice.get("auto"):
            media = None
        else:
            raise FarmError("Choose a clip or picture.")
        if isinstance(media, dict):
            media["locked"] = True
        scenes[index]["media"] = media
        data = {**post.data, "scenes": scenes, "edited": True}
        return await self._update(post, data=data)

    async def ai_edit(
        self, post_id: str, instruction: str, *, chapter: int | None = None
    ) -> FarmPost:
        """Ask the AI to change the script ('make the hook scarier', 'cut the
        third scene'); scenes it keeps keep their pictures."""
        post = await self.post(post_id)
        if post.status == "making":
            raise FarmError("Wait until it is made, or stop it, before editing.")
        instruction = _text(instruction, 600)
        if not instruction:
            raise FarmError("Say what to change.")
        scenes = _scenes(post.data)
        if not scenes:
            raise FarmError("Make the video first; then the AI can edit it.")
        if chapter is None and len(scenes) > MAX_EDIT_SCENES:
            raise FarmError("This video is long: pick a chapter for the AI to edit.")
        picked = [
            n
            for n, scene in enumerate(scenes)
            if chapter is None or whole(scene.get("chapter"), -1) == chapter
        ]
        if not picked:
            raise FarmError("There's no such chapter.")
        before = [scenes[n] for n in picked]
        changed = formats.parse_edit(
            await self._think(
                formats.EDIT_SYSTEM, formats.edit_prompt(before, instruction)
            )
        )
        if not changed:
            raise FarmError(
                "The AI didn't send back an edit; try saying it another way."
            )
        kept = {
            (str(scene.get("show")), str(scene.get("say"))[:40]): scene.get("media")
            for scene in before
        }
        by_show = {str(scene.get("show")): scene.get("media") for scene in before}
        for number, scene in enumerate(changed):
            media = kept.get(
                (str(scene["show"]), str(scene["say"])[:40])
            ) or by_show.get(str(scene["show"]))
            scene["media"] = media
            # A cartoon shot keeps its place, characters, and camera.
            for key, value in _shot_fields(
                before[min(number, len(before) - 1)]
            ).items():
                scene.setdefault(key, value)
            if chapter is not None:
                scene["chapter"] = chapter
        start, end = picked[0], picked[-1] + 1
        scenes = scenes[:start] + changed + scenes[end:]
        data = {**post.data, "scenes": scenes, "edited": True}
        return await self._update(post, data=data)

    async def set_music(self, post_id: str, fields: JsonObject) -> FarmPost:
        """A music edit's song, lyrics, and the part of the song it uses."""
        post = await self.post(post_id)
        if post.status == "making":
            raise FarmError("Wait until it is made, or stop it, before editing.")
        data = dict(post.data)
        if "song" in fields:
            song = _text(fields.get("song"), 40)
            if song:
                try:
                    track = await self.library.asset(song)
                except LibraryError as error:
                    raise FarmError(str(error)) from error
                if track.kind not in {"audio", "video"}:
                    raise FarmError(
                        "The song has to be a sound file or a video with sound."
                    )
            data["song"] = song
        if "lyrics" in fields:
            data["lyrics"] = str(fields.get("lyrics") or "")[:20_000]
        if "song_start" in fields:
            raw = fields.get("song_start")
            data["song_start"] = (
                -1.0 if raw in (None, "", "auto") else max(0.0, _seconds(raw))
            )
        if "song_length" in fields:
            data["song_length"] = min(90.0, _seconds(fields.get("song_length")))
        if "big_words" in fields:
            raw = fields.get("big_words")
            items = raw if isinstance(raw, list) else str(raw or "").split(",")
            data["big_words"] = [
                _text(item, 30).upper() for item in items if _text(item, 30)
            ][:20]
        return await self._update(post, data=data)

    # ------------------------------------------------------------ the queue

    async def queue(self, channel_id: str | None = None) -> list[FarmPost]:
        """Finished videos waiting to go up, soonest first."""
        ready = await self.posts(channel_id, status="ready")
        return sorted(ready, key=lambda post: post.scheduled_at or 1 << 62)

    async def needs_more(self, channel: FarmChannel) -> bool:
        """Whether autopilot should make another video for this channel."""
        waiting = [
            post
            for post in await self.posts(channel.id)
            if post.status in {"ready", "making"}
        ]
        return len(waiting) < channel.posts_per_day

    async def overview(self) -> JsonObject:
        await self.recover()
        channels = await self.channels()
        posts = await self._store.find(FarmPost, order_by="created_at DESC")
        counts: dict[str, dict[str, int]] = {}
        for post in posts:
            row = counts.setdefault(post.channel_id, {})
            row[post.status] = row.get(post.status, 0) + 1
        ready, why = video_tools()
        assets = await self.library.assets()
        return {
            "channels": [channel_view(c, counts.get(c.id)) for c in channels],
            "posts": [self.view(post) for post in posts[:200]],
            "styles": [
                {
                    "key": s.key,
                    "label": s.label,
                    "pitch": s.pitch,
                    "example": s.example,
                    "long": s.long,
                    "fandom": s.fandom,
                    "kind": s.kind,
                }
                for s in formats.STYLES
            ],
            "platforms": formats.PLATFORMS,
            "looks": list(formats.LOOKS),
            "visuals": list(formats.VISUALS),
            "textures": list(formats.TEXTURES),
            "shapes": list(formats.SHAPES),
            "paces": list(formats.PACES),
            "characters": [c.model_dump() for c in await self.characters()],
            "character_options": animated.character_options(),
            "library": {
                "count": len(assets),
                "backgrounds": [
                    {"id": a.id, "name": a.name}
                    for a in assets
                    if a.kind == "video" and a.background
                ],
                "songs": [
                    {"id": a.id, "name": a.name, "duration": a.duration}
                    for a in assets
                    if a.kind == "audio"
                ],
                "pictures": [
                    {"id": a.id, "name": a.name} for a in assets if a.kind == "image"
                ][:300],
            },
            "tools": {
                "video": ready,
                "why": why,
                "image_maker": self._visuals().can_make,
                "pexels": bool(self._pexels_key()),
            },
            "busy": self._line.locked(),
        }

    def view(self, post: FarmPost) -> JsonObject:
        """A post for the page; long scene lists stay out of the overview."""
        view: JsonObject = post.model_dump()
        data = dict(post.data)
        scenes = _scenes(data)
        data.pop("scenes", None)
        data.pop("long", None)
        view["data"] = data
        view["scene_count"] = len(scenes)
        view["kind"] = str(data.get("kind") or "short")
        base = f"/studio/api/farm/posts/{post.id}/files/"
        if post.status in DONE and data.get("video"):
            view["video_url"] = base + str(data["video"])
            view["cover_url"] = base + str(data.get("cover") or "cover.jpg")
            if data.get("thumb"):
                view["thumb_url"] = base + str(data["thumb"])
        return view

    def editor_view(self, post: FarmPost) -> JsonObject:
        """A post with every scene and a preview address for its media."""
        view = self.view(post)
        base = f"/studio/api/farm/posts/{post.id}/files/"
        scenes = _scenes(post.data)
        for scene in scenes:
            media = scene.get("media")
            if isinstance(media, dict):
                if media.get("file") and media.get("type") == "image":
                    media["preview"] = base + str(media["file"])
                elif media.get("asset"):
                    media["preview"] = f"/studio/api/farm/media/{media['asset']}/thumb"
        view["scenes"] = scenes
        view["chapters"] = [
            str(chapter.get("title")) for chapter in _chapter_list(post.data)
        ]
        return view


def _shot_fields(scene: JsonObject) -> JsonObject:
    """A cartoon shot's place, characters, and camera, or a music edit's
    cut, cleaned: what the editor may change beyond the words."""
    out: JsonObject = {}
    for key in ("place", "camera", "focus", "speaker", "voice"):
        if key in scene:
            out[key] = _text(scene.get(key), 40)
    raw = scene.get("cast")
    if isinstance(raw, list):
        out["cast"] = [
            {
                "name": _text(actor.get("name"), 40),
                "action": _text(actor.get("action"), 20) or "stand",
                "at": _text(actor.get("at"), 20),
                "feel": _text(actor.get("feel"), 20),
            }
            for actor in raw[:4]
            if isinstance(actor, dict) and _text(actor.get("name"), 40)
        ]
    cut = scene.get("cut")
    if isinstance(cut, dict):
        out["cut"] = {
            "start": _seconds(cut.get("start")),
            "end": _seconds(cut.get("end")),
            "punch": bool(cut.get("punch")),
            "flash": bool(cut.get("flash")),
            "shake": bool(cut.get("shake")),
        }
    return out


def _chapter_list(data: JsonObject) -> list[JsonObject]:
    state = data.get("long")
    chapters = state.get("chapters") if isinstance(state, dict) else None
    return (
        [c for c in chapters if isinstance(c, dict)]
        if isinstance(chapters, list)
        else []
    )


def _chapter_titles(data: JsonObject) -> list[str]:
    return [str(chapter.get("title") or "") for chapter in _chapter_list(data)]


def _hook_banner(hook: str) -> str:
    """Up to six words of the hook for the big banner at the start."""
    words = hook.split()
    short = " ".join(words[:6])
    return short if len(words) <= 6 else short.rstrip(",.;:") + "…"


def next_slot(
    channel: FarmChannel, taken: Sequence[int], now: datetime | None = None
) -> int:
    """The channel's next free posting time, in ms."""
    current = now or datetime.now().astimezone()
    busy = set(taken)
    for day in range(0, 60):
        date = (current + timedelta(days=day)).date()
        for time in clean_times(list(channel.post_times)):
            hour, minute = (int(part) for part in time.split(":"))
            slot = datetime(
                date.year, date.month, date.day, hour, minute, tzinfo=current.tzinfo
            )
            stamp = int(slot.timestamp() * 1000)
            if slot > current + timedelta(minutes=5) and stamp not in busy:
                return stamp
    return int((current + timedelta(days=1)).timestamp() * 1000)
