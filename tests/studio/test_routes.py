"""The Studio HTTP surface: the app shell, its API, and its guards."""

import httpx
import pytest
import pytest_asyncio

from free_claude_code.config.settings import Settings
from free_claude_code.core.version import package_version
from free_claude_code.studio.llm import LLMReply
from tests.api.support import create_test_app
from tests.studio.conftest import tool_reply


@pytest_asyncio.fixture
async def studio_api(make_studio):
    studio, model = make_studio(
        [
            tool_reply("write_file", {"path": "index.html", "content": "<h1>Hi</h1>"}),
            tool_reply("finish", {"summary": "Wrote the page."}),
        ],
        STUDIO_LIGHT_TUNING_ENABLED=True,
    )
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            yield client, studio, model, app
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_app_shell_is_installable(studio_api):
    client, *_ = studio_api

    page = await client.get("/studio")
    assert page.status_code == 200
    assert "apple-mobile-web-app-capable" in page.text
    assert "viewport-fit=cover" in page.text
    assert package_version() in page.text

    manifest = await client.get("/studio/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"

    asset = await client.get(f"/studio/assets/{package_version()}/studio.js")
    assert asset.status_code == 200
    stale = await client.get("/studio/assets/0.0.0/studio.js")
    assert stale.status_code == 404


@pytest.mark.asyncio
async def test_the_iphone_install_pieces_are_served(studio_api):
    client, *_ = studio_api
    version = package_version()

    manifest = (await client.get("/studio/manifest.webmanifest")).json()
    png_icons = [icon for icon in manifest["icons"] if icon["type"] == "image/png"]
    assert {icon["sizes"] for icon in png_icons} == {"192x192", "512x512"}
    assert any("maskable" in icon["purpose"] for icon in manifest["icons"])

    page = (await client.get("/studio")).text
    assert 'rel="apple-touch-icon"' in page
    assert "icon-180.png" in page
    assert "apple-mobile-web-app-capable" in page

    icon = await client.get(f"/studio/assets/{version}/icon-180.png")
    assert icon.status_code == 200
    assert icon.content.startswith(b"\x89PNG")

    worker = await client.get("/studio/sw.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/studio"
    assert "__FCC_VERSION__" not in worker.text
    assert version in worker.text


@pytest.mark.asyncio
async def test_connect_lists_addresses_for_the_phone(studio_api):
    client, *_ = studio_api

    body = (await client.get("/studio/api/connect")).json()

    assert body["port"] == 8082  # the port this request arrived on
    assert any(url.startswith("http://localhost:8082/studio") for url in body["urls"])
    assert body["auth_required"] is False
    assert body["loopback_only"] is False


@pytest.mark.asyncio
async def test_bootstrap_creates_the_starter_agents(studio_api):
    client, *_ = studio_api

    created = await client.post("/studio/api/bootstrap")
    assert created.status_code == 200
    assert set(created.json()["created_agents"]) == {
        "Jarvis",
        "Researcher",
        "Guide",
        "Builder",
        "Teacher",
        "Student",
    }

    listed = await client.get("/studio/api/agents")
    assert len(listed.json()["agents"]) == 6


@pytest.mark.asyncio
async def test_the_guide_model_downloads_only_when_asked(studio_api):
    client, studio, *_ = studio_api

    quiet = await client.post("/studio/api/bootstrap")
    assert quiet.json()["guide_download"] is None
    assert await studio.assets() == ()

    asked = await client.post("/studio/api/bootstrap", json={"download_guide": True})
    queued = asked.json()["guide_download"]
    assert queued["source_url"].endswith(".gguf")
    assert queued["preloaded"] is True
    await studio.shutdown()  # the fetch itself is background work, not this test


@pytest.mark.asyncio
async def test_a_chat_turn_returns_the_transcript(studio_api):
    client, *_ = studio_api
    await client.post("/studio/api/bootstrap")
    agents = (await client.get("/studio/api/agents")).json()["agents"]
    builder = next(agent for agent in agents if agent["name"] == "Builder")
    site = (await client.post("/studio/api/sites", json={"name": "Demo"})).json()
    chat = (
        await client.post(
            "/studio/api/chats", json={"agent_id": builder["id"], "site_id": site["id"]}
        )
    ).json()

    reply = await client.post(
        f"/studio/api/chats/{chat['id']}/messages", json={"text": "build it"}
    )

    assert reply.status_code == 200
    body = reply.json()
    assert body["reply"] == "Wrote the page."
    assert "write_file" in body["tool_calls"]
    assert body["messages"][0]["role"] == "user"

    files = await client.get(f"/studio/api/sites/{site['id']}/files")
    assert [item["path"] for item in files.json()["files"]] == [
        "app.js",
        "index.html",
        "styles.css",
    ]


@pytest.mark.asyncio
async def test_turning_on_light_tuning_opens_a_new_chat(studio_api):
    client, *_ = studio_api
    await client.post("/studio/api/bootstrap")
    agents = (await client.get("/studio/api/agents")).json()["agents"]
    chat = (
        await client.post("/studio/api/chats", json={"agent_id": agents[1]["id"]})
    ).json()

    response = await client.post(
        f"/studio/api/chats/{chat['id']}/settings",
        json={"settings": {"light_tuning": True}},
    )

    body = response.json()
    assert body["chat"]["settings"]["light_tuning"] is True
    assert body["opened_chat"] is not None
    assert body["opened_chat"]["id"] != chat["id"]
    assert body["opened_chat"]["parent_chat_id"] == chat["id"]
    assert "fresh chat" in body["note"]

    opened = await client.get(f"/studio/api/chats/{body['opened_chat']['id']}")
    assert opened.json()["messages"][0]["data"]["kind"] == "tuning_enabled"


@pytest.mark.asyncio
async def test_site_preview_serves_files_and_blocks_traversal(studio_api):
    client, *_ = studio_api
    site = (await client.post("/studio/api/sites", json={"name": "Demo"})).json()

    page = await client.get(f"/studio/sites/{site['id']}/index.html")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "Demo" in page.text

    escaped = await client.get(f"/studio/sites/{site['id']}/../../secrets.txt")
    assert escaped.status_code in {400, 404}

    archive = await client.get(f"/studio/api/sites/{site['id']}/archive")
    assert archive.status_code == 200
    assert archive.content.startswith(b"PK")


@pytest.mark.asyncio
async def test_model_catalog_and_download_validation(studio_api):
    client, *_ = studio_api

    listing = await client.get("/studio/api/models")
    assert listing.status_code == 200
    assert any(entry["guide"] for entry in listing.json()["catalog"])

    refused = await client.post(
        "/studio/api/models/download", json={"url": "file:///etc/passwd"}
    )
    assert refused.status_code == 400
    assert "http(s)" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_tuning_endpoints_drive_a_run(studio_api):
    client, studio, *_ = studio_api
    await client.post("/studio/api/bootstrap")
    agents = (await client.get("/studio/api/agents")).json()["agents"]
    pack = (
        await client.post(
            "/studio/api/tuning/packs", json={"agent_id": agents[1]["id"]}
        )
    ).json()

    added = await client.post(
        f"/studio/api/tuning/packs/{pack['id']}/samples",
        json={"pairs": [["q1", "a1"], ["q2", "a2"], ["q3", "a3"]]},
    )
    assert added.json() == {"added": 3, "total": 3}

    started = await client.post(f"/studio/api/tuning/packs/{pack['id']}/start")
    assert started.status_code == 200
    await studio.wait_for_background()

    job = await client.get(f"/studio/api/tuning/jobs/{started.json()['id']}")
    assert job.json()["status"] in {"succeeded", "failed"}
    assert job.json()["progress"] == 1.0


@pytest.mark.asyncio
async def test_missing_records_report_404(studio_api):
    client, *_ = studio_api

    response = await client.get("/studio/api/chats/cht_missing")

    assert response.status_code == 404
    assert response.json()["code"] == "StudioNotFoundError"


@pytest.mark.asyncio
async def test_guide_answers_without_a_model(studio_api):
    client, *_ = studio_api

    response = await client.post(
        "/studio/api/guide/ask", json={"question": "how do I install this on iphone?"}
    )

    body = response.json()
    assert body["offline"] is True
    assert "Home Screen" in body["text"] or "Share" in body["text"]


@pytest.mark.asyncio
async def test_studio_is_503_when_disabled():
    app = create_test_app(studio=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/studio/api/overview")
        assert response.status_code == 503
    await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_proxy_auth_guards_studio(make_studio):
    studio, _ = make_studio([LLMReply(text="hi")])
    settings = Settings.model_validate(
        {
            "MODEL": "nvidia_nim/test-model",
            "PROXY_AUTH_ENABLED": True,
            "ANTHROPIC_AUTH_TOKEN": "s3cret",
        }
    )
    app = create_test_app(settings, studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        assert (await client.get("/studio/api/overview")).status_code == 401
        with_header = await client.get(
            "/studio/api/overview", headers={"x-api-key": "s3cret"}
        )
        assert with_header.status_code == 200
        with_query = await client.get("/studio/api/overview?token=s3cret")
        assert with_query.status_code == 200
    await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_rooms_run_in_the_background_and_report_progress(make_studio):
    studio, _ = make_studio(lambda system, prompt: "Room reply.")
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        lead = (
            await client.post("/studio/api/agents", json={"name": "Lead", "tools": []})
        ).json()
        room = (
            await client.post(
                "/studio/api/rooms", json={"title": "Team", "member_ids": [lead["id"]]}
            )
        ).json()
        assert room["kind"] == "room"

        posted = await client.post(
            f"/studio/api/rooms/{room['id']}/messages", json={"text": "hello"}
        )
        assert posted.status_code == 202
        assert (await client.get(f"/studio/api/rooms/{room['id']}")).json()["running"]

        await studio.wait_for_background()
        detail = (await client.get(f"/studio/api/rooms/{room['id']}")).json()
        assert detail["running"] is False
        assert [member["name"] for member in detail["members"]] == ["Lead"]
        assert detail["messages"][-1]["text"] == "Room reply."

        tail = (
            await client.get(
                f"/studio/api/rooms/{room['id']}",
                params={"after": detail["messages"][-1]["sequence"]},
            )
        ).json()
        assert tail["messages"] == []

        task = await client.post(
            f"/studio/api/rooms/{room['id']}/task", json={"goal": "Plan a picnic"}
        )
        assert task.status_code == 202
        stopped = await client.post(f"/studio/api/rooms/{room['id']}/stop")
        assert stopped.json()["settings"]["stop_requested"] is True
        await studio.wait_for_background()

        listed = (await client.get("/studio/api/rooms")).json()["rooms"]
        assert [item["id"] for item in listed] == [room["id"]]
    await studio.shutdown()
    await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_the_hud_talks_to_the_main_ai_in_the_background(make_studio):
    studio, _ = make_studio(["Good evening. The team is standing by."])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            console = (await client.get("/studio/api/main")).json()
            assert console["agent"]["name"] == "Jarvis"
            assert console["messages"] == []

            sent = await client.post("/studio/api/main/messages", json={"text": "hi"})
            assert sent.status_code == 202
            assert sent.json()["chat_id"] == console["chat"]["id"]
            await studio.wait_for_background()

            after = (await client.get("/studio/api/main")).json()
            assert [m["text"] for m in after["messages"]] == [
                "hi",
                "Good evening. The team is standing by.",
            ]
            assert after["thinking"] is False

            empty = await client.post("/studio/api/main/messages", json={"text": " "})
            assert empty.status_code == 400

            fresh = (await client.post("/studio/api/main/new")).json()
            assert fresh["id"] != console["chat"]["id"]

            shared = await client.post(
                "/studio/api/memory/shared", json={"text": "The user likes dark mode"}
            )
            assert shared.json()["author"] == "you"
            listed = (await client.get("/studio/api/memory/shared")).json()
            assert [m["text"] for m in listed["memories"]] == [
                "The user likes dark mode"
            ]
            assert (await client.get("/studio/api/main")).json()["memory"]["count"] == 1
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
