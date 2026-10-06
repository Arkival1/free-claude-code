"""HTTP adapter for the Studio app: agents, models, tuning, and classes."""

import asyncio
import contextlib
import json
import re
import secrets
import socket
import sys
import time
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel, Field

from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject
from free_claude_code.core.version import package_version
from free_claude_code.studio import StudioError, StudioNotFoundError, StudioService
from free_claude_code.studio.downloads import DownloadError
from free_claude_code.studio.extensions import Extension
from free_claude_code.studio.farm.farm import FarmError
from free_claude_code.studio.farm.library import (
    MAX_UPLOAD as MAX_LIBRARY_UPLOAD,
)
from free_claude_code.studio.farm.library import (
    LibraryError,
    asset_view,
    kind_of,
)
from free_claude_code.studio.file_text import MAX_UPLOAD, read_file_text
from free_claude_code.studio.lab.sim import LabError
from free_claude_code.studio.llm import ChatMessage
from free_claude_code.studio.local_voice import LocalVoiceError
from free_claude_code.studio.lora import (
    KNOWN_BASES,
    WORKER_PATH,
    LoraAuthError,
    LoraError,
)
from free_claude_code.studio.models import Agent, LoraJob, PhoneLink, VideoNote
from free_claude_code.studio.phone_link import PhoneAuthError, PhoneLinkError
from free_claude_code.studio.photos import MAX_PHOTO_BYTES, PhotoError
from free_claude_code.studio.playbook import PlaybookNote
from free_claude_code.studio.school import SchoolError
from free_claude_code.studio.sites import SiteError, content_type_for
from free_claude_code.studio.tuning import TuningError
from free_claude_code.studio.vault import VaultError, item_view
from free_claude_code.studio.videos import clock, render_note
from free_claude_code.studio.voice import MAX_AUDIO_BYTES, VoiceError

from .dependencies import get_services, get_settings
from .ports import ApiServices

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent / "studio_static"
_ASSET_VERSION_PLACEHOLDER = "__FCC_VERSION__"
_ASSET_FILENAMES = frozenset(
    {
        "studio.css",
        "studio.js",
        "lab.css",
        "lab.js",
        "farm.css",
        "farm.js",
        "hq.css",
        "hq.js",
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
    all_tools: bool = True


class StudyPayload(BaseModel):
    topic: str = Field(min_length=3, max_length=160)
    focus: str = Field(default="", max_length=300)
    depth: Literal["quick", "normal", "deep"] = "normal"


class TodoPayload(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    due: str = Field(default="", max_length=80)


class VideoPayload(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    focus: str = Field(default="", max_length=300)


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


class UseModelPayload(BaseModel):
    model: str = Field(min_length=1, max_length=300)
    everyone: bool = False


class EngineUsePayload(BaseModel):
    on: bool


class EngineTunePayload(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class EngineModelPayload(BaseModel):
    context: int | None = Field(default=None, ge=1024, le=131_072)
    gpu_layers: int | None = Field(default=None, ge=-1, le=999)
    flash_attention: Literal["auto", "on", "off"] | None = None
    kv_cache: Literal["f16", "q8_0", "q4_0"] | None = None
    threads: int | None = Field(default=None, ge=0, le=256)


class TeamModelsPayload(BaseModel):
    assignments: dict[str, str] = Field(min_length=1, max_length=50)


class ModelTestPayload(BaseModel):
    model: str = Field(min_length=1, max_length=300)


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


class GuideTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class GuidePayload(BaseModel):
    question: str
    history: list[GuideTurn] = Field(default_factory=list, max_length=12)


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


class PlaybookPayload(BaseModel):
    text: str = Field(max_length=20_000)


class AgentChatPayload(BaseModel):
    """An OpenAI-style chat request; model is the agent's name."""

    model: str = Field(default="jarvis", max_length=80)
    messages: list[dict[str, object]] = Field(min_length=1)
    stream: bool = False
    user: str | None = Field(default=None, max_length=80)
    wait: bool = False


class ExtensionPayload(BaseModel):
    url: str = Field(min_length=3, max_length=500)


class ServerSwitchPayload(BaseModel):
    on: bool


class ServerPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    command: str = Field(default="", max_length=400)
    args: list[str] | str = Field(default_factory=list)
    url: str = Field(default="", max_length=500)


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
def studio_page(_: None = Access) -> HTMLResponse:
    """Serve the installable Studio app shell."""
    template = _asset_path("index.html").read_text(encoding="utf-8")
    return HTMLResponse(template.replace(_ASSET_VERSION_PLACEHOLDER, package_version()))


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
            "background_color": "#02070d",
            "theme_color": "#02070d",
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


class SpeakPayload(BaseModel):
    text: str


@router.get("/studio/api/voice")
async def voice_status(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Say how the main AI speaks and listens, and whether it is ready."""
    return studio.voice_status()


@router.post("/studio/api/voice/setup")
async def voice_setup(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Download the built-in voice and speech recognition, once."""
    return studio.start_voice_setup()


@router.post("/studio/api/voice/speak", include_in_schema=False)
async def voice_speak(
    payload: SpeakPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> Response:
    """Say one reply in the main AI's voice."""
    speech = await studio.speak(payload.text)
    return Response(
        content=speech.audio,
        media_type=speech.content_type,
        headers={"cache-control": "no-store"},
    )


@router.post("/studio/api/voice/transcribe")
async def voice_transcribe(
    request: Request,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Turn one recorded turn of the user's speech into text."""
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="That recording is too long.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="That recording is too long.")
        chunks.append(chunk)
    content_type = request.headers.get("content-type", "audio/wav").split(";")[0]
    if not content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Send the recording as audio.")
    text = await studio.transcribe(b"".join(chunks), content_type=content_type)
    return {"text": text}


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
    """Return every agent, with the tools each really gets and their cost."""
    return {
        "agents": [await studio.agent_view(agent) for agent in await studio.agents()]
    }


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
        all_tools=payload.all_tools,
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
    return await studio.delete_agent(agent_id)


@router.get("/studio/api/studies")
async def list_studies(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Subjects Jarvis taught himself or is learning now."""
    return {"studies": [study.model_dump() for study in await studio.studies()]}


@router.post("/studio/api/studies")
async def start_study(
    payload: StudyPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Have Jarvis teach himself a subject in the background."""
    study = await studio.start_study(
        payload.topic, focus=payload.focus, depth=payload.depth, started_by="you"
    )
    return study.model_dump()


@router.get("/studio/api/studies/{study_id}")
async def study_detail(
    study_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """A study with its plan, lessons, notes, self-checks, and sources."""
    study, lessons = await studio.study_detail(study_id)
    return {
        "study": study.model_dump(),
        "lessons": [lesson.model_dump() for lesson in lessons],
    }


@router.post("/studio/api/studies/{study_id}/stop")
async def stop_study(
    study_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Stop a study; finished lessons are kept."""
    return (await studio.stop_study(study_id)).model_dump()


@router.delete("/studio/api/studies/{study_id}")
async def delete_study(
    study_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Forget a study, its lessons, and their memory entries."""
    return {"deleted": await studio.delete_study(study_id)}


@router.get("/studio/api/todos")
async def list_todos(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """The user's to-do list and reminders."""
    return {"todos": [item.model_dump() for item in await studio.todos()]}


@router.post("/studio/api/todos")
async def add_todo(
    payload: TodoPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Add a to-do, with a reminder when due says when."""
    item = await studio.add_todo(payload.text, due=payload.due, added_by="you")
    return item.model_dump()


@router.post("/studio/api/todos/{todo_id}/done")
async def finish_todo(
    todo_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Tick a to-do off."""
    return (await studio.finish_todo(todo_id)).model_dump()


@router.delete("/studio/api/todos/{todo_id}")
async def remove_todo(
    todo_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Remove a to-do."""
    return {"deleted": await studio.remove_todo(todo_id)}


def _video_json(note: VideoNote, *, full: bool = False) -> JsonObject:
    data = note.model_dump(exclude={"segments"})
    data["length"] = clock(note.segments[-1][0]) if note.segments else ""
    data["lines"] = len(note.segments)
    if full:
        data["notes"] = render_note(note)
        data["transcript"] = [
            {"at": clock(start), "seconds": start, "text": text}
            for start, text in note.segments
        ]
    return data


@router.get("/studio/api/videos")
async def list_videos(
    q: str = "",
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Videos the team studied, best match first when searching."""
    return {"videos": [_video_json(note) for note in await studio.video_notes(q)]}


@router.post("/studio/api/videos")
async def study_video(
    payload: VideoPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Study a YouTube video into notes for the agents."""
    note = await studio.study_video(payload.url, focus=payload.focus)
    return _video_json(note, full=True)


@router.get("/studio/api/videos/{note_id}")
async def video_note(
    note_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """One studied video: its notes and its transcript with times."""
    return _video_json(await studio.video_note(note_id), full=True)


@router.delete("/studio/api/videos/{note_id}")
async def delete_video(
    note_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Forget a studied video and its memory entry."""
    return {"deleted": await studio.delete_video_note(note_id)}


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


@router.get("/studio/api/chats/{chat_id}/notes")
async def chat_notes(
    chat_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """The running notes Studio keeps on a long conversation."""
    return (await studio.chat_notes(chat_id)).model_dump()


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
    return {
        "default_model": studio.default_model,
        "server": await _server_models(services),
        "local": await studio.local_models(),
    }


async def _server_models(services: ApiServices) -> list[str]:
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
    return sorted({info.model_id for info in infos} | configured)


@router.get("/studio/api/hq")
async def hq(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """The team in the pixel HQ: stations, who is where, and the newest steps."""
    return await studio.hq()


@router.post("/studio/api/hq/agents/{agent_id}/say", status_code=202)
async def hq_say(
    agent_id: str,
    payload: MessagePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Talk to one agent from the HQ; it answers in the background."""
    return await studio.hq_say(agent_id, payload.text)


@router.post("/studio/api/hq/agents/{agent_id}/stop")
async def hq_stop(
    agent_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Stop an agent's background tasks."""
    stopped = await studio.stop_agent_work(agent_id)
    return {"stopped": len(stopped)}


@router.get("/studio/api/agents/{agent_id}/activity")
async def agent_activity(
    agent_id: str,
    after: int = 0,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """One agent's current task and its newest steps, for the HUD."""
    return await studio.agent_activity(agent_id, after=after)


@router.post("/studio/api/models/pick-file")
async def pick_model_file(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Open a file picker on this PC and add the chosen model to LM Studio."""
    return await studio.pick_model_file()


@router.get("/studio/api/engine")
async def engine_status(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Model Control: the built-in engine and every model it can run."""
    return await studio.engine_status()


@router.post("/studio/api/engine/install")
async def engine_install(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Download the llama.cpp engine; progress shows in the status."""
    return studio.engine_install()


@router.post("/studio/api/engine/use")
async def engine_use(
    payload: EngineUsePayload,
    services: ApiServices = Depends(get_services),
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Run local models with the built-in engine, or go back to LM Studio."""
    result = await services.admin.apply_admin_config(
        {"STUDIO_ENGINE": "true" if payload.on else "false"}
    )
    if not result.get("applied"):
        errors = result.get("errors")
        detail = "; ".join(str(e) for e in errors) if isinstance(errors, list) else ""
        raise HTTPException(status_code=400, detail=detail or "Could not save that.")
    if payload.on:
        with contextlib.suppress(StudioError):
            await studio.engine_start()
    else:
        await studio.engine_stop()
    return await studio.engine_status()


@router.post("/studio/api/engine/start")
async def engine_start(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    await studio.engine_start()
    return await studio.engine_status()


@router.post("/studio/api/engine/stop")
async def engine_stop(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    await studio.engine_stop()
    return await studio.engine_status()


@router.post("/studio/api/engine/models/{name}/load")
async def engine_load(
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    await studio.engine_load(name)
    return {"ok": True}


@router.post("/studio/api/engine/models/{name}/unload")
async def engine_unload(
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    await studio.engine_unload(name)
    return {"ok": True}


@router.put("/studio/api/engine/models/{name}")
async def engine_model_settings(
    name: str,
    payload: EngineModelPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Change how one model runs; a loaded model reloads with the change."""
    return await studio.engine_settings(name, payload.model_dump(exclude_none=True))


@router.post("/studio/api/engine/tune")
async def engine_tune(
    payload: EngineTunePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Fit one model (or every model) to this PC's graphics card."""
    return {"tuned": list(await studio.engine_tune(payload.name))}


@router.post("/studio/api/engine/models/{name}/benchmark")
async def engine_benchmark(
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Time a short reply: how fast the model reads and writes on this PC."""
    return dict(await studio.engine_benchmark(name))


@router.post("/studio/api/engine/models/{name}/fastest", status_code=202)
async def engine_find_fastest(
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Try the settings that change speed on this card and keep the fastest;
    progress shows on the model in the engine status."""
    return await studio.engine_find_fastest(name)


@router.post("/studio/api/engine/identify")
async def engine_identify(
    request: Request,
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """What a file is, from its first bytes, before a big upload starts."""
    head = bytearray()
    async for chunk in request.stream():
        head.extend(chunk)
        if len(head) >= 4096:
            break
    return studio.engine_identify(name, bytes(head[:4096]))


@router.post("/studio/api/engine/install-file")
async def engine_install_file(
    request: Request,
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Install a llama.cpp release file downloaded by hand."""
    return await studio.engine_install_file(name, request.stream())


@router.post("/studio/api/engine/upload")
async def engine_upload(
    request: Request,
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Receive a model file as it streams in, then say what it can do."""
    length = request.headers.get("content-length")
    size = int(length) if length and length.isdigit() else None
    return await studio.engine_upload(name, request.stream(), size=size)


@router.post("/studio/api/engine/pick-file")
async def engine_pick_file(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Choose a model file on this PC in a normal file window."""
    return await studio.engine_add_from_pc()


@router.get("/studio/api/engine/models/{name}/report")
async def engine_report(
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """What one model can do: tools, vision, reasoning, fit, and best use."""
    return await studio.engine_report(name)


@router.post("/studio/api/files/read")
async def read_attached_file(
    request: Request,
    name: str,
    _: None = Access,
) -> JsonObject:
    """Read the text out of a file attached to a chat message."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"Attach files up to {MAX_UPLOAD // 1024 // 1024} MB.",
        )
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(
                status_code=413,
                detail=f"Attach files up to {MAX_UPLOAD // 1024 // 1024} MB.",
            )
    return await asyncio.to_thread(read_file_text, name, bytes(data))


class PhotoNotePayload(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/studio/api/photos")
async def add_photo(
    request: Request,
    name: str,
    note: str = "",
    chat_id: str | None = None,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Keep one business photo the user sent the agents, with a note."""
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="Send photos up to 15 MB.")
    return await studio.add_photo(name, bytes(data), note=note, chat_id=chat_id)


@router.get("/studio/api/photos")
async def list_photos(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    return {"photos": await studio.photo_list()}


@router.get("/studio/api/photos/{photo_id}/file")
async def photo_file(
    photo_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> FileResponse:
    try:
        photo = await studio.photos.find(photo_id)
    except PhotoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        studio.photos.path(photo),
        media_type=photo.content_type,
        headers={"cache-control": "private, max-age=3600"},
    )


@router.patch("/studio/api/photos/{photo_id}")
async def set_photo_note(
    photo_id: str,
    payload: PhotoNotePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    return await studio.set_photo_note(photo_id, payload.note)


@router.delete("/studio/api/photos/{photo_id}")
async def delete_photo(
    photo_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    return {"deleted": await studio.delete_photo(photo_id)}


@router.get("/studio/api/engine/logs")
async def engine_logs(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    return {"lines": studio.engine_logs()}


@router.get("/studio/api/team-models")
async def team_models(
    services: ApiServices = Depends(get_services),
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Which model each agent thinks with, and the models to choose from."""
    found = await studio.team_models()
    found["server"] = sorted(
        set(await _server_models(services)) | set(studio.server_model_list())
    )
    return found


@router.post("/studio/api/team-models")
async def assign_team_models(
    payload: TeamModelsPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Give each agent its own model."""
    changed = await studio.assign_models(payload.assignments)
    return {"changed": [agent.id for agent in changed]}


@router.post("/studio/api/team-models/test")
async def test_team_model(
    payload: ModelTestPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Check that one model answers with the user's key."""
    return await studio.test_model(payload.model)


@router.post("/studio/api/team-check")
async def team_check(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Test every agent's model and post the results in the team room."""
    return {"results": await studio.team_check()}


@router.get("/studio/api/team-models/suggest")
async def suggest_team_models(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """A starting mix of models for the team, from the models on this PC."""
    return {"assignments": await studio.suggest_team_models()}


@router.post("/studio/api/models/use")
async def use_model(
    payload: UseModelPayload,
    services: ApiServices = Depends(get_services),
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Make one model the main AI's brain, or every agent's."""
    model = payload.model.strip()
    updates: dict[str, str | None] = {"STUDIO_MAIN_AGENT_MODEL": model}
    if payload.everyone:
        updates |= {"STUDIO_DEFAULT_MODEL": model, "STUDIO_GUIDE_MODEL": model}
    result = await services.admin.apply_admin_config(updates)
    if not result.get("applied"):
        errors = result.get("errors")
        detail = "; ".join(str(e) for e in errors) if isinstance(errors, list) else ""
        raise HTTPException(status_code=400, detail=detail or "Could not save that.")
    changed = await studio.choose_model(model, everyone=payload.everyone)
    return {"model": model, "everyone": payload.everyone, "agents_changed": changed}


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


@router.delete("/studio/api/agents/{agent_id}/memory-area")
async def clear_memory_area(
    agent_id: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Empty the memory area an agent keeps on a server AI."""
    return {"removed": await studio.clear_memory_area(agent_id)}


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


def _latest_user_text(messages: list[dict[str, object]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
            )
    return ""


@router.get("/studio/v1/models")
async def agent_models(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Every agent as an OpenAI-style model, for apps that talk to the team."""
    return {
        "object": "list",
        "data": [
            {
                "id": agent.name.casefold(),
                "object": "model",
                "owned_by": "fcc-studio",
                "created": agent.created_at // 1000,
                "description": agent.description[:200],
            }
            for agent in await studio.api_agents()
        ],
    }


@router.post("/studio/v1/chat/completions")
async def agent_chat_completion(
    payload: AgentChatPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
):
    """Talk to Jarvis or any agent the OpenAI way: model is the agent's name,
    user keeps separate conversations, and wait also returns what teammates
    reported back."""
    text = _latest_user_text(payload.messages)
    agent, reply = await studio.api_ask(
        payload.model, text, conversation=payload.user or "", wait=payload.wait
    )
    reply_id = f"chatcmpl-{secrets.token_hex(8)}"
    created = int(time.time())
    model = agent.name.casefold()
    if not payload.stream:
        return {
            "id": reply_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def chunk(delta: JsonObject, finish: str | None) -> str:
        body = {
            "id": reply_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(body)}\n\n"

    async def events():
        yield chunk({"role": "assistant", "content": reply}, None)
        yield chunk({}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


def _extension(extension: Extension) -> JsonObject:
    return {
        "id": extension.id,
        "name": extension.name,
        "source": extension.source,
        "description": extension.description,
        "plugins": list(extension.plugins),
        "vaulted": extension.vaulted,
        "skills": [
            {"name": skill.name, "description": skill.description, "kind": skill.kind}
            for skill in extension.skills
        ],
        "agents": [
            {"name": agent.name, "description": agent.description, "tools": agent.tools}
            for agent in extension.agents
        ],
        "servers": [
            {
                "name": server.name,
                "shown": server.shown(),
                "transport": server.transport,
                "enabled": server.enabled,
            }
            for server in extension.servers
        ],
    }


@router.get("/studio/api/extensions")
async def list_extensions(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Skills, agents, commands, and MCP servers added from GitHub."""
    return {"extensions": [_extension(item) for item in await studio.extensions()]}


@router.post("/studio/api/extensions")
async def add_extension(
    payload: ExtensionPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Pull in everything a GitHub repo offers."""
    return _extension(await studio.add_extension(payload.url))


@router.post("/studio/api/extensions/servers")
async def add_mcp_server(
    payload: ServerPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Add an MCP server by its command (npx/uvx ...) or web address."""
    args = payload.args.split() if isinstance(payload.args, str) else payload.args
    command = payload.command.strip()
    if command and not args and " " in command:
        command, *args = command.split()
    return _extension(
        await studio.add_server(
            name=payload.name, command=command, args=args, url=payload.url
        )
    )


@router.get("/studio/api/vault")
async def list_vault(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Every repo and release kept on this PC, newest first."""
    items = await studio.vault.items()
    return {
        "items": [item_view(item) for item in items],
        "bytes": sum(item.size for item in items),
        "folder": str(studio.vault.folder),
    }


@router.get("/studio/api/vault/{item_id}/file")
async def vault_file(
    item_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> FileResponse:
    """Download a kept copy."""
    try:
        item = await studio.vault.item(item_id)
        path = studio.vault.path(item)
    except VaultError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That copy's file is missing.")
    return FileResponse(path, filename=item.name)


@router.post("/studio/api/vault/{item_id}/restore")
async def restore_from_vault(
    item_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Add a repo again from its kept copy (no download)."""
    return _extension(await studio.restore_extension(item_id))


@router.delete("/studio/api/vault/{item_id}")
async def remove_from_vault(
    item_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    return {"removed": await studio.vault.remove(item_id)}


@router.delete("/studio/api/extensions/{ext_id}")
async def remove_extension(
    ext_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Remove an extension and stop its servers."""
    await studio.remove_extension(ext_id)
    return {"removed": True}


@router.post("/studio/api/extensions/{ext_id}/servers/{name}")
async def switch_mcp_server(
    ext_id: str,
    name: str,
    payload: ServerSwitchPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Turn one MCP server on or off."""
    return _extension(await studio.switch_server(ext_id, name, on=payload.on))


@router.post("/studio/api/extensions/{ext_id}/servers/{name}/check")
async def check_mcp_server(
    ext_id: str,
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Start one server and list its tools."""
    tools = await studio.check_server(ext_id, name)
    return {
        "tools": [
            {"name": tool.name, "description": tool.description[:200]} for tool in tools
        ]
    }


@router.post("/studio/api/extensions/{ext_id}/agents/{name}")
async def add_extension_agent(
    ext_id: str,
    name: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Make one of a plugin's agents part of the team."""
    agent = await studio.add_extension_agent(ext_id, name)
    return {"id": agent.id, "name": agent.name}


def _playbook_note(note: PlaybookNote) -> JsonObject:
    return {
        "tool": note.tool,
        "file": note.path.name,
        "when": list(note.when),
        "learned": len(note.learned),
        "text": note.text,
    }


@router.get("/studio/api/playbook")
async def playbook(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Jarvis's playbook: where its notes live and what each one says."""
    folder, in_vault, notes = await studio.playbook()
    return {
        "folder": folder,
        "in_vault": in_vault,
        "enabled": studio.settings.studio_jarvis_playbook,
        "notes": [_playbook_note(note) for note in notes],
    }


@router.put("/studio/api/playbook/{tool}")
async def save_playbook_note(
    tool: str,
    payload: PlaybookPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Save the user's edit to one playbook note."""
    return _playbook_note(await studio.save_playbook_note(tool, payload.text))


@router.post("/studio/api/playbook/{tool}/reset")
async def reset_playbook_note(
    tool: str,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Put Studio's starting note back for one tool."""
    return _playbook_note(await studio.reset_playbook_note(tool))


@router.post("/studio/api/guide/ask")
async def ask_guide(
    payload: GuidePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Ask the guide how the app works; it knows this install's state too."""
    history = [
        ChatMessage.user(turn.text)
        if turn.role == "user"
        else ChatMessage.assistant(turn.text)
        for turn in payload.history
    ]
    answer = await studio.ask_guide(payload.question, history)
    return {
        "text": answer.text,
        "topics": list(answer.topics),
        "route": answer.route,
        "offline": answer.offline,
        "links": [{"label": link.label, "route": link.route} for link in answer.links],
        "suggestions": list(answer.suggestions),
    }


@router.get("/studio/api/guide")
async def guide_overview(
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """What is wrong right now, starter questions, and where everything lives."""
    return await studio.guide_overview()


def studio_error_status(error: Exception) -> int:
    """Map a Studio failure to its HTTP status."""
    if isinstance(error, StudioNotFoundError):
        return 404
    if isinstance(error, LoraAuthError):
        return 401
    if isinstance(error, VoiceError | LocalVoiceError):
        return 409
    if isinstance(
        error, SiteError | DownloadError | TuningError | SchoolError | LoraError
    ):
        return 400
    if isinstance(error, StudioError):
        return 400
    return 500


# ------------------------------------------------------------ FCC Phone
# The phone app lives on another origin (GitHub Pages), so the paths under
# /studio/api/phone/ answer any origin (see PhoneCorsMiddleware). Each needs a
# pairing code or the phone's secret; managing phones stays on /studio/api/phones.


class PhonePairPayload(BaseModel):
    code: str = Field(min_length=4, max_length=40)
    name: str = Field(default="iPhone", max_length=80)


def _phone_token(request: Request) -> str:
    return _bearer(request.headers.get("authorization"))


async def _phone(request: Request, studio: StudioService) -> PhoneLink:
    try:
        return await studio.phone_auth(_phone_token(request))
    except PhoneAuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


def _phone_failed(error: PhoneLinkError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@router.post("/studio/api/phones/code")
async def phone_pairing_code(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """A code to type into FCC Phone (on the PC only)."""
    return studio.phone_pairing_code()


@router.get("/studio/api/phones")
async def phone_list(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    return await studio.phone_links()


@router.delete("/studio/api/phones/{link_id}")
async def phone_unlink(
    link_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    return {"deleted": await studio.phone_unlink(link_id)}


@router.post("/studio/api/phone/pair")
async def phone_pair(
    payload: PhonePairPayload, studio: StudioService = Depends(get_studio)
) -> JsonObject:
    """Trade a pairing code for the secret the phone keeps."""
    try:
        return await studio.phone_pair(payload.code, payload.name)
    except PhoneLinkError as error:
        raise _phone_failed(error) from error


@router.get("/studio/api/phone/hello")
async def phone_hello(
    request: Request, studio: StudioService = Depends(get_studio)
) -> JsonObject:
    return await studio.phone_hello(await _phone(request, studio))


@router.post("/studio/api/phone/sync")
async def phone_sync(
    request: Request, studio: StudioService = Depends(get_studio)
) -> JsonObject:
    """Share the phone's new memories and send the PC's back."""
    link = await _phone(request, studio)
    body = await _json_body(request)
    try:
        return await studio.phone_sync(link, body.get("memories", []))
    except PhoneLinkError as error:
        raise _phone_failed(error) from error


@router.post("/studio/api/phone/search")
async def phone_search(
    request: Request, studio: StudioService = Depends(get_studio)
) -> JsonObject:
    """Search the web with the PC's search setup for a phone agent."""
    link = await _phone(request, studio)
    body = await _json_body(request)
    try:
        return await studio.phone_search(link, str(body.get("query") or ""))
    except PhoneLinkError as error:
        raise _phone_failed(error) from error


@router.post("/studio/api/phone/complete")
async def phone_complete(
    request: Request, studio: StudioService = Depends(get_studio)
) -> JsonObject:
    """Think with the PC's main AI model for a phone agent."""
    link = await _phone(request, studio)
    body = await _json_body(request)
    try:
        return await studio.phone_complete(link, body)
    except PhoneLinkError as error:
        raise _phone_failed(error) from error


async def _json_body(request: Request) -> JsonObject:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > 2_000_000:
        raise HTTPException(status_code=413, detail="That is too much to send at once.")
    try:
        body = await request.json()
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Send JSON.") from error
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Send a JSON object.")
    return body


# FCC Phone's own files, so a phone on the PC's network (or Tailscale) can
# open it from here too. They hold no secrets: everything lives on the phone.
PHONE_DIR = Path(__file__).with_name("phone_static")
_PHONE_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
    ".txt": "text/plain; charset=utf-8",
}


@router.get("/phone", include_in_schema=False)
def phone_root() -> RedirectResponse:
    return RedirectResponse("/phone/", status_code=307)


@router.get("/phone/", include_in_schema=False)
@router.get("/phone/{name:path}", include_in_schema=False)
def phone_file(name: str = "index.html") -> FileResponse:
    root = PHONE_DIR.resolve()
    path = (root / (name or "index.html")).resolve()
    kind = _PHONE_TYPES.get(path.suffix)
    if kind is None or not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Not part of FCC Phone.")
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- the Lab


class LabMixPayload(BaseModel):
    items: list[JsonObject] = Field(default_factory=list, max_length=12)
    heat: bool = False
    flame: bool = False


class LabMakePayload(BaseModel):
    request: str = Field(min_length=1, max_length=400)
    batch_g: float | None = Field(default=None, gt=0, le=100_000)


class LabPartsPayload(BaseModel):
    parts: list[JsonObject] = Field(default_factory=list, max_length=60)
    series: bool = True
    name: str = Field(default="", max_length=120)
    save: bool = False


class LabLookupPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class LabSavePayload(BaseModel):
    name: str = Field(default="", max_length=120)
    kind: str = "mix"
    request: str = Field(default="", max_length=400)
    data: JsonObject = Field(default_factory=dict)


class LabRenamePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _lab_failed(error: LabError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@router.get("/studio/api/lab")
async def lab_catalogue(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Everything on the Lab's shelves: elements, chemicals, materials, parts."""
    return await studio.lab.catalogue()


@router.post("/studio/api/lab/mix")
async def lab_mix(
    payload: LabMixPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Pour things together and see what happens."""
    try:
        return await studio.lab.mix(
            payload.items, heat=payload.heat, flame=payload.flame
        )
    except LabError as error:
        raise _lab_failed(error) from error


@router.post("/studio/api/lab/make")
async def lab_make(
    payload: LabMakePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Make a product or gadget from a plain request."""
    try:
        return await studio.lab.make(payload.request, batch_g=payload.batch_g)
    except LabError as error:
        raise _lab_failed(error) from error


@router.post("/studio/api/lab/build")
async def lab_build(
    payload: LabPartsPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Power a set of electronics parts on the circuit bench."""
    try:
        return await studio.lab.build(
            payload.parts, series=payload.series, name=payload.name, save=payload.save
        )
    except LabError as error:
        raise _lab_failed(error) from error


@router.post("/studio/api/lab/material")
async def lab_material(
    payload: LabPartsPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Blend materials and run the test rigs."""
    try:
        return await studio.lab.material(
            payload.parts, name=payload.name, save=payload.save
        )
    except LabError as error:
        raise _lab_failed(error) from error


@router.post("/studio/api/lab/lookup")
async def lab_lookup(
    payload: LabLookupPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """A chemical from the shelf, or learned from PubChem."""
    try:
        return await studio.lab.lookup(payload.name)
    except LabError as error:
        raise _lab_failed(error) from error


@router.get("/studio/api/lab/projects")
async def lab_projects(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    return {"projects": await studio.lab.projects()}


@router.post("/studio/api/lab/projects")
async def lab_save(
    payload: LabSavePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    try:
        return await studio.lab.save(
            name=payload.name,
            kind=payload.kind,
            data=payload.data,
            request=payload.request,
        )
    except LabError as error:
        raise _lab_failed(error) from error


@router.get("/studio/api/lab/projects/{project_id}")
async def lab_project(
    project_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    return await studio.lab.project(project_id)


@router.patch("/studio/api/lab/projects/{project_id}")
async def lab_rename(
    project_id: str,
    payload: LabRenamePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    return await studio.lab.rename(project_id, payload.name)


@router.delete("/studio/api/lab/projects/{project_id}")
async def lab_delete(
    project_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    return {"deleted": await studio.lab.delete(project_id)}


@router.get("/studio/api/lab/chat")
async def lab_chat(
    after: int = 0,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """The Lab chat with the main AI; poll while it works."""
    return await studio.lab_console(after=after)


@router.post("/studio/api/lab/chat", status_code=202)
async def lab_say(
    payload: MessagePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Ask the main AI to make or test something in the Lab."""
    chat = await studio.lab_say(payload.text)
    return {"accepted": True, "chat_id": chat.id}


# ---------------------------------------------------------- the Content Farm


class FarmChannelPayload(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    niche: str | None = Field(default=None, max_length=160)
    platform: str | None = Field(default=None, max_length=20)
    style: str | None = Field(default=None, max_length=20)
    look: str | None = Field(default=None, max_length=20)
    visuals: str | None = Field(default=None, max_length=20)
    voice: str | None = Field(default=None, max_length=40)
    seconds: int | None = Field(default=None, ge=10, le=180)
    posts_per_day: int | None = Field(default=None, ge=1, le=10)
    post_times: list[str] | None = Field(default=None, max_length=10)
    hashtags: list[str] | None = Field(default=None, max_length=30)
    call_to_action: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=1_000)
    autopilot: bool | None = None
    fandom: str | None = Field(default=None, max_length=120)
    wiki: str | None = Field(default=None, max_length=200)
    ai_media: bool | None = None
    ai_polish: bool | None = None
    background: str | None = Field(default=None, max_length=40)
    minutes: int | None = Field(default=None, ge=5, le=600)
    captions: bool | None = None
    cast: list[str] | None = Field(default=None, max_length=12)
    series: str | None = Field(default=None, max_length=80)
    texture: str | None = Field(default=None, max_length=20)
    song: str | None = Field(default=None, max_length=40)
    theme: str | None = Field(default=None, max_length=9)
    shape: str | None = Field(default=None, max_length=10)
    pace: str | None = Field(default=None, max_length=10)


class FarmCharacterPayload(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=400)
    skin: str | None = Field(default=None, max_length=9)
    hair: str | None = Field(default=None, max_length=20)
    hair_colour: str | None = Field(default=None, max_length=9)
    wear: str | None = Field(default=None, max_length=20)
    wear_colour: str | None = Field(default=None, max_length=9)
    age: str | None = Field(default=None, max_length=10)
    beard: bool | None = None
    earrings: bool | None = None
    glasses: bool | None = None
    head_asset: str | None = Field(default=None, max_length=40)
    voice: str | None = Field(default=None, max_length=40)


class FarmMusicPayload(BaseModel):
    song: str | None = Field(default=None, max_length=40)
    lyrics: str | None = Field(default=None, max_length=20_000)
    song_start: float | str | None = None
    song_length: float | None = Field(default=None, ge=0, le=90)
    big_words: list[str] | str | None = None


class FarmIdeasPayload(BaseModel):
    count: int = Field(default=5, ge=1, le=10)
    topic: str = Field(default="", max_length=200)


class FarmIdeaPayload(BaseModel):
    title: str = Field(min_length=1, max_length=140)


class FarmPostPayload(BaseModel):
    title: str | None = Field(default=None, max_length=140)
    caption: str | None = Field(default=None, max_length=2_200)
    scheduled_at: int | None = Field(default=None, ge=0)


class FarmPostedPayload(BaseModel):
    posted: bool = True


def _farm_failed(error: FarmError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


def _channel_fields(payload: FarmChannelPayload) -> JsonObject:
    return cast(JsonObject, payload.model_dump(exclude_none=True))


@router.get("/studio/api/farm")
async def farm_overview(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Channels, every video and idea, styles, and what this PC can do."""
    return await studio.farm_overview()


@router.post("/studio/api/farm/channels")
async def farm_add_channel(
    payload: FarmChannelPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    return await studio.save_farm_channel(_channel_fields(payload))


@router.put("/studio/api/farm/channels/{channel_id}")
async def farm_edit_channel(
    channel_id: str,
    payload: FarmChannelPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    return await studio.save_farm_channel(_channel_fields(payload), channel_id)


@router.delete("/studio/api/farm/channels/{channel_id}")
async def farm_delete_channel(
    channel_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    try:
        return {"deleted": await studio.farm.delete_channel(channel_id)}
    except FarmError as error:
        raise _farm_failed(error) from error


@router.post("/studio/api/farm/channels/{channel_id}/ideas")
async def farm_ideas(
    channel_id: str,
    payload: FarmIdeasPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """New ideas on the board, written by the team's local model."""
    posts = await studio.farm_ideas(
        channel_id, count=payload.count, topic=payload.topic
    )
    return {"posts": posts}


@router.post("/studio/api/farm/channels/{channel_id}/posts")
async def farm_add_idea(
    channel_id: str,
    payload: FarmIdeaPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    try:
        channel = await studio.farm.channel(channel_id)
        post = await studio.farm.add_idea(channel, payload.title)
    except FarmError as error:
        raise _farm_failed(error) from error
    return studio.farm.view(post)


@router.post("/studio/api/farm/channels/{channel_id}/fill", status_code=202)
async def farm_fill(
    channel_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Make a day of videos for the channel, in the background."""
    return {"started": await studio.farm_fill(channel_id)}


@router.post("/studio/api/farm/posts/{post_id}/make", status_code=202)
async def farm_make(
    post_id: str,
    rewrite: bool = False,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Make a video; with rewrite, from a new script. Without it, a video
    with scenes is rendered again with its edits."""
    try:
        post = await studio.farm.post(post_id)
    except FarmError as error:
        raise _farm_failed(error) from error
    if post.status == "making":
        raise HTTPException(status_code=409, detail="That video is already being made.")
    return {"started": await studio.farm_make([post.id], rewrite=rewrite)}


@router.post("/studio/api/farm/posts/{post_id}/stop")
async def farm_stop(
    post_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Stop a video being made; what was written and voiced is kept."""
    studio.farm.stop(post_id)
    return {"stopping": True}


class FarmScenesPayload(BaseModel):
    scenes: list[dict[str, object]] = Field(max_length=2_000)


class FarmSceneMediaPayload(BaseModel):
    asset_id: str = Field(default="", max_length=40)
    url: str = Field(default="", max_length=2_000)
    source: str = Field(default="", max_length=20)
    title: str = Field(default="", max_length=200)
    credit: str = Field(default="", max_length=300)
    auto: bool = False


class FarmAiEditPayload(BaseModel):
    instruction: str = Field(min_length=1, max_length=600)
    chapter: int | None = Field(default=None, ge=0, le=100)


@router.get("/studio/api/farm/characters")
async def farm_characters(
    studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """The cartoon characters: how each looks and sounds."""
    return {"characters": [c.model_dump() for c in await studio.farm.characters()]}


@router.post("/studio/api/farm/characters")
async def farm_add_character(
    payload: FarmCharacterPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    try:
        made = await studio.farm.save_character(
            cast(JsonObject, payload.model_dump(exclude_none=True))
        )
    except FarmError as error:
        raise _farm_failed(error) from error
    return made.model_dump()


@router.put("/studio/api/farm/characters/{character_id}")
async def farm_edit_character(
    character_id: str,
    payload: FarmCharacterPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    try:
        saved = await studio.farm.save_character(
            cast(JsonObject, payload.model_dump(exclude_none=True)), character_id
        )
    except FarmError as error:
        raise _farm_failed(error) from error
    return saved.model_dump()


@router.get("/studio/api/farm/characters/{character_id}/picture")
async def farm_character_picture(
    character_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> FileResponse:
    """The character, drawn standing and waving."""
    try:
        path = await studio.farm.character_picture(character_id)
    except FarmError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        path, media_type="image/png", headers={"cache-control": "no-store"}
    )


@router.delete("/studio/api/farm/characters/{character_id}")
async def farm_delete_character(
    character_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    try:
        return {"deleted": await studio.farm.delete_character(character_id)}
    except FarmError as error:
        raise _farm_failed(error) from error


@router.put("/studio/api/farm/posts/{post_id}/music")
async def farm_post_music(
    post_id: str,
    payload: FarmMusicPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """A music edit's song, lyrics, the part of the song, and its big words."""
    try:
        post = await studio.farm.set_music(
            post_id, cast(JsonObject, payload.model_dump(exclude_unset=True))
        )
    except FarmError as error:
        raise _farm_failed(error) from error
    return studio.farm.editor_view(post)


@router.get("/studio/api/farm/posts/{post_id}/editor")
async def farm_editor(
    post_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """A video's every scene, for the editor."""
    return await studio.farm_editor(post_id)


@router.put("/studio/api/farm/posts/{post_id}/scenes")
async def farm_edit_scenes(
    post_id: str,
    payload: FarmScenesPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Your own edit: new lines, words on screen, order. Render to apply it."""
    scenes = [cast(JsonObject, scene) for scene in payload.scenes]
    return await studio.farm_edit_scenes(post_id, scenes)


@router.put("/studio/api/farm/posts/{post_id}/scenes/{index}/media")
async def farm_scene_media(
    post_id: str,
    index: int,
    payload: FarmSceneMediaPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Put a library clip or picture, or a picture from the web, in a scene."""
    choice = cast(JsonObject, payload.model_dump())
    return await studio.farm_scene_media(post_id, index, choice)


@router.post("/studio/api/farm/posts/{post_id}/ai-edit")
async def farm_ai_edit(
    post_id: str,
    payload: FarmAiEditPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Ask the AI to change the script; render to apply it."""
    return await studio.farm_ai_edit(
        post_id, payload.instruction, chapter=payload.chapter
    )


@router.get("/studio/api/farm/posts/{post_id}/candidates")
async def farm_candidates(
    post_id: str,
    q: str = "",
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Clips and pictures that could go in a scene: yours, then the wiki's."""
    return {"candidates": await studio.farm_candidates(post_id, q[:200])}


# ------------------------------------------------- the farm's media library


class FarmLinkPayload(BaseModel):
    folder: str = Field(min_length=1, max_length=1_000)
    show: str = Field(default="", max_length=120)
    background: bool = False


class FarmAssetPayload(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=30)
    note: str | None = Field(default=None, max_length=1_000)
    show: str | None = Field(default=None, max_length=120)
    background: bool | None = None


def _library_failed(error: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@router.get("/studio/api/farm/media")
async def farm_media(
    show: str = "",
    kind: str = "",
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    assets = await studio.farm.library.assets(show=show, kind=kind)
    return {"assets": [asset_view(asset) for asset in assets[:1_000]]}


@router.post("/studio/api/farm/media")
async def farm_upload_media(
    request: Request,
    name: str,
    show: str = "",
    tags: str = "",
    background: bool = False,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Upload one clip or picture; the file is the request body, streamed."""
    library = studio.farm.library
    if not kind_of(Path(name)):
        raise HTTPException(
            status_code=400,
            detail="Send a picture (JPG, PNG, WebP) or a clip (MP4, MOV, MKV, WebM).",
        )
    target = library.incoming(name)
    size = 0
    try:
        async with await anyio.open_file(target, "wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_LIBRARY_UPLOAD:
                    raise HTTPException(
                        status_code=413, detail="That file is over 4 GB."
                    )
                await out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="The file was empty.")
        asset = await library.add_file(
            target,
            name=name,
            tags=[tag for tag in tags.split(",") if tag.strip()],
            show=show,
            background=background,
            move=True,
        )
    except LibraryError as error:
        raise _library_failed(error) from error
    finally:
        target.unlink(missing_ok=True)
    return asset_view(asset)


@router.post("/studio/api/farm/media/link")
async def farm_link_folder(
    payload: FarmLinkPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Add every clip and picture in a folder on this PC, without copying."""
    try:
        added = await studio.farm.library.link_folder(
            payload.folder, show=payload.show, background=payload.background
        )
    except LibraryError as error:
        raise _library_failed(error) from error
    return {"added": len(added), "assets": [asset_view(a) for a in added[:200]]}


@router.patch("/studio/api/farm/media/{asset_id}")
async def farm_edit_media(
    asset_id: str,
    payload: FarmAssetPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    try:
        asset = await studio.farm.library.edit(
            asset_id, cast(JsonObject, payload.model_dump(exclude_none=True))
        )
    except LibraryError as error:
        raise _library_failed(error) from error
    return asset_view(asset)


@router.delete("/studio/api/farm/media/{asset_id}")
async def farm_delete_media(
    asset_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    """Remove from the library (a linked file stays on the PC)."""
    try:
        return {"deleted": await studio.farm.library.delete(asset_id)}
    except LibraryError as error:
        raise _library_failed(error) from error


@router.get("/studio/api/farm/media/{asset_id}/thumb")
async def farm_media_thumb(
    asset_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> FileResponse:
    try:
        asset = await studio.farm.library.asset(asset_id)
    except LibraryError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    thumb = await studio.farm.library.thumb(asset)
    if thumb is None:
        raise HTTPException(status_code=404, detail="No preview for that file.")
    return FileResponse(
        thumb,
        media_type="image/jpeg",
        headers={"cache-control": "private, max-age=3600"},
    )


@router.get("/studio/api/farm/media/{asset_id}/file")
async def farm_media_file(
    asset_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> FileResponse:
    try:
        asset = await studio.farm.library.asset(asset_id)
    except LibraryError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    path = studio.farm.library.path(asset)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That file has moved or gone.")
    return FileResponse(path, headers={"cache-control": "private, max-age=3600"})


@router.patch("/studio/api/farm/posts/{post_id}")
async def farm_edit_post(
    post_id: str,
    payload: FarmPostPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    try:
        post = await studio.farm.edit_post(
            post_id, cast(JsonObject, payload.model_dump(exclude_none=True))
        )
    except FarmError as error:
        raise _farm_failed(error) from error
    return studio.farm.view(post)


@router.post("/studio/api/farm/posts/{post_id}/posted")
async def farm_posted(
    post_id: str,
    payload: FarmPostedPayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    try:
        post = await studio.farm.mark_posted(post_id, payload.posted)
    except FarmError as error:
        raise _farm_failed(error) from error
    return studio.farm.view(post)


@router.delete("/studio/api/farm/posts/{post_id}")
async def farm_delete_post(
    post_id: str, studio: StudioService = Depends(get_studio), _: None = Access
) -> JsonObject:
    try:
        return {"deleted": await studio.farm.delete_post(post_id)}
    except FarmError as error:
        raise _farm_failed(error) from error


_FARM_FILES = {
    ".mp4": "video/mp4",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".wav": "audio/wav",
}


@router.get("/studio/api/farm/posts/{post_id}/files/{name:path}")
async def farm_file(
    post_id: str,
    name: str,
    download: bool = False,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> FileResponse:
    """A finished video, its cover, or a scene picture."""
    try:
        post = await studio.farm.post(post_id)
        path = studio.farm.file(post, name)
    except FarmError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    kind = _FARM_FILES.get(path.suffix.lower())
    if kind is None or not path.is_file():
        raise HTTPException(status_code=404, detail="No such file.")
    slug = re.sub(r"[^a-z0-9]+", "-", post.title.lower()).strip("-")[:60] or "video"
    return FileResponse(
        path,
        media_type=kind,
        filename=f"{slug}{path.suffix}" if download else None,
        content_disposition_type="attachment" if download else "inline",
        headers={"cache-control": "private, max-age=60"},
    )


@router.get("/studio/api/farm/chat")
async def farm_chat(
    after: int = 0,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """The Content Farm chat with the main AI; poll while it works."""
    return await studio.farm_console(after=after)


@router.post("/studio/api/farm/chat", status_code=202)
async def farm_say(
    payload: MessagePayload,
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Ask the main AI for videos, ideas, or advice in the Content Farm."""
    chat = await studio.farm_say(payload.text)
    return {"accepted": True, "chat_id": chat.id}
