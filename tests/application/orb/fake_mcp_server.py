"""A tiny stdio MCP server used by the orb tests (stands in for jarvis-clean-v3)."""

import json
import sys

TOOLS = [
    {
        "name": "memory_offload",
        "description": "Save a memory note into the Obsidian vault.",
        "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}},
    },
    {
        "name": "memory_resume",
        "description": "Reload recent memory notes.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
    {
        "name": "weather_lookup",
        "description": "Get the weather forecast for a city.",
        "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}},
    },
    {
        "name": "desktop_click",
        "description": "Click a button on the screen.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]
saved = []


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


print("stray startup banner that is not JSON", flush=True)
for line in sys.stdin:
    request = json.loads(line)
    method, rid = request.get("method"), request.get("id")
    if rid is None:
        continue
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {"serverInfo": {"name": "fake"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = request["params"]["name"]
        args = request["params"]["arguments"]
        if name == "memory_offload":
            saved.append(args)
            text = f"Saved note '{args.get('title')}' ({len(saved)} saved)"
        elif name == "memory_resume":
            text = "Owner's name is Spawn. Project: JARVIS orb."
        elif name == "weather_lookup":
            text = f"Sunny in {args.get('city')}"
        else:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": "no screen"}],
                    },
                }
            )
            continue
        send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"content": [{"type": "text", "text": text}]},
            }
        )
    else:
        send(
            {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "nope"}}
        )
