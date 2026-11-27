import json

import httpx

from free_claude_code.application.orb import Advisor, OrbBrain, OrbStudio, ToolCatalog
from free_claude_code.application.orb.advisor import (
    ADVISOR_TOOLS,
    fcc_messages_sender,
)

TOOLS = [
    {
        "name": "video_to_notes",
        "description": "Make Obsidian notes from a YouTube video. Runs in the background.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}, "language": {"type": "string"}},
            "required": ["url"],
        },
    },
    {"name": "job_status", "description": "Check a background job.", "inputSchema": {}},
    {"name": "memory_recall", "description": "Search the owner's memory notes."},
]


class SpyToolbox:
    """Records any attempt to RUN a tool. The advisor must never cause one."""

    def __init__(self):
        self.calls = []

    def tools(self):
        return TOOLS

    def has(self, suffix):
        return None

    def call(self, name, arguments):
        self.calls.append(name)
        return "tool ran"


def scripted(replies, seen):
    replies = list(replies)

    def send(body):
        seen.append(json.loads(json.dumps(body)))
        return replies.pop(0)

    return send


def test_catalog_is_a_read_only_copy_with_search_and_describe():
    tools = json.loads(json.dumps(TOOLS))
    catalog = ToolCatalog(tools)
    tools[0]["description"] = "changed"
    assert catalog.search("youtube notes").startswith(
        "video_to_notes: Make Obsidian notes"
    )
    assert "url (string) required" in catalog.describe("video_to_notes")
    assert "language (string)" in catalog.describe("video_to_notes")
    assert "no tool called" in catalog.describe("format_disk")
    assert catalog.search("zzz") == "No matching tools. Try other keywords."


def test_advisor_can_only_look_up_tools_never_run_them():
    seen = []
    send = scripted(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "1",
                        "name": "search_tools",
                        "input": {"query": "youtube"},
                    },
                    {
                        "type": "tool_use",
                        "id": "2",
                        "name": "memory_recall",
                        "input": {"query": "owner"},
                    },
                    {
                        "type": "tool_use",
                        "id": "3",
                        "name": "video_to_notes",
                        "input": {"url": "x"},
                    },
                ]
            },
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "4",
                        "name": "describe_tool",
                        "input": {"name": "video_to_notes"},
                    }
                ]
            },
            {
                "content": [
                    {
                        "type": "text",
                        "text": "Call video_to_notes with the url, then job_status.",
                    }
                ]
            },
        ],
        seen,
    )
    toolbox = SpyToolbox()
    advice = Advisor(send, model="claude-sonnet").advise(
        "How do I make notes from a video?", ToolCatalog(toolbox.tools())
    )
    assert advice.startswith("ADVICE (from the advisor; you decide what to do):")
    assert "video_to_notes" in advice
    assert toolbox.calls == []  # nothing was ever executed
    results = {r["tool_use_id"]: r for r in seen[1]["messages"][-1]["content"]}
    assert results["1"]["content"].startswith("video_to_notes")
    for refused in ("2", "3"):
        assert results[refused]["is_error"] is True
        assert results[refused]["content"].startswith("Refused")
    # Only the two lookups are ever offered, and only JARVIS's question is sent.
    for body in seen:
        assert [t["name"] for t in body.get("tools", ADVISOR_TOOLS)] == [
            "search_tools",
            "describe_tool",
        ]
        assert body["model"] == "claude-sonnet"
    assert seen[0]["messages"] == [
        {"role": "user", "content": "How do I make notes from a video?"}
    ]


def test_advisor_stops_after_limited_rounds():
    seen = []
    loop = {
        "content": [
            {
                "type": "tool_use",
                "id": "x",
                "name": "search_tools",
                "input": {"query": "a"},
            }
        ]
    }
    send = scripted(
        [loop] * 4 + [{"content": [{"type": "text", "text": "done"}]}], seen
    )
    assert (
        Advisor(send, model="m", max_rounds=4)
        .advise("q", ToolCatalog(TOOLS))
        .endswith("done")
    )
    assert "tools" not in seen[-1]  # final round cannot look anything up
    assert len(seen) == 5


def test_brain_offers_advisor_only_when_on_and_never_shares_memory(tmp_path):
    requests = []
    answers = [
        {
            "tool_calls": [
                {
                    "id": "a",
                    "type": "function",
                    "function": {
                        "name": "ask_advisor",
                        "arguments": json.dumps(
                            {"question": "best tool for video notes?"}
                        ),
                    },
                }
            ]
        },
        {"content": "Using video_to_notes, sir."},
        {"content": "Hello."},
    ]

    def lm(request):
        if request.url.path.endswith("/api/v0/models"):
            return httpx.Response(
                200, json={"data": [{"id": "q", "type": "llm", "state": "loaded"}]}
            )
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": answers.pop(0)}]})

    toolbox = SpyToolbox()
    advisor_seen = []
    studio = OrbStudio(
        lambda: "http://127.0.0.1:1234/v1",
        toolbox_factory=lambda: toolbox,
        brain_factory=lambda **kw: OrbBrain(
            **kw, http=httpx.Client(transport=httpx.MockTransport(lm))
        ),
        advisor_sender=lambda: scripted(
            [{"content": [{"type": "text", "text": "Use video_to_notes."}]}],
            advisor_seen,
        ),
    )
    assert studio.advise("anything").startswith("ERROR: the advisor is off")
    studio.brain().memory_note = "SECRET: owner's bank is X"
    studio.set_local_only(False)
    studio.set_advisor("claude-sonnet")
    reply = studio.ask("Make notes from my video")
    assert reply.text == "Using video_to_notes, sir." and reply.tools_used == [
        "ask_advisor"
    ]
    assert "ask_advisor" in [t["function"]["name"] for t in requests[0]["tools"]]
    assert "Use video_to_notes." in requests[1]["messages"][-1]["content"]
    assert toolbox.calls == []
    assert "SECRET" not in json.dumps(advisor_seen)
    assert "Make notes from my video" not in json.dumps(advisor_seen)
    studio.set_advisor(None)
    studio.ask("hi")
    assert "ask_advisor" not in [
        t["function"]["name"] for t in requests[2].get("tools", [])
    ]
    assert studio.status()["advisor_model"] is None


def test_sender_uses_fcc_messages_endpoint():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    send = fcc_messages_sender(
        "http://127.0.0.1:8082/",
        "freecc",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert send({"model": "m"}) == {"content": [{"type": "text", "text": "ok"}]}
    assert str(seen[0].url) == "http://127.0.0.1:8082/v1/messages"
    assert seen[0].headers["x-api-key"] == "freecc"
