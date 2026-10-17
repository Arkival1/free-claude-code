"""The Content Farm: channels, ideas, scripts, and finished vertical videos."""

import json
import wave
from datetime import datetime, timedelta
from itertools import pairwise

import httpx
import pytest

from free_claude_code.studio.farm import formats
from free_claude_code.studio.farm.farm import clean_times, next_slot
from free_claude_code.studio.farm.requests import farm_job
from free_claude_code.studio.farm.timing import (
    chunks,
    join_wavs,
    silent_wav,
    spread_words,
    wav_length,
)
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import FarmChannel
from free_claude_code.studio.tools import (
    DEFAULT_TOOL_NAMES,
    MAIN_TOOL_NAMES,
    TOOL_SPEC_BY_NAME,
)
from tests.api.support import create_test_app

from .conftest import tool_reply

SCRIPT = {
    "title": "Black holes can sing",
    "scenes": [
        {"say": "Black holes can sing.", "show": "black hole", "text": "THEY SING"},
        {"say": "NASA turned the sound waves into audio.", "show": "nasa"},
        {"say": "The note is a B flat, way below our hearing.", "show": "sound wave"},
        {"say": "Follow for a space fact every day.", "show": "galaxy"},
    ],
    "caption": "The universe has a soundtrack.",
    "hashtags": ["#space", "astronomy", "#space"],
}
IDEAS = ["Black holes can sing", "Why Venus spins backwards", "A day on Mercury"]


def farm_writer(system: str, prompt: str):
    if system == formats.IDEAS_SYSTEM:
        return LLMReply(text=json.dumps(IDEAS))
    if system == formats.WRITER_SYSTEM:
        return LLMReply(text="Here you go:\n" + json.dumps(SCRIPT))
    if "running notes" in system:
        return LLMReply(text="Goal:\n- Videos")
    return LLMReply(text="On it! They'll be in the queue.")


def video_ready():
    pytest.importorskip("PIL")
    pytest.importorskip("imageio_ffmpeg")


# ------------------------------------------------------------ the writer


def test_a_script_is_read_from_json_and_cleaned():
    script = formats.parse_script(
        json.dumps(SCRIPT), idea="black holes", seconds=30, channel_tags=("#facts",)
    )
    assert script.hook == "Black holes can sing."
    assert [scene.show for scene in script.scenes][:2] == ["black hole", "nasa"]
    assert script.scenes[0].text == "THEY SING"
    # The channel's tags first, no repeats, every one a #tag.
    assert script.hashtags == ("#facts", "#space", "#astronomy")
    caption = formats.full_caption(script, "Follow for more", "instagram")
    assert caption.startswith("The universe has a soundtrack.\n\nFollow for more")
    assert caption.endswith("#facts #space #astronomy")
    # YouTube gets the title first, and #Shorts.
    youtube = formats.full_caption(script, "Follow for more")
    assert youtube.startswith("Black holes can sing\n\nThe universe")
    assert youtube.endswith("#astronomy #Shorts")


def test_a_script_in_plain_words_still_becomes_scenes():
    reply = (
        "1. Octopuses have three hearts. Two pump blood to the gills.\n"
        "2. Their blood is blue because of copper.\n"
        "3. They can taste with their arms!"
    )
    script = formats.parse_script(reply, idea="octopus facts", seconds=15)
    assert 2 <= len(script.scenes) <= formats.scene_count(15)
    assert "three hearts" in script.scenes[0].say
    assert all(scene.show for scene in script.scenes)


def test_ideas_come_from_json_or_a_list():
    assert formats.parse_ideas(json.dumps(IDEAS), count=2) == IDEAS[:2]
    listed = "Sure!\n1. Why cats purr\n2) How cats see at night\n- Why cats purr"
    assert formats.parse_ideas(listed, count=5) == [
        "Why cats purr",
        "How cats see at night",
    ]
    wrapped = json.dumps({"ideas": [{"title": "Sharks are older than trees"}]})
    assert formats.parse_ideas(wrapped, count=3) == ["Sharks are older than trees"]


def test_the_writer_is_asked_for_the_length_and_style():
    prompt = formats.script_prompt(
        idea="5 facts about the deep sea",
        niche="ocean",
        style="facts",
        platform="tiktok",
        seconds=30,
        call_to_action="Follow for part 2",
        notes="no swearing",
        facts="- The Mariana Trench is 11 km deep",
    )
    assert "about 78 spoken words in 6 scenes" in prompt
    assert "TikTok" in prompt and "Follow for part 2" in prompt
    assert "Mariana Trench" in prompt and "no swearing" in prompt


# ------------------------------------------------------------ timing


def test_words_are_timed_across_their_scene_and_grouped():
    words = spread_words("Black holes can sing, really.", 2.0, 2.5)
    assert words[0].start == 2.0 and words[-1].end == pytest.approx(4.5, abs=0.01)
    assert all(a.end == pytest.approx(b.start, abs=0.01) for a, b in pairwise(words))
    grouped = chunks(words)
    # A comma ends a screenful early.
    assert [len(chunk.words) for chunk in grouped] == [3, 1, 1]


def test_voice_clips_join_with_breaths_between():
    joined = join_wavs([silent_wav(1.0), silent_wav(0.5)], [0.2, 0.2])
    assert wav_length(joined) == pytest.approx(1.9, abs=0.01)
    with wave.open(__import__("io").BytesIO(joined)) as reader:
        assert reader.getframerate() == 24_000


def test_posting_times_fill_the_next_free_slots():
    channel = FarmChannel(name="space", post_times=("09:00", "18:00"))
    now = datetime(2026, 10, 4, 12, 0).astimezone()
    first = next_slot(channel, [], now=now)
    assert datetime.fromtimestamp(first / 1000).hour == 18
    second = next_slot(channel, [first], now=now)
    later = datetime.fromtimestamp(second / 1000)
    assert (later.hour, later.date()) == (9, (now + timedelta(days=1)).date())
    assert clean_times("7:05, 25:00, 18:00, 7:05") == ("07:05", "18:00")


# ------------------------------------------------------------ what users say


@pytest.mark.parametrize(
    ("text", "in_farm", "action", "topic", "count"),
    [
        ("make 3 reels about black holes", False, "make", "black holes", 3),
        (
            "jarvis make a video about sharks in the content farm",
            False,
            "make",
            "sharks",
            1,
        ),
        ("give me 5 video ideas about space", False, "ideas", "space", 5),
        ("make one about sharks", True, "make", "sharks", 1),
        ("give me ideas", True, "ideas", "", 5),
        ("start a channel about gym motivation", True, "channel", "gym motivation", 1),
    ],
)
def test_farm_jobs_are_read_from_what_the_user_says(
    text, in_farm, action, topic, count
):
    job = farm_job(text, in_farm=in_farm)
    assert job is not None
    assert (job.action, job.topic, job.count) == (action, topic, count)


@pytest.mark.parametrize(
    ("text", "in_farm"),
    [
        ("make me a website", False),
        ("what reels should I make?", False),
        ("make shampoo in the lab", False),
        ("make a todo list", True),
    ],
)
def test_other_messages_are_not_farm_jobs(text, in_farm):
    assert farm_job(text, in_farm=in_farm) is None


def test_a_channel_is_named_with_for_at():
    job = farm_job("make 2 tiktoks about cats for @catfacts.daily", in_farm=False)
    assert job is not None and (job.channel, job.topic) == ("catfacts.daily", "cats")


def test_only_jarvis_and_the_farm_agent_get_the_farm():
    assert "farm" in MAIN_TOOL_NAMES
    assert "farm" not in DEFAULT_TOOL_NAMES
    properties = TOOL_SPEC_BY_NAME["farm"].parameters["properties"]
    assert isinstance(properties, dict)
    action = properties["action"]
    assert isinstance(action, dict)
    assert action["enum"] == ["make", "ideas", "channel", "list", "queue"]


# ------------------------------------------------------------ the farm


@pytest.mark.asyncio
async def test_a_channel_fills_its_idea_board(make_studio):
    studio, model = make_studio(farm_writer)
    channel = await studio.save_farm_channel(
        {"niche": "space facts", "style": "facts", "post_times": ["7:30", "19:00"]}
    )
    assert channel["name"] == "spacefacts" and channel["post_times"] == [
        "07:30",
        "19:00",
    ]
    posts = await studio.farm_ideas(channel["id"], count=3, topic="planets")
    assert [post["title"] for post in posts] == IDEAS
    assert all(post["status"] == "idea" for post in posts)
    asked = next(c for c in model.calls if c["system"] == formats.IDEAS_SYSTEM)
    assert "this time about: planets" in str(asked["prompt"])
    overview = await studio.farm_overview()
    assert overview["channels"][0]["counts"] == {"idea": 3}
    assert {style["key"] for style in overview["styles"]} >= {
        "facts",
        "story",
        "ai_art",
    }


@pytest.mark.asyncio
async def test_a_video_is_written_voiced_and_rendered(make_studio):
    video_ready()
    studio, _ = make_studio(farm_writer)
    channel = await studio.farm.save_channel(
        {"niche": "space", "visuals": "text", "voice": "none", "seconds": 15}
    )
    idea = await studio.farm.add_idea(channel, "Black holes can sing")

    post = await studio.farm.make(idea.id)

    assert post.status == "ready", post.error
    assert post.progress == 100 and post.scheduled_at > 0
    assert post.data["script"]["hook"] == "Black holes can sing."
    assert "#space" in post.data["caption_full"]
    video = studio.farm.file(post, "video.mp4")
    assert video.stat().st_size > 10_000
    assert video.read_bytes()[4:8] == b"ftyp"
    assert studio.farm.file(post, "cover.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    # Four scenes read at the farm's pace, with breaths between.
    assert 6 < post.data["duration"] < 14
    with pytest.raises(ValueError):
        studio.farm.file(post, "../../escape.mp4")


@pytest.mark.asyncio
async def test_videos_go_through_the_app(make_studio):
    video_ready()
    studio, _ = make_studio(farm_writer)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        made = await client.post(
            "/studio/api/farm/channels",
            json={"niche": "space", "visuals": "text", "voice": "none", "seconds": 10},
        )
        assert made.status_code == 200, made.text
        channel = made.json()
        idea = await client.post(
            f"/studio/api/farm/channels/{channel['id']}/posts",
            json={"title": "Black holes can sing"},
        )
        post_id = idea.json()["id"]
        started = await client.post(f"/studio/api/farm/posts/{post_id}/make")
        assert started.status_code == 202
        await studio.wait_for_background()
        overview = (await client.get("/studio/api/farm")).json()
        [post] = overview["posts"]
        assert post["status"] == "ready", post["error"]
        video = await client.get(post["video_url"])
        assert video.headers["content-type"] == "video/mp4"
        download = await client.get(post["video_url"] + "?download=1")
        assert "black-holes-can-sing.mp4" in download.headers["content-disposition"]
        posted = await client.post(
            f"/studio/api/farm/posts/{post_id}/posted", json={"posted": True}
        )
        assert posted.json()["status"] == "posted"
        chat = (await client.get("/studio/api/farm/chat")).json()
        assert any(
            "Video ready: Black holes can sing" in m["text"] for m in chat["messages"]
        )
        gone = await client.delete(f"/studio/api/farm/channels/{channel['id']}")
        assert gone.json() == {"deleted": True}
        assert (await client.get("/studio/api/farm")).json()["posts"] == []


@pytest.mark.asyncio
async def test_a_bad_channel_or_missing_tools_say_so(make_studio, monkeypatch):
    studio, _ = make_studio(farm_writer)
    channel = await studio.farm.save_channel({"niche": "cats"})
    idea = await studio.farm.add_idea(channel, "Why cats purr")
    from free_claude_code.studio.farm import farm as farm_module

    monkeypatch.setattr(farm_module, "video_tools", lambda: (False, "Install it."))
    post = await studio.farm.make(idea.id)
    assert post.status == "failed" and "Install it." in post.error


@pytest.mark.asyncio
async def test_jarvis_makes_reels_from_the_farm_chat(make_studio):
    video_ready()
    turns = iter(
        [
            tool_reply("farm", {"action": "make", "topic": "black holes", "count": 2}),
            LLMReply(text="Two space videos are on the way!"),
        ]
    )

    def respond(system: str, prompt: str):
        if system in {formats.IDEAS_SYSTEM, formats.WRITER_SYSTEM}:
            return farm_writer(system, prompt)
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Videos")
        return next(turns, LLMReply(text="Done."))

    studio, model = make_studio(respond)
    await studio.ensure_defaults()
    main = await studio.main_agent()
    assert "farm" in main.tools
    await studio.farm.save_channel(
        {"niche": "space", "visuals": "text", "voice": "none"}
    )

    await studio.farm_say("what should we post this week", background=False)
    await studio.wait_for_background()

    console = await studio.farm_console()
    tool = next(m for m in console["messages"] if m["role"] == "tool")
    assert tool["data"]["tool"] == "farm" and len(tool["data"]["post_ids"]) == 2
    farm_call = next(c for c in model.calls if "Content Farm" in str(c["system"]))
    assert "farm" in farm_call["tools"]
    ready = await studio.farm.queue()
    assert len(ready) == 2
    assert ready[0].scheduled_at < ready[1].scheduled_at


@pytest.mark.asyncio
async def test_saying_make_in_the_farm_chat_makes_them(make_studio):
    studio, model = make_studio(farm_writer)
    await studio.ensure_defaults()

    await studio.farm_say("make 3 reels about planets", background=False)

    # With no channel yet, one is made for the topic.
    [channel] = await studio.farm.channels()
    assert channel.niche == "planets"
    posts = await studio.farm.posts(channel.id)
    assert len(posts) == 3
    # The agent's reply; the farm's own writing calls can finish after it.
    note = next(
        str(call["studio_note"])
        for call in reversed(model.calls)
        if call["studio_note"]
    )
    assert "Studio already did this in the Content Farm" in note
    await studio.shutdown()


@pytest.mark.asyncio
async def test_reels_asked_for_in_the_main_chat_go_to_the_farm_agent(make_studio):
    studio, model = make_studio(farm_writer)
    await studio.ensure_defaults()
    producer = await studio.agent_by_name("Farm")
    assert producer is not None and producer.role == "farm"

    await studio.main_say("make 2 reels about sharks", background=False)
    await studio.wait_for_background()

    [run] = await studio.runs()
    assert run.agent_id == producer.id
    assert "Make 2 videos about sharks in the Content Farm." in run.goal
    # Its model only talked, so Studio ran the farm job for it.
    [channel] = await studio.farm.channels()
    assert len(await studio.farm.posts(channel.id)) == 2
    note = next(
        str(c["studio_note"])
        for c in model.calls
        if "the user's main AI" in str(c["system"])
    )
    assert "went to the Farm agent" in note
    await studio.shutdown()


@pytest.mark.asyncio
async def test_a_local_image_maker_draws_the_pictures(make_studio):
    video_ready()
    from io import BytesIO

    from PIL import Image

    picture = BytesIO()
    Image.new("RGB", (64, 112), "purple").save(picture, "PNG")
    asked: list[str] = []

    def stable_diffusion(request: httpx.Request) -> httpx.Response:
        asked.append(json.loads(request.content)["prompt"])
        import base64

        return httpx.Response(
            200, json={"images": [base64.b64encode(picture.getvalue()).decode()]}
        )

    studio, _ = make_studio(farm_writer, STUDIO_FARM_IMAGE_URL="http://127.0.0.1:7860")
    studio.farm_image_transport = httpx.MockTransport(stable_diffusion)
    channel = await studio.farm.save_channel(
        {"niche": "space", "visuals": "ai", "voice": "none", "seconds": 10}
    )
    idea = await studio.farm.add_idea(channel, "Black holes can sing")
    post = await studio.farm.make(idea.id)

    assert post.status == "ready", post.error
    assert len(asked) == 4 and asked[0].startswith("black hole, space, vertical 9:16")
    first = post.data["scenes"][0]["media"]
    assert first["source"] == "ai" and first["file"].endswith(".png")
    assert studio.farm.file(post, first["file"]).is_file()
