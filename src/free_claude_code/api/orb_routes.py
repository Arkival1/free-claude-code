"""JARVIS Orb: a local-only voice page backed by LM Studio and its MCP tools."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from free_claude_code.application.orb import OrbStudio
from free_claude_code.application.orb.advisor import fcc_messages_sender
from free_claude_code.application.orb.ears import (
    MAX_AUDIO_BYTES,
    MAX_FILE_BYTES,
    EarsError,
    LocalEars,
)
from free_claude_code.application.orb.voice import JarvisVoice, VoiceError
from free_claude_code.application.orb.youtube import YouTubeAudio, YouTubeError
from free_claude_code.config.paths import config_dir_path
from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.core.version import package_version

from .admin_security import require_loopback_admin
from .dependencies import get_services

router = APIRouter()

ORB_STATIC_DIR = Path(__file__).resolve().parent / "orb_static"
APP_ICON = Path(__file__).resolve().parent.parent / "assets" / "app-icon.svg"
_VERSION_PLACEHOLDER = "__FCC_VERSION__"
_ORB_ASSETS = frozenset({"orb.css", "orb.js", "core-orb.js"})


class OrbChatPayload(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class OrbSayPayload(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    source: str = Field(default="jarvis", max_length=40)


class OrbModelPayload(BaseModel):
    model: str | None = Field(default=None, max_length=300)


class OrbAdvisorPayload(BaseModel):
    model: str | None = Field(default=None, max_length=300)


class OrbAdvisePayload(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class OrbVoicePayload(BaseModel):
    voice: str | None = Field(default=None, max_length=40)
    speed: float | None = Field(default=None, ge=0.6, le=1.5)
    effect: bool | None = None


class OrbYouTubePayload(BaseModel):
    url: str = Field(min_length=10, max_length=400)


class OrbActivityPayload(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=20)
    step: int | None = Field(default=None, ge=0, le=50)
    steps: int | None = Field(default=None, ge=1, le=50)
    step_name: str | None = Field(default=None, max_length=200)
    detail: str | None = Field(default=None, max_length=400)
    percent: float | None = Field(default=None, ge=0, le=100)
    reset_percent: bool = False
    log: list[str] | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=300)


class OrbPrivacyPayload(BaseModel):
    local_only: bool


class OrbSpeakPayload(BaseModel):
    text: str = Field(min_length=1, max_length=1500)


class OrbResumePayload(BaseModel):
    topic: str = Field(default="", max_length=500)


def orb_studio(request: Request) -> OrbStudio:
    """The app's single orb, created the first time it is needed."""
    studio = getattr(request.app.state, "orb_studio", None)
    if studio is None:
        services = get_services(request)

        def base_url() -> str:
            return services.requests.current_settings().lm_studio_base_url

        def advisor_sender():
            settings = services.requests.current_settings()
            return fcc_messages_sender(
                local_proxy_root_url(settings), settings.proxy_auth_token
            )

        studio = OrbStudio(
            base_url,
            advisor_sender=advisor_sender,
            voice=JarvisVoice(config_dir_path() / "orb_voice"),
            ears=LocalEars(config_dir_path() / "orb_ears"),
        )
        request.app.state.orb_studio = studio
    return studio


@router.get("/orb", include_in_schema=False)
def orb_page(request: Request) -> HTMLResponse:
    require_loopback_admin(request)
    page = (ORB_STATIC_DIR / "orb.html").read_text(encoding="utf-8")
    return HTMLResponse(page.replace(_VERSION_PLACEHOLDER, package_version()))


@router.get("/orb/assets/{version}/{filename}", include_in_schema=False)
def orb_asset(version: str, filename: str, request: Request) -> FileResponse:
    require_loopback_admin(request)
    if version != package_version():
        raise HTTPException(status_code=404, detail="Orb asset not found")
    if filename == "app-icon.svg":
        return FileResponse(APP_ICON)
    if filename not in _ORB_ASSETS:
        raise HTTPException(status_code=404, detail="Orb asset not found")
    return FileResponse(ORB_STATIC_DIR / filename)


@router.get("/orb/api/status")
def orb_status(request: Request) -> dict[str, object]:
    require_loopback_admin(request)
    return {"version": package_version(), **orb_studio(request).status()}


@router.get("/orb/api/models")
async def orb_models(request: Request) -> dict[str, object]:
    require_loopback_admin(request)
    studio = orb_studio(request)
    try:
        models = await asyncio.to_thread(lambda: studio.brain().list_models())
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"LM Studio is not reachable: {exc}"
        ) from exc
    return {"models": models, "current": studio.brain().model}


@router.post("/orb/api/model")
async def orb_set_model(
    payload: OrbModelPayload, request: Request
) -> dict[str, object]:
    require_loopback_admin(request)
    studio = orb_studio(request)
    await asyncio.to_thread(studio.set_model, payload.model)
    return {"model": payload.model}


@router.post("/orb/api/chat")
async def orb_chat(payload: OrbChatPayload, request: Request) -> dict[str, object]:
    require_loopback_admin(request)
    studio = orb_studio(request)
    try:
        reply = await asyncio.to_thread(studio.ask, payload.text.strip())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "reply": reply.text,
        "tools_used": reply.tools_used,
        "compacted": reply.compacted,
        "model": reply.model,
    }


@router.post("/orb/api/new")
async def orb_new(request: Request) -> dict[str, object]:
    require_loopback_admin(request)
    saved = await asyncio.to_thread(orb_studio(request).brain().new_conversation)
    return {"saved": saved}


@router.post("/orb/api/resume")
async def orb_resume(payload: OrbResumePayload, request: Request) -> dict[str, object]:
    require_loopback_admin(request)
    brain = orb_studio(request).brain()
    memory = await asyncio.to_thread(brain.resume, payload.topic)
    return {"memory": memory, "loaded": bool(brain.memory_note)}


@router.post("/orb/api/tools/reload")
async def orb_reload_tools(request: Request) -> dict[str, object]:
    require_loopback_admin(request)
    studio = orb_studio(request)
    await asyncio.to_thread(studio.reload_tools)
    return studio.status()


@router.post("/orb/api/say")
def orb_say(payload: OrbSayPayload, request: Request) -> dict[str, object]:
    """Let JARVIS (running in LM Studio) speak through the orb."""
    require_loopback_admin(request)
    return {"id": orb_studio(request).inbox.say(payload.text, payload.source)}


@router.get("/orb/api/inbox")
def orb_inbox(request: Request, after: int = 0) -> dict[str, object]:
    require_loopback_admin(request)
    studio = orb_studio(request)
    return {"items": studio.inbox.after(after), "state": studio.state}


@router.post("/orb/api/advisor")
def orb_set_advisor(payload: OrbAdvisorPayload, request: Request) -> dict[str, object]:
    """Turn the read-only API advisor on (model name) or off (null)."""
    require_loopback_admin(request)
    studio = orb_studio(request)
    try:
        studio.set_advisor(payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"advisor_model": studio.advisor_model}


@router.post("/orb/api/advise")
async def orb_advise(payload: OrbAdvisePayload, request: Request) -> dict[str, object]:
    """JARVIS (in LM Studio) asks the advisor; it can only read the tool list."""
    require_loopback_admin(request)
    studio = orb_studio(request)
    try:
        advice = await asyncio.to_thread(studio.advise, payload.question)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"advice": advice, "advisor_model": studio.advisor_model}


def _voice(request: Request) -> JarvisVoice:
    voice = orb_studio(request).voice
    if voice is None:
        raise HTTPException(status_code=404, detail="This orb has no offline voice.")
    return voice


@router.get("/orb/api/voice")
def orb_voice_status(request: Request) -> dict[str, object]:
    require_loopback_admin(request)
    return _voice(request).status()


@router.post("/orb/api/voice/setup")
def orb_voice_setup(request: Request) -> dict[str, object]:
    """Download Jarvis's voice once (about 120 MB); it then works offline."""
    require_loopback_admin(request)
    voice = _voice(request)
    voice.start_download()
    return voice.status()


@router.post("/orb/api/voice/settings")
def orb_voice_settings(payload: OrbVoicePayload, request: Request) -> dict[str, object]:
    require_loopback_admin(request)
    voice = _voice(request)
    try:
        voice.configure(voice=payload.voice, speed=payload.speed, effect=payload.effect)
    except VoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return voice.status()


@router.post("/orb/api/speak")
async def orb_speak(payload: OrbSpeakPayload, request: Request) -> Response:
    """Speak one sentence with Jarvis's offline voice; returns WAV audio."""
    require_loopback_admin(request)
    voice = _voice(request)
    try:
        audio = await asyncio.to_thread(voice.synthesize, payload.text)
    except VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/wav")


@router.post("/orb/api/privacy")
def orb_privacy(payload: OrbPrivacyPayload, request: Request) -> dict[str, object]:
    """Local only (default on): the advisor may only use a model on this PC."""
    require_loopback_admin(request)
    studio = orb_studio(request)
    studio.set_local_only(payload.local_only)
    return {"local_only": studio.local_only, "advisor_model": studio.advisor_model}


def _ears(request: Request) -> LocalEars:
    ears = orb_studio(request).ears
    if ears is None:
        raise HTTPException(status_code=404, detail="This orb has no offline ears.")
    return ears


@router.get("/orb/api/ears")
def orb_ears_status(request: Request) -> dict[str, object]:
    require_loopback_admin(request)
    return _ears(request).status()


@router.post("/orb/api/ears/setup")
def orb_ears_setup(request: Request) -> dict[str, object]:
    """Download Whisper once (about 145 MB); it then works offline."""
    require_loopback_admin(request)
    ears = _ears(request)
    ears.start_download()
    return ears.status()


@router.post("/orb/api/listen")
async def orb_listen(request: Request) -> dict[str, object]:
    """Turn a recording from the orb's microphone into text, on this PC."""
    require_loopback_admin(request)
    ears = _ears(request)
    audio = await request.body()
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="That recording is too long.")
    try:
        text = await asyncio.to_thread(ears.transcribe, audio)
    except EarsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"text": text}


@router.post("/orb/api/transcribe")
async def orb_transcribe(request: Request) -> dict[str, object]:
    """Transcribe a whole audio file on this PC (used by JARVIS's video notes)."""
    require_loopback_admin(request)
    ears = _ears(request)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="That audio file is too big.")
    audio = await request.body()
    task_id, report = _progress(
        request, "FCC Whisper transcribing", "Transcribing audio"
    )
    try:
        out = await asyncio.to_thread(ears.transcribe_file, audio, report)
    except EarsError as exc:
        orb_studio(request).activity.update(task_id, detail=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    report(100.0)
    return out


def _youtube(request: Request) -> YouTubeAudio:
    youtube = getattr(request.app.state, "orb_youtube", None)
    if youtube is None:
        youtube = YouTubeAudio(config_dir_path() / "orb_downloads")
        request.app.state.orb_youtube = youtube
    return youtube


@router.post("/orb/api/youtube/audio")
async def orb_youtube_audio(
    payload: OrbYouTubePayload, request: Request
) -> FileResponse:
    """Download one YouTube video's audio (reused if already here) and return it."""
    require_loopback_admin(request)
    task_id, report = _progress(
        request, "FCC downloading the audio", "Downloading YouTube audio"
    )
    board = orb_studio(request).activity
    try:
        got = await asyncio.to_thread(_youtube(request).download, payload.url, report)
    except YouTubeError as exc:
        board.update(task_id, detail=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    report(100.0)
    return FileResponse(
        got["path"],
        media_type="application/octet-stream",
        filename=f"{got['video_id']}.{got['ext']}",
        headers={"X-Audio-Ext": got["ext"], "X-Video-Id": got["video_id"]},
    )


@router.post("/orb/api/youtube/transcript")
async def orb_youtube_transcript(
    payload: OrbYouTubePayload, request: Request
) -> dict[str, object]:
    """Download a YouTube video's audio and transcribe it, all on this PC."""
    require_loopback_admin(request)
    ears = _ears(request)
    _, fetched = _progress(request, "FCC downloading the audio", "YouTube transcript")
    try:
        got = await asyncio.to_thread(_youtube(request).download, payload.url, fetched)
        _, heard = _progress(request, "FCC Whisper transcribing", "YouTube transcript")
        out = await asyncio.to_thread(
            ears.transcribe_file, got["path"].read_bytes(), heard
        )
    except YouTubeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except EarsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "video_id": got["video_id"],
        "title": got["title"],
        "audio_file": str(got["path"]),
        **out,
    }


@router.get("/orb/api/activity")
def orb_activity(request: Request) -> dict[str, object]:
    """Progress bars and the live feed of what JARVIS is doing."""
    require_loopback_admin(request)
    return orb_studio(request).activity.snapshot()


@router.post("/orb/api/activity")
def orb_report_activity(
    payload: OrbActivityPayload, request: Request
) -> dict[str, object]:
    """JARVIS reports a job step or a tool call (from LM Studio or the orb)."""
    require_loopback_admin(request)
    board = orb_studio(request).activity
    if payload.note:
        board.note(payload.note, payload.source or "jarvis")
    fields = payload.model_dump(
        exclude={"id", "note", "reset_percent"}, exclude_none=True
    )
    if payload.reset_percent:
        fields["percent"] = None
    task_id = None
    if payload.id or payload.title:
        task_id = board.update(payload.id, **fields)
    return {"id": task_id}


def _progress(request: Request, label: str, default_title: str):
    """Report FCC's own download/transcribe % on the JARVIS job that asked for it."""
    board = orb_studio(request).activity
    job = request.headers.get("x-jarvis-job") or None
    task_id = board.update(
        job,
        detail=label,
        percent=0.0,
        **({} if job else {"title": default_title, "source": "fcc"}),
    )

    def report(percent: float) -> None:
        board.update(task_id, percent=percent, detail=f"{label} {percent:.0f}%")

    return task_id, report
