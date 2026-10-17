"""Files people hand Studio, simple agent deletion, and the weather tool."""

import io
import json
import struct
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from free_claude_code.studio import service as service_module
from free_claude_code.studio.file_text import MAX_TEXT, MAX_UPLOAD, read_file_text
from free_claude_code.studio.gguf_info import read_gguf_info
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.model_inspect import (
    best_for,
    file_advice,
    identify,
    model_report,
)
from free_claude_code.studio.models import AgentRun, Chat, MemoryEntry, Message
from free_claude_code.studio.weather import WeatherError, forecast, weather_request
from tests.api.support import create_test_app

from .test_model_control import fake_gguf

TOOLS_TEMPLATE = "{% if tools %}{{ tools | tojson }}{% endif %}<tool_call>"
THINKING_TEMPLATE = "{% if enable_thinking %}<think>{% endif %}"


def plain(value: object) -> Any:
    """JSON data as plain Python, so tests can index into it."""
    return json.loads(json.dumps(value))


def gguf_bytes(tmp_path: Path, name: str = "m.gguf", **options) -> bytes:
    return fake_gguf(tmp_path / "src" / name, **options).read_bytes()


def office(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for path, body in members.items():
            bundle.writestr(path, body)
    return buffer.getvalue()


def simple_pdf(text: str) -> bytes:
    """A small valid PDF with one line of text on one page."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


# ------------------------------------------------------------ what a file is


def test_a_files_first_bytes_say_what_it_is():
    assert identify(b"GGUF\x03\x00\x00\x00", "x.bin") == ("gguf", "GGUF model")
    assert identify(b"%PDF-1.7", "a.pdf")[0] == "pdf"
    assert identify(b"\x89PNG\r\n\x1a\n", "a.png") == ("image", "PNG image")
    assert identify(b"RIFF\0\0\0\0WEBPVP8 ", "a.webp") == ("image", "WebP image")
    assert identify(b"PK\x03\x04", "notes.docx") == ("document", "Word document")
    assert identify(b"PK\x03\x04", "model.pth") == ("pytorch", "PyTorch weights")
    assert identify(b"PK\x03\x04", "stuff.zip") == ("zip", "ZIP archive")
    assert identify(b"MZ\x90\x00", "setup.exe") == ("program", "Windows program")
    header = struct.pack("<Q", 120) + b'{"__metadata__"'
    assert identify(header, "model.safetensors")[0] == "safetensors"
    assert identify(b"print('hi')\n", "a.py") == ("text", "text file")
    assert identify(b"\xff\xfe\x00\xd8", "blob")[0] == "unknown"


def test_files_that_are_not_models_say_what_to_do_instead():
    raw = file_advice(
        "safetensors", "safetensors model weights", "Qwen3-8B.safetensors"
    )
    assert "Qwen3-8B GGUF" in raw and "Q4_K_M" in raw
    assert "Attach it in a chat" in file_advice("pdf", "PDF document", "a.pdf")
    assert "unzip" in file_advice("zip", "ZIP archive", "m.zip")
    assert "not a model file" in file_advice("unknown", "file", "blob")


def test_a_model_report_lists_what_it_can_do(tmp_path):
    path = fake_gguf(tmp_path / "coder.gguf", template=TOOLS_TEMPLATE)
    info = read_gguf_info(path)
    report = plain(
        model_report(
            name="qwen2.5-coder-1.5b-instruct",
            file=path.name,
            info=info,
            size=1_100_000_000,
            vision=False,
            gpu_gb=7.0,
        )
    )
    can = {row["what"]: row["yes"] for row in report["can"]}
    assert can == {
        "Use tools": True,
        "See images": False,
        "Reason step by step": False,
        "Fit on your graphics card": True,
    }
    assert report["capabilities"] == {
        "tools": True,
        "vision": False,
        "reasoning": False,
    }
    assert report["best_for"][:2] == ["Builder", "Tester"]
    assert report["settings"]["gpu_layers"] == -1


def test_what_each_model_suits(tmp_path):
    thinker = read_gguf_info(
        fake_gguf(tmp_path / "t.gguf", template=TOOLS_TEMPLATE + THINKING_TEMPLATE)
    )
    assert best_for("qwen3-8b", thinker, vision=False) == [
        "Helper",
        "Jarvis",
        "Researcher",
    ]
    plain = read_gguf_info(fake_gguf(tmp_path / "p.gguf"))
    assert best_for("tinyllama-1.1b", plain, vision=True) == [
        "Guide",
        "looking at images",
    ]


# --------------------------------------------------------- adding a model file


async def chunked(data: bytes, size: int = 7):
    for start in range(0, len(data), size):
        yield data[start : start + size]


@pytest.mark.asyncio
async def test_an_uploaded_model_is_saved_and_reported(make_studio, tmp_path):
    studio, _ = make_studio([])
    data = gguf_bytes(tmp_path, template=TOOLS_TEMPLATE)

    report = plain(
        await studio.engine_upload(
            "../../Coder 1.5B Q4_K_M.gguf", chunked(data), size=len(data)
        )
    )

    saved = tmp_path / "models" / "added" / "Coder-1.5B-Q4_K_M.gguf"
    assert saved.read_bytes() == data, "the name loses its folders"
    assert not list(saved.parent.glob("*.part"))
    assert report["is_model"] and report["capabilities"]["tools"]
    assert report["name"] == "coder-1.5b"
    assert "ready on Model Control" in report["message"]
    names = [m["name"] for m in plain(await studio.engine_status())["models"]]
    assert "coder-1.5b" in names
    assert plain(await studio.engine_report("coder-1.5b"))["file"] == saved.name


@pytest.mark.asyncio
async def test_a_file_that_is_not_a_model_is_refused_early(make_studio, tmp_path):
    studio, _ = make_studio([])
    received: list[int] = []

    async def pdf():
        for chunk in (b"%PDF-1.7\n", b"x" * 1000, b"y" * 1000):
            received.append(len(chunk))
            yield chunk

    report = plain(await studio.engine_upload("notes.pdf", pdf(), size=None))

    assert report == {
        "is_model": False,
        "kind": "pdf",
        "label": "PDF document",
        "file": "notes.pdf",
        "message": file_advice("pdf", "PDF document", "notes.pdf"),
    }
    assert received == [9], "it stops reading at the first chunk"
    assert not list((tmp_path / "models" / "added").iterdir())


@pytest.mark.asyncio
async def test_a_broken_upload_leaves_nothing_behind(make_studio, tmp_path):
    studio, _ = make_studio([])

    async def dropped():
        yield b"GGUF\x03\x00\x00\x00"
        raise OSError("connection lost")

    with pytest.raises(OSError, match="connection lost"):
        await studio.engine_upload("big.gguf", dropped(), size=None)
    assert not list((tmp_path / "models" / "added").iterdir())

    with pytest.raises(Exception, match="Not enough disk space"):
        await studio.engine_upload("huge.gguf", chunked(b"GGUF"), size=10**18)


@pytest.mark.asyncio
async def test_a_model_on_this_pc_is_added_without_uploading(
    make_studio, tmp_path, monkeypatch
):
    studio, _ = make_studio([])
    source = fake_gguf(tmp_path / "Downloads" / "tiny-q8_0.gguf")
    other = tmp_path / "Downloads" / "photo.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
    picks: list[Path | None] = [source, other, None]

    async def pick() -> Path | None:
        return picks.pop(0)

    monkeypatch.setattr(service_module, "pick_model_file", pick)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            added = (await client.post("/studio/api/engine/pick-file")).json()
            assert added["picked"] and added["is_model"] and added["name"] == "tiny"
            copy = tmp_path / "models" / "added" / "tiny-q8_0.gguf"
            assert copy.read_bytes() == source.read_bytes()
            photo = (await client.post("/studio/api/engine/pick-file")).json()
            assert photo["picked"] and not photo["is_model"]
            assert photo["label"] == "PNG image"
            assert (await client.post("/studio/api/engine/pick-file")).json() == {
                "picked": False
            }

            report = await client.get("/studio/api/engine/models/tiny/report")
            assert report.status_code == 200 and report.json()["name"] == "tiny"
            missing = await client.get("/studio/api/engine/models/nope/report")
            assert missing.status_code == 400

            head = await client.post(
                "/studio/api/engine/identify",
                params={"name": "Qwen3-8B.safetensors"},
                content=struct.pack("<Q", 200) + b'{"__metadata__":{}}' + b"\0" * 9000,
            )
            assert head.json()["kind"] == "safetensors"
            assert not head.json()["is_model"]
            model_head = await client.post(
                "/studio/api/engine/identify",
                params={"name": "m.gguf"},
                content=b"GGUF\x03\x00\x00\x00",
            )
            assert model_head.json()["is_model"]

            upload = await client.post(
                "/studio/api/engine/upload",
                params={"name": "second.gguf"},
                content=gguf_bytes(tmp_path, "second.gguf"),
            )
            assert upload.status_code == 200 and upload.json()["name"] == "second"
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_model_headers_are_read_once(make_studio, tmp_path, monkeypatch):
    from free_claude_code.studio import engine as engine_module

    studio, _ = make_studio([], STUDIO_ENGINE_FOLDERS=str(tmp_path / "gguf"))
    fake_gguf(tmp_path / "gguf" / "tiny-q8_0.gguf")
    reads: list[Path] = []
    real = engine_module.read_gguf_info

    def counting(path: Path):
        reads.append(path)
        return real(path)

    monkeypatch.setattr(engine_module, "read_gguf_info", counting)
    await studio.engine_status()
    await studio.engine_report("tiny")
    await studio.engine_upload(
        "extra.gguf", chunked(gguf_bytes(tmp_path, "extra.gguf")), size=None
    )
    assert sorted(path.name for path in reads) == ["extra.gguf", "tiny-q8_0.gguf"]


# ------------------------------------------------------------ attached files


def test_text_and_code_are_read_as_they_are():
    read = plain(read_file_text("app.py", b"def hi():\r\n    return 1\r\n"))
    assert read["text"] == "def hi():\n    return 1"
    assert read["kind"] == "text" and not read["truncated"]
    assert read["message"] == "Read 22 characters."
    csv = plain(read_file_text("people.csv", "name,city\nAna,Sāo Paulo\n".encode()))
    assert "Sāo Paulo" in csv["text"]


def test_office_files_give_up_their_text():
    docx = office(
        {
            "word/document.xml": "<w:document><w:body><w:p><w:r><w:t>Hello"
            "</w:t></w:r><w:r><w:tab/><w:t>there &amp; you</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Line two</w:t></w:r></w:p></w:body></w:document>"
        }
    )
    assert plain(read_file_text("a.docx", docx))["text"] == (
        "Hello there & you\nLine two"
    )
    xlsx = office(
        {
            "xl/workbook.xml": "<workbook/>",
            "xl/sharedStrings.xml": "<sst><si><t>Name</t></si><si><t>Ana</t></si></sst>",
            "xl/worksheets/sheet1.xml": '<sheetData><row><c t="s"><v>0</v></c>'
            '<c><v>42</v></c></row><row><c t="s"><v>1</v></c>'
            '<c t="inlineStr"><is><t>hi</t></is></c></row></sheetData>',
        }
    )
    assert plain(read_file_text("a.xlsx", xlsx))["text"] == (
        "Sheet 1:\nName\t42\nAna\thi"
    )
    pptx = office(
        {
            "ppt/slides/slide10.xml": "<p:sld><a:p><a:t>Last</a:t></a:p></p:sld>",
            "ppt/slides/slide2.xml": "<p:sld><a:p><a:t>Second</a:t></a:p></p:sld>",
        }
    )
    assert plain(read_file_text("deck.pptx", pptx))["text"] == (
        "Slide 1:\nSecond\n\nSlide 2:\nLast"
    )


def test_a_pdf_gives_up_its_text():
    read = plain(read_file_text("report.pdf", simple_pdf("Quarterly sales went up")))
    assert read["kind"] == "pdf"
    assert "Quarterly sales went up" in read["text"]


def test_files_without_text_say_so():
    png = plain(read_file_text("cat.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 20))
    assert png["text"] == "" and "is a picture" in png["message"]
    model = plain(read_file_text("m.gguf", b"GGUF\x03\x00\x00\x00"))
    assert "Model Control" in model["message"]
    program = plain(read_file_text("setup.exe", b"MZ\x90\x00\x03\x00"))
    assert "has no text to read" in program["message"]


def test_long_files_are_cut_to_what_an_agent_can_take():
    read = plain(read_file_text("big.txt", b"a" * (MAX_TEXT + 500)))
    assert read["truncated"] and len(read["text"]) == MAX_TEXT
    assert read["chars"] == MAX_TEXT + 500
    assert f"the first {MAX_TEXT:,} go to the agent" in read["message"]


@pytest.mark.asyncio
async def test_attached_files_are_read_through_the_route(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            read = await client.post(
                "/studio/api/files/read",
                params={"name": "notes.md"},
                content=b"# Plan\nShip it.",
            )
            assert read.status_code == 200
            assert read.json()["text"] == "# Plan\nShip it."
            too_big = await client.post(
                "/studio/api/files/read",
                params={"name": "huge.txt"},
                content=b"a" * (MAX_UPLOAD + 1),
            )
            assert too_big.status_code == 413
            assert "25 MB" in too_big.json()["detail"]
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


# ---------------------------------------------------------- deleting agents


@pytest.mark.asyncio
async def test_deleting_an_agent_takes_everything_that_was_only_its_own(make_studio):
    studio, _ = make_studio(["Done."])
    await studio.ensure_defaults()
    agents = {agent.name: agent for agent in await studio.agents()}
    builder, helper = agents["Builder"], agents["Helper"]
    chat = await studio.create_chat(agent_id=builder.id)
    await studio.send(chat.id, "hello")
    await studio.remember(builder.id, "Likes teal.")
    await studio.remember(helper.id, "Keeps lists.")
    room = await studio.create_room(member_ids=[builder.id, helper.id], title="Crew")
    solo = await studio.create_room(member_ids=[builder.id], title="Solo")
    assert room.agent_id == builder.id
    store = studio._store
    await store.put(AgentRun(agent_id=builder.id, chat_id=chat.id, goal="build"))

    own = await store.find(Chat, where={"agent_id": builder.id, "kind": "chat"})
    chats = len(own) + 1  # its chats, and the room only it was in
    memories = await store.count(MemoryEntry, where={"agent_id": builder.id})
    assert own and memories >= 1

    done = plain(await studio.delete_agent(builder.id))

    assert done == {
        "deleted": True,
        "name": "Builder",
        "chats": chats,
        "memories": memories,
    }
    assert builder.id not in {agent.id for agent in await studio.agents()}
    assert not await store.find(Chat, where={"agent_id": builder.id})
    assert not await store.find(Message, where={"chat_id": chat.id})
    assert not await store.find(AgentRun, where={"agent_id": builder.id})
    assert not await store.find(MemoryEntry, where={"agent_id": builder.id})
    assert await store.find(MemoryEntry, where={"agent_id": helper.id})
    kept = await studio.chat(room.id)
    assert (kept.member_ids, kept.agent_id) == ((helper.id,), helper.id)
    assert await store.get(Chat, solo.id) is None, "an empty room goes"


@pytest.mark.asyncio
async def test_the_main_ai_and_guide_cannot_be_deleted(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    agents = {agent.role: agent for agent in await studio.agents()}
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            for role, why in (("main", "runs the team"), ("guide", "explains")):
                refused = await client.delete(f"/studio/api/agents/{agents[role].id}")
                assert refused.status_code == 400 and why in refused.json()["detail"]
            gone = await client.delete(f"/studio/api/agents/{agents['tester'].id}")
            assert gone.status_code == 200 and gone.json()["name"] == "Tester"
            missing = await client.delete(f"/studio/api/agents/{agents['tester'].id}")
            assert missing.status_code == 404
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


# ------------------------------------------------------------------- weather


GEOCODE = {
    "results": [
        {
            "name": "Sydney",
            "admin1": "New South Wales",
            "country": "Australia",
            "latitude": -33.87,
            "longitude": 151.21,
        }
    ]
}
FORECAST = {
    "current": {
        "temperature_2m": 21.4,
        "apparent_temperature": 20.6,
        "relative_humidity_2m": 60,
        "weather_code": 2,
        "wind_speed_10m": 14.2,
    },
    "daily": {
        "time": ["2026-09-26", "2026-09-27", "2026-09-28"],
        "weather_code": [2, 61, 0],
        "temperature_2m_max": [23.1, 19.8, 25.0],
        "temperature_2m_min": [14.2, 13.9, 15.5],
        "precipitation_probability_max": [10, 80, 0],
    },
}


def weather_service(seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if "geocoding" in request.url.host:
            name = request.url.params["name"]
            return httpx.Response(200, json=GEOCODE if name == "Sydney" else {})
        return httpx.Response(200, json=FORECAST)

    return httpx.MockTransport(handler)


def test_weather_questions_are_spotted():
    assert weather_request("what's the weather in Sydney tomorrow?") == "Sydney"
    assert weather_request("Will it rain in New York today") == "New York"
    assert weather_request("forecast for St. Kilda this weekend") == "St. Kilda"
    assert weather_request("how cold is it in Oslo right now?") == "Oslo"
    assert weather_request("build a weather app in react") is None
    assert weather_request("the weather has been nice") is None


@pytest.mark.asyncio
async def test_the_forecast_is_told_in_plain_words():
    seen: list[httpx.Request] = []
    report = await forecast("Sydney", days=3, transport=weather_service(seen))
    assert report.splitlines() == [
        "Weather in Sydney, New South Wales, Australia: now 21°C (feels like 21°C), "
        "partly cloudy, wind 14 km/h, humidity 60%.",
        "Today: partly cloudy, 23°C high, 14°C low, 10% chance of rain.",
        "Tomorrow: light rain, 20°C high, 14°C low, 80% chance of rain.",
        "Monday: clear sky, 25°C high, 16°C low, 0% chance of rain.",
    ]
    assert seen[1].url.params["latitude"] == "-33.87"
    assert seen[1].url.params["forecast_days"] == "3"
    with pytest.raises(WeatherError, match="No place called Atlantis"):
        await forecast("Atlantis", transport=weather_service())


@pytest.mark.asyncio
async def test_jarvis_checks_the_weather_before_answering(make_studio):
    def reply(system: str, prompt: str) -> LLMReply:
        return LLMReply(text="Partly cloudy and 21°C in Sydney.")

    studio, model = make_studio(reply)
    studio._search_transport = weather_service()
    await studio.main_say("what's the weather in Sydney?", background=False)

    chat = await studio.main_chat()
    said = await studio.transcript(chat.id)
    tool = next(m for m in said if m.author == "weather")
    assert tool.data["place"] == "Sydney"
    assert tool.text.startswith("Weather in Sydney, New South Wales")
    assert any("Weather in Sydney" in str(call["messages"]) for call in model.calls)
    assert said[-1].text == "Partly cloudy and 21°C in Sydney."


@pytest.mark.asyncio
async def test_no_weather_is_fetched_with_web_access_off(make_studio):
    studio, _ = make_studio(["It's off."], STUDIO_WEB_ACCESS="off")
    seen: list[httpx.Request] = []
    studio._search_transport = weather_service(seen)
    await studio.main_say("what's the weather in Sydney?", background=False)
    assert not seen
    with pytest.raises(ValueError, match="Web access is off"):
        await studio._weather("Sydney")
