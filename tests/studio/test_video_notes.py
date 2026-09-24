"""Videos become notes the agents can use, keep in memory, and look back at."""

import json

import httpx
import pytest

from free_claude_code.studio import StudioError, StudioService
from free_claude_code.studio.llm import LLMReply, StudioLLMError, StudioModelRouter
from free_claude_code.studio.memory import SHARED_MEMORY_ID
from free_claude_code.studio.models import MemoryEntry, VideoNote
from free_claude_code.studio.platforms import caption_segments
from free_claude_code.studio.videos import parse_digest, passages, plain_digest
from tests.api.support import create_test_app

from .conftest import ScriptedLLM, tool_reply

VIDEO = "tomatoVid01"
LINK = f"https://youtu.be/{VIDEO}"
LINES = [
    (0, "Welcome back to the garden."),
    (20, "Today we plant tomatoes in pots."),
    (50, "Water tomatoes deeply twice a week."),
    (95, "Prune the suckers so the plant grows tall."),
    (140, "Use a stake early so it does not fall over."),
]
DIGEST = """SUMMARY: How to grow tomatoes in pots, from planting to pruning.
KEY POINTS:
- Water deeply twice a week
- Prune suckers
STEPS:
1. Plant in a large pot
2. Stake early
NAMES:
- Tomato cage
WATCH OUT:
- Shallow watering weakens roots
"""


def youtube(seen: list[httpx.Request], *, captions: bool = True):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/watch":
            tracks = (
                '"captionTracks":[{"baseUrl":"https://www.youtube.com/api/timedtext'
                f'?v={request.url.params["v"]}&lang=en","languageCode":"en"}}]'
                if captions
                else ""
            )
            return httpx.Response(
                200,
                text=(
                    '<meta name="title" content="Grow tomatoes in pots">'
                    f'<script>{{"captions":{{"playerCaptionsTracklistRenderer":{{{tracks}}}}}}}'
                    "</script>"
                ),
            )
        if path == "/api/timedtext":
            return httpx.Response(
                200,
                json={
                    "events": [
                        {"tStartMs": second * 1000, "segs": [{"utf8": text}]}
                        for second, text in LINES
                    ]
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def studio_with(tmp_path, store, web_tools, studio_settings, replies, **settings):
    seen: list[httpx.Request] = []
    model = ScriptedLLM(replies)
    values = studio_settings(**settings)
    studio = StudioService(
        store=store,
        web_tools=web_tools,
        settings_provider=lambda: values,
        models_dir=tmp_path / "models",
        sites_dir=tmp_path / "sites",
        router=StudioModelRouter(proxy=model, local=model),
        search_transport=youtube(seen),
        voice_transport=youtube(seen),
    )
    return studio, model, seen


def test_captions_keep_their_times():
    json3 = json.dumps(
        {"events": [{"tStartMs": 61500, "segs": [{"utf8": "Hi "}, {"utf8": "there"}]}]}
    )
    assert caption_segments(json3) == ((61, "Hi there"),)
    xml = '<transcript><text start="3.2" dur="1">A &amp; B</text></transcript>'
    assert caption_segments(xml) == ((3, "A & B"),)


def test_notes_are_read_back_into_sections():
    digest = parse_digest(DIGEST)

    assert digest.summary.startswith("How to grow tomatoes")
    assert digest.points == ("Water deeply twice a week", "Prune suckers")
    assert digest.steps == ("Plant in a large pot", "Stake early")
    assert digest.names == ("Tomato cage",)
    assert digest.cautions == ("Shallow watering weakens roots",)
    fallback = plain_digest(
        "Tomatoes", " ".join(text for _, text in LINES) * 3, "Grow tomatoes"
    )
    assert fallback.summary and fallback.points


def test_the_transcript_parts_about_a_question_come_with_their_time():
    note = VideoNote(
        video_id=VIDEO,
        url=f"https://www.youtube.com/watch?v={VIDEO}",
        title="T",
        segments=tuple(LINES),
    )

    found = passages(note, "how often to water")

    assert found[0][0] == 50
    assert "Water tomatoes deeply" in found[0][1]


@pytest.mark.asyncio
async def test_a_video_the_user_gives_becomes_notes_in_memory(
    tmp_path, store, web_tools, studio_settings
):
    studio, model, _ = studio_with(
        tmp_path, store, web_tools, studio_settings, [DIGEST]
    )
    await studio.ensure_defaults()

    note = await studio.study_video(LINK, focus="watering")

    assert note.title == "Grow tomatoes in pots"
    assert note.points == ("Water deeply twice a week", "Prune suckers")
    assert note.segments[2] == (50, "Water tomatoes deeply twice a week.")
    assert note.source == "user" and note.focus == "watering"
    assert "The team wants to know about: watering" in str(model.calls[0]["prompt"])
    memory = await studio.store.require(MemoryEntry, note.memory_id)
    assert memory.agent_id == SHARED_MEMORY_ID
    assert {"video", "youtube"} <= set(memory.tags)
    assert note.url in memory.text and note.id in memory.text
    assert "Water deeply twice a week" in memory.text

    again = await studio.study_video(LINK, focus="watering")
    assert again.id == note.id and len(model.calls) == 1, "studied once"

    assert await studio.delete_video_note(note.id) is True
    assert await studio.store.get(MemoryEntry, note.memory_id) is None


@pytest.mark.asyncio
async def test_agents_look_back_at_a_video_through_its_notes(
    tmp_path, store, web_tools, studio_settings
):
    studio, _, _ = studio_with(
        tmp_path,
        store,
        web_tools,
        studio_settings,
        [
            tool_reply("study_video", {"url": LINK}),
            DIGEST,
            tool_reply("video_notes", {"query": "how often to water"}, call_id="c2"),
            "Water deeply twice a week [0:50].",
        ],
    )
    await studio.ensure_defaults()
    researcher = await studio.agent_by_name("Researcher")
    assert researcher is not None
    assert {"study_video", "video_notes"} <= set(researcher.tools)
    builder = await studio.agent_by_name("Builder")
    assert builder is not None and "video_notes" in builder.tools
    chat = await studio.create_chat(agent_id=researcher.id)

    await studio.send(chat.id, f"study {LINK} then tell me how often to water")

    tools = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert tools[0].author == "study_video"
    assert tools[0].text.startswith("Video notes: Grow tomatoes in pots")
    assert "Steps:\n1. Plant in a large pot" in tools[0].text
    looked = tools[1].text
    assert "Transcript parts about 'how often to water':" in looked
    assert f"[0:50] https://www.youtube.com/watch?v={VIDEO}&t=50s" in looked


@pytest.mark.asyncio
async def test_research_turns_the_videos_it_reads_into_notes(
    tmp_path, store, web_tools, studio_settings
):
    def model_down(system: str, prompt: str):
        raise StudioLLMError("LM Studio is not running")

    studio, model, seen = studio_with(
        tmp_path, store, web_tools, studio_settings, model_down
    )
    page = await studio._reader().youtube_video(LINK)
    assert page.transcript and page.segments
    fetched = len(seen)

    studio._study_later(page)
    studio._study_later(page)
    await studio.wait_for_background()
    notes = await studio.video_notes()

    assert [note.source for note in notes] == ["research"]
    assert notes[0].summary, "with the model down, plain notes are kept"
    assert len(seen) == fetched, "the transcript research read is reused"
    assert len(model.calls) <= 1, "the same video is studied once"


@pytest.mark.asyncio
async def test_a_video_without_captions_cannot_be_studied(
    tmp_path, store, web_tools, studio_settings
):
    model = ScriptedLLM([DIGEST])
    values = studio_settings()
    studio = StudioService(
        store=store,
        web_tools=web_tools,
        settings_provider=lambda: values,
        models_dir=tmp_path / "models",
        sites_dir=tmp_path / "sites",
        router=StudioModelRouter(proxy=model, local=model),
        search_transport=youtube([], captions=False),
    )

    with pytest.raises(StudioError, match="captions"):
        await studio.study_video(LINK)
    with pytest.raises(StudioError, match="not a YouTube"):
        await studio.study_video("https://example.com/video")
    assert model.calls == []


@pytest.mark.asyncio
async def test_video_notes_through_the_routes(
    tmp_path, store, web_tools, studio_settings
):
    studio, _, _ = studio_with(
        tmp_path, store, web_tools, studio_settings, [LLMReply(text=DIGEST)]
    )
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            made = await client.post("/studio/api/videos", json={"url": LINK})
            assert made.status_code == 200
            body = made.json()
            assert body["notes"].startswith("Video notes: Grow tomatoes in pots")
            assert body["transcript"][2] == {
                "at": "0:50",
                "seconds": 50,
                "text": "Water tomatoes deeply twice a week.",
            }
            assert body["length"] == "2:20" and body["lines"] == 5
            listed = (
                await client.get("/studio/api/videos", params={"q": "prune"})
            ).json()
            assert [video["id"] for video in listed["videos"]] == [body["id"]]
            assert "segments" not in listed["videos"][0]
            bad = await client.post(
                "/studio/api/videos", json={"url": "https://x.test"}
            )
            assert bad.status_code == 400
            gone = await client.delete(f"/studio/api/videos/{body['id']}")
            assert gone.json() == {"deleted": True}
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
