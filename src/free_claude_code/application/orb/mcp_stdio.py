"""Minimal MCP stdio client: start the same tool servers LM Studio runs and call them.

The protocol is newline-delimited JSON-RPC 2.0 over the child's stdin/stdout.
Only what the orb needs is implemented: initialize, tools/list and tools/call.
"""

import contextlib
import itertools
import json
import os
import queue
import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import IO, Any

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "fcc-jarvis-orb", "version": "1"}
_CREATE_NO_WINDOW = 0x08000000


class McpError(RuntimeError):
    """A tool server failed to start, answered with an error, or timed out."""


@dataclass(frozen=True, slots=True)
class McpServerSpec:
    """How to launch one stdio MCP server (as written in LM Studio's mcp.json)."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: str | None = None


PopenFactory = Callable[..., Any]


class McpStdioClient:
    """One running MCP server process and its JSON-RPC request/response plumbing."""

    def __init__(
        self,
        spec: McpServerSpec,
        *,
        popen: PopenFactory = subprocess.Popen,
        timeout: float = 30.0,
    ) -> None:
        self.spec = spec
        self._popen = popen
        self._timeout = timeout
        self._ids = itertools.count(1)
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._process: Any = None
        self.server_info: dict[str, Any] = {}

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        env = {**os.environ, **dict(self.spec.env)}
        env.setdefault("PYTHONIOENCODING", "utf-8")
        extra: dict[str, Any] = {}
        if os.name == "nt":
            extra["creationflags"] = _CREATE_NO_WINDOW
        try:
            self._process = self._popen(
                [self.spec.command, *self.spec.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=self.spec.cwd or None,
                **extra,
            )
        except OSError as exc:
            raise McpError(
                f"Could not start tool server '{self.spec.name}': {exc}"
            ) from exc
        threading.Thread(
            target=self._read_loop,
            args=(self._process.stdout,),
            name=f"orb-mcp-{self.spec.name}",
            daemon=True,
        ).start()
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
            timeout=max(self._timeout, 60.0),
        )
        self.server_info = dict(result.get("serverInfo") or {})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(50):
            params = {"cursor": cursor} if cursor else {}
            result = self.request("tools/list", params)
            tools.extend(t for t in result.get("tools", []) if isinstance(t, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(
        self, name: str, arguments: Mapping[str, Any], *, timeout: float = 180.0
    ) -> str:
        result = self.request(
            "tools/call", {"name": name, "arguments": dict(arguments)}, timeout=timeout
        )
        parts: list[str] = []
        for item in result.get("content") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(f"[{item.get('type', 'content')} omitted]")
        structured = result.get("structuredContent")
        if not parts and structured is not None:
            parts.append(json.dumps(structured, ensure_ascii=False))
        text = "\n".join(parts).strip() or "(no output)"
        return f"ERROR: {text}" if result.get("isError") else text

    def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if self._process is None:
            raise McpError(f"Tool server '{self.spec.name}' is not running.")
        request_id = next(self._ids)
        answer: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[request_id] = answer
        try:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": dict(params),
                }
            )
            try:
                message = answer.get(timeout=timeout or self._timeout)
            except queue.Empty as exc:
                raise McpError(
                    f"Tool server '{self.spec.name}' did not answer {method} in time."
                ) from exc
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        if "error" in message:
            error = message["error"] or {}
            detail = error.get("message") if isinstance(error, dict) else error
            raise McpError(f"{self.spec.name}: {detail}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        try:
            process.terminate()
            process.wait(timeout=5)
        except OSError, subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                process.kill()
        self._fail_pending("Tool server stopped.")

    def _send(self, message: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise McpError(f"Tool server '{self.spec.name}' is not running.")
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                process.stdin.write(data)
                process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise McpError(
                f"Tool server '{self.spec.name}' closed its input: {exc}"
            ) from exc

    def _read_loop(self, stdout: IO[bytes]) -> None:
        try:
            for raw in stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue  # stray print() output from the server
                if isinstance(message, dict):
                    self._dispatch(message)
        except OSError, ValueError:
            pass
        self._fail_pending(f"Tool server '{self.spec.name}' exited.")

    def _dispatch(self, message: dict[str, Any]) -> None:
        if "method" in message:
            if "id" in message:  # a server->client request (e.g. ping)
                reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
                if message["method"] == "ping":
                    reply["result"] = {}
                else:
                    reply["error"] = {"code": -32601, "message": "Not supported"}
                with contextlib.suppress(McpError):
                    self._send(reply)
            return
        request_id = message.get("id")
        with self._lock:
            answer = (
                self._pending.get(request_id) if isinstance(request_id, int) else None
            )
        if answer is not None:
            answer.put(message)

    def _fail_pending(self, reason: str) -> None:
        with self._lock:
            waiting = list(self._pending.values())
        for answer in waiting:
            with contextlib.suppress(queue.Full):
                answer.put_nowait({"error": {"message": reason}})
