"""Content Farm 2: the media library, fandom lore and stills, two-hour sleep
videos, gameplay backgrounds, and editing by hand or by AI."""

import json
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from free_claude_code.studio.farm import formats, longform
from free_claude_code.studio.farm.fandom import Fandom, api_for, plain, wiki_slug
from free_claude_code.studio.farm.library import name_tags, scene_words
from free_claude_code.studio.farm.requests import farm_job
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.service import long_title, show_of
from tests.api.support import create_test_app

WIKI = "https://breakingbad.fandom.com/api.php"


def video_ready():
    pytest.importorskip("PIL")
    pytest.importorskip("imageio_ffmpeg")


def png(colour: str = "purple", size=(640, 360)) -> bytes:
    from PIL import Image

    out = BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


def clip(path: Path, seconds: float = 4.0) -> Path:
    """A short test clip made with ffmpeg."""
    import subprocess

    from free_claude_code.studio.farm.render import find_ffmpeg

    ffmpeg = find_ffmpeg()
    assert ffmpeg
    subprocess.run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24",
            "-t",
            str(seconds),
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def fake_wiki(images: dict[str, list[str]] | None = None, text: str = ""):
    """A Fandom wiki answering the MediaWiki API, and its pictures."""
    images = images or {
        "Walter White": ["1x01 - Walt teaching chemistry.jpg", "Walt logo.svg"],
        "Gray Matter Technologies": ["1x05 - Gray Matter party.png"],
    }
    lore = text or (
        "<p>Gray Matter Technologies is a company co-founded by Walter White "
        "and Elliott Schwartz.</p><sup>[1]</sup><p>Walt sold his share for "
        "five thousand dollars.</p>"
    )
    picture = png("teal", (800, 450))

    def handle(request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        if url.netloc == "static.wikia.nocookie.net":
            return httpx.Response(
                200, content=picture, headers={"content-type": "image/png"}
            )
        if url.netloc != "breakingbad.fandom.com":
            return httpx.Response(404)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if query.get("meta") == "siteinfo":
            return httpx.Response(200, json={"query": {"general": {"sitename": "BB"}}})
        if query.get("list") == "search":
            words = query["srsearch"].lower()
            hits = [
                title
                for title in images
                if any(w in title.lower() for w in words.split())
            ]
            return httpx.Response(
                200,
                json={
                    "query": {"search": [{"title": t} for t in hits or list(images)]}
                },
            )
        if query.get("action") == "parse":
            return httpx.Response(200, json={"parse": {"text": lore}})
        if query.get("generator") == "images":
            files = images.get(query["titles"], [])
            pages = [
                {
                    "title": f"File:{name}",
                    "imageinfo": [
                        {
                            "url": f"https://static.wikia.nocookie.net/bb/{name.replace(' ', '_')}",
                            "width": 1280,
                            "height": 720,
                            "mime": "image/svg+xml"
                            if name.endswith(".svg")
                            else "image/png",
                        }
                    ],
                }
                for name in files
            ]
            return httpx.Response(200, json={"query": {"pages": pages}})
        return httpx.Response(404)

    return httpx.MockTransport(handle)


# ------------------------------------------------------------ small pieces


def test_wiki_addresses_and_text():
    assert wiki_slug("The Walking Dead") == "walkingdead"
    assert wiki_slug("Breaking Bad") == "breakingbad"
    assert api_for("https://breakingbad.fandom.com/wiki/Walter_White") == WIKI
    assert (
        api_for("starwars.fandom.com/es/wiki/Yoda")
        == "https://starwars.fandom.com/es/api.php"
    )
    text = plain(
        "<p>Walt is a <b>chemistry</b> teacher.[2]</p><script>x()</script><p>Hi</p>"
    )
    assert text == "Walt is a chemistry teacher."


def test_files_are_tagged_from_their_names_and_folders():
    tags = name_tags("Breaking Bad", "S01E05", "walt_teaching-class.mp4")
    assert {"breaking", "bad", "s01e05", "walt", "teaching", "class"} <= set(tags)
    words = scene_words("Then Walter White met Elliott at Gray Matter.", "the company")
    assert words[:4] == ("walter", "white", "elliott", "gray")
    long_line = (
        "Walt and Jesse cooked in an old RV in the desert, far from Tuco "
        "Salamanca, Gus Fring, Los Pollos Hermanos, and the Southwest."
    )
    assert "desert" in scene_words(long_line)


def test_long_videos_are_planned_in_chapters():
    assert longform.chapter_count(120) == 24
    assert longform.chapter_words(120) == 700
    title, chapters = longform.parse_outline(
        json.dumps(
            {
                "title": "The entire lore of Breaking Bad",
                "chapters": [
                    {"title": "The Teacher", "topic": "Walter White early life"}
                ]
                * 3,
            }
        ),
        count=24,
        title="x",
    )
    assert title == "The entire lore of Breaking Bad" and len(chapters) == 3
    _, listed = longform.parse_outline(
        "Chapter 1: The Teacher\nChapter 2: Gray Matter begins\n- The Diagnosis arrives",
        count=5,
        title="x",
    )
    assert [c["title"] for c in listed] == [
        "The Teacher",
        "Gray Matter begins",
        "The Diagnosis arrives",
    ]
    text = longform.clean_narration(
        "## Chapter 1\n**The Teacher**\nWalt taught. He was quiet.\n- Calm."
    )
    assert text == "Walt taught. He was quiet. Calm."
    scenes = longform.scenes_from(
        " ".join(["Walter White taught chemistry."] * 30), chapter=2
    )
    assert all(scene["chapter"] == 2 for scene in scenes)
    assert 2 <= len(scenes) <= 4 and "Walter White" in str(scenes[0]["show"])
    described = longform.youtube_description(
        title="Lore",
        show="Breaking Bad",
        chapters=[(0, "Intro"), (3725.0, "The End")],
        tags=["#lore"],
    )
    assert "00:00 Intro" in described and "1:02:05 The End" in described


@pytest.mark.parametrize(
    ("text", "long", "minutes", "topic"),
    [
        (
            "make a 2 hour sleep video about the entire lore of Breaking Bad",
            True,
            120,
            "the entire lore of Breaking Bad",
        ),
        ("make a 3 hour lore video about star wars", True, 180, "star wars"),
        ("make a sleep video about interstellar", True, 0, "interstellar"),
        ("make 3 reels about black holes", False, 0, "black holes"),
    ],
)
def test_long_jobs_are_read_from_what_the_user_says(text, long, minutes, topic):
    job = farm_job(text, in_farm=False)
    assert job is not None and (job.long, job.minutes, job.topic) == (
        long,
        minutes,
        topic,
    )


def test_shows_and_titles_for_long_videos():
    assert show_of("the entire lore of Breaking Bad") == "Breaking Bad"
    assert show_of("what if Walt never got cancer") == ""
    assert long_title("the lore of Halo", "lore_sleep") == (
        "The entire lore of Halo, explained to fall asleep to"
    )
    assert long_title("what if Walt never got cancer", "what_if_sleep").startswith(
        "What if Walt never got cancer? A calm"
    )


def test_the_styles_cover_shorts_and_sleep_videos():
    keys = {style.key for style in formats.short_styles()}
    assert {"gameplay_story", "what_if", "lore"} <= keys
    assert {style.key for style in formats.long_styles()} == {
        "lore_sleep",
        "what_if_sleep",
        "theory_sleep",
    }
    assert next(iter(formats.PLATFORMS)) == "youtube"


# ------------------------------------------------------------ fandom


@pytest.mark.asyncio
async def test_the_fandom_wiki_gives_lore_and_real_stills():
    fandom = Fandom(fake_wiki())
    assert await fandom.wiki_for("Breaking Bad") == WIKI
    lore = await fandom.lore("Breaking Bad", "Gray Matter")
    assert "co-founded by Walter White" in lore and "[1]" not in lore
    pictures = await fandom.pictures("Breaking Bad", "Walter White")
    # The logo is skipped: only stills big enough for a video.
    assert [p.title for p in pictures] == ["1x01 - Walt teaching chemistry"]
    assert pictures[0].credit.startswith("Image: breakingbad.fandom.com")


# ------------------------------------------------------------ the library


@pytest.mark.asyncio
async def test_clips_and_pictures_go_in_the_library(make_studio, tmp_path):
    video_ready()
    studio, _ = make_studio([])
    folder = tmp_path / "Breaking Bad" / "Season 1"
    folder.mkdir(parents=True)
    clip(folder / "walt teaching chemistry.mp4")
    (folder / "jesse pinkman.png").write_bytes(png())
    (folder / "notes.txt").write_text("not media")
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        linked = await client.post(
            "/studio/api/farm/media/link",
            json={"folder": str(tmp_path / "Breaking Bad")},
        )
        assert linked.status_code == 200, linked.text
        assert linked.json()["added"] == 2
        uploaded = await client.post(
            "/studio/api/farm/media",
            params={
                "name": "minecraft parkour.mp4",
                "background": "true",
                "tags": "gameplay",
            },
            content=(folder / "walt teaching chemistry.mp4").read_bytes(),
        )
        assert uploaded.status_code == 200, uploaded.text
        upload = uploaded.json()
        assert upload["background"] and upload["kind"] == "video"
        assert upload["duration"] == pytest.approx(4.0, abs=0.2)
        assets = (await client.get("/studio/api/farm/media")).json()["assets"]
        teaching = next(a for a in assets if a["name"] == "walt teaching chemistry")
        assert teaching["show"] == "Breaking Bad" and "season" in teaching["tags"]
        thumb = await client.get(teaching["thumb_url"])
        assert thumb.headers["content-type"] == "image/jpeg"
        edited = await client.patch(
            f"/studio/api/farm/media/{teaching['id']}", json={"note": "Walt in class"}
        )
        assert edited.json()["note"] == "Walt in class"
        refused = await client.post(
            "/studio/api/farm/media", params={"name": "notes.txt"}, content=b"x"
        )
        assert refused.status_code == 400
        overview = (await client.get("/studio/api/farm")).json()
        assert overview["library"]["backgrounds"] == [
            {"id": upload["id"], "name": "minecraft parkour"}
        ]
        gone = await client.delete(f"/studio/api/farm/media/{teaching['id']}")
        assert gone.json() == {"deleted": True}
        # A linked file stays on the PC.
        assert (folder / "walt teaching chemistry.mp4").is_file()
    best = await studio.farm.library.best(("jesse",), show="Breaking Bad")
    assert [asset.name for asset in best] == ["jesse pinkman"]


# ------------------------------------------------------------ picking media


def writer(system: str, prompt: str):
    if system == formats.WRITER_SYSTEM:
        return LLMReply(
            text=json.dumps(
                {
                    "title": "Walt's five thousand dollar mistake",
                    "scenes": [
                        {
                            "say": "Walter White sold Gray Matter for five grand.",
                            "show": "Gray Matter",
                        },
                        {"say": "Jesse Pinkman never knew.", "show": "Jesse Pinkman"},
                        {
                            "say": "Follow for more Breaking Bad lore.",
                            "show": "Walter White",
                        },
                    ],
                    "caption": "The worst deal in TV history.",
                    "hashtags": ["#breakingbad"],
                }
            )
        )
    if system == formats.POLISH_SYSTEM:
        script = json.loads(prompt)
        script["scenes"][0]["say"] = "Walt threw away billions for five grand."
        return LLMReply(text=json.dumps(script))
    if system == formats.IDEAS_SYSTEM:
        return LLMReply(text=json.dumps(["Walt's worst deal", "Jesse's secret"]))
    if system == formats.EDIT_SYSTEM:
        rows = json.loads(prompt.split("The scenes now:\n", 1)[1])["scenes"]
        rows[1] = {
            "say": "Jesse found out years later.",
            "show": "Jesse Pinkman",
            "text": "YEARS LATER",
        }
        return LLMReply(text=json.dumps({"scenes": rows}))
    if system == longform.OUTLINE_SYSTEM:
        return LLMReply(
            text=json.dumps(
                {
                    "title": "The entire lore of Breaking Bad, to sleep to",
                    "chapters": [
                        {"title": "The Teacher", "topic": "Walter White"},
                        {"title": "Gray Matter", "topic": "Gray Matter Technologies"},
                        {"title": "The End", "topic": "Walter White"},
                    ],
                }
            )
        )
    if system == longform.CHAPTER_SYSTEM:
        chapter = prompt.split("Chapter ", 1)[1].split(" of ", 1)[0]
        return LLMReply(
            text=f"Chapter {chapter}\n"
            + " ".join(["Walter White taught chemistry quietly."] * 14)
        )
    return LLMReply(text="ok")


@pytest.mark.asyncio
async def test_a_lore_short_uses_the_library_then_the_wiki_and_is_polished(
    make_studio, tmp_path
):
    video_ready()
    studio, model = make_studio(writer)
    studio.farm.fandom = Fandom(fake_wiki())
    studio.farm._transport = fake_wiki()
    pic = tmp_path / "jesse pinkman.png"
    pic.write_bytes(png("orange"))
    await studio.farm.library.add_file(
        pic, name="jesse pinkman.png", show="Breaking Bad"
    )
    channel = await studio.farm.save_channel(
        {
            "fandom": "Breaking Bad",
            "style": "lore",
            "voice": "none",
            "seconds": 10,
            "ai_media": False,
        }
    )
    assert channel.platform == "youtube" and channel.visuals == "auto"
    idea = await studio.farm.add_idea(channel, "Walt's worst deal")

    post = await studio.farm.make(idea.id)

    assert post.status == "ready", post.error
    scenes = post.data["scenes"]
    assert scenes[0]["say"] == "Walt threw away billions for five grand."
    sources = [scene["media"]["source"] for scene in scenes]
    assert sources[1] == "library"  # Jesse, from your own pictures
    assert "wiki" in sources  # real stills from the fandom wiki
    assert "card" not in sources and "ai" not in sources  # AI media is off
    assert "Image: breakingbad.fandom.com" in post.data["caption_full"]
    assert post.data["yt_title"] == "Walt's five thousand dollar mistake"
    writer_call = next(c for c in model.calls if c["system"] == formats.WRITER_SYSTEM)
    assert "co-founded by Walter White" in str(writer_call["prompt"])


@pytest.mark.asyncio
async def test_a_gameplay_story_runs_over_the_background_clip(make_studio, tmp_path):
    video_ready()
    studio, _ = make_studio(writer)
    gameplay = await studio.farm.library.add_file(
        clip(tmp_path / "parkour.mp4", 12), name="parkour.mp4", background=True
    )
    channel = await studio.farm.save_channel(
        {
            "niche": "scary stories",
            "style": "gameplay_story",
            "visuals": "none",
            "background": gameplay.id,
            "voice": "none",
            "seconds": 10,
        }
    )
    idea = await studio.farm.add_idea(channel, "The knock at 3 AM")
    post = await studio.farm.make(idea.id)
    assert post.status == "ready", post.error
    assert all(scene["media"]["type"] == "none" for scene in post.data["scenes"])
    with pytest.raises(Exception, match="has to be a clip"):
        picture = tmp_path / "p.png"
        picture.write_bytes(png())
        still = await studio.farm.library.add_file(picture, name="p.png")
        await studio.farm.save_channel({"background": still.id}, channel.id)


# ------------------------------------------------------------ long videos


@pytest.mark.asyncio
async def test_a_two_hour_sleep_video_is_written_in_chapters(make_studio, tmp_path):
    video_ready()
    studio, model = make_studio(writer)
    studio.farm.fandom = Fandom(fake_wiki())
    studio.farm._transport = fake_wiki()
    footage = await studio.farm.library.add_file(
        clip(tmp_path / "walter white lab.mp4", 6),
        name="walter white lab.mp4",
        show="Breaking Bad",
    )
    channel = await studio.farm.save_channel(
        {
            "fandom": "Breaking Bad",
            "style": "lore_sleep",
            "voice": "none",
            "minutes": 15,
        }
    )
    assert channel.look == "cinema" and not channel.captions
    idea = await studio.farm.add_idea(channel, "The entire lore of Breaking Bad")

    post = await studio.farm.make(idea.id)

    assert post.status == "ready", post.error
    assert post.data["kind"] == "long"
    assert [c["title"] for c in post.data["chapters"]] == [
        "The Teacher",
        "Gray Matter",
        "The End",
    ]
    assert post.data["chapters"][0]["start"] == 0
    assert "00:00 The Teacher" in post.data["caption_full"]
    assert post.data["thumb"] == "thumb.jpg"
    scenes = post.data["scenes"]
    assert {scene["chapter"] for scene in scenes} == {0, 1, 2}
    assert any(s["media"].get("asset") == footage.id for s in scenes)
    assert any(s["media"]["source"] == "wiki" for s in scenes)
    chapter_calls = [
        c
        for c in model.calls
        if c["system"] == longform.CHAPTER_SYSTEM and "Carry on" not in str(c["prompt"])
    ]
    assert len(chapter_calls) == 3
    assert "co-founded by Walter White" in str(chapter_calls[1]["prompt"])
    from free_claude_code.studio.farm.render import probe

    seconds, width, height = probe(studio.farm.file(post, "video.mp4"))
    assert (width, height) == (1280, 720) and seconds > 20
    view = studio.farm.view(post)
    assert "scenes" not in view["data"] and view["scene_count"] == len(scenes)


@pytest.mark.asyncio
async def test_a_stopped_long_video_carries_on_from_its_chapters(make_studio):
    studio, model = make_studio(writer)
    channel = await studio.farm.save_channel(
        {"niche": "space", "style": "what_if_sleep", "voice": "none", "minutes": 15}
    )
    idea = await studio.farm.add_idea(channel, "What if the Moon vanished")
    state = {
        "title": "What if the Moon vanished",
        "chapters": [{"title": f"Part {n}", "topic": "moon"} for n in range(3)],
        "texts": ["The tides went still. " * 10],
    }
    await studio._store.put(idea.model_copy(update={"data": {"long": state}}))
    post = await studio.farm.post(idea.id)
    data = await studio.farm._write_long(post, channel, dict(post.data))
    # Only the two chapters still missing were written (each asked to carry
    # on once, since the test writer is brief).
    written = [
        c
        for c in model.calls
        if c["system"] == longform.CHAPTER_SYSTEM and "Carry on" not in str(c["prompt"])
    ]
    assert [str(c["prompt"]).split("\n")[3] for c in written] == [
        "Chapter 2 of 3: Part 1",
        "Chapter 3 of 3: Part 2",
    ]
    assert len(data["long"]["texts"]) == 3
    assert data["scenes"][0]["say"].startswith("The tides went still.")


# ------------------------------------------------------------ editing


@pytest.mark.asyncio
async def test_you_and_the_ai_can_edit_a_video_and_render_it_again(
    make_studio, tmp_path
):
    video_ready()
    studio, _ = make_studio(writer)
    studio.farm.fandom = Fandom(fake_wiki())
    studio.farm._transport = fake_wiki()
    channel = await studio.farm.save_channel(
        {"fandom": "Breaking Bad", "style": "lore", "voice": "none", "seconds": 10}
    )
    idea = await studio.farm.add_idea(channel, "Walt's worst deal")
    post = await studio.farm.make(idea.id)
    assert post.status == "ready", post.error
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        editor = (await client.get(f"/studio/api/farm/posts/{post.id}/editor")).json()
        scenes = editor["scenes"]
        assert len(scenes) == 3 and scenes[0]["media"]["preview"].startswith(
            "/studio/api/farm/posts/"
        )
        kept = scenes[0]["media"]
        # Your own edit: a new line for scene 3, scene 1 kept as it was.
        scenes[2]["say"] = "Subscribe for the rest of the story."
        saved = await client.put(
            f"/studio/api/farm/posts/{post.id}/scenes", json={"scenes": scenes}
        )
        assert saved.status_code == 200, saved.text
        edited = saved.json()
        assert edited["data"]["edited"] is True
        assert edited["scenes"][0]["media"]["file"] == kept["file"]
        # The AI's edit: it rewrote scene 2 and kept the others' pictures.
        ai = await client.post(
            f"/studio/api/farm/posts/{post.id}/ai-edit",
            json={"instruction": "make scene 2 a cliffhanger"},
        )
        assert ai.status_code == 200, ai.text
        after = ai.json()["scenes"]
        assert (
            after[1]["say"] == "Jesse found out years later."
            and after[1]["text"] == "YEARS LATER"
        )
        assert after[0]["media"]["file"] == kept["file"]
        # Swap a scene's picture for one from your library.
        picture = tmp_path / "jesse.png"
        picture.write_bytes(png("red"))
        asset = await studio.farm.library.add_file(picture, name="jesse.png")
        swapped = await client.put(
            f"/studio/api/farm/posts/{post.id}/scenes/2/media",
            json={"asset_id": asset.id},
        )
        assert swapped.json()["scenes"][2]["media"]["asset"] == asset.id
        assert swapped.json()["scenes"][2]["media"]["locked"] is True
        candidates = (
            await client.get(
                f"/studio/api/farm/posts/{post.id}/candidates",
                params={"q": "Walter White"},
            )
        ).json()
        assert any(c["source"] == "wiki" for c in candidates["candidates"])
        render = await client.post(f"/studio/api/farm/posts/{post.id}/make")
        assert render.status_code == 202
        await studio.wait_for_background()
    final = await studio.farm.post(post.id)
    assert final.status == "ready", final.error
    assert final.data["scenes"][1]["say"] == "Jesse found out years later."
    assert final.data["scenes"][2]["media"]["asset"] == asset.id
    assert "edited" not in final.data


@pytest.mark.asyncio
async def test_a_long_video_is_ai_edited_a_chapter_at_a_time(make_studio):
    studio, _ = make_studio(writer)
    channel = await studio.farm.save_channel({"niche": "space", "style": "lore_sleep"})
    idea = await studio.farm.add_idea(channel, "Space lore")
    scenes = [
        {"say": f"Line {n}.", "show": "stars", "text": "", "chapter": n // 25}
        for n in range(50)
    ]
    await studio._store.put(idea.model_copy(update={"data": {"scenes": scenes}}))
    with pytest.raises(Exception, match="pick a chapter"):
        await studio.farm.ai_edit(idea.id, "calmer")
    post = await studio.farm.ai_edit(idea.id, "calmer", chapter=1)
    assert len(post.data["scenes"]) == 50
    assert post.data["scenes"][26]["say"] == "Jesse found out years later."
    assert post.data["scenes"][26]["chapter"] == 1


@pytest.mark.asyncio
async def test_jarvis_starts_a_two_hour_video_from_the_farm_chat(
    make_studio, monkeypatch
):
    studio, _ = make_studio(writer)
    await studio.ensure_defaults()
    started: list[list[str]] = []

    async def fake_make(post_ids, **_):
        started.append(list(post_ids))
        return len(post_ids)

    monkeypatch.setattr(studio, "farm_make", fake_make)
    from free_claude_code.studio import service as service_module

    monkeypatch.setattr(service_module, "video_tools", lambda: (True, ""))
    await studio.farm_say(
        "make a 2 hour sleep video about the entire lore of Breaking Bad",
        background=False,
    )
    [channel] = await studio.farm.channels()
    assert channel.style == "lore_sleep" and channel.fandom == "Breaking Bad"
    assert channel.minutes == 120
    [post] = await studio.farm.posts(channel.id)
    assert post.title == "The entire lore of Breaking Bad, explained to fall asleep to"
    assert started == [[post.id]]
