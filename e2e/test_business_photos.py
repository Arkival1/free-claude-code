"""Photos of the real business, with notes, on the PC and the phone; and who
may direct whom, and whose memory is whose, on the phone."""

import io
import re
import struct
import zipfile
import zlib

from playwright.sync_api import FilePayload, Page, expect

from e2e.test_fcc_phone import fake_gemini, go, open_phone, say, tool_call, use_gemini


def png_bytes(width: int, height: int, rgb=(200, 80, 40)) -> bytes:
    """A real PNG, so browsers can open and shrink it."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(rgb) * width
    raw = zlib.compress(row * height)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", raw)
        + chunk(b"IEND", b"")
    )


SHOP: FilePayload = {
    "name": "Shop Front.png",
    "mimeType": "image/png",
    "buffer": png_bytes(64, 48),
}


def test_the_pc_keeps_business_photos_with_notes(
    page: Page, admin_base_url: str
) -> None:
    page.goto(f"{admin_base_url}/studio#agents")
    photos = page.locator(
        ".card", has=page.get_by_role("heading", name=re.compile(r"Business photos$"))
    )
    expect(photos).to_contain_text("No photos yet.")
    photos.get_by_label("Note for new photos").fill(
        "Our shop on Main St, open 7am-9pm."
    )
    photos.get_by_label("Add business photos").set_input_files([SHOP])
    tile = photos.locator(".photo-tile")
    expect(tile).to_have_count(1)
    expect(tile).to_contain_text("shop-front.png")
    note = tile.get_by_label("Note for shop-front.png")
    expect(note).to_have_value("Our shop on Main St, open 7am-9pm.")
    shown = tile.locator("img").evaluate(
        "img => img.decode().then(() => img.naturalWidth)"
    )
    assert shown == 64
    note.fill("Shop front, green door.")
    note.blur()
    expect(page.get_by_text("Note saved.")).to_be_visible()
    listed = page.evaluate("() => fetch('/studio/api/photos').then(r => r.json())")
    assert listed["photos"][0]["note"] == "Shop front, green door."


def photo_builder(body: dict) -> dict:
    system = body["messages"][0]["content"]
    last = body["messages"][-1]
    said = last.get("content") or ""
    if "You are Builder" not in system:
        return say("Hi!")
    if last["role"] == "user":
        return tool_call("list_photos", {})
    if said.startswith("1. shop-front"):
        return tool_call(
            "use_photo", {"photo": "shop-front", "path": "images/front.jpg"}
        )
    if said.startswith("Put shop-front"):
        page = (
            "<!doctype html><html><head><meta name='viewport' content='width=device-width'>"
            "<title>Luna</title></head><body><h1>Luna</h1>"
            "<img src='images/front.png' alt='Our shop' width='64' height='48'></body></html>"
        )
        return tool_call("write_file", {"path": "index.html", "content": page})
    return say("Built the page with your shop photo.")


def test_the_phone_builder_uses_photos_sent_in_a_chat(
    page: Page, admin_base_url: str
) -> None:
    seen = fake_gemini(page, photo_builder)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "chat/builder")
    page.get_by_label("Choose photos").set_input_files([SHOP])
    expect(page.locator(".attach-chips")).to_contain_text("shop-front.png")
    page.get_by_label("Message", exact=True).fill(
        "Our shop front, open 7am-9pm every day."
    )
    page.get_by_label("Message", exact=True).press("Enter")
    expect(page.locator(".messages")).to_contain_text(
        "Built the page with your shop photo.", timeout=20000
    )

    first = seen[0]["messages"][-1]["content"]
    assert "[Business photo: shop-front.png (64x48)" in first
    results = [
        m["content"] for call in seen for m in call["messages"] if m["role"] == "tool"
    ]
    assert any(
        "the user says: Our shop front, open 7am-9pm every day." in r for r in results
    )
    assert any(
        r.startswith("Put shop-front.png") and "images/front.png" in r for r in results
    )

    project = page.evaluate("() => window.fccPhone.state.projects[0]")
    assert project["files"]["images/front.png"].startswith("data:image/png")
    go(page, "projects")
    page.get_by_role("button", name=f"Open {project['name']}").click()
    shown = (
        page.frame_locator("iframe.preview")
        .locator("img")
        .evaluate("img => img.decode().then(() => img.naturalWidth)")
    )
    assert shown == 64
    raw = page.evaluate(
        """async () => [...new Uint8Array(await window.fccPhone.zipProject(
            window.fccPhone.state.projects[0]).arrayBuffer())]"""
    )
    with zipfile.ZipFile(io.BytesIO(bytes(raw))) as archive:
        picture = archive.read(f"{project['slug']}/images/front.png")
    assert picture.startswith(b"\x89PNG")

    go(page, "projects")
    card = page.locator(
        ".card", has=page.get_by_role("heading", name=re.compile(r"Business photos$"))
    )
    expect(card.locator(".photo-tile")).to_have_count(1)
    expect(card.get_by_label("Note for shop-front.png")).to_have_value(
        "Our shop front, open 7am-9pm every day."
    )


def test_jarvis_keeps_his_own_memory_on_the_phone(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    result = page.evaluate(
        """async () => {
            const f = window.fccPhone;
            const jarvis = f.state.agents.find((a) => a.id === 'jarvis');
            const builder = f.state.agents.find((a) => a.id === 'builder');
            const own = await f.remember(jarvis, 'The user prefers short answers.');
            const shared = await f.remember(jarvis, 'The cafe opens at 7am.', {share: true});
            await f.remember(builder, 'The cafe logo is a crescent moon.');
            return {
                own, shared,
                builderSeesOwn: f.recall(builder, 'user prefers short answers', 5).length,
                builderSeesShared: f.recall(builder, 'opens 7am', 5).length,
                jarvisSeesBuilder: f.recall(jarvis, 'cafe logo crescent moon', 5),
            };
        }"""
    )
    assert result["own"].startswith("Saved to your own memory")
    assert result["shared"].startswith("Saved to memory")
    assert result["builderSeesOwn"] == 0 and result["builderSeesShared"] == 1
    assert result["jarvisSeesBuilder"][0]["from"] == "from Builder"
    go(page, "memory")
    expect(
        page.get_by_text("Jarvis's own memory · only Jarvis reads it")
    ).to_be_visible()


def cloud_builder_asks_tester(body: dict) -> dict:
    system = body["messages"][0]["content"]
    last = body["messages"][-1]
    if "You are Builder" in system and last["role"] == "user":
        return tool_call("ask_agent", {"agent": "Tester", "task": "Test it."})
    if last["role"] == "tool":
        return say(f"Told: {last['content'][:120]}")
    return say("Hi!")


def test_cloud_agents_cannot_direct_phone_agents(
    page: Page, admin_base_url: str
) -> None:
    fake_gemini(page, cloud_builder_asks_tester)
    open_phone(page, admin_base_url)
    use_gemini(page)
    page.evaluate(
        """async () => {
            const tester = window.fccPhone.state.agents.find((a) => a.id === 'tester');
            tester.brain = 'local';
        }"""
    )
    go(page, "chat/builder")
    page.get_by_label("Message", exact=True).fill("Build and test it")
    page.get_by_label("Message", exact=True).press("Enter")
    expect(page.locator(".messages")).to_contain_text(
        "Tester thinks on this phone and takes jobs from Jarvis", timeout=15000
    )


def test_a_photo_attached_in_a_pc_chat_keeps_the_message_as_its_note(
    page: Page, admin_base_url: str
) -> None:
    page.goto(f"{admin_base_url}/studio#agents")
    chat_id = page.evaluate(
        """async () => {
            await fetch('/studio/api/bootstrap', {method: 'POST',
                headers: {'content-type': 'application/json'}, body: '{}'});
            const {agents} = await fetch('/studio/api/agents').then(r => r.json());
            const builder = agents.find(a => a.name === 'Builder');
            const chat = await fetch('/studio/api/chats', {method: 'POST',
                headers: {'content-type': 'application/json'},
                body: JSON.stringify({agent_id: builder.id})}).then(r => r.json());
            return chat.id || chat.chat.id;
        }"""
    )
    page.goto(f"{admin_base_url}/studio#chat/{chat_id}")
    page.get_by_label("Attach files or photos").set_input_files([SHOP])
    expect(page.locator(".attach-chips")).to_contain_text("🖼 shop-front.png")
    page.get_by_placeholder("Message").fill("This is our bakery's front door.")
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".bubble.user").last).to_contain_text(
        "This is our bakery's front door."
    )
    page.wait_for_function(
        """() => fetch('/studio/api/photos').then(r => r.json()).then(
            data => data.photos.some(p => p.note === "This is our bakery's front door."))"""
    )
    transcript = page.evaluate(
        f"() => fetch('/studio/api/chats/{chat_id}').then(r => r.json())"
    )
    said = [m["text"] for m in transcript["messages"] if m["role"] == "user"]
    assert "[Business photo: shop-front.png (64x48" in said[0]
