"""The desktop browser agents drive, and watching videos on this PC."""

from pathlib import Path

import httpx
import pytest

from free_claude_code.studio import StudioError, StudioService
from free_claude_code.studio.desk import (
    PART_CHARS,
    DeskBrowser,
    DeskError,
    PageShot,
    is_private_host,
    render,
    safe_button,
)
from free_claude_code.studio.llm import StudioModelRouter
from free_claude_code.studio.models import VideoNote
from free_claude_code.studio.presets import RESEARCHER_TOOLS
from free_claude_code.studio.tools import MAIN_TOOL_NAMES, TOOL_SPEC_BY_NAME
from free_claude_code.studio.video_ears import (
    VideoEars,
    VideoEarsError,
    file_key,
    join_lines,
    local_media,
)
from tests.api.support import create_test_app

from .conftest import ScriptedLLM, tool_reply

DIGEST = """SUMMARY: How to bake sourdough at home.
KEY POINTS:
- Feed the starter the night before
STEPS:
1. Mix and rest
"""
HEARD = [
    (0.0, "Today we bake sourdough."),
    (6.5, "Feed the starter the night before,"),
    (14.0, "then mix the dough and let it rest."),
]


class FakePage:
    """A stand-in browser tab: pages by address, with links and a video."""

    def __init__(self, pages: dict[str, PageShot]) -> None:
        self.pages = pages
        self.history: list[str] = []
        self.scrolled: list[bool] = []
        self.video_calls: list[str] = []
        self.pressed: list[int] = []
        self.labels = ["Accept all", "Buy now", "Show more", "Sign in"]
        self.closed = False

    async def goto(self, url: str) -> None:
        self.history.append(url)

    async def back(self) -> bool:
        if len(self.history) < 2:
            return False
        self.history.pop()
        return True

    async def snapshot(self) -> PageShot:
        url = self.history[-1] if self.history else "about:blank"
        return self.pages.get(url, PageShot(url=url, title="", text=""))

    async def scroll(self, down: bool) -> None:
        self.scrolled.append(down)

    async def video(self, action: str) -> bool:
        page = await self.snapshot()
        if page.video is None:
            return False
        self.video_calls.append(action)
        return True

    async def buttons(self) -> list[tuple[int, str]]:
        return list(enumerate(self.labels))

    async def press(self, index: int) -> bool:
        self.pressed.append(index)
        return True

    async def start_recording(self, rate: float) -> dict[str, object]:
        page = await self.snapshot()
        if page.video is None:
            return {"error": "This page has no video."}
        self.video_calls.append(f"record x{rate:g}")
        return {"length": 9, "title": page.title}

    async def recording_state(self) -> dict[str, object] | None:
        return {"at": 9, "ended": True, "paused": False}

    async def finish_recording(self) -> bytes:
        return b"webm sound"

    async def close(self) -> None:
        self.closed = True


SEARCH = "https://duckduckgo.com/?q=sourdough+starter"
ARTICLE = "https://bread.example/starter"
WATCH = "https://www.youtube.com/watch?v=bakeVideo01"


def pages() -> dict[str, PageShot]:
    return {
        SEARCH: PageShot(
            url=SEARCH,
            title="sourdough starter at DuckDuckGo",
            text="Results\nHow to feed a sourdough starter",
            links=(
                ("How to feed a starter", ARTICLE),
                ("Sourdough video", WATCH),
            ),
        ),
        ARTICLE: PageShot(
            url=ARTICLE,
            title="Feeding a starter",
            text="Intro. " + "Flour and water. " * 700,
            links=(("Home", "https://bread.example/"),),
        ),
        WATCH: PageShot(
            url=WATCH,
            title="Bake sourdough - YouTube",
            text="Bake sourdough",
            video={"playing": False, "at": 0, "length": 600},
        ),
        "http://192.168.1.1/": PageShot(
            url="http://192.168.1.1/", title="Router", text="admin"
        ),
    }


def desk_with(page: FakePage, **options: bool) -> DeskBrowser:
    async def opener() -> FakePage:
        return page

    return DeskBrowser(opener, **options)


def test_harmless_buttons_only():
    assert safe_button("Accept all")
    assert safe_button("Show more")
    assert safe_button("Next")
    assert not safe_button("Buy now")
    assert not safe_button("Sign in")
    assert not safe_button("Subscribe")
    assert not safe_button("Accept and pay")
    assert not safe_button("Delete account")


def test_links_to_this_pc_and_the_home_network_are_private():
    assert is_private_host("http://localhost:8082/studio")
    assert is_private_host("http://192.168.1.1/")
    assert is_private_host("http://printer.local/")
    assert not is_private_host("https://www.youtube.com/watch?v=x")


def test_a_page_reads_in_parts_with_numbered_links():
    shot = PageShot(
        url="https://a.example/",
        title="A",
        text="x" * (PART_CHARS + 10),
        links=tuple((f"Link {n}", f"https://a.example/{n}") for n in range(40)),
    )
    first = render(shot)
    assert "part 1 of 2" in first and "[More: read with part 2" in first
    assert "1. Link 0 — https://a.example/0" in first
    assert "…and 10 more" in first
    filtered = render(shot, query="link 39")
    assert "40. Link 39" in filtered and "1. Link 0" not in filtered


@pytest.mark.asyncio
async def test_agents_search_read_click_scroll_and_go_back():
    page = FakePage(pages())
    desk = desk_with(page)

    found = await desk.search("sourdough starter", by="Researcher")
    assert found.url == SEARCH and desk.open
    clicked = await desk.follow(1, by="Researcher")
    assert clicked.title == "Feeding a starter"
    scrolled = await desk.scroll(by="Researcher")
    assert page.scrolled == [True] and desk.state.part == 2
    assert "part 2 of" in render(scrolled, part=desk.state.part)
    back = await desk.back()
    assert back.url == SEARCH
    with pytest.raises(DeskError, match="no link 9"):
        await desk.follow(9)
    assert desk.state.used_by == ""
    await desk.close()
    assert page.closed and not desk.open


@pytest.mark.asyncio
async def test_agents_cannot_open_this_pc_or_press_risky_buttons():
    page = FakePage(pages())
    desk = desk_with(page)

    with pytest.raises(DeskError, match="home network"):
        await desk.go("http://192.168.1.1/")
    with pytest.raises(DeskError, match="http and https"):
        await desk.go("file:///C:/Users/me/secret.txt")
    assert page.history == []

    await desk.go("bread.example/starter")
    assert page.history == [ARTICLE], "https:// is added"
    assert [label for _, label in await desk.buttons()] == ["Accept all", "Show more"]
    await desk.press("show more")
    assert page.pressed == [2]
    with pytest.raises(DeskError, match="may not press"):
        await desk.press("Buy now")
    with pytest.raises(DeskError, match="no video"):
        await desk.video("play")


@pytest.mark.asyncio
async def test_a_page_that_leads_to_the_home_network_is_closed():
    page = FakePage(pages())
    desk = desk_with(page)
    await desk.go(ARTICLE)
    page.history.append("http://192.168.1.1/")  # a redirect

    with pytest.raises(DeskError, match="closed it"):
        await desk.look()
    assert page.history[-1] == "about:blank"


def test_only_video_files_in_the_users_folders(tmp_path):
    home = tmp_path / "home"
    (home / "Videos").mkdir(parents=True)
    clip = home / "Videos" / "garden tour.mp4"
    clip.write_bytes(b"video")
    (home / "notes.txt").write_text("private")
    outside = tmp_path / "other.mp4"
    outside.write_bytes(b"video")

    assert local_media(str(clip), home) == clip.resolve()
    assert local_media(f'"{clip}"', home) == clip.resolve(), "Copy as path quotes"
    assert local_media(clip.as_uri(), home) == clip.resolve()
    assert local_media("https://youtu.be/abc", home) is None
    assert local_media("sourdough tips", home) is None
    with pytest.raises(VideoEarsError, match="not a video"):
        local_media(str(home / "notes.txt"), home)
    with pytest.raises(VideoEarsError, match="your own folders"):
        local_media(str(outside), home)
    with pytest.raises(VideoEarsError, match="no video at"):
        local_media(str(home / "Videos" / "missing.mp4"), home)


def test_whisper_pieces_become_caption_lines():
    lines = join_lines(
        [
            (0.0, "Hello there."),
            (1.0, "Short"),
            (2.0, "bits"),
            (3.0, "join up."),
            (40.0, " "),
        ]
    )
    assert lines == ((0, "Hello there."), (1, "Short bits join up."))


@pytest.mark.asyncio
async def test_web_videos_are_fetched_then_heard_and_the_sound_is_deleted(tmp_path):
    folders: list[Path] = []

    def fetch(url: str, folder: Path, minutes: int) -> tuple[Path, str]:
        folders.append(folder)
        sound = folder / "sound.m4a"
        sound.write_bytes(b"sound")
        return sound, "Bake sourdough"

    def hear(path: Path, minutes: int):
        assert path.read_bytes() == b"sound" and minutes == 30
        return HEARD, 20.0

    ears = VideoEars(
        hear=hear, work=tmp_path / "work", home=tmp_path, max_minutes=30, fetch=fetch
    )
    heard = await ears.listen("https://vimeo.com/123")

    assert heard.title == "Bake sourdough" and heard.seconds == 20
    assert heard.segments[0] == (0, "Today we bake sourdough.")
    assert not folders[0].exists(), "the downloaded sound is not kept"
    with pytest.raises(VideoEarsError, match="home network"):
        await ears.listen("http://10.0.0.5/video.mp4")


def studio_for(tmp_path, store, web_tools, studio_settings, replies, page, **settings):
    model = ScriptedLLM(replies)
    values = studio_settings(**settings)
    home = tmp_path / "home"
    (home / "Videos").mkdir(parents=True, exist_ok=True)

    async def opener() -> FakePage:
        return page

    def hear(path: Path, minutes: int):
        return HEARD, 20.0

    def fetch(url: str, folder: Path, minutes: int) -> tuple[Path, str]:
        sound = folder / "sound.m4a"
        sound.write_bytes(b"sound")
        return sound, "Bake sourdough"

    def no_captions(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/watch":
            return httpx.Response(
                200, text='<meta name="title" content="Bake sourdough">'
            )
        return httpx.Response(404)

    studio = StudioService(
        store=store,
        web_tools=web_tools,
        settings_provider=lambda: values,
        models_dir=tmp_path / "models",
        sites_dir=tmp_path / "sites",
        router=StudioModelRouter(proxy=model, local=model),
        search_transport=httpx.MockTransport(no_captions),
        desk_opener=opener,
        media_home=home,
        hear=hear,
        fetch=fetch,
    )
    return studio, model, home


def test_jarvis_and_the_researcher_get_the_desktop_browser():
    assert "desktop_browser" in RESEARCHER_TOOLS
    assert "desktop_browser" in MAIN_TOOL_NAMES
    spec = TOOL_SPEC_BY_NAME["desktop_browser"]
    assert "never type, sign in, or buy" in spec.description
    properties = TOOL_SPEC_BY_NAME["study_video"].parameters["properties"]
    assert isinstance(properties, dict) and "show" in properties


@pytest.mark.asyncio
async def test_the_researcher_browses_and_watches_a_video_on_the_desktop(
    tmp_path, store, web_tools, studio_settings
):
    page = FakePage(pages())
    studio, _, _ = studio_for(
        tmp_path,
        store,
        web_tools,
        studio_settings,
        [
            tool_reply(
                "desktop_browser", {"action": "search", "query": "sourdough starter"}
            ),
            tool_reply(
                "desktop_browser", {"action": "click", "number": 2}, call_id="c2"
            ),
            tool_reply(
                "desktop_browser", {"action": "watch", "focus": "feeding"}, call_id="c3"
            ),
            DIGEST,
            "Feed the starter the night before.",
        ],
        page,
    )
    await studio.ensure_defaults()
    researcher = await studio.agent_by_name("Researcher")
    assert researcher is not None and "desktop_browser" in researcher.tools
    chat = await studio.create_chat(agent_id=researcher.id)

    await studio.send(chat.id, "find a sourdough video on my screen and watch it")

    tools = [m for m in await studio.transcript(chat.id) if m.role == "tool"]
    assert [m.author for m in tools] == ["desktop_browser"] * 3
    assert "1. How to feed a starter — https://bread.example/starter" in tools[0].text
    assert "Video on this page: paused" in tools[1].text
    assert tools[2].text.startswith("Playing it in the desktop browser.")
    assert "Video notes: Bake sourdough" in tools[2].text
    assert page.video_calls == ["play"]
    note = (await studio.video_notes())[0]
    assert note.video_id == "bakeVideo01", "heard on this PC: no captions"
    assert note.segments[1] == (
        6,
        "Feed the starter the night before, then mix the dough and let it rest.",
    )
    assert studio.desk_status()["used_by"] == "Researcher"
    await studio.shutdown()
    assert page.closed


@pytest.mark.asyncio
async def test_a_video_file_on_this_pc_becomes_notes(
    tmp_path, store, web_tools, studio_settings
):
    page = FakePage(pages())
    studio, _, home = studio_for(
        tmp_path, store, web_tools, studio_settings, [DIGEST], page
    )
    clip = home / "Videos" / "bake_day.mp4"
    clip.write_bytes(b"video")

    note = await studio.study_video(f'"{clip}"', show=True)

    assert note.title == "bake day" and note.url == str(clip.resolve())
    assert note.video_id == file_key(clip.resolve())
    assert page.history == [clip.resolve().as_uri()], "played in the window"
    again = await studio.study_video(str(clip))
    assert again.id == note.id
    assert await studio.store.get(VideoNote, note.id) is not None
    with pytest.raises(StudioError, match="your own folders"):
        await studio.study_video(str(tmp_path / "elsewhere.mp4"))
    await studio.shutdown()


@pytest.mark.asyncio
async def test_server_agents_cannot_watch_files_on_this_pc(
    tmp_path, store, web_tools, studio_settings
):
    page = FakePage(pages())
    studio, _, home = studio_for(
        tmp_path,
        store,
        web_tools,
        studio_settings,
        [],
        page,
        STUDIO_PRIVATE_MEMORY=True,
    )
    clip = home / "Videos" / "family.mp4"
    clip.write_bytes(b"video")
    from free_claude_code.studio.llm import ToolCall
    from free_claude_code.studio.tools import ToolContext

    outcome = await studio._toolbox().run(
        ToolCall(id="c1", name="study_video", arguments={"url": str(clip)}),
        ToolContext(agent_id="a1", chat_id="c1", memory_owner="server:a1"),
    )
    assert (
        outcome.failed
        and "only watched by agents that think on this PC" in outcome.text
    )
    await studio.shutdown()


@pytest.mark.asyncio
async def test_the_desktop_browser_through_the_routes(
    tmp_path, store, web_tools, studio_settings
):
    page = FakePage(pages())
    studio, _, _ = studio_for(tmp_path, store, web_tools, studio_settings, [], page)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            status = (await client.get("/studio/api/desk")).json()
            assert status["installed"] and not status["open"]
            opened = await client.post("/studio/api/desk/open", json={"url": ARTICLE})
            assert opened.json()["title"] == "Feeding a starter"
            assert opened.json()["used_by"] == "You"
            refused = await client.post(
                "/studio/api/desk/open", json={"url": "http://192.168.1.1/"}
            )
            assert refused.status_code == 400
            played = await client.post("/studio/api/desk/play", json={"url": WATCH})
            assert played.status_code == 200 and page.video_calls == ["play"]
            closed = (await client.post("/studio/api/desk/close")).json()
            assert not closed["open"] and page.closed
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_a_video_that_cannot_be_downloaded_is_recorded_in_the_window(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("free_claude_code.studio.desk.RECORD_POLL", 0)
    page = FakePage(pages())
    desk = desk_with(page)

    def blocked(url: str, folder: Path, minutes: int) -> tuple[Path, str]:
        raise VideoEarsError("Sign in to confirm you're not a bot")

    def hear(path: Path, minutes: int):
        assert path.read_bytes() == b"webm sound"
        return [(0.0, "Today we bake sourdough."), (5.0, "Feed the starter.")], 9.0

    async def record(url: str, folder: Path, minutes: int):
        return await desk.record_sound(url, folder, max_minutes=minutes)

    ears = VideoEars(
        hear=hear, work=tmp_path / "work", home=tmp_path, fetch=blocked, record=record
    )
    heard = await ears.listen(WATCH)

    assert page.video_calls == ["record x2"]
    assert heard.title == "Bake sourdough - YouTube"
    assert heard.segments == (
        (0, "Today we bake sourdough."),
        (10, "Feed the starter."),
    ), "played at double speed, the times are put back on the video's clock"
    assert heard.seconds == 18
    with pytest.raises(DeskError, match="no video"):
        await desk.record_sound(ARTICLE, tmp_path / "x", max_minutes=5)
