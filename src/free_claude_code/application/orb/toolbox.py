"""The orb's tools: the stdio MCP servers listed in LM Studio's mcp.json."""

import json
import re
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .mcp_stdio import McpError, McpServerSpec, McpStdioClient

# Always offered when the server has them: memory, notes and the voice bridge.
ALWAYS_TOOL_PATTERNS = (
    "memory_recall",
    "memory_offload",
    "memory_resume",
    "jarvis_status",
    "obsidian_note",
    "vault_search",
)
_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "you",
        "your",
        "with",
        "that",
        "this",
        "from",
        "can",
        "what",
        "please",
        "into",
        "about",
        "have",
        "are",
        "was",
        "were",
        "will",
        "would",
        "could",
        "should",
        "just",
        "then",
        "them",
        "they",
        "his",
        "her",
        "its",
        "our",
    ]
)

ClientFactory = Callable[[McpServerSpec], McpStdioClient]


def lmstudio_mcp_paths(home: Path | None = None) -> list[Path]:
    """Places LM Studio keeps mcp.json (newest layout first)."""
    base = home or Path.home()
    return [
        base / ".lmstudio" / "mcp.json",
        base / ".cache" / "lm-studio" / "mcp.json",
    ]


def load_server_specs(path: Path) -> tuple[list[McpServerSpec], list[str]]:
    """Read stdio servers from an mcp.json file. Returns (specs, skipped notes)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    specs: list[McpServerSpec] = []
    skipped: list[str] = []
    if not isinstance(servers, dict):
        return specs, ["mcp.json has no mcpServers section"]
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        command = entry.get("command")
        if not isinstance(command, str) or not command.strip():
            skipped.append(f"{name}: only local (command) servers are supported")
            continue
        raw_args = entry.get("args") or []
        raw_env = entry.get("env") or {}
        specs.append(
            McpServerSpec(
                name=str(name),
                command=command,
                args=tuple(
                    str(a) for a in raw_args if isinstance(a, str | int | float)
                ),
                env={str(k): str(v) for k, v in raw_env.items()}
                if isinstance(raw_env, dict)
                else {},
                cwd=entry.get("cwd") if isinstance(entry.get("cwd"), str) else None,
            )
        )
    return specs, skipped


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def select_tools(
    tools: Sequence[Mapping[str, Any]],
    prompt: str,
    *,
    always: Iterable[str] = ALWAYS_TOOL_PATTERNS,
    limit: int = 14,
) -> list[Mapping[str, Any]]:
    """Pick the tools worth showing a small model for this message.

    Small local models get confused by 90 tool schemas, so the orb offers the
    memory tools plus the ones whose name or description match the request.
    """
    patterns = tuple(always)
    wanted = _words(prompt)
    chosen: list[Mapping[str, Any]] = []
    scored: list[tuple[int, int, Mapping[str, Any]]] = []
    for index, tool in enumerate(tools):
        name = str(tool.get("name", ""))
        if any(p in name for p in patterns):
            chosen.append(tool)
            continue
        name_words = _words(name.replace("_", " "))
        desc_words = _words(str(tool.get("description", ""))[:400])
        score = 3 * len(wanted & name_words) + len(wanted & desc_words)
        if score:
            scored.append((-score, index, tool))
    scored.sort(key=lambda item: (item[0], item[1]))
    room = max(0, limit - len(chosen))
    return chosen[:limit] + [tool for _, _, tool in scored[:room]]


def openai_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": str(tool.get("name")),
            "description": str(tool.get("description") or "")[:1024],
            "parameters": schema,
        },
    }


class McpToolbox:
    """Start LM Studio's stdio MCP servers on demand and route tool calls."""

    def __init__(
        self,
        specs: Sequence[McpServerSpec],
        *,
        client_factory: ClientFactory = McpStdioClient,
        skipped: Sequence[str] = (),
    ) -> None:
        self._specs = list(specs)
        self._factory = client_factory
        self._clients: dict[str, McpStdioClient] = {}
        self._owner: dict[str, str] = {}
        self._tools: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.problems: list[str] = list(skipped)

    @classmethod
    def from_lmstudio(cls, paths: Iterable[Path] | None = None) -> McpToolbox:
        for path in paths or lmstudio_mcp_paths():
            if path.is_file():
                try:
                    specs, skipped = load_server_specs(path)
                except (OSError, ValueError) as exc:
                    return cls([], skipped=[f"Could not read {path}: {exc}"])
                return cls(specs, skipped=skipped)
        return cls([], skipped=["LM Studio mcp.json not found (no tools yet)"])

    @property
    def server_names(self) -> list[str]:
        return [spec.name for spec in self._specs]

    def tools(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_started()
            return list(self._tools)

    def has(self, suffix: str) -> str | None:
        """Return the full name of a tool ending with ``suffix``, if any."""
        for tool in self.tools():
            name = str(tool.get("name", ""))
            if name == suffix or name.endswith(suffix):
                return name
        return None

    def call(self, name: str, arguments: Mapping[str, Any]) -> str:
        with self._lock:
            self._ensure_started()
            server = self._owner.get(name)
            client = self._clients.get(server or "")
        if client is None:
            return f"ERROR: there is no tool called {name}."
        if not client.alive:
            with self._lock:
                self._restart(server or "")
                client = self._clients.get(server or "")
            if client is None:
                return f"ERROR: the tool server for {name} is not running."
        try:
            return client.call_tool(name, arguments)
        except McpError as exc:
            return f"ERROR: {exc}"

    def reload(self) -> None:
        self.close()
        with self._lock:
            self._ensure_started()

    def close(self) -> None:
        with self._lock:
            for client in self._clients.values():
                client.close()
            self._clients.clear()
            self._owner.clear()
            self._tools.clear()

    def _ensure_started(self) -> None:
        if self._clients or not self._specs:
            return
        for spec in self._specs:
            self._restart(spec.name)

    def _restart(self, server: str) -> None:
        spec = next((s for s in self._specs if s.name == server), None)
        if spec is None:
            return
        old = self._clients.pop(server, None)
        if old is not None:
            old.close()
        self._tools = [t for t in self._tools if self._owner.get(t["name"]) != server]
        for name in [n for n, owner in self._owner.items() if owner == server]:
            del self._owner[name]
        client = self._factory(spec)
        try:
            client.start()
            listed = client.list_tools()
        except McpError as exc:
            client.close()
            self.problems.append(str(exc))
            return
        self._clients[server] = client
        for tool in listed:
            name = tool.get("name")
            if isinstance(name, str) and name not in self._owner:
                self._owner[name] = server
                self._tools.append(tool)
