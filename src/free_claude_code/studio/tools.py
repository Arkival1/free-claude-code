"""The tools Studio agents can call, and the sandbox that executes them."""

import fnmatch
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import aiohttp
import httpx

from free_claude_code.application.web_tools.ports import (
    WebFetchEgressPolicy,
    WebFetchEgressViolation,
    WebToolsPort,
)
from free_claude_code.core.json_types import JsonObject

from .commands import CommandBroker, CommandError
from .llm import ToolCall, ToolSpec
from .memory import SHARED_MEMORY_ID, MemoryService
from .platforms import PlatformError, PlatformReader, platform_of
from .research import PLATFORMS, DeepResearch
from .search import SearchError, StudioSearch
from .sites import SiteError, SiteWorkspace

FINISH_TOOL = "finish"
COMMAND_TOOL = "run_command"
ASK_AGENT_TOOL = "ask_agent"
TEAM_TASK_TOOL = "team_task"
DELEGATION_TOOLS = frozenset({ASK_AGENT_TOOL, TEAM_TASK_TOOL})
WEB_TOOLS: tuple[str, ...] = ("web_search", "web_fetch")
RESEARCH_TOOL = "research"
TEST_CODE_TOOL = "test_code"
ASK_RESEARCHER_TOOL = "ask_researcher"
ASK_HELPER_TOOL = "ask_helper"
HELPER_ROLE = "helper"
MAX_SEARCH_MATCHES = 60
MAX_READ_LINES = 400
NETWORK_TOOLS = frozenset({*WEB_TOOLS, RESEARCH_TOOL})
RESEARCHER_ROLE = "researcher"
TEST_LANGUAGES = {
    "python": "py",
    "py": "py",
    "javascript": "js",
    "js": "js",
    "node": "js",
    "html": "html",
    "css": "css",
}
MAIN_ROLE = "main"
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
        description=(
            "Read one file in the project. Give start_line (and max_lines) to read "
            "a numbered section, which is what you need before edit_file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "description": "1-based line."},
                "max_lines": {"type": "integer"},
            },
            "required": ["path"],
        },
    ),
    ToolSpec(
        name="edit_file",
        description=(
            "Change part of a file without rewriting it: replace old_text, which "
            "must appear exactly once (copy it from read_file), with new_text. "
            "Set replace_all to change every occurrence."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    ),
    ToolSpec(
        name="search_files",
        description=(
            "Search the project's files for a regular expression and get "
            "path:line matches, like grep. Narrow it with glob, e.g. *.js."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "glob": {"type": "string"},
                "ignore_case": {"type": "boolean"},
            },
            "required": ["pattern"],
        },
    ),
    ToolSpec(
        name="list_files",
        description=(
            "List the files in the project. Give pattern, e.g. src/**/*.ts or "
            "*.css, to list only matching files."
        ),
        parameters={
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
        },
    ),
    ToolSpec(
        name="update_plan",
        description=(
            "Write down or update your step-by-step plan for this task, with each "
            "step pending, in_progress, or done. Keep one step in progress."
        ),
        parameters={
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done"],
                            },
                        },
                        "required": ["step"],
                    },
                }
            },
            "required": ["steps"],
        },
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
        name=RESEARCH_TOOL,
        description=(
            "Research a question in depth: searches the web, Reddit, YouTube, "
            "Stack Overflow, GitHub, MDN, and dev.to, reads at least ten "
            "sources, and returns the useful parts numbered so you can cite "
            "them. Use it for how-to, best practice, and fixing errors."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "What to find out."},
                "platforms": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(PLATFORMS)},
                    "description": "Optional: only these platforms.",
                },
            },
            "required": ["question"],
        },
    ),
    ToolSpec(
        name=TEST_CODE_TOOL,
        description=(
            "Try out a code snippet before relying on it: saves it in the "
            "project's lab folder and runs it (python or javascript), returning "
            "the output and exit code. HTML and CSS are saved for preview."
        ),
        parameters={
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "html", "css"],
                },
                "code": {"type": "string"},
            },
            "required": ["language", "code"],
        },
    ),
    ToolSpec(
        name=ASK_HELPER_TOOL,
        description=(
            "Ask the team's Helper to think with you: it filters material (like "
            "research findings or an error log) against your task, brainstorms "
            "ways to succeed, and returns concrete next steps."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "What you are trying to do and where you are stuck.",
                },
                "material": {
                    "type": "string",
                    "description": "Optional findings, logs, or notes to work from.",
                },
            },
            "required": ["request"],
        },
    ),
    ToolSpec(
        name=ASK_RESEARCHER_TOOL,
        description=(
            "Ask the team's Researcher to look something up and report back, "
            "for example how to fix an error you are stuck on. Include the "
            "exact error, what you tried, and your stack."
        ),
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
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
        name=ASK_AGENT_TOOL,
        description=(
            "Hand one task to another agent on your team and wait for its report. "
            "Use it for work that needs that agent's tools or model, like "
            "researching or building a website or app."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "The agent's name."},
                "task": {
                    "type": "string",
                    "description": "Everything the agent needs to do the task.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional project to work in, by name; a new one is "
                        "created when no project has that name."
                    ),
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "True to let the agent work in the background and "
                        "report when done, instead of waiting for it."
                    ),
                },
            },
            "required": ["agent", "task"],
        },
    ),
    ToolSpec(
        name=TEAM_TASK_TOOL,
        description=(
            "Put several agents in a room to work on one goal together, handing "
            "parts to each other, and wait for their result."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Agent names; the first one leads.",
                },
                "goal": {"type": "string"},
                "project": {
                    "type": "string",
                    "description": "Optional project to work in, by name.",
                },
            },
            "required": ["agents", "goal"],
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
DEFAULT_TOOL_NAMES: tuple[str, ...] = tuple(
    spec.name for spec in TOOL_SPECS if spec.name not in DELEGATION_TOOLS
)
MAIN_TOOL_NAMES: tuple[str, ...] = (
    ASK_AGENT_TOOL,
    TEAM_TASK_TOOL,
    RESEARCH_TOOL,
    ASK_HELPER_TOOL,
    "web_search",
    "web_fetch",
    "remember",
    "recall",
    FINISH_TOOL,
)
SHARED_REMEMBER_SPEC = ToolSpec(
    name="remember",
    description=(
        "Save one durable fact into the team's shared memory, where every agent "
        "can recall it. Set private to true to keep it to yourself."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "private": {"type": "boolean"},
        },
        "required": ["text"],
    },
)
SHARED_RECALL_SPEC = ToolSpec(
    name="recall",
    description="Search your own memory and the team's shared memory.",
    parameters=TOOL_SPEC_BY_NAME["recall"].parameters,
)


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything one tool call is allowed to touch."""

    agent_id: str
    chat_id: str
    site_id: str | None = None
    agent_name: str = "Agent"
    agent_role: str = "assistant"


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """The rendered result of one tool call plus structured transcript data."""

    text: str
    data: JsonObject
    failed: bool = False


class TeamDelegate(Protocol):
    """Lets the main agent hand work to the rest of the team."""

    async def ask_agent(
        self,
        context: ToolContext,
        *,
        agent: str,
        task: str,
        project: str,
        background: bool = False,
    ) -> ToolOutcome:
        """Run one task on another agent and report its result."""
        ...

    async def consult(self, context: ToolContext, *, question: str) -> ToolOutcome:
        """Ask the team's Researcher a question and wait for its answer."""
        ...

    async def help(
        self, context: ToolContext, *, request: str, material: str
    ) -> ToolOutcome:
        """Ask the team's Helper to turn material into a plan for a task."""
        ...

    async def team_task(
        self,
        context: ToolContext,
        *,
        agents: Sequence[str],
        goal: str,
        project: str,
    ) -> ToolOutcome:
        """Run one goal with several agents in a room and report the result."""
        ...


def tool_specs(
    names: Sequence[str],
    *,
    commands_enabled: bool = False,
    shared_memory: bool = False,
    delegation: bool = False,
) -> tuple[ToolSpec, ...]:
    """Return the specs for named tools, always including ``finish``."""
    chosen: list[ToolSpec] = []
    for name in names:
        spec = TOOL_SPEC_BY_NAME.get(name)
        if spec is None:
            continue
        if name == COMMAND_TOOL and not commands_enabled:
            continue
        if name in DELEGATION_TOOLS and not delegation:
            continue
        if shared_memory and name == "remember":
            spec = SHARED_REMEMBER_SPEC
        elif shared_memory and name == "recall":
            spec = SHARED_RECALL_SPEC
        chosen.append(spec)
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
        delegate: TeamDelegate | None = None,
        searcher: StudioSearch | None = None,
        web_access: str = "all",
        reader: PlatformReader | None = None,
        research_sources: int = 10,
    ) -> None:
        self._web = web_tools
        self._sites = sites
        self._memory = memory
        self._egress = egress
        self._commands = commands
        self._command_policy = command_policy
        self._command_timeout = command_timeout
        self._delegate = delegate
        self._searcher = searcher
        self._web_access = web_access
        self._reader = reader or PlatformReader()
        self._research_sources = research_sources

    @property
    def commands_enabled(self) -> bool:
        return self._commands is not None and self._command_policy in {"ask", "auto"}

    @property
    def shared_memory(self) -> bool:
        return self._memory.shared_enabled

    @property
    def web_enabled(self) -> bool:
        return self._web_access != "off"

    def tool_names(self, names: Sequence[str], *, role: str) -> tuple[str, ...]:
        """Apply the web access setting to an agent's own tool list."""
        chosen = [
            name for name in names if self.web_enabled or name not in NETWORK_TOOLS
        ]
        if self._web_access == "all" and role != "guide":
            chosen.extend(name for name in WEB_TOOLS if name not in chosen)
        return tuple(chosen)

    def delegation_allowed(self, role: str) -> bool:
        """Only the main agent may hand work to other agents."""
        return self._delegate is not None and role == MAIN_ROLE

    async def run(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        """Execute one tool call, converting every failure into tool output."""
        if call.name in NETWORK_TOOLS and not self.web_enabled:
            return ToolOutcome(
                text="Web access is off in Studio settings.",
                data={"tool": call.name},
                failed=True,
            )
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
                case "edit_file":
                    return await self._edit_file(call, context)
                case "search_files":
                    return await self._search_files(call, context)
                case "list_files":
                    return await self._list_files(call, context)
                case "update_plan":
                    return await self._update_plan(call, context)
                case "ask_helper":
                    return await self._ask_helper(call, context)
                case "delete_file":
                    return await self._delete_file(call, context)
                case "run_command":
                    return await self._run_command(call, context)
                case "remember":
                    return await self._remember(call, context)
                case "recall":
                    return await self._recall(call, context)
                case "ask_agent" | "team_task":
                    return await self._delegate_call(call, context)
                case "research":
                    return await self._research(call)
                case "test_code":
                    return await self._test_code(call, context)
                case "ask_researcher":
                    return await self._consult(call, context)
                case _:
                    return ToolOutcome(
                        text=f"Unknown tool '{call.name}'.",
                        data={"tool": call.name},
                        failed=True,
                    )
        except (
            SiteError,
            WebFetchEgressViolation,
            CommandError,
            SearchError,
            PlatformError,
            httpx.HTTPError,
            aiohttp.ClientError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            return ToolOutcome(
                text=f"{call.name} failed: {error}",
                data={"tool": call.name, "error": str(error)},
                failed=True,
            )

    async def _web_search(self, call: ToolCall) -> ToolOutcome:
        query = str(call.arguments.get("query", "")).strip()
        if not query:
            raise ValueError("A search query is required.")
        if self._searcher is not None:
            report = await self._searcher.search(query, limit=MAX_SEARCH_RESULTS)
            provider, note = report.provider, report.note
            hits = [(hit.title, hit.url, hit.snippet) for hit in report.hits]
        else:
            results = (await self._web.search(query))[:MAX_SEARCH_RESULTS]
            provider, note = "web", ""
            hits = [(result.title, result.url, "") for result in results]
        data: JsonObject = {
            "tool": "web_search",
            "query": query,
            "provider": provider,
            "results": [{"title": title, "url": url} for title, url, _ in hits],
        }
        if note:
            data["note"] = note
        if not hits:
            text = f"No results for {query!r}."
            if note:
                text += f" {note}"
            return ToolOutcome(text=f"{text} Try a shorter query.", data=data)
        lines: list[str] = [f"Note: {note}"] if note else []
        for index, (title, url, snippet) in enumerate(hits, start=1):
            lines.append(f"{index}. {title} — {url}")
            if snippet:
                lines.append(f"   {snippet}")
        lines.append("Read a page in full with web_fetch.")
        return ToolOutcome(text="\n".join(lines), data=data)

    async def _web_fetch(self, call: ToolCall) -> ToolOutcome:
        url = str(call.arguments.get("url", "")).strip()
        if not url:
            raise ValueError("A URL is required.")
        if platform_of(url) != "web":
            page = await self._reader.read(url)
            body = page.text[:MAX_FETCH_CHARS]
            note = f"\n\n({page.note})" if page.note else ""
            return ToolOutcome(
                text=f"{page.title}\n{page.url}\n\n{body}{note}",
                data={
                    "tool": "web_fetch",
                    "url": page.url,
                    "title": page.title,
                    "platform": page.platform,
                    "chars": len(body),
                },
            )
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
        start = _int_arg(call.arguments.get("start_line"))
        limit = _int_arg(call.arguments.get("max_lines"))
        data: JsonObject = {"tool": "read_file", "site_id": site_id, "path": path}
        if start is None and limit is None:
            text = content[:MAX_FETCH_CHARS]
            if len(content) > MAX_FETCH_CHARS:
                text += "\n[... cut; read further with start_line]"
            return ToolOutcome(text=text, data=data)
        lines = content.splitlines()
        first = max(1, start or 1)
        count = max(1, min(MAX_READ_LINES, limit or MAX_READ_LINES))
        shown = lines[first - 1 : first - 1 + count]
        numbered = "\n".join(
            f"{number:>5}  {line}" for number, line in enumerate(shown, start=first)
        )
        last = first + len(shown) - 1
        header = f"{path}: lines {first}-{last} of {len(lines)}"
        return ToolOutcome(
            text=f"{header}\n{numbered}"[: MAX_FETCH_CHARS * 2],
            data={**data, "start_line": first, "end_line": last},
        )

    async def _edit_file(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        path = str(call.arguments.get("path", ""))
        old = call.arguments.get("old_text")
        new = call.arguments.get("new_text")
        if not isinstance(old, str) or not old:
            raise ValueError("Give old_text: the exact text to replace.")
        if not isinstance(new, str):
            raise ValueError("Give new_text: what to put in its place.")
        content = await self._sites.read(site_id, path)
        found = content.count(old)
        replace_all = call.arguments.get("replace_all") is True
        if found == 0:
            raise ValueError(
                f"old_text was not found in {path}. Read the file again and copy "
                "the text exactly, including spaces."
            )
        if found > 1 and not replace_all:
            raise ValueError(
                f"old_text appears {found} times in {path}. Include more "
                "surrounding lines so it is unique, or set replace_all."
            )
        updated = (
            content.replace(old, new) if replace_all else content.replace(old, new, 1)
        )
        written = await self._sites.write(site_id, path, updated)
        changed = found if replace_all else 1
        return ToolOutcome(
            text=f"Edited {written.path}: replaced {changed} occurrence(s).",
            data={
                "tool": "edit_file",
                "site_id": site_id,
                "path": written.path,
                "replacements": changed,
            },
        )

    async def _search_files(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        raw = str(call.arguments.get("pattern", ""))
        if not raw:
            raise ValueError("Give a pattern to search for.")
        flags = re.IGNORECASE if call.arguments.get("ignore_case") is True else 0
        try:
            pattern = re.compile(raw, flags)
        except re.error as error:
            raise ValueError(
                f"That pattern is not a valid regular expression: {error}"
            ) from error
        glob = str(call.arguments.get("glob") or "").strip()
        matches: list[str] = []
        searched = 0
        for item in await self._sites.files(site_id):
            if glob and not _glob_match(item.path, glob):
                continue
            if not _is_text(item.content_type):
                continue
            try:
                content = await self._sites.read(site_id, item.path)
            except SiteError:
                continue
            searched += 1
            for number, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{item.path}:{number}: {line.strip()[:200]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        break
            if len(matches) >= MAX_SEARCH_MATCHES:
                break
        text = "\n".join(matches) or f"No matches in {searched} file(s)."
        if len(matches) >= MAX_SEARCH_MATCHES:
            text += "\n[more matches not shown; narrow the pattern or glob]"
        return ToolOutcome(
            text=text,
            data={"tool": "search_files", "matches": len(matches), "files": searched},
        )

    async def _list_files(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        pattern = str(call.arguments.get("pattern") or "").strip()
        files = [
            item
            for item in await self._sites.files(site_id)
            if not pattern or _glob_match(item.path, pattern)
        ]
        listing = "\n".join(f"{item.path} ({item.size} bytes)" for item in files)
        empty = f"No files match {pattern}." if pattern else "The site is empty."
        return ToolOutcome(
            text=listing or empty,
            data={
                "tool": "list_files",
                "site_id": site_id,
                "files": [item.path for item in files],
            },
        )

    async def _update_plan(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        raw = call.arguments.get("steps")
        if not isinstance(raw, list) or not raw:
            raise ValueError("Give the plan as a list of steps.")
        marks = {"done": "[x]", "in_progress": "[>]", "pending": "[ ]"}
        lines: list[str] = []
        for item in raw[:20]:
            if isinstance(item, dict):
                step = str(item.get("step", "")).strip()
                status = str(item.get("status") or "pending")
            else:
                step, status = str(item).strip(), "pending"
            if step:
                lines.append(f"{marks.get(status, '[ ]')} {step}")
        if not lines:
            raise ValueError("The plan has no steps.")
        plan = "\n".join(lines)
        await self._memory.replace_plan(context.agent_id, plan, chat_id=context.chat_id)
        done = sum(1 for line in lines if line.startswith("[x]"))
        return ToolOutcome(
            text=f"Plan ({done}/{len(lines)} done):\n{plan}",
            data={"tool": "update_plan", "steps": len(lines), "done": done},
        )

    async def _ask_helper(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        if self._delegate is None:
            raise ValueError("There is no team to ask.")
        if context.agent_role == HELPER_ROLE:
            raise ValueError("You are the helper; think it through yourself.")
        request = str(call.arguments.get("request", "")).strip()
        if not request:
            raise ValueError("Say what you need help with.")
        material = str(call.arguments.get("material") or "").strip()
        return await self._delegate.help(context, request=request, material=material)

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
        private = call.arguments.get("private") is True
        shared = self._memory.shared_enabled and not private
        if shared:
            entry = await self._memory.share(
                text,
                author=context.agent_name,
                tags=tags,
                source="tool",
                chat_id=context.chat_id,
            )
        else:
            entry = await self._memory.remember(
                context.agent_id,
                text,
                tags=tags,
                source="tool",
                chat_id=context.chat_id,
            )
        if entry is None:
            raise ValueError("Nothing to remember.")
        where = "team memory" if shared else "your memory"
        return ToolOutcome(
            text=f"Saved to {where}: {entry.text}",
            data={"tool": "remember", "memory_id": entry.id, "shared": shared},
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
            text="\n".join(
                f"- {'(team) ' if entry.agent_id == SHARED_MEMORY_ID else ''}"
                f"{entry.text}"
                for entry in entries
            ),
            data={"tool": "recall", "query": query, "hits": len(entries)},
        )

    async def _delegate_call(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        if self._delegate is None or not self.delegation_allowed(context.agent_role):
            raise ValueError("Only the main agent can hand work to other agents.")
        project = str(call.arguments.get("project") or "").strip()
        if call.name == ASK_AGENT_TOOL:
            agent = str(call.arguments.get("agent", "")).strip()
            task = str(call.arguments.get("task", "")).strip()
            if not agent or not task:
                raise ValueError("Say which agent and what the task is.")
            return await self._delegate.ask_agent(
                context,
                agent=agent,
                task=task,
                project=project,
                background=call.arguments.get("background") is True,
            )
        raw_agents = call.arguments.get("agents")
        if isinstance(raw_agents, str):
            raw_agents = [part for part in raw_agents.split(",") if part.strip()]
        agents = (
            [str(item).strip() for item in raw_agents if str(item).strip()]
            if isinstance(raw_agents, list)
            else []
        )
        goal = str(call.arguments.get("goal", "")).strip()
        if not agents or not goal:
            raise ValueError("Name the agents and the goal.")
        return await self._delegate.team_task(
            context, agents=agents, goal=goal, project=project
        )

    async def _research(self, call: ToolCall) -> ToolOutcome:
        if self._searcher is None:
            raise ValueError("Web search is not set up.")
        question = str(call.arguments.get("question", "")).strip()
        raw = call.arguments.get("platforms")
        platforms = [str(item) for item in raw] if isinstance(raw, list) else []
        engine = DeepResearch(
            search=self._searcher,
            reader=self._reader,
            fetch=lambda url: self._web.fetch(url, egress=self._egress),
            wanted=self._research_sources,
        )
        report = await engine.run(question, platforms=platforms)
        return ToolOutcome(
            text=report.render(),
            data={
                "tool": RESEARCH_TOOL,
                "question": report.question,
                "sources": [
                    {
                        "n": source.number,
                        "title": source.title,
                        "url": source.url,
                        "platform": source.platform,
                        "read": source.read,
                    }
                    for source in report.sources
                ],
                "wanted": report.wanted,
            },
            failed=not report.sources,
        )

    async def _test_code(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        site_id = self._require_site(context)
        language = str(call.arguments.get("language", "")).strip().lower()
        code = call.arguments.get("code")
        suffix = TEST_LANGUAGES.get(language)
        if suffix is None:
            raise ValueError("test_code runs python or javascript, or saves html/css.")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("Give the code to test.")
        path = f"lab/test_{time.time_ns() // 1_000_000}.{suffix}"
        await self._sites.write(site_id, path, code)
        if suffix in {"html", "css"}:
            return ToolOutcome(
                text=f"Saved {path}. Open the project preview to check it.",
                data={"tool": TEST_CODE_TOOL, "path": path, "ran": False},
            )
        if not self.commands_enabled or self._commands is None:
            raise CommandError(
                "Testing code needs Agents Can Run Commands set to Ask or Auto "
                f"in Studio settings. The snippet is saved as {path}."
            )
        runner = f'"{sys.executable}"' if suffix == "py" else "node"
        result = await self._commands.request(
            agent_id=context.agent_id,
            agent_name=context.agent_name,
            chat_id=context.chat_id,
            site_id=site_id,
            command=f"{runner} {path}",
            cwd=self._sites.directory(site_id),
            policy=self._command_policy,
            timeout=self._command_timeout,
        )
        request = result.request
        passed = request.status == "ran" and (request.exit_code or 0) == 0
        verdict = "PASSED" if passed else "FAILED"
        return ToolOutcome(
            text=f"{verdict} ({path})\n{result.text}",
            data={
                "tool": TEST_CODE_TOOL,
                "path": path,
                "ran": request.status == "ran",
                "passed": passed,
                "exit_code": request.exit_code,
                "request_id": request.id,
            },
            failed=not passed,
        )

    async def _consult(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        if self._delegate is None:
            raise ValueError("There is no team to ask.")
        if context.agent_role == RESEARCHER_ROLE:
            raise ValueError("You are the researcher; use research instead.")
        question = str(call.arguments.get("question", "")).strip()
        if not question:
            raise ValueError("Say what the researcher should find out.")
        return await self._delegate.consult(context, question=question)

    def _require_site(self, context: ToolContext) -> str:
        if not context.site_id:
            raise ValueError(
                "This conversation has no project workspace. Attach a project first."
            )
        return context.site_id


def _int_arg(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _glob_match(path: str, pattern: str) -> bool:
    """Match a project path the way people expect globs to behave."""
    name = path.rsplit("/", 1)[-1]
    if "/" not in pattern:
        return fnmatch.fnmatch(name, pattern)
    if fnmatch.fnmatch(path, pattern):
        return True
    # Let "src/**/*.ts" also match files directly in src/.
    return "**/" in pattern and fnmatch.fnmatch(path, pattern.replace("**/", ""))


def _is_text(content_type: str) -> bool:
    kind = content_type.split(";", 1)[0].strip()
    return kind.startswith("text/") or kind in {
        "application/json",
        "application/javascript",
        "application/xml",
        "image/svg+xml",
        "application/toml",
        "application/x-yaml",
    }
