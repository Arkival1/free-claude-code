"""Every research run brings 3 web pages, 2 good Reddit threads, 2 transcribed videos."""

import json

import httpx
import pytest

from free_claude_code.core.web_tools import WebFetchResult
from free_claude_code.studio.platforms import (
    PlatformReader,
    caption_text,
    parse_youtube_results,
)
from free_claude_code.studio.research import (
    DeepResearch,
    ResearchMix,
    is_technical,
    relevance,
)
from free_claude_code.studio.search import StudioSearch

from .conftest import RecordingWebTools, tool_reply


def post(n: str, title: str, **extra: object) -> dict:
    return {
        "data": {
            "permalink": f"/r/gardening/comments/{n}/x/",
            "title": title,
            "subreddit": "gardening",
            "score": extra.get("score", 50),
            "num_comments": extra.get("comments", 20),
            "selftext": extra.get("text", ""),
            "over_18": extra.get("nsfw", False),
        }
    }


REDDIT_POSTS = [
    post("nsfw", "Tomato plants growing tips", nsfw=True),
    post("off", "My cat sleeps all day"),
    post("quiet", "Tomato growing question", score=1, comments=0),
    post("good1", "Best tips for growing tomato plants", score=900, comments=150),
    post("good2", "Growing tomatoes in pots: what worked", score=300, comments=80),
    post("good3", "Tomato plants growing tall", score=20, comments=5),
]


def thread(n: str) -> list[dict]:
    quiet = n == "quiet"
    return [
        {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": f"Thread {n} about growing tomato plants",
                            "subreddit": "gardening",
                            "selftext": "How do you keep tomato plants growing strong?",
                            "score": 1 if quiet else 200,
                            "num_comments": 0 if quiet else 30,
                        }
                    }
                ]
            }
        },
        {
            "data": {
                "children": []
                if quiet
                else [
                    {
                        "kind": "t1",
                        "data": {"body": "Water tomato plants deeply.", "score": 50},
                    },
                    {"kind": "t1", "data": {"body": "Stake them early.", "score": 9}},
                ]
            }
        },
    ]


def results_page(videos: list[tuple[str, str, str]]) -> str:
    renderers = [
        {
            "videoRenderer": {
                "videoId": video,
                "title": {"runs": [{"text": title}]},
                "ownerText": {"runs": [{"text": "GardenTV"}]},
                "lengthText": {"simpleText": length},
                "viewCountText": {"simpleText": "12,345 views"},
            }
        }
        for video, title, length in videos
    ]
    data = {"contents": {"sectionListRenderer": {"contents": renderers}}}
    return f"<script>var ytInitialData = {json.dumps(data)};</script>"


VIDEOS = [
    ("shortsvid01", "Tomato plants growing hack #shorts", "0:45"),
    ("nocaptions1", "Growing tomato plants from seed", "12:03"),
    ("withcaption", "How to grow tomato plants: full guide", "18:20"),
    ("unrelated01", "Fixing a bike chain", "5:00"),
    ("secondgood1", "Tomato plants growing mistakes", "1:02:10"),
]


def watch(video: str, captioned: bool) -> str:
    tracks = (
        '"captionTracks":[{"baseUrl":"https://www.youtube.com/api/timedtext?v='
        f'{video}&lang=en","languageCode":"en"}}]'
        if captioned
        else ""
    )
    return (
        f'<meta name="title" content="Video {video}">'
        f'<script>{{"captions":{{"playerCaptionsTracklistRenderer":{{{tracks}}}}}}}'
        "</script>"
    )


def server(seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if request.url.host == "api.tavily.com":
            query = json.loads(request.content)["query"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": f"Growing tomato plants guide {n}",
                            "url": f"https://garden{n}.example/{query.replace(' ', '-')}",
                            "content": "tomato plants growing tips",
                        }
                        for n in range(5)
                    ]
                },
            )
        if path == "/search.json":
            return httpx.Response(200, json={"data": {"children": REDDIT_POSTS}})
        if path.startswith("/r/gardening/comments/"):
            return httpx.Response(200, json=thread(path.split("/")[4]))
        if path == "/results":
            return httpx.Response(200, text=results_page(VIDEOS))
        if path == "/watch":
            video = request.url.params["v"]
            return httpx.Response(
                200, text=watch(video, video in {"withcaption", "secondgood1"})
            )
        if path == "/api/timedtext":
            return httpx.Response(
                200,
                json={"events": [{"segs": [{"utf8": "Plant tomato plants deep."}]}]},
            )
        if path.startswith("/youtubei/"):
            return httpx.Response(403)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def fetch(url: str) -> WebFetchResult:
    return WebFetchResult(
        url=url,
        title=f"Page {url}",
        media_type="text/html",
        data="Tomato plants keep growing when they get full sun and deep water.",
    )


def engine(seen: list[httpx.Request], **kwargs) -> DeepResearch:
    transport = server(seen)
    return DeepResearch(
        search=StudioSearch(
            provider="tavily",
            api_key="tvly-k",
            base_url="",
            fallback=RecordingWebTools(),
            transport=transport,
        ),
        reader=PlatformReader(transport=transport),
        fetch=fetch,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_research_brings_three_pages_two_threads_and_two_videos():
    seen: list[httpx.Request] = []

    report = await engine(seen, wanted=10).run("growing tomato plants")

    by = {
        name: [s for s in report.sources if s.platform == name]
        for name in ("web", "reddit", "youtube")
    }
    assert len(by["web"]) >= 3
    assert [s.url for s in by["reddit"]] == [
        "https://www.reddit.com/r/gardening/comments/good1/x/",
        "https://www.reddit.com/r/gardening/comments/good2/x/",
    ], (
        "on-topic threads with the most votes and replies; no NSFW, off-topic, or silent ones"
    )
    assert all("comments" in s.detail for s in by["reddit"])
    assert [s.url for s in by["youtube"]] == [
        "https://www.youtube.com/watch?v=withcaption",
        "https://www.youtube.com/watch?v=secondgood1",
    ], "only videos whose transcript was read; shorts and off-topic skipped"
    assert all(s.detail == "transcript read" for s in by["youtube"])
    assert "Plant tomato plants deep." in by["youtube"][0].excerpt
    assert [s.number for s in report.sources] == list(range(1, len(report.sources) + 1))
    assert not any(s.platform == "stackoverflow" for s in report.sources)

    rendered = report.render()
    for heading in ("## Web", "## Reddit", "## YouTube"):
        assert heading in rendered
    assert "https://www.youtube.com/watch?v=withcaption; transcript read" in rendered
    assert "give the user the links you used" in rendered
    assert not any("Found" in note for note in report.notes)
    videos_read = [r for r in seen if r.url.path == "/watch"]
    assert "shortsvid01" not in {r.url.params["v"] for r in videos_read}


@pytest.mark.asyncio
async def test_the_mix_can_be_changed_per_question():
    seen: list[httpx.Request] = []

    report = await engine(seen, wanted=5).run(
        "growing tomato plants", mix=ResearchMix(web=4, reddit=1, youtube=0)
    )

    platforms = [s.platform for s in report.sources]
    assert platforms.count("web") >= 4
    assert platforms.count("reddit") == 1
    assert "youtube" not in platforms
    assert not any(r.url.path in {"/results", "/watch"} for r in seen)


@pytest.mark.asyncio
async def test_too_few_good_threads_are_reported_not_padded():
    seen: list[httpx.Request] = []

    report = await engine(seen, mix=ResearchMix(reddit=5)).run("growing tomato plants")

    reddit = [s for s in report.sources if s.platform == "reddit"]
    assert len(reddit) == 3
    assert "Found 3 of 5 Reddit threads" in " ".join(report.notes)


@pytest.mark.asyncio
async def test_captions_come_from_the_player_api_when_the_watch_page_is_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/watch":
            return httpx.Response(200, text="<html>Before you continue</html>")
        if request.url.path == "/oembed":
            return httpx.Response(200, json={"title": "Grow tomatoes"})
        if request.url.path == "/youtubei/v1/player":
            assert json.loads(request.content)["videoId"] == "abcdefghijk"
            return httpx.Response(
                200,
                json={
                    "videoDetails": {"shortDescription": "All about tomatoes"},
                    "captions": {
                        "playerCaptionsTracklistRenderer": {
                            "captionTracks": [
                                {
                                    "baseUrl": "https://www.youtube.com/api/timedtext?v=abcdefghijk&fmt=srv3",
                                    "languageCode": "en",
                                }
                            ]
                        }
                    },
                },
            )
        if request.url.path == "/api/timedtext":
            assert request.url.params["fmt"] == "json3"
            return httpx.Response(
                200,
                text='<transcript><text start="0">Dig &amp; plant.</text></transcript>',
            )
        return httpx.Response(404)

    reader = PlatformReader(transport=httpx.MockTransport(handler))
    video = await reader.youtube_video("https://youtu.be/abcdefghijk")

    assert video.transcript is True
    assert "Dig & plant." in video.text
    assert "All about tomatoes" in video.text
    assert video.note == ""


def test_youtube_results_and_captions_are_parsed():
    videos = parse_youtube_results(results_page(VIDEOS), limit=3)

    assert [v.video_id for v in videos] == ["shortsvid01", "nocaptions1", "withcaption"]
    assert videos[0].seconds == 45 and videos[1].seconds == 723
    assert videos[2].views == 12345 and videos[2].channel == "GardenTV"
    assert parse_youtube_results("<html></html>") == ()
    assert caption_text('{"events":[{"segs":[{"utf8":"a "},{"utf8":"b"}]}]}') == "a b"


def test_questions_are_sorted_into_coding_and_everyday():
    assert is_technical("fix this python error")
    assert is_technical("how to learn css grid")
    assert not is_technical("growing tomato plants")
    assert relevance("Tide tables", ["tides"]) == 1.0
    assert relevance("nothing here", ["tides", "moon"]) == 0.0


@pytest.mark.asyncio
async def test_agents_can_ask_for_a_different_mix(make_studio):
    studio, _ = make_studio(
        [
            tool_reply(
                "research",
                {"question": "tides", "reddit": 0, "youtube": "0", "web": 99},
            ),
            "done",
        ],
        STUDIO_RESEARCH_REDDIT=4,
    )
    toolbox = studio._toolbox()
    assert toolbox._research_mix.reddit == 4
    agent = await studio.create_agent(name="Scout", role="researcher")
    chat = await studio.create_chat(agent_id=agent.id)

    await studio.send(chat.id, "research tides")

    tool = next(m for m in await studio.transcript(chat.id) if m.role == "tool")
    platforms = {source["platform"] for source in tool.data["sources"]}
    assert "reddit" not in platforms and "youtube" not in platforms
