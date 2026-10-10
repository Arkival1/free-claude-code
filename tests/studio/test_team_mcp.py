"""The team as an MCP server at /mcp, for Claude Code, Codex, Cursor, Gemini
CLI, VS Code, Cline, Goose, and any other tool that speaks MCP."""

import asyncio

import httpx
import pytest

from free_claude_code.studio.teamplan import PLANNER_SYSTEM
from tests.api.support import create_test_app

from .conftest import tool_reply


def rpc(method: str, params: dict | None = None, message_id: int = 1) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


async def call(client: httpx.AsyncClient, name: str, **arguments) -> tuple[str, bool]:
    response = await client.post(
        "/mcp", json=rpc("tools/call", {"name": name, "arguments": arguments})
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    return result["content"][0]["text"], result["isError"]


def client_for(studio) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    )


@pytest.mark.asyncio
async def test_an_mcp_client_connects_and_sees_the_team_tools(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    async with client_for(studio) as client:
        hello = await client.post(
            "/mcp",
            json=rpc(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "claude-code", "version": "1"},
                },
            ),
        )
        result = hello.json()["result"]
        assert result["protocolVersion"] == "2025-03-26"
        assert result["capabilities"] == {"tools": {"listChanged": False}}
        assert result["serverInfo"]["name"] == "lcc-studio"
        assert "lcc_plan" in result["instructions"]

        ready = await client.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert ready.status_code == 202 and not ready.content

        tools = (await client.post("/mcp", json=rpc("tools/list"))).json()["result"]
        names = [tool["name"] for tool in tools["tools"]]
        assert names == [
            "lcc_team",
            "lcc_chat",
            "lcc_ask",
            "lcc_plan",
            "lcc_status",
            "lcc_stop",
            "lcc_projects",
            "lcc_files",
            "lcc_read",
        ]
        assert all(tool["inputSchema"]["type"] == "object" for tool in tools["tools"])

        team, failed = await call(client, "lcc_team")
        assert not failed and "- Builder (builder, free" in team
        # Each agent gets a line, not its whole instructions.
        assert all(len(line) < 260 for line in team.splitlines())


@pytest.mark.asyncio
async def test_an_mcp_client_gives_an_agent_a_job_and_reads_the_result(make_studio):
    def respond(system: str, prompt: str):
        if "Write a haiku" in prompt:
            return tool_reply("finish", {"summary": "Warm bread at sunrise."})
        return "ok"

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    site = await studio.create_site(name="Bakery")
    await studio.workspace.write(site.id, "index.html", "<h1>Joe's Bakery</h1>")
    async with client_for(studio) as client:
        report, failed = await call(
            client, "lcc_ask", agent="helper", task="Write a haiku about bread"
        )
        assert not failed and report.startswith("Helper succeeded")
        assert "Warm bread at sunrise." in report
        task_id = report.split("(task ")[1].split(")")[0]
        status, _ = await call(client, "lcc_status", task_id=task_id)
        assert "succeeded" in status and "Warm bread" in status

        listed, _ = await call(client, "lcc_projects")
        assert "Bakery" in listed
        files, _ = await call(client, "lcc_files", project="bakery")
        assert "index.html" in files
        page, _ = await call(client, "lcc_read", project="Bakery", path="index.html")
        assert page == "<h1>Joe's Bakery</h1>"

        nobody, failed = await call(client, "lcc_ask", agent="Wizard", task="x")
        assert failed and "No agent called 'Wizard'" in nobody and "Builder" in nobody
        missing, failed = await call(client, "lcc_read", project="Nope", path="a")
        assert failed and "No project called 'Nope'" in missing


@pytest.mark.asyncio
async def test_an_mcp_client_runs_a_team_plan(make_studio):
    def respond(system: str, prompt: str):
        if system == PLANNER_SYSTEM:
            return (
                '[{"agent": "Researcher", "do": "find rye prices"},'
                ' {"agent": "Helper", "do": "write the price list", "needs": ["s1"]}]'
            )
        return tool_reply("finish", {"summary": "Rye: $6."})

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    async with client_for(studio) as client:
        started, failed = await call(client, "lcc_plan", goal="A rye price list")
        assert not failed and "started with 2 step(s)" in started
        assert "s2. Helper: write the price list (after s1)" in started
        plan_id = started.split("Plan ")[1].split(" ")[0]
        await asyncio.wait_for(studio.wait_for_background(), timeout=20)
        status, _ = await call(client, "lcc_status", plan_id=plan_id)
        assert "is done: 2 of 2 step(s) done" in status
        team, _ = await call(client, "lcc_status")
        assert "Builder" in team


@pytest.mark.asyncio
async def test_batches_errors_and_other_methods(make_studio):
    studio, _ = make_studio([])
    async with client_for(studio) as client:
        batch = await client.post(
            "/mcp",
            json=[
                rpc("ping", message_id=7),
                {"jsonrpc": "2.0", "method": "notifications/cancelled"},
            ],
        )
        assert batch.json() == [{"jsonrpc": "2.0", "id": 7, "result": {}}]
        unknown = (await client.post("/mcp", json=rpc("resources/list"))).json()
        assert unknown["error"]["code"] == -32601
        bad_tool = (
            await client.post("/mcp", json=rpc("tools/call", {"name": "rm_rf"}))
        ).json()
        assert bad_tool["error"]["code"] == -32602
        not_json = await client.post("/mcp", content=b"{nope")
        assert (
            not_json.status_code == 400 and not_json.json()["error"]["code"] == -32700
        )
        assert (await client.get("/mcp")).status_code == 405


@pytest.mark.asyncio
async def test_other_websites_and_a_switched_off_server_are_refused(make_studio):
    studio, _ = make_studio([])
    async with client_for(studio) as client:
        evil = await client.post(
            "/mcp", json=rpc("ping"), headers={"origin": "https://evil.example"}
        )
        assert evil.status_code == 403
        local = await client.post(
            "/mcp", json=rpc("ping"), headers={"origin": "http://localhost:3000"}
        )
        assert local.status_code == 200

    off, _ = make_studio([], STUDIO_MCP_SERVER=False)
    async with client_for(off) as client:
        refused = await client.post("/mcp", json=rpc("ping"))
        assert refused.status_code == 403
        assert "turned off" in refused.json()["error"]["message"]
