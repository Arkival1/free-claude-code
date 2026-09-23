"""The tools Studio agents can call, and the sandbox that executes them."""

from collections.abc import Sequence
from dataclasses import dataclass

from free_claude_code.application.web_tools.ports import (
    WebFetchEgressPolicy,
    WebFetchEgressViolation,
    WebToolsPort,
)
from free_claude_code.core.json_types import JsonObject

from .commands import CommandBroker, CommandError
from .llm import ToolCall, ToolSpec
from .memory import MemoryService
from .sites import SiteError, SiteWorkspace

FINISH_TOOL = "finish"
COMMAND_TOOL = "run_command"
MAX_FETCH_CHARS = 6_000
MAX_SEARCH_RESULTS = 6

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="web_search",
        description="Search the web and return result titles and URLs.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."}
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="web_fetch",
        description="Fetch one web page and return its readable text.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute http(s) URL."}
            },
            "required": ["url"],
        },
    ),
    ToolSpec(
        name="write_file",
        description=(
            "Create or replace one file in the website workspace, "
            "for example index.html or styles.css."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Site-relative file path."},
                "content": {"type": "string", "description": "Complete file text."},
            },
            "required": ["path", "content"],
        },
    ),
    ToolSpec(
        name="read_file",
        description="Read one file already in the website workspace.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    ToolSpec(
        name="list_files",
        description="List every file in the website workspace.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="delete_file",
        description="Delete one file from the project workspace.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    ToolSpec(
        name=COMMAND_TOOL,
        description=(
            "Run one short, non-interactive shell command in the project folder: "
            "install packages, build, run tests or a script. It has a time limit, "
            "so never start servers or watchers that keep running."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "e.g. npm install, npm run build, python -m pytest",
                }
            },
            "required": ["command"],
        },
    ),
    ToolSpec(
        name="remember",
        description="Save one durable fact into your own memory.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["text"],
        },
    ),
    ToolSpec(
        name="recall",
        description="Search your own memory for something you learned before.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    ToolSpec(
        name=FINISH_TOOL,
        description="Finish the task and report the result to the user.",
        parameters={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    ),
)

TOOL_SPEC_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}
DEFAULT_TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOOL_SPECS)


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything one tool call is allowed to touch."""

    agent_id: str
    chat_id: str
    site_id: str | None = None
    agent_name: str = "Agent"


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """The rendered result of one tool call plus structured transcript data."""

    text: str
    data: JsonObject
    failed: bool = False


def tool_specs(
    names: Sequence[str], *, commands_enabled: bool = False
) -> tuple[ToolSpec, ...]:
    """Return the specs for named tools, always including ``finish``."""
    chosen = [
        TOOL_SPEC_BY_NAME[name]
        for name in names
        if name in TOOL_SPEC_BY_NAME and (commands_enabled or name != COMMAND_TOOL)
    ]
    if all(spec.name != FINISH_TOOL for spec in chosen):
        chosen.append(TOOL_SPEC_BY_NAME[FINISH_TOOL])
    return tuple(chosen)


class AgentToolbox:
    """Execute agent tool calls against the web, a site, and agent memory."""

    def __init__(
        self,
        *,
        web_tools: WebToolsPort,
        sites: SiteWorkspace,
        memory: MemoryService,
        egress: WebFetchEgressPolicy,
        commands: CommandBroker | None = None,
        command_policy: str = "off",
        command_timeout: float = 120.0,
    ) -> None:
        self._web = web_tools
        self._sites = sites
        self._memory = memory
        self._egress = egress
        self._commands = commands
        self._command_policy = command_policy
        self._command_timeout = command_timeout

    @property
    def commands_enabled(self) -> bool:
        return self._commands is not None and self._command_policy in {"ask", "auto"}

    async def run(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        """Execute one tool call, converting every failure into tool output."""
        try:
            match call.name:
                case "web_search":
                    return await self._web_search(call)
                case "web_fetch":
                    return await self._web_fetch(call)
                case "write_file":
                    return await self._write_file(call, context)
                case "read_file":
                    return await self._read_file(call, context)
                case "list_files":
                    return await self._list_files(context)
                case "delete_file":
                    return await self._delete_file(call, context)
                case "run_command":
                    return await self._run_command(call, context)
                case "remember":
                    return await self._remember(call, context)
                case "recall":
                    return await self._recall(call, context)
                case _:
                    return ToolOutcome(
                        text=f"Unknown tool '{call.name}'.",
                        data={"tool": call.name},
                        failed=True,
                    )
        except (SiteError, WebFetchEgressViolation, CommandError, ValueError) as error:
            return ToolOutcome(
                text=f"{call.name} failed: {error}",
                data={"tool": call.name, "error": str(error)},
                failed=True,
            )

    async def _web_search(self, call: ToolCall) -> ToolOutcome:
        query = str(call.arguments.get("query", "")).strip()
        if not query:
            raise ValueError("A search query is required.")
        results = (await self._web.search(query))[:MAX_SEARCH_RESULTS]
        if not results:
            return ToolOutcome(
                text=f"No results for {query!r}.",
                data={"tool": "web_search", "query": query, "results": []},
            )
        rendered = "\n".join(
            f"{index}. {result.title} — {result.url}"
            for index, result in enumerate(results, start=1)
        )
        return ToolOutcome(
            text=rendered,
            data={
                "tool": "web_search",
                "query": query,
                "results": [
                    {"title": result.title, "url": result.url} for result in results
                ],
            },
        )

    async def _web_fetch(self, call: ToolCall) -> ToolOutcome:
        url = str(call.arguments.get("url", "")).strip()
        if not url:
            raise ValueError("A URL is required.")
        result = await self._web.fetch(url, egress=self._egress)
        body = result.data[:MAX_FETCH_CHARS]
        return ToolOutcome(
            text=f"{result.title}\n{result.url}\n\n{body}",
            data={
                "tool": "web_fetch",
                "url": result.url,
                "title": result.title,
                "chars": len(body),
            },
        )

    async def _write_file(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        path = str(call.arguments.get("path", ""))
        content = call.arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("File content must be text.")
        written = await self._sites.write(site_id, path, content)
        return ToolOutcome(
            text=f"Wrote {written.path} ({written.size} bytes).",
            data={
                "tool": "write_file",
                "site_id": site_id,
                "path": written.path,
                "size": written.size,
            },
        )

    async def _read_file(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        path = str(call.arguments.get("path", ""))
        content = await self._sites.read(site_id, path)
        return ToolOutcome(
            text=content[:MAX_FETCH_CHARS],
            data={"tool": "read_file", "site_id": site_id, "path": path},
        )

    async def _list_files(self, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        files = await self._sites.files(site_id)
        listing = "\n".join(f"{item.path} ({item.size} bytes)" for item in files)
        return ToolOutcome(
            text=listing or "The site is empty.",
            data={
                "tool": "list_files",
                "site_id": site_id,
                "files": [item.path for item in files],
            },
        )

    async def _delete_file(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        path = str(call.arguments.get("path", ""))
        deleted = await self._sites.delete(site_id, path)
        return ToolOutcome(
            text=f"Deleted {path}." if deleted else f"{path} did not exist.",
            data={"tool": "delete_file", "site_id": site_id, "path": path},
        )

    async def _run_command(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        if not self.commands_enabled or self._commands is None:
            raise CommandError("Running commands is turned off in Studio settings.")
        result = await self._commands.request(
            agent_id=context.agent_id,
            agent_name=context.agent_name,
            chat_id=context.chat_id,
            site_id=site_id,
            command=str(call.arguments.get("command", "")),
            cwd=self._sites.directory(site_id),
            policy=self._command_policy,
            timeout=self._command_timeout,
        )
        request = result.request
        return ToolOutcome(
            text=result.text,
            data={
                "tool": COMMAND_TOOL,
                "request_id": request.id,
                "status": request.status,
                "exit_code": request.exit_code,
            },
            failed=request.status != "ran" or (request.exit_code or 0) != 0,
        )

    async def _remember(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        text = str(call.arguments.get("text", ""))
        raw_tags = call.arguments.get("tags")
        tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []
        entry = await self._memory.remember(
            context.agent_id,
            text,
            tags=tags,
            source="tool",
            chat_id=context.chat_id,
        )
        if entry is None:
            raise ValueError("Nothing to remember.")
        return ToolOutcome(
            text=f"Remembered: {entry.text}",
            data={"tool": "remember", "memory_id": entry.id},
        )

    async def _recall(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        query = str(call.arguments.get("query", ""))
        entries = await self._memory.recall(context.agent_id, query)
        if not entries:
            return ToolOutcome(
                text="Nothing relevant in memory.",
                data={"tool": "recall", "query": query, "hits": 0},
            )
        return ToolOutcome(
            text="\n".join(f"- {entry.text}" for entry in entries),
            data={"tool": "recall", "query": query, "hits": len(entries)},
        )

    def _require_site(self, context: ToolContext) -> str:
        if not context.site_id:
            raise ValueError(
                "This conversation has no project workspace. Attach a project first."
            )
        return context.site_id
