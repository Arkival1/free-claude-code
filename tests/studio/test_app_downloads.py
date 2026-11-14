"""6.62: when agents build or change an app, the user gets it to download,
like a file handed over in a chat."""

import io
import zipfile

import httpx
import pytest

from free_claude_code.core.json_types import JsonObject
from free_claude_code.studio.llm import LLMReply
from tests.api.support import create_test_app
from tests.studio.conftest import tool_reply

PAGE = "<!doctype html><title>Tides</title><h1>Tides</h1>"


def cards(transcript) -> list[dict]:
    return [m.data for m in transcript if m.data.get("kind") == "download"]


async def builder_chat(studio, **chat):
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    site = await studio.create_site(name="Tide Times")
    return site, await studio.create_chat(agent_id=builder.id, site_id=site.id, **chat)


@pytest.mark.asyncio
async def test_a_finished_app_comes_with_a_download_card(make_studio):
    studio, _ = make_studio(
        [
            tool_reply("write_file", {"path": "index.html", "content": PAGE}),
            tool_reply("write_file", {"path": "app.js", "content": "alert(1)"}),
            tool_reply("finish", {"summary": "Built it."}),
        ]
    )
    site, chat = await builder_chat(studio)
    (studio.workspace.directory(site.id) / "node_modules" / "x").mkdir(parents=True)
    (studio.workspace.directory(site.id) / "node_modules" / "x" / "big.js").write_text(
        "junk"
    )

    await studio.send(chat.id, "Build a tide app")

    transcript = await studio.transcript(chat.id)
    [card] = cards(transcript)
    assert transcript[-1].data == card, "handed over after the reply"
    assert card["name"] == "Tide Times" and card["file_name"] == "tide-times.zip"
    files = await studio.workspace.files(site.id)
    assert {"index.html", "app.js"} <= {item.path for item in files}
    assert card["files"] == len(files)
    assert card["bytes"] == sum(item.size for item in files)
    assert card["url"] == f"/studio/api/sites/{site.id}/archive"
    assert card["preview"] == f"/studio/sites/{site.id}/index.html"
    assert f"ready to download: {len(files)} files" in transcript[-1].text

    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get(str(card["url"]))
    assert response.status_code == 200
    assert 'filename="tide-times.zip"' in response.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert sorted(names) == sorted(item.path for item in files)
    assert not any("node_modules" in name for name in names)


@pytest.mark.asyncio
async def test_a_turn_that_only_reads_or_talks_hands_nothing_over(make_studio):
    studio, _ = make_studio(
        [
            tool_reply("write_file", {"path": "index.html", "content": PAGE}),
            tool_reply("finish", {"summary": "Built it."}),
            tool_reply("read_file", {"path": "index.html"}),
            LLMReply(text="It has one page."),
            LLMReply(text="Hello!"),
        ]
    )
    _, chat = await builder_chat(studio)
    await studio.send(chat.id, "Build it")
    await studio.send(chat.id, "What's in it?")
    await studio.send(chat.id, "hi")
    assert len(cards(await studio.transcript(chat.id))) == 1


@pytest.mark.asyncio
async def test_the_chat_that_asked_for_the_app_gets_it_too(make_studio):
    edit: JsonObject = {
        "path": "index.html",
        "old_text": "<h1>Tides",
        "new_text": "<h1>Tide Times",
    }
    plans = {
        "Build it": [
            tool_reply("write_file", {"path": "index.html", "content": PAGE}),
            tool_reply("finish", {"summary": "Built it."}),
        ],
        "Look at it": [
            tool_reply("read_file", {"path": "index.html"}),
            tool_reply("finish", {"summary": "Looks fine."}),
        ],
        "Rename it": [
            tool_reply("edit_file", edit),
            tool_reply("finish", {"summary": "Renamed."}),
        ],
    }
    steps: list = []

    def answer(system: str, prompt: str):
        for said, plan in plans.items():
            if prompt.strip() == said:
                steps[:] = list(plan)
        return steps.pop(0) if steps else LLMReply(text="Done.")

    studio, _ = make_studio(answer)
    main = await studio.main_agent()
    parent = await studio.create_chat(agent_id=main.id)
    site, child = await builder_chat(studio, parent_chat_id=parent.id)

    await studio.send(child.id, "Build it")
    [handed] = cards(await studio.transcript(parent.id))
    assert handed["site_id"] == site.id

    # Nothing changed: no second card. A change: a fresh one.
    await studio.send(child.id, "Look at it")
    assert len(cards(await studio.transcript(parent.id))) == 1
    await studio.send(child.id, "Rename it")
    parent_cards = cards(await studio.transcript(parent.id))
    assert len(parent_cards) == 2
    assert parent_cards[-1]["bytes"] == parent_cards[0]["bytes"] + len(
        "Tide Times"
    ) - len("Tides")
