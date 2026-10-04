"""The Content Farm: channels, an idea board, and a line that makes videos.

A channel is one account: a niche, a style, a voice, and when it posts. The
farm fills the idea board, writes each script with the team's local model,
reads it with the built-in voice, finds a picture for every scene, and
renders a vertical MP4 with captions. Finished videos wait in the posting
queue with their caption and hashtags, at the channel's next posting time.
Posting itself stays with the user: the platforms only allow it from their
own apps or business APIs.
"""

import asyncio
import concurrent.futures
import contextlib
import re
import shutil
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import anyio
from loguru import logger

from free_claude_code.core.json_types import JsonObject

from ..models import FarmChannel, FarmPost, now_ms
from ..store import StudioStore
from . import formats
from .formats import Script
from .render import Plan, RenderError, Shot, render, video_tools
from .timing import (
    GAP,
    chunks,
    join_wavs,
    reading_time,
    silent_wav,
    spread_words,
    wav_length,
)
from .visuals import Picture, Visuals

Think = Callable[[str, str], Awaitable[str]]
"""Ask the farm's writer (the team's local model): (system, prompt) → text."""
Speak = Callable[[str, str], Awaitable[bytes | None]]
"""Read a line aloud: (text, voice) → WAV bytes, or None with no voice."""
Research = Callable[[str], Awaitable[str]]
"""Search the web: query → a few lines of results, or '' when offline."""

MAX_CHANNELS = 30
MAX_POSTS = 600
MAX_IDEAS = 10
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_RESEARCHED = {"facts", "explainer", "news", "tips"}
ACTIVE = ("making",)
DONE = ("ready", "posted")


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


def channel_view(
    channel: FarmChannel, counts: dict[str, int] | None = None
) -> JsonObject:
    view: JsonObject = channel.model_dump()
    view["post_times"] = list(channel.post_times)
    view["hashtags"] = list(channel.hashtags)
    view["style_label"] = formats.style_of(channel.style).label
    view["platform_label"] = formats.PLATFORMS.get(channel.platform, channel.platform)
    view["counts"] = dict(counts or {})
    return view


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
        video_size: Callable[[], str] = lambda: "720p",
        music: Callable[[], Path | None] = lambda: None,
    ) -> None:
        self._store = store
        self._root = root
        self._think = think
        self._speak = speak
        self._research = research
        self._visuals = visuals
        self._video_size = video_size
        self._music = music
        self._line = asyncio.Lock()
        """One video at a time: rendering uses every core."""
        self._stopped: set[str] = set()
        self._recovered = False

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
                if wanted in channel.name.lower() or wanted in channel.niche.lower():
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
        if not name:
            name = re.sub(r"[^a-z0-9]+", "", niche.lower())[:24] or "mychannel"
        tags = merged.get("hashtags")
        values: JsonObject = {
            "name": name,
            "niche": niche,
            "platform": _choice(
                merged.get("platform"), tuple(formats.PLATFORMS), "instagram"
            ),
            "style": _choice(merged.get("style"), tuple(formats.STYLE_BY_KEY), "facts"),
            "look": _choice(merged.get("look"), formats.LOOKS, "bold"),
            "visuals": _choice(merged.get("visuals"), formats.VISUALS, "photos"),
            "voice": _text(merged.get("voice"), 40) or "am_michael",
            "seconds": formats.clamp_seconds(whole(merged.get("seconds"), 30)),
            "posts_per_day": max(1, min(10, whole(merged.get("posts_per_day"), 1))),
            "post_times": list(clean_times(merged.get("post_times"))),
            "hashtags": list(
                formats.clean_hashtags(tags if isinstance(tags, list | str) else [])
            ),
            "call_to_action": _text(merged.get("call_to_action"), 160),
            "notes": _text(merged.get("notes"), 1_000),
            "autopilot": bool(merged.get("autopilot")),
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
        path = (self.folder(post) / name).resolve()
        if path.parent != self.folder(post).resolve():
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
            data["caption_full"] = str(fields.get("caption") or "")[:2_200]
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
        """Videos left half made when the app closed are marked failed."""
        if self._recovered:
            return
        self._recovered = True
        if self._line.locked():
            return
        for post in await self.posts(status="making"):
            await self._update(
                post,
                status="failed",
                error="The app closed while this was being made. Press Make again.",
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
        if channel.style in _RESEARCHED or channel.style == "news":
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
        on_change: Callable[[FarmPost], Awaitable[None]] | None = None,
    ) -> FarmPost:
        """Write, voice, picture, and render one video. Slow: run it in the
        background; the post's stage and progress show how far it is."""
        post = await self.post(post_id)
        if post.status == "making":
            raise FarmError("That video is already being made.")
        channel = await self.channel(post.channel_id)
        post = await self._update(
            post,
            status="making",
            stage="Waiting for the video before it",
            progress=0,
            error="",
        )
        self._stopped.discard(post.id)
        async with self._line:
            try:
                post = await self._make(post, channel)
            except FarmError as error:
                if post.id in self._stopped:
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
            raise FarmError("Stopped.")

    async def _stage(self, post: FarmPost, stage: str, progress: int) -> FarmPost:
        self._check(post)
        return await self._update(post, stage=stage, progress=progress)

    async def _make(self, post: FarmPost, channel: FarmChannel) -> FarmPost:
        ready, why = video_tools()
        if not ready:
            raise FarmError(f"Videos can't be made on this PC yet: {why}")
        post = await self._stage(post, "Writing the script", 5)
        script = await self.write(channel, post.title)
        data: JsonObject = {**post.data, "script": script.to_json()}
        post = await self._update(post, data=data)
        post = await self._stage(post, "Recording the voiceover", 25)
        clips = await self._voice(channel, script, post)
        post = await self._stage(post, "Finding pictures", 45)
        pictures = await self._pictures(channel, script, post)
        post = await self._stage(post, "Rendering the video", 60)
        folder = self.folder(post)
        await anyio.to_thread.run_sync(
            lambda: folder.mkdir(parents=True, exist_ok=True)
        )
        shots: list[Shot] = []
        words: tuple = ()
        at = 0.0
        audio: list[bytes] = []
        for number, scene in enumerate(script.scenes):
            clip = clips[number]
            length = wav_length(clip) if clip else reading_time(scene.say)
            picture = pictures[number]
            image = None
            if picture is not None:
                image = folder / f"scene{number + 1}{picture.ext}"
                await anyio.Path(image).write_bytes(picture.data)
            shots.append(
                Shot(image, at, length + GAP, label=scene.text, show=scene.show)
            )
            words += spread_words(scene.say, at, length)
            audio.append(clip or silent_wav(length))
            at += length + GAP
        voice = folder / "voice.wav"
        try:
            joined = join_wavs(audio, [GAP] * len(audio))
        except ValueError:
            joined = silent_wav(at)
        await anyio.Path(voice).write_bytes(joined)
        plan = Plan(
            shots=tuple(shots),
            chunks=chunks(words),
            hook=script.scenes[0].text or _hook_banner(script),
            duration=at,
            look=channel.look,
            size=self._video_size(),
            handle=channel.name,
            seed=sum(map(ord, post.id)) % 97,
            music=self._music(),
        )
        loop = asyncio.get_running_loop()
        last = [60]
        reports: list[concurrent.futures.Future[FarmPost]] = []

        def report(share: float) -> None:
            value = 60 + int(share * 38)
            if value >= last[0] + 4:
                last[0] = value
                reports.append(
                    asyncio.run_coroutine_threadsafe(
                        self._update(post, progress=value), loop
                    )
                )

        self._check(post)
        try:
            await anyio.to_thread.run_sync(
                lambda: render(
                    plan,
                    audio=voice,
                    out=folder / "video.mp4",
                    cover=folder / "cover.jpg",
                    progress=report,
                )
            )
        except RenderError as error:
            raise FarmError(str(error)) from error
        finally:
            # Progress saves still on their way must land before the last one.
            for sent in reports:
                with contextlib.suppress(Exception):
                    await asyncio.wrap_future(sent)
        self._check(post)
        taken = [
            other.scheduled_at
            for other in await self.posts(channel.id)
            if other.scheduled_at and other.id != post.id
        ]
        credits = sorted({p.credit for p in pictures if p is not None and p.credit})
        data = {
            **data,
            "video": "video.mp4",
            "cover": "cover.jpg",
            "duration": round(at, 1),
            "voiced": any(clips),
            "credits": credits,
            "caption_full": formats.full_caption(script, channel.call_to_action)
            + (f"\n\n{'; '.join(credits)}" if credits else ""),
        }
        return await self._update(
            post,
            status="ready",
            stage="",
            progress=100,
            data=data,
            scheduled_at=next_slot(channel, taken),
        )

    async def write(self, channel: FarmChannel, idea: str) -> Script:
        facts = ""
        if channel.style in _RESEARCHED:
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
        )
        reply = await self._think(formats.WRITER_SYSTEM, prompt)
        script = formats.parse_script(
            reply, idea=idea, seconds=channel.seconds, channel_tags=channel.hashtags
        )
        if not script.scenes:
            raise FarmError("The writer's script was empty; try again.")
        return script

    async def _voice(
        self, channel: FarmChannel, script: Script, post: FarmPost
    ) -> list[bytes | None]:
        if channel.voice == "none":
            return [None] * len(script.scenes)
        clips: list[bytes | None] = []
        for scene in script.scenes:
            self._check(post)
            clips.append(await self._speak(scene.say, channel.voice))
            if clips[-1] is None:
                # No voice on this PC: the whole video goes captions-only.
                return [None] * len(script.scenes)
        return clips

    async def _pictures(
        self, channel: FarmChannel, script: Script, post: FarmPost
    ) -> list[Picture | None]:
        if channel.visuals == "text":
            return [None] * len(script.scenes)
        visuals = self._visuals()
        used: set[str] = set()
        found: list[Picture | None] = []
        for number, scene in enumerate(script.scenes):
            self._check(post)
            found.append(
                await visuals.picture(
                    scene.show, mode=channel.visuals, used=used, style=channel.niche
                )
            )
            await self._update(
                post, progress=45 + int(15 * (number + 1) / len(script.scenes))
            )
        return found

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
        return {
            "channels": [channel_view(c, counts.get(c.id)) for c in channels],
            "posts": [self.view(post) for post in posts[:200]],
            "styles": [
                {"key": s.key, "label": s.label, "pitch": s.pitch, "example": s.example}
                for s in formats.STYLES
            ],
            "platforms": formats.PLATFORMS,
            "looks": list(formats.LOOKS),
            "tools": {
                "video": ready,
                "why": why,
                "image_maker": self._visuals().can_make,
            },
            "busy": self._line.locked(),
        }

    def view(self, post: FarmPost) -> JsonObject:
        view: JsonObject = post.model_dump()
        base = f"/studio/api/farm/posts/{post.id}/files/"
        data = post.data
        if post.status in DONE and data.get("video"):
            view["video_url"] = base + str(data["video"])
            view["cover_url"] = base + str(data.get("cover") or "cover.jpg")
        return view


def _hook_banner(script: Script) -> str:
    """Up to six words of the hook for the big banner at the start."""
    words = script.hook.split()
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
