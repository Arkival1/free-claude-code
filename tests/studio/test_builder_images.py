"""The Builder's picture tools: free photos from Openverse, saved into the project."""

import httpx
import pytest

from free_claude_code.studio.images import ImageError, download_image
from free_claude_code.studio.llm import ToolCall
from free_claude_code.studio.models import Agent
from free_claude_code.studio.polish import polish_notes
from free_claude_code.studio.presets import (
    _OLD_BUILDER_PROMPT_V5,
    BUILDER_PROMPT,
    TOOL_GROUPS,
)
from free_claude_code.studio.tools import ToolContext

# A public address, so no name lookup is needed in tests.
PHOTO = "https://93.184.215.14/photos/cafe.jpg"
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 2000
OTHER = "https://93.184.215.14/photos/other.jpg"
OTHER_JPEG = b"\xff\xd8\xff\xe0" + b"y" * 1000


def image_web(seen: list[str] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        if request.url.host == "api.openverse.org":
            query = request.url.params.get("q", "")
            if query == "nothing":
                return httpx.Response(200, json={"results": []})
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": PHOTO,
                            "width": 1600,
                            "height": 900,
                            "title": "Cafe counter",
                            "creator": "Ana",
                            "license": "by",
                            "license_version": "2.0",
                            "foreign_landing_url": "https://example.org/cafe",
                        },
                        {
                            "url": "http://insecure.example/x.jpg",
                            "creator": "Bob",
                            "license": "by",
                        },
                        {
                            "url": "https://93.184.215.14/photos/beans.png",
                            "width": 800,
                            "height": 800,
                            "creator": "Cleo",
                            "license": "cc0",
                        },
                    ]
                },
            )
        path = request.url.path
        if path == "/photos/cafe.jpg":
            return httpx.Response(
                200, content=JPEG, headers={"content-type": "image/jpeg"}
            )
        if path == "/photos/other.jpg":
            return httpx.Response(
                200, content=OTHER_JPEG, headers={"content-type": "image/jpeg"}
            )
        if path == "/photos/beans.png":
            return httpx.Response(
                200, content=b"\x89PNG....", headers={"content-type": "image/png"}
            )
        if path == "/photos/moved.jpg":
            return httpx.Response(302, headers={"location": PHOTO})
        if path == "/photos/sneaky.jpg":
            return httpx.Response(
                302, headers={"location": "https://127.0.0.1/secret.png"}
            )
        if path == "/page.html":
            return httpx.Response(
                200, text="<html>", headers={"content-type": "text/html"}
            )
        if path == "/huge.jpg":
            return httpx.Response(
                200, content=b"x" * 5_000_001, headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(404)

    return httpx.MockTransport(handle)


async def builder_in_project(studio):
    site = await studio.create_site(name="Cafe")
    agent = await studio.create_agent(name="Maker", role="builder")
    context = ToolContext(
        agent_id=agent.id,
        chat_id="cht_x",
        site_id=site.id,
        agent_name="Maker",
        agent_role="builder",
    )
    return site, context


async def run(studio, context, name, **arguments):
    return await studio._toolbox().run(
        ToolCall(id="t", name=name, arguments=arguments), context
    )


@pytest.mark.asyncio
async def test_finding_photos_gives_sizes_and_credit_lines(make_studio):
    studio, _ = make_studio([])
    seen: list[str] = []
    studio._search_transport = image_web(seen)
    _, context = await builder_in_project(studio)

    found = await run(
        studio, context, "find_images", query="  cafe  ", orientation="wide"
    )

    assert not found.failed
    assert (
        "1. Cafe counter (1600x900) https://93.184.215.14/photos/cafe.jpg" in found.text
    )
    assert "Credit: Photo by Ana, CC BY 2.0" in found.text
    assert "Photo by Cleo (public domain)" in found.text
    assert "insecure.example" not in found.text
    search = httpx.URL(seen[0])
    assert search.params["q"] == "cafe"
    assert search.params["license_type"] == "commercial"
    assert search.params["mature"] == "false"
    assert search.params["aspect_ratio"] == "wide"
    assert [image["url"] for image in found.data["images"]] == [
        PHOTO,
        "https://93.184.215.14/photos/beans.png",
    ]

    none = await run(studio, context, "find_images", query="nothing")
    assert "No free photos" in none.text


@pytest.mark.asyncio
async def test_saving_a_photo_into_the_project(make_studio):
    studio, _ = make_studio([])
    studio._search_transport = image_web()
    site, context = await builder_in_project(studio)
    toolbox = studio._toolbox()

    await toolbox.run(
        ToolCall(id="a", name="find_images", arguments={"query": "cafe"}), context
    )
    saved = await toolbox.run(
        ToolCall(
            id="b", name="save_image", arguments={"url": PHOTO, "path": "images/hero"}
        ),
        context,
    )

    assert not saved.failed, saved.text
    assert saved.data["path"] == "images/hero.jpg"
    assert 'width="1600" height="900"' in saved.text
    assert "Photo by Ana, CC BY 2.0" in saved.text
    assert await studio.workspace.read_bytes(site.id, "images/hero.jpg") == JPEG

    # The wrong extension is corrected to the picture's real type.
    beans = await run(
        studio,
        context,
        "save_image",
        url="https://93.184.215.14/photos/beans.png",
        path="images/beans.jpg",
    )
    assert beans.data["path"] == "images/beans.png"

    # Redirects are followed.
    moved = await run(
        studio,
        context,
        "save_image",
        url="https://93.184.215.14/photos/moved.jpg",
        path="images/moved.jpg",
    )
    assert not moved.failed, moved.text
    assert await studio.workspace.read_bytes(site.id, "images/moved.jpg") == JPEG

    # A replaced picture is kept, so restore_file can put it back.
    await run(studio, context, "save_image", url=OTHER, path="images/hero.jpg")
    assert await studio.workspace.read_bytes(site.id, "images/hero.jpg") == OTHER_JPEG
    undone = await run(
        studio, context, "restore_file", path="images/hero.jpg", versions_back=1
    )
    assert not undone.failed, undone.text
    assert await studio.workspace.read_bytes(site.id, "images/hero.jpg") == JPEG


@pytest.mark.asyncio
async def test_saved_photos_count_as_present_for_check_project(make_studio):
    studio, _ = make_studio([])
    studio._search_transport = image_web()
    site, context = await builder_in_project(studio)
    await run(studio, context, "save_image", url=PHOTO, path="images/hero.jpg")
    await studio.write_site_file(
        site.id,
        "index.html",
        '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
        '<title>Cafe</title></head><body><img src="images/hero.jpg" alt="Cafe">'
        '<img src="images/gone.jpg" alt="Gone"></body></html>',
    )

    checked = await run(studio, context, "check_project")

    assert "images/gone.jpg, which is missing" in checked.text
    assert "images/hero.jpg" not in checked.text


@pytest.mark.asyncio
async def test_unsafe_or_wrong_addresses_are_refused(make_studio):
    studio, _ = make_studio([])
    studio._search_transport = image_web()
    _, context = await builder_in_project(studio)

    cases = {
        "http://93.184.215.14/photos/cafe.jpg": "https://",
        "https://127.0.0.1/secret.png": "private network",
        "https://10.1.2.3/secret.png": "private network",
        "https://93.184.215.14/photos/sneaky.jpg": "private network",
        "https://93.184.215.14/page.html": "isn't a JPEG",
        "https://93.184.215.14/huge.jpg": "over 5 MB",
    }
    for url, reason in cases.items():
        outcome = await run(studio, context, "save_image", url=url, path="images/x.jpg")
        assert outcome.failed, url
        assert reason in outcome.text, (url, outcome.text)

    bad_path = await run(studio, context, "save_image", url=PHOTO, path="../x.jpg")
    assert bad_path.failed


@pytest.mark.asyncio
async def test_private_addresses_allowed_only_when_the_setting_says_so():
    local = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=JPEG, headers={"content-type": "image/jpeg"}
        )
    )
    with pytest.raises(ImageError):
        await download_image("https://192.168.1.5/a.jpg", transport=local)
    data, suffix = await download_image(
        "https://192.168.1.5/a.jpg", allow_private=True, transport=local
    )
    assert (data, suffix) == (JPEG, ".jpg")


@pytest.mark.asyncio
async def test_picture_tools_follow_web_access(make_studio):
    studio, _ = make_studio([], studio_web_access="off")
    studio._search_transport = image_web()
    _, context = await builder_in_project(studio)

    outcome = await run(studio, context, "find_images", query="cafe")

    assert outcome.failed and "Web access is off" in outcome.text
    toolbox = studio._toolbox()
    assert "find_images" not in toolbox.tool_names(
        ("find_images", "write_file"), role="builder"
    )


@pytest.mark.asyncio
async def test_the_builder_gets_the_picture_tools_and_new_prompt(make_studio):
    studio, _ = make_studio([])
    agents = await studio.ensure_defaults()
    builder = next(agent for agent in agents if agent.name == "Builder")
    assert {"find_images", "save_image"} <= set(builder.tools)
    assert "find_images" in builder.system_prompt

    # A Builder from an earlier version is upgraded in place.
    await studio._store.put(
        builder.model_copy(
            update={
                "tools": tuple(
                    tool
                    for tool in builder.tools
                    if tool not in {"find_images", "save_image"}
                ),
                "system_prompt": _OLD_BUILDER_PROMPT_V5,
            }
        )
    )
    await studio.ensure_defaults()
    upgraded = await studio._store.get(Agent, builder.id)
    assert upgraded is not None
    assert {"find_images", "save_image"} <= set(upgraded.tools)
    assert upgraded.system_prompt == BUILDER_PROMPT
    grouped = {tool for _, tools in TOOL_GROUPS for tool in tools}
    assert {"find_images", "save_image"} <= grouped


def test_polish_suggests_fonts_alt_text_pictures_and_a_description():
    page = (
        "<header></header><main><h1>Hi</h1><img src=a.jpg width=1 height=1></main>"
        '<footer></footer><link rel="icon" href="x">'
    )
    notes = " ".join(
        polish_notes({"index.html": page, "styles.css": "body{color:#111}"})
    )
    assert "font-family" in notes
    assert "alt text" in notes
    assert 'name="description"' in notes
    assert "has no pictures" not in notes

    bare = polish_notes(
        {
            "index.html": "<h1>Hi</h1><section></section><section></section>",
            "styles.css": "body{color:#111}",
        }
    )
    assert any("find_images" in note for note in bare)
    # An emoji favicon is an <svg> inside a <link>, not a picture on the page.
    favicon = polish_notes(
        {
            "index.html": "<h1>Hi</h1><section></section><section></section>"
            '<link rel="icon" href="data:image/svg+xml,'
            "<svg xmlns='http://www.w3.org/2000/svg'><text>x</text></svg>\">",
            "styles.css": "body{color:#111}",
        }
    )
    assert any("has no pictures" in note for note in favicon)

    # Photos already saved in the project come first, before a new search.
    saved = polish_notes(
        {
            "index.html": "<h1>Hi</h1><section></section><section></section>",
            "styles.css": "body{color:#111}",
        },
        ["images/hero.jpg", "images/product.jpg"],
    )
    assert any(
        "already has images/hero.jpg, images/product.jpg" in note
        and "find_images" not in note
        for note in saved
    )

    finished = polish_notes(
        {
            "index.html": page.replace("<img ", '<img alt="A cafe" ')
            + '<meta name="description" content="A cafe">',
            "styles.css": "body{font-family:Inter,system-ui}",
        }
    )
    assert not any(
        word in " ".join(finished)
        for word in ("font-family", "alt text", 'name="description"')
    )
