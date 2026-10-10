"""The ideas board: the user's references (notes, photos, videos, links) that
the agents search before they design or build."""

import httpx
import pytest

from free_claude_code.studio.agents import ideas_prompt
from free_claude_code.studio.ideas import IdeaError, clean_tags, video_info
from free_claude_code.studio.llm import ToolCall
from free_claude_code.studio.tools import ToolContext
from tests.api.support import create_test_app
from tests.studio.test_business_photos import jpeg

HERO = jpeg(1600, 900)
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


def test_videos_and_tags_are_read_plainly():
    assert video_info(MP4) == (".mp4", "video/mp4")
    assert video_info(WEBM) == (".webm", "video/webm")
    assert video_info(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 8)[0] == ".mov"
    with pytest.raises(IdeaError, match="MP4, MOV, or WebM"):
        video_info(b"%PDF-1.7")
    assert clean_tags("UI, Website , ui,  Colours!") == ("ui", "website", "colours")


@pytest.mark.asyncio
async def test_the_board_keeps_notes_links_photos_and_videos(make_studio):
    studio, _ = make_studio([])
    board = studio.ideas
    note = await board.add(
        title="Warm and calm",
        text="Cream background, deep brown text, lots of space.",
        tags="colours, website",
        project="Rosie's Bakery",
    )
    link = await board.add(
        text="I like how the menu cards look.",
        url="https://example.com/bakery",
        tags=["ui"],
    )
    photo = await board.add(
        title="Hero I like", text="Big photo, short headline", data=HERO, name="a.jpg"
    )
    clip = await board.add(name="scroll-demo.mp4", text="Smooth scrolling", data=MP4)

    assert [note.kind, link.kind, photo.kind, clip.kind] == [
        "note",
        "link",
        "photo",
        "video",
    ]
    assert link.title == "I like how the menu cards look."
    assert (photo.width, photo.height) == (1600, 900)
    assert clip.title == "scroll demo" and clip.content_type == "video/mp4"
    assert board.path(photo).read_bytes() == HERO

    assert [i.id for i in await board.ideas("brown")] == [note.id]
    assert [i.id for i in await board.ideas(tag="ui")] == [link.id]
    assert [i.id for i in await board.ideas(kind="video")] == [clip.id]
    assert [i.id for i in await board.ideas(project="rosie")] == [note.id]

    for bad, message in (
        ({"title": "x"}, "Write the idea"),
        ({"title": "x", "url": "ftp://nope"}, "http"),
        ({"title": "x", "data": b"%PDF-1.7 nope"}, "MP4, MOV, or WebM"),
    ):
        with pytest.raises(IdeaError, match=message):
            await board.add(**bad)

    edited = await board.update(note.id, {"text": "Cream and brown.", "tags": "calm"})
    assert edited.text == "Cream and brown." and edited.tags == ("calm",)
    assert await board.delete(photo.id)
    assert not board.path(photo).exists()


@pytest.mark.asyncio
async def test_agents_search_read_and_use_the_board(make_studio):
    studio, model = make_studio(["Done."])
    builder = next(a for a in await studio.ensure_defaults() if a.name == "Builder")
    assert "ideas" in builder.tools
    site = await studio.create_site(name="Bakery")
    context = ToolContext(
        agent_id=builder.id,
        chat_id="cht_x",
        site_id=site.id,
        agent_name="Builder",
        agent_role="builder",
    )
    toolbox = studio._toolbox()

    async def run(**arguments):
        return await toolbox.run(
            ToolCall(id="t", name="ideas", arguments=arguments), context
        )

    empty = await run(action="search")
    assert "hasn't added anything" in empty.text

    hero = await studio.ideas.add(
        title="Hero I like", text="Big photo, short headline", data=HERO, tags="ui"
    )
    await studio.ideas.add(title="Calm colours", text="Cream and deep brown.")
    found = await run(action="search", query="headline")
    assert "[photo] Hero I like" in found.text
    assert "the user says: Big photo, short headline" in found.text
    assert "Calm colours" not in found.text
    full = await run(action="read", idea="hero i like")
    assert "1600x900 photo" in full.text and "action use" in full.text
    used = await run(action="use", idea=hero.id)
    assert used.data["path"] == "images/hero-i-like.jpg"
    assert await studio.workspace.read_bytes(site.id, "images/hero-i-like.jpg") == HERO
    clip = await studio.ideas.add(name="demo.mp4", text="feel", data=MP4)
    refused = await run(action="use", idea=clip.id)
    assert refused.failed and "not a photo" in refused.text

    # An agent with the tool hears about the board before it starts.
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)
    await studio.send(chat.id, "Make the bakery site")
    system = str(model.calls[-1]["system"])
    assert ideas_prompt(["demo", "Calm colours", "Hero I like"]) in system


@pytest.mark.asyncio
async def test_the_board_through_the_app(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        note = await client.post(
            "/studio/api/ideas",
            json={"text": "Rounded cards", "url": "https://example.com", "tags": "ui"},
        )
        assert note.status_code == 200, note.text
        assert note.json()["kind"] == "link"
        photo = await client.post(
            "/studio/api/ideas/upload",
            params={"name": "look.jpg", "title": "The look", "tags": "ui, hero"},
            content=HERO,
        )
        assert photo.status_code == 200, photo.text
        added = photo.json()
        served = await client.get(added["file_url"])
        assert served.status_code == 200 and served.content == HERO
        listed = (await client.get("/studio/api/ideas", params={"tag": "hero"})).json()
        assert [i["id"] for i in listed["ideas"]] == [added["id"]]
        assert listed["tags"] == ["hero", "ui"]
        bad = await client.post(
            "/studio/api/ideas/upload", params={"name": "x.pdf"}, content=b"%PDF"
        )
        assert bad.status_code == 400
        changed = await client.patch(
            f"/studio/api/ideas/{added['id']}", json={"text": "Exactly this feel."}
        )
        assert changed.json()["text"] == "Exactly this feel."
        gone = await client.delete(f"/studio/api/ideas/{added['id']}")
        assert gone.json() == {"deleted": True}
        assert (await client.get(added["file_url"])).status_code == 404
