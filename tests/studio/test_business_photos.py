"""Photos of the user's business, sent with notes, for the Builder to use."""

import struct

import httpx
import pytest

from free_claude_code.studio.llm import ToolCall
from free_claude_code.studio.photos import PhotoError, image_info
from free_claude_code.studio.tools import MAIN_TOOL_NAMES, SEALED_TOOLS, ToolContext
from tests.api.support import create_test_app


def jpeg(width: int, height: int) -> bytes:
    app0 = (
        b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    sof = (
        b"\xff\xc0"
        + struct.pack(">HBHHB", 17, 8, height, width, 3)
        + b"\x01\x22\x00" * 3
    )
    return b"\xff\xd8" + app0 + sof + b"\x00" * 64 + b"\xff\xd9"


def png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I4sII", 13, b"IHDR", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


SHOP = jpeg(1600, 1200)


def test_sizes_are_read_from_the_header():
    assert image_info(SHOP) == ("jpeg", 1600, 1200)
    assert image_info(png(400, 300)) == ("png", 400, 300)
    assert image_info(b"GIF89a" + struct.pack("<HH", 64, 32) + b"\x00" * 8) == (
        "gif",
        64,
        32,
    )
    webp = (
        b"RIFF"
        + b"\x00" * 4
        + b"WEBPVP8X"
        + b"\x00" * 8
        + (799).to_bytes(3, "little")
        + (599).to_bytes(3, "little")
    )
    assert image_info(webp) == ("webp", 800, 600)
    with pytest.raises(PhotoError, match="HEIC"):
        image_info(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20)
    with pytest.raises(PhotoError, match="JPEG, PNG"):
        image_info(b"not a picture at all")


@pytest.mark.asyncio
async def test_photos_are_kept_with_notes_through_the_app(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        added = await client.post(
            "/studio/api/photos",
            params={"name": "IMG_2041 Shop Front.JPG", "note": "Our shop on Main St"},
            content=SHOP,
        )
        assert added.status_code == 200, added.text
        photo = added.json()
        assert photo["name"] == "img-2041-shop-front.jpg"
        assert (photo["width"], photo["height"]) == (1600, 1200)
        assert photo["note"] == "Our shop on Main St"

        listed = (await client.get("/studio/api/photos")).json()["photos"]
        assert [item["id"] for item in listed] == [photo["id"]]
        served = await client.get(photo["url"])
        assert served.status_code == 200 and served.content == SHOP
        assert served.headers["content-type"] == "image/jpeg"

        noted = await client.patch(
            f"/studio/api/photos/{photo['id']}",
            json={"note": "Shop front. Open 7am-9pm every day."},
        )
        assert noted.json()["note"] == "Shop front. Open 7am-9pm every day."

        refused = await client.post(
            "/studio/api/photos",
            params={"name": "x.heic"},
            content=b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20,
        )
        assert (
            refused.status_code == 400 and "Most Compatible" in refused.json()["detail"]
        )

        gone = await client.delete(f"/studio/api/photos/{photo['id']}")
        assert gone.json() == {"deleted": True}
        assert (await client.get(photo["url"])).status_code == 404


@pytest.mark.asyncio
async def test_the_builder_lists_and_uses_the_photos(make_studio):
    studio, _ = make_studio([])
    shop = await studio.add_photo("shop.jpg", SHOP, note="Our shop front, green door.")
    await studio.add_photo("logo.png", png(400, 400), note="The logo")
    site = await studio.create_site(name="Cafe")
    builder = next(a for a in await studio.ensure_defaults() if a.name == "Builder")
    context = ToolContext(
        agent_id=builder.id,
        chat_id="cht_x",
        site_id=site.id,
        agent_name="Builder",
        agent_role="builder",
    )
    toolbox = studio._toolbox()

    async def run(name, **arguments):
        return await toolbox.run(
            ToolCall(id="t", name=name, arguments=arguments), context
        )

    listed = await run("list_photos")
    assert "shop.jpg (1600x1200, wide" in listed.text
    assert "the user says: Our shop front, green door." in listed.text
    assert "logo.png (400x400, square" in listed.text
    only = await run("list_photos", query="door")
    assert "shop.jpg" in only.text and "logo.png" not in only.text

    used = await run("use_photo", photo="shop", path="images/front.png")
    assert not used.failed, used.text
    assert used.data["path"] == "images/front.jpg", "the real type wins"
    assert 'width="1600" height="1200"' in used.text
    assert "green door" in used.text
    assert await studio.workspace.read_bytes(site.id, "images/front.jpg") == SHOP
    by_id = await run("use_photo", photo=shop["id"])
    assert by_id.data["path"] == "images/shop.jpg"

    missing = await run("use_photo", photo="menu board")
    assert missing.failed and "list_photos shows them" in missing.text

    assert {"list_photos", "use_photo"} <= set(builder.tools)
    assert "list_photos" in MAIN_TOOL_NAMES
    assert not {"list_photos", "use_photo"} & SEALED_TOOLS, "server builders need them"


@pytest.mark.asyncio
async def test_no_photos_yet_says_how_to_send_them(make_studio):
    studio, _ = make_studio([])
    builder = next(a for a in await studio.ensure_defaults() if a.name == "Builder")
    outcome = await studio._toolbox().run(
        ToolCall(id="t", name="list_photos", arguments={}),
        ToolContext(agent_id=builder.id, chat_id="c", agent_role="builder"),
    )
    assert "attach photos to any message" in outcome.text
