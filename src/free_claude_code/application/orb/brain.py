"""The orb's conversation loop: LM Studio chat completions + MCP tools + memory.

When the conversation grows past the context budget, older turns are summarised,
handed to the vault through the ``memory_offload`` tool and replaced by a short
memory note, so the owner can keep talking indefinitely.
"""

import json
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import httpx

from .toolbox import openai_tool, select_tools

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
MAX_TOOL_ROUNDS = 8
TOOL_RESULT_CHARS = 6000
MEMORY_NOTE_CHARS = 3500


class Toolbox(Protocol):
    def tools(self) -> list[dict[str, Any]]: ...

    def has(self, suffix: str) -> str | None: ...

    def call(self, name: str, arguments: Mapping[str, Any]) -> str: ...


@dataclass(slots=True)
class OrbReply:
    text: str
    tools_used: list[str] = field(default_factory=list)
    compacted: bool = False
    model: str = ""


def clean_reply(text: str) -> str:
    text = _THINK.sub("", text or "")
    if "</think>" in text:  # opening tag was in the prompt template
        text = text.split("</think>", 1)[1]
    return text.strip()


def estimate_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) // 3 + 1


class OrbBrain:
    """One continuing conversation with the local model."""

    def __init__(
        self,
        *,
        base_url: str,
        toolbox: Toolbox,
        skills: str,
        model: str | None = None,
        context_tokens: int = 50_000,
        reply_tokens: int = 1500,
        tool_limit: int = 14,
        http: httpx.Client | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.toolbox = toolbox
        self.skills = skills
        self.model = model
        self.context_tokens = context_tokens
        self.reply_tokens = reply_tokens
        self.tool_limit = tool_limit
        self.history: list[dict[str, Any]] = []
        self.memory_note = ""
        self.resumed = False
        self._http = http or httpx.Client(timeout=httpx.Timeout(600.0, connect=5.0))
        self._clock = clock
        self._lock = threading.Lock()

    # ---------- model discovery ----------
    def list_models(self) -> list[dict[str, Any]]:
        """Models LM Studio offers; loaded ones first when the native API says so."""
        root = self.base_url.removesuffix("/v1")
        try:
            response = self._http.get(f"{root}/api/v0/models", timeout=5.0)
            response.raise_for_status()
            data = response.json().get("data", [])
            models = [
                {"id": m["id"], "loaded": m.get("state") == "loaded"}
                for m in data
                if isinstance(m, dict)
                and m.get("type") in {"llm", "vlm"}
                and isinstance(m.get("id"), str)
            ]
            if models:
                return sorted(models, key=lambda m: not m["loaded"])
        except httpx.HTTPError, ValueError, KeyError:
            pass
        response = self._http.get(f"{self.base_url}/models", timeout=5.0)
        response.raise_for_status()
        return [
            {"id": m["id"], "loaded": False}
            for m in response.json().get("data", [])
            if isinstance(m, dict)
            and isinstance(m.get("id"), str)
            and "embed" not in m["id"].lower()
        ]

    def current_model(self) -> str:
        if not self.model:
            models = self.list_models()
            if not models:
                raise RuntimeError("LM Studio has no chat model. Load one first.")
            self.model = models[0]["id"]
        return self.model

    # ---------- conversation ----------
    def ask(self, text: str) -> OrbReply:
        with self._lock:
            model = self.current_model()
            if not self.resumed:
                self.resumed = True
                self._resume(text)
            self.history.append({"role": "user", "content": text})
            compacted = self._compact_if_needed()
            reply = OrbReply(text="", compacted=compacted, model=model)
            offered = [
                openai_tool(t)
                for t in select_tools(self.toolbox.tools(), text, limit=self.tool_limit)
            ]
            for _ in range(MAX_TOOL_ROUNDS):
                message = self._complete(self._messages(), offered)
                calls = message.get("tool_calls") or []
                if not calls:
                    reply.text = clean_reply(message.get("content") or "")
                    break
                self.history.append(
                    {
                        "role": "assistant",
                        "content": clean_reply(message.get("content") or ""),
                        "tool_calls": calls,
                    }
                )
                for call in calls:
                    self.history.append(self._run_call(call, reply))
            else:
                final = self._complete(self._messages(), [])
                reply.text = clean_reply(final.get("content") or "")
            if not reply.text:
                reply.text = (
                    "Done." if reply.tools_used else "I have no answer for that."
                )
            self.history.append({"role": "assistant", "content": reply.text})
            return reply

    def new_conversation(self) -> str:
        """Save the current talk to the vault and start fresh (memory stays)."""
        with self._lock:
            saved = ""
            if any(m["role"] == "user" for m in self.history):
                summary = self._summarise(self.history)
                saved = self._offload(summary)
                self._remember(summary)
            self.history.clear()
            return saved

    def resume(self, topic: str = "") -> str:
        with self._lock:
            self.resumed = True
            return self._resume(topic)

    # ---------- internals ----------
    def _system_prompt(self) -> str:
        now = self._clock().strftime("%A %d %B %Y, %H:%M")
        parts = [self.skills.strip(), f"Current local time: {now}."]
        if self.memory_note:
            parts.append(
                "## Memory from earlier conversations (from the Obsidian vault)\n"
                + self.memory_note
            )
        return "\n\n".join(parts)

    def _messages(self) -> list[dict[str, Any]]:
        return [{"role": "system", "content": self._system_prompt()}, *self.history]

    def _complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.current_model(),
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": self.reply_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        try:
            response = self._http.post(f"{self.base_url}/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Could not reach LM Studio at {self.base_url}: {exc}. "
                "Open LM Studio and start its local server."
            ) from exc
        if response.status_code >= 400:
            raise RuntimeError(
                f"LM Studio answered {response.status_code}: {response.text[:300]}"
            )
        choices = response.json().get("choices") or [{}]
        message = choices[0].get("message") or {}
        return message if isinstance(message, dict) else {}

    def _run_call(self, call: Mapping[str, Any], reply: OrbReply) -> dict[str, Any]:
        function = call.get("function") or {}
        name = str(function.get("name") or "")
        raw = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
            result = self.toolbox.call(name, arguments)
        except ValueError as exc:
            result = f"ERROR: the arguments for {name} were not valid JSON ({exc})."
        reply.tools_used.append(name)
        if len(result) > TOOL_RESULT_CHARS:
            result = result[:TOOL_RESULT_CHARS] + "\n...(cut; ask for less)"
        return {
            "role": "tool",
            "tool_call_id": str(call.get("id") or name),
            "content": result,
        }

    def _budget(self) -> int:
        return int(self.context_tokens * 0.55)

    def _compact_if_needed(self) -> bool:
        if estimate_tokens(self._messages()) <= self._budget() or len(self.history) < 4:
            return False
        cut = self._cut_point()
        if cut <= 0:
            return False
        old, self.history = self.history[:cut], self.history[cut:]
        summary = self._summarise(old)
        self._offload(summary)
        self._remember(summary)
        return True

    def _cut_point(self) -> int:
        """Index of a user turn near the middle, keeping tool exchanges whole."""
        users = [i for i, m in enumerate(self.history) if m["role"] == "user"]
        if len(users) < 2:
            return 0
        return users[len(users) // 2]

    def _summarise(self, messages: Sequence[Mapping[str, Any]]) -> str:
        lines = []
        for m in messages:
            if m["role"] in {"user", "assistant"} and m.get("content"):
                lines.append(f"{m['role'].upper()}: {m['content']}")
            elif m["role"] == "tool":
                lines.append(f"TOOL RESULT: {str(m.get('content'))[:400]}")
        transcript = "\n".join(lines)[-24_000:]
        prompt = [
            {
                "role": "system",
                "content": "You write long-term memory notes for JARVIS. Be factual "
                "and brief. Never invent anything.",
            },
            {
                "role": "user",
                "content": "Summarise this conversation as Markdown with these "
                "headings: ## Facts about the owner, ## Decisions, ## Done, "
                "## Open tasks, ## Key details (names, paths, numbers). "
                "Skip empty headings.\n\n" + transcript,
            },
        ]
        try:
            text = clean_reply(self._complete(prompt, []).get("content") or "")
        except RuntimeError:
            text = ""
        return text or transcript[-3000:]

    def _offload(self, summary: str) -> str:
        tool = self.toolbox.has("memory_offload")
        if not tool:
            return ""
        stamp = self._clock().strftime("%Y-%m-%d %H:%M")
        return self.toolbox.call(
            tool,
            {
                "title": f"Orb conversation {stamp}",
                "content": summary,
                "kind": "conversation",
                "tags": ["orb", "conversation"],
            },
        )

    def _remember(self, summary: str) -> None:
        note = (self.memory_note + "\n\n" + summary).strip()
        self.memory_note = note[-MEMORY_NOTE_CHARS:]

    def _resume(self, topic: str) -> str:
        tool = self.toolbox.has("memory_resume")
        if not tool:
            return ""
        result = self.toolbox.call(tool, {"query": topic, "max_chars": 3000})
        if result and not result.startswith("ERROR"):
            self.memory_note = result[-MEMORY_NOTE_CHARS:]
        return result
