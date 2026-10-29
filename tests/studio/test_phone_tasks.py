"""FCC Phone's Tasks (a whole job run by the PC's team, like Manus), and
adding plugins and subagents from the phone; all through the PC link."""

import asyncio
import base64
from typing import Any

import pytest

from free_claude_code.studio.extensions import BUILTIN_ID, Extension
from free_claude_code.studio.models import TeamPlan
from free_claude_code.studio.phone_tasks import FILES_CHARS, pick_files
from free_claude_code.studio.teamplan import PLANNER_SYSTEM
from tests.api.support import create_test_app

from .conftest import tool_reply
from .test_phone_link import ORIGIN, paired
from .test_trading_routes import client_for

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
PATHS = (
    ("GET", "/studio/api/phone/tasks", None),
    ("POST", "/studio/api/phone/tasks", {"goal": "a job"}),
    ("GET", "/studio/api/phone/tasks/x", None),
    ("POST", "/studio/api/phone/tasks/x/stop", None),
    ("POST", "/studio/api/phone/tasks/x/resume", None),
    ("GET", "/studio/api/phone/tasks/x/files", None),
    ("POST", "/studio/api/phone/plugins", {"url": "github.com/o/r"}),
    ("POST", "/studio/api/phone/plugins/x/switch", {"on": True}),
    ("GET", "/studio/api/phone/subagents", None),
    ("POST", "/studio/api/phone/subagents", {"name": "A", "role": "tester"}),
    ("POST", "/studio/api/phone/subagents/x/switch", {"on": True}),
    ("GET", "/studio/api/phone/hq", None),
    ("POST", "/studio/api/phone/hq/agents/x/say", {"text": "hello"}),
)


def data(value: object) -> Any:
    return value


def team(system: str, prompt: str):
    if system == PLANNER_SYSTEM:
        return (
            '{"steps": [{"agent": "Researcher", "do": "find three electricians\' prices"},'
            ' {"agent": "Helper", "do": "write the quote form wording"}]}'
        )
    return tool_reply("finish", {"summary": "Done: " + "x" * 3000})


@pytest.mark.asyncio
async def test_the_new_phone_paths_need_the_phone_secret(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with client_for(app) as client:
        for method, path, body in PATHS:
            refused = await client.request(
                method, path, json=body, headers={"Origin": ORIGIN}
            )
            assert refused.status_code == 401, path
    await studio.shutdown()


@pytest.mark.asyncio
async def test_a_task_from_the_phone_runs_on_the_pc_team(make_studio):
    studio, _ = make_studio(team)
    await studio.ensure_defaults()
    app = create_test_app(studio=studio)
    async with client_for(app) as client:
        _, phone = await paired(client)
        started = await client.post(
            "/studio/api/phone/tasks",
            json={"goal": "  Price up   a switchboard job  "},
            headers=phone,
        )
        assert started.status_code == 202, started.text
        task = data(started.json())
        assert task["goal"] == "Price up a switchboard job"
        await asyncio.wait_for(studio.wait_for_background(), timeout=20)

        done = data(
            (
                await client.get(f"/studio/api/phone/tasks/{task['id']}", headers=phone)
            ).json()
        )
        assert done["status"] == "done" and not done["running"]
        assert [step["agent"] for step in done["steps"]] == ["Researcher", "Helper"]
        assert done["done_steps"] == 2
        # Trimmed for the phone's small models.
        assert all(len(step["result"]) <= 1500 for step in done["steps"])
        listed = data(
            (await client.get("/studio/api/phone/tasks", headers=phone)).json()
        )
        assert listed["tasks"][0]["id"] == task["id"]
        plan = await studio.plan(task["id"])
        assert plan.made_by == "you (iPhone 12 Pro)"

        again = await client.post(
            f"/studio/api/phone/tasks/{task['id']}/resume", headers=phone
        )
        assert again.status_code == 202
        empty = await client.post(
            "/studio/api/phone/tasks", json={"goal": "   "}, headers=phone
        )
        assert empty.status_code == 400
        gone = await client.post("/studio/api/phone/tasks/nope/stop", headers=phone)
        assert gone.status_code == 400 and "gone" in gone.text
    await studio.shutdown()


@pytest.mark.asyncio
async def test_a_tasks_files_come_to_the_phone(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    site = await studio.create_site(name="Bright Spark")
    await studio.workspace.write(site.id, "index.html", "<h1>Bright Spark</h1>")
    await studio.workspace.write_image(site.id, "images/logo.png", PNG)
    plan = TeamPlan(goal="site", status="done", site_id=site.id)
    await studio._store.put(plan)
    no_files = TeamPlan(goal="research", status="done")
    await studio._store.put(no_files)
    async with client_for(app) as client:
        _, phone = await paired(client)
        found = data(
            (
                await client.get(
                    f"/studio/api/phone/tasks/{plan.id}/files", headers=phone
                )
            ).json()
        )
        assert found["name"] == "Bright Spark"
        assert found["files"]["index.html"] == "<h1>Bright Spark</h1>"
        assert found["files"]["images/logo.png"].startswith("data:image/png;base64,")
        refused = await client.get(
            f"/studio/api/phone/tasks/{no_files.id}/files", headers=phone
        )
        assert refused.status_code == 400 and "didn't make any files" in refused.text
    await studio.shutdown()


def test_big_and_binary_files_stay_on_the_pc():
    sent, left = pick_files(
        [
            ("photo.png", "image/png", 200_000),
            ("index.html", "text/html", 50_000),
            ("song.mp3", "audio/mpeg", 1_000),
            ("huge.js", "application/javascript", 400_000),
            *[(f"page{i}.html", "text/html", 290_000) for i in range(6)],
        ]
    )
    assert sent[0] == "index.html", "text comes before pictures"
    assert "song.mp3" in left and "huge.js" in left
    total = sum(
        200_000 * 4 // 3
        if path == "photo.png"
        else 50_000
        if path == "index.html"
        else 290_000
        for path in sent
    )
    assert total <= FILES_CHARS


@pytest.mark.asyncio
async def test_plugins_and_subagents_from_the_phone(make_studio, monkeypatch):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    await studio._extensions.install_builtin()
    app = create_test_app(studio=studio)
    asked: list[str] = []

    async def add_extension(link: str) -> Extension:
        asked.append(link)
        return Extension(id="ext_demo", name="owner/demo-skills", source=link)

    monkeypatch.setattr(studio, "add_extension", add_extension)
    async with client_for(app) as client:
        _, phone = await paired(client)
        added = await client.post(
            "/studio/api/phone/plugins",
            json={"url": " https://github.com/owner/demo-skills "},
            headers=phone,
        )
        assert added.status_code == 200, added.text
        assert asked == ["https://github.com/owner/demo-skills"]

        repos = data(
            (await client.get("/studio/api/phone/plugins", headers=phone)).json()
        )["repos"]
        fcc = next(repo for repo in repos if repo["id"] == BUILTIN_ID)
        off = await client.post(
            f"/studio/api/phone/plugins/{fcc['id']}/switch",
            json={"on": False},
            headers=phone,
        )
        assert off.status_code == 200 and off.json()["enabled"] is False
        assert not (await studio._extensions.get(BUILTIN_ID)).enabled
        missing = await client.post(
            "/studio/api/phone/plugins/nope/switch", json={"on": True}, headers=phone
        )
        assert missing.status_code == 400

        helpers = data(
            (await client.get("/studio/api/phone/subagents", headers=phone)).json()
        )
        assert {"tester", "researcher"} <= {role["role"] for role in helpers["roles"]}
        made = await client.post(
            "/studio/api/phone/subagents",
            json={"name": "Checker", "role": "tester"},
            headers=phone,
        )
        assert made.status_code == 200, made.text
        checker = made.json()
        assert checker["active"] is True
        switched = await client.post(
            f"/studio/api/phone/subagents/{checker['id']}/switch",
            json={"on": False},
            headers=phone,
        )
        assert switched.status_code == 200 and switched.json()["active"] is False
        bad = await client.post(
            "/studio/api/phone/subagents",
            json={"name": "Wizard", "role": "wizard"},
            headers=phone,
        )
        assert bad.status_code == 400
        twice = await client.post(
            "/studio/api/phone/subagents",
            json={"name": "checker", "role": "tester"},
            headers=phone,
        )
        assert twice.status_code == 400
    await studio.shutdown()


@pytest.mark.asyncio
async def test_the_phone_hq_shows_the_team_and_talks_to_an_agent(make_studio):
    studio, _ = make_studio(["On it."])
    await studio.ensure_defaults()
    app = create_test_app(studio=studio)
    async with client_for(app) as client:
        _, phone = await paired(client)
        hq = data((await client.get("/studio/api/phone/hq", headers=phone)).json())
        names = {agent["name"] for agent in hq["agents"]}
        assert {"Jarvis", "Builder", "Researcher"} <= names
        jarvis = next(agent for agent in hq["agents"] if agent["main"])
        assert jarvis["station"] and "chat_id" not in jarvis
        assert {station["id"] for station in hq["stations"]} >= {"desk", "lounge"}
        assert "pending" not in hq, "approvals are answered on the PC"

        said = await client.post(
            f"/studio/api/phone/hq/agents/{jarvis['id']}/say",
            json={"text": "how is the team?"},
            headers=phone,
        )
        assert said.status_code == 202, said.text
        await asyncio.wait_for(studio.wait_for_background(), timeout=20)
        missing = await client.post(
            "/studio/api/phone/hq/agents/nope/say", json={"text": "hi"}, headers=phone
        )
        assert missing.status_code == 400
    await studio.shutdown()
