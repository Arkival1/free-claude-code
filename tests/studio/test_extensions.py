"""Skills, agents, commands, and MCP servers added from GitHub."""

import io
import json
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio.extensions import (
    ExtensionError,
    ExtensionLibrary,
    front_matter,
    parse_link,
)
from free_claude_code.studio.llm import LLMReply, ToolCall
from free_claude_code.studio.tools import ToolContext
from tests.api.support import create_test_app

FAKE_SERVER = """
import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message["method"]
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fake", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "shout", "description": "Say it louder.",
                  "inputSchema": {"type": "object", "properties": {
                      "text": {"type": "string", "description": "What to shout."}},
                      "required": ["text"]}}]}
    elif method == "tools/call":
        said = message["params"]["arguments"]["text"]
        result = {"content": [{"type": "text", "text": said.upper() + "!"}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
"""


def repo_zip(files: dict[str, str], top: str = "repo-main") -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for path, text in files.items():
            archive.writestr(f"{top}/{path}", text)
        archive.writestr(f"{top}/../evil.txt", "nope")
    return data.getvalue()


PLUGIN = {
    ".claude-plugin/plugin.json": json.dumps(
        {
            "name": "helpers",
            "description": "Handy helpers.",
            "mcpServers": {
                "shouter": {
                    "command": sys.executable,
                    "args": ["${CLAUDE_PLUGIN_ROOT}/server.py"],
                }
            },
        }
    ),
    "server.py": FAKE_SERVER,
    "skills/pdf/SKILL.md": "---\nname: pdf\ndescription: Read and fill PDF forms.\n---\n# PDF\nUse pypdf to read forms.",
    "agents/reviewer.md": "---\nname: reviewer\ndescription: Reviews code.\ntools: Read, Grep, Bash\n---\nYou review code carefully.",
    "commands/deploy.md": "---\ndescription: Ship the site.\n---\nBuild, then upload the dist folder.",
    ".mcp.json": json.dumps(
        {"mcpServers": {"web": {"url": "https://mcp.example/mcp"}}}
    ),
}


def github(files: dict[str, str], seen: list[str] | None = None) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        if "codeload.github.com/owner/missing" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=repo_zip(files))

    return httpx.MockTransport(answer)


@pytest.mark.parametrize(
    ("link", "name", "url"),
    [
        (
            "https://github.com/owner/repo",
            "owner/repo",
            "https://codeload.github.com/owner/repo/zip/HEAD",
        ),
        (
            "github.com/owner/repo.git",
            "owner/repo",
            "https://codeload.github.com/owner/repo/zip/HEAD",
        ),
        ("owner/repo", "owner/repo", "https://codeload.github.com/owner/repo/zip/HEAD"),
        (
            "https://github.com/owner/repo/tree/dev/plugins/x",
            "owner/repo/plugins/x",
            "https://codeload.github.com/owner/repo/zip/dev",
        ),
    ],
)
def test_github_links_are_read(link, name, url):
    repo = parse_link(link)
    assert repo.name == name and repo.zip_url == url


def test_a_non_github_link_is_refused():
    with pytest.raises(ExtensionError):
        parse_link("https://example.com/thing")


def test_front_matter_reads_folded_lines():
    values, body = front_matter("---\nname: x\ndescription: >\n  one\n  two\n---\nBody")
    assert values == {"name": "x", "description": "one two"} and body == "Body"


@pytest.mark.asyncio
async def test_a_plugin_repo_brings_everything(tmp_path):
    library = ExtensionLibrary(tmp_path / "ext", transport=github(PLUGIN))

    added = await library.add_github("https://github.com/owner/repo")

    assert added.plugins == ["helpers"] and added.description == "Handy helpers."
    assert {(s.name, s.kind) for s in added.skills} == {
        ("pdf", "skill"),
        ("/deploy", "command"),
    }
    [reviewer] = added.agents
    assert reviewer.tools == ["Read", "Grep", "Bash"] and "carefully" in reviewer.prompt
    servers = {server.name: server for server in added.servers}
    assert set(servers) == {"shouter", "web"}
    assert not any(server.enabled for server in added.servers), (
        "off until the user says"
    )
    assert "${CLAUDE_PLUGIN_ROOT}" not in servers["shouter"].args[0]
    assert servers["web"].transport == "http"
    assert not (tmp_path / "ext" / added.id / "evil.txt").exists()
    assert [item.id for item in await library.all()] == [added.id]


@pytest.mark.asyncio
async def test_a_plain_repo_becomes_a_skill_from_its_readme(tmp_path):
    library = ExtensionLibrary(
        tmp_path / "ext",
        transport=github({"README.md": "# Tidy CSS\nTips for tidy CSS."}),
    )
    added = await library.add_github("owner/tidy")
    [skill] = added.skills
    assert skill.kind == "readme" and skill.description == "Tidy CSS"
    assert "Tips for tidy CSS" in await library.skill_text(added, skill)


@pytest.mark.asyncio
async def test_a_missing_repo_says_so(tmp_path):
    library = ExtensionLibrary(tmp_path / "ext", transport=github(PLUGIN))
    with pytest.raises(ExtensionError, match="no public repo owner/missing"):
        await library.add_github("owner/missing")


@pytest.mark.asyncio
async def test_agents_use_skills_and_switched_on_mcp_servers(make_studio):
    studio, _ = make_studio([])
    studio._extensions._transport = github(PLUGIN)
    added = await studio.add_extension("https://github.com/owner/repo")
    context = ToolContext(agent_id="a", chat_id="c")

    listed = await studio._assistant_tool(
        ToolCall(id="1", name="skill", arguments={"action": "list"}), context
    )
    assert "pdf: Read and fill PDF forms." in listed.text
    read = await studio._assistant_tool(
        ToolCall(id="2", name="skill", arguments={"action": "read", "name": "pdf"}),
        context,
    )
    assert "Use pypdf" in read.text

    off = await studio._assistant_tool(
        ToolCall(id="3", name="mcp", arguments={"action": "servers"}), context
    )
    assert "No MCP servers are switched on" in off.text

    await studio.switch_server(added.id, "shouter", on=True)
    try:
        tools = await studio._assistant_tool(
            ToolCall(
                id="4", name="mcp", arguments={"action": "tools", "server": "shouter"}
            ),
            context,
        )
        assert "shout: Say it louder." in tools.text and "text (required)" in tools.text
        shouted = await studio._assistant_tool(
            ToolCall(
                id="5",
                name="mcp",
                arguments={
                    "action": "call",
                    "server": "shouter",
                    "tool": "shout",
                    "arguments": {"text": "hello"},
                },
            ),
            context,
        )
        assert shouted.text == "HELLO!" and not shouted.failed
    finally:
        await studio.shutdown()


@pytest.mark.asyncio
async def test_a_plugin_agent_joins_the_team_with_studio_tools(make_studio):
    studio, _ = make_studio([])
    studio._extensions._transport = github(PLUGIN)
    added = await studio.add_extension("owner/repo")

    agent = await studio.add_extension_agent(added.id, "reviewer")

    assert agent.name == "reviewer" and agent.system_prompt.startswith("You review")
    assert {"read_file", "search_files", "run_command", "skill", "mcp"} <= set(
        agent.tools
    )


@pytest.mark.asyncio
async def test_jarvis_has_the_new_tools(make_studio):
    studio, model = make_studio(lambda system, prompt: LLMReply(text="Hi."))
    await studio.ensure_defaults()
    await studio.main_say("hello", background=False)
    assert {"skill", "mcp", "code_and_test"} <= set(model.calls[-1]["tools"])


@pytest.mark.asyncio
async def test_extensions_through_the_routes(make_studio, tmp_path: Path):
    studio, _ = make_studio([])
    studio._extensions._transport = github(PLUGIN)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            added = await client.post(
                "/studio/api/extensions", json={"url": "https://github.com/owner/repo"}
            )
            assert added.status_code == 200
            body = added.json()
            assert len(body["skills"]) == 2 and body["agents"][0]["name"] == "reviewer"
            ext_id = body["id"]
            switched = await client.post(
                f"/studio/api/extensions/{ext_id}/servers/shouter", json={"on": True}
            )
            assert [
                s["enabled"]
                for s in switched.json()["servers"]
                if s["name"] == "shouter"
            ] == [True]
            checked = await client.post(
                f"/studio/api/extensions/{ext_id}/servers/shouter/check"
            )
            assert checked.status_code == 200
            assert [tool["name"] for tool in checked.json()["tools"]] == ["shout"]
            by_hand = await client.post(
                "/studio/api/extensions/servers",
                json={
                    "name": "files",
                    "command": "npx -y @modelcontextprotocol/server-filesystem /tmp",
                },
            )
            server = by_hand.json()["servers"][0]
            assert server["enabled"] and server["shown"].startswith("npx -y")
            bad = await client.post(
                "/studio/api/extensions", json={"url": "not a link"}
            )
            assert bad.status_code == 400
            gone = await client.delete(f"/studio/api/extensions/{ext_id}")
            assert gone.json() == {"removed": True}
            left = (await client.get("/studio/api/extensions")).json()["extensions"]
            assert [item["name"] for item in left] == ["Added by hand"]
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
