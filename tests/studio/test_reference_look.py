"""Photos and videos the owner sends, turned into build briefs (look_reference)."""

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from free_claude_code.studio import reference_look
from free_claude_code.studio.llm import LLMReply, StudioLLMError

from .test_builder_images import builder_in_project, run

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg on PATH")
VISION = "nvidia_nim/vision-model"
GAME_BRIEF = (
    "GENRE: 2d platformer\nVIEW AND CAMERA: side view, follows the player.\n"
    "PLAYER: a small red fox."
)


def made(tmp_path: Path, name: str, *args: str) -> bytes:
    assert FFMPEG
    target = tmp_path / name
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", *args, str(target)], check=True)
    return target.read_bytes()


def picture(tmp_path: Path) -> bytes:
    return made(
        tmp_path,
        "shot.png",
        "-f",
        "lavfi",
        "-i",
        "color=red:s=2000x1000",
        "-frames:v",
        "1",
    )


def video(tmp_path: Path) -> bytes:
    return made(
        tmp_path,
        "play.mp4",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=3:size=320x240:rate=10",
        "-c:v",
        "mpeg4",
    )


def test_lengths_and_genres_are_read_from_text():
    assert reference_look.duration_of("  Duration: 00:01:02.50, start") == 62.5
    assert reference_look.duration_of("no length") == 0.0
    assert reference_look.genre_of(GAME_BRIEF) == "2d platformer"
    assert reference_look.genre_of("**GENRE:** Top-down RPG, cosy") == "top down rpg"
    assert reference_look.genre_of("nothing") == ""
    assert reference_look.slug("My Game!! 2") == "my-game-2"


@needs_ffmpeg
@pytest.mark.asyncio
async def test_a_game_photo_becomes_a_brief_with_demos_and_a_saved_note(
    make_studio, tmp_path
):
    studio, model = make_studio(
        lambda system, prompt: LLMReply(text=GAME_BRIEF),
        STUDIO_VISION_MODEL=VISION,
    )
    site, context = await builder_in_project(studio)
    idea = await studio._ideas.add(
        title="Fox game",
        text="my own art",
        category="game",
        name="fox.png",
        data=picture(tmp_path),
    )
    outcome = await run(studio, context, "look_reference", idea=idea.title)
    assert not outcome.failed, outcome.text
    assert "red fox" in outcome.text and outcome.data["make"] == "game"
    assert outcome.data["demos"] and "Closest Godot demos" in outcome.text
    asked = model.calls[-1]
    assert asked["model"] == VISION
    message = asked["messages"][-1]
    assert "my own art" in message.content
    (image,) = message.images
    head, _, body = image.partition(",")
    assert head == "data:image/jpeg;base64"
    sent = base64.b64decode(body)
    assert sent[:2] == b"\xff\xd8"  # shrunk to a JPEG
    assert "GENRE" in asked["system"] and "BELONGS TO SOMEONE ELSE" in asked["system"]
    note = await studio.workspace.read(site.id, outcome.data["note"])
    assert "red fox" in note and outcome.data["note"].startswith(
        "reference-notes/fox-game-"
    )


@needs_ffmpeg
@pytest.mark.asyncio
async def test_a_video_is_seen_as_nine_frames_in_time_order(make_studio, tmp_path):
    studio, model = make_studio(
        lambda system, prompt: LLMReply(text=GAME_BRIEF),
        STUDIO_VISION_MODEL=VISION,
    )
    site, context = await builder_in_project(studio)
    idea = await studio._ideas.add(
        title="Run cycle", category="game", name="run.mp4", data=video(tmp_path)
    )
    outcome = await run(
        studio, context, "look_reference", idea=idea.id, focus="the run animation"
    )
    assert not outcome.failed, outcome.text
    assert 2.5 <= outcome.data["video_seconds"] <= 3.5
    asked = model.calls[-1]
    assert "sheet of 9 frames" in asked["system"]
    assert "the run animation" in asked["messages"][-1].content
    sheet = await studio.workspace.read_bytes(site.id, outcome.data["frames"])
    assert sheet[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_without_a_vision_model_it_says_what_to_set(make_studio, tmp_path):
    studio, model = make_studio([])
    _, context = await builder_in_project(studio)
    outcome = await run(studio, context, "look_reference", idea="anything")
    assert outcome.failed and "Vision Model" in outcome.text
    assert not model.calls


@needs_ffmpeg
@pytest.mark.asyncio
async def test_a_model_that_cant_see_fails_with_the_reason(make_studio, tmp_path):
    def respond(system: str, prompt: str) -> object:
        raise StudioLLMError("this model doesn't take images")

    studio, _ = make_studio(respond, STUDIO_VISION_MODEL="nvidia_nim/text")
    _, context = await builder_in_project(studio)
    await studio._ideas.add(title="Shop", name="shop.png", data=picture(tmp_path))
    outcome = await run(studio, context, "look_reference", idea="Shop")
    assert outcome.failed and "doesn't take images" in outcome.text


@pytest.mark.asyncio
async def test_a_note_or_link_has_nothing_to_look_at(make_studio):
    studio, _ = make_studio([], STUDIO_VISION_MODEL=VISION)
    _, context = await builder_in_project(studio)
    await studio._ideas.add(title="Idea", text="a racing game")
    note = await run(studio, context, "look_reference", idea="Idea")
    assert note.failed and "no photo or video" in note.text
    nothing = await run(studio, context, "look_reference")
    assert nothing.failed and "Say which reference" in nothing.text


@pytest.mark.asyncio
async def test_a_video_without_ffmpeg_says_how_to_get_it(monkeypatch, tmp_path):
    monkeypatch.setattr(reference_look, "find_ffmpeg", lambda: None)
    with pytest.raises(reference_look.ReferenceLookError, match="ffmpeg"):
        await reference_look.video_sheet(tmp_path / "a.mp4", None)
    kind, data = await reference_look.photo_picture(b"small", "image/png", None)
    assert (kind, data) == ("image/png", b"small")
    with pytest.raises(reference_look.ReferenceLookError, match="too big"):
        await reference_look.photo_picture(b"x" * 4_000_000, "image/png", None)


@pytest.mark.asyncio
async def test_game_references_have_their_own_category_for_the_game_makers(
    make_studio,
):
    studio, _ = make_studio([])
    idea = await studio._ideas.add(
        title="Boss fight", text="the dragon", category="games"
    )
    assert idea.category == "game"
    listed = await studio.idea_list()
    assert listed["categories"]["game"] == 1
    _, context = await builder_in_project(studio)
    found = await run(studio, context, "ideas", action="search", category="game")
    assert idea.id in found.data["ideas"]


@needs_ffmpeg
@pytest.mark.asyncio
@pytest.mark.parametrize("seconds", ["0.4", "1", "7"])
async def test_videos_of_any_length_give_a_whole_sheet(tmp_path, seconds):
    clip = tmp_path / "clip.mp4"
    made(
        tmp_path,
        "clip.mp4",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={seconds}:size=320x240:rate=24",
        "-c:v",
        "mpeg4",
    )
    sheet, length = await reference_look.video_sheet(clip, FFMPEG)
    assert sheet[:2] == b"\xff\xd8"
    assert abs(length - float(seconds)) < 0.3


@needs_ffmpeg
@pytest.mark.asyncio
async def test_a_builder_in_a_godot_project_gets_a_game_brief_and_notes_dont_clash(
    make_studio, tmp_path
):
    studio, _ = make_studio(
        lambda system, prompt: LLMReply(text=GAME_BRIEF),
        STUDIO_VISION_MODEL=VISION,
    )
    site, context = await builder_in_project(studio)
    started = await run(studio, context, "godot", action="start")
    assert not started.failed, started.text
    await studio.workspace.write_image(site.id, "images/shot.png", picture(tmp_path))
    looked = await run(studio, context, "look_reference", file="images/shot.png")
    assert not looked.failed, looked.text
    assert looked.data["make"] == "game"
    first = await studio._ideas.add(title="Fox", name="a.png", data=picture(tmp_path))
    second = await studio._ideas.add(title="Fox", name="b.png", data=picture(tmp_path))
    notes = {
        (await run(studio, context, "look_reference", idea=idea.id)).data["note"]
        for idea in (first, second)
    }
    assert len(notes) == 2


@needs_ffmpeg
@pytest.mark.asyncio
async def test_a_mov_video_in_the_project_is_read(make_studio, tmp_path):
    studio, _ = make_studio(
        lambda system, prompt: LLMReply(text=GAME_BRIEF),
        STUDIO_VISION_MODEL=VISION,
    )
    site, context = await builder_in_project(studio)
    data = made(
        tmp_path,
        "clip.mov",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=320x240:rate=10",
        "-c:v",
        "mpeg4",
    )
    await studio.workspace.copy_library_bytes(site.id, "videos/clip.mov", data)
    looked = await run(studio, context, "look_reference", file="videos/clip.mov")
    assert not looked.failed, looked.text
    assert looked.data["frames"].endswith("-frames.jpg")


@pytest.mark.asyncio
async def test_looking_is_not_counted_as_writing():
    from free_claude_code.studio.agents import WRITE_TOOLS

    assert "look_reference" not in WRITE_TOOLS


def test_every_brief_ends_with_changes_that_make_it_ours():
    for make in reference_look.MAKES:
        system, _ = reference_look.brief_prompt(make, title="x", notes="", focus="")
        assert "MAKE IT OURS" in system and "not a copy" in system


@pytest.mark.asyncio
async def test_the_changer_gets_look_reference_once_and_keeps_notes_out_of_updates(
    make_studio, tmp_path
):
    from free_claude_code.studio.models import StudioFlag
    from free_claude_code.studio.presets import CHANGER_PROMPT, CHANGER_TOOLS
    from free_claude_code.studio.tools import ToolContext

    assert "look_reference" in CHANGER_TOOLS and "look_reference" in CHANGER_PROMPT
    studio, _ = make_studio(
        lambda system, prompt: LLMReply(text="SCREENS AND PARTS: a list."),
        STUDIO_VISION_MODEL=VISION,
    )
    changer = await studio._changer_agent()
    await studio._store.put(
        changer.model_copy(
            update={"tools": tuple(t for t in changer.tools if t != "look_reference")}
        )
    )
    await studio._store.delete(StudioFlag, "changer_look_reference_v1")
    assert "look_reference" in (await studio._changer_agent()).tools
    copy = await studio.create_site(name="FCC copy")
    monkey = pytest.MonkeyPatch()

    async def changer_copy():
        return copy

    monkey.setattr(studio, "_changer_copy", changer_copy)
    try:
        if not FFMPEG:
            pytest.skip("the look itself needs ffmpeg on PATH")
        await studio._ideas.add(title="Menu", name="m.png", data=picture(tmp_path))
        context = ToolContext(
            agent_id=changer.id, chat_id="c", site_id=copy.id, agent_role="agent"
        )
        looked = await run(studio, context, "look_reference", idea="Menu")
        assert not looked.failed, looked.text
        assert looked.data["make"] == "app" and "note" not in looked.data
        paths = {item.path for item in await studio.workspace.files(copy.id)}
        assert not any(path.startswith("reference-notes/") for path in paths)
    finally:
        monkey.undo()
