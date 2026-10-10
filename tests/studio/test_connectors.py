"""Connectors: outside services the team uses with a token (GitHub, Zapier,
email, a Discord webhook, ...), kept private and used through the mcp tool."""

import json
import stat
from email.message import EmailMessage

import httpx
import pytest

from free_claude_code.studio import connectors as connectors_module
from free_claude_code.studio import service as service_module
from free_claude_code.studio.connectors import (
    SECRET_SHOWN,
    ConnectorError,
    check_values,
    connector,
    mcp_server,
    webhook_body,
)
from free_claude_code.studio.llm import ToolCall
from free_claude_code.studio.mcp import McpManager
from free_claude_code.studio.tools import ToolContext
from tests.api.support import create_test_app

from .conftest import tool_reply

CONTEXT = ToolContext(agent_id="a", chat_id="c")
DISCORD = "https://discord.com/api/webhooks/1/abc"


async def use_mcp(studio, **arguments):
    return await studio._assistant_tool(
        ToolCall(id="1", name="mcp", arguments=arguments), CONTEXT
    )


def test_each_connector_checks_its_values_and_builds_its_server():
    github = connector("github")
    with pytest.raises(ConnectorError, match="needs Token"):
        check_values(github, {})
    server = mcp_server(github, check_values(github, {"token": " ghp_x ", "x": "y"}))
    assert server.url == "https://api.githubcopilot.com/mcp/"
    assert server.headers == {"Authorization": "Bearer ghp_x"}

    context7 = connector("context7")
    assert mcp_server(context7, check_values(context7, {})).headers == {}
    assert mcp_server(context7, {"token": "c7"}).headers == {"CONTEXT7_API_KEY": "c7"}

    supabase = connector("supabase")
    url = mcp_server(supabase, {"token": "t", "project_ref": "abc"}).url
    assert url == "https://mcp.supabase.com/mcp?read_only=true&project_ref=abc"

    with pytest.raises(ConnectorError, match="https://"):
        check_values(connector("webhook"), {"url": "http://example.com/hook"})
    email = connector("email")
    assert check_values(email, {"address": "me@gmail.com", "password": "p"}) == {
        "provider": "gmail",
        "address": "me@gmail.com",
        "password": "p",
    }
    with pytest.raises(ConnectorError, match="SMTP and IMAP"):
        check_values(email, {"provider": "other", "address": "a@b.c", "password": "p"})
    with pytest.raises(ConnectorError, match="must be one of"):
        check_values(email, {"provider": "aol", "address": "a@b.c", "password": "p"})
    with pytest.raises(ConnectorError, match="No connector"):
        connector("myspace")

    assert webhook_body(DISCORD, "hi") == {"content": "hi"}
    assert webhook_body("https://hooks.slack.com/services/x", "hi") == {"text": "hi"}


@pytest.mark.asyncio
async def test_tokens_stay_private_and_are_kept_when_left_as_shown(make_studio):
    studio, _ = make_studio([])
    saved = await studio.save_connector("github", {"token": "ghp_secret"})
    assert saved["connected"] and saved["fields"][0]["value"] == SECRET_SHOWN
    assert "ghp_secret" not in json.dumps(studio.connectors_view())

    path = studio._connectors._path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["connectors"]["github"]["token"] == "ghp_secret"

    await studio.save_connector("github", {"token": SECRET_SHOWN})
    await studio.save_connector("github", {"token": ""})
    assert studio._connectors.values("github")["token"] == "ghp_secret"
    await studio.save_connector("github", {"token": "ghp_new"})
    assert studio._connectors.values("github")["token"] == "ghp_new"

    await studio.remove_connector("github")
    assert "github" not in json.loads(path.read_text())["connectors"]
    with pytest.raises(ConnectorError, match="isn't connected"):
        await studio.test_connector("github")


GITHUB_TOOLS = [
    {
        "name": "get_me",
        "description": "Details about the signed-in user.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_issues",
        "description": "Issues in a repository.",
        "inputSchema": {
            "type": "object",
            "properties": {"repo": {"type": "string"}},
            "required": ["repo"],
        },
    },
]


def fake_github(seen: list[httpx.Request]):
    """A web MCP server like GitHub's: a token in a header, two tools."""

    def server(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers["authorization"] == "Bearer expired":
            return httpx.Response(401, text="unauthorized: token authentication failed")
        message = json.loads(request.content)
        if "id" not in message:
            return httpx.Response(202)
        result: dict = {}
        if message["method"] == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {}}
        elif message["method"] == "tools/list":
            result = {"tools": GITHUB_TOOLS}
        elif message["method"] == "tools/call":
            repo = message["params"]["arguments"]["repo"]
            result = {"content": [{"type": "text", "text": f"#1 Fix login in {repo}"}]}
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": message["id"], "result": result}
        )

    return server


@pytest.mark.asyncio
async def test_agents_use_a_web_connector_with_its_token(make_studio):
    seen: list[httpx.Request] = []
    studio, _ = make_studio([])
    studio._mcp = McpManager(transport=httpx.MockTransport(fake_github(seen)))
    await studio.save_connector("github", {"token": "ghp_x"})

    listed = await use_mcp(studio, action="servers")
    assert "- github [Connectors]" in listed.text
    tools = await use_mcp(studio, action="tools", server="github")
    assert "list_issues: Issues in a repository." in tools.text
    called = await use_mcp(
        studio,
        action="call",
        server="GitHub",
        tool="list_issues",
        arguments={"repo": "me/site"},
    )
    assert called.text == "#1 Fix login in me/site" and not called.failed
    # A guessed tool name gets the real ones back, so the next turn can fix it.
    guessed = await use_mcp(
        studio, action="call", server="github", tool="search", arguments={}
    )
    assert guessed.failed and "github has no tool 'search'" in guessed.text
    assert "- list_issues: Issues in a repository." in guessed.text
    same = await use_mcp(
        studio,
        action="call",
        server="github",
        tool="List_Issues",
        arguments={"repo": "me/app"},
    )
    assert same.text == "#1 Fix login in me/app"
    assert {r.headers["authorization"] for r in seen} == {"Bearer ghp_x"}

    tried = await studio.test_connector("github")
    assert tried == "Connected: 2 tools (get_me, list_issues)."

    await studio.save_connector("github", {"token": "expired"})
    with pytest.raises(ConnectorError, match="GitHub refused the token"):
        await studio.test_connector("github")


@pytest.mark.asyncio
async def test_naming_a_connected_service_shows_the_main_ai_its_tools(make_studio):
    studio, model = make_studio(["On it."])
    await studio.ensure_defaults()
    studio._mcp = McpManager(transport=httpx.MockTransport(fake_github([])))
    await studio.save_connector("github", {"token": "ghp_x"})
    await studio.save_connector("webhook", {"url": DISCORD})

    def last_note() -> str:
        return next(
            str(call["studio_note"])
            for call in reversed(model.calls)
            if call["studio_note"]
        )

    await studio.main_say(
        "which issues are open on GitHub for me/site?", background=False
    )
    note = last_note()
    assert "the MCP server you were asked about is on" in note
    # The tool that fits the message comes first.
    assert note.index("- list_issues: Issues") < note.index("- get_me:")
    assert "repo (required)" in note and "post_message" not in note

    # Research words don't send it to the Researcher: GitHub is the way.
    await studio.main_say(
        "look up on github which issues are open on me/site", background=False
    )
    assert "list_issues" in last_note()
    main_chat = await studio.main_chat()
    handed = [
        message
        for message in await studio._store.transcript(main_chat.id)
        if message.role == "tool" and message.data.get("tool") == "ask_agent"
    ]
    assert handed == []

    # 'Ask GitHub ...' reads like a job for an agent; the playbook shows the
    # mcp note instead, so the model isn't pushed to hand it out.
    await studio.main_say(
        "Ask the GitHub connector to find out which issues are open on me/site",
        background=False,
    )
    note = last_note()
    assert "MCP tool servers (mcp)" in note and "Give one agent a job" not in note

    await studio.main_say("tell my discord the site is live", background=False)
    note = last_note()
    assert "webhook:\n- post_message" in note and "list_issues" not in note

    model.calls.clear()
    await studio.main_say("what's the weather like?", background=False)
    assert all(
        "MCP server you were asked about" not in str(call["studio_note"])
        for call in model.calls
    )


@pytest.mark.asyncio
async def test_a_hand_off_goes_back_to_the_service_the_user_named(make_studio):
    studio, _ = make_studio(
        [
            tool_reply(
                "ask_agent",
                {"agent": "Researcher", "task": "Ask GitHub about me/site issues"},
            ),
            tool_reply(
                "mcp",
                {
                    "action": "call",
                    "server": "github",
                    "tool": "list_issues",
                    "arguments": {"repo": "me/site"},
                },
                call_id="call_2",
            ),
            "One issue is open: Fix login.",
        ]
    )
    await studio.ensure_defaults()
    studio._mcp = McpManager(transport=httpx.MockTransport(fake_github([])))
    await studio.save_connector("github", {"token": "ghp_x"})

    await studio.main_say(
        "Ask GitHub which issues are open on me/site", background=False
    )
    main_chat = await studio.main_chat()
    tools = [
        message
        for message in await studio._store.transcript(main_chat.id)
        if message.role == "tool"
    ]
    assert tools[0].data.get("redirected") == "mcp"
    assert "use github yourself" in tools[0].text
    assert tools[1].text == "#1 Fix login in me/site"
    assert not await studio.runs()
    # Only once: a later hand-off in another turn goes through as usual.
    assert main_chat.id not in studio._service_turns


@pytest.mark.asyncio
async def test_agents_post_to_a_discord_channel(make_studio):
    posts: list[dict] = []
    status = {"code": 204}

    def discord(request: httpx.Request) -> httpx.Response:
        posts.append(json.loads(request.content))
        return httpx.Response(status["code"])

    studio, _ = make_studio([])
    studio._connector_transport = httpx.MockTransport(discord)
    nothing = await use_mcp(studio, action="servers")
    assert "Connectors page" in nothing.text

    await studio.save_connector("webhook", {"url": DISCORD})
    listed = await use_mcp(studio, action="servers")
    assert listed.text == "MCP servers:\n- webhook [Connectors, built in]"
    tools = await use_mcp(studio, action="tools", server="webhook")
    assert "post_message" in tools.text and "text (the message)" in tools.text

    posted = await use_mcp(
        studio,
        action="call",
        server="webhook",
        tool="post_message",
        arguments={"text": "The bakery site is live."},
    )
    assert posted.text == "Posted." and posts == [
        {"content": "The bakery site is live."}
    ]
    assert await studio.test_connector("webhook") == "Posted a test message."
    wrong = await use_mcp(
        studio, action="call", server="webhook", tool="send", arguments={}
    )
    assert wrong.failed and "- post_message:" in wrong.text

    status["code"] = 404
    broken = await use_mcp(
        studio,
        action="call",
        server="webhook",
        tool="post_message",
        arguments={"text": "hi"},
    )
    assert broken.failed and "answered 404" in broken.text
    with pytest.raises(ConnectorError, match="didn't work"):
        await studio.test_connector("webhook")


class FakeImap:
    """An inbox with one unread mail."""

    def __init__(self, host: str, timeout: float) -> None:
        self.host = host

    def __enter__(self) -> FakeImap:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        assert (user, password) == ("me@gmail.com", "app-pass")

    def select(self, box: str, readonly: bool) -> None:
        assert readonly

    def search(self, charset: object, *criteria: str) -> tuple[str, list[bytes]]:
        assert criteria[0] == "UNSEEN"
        return "OK", [b"7"]

    def fetch(self, mail_id: bytes, parts: str) -> tuple[str, list[object]]:
        assert parts == "(BODY.PEEK[])"
        mail = EmailMessage()
        mail["From"] = "Ann <ann@example.com>"
        mail["Subject"] = "Cake order"
        mail["Date"] = "Fri, 10 Oct 2026 09:00:00 +0000"
        mail.set_content("Two   rye loaves\nfor Saturday, please.")
        return "OK", [(b"7 (BODY[] {1})", mail.as_bytes()), b")"]


@pytest.mark.asyncio
async def test_email_reads_the_inbox_and_sends_only_with_a_yes(
    make_studio, monkeypatch
):
    sent: list[EmailMessage] = []
    monkeypatch.setattr(connectors_module.imaplib, "IMAP4_SSL", FakeImap)
    monkeypatch.setattr(service_module, "send_now", lambda _, m: sent.append(m))
    monkeypatch.setattr(connectors_module, "send_now", lambda _, m: sent.append(m))
    studio, _ = make_studio([])
    await studio.save_connector(
        "email",
        {"provider": "gmail", "address": "me@gmail.com", "password": "app-pass"},
    )

    inbox = await use_mcp(
        studio, action="call", server="email", tool="read_inbox", arguments={}
    )
    assert "From: Ann <ann@example.com>" in inbox.text
    assert "Subject: Cake order" in inbox.text
    assert "Two rye loaves for Saturday, please." in inbox.text
    assert await studio.test_connector("email") == "Signed in to me@gmail.com."

    written = await use_mcp(
        studio,
        action="call",
        server="email",
        tool="send_email",
        arguments={"to": "ann@example.com", "subject": "Re: Cake", "body": "Yes!"},
    )
    assert "saved for the user to approve" in written.text and not sent
    drafts = studio.connectors_view()["drafts"]
    assert [(d["to"], d["body"]) for d in drafts] == [("ann@example.com", "Yes!")]
    desk = await studio.hq()
    approvals = next(s for s in desk["stations"] if s["id"] == "approvals")
    assert desk["drafts"] == 1 and approvals["count"] == 1
    assert approvals["note"] == "1 email draft(s) waiting for your yes"

    assert await studio.send_draft(drafts[0]["id"]) == "Sent to ann@example.com."
    assert sent[0]["To"] == "ann@example.com" and sent[0]["From"] == "me@gmail.com"
    assert studio.connectors_view()["drafts"] == []
    with pytest.raises(ConnectorError, match="gone"):
        await studio.send_draft(drafts[0]["id"])

    # A failed send keeps the draft for another try.
    def refuse(*_: object) -> None:
        raise OSError("no route to host")

    await use_mcp(
        studio,
        action="call",
        server="email",
        tool="send_email",
        arguments={"to": "bo@example.com", "body": "Hi"},
    )
    monkeypatch.setattr(service_module, "send_now", refuse)
    draft_id = studio.connectors_view()["drafts"][0]["id"]
    with pytest.raises(ConnectorError, match="didn't send"):
        await studio.send_draft(draft_id)
    kept = studio.connectors_view()["drafts"]
    assert [d["to"] for d in kept] == ["bo@example.com"]
    studio.discard_draft(kept[0]["id"])
    assert studio.connectors_view()["drafts"] == []

    await studio.save_connector(
        "email",
        {"provider": "gmail", "address": "me@gmail.com", "send_without_asking": "yes"},
    )
    straight = await use_mcp(
        studio,
        action="call",
        server="email",
        tool="send_email",
        arguments={"to": "cy@example.com", "body": "Done."},
    )
    assert straight.text == "Sent to cy@example.com."
    assert sent[-1]["To"] == "cy@example.com"


@pytest.mark.asyncio
async def test_the_connectors_page_api(make_studio):
    studio, _ = make_studio([])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_test_app(studio=studio)),
        base_url="http://127.0.0.1",
    ) as client:
        listed = (await client.get("/studio/api/connectors")).json()
        ids = [item["id"] for item in listed["connectors"]]
        assert ids[:2] == ["zapier", "github"] and "email" in ids
        assert listed["drafts"] == []

        missing = await client.put("/studio/api/connectors/zapier", json={"values": {}})
        assert missing.status_code == 400 and "needs Token" in missing.json()["detail"]
        unknown = await client.put("/studio/api/connectors/nope", json={"values": {}})
        assert unknown.status_code == 400

        saved = await client.put(
            "/studio/api/connectors/zapier", json={"values": {"token": "zap-secret"}}
        )
        assert saved.status_code == 200 and saved.json()["connected"]
        page = await client.get("/studio/api/connectors")
        assert "zap-secret" not in page.text and SECRET_SHOWN in page.text

        off = await client.post("/studio/api/connectors/email/test")
        assert off.json() == {
            "ok": False,
            "message": "Email (built in) isn't connected.",
        }
        gone = await client.post("/studio/api/connectors/drafts/drf_x/send")
        assert gone.status_code == 400
        assert (
            await client.delete("/studio/api/connectors/drafts/drf_x")
        ).status_code == 400

        removed = await client.delete("/studio/api/connectors/zapier")
        zapier = next(c for c in removed.json()["connectors"] if c["id"] == "zapier")
        assert not zapier["connected"]
