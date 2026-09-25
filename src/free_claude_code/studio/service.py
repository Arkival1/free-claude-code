"""The Studio facade: one object the HTTP layer and tests both drive."""

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import anyio.to_thread
import httpx
from loguru import logger

from free_claude_code.application.web_tools.ports import (
    WebFetchEgressPolicy,
    WebToolsPort,
    web_fetch_allowed_scheme_set,
)
from free_claude_code.config.model_refs import parse_provider_type
from free_claude_code.config.provider_catalog import PROVIDER_CATALOG
from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject, JsonValue

from . import system_monitor
from .agents import AgentRunner, TurnResult
from .assistant_tools import describe_time, now_line, parse_when
from .commands import CommandBroker, CommandError
from .connectivity import Connectivity
from .convo_notes import NotesKeeper
from .crew import Crew
from .downloads import CURATED_MODELS, ModelLibrary
from .guide import (
    GUIDE_TOPICS,
    STARTER_QUESTIONS,
    GuideAnswer,
    GuideAssistant,
    GuideState,
    diagnose,
    offline_answer,
    page_name,
)
from .learning import (
    LearnEngine,
    StudyStopped,
    parse_learn_request,
    wants_to_stop_learning,
)
from .llm import (
    LOCAL_MODEL_PREFIX,
    ChatMessage,
    LocalOpenAILLM,
    ProxyLLM,
    StudioLLMError,
    StudioModelRouter,
    ToolCall,
)
from .local_voice import (
    LocalVoice,
    LocalVoiceError,
    SetupState,
    speech_package_ready,
)
from .lora import LoraTrainer
from .memory import SHARED_MEMORY_ID, SKILL_TAG, MemoryService, keywords
from .model_files import (
    ModelFileError,
    check_model_file,
    match_listed_model,
    pick_model_file,
    place_in_lmstudio,
)
from .models import (
    AGENT_ROLES,
    Agent,
    AgentRun,
    Chat,
    ChatNotes,
    CommandRequest,
    Course,
    ExamQuestion,
    Lesson,
    LoraJob,
    MemoryEntry,
    Message,
    ModelAsset,
    SiteProject,
    Study,
    StudyLesson,
    TodoItem,
    TuneJob,
    TunePack,
    TuneSample,
    VideoNote,
    now_ms,
)
from .obsidian import ObsidianVault, VaultStatus
from .orders import parse_orders, pick_agent
from .platforms import (
    PlatformError,
    PlatformPage,
    PlatformReader,
    platform_of,
    youtube_id,
)
from .presets import (
    BUILDER_PROMPT,
    HELPER_PROMPT,
    HELPER_TOOLS,
    PROMPT_UPGRADES,
    RESEARCHER_PROMPT,
    RESEARCHER_TOOLS,
    TESTER_PROMPT,
    TESTER_TOOLS,
    agent_options,
)
from .recall_messages import Found, search
from .recall_messages import line as message_line
from .research import DeepResearch, ResearchMix, ResearchReport, relevance
from .rooms import RoomError, RoomOutcome, RoomService
from .school import School
from .search import SearchError, StudioSearch
from .sites import SiteWorkspace, slugify
from .store import StudioNotFoundError, StudioStore
from .team_models import (
    find_agent_name,
    match_model,
    model_label,
    parse_model_request,
    suggest_mix,
)
from .tools import (
    DEFAULT_TOOL_NAMES,
    MAIN_ROLE,
    MAIN_TOOL_NAMES,
    TOOL_SPEC_BY_NAME,
    AgentToolbox,
    ToolContext,
    ToolOutcome,
)
from .tuning import CloudTuner, LightTuner, TuningError
from .videos import VIDEO_TAGS, VideoError, VideoStudy, memory_line
from .voice import SpeechAudio, VoiceError, VoiceService, speakable

GUIDE_AGENT_NAME = "Guide"
BUILDER_AGENT_NAME = "Builder"
TEACHER_AGENT_NAME = "Teacher"
STUDENT_AGENT_NAME = "Student"
RESEARCHER_AGENT_NAME = "Researcher"
HELPER_AGENT_NAME = "Helper"
TESTER_AGENT_NAME = "Tester"
_DEFAULT_UPGRADES: dict[str, tuple[str, ...]] = {
    BUILDER_AGENT_NAME: (
        "research",
        "test_code",
        "ask_researcher",
        "edit_file",
        "search_files",
        "update_plan",
        "ask_helper",
        "check_project",
        "video_notes",
        "start_project",
        "restore_file",
        "polish_check",
        "conversation",
        "knowledge",
    ),
    RESEARCHER_AGENT_NAME: RESEARCHER_TOOLS,
    HELPER_AGENT_NAME: HELPER_TOOLS,
    TESTER_AGENT_NAME: TESTER_TOOLS,
}
_DEFAULT_ROLES = {
    BUILDER_AGENT_NAME: "builder",
    RESEARCHER_AGENT_NAME: "researcher",
    HELPER_AGENT_NAME: "helper",
    TESTER_AGENT_NAME: "tester",
}
SHARED_MEMORY_NAME = "Team memory"
MAIN_CONSOLE_SETTING = "console"
MAIN_PROMPT_NOTE = (
    "Run the team for the user: answer directly when you can, and hand work "
    "that needs building, research, or commands to the right agents."
)
_LOCAL_PROBE_SECONDS = 15.0
_DASHBOARD_SECONDS = 4.0
TEACH_MATERIAL_CHARS = 12_000
TEACH_PROMPT = (
    "You are turning material into a skill an AI agent will follow later. "
    "Write a short, practical how-to: when to use it, the exact commands, "
    "code patterns, or steps, and the gotchas. Plain text, at most 12 lines, "
    "no preamble."
)


class StudioError(RuntimeError):
    """Raised when a Studio operation cannot be completed."""


@dataclass(frozen=True, slots=True)
class ChatSettingsResult:
    """What a chat settings change produced, including a new chat."""

    chat: Chat
    opened_chat: Chat | None = None
    note: str = ""


_REMINDER_SECONDS = 10.0
_RECENT_RUNS = 40
_RECENT_STUDY_MS = 10 * 60_000


BRIEFING_PROMPT = (
    "You are {name}, the user's main AI, running on their PC. {agent} is an AI "
    "on an outside server. It cannot see the user's memory, notes, Obsidian "
    "vault, or earlier conversations; your briefing is all it gets. Write the "
    "briefing for this job: what the user wants done and why, the "
    "requirements, preferences, and facts from the conversation and your "
    "memory that the job needs, and what to hand back. Leave out anything "
    "personal the job does not need, such as names, addresses, contact "
    "details, health, money, passwords, and keys. Write it as direct "
    "instructions to {agent}, under 220 words. Write only the briefing."
)


def _study_started(study: Study) -> str:
    lessons = {"quick": 4, "normal": 7, "deep": 10}.get(study.depth, 7)
    return (
        f"Started learning {study.topic} ({study.depth}: about {lessons} lessons, "
        "each researched on the web, Reddit, and YouTube, written up as notes, "
        "and self-checked). Progress shows on the HUD."
    )


READ_MESSAGES = 40


def _whole(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("#").isdigit():
        return int(value.strip().lstrip("#"))
    return None


_SPEECH_CACHE = 48
"""Recently spoken pieces kept as audio, so repeats play at once."""


def _local(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000)


def _ago(ms: int) -> str:
    minutes = max(0, ms // 60_000)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} h ago" if hours < 48 else f"{hours // 24} days ago"


def _todo_lines(items: Sequence[TodoItem], *, now: datetime) -> str:
    lines = []
    for item in items:
        when = (
            f" — reminder {describe_time(_local(item.due_at), now=now)}"
            + (" (overdue)" if item.due_at < now.timestamp() * 1000 else "")
            if item.due_at
            else ""
        )
        lines.append(f"- {item.text}{when} (id {item.id})")
    return "\n".join(lines)


def _default_tools() -> tuple[str, ...]:
    return DEFAULT_TOOL_NAMES


def _shared_memory_owner() -> Agent:
    """Stand in for the team when its memory is written to Obsidian."""
    return Agent.model_validate(
        {
            "id": SHARED_MEMORY_ID,
            "name": SHARED_MEMORY_NAME,
            "role": "assistant",
            "model": "shared by every agent",
        }
    )


class StudioService:
    """Own every Studio use case and the background work they start."""

    def __init__(
        self,
        *,
        store: StudioStore,
        web_tools: WebToolsPort,
        settings_provider: Callable[[], Settings],
        models_dir: Path,
        sites_dir: Path,
        router: StudioModelRouter | None = None,
        search_transport: httpx.AsyncBaseTransport | None = None,
        voice_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._store = store
        self._web_tools = web_tools
        self._search_transport = search_transport
        self._voice_transport = voice_transport
        self._connectivity = Connectivity(transport=search_transport)
        self._settings_provider = settings_provider
        self._sites = SiteWorkspace(sites_dir)
        self._library = ModelLibrary(store=store, models_dir=models_dir)
        self._models_dir = models_dir
        self._voice_setup = SetupState()
        self._router = router or self._build_router(settings_provider())
        self._tasks: set[asyncio.Task[object]] = set()
        self._room_locks: dict[str, asyncio.Lock] = {}
        self._commands = CommandBroker(store=store)
        self._lora = LoraTrainer(
            store=store,
            router=self._router,
            jobs_dir=models_dir / "lora",
            settings_provider=settings_provider,
            spawn=self.spawn,
        )
        self._room_activity: dict[str, int] = {}
        self._memory_sync_lock = asyncio.Lock()
        self._main_busy = 0
        self._main_error: str | None = None
        self._local_probe: tuple[float, JsonObject] | None = None
        self._loaded_probe: tuple[float, tuple[str, ...] | None] | None = None
        self._agent_busy: dict[str, int] = {}
        self._mirror_queued = False
        self._live_text: dict[str, str] = {}
        self._console_extras: tuple[float, JsonObject] | None = None
        self._stand_in_note = ""
        self._video_lock = asyncio.Lock()
        self._run_jobs: dict[str, asyncio.Task[object]] = {}
        self._study_jobs: dict[str, asyncio.Task[object]] = {}
        self._reminders_checked = -_REMINDER_SECONDS
        self._speech_cache: dict[tuple[object, ...], bytes] = {}
        self._notes_keeper = NotesKeeper(
            store=self._store, router=self._router, spawn=self.spawn
        )
        self._voice_warmed = False
        self._studying: set[str] = set()
        self._router.use_stand_in(self._stand_in_model)
        self._router.use_turns(lambda: self.settings.studio_local_model_turns)

    # ---------------------------------------------------------------- wiring

    @property
    def settings(self) -> Settings:
        return self._settings_provider()

    @property
    def store(self) -> StudioStore:
        return self._store

    @property
    def workspace(self) -> SiteWorkspace:
        return self._sites

    @property
    def library(self) -> ModelLibrary:
        return self._library

    @property
    def lora(self) -> LoraTrainer:
        return self._lora

    def _build_router(self, settings: Settings) -> StudioModelRouter:
        proxy = ProxyLLM(
            base_url=f"http://127.0.0.1:{settings.port}",
            token=settings.proxy_auth_token if settings.proxy_auth_enabled else "",
            default_model=self.default_model,
        )
        local = LocalOpenAILLM(
            base_url=settings.studio_local_base_url,
            api_key=settings.studio_local_api_key or "",
            fast=lambda: self.settings.studio_local_fast_replies,
        )
        return StudioModelRouter(proxy=proxy, local=local)

    @property
    def default_model(self) -> str:
        settings = self.settings
        return settings.studio_default_model or settings.model

    def _server_model_ready(self, model: str) -> bool:
        """False when the model's provider needs a key or URL that is not set."""
        descriptor = PROVIDER_CATALOG.get(parse_provider_type(model))
        if descriptor is None or descriptor.local or descriptor.credential_attr is None:
            return True
        settings = self.settings
        return all(
            isinstance(getattr(settings, attr, None), str)
            and bool(getattr(settings, attr))
            for attr in descriptor.configuration_attrs()
        )

    async def _stand_in_model(self, model: str) -> str | None:
        """Use a model on this PC for one that cannot be reached.

        A fresh install defaults to a server model; when its provider has no
        key, or a local model is named that the runtime does not have, and LM
        Studio (or another local runtime) is serving a model, the agents use
        that instead of failing. The model loaded in memory wins.
        """
        local = model.startswith(LOCAL_MODEL_PREFIX)
        if not local and self._server_model_ready(model):
            return None
        status = await self._local_status()
        listed = status.get("models")
        served = [
            str(name)
            for name in (listed if isinstance(listed, list) else [])
            if "embed" not in str(name).lower()
        ]
        if not status.get("reachable") or not served or model in served:
            return None
        now = time.monotonic()
        cached = self._loaded_probe
        if cached is None or now - cached[0] >= _LOCAL_PROBE_SECONDS:
            cached = (now, await self._router.loaded_local_models())
            self._loaded_probe = cached
        loaded = [f"{LOCAL_MODEL_PREFIX}{name}" for name in cached[1] or ()]
        pick = next((name for name in loaded if name in served), served[0])
        why = "is not on this PC" if local else "has no key"
        note = f"{model} {why}, so Studio is using {pick} instead."
        if note != self._stand_in_note:
            self._stand_in_note = note
            logger.info("Studio: {}", note)
        return pick

    async def effective_model(self, model: str) -> str:
        """The model a call to this reference actually reaches."""
        return await self._stand_in_model(model) or model

    def _memory(self) -> MemoryService:
        settings = self.settings
        return MemoryService(
            self._store,
            working_limit=settings.studio_memory_working_limit,
            recall_limit=settings.studio_memory_recall_limit,
            shared=settings.studio_shared_memory,
        )

    def _search(self) -> StudioSearch:
        settings = self.settings
        return StudioSearch(
            provider=settings.studio_search_provider,
            api_key=settings.studio_search_api_key or "",
            base_url=settings.studio_search_base_url or "",
            fallback=self._web_tools,
            transport=self._search_transport,
        )

    def local_voice(self) -> LocalVoice:
        """The built-in voice and ears, stored with the models."""
        settings = self.settings
        return LocalVoice(
            self._models_dir / "voice",
            quality=settings.studio_voice_quality,
            voice=settings.studio_voice_name,
            speed=settings.studio_voice_speed,
            effect=settings.studio_voice_effect,
            whisper_size=settings.studio_voice_ears,
            language=settings.studio_voice_language or "",
            transport=self._voice_transport,
        )

    def voice_engines(self) -> tuple[str, str]:
        """Which engine speaks and which listens: builtin, server, or browser."""
        settings = self.settings
        chosen = settings.studio_voice_engine
        if chosen == "auto":
            chosen = (
                "builtin"
                if speech_package_ready()
                else "server"
                if settings.studio_voice_speak_url
                else "browser"
            )
        local = self.local_voice()
        if chosen == "builtin":
            listen = (
                "builtin"
                if local.status()["listen_package"]
                else "server"
                if settings.studio_voice_listen_url
                else "browser"
            )
            return "builtin", listen
        if chosen == "server":
            return "server", "server" if settings.studio_voice_listen_url else "browser"
        return "browser", "browser"

    def voice_status(self) -> JsonObject:
        """Everything the HUD needs to know to talk and listen."""
        speak, listen = self.voice_engines()
        local = self.local_voice()
        details = local.status()
        speak_ready = (
            bool(details["speech_ready"]) if speak == "builtin" else speak == "server"
        )
        listen_ready = (
            bool(details["listen_ready"]) if listen == "builtin" else listen == "server"
        )
        return {
            "speak": speak,
            "listen": listen,
            "speak_ready": speak_ready,
            "listen_ready": listen_ready,
            "builtin": details,
            "server": self.voice().status(),
            "setup": self._voice_setup.as_json(),
        }

    def start_voice_setup(self) -> JsonObject:
        """Download the built-in voice and ears once, in the background."""
        state = self._voice_setup
        if state.phase != "running":
            state.phase = "running"
            state.done = 0
            state.total = 0
            state.message = "Preparing the voice"
            self.spawn(self._voice_setup_run())
        return self.voice_status()

    async def _voice_setup_run(self) -> None:
        state = self._voice_setup

        async def progress(done: int, total: int, message: str) -> None:
            state.done, state.total, state.message = done, total, message

        try:
            await self.local_voice().setup(state, progress)
        finally:
            state.phase = "failed" if state.errors else "ready"
            state.message = "; ".join(state.errors) or "Voice ready"

    async def speak(self, text: str) -> SpeechAudio:
        """Say one reply in the main AI's voice, on this PC or via a server."""
        speak, _ = self.voice_engines()
        if speak == "builtin":
            if not self.local_voice().speech_ready():
                raise VoiceError("The built-in voice is still downloading.")
            settings = self.settings
            spoken = speakable(text)
            key = (
                spoken,
                settings.studio_voice_name,
                settings.studio_voice_speed,
                settings.studio_voice_effect,
                settings.studio_voice_quality,
            )
            audio = self._speech_cache.get(key)
            if audio is None:
                audio = await self.local_voice().speak(spoken)
                self._speech_cache[key] = audio
                while len(self._speech_cache) > _SPEECH_CACHE:
                    self._speech_cache.pop(next(iter(self._speech_cache)))
            return SpeechAudio(audio=audio, content_type="audio/wav")
        if speak == "server":
            return await self.voice().speak(text)
        raise VoiceError("The browser speaks for the main AI; nothing to render here.")

    async def transcribe(self, audio: bytes, *, content_type: str) -> str:
        """Turn one recorded turn of the user's speech into text."""
        _, listen = self.voice_engines()
        if listen == "builtin":
            if "wav" not in content_type:
                raise VoiceError("The built-in ears take WAV recordings.")
            return await self.local_voice().transcribe(audio)
        if listen == "server":
            return await self.voice().transcribe(audio, content_type=content_type)
        raise VoiceError("The browser listens for the main AI.")

    def voice(self) -> VoiceService:
        """The voice-server engine, as configured right now."""
        settings = self.settings
        name = settings.studio_voice_name
        return VoiceService(
            speak_url=settings.studio_voice_speak_url or "",
            speak_key=settings.studio_voice_speak_key or "",
            speak_model=settings.studio_voice_speak_model,
            voice="bm_george" if name == "jarvis" else name,
            listen_url=settings.studio_voice_listen_url or "",
            listen_key=settings.studio_voice_listen_key or "",
            listen_model=settings.studio_voice_listen_model,
            language=settings.studio_voice_language or "",
            transport=self._voice_transport,
        )

    def _reader(self) -> PlatformReader:
        settings = self.settings
        return PlatformReader(
            youtube_api_key=settings.studio_youtube_api_key or "",
            reddit_client_id=settings.studio_reddit_client_id or "",
            reddit_client_secret=settings.studio_reddit_client_secret or "",
            transport=self._search_transport,
        )

    def _videos(self) -> VideoStudy:
        return VideoStudy(
            store=self._store,
            reader=self._reader(),
            router=self._router,
            model=self._video_model,
            remember=self._remember_video,
            lock=self._video_lock,
        )

    async def _video_model(self) -> str:
        """Videos are studied with the Researcher's model, like its research."""
        researcher = await self.agent_by_name(RESEARCHER_AGENT_NAME)
        chosen = (researcher.model if researcher else "") or self.default_model
        return await self.effective_model(chosen)

    async def _remember_video(self, note: VideoNote) -> str:
        """Put a studied video in the team's memory, replacing an older entry."""
        memory = self._memory()
        if note.memory_id:
            await self._store.delete(MemoryEntry, note.memory_id)
        owner = SHARED_MEMORY_ID
        if not memory.shared_enabled:
            researcher = await self.agent_by_name(RESEARCHER_AGENT_NAME)
            owner = researcher.id if researcher else SHARED_MEMORY_ID
        entry = await memory.remember(
            owner,
            memory_line(note),
            tags=(*VIDEO_TAGS, "verified"),
            source=note.url,
            author=note.studied_by or "Researcher",
        )
        return entry.id if entry else ""

    def _study_later(self, page: PlatformPage) -> None:
        """Turn a video research just read into notes, without holding anyone up."""
        video = youtube_id(page.url) or page.url
        if video in self._studying:
            return
        self._studying.add(video)

        async def study() -> None:
            try:
                await self._videos().study(page.url, page=page, source="research")
                await self._after_memory_change([], wait=False)
            except (VideoError, StudioError, OSError) as error:
                logger.info("Studio: could not study {}: {}", page.url, error)
            finally:
                self._studying.discard(video)

        self.spawn(study())

    async def study_video(self, url: str, *, focus: str = "") -> VideoNote:
        """Study a video the user gives Studio."""
        try:
            note = await self._videos().study(url, focus=focus, source="user")
        except (VideoError, PlatformError, httpx.HTTPError) as error:
            raise StudioError(str(error)) from error
        await self._after_memory_change([], wait=False)
        return note

    async def video_notes(self, query: str = "") -> tuple[VideoNote, ...]:
        """Studied videos, best match first when there is a query."""
        return tuple(await self._videos().notes(query, limit=50))

    async def video_note(self, note_id: str) -> VideoNote:
        return await self._store.require(VideoNote, note_id)

    async def delete_video_note(self, note_id: str) -> bool:
        """Forget a studied video and its memory entry."""
        note = await self._store.get(VideoNote, note_id)
        if note is None:
            return False
        if note.memory_id:
            await self._store.delete(MemoryEntry, note.memory_id)
        return await self._store.delete(VideoNote, note_id)

    def _egress(self) -> WebFetchEgressPolicy:
        settings = self.settings
        return WebFetchEgressPolicy(
            allow_private_network_targets=settings.web_fetch_allow_private_networks,
            allowed_schemes=web_fetch_allowed_scheme_set(
                settings.web_fetch_allowed_schemes
            ),
        )

    def _toolbox(self) -> AgentToolbox:
        settings = self.settings
        return AgentToolbox(
            web_tools=self._web_tools,
            sites=self._sites,
            memory=self._memory(),
            egress=self._egress(),
            commands=self._commands,
            command_policy=settings.studio_agent_commands,
            command_timeout=float(settings.studio_command_timeout),
            delegate=Crew(
                store=self._store,
                host=self,
                helper_pipeline=settings.studio_helper_pipeline,
            ),
            searcher=self._search(),
            web_access=settings.studio_web_access,
            reader=self._reader(),
            research_sources=settings.studio_research_sources,
            research_mix=ResearchMix(
                web=settings.studio_research_web,
                reddit=settings.studio_research_reddit,
                youtube=settings.studio_research_youtube,
            ),
            connectivity=self._connectivity,
            app_help=self.app_help,
            videos=self._videos(),
            study_later=self._study_later,
            assistant=self._assistant_tool,
        )

    def _runner(self) -> AgentRunner:
        return AgentRunner(
            store=self._store,
            router=self._router,
            toolbox=self._toolbox(),
            memory=self._memory(),
            default_model=self.default_model,
            max_steps=self.settings.studio_agent_max_steps,
            builder_max_steps=self.settings.studio_builder_max_steps,
            live=self._live_text,
            temperature=self.settings.studio_agent_temperature,
            notes=self._notes_keeper,
            sealed=self.is_private_from,
        )

    def _tuner(self) -> LightTuner:
        settings = self.settings
        cloud: CloudTuner | None = None
        if settings.studio_cloud_tuning_base_url:
            cloud = CloudTuner(
                base_url=settings.studio_cloud_tuning_base_url,
                api_key=settings.studio_cloud_tuning_api_key or "",
            )
        return LightTuner(
            store=self._store,
            router=self._router,
            default_model=self.default_model,
            rounds=settings.studio_tuning_rounds,
            cloud=cloud,
            cloud_provider=settings.studio_cloud_tuning_provider or "",
        )

    def _school(self) -> School:
        return School(
            store=self._store,
            router=self._router,
            memory=self._memory(),
            tuner=self._tuner(),
            default_model=self.default_model,
            sealed=self.is_private_from,
        )

    def _rooms(self) -> RoomService:
        return RoomService(
            store=self._store,
            runner=self._runner(),
            memory=self._memory(),
        )

    def _vault(self) -> ObsidianVault:
        settings = self.settings
        root = (
            Path(settings.studio_obsidian_vault).expanduser()
            if settings.studio_obsidian_vault
            else None
        )
        return ObsidianVault(root, folder=settings.studio_obsidian_folder)

    def _guide(self, model: str) -> GuideAssistant:
        return GuideAssistant(router=self._router, model=model)

    def spawn(self, coroutine) -> asyncio.Task[object]:
        """Run background work and keep a reference until it finishes."""
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def wait_for_background(self) -> None:
        """Wait for background work started by this service to finish."""
        while self._tasks:
            for task in tuple(self._tasks):
                with contextlib.suppress(Exception):
                    await task

    async def shutdown(self) -> None:
        """Cancel outstanding background work."""
        for task in tuple(self._tasks):
            task.cancel()
        for task in tuple(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # ---------------------------------------------------------------- agents

    async def ensure_defaults(self) -> tuple[Agent, ...]:
        """Create the starter agents the app expects on first run."""
        existing = await self._store.find(Agent)
        by_name = {agent.name: agent for agent in existing}
        settings = self.settings
        wanted = (
            (
                GUIDE_AGENT_NAME,
                "guide",
                settings.studio_guide_model,
                "Explain how this app works, in plain language.",
                (),
            ),
            (
                BUILDER_AGENT_NAME,
                "builder",
                self.default_model,
                BUILDER_PROMPT,
                _default_tools(),
            ),
            (
                RESEARCHER_AGENT_NAME,
                "researcher",
                self.default_model,
                RESEARCHER_PROMPT,
                RESEARCHER_TOOLS,
            ),
            (
                HELPER_AGENT_NAME,
                "helper",
                self.default_model,
                HELPER_PROMPT,
                HELPER_TOOLS,
            ),
            (
                TESTER_AGENT_NAME,
                "tester",
                self.default_model,
                TESTER_PROMPT,
                TESTER_TOOLS,
            ),
            (
                TEACHER_AGENT_NAME,
                "teacher",
                settings.studio_teacher_model or self.default_model,
                "Plan lessons, teach them one at a time, and test the student.",
                (),
            ),
            (
                STUDENT_AGENT_NAME,
                "student",
                settings.studio_student_model or self.default_model,
                "Learn from the teacher and keep what you learn in memory.",
                (),
            ),
        )
        await self._upgrade_defaults(existing)
        created: list[Agent] = []
        if all(agent.role != MAIN_ROLE for agent in existing):
            main = Agent.model_validate(
                {
                    "name": settings.studio_main_agent_name,
                    "role": MAIN_ROLE,
                    "model": settings.studio_main_agent_model or self.default_model,
                    "model_setting": settings.studio_main_agent_model or "",
                    "system_prompt": MAIN_PROMPT_NOTE,
                    "description": "Your main AI. Talks with you and runs the team.",
                    "tools": MAIN_TOOL_NAMES,
                    "local_only": (settings.studio_main_agent_model or "").startswith(
                        LOCAL_MODEL_PREFIX
                    ),
                }
            )
            await self._store.put(main)
            created.append(main)
        for name, role, model, prompt, tools in wanted:
            if name in by_name:
                continue
            agent = Agent.model_validate(
                {
                    "name": name,
                    "role": role,
                    "model": model,
                    "system_prompt": prompt,
                    "description": prompt,
                    "tools": tools,
                    "local_only": model.startswith("local/"),
                }
            )
            await self._store.put(agent)
            created.append(agent)
        return tuple(created)

    def agent_options(self) -> JsonObject:
        """Roles, presets, and tool groups for the add-agent sheet."""
        return agent_options()

    async def _upgrade_defaults(self, existing: Sequence[Agent]) -> None:
        """Give starter agents from older versions their newer tools and roles.

        Starter agents made before a Studio Default Model was set were given
        the server's model; once one is set, they move to it.
        """
        settings = self.settings
        studio_default = settings.studio_default_model
        for agent in existing:
            if (
                studio_default
                and agent.name in _DEFAULT_ROLES
                and agent.role != "guide"
                and agent.model == settings.model
                and agent.model != studio_default
            ):
                agent = agent.model_copy(
                    update={
                        "model": studio_default,
                        "local_only": studio_default.startswith(LOCAL_MODEL_PREFIX),
                        "updated_at": now_ms(),
                    }
                )
                await self._store.put(agent)
            if agent.role == MAIN_ROLE:
                wanted = MAIN_TOOL_NAMES
                role = MAIN_ROLE
            elif agent.name in _DEFAULT_UPGRADES:
                wanted = _DEFAULT_UPGRADES[agent.name]
                role = (
                    _DEFAULT_ROLES[agent.name] if agent.role == "agent" else agent.role
                )
            else:
                continue
            missing = tuple(tool for tool in wanted if tool not in agent.tools)
            prompt = PROMPT_UPGRADES.get(agent.system_prompt, agent.system_prompt)
            if not missing and role == agent.role and prompt == agent.system_prompt:
                continue
            await self._store.put(
                agent.model_copy(
                    update={
                        "tools": (*agent.tools, *missing),
                        "role": role,
                        "system_prompt": prompt,
                        "updated_at": now_ms(),
                    }
                )
            )

    async def agents(self) -> tuple[Agent, ...]:
        """Return every agent, oldest first."""
        return await self._store.find(Agent, order_by="created_at ASC")

    async def agent(self, agent_id: str) -> Agent:
        """Return one agent or raise."""
        return await self._store.require(Agent, agent_id)

    async def agent_by_name(self, name: str) -> Agent | None:
        """Return the first agent with an exact name."""
        for agent in await self.agents():
            if agent.name == name:
                return agent
        return None

    async def create_agent(
        self,
        *,
        name: str,
        role: str = "assistant",
        model: str = "",
        system_prompt: str = "",
        tools: Sequence[str] | None = None,
        memory_enabled: bool = True,
        description: str = "",
    ) -> Agent:
        """Create one agent with its own role, model, tools, and memory."""
        if not name.strip():
            raise StudioError("An agent needs a name.")
        if role not in AGENT_ROLES or role in {MAIN_ROLE, "guide"}:
            raise StudioError(f"Pick a role; {role!r} is not one Studio knows.")
        chosen = tuple(dict.fromkeys(tools)) if tools is not None else _default_tools()
        unknown = [tool for tool in chosen if tool not in TOOL_SPEC_BY_NAME]
        if unknown:
            raise StudioError(f"Unknown tools: {', '.join(unknown)}.")
        agent = Agent.model_validate(
            {
                "name": name.strip(),
                "role": role,
                "model": model or self.default_model,
                "system_prompt": system_prompt,
                "description": description or system_prompt[:200],
                "tools": chosen,
                "memory_enabled": memory_enabled,
                "local_only": (model or "").startswith("local/"),
            }
        )
        await self._store.put(agent)
        return agent

    async def update_agent(self, agent_id: str, updates: JsonObject) -> Agent:
        """Apply a partial update to one agent."""
        agent = await self._store.require(Agent, agent_id)
        allowed = {
            key: value
            for key, value in updates.items()
            if key
            in {
                "name",
                "role",
                "model",
                "system_prompt",
                "description",
                "tools",
                "memory_enabled",
                "tune_pack_id",
                "archived",
            }
        }
        if "tools" in allowed and isinstance(allowed["tools"], list):
            allowed["tools"] = tuple(str(item) for item in allowed["tools"])
        updated = agent.model_copy(update={**allowed, "updated_at": now_ms()})
        await self._store.put(updated)
        return updated

    async def delete_agent(self, agent_id: str) -> bool:
        """Delete one agent and the memories it owns."""
        await self._store.delete_where(MemoryEntry, {"agent_id": agent_id})
        return await self._store.delete(Agent, agent_id)

    # ----------------------------------------------------------------- chats

    async def chats(self, *, kind: str | None = None) -> tuple[Chat, ...]:
        """Return chats, most recently updated first."""
        where = {"kind": kind} if kind else None
        return await self._store.find(Chat, where=where, order_by="updated_at DESC")

    async def chat(self, chat_id: str) -> Chat:
        """Return one chat or raise."""
        return await self._store.require(Chat, chat_id)

    async def create_chat(
        self,
        *,
        agent_id: str | None = None,
        title: str = "",
        kind: str = "chat",
        site_id: str | None = None,
        settings: JsonObject | None = None,
        parent_chat_id: str | None = None,
    ) -> Chat:
        """Open one chat bound to an agent."""
        if agent_id is None:
            agents = await self.agents()
            if not agents:
                await self.ensure_defaults()
                agents = await self.agents()
            agent_id = agents[0].id
        agent = await self._store.require(Agent, agent_id)
        chat = Chat.model_validate(
            {
                "title": title or f"{agent.name} chat",
                "kind": kind,
                "agent_id": agent.id,
                "site_id": site_id,
                "settings": dict(settings or {}),
                "parent_chat_id": parent_chat_id,
            }
        )
        await self._store.put(chat)
        return chat

    async def transcript(self, chat_id: str, *, after: int = 0) -> tuple[Message, ...]:
        """Return a chat transcript, optionally only entries after a sequence."""
        return await self._store.transcript(chat_id, after=after)

    async def send(self, chat_id: str, text: str) -> TurnResult:
        """Send one user message and return the agent's reply."""
        if not text.strip():
            raise StudioError("Write something first.")
        chat = await self._store.require(Chat, chat_id)
        if chat.agent_id is None:
            raise StudioError("This chat has no agent.")
        if chat.kind == "room":
            outcome = await self.room_say(chat.id, text, background=False)
            last = await self._store.transcript(chat.id, limit=1)
            reply = last[-1].text if last else ""
            return TurnResult(
                text=reply,
                steps=outcome.turns if outcome else 0,
                tool_calls=outcome.speakers if outcome else (),
            )
        agent = await self._store.require(Agent, chat.agent_id)
        if agent.role == "guide":
            return await self._guide_turn(chat, agent, text)
        async with self._working(agent.id):
            prepare = (
                (lambda: self._prepare_main_turn(agent, chat, text))
                if agent.role == MAIN_ROLE
                else None
            )
            result = await self._runner().reply(agent, chat, text, prepare=prepare)
        await self._after_memory_change([agent.id], wait=False)
        if chat.title in {"New chat", f"{agent.name} chat"}:
            await self._store.put(
                chat.model_copy(
                    update={"title": text.strip()[:48], "updated_at": now_ms()}
                )
            )
        if self.settings.studio_obsidian_auto_sync:
            await self._safe_sync_chat(chat.id)
        return result

    async def _guide_turn(self, chat: Chat, agent: Agent, text: str) -> TurnResult:
        await self._store.append_message(
            chat_id=chat.id, role="user", text=text, author="user"
        )
        answer = await self.ask_guide(text)
        await self._store.append_message(
            chat_id=chat.id,
            role="assistant",
            text=answer.text,
            author=agent.name,
            data={
                "topics": list(answer.topics),
                "route": answer.route,
                "offline": answer.offline,
                "links": [
                    {"label": link.label, "route": link.route} for link in answer.links
                ],
                "suggestions": list(answer.suggestions),
            },
        )
        return TurnResult(text=answer.text, steps=1)

    async def update_chat_settings(
        self, chat_id: str, updates: JsonObject
    ) -> ChatSettingsResult:
        """Apply chat settings; toggles that change behavior open a new chat."""
        chat = await self._store.require(Chat, chat_id)
        merged = {**chat.settings, **updates}
        updated = chat.model_copy(update={"settings": merged, "updated_at": now_ms()})
        await self._store.put(updated)
        turned_on = [
            key
            for key in ("light_tuning", "teacher_mode")
            if bool(updates.get(key)) and not bool(chat.settings.get(key))
        ]
        if "light_tuning" in turned_on:
            opened = await self._open_tuned_chat(updated)
            return ChatSettingsResult(
                chat=updated,
                opened_chat=opened,
                note=(
                    "Light tuning is on. A fresh chat opened so the tuned profile "
                    "starts clean."
                ),
            )
        if "teacher_mode" in turned_on:
            course = await self.open_class(topic=chat.title)
            opened = await self._store.require(Chat, course.chat_id)
            return ChatSettingsResult(
                chat=updated,
                opened_chat=opened,
                note="Teacher mode is on. A classroom opened for this topic.",
            )
        return ChatSettingsResult(chat=updated)

    async def _open_tuned_chat(self, chat: Chat) -> Chat:
        if chat.agent_id is None:
            raise StudioError("This chat has no agent to tune.")
        agent = await self._store.require(Agent, chat.agent_id)
        pack = await self._active_pack(agent)
        # Turning tuning on in chat settings is the user's consent for this
        # agent, so the pack may run without the global switch.
        updates: dict[str, object] = {"opted_in": True}
        if pack.teacher_model is None and agent.model.startswith(LOCAL_MODEL_PREFIX):
            updates["teacher_model"] = self.default_model
        pack = pack.model_copy(update=updates)
        await self._store.put(pack)
        fresh = await self.create_chat(
            agent_id=agent.id,
            title=f"{agent.name} (tuned)",
            site_id=chat.site_id,
            settings={**chat.settings, "light_tuning": True, "pack_id": pack.id},
            parent_chat_id=chat.id,
        )
        await self._store.append_message(
            chat_id=fresh.id,
            role="event",
            text=(
                "Light tuning is on for this chat. Add a few example answers on "
                "the Tuning tab, then run a tune; it takes a handful of small "
                "calls and finishes on a phone."
            ),
            author="studio",
            data={"kind": "tuning_enabled", "pack_id": pack.id},
        )
        return fresh

    async def _active_pack(self, agent: Agent) -> TunePack:
        packs = await self._store.find(TunePack, where={"agent_id": agent.id})
        active = next((pack for pack in packs if pack.active), None)
        if active is not None:
            return active
        if packs:
            return packs[-1]
        return await self._tuner().create_pack(
            agent, backend=self.settings.studio_tuning_backend
        )

    async def delete_chat(self, chat_id: str) -> bool:
        """Delete one chat, its transcript, and its notes."""
        await self._store.delete_where(Message, {"chat_id": chat_id})
        await self._store.delete(ChatNotes, chat_id)
        return await self._store.delete(Chat, chat_id)

    async def chat_notes(self, chat_id: str) -> ChatNotes:
        """The running notes on a long conversation (empty until it is long)."""
        await self._store.require(Chat, chat_id)
        return await self._notes_keeper.get(chat_id)

    # -------------------------------------------------------------- commands

    async def pending_commands(self) -> tuple[CommandRequest, ...]:
        """Return agent commands waiting for the user's approval."""
        return await self._commands.pending()

    async def decide_command(self, request_id: str, *, approve: bool) -> CommandRequest:
        """Approve or deny one waiting command."""
        try:
            return await self._commands.decide(request_id, approve=approve)
        except CommandError as error:
            raise StudioError(str(error)) from error

    # ----------------------------------------------------------------- rooms

    async def create_room(
        self,
        *,
        title: str = "",
        member_ids: Sequence[str] = (),
        goal: str = "",
        site_id: str | None = None,
    ) -> Chat:
        """Open a chat room for the user and several agents."""
        if not member_ids:
            await self.ensure_defaults()
            member_ids = [
                agent.id
                for agent in await self.agents()
                if agent.role
                in {
                    "agent",
                    "builder",
                    "researcher",
                    "helper",
                    "teacher",
                    "student",
                    "assistant",
                }
            ]
        if site_id:
            await self._store.require(SiteProject, site_id)
        try:
            room = await self._rooms().create(
                title=title, member_ids=member_ids, goal=goal
            )
        except RoomError as error:
            raise StudioError(str(error)) from error
        if site_id:
            room = room.model_copy(update={"site_id": site_id})
            await self._store.put(room)
        return room

    async def rooms(self) -> tuple[Chat, ...]:
        """Return every room, most recently active first."""
        return await self.chats(kind="room")

    async def room_detail(self, room_id: str, *, after: int = 0) -> JsonObject:
        """Return a room, who is in it, its task state, and its transcript."""
        room = await self._store.require(Chat, room_id)
        members = await self._rooms().members(room)
        messages = await self._store.transcript(room_id, after=after)
        return {
            "room": room.model_dump(),
            "members": [member.model_dump() for member in members],
            "running": self._room_activity.get(room_id, 0) > 0,
            "messages": [message.model_dump() for message in messages],
        }

    async def room_members(self, room_id: str, member_ids: Sequence[str]) -> Chat:
        """Replace a room's members."""
        try:
            return await self._rooms().set_members(room_id, member_ids)
        except RoomError as error:
            raise StudioError(str(error)) from error

    async def room_say(
        self, room_id: str, text: str, *, background: bool = True
    ) -> RoomOutcome | None:
        """Post as the user; the addressed agents answer and may hand off."""
        try:
            _, speakers = await self._rooms().post(room_id, text)
        except RoomError as error:
            raise StudioError(str(error)) from error
        return await self._drive_room(room_id, speakers, background=background)

    async def room_start_task(
        self, room_id: str, goal: str, *, background: bool = True
    ) -> RoomOutcome | None:
        """Give the room a task; the lead agent plans it and hands parts off."""
        try:
            _, speakers = await self._rooms().start_task(room_id, goal)
        except RoomError as error:
            raise StudioError(str(error)) from error
        return await self._drive_room(room_id, speakers, background=background)

    async def room_continue(
        self, room_id: str, *, background: bool = True
    ) -> RoomOutcome | None:
        """Let the lead agent pick the conversation back up."""
        room = await self._store.require(Chat, room_id)
        members = await self._rooms().members(room)
        if not members:
            raise StudioError("This room has no agents.")
        return await self._drive_room(room_id, members[:1], background=background)

    async def room_stop(self, room_id: str) -> Chat:
        """Stop the agents after the turn in progress."""
        try:
            return await self._rooms().stop(room_id)
        except RoomError as error:
            raise StudioError(str(error)) from error

    async def _drive_room(
        self, room_id: str, speakers: Sequence[Agent], *, background: bool
    ) -> RoomOutcome | None:
        # Count the work as active before it is scheduled, so a status read
        # made right after posting already reports the agents as talking.
        self._room_activity[room_id] = self._room_activity.get(room_id, 0) + 1
        if background:
            self.spawn(self._converse(room_id, speakers))
            return None
        return await self._converse(room_id, speakers)

    async def _converse(self, room_id: str, speakers: Sequence[Agent]) -> RoomOutcome:
        lock = self._room_locks.setdefault(room_id, asyncio.Lock())
        try:
            async with lock:
                outcome = await self._rooms().converse(room_id, speakers)
            room = await self._store.require(Chat, room_id)
            await self._after_memory_change(list(room.member_ids))
        finally:
            # Only report the room idle once its memory is mirrored too.
            remaining = self._room_activity.get(room_id, 1) - 1
            if remaining > 0:
                self._room_activity[room_id] = remaining
            else:
                self._room_activity.pop(room_id, None)
        return outcome

    async def _after_memory_change(
        self, agent_ids: Sequence[str], *, wait: bool = True
    ) -> None:
        """Mirror memory into Obsidian after agents write to it, when enabled.

        After an agent's turn the mirror runs in the background, so the reply
        is done without waiting for files to be written; memory itself is
        already saved. Changes made while a mirror runs get one more mirror.
        """
        settings = self.settings
        if not (
            agent_ids
            and settings.studio_obsidian_memory_sync
            and settings.studio_obsidian_vault
        ):
            return
        if wait:
            await self._mirror_memory()
            return
        if not self._mirror_queued:
            self._mirror_queued = True
            self.spawn(self._mirror_memory())

    async def _mirror_memory(self) -> None:
        self._mirror_queued = False
        try:
            await self.sync_memory_structure()
        except (OSError, RuntimeError) as error:
            logger.warning("Studio memory mirror failed: {}", error)

    # ------------------------------------------------------------ agent runs

    async def start_task(
        self,
        *,
        agent_id: str,
        goal: str,
        site_id: str | None = None,
        chat_id: str | None = None,
        parent_chat_id: str | None = None,
    ) -> AgentRun:
        """Queue one autonomous agent task and start it in the background."""
        agent = await self._store.require(Agent, agent_id)
        if not goal.strip():
            raise StudioError("A task needs a goal.")
        chat = (
            await self._store.require(Chat, chat_id)
            if chat_id
            else await self.create_chat(
                agent_id=agent.id,
                title=goal.strip()[:48],
                kind="agent",
                site_id=site_id,
                parent_chat_id=parent_chat_id,
            )
        )
        run = AgentRun.model_validate(
            {
                "agent_id": agent.id,
                "chat_id": chat.id,
                "goal": goal.strip(),
                "site_id": site_id or chat.site_id,
                "max_steps": self._steps_for(agent),
            }
        )
        await self._store.put(run)
        job = self.spawn(self._run_task(agent.id, chat.id, run.id))
        self._run_jobs[run.id] = job
        job.add_done_callback(lambda _: self._run_jobs.pop(run.id, None))
        return run

    async def _run_task(self, agent_id: str, chat_id: str, run_id: str) -> None:
        try:
            agent = await self._store.require(Agent, agent_id)
            chat = await self._store.require(Chat, chat_id)
            run = await self._store.require(AgentRun, run_id)
            async with self._working(agent.id):
                finished = await self._runner().run_task(agent, chat, run)
            await self._refresh_site_count(finished.site_id)
            await self._after_memory_change([agent.id], wait=False)
            if chat.parent_chat_id:
                await self._report_to_parent(chat, agent, finished)
        except (StudioNotFoundError, StudioError) as error:
            logger.warning("Studio task {} failed to start: {}", run_id, error)

    async def _report_to_parent(self, chat: Chat, agent: Agent, run: AgentRun) -> None:
        """Tell the conversation that handed off the work how it went."""
        parent_id = chat.parent_chat_id
        if parent_id is None or await self._store.get(Chat, parent_id) is None:
            return
        summary = (run.result or run.error or "").strip()[:600]
        await self._store.append_message(
            chat_id=parent_id,
            role="event",
            text=f"{agent.name} finished in the background ({run.status}): {summary}",
            author=agent.name,
            data={
                "kind": "background_done",
                "run_id": run.id,
                "chat_id": chat.id,
                "status": run.status,
            },
        )

    def _steps_for(self, agent: Agent) -> int:
        """Builders get room for whole apps; everyone else the usual budget."""
        settings = self.settings
        if agent.role == "builder":
            return max(
                settings.studio_builder_max_steps, settings.studio_agent_max_steps
            )
        return settings.studio_agent_max_steps

    async def stop_agent_work(self, agent_id: str) -> list[AgentRun]:
        """Stop an agent's background tasks; returns the tasks that were stopped."""
        stopped: list[AgentRun] = []
        for run in await self.runs(agent_id=agent_id):
            if run.status not in {"queued", "running"}:
                continue
            job = self._run_jobs.pop(run.id, None)
            if job is None:
                continue
            job.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await job
            current = await self._store.require(AgentRun, run.id)
            finished = current.model_copy(
                update={
                    "status": "cancelled",
                    "error": "Stopped by the user.",
                    "updated_at": now_ms(),
                }
            )
            await self._store.put(finished)
            await self._store.append_message(
                chat_id=run.chat_id,
                role="event",
                text="Stopped by the user.",
                author="studio",
                data={"kind": "run_finished", "run_id": run.id, "status": "cancelled"},
            )
            stopped.append(finished)
        return stopped

    async def team_report(self) -> str:
        """What every agent is doing and has just done, for the main AI."""
        runs = (*await self._active_runs(), *await self.runs(limit=_RECENT_RUNS))
        busy = await self._busy_agents(runs)
        now = now_ms()
        lines: list[str] = []
        for agent in await self.agents():
            if agent.archived or agent.role in {MAIN_ROLE, "guide"}:
                continue
            own = [run for run in runs if run.agent_id == agent.id]
            active = next((r for r in own if r.status in {"queued", "running"}), None)
            done = next((r for r in own if r.status not in {"queued", "running"}), None)
            state = "working" if agent.id in busy or active else "free"
            line = f"- {agent.name} ({agent.role}, {state})"
            if active is not None:
                line += f": on step {active.step} of {active.max_steps} of '{active.goal[:120]}'"
            if done is not None:
                minutes = max(0, (now - done.updated_at) // 60_000)
                outcome = (done.result or done.error or "").strip().replace("\n", " ")
                line += (
                    f". Last task {done.status} {minutes} min ago: '{done.goal[:80]}'"
                    + (f" — {outcome[:160]}" if outcome else "")
                )
            lines.append(line)
        pending = await self._commands.pending()
        if pending:
            lines.append(
                f"{len(pending)} command(s) wait for the user's Run it or Deny."
            )
        return "\n".join(lines) or "The team has no agents yet."

    async def _prepare_main_turn(self, main: Agent, chat: Chat, text: str) -> str:
        """The clock, plus any orders handed out, for the main AI's reply."""
        switched = await self._carry_out_model_change(main, chat, text)
        if switched:
            return "\n".join((now_line(datetime.now()), switched))
        orders = await self._carry_out_orders(main, chat, text)
        learning = await self._carry_out_learning(chat, text, started_by=main.name)
        return "\n".join(
            part for part in (now_line(datetime.now()), orders, learning) if part
        )

    async def _carry_out_learning(
        self, chat: Chat, text: str, *, started_by: str
    ) -> str:
        """'Learn electrical engineering' starts a study at once; 'stop learning' stops it."""
        if wants_to_stop_learning(text):
            active = [
                s for s in await self.studies() if s.status in {"planning", "learning"}
            ]
            for study in active:
                await self.stop_study(study.id)
            if not active:
                return "There was no study running to stop."
            stopped = (
                f"Stopped learning {active[0].topic}; the finished lessons are kept."
            )
            await self._store.append_message(
                chat_id=chat.id,
                role="tool",
                text=stopped,
                author="learn",
                data={"tool": "learn", "study_id": active[0].id, "order": True},
            )
            return f"{stopped} Tell the user in a sentence."
        wanted = parse_learn_request(text)
        if wanted is None:
            return ""
        topic, depth = wanted
        try:
            study = await self.start_study(topic, depth=depth, started_by=started_by)
        except StudioError as error:
            return f"Could not start learning {topic}: {error}"
        await self._store.append_message(
            chat_id=chat.id,
            role="tool",
            text=_study_started(study),
            author="learn",
            data={"tool": "learn", "study_id": study.id, "order": True},
        )
        return (
            f"{_study_started(study)} Do not start it again; tell the user in a "
            "sentence that you are on it and that the bar on the HUD shows how far "
            "you are."
        )

    # ------------------------------------------------------ assistant tools

    async def _assistant_tool(
        self, call: ToolCall, context: ToolContext
    ) -> ToolOutcome:
        """To-dos, projects, and the PC's status, for the main AI and the Helper."""
        match call.name:
            case "todo":
                return await self._todo_tool(call, context)
            case "list_projects":
                return await self._projects_tool(call)
            case "conversation":
                return await self._conversation_tool(call, context)
            case "learn":
                study = await self.start_study(
                    str(call.arguments.get("topic") or ""),
                    focus=str(call.arguments.get("focus") or ""),
                    depth=str(call.arguments.get("depth") or "normal"),
                    started_by=context.agent_name,
                )
                return ToolOutcome(
                    text=_study_started(study),
                    data={"tool": "learn", "study_id": study.id},
                )
            case "knowledge":
                return await self._knowledge_tool(call)
            case "agent_model":
                return await self._agent_model_tool(call)
            case _:
                return await self._system_tool()

    async def _todo_tool(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        action = str(call.arguments.get("action", "")).strip().lower()
        wanted = str(call.arguments.get("id", "")).strip()
        now = datetime.now()
        if action == "add":
            item = await self.add_todo(
                str(call.arguments.get("text", "")),
                due=str(call.arguments.get("due") or ""),
                added_by=context.agent_name,
            )
            when = (
                f" Reminder {describe_time(_local(item.due_at), now=now)}."
                if item.due_at
                else ""
            )
            text = f"Added to the to-do list: {item.text}.{when} (id {item.id})"
        elif action in {"done", "remove"}:
            item = await self._find_todo(wanted)
            if action == "done":
                await self.finish_todo(item.id)
                text = f"Marked done: {item.text}."
            else:
                await self.remove_todo(item.id)
                text = f"Removed: {item.text}."
        else:
            items = await self.todos()
            text = _todo_lines(items, now=now) or "The to-do list is empty."
        return ToolOutcome(text=text, data={"tool": "todo", "action": action or "list"})

    async def _find_todo(self, wanted: str) -> TodoItem:
        if not wanted:
            raise ValueError("Give the id from the to-do list.")
        item = await self._store.get(TodoItem, wanted)
        if item is not None:
            return item
        match = [
            item
            for item in await self.todos()
            if wanted.casefold() in item.text.casefold()
        ]
        if len(match) == 1:
            return match[0]
        raise ValueError(f"No single to-do matches {wanted!r}; list them for the ids.")

    async def _conversation_tool(
        self, call: ToolCall, context: ToolContext
    ) -> ToolOutcome:
        """Search or read every message of an agent's conversations."""
        args = call.arguments
        query = str(args.get("query") or "").strip()
        first, last = _whole(args.get("from")), _whole(args.get("to"))
        if first is not None or last is not None:
            low = max(1, first or (last or 1) - 10)
            high = max(low, last or low + 20)
            high = min(high, low + READ_MESSAGES - 1)
            messages = [
                message
                for message in await self._store.transcript(
                    context.chat_id, after=low - 1
                )
                if message.sequence <= high
            ]
            text = "\n".join(message_line(message, limit=2_000) for message in messages)
            return ToolOutcome(
                text=text or f"There are no messages #{low} to #{high}.",
                data={"tool": "conversation", "from": low, "to": high},
            )
        found = [
            Found(message) for message in await self._store.transcript(context.chat_id)
        ]
        if str(args.get("scope") or "this") == "all":
            for other in await self._store.find(
                Chat,
                where={"agent_id": context.agent_id},
                order_by="updated_at DESC",
                limit=10,
            ):
                if other.id != context.chat_id:
                    found.extend(
                        Found(message, earlier_chat=True)
                        for message in await self._store.transcript(other.id)
                    )
        if not query:
            newest = found[-1].message.sequence if found else 0
            return ToolOutcome(
                text=(
                    f"This conversation has {newest} messages (#1 to #{newest}). "
                    "Search with query, or read with from and to."
                ),
                data={"tool": "conversation", "messages": newest},
            )
        hits = search(found, query, limit=12)
        lines = [
            message_line(
                item.message,
                where=" (earlier conversation)" if item.earlier_chat else "",
            )
            for item in hits
        ]
        text = (
            "\n".join(lines)
            + "\nRead around a hit with from and to for the full exchange."
            if lines
            else f"Nothing in the conversation matches '{query}'."
        )
        return ToolOutcome(
            text=text, data={"tool": "conversation", "query": query, "hits": len(hits)}
        )

    # -------------------------------------------------------- private memory

    def runs_on_this_pc(self, model: str) -> bool:
        """True for models this PC runs itself (LM Studio, Ollama, llama.cpp)."""
        if model.startswith(LOCAL_MODEL_PREFIX):
            return True
        descriptor = PROVIDER_CATALOG.get(parse_provider_type(model))
        return descriptor is not None and descriptor.local

    async def is_private_from(self, agent: Agent) -> bool:
        """True when the agent thinks on a server, so memory stays away from it."""
        if not self.settings.studio_private_memory:
            return False
        model = await self.effective_model(agent.model or self.default_model)
        return not self.runs_on_this_pc(model)

    async def _briefed(
        self, worker: Agent, goal: str, parent_chat_id: str | None
    ) -> str:
        """The job as a server agent gets it: with the main AI's briefing.

        A server agent cannot see memory, so when the main AI (on this PC)
        hands it work, the main AI writes what the job needs from the
        conversation and memory, and the briefing is shown to the user.
        """
        if not parent_chat_id or not await self.is_private_from(worker):
            return goal
        main = await self.main_agent()
        parent = await self._store.get(Chat, parent_chat_id)
        if parent is None or parent.agent_id != main.id:
            return goal
        if await self.is_private_from(main):
            return goal
        brief = await self._write_briefing(main, worker, goal, parent)
        await self._store.append_message(
            chat_id=parent.id,
            role="tool",
            text=(
                f"Briefing for {worker.name} (a server AI, so it can't see your "
                f"memory):\n{brief}"
            ),
            author="briefing",
            data={"tool": "briefing", "agent": worker.name, "agent_id": worker.id},
        )
        return f"The job: {goal.strip()}\n\nBriefing from {main.name}:\n{brief}"

    async def _write_briefing(
        self, main: Agent, worker: Agent, goal: str, chat: Chat
    ) -> str:
        said = [
            message
            for message in await self._store.transcript(chat.id, limit=16)
            if message.role in {"user", "assistant"} and message.text.strip()
        ][-10:]
        recent = "\n".join(
            f"{'User' if m.role == 'user' else main.name}: {' '.join(m.text.split())[:400]}"
            for m in said
        )
        memory = (
            await self._memory().context_block(main.id, goal)
            if main.memory_enabled
            else ""
        )
        prompt = "\n\n".join(
            part
            for part in (
                f"The job: {goal.strip()}",
                f"Recent conversation:\n{recent}" if recent else "",
                memory,
            )
            if part
        )
        try:
            reply = await self._router.complete(
                [ChatMessage.user(prompt)],
                model=await self.effective_model(main.model or self.default_model),
                system=BRIEFING_PROMPT.format(name=main.name, agent=worker.name),
                temperature=0.2,
                max_tokens=500,
            )
            brief = reply.text.strip()
        except StudioLLMError as error:
            logger.info("Studio: briefing fell back to the job itself: {}", error)
            brief = ""
        return brief or goal.strip()

    # ---------------------------------------------------------- team brains

    async def _known_models(self) -> list[str]:
        """Models on this PC first, then the server models already in use."""
        local = await self.local_models()
        listed = local.get("models")
        known = [
            str(model)
            for model in (listed if isinstance(listed, list) else [])
            if "embed" not in str(model).lower()
        ]
        settings = self.settings
        for model in (
            settings.studio_default_model,
            settings.model,
            *(settings.model_fallbacks or ()),
            *(agent.model for agent in await self.agents()),
        ):
            if model and model not in known:
                known.append(model)
        return known

    async def team_models(self) -> JsonObject:
        """Which model each agent thinks with, and what it actually reaches."""
        rows: list[JsonValue] = []
        for agent in await self.agents():
            if agent.archived:
                continue
            model = agent.model or self.default_model
            using = await self.effective_model(model)
            rows.append(
                {
                    "id": agent.id,
                    "name": agent.name,
                    "role": agent.role,
                    "model": model,
                    "using": using,
                    "private": await self.is_private_from(agent),
                    "note": ""
                    if using == model
                    else f"{model_label(model)} isn't available, so "
                    f"{agent.name} is using {model_label(using)} for now.",
                }
            )
        turns = self._router.turns
        return {
            "agents": rows,
            "local": await self.local_models(),
            "turns": self.settings.studio_local_model_turns,
            "private_memory": self.settings.studio_private_memory,
            "working": [model_label(m) for m in turns.working],
            "waiting": [model_label(m) for m in turns.waiting],
        }

    async def assign_models(self, assignments: Mapping[str, str]) -> tuple[Agent, ...]:
        """Give each named agent its own model. Returns the agents changed."""
        changed: list[Agent] = []
        for agent_id, wanted in assignments.items():
            model = wanted.strip()
            if not model:
                raise StudioError("Pick a model for every agent you change.")
            agent = await self._store.require(Agent, agent_id)
            if agent.model == model:
                continue
            agent = agent.model_copy(
                update={
                    "model": model,
                    "local_only": model.startswith(LOCAL_MODEL_PREFIX),
                    "updated_at": now_ms(),
                }
            )
            await self._store.put(agent)
            changed.append(agent)
        return tuple(changed)

    async def suggest_team_models(self) -> dict[str, str]:
        """A starting mix from the models on this PC: agent id to model."""
        local = await self.local_models()
        listed = local.get("models")
        models = [str(m) for m in (listed if isinstance(listed, list) else [])]
        team = [(a.id, a.role) for a in await self.agents() if not a.archived]
        return suggest_mix(team, models)

    async def _find_team_member(self, spoken: str) -> Agent:
        team = [agent for agent in await self.agents() if not agent.archived]
        main = await self.main_agent()
        name = find_agent_name(spoken, [a.name for a in team], main=main.name)
        agent = next((a for a in team if a.name == name), None)
        if agent is None:
            raise ValueError(
                f"No agent called {spoken}. The team: "
                + ", ".join(a.name for a in team)
                + "."
            )
        return agent

    async def _agent_model_tool(self, call: ToolCall) -> ToolOutcome:
        spoken = str(call.arguments.get("agent") or "").strip()
        wanted = str(call.arguments.get("model") or "").strip()
        if not spoken:
            brains = await self.team_models()
            rows = brains["agents"] if isinstance(brains["agents"], list) else []
            lines = [
                f"- {row['name']}: {model_label(str(row['model']))}"
                + (f" ({row['note']})" if row.get("note") else "")
                for row in rows
                if isinstance(row, dict)
            ]
            local = [
                model_label(m)
                for m in await self._known_models()
                if m.startswith(LOCAL_MODEL_PREFIX)
            ]
            text = "\n".join(lines) + (
                "\nModels on this PC: " + ", ".join(local)
                if local
                else "\nLM Studio lists no models right now."
            )
            return ToolOutcome(text=text, data={"tool": "agent_model"})
        agent = await self._find_team_member(spoken)
        if not wanted:
            return ToolOutcome(
                text=f"{agent.name} thinks with {model_label(agent.model)}.",
                data={"tool": "agent_model", "agent_id": agent.id},
            )
        known = await self._known_models()
        model = match_model(wanted, known)
        if model is None:
            local = [model_label(m) for m in known if m.startswith(LOCAL_MODEL_PREFIX)]
            raise ValueError(
                f"No model matches '{wanted}'. "
                + (
                    "Models on this PC: " + ", ".join(local) + "."
                    if local
                    else "LM Studio lists no models right now."
                )
            )
        await self.assign_models({agent.id: model})
        return ToolOutcome(
            text=f"{agent.name} now thinks with {model_label(model)}.",
            data={"tool": "agent_model", "agent_id": agent.id, "model": model},
        )

    async def _carry_out_model_change(self, main: Agent, chat: Chat, text: str) -> str:
        """'Give the Builder qwen coder' switches the Builder's model at once."""
        team = [agent for agent in await self.agents() if not agent.archived]
        wanted = parse_model_request(text, [a.name for a in team], main=main.name)
        if wanted is None:
            return ""
        spoken, model_text = wanted
        model = match_model(model_text, await self._known_models())
        agent = next((a for a in team if a.name == spoken), None)
        if model is None or agent is None:
            return ""
        await self.assign_models({agent.id: model})
        line = f"{agent.name} now thinks with {model_label(model)}."
        await self._store.append_message(
            chat_id=chat.id,
            role="tool",
            text=line,
            author="agent_model",
            data={
                "tool": "agent_model",
                "agent_id": agent.id,
                "model": model,
                "order": True,
            },
        )
        return f"{line} It is done; tell the user in a sentence."

    # ------------------------------------------------------------- learning

    async def start_study(
        self,
        topic: str,
        *,
        focus: str = "",
        depth: str = "normal",
        started_by: str = "you",
    ) -> Study:
        """Start teaching the main AI a subject in the background."""
        cleaned = " ".join(topic.split())[:160]
        if len(cleaned) < 3:
            raise StudioError("Say what to learn.")
        for other in await self.studies():
            if other.status in {"planning", "learning"}:
                raise StudioError(
                    f"Already learning {other.topic} ({round(other.progress * 100)}%). "
                    "Stop it first, or wait until it finishes."
                )
        study = Study(
            topic=cleaned,
            focus=" ".join(focus.split())[:300],
            depth=depth if depth in {"quick", "normal", "deep"} else "normal",
            started_by=started_by,
            step="Getting ready",
        )
        await self._store.put(study)
        job = self.spawn(self._run_study(study.id))
        self._study_jobs[study.id] = job
        job.add_done_callback(lambda _: self._study_jobs.pop(study.id, None))
        return study

    async def _run_study(self, study_id: str) -> None:
        main = await self.main_agent()
        engine = LearnEngine(
            store=self._store,
            router=self._router,
            model=lambda: self.effective_model(main.model or self.default_model),
            research=self._study_research,
            remember=self._remember_learned,
            name=main.name,
        )
        chat = await self.main_chat()
        try:
            study = await engine.run(study_id)
        except StudyStopped:
            return
        except (
            StudioError,
            StudioLLMError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            logger.warning("Studio: study {} failed: {}", study_id, error)
            current = await self._store.get(Study, study_id)
            if current is not None:
                await self._store.put(
                    current.model_copy(
                        update={
                            "status": "failed",
                            "error": str(error),
                            "updated_at": now_ms(),
                        }
                    )
                )
            await self._store.append_message(
                chat_id=chat.id,
                role="assistant",
                text=f"I had to stop learning: {error}",
                author=main.name,
                data={"kind": "study", "study_id": study_id},
            )
            return
        understood = round((study.understanding or 0) * 100)
        await self._store.append_message(
            chat_id=chat.id,
            role="assistant",
            text=(
                f"I finished learning {study.topic}: {len(study.plan)} lessons, "
                f"self-check {understood}%. Ask me anything about it, or open "
                "Knowledge & Memory to read my notes."
            ),
            author=main.name,
            data={"kind": "study", "study_id": study.id},
        )
        await self._after_memory_change([main.id], wait=False)

    async def _study_research(
        self, query: str, wanted: int, on_source: Callable[[str], None]
    ) -> ResearchReport:
        settings = self.settings
        engine = DeepResearch(
            search=self._search(),
            reader=self._reader(),
            fetch=lambda url: self._web_tools.fetch(url, egress=self._egress()),
            wanted=wanted,
            mix=ResearchMix(
                web=min(settings.studio_research_web, wanted),
                reddit=min(settings.studio_research_reddit, 1),
                youtube=min(settings.studio_research_youtube, 1),
            ),
            on_source=on_source,
        )
        report = await engine.run(query)
        for page in report.videos:
            self._study_later(page)
        return report

    async def _remember_learned(
        self, text: str, tags: tuple[str, ...], source: str
    ) -> str:
        memory = self._memory()
        owner = SHARED_MEMORY_ID
        if not memory.shared_enabled:
            owner = (await self.main_agent()).id
        entry = await memory.remember(
            owner, text, tags=tags, source=source, author="Learn mode"
        )
        return entry.id if entry else ""

    async def stop_study(self, study_id: str) -> Study:
        """Stop a study; the lessons it finished are kept."""
        study = await self._store.require(Study, study_id)
        if study.status in {"planning", "learning"}:
            study = study.model_copy(
                update={
                    "status": "cancelled",
                    "step": "Stopped by the user",
                    "updated_at": now_ms(),
                }
            )
            await self._store.put(study)
        job = self._study_jobs.pop(study_id, None)
        if job is not None:
            job.cancel()
        return study

    async def studies(self) -> tuple[Study, ...]:
        return await self._store.find(Study, order_by="created_at DESC")

    async def study_detail(
        self, study_id: str
    ) -> tuple[Study, tuple[StudyLesson, ...]]:
        study = await self._store.require(Study, study_id)
        lessons = await self._store.find(
            StudyLesson, where={"study_id": study_id}, order_by="ordinal ASC"
        )
        return study, lessons

    async def delete_study(self, study_id: str) -> bool:
        """Forget a study, its lessons, and their memory entries."""
        await self.stop_study(study_id)
        study, lessons = await self.study_detail(study_id)
        for item in (*lessons, study):
            if item.memory_id:
                await self._store.delete(MemoryEntry, item.memory_id)
        await self._store.delete_where(StudyLesson, {"study_id": study_id})
        return await self._store.delete(Study, study_id)

    async def _knowledge_tool(self, call: ToolCall) -> ToolOutcome:
        wanted = str(call.arguments.get("id") or "").strip()
        query = str(call.arguments.get("query") or "").strip()
        if wanted.startswith("lsn_"):
            lesson = await self._store.get(StudyLesson, wanted)
            if lesson is None:
                raise ValueError(f"No lesson with id {wanted}.")
            study = await self._store.get(Study, lesson.study_id)
            quiz = "\n".join(f"Q: {q}\nA: {a}" for q, a in lesson.quiz)
            text = (
                f"Lesson {lesson.ordinal + 1} of {study.topic if study else 'a study'}: "
                f"{lesson.title}\n\n{lesson.notes}"
                + (f"\n\nSelf-check:\n{quiz}" if quiz else "")
                + (
                    "\n\nSources:\n" + "\n".join(lesson.sources)
                    if lesson.sources
                    else ""
                )
            )
            return ToolOutcome(text=text, data={"tool": "knowledge", "id": wanted})
        if wanted.startswith("stu_"):
            study, lessons = await self.study_detail(wanted)
            text = (
                f"Study of {study.topic} ({study.status}, {round(study.progress * 100)}%)\n"
                f"{study.summary or 'The study guide is written when it finishes.'}\n\nLessons:\n"
                + "\n".join(f"- {lesson.id}: {lesson.title}" for lesson in lessons)
            )
            return ToolOutcome(text=text, data={"tool": "knowledge", "id": wanted})
        lessons = await self._store.find(StudyLesson, order_by="created_at DESC")
        terms = keywords(query)
        if terms:
            scored = sorted(
                (
                    (
                        relevance(
                            f"{lesson.title} {lesson.title} {lesson.notes}", terms
                        ),
                        lesson,
                    )
                    for lesson in lessons
                ),
                key=lambda pair: -pair[0],
            )
            lessons = tuple(lesson for fit, lesson in scored if fit > 0)
        topics = {study.id: study.topic for study in await self.studies()}
        lines = [
            f"- {lesson.id}: {topics.get(lesson.study_id, '?')} → {lesson.title}"
            for lesson in lessons[:15]
        ]
        text = (
            "\n".join(lines) + "\nRead one with its id."
            if lines
            else "Nothing learned matches that yet."
            if query
            else "Nothing has been learned yet; the learn tool starts a study."
        )
        return ToolOutcome(text=text, data={"tool": "knowledge", "query": query})

    async def _projects_tool(self, call: ToolCall) -> ToolOutcome:
        query = str(call.arguments.get("query") or "").strip().casefold()
        sites = [
            site
            for site in await self.sites()
            if not query
            or query in site.name.casefold()
            or query in site.description.casefold()
        ]
        now = now_ms()
        lines = [
            f"- {site.name}: {site.file_count} files, changed "
            f"{_ago(now - site.updated_at)}. Preview /studio/sites/{site.id}/index.html"
            f" · open in the app /studio#site/{site.id}"
            for site in sites[:25]
        ]
        text = "\n".join(lines) or (
            "No project matches that." if query else "There are no projects yet."
        )
        return ToolOutcome(
            text=text, data={"tool": "list_projects", "projects": [s.id for s in sites]}
        )

    async def _system_tool(self) -> ToolOutcome:
        reading = await anyio.to_thread.run_sync(
            lambda: system_monitor.sample(self._models_dir)
        )
        local = await self._local_status()
        voice = self.voice_status()
        listed = local.get("models")
        served = ", ".join(
            str(m) for m in (listed if isinstance(listed, list) else [])[:6]
        )
        lines = [
            f"CPU {reading.get('cpu') if reading.get('cpu') is not None else '?'}% of "
            f"{reading.get('cores')} cores; memory {reading.get('memory')}% of "
            f"{reading.get('memory_gb')} GB; disk {reading.get('disk')}% of "
            f"{reading.get('disk_gb')} GB used.",
            "LM Studio: "
            + (
                f"running, serving {served or 'no models'}."
                if local.get("reachable")
                else f"not reachable at {local.get('base_url')}."
            ),
            f"Internet: {'online' if self._connectivity.online else 'offline'}.",
            f"Voice: {voice.get('speak')}"
            f"{'' if voice.get('speak_ready') else ' (not downloaded yet)'}.",
        ]
        return ToolOutcome(
            text="\n".join(lines), data={"tool": "system_status", **reading}
        )

    async def todos(self, *, include_done: bool = False) -> tuple[TodoItem, ...]:
        """The user's to-do list: reminders by time first, then the rest."""
        items = await self._store.find(TodoItem, order_by="created_at ASC")
        shown = [item for item in items if include_done or not item.done]
        return tuple(
            sorted(
                shown,
                key=lambda item: (item.done, item.due_at or 2**62, item.created_at),
            )
        )

    async def add_todo(
        self, text: str, *, due: str = "", added_by: str = "you"
    ) -> TodoItem:
        """Add a to-do, with a reminder when due says when."""
        cleaned = " ".join(text.split())[:300]
        if not cleaned:
            raise StudioError("Say what to add.")
        due_at = None
        if due.strip():
            try:
                due_at = int(parse_when(due, now=datetime.now()).timestamp() * 1000)
            except ValueError as error:
                raise StudioError(str(error)) from error
        item = TodoItem(text=cleaned, due_at=due_at, added_by=added_by)
        await self._store.put(item)
        return item

    async def finish_todo(self, todo_id: str) -> TodoItem:
        item = await self._store.require(TodoItem, todo_id)
        done = item.model_copy(update={"done": True, "done_at": now_ms()})
        await self._store.put(done)
        return done

    async def remove_todo(self, todo_id: str) -> bool:
        return await self._store.delete(TodoItem, todo_id)

    async def _fire_due_reminders(self) -> None:
        """Announce reminders that are due in the main AI's conversation."""
        now = time.monotonic()
        if now - self._reminders_checked < _REMINDER_SECONDS:
            return
        self._reminders_checked = now
        due = [
            item
            for item in await self._store.find(TodoItem, where={"done": False})
            if item.due_at is not None and not item.reminded and item.due_at <= now_ms()
        ]
        if not due:
            return
        main = await self.main_agent()
        chat = await self.main_chat()
        for item in due:
            await self._store.put(item.model_copy(update={"reminded": True}))
            await self._store.append_message(
                chat_id=chat.id,
                role="assistant",
                text=f"Reminder: {item.text}",
                author=main.name,
                data={"kind": "reminder", "todo_id": item.id},
            )

    def _warm_voice(self) -> None:
        """Load the built-in voice in the background once the HUD is open."""
        if self._voice_warmed:
            return
        speak, _ = self.voice_engines()
        if speak != "builtin":
            return
        voice = self.local_voice()
        if not voice.speech_ready():
            # Still downloading: try again on a later poll, once it is here.
            return
        self._voice_warmed = True

        async def warm() -> None:
            try:
                await anyio.to_thread.run_sync(voice.warm)
            except (LocalVoiceError, OSError, RuntimeError, ValueError) as error:
                logger.info("Studio: voice warm-up skipped: {}", error)

        self.spawn(warm())

    async def _carry_out_orders(self, main: Agent, chat: Chat, text: str) -> str:
        """Hand out the jobs the user told the main AI to give, before it answers.

        'Have Builder make a page', '@Researcher look into X', 'get an agent to
        ...', and 'stop Builder' are carried out right away, so an order never
        depends on a small model choosing to call a tool.
        """
        team = [
            agent
            for agent in await self.agents()
            if not agent.archived and agent.role not in {MAIN_ROLE, "guide"}
        ]
        orders = parse_orders(text, [agent.name for agent in team])
        if not orders:
            return ""
        crew = Crew(
            store=self._store,
            host=self,
            helper_pipeline=self.settings.studio_helper_pipeline,
        )
        context = ToolContext(
            agent_id=main.id,
            chat_id=chat.id,
            site_id=chat.site_id,
            agent_name=main.name,
            agent_role=main.role,
        )
        done: list[str] = []
        for order in orders:
            name = order.agent or pick_agent(
                order.task, [(agent.name, agent.role) for agent in team]
            )
            worker = next((agent for agent in team if agent.name == name), None)
            if worker is None:
                continue
            if order.stop:
                stopped = await self.stop_agent_work(worker.id)
                line = (
                    f"Stopped {worker.name}: "
                    + "; ".join(f"'{run.goal[:80]}'" for run in stopped)
                    if stopped
                    else f"{worker.name} had no background task to stop."
                )
                await self._store.append_message(
                    chat_id=chat.id,
                    role="tool",
                    text=line,
                    author="stop_agent",
                    data={"tool": "stop_agent", "agent": worker.name, "order": True},
                )
                done.append(line)
                continue
            try:
                outcome = await crew.ask_agent(
                    context,
                    agent=worker.name,
                    task=order.task,
                    project="",
                    background=True,
                )
            except (ValueError, StudioError) as error:
                done.append(f"Could not give {worker.name} the job: {error}")
                continue
            await self._store.append_message(
                chat_id=chat.id,
                role="tool",
                text=outcome.text,
                author="ask_agent",
                data={**outcome.data, "order": True, "task": order.task},
            )
            done.append(
                f"{worker.name} is now working on: {order.task}. {outcome.text}"
            )
        if not done:
            return ""
        return (
            "The user's orders were handed out already:\n"
            + "\n".join(f"- {line}" for line in done)
            + "\nDo not hand these out again or do the work yourself. Tell the user "
            "in a sentence or two who is doing what; each agent reports back here "
            "when it finishes. Answer anything else they asked."
        )

    async def start_agent_task(
        self,
        agent: Agent,
        goal: str,
        *,
        site_id: str | None,
        parent_chat_id: str | None,
    ) -> AgentRun:
        """Start a hand-off in the background; the crew uses this."""
        return await self.start_task(
            agent_id=agent.id,
            goal=await self._briefed(agent, goal, parent_chat_id),
            site_id=site_id,
            parent_chat_id=parent_chat_id,
        )

    async def runs(
        self, *, agent_id: str | None = None, limit: int | None = None
    ) -> tuple[AgentRun, ...]:
        """Return agent tasks, newest first."""
        where = {"agent_id": agent_id} if agent_id else None
        return await self._store.find(
            AgentRun, where=where, order_by="created_at DESC", limit=limit
        )

    async def _active_runs(self) -> tuple[AgentRun, ...]:
        """Tasks still going, without reading every task ever run."""
        running = await self._store.find(AgentRun, where={"status": "running"})
        queued = await self._store.find(AgentRun, where={"status": "queued"})
        return (*running, *queued)

    async def run(self, run_id: str) -> AgentRun:
        """Return one agent task."""
        return await self._store.require(AgentRun, run_id)

    async def run_agent_task(
        self,
        agent: Agent,
        goal: str,
        *,
        site_id: str | None,
        parent_chat_id: str | None,
    ) -> tuple[AgentRun, Chat]:
        """Run one task on an agent and wait for it; the main agent uses this."""
        goal = await self._briefed(agent, goal, parent_chat_id)
        chat = await self.create_chat(
            agent_id=agent.id,
            title=goal.strip()[:48],
            kind="agent",
            site_id=site_id,
            parent_chat_id=parent_chat_id,
        )
        run = AgentRun.model_validate(
            {
                "agent_id": agent.id,
                "chat_id": chat.id,
                "goal": goal.strip(),
                "site_id": site_id,
                "max_steps": self._steps_for(agent),
            }
        )
        await self._store.put(run)
        async with self._working(agent.id):
            finished = await self._runner().run_task(agent, chat, run)
        await self._refresh_site_count(site_id)
        await self._after_memory_change([agent.id], wait=False)
        return finished, chat

    async def run_team_task(
        self, agents: Sequence[Agent], goal: str, *, site_id: str | None
    ) -> tuple[Chat, RoomOutcome]:
        """Open a room for a goal and let the agents work until they settle."""
        room = await self.create_room(
            title=goal.strip()[:48],
            member_ids=[agent.id for agent in agents],
            site_id=site_id,
        )
        outcome = await self.room_start_task(room.id, goal, background=False)
        await self._refresh_site_count(site_id)
        room = await self._store.require(Chat, room.id)
        return room, outcome or RoomOutcome(turns=0, speakers=())

    async def _refresh_site_count(self, site_id: str | None) -> None:
        if not site_id:
            return
        site = await self._store.get(SiteProject, site_id)
        if site is None:
            return
        files = await self._sites.files(site_id)
        if len(files) != site.file_count:
            await self._store.put(
                site.model_copy(
                    update={"file_count": len(files), "updated_at": now_ms()}
                )
            )

    # ------------------------------------------------------------------- web

    def web_status(self) -> JsonObject:
        """Say how agents reach the internet, without revealing any key."""
        reader = self._reader()
        return {
            **self._search().status(),
            "access": self.settings.studio_web_access,
            "online": self._connectivity.online,
            "reddit": "official API" if reader.reddit_app_ready else "public pages",
            "youtube": "YouTube API"
            if reader.youtube_search_ready
            else "YouTube search, no key",
            "sources": self.settings.studio_research_sources,
            "mix": {
                "web": self.settings.studio_research_web,
                "reddit": self.settings.studio_research_reddit,
                "youtube": self.settings.studio_research_youtube,
            },
        }

    async def test_search(self, query: str) -> JsonObject:
        """Run one search the way agents do, so the user can check the setup."""
        try:
            report = await self._search().search(query or "weather today", limit=5)
        except (SearchError, ValueError) as error:
            return {"ok": False, "error": str(error), **self.web_status()}
        return {
            "ok": True,
            **self.web_status(),
            "used": report.provider,
            "note": report.note,
            "results": [
                {"title": hit.title, "url": hit.url, "snippet": hit.snippet}
                for hit in report.hits
            ],
        }

    # ------------------------------------------------------------- main agent

    async def main_agent(self) -> Agent:
        """Return the main AI, creating the starter team on first use."""
        for agent in await self.agents():
            if agent.role == MAIN_ROLE and not agent.archived:
                return await self._follow_main_setting(agent)
        await self.ensure_defaults()
        for agent in await self.agents():
            if agent.role == MAIN_ROLE:
                if agent.archived:
                    agent = agent.model_copy(update={"archived": False})
                    await self._store.put(agent)
                return agent
        raise StudioError("The main AI is missing.")

    async def _follow_main_setting(self, agent: Agent) -> Agent:
        """A new Main AI Model setting moves the main AI to that model.

        The setting applies when it changes; a model picked for the main AI
        afterwards in Team brains stays until the setting changes again.
        """
        wanted = self.settings.studio_main_agent_model
        if not wanted or wanted == agent.model_setting:
            return agent
        agent = agent.model_copy(
            update={
                "model": wanted,
                "model_setting": wanted,
                "local_only": wanted.startswith(LOCAL_MODEL_PREFIX),
                "updated_at": now_ms(),
            }
        )
        await self._store.put(agent)
        return agent

    async def main_chat(self, *, fresh: bool = False) -> Chat:
        """Return the main AI's console conversation, opening one if needed."""
        agent = await self.main_agent()
        if not fresh:
            for chat in await self._store.find(
                Chat, where={"agent_id": agent.id}, order_by="updated_at DESC"
            ):
                if chat.settings.get(MAIN_CONSOLE_SETTING):
                    return chat
        return await self.create_chat(
            agent_id=agent.id,
            title=agent.name,
            settings={MAIN_CONSOLE_SETTING: True},
        )

    async def main_say(self, text: str, *, background: bool = True) -> Chat:
        """Talk to the main AI; it answers and may run the team meanwhile."""
        if not text.strip():
            raise StudioError("Say something first.")
        chat = await self.main_chat()
        self._main_busy += 1
        self._main_error = None
        if background:
            self.spawn(self._main_turn(chat.id, text))
        else:
            await self._main_turn(chat.id, text)
        return chat

    async def _main_turn(self, chat_id: str, text: str) -> None:
        try:
            result = await self.send(chat_id, text)
            if result.failed:
                self._main_error = result.error or "The main AI did not finish."
        except (StudioError, StudioNotFoundError) as error:
            self._main_error = str(error)
            await self._store.append_message(
                chat_id=chat_id,
                role="event",
                text=f"Could not answer: {error}",
                author="studio",
                data={"kind": "error"},
            )
        finally:
            self._main_busy = max(0, self._main_busy - 1)
            # Keep the console chat at the top so it is the one reopened.
            chat = await self._store.get(Chat, chat_id)
            if chat is not None:
                await self._store.put(chat.model_copy(update={"updated_at": now_ms()}))

    @contextlib.asynccontextmanager
    async def _working(self, agent_id: str) -> AsyncIterator[None]:
        """Mark an agent busy while one of its turns runs."""
        self._agent_busy[agent_id] = self._agent_busy.get(agent_id, 0) + 1
        try:
            yield
        finally:
            self._agent_busy[agent_id] -= 1
            if self._agent_busy[agent_id] <= 0:
                del self._agent_busy[agent_id]

    async def _busy_agents(self, runs: Sequence[AgentRun]) -> set[str]:
        """Agents with a running task, an active turn, or a room that is talking."""
        running = {run.agent_id for run in runs if run.status == "running"}
        running.update(self._agent_busy)
        for room_id, count in self._room_activity.items():
            if count > 0:
                room = await self._store.get(Chat, room_id)
                if room is not None:
                    running.update(room.member_ids)
        return running

    async def agent_activity(self, agent_id: str, *, after: int = 0) -> JsonObject:
        """What one agent is doing: its latest task and its newest steps."""
        agent = await self.agent(agent_id)
        busy = agent_id in await self._busy_agents(await self._active_runs())
        own_runs = list(await self.runs(agent_id=agent_id, limit=5))
        chats = await self._store.find(
            Chat, where={"agent_id": agent_id}, order_by="updated_at DESC", limit=1
        )
        chat = chats[0] if chats else None
        messages: Sequence[Message] = ()
        if chat is not None:
            messages = (
                await self._store.transcript(chat.id, after=after)
                if after
                else await self._store.transcript(chat.id, limit=40)
            )
        if chat is not None and chat.kind == "room":
            # A room holds the whole team; show only this agent's part in it.
            messages = [
                message
                for message in messages
                if message.role == "user" or message.author == agent.name
            ]
        run = own_runs[0] if own_runs else None
        return {
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "role": agent.role,
                "model": await self.effective_model(agent.model or self.default_model),
                "busy": busy,
            },
            "chat": {"id": chat.id, "title": chat.title} if chat else None,
            "live": self._live_text.get(chat.id, "") if chat else "",
            "run": {
                "id": run.id,
                "goal": run.goal,
                "status": run.status,
                "step": run.step,
                "updated_at": run.updated_at,
            }
            if run
            else None,
            "messages": [
                {
                    "sequence": message.sequence,
                    "role": message.role,
                    "author": message.author,
                    "text": message.text[:1500],
                    "tool": message.data.get("tool")
                    or (message.author if message.role == "tool" else None),
                    "failed": bool(message.data.get("failed")),
                    "partial": bool(message.data.get("partial")),
                    "at": message.created_at,
                }
                for message in messages
            ],
        }

    async def main_console(self, *, after: int = 0) -> JsonObject:
        """Return what the HUD shows: the conversation, the team, and systems."""
        await self._connectivity.check()
        await self._fire_due_reminders()
        self._warm_voice()
        agent = await self.main_agent()
        chat = await self.main_chat()
        messages = (
            await self._store.transcript(chat.id, after=after)
            if after
            else await self._store.transcript(chat.id, limit=80)
        )
        runs = await self.runs(limit=_RECENT_RUNS)
        running = await self._busy_agents(await self._active_runs())
        team = [
            {
                "id": member.id,
                "name": member.name,
                "role": member.role,
                "model": member.model,
                "using": using,
                "busy": member.id in running,
                "local": self.runs_on_this_pc(using),
                "private": await self.is_private_from(member),
            }
            for member in await self.agents()
            if member.id != agent.id and not member.archived
            for using in [
                await self.effective_model(member.model or self.default_model)
            ]
        ]
        # Only the newest few and a count: the team's memory can hold thousands.
        shared = await self._store.find(
            MemoryEntry,
            where={"agent_id": SHARED_MEMORY_ID},
            order_by="used_at DESC",
            limit=8,
        )
        shared_count = await self._store.count(
            MemoryEntry, where={"agent_id": SHARED_MEMORY_ID}
        )
        pending = await self._commands.pending()
        return {
            "agent": agent.model_dump(),
            "chat": chat.model_dump(),
            "messages": [message.model_dump() for message in messages],
            "thinking": self._main_busy > 0,
            "error": self._main_error,
            "team": team,
            "runs": [
                {
                    "id": run.id,
                    "agent_id": run.agent_id,
                    "chat_id": run.chat_id,
                    "goal": run.goal,
                    "status": run.status,
                    "step": run.step,
                    "updated_at": run.updated_at,
                }
                for run in runs[:6]
            ],
            "approvals": [request.model_dump() for request in pending],
            "memory": {
                "enabled": self.settings.studio_shared_memory,
                "count": shared_count,
                "recent": [entry.model_dump() for entry in shared],
            },
            "systems": {
                "main_model": await self.effective_model(
                    agent.model or self.default_model
                ),
                "local": await self._local_status(),
                "server_model": await self.effective_model(self.default_model),
                "commands": self.settings.studio_agent_commands,
                "web": self.web_status(),
                "voice": self.voice_status(),
            },
            "live": self._live_text.get(chat.id, ""),
            "learning": [
                {
                    "id": study.id,
                    "topic": study.topic,
                    "status": study.status,
                    "progress": study.progress,
                    "step": study.step,
                    "done": study.done,
                    "lessons": len(study.plan),
                    "understanding": study.understanding,
                }
                for study in await self._store.find(
                    Study, order_by="updated_at DESC", limit=2
                )
                if study.status in {"planning", "learning"}
                or now_ms() - study.updated_at < _RECENT_STUDY_MS
            ],
            "room": await self._room_snapshot(),
            **await self._dashboard_extras(
                runs,
                {str(member["id"]): str(member["name"]) for member in team},
                shared_count,
            ),
        }

    async def _dashboard_extras(
        self, runs: Sequence[AgentRun], names: Mapping[str, str], shared: int
    ) -> JsonObject:
        """Gauges, missions, and memory counts, rebuilt only when needed.

        The HUD polls quickly while agents work. The CPU and memory gauges
        refresh every few seconds; missions and memory counts are rebuilt only
        when a task, chat, or the shared memory has changed.
        """
        now = time.monotonic()
        newest = await self._store.find(Chat, order_by="updated_at DESC", limit=1)
        signature: JsonObject = {
            "shared": shared,
            "runs": [[run.id, run.status, run.updated_at] for run in runs[:8]],
            "chat": newest[0].updated_at if newest else 0,
        }
        cached = self._console_extras
        if cached is None or cached[1].get("signature") != signature:
            cached = (
                cached[0] if cached else 0.0,
                {
                    "signature": signature,
                    "timeline": await self._timeline(runs, names),
                    "insights": await self._insights(shared),
                    "monitor": cached[1].get("monitor") if cached else None,
                },
            )
        if cached[1].get("monitor") is None or now - cached[0] >= _DASHBOARD_SECONDS:
            monitor = await anyio.to_thread.run_sync(
                lambda: system_monitor.sample(self._models_dir)
            )
            cached = (now, {**cached[1], "monitor": monitor})
        self._console_extras = cached
        return {key: value for key, value in cached[1].items() if key != "signature"}

    async def _room_snapshot(self) -> JsonObject | None:
        """The most recent agent room, for the HUD's team chat panel."""
        rooms = await self._store.find(
            Chat, where={"kind": "room"}, order_by="updated_at DESC", limit=1
        )
        if not rooms:
            return None
        room = rooms[0]
        members = [
            agent.name for agent in await self.agents() if agent.id in room.member_ids
        ]
        messages = await self._store.transcript(room.id, limit=10)
        return {
            "id": room.id,
            "title": room.title,
            "members": members,
            "goal": str(room.settings.get("goal") or ""),
            "task_status": str(room.settings.get("task_status") or ""),
            "running": self._room_activity.get(room.id, 0) > 0,
            "messages": [
                {
                    "sequence": message.sequence,
                    "role": message.role,
                    "author": message.author,
                    "text": message.text[:400],
                }
                for message in messages
                if message.role in {"user", "assistant", "event"}
            ],
        }

    async def _timeline(
        self, runs: Sequence[AgentRun], names: Mapping[str, str]
    ) -> list[JsonObject]:
        """Recent missions across tasks, rooms, classes, and training."""
        items: list[JsonObject] = [
            {
                "kind": "task",
                "title": run.goal[:90],
                "who": names.get(run.agent_id, "Agent"),
                "status": run.status,
                "at": run.updated_at,
                "route": f"task/{run.id}",
            }
            for run in runs[:8]
        ]
        for room in await self._store.find(
            Chat, where={"kind": "room"}, order_by="updated_at DESC", limit=4
        ):
            goal = str(room.settings.get("goal") or "")
            if goal:
                items.append(
                    {
                        "kind": "room",
                        "title": goal[:90],
                        "who": room.title,
                        "status": str(room.settings.get("task_status") or "talking"),
                        "at": room.updated_at,
                        "route": f"room/{room.id}",
                    }
                )
        items.extend(
            {
                "kind": "class",
                "title": course.topic[:90],
                "who": "Classroom",
                "status": course.status,
                "at": course.updated_at,
                "route": f"class/{course.id}",
            }
            for course in await self._store.find(
                Course, order_by="updated_at DESC", limit=3
            )
        )
        items.extend(
            {
                "kind": "training",
                "title": f"LoRA: {job.base_model}"[:90],
                "who": "Training",
                "status": job.status,
                "at": job.updated_at,
                "route": f"lora/{job.id}",
            }
            for job in await self._store.find(
                LoraJob, order_by="updated_at DESC", limit=3
            )
        )
        items.sort(key=lambda item: int(str(item["at"])), reverse=True)
        return items[:8]

    async def _insights(self, shared: int) -> JsonObject:
        """Counts for the HUD's memory panel."""
        owners = await self._store.count(MemoryEntry, distinct="agent_id")
        return {
            "memories": await self._store.count(MemoryEntry),
            "shared": shared,
            "skills": await self._store.count(
                MemoryEntry, contains=("tags", json.dumps(SKILL_TAG))
            ),
            "agents": owners - (1 if shared else 0),
            "conversations": await self._store.count(Chat),
            "projects": await self._store.count(SiteProject),
        }

    async def _local_status(self) -> JsonObject:
        cached = self._local_probe
        now = time.monotonic()
        if cached is not None and now - cached[0] < _LOCAL_PROBE_SECONDS:
            return cached[1]
        status = await self.local_models()
        self._local_probe = (now, status)
        return status

    # ----------------------------------------------------------------- sites

    async def create_site(
        self, *, name: str, description: str = "", agent_id: str | None = None
    ) -> SiteProject:
        """Create a website workspace with a valid starter page."""
        if not name.strip():
            raise StudioError("A site needs a name.")
        site = SiteProject.model_validate(
            {
                "name": name.strip(),
                "slug": slugify(name),
                "description": description,
                "agent_id": agent_id,
            }
        )
        await self._sites.scaffold(site.id, site.name)
        files = await self._sites.files(site.id)
        site = site.model_copy(update={"file_count": len(files)})
        await self._store.put(site)
        return site

    async def sites(self) -> tuple[SiteProject, ...]:
        """Return every site workspace, newest first."""
        return await self._store.find(SiteProject, order_by="created_at DESC")

    async def site(self, site_id: str) -> SiteProject:
        """Return one site workspace."""
        return await self._store.require(SiteProject, site_id)

    async def site_files(self, site_id: str) -> tuple[JsonObject, ...]:
        """Return the files in one site as JSON-ready rows."""
        await self._store.require(SiteProject, site_id)
        return tuple(
            {"path": item.path, "size": item.size, "content_type": item.content_type}
            for item in await self._sites.files(site_id)
        )

    async def write_site_file(
        self, site_id: str, path: str, content: str
    ) -> JsonObject:
        """Write one file into a site from the UI."""
        site = await self._store.require(SiteProject, site_id)
        written = await self._sites.write(site_id, path, content)
        files = await self._sites.files(site_id)
        await self._store.put(
            site.model_copy(update={"file_count": len(files), "updated_at": now_ms()})
        )
        return {"path": written.path, "size": written.size}

    async def delete_site(self, site_id: str) -> bool:
        """Delete a site workspace and its files."""
        await self._sites.remove(site_id)
        return await self._store.delete(SiteProject, site_id)

    # ---------------------------------------------------------------- models

    def catalog(self) -> tuple[JsonObject, ...]:
        """Return the curated small models offered for download."""
        return tuple(
            {
                "id": entry.id,
                "name": entry.name,
                "url": entry.url,
                "parameters": entry.parameters,
                "quantization": entry.quantization,
                "approx_bytes": entry.approx_bytes,
                "note": entry.note,
                "guide": entry.guide,
            }
            for entry in CURATED_MODELS
        )

    async def download_model(
        self, *, catalog_id: str = "", url: str = "", name: str = "", sha256: str = ""
    ) -> ModelAsset:
        """Queue one model download and start it in the background."""
        if catalog_id:
            asset = await self._library.queue_catalog(catalog_id)
        elif url:
            asset = await self._library.queue(url=url, name=name, sha256=sha256 or None)
        else:
            raise StudioError("Choose a catalog model or give a download URL.")
        if asset.status != "ready":
            self.spawn(self._library.download(asset.id))
        return asset

    async def local_models(self) -> JsonObject:
        """Report which models the local runtime is serving right now."""
        base_url = self.settings.studio_local_base_url
        try:
            served = await self._router.local_models()
        except StudioLLMError as error:
            return {
                "base_url": base_url,
                "reachable": False,
                "models": [],
                "error": str(error),
            }
        return {
            "base_url": base_url,
            "reachable": True,
            "models": [f"{LOCAL_MODEL_PREFIX}{model}" for model in served],
            "error": None,
        }

    async def pick_model_file(self) -> JsonObject:
        """Let the user choose a model file on this PC and add it to LM Studio."""
        try:
            path = await pick_model_file()
        except ModelFileError as error:
            raise StudioError(str(error)) from error
        if path is None:
            return {"picked": False}
        return await self.add_model_file(path)

    async def add_model_file(self, path: Path) -> JsonObject:
        """Put a .gguf file where LM Studio loads it, and name it for Studio."""
        models_dir = self._lora.lmstudio_dir()
        if models_dir is None:
            raise StudioError(
                "Could not find LM Studio's models folder. Open LM Studio once, "
                "or set LM Studio Models Folder in admin settings under Studio."
            )
        try:
            placed = await anyio.to_thread.run_sync(
                lambda: place_in_lmstudio(check_model_file(path), models_dir)
            )
        except (ModelFileError, OSError) as error:
            raise StudioError(str(error)) from error
        self._local_probe = None
        self._loaded_probe = None
        status = await self._local_status()
        listed = status.get("models")
        names = [
            str(name).removeprefix(LOCAL_MODEL_PREFIX)
            for name in (listed if isinstance(listed, list) else [])
        ]
        found = match_listed_model(placed, names)
        return {
            "picked": True,
            "path": str(placed),
            "model": f"{LOCAL_MODEL_PREFIX}{found}" if found else None,
            "note": ""
            if found
            else (
                "Added to LM Studio. If it is not in the list yet, make sure "
                "LM Studio's server is running, then press Refresh."
            ),
        }

    async def choose_model(self, model: str, *, everyone: bool) -> int:
        """Switch the main AI, or every agent, to one model. Returns how many."""
        if not model.strip():
            raise StudioError("Pick a model first.")
        changed = 0
        for agent in await self.agents():
            if agent.archived or agent.model == model:
                continue
            if not everyone and agent.role != MAIN_ROLE:
                continue
            await self._store.put(
                agent.model_copy(
                    update={
                        "model": model,
                        "local_only": model.startswith(LOCAL_MODEL_PREFIX),
                        "updated_at": now_ms(),
                    }
                )
            )
            changed += 1
        return changed

    async def assets(self) -> tuple[ModelAsset, ...]:
        """Return every tracked model download."""
        return await self._library.assets()

    async def ensure_guide_model(self) -> ModelAsset | None:
        """Download the preloaded guide model when it is missing."""
        settings = self.settings
        if not settings.studio_guide_model.startswith("local/"):
            return None
        ready = await self._library.ready_models()
        if ready:
            return None
        return await self.download_model(catalog_id=settings.studio_guide_catalog_id)

    # ---------------------------------------------------------------- tuning

    async def packs(self, *, agent_id: str | None = None) -> tuple[TunePack, ...]:
        """Return tune packs, newest first."""
        where = {"agent_id": agent_id} if agent_id else None
        return await self._store.find(TunePack, where=where, order_by="created_at DESC")

    async def create_pack(
        self,
        agent_id: str,
        *,
        name: str = "",
        teacher_model: str | None = None,
        opted_in: bool = False,
    ) -> TunePack:
        """Create one tune pack; a teacher model may coach a local student."""
        agent = await self._store.require(Agent, agent_id)
        return await self._tuner().create_pack(
            agent,
            name=name,
            backend=self.settings.studio_tuning_backend,
            teacher_model=teacher_model,
            opted_in=opted_in,
        )

    async def add_samples(
        self, pack_id: str, pairs: Sequence[tuple[str, str]], *, split: str = "train"
    ) -> int:
        """Add prompt/answer examples to a pack."""
        return await self._tuner().add_samples(pack_id, pairs, split=split)

    async def samples(self, pack_id: str) -> tuple[TuneSample, ...]:
        """Return the examples attached to a pack."""
        return await self._store.find(TuneSample, where={"pack_id": pack_id})

    async def start_tuning(
        self,
        pack_id: str,
        *,
        backend: str | None = None,
        background: bool = True,
    ) -> TuneJob:
        """Queue a tuning run on the server trainer or locally, per request."""
        settings = self.settings
        pack = await self._store.require(TunePack, pack_id)
        chosen = backend or pack.backend
        if chosen not in {"local_light", "cloud"}:
            raise StudioError("Choose local or server tuning.")
        if chosen == "local_light" and not (
            settings.studio_light_tuning_enabled or pack.opted_in
        ):
            raise StudioError(
                "Light tuning is off. Turn it on in Studio settings, or in this "
                "agent's chat settings."
            )
        if chosen == "cloud" and not settings.studio_cloud_tuning_base_url:
            raise StudioError(
                "Server tuning needs a trainer. Set Cloud Trainer URL and Key in "
                "Studio settings."
            )
        if chosen == "cloud" and pack.base_model.startswith(LOCAL_MODEL_PREFIX):
            raise StudioError(
                "Server tuning trains server models, and this agent runs a local "
                "model. Use local tuning, or give the agent a server model first."
            )
        if chosen != pack.backend:
            await self._store.put(
                pack.model_copy(update={"backend": chosen, "updated_at": now_ms()})
            )
        tuner = self._tuner()
        try:
            job = await tuner.start(pack_id)
        except TuningError as error:
            raise StudioError(str(error)) from error
        if background:
            self.spawn(tuner.run(job.id))
        return job

    async def refresh_job(self, job_id: str) -> TuneJob:
        """Check a server tuning run again, e.g. after a restart."""
        return await self._tuner().refresh(job_id)

    def tuning_options(self) -> JsonObject:
        """Say which tuning backends can run right now and why not."""
        settings = self.settings
        return {
            "local": {
                "enabled": settings.studio_light_tuning_enabled,
                "rounds": settings.studio_tuning_rounds,
                "note": "Instruction-pack search. Runs anywhere, including for local models.",
            },
            "server": {
                "enabled": bool(settings.studio_cloud_tuning_base_url),
                "provider": settings.studio_cloud_tuning_provider or "",
                "note": "Weight training on an OpenAI-compatible fine-tuning API.",
            },
            "default": settings.studio_tuning_backend,
        }

    async def run_tuning(self, job_id: str) -> TuneJob:
        """Run one queued tuning job to completion and return its final state."""
        return await self._tuner().run(job_id)

    async def jobs(self, *, agent_id: str | None = None) -> tuple[TuneJob, ...]:
        """Return tuning jobs, newest first."""
        where = {"agent_id": agent_id} if agent_id else None
        return await self._store.find(TuneJob, where=where, order_by="created_at DESC")

    async def job(self, job_id: str) -> TuneJob:
        """Return one tuning job."""
        return await self._store.require(TuneJob, job_id)

    async def cancel_job(self, job_id: str) -> TuneJob:
        """Ask a running tuning job to stop at its next checkpoint."""
        job = await self._store.require(TuneJob, job_id)
        cancelled = job.model_copy(
            update={
                "status": "cancelled",
                "message": "Cancelled",
                "updated_at": now_ms(),
            }
        )
        await self._store.put(cancelled)
        return cancelled

    # ---------------------------------------------------------------- school

    async def open_class(
        self,
        *,
        topic: str,
        lesson_count: int = 3,
        start: bool = False,
        teacher_id: str | None = None,
        student_id: str | None = None,
    ) -> Course:
        """Open a class; any agent can teach and any other agent can learn."""
        await self.ensure_defaults()
        teacher = (
            await self._store.require(Agent, teacher_id)
            if teacher_id
            else await self.agent_by_name(TEACHER_AGENT_NAME)
        )
        student = (
            await self._store.require(Agent, student_id)
            if student_id
            else await self.agent_by_name(STUDENT_AGENT_NAME)
        )
        if teacher is None or student is None:
            raise StudioError("The teacher and student agents are missing.")
        if teacher.id == student.id:
            raise StudioError("Pick two different agents to teach and to learn.")
        course = await self._school().open_course(
            topic=topic,
            teacher=teacher,
            student=student,
            lesson_count=lesson_count,
            pass_mark=self.settings.studio_class_pass_mark,
        )
        if start:
            self.spawn(self.run_class(course.id))
        return course

    async def run_class(self, course_id: str) -> Course:
        """Teach and test one class, tuning the student when it passes."""
        course = await self._school().run_course(
            course_id, tune_on_pass=self.settings.studio_light_tuning_enabled
        )
        await self._after_memory_change(
            [course.teacher_agent_id, course.student_agent_id]
        )
        return course

    def start_class(self, course_id: str) -> None:
        """Run a class in the background so the UI can watch it live."""
        self.spawn(self.run_class(course_id))

    async def courses(self) -> tuple[Course, ...]:
        """Return every class, newest first."""
        return await self._store.find(Course, order_by="created_at DESC")

    async def course_detail(self, course_id: str) -> JsonObject:
        """Return one class with its lessons, test, and transcript."""
        course = await self._store.require(Course, course_id)
        lessons = await self._store.find(
            Lesson, where={"course_id": course_id}, order_by="ordinal ASC"
        )
        questions = await self._store.find(
            ExamQuestion, where={"course_id": course_id}, order_by="ordinal ASC"
        )
        transcript = await self._store.transcript(course.chat_id)
        return {
            "course": course.model_dump(),
            "progress": course.progress,
            "lessons": [lesson.model_dump() for lesson in lessons],
            "questions": [question.model_dump() for question in questions],
            "messages": [message.model_dump() for message in transcript],
        }

    # ---------------------------------------------------------------- memory

    async def memories(
        self, agent_id: str, *, scope: str | None = None
    ) -> tuple[MemoryEntry, ...]:
        """Return one agent's memories."""
        return await self._memory().entries(agent_id, scope=scope)

    async def remember(
        self, agent_id: str, text: str, *, scope: str = "long_term"
    ) -> MemoryEntry | None:
        """Write one memory by hand; ``shared`` writes to the team memory."""
        if agent_id == SHARED_MEMORY_ID:
            scope = "long_term"
        else:
            await self._store.require(Agent, agent_id)
        entry = await self._memory().remember(
            agent_id,
            text,
            scope=scope,
            source="user",
            author="you" if agent_id == SHARED_MEMORY_ID else "",
        )
        await self._after_memory_change([agent_id])
        return entry

    async def teach_agent(
        self, agent_id: str, *, text: str = "", url: str = ""
    ) -> MemoryEntry:
        """Turn a link or notes into a skill the agent keeps in every prompt."""
        agent = await self._store.require(Agent, agent_id)
        notes = text.strip()
        link = url.strip()
        material = ""
        if link:
            material = await self._read_for_teaching(link)
        if not notes and not material:
            raise StudioError("Give a link or write what to teach.")
        prompt = "\n\n".join(
            part
            for part in (
                f"Material from {link}:\n{material}" if material else "",
                f"The user's notes:\n{notes}" if notes else "",
            )
            if part
        )
        try:
            reply = await self._router.complete(
                [ChatMessage.user(prompt)],
                model=agent.model or self.default_model,
                system=TEACH_PROMPT,
                max_tokens=700,
            )
            skill = reply.text.strip()
        except StudioLLMError as error:
            logger.warning("Studio could not condense a skill: {}", error)
            skill = ""
        if not skill:
            skill = (notes or material)[:1_200]
        if link:
            skill = f"{skill}\nSource: {link}"
        entry = await self._memory().remember(
            agent.id,
            skill,
            tags=(SKILL_TAG,),
            source=link or "taught",
            author="you",
        )
        if entry is None:
            raise StudioError("There was nothing to teach.")
        await self._after_memory_change([agent.id])
        return entry

    async def skills(self, agent_id: str) -> tuple[MemoryEntry, ...]:
        """Return what the user taught one agent."""
        await self._store.require(Agent, agent_id)
        return await self._memory().skills(agent_id, limit=50)

    async def _read_for_teaching(self, url: str) -> str:
        try:
            if platform_of(url) != "web":
                page = await self._reader().read(url)
                return page.text[:TEACH_MATERIAL_CHARS]
            fetched = await self._web_tools.fetch(url, egress=self._egress())
            return fetched.data[:TEACH_MATERIAL_CHARS]
        except (PlatformError, httpx.HTTPError, OSError, ValueError) as error:
            raise StudioError(f"Could not read that link: {error}") from error

    async def forget(self, memory_id: str) -> bool:
        """Delete one memory."""
        return await self._memory().forget(memory_id)

    async def promote_memory(self, memory_id: str) -> MemoryEntry:
        """Move a working note into long-term memory."""
        return await self._memory().promote(memory_id)

    async def clear_memory(self, agent_id: str, *, scope: str | None = None) -> int:
        """Delete an agent's memories."""
        return await self._memory().clear(agent_id, scope=scope)

    # -------------------------------------------------------------- obsidian

    async def vault_status(self) -> VaultStatus:
        """Describe the configured Obsidian vault."""
        return await self._vault().status()

    async def sync_chat(self, chat_id: str) -> str:
        """Write one chat into the vault and return the note path."""
        chat = await self._store.require(Chat, chat_id)
        messages = await self._store.transcript(chat_id)
        agent = await self._store.get(Agent, chat.agent_id) if chat.agent_id else None
        path = await self._vault().export_chat(chat, messages, agent=agent)
        return str(path)

    async def _safe_sync_chat(self, chat_id: str) -> None:
        try:
            await self.sync_chat(chat_id)
        except (OSError, RuntimeError) as error:
            logger.warning("Studio Obsidian sync failed: {}", error)

    async def sync_course(self, course_id: str) -> str:
        """Write one class into the vault and return the note path."""
        course = await self._store.require(Course, course_id)
        lessons = await self._store.find(
            Lesson, where={"course_id": course_id}, order_by="ordinal ASC"
        )
        questions = await self._store.find(
            ExamQuestion, where={"course_id": course_id}, order_by="ordinal ASC"
        )
        teacher = await self._store.get(Agent, course.teacher_agent_id)
        student = await self._store.get(Agent, course.student_agent_id)
        path = await self._vault().export_course(
            course,
            lessons=lessons,
            questions=questions,
            teacher=teacher,
            student=student,
        )
        return str(path)

    async def sync_memory(self, agent_id: str) -> str:
        """Write one agent's memory into the vault and return the note path."""
        agent = (
            _shared_memory_owner()
            if agent_id == SHARED_MEMORY_ID
            else await self._store.require(Agent, agent_id)
        )
        entries = await self._memory().entries(agent_id)
        path = await self._vault().export_memory(agent, entries)
        return str(path)

    async def pull_memory_edits(self) -> int:
        """Apply edits the user made to memory notes in Obsidian."""
        current = {entry.id: entry for entry in await self._store.find(MemoryEntry)}
        edits = await self._vault().memory_edits(current)
        for edit in edits:
            entry = current[edit.memory_id]
            await self._store.put(
                entry.model_copy(
                    update={"text": edit.text, "scope": edit.scope, "used_at": now_ms()}
                )
            )
        return len(edits)

    async def sync_memory_structure(self) -> JsonObject:
        """Pull Obsidian edits first, then mirror every agent's memory."""
        async with self._memory_sync_lock:
            return await self._sync_memory_structure()

    async def _sync_memory_structure(self) -> JsonObject:
        pulled = await self.pull_memory_edits()
        agents = list(await self.agents())
        entries: dict[str, list[MemoryEntry]] = {agent.id: [] for agent in agents}
        for entry in await self._store.find(MemoryEntry, order_by="created_at ASC"):
            entries.setdefault(entry.agent_id, []).append(entry)
        if entries.get(SHARED_MEMORY_ID):
            agents.insert(0, _shared_memory_owner())
        result = await self._vault().mirror_memory(agents, entries)
        return {
            "pulled": pulled,
            "written": result.notes_written,
            "removed": result.notes_removed,
            "agents": result.agents,
        }

    async def import_vault_notes(self, agent_id: str) -> int:
        """Read the vault Inbox into one agent's (or the team's) memory."""
        agent = (
            _shared_memory_owner()
            if agent_id == SHARED_MEMORY_ID
            else await self._store.require(Agent, agent_id)
        )
        notes = await self._vault().import_notes()
        memory = self._memory()
        stored = 0
        for note in notes:
            for line in note.splitlines():
                text = line.strip("-# ").strip()
                if len(text) >= 12 and not text.startswith("---"):
                    entry = await memory.remember(
                        agent.id, text, source="obsidian", tags=("obsidian",)
                    )
                    stored += 1 if entry is not None else 0
        return stored

    # ----------------------------------------------------------------- guide

    async def guide_state(self) -> GuideState:
        """Describe this install, live, for the guide and its problem check.

        The guide answers with its own small model when that is downloaded or
        served; otherwise it borrows the model LM Studio has loaded, the same
        stand-in the other agents use, so it is never stuck on built-in help
        while a model is running on this PC.
        """
        settings = self.settings
        ready = await self._library.ready_models()
        local = await self._local_status()
        listed = local.get("models")
        served = tuple(
            str(name) for name in (listed if isinstance(listed, list) else [])
        )
        guide_model = await self.effective_model(settings.studio_guide_model)
        guide_ready = (
            guide_model in served
            or (guide_model == settings.studio_guide_model and bool(ready))
            if guide_model.startswith(LOCAL_MODEL_PREFIX)
            else self._server_model_ready(guide_model)
        )
        agents = [agent for agent in await self.agents() if not agent.archived]
        main = next((agent for agent in agents if agent.role == MAIN_ROLE), None)
        main_model = await self.effective_model(
            (main.model if main else "") or self.default_model
        )
        busy = await self._busy_agents(await self._active_runs())
        web = self.web_status()
        voice = self.voice_status()
        online = web.get("online")
        state = GuideState(
            agent_count=len(agents),
            site_count=len(await self.sites()),
            ready_models=len(ready),
            guide_model=guide_model,
            guide_model_ready=guide_ready,
            tuning_enabled=settings.studio_light_tuning_enabled,
            teacher_enabled=settings.studio_teacher_enabled,
            vault_configured=bool(settings.studio_obsidian_vault),
            main_name=main.name if main else settings.studio_main_agent_name,
            main_model=main_model,
            main_model_ready=main_model.startswith(LOCAL_MODEL_PREFIX)
            or self._server_model_ready(main_model),
            local_url=str(local.get("base_url") or settings.studio_local_base_url),
            local_reachable=bool(local.get("reachable")),
            local_models=served,
            web_online=online if isinstance(online, bool) else None,
            web_access=str(web.get("access") or ""),
            search_provider=str(web.get("label") or web.get("provider") or ""),
            search_problem=str(web.get("problem") or ""),
            voice_speak=str(voice.get("speak") or ""),
            voice_ready=bool(voice.get("speak_ready")),
            commands=settings.studio_agent_commands,
            approvals=len(await self._commands.pending()),
            busy_agents=tuple(agent.name for agent in agents if agent.id in busy),
            agents=tuple(agent.name for agent in agents),
            last_error=self._main_error or "",
        )
        return replace(state, problems=diagnose(state))

    async def ask_guide(
        self, question: str, history: Sequence[ChatMessage] = ()
    ) -> GuideAnswer:
        """Answer one question about the app, knowing this install's state."""
        state = await self.guide_state()
        return await self._guide(state.guide_model).answer(
            question, state, history=history
        )

    async def app_help(self, question: str) -> str:
        """The guide's notes on a question, for Jarvis's app_help tool.

        No model call: the matching notes, where to tap, and anything wrong
        right now, so Jarvis answers app questions with the real button names.
        """
        state = await self.guide_state()
        answer = offline_answer(question, state)
        lines = [answer.text]
        if state.problems and not answer.text.startswith("Right now:"):
            lines.append(
                "Right now: "
                + " ".join(f"{p.title}: {p.fix}" for p in state.problems[:3])
            )
        if answer.links:
            lines.append(
                "Pages: " + ", ".join(link.label for link in answer.links) + "."
            )
        return "\n\n".join(lines)

    async def guide_overview(self) -> JsonObject:
        """What the guide sheet opens with: problems, starters, and every topic."""
        state = await self.guide_state()
        return {
            "problems": [
                {
                    "title": problem.title,
                    "fix": problem.fix,
                    "route": problem.route,
                    "page": page_name(problem.route) if problem.route else "",
                }
                for problem in state.problems
            ],
            "starters": list(STARTER_QUESTIONS),
            "topics": [
                {
                    "title": topic.title,
                    "where": topic.where,
                    "route": topic.route,
                    "page": page_name(topic.route) if topic.route else "",
                }
                for topic in GUIDE_TOPICS
            ],
            "model": state.guide_model,
            "offline": not state.guide_model_ready
            and state.guide_model.startswith(LOCAL_MODEL_PREFIX),
        }

    # -------------------------------------------------------------- overview

    async def overview(self) -> JsonObject:
        """Return the home screen payload for the app."""
        settings = self.settings
        agents = await self.agents()
        chats = await self.chats()
        jobs = await self.jobs()
        courses = await self.courses()
        assets = await self.assets()
        return {
            "agents": [agent.model_dump() for agent in agents],
            "chats": [chat.model_dump() for chat in chats[:20]],
            "sites": [site.model_dump() for site in await self.sites()],
            "runs": [run.model_dump() for run in await self.runs(limit=10)],
            "jobs": [
                {**job.model_dump(), "progress": job.progress} for job in jobs[:10]
            ],
            "courses": [
                {**course.model_dump(), "progress": course.progress}
                for course in courses[:10]
            ],
            "assets": [
                {**asset.model_dump(), "progress": asset.progress}
                for asset in assets[:20]
            ],
            "settings": {
                "default_model": self.default_model,
                "guide_model": settings.studio_guide_model,
                "local_base_url": settings.studio_local_base_url,
                "light_tuning_enabled": settings.studio_light_tuning_enabled,
                "tuning_backend": settings.studio_tuning_backend,
                "teacher_enabled": settings.studio_teacher_enabled,
                "obsidian_configured": bool(settings.studio_obsidian_vault),
                "class_pass_mark": settings.studio_class_pass_mark,
                "shared_memory": settings.studio_shared_memory,
                "main_agent_name": settings.studio_main_agent_name,
                "web": self.web_status(),
            },
        }
