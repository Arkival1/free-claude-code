"""A read-only advisor: an API model that may ONLY look up JARVIS's tools and give advice.

The advisor never runs a tool, never sees the conversation, the owner's memory,
notes, files or screen. It receives one question written by JARVIS, can call
``search_tools`` / ``describe_tool`` over a metadata-only copy of the tool list,
and answers with advice that JARVIS (the local model) may follow or ignore.
"""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx

MAX_QUESTION_CHARS = 4000
MAX_ADVICE_CHARS = 4000
MAX_ROUNDS = 4
ADVISOR_TOOL_NAME = "ask_advisor"

ADVISOR_SYSTEM = (
    "You are an advisor to JARVIS, a small local AI assistant on the owner's "
    "Windows PC. You cannot act. You can ONLY look up JARVIS's tools with "
    "search_tools and describe_tool. You cannot run tools and cannot see files, "
    "notes, memory, the screen or anything about the owner. Answer JARVIS's "
    "question with short, concrete advice: which tools to use, in what order, "
    "with which arguments, and how to check each step worked. Only recommend "
    "tools you looked up. Never ask for personal data, passwords or files."
)

ADVISOR_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_tools",
        "description": "Search JARVIS's tools by keywords. Returns names and one-line summaries.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "describe_tool",
        "description": "Read what one JARVIS tool does and which arguments it takes.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]

ASK_ADVISOR_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": ADVISOR_TOOL_NAME,
        "description": (
            "Ask the advisor (another model) for advice on HOW to do a task "
            "with your tools. It can only read your tool list; it cannot act or see "
            "anything. Ask in general terms: never include names, personal details, "
            "passwords, file contents or memories."
        ),
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
}

_WORD = re.compile(r"[a-z0-9]{2,}")

Sender = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class ToolCatalog:
    """A metadata-only copy of the tool list: names, descriptions, argument schemas."""

    def __init__(self, tools: Sequence[Mapping[str, Any]]) -> None:
        self._tools = {
            str(t.get("name")): {
                "description": str(t.get("description") or ""),
                "schema": json.loads(json.dumps(t.get("inputSchema") or {})),
            }
            for t in tools
            if isinstance(t.get("name"), str)
        }

    def __len__(self) -> int:
        return len(self._tools)

    def search(self, query: str, limit: int = 8) -> str:
        words = set(_WORD.findall(query.lower()))
        scored = []
        for name, info in self._tools.items():
            hay = set(
                _WORD.findall(
                    (name.replace("_", " ") + " " + info["description"]).lower()
                )
            )
            score = len(words & hay) + 2 * sum(w in name for w in words)
            if score:
                scored.append((-score, name))
        scored.sort()
        if not scored:
            return "No matching tools. Try other keywords."
        return "\n".join(
            f"{name}: {self._tools[name]['description'].split('. ')[0][:160]}"
            for _, name in scored[:limit]
        )

    def describe(self, name: str) -> str:
        info = self._tools.get(name)
        if info is None:
            return f"There is no tool called {name}. Use search_tools first."
        schema = info["schema"] if isinstance(info["schema"], dict) else {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        args = [
            f"- {arg} ({spec.get('type', 'any') if isinstance(spec, dict) else 'any'})"
            + (" required" if arg in required else "")
            for arg, spec in props.items()
        ]
        return f"{name}\n{info['description']}\nArguments:\n" + (
            "\n".join(args) or "- none"
        )


class Advisor:
    """Runs the advisor conversation; only the two read-only lookups are honoured."""

    def __init__(
        self, send: Sender, *, model: str, max_rounds: int = MAX_ROUNDS
    ) -> None:
        self._send = send
        self.model = model
        self._max_rounds = max_rounds

    def advise(self, question: str, catalog: ToolCatalog) -> str:
        question = (question or "").strip()[:MAX_QUESTION_CHARS]
        if not question:
            return "ERROR: ask the advisor a question."
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        last_text = ""
        for round_number in range(self._max_rounds + 1):
            body: dict[str, Any] = {
                "model": self.model,
                "max_tokens": 1200,
                "system": ADVISOR_SYSTEM,
                "messages": messages,
            }
            if round_number < self._max_rounds:
                body["tools"] = ADVISOR_TOOLS
            reply = self._send(body)
            blocks = [b for b in reply.get("content") or [] if isinstance(b, dict)]
            text = "\n".join(
                str(b.get("text", "")) for b in blocks if b.get("type") == "text"
            ).strip()
            last_text = text or last_text
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not uses:
                break
            messages.append({"role": "assistant", "content": blocks})
            messages.append(
                {"role": "user", "content": [self._lookup(u, catalog) for u in uses]}
            )
        advice = last_text or "The advisor had no advice."
        return (
            "ADVICE (from the advisor; you decide what to do):\n"
            + advice[:MAX_ADVICE_CHARS]
        )

    @staticmethod
    def _lookup(use: Mapping[str, Any], catalog: ToolCatalog) -> dict[str, Any]:
        name = use.get("name")
        raw_args = use.get("input")
        args: Mapping[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        is_error = False
        if name == "search_tools":
            content = catalog.search(str(args.get("query", "")))
        elif name == "describe_tool":
            content = catalog.describe(str(args.get("name", "")))
        else:
            content = "Refused: the advisor may only search and read tool descriptions."
            is_error = True
        return {
            "type": "tool_result",
            "tool_use_id": str(use.get("id", "")),
            "content": content,
            "is_error": is_error,
        }


def fcc_messages_sender(
    root_url: str, token: str, http: httpx.Client | None = None
) -> Sender:
    """Send advisor requests through this FCC's own /v1/messages (your API providers)."""
    client = http or httpx.Client(timeout=httpx.Timeout(180.0, connect=5.0))

    def send(body: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            response = client.post(
                f"{root_url.rstrip('/')}/v1/messages",
                json=dict(body),
                headers={"x-api-key": token, "anthropic-version": "2023-06-01"},
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"The advisor could not be reached: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(
                f"The advisor model answered {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        return data if isinstance(data, dict) else {}

    return send
