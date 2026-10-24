"""A small MCP client: the team's door to MCP tool servers.

A stdio server is a program Studio starts (npx, uvx, python, ...) and talks to
in JSON-RPC lines on stdin/stdout; an HTTP server is a web address taking
JSON-RPC posts (plain JSON or server-sent events back). Each server starts the
first time an agent uses it and stays up until Studio shuts down.
"""

import asyncio
import contextlib
import json
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import httpx
from loguru import logger

PROTOCOL = "2025-06-18"
START_SECONDS = 120.0
"""npx and uvx download a server the first time, which can take a while."""
CALL_SECONDS = 120.0
MAX_RESULT_CHARS = 12_000


class McpError(RuntimeError):
    """A server couldn't start, or a call failed."""


@dataclass(frozen=True, slots=True)
class McpTool:
    name: str
    description: str
    schema: Mapping[str, object]


def _resolve(command: str) -> list[str]:
    """The command as this OS runs it ('npx' is npx.cmd on Windows)."""
    found = shutil.which(command)
    if found is None:
        raise McpError(
            f"'{command}' isn't installed on this PC"
            + (
                " (install Node.js for npx servers)."
                if command in {"npx", "node", "npm"}
                else " (uv comes with Studio; for uvx run the Studio installer again)."
                if command in {"uvx", "uv"}
                else "."
            )
        )
    if sys.platform == "win32" and found.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", found]
    return [found]


def _text_of(result: Mapping[str, object]) -> str:
    parts: list[str] = []
    content = result.get("content")
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text") or ""))
        elif kind == "resource":
            resource = item.get("resource")
            if isinstance(resource, dict):
                parts.append(str(resource.get("text") or resource.get("uri") or ""))
        elif kind in {"image", "audio"}:
            parts.append(f"[{kind} {item.get('mimeType', '')}]")
    structured = result.get("structuredContent")
    if not parts and structured is not None:
        parts.append(json.dumps(structured)[:MAX_RESULT_CHARS])
    text = "\n".join(part for part in parts if part).strip() or "(no output)"
    return text[:MAX_RESULT_CHARS]


class _Session:
    async def request(
        self, method: str, params: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        raise NotImplementedError

    async def notify(self, method: str) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def handshake(self) -> None:
        await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "fcc-studio", "version": "1"},
            },
        )
        await self.notify("notifications/initialized")

    async def tools(self) -> list[McpTool]:
        found: list[McpTool] = []
        cursor: object = None
        for _ in range(20):
            result = await self.request(
                "tools/list", {"cursor": cursor} if cursor else {}
            )
            listed = result.get("tools")
            for item in listed if isinstance(listed, list) else []:
                if isinstance(item, dict) and item.get("name"):
                    schema = item.get("inputSchema")
                    found.append(
                        McpTool(
                            name=str(item["name"]),
                            description=str(item.get("description") or ""),
                            schema=schema if isinstance(schema, dict) else {},
                        )
                    )
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return found

    async def call(
        self, name: str, arguments: Mapping[str, object]
    ) -> tuple[str, bool]:
        result = await self.request(
            "tools/call", {"name": name, "arguments": dict(arguments)}
        )
        return _text_of(result), bool(result.get("isError"))


class StdioSession(_Session):
    """A server Studio runs as a program and talks to on stdin/stdout."""

    def __init__(
        self,
        command: str,
        args: Sequence[str],
        env: Mapping[str, str],
        cwd: str | None = None,
    ) -> None:
        self._command = command
        self._args = list(args)
        self._env = dict(env)
        self._cwd = cwd
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future[dict[str, object]]] = {}
        self._next = 0
        self._reader: asyncio.Task[None] | None = None
        self._stderr: list[str] = []

    async def start(self) -> None:
        argv = [*_resolve(self._command), *self._args]
        try:
            self._process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **self._env},
                cwd=self._cwd,
                limit=16 * 1024 * 1024,
            )
        except OSError as error:
            raise McpError(f"Couldn't start {self._command}: {error}") from error
        self._reader = asyncio.ensure_future(self._read())
        asyncio.ensure_future(self._read_errors())
        await asyncio.wait_for(self.handshake(), timeout=START_SECONDS)

    async def _read(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            wanted = message.get("id")
            if (
                isinstance(wanted, int)
                and wanted in self._pending
                and ("result" in message or "error" in message)
            ):
                future = self._pending.pop(wanted)
                if not future.done():
                    future.set_result(message)
            elif "method" in message and "id" in message:
                # A request from the server (sampling, roots): say we can't.
                await self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32601, "message": "Not supported"},
                    }
                )
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpError(self._died()))
        self._pending.clear()

    async def _read_errors(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            self._stderr = [*self._stderr[-20:], line.decode(errors="replace").rstrip()]

    def _died(self) -> str:
        said = "\n".join(self._stderr[-5:])
        return "The server stopped." + (f" It said:\n{said}" if said else "")

    async def _send(self, message: Mapping[str, object]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise McpError(self._died())
        process.stdin.write((json.dumps(message) + "\n").encode())
        await process.stdin.drain()

    async def request(
        self, method: str, params: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        self._next += 1
        wanted = self._next
        future: asyncio.Future[dict[str, object]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[wanted] = future
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": wanted,
                "method": method,
                "params": dict(params or {}),
            }
        )
        try:
            answer = await asyncio.wait_for(future, timeout=CALL_SECONDS)
        except TimeoutError as error:
            self._pending.pop(wanted, None)
            raise McpError(f"The server didn't answer {method} in time.") from error
        if "error" in answer:
            error = answer["error"]
            message = error.get("message") if isinstance(error, dict) else error
            raise McpError(f"The server said: {message}")
        result = answer.get("result")
        return result if isinstance(result, dict) else {}

    async def notify(self, method: str) -> None:
        await self._send({"jsonrpc": "2.0", "method": method})

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
        if self._reader is not None:
            self._reader.cancel()


class HttpSession(_Session):
    """A server at a web address (MCP over HTTP)."""

    def __init__(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._headers = dict(headers)
        self._client = httpx.AsyncClient(transport=transport, timeout=CALL_SECONDS)
        self._session_id = ""
        self._next = 0

    async def start(self) -> None:
        await asyncio.wait_for(self.handshake(), timeout=START_SECONDS)

    async def _post(self, message: Mapping[str, object]) -> httpx.Response:
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            **self._headers,
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        try:
            response = await self._client.post(
                self._url, json=dict(message), headers=headers
            )
        except httpx.HTTPError as error:
            raise McpError(f"The server didn't answer: {error}") from error
        self._session_id = response.headers.get("mcp-session-id", self._session_id)
        if response.status_code >= 400:
            raise McpError(
                f"The server answered {response.status_code}: {response.text[:300]}"
            )
        return response

    async def request(
        self, method: str, params: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        self._next += 1
        response = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next,
                "method": method,
                "params": dict(params or {}),
            }
        )
        answer = _answer_from(response, self._next)
        if "error" in answer:
            error = answer["error"]
            message = error.get("message") if isinstance(error, dict) else error
            raise McpError(f"The server said: {message}")
        result = answer.get("result")
        return result if isinstance(result, dict) else {}

    async def notify(self, method: str) -> None:
        await self._post({"jsonrpc": "2.0", "method": method})

    @property
    def alive(self) -> bool:
        return not self._client.is_closed

    async def close(self) -> None:
        await self._client.aclose()


def _answer_from(response: httpx.Response, wanted: int) -> dict[str, object]:
    kind = response.headers.get("content-type", "")
    if "text/event-stream" in kind:
        for line in response.text.splitlines():
            if not line.startswith("data:"):
                continue
            with contextlib.suppress(json.JSONDecodeError):
                message = json.loads(line[5:].strip())
                if isinstance(message, dict) and message.get("id") == wanted:
                    return message
        raise McpError("The server's answer had no reply in it.")
    try:
        message = response.json()
    except ValueError as error:
        raise McpError("The server sent something that isn't JSON.") from error
    if isinstance(message, list):
        message = next(
            (m for m in message if isinstance(m, dict) and m.get("id") == wanted), {}
        )
    return message if isinstance(message, dict) else {}


@dataclass(frozen=True, slots=True)
class ServerSpec:
    key: str
    """Unique per extension and server, e.g. 'ext_x/filesystem'."""
    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    url: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    cwd: str | None = None


class McpManager:
    """Start servers when first used, keep them up, and close them at exit."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._sessions: dict[str, StdioSession | HttpSession] = {}
        self._tools: dict[str, list[McpTool]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._transport = transport

    async def _session(self, spec: ServerSpec) -> StdioSession | HttpSession:
        lock = self._locks.setdefault(spec.key, asyncio.Lock())
        async with lock:
            current = self._sessions.get(spec.key)
            if current is not None and current.alive:
                return current
            session: StdioSession | HttpSession
            if spec.url:
                session = HttpSession(
                    spec.url, dict(spec.headers), transport=self._transport
                )
            else:
                session = StdioSession(
                    spec.command, spec.args, dict(spec.env), spec.cwd
                )
            try:
                await session.start()
            except (McpError, TimeoutError, OSError) as error:
                await session.close()
                if isinstance(error, TimeoutError):
                    raise McpError(f"{spec.name} didn't start in time.") from error
                raise McpError(f"{spec.name} didn't start: {error}") from error
            self._sessions[spec.key] = session
            self._tools.pop(spec.key, None)
            return session

    async def tools(self, spec: ServerSpec) -> list[McpTool]:
        if spec.key not in self._tools:
            session = await self._session(spec)
            self._tools[spec.key] = await session.tools()
        return self._tools[spec.key]

    async def call(
        self, spec: ServerSpec, tool: str, arguments: Mapping[str, object]
    ) -> tuple[str, bool]:
        session = await self._session(spec)
        return await session.call(tool, arguments)

    async def stop(self, key: str) -> None:
        session = self._sessions.pop(key, None)
        self._tools.pop(key, None)
        if session is not None:
            await session.close()

    async def close(self) -> None:
        for key in list(self._sessions):
            try:
                await self.stop(key)
            except Exception as error:
                logger.debug("Studio: an MCP server didn't close cleanly: {}", error)
