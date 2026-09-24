"""HTTP adapter for the Studio app: agents, models, tuning, and classes."""

import asyncio
import secrets
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject
from free_claude_code.core.version import package_version
from free_claude_code.studio import StudioError, StudioNotFoundError, StudioService
from free_claude_code.studio.downloads import DownloadError
from free_claude_code.studio.lora import (
    KNOWN_BASES,
    WORKER_PATH,
    LoraAuthError,
    LoraError,
)
from free_claude_code.studio.models import Agent, LoraJob
from free_claude_code.studio.school import SchoolError
from free_claude_code.studio.sites import SiteError, content_type_for
from free_claude_code.studio.tuning import TuningError

from .dependencies import get_services, get_settings
from .ports import ApiServices

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent / "studio_static"
_ASSET_VERSION_PLACEHOLDER = "__FCC_VERSION__"
_UI_THEME_PLACEHOLDER = "__FCC_UI_THEME__"
_ASSET_FILENAMES = frozenset(
    {
        "studio.css",
        "studio.js",
        "icon.svg",
        "icon-180.png",
        "icon-192.png",
        "icon-512.png",
    }
)


class ChatPayload(BaseModel):
    agent_id: str | None = None
    title: str = ""
    kind: str = "chat"
    site_id: str | None = None


class MessagePayload(BaseModel):
    text: str


class ChatSettingsPayload(BaseModel):
    settings: JsonObject = Field(default_factory=dict)


class AgentPayload(BaseModel):
    name: str
    role: str = "assistant"
    model: str = ""
    system_prompt: str = ""
    tools: list[str] | None = None
    memory_enabled: bool = True
    description: str = ""


class TeachPayload(BaseModel):
    text: str = ""
    url: str = ""


class AgentUpdatePayload(BaseModel):
    updates: JsonObject = Field(default_factory=dict)


class TaskPayload(BaseModel):
    agent_id: str
    goal: str
    site_id: str | None = None
    chat_id: str | None = None


class SitePayload(BaseModel):
    name: str
    description: str = ""
    agent_id: str | None = None


class SiteFilePayload(BaseModel):
    path: str
    content: str


class DownloadPayload(BaseModel):
    catalog_id: str = ""
    url: str = ""
    name: str = ""
    sha256: str = ""


class PackPayload(BaseModel):
    agent_id: str
    name: str = ""
    teacher_model: str | None = None


class TuneStartPayload(BaseModel):
    backend: str | None = None


class SamplePayload(BaseModel):
    pairs: list[tuple[str, str]] = Field(default_factory=list)
    split: str = "train"


class CoursePayload(BaseModel):
    topic: str
    lesson_count: int = 3
    start: bool = True
    teacher_id: str | None = None
    student_id: str | None = None


class MemoryPayload(BaseModel):
    text: str
    scope: str = "long_term"


class GuidePayload(BaseModel):
    question: str


class BootstrapPayload(BaseModel):
    download_guide: bool = False


class LoraPayload(BaseModel):
    agent_id: str
    base_model: str
    runner: str = "local"
    sources: list[str] = Field(default_factory=lambda: ["examples", "classes"])
    topics: list[str] = Field(default_factory=list)
    examples_per_topic: int = 8
    teacher_model: str | None = None
    ollama_base: str = ""
    rank: int | None = None
    alpha: int | None = None
    epochs: int | None = None
    learning_rate: float | None = None
    max_seq_len: int | None = None
    quantize: str | None = None
    export: str | None = None
    gguf_quant: str | None = None


class WorkerFailure(BaseModel):
    error: str = "The worker failed."


class RoomPayload(BaseModel):
    title: str = ""
    member_ids: list[str] = Field(default_factory=list)
    goal: str = ""
    site_id: str | None = None


class RoomMembersPayload(BaseModel):
    member_ids: list[str]


class GoalPayload(BaseModel):
    goal: str


class SyncPayload(BaseModel):
    chat_id: str | None = None
    course_id: str | None = None
    agent_id: str | None = None


def require_studio_access(
    request: Request, settings: Settings = Depends(get_settings)
) -> None:
    """Require the proxy token for Studio when proxy auth is enabled."""
    if not settings.proxy_auth_enabled:
        return
    presented = (
        _bearer(request.headers.get("authorization"))
        or request.headers.get("x-api-key")
        or request.query_params.get("token")
        or request.cookies.get("fcc_studio_token")
        or ""
    )
    if not presented or not secrets.compare_digest(
        presented.encode("utf-8"), settings.proxy_auth_token.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Studio requires the proxy token.")


def _bearer(value: str | None) -> str:
    if not value:
        return ""
    parts = value.split(maxsplit=1)
    if len(parts) == 2 and parts[0].casefold() == "bearer":
        return parts[1].strip()
    return ""


def get_studio(services: ApiServices = Depends(get_services)) -> StudioService:
    """Return the Studio service, or report that Studio is switched off."""
    if services.studio is None:
        raise HTTPException(status_code=503, detail="Studio is disabled.")
    return services.studio


Access = Depends(require_studio_access)


def _asset_path(filename: str) -> Path:
    path = STATIC_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Studio asset not found")
    return path


@router.get("/studio", include_in_schema=False)
def studio_page(
    settings: Settings = Depends(get_settings), _: None = Access
) -> HTMLResponse:
    """Serve the installable Studio app shell."""
    template = _asset_path("index.html").read_text(encoding="utf-8")
    page = template.replace(_ASSET_VERSION_PLACEHOLDER, package_version()).replace(
        _UI_THEME_PLACEHOLDER, settings.studio_ui_theme
    )
    return HTMLResponse(page)


@router.get("/studio/manifest.webmanifest", include_in_schema=False)
def studio_manifest() -> JSONResponse:
    """Serve the web app manifest so iOS can install Studio."""
    return JSONResponse(
        {
            "name": "FCC Studio",
            "short_name": "Studio",
            "start_url": "/studio",
            "scope": "/studio",
            "display": "standalone",
            "background_color": "#0b0d12",
            "theme_color": "#0b0d12",
            "orientation": "portrait",
            "id": "/studio",
            "icons": [
                {
                    "src": f"/studio/assets/{package_version()}/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": f"/studio/assets/{package_version()}/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": f"/studio/assets/{package_version()}/icon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any",
                },
            ],
        },
        media_type="application/manifest+json",
    )


@router.get("/studio/sw.js", include_in_schema=False)
def studio_service_worker() -> Response:
    """Serve the service worker with the scope the app shell needs."""
    body = _asset_path("sw.js").read_text(encoding="utf-8")
    return Response(
        content=body.replace(_ASSET_VERSION_PLACEHOLDER, package_version()),
        media_type="text/javascript",
        headers={"service-worker-allowed": "/studio", "cache-control": "no-cache"},
    )


@router.get("/studio/assets/{version}/{filename}", include_in_schema=False)
def studio_asset(version: str, filename: str) -> FileResponse:
    """Serve a versioned Studio asset."""
    if version != package_version() or filename not in _ASSET_FILENAMES:
        raise HTTPException(status_code=404, detail="Studio asset not found")
    return FileResponse(_asset_path(filename))


@router.get("/studio/api/connect")
def studio_connect(
    request: Request, settings: Settings = Depends(get_settings), _: None = Access
) -> JsonObject:
    """Tell the user every address this device can open Studio on."""
    token = settings.proxy_auth_token if settings.proxy_auth_enabled else ""
    suffix = f"?token={token}" if token else ""
    addresses = _reachable_hosts(settings.host)
    # Prefer the port this request actually arrived on over the configured one.
    port = request.url.port or settings.port
    return {
        "urls": [f"http://{host}:{port}/studio{suffix}" for host in addresses],
        "port": port,
        "bound_host": settings.host,
        "loopback_only": _is_loopback_bind(settings.host),
        "auth_required": settings.proxy_auth_enabled,
        "viewing_from": request.client.host if request.client else "",
    }


def _is_loopback_bind(host: str) -> bool:
    """Return whether the server is only listening to this machine."""
    return host.strip() in {"127.0.0.1", "::1", "localhost"}


def _reachable_hosts(bound_host: str) -> tuple[str, ...]:
    """Return loopback, LAN, and Bonjour names this server answers on."""
    hosts: list[str] = ["localhost"]
    if _is_loopback_bind(bound_host):
        return tuple(hosts)
    hostname = socket.gethostname()
    # Windows does not reliably answer Bonjour names, so offer IPs only there.
    if hostname and "." not in hostname and sys.platform != "win32":
        hosts.append(f"{hostname}.local")
    for address in _local_addresses():
        if address not in hosts:
            hosts.append(address)
    return tuple(hosts)


def _local_addresses() -> tuple[str, ...]:
    """Return this machine's IPv4 addresses without sending any traffic."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 53))  # TEST-NET-1: routed nowhere
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = str(info[4][0])
            if address not in found and not address.startswith("127."):
                found.append(address)
    except OSError:
        pass
    return tuple(found)


@router.get("/studio/api/overview")
async def overview(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Return everything the home screen shows."""
    return await studio.overview()


@router.post("/studio/api/bootstrap")
async def bootstrap(
    payload: BootstrapPayload | None = None,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Create the starter agents, and fetch the guide model only when asked."""
    created = await studio.ensure_defaults()
    asset = (
        await studio.ensure_guide_model()
        if payload is not None and payload.download_guide
        else None
    )
    return {
        "created_agents": [agent.name for agent in created],
        "guide_download": asset.model_dump() if asset else None,
    }


class SearchTestPayload(BaseModel):
    query: str = ""


@router.get("/studio/api/web")
async def web_status(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Say which search service agents use and whether it is ready."""
    return studio.web_status()


@router.post("/studio/api/web/test")
async def web_test(
    payload: SearchTestPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Run one search exactly as an agent would."""
    return await studio.test_search(payload.query)


@router.get("/studio/api/main")
async def main_console(
    after: int = 0,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return the HUD: the main AI's conversation, its team, and systems."""
    return await studio.main_console(after=after)


@router.post("/studio/api/main/messages", status_code=202)
async def main_say(
    payload: MessagePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Talk to the main AI; it answers in the background while the HUD polls."""
    chat = await studio.main_say(payload.text)
    return {"accepted": True, "chat_id": chat.id}


@router.post("/studio/api/main/new")
async def main_new_conversation(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Start a fresh conversation with the main AI."""
    chat = await studio.main_chat(fresh=True)
    return chat.model_dump()


@router.get("/studio/api/agents")
async def list_agents(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Return every agent."""
    return {"agents": [agent.model_dump() for agent in await studio.agents()]}


@router.post("/studio/api/agents")
async def create_agent(
    payload: AgentPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Create one agent."""
    agent = await studio.create_agent(
        name=payload.name,
        role=payload.role,
        model=payload.model,
        system_prompt=payload.system_prompt,
        tools=payload.tools,
        memory_enabled=payload.memory_enabled,
        description=payload.description,
    )
    return agent.model_dump()


@router.get("/studio/api/agent-options")
async def agent_options(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """List the roles and tools the add-agent sheet offers."""
    return studio.agent_options()


@router.post("/studio/api/agents/{agent_id}/teach")
async def teach_agent(
    agent_id: str,
    payload: TeachPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Teach one agent a skill from a link or notes."""
    entry = await studio.teach_agent(agent_id, text=payload.text, url=payload.url)
    return entry.model_dump()


@router.get("/studio/api/agents/{agent_id}/skills")
async def agent_skills(
    agent_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return what the user taught one agent."""
    return {"skills": [entry.model_dump() for entry in await studio.skills(agent_id)]}


@router.patch("/studio/api/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    payload: AgentUpdatePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Apply a partial update to one agent."""
    agent = await studio.update_agent(agent_id, payload.updates)
    return agent.model_dump()


@router.delete("/studio/api/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Delete one agent and its memories."""
    return {"deleted": await studio.delete_agent(agent_id)}


@router.get("/studio/api/chats")
async def list_chats(
    kind: str | None = None,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return chats, newest activity first."""
    chats = await studio.chats(kind=kind)
    return {"chats": [chat.model_dump() for chat in chats]}


@router.post("/studio/api/chats")
async def create_chat(
    payload: ChatPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Open one chat."""
    chat = await studio.create_chat(
        agent_id=payload.agent_id,
        title=payload.title,
        kind=payload.kind,
        site_id=payload.site_id,
    )
    return chat.model_dump()


@router.get("/studio/api/chats/{chat_id}")
async def read_chat(
    chat_id: str,
    after: int = 0,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return one chat and its transcript."""
    chat = await studio.chat(chat_id)
    messages = await studio.transcript(chat_id, after=after)
    return {
        "chat": chat.model_dump(),
        "messages": [message.model_dump() for message in messages],
    }


@router.post("/studio/api/chats/{chat_id}/messages")
async def send_message(
    chat_id: str,
    payload: MessagePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Send one message and return the agent's reply."""
    result = await studio.send(chat_id, payload.text)
    messages = await studio.transcript(chat_id)
    return {
        "reply": result.text,
        "steps": result.steps,
        "failed": result.failed,
        "tool_calls": list(result.tool_calls),
        "messages": [message.model_dump() for message in messages],
    }


@router.post("/studio/api/chats/{chat_id}/settings")
async def update_chat_settings(
    chat_id: str,
    payload: ChatSettingsPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Change chat settings; some toggles open a fresh chat."""
    result = await studio.update_chat_settings(chat_id, payload.settings)
    return {
        "chat": result.chat.model_dump(),
        "opened_chat": result.opened_chat.model_dump() if result.opened_chat else None,
        "note": result.note,
    }


@router.delete("/studio/api/chats/{chat_id}")
async def delete_chat(
    chat_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Delete one chat and its transcript."""
    return {"deleted": await studio.delete_chat(chat_id)}


@router.get("/studio/api/commands/pending")
async def pending_commands(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Return agent commands waiting for approval, and whether commands are on."""
    pending = await studio.pending_commands()
    return {
        "policy": studio.settings.studio_agent_commands,
        "pending": [item.model_dump() for item in pending],
    }


@router.post("/studio/api/commands/{request_id}/approve")
async def approve_command(
    request_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Let an agent run the command it asked for."""
    return (await studio.decide_command(request_id, approve=True)).model_dump()


@router.post("/studio/api/commands/{request_id}/deny")
async def deny_command(
    request_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Refuse a command; the agent is told and carries on."""
    return (await studio.decide_command(request_id, approve=False)).model_dump()


@router.get("/studio/api/rooms")
async def list_rooms(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Return every agent chat room."""
    return {"rooms": [room.model_dump() for room in await studio.rooms()]}


@router.post("/studio/api/rooms")
async def create_room(
    payload: RoomPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Open a room; with no members listed, every working agent joins."""
    room = await studio.create_room(
        title=payload.title,
        member_ids=payload.member_ids,
        goal=payload.goal,
        site_id=payload.site_id,
    )
    return room.model_dump()


@router.get("/studio/api/rooms/{room_id}")
async def read_room(
    room_id: str,
    after: int = 0,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return a room, its members, task state, and transcript."""
    return await studio.room_detail(room_id, after=after)


@router.put("/studio/api/rooms/{room_id}/members")
async def set_room_members(
    room_id: str,
    payload: RoomMembersPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Change who is in a room."""
    room = await studio.room_members(room_id, payload.member_ids)
    return room.model_dump()


@router.post("/studio/api/rooms/{room_id}/messages", status_code=202)
async def room_message(
    room_id: str,
    payload: MessagePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Post to the room; agents answer in the background."""
    await studio.room_say(room_id, payload.text)
    return {"accepted": True}


@router.post("/studio/api/rooms/{room_id}/task", status_code=202)
async def room_task(
    room_id: str,
    payload: GoalPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Start a task the agents plan, hand off, and finish together."""
    await studio.room_start_task(room_id, payload.goal)
    return {"accepted": True}


@router.post("/studio/api/rooms/{room_id}/continue", status_code=202)
async def room_continue(
    room_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Let the agents keep going after a pause."""
    await studio.room_continue(room_id)
    return {"accepted": True}


@router.post("/studio/api/rooms/{room_id}/stop")
async def room_stop(
    room_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Stop the agents after the turn in progress."""
    room = await studio.room_stop(room_id)
    return room.model_dump()


@router.post("/studio/api/tasks")
async def start_task(
    payload: TaskPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Start one autonomous agent task."""
    run = await studio.start_task(
        agent_id=payload.agent_id,
        goal=payload.goal,
        site_id=payload.site_id,
        chat_id=payload.chat_id,
    )
    return run.model_dump()


@router.get("/studio/api/tasks")
async def list_tasks(
    agent_id: str | None = None,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return agent tasks."""
    runs = await studio.runs(agent_id=agent_id)
    return {"runs": [run.model_dump() for run in runs]}


@router.get("/studio/api/tasks/{run_id}")
async def read_task(
    run_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return one agent task and its live transcript."""
    run = await studio.run(run_id)
    messages = await studio.transcript(run.chat_id)
    return {
        "run": run.model_dump(),
        "messages": [message.model_dump() for message in messages],
    }


@router.get("/studio/api/sites")
async def list_sites(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Return every website workspace."""
    return {"sites": [site.model_dump() for site in await studio.sites()]}


@router.post("/studio/api/sites")
async def create_site(
    payload: SitePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Create one website workspace."""
    site = await studio.create_site(
        name=payload.name, description=payload.description, agent_id=payload.agent_id
    )
    return site.model_dump()


@router.get("/studio/api/sites/{site_id}/files")
async def list_site_files(
    site_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return the files in one website workspace."""
    site = await studio.site(site_id)
    return {"site": site.model_dump(), "files": list(await studio.site_files(site_id))}


@router.put("/studio/api/sites/{site_id}/files")
async def write_site_file(
    site_id: str,
    payload: SiteFilePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Write one file into a website workspace."""
    return await studio.write_site_file(site_id, payload.path, payload.content)


@router.delete("/studio/api/sites/{site_id}")
async def delete_site(
    site_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Delete one website workspace."""
    return {"deleted": await studio.delete_site(site_id)}


@router.get("/studio/api/sites/{site_id}/archive", include_in_schema=False)
async def download_site(
    site_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> Response:
    """Download one website workspace as a zip archive."""
    site = await studio.site(site_id)
    payload = await studio.workspace.archive(site_id)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{site.slug}.zip"'},
    )


@router.get("/studio/sites/{site_id}/{file_path:path}", include_in_schema=False)
async def preview_site(
    site_id: str,
    file_path: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> Response:
    """Serve one file from a website workspace for live preview."""
    await studio.site(site_id)
    relative = file_path or "index.html"
    if relative.endswith("/"):
        relative = f"{relative}index.html"
    payload = await studio.workspace.read_bytes(site_id, relative)
    return Response(content=payload, media_type=content_type_for(relative))


@router.get("/studio/api/models")
async def list_models(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Return the curated catalog and every tracked download."""
    assets = await studio.assets()
    return {
        "catalog": list(studio.catalog()),
        "assets": [
            {**asset.model_dump(), "progress": asset.progress} for asset in assets
        ],
        "models_dir": str(studio.library.directory),
    }


@router.get("/studio/api/models/available")
async def available_models(
    services: ApiServices = Depends(get_services),
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return server models FCC can route to and local models being served."""
    # Right after startup the provider catalog is still loading; wait briefly.
    try:
        snapshot = await asyncio.wait_for(services.requests.wait_for_catalog(), 5.0)
        infos = snapshot.cached_prefixed_model_infos()
    except TimeoutError:
        infos = services.requests.cached_prefixed_model_infos()
    settings = services.requests.current_settings()
    configured = {settings.model, *(settings.model_fallbacks or ())}
    if settings.studio_default_model:
        configured.add(settings.studio_default_model)
    server = sorted({info.model_id for info in infos} | configured)
    return {
        "default_model": studio.default_model,
        "server": server,
        "local": await studio.local_models(),
    }


@router.post("/studio/api/models/download")
async def download_model(
    payload: DownloadPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Queue one model download and start it in the background."""
    asset = await studio.download_model(
        catalog_id=payload.catalog_id,
        url=payload.url,
        name=payload.name,
        sha256=payload.sha256,
    )
    return asset.model_dump()


@router.post("/studio/api/models/{asset_id}/cancel")
async def cancel_download(
    asset_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Stop one download; the partial file stays so it can resume."""
    asset = await studio.library.cancel(asset_id)
    return asset.model_dump()


@router.delete("/studio/api/models/{asset_id}")
async def delete_model(
    asset_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Delete one downloaded model file."""
    return {"deleted": await studio.library.remove(asset_id)}


@router.post("/studio/api/models/scan")
async def scan_models(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Adopt model files copied into the models folder by hand."""
    adopted = await studio.library.scan_directory()
    return {"adopted": [asset.model_dump() for asset in adopted]}


@router.get("/studio/api/tuning")
async def tuning_state(
    agent_id: str | None = None,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return tune packs and jobs for the tuning screen."""
    packs = await studio.packs(agent_id=agent_id)
    jobs = await studio.jobs(agent_id=agent_id)
    return {
        "enabled": studio.settings.studio_light_tuning_enabled,
        "backend": studio.settings.studio_tuning_backend,
        "options": studio.tuning_options(),
        "packs": [pack.model_dump() for pack in packs],
        "jobs": [{**job.model_dump(), "progress": job.progress} for job in jobs],
    }


@router.post("/studio/api/tuning/packs")
async def create_pack(
    payload: PackPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Create one tune pack for an agent."""
    pack = await studio.create_pack(
        payload.agent_id, name=payload.name, teacher_model=payload.teacher_model
    )
    return pack.model_dump()


@router.post("/studio/api/tuning/packs/{pack_id}/samples")
async def add_samples(
    pack_id: str,
    payload: SamplePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Attach example answers to a pack."""
    added = await studio.add_samples(pack_id, payload.pairs, split=payload.split)
    samples = await studio.samples(pack_id)
    return {"added": added, "total": len(samples)}


@router.post("/studio/api/tuning/packs/{pack_id}/start")
async def start_tuning(
    pack_id: str,
    payload: TuneStartPayload | None = None,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Start a tuning run: "local_light" on this machine or "cloud" on the server."""
    backend = payload.backend if payload is not None else None
    job = await studio.start_tuning(pack_id, backend=backend)
    return {**job.model_dump(), "progress": job.progress}


@router.post("/studio/api/tuning/jobs/{job_id}/refresh")
async def refresh_tuning(
    job_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Check a server tuning run again."""
    job = await studio.refresh_job(job_id)
    return {**job.model_dump(), "progress": job.progress}


@router.get("/studio/api/tuning/jobs/{job_id}")
async def read_job(
    job_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return one tuning job's live progress."""
    job = await studio.job(job_id)
    return {**job.model_dump(), "progress": job.progress}


@router.post("/studio/api/tuning/jobs/{job_id}/cancel")
async def cancel_tuning(
    job_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Stop a tuning run at its next checkpoint."""
    job = await studio.cancel_job(job_id)
    return job.model_dump()


def _lora_view(job: LoraJob) -> JsonObject:
    """A job as the UI sees it; the worker token is shown only via commands."""
    data = job.model_dump(exclude={"worker_token"})
    data["progress"] = job.progress
    return data


def _worker_url(request: Request, settings: Settings) -> str:
    """The Studio address a remote worker should call back to."""
    if settings.studio_lora_public_url:
        return settings.studio_lora_public_url.rstrip("/")
    port = request.url.port or settings.port
    hosts = [host for host in _reachable_hosts(settings.host) if host != "localhost"]
    return f"http://{hosts[0] if hosts else 'localhost'}:{port}"


@router.get("/studio/api/lora")
async def lora_overview(
    agent_id: str | None = None,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return trainable base models and LoRA jobs."""
    where = {"agent_id": agent_id} if agent_id else None
    jobs = await studio.store.find(LoraJob, where=where, order_by="created_at DESC")
    return {
        "bases": [
            {
                "repo": base.repo,
                "ollama": base.ollama,
                "size": base.size,
                "note": base.note,
                "gated": base.gated,
            }
            for base in KNOWN_BASES
        ],
        "jobs": [_lora_view(job) for job in jobs],
    }


@router.get("/studio/api/lora/environment")
async def lora_environment(
    refresh: bool = False,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Report whether this computer can train, and whether Ollama can serve."""
    return await studio.lora.probe(refresh=refresh)


@router.post("/studio/api/lora/jobs")
async def create_lora_job(
    payload: LoraPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Start a LoRA job: build the data, then train here or on a worker."""
    hyper = payload.model_dump(
        include={
            "rank",
            "alpha",
            "epochs",
            "learning_rate",
            "max_seq_len",
            "quantize",
            "export",
            "gguf_quant",
        }
    )
    job = await studio.lora.create(
        agent_id=payload.agent_id,
        base_model=payload.base_model,
        runner=payload.runner,
        sources=payload.sources,
        topics=payload.topics,
        examples_per_topic=payload.examples_per_topic,
        teacher_model=payload.teacher_model,
        ollama_base=payload.ollama_base,
        hyper=hyper,
    )
    return _lora_view(job)


@router.get("/studio/api/lora/jobs/{job_id}")
async def read_lora_job(
    job_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return one job, its files, and how to run it on another machine."""
    job = await studio.store.require(LoraJob, job_id)
    folder = studio.lora.job_dir(job.id)
    files = [
        name
        for name in (
            "train.jsonl",
            "eval.jsonl",
            "model.gguf",
            "adapter.zip",
            "adapter.gguf",
            "Modelfile",
            "worker.log",
        )
        if (folder / name).is_file()
    ]
    view = _lora_view(job)
    view["files"] = files
    agent = await studio.store.get(Agent, job.agent_id)
    view["agent_name"] = agent.name if agent else ""
    view["agent_model"] = agent.model if agent else ""
    view["in_use"] = bool(
        agent
        and job.status == "succeeded"
        and studio.lora.ollama_name(job, agent) in agent.model
    )
    lmstudio = studio.lora.lmstudio_dir()
    view["lmstudio_dir"] = str(lmstudio) if lmstudio else ""
    if job.status not in {"succeeded", "failed", "cancelled"}:
        url = _worker_url(request, settings)
        commands = studio.lora.worker_commands(job, url)
        if (urlsplit(url).hostname or "") in {"localhost", "127.0.0.1", "::1"}:
            commands["warning"] = (
                "Studio only accepts connections from this computer, so another "
                "machine can't reach it. Set Address For Remote Trainers (a "
                "Tailscale address works well) or run Studio with HOST=0.0.0.0."
            )
        view["commands"] = commands
    return view


@router.post("/studio/api/lora/jobs/{job_id}/cancel")
async def cancel_lora_job(
    job_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Stop a LoRA job."""
    return _lora_view(await studio.lora.cancel(job_id))


@router.post("/studio/api/lora/jobs/{job_id}/install")
async def install_lora_job(
    job_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Try installing a finished adapter into Ollama again."""
    return _lora_view(await studio.lora.install(job_id))


@router.post("/studio/api/lora/jobs/{job_id}/switch")
async def switch_lora_job(
    job_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Point the student at the trained model once LM Studio or Ollama serves it."""
    return _lora_view(await studio.lora.switch(job_id))


@router.post("/studio/api/lora/jobs/{job_id}/revert")
async def revert_lora_job(
    job_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Point the student back at the model it used before this job."""
    return _lora_view(await studio.lora.revert(job_id))


@router.get("/studio/api/lora/jobs/{job_id}/files/{name}", include_in_schema=False)
async def lora_file(
    job_id: str,
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> FileResponse:
    """Download a job's dataset, adapter, Modelfile, or trainer log."""
    return FileResponse(studio.lora.file_path(job_id, name), filename=name)


@router.get("/studio/lora/worker.py", include_in_schema=False)
def lora_worker_script() -> FileResponse:
    """Serve the standalone trainer so a GPU machine can download it."""
    return FileResponse(
        WORKER_PATH, media_type="text/x-python", filename="lora_worker.py"
    )


async def _worker_job(job_id: str, request: Request, studio: StudioService) -> LoraJob:
    return await studio.lora.authorize(job_id, request.headers.get("x-lora-token", ""))


@router.get("/studio/api/lora/worker/{job_id}/spec", include_in_schema=False)
async def worker_spec(
    job_id: str, request: Request, studio: StudioService = Depends(get_studio)
) -> JsonObject:
    job = await _worker_job(job_id, request, studio)
    if job.status in {"succeeded", "failed", "cancelled"}:
        raise HTTPException(status_code=410, detail="This job has already ended.")
    return studio.lora.spec(job)


@router.get("/studio/api/lora/worker/{job_id}/dataset", include_in_schema=False)
async def worker_dataset(
    job_id: str,
    request: Request,
    split: str = "train",
    studio: StudioService = Depends(get_studio),
) -> FileResponse:
    job = await _worker_job(job_id, request, studio)
    if not job.dataset_ready:
        raise HTTPException(status_code=409, detail="The training set is not ready.")
    return FileResponse(
        await studio.lora.dataset_path(job, split), media_type="application/jsonl"
    )


@router.post("/studio/api/lora/worker/{job_id}/progress", include_in_schema=False)
async def worker_progress(
    job_id: str, request: Request, studio: StudioService = Depends(get_studio)
) -> JsonObject:
    job = await _worker_job(job_id, request, studio)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Progress must be a JSON object.")
    return await studio.lora.report(job, payload)


@router.put("/studio/api/lora/worker/{job_id}/files/{name}", include_in_schema=False)
async def worker_upload(
    job_id: str,
    name: str,
    request: Request,
    studio: StudioService = Depends(get_studio),
) -> JsonObject:
    job = await _worker_job(job_id, request, studio)
    size = await studio.lora.receive(job, name, request.stream())
    return {"stored": name, "bytes": size}


@router.post("/studio/api/lora/worker/{job_id}/finish", include_in_schema=False)
async def worker_finish(
    job_id: str, request: Request, studio: StudioService = Depends(get_studio)
) -> JsonObject:
    job = await _worker_job(job_id, request, studio)
    payload = await request.json()
    return _lora_view(
        await studio.lora.finish(job, payload if isinstance(payload, dict) else {})
    )


@router.post("/studio/api/lora/worker/{job_id}/fail", include_in_schema=False)
async def worker_fail(
    job_id: str,
    payload: WorkerFailure,
    request: Request,
    studio: StudioService = Depends(get_studio),
) -> JsonObject:
    job = await _worker_job(job_id, request, studio)
    return _lora_view(await studio.lora.fail(job.id, payload.error))


@router.get("/studio/api/school/courses")
async def list_courses(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Return every class."""
    courses = await studio.courses()
    return {
        "enabled": studio.settings.studio_teacher_enabled,
        "pass_mark": studio.settings.studio_class_pass_mark,
        "courses": [
            {**course.model_dump(), "progress": course.progress} for course in courses
        ],
    }


@router.post("/studio/api/school/courses")
async def open_course(
    payload: CoursePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Open a class and optionally start teaching it right away."""
    course = await studio.open_class(
        topic=payload.topic,
        lesson_count=payload.lesson_count,
        start=payload.start,
        teacher_id=payload.teacher_id,
        student_id=payload.student_id,
    )
    return course.model_dump()


@router.get("/studio/api/school/courses/{course_id}")
async def read_course(
    course_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return one class with lessons, test results, and the classroom chat."""
    return await studio.course_detail(course_id)


@router.post("/studio/api/school/courses/{course_id}/start")
async def start_course(
    course_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Start or resume teaching one class in the background."""
    studio.start_class(course_id)
    return {"started": True, "course_id": course_id}


@router.get("/studio/api/memory/{agent_id}")
async def list_memory(
    agent_id: str,
    scope: str | None = None,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Return one agent's memories."""
    entries = await studio.memories(agent_id, scope=scope)
    return {"memories": [entry.model_dump() for entry in entries]}


@router.post("/studio/api/memory/{agent_id}")
async def write_memory(
    agent_id: str,
    payload: MemoryPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Write one memory by hand."""
    entry = await studio.remember(agent_id, payload.text, scope=payload.scope)
    return entry.model_dump() if entry else {}


@router.delete("/studio/api/memory/entry/{memory_id}")
async def forget_memory(
    memory_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Delete one memory."""
    return {"deleted": await studio.forget(memory_id)}


@router.post("/studio/api/memory/entry/{memory_id}/promote")
async def promote_memory(
    memory_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Move a working note into long-term memory."""
    entry = await studio.promote_memory(memory_id)
    return entry.model_dump()


@router.get("/studio/api/obsidian")
async def obsidian_status(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Describe the configured Obsidian vault."""
    status = await studio.vault_status()
    return {
        "configured": status.configured,
        "path": status.path,
        "exists": status.exists,
        "writable": status.writable,
        "note_count": status.note_count,
        "candidates": list(status.candidates),
        "folder": studio.settings.studio_obsidian_folder,
        "auto_sync": studio.settings.studio_obsidian_auto_sync,
        "memory_sync": studio.settings.studio_obsidian_memory_sync,
    }


@router.post("/studio/api/obsidian/memory/sync")
async def obsidian_memory_sync(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Pull memory edits from the vault, then mirror every agent's memory."""
    return await studio.sync_memory_structure()


@router.post("/studio/api/obsidian/memory/pull")
async def obsidian_memory_pull(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Apply memory edits made in Obsidian without writing anything back."""
    return {"pulled": await studio.pull_memory_edits()}


@router.post("/studio/api/obsidian/sync")
async def obsidian_sync(
    payload: SyncPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Write one chat, class, or agent memory into the vault."""
    if payload.chat_id:
        return {"note": await studio.sync_chat(payload.chat_id)}
    if payload.course_id:
        return {"note": await studio.sync_course(payload.course_id)}
    if payload.agent_id:
        return {"note": await studio.sync_memory(payload.agent_id)}
    raise HTTPException(status_code=400, detail="Choose something to sync.")


@router.post("/studio/api/obsidian/import")
async def obsidian_import(
    payload: SyncPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Import vault Inbox notes into one agent's memory."""
    if not payload.agent_id:
        raise HTTPException(status_code=400, detail="Choose an agent.")
    return {"imported": await studio.import_vault_notes(payload.agent_id)}


@router.post("/studio/api/guide/ask")
async def ask_guide(
    payload: GuidePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Ask the small preloaded guide model how the app works."""
    answer = await studio.ask_guide(payload.question)
    return {
        "text": answer.text,
        "topics": list(answer.topics),
        "route": answer.route,
        "offline": answer.offline,
    }


def studio_error_status(error: Exception) -> int:
    """Map a Studio failure to its HTTP status."""
    if isinstance(error, StudioNotFoundError):
        return 404
    if isinstance(error, LoraAuthError):
        return 401
    if isinstance(
        error, SiteError | DownloadError | TuningError | SchoolError | LoraError
    ):
        return 400
    if isinstance(error, StudioError):
        return 400
    return 500
