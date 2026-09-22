"""HTTP adapter for the Studio app: agents, models, tuning, and classes."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject
from free_claude_code.core.version import package_version
from free_claude_code.studio import StudioError, StudioNotFoundError, StudioService
from free_claude_code.studio.downloads import DownloadError
from free_claude_code.studio.school import SchoolError
from free_claude_code.studio.sites import SiteError, content_type_for
from free_claude_code.studio.tuning import TuningError

from .dependencies import get_services, get_settings
from .ports import ApiServices

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent / "studio_static"
_ASSET_VERSION_PLACEHOLDER = "__FCC_VERSION__"
_ASSET_FILENAMES = frozenset({"studio.css", "studio.js", "icon.svg"})


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


class SamplePayload(BaseModel):
    pairs: list[tuple[str, str]] = Field(default_factory=list)
    split: str = "train"


class CoursePayload(BaseModel):
    topic: str
    lesson_count: int = 3
    start: bool = True


class MemoryPayload(BaseModel):
    text: str
    scope: str = "long_term"


class GuidePayload(BaseModel):
    question: str


class BootstrapPayload(BaseModel):
    download_guide: bool = False


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
            "background_color": "#0b0d12",
            "theme_color": "#0b0d12",
            "orientation": "portrait",
            "icons": [
                {
                    "src": f"/studio/assets/{package_version()}/icon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        },
        media_type="application/manifest+json",
    )


@router.get("/studio/assets/{version}/{filename}", include_in_schema=False)
def studio_asset(version: str, filename: str) -> FileResponse:
    """Serve a versioned Studio asset."""
    if version != package_version() or filename not in _ASSET_FILENAMES:
        raise HTTPException(status_code=404, detail="Studio asset not found")
    return FileResponse(_asset_path(filename))


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
    )
    return agent.model_dump()


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
    pack = await studio.create_pack(payload.agent_id, name=payload.name)
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
    studio: StudioService = Depends(get_studio),
    _: None = Access,
) -> JsonObject:
    """Start a very light tuning run."""
    job = await studio.start_tuning(pack_id)
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
        topic=payload.topic, lesson_count=payload.lesson_count, start=payload.start
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
    }


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
    if isinstance(error, SiteError | DownloadError | TuningError | SchoolError):
        return 400
    if isinstance(error, StudioError):
        return 400
    return 500
