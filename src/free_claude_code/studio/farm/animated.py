"""Animated cartoons and beat-for-beat music edits, made on the farm's line.

A cartoon is written as a screenplay (who is in each shot, what they do,
where, and how the camera films it), voiced line by line (the narrator, or a
character in their own voice), and animated. A music edit listens to a song
for its beat, finds the words being sung (pasted lyrics, timed lyrics, or
the built-in Whisper), cuts clips from the library on the beat, and spells
the big words out across the screen.
"""

import json
import random
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol

import anyio

from free_claude_code.core.json_types import JsonObject

from ..models import FarmChannel, FarmCharacter, FarmPost
from . import beats as beat
from .beats import BeatError, Sung
from .cartoon.film import CartoonFrames, Film, Scene
from .cartoon.heads import AGES, HAIR, WEAR, Look, colour
from .cartoon.puppet import FEEL_OF, Placed
from .cartoon.scene import CartoonShot, spot, spread
from .cartoon.screenplay import SCREENPLAY_SYSTEM, parse_screenplay, screenplay_prompt
from .edit import EditCut, EditFrames, EditPlan, group_phrases, is_lrc, lrc_phrases
from .fandom import Fandom
from .library import MediaLibrary, scene_words, word_score
from .render import SIZES, encode, find_ffmpeg
from .timing import GAP, spread_words, write_joined

Hear = Callable[[bytes], Awaitable[list[tuple[str, float, float]]]]
"""Words heard in a WAV and when: (word, start, end) in seconds."""

MAX_CAST = 12


class AnimatedError(ValueError):
    """A cartoon or edit can't be made, said plainly."""


class Line(Protocol):
    """What cartoons and music edits use of the farm's production line."""

    library: MediaLibrary
    fandom: Fandom
    _think: Callable[[str, str], Awaitable[str]]
    _video_size: Callable[[], str]
    _music: Callable[[], Path | None]

    def folder(self, post: FarmPost) -> Path: ...

    def media_path(self, post: FarmPost, media: JsonObject) -> Path | None: ...

    async def characters(self) -> list[FarmCharacter]: ...

    async def _asset_path(self, asset_id: str) -> Path | None: ...

    async def _stage(self, post: FarmPost, stage: str, progress: int) -> FarmPost: ...

    async def _update(self, post: FarmPost, **fields: object) -> FarmPost: ...

    async def _render(
        self,
        post: FarmPost,
        work: Callable[[Callable[[float], None], Callable[[], bool]], None],
    ) -> None: ...

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
    ) -> FarmPost: ...


EDIT_SECONDS = (8, 90)
BIG_SYSTEM = (
    "You edit music videos. From song lyrics, pick the few words that should "
    "be spelled out huge across the screen: the hook, names, and the words "
    "the singer hits hardest. Reply with JSON only."
)


def kind_of(channel: FarmChannel) -> str:
    from .formats import style_of

    return style_of(channel.style).kind


def frame_size(channel: FarmChannel, base: str) -> tuple[int, int]:
    """The video's size: the app's video size, tall or wide as the channel says."""
    size = base.removesuffix("-wide")
    return (
        SIZES[f"{size}-wide"]
        if channel.shape == "wide"
        else SIZES.get(size, SIZES["720p"])
    )


# ------------------------------------------------------------ characters


def clean_character(fields: JsonObject, old: FarmCharacter | None = None) -> JsonObject:
    base: JsonObject = old.model_dump() if old else {}
    merged = {**base, **{k: v for k, v in fields.items() if v is not None}}

    def text(key: str, limit: int) -> str:
        return " ".join(str(merged.get(key) or "").split())[:limit]

    def pick(key: str, allowed: tuple[str, ...], default: str) -> str:
        value = text(key, 20).lower()
        return value if value in allowed else default

    def hex_colour(key: str) -> str:
        value = text(key, 9)
        return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else ""

    name = text("name", 40)
    if not name:
        raise AnimatedError("Give the character a name.")
    return {
        "name": name,
        "description": text("description", 400),
        "skin": hex_colour("skin"),
        "hair": pick("hair", HAIR, ""),
        "hair_colour": hex_colour("hair_colour"),
        "wear": pick("wear", WEAR, ""),
        "wear_colour": hex_colour("wear_colour"),
        "age": pick("age", AGES, "adult"),
        "beard": bool(merged.get("beard")),
        "earrings": bool(merged.get("earrings")),
        "glasses": bool(merged.get("glasses")),
        "head_asset": text("head_asset", 40),
        "voice": text("voice", 40),
    }


def character_options() -> JsonObject:
    """The choices a character's look can take, for the page."""
    from .cartoon.heads import HAIR_COLOURS, SKINS, WEAR_COLOURS
    from .cartoon.puppet import ACTIONS
    from .cartoon.stages import PLACES

    return {
        "hair": list(HAIR),
        "wear": list(WEAR),
        "ages": list(AGES),
        "skins": list(SKINS),
        "hair_colours": list(HAIR_COLOURS),
        "wear_colours": list(WEAR_COLOURS),
        "places": list(PLACES),
        "actions": list(ACTIONS),
        "cameras": ["wide", "medium", "close", "push", "pan"],
    }


def look_of(character: FarmCharacter, head: Path | None = None) -> Look:
    return Look(
        name=character.name,
        skin=character.skin,
        hair=character.hair,
        hair_colour=character.hair_colour,
        wear=character.wear,
        wear_colour=character.wear_colour,
        age=character.age,
        beard=character.beard,
        earrings=character.earrings,
        glasses=character.glasses,
        head_image=head,
    )


def draw_character(look: Look, out: Path, *, size: int = 320) -> None:
    """A character standing on a plain stage, for the cast list (runs on a
    thread)."""
    from PIL import Image

    from .cartoon.puppet import draw_figure

    canvas = Image.new("RGB", (size, size), (238, 232, 220))
    draw_figure(
        canvas,
        Placed(look=look, action="wave", x=0.5, facing=1, feeling="happy"),
        t=0.4,
        length=2.0,
        ground=size * 0.94,
        height=size * 0.82,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG")


async def cast_of(farm: Line, channel: FarmChannel) -> list[FarmCharacter]:
    found = {c.id: c for c in await farm.characters()}
    return [found[i] for i in channel.cast if i in found][:MAX_CAST]


async def _looks(farm: Line, cast: list[FarmCharacter]) -> dict[str, tuple[Look, str]]:
    """Each cast member's look and voice, by lower-case name."""
    out: dict[str, tuple[Look, str]] = {}
    for character in cast:
        head = (
            await farm._asset_path(character.head_asset)
            if character.head_asset
            else None
        )
        out[character.name.lower()] = (look_of(character, head), character.voice)
    return out


# ------------------------------------------------------------ cartoons


async def write_cartoon(
    farm: Line, post: FarmPost, channel: FarmChannel, data: JsonObject
) -> JsonObject:
    """The story as a screenplay: one line and one shot at a time."""
    await farm._stage(post, "Writing the story", 5)
    cast = await cast_of(farm, channel)
    facts = ""
    if channel.fandom:
        facts = await farm.fandom.lore(
            channel.fandom, post.title, link=channel.wiki, chars=2_500
        )
    prompt = screenplay_prompt(
        idea=post.title,
        cast=[{"name": c.name, "description": c.description} for c in cast],
        seconds=channel.seconds,
        notes=channel.notes,
        facts=facts,
        series=channel.series,
    )
    play = parse_screenplay(
        await farm._think(SCREENPLAY_SYSTEM, prompt),
        idea=post.title,
        cast_names=[c.name for c in cast],
    )
    shots = play["shots"]
    if not isinstance(shots, list) or not shots:
        raise AnimatedError("The writer's story was empty; try again.")
    voices = {c.name.lower(): c.voice for c in cast if c.voice}
    for shot in shots:
        if isinstance(shot, dict):
            speaker = str(shot.get("speaker") or "").lower()
            if speaker in voices:
                shot["voice"] = voices[speaker]
    from .formats import clean_hashtags

    tags = play.get("hashtags")
    return {
        **data,
        "kind": "cartoon",
        "series": channel.series or str(play.get("series") or ""),
        "script": {
            "title": play["title"],
            "hook": "",
            "caption": play["caption"],
            "hashtags": list(
                clean_hashtags(tags if isinstance(tags, list) else [], channel.hashtags)
            ),
        },
        "scenes": shots,
    }


def _actors(
    scene: JsonObject, looks: dict[str, tuple[Look, str]]
) -> tuple[Placed, ...]:
    raw = scene.get("cast")
    cast = (
        [a for a in raw if isinstance(a, dict) and a.get("name")]
        if isinstance(raw, list)
        else []
    )
    cast = cast[:4]
    spots = spread(len(cast))
    speaker = str(scene.get("speaker") or "").lower()
    placed: list[Placed] = []
    for number, actor in enumerate(cast):
        name = str(actor.get("name"))
        look = looks.get(name.lower(), (Look(name=name), ""))[0]
        x = spot(actor.get("at"), spots[number])
        action = str(actor.get("action") or "stand")
        speaking = name.lower() == speaker
        if speaking and action == "stand":
            action = "talk"
        feel = str(actor.get("feel") or "")
        placed.append(
            Placed(
                look=look,
                action=action,
                x=x,
                # Everyone faces the middle of the scene.
                facing=1 if x < 0.5 else -1,
                feeling=feel if feel and feel != "neutral" else FEEL_OF.get(action, ""),
                speaking=speaking,
            )
        )
    return tuple(placed)


async def finish_cartoon(
    farm: Line,
    post: FarmPost,
    channel: FarmChannel,
    data: JsonObject,
    scenes: list[JsonObject],
    voices: list[Path | None],
    lengths: list[float],
) -> FarmPost:
    """Animate the voiced screenplay and render it."""
    looks = await _looks(farm, await cast_of(farm, channel))
    size = frame_size(channel, farm._video_size())
    timed: list[Scene] = []
    words: tuple = ()
    at = 0.0
    for number, scene in enumerate(scenes):
        length = lengths[number] + GAP
        camera = str(scene.get("camera") or "wide")
        shot = CartoonShot(
            place=str(scene.get("place") or "hut"),
            actors=_actors(scene, looks),
            camera=camera,
            focus=str(scene.get("focus") or scene.get("speaker") or ""),
            seed=number % 3,
        )
        timed.append(Scene(shot, at, length))
        words += spread_words(str(scene.get("say") or ""), at, lengths[number])
        at += length
    title = str(data.get("series") or channel.series or "")
    film = Film(
        scenes=tuple(timed),
        words=words,
        duration=at,
        size=size,
        title=title,
        texture=channel.texture,
        captions=channel.captions,
    )
    folder = farm.folder(post)
    audio = folder / "voice.wav"
    await anyio.to_thread.run_sync(lambda: write_joined(voices, lengths, GAP, audio))
    music = await farm._asset_path(channel.song) if channel.song else farm._music()

    def work(report: Callable[[float], None], stopped: Callable[[], bool]) -> None:
        CartoonFrames(film).draw(min(1.2, at / 3)).save(
            folder / "cover.jpg", "JPEG", quality=88
        )
        frames = CartoonFrames(film)
        encode(
            frames.draw,
            size=size,
            fps=film.fps,
            duration=at,
            audio=audio,
            out=folder / "video.mp4",
            music=music,
            music_volume=0.12,
            progress=report,
            stopped=stopped,
            close=frames.close,
        )

    post = await farm._stage(post, "Animating the cartoon", 62)
    await farm._render(post, work)
    return await farm._finish(
        post, channel, data, duration=at, voiced=any(voices), long=False
    )


# ------------------------------------------------------------ music edits


def _number(value: object, default: float) -> float:
    try:
        return float(str(value))
    except ValueError:
        return default


async def song_of(farm: Line, post: FarmPost, channel: FarmChannel) -> Path:
    asset_id = str(post.data.get("song") or channel.song or "")
    if not asset_id:
        raise AnimatedError(
            "Add the song first: upload it to the Library (MP3, WAV, M4A, or a "
            "video with the song), then pick it in the channel or in this video's editor."
        )
    asset = await farm.library.asset(asset_id)
    if asset.kind not in {"audio", "video"}:
        raise AnimatedError("The song has to be a sound file or a video with sound.")
    path = farm.library.path(asset)
    if not path.is_file():
        raise AnimatedError("The song's file isn't on this PC any more.")
    return path


async def _big_words(
    farm: Line, channel: FarmChannel, words: list[Sung], chosen: object
) -> list[Sung]:
    picked = [str(w) for w in chosen] if isinstance(chosen, list) else []
    if not picked and words and channel.ai_polish:
        lyrics = " ".join(w.text for w in words)[:2_000]
        try:
            reply = await farm._think(
                BIG_SYSTEM,
                f"Lyrics:\n{lyrics}\n\nPick 3 to 8 single words (or short tokens like "
                '1-800). JSON: {"big": ["WORD", ...]}',
            )
            found = re.search(r"\{.*\}", reply, re.S)
            data = json.loads(found.group(0)) if found else {}
            raw = data.get("big") if isinstance(data, dict) else None
            picked = [str(w) for w in raw][:8] if isinstance(raw, list) else []
        except ValueError:
            picked = []
    return beat.pick_big(words, picked or None)


async def _clips(
    farm: Line,
    post: FarmPost,
    channel: FarmChannel,
    cuts: list[beat.Cut],
    words: list[Sung],
    old: list[JsonObject],
) -> list[JsonObject]:
    """A clip (or picture) for every cut: what the user chose stays, the
    rest come from the library, matched to the words sung over the cut."""
    assets = [
        a
        for a in await farm.library.assets(show=channel.fandom)
        if a.kind in {"video", "image"} and a.id != channel.song
    ]
    if not assets:
        raise AnimatedError(
            "Add clips to the Library first (upload them, or link a folder of "
            f"{channel.fandom or 'your'} clips): a music edit cuts between them."
        )
    rng = random.Random(post.id)
    order = assets[:]
    rng.shuffle(order)
    used: set[str] = set()
    scenes: list[JsonObject] = []
    for number, cut in enumerate(cuts):
        sung = [w.text for w in words if cut.start <= w.start < cut.end]
        say = " ".join(sung) or "♪"
        media = None
        if number < len(old):
            previous = old[number].get("media")
            if isinstance(previous, dict) and previous.get("locked"):
                media = previous
        if media is None:
            terms = scene_words(say) if sung else ()
            fits = (
                await farm.library.best(
                    terms,
                    show=channel.fandom,
                    kinds=("video", "image"),
                    used=used,
                    limit=3,
                )
                if terms
                else []
            )
            # (Never the last bit of a clip: downloaded ones end on a logo.)
            # Only a clip named or tagged with a sung word; else the next
            # unused one, in a shuffled order.
            fits = [
                a
                for a in fits
                if a.id not in used
                and a.id != channel.song
                and word_score(a, terms) > 0
            ]
            if fits:
                asset = fits[0]
            else:
                asset = next((a for a in order if a.id not in used), order[0])
            used.add(asset.id)
            if len(used) >= len(assets):
                used.clear()
            length = cut.end - cut.start
            start = (
                rng.uniform(0, max(0.0, asset.duration * 0.88 - length))
                if asset.kind == "video"
                else 0.0
            )
            media = {
                "type": "clip" if asset.kind == "video" else "image",
                "asset": asset.id,
                "start": round(start, 2),
                "source": "library",
                "title": asset.name,
            }
        scenes.append(
            {
                "say": say,
                "show": str(media.get("title") or "")[:120],
                "text": "",
                "media": media,
                "cut": {
                    "start": cut.start,
                    "end": cut.end,
                    "punch": cut.punch,
                    "flash": cut.flash,
                    "shake": cut.shake,
                },
            }
        )
    return scenes


async def _lyrics(
    farm: Line,
    song: Path,
    text: str,
    found: beat.Beats,
    start: float,
    end: float,
    hear: Hear | None,
) -> tuple[list[tuple[Sung, ...]], str]:
    """The lyrics' words and timings, and where the timings came from."""
    if text and is_lrc(text):
        return lrc_phrases(text, start=start, end=end), "timed lyrics"
    plain = "\n".join(line for line in text.splitlines() if line.strip())
    if hear is not None:
        try:
            samples = await anyio.to_thread.run_sync(
                lambda: beat.decode(song, start=start, length=end - start, rate=16_000)
            )
            heard = await hear(_wav(samples, 16_000))
        except BeatError, OSError, RuntimeError, ValueError:
            heard = []
        if heard:
            words = [Sung(w, round(s, 3), round(e, 3)) for w, s, e in heard]
            if plain:
                words = beat.align(words, plain)
            return group_phrases(words, plain), "heard by Whisper"
    if plain:
        words = beat.spread_lyrics(plain, found, start=start, end=end)
        return group_phrases(words, plain), "spread over the beat"
    return [], "no lyrics"


def _wav(samples: bytes, rate: int) -> bytes:
    import io
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(samples)
    return out.getvalue()


async def make_edit(
    farm: Line, post: FarmPost, channel: FarmChannel, hear: Hear | None
) -> FarmPost:
    """Listen to the song, cut the clips on its beat, and render."""
    song = await song_of(farm, post, channel)
    post = await farm._stage(post, "Listening to the song", 8)
    try:
        found = await anyio.to_thread.run_sync(lambda: beat.analyse(song))
    except BeatError as error:
        raise AnimatedError(str(error)) from error
    if len(found.beats) < 8:
        raise AnimatedError("No steady beat was found in that song.")
    data = dict(post.data)
    seconds = _number(data.get("song_length"), 0.0) or float(channel.seconds)
    seconds = max(EDIT_SECONDS[0], min(EDIT_SECONDS[1], seconds, found.duration))
    chosen = _number(data.get("song_start"), -1.0)
    if chosen < 0:
        start, end = beat.best_window(found, seconds)
    else:
        start = min(chosen, max(0.0, found.duration - seconds))
        end = start + seconds
    post = await farm._stage(post, "Reading the lyrics", 18)
    phrases, source = await _lyrics(
        farm, song, str(data.get("lyrics") or ""), found, start, end, hear
    )
    words = [w for phrase in phrases for w in phrase]
    big = await _big_words(farm, channel, words, data.get("big_words"))
    cuts = beat.plan_cuts(found, start=start, end=end, pace=channel.pace)
    post = await farm._stage(post, "Choosing clips for every beat", 30)
    raw = data.get("scenes")
    old = [dict(s) for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []
    scenes = await _clips(farm, post, channel, cuts, words, old)
    data.update(
        {
            "kind": "edit",
            "scenes": scenes,
            "tempo": round(found.tempo, 1),
            "song_window": [round(start, 2), round(end, 2)],
            "lyrics_from": source,
            "big_words_used": [w.text for w in big],
            "script": {
                "title": post.title,
                "hook": "",
                "caption": post.title,
                "hashtags": list(channel.hashtags) or ["#edit", "#fyp"],
            },
        }
    )
    data.pop("edited", None)
    post = await farm._update(post, data=data)
    edit_cuts: list[EditCut] = []
    for scene, cut in zip(scenes, cuts, strict=True):
        media = scene.get("media") if isinstance(scene.get("media"), dict) else {}
        assert isinstance(media, dict)
        path = (
            await farm._asset_path(str(media.get("asset")))
            if media.get("asset")
            else farm.media_path(post, media)
        )
        is_clip = media.get("type") == "clip"
        edit_cuts.append(
            EditCut(
                start=cut.start,
                end=cut.end,
                clip=path if is_clip else None,
                image=None if is_clip else path,
                clip_start=_number(media.get("start"), 0.0),
                punch=cut.punch,
                flash=cut.flash,
                shake=cut.shake,
            )
        )
    size = frame_size(channel, farm._video_size())
    plan = EditPlan(
        cuts=tuple(edit_cuts),
        phrases=tuple(phrases),
        big=tuple(big),
        duration=end - start,
        size=size,
        theme=colour(channel.theme, (255, 95, 200)),
        lyrics=channel.captions,
    )
    folder = farm.folder(post)
    await anyio.to_thread.run_sync(lambda: folder.mkdir(parents=True, exist_ok=True))
    audio = folder / "song.wav"
    try:
        await anyio.to_thread.run_sync(
            lambda: beat.cut_song(song, audio, start=start, length=end - start)
        )
    except BeatError as error:
        raise AnimatedError(str(error)) from error
    cover_at = big[0].start + 0.5 if big else min(1.0, plan.duration / 3)

    def work(report: Callable[[float], None], stopped: Callable[[], bool]) -> None:
        ffmpeg = find_ffmpeg()
        cover = EditFrames(plan, ffmpeg)
        try:
            cover.draw(cover_at).save(folder / "cover.jpg", "JPEG", quality=88)
        finally:
            cover.close()
        frames = EditFrames(plan, ffmpeg)
        encode(
            frames.draw,
            size=size,
            fps=plan.fps,
            duration=plan.duration,
            audio=audio,
            out=folder / "video.mp4",
            progress=report,
            stopped=stopped,
            close=frames.close,
        )

    post = await farm._stage(post, "Cutting the edit", 62)
    await farm._render(post, work)
    return await farm._finish(
        post, channel, data, duration=plan.duration, voiced=True, long=False
    )


__all__ = [
    "AnimatedError",
    "Hear",
    "cast_of",
    "character_options",
    "clean_character",
    "finish_cartoon",
    "kind_of",
    "look_of",
    "make_edit",
    "song_of",
    "write_cartoon",
]
