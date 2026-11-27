import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from free_claude_code.application.orb import (
    McpError,
    McpServerSpec,
    McpStdioClient,
    McpToolbox,
    OrbBrain,
    OrbStudio,
    select_tools,
)
from free_claude_code.application.orb.brain import clean_reply
from free_claude_code.application.orb.studio import SpeechInbox, bundled_skills
from free_claude_code.application.orb.toolbox import load_server_specs

FAKE_SERVER = str(Path(__file__).with_name("fake_mcp_server.py"))


def fake_spec(name: str = "jarvis") -> McpServerSpec:
    return McpServerSpec(name=name, command=sys.executable, args=("-u", FAKE_SERVER))


@pytest.fixture
def toolbox():
    box = McpToolbox([fake_spec()])
    yield box
    box.close()


class FakeLmStudio:
    """Scripted OpenAI-compatible LM Studio answers."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v0/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "text-embed", "type": "embeddings", "state": "loaded"},
                        {"id": "other", "type": "llm", "state": "not-loaded"},
                        {"id": "qwen3.5-4b", "type": "llm", "state": "loaded"},
                    ]
                },
            )
        body = json.loads(request.content)
        self.requests.append(body)
        answer = self.answers.pop(0) if self.answers else {"content": "ok"}
        return httpx.Response(200, json={"choices": [{"message": answer}]})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def tool_call(name: str, args: dict, call_id: str = "c1") -> dict:
    return {
        "content": "<think>planning</think>",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def make_brain(lm: FakeLmStudio, box, **kw) -> OrbBrain:
    return OrbBrain(
        base_url="http://127.0.0.1:1234/v1",
        toolbox=box,
        skills="You are JARVIS.",
        http=lm.client(),
        clock=lambda: datetime(2026, 11, 27, 20, 15),
        **kw,
    )


def test_stdio_client_lists_and_calls_tools_and_ignores_banner():
    client = McpStdioClient(fake_spec())
    client.start()
    try:
        assert client.server_info == {"name": "fake"}
        names = [t["name"] for t in client.list_tools()]
        assert names == [
            "memory_offload",
            "memory_resume",
            "weather_lookup",
            "desktop_click",
        ]
        assert client.call_tool("weather_lookup", {"city": "Leeds"}) == "Sunny in Leeds"
        assert client.call_tool("desktop_click", {}) == "ERROR: no screen"
        with pytest.raises(McpError, match="nope"):
            client.request("resources/list", {})
    finally:
        client.close()
    assert not client.alive


def test_stdio_client_reports_missing_program():
    client = McpStdioClient(McpServerSpec(name="ghost", command="no-such-program-xyz"))
    with pytest.raises(McpError, match="Could not start tool server 'ghost'"):
        client.start()


def test_load_server_specs_reads_lmstudio_mcp_json(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "jarvis-clean-v3": {
                        "command": "C:/JARVIS/.venv/Scripts/python.exe",
                        "args": ["server.py"],
                        "env": {"PYTHONUTF8": "1"},
                        "cwd": "C:/JARVIS",
                    },
                    "remote": {"url": "https://example.invalid/mcp"},
                }
            }
        ),
        encoding="utf-8",
    )
    specs, skipped = load_server_specs(path)
    assert specs == [
        McpServerSpec(
            name="jarvis-clean-v3",
            command="C:/JARVIS/.venv/Scripts/python.exe",
            args=("server.py",),
            env={"PYTHONUTF8": "1"},
            cwd="C:/JARVIS",
        )
    ]
    assert skipped == ["remote: only local (command) servers are supported"]


def test_toolbox_without_lmstudio_config_has_no_tools(tmp_path):
    box = McpToolbox.from_lmstudio([tmp_path / "missing.json"])
    assert box.tools() == []
    assert "not found" in box.problems[0]
    assert box.call("anything", {}).startswith("ERROR")


def test_select_tools_keeps_memory_tools_and_matches_the_request():
    tools = [
        {"name": "memory_recall", "description": "search memory"},
        {"name": "weather_lookup", "description": "Get the weather forecast"},
        {"name": "desktop_click", "description": "Click a button"},
        {"name": "video_notes", "description": "Make notes from a YouTube video"},
    ]
    picked = [t["name"] for t in select_tools(tools, "What's the weather forecast?")]
    assert picked == ["memory_recall", "weather_lookup"]
    picked = [t["name"] for t in select_tools(tools, "notes from this youtube video")]
    assert picked == ["memory_recall", "video_notes"]
    assert len(select_tools(tools, "click weather video", limit=2)) == 2


def test_clean_reply_drops_thinking():
    assert clean_reply("<think>hmm</think> Hello sir.") == "Hello sir."
    assert clean_reply("reasoning only</think>Answer") == "Answer"


def test_brain_uses_loaded_model_runs_tools_and_resumes_memory(toolbox):
    lm = FakeLmStudio(
        [
            tool_call("weather_lookup", {"city": "Leeds"}),
            {"content": "Sunny in Leeds, sir."},
        ]
    )
    brain = make_brain(lm, toolbox)
    reply = brain.ask("What's the weather forecast in Leeds?")
    assert reply.text == "Sunny in Leeds, sir."
    assert reply.tools_used == ["weather_lookup"]
    assert reply.model == "qwen3.5-4b"
    first = lm.requests[0]
    assert first["model"] == "qwen3.5-4b"
    offered = [t["function"]["name"] for t in first["tools"]]
    assert "weather_lookup" in offered and "desktop_click" not in offered
    system = first["messages"][0]["content"]
    assert "You are JARVIS." in system and "Owner's name is Spawn" in system
    assert "Friday 27 November 2026" in system
    tool_message = lm.requests[1]["messages"][-1]
    assert tool_message == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": "Sunny in Leeds",
    }


def test_brain_reports_bad_tool_arguments_to_the_model(toolbox):
    bad = tool_call("weather_lookup", {})
    bad["tool_calls"][0]["function"]["arguments"] = "{not json"
    lm = FakeLmStudio([bad, {"content": "Sorry."}])
    reply = make_brain(lm, toolbox).ask("weather?")
    assert reply.text == "Sorry."
    assert "not valid JSON" in lm.requests[1]["messages"][-1]["content"]


def test_brain_compacts_old_turns_into_obsidian_memory(toolbox):
    lm = FakeLmStudio([])
    brain = make_brain(lm, toolbox, context_tokens=2000)
    for i in range(6):
        lm.answers.append({"content": f"Answer {i} " + "detail " * 40})
        brain.ask(f"Question {i} " + "words " * 40)
    assert any(m["role"] == "user" for m in brain.history)
    assert "Question 0" not in json.dumps(brain.history)
    assert brain.memory_note  # summary kept in the prompt
    saved = toolbox.call("memory_offload", {"title": "probe"})
    assert "saved)" in saved and not saved.startswith("Saved note 'probe' (1 saved)")


def test_brain_new_conversation_saves_to_vault(toolbox):
    lm = FakeLmStudio(
        [{"content": "Noted."}, {"content": "## Facts about the owner\nLikes tea"}]
    )
    brain = make_brain(lm, toolbox)
    brain.ask("Remember I like tea")
    saved = brain.new_conversation()
    assert saved.startswith("Saved note 'Orb conversation 2026-11-27 20:15'")
    assert brain.history == []
    assert "Likes tea" in brain.memory_note


def test_brain_explains_when_lmstudio_is_off(toolbox):
    def refuse(request):
        raise httpx.ConnectError("refused")

    brain = OrbBrain(
        base_url="http://127.0.0.1:1234/v1",
        toolbox=toolbox,
        skills="",
        model="qwen",
        http=httpx.Client(transport=httpx.MockTransport(refuse)),
    )
    brain.resumed = True
    with pytest.raises(RuntimeError, match="Open LM Studio"):
        brain.ask("hi")


def test_speech_inbox_returns_only_new_items():
    inbox = SpeechInbox(keep=3)
    first = inbox.say("one")
    inbox.say("two", source="lmstudio")
    assert [i["text"] for i in inbox.after(first)] == ["two"]
    for n in range(5):
        inbox.say(str(n))
    assert len(inbox.after(0)) == 3 and inbox.last_id == 7


def test_bundled_skills_teach_voice_and_obsidian_memory():
    skills = bundled_skills()
    assert "read aloud" in skills
    assert "memory_offload" in skills and "memory_recall" in skills


def test_studio_status_before_and_after_first_use(toolbox):
    lm = FakeLmStudio([{"content": "Hello."}])
    studio = OrbStudio(
        lambda: "http://127.0.0.1:1234/v1",
        toolbox_factory=lambda: toolbox,
        brain_factory=lambda **kw: OrbBrain(**kw, http=lm.client()),
    )
    assert studio.status()["started"] is False
    assert studio.ask("hi").text == "Hello."
    status = studio.status()
    assert (
        status["started"] and status["turns"] == 1 and status["servers"] == ["jarvis"]
    )
    assert status["has_memory"] is True


def test_tool_text_unwraps_jarvis_results():
    from free_claude_code.application.orb.brain import tool_text

    assert tool_text('{"ok": true, "result": "Owner likes tea"}') == "Owner likes tea"
    assert tool_text('{"ok": false, "error": "Permission files disabled"}') == (
        "ERROR: Permission files disabled"
    )
    assert tool_text('{"ok": true, "result": {"saved": "x.md"}}') == '{"saved": "x.md"}'
    assert tool_text("plain words") == "plain words"
    assert tool_text('["not", "jarvis"]') == '["not", "jarvis"]'
