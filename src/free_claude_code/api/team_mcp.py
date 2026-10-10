"""The Studio team as an MCP server, for any AI tool that speaks MCP.

Claude Code, Codex, Cursor, Gemini CLI, VS Code, Cline, Continue, Goose, Zed,
OpenCode and others add http://127.0.0.1:8082/mcp as an HTTP MCP server and
get tools to use the team: talk to the main AI, give one agent a job, run a
team plan, check on work, stop it, and read the projects' files.

It is MCP's Streamable HTTP transport without server-sent events: each POST
carries one JSON-RPC message and gets one JSON answer. Browsers on other
sites are refused (their Origin isn't this PC), and the proxy token is
needed when one is set.
"""

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from free_claude_code.core.version import package_version
from free_claude_code.studio import StudioError, StudioNotFoundError, StudioService

from .studio_routes import Access, get_studio

router = APIRouter()

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_FILE_CHARS = 20_000
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
INSTRUCTIONS = (
    "LCC Studio's AI team runs on this PC: a main AI (it runs the team and "
    "knows the user) and agents such as a Researcher, Builder, Coder, Tester, "
    "and Helper. Use lcc_chat to talk to the main AI, lcc_ask to give one agent "
    "a job, and lcc_plan for a bigger job the team splits into steps. Long "
    "jobs: start them with wait false and check with lcc_status. lcc_projects, "
    "lcc_files, and lcc_read show what the team made."
)


def _tool(name: str, description: str, properties: dict, required=()) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
        },
    }


_TEXT = {"type": "string"}
TOOLS = (
    _tool(
        "lcc_team",
        "The team: each agent's name, role, what it does, model, and whether "
        "it is working right now.",
        {},
    ),
    _tool(
        "lcc_chat",
        "Talk to the team's main AI (it knows the user, hands out work, and "
        "answers). Returns its reply.",
        {"message": _TEXT},
        ["message"],
    ),
    _tool(
        "lcc_ask",
        "Give one agent a job (research, build, code, test, plan, ...). With "
        "wait (the default) it returns the agent's report; with wait false it "
        "returns a task id to check with lcc_status.",
        {
            "agent": {"type": "string", "description": "The agent's name."},
            "task": {"type": "string", "description": "The job, with what it needs."},
            "project": {"type": "string", "description": "Optional project name."},
            "wait": {"type": "boolean", "default": True},
        },
        ["agent", "task"],
    ),
    _tool(
        "lcc_plan",
        "Give the whole team a bigger job: it is split into steps for the right "
        "agents, run in order, each handed what the steps before it produced. "
        "Returns the plan; check it with lcc_status.",
        {"goal": _TEXT, "project": {"type": "string"}},
        ["goal"],
    ),
    _tool(
        "lcc_relay",
        "Pass a job through the relay: LCC's own agent for it does it first, "
        "then one agent from each repo in the relay (VoltAgent subagents, "
        "OpenHands, MetaGPT, FinRobot, crewAI, and others that fit), one after "
        "another, each improving the last one's work. Returns the stages; check "
        "it with lcc_status.",
        {"goal": _TEXT, "project": {"type": "string"}},
        ["goal"],
    ),
    _tool(
        "lcc_status",
        "How work is going: a plan (plan_id), one task (task_id), or, with "
        "neither, the whole team.",
        {"plan_id": _TEXT, "task_id": _TEXT},
    ),
    _tool(
        "lcc_stop",
        "Stop a plan (plan_id) or everything one agent is doing (agent).",
        {"plan_id": _TEXT, "agent": _TEXT},
    ),
    _tool("lcc_projects", "The team's projects: names, ids, and file counts.", {}),
    _tool(
        "lcc_files",
        "The files in one project.",
        {"project": {"type": "string", "description": "Project name or id."}},
        ["project"],
    ),
    _tool(
        "lcc_read",
        "Read one file from a project.",
        {"project": _TEXT, "path": _TEXT},
        ["project", "path"],
    ),
)


class ToolFailure(Exception):
    """A tool call that can't be done; told to the caller as a tool error."""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


async def _agent(studio: StudioService, name: str):
    wanted = name.strip().casefold()
    for agent in await studio.agents():
        if not agent.archived and agent.name.casefold() == wanted:
            return agent
    names = ", ".join(a.name for a in await studio.agents() if not a.archived)
    raise ToolFailure(f"No agent called {name!r}. The team: {names}.")


async def _project(studio: StudioService, wanted: str):
    key = wanted.strip().casefold()
    for site in await studio.sites():
        if key in {site.id.casefold(), site.name.casefold(), site.slug.casefold()}:
            return site
    names = ", ".join(site.name for site in await studio.sites()) or "none yet"
    raise ToolFailure(f"No project called {wanted!r}. Projects: {names}.")


def _gist(text: str) -> str:
    """The first sentence of an agent's description."""
    text = " ".join(text.split())
    end = min((i for i in (text.find(". "), text.find(": ")) if i > 0), default=-1)
    first = text[: end + 1] if end > 0 else text
    return first[:140]


async def _team(studio: StudioService, _: Mapping[str, Any]) -> str:
    busy = await studio.busy_agent_ids()
    lines = []
    for agent in await studio.agents():
        if agent.archived:
            continue
        state = "working" if agent.id in busy else "free"
        what = _gist(agent.description)
        lines.append(
            f"- {agent.name} ({agent.role}, {state}, model {agent.model})"
            + (f": {what}" if what else "")
        )
    return "\n".join(lines)


async def _chat(studio: StudioService, args: Mapping[str, Any]) -> str:
    message = _text(args.get("message"))
    if not message:
        raise ToolFailure("Say something to the main AI.")
    chat = await studio.main_say(message, background=False)
    main = await studio.main_agent()
    reply = next(
        (
            m
            for m in reversed(await studio.transcript(chat.id))
            if m.role == "assistant" and m.author == main.name and m.text.strip()
        ),
        None,
    )
    return reply.text if reply else f"{main.name} didn't answer."


async def _ask(studio: StudioService, args: Mapping[str, Any]) -> str:
    agent = await _agent(studio, _text(args.get("agent")))
    task = _text(args.get("task"))
    if not task:
        raise ToolFailure("Say what the job is.")
    project = _text(args.get("project"))
    site_id = (await _project(studio, project)).id if project else None
    if args.get("wait") is False:
        run = await studio.start_agent_task(
            agent, task, site_id=site_id, parent_chat_id=None
        )
        return f"{agent.name} started it. Task id: {run.id} (check with lcc_status)."
    run, _ = await studio.run_agent_task(
        agent, task, site_id=site_id, parent_chat_id=None
    )
    report = (run.result or run.error or "(no report)").strip()
    return f"{agent.name} {run.status} (task {run.id}):\n{report}"


async def _plan(studio: StudioService, args: Mapping[str, Any]) -> str:
    goal = _text(args.get("goal"))
    if not goal:
        raise ToolFailure("Say what the plan is for.")
    plan = await studio.start_plan(
        goal, made_by="an MCP client", project=_text(args.get("project"))
    )
    lines = [f"Plan {plan.id} started with {len(plan.steps)} step(s):"]
    lines += [
        f"{s.id}. {s.agent}: {s.do}"
        + (f" (after {', '.join(s.needs)})" if s.needs else "")
        for s in plan.steps
    ]
    lines.append("Check it with lcc_status and plan_id.")
    return "\n".join(lines)


async def _relay(studio: StudioService, args: Mapping[str, Any]) -> str:
    goal = _text(args.get("goal"))
    if not goal:
        raise ToolFailure("Say what the relay is for.")
    plan = await studio.start_relay(
        goal, made_by="an MCP client", project=_text(args.get("project"))
    )
    lines = [f"Relay {plan.id} started with {len(plan.steps)} stage(s), in order:"]
    lines += [
        f"{number}. {s.agent}" + (f" ({s.source})" if s.source else "")
        for number, s in enumerate(plan.steps, 1)
    ]
    lines.append("Check it with lcc_status and plan_id.")
    return "\n".join(lines)


async def _status(studio: StudioService, args: Mapping[str, Any]) -> str:
    plan_id, task_id = _text(args.get("plan_id")), _text(args.get("task_id"))
    if plan_id:
        plan = await studio.plan(plan_id)
        if plan.summary:
            return plan.summary
        lines = [f"Plan {plan.id} is {plan.status}: {plan.goal}"]
        lines += [
            f"{s.id}. {s.agent} [{s.status}] {s.do}"
            + (f"\n   {s.result[:400]}" if s.result else "")
            for s in plan.steps
        ]
        return "\n".join(lines)
    if task_id:
        run = await studio.run(task_id)
        report = (run.result or run.error or "").strip()
        return f"Task {run.id} is {run.status} after {run.step} steps." + (
            f"\n{report}" if report else ""
        )
    return await studio.team_report()


async def _stop(studio: StudioService, args: Mapping[str, Any]) -> str:
    plan_id, name = _text(args.get("plan_id")), _text(args.get("agent"))
    if plan_id:
        plan = await studio.stop_plan(plan_id)
        return f"Plan {plan.id} is {plan.status}."
    if name:
        agent = await _agent(studio, name)
        stopped = await studio.stop_agent_work(agent.id)
        return f"Stopped {len(stopped)} job(s) of {agent.name}."
    raise ToolFailure("Say which plan_id or agent to stop.")


async def _projects(studio: StudioService, _: Mapping[str, Any]) -> str:
    sites = await studio.sites()
    if not sites:
        return "No projects yet."
    return "\n".join(f"- {s.name} (id {s.id}, {s.file_count} files)" for s in sites)


async def _files(studio: StudioService, args: Mapping[str, Any]) -> str:
    site = await _project(studio, _text(args.get("project")))
    rows = await studio.site_files(site.id)
    if not rows:
        return f"{site.name} has no files yet."
    return "\n".join(f"- {row['path']} ({row['size']} bytes)" for row in rows)


async def _read(studio: StudioService, args: Mapping[str, Any]) -> str:
    site = await _project(studio, _text(args.get("project")))
    path = _text(args.get("path"))
    try:
        text = await studio.workspace.read(site.id, path)
    except (StudioError, UnicodeDecodeError, ValueError) as error:
        raise ToolFailure(f"Couldn't read {path!r} in {site.name}: {error}") from error
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + f"\n[... cut at {MAX_FILE_CHARS} characters]"
    return text


HANDLERS: dict[str, Callable[[StudioService, Mapping[str, Any]], Awaitable[str]]] = {
    "lcc_team": _team,
    "lcc_chat": _chat,
    "lcc_ask": _ask,
    "lcc_plan": _plan,
    "lcc_relay": _relay,
    "lcc_status": _status,
    "lcc_stop": _stop,
    "lcc_projects": _projects,
    "lcc_files": _files,
    "lcc_read": _read,
}


def _local_origin(request: Request) -> bool:
    """A page on another website must not drive the team (DNS rebinding)."""
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return True
    return (urlparse(origin).hostname or "") in LOCAL_HOSTS


def _answer(message_id: object, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: object, code: int, text: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": text},
    }


async def _handle(studio: StudioService, message: object) -> dict | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Not a JSON-RPC 2.0 message.")
    method = message.get("method")
    message_id = message.get("id")
    if "id" not in message:
        return None  # a notification (initialized, cancelled, ...)
    params = message.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        return _answer(
            message_id,
            {
                "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "lcc-studio",
                    "title": "LCC Studio team",
                    "version": package_version(),
                },
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _answer(message_id, {})
    if method == "tools/list":
        return _answer(message_id, {"tools": list(TOOLS)})
    if method == "tools/call":
        if not isinstance(params, dict):
            return _error(message_id, -32602, "params must be an object.")
        handler = HANDLERS.get(str(params.get("name")))
        if handler is None:
            return _error(message_id, -32602, f"Unknown tool {params.get('name')!r}.")
        arguments = params.get("arguments") or {}
        try:
            text = await handler(
                studio, arguments if isinstance(arguments, dict) else {}
            )
            failed = False
        except (ToolFailure, StudioError, StudioNotFoundError, ValueError) as error:
            text, failed = str(error) or type(error).__name__, True
        return _answer(
            message_id,
            {"content": [{"type": "text", "text": text}], "isError": failed},
        )
    return _error(message_id, -32601, f"Method {method!r} not found.")


@router.post("/mcp")
async def team_mcp(
    request: Request,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> Response:
    """One MCP JSON-RPC message (or a batch) in, its answer out."""
    if not studio.settings.studio_mcp_server:
        return JSONResponse(
            status_code=403,
            content=_error(
                None, -32000, "The team's MCP server is turned off in Settings."
            ),
        )
    if not _local_origin(request):
        return JSONResponse(
            status_code=403, content=_error(None, -32000, "Not from this PC.")
        )
    try:
        body = json.loads(await request.body() or b"null")
    except ValueError:
        return JSONResponse(
            status_code=400, content=_error(None, -32700, "The body isn't JSON.")
        )
    if isinstance(body, list):
        answers = [a for a in [await _handle(studio, m) for m in body] if a is not None]
        return JSONResponse(content=answers) if answers else Response(status_code=202)
    answer = await _handle(studio, body)
    if answer is None:
        return Response(status_code=202)
    return JSONResponse(content=answer)


@router.api_route("/mcp", methods=["GET", "DELETE"])
async def team_mcp_other(_: None = Access) -> Response:
    """No event stream and no sessions: every answer comes back on its POST."""
    return Response(status_code=405, headers={"Allow": "POST"})
