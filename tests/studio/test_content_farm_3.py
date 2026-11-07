"""Content Farm 3: animated cartoon stories with your own characters, and
music edits cut beat for beat to a song you give it."""

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from free_claude_code.studio.farm import beats, edit
from free_claude_code.studio.farm.beats import Sung
from free_claude_code.studio.farm.cartoon.screenplay import (
    SCREENPLAY_SYSTEM,
    action_of,
    camera_of,
    parse_screenplay,
)
from free_claude_code.studio.farm.requests import farm_job
from free_claude_code.studio.llm import LLMReply
from tests.api.support import create_test_app
from tests.studio.test_content_farm_2 import clip


def video_ready():
    pytest.importorskip("PIL")
    pytest.importorskip("imageio_ffmpeg")
    pytest.importorskip("numpy")


def song(path: Path, seconds: float = 16.0, bpm: float = 120.0) -> Path:
    """A test song: a kick drum on every beat, louder on every bar's first."""
    from free_claude_code.studio.farm.render import find_ffmpeg

    ffmpeg = find_ffmpeg()
    assert ffmpeg
    beat = 60 / bpm
    kick = (
        f"(0.5+0.4*eq(mod(floor(t/{beat}),4),0))*sin(2*PI*55*t)*exp(-25*mod(t,{beat}))"
        f"+0.05*sin(2*PI*440*t)"
    )
    subprocess.run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='{kick}':s=22050:d={seconds}",
            str(path),
        ],
        check=True,
    )
    return path


# ------------------------------------------------------------ the beat


def test_the_beat_of_a_song_is_found(tmp_path):
    video_ready()
    found = beats.analyse(song(tmp_path / "kick.wav"))
    assert found.tempo == pytest.approx(120, abs=4)
    gaps = [b - a for a, b in zip(found.beats, found.beats[1:], strict=False)]
    assert sum(gaps) / len(gaps) == pytest.approx(0.5, abs=0.03)
    assert found.downbeats and set(found.downbeats) <= set(found.beats)
    cuts = beats.plan_cuts(found, start=2.0, end=10.0, pace="fast")
    assert cuts[0].start == 0 and cuts[-1].end == pytest.approx(8.0, abs=0.01)
    assert all(cut.end - cut.start >= beats.MIN_CUT for cut in cuts)
    assert any(cut.punch for cut in cuts)
    slow = beats.plan_cuts(found, start=2.0, end=10.0, pace="slow")
    assert len(slow) < len(cuts)
    start, end = beats.best_window(found, 6)
    assert end - start == pytest.approx(6)


def test_lyrics_are_timed_from_lrc_or_lines():
    lrc = "[00:01.00] You can't spell my name\n[00:03.50] without the money\n[00:20.00] later"
    assert edit.is_lrc(lrc) and not edit.is_lrc("just words")
    phrases = edit.lrc_phrases(lrc, start=0.5, end=10.0)
    assert [w.text for w in phrases[0]] == ["You", "can't", "spell", "my", "name"]
    assert phrases[0][0].start == pytest.approx(0.5)
    assert len(phrases) == 2  # the line at 20s is after the edit
    words = [
        Sung(w, n * 0.3, n * 0.3 + 0.25)
        for n, w in enumerate(["a", "b", "c", "d", "e"])
    ]
    grouped = edit.group_phrases(words, "a b\nc d e")
    assert [len(p) for p in grouped] == [2, 3]
    heard = [Sung("you", 0, 0.2), Sung("cant", 0.2, 0.4), Sung("spel", 0.4, 0.6)]
    fixed = beats.align(heard, "You can't spell")
    assert [w.text for w in fixed] == ["You", "can't", "spell"]
    sung = [Sung("Steven", 0, 0.4), Sung("money", 0.5, 0.9), Sung("hero", 1.0, 1.3)]
    big = beats.pick_big(sung, ["money"])
    assert [w.text for w in big] == ["MONEY"]


# ------------------------------------------------------------ the story


def test_a_screenplay_is_read_however_it_is_written():
    reply = json.dumps(
        {
            "title": "The king who couldn't walk",
            "series": "Epic Comebacks",
            "shots": [
                {
                    "place": "mud hut",
                    "cast": [
                        {"name": "sundiata", "action": "crawling", "at": "left"},
                        {"name": "Sogolon", "action": "weep", "feel": "sad"},
                    ],
                    "camera": "close Sogolon",
                    "speaker": "narrator",
                    "say": "He could not walk.",
                },
                {"say": "The village laughed.", "camera": "pan"},
                {"say": "", "camera": "wide"},
            ],
        }
    )
    play: Any = cast(
        Any,
        parse_screenplay(reply, idea="Sundiata", cast_names=["Sundiata", "Sogolon"]),
    )
    shots = play["shots"]
    assert len(shots) == 2 and play["series"] == "Epic Comebacks"
    first = shots[0]
    assert first["place"] == "hut" and first["camera"] == "close"
    assert first["focus"] == "Sogolon" and first["speaker"] == ""
    assert [a["name"] for a in first["cast"]] == ["Sundiata", "Sogolon"]
    assert [a["action"] for a in first["cast"]] == ["crawl", "cry"]
    # A shot that doesn't say keeps the place and the people of the one before.
    assert shots[1]["place"] == "hut" and len(shots[1]["cast"]) == 2
    assert action_of("enter") == "walk_in" and action_of("??") == "stand"
    assert camera_of("Medium on Bob") == ("medium", "on Bob")
    prose: Any = parse_screenplay(
        "Once there was a king. He could not walk at all. Then he stood.",
        idea="x",
        cast_names=["Sundiata"],
    )
    assert (
        len(prose["shots"]) == 3 and prose["shots"][0]["cast"][0]["name"] == "Sundiata"
    )


def test_cartoon_characters_act_in_painted_places():
    video_ready()
    from free_claude_code.studio.farm.cartoon.film import CartoonFrames, Film, Scene
    from free_claude_code.studio.farm.cartoon.heads import Look
    from free_claude_code.studio.farm.cartoon.puppet import ACTIONS, Placed
    from free_claude_code.studio.farm.cartoon.scene import CartoonShot, paint
    from free_claude_code.studio.farm.cartoon.stages import PLACES
    from free_claude_code.studio.farm.timing import spread_words

    king = Look("Sundiata", wear="crown", beard=True)
    kid = Look("Kid", age="kid")
    for number, action in enumerate(ACTIONS):
        place = PLACES[number % len(PLACES)]
        shot = CartoonShot(
            place,
            (
                Placed(king, action, 0.35, 1, speaking=True),
                Placed(kid, "stand", 0.7, -1),
            ),
            camera=("wide", "medium", "close", "push", "pan")[number % 5],
        )
        frame = paint(shot, 0.4, 2.0, (320, 180))
        assert frame.size == (320, 180)
    shot = CartoonShot("savanna", (Placed(king, "talk", 0.5, 1, speaking=True),))
    film = Film(
        scenes=(Scene(shot, 0.0, 2.0),),
        words=spread_words("He could not walk", 0.0, 2.0),
        duration=2.0,
        size=(360, 640),
        title="Most Epic Comebacks in History",
    )
    frame = CartoonFrames(film).draw(0.3)
    assert frame.size == (360, 640)
    # Wooden planks around the cartoon, which sits a little above the middle.
    red, green, blue = frame.getpixel((10, 10))
    assert red > green > blue
    assert frame.getpixel((180, 300)) != frame.getpixel((180, 600))


def test_cartoon_and_edit_jobs_are_read_from_what_the_user_says():
    job = farm_job("make a cartoon about the king who couldn't walk", in_farm=False)
    assert job is not None and job.kind == "cartoon"
    assert job.topic == "the king who couldn't walk"
    job = farm_job("make 2 music edits for @stevenedits", in_farm=True)
    assert job is not None and (job.kind, job.count, job.channel) == (
        "edit",
        2,
        "stevenedits",
    )
    assert farm_job("make an edit to my code", in_farm=False) is None
    assert farm_job("make me a cartoon website about cats", in_farm=False) is None
    plain = farm_job("make 3 videos about sharks", in_farm=False)
    assert plain is not None and plain.kind == ""


# ------------------------------------------------------------ on the farm


def story_writer(system: str, prompt: str):
    if system == SCREENPLAY_SYSTEM:
        assert "Sundiata: a prince who couldn't walk" in prompt
        return LLMReply(
            text=json.dumps(
                {
                    "title": "The king who couldn't walk",
                    "series": "Epic Comebacks",
                    "shots": [
                        {
                            "place": "hut",
                            "cast": [
                                {"name": "Sundiata", "action": "crawl", "at": "left"},
                                {"name": "Sogolon", "action": "cry", "at": "right"},
                            ],
                            "camera": "wide",
                            "say": "Sundiata could not walk.",
                        },
                        {
                            "camera": "close Sogolon",
                            "speaker": "Sogolon",
                            "say": "My son will be king.",
                        },
                        {
                            "place": "palace",
                            "cast": [{"name": "Sundiata", "action": "cheer"}],
                            "camera": "push",
                            "say": "And he was.",
                        },
                    ],
                    "caption": "From crawling to king.",
                    "hashtags": ["#history"],
                }
            )
        )
    return LLMReply(text=json.dumps({"big": ["MONEY", "HERO"]}))


@pytest.mark.asyncio
async def test_characters_are_made_drawn_and_cast(make_studio, tmp_path):
    video_ready()
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        made = await client.post(
            "/studio/api/farm/characters",
            json={
                "name": "Sogolon",
                "description": "his mother",
                "wear": "wrap",
                "wear_colour": "#3fa9f5",
                "hair": "mohawk",
                "age": "old",
                "earrings": True,
                "voice": "bf_emma",
            },
        )
        assert made.status_code == 200, made.text
        mother = made.json()
        assert mother["hair"] == "" and mother["age"] == "old" and mother["earrings"]
        picture = await client.get(
            f"/studio/api/farm/characters/{mother['id']}/picture"
        )
        assert picture.status_code == 200 and picture.content[:4] == b"\x89PNG"
        nameless = await client.post("/studio/api/farm/characters", json={"name": " "})
        assert nameless.status_code == 400
        clip_file = clip(tmp_path / "c.mp4", 1)
        footage = await studio.farm.library.add_file(clip_file, name="c.mp4")
        bad_head = await client.put(
            f"/studio/api/farm/characters/{mother['id']}",
            json={"head_asset": footage.id},
        )
        assert bad_head.status_code == 400
        channel = await client.post(
            "/studio/api/farm/channels",
            json={
                "niche": "history",
                "style": "cartoon_story",
                "cast": [mother["id"], "fcr_missing"],
                "series": "Most Epic Comebacks in History",
                "texture": "paper",
                "shape": "wide",
                "theme": "pink",
                "fandom": "History",
                "minutes": 60,
                "ai_media": False,
            },
        )
        assert channel.status_code == 200, channel.text
        saved = channel.json()
        assert saved["cast"] == [mother["id"]]
        assert (saved["texture"], saved["shape"], saved["theme"]) == (
            "paper",
            "wide",
            "#ff5fc8",
        )
        # Settings the page sends are all kept.
        assert (saved["fandom"], saved["minutes"], saved["ai_media"]) == (
            "History",
            60,
            False,
        )
        overview = (await client.get("/studio/api/farm")).json()
        assert [c["name"] for c in overview["characters"]] == ["Sogolon"]
        assert "crown" in overview["character_options"]["wear"]
        assert {s["kind"] for s in overview["styles"]} == {
            "narrated",
            "cartoon",
            "edit",
        }
        gone = await client.delete(f"/studio/api/farm/characters/{mother['id']}")
        assert gone.json() == {"deleted": True}
    channel_now = await studio.farm.channel(saved["id"])
    assert channel_now.cast == ()


@pytest.mark.asyncio
async def test_a_cartoon_story_is_written_voiced_and_animated(make_studio):
    video_ready()
    studio, model = make_studio(story_writer)
    king = await studio.farm.save_character(
        {
            "name": "Sundiata",
            "description": "a prince who couldn't walk",
            "wear": "crown",
        }
    )
    mother = await studio.farm.save_character({"name": "Sogolon", "voice": "bf_emma"})
    channel = await studio.farm.save_channel(
        {
            "niche": "history",
            "style": "cartoon_story",
            "cast": [king.id, mother.id],
            "voice": "none",
            "seconds": 10,
        }
    )
    idea = await studio.farm.add_idea(channel, "The king who couldn't walk")

    post = await studio.farm.make(idea.id)

    assert post.status == "ready", post.error
    assert post.data["kind"] == "cartoon" and post.data["series"] == "Epic Comebacks"
    shots = post.data["scenes"]
    assert [s["place"] for s in shots] == ["hut", "hut", "palace"]
    assert shots[1]["speaker"] == "Sogolon" and shots[1]["voice"] == "bf_emma"
    assert [a["name"] for a in shots[1]["cast"]] == ["Sundiata", "Sogolon"]
    folder = studio.farm.folder(post)
    assert (folder / "video.mp4").stat().st_size > 1_000
    assert (folder / "cover.jpg").is_file()
    assert "From crawling to king." in post.data["caption_full"]
    assert any(c["system"] == SCREENPLAY_SYSTEM for c in model.calls)
    # Your own edit keeps each shot's place, characters, and camera.
    edited = await studio.farm.edit_scenes(
        post.id,
        [
            {**shots[0], "say": "He crawled for seven years.", "place": "forest"},
            shots[2],
        ],
    )
    assert edited.data["scenes"][0]["place"] == "forest"
    assert edited.data["scenes"][0]["cast"][0]["action"] == "crawl"


@pytest.mark.asyncio
async def test_a_music_edit_cuts_clips_on_the_beat(make_studio, tmp_path):
    video_ready()
    studio, _ = make_studio(story_writer)
    track = await studio.farm.library.add_file(
        song(tmp_path / "money.wav", 20), name="Money Longer.wav"
    )
    assert track.kind == "audio" and track.duration == pytest.approx(20, abs=0.3)
    channel = await studio.farm.save_channel(
        {
            "niche": "Steven Universe edits",
            "style": "beat_edit",
            "fandom": "Steven Universe",
            "song": track.id,
            "seconds": 10,
            "pace": "fast",
        }
    )
    idea = await studio.farm.add_idea(channel, "Steven money edit")
    failed = await studio.farm.make(idea.id)
    assert failed.status == "failed" and "Add clips to the Library" in failed.error
    for name in ("steven running.mp4", "garnet fusion.mp4"):
        await studio.farm.library.add_file(
            clip(tmp_path / name, 6), name=name, show="Steven Universe"
        )
    await studio.farm.set_music(
        idea.id,
        {
            "lyrics": "[00:00.50] You can't spell my name\n[00:03.00] without the money\n"
            "[00:06.00] he's my hero",
            "song_start": 0,
            "big_words": "money, hero",
        },
    )

    post = await studio.farm.make(idea.id)

    assert post.status == "ready", post.error
    data = post.data
    assert data["kind"] == "edit" and data["tempo"] == pytest.approx(120, abs=4)
    assert data["song_window"] == [0.0, 10.0]
    assert data["lyrics_from"] == "timed lyrics"
    assert data["big_words_used"] == ["MONEY", "HERO"]
    cuts = data["scenes"]
    assert len(cuts) >= 6
    assert all(scene["media"]["type"] == "clip" for scene in cuts)
    assert cuts[0]["cut"]["start"] == 0 and cuts[-1]["cut"]["end"] == pytest.approx(10)
    from free_claude_code.studio.farm.render import probe

    seconds, width, height = probe(studio.farm.folder(post) / "video.mp4")
    assert seconds == pytest.approx(10, abs=0.3) and height > width
    # Pick your own clip for a cut; it stays when the edit is made again.
    first = cuts[0]["media"]["asset"]
    other = next(c["media"]["asset"] for c in cuts if c["media"]["asset"] != first)
    await studio.farm.set_scene_media(post.id, 0, {"asset_id": other})
    again = await studio.farm.make(post.id)
    assert again.data["scenes"][0]["media"]["asset"] == other


@pytest.mark.asyncio
async def test_a_music_edit_without_a_song_says_what_to_do(make_studio):
    video_ready()
    studio, _ = make_studio([])
    channel = await studio.farm.save_channel({"niche": "edits", "style": "beat_edit"})
    idea = await studio.farm.add_idea(channel, "an edit")
    post = await studio.farm.make(idea.id)
    assert post.status == "failed" and "Add the song first" in post.error
