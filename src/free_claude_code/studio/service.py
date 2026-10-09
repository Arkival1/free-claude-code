"""The Studio facade: one object the HTTP layer and tests both drive."""

import asyncio
import contextlib
import json
import re
import secrets
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
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
from free_claude_code.core.version import package_version

from . import system_monitor
from .agents import SEALED_TOOLS, AgentRunner, TurnResult
from .assistant_tools import describe_time, now_line, parse_when
from .claw import ClawCode, ClawError
from .code_loop import code_and_test, project_name
from .commands import CommandBroker, CommandError
from .connectivity import Connectivity
from .convo_notes import NotesKeeper
from .crew import Crew
from .desk import (
    INSTALL_HINT,
    DeskBrowser,
    DeskError,
    Opener,
    desk_package_ready,
    playwright_opener,
)
from .downloads import CURATED_MODELS, ModelLibrary
from .engine import ENGINE_ARCHIVE, Engine, EngineError, not_a_model
from .extensions import (
    UPLOAD_OWNER,
    Extension,
    ExtensionError,
    ExtensionLibrary,
    McpServer,
    Skill,
)
from .farm.cartoon.aiart import ArtError
from .farm.farm import ContentFarm, FarmError, channel_view, whole
from .farm.formats import style_of
from .farm.render import video_tools
from .farm.requests import FarmJob, farm_job
from .farm.visuals import Visuals
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
from .hq import station_for, stations_view
from .image_cloud import CloudSettings, ImageCloudError, make_picture
from .image_engine import ImageEngine, ImageEngineError, Picture
from .lab import text as lab_text
from .lab.bench import LabBench
from .lab.requests import lab_job
from .lab.sim import LabError
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
    model_missing,
    short_arguments,
)
from .local_voice import (
    VOICE_CHOICES,
    LocalVoice,
    LocalVoiceError,
    SetupState,
    listen_package_ready,
    speech_package_ready,
)
from .lora import LoraTrainer
from .mcp import McpError, McpManager, McpTool, ServerSpec
from .memory import (
    SERVER_AREA_PREFIX,
    SHARED_MEMORY_ID,
    SKILL_TAG,
    MemoryService,
    keywords,
    server_area,
)
from .model_files import (
    ModelFileError,
    check_model_file,
    match_listed_model,
    pick_model_file,
    place_in_lmstudio,
)
from .model_inspect import identify
from .models import (
    AGENT_ROLES,
    Agent,
    AgentRun,
    Chat,
    ChatNotes,
    CommandRequest,
    Course,
    ExamQuestion,
    FarmChannel,
    FarmPost,
    Lesson,
    LoraJob,
    MemoryEntry,
    Message,
    ModelAsset,
    PhoneLink,
    Photo,
    SiteProject,
    StudioFlag,
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
from .orders import (
    Order,
    build_request,
    called_agent,
    code_request,
    is_job,
    is_yes,
    offered_orders,
    parse_orders,
    pick_agent,
    route_prompt,
    routed_agent,
    web_request,
    worth_routing,
)
from .phone_link import (
    MAX_MEMORY_CHARS,
    MAX_PULL,
    MAX_REPLY_TOKENS,
    PAIR_SECONDS,
    PHONE_TAG,
    PhoneLinkError,
    PhoneLinks,
    chat_messages,
    incoming_memories,
    link_view,
    reply_json,
    tailscale_address,
    tool_specs,
)
from .photos import PhotoError, PhotoLibrary
from .platforms import (
    PlatformError,
    PlatformPage,
    PlatformReader,
    platform_of,
    youtube_id,
)
from .playbook import (
    PLAYBOOK_FOLDER,
    Playbook,
    PlaybookError,
    PlaybookNote,
    own_tool,
    starter_notes,
)
from .presets import (
    BUILDER_PROMPT,
    CODER_PROMPT,
    CODER_TOOLS,
    FARM_AGENT_PROMPT,
    FARM_AGENT_TOOLS,
    HELPER_PROMPT,
    HELPER_TOOLS,
    LAB_AGENT_PROMPT,
    LAB_AGENT_TOOLS,
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
from .search import SearchBudget, SearchError, StudioSearch
from .sites import SiteWorkspace, slugify
from .starter import StarterRepo, bundled_bytes, load_starters
from .store import StudioNotFoundError, StudioStore
from .team_models import (
    find_agent_name,
    match_model,
    model_label,
    parse_model_request,
    suggest_mix,
)
from .tools import (
    ALL_TOOL_NAMES,
    DEFAULT_TOOL_NAMES,
    MAIN_ONLY_TOOLS,
    MAIN_ROLE,
    MAIN_TOOL_NAMES,
    TOOL_SPEC_BY_NAME,
    TOOLSHED_TOOL,
    AgentToolbox,
    ToolContext,
    ToolOutcome,
    tool_tokens,
)
from .tuning import CloudTuner, LightTuner, TuningError
from .vault import RepoVault
from .video_ears import Fetch, Hear, VideoEars, VideoEarsError, ytdlp_fetch
from .videos import VIDEO_TAGS, VideoError, VideoStudy, memory_line
from .voice import SpeechAudio, VoiceError, VoiceService, speakable
from .weather import WeatherError, forecast, weather_request

GUIDE_AGENT_NAME = "Guide"
BUILDER_AGENT_NAME = "Builder"
TEACHER_AGENT_NAME = "Teacher"
STUDENT_AGENT_NAME = "Student"
RESEARCHER_AGENT_NAME = "Researcher"
HELPER_AGENT_NAME = "Helper"
TESTER_AGENT_NAME = "Tester"
CODER_AGENT_NAME = "Coder"
LAB_AGENT_NAME = "Lab"
FARM_AGENT_NAME = "Farm"
_DEFAULT_UPGRADES: dict[str, tuple[str, ...]] = {
    BUILDER_AGENT_NAME: (
        "skill",
        "mcp",
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
        "find_images",
        "save_image",
        "list_photos",
        "use_photo",
    ),
    RESEARCHER_AGENT_NAME: RESEARCHER_TOOLS,
    HELPER_AGENT_NAME: HELPER_TOOLS,
    TESTER_AGENT_NAME: TESTER_TOOLS,
    CODER_AGENT_NAME: CODER_TOOLS,
    LAB_AGENT_NAME: LAB_AGENT_TOOLS,
    FARM_AGENT_NAME: FARM_AGENT_TOOLS,
}
_DEFAULT_ROLES = {
    BUILDER_AGENT_NAME: "builder",
    RESEARCHER_AGENT_NAME: "researcher",
    HELPER_AGENT_NAME: "helper",
    TESTER_AGENT_NAME: "tester",
    CODER_AGENT_NAME: "coder",
    LAB_AGENT_NAME: "lab",
    FARM_AGENT_NAME: "farm",
}
SHARED_MEMORY_NAME = "Team memory"
TEAM_LAYOUT_FLAG = "team_layout_v1"
AGENT_RESCAN_FLAG = "extension_agents_v2"
OWN_MEMORY_FLAG = "extension_agent_memory_v1"
"""Repo agents added in 6.61.1 were given remember and recall."""
OWN_MEMORY_TOOLS = ("remember", "recall")
"""A repo agent's own memory (its own area while it thinks on a server)."""
TOOLSHED_FLAG = "extension_agent_toolshed_v1"
"""Repo agents already on the team were given the toolshed."""
REPO_AGENT_EXTRAS = (*OWN_MEMORY_TOOLS, TOOLSHED_TOOL)
"""What every repo agent gets beyond the tools it asks for."""
"""Added repos had their agents read again with the front-matter rule."""
LOCAL_TEAM_ROLES = frozenset({MAIN_ROLE, "guide", "helper", "lab", "farm"})
"""Roles that think on this PC; every other agent thinks on a server."""
CLASS_ROLES = frozenset({"teacher", "student"})
"""Classes keep their own choice: a server teacher and a local student."""
MAIN_CONSOLE_SETTING = "console"
LAB_CHAT_SETTING = "lab"
FARM_CHAT_SETTING = "farm"
FARM_PILOT_SECONDS = 600.0
"""How often autopilot checks whether a channel needs another video."""
ENGINE_RETRY_SECONDS = 300.0
"""After the engine fails to start, LM Studio answers this long before a retry."""


_CLAUDE_TOOLS = {
    "read": ("read_file",),
    "write": ("write_file",),
    "edit": ("edit_file",),
    "multiedit": ("edit_file",),
    "bash": ("run_command",),
    "grep": ("search_files",),
    "glob": ("list_files",),
    "ls": ("list_files",),
    "webfetch": ("web_fetch",),
    "websearch": ("web_search",),
    "todowrite": ("update_plan",),
}


def _studio_tools(claude_tools: Sequence[str]) -> tuple[str, ...]:
    """Claude Code's tool names (Read, Bash, ...) as Studio's, plus skills
    and MCP; an agent naming none gets the usual set."""
    if not claude_tools:
        return tuple(dict.fromkeys((*_default_tools(), "skill", "mcp")))
    mapped = [
        tool
        for name in claude_tools
        for tool in _CLAUDE_TOOLS.get(name.strip().lower().split("(")[0], ())
    ]
    return tuple(dict.fromkeys(("read_file", "list_files", *mapped, "skill", "mcp")))


def _job_line(goal: str) -> str:
    """A job's first line, as the room shows it: the long how-to after it
    (the Coder's and Tester's instructions) stays in the job itself."""
    job = goal.split("\n\nBriefing from ")[0].removeprefix("The job: ").strip()
    return " ".join(job.split("\n", 1)[0].split())


def _plain_error(run: AgentRun) -> str:
    """Why a job stopped, in words rather than an error code."""
    error = (run.error or run.status).strip()
    if error == "step_limit":
        return (
            f"Ran out of steps ({run.step}) before finishing. What it made so far "
            "is saved; ask again to carry on, or with a narrower goal."
        )
    return error


def _file_rank(path: str) -> tuple[int, str]:
    """The page first, then other pages, styles, scripts, and the rest."""
    if path == "index.html":
        return (0, path)
    order = {".html": 1, ".css": 2, ".js": 3}
    return (order.get(Path(path).suffix, 4), path)


FOLLOW_UP_PROMPT = (
    "(Studio) {agent} {status} the job you gave it: {job}\n"
    "Its report:\n{result}\n\n"
    "Tell the user in a few sentences what it found or made and what that means "
    "for them, in your own words, with the links that matter. Then suggest the "
    "next step, if there is one; the user decides."
)
FOLLOW_UP_REPORT_CHARS = 6_000
"""How much of a teammate's report the main AI reads when it follows up."""
LAB_NOTE_CHARS = 3_000
"""How much of a Lab result the main AI reads before describing it."""
ROOM_POST_CHARS = 1_500
"""How much of a result an agent posts in the team room."""
ROOM_NOTE_CHARS = 400
"""How much of each room message an agent starting a job reads."""
ROOM_NEEDED = 8192
"""Tokens of context an agent needs: instructions, tools, the talk so far,
and room to answer."""
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


def farm_style_label(style: str) -> str:
    return style_of(style).label.lower()


_SHOW_LEAD = re.compile(
    r"^(?:the\s+)?(?:entire\s+|full\s+|whole\s+|complete\s+)?(?:lore|story|history|"
    r"timeline|theories|theory)\s+(?:of|about|behind)\s+|^everything\s+about\s+",
    re.I,
)


def show_of(topic: str) -> str:
    """'the entire lore of Breaking Bad' → 'Breaking Bad'; a what-if names none."""
    text = topic.strip()
    if text.lower().startswith("what if"):
        return ""
    return _SHOW_LEAD.sub("", text).strip(" ,.!") or text


def long_title(topic: str, style: str) -> str:
    """A sleep video's working title from what was asked."""
    text = topic.strip().rstrip(".!")
    if text.lower().startswith("what if"):
        return f"{text[0].upper()}{text[1:]}? A calm what-if to fall asleep to"
    if style == "theory_sleep":
        return f"Every {show_of(text)} theory, explained to fall asleep to"
    show = show_of(text)
    return f"The entire lore of {show}, explained to fall asleep to"


def farm_task(job: FarmJob) -> str:
    """A Farm job in words the Farm agent's safety net reads back."""
    about = f" about {job.topic}" if job.topic else ""
    for_channel = f" for @{job.channel}" if job.channel else ""
    if job.action == "channel":
        return f"Start a channel about {job.topic} in the Content Farm."
    if job.action == "ideas":
        return (
            f"Give me {job.count} video ideas{about}{for_channel} in the Content Farm."
        )
    plural = "video" if job.count == 1 else "videos"
    if job.kind:
        thing = {"cartoon": "cartoon", "edit": "music edit"}[job.kind]
        things = thing if job.count == 1 else f"{thing}s"
        return f"Make {job.count} {things}{about}{for_channel} in the Content Farm."
    if job.long:
        hours = f"{job.minutes / 60:g} hour" if job.minutes else "long"
        return f"Make {job.count} {hours} sleep {plural}{about}{for_channel} in the Content Farm."
    return f"Make {job.count} {plural}{about}{for_channel} in the Content Farm."


def _dict_list(value: object) -> list[JsonObject]:
    """The objects in a tool argument that should be a list of them."""
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


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
        server_models: Callable[[], Sequence[str]] | None = None,
        starter_repos: Path | None = None,
        desk_opener: Opener | None = None,
        media_home: Path | None = None,
        hear: Hear | None = None,
        fetch: Fetch | None = None,
    ) -> None:
        self._store = store
        # The desktop browser agents drive, opened on first use and kept
        # open between turns; and how videos with no captions are heard.
        self._desk_opener = desk_opener
        self._desk: DeskBrowser | None = None
        self._desk_config: tuple[str, bool, bool] | None = None
        self._media_home = media_home or Path.home()
        self._hear = hear
        self._fetch = fetch
        self._data_root = sites_dir.parent
        # Claw Code, built on this PC from FCC's own copy (vendor/claw-code).
        self.claw = ClawCode(self._data_root / "claw-code")
        # Outside repos that come with FCC (vendor/repos), added on first load.
        self._starter_folder = starter_repos
        self._starters_lock = asyncio.Lock()
        self._starters_checked = False
        self._server_models = server_models or (lambda: ())
        self._web_tools = web_tools
        self._search_transport = search_transport
        self._voice_transport = voice_transport
        self._connectivity = Connectivity(transport=search_transport)
        self._settings_provider = settings_provider
        self._sites = SiteWorkspace(sites_dir)
        self._photos = PhotoLibrary(store, sites_dir.parent / "photos")
        # Jarvis's playbook until an Obsidian vault is set.
        self._playbook_home = sites_dir.parent / "playbook"
        # Skills, agents, and MCP servers added from GitHub.
        # A copy of every repo and release Studio downloads, so they still
        # install after the original is deleted from GitHub.
        self.vault = RepoVault(sites_dir.parent / "vault")
        self._extensions = ExtensionLibrary(
            sites_dir.parent / "extensions",
            transport=search_transport,
            vault=self.vault,
        )
        self._mcp = McpManager()
        self._library = ModelLibrary(store=store, models_dir=models_dir)
        self._models_dir = models_dir
        self._voice_setup = SetupState()
        self._phones = PhoneLinks(store)
        self._engine = Engine(
            root=models_dir / "engine",
            store=store,
            folders=self._engine_folders,
            port=lambda: self.settings.studio_engine_port,
            build=lambda: self.settings.studio_engine_build,
            binary_override=lambda: self.settings.studio_engine_path or "",
            models_at_once=lambda: self.settings.studio_engine_models_at_once,
            gpu_gb=lambda: self.settings.studio_engine_gpu_gb,
            vault=self.vault,
        )
        # Pictures painted on this PC (stable-diffusion.cpp) for cartoons.
        self.image_engine = ImageEngine(
            models_dir / "image-engine",
            build=lambda: self.settings.studio_image_build,
            style=lambda: self.settings.studio_image_style,
            vault=self.vault,
        )
        self.image_transport: httpx.AsyncBaseTransport | None = None
        """Tests point the online image service here."""
        self._image_sample: JsonObject = {"state": "idle", "error": "", "made": 0}
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
        # The app's first page load asks for the starter team from several
        # requests at once; without this each one creates its own copy.
        self._defaults_lock = asyncio.Lock()
        self._room_lock = asyncio.Lock()
        # Coding jobs the Coder and the Tester are on, so one isn't started twice.
        self._code_loops: set[str] = set()
        self._budget = SearchBudget()
        self._chat_turns: dict[str, asyncio.Lock] = {}
        self._main_busy = 0
        self._main_error: str | None = None
        self._lab = LabBench(store, think=self._lab_think, transport=search_transport)
        self._lab_busy = 0
        self._lab_error: str | None = None
        self._farm = ContentFarm(
            store,
            sites_dir.parent / "farm",
            think=self._farm_think,
            speak=self._farm_speak,
            research=self._farm_research,
            visuals=self._farm_visuals,
            video_size=lambda: self.settings.studio_farm_video_size,
            music=self._farm_music,
            pexels_key=lambda: self.settings.studio_farm_pexels_key or "",
            hear=self._farm_hear,
            transport=search_transport,
            paint=self._farm_paint,
            paints=self.paints_cartoons,
            art_style=lambda: (
                ("cloud-" if self.settings.studio_image_source == "cloud" else "")
                + self.settings.studio_image_style
            ),
        )
        self._farm_busy = 0
        self._farm_error: str | None = None
        self._farm_pilot: asyncio.Task[None] | None = None
        # Tests point the farm's image maker here instead of a real server.
        self.farm_image_transport: httpx.AsyncBaseTransport | None = None
        self._engine_start_failed = False
        self._engine_retry_at = 0.0
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
        self._router.use_fallback(lambda: self.server_model)
        self._router.use_turns(lambda: self.settings.studio_local_model_turns)
        self._router.before_local(self._engine_before_local)

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
            base_url=self._local_url,
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

    def _search_budget(self) -> SearchBudget:
        """Today's use of the search keys, shared by every search Studio runs."""
        self._budget.daily_limit = self.settings.studio_search_daily_limit
        return self._budget

    def _search(self) -> StudioSearch:
        settings = self.settings
        return StudioSearch(
            provider=settings.studio_search_provider,
            api_key=settings.studio_search_api_key or "",
            backup_key=settings.studio_search_backup_api_key or "",
            order=settings.studio_search_order,
            budget=self._search_budget(),
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
            vault=self.vault,
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
            ears=self._ears(),
        )

    def _ears(self) -> VideoEars:
        """Listening to videos on this PC with the main AI's ears (Whisper)."""
        settings = self.settings
        voice = self.local_voice()
        return VideoEars(
            hear=self._hear or voice.hear_file,
            work=self._data_root / "listening",
            home=self._media_home,
            max_minutes=settings.studio_watch_max_minutes,
            fetch=self._fetch or ytdlp_fetch,
            allow_private=settings.web_fetch_allow_private_networks,
            ready=(lambda: True) if self._hear else listen_package_ready,
            record=self._record_in_desk,
        )

    async def _record_in_desk(
        self, url: str, folder: Path, max_minutes: int
    ) -> tuple[Path, str, float]:
        """When a web video's sound cannot be downloaded, play it in the
        desktop browser and record it as it plays."""
        if self._desk_opener is None and not desk_package_ready():
            raise VideoEarsError(INSTALL_HINT)
        try:
            return await self.desk_browser().record_sound(
                url, folder, max_minutes=max_minutes, by="Video notes"
            )
        except DeskError as error:
            raise VideoEarsError(f"Could not listen to it: {error}") from error

    def desk_browser(self) -> DeskBrowser:
        """The browser window on the desktop the agents drive (one, shared)."""
        settings = self.settings
        config = (
            settings.studio_desk_browser,
            settings.studio_desk_visible,
            settings.web_fetch_allow_private_networks,
        )
        if self._desk is None or (config != self._desk_config and not self._desk.open):
            opener = self._desk_opener or playwright_opener(
                self._data_root / "desk-browser",
                browser=config[0],
                visible=config[1],
            )
            self._desk = DeskBrowser(opener, allow_private=config[2])
            self._desk_config = config
        return self._desk

    def desk_status(self) -> JsonObject:
        """For the app: whether the desktop browser is installed and open."""
        desk = self._desk
        shot = desk.state.shot if desk is not None else None
        return {
            "installed": self._desk_opener is not None or desk_package_ready(),
            "open": bool(desk and desk.open),
            "url": shot.url if shot else "",
            "title": shot.title if shot else "",
            "used_by": desk.state.used_by if desk is not None else "",
            "listening": self._hear is not None or listen_package_ready(),
        }

    async def show_video(self, url: str) -> JsonObject:
        """Play a video (a link or a file on this PC) in the desktop browser."""
        desk = self.desk_browser()
        try:
            local = self._videos().local_file(url)
            if local is not None:
                await desk.show_file(local, by="You")
            else:
                await desk.go(url, by="You")
            await desk.video("play", by="You")
        except (DeskError, VideoError) as error:
            raise StudioError(str(error)) from error
        return self.desk_status()

    async def open_in_desk(self, url: str) -> JsonObject:
        """Open a page in the desktop browser for the user."""
        try:
            await self.desk_browser().go(url, by="You")
        except DeskError as error:
            raise StudioError(str(error)) from error
        return self.desk_status()

    # ------------------------------------------------------------ image engine

    def image_cloud(self) -> CloudSettings:
        return CloudSettings(
            base_url=self.settings.studio_image_cloud_url or "",
            api_key=self.settings.studio_image_cloud_key or "",
            model=self.settings.studio_image_cloud_model,
        )

    def painting_ready(self) -> bool:
        """Whether pictures can be painted now (this PC's engine, or online)."""
        if self.settings.studio_image_source == "cloud":
            return self.image_cloud().ready
        return self.image_engine.ready()

    def paints_cartoons(self) -> bool:
        art = self.settings.studio_cartoon_art
        return art == "painted" or (art == "auto" and self.painting_ready())

    def image_status(self) -> JsonObject:
        return self.image_engine.status() | {
            "source": self.settings.studio_image_source,
            "cloud_ready": self.image_cloud().ready,
            "painting_ready": self.painting_ready(),
            "cartoon_art": self.settings.studio_cartoon_art,
            "sample": dict(self._image_sample),
        }

    def start_image_install(self) -> JsonObject:
        """Download stable-diffusion.cpp and the style, in the background."""

        async def work() -> None:
            try:
                if self.image_engine.binary() is None:
                    await self.image_engine.install()
                if not self.image_engine.style_ready():
                    await self.image_engine.setup_style()
            except ImageEngineError as error:
                logger.info("Studio: image engine setup stopped: {}", error)

        busy = {"checking", "downloading", "unpacking"}
        if (
            self.image_engine.install_state.state not in busy
            and self.image_engine.setup_state.state != "downloading"
        ):
            self.spawn(work())
        return self.image_status()

    @property
    def image_sample_path(self) -> Path:
        return self._models_dir / "image-engine" / "sample.png"

    def start_image_sample(self, prompt: str, kind: str = "character") -> JsonObject:
        """Paint a test picture in the background, to see the style."""
        if not self.painting_ready():
            raise StudioError("Set up the image engine first.")
        if self._image_sample.get("state") == "painting":
            return self.image_status()
        from .farm.cartoon.aiart import (
            PLACE_SIZE,
            SPRITE_SIZE,
            character_prompt,
            place_prompt,
        )

        words = " ".join(prompt.split())[:300] or "a teenage superhero"
        place = kind == "place"
        text = place_prompt(words) if place else character_prompt(words, words)
        size = PLACE_SIZE if place else SPRITE_SIZE
        self._image_sample = {"state": "painting", "error": "", "made": 0}

        async def work() -> None:
            out = self.image_sample_path.with_name("sample-new.png")
            try:
                await self.paint(text, size, secrets.randbelow(100_000), out)
                out.replace(self.image_sample_path)
                self._image_sample = {"state": "ready", "error": "", "made": now_ms()}
            except (StudioError, OSError) as error:
                self._image_sample = {"state": "failed", "error": str(error), "made": 0}

        self.spawn(work())
        return self.image_status()

    async def install_image_archive(self, archive: Path) -> JsonObject:
        try:
            await self.image_engine.install_archive(archive)
        except ImageEngineError as error:
            raise StudioError(str(error)) from error
        return self.image_status()

    async def paint(
        self,
        prompt: str,
        size: tuple[int, int],
        seed: int,
        out: Path,
        start_from: Path | None = None,
        strength: float = 0.5,
    ) -> Path:
        """Paint one picture with whichever image engine is chosen."""
        try:
            if self.settings.studio_image_source == "cloud":
                style = self.image_engine.style()
                return await make_picture(
                    self.image_cloud(),
                    f"{style.prompt}, {prompt}",
                    out,
                    size=size,
                    start_from=start_from,
                    transport=self.image_transport,
                )
            return await self.image_engine.make(
                Picture(
                    prompt=prompt,
                    width=size[0],
                    height=size[1],
                    seed=seed,
                    start_from=start_from,
                    strength=strength,
                    # Places are painted wide, characters tall.
                    scenery=size[0] > size[1],
                ),
                out,
            )
        except (ImageEngineError, ImageCloudError) as error:
            raise StudioError(str(error)) from error

    async def _farm_paint(
        self,
        prompt: str,
        size: tuple[int, int],
        seed: int,
        out: Path,
        start_from: Path | None,
        strength: float,
    ) -> Path:
        try:
            return await self.paint(prompt, size, seed, out, start_from, strength)
        except StudioError as error:
            raise ArtError(str(error)) from error

    def claw_status(self) -> JsonObject:
        return self.claw.status()

    def build_claw(self) -> JsonObject:
        try:
            return self.claw.start_build()
        except ClawError as error:
            raise StudioError(str(error)) from error

    def open_claw(self, folder: str = "") -> JsonObject:
        """Open Claw Code in a terminal on this PC, connected to FCC."""
        place = (
            Path(folder.strip().strip('"')).expanduser()
            if folder.strip()
            else Path.home()
        )
        try:
            self.claw.open_terminal(place)
        except (ClawError, OSError) as error:
            raise StudioError(str(error)) from error
        return self.claw.status() | {"opened_in": str(place)}

    async def close_desk_browser(self) -> None:
        if self._desk is not None:
            await self._desk.close()

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

    async def study_video(
        self, url: str, *, focus: str = "", show: bool = False
    ) -> VideoNote:
        """Watch a video the user gives Studio (a link or a file on this PC),
        playing it in the desktop browser too when asked."""
        videos = self._videos()
        if show:
            try:
                await self.show_video(url)
            except StudioError as error:  # the notes still get made
                logger.info("Studio: could not play {} on the desktop: {}", url, error)
        try:
            note = await videos.study(url, focus=focus, source="user")
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
            all_tools=settings.studio_all_tools,
            image_transport=self._search_transport,
            photos=self._photos,
            desk=self.desk_browser(),
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
            coder_max_steps=self.settings.studio_coder_max_steps,
            live=self._live_text,
            temperature=self.settings.studio_agent_temperature,
            notes=self._notes_keeper,
            sealed=self.is_private_from,
            local_control=self.settings.studio_local_control,
            main_own_memory=self.settings.studio_main_own_memory,
            learned=self._learn_call if self.settings.studio_jarvis_playbook else None,
            built=self._offer_app_download,
        )

    async def _offer_app_download(self, chat: Chat, site_ids: frozenset[str]) -> None:
        """When agents build or change an app, the user gets it to download,
        in the chat where it was made and in every chat that asked for it."""
        for site_id in sorted(site_ids):
            site = await self._store.get(SiteProject, site_id)
            files = await self._sites.files(site_id) if site is not None else ()
            if site is None or not files:
                continue
            size = sum(item.size for item in files)
            paths = {item.path for item in files}
            card: JsonObject = {
                "kind": "download",
                "site_id": site.id,
                "name": site.name,
                "file_name": f"{site.slug}.zip",
                "files": len(files),
                "bytes": size,
                "url": f"/studio/api/sites/{site.id}/archive",
                "preview": f"/studio/sites/{site.id}/index.html"
                if "index.html" in paths
                else "",
            }
            text = (
                f"{site.name} is ready to download: {len(files)} file"
                f"{'' if len(files) == 1 else 's'}, {_size_label(size)}."
            )
            target: Chat | None = chat
            for _ in range(6):
                if target is None:
                    break
                if not await self._same_card_last(target.id, card):
                    await self._store.append_message(
                        chat_id=target.id,
                        role="event",
                        text=text,
                        author="studio",
                        data=card,
                    )
                target = (
                    await self._store.get(Chat, target.parent_chat_id)
                    if target.parent_chat_id
                    else None
                )

    async def _same_card_last(self, chat_id: str, card: JsonObject) -> bool:
        """True when the chat already offers this app, unchanged since."""
        for message in reversed(await self._store.transcript(chat_id, limit=30)):
            if (
                message.data.get("kind") == "download"
                and message.data.get("site_id") == card["site_id"]
            ):
                return (
                    message.data.get("files") == card["files"]
                    and message.data.get("bytes") == card["bytes"]
                )
        return False

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
        if self._farm_pilot is not None:
            self._farm_pilot.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._farm_pilot
        await self._engine.stop()
        await self._mcp.close()
        await self.close_desk_browser()

    # ----------------------------------------------------------- the engine

    def _local_url(self) -> str:
        """Where local models are served: the built-in engine, or LM Studio.

        With the engine switched on but not installed, or failing to start,
        LM Studio (or whatever Local Model Server names) answers instead, so
        a half-finished engine setup never leaves the agents without a brain.
        """
        settings = self.settings
        if settings.studio_engine and self._engine_usable():
            return f"{self._engine.url}/v1"
        return settings.studio_local_base_url

    def _engine_usable(self) -> bool:
        engine = self._engine
        return engine.running or (
            engine.binary() is not None and not self._engine_start_failed
        )

    def _engine_folders(self) -> list[tuple[str, Path]]:
        folders: list[tuple[str, Path]] = [("Studio", self._models_dir)]
        lmstudio = self._lora.lmstudio_dir()
        if lmstudio is not None:
            folders.append(("LM Studio", lmstudio))
        extra = self.settings.studio_engine_folders or ""
        folders.extend(
            ("Your folder", Path(part.strip()).expanduser())
            for part in re.split(r"[;\n]", extra)
            if part.strip()
        )
        return folders

    async def _engine_before_local(self) -> None:
        """Start the built-in engine on the first local call, when it is on."""
        engine = self._engine
        if not self.settings.studio_engine or engine.running:
            return
        if engine.binary() is None:
            return
        if self._engine_start_failed and time.monotonic() < self._engine_retry_at:
            return
        try:
            await engine.start()
        except EngineError as error:
            logger.warning(
                "Studio: the built-in engine did not start, using {} instead: {}",
                self.settings.studio_local_base_url,
                error,
            )
            self._engine_start_failed = True
            self._engine_retry_at = time.monotonic() + ENGINE_RETRY_SECONDS
            self._local_probe = None
            return
        self._engine_start_failed = False
        self._local_probe = None
        self._loaded_probe = None

    async def engine_status(self) -> JsonObject:
        settings = self.settings
        return await self._engine.status(
            speeds=self._router.local_speeds(),
            on=settings.studio_engine,
            lm_studio_running=settings.studio_engine
            and await self._lm_studio_answers(),
        )

    async def _lm_studio_answers(self) -> bool:
        """True when LM Studio's server answers while the engine is in use."""
        base = self.settings.studio_local_base_url.rstrip("/")
        if base.startswith(self._engine.url):
            return False
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                response = await client.get(f"{base}/models")
        except httpx.HTTPError:
            return False
        return response.status_code < 400

    def engine_identify(self, name: str, head: bytes) -> JsonObject:
        """What a file is, from its first bytes, before it is uploaded."""
        if ENGINE_ARCHIVE.match(Path(name).name):
            return {
                "is_model": False,
                "engine": True,
                "kind": "engine",
                "label": "llama.cpp engine",
                "file": name,
                "message": "The llama.cpp engine. Installing it…",
            }
        kind, label = identify(head, name)
        if kind == "gguf":
            return {
                "is_model": True,
                "kind": kind,
                "label": label,
                "file": name,
                "message": "A model file. Adding it…",
            }
        return not_a_model(kind, label, name)

    async def engine_install_file(
        self, name: str, chunks: AsyncIterator[bytes]
    ) -> JsonObject:
        """Install a llama.cpp release file the user downloaded themselves."""
        plain = Path(name).name
        if not ENGINE_ARCHIVE.match(plain):
            raise StudioError(
                "Drop the llama.cpp release file itself (llama-b1234-bin-….zip)."
            )
        folder = self._models_dir / "engine"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / plain
        handle = await anyio.to_thread.run_sync(target.open, "wb")
        try:
            async for chunk in chunks:
                await anyio.to_thread.run_sync(handle.write, chunk)
        finally:
            await anyio.to_thread.run_sync(handle.close)
        tag = await self._engine_call(self._engine.install_archive(target))
        self._local_probe = None
        return {"installed": True, "version": tag}

    async def engine_upload(
        self, name: str, chunks: AsyncIterator[bytes], *, size: int | None
    ) -> JsonObject:
        return await self._engine_call(self._engine.receive(name, chunks, size=size))

    async def engine_add_from_pc(self) -> JsonObject:
        """Pick a file in a normal window on this PC and add it without copying."""
        try:
            path = await pick_model_file()
        except ModelFileError as error:
            raise StudioError(str(error)) from error
        if path is None:
            return {"picked": False}
        return {"picked": True} | await self._engine_call(self._engine.add_file(path))

    async def engine_report(self, name: str) -> JsonObject:
        return await self._engine_call(self._engine.report(name))

    async def engine_tune(self, name: str | None = None) -> list[JsonObject]:
        done = await self._engine_call(self._engine.tune([name] if name else None))
        self._loaded_probe = None
        return done

    async def engine_benchmark(self, name: str) -> dict[str, float]:
        result = await self._engine_call(self._engine.benchmark(name))
        self._loaded_probe = None
        return result

    async def engine_find_fastest(self, name: str) -> JsonObject:
        """Search for the model's fastest settings in the background."""
        models = await self._engine.models()
        if name not in {model.name for model in models}:
            raise StudioError(f"No model called {name} on this PC.")
        if self._engine.binary() is None:
            raise StudioError(
                "The built-in engine is not installed yet. Press Install engine."
            )
        hunt = self._engine.speed_hunts.get(name)
        if hunt is not None and hunt.state == "running":
            return hunt.view()

        async def search() -> None:
            try:
                await self._engine.find_fastest(name)
            except EngineError as error:
                logger.warning("Studio: the speed search stopped: {}", error)
            finally:
                self._loaded_probe = None

        self.spawn(search())
        await asyncio.sleep(0)
        found = self._engine.speed_hunts.get(name)
        return (
            found.view() if found is not None else {"model": name, "state": "running"}
        )

    def engine_install(self) -> JsonObject:
        """Download the engine in the background; progress shows in the status."""

        async def install() -> None:
            try:
                await self._engine.install()
            except EngineError as error:
                logger.warning("Studio: engine install failed: {}", error)

        if self._engine.install_state.state not in {
            "checking",
            "downloading",
            "unpacking",
        }:
            self.spawn(install())
        return {"state": "checking"}

    async def engine_start(self) -> None:
        await self._engine_call(self._engine.start())
        self._engine_start_failed = False
        self._local_probe = None
        self._loaded_probe = None

    async def engine_stop(self) -> None:
        await self._engine.stop()
        self._local_probe = None

    async def engine_load(self, name: str) -> None:
        await self._engine_call(self._engine.load(name))
        self._loaded_probe = None

    async def engine_unload(self, name: str) -> None:
        await self._engine_call(self._engine.unload(name))
        self._loaded_probe = None

    async def engine_settings(self, name: str, values: JsonObject) -> JsonObject:
        saved = await self._engine_call(self._engine.save_settings(name, values))
        return saved.model_dump()

    def engine_logs(self, limit: int = 200) -> list[str]:
        return self._engine.logs(limit)

    async def _engine_call[T](self, work: Awaitable[T]) -> T:
        try:
            return await work
        except EngineError as error:
            raise StudioError(str(error)) from error

    # ---------------------------------------------------------------- agents

    async def ensure_defaults(self) -> tuple[Agent, ...]:
        """Create the starter agents the app expects on first run."""
        async with self._defaults_lock:
            return await self._ensure_defaults()

    async def _ensure_defaults(self) -> tuple[Agent, ...]:
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
                self.server_model,
                BUILDER_PROMPT,
                _default_tools(),
            ),
            (
                RESEARCHER_AGENT_NAME,
                "researcher",
                self.server_model,
                RESEARCHER_PROMPT,
                RESEARCHER_TOOLS,
            ),
            (
                HELPER_AGENT_NAME,
                "helper",
                self._local_team_model(existing),
                HELPER_PROMPT,
                HELPER_TOOLS,
            ),
            (
                TESTER_AGENT_NAME,
                "tester",
                self.server_model,
                TESTER_PROMPT,
                TESTER_TOOLS,
            ),
            (
                CODER_AGENT_NAME,
                "coder",
                self.server_model,
                CODER_PROMPT,
                CODER_TOOLS,
            ),
            (
                LAB_AGENT_NAME,
                "lab",
                self._local_team_model(existing),
                LAB_AGENT_PROMPT,
                LAB_AGENT_TOOLS,
            ),
            (
                FARM_AGENT_NAME,
                "farm",
                self._local_team_model(existing),
                FARM_AGENT_PROMPT,
                FARM_AGENT_TOOLS,
            ),
            (
                TEACHER_AGENT_NAME,
                "teacher",
                settings.studio_teacher_model or self.server_model,
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
        return agent_options() | {
            "all_tools": self.settings.studio_all_tools,
            "commands_enabled": self.settings.studio_agent_commands in {"ask", "auto"},
            # Web Access "all" gives every agent but the Guide web search and fetch.
            "web_for_all": self.settings.studio_web_access == "all",
        }

    def _is_local(self, model: str) -> bool:
        try:
            return self.runs_on_this_pc(model)
        except ValueError:
            return False

    @property
    def server_model(self) -> str:
        """The model agents think with on a server: the Studio default, or the
        proxy's model when the Studio default runs on this PC."""
        default = self.default_model
        return self.settings.model if self._is_local(default) else default

    def _local_team_model(self, existing: Sequence[Agent] = ()) -> str:
        """The model on this PC that the Helper shares with the main AI."""
        wanted = self.settings.studio_main_agent_model or ""
        if wanted and self._is_local(wanted):
            return wanted
        for agent in existing:
            if agent.role == MAIN_ROLE and self._is_local(agent.model):
                return agent.model
        return self.default_model

    async def _apply_team_layout(self, existing: Sequence[Agent]) -> list[Agent]:
        """Once: the main AI, Guide, and Helper think on this PC; every other
        agent on a server. Choices made afterwards are kept."""
        if await self._store.get(StudioFlag, TEAM_LAYOUT_FLAG) is not None:
            return list(existing)
        local = self._local_team_model(existing)
        server = self.server_model
        result: list[Agent] = []
        for agent in existing:
            model = agent.model
            if agent.role in CLASS_ROLES:
                pass  # Classes pair a server teacher with a local student.
            elif agent.role == "helper" and not self._is_local(model):
                model = local
            elif agent.role not in LOCAL_TEAM_ROLES and self._is_local(model):
                model = server
            if model != agent.model:
                agent = agent.model_copy(
                    update={
                        "model": model,
                        "local_only": model.startswith(LOCAL_MODEL_PREFIX),
                        "updated_at": now_ms(),
                    }
                )
                await self._store.put(agent)
            result.append(agent)
        await self._store.put(StudioFlag(id=TEAM_LAYOUT_FLAG, value="1"))
        return result

    async def _upgrade_defaults(self, existing: Sequence[Agent]) -> None:
        """Give starter agents from older versions their newer tools and roles.

        Starter agents made before a Studio Default Model was set were given
        the server's model; once one is set, they move to it (the server
        agents only, when it is a model on this PC).
        """
        settings = self.settings
        studio_default = settings.studio_default_model
        existing = await self._apply_team_layout(existing)
        for agent in existing:
            if (
                studio_default
                and (
                    not self._is_local(studio_default)
                    or agent.role in LOCAL_TEAM_ROLES | CLASS_ROLES
                )
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

    def has_every_tool(self, agent: Agent) -> bool:
        """Whether the agent gets every tool: chosen for it, and allowed."""
        return (
            self.settings.studio_all_tools and agent.all_tools and agent.role != "guide"
        )

    async def tools_in_use(
        self, agent: Agent, *, every_tool: bool | None = None
    ) -> tuple[str, ...]:
        """The tools an agent really gets on its next turn (or would, with
        ``every_tool`` set either way)."""
        granted = agent.tools
        if every_tool is None:
            every_tool = self.has_every_tool(agent)
        if every_tool and agent.role != "guide":
            granted = (
                *agent.tools,
                *(
                    name
                    for name in ALL_TOOL_NAMES
                    if name not in agent.tools
                    and name != TOOLSHED_TOOL
                    and (agent.role == MAIN_ROLE or name not in MAIN_ONLY_TOOLS)
                ),
            )
        if await self.is_private_from(agent):
            granted = tuple(t for t in granted if t not in SEALED_TOOLS)
        return granted

    async def agent_view(self, agent: Agent) -> JsonObject:
        """One agent for the app: its tools, their token cost, and its memory."""
        using = await self.tools_in_use(agent)
        private = await self.is_private_from(agent)
        area = (
            await self._store.count(
                MemoryEntry, where={"agent_id": server_area(agent.id)}
            )
            if private
            else 0
        )
        return agent.model_dump() | {
            "tools_in_use": list(using),
            "all_tools": self.has_every_tool(agent),
            "every_tool_allowed": self.settings.studio_all_tools
            and agent.role != "guide",
            "tool_tokens": tool_tokens(using),
            "every_tool_tokens": tool_tokens(
                await self.tools_in_use(agent, every_tool=True)
            ),
            "own_tool_tokens": tool_tokens(
                await self.tools_in_use(agent, every_tool=False)
            ),
            "private": private,
            "memory_area": server_area(agent.id),
            "memory_area_count": area,
            "command": self._command_line(agent, private=private),
            "own_memory": agent.role == MAIN_ROLE
            and self.settings.studio_main_own_memory
            and not private,
        }

    def _command_line(self, agent: Agent, *, private: bool) -> str:
        """Who this agent directs and who directs it, in a few words."""
        if agent.role == MAIN_ROLE:
            return "Directs every agent"
        if agent.role == "guide":
            return "Explains the app"
        if private:
            return (
                "Takes jobs from the main AI and the agents on this PC"
                if self.settings.studio_local_control
                else "Takes jobs from the main AI"
            )
        if self.settings.studio_local_control:
            return "Directs the agents on server AIs; takes jobs from the main AI"
        return "Takes jobs from the main AI"

    async def set_every_tool(self, agent_id: str, on: bool) -> Agent:
        """Give one agent every tool, or only its own."""
        agent = await self._store.require(Agent, agent_id)
        if agent.role == "guide" and on:
            raise StudioError(
                "The Guide keeps its few tools: it runs on the smallest model."
            )
        return await self.update_agent(agent_id, {"all_tools": on})

    # ------------------------------------------------------------ photos

    @property
    def photos(self) -> PhotoLibrary:
        """The user's business photos."""
        return self._photos

    async def add_photo(
        self, name: str, data: bytes, *, note: str = "", chat_id: str | None = None
    ) -> JsonObject:
        """Keep one business photo the user sent, with their note."""
        try:
            photo = await self._photos.add(name, data, note=note, chat_id=chat_id)
        except PhotoError as error:
            raise StudioError(str(error)) from error
        return photo_view(photo)

    async def photo_list(self) -> list[JsonObject]:
        return [photo_view(photo) for photo in await self._photos.photos()]

    async def set_photo_note(self, photo_id: str, note: str) -> JsonObject:
        return photo_view(await self._photos.set_note(photo_id, note))

    async def delete_photo(self, photo_id: str) -> bool:
        return await self._photos.delete(photo_id)

    # ------------------------------------------------------------ the Lab

    @property
    def lab(self) -> LabBench:
        """The Lab: mixing, products, materials, and electronics."""
        return self._lab

    async def _lab_think(self, system: str, prompt: str) -> str:
        """The Lab's own questions go to a server AI: it knows more chemistry.

        When no server model answers (no key, or one the key can't use), the
        main AI's own model takes them, so the Lab still works offline.
        """
        server = await self.effective_model(self.server_model)
        try:
            reply = await self._router.complete(
                [ChatMessage.user(prompt)],
                model=server,
                system=system,
                temperature=0.2,
                max_tokens=900,
            )
        except StudioLLMError:
            own = (await self.main_agent()).model or self.default_model
            if own == server:
                raise
            reply = await self._router.complete(
                [ChatMessage.user(prompt)],
                model=own,
                system=system,
                temperature=0.2,
                max_tokens=900,
            )
        return reply.text

    async def lab_chat(self) -> Chat:
        """The Lab's chat with the main AI, opening one if needed."""
        agent = await self.main_agent()
        for chat in await self._store.find(
            Chat, where={"agent_id": agent.id}, order_by="updated_at DESC"
        ):
            if chat.settings.get(LAB_CHAT_SETTING):
                return chat
        return await self.create_chat(
            agent_id=agent.id,
            title=f"{agent.name} in the Lab",
            settings={LAB_CHAT_SETTING: True},
        )

    async def lab_say(self, text: str, *, background: bool = True) -> Chat:
        """Ask the main AI to make or test something in the Lab."""
        if not text.strip():
            raise StudioError("Say what to make or test.")
        chat = await self.lab_chat()
        self._lab_busy += 1
        self._lab_error = None
        if background:
            self.spawn(self._lab_turn(chat.id, text))
        else:
            await self._lab_turn(chat.id, text)
        return chat

    async def _lab_turn(self, chat_id: str, text: str) -> None:
        try:
            async with self._turn_lock(chat_id):
                result = await self.send(chat_id, text)
            if result.failed:
                self._lab_error = result.error or "The main AI did not finish."
        except (StudioError, StudioNotFoundError) as error:
            self._lab_error = str(error)
            await self._store.append_message(
                chat_id=chat_id,
                role="event",
                text=f"Could not answer: {error}",
                author="studio",
                data={"kind": "error"},
            )
        finally:
            self._lab_busy = max(0, self._lab_busy - 1)

    async def lab_console(self, *, after: int = 0) -> JsonObject:
        """The Lab chat so far, and whether the main AI is still working."""
        chat = await self.lab_chat()
        messages = await self._store.transcript(chat.id, after=after)
        agent = await self.main_agent()
        return {
            "chat_id": chat.id,
            "agent": agent.name,
            "busy": self._lab_busy > 0,
            "error": self._lab_error,
            "messages": [message.model_dump() for message in messages],
        }

    async def _lab_tool(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        arguments = call.arguments
        action = str(arguments.get("action") or "").strip().lower()
        request = str(arguments.get("request") or "").strip()
        made_by = context.agent_name or "An agent"
        try:
            if action == "make":
                project = await self._lab.make(request, made_by=made_by)
                return ToolOutcome(
                    text=lab_text.describe_project(project),
                    data={"tool": "lab", "action": "make", "project_id": project["id"]},
                )
            if action == "mix":
                items = _dict_list(arguments.get("items"))
                result = await self._lab.mix(
                    items,
                    heat=bool(arguments.get("heat")),
                    flame=bool(arguments.get("flame")),
                )
                names = (
                    " + ".join(str(item.get("name")) for item in result["ingredients"])
                    or "Mix"
                )
                project = await self._lab.save(
                    name=names[:80],
                    kind="mix",
                    data=result,
                    request=request,
                    made_by=made_by,
                )
                return ToolOutcome(
                    text=lab_text.describe_mix(result),
                    data={"tool": "lab", "action": "mix", "project_id": project["id"]},
                )
            if action == "build":
                parts = _dict_list(arguments.get("parts"))
                series = arguments.get("series")
                result = await self._lab.build(
                    parts,
                    series=series if isinstance(series, bool) else True,
                    name=request,
                    save=True,
                    made_by=made_by,
                )
                return ToolOutcome(
                    text=lab_text.describe_build(result),
                    data={"tool": "lab", "action": "build", "project_id": result["id"]},
                )
            if action == "material":
                parts = _dict_list(arguments.get("parts"))
                result = await self._lab.material(
                    parts, name=request, save=True, made_by=made_by
                )
                return ToolOutcome(
                    text=lab_text.describe_material(result),
                    data={
                        "tool": "lab",
                        "action": "material",
                        "project_id": result["id"],
                    },
                )
            if action == "find":
                return ToolOutcome(
                    text=await lab_text.find(self._lab, request),
                    data={"tool": "lab", "action": "find"},
                )
            if action == "list":
                projects = await self._lab.projects()
                lines = [
                    f"- {p['name']} ({p['kind']}, by {p['made_by']})"
                    for p in projects[:20]
                ]
                return ToolOutcome(
                    text="\n".join(lines) or "Nothing has been made in the Lab yet.",
                    data={"tool": "lab", "action": "list"},
                )
        except LabError as error:
            return ToolOutcome(text=str(error), data={"tool": "lab"}, failed=True)
        return ToolOutcome(
            text="Use action make, mix, build, material, find, or list.",
            data={"tool": "lab"},
            failed=True,
        )

    # ------------------------------------------------------- the Content Farm

    @property
    def farm(self) -> ContentFarm:
        """The Content Farm: faceless short videos, idea to finished MP4."""
        return self._farm

    async def _farm_writer(self) -> str:
        """The farm writes with the Farm agent's model: the team's local one."""
        writer = await self._team_member("farm")
        if writer is not None and writer.model:
            return writer.model
        return (await self.main_agent()).model or self.default_model

    async def _farm_think(self, system: str, prompt: str) -> str:
        model = await self.effective_model(await self._farm_writer())
        try:
            reply = await self._router.complete(
                [ChatMessage.user(prompt)],
                model=model,
                system=system,
                temperature=0.8,
                max_tokens=1_400,
            )
        except StudioLLMError as error:
            own = await self.effective_model(
                (await self.main_agent()).model or self.default_model
            )
            if own == model:
                raise FarmError(f"The writer's model didn't answer: {error}") from error
            try:
                reply = await self._router.complete(
                    [ChatMessage.user(prompt)],
                    model=own,
                    system=system,
                    temperature=0.8,
                    max_tokens=1_400,
                )
            except StudioLLMError as again:
                raise FarmError(f"The writer's model didn't answer: {again}") from again
        return reply.text

    async def _farm_speak(self, text: str, voice: str, speed: float) -> bytes | None:
        """A line read by the built-in voice, or None when there is none."""
        if voice == "none" or not speech_package_ready():
            return None
        settings = self.settings
        speaker = LocalVoice(
            self._models_dir / "voice",
            quality=settings.studio_voice_quality,
            voice=voice if voice in VOICE_CHOICES else "am_michael",
            speed=speed,
            effect="none",
            transport=self._voice_transport,
        )
        if not speaker.speech_ready():
            return None
        try:
            return await speaker.speak(text)
        except (LocalVoiceError, OSError, RuntimeError, ValueError) as error:
            logger.info("Content Farm: the voice failed: {}", error)
            return None

    async def _farm_hear(self, wav: bytes) -> list[tuple[str, float, float]]:
        """The words sung in a song and when, by the built-in Whisper; none
        when the ears aren't set up (the lyrics are then spread on the beat)."""
        if not listen_package_ready():
            return []
        ears = self.local_voice()
        if not ears.listen_ready():
            return []
        try:
            return await anyio.to_thread.run_sync(lambda: ears.timed_words(wav))
        except (LocalVoiceError, OSError, RuntimeError, ValueError) as error:
            logger.info("Content Farm: Whisper couldn't hear the song: {}", error)
            return []

    async def _farm_research(self, query: str) -> str:
        if self.settings.studio_web_access == "off":
            return ""
        try:
            report = await self._search().search(query[:200], limit=5)
        except (SearchError, ValueError, httpx.HTTPError) as error:
            logger.info("Content Farm: search failed: {}", error)
            return ""
        return "\n".join(
            f"- {hit.title}: {hit.snippet}"[:300] for hit in report.hits[:5]
        )

    def _farm_visuals(self) -> Visuals:
        return Visuals(
            image_url=self.settings.studio_farm_image_url or "",
            transport=self._search_transport,
            image_transport=self.farm_image_transport,
        )

    def _farm_music(self) -> Path | None:
        chosen = (self.settings.studio_farm_music or "").strip().strip('"')
        path = Path(chosen).expanduser() if chosen else None
        return path if path is not None and path.is_file() else None

    async def farm_overview(self) -> JsonObject:
        overview = await self._farm.overview()
        overview["voice"] = speech_package_ready() and self.local_voice().speech_ready()
        overview["voices"] = [v for v in VOICE_CHOICES if v != "jarvis"]
        self._start_farm_pilot(
            any(
                channel.get("autopilot") for channel in _dict_list(overview["channels"])
            )
        )
        return overview

    async def save_farm_channel(
        self, fields: JsonObject, channel_id: str | None = None
    ) -> JsonObject:
        try:
            channel = await self._farm.save_channel(fields, channel_id)
        except FarmError as error:
            raise StudioError(str(error)) from error
        self._start_farm_pilot(channel.autopilot)
        return channel_view(channel)

    async def farm_ideas(
        self, channel_id: str, *, count: int = 5, topic: str = ""
    ) -> list[JsonObject]:
        try:
            channel = await self._farm.channel(channel_id)
            posts = await self._farm.ideas(channel, count=count, topic=topic)
        except FarmError as error:
            raise StudioError(str(error)) from error
        return [self._farm.view(post) for post in posts]

    async def farm_make(
        self,
        post_ids: Sequence[str],
        *,
        tell_chat: str | None = None,
        rewrite: bool = False,
    ) -> int:
        """Start making videos, one after another, in the background."""
        ready = [post_id for post_id in post_ids if post_id]
        if not ready:
            return 0
        self.spawn(self._farm_line(ready, tell_chat, rewrite))
        return len(ready)

    async def _farm_line(
        self, post_ids: Sequence[str], tell_chat: str | None, rewrite: bool = False
    ) -> None:
        for post_id in post_ids:
            try:
                post = await self._farm.make(post_id, rewrite=rewrite)
            except FarmError as error:
                logger.info("Content Farm: {}", error)
                continue
            await self._farm_news(post, tell_chat)

    async def _farm_news(self, post: FarmPost, tell_chat: str | None) -> None:
        """Say in the farm chat (and where it was asked) that a video is done."""
        if post.status == "ready":
            when = (
                datetime.fromtimestamp(post.scheduled_at / 1000).strftime(
                    "%a %d %b %H:%M"
                )
                if post.scheduled_at
                else "when you like"
            )
            text = f"Video ready: {post.title} (post it {when})."
        elif post.status == "failed":
            text = f"Couldn't make '{post.title}': {post.error}"
        else:
            return
        chats = {(await self.farm_chat()).id}
        if tell_chat:
            chats.add(tell_chat)
        for chat_id in chats:
            with contextlib.suppress(StudioNotFoundError, StudioError):
                await self._store.append_message(
                    chat_id=chat_id,
                    role="event",
                    text=text,
                    author="farm",
                    data={"kind": "farm", "post_id": post.id, "status": post.status},
                )

    async def farm_editor(self, post_id: str) -> JsonObject:
        try:
            return self._farm.editor_view(await self._farm.post(post_id))
        except FarmError as error:
            raise StudioError(str(error)) from error

    async def farm_edit_scenes(
        self, post_id: str, scenes: list[JsonObject]
    ) -> JsonObject:
        try:
            post = await self._farm.edit_scenes(post_id, scenes)
        except FarmError as error:
            raise StudioError(str(error)) from error
        return self._farm.editor_view(post)

    async def farm_scene_media(
        self, post_id: str, index: int, choice: JsonObject
    ) -> JsonObject:
        try:
            post = await self._farm.set_scene_media(post_id, index, choice)
        except (FarmError, ValueError) as error:
            raise StudioError(str(error)) from error
        return self._farm.editor_view(post)

    async def farm_ai_edit(
        self, post_id: str, instruction: str, *, chapter: int | None = None
    ) -> JsonObject:
        try:
            post = await self._farm.ai_edit(post_id, instruction, chapter=chapter)
        except FarmError as error:
            raise StudioError(str(error)) from error
        return self._farm.editor_view(post)

    async def farm_candidates(self, post_id: str, query: str) -> list[JsonObject]:
        """Clips and pictures that could go in a scene, for the editor."""
        try:
            post = await self._farm.post(post_id)
            channel = await self._farm.channel(post.channel_id)
        except FarmError as error:
            raise StudioError(str(error)) from error
        picker = self._farm.picker(post, channel)
        found = await picker.candidates(query or post.title)
        return [item.to_json() for item in found]

    async def farm_fill(self, channel_id: str) -> int:
        """Make a day of videos for one channel: its ideas first, then new ones."""
        try:
            channel = await self._farm.channel(channel_id)
            ideas = await self._farm.posts(channel.id, status="idea")
            ideas.reverse()
            wanted = channel.posts_per_day
            if len(ideas) < wanted:
                ideas += await self._farm.ideas(channel, count=wanted - len(ideas))
        except FarmError as error:
            raise StudioError(str(error)) from error
        return await self.farm_make([post.id for post in ideas[:wanted]])

    def _start_farm_pilot(self, wanted: bool) -> None:
        if not wanted or (self._farm_pilot is not None and not self._farm_pilot.done()):
            return
        self._farm_pilot = asyncio.ensure_future(self._farm_autopilot())

    async def _farm_autopilot(self) -> None:
        """Keep each autopilot channel's queue a day deep, one video at a time."""
        while True:
            try:
                await self._farm_pilot_round()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("Content Farm autopilot: {}", error)
            await asyncio.sleep(FARM_PILOT_SECONDS)

    async def _farm_pilot_round(self) -> None:
        if not video_tools()[0]:
            return
        for channel in await self._farm.channels():
            if not channel.autopilot or not await self._farm.needs_more(channel):
                continue
            ideas = await self._farm.posts(channel.id, status="idea")
            post = ideas[-1] if ideas else None
            if post is None:
                made = await self._farm.ideas(channel, count=3, made_by="Autopilot")
                post = made[0]
            await self._farm_news(await self._farm.make(post.id), None)

    async def farm_chat(self) -> Chat:
        """The Content Farm's chat with the main AI, opening one if needed."""
        agent = await self.main_agent()
        for chat in await self._store.find(
            Chat, where={"agent_id": agent.id}, order_by="updated_at DESC"
        ):
            if chat.settings.get(FARM_CHAT_SETTING):
                return chat
        return await self.create_chat(
            agent_id=agent.id,
            title=f"{agent.name} in the Content Farm",
            settings={FARM_CHAT_SETTING: True},
        )

    async def farm_say(self, text: str, *, background: bool = True) -> Chat:
        """Ask the main AI for videos, ideas, or advice in the farm."""
        if not text.strip():
            raise StudioError("Say what to make.")
        chat = await self.farm_chat()
        self._farm_busy += 1
        self._farm_error = None
        if background:
            self.spawn(self._farm_turn(chat.id, text))
        else:
            await self._farm_turn(chat.id, text)
        return chat

    async def _farm_turn(self, chat_id: str, text: str) -> None:
        try:
            async with self._turn_lock(chat_id):
                result = await self.send(chat_id, text)
            if result.failed:
                self._farm_error = result.error or "The main AI did not finish."
        except (StudioError, StudioNotFoundError) as error:
            self._farm_error = str(error)
            await self._store.append_message(
                chat_id=chat_id,
                role="event",
                text=f"Could not answer: {error}",
                author="studio",
                data={"kind": "error"},
            )
        finally:
            self._farm_busy = max(0, self._farm_busy - 1)

    async def farm_console(self, *, after: int = 0) -> JsonObject:
        """The farm chat so far, and whether the main AI is still working."""
        chat = await self.farm_chat()
        messages = await self._store.transcript(chat.id, after=after)
        agent = await self.main_agent()
        return {
            "chat_id": chat.id,
            "agent": agent.name,
            "busy": self._farm_busy > 0,
            "error": self._farm_error,
            "messages": [message.model_dump() for message in messages],
        }

    async def _farm_tool(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        arguments = call.arguments
        action = str(arguments.get("action") or "").strip().lower()
        topic = " ".join(str(arguments.get("topic") or "").split())[:200]
        name = str(arguments.get("channel") or "").strip()
        asked = whole(arguments.get("count"), 0)
        count = max(1, min(10, asked or 1))
        made_by = context.agent_name or "An agent"
        data: JsonObject = {"tool": "farm", "action": action}
        try:
            if action == "channel":
                if not topic:
                    raise FarmError("Say what the channel is about.")
                channel = await self._farm.save_channel(
                    {
                        "niche": topic,
                        "style": str(arguments.get("style") or "facts"),
                        "fandom": str(arguments.get("fandom") or ""),
                    }
                )
                return ToolOutcome(
                    text=(
                        f"Added the channel @{channel.name} about {channel.niche} "
                        f"({farm_style_label(channel.style)} videos, "
                        f"{channel.seconds} seconds, posting at "
                        f"{', '.join(channel.post_times)}). Change its voice, look, "
                        "and posting times on the Content Farm page."
                    ),
                    data={**data, "channel_id": channel.id},
                )
            if action == "list":
                return ToolOutcome(text=await self._farm_list(), data=data)
            if action == "queue":
                return ToolOutcome(text=await self._farm_queue_text(), data=data)
            long = bool(arguments.get("long")) or bool(arguments.get("minutes"))
            kind = str(arguments.get("kind") or "").strip().lower()
            channel = await self._farm_channel_for(
                name,
                topic,
                long=long,
                minutes=whole(arguments.get("minutes"), 0),
                kind=kind if kind in {"cartoon", "edit"} else "",
            )
            if action == "make" and long and topic:
                return await self._farm_make_long(
                    channel, topic, made_by, context, data
                )
            if action == "ideas":
                count = asked or 5
                posts = await self._farm.ideas(
                    channel, count=count, topic=topic, made_by=made_by
                )
                lines = "\n".join(f"{n}. {p.title}" for n, p in enumerate(posts, 1))
                return ToolOutcome(
                    text=f"New ideas on @{channel.name}'s board:\n{lines}",
                    data={**data, "channel_id": channel.id},
                )
            if action == "make":
                ready, why = video_tools()
                if not ready:
                    raise FarmError(f"Videos can't be made on this PC yet: {why}")
                if topic:
                    posts = await self._farm.ideas(
                        channel, count=count, topic=topic, made_by=made_by
                    )
                else:
                    posts = list(
                        reversed(await self._farm.posts(channel.id, status="idea"))
                    )[:count]
                    if len(posts) < count:
                        posts += await self._farm.ideas(
                            channel, count=count - len(posts), made_by=made_by
                        )
                started = await self.farm_make(
                    [post.id for post in posts[:count]],
                    tell_chat=None
                    if context.chat_id == (await self.farm_chat()).id
                    else context.chat_id,
                )
                lines = "\n".join(
                    f"{n}. {p.title}" for n, p in enumerate(posts[:count], 1)
                )
                return ToolOutcome(
                    text=(
                        f"Making {started} video(s) for @{channel.name}, one after "
                        f"another (about a minute or two each):\n{lines}\nThey show "
                        "up in the posting queue on the Content Farm page, with the "
                        "caption and hashtags ready to paste."
                    ),
                    data={
                        **data,
                        "channel_id": channel.id,
                        "post_ids": [post.id for post in posts[:count]],
                    },
                )
        except FarmError as error:
            return ToolOutcome(text=str(error), data=data, failed=True)
        return ToolOutcome(
            text="Use action make, ideas, channel, list, or queue.",
            data=data,
            failed=True,
        )

    async def _farm_channel_for(
        self,
        name: str,
        topic: str,
        *,
        long: bool = False,
        minutes: int = 0,
        kind: str = "",
    ) -> FarmChannel:
        """The channel asked for; with none yet (or no long one for a long
        video), one made for the topic."""
        channels = await self._farm.channels()
        if long:
            mine = [c for c in channels if style_of(c.style).long]
            wanted = name.lower().lstrip("@")
            for channel in mine:
                if wanted and wanted in channel.name.lower():
                    return channel
            show = show_of(topic)
            for channel in mine:
                if show and channel.fandom and channel.fandom.lower() in topic.lower():
                    return channel
            if mine and not show:
                return mine[-1]
            style = (
                "what_if_sleep" if topic.lower().startswith("what if") else "lore_sleep"
            )
            fields: JsonObject = {
                "niche": show or topic,
                "style": style,
                "fandom": show,
            }
            if minutes:
                fields["minutes"] = minutes
            return await self._farm.save_channel(fields)
        if kind and not name:
            # 'make a cartoon about ...' goes to a cartoon channel (made if
            # there is none); 'make an edit ...' to a music edit channel.
            mine = [c for c in channels if style_of(c.style).kind == kind]
            if mine:
                return mine[-1]
            return await self._farm.save_channel(
                {
                    "niche": topic,
                    "style": "cartoon_story" if kind == "cartoon" else "beat_edit",
                }
            )
        if not channels and topic:
            return await self._farm.save_channel({"niche": topic})
        return await self._farm.find_channel(name)

    async def _farm_make_long(
        self,
        channel: FarmChannel,
        topic: str,
        made_by: str,
        context: ToolContext,
        data: JsonObject,
    ) -> ToolOutcome:
        """One two-hour video, titled from what was asked."""
        ready, why = video_tools()
        if not ready:
            raise FarmError(f"Videos can't be made on this PC yet: {why}")
        title = long_title(topic, style_of(channel.style).key)
        post = await self._farm.add_idea(channel, title, made_by=made_by)
        await self.farm_make(
            [post.id],
            tell_chat=None
            if context.chat_id == (await self.farm_chat()).id
            else context.chat_id,
        )
        return ToolOutcome(
            text=(
                f"Making a {channel.minutes // 60 or 1} hour video for @{channel.name}: "
                f"{title}. It writes {channel.minutes // 5} chapters with the fandom "
                "wiki's lore, records the calm voiceover, finds real stills and your "
                "clips, and renders it in 16:9: this takes a few hours on this PC. "
                "Watch it on the Content Farm page; what's done is kept if it stops."
            ),
            data={**data, "channel_id": channel.id, "post_ids": [post.id]},
        )

    async def _farm_list(self) -> str:
        channels = await self._farm.channels()
        if not channels:
            return "The Content Farm has no channels yet."
        lines = []
        for channel in channels:
            posts = await self._farm.posts(channel.id)
            count = dict.fromkeys(("idea", "making", "ready", "posted"), 0)
            for post in posts:
                if post.status in count:
                    count[post.status] += 1
            lines.append(
                f"- @{channel.name}: {channel.niche or 'no niche'} "
                f"({farm_style_label(channel.style)}); {count['idea']} ideas, "
                f"{count['making']} being made, {count['ready']} ready, "
                f"{count['posted']} posted"
                + (", autopilot on" if channel.autopilot else "")
            )
        return "\n".join(lines)

    async def _farm_queue_text(self) -> str:
        ready = await self._farm.queue()
        if not ready:
            return "No finished videos are waiting to be posted."
        names = {channel.id: channel.name for channel in await self._farm.channels()}
        return "\n".join(
            f"- {datetime.fromtimestamp(post.scheduled_at / 1000):%a %d %b %H:%M}: "
            f"@{names.get(post.channel_id, '?')}: {post.title}"
            for post in ready[:20]
        )

    async def _carry_out_farm(self, main: Agent, chat: Chat, text: str) -> str:
        """Videos, ideas, or a channel asked for in words, done before the main
        AI answers, so a small model never has to pick the farm tool."""
        in_farm = bool(chat.settings.get(FARM_CHAT_SETTING))
        job = farm_job(text, in_farm=in_farm)
        if job is None:
            return ""
        producer = None if in_farm else await self._team_member("farm")
        if producer is not None:
            return await self._hand_to_farm_agent(main, chat, producer, job)
        arguments: JsonObject = {
            "action": job.action,
            "topic": job.topic,
            "count": job.count,
            "long": job.long,
        }
        if job.minutes:
            arguments["minutes"] = job.minutes
        if job.channel:
            arguments["channel"] = job.channel
        if job.kind:
            arguments["kind"] = job.kind
        context = ToolContext(
            agent_id=main.id,
            chat_id=chat.id,
            site_id=chat.site_id,
            agent_name=main.name,
            agent_role=main.role,
        )
        outcome = await self._farm_tool(
            ToolCall(id="studio-farm", name="farm", arguments=arguments), context
        )
        await self._store.append_message(
            chat_id=chat.id,
            role="tool",
            text=outcome.text,
            author="farm",
            data={**outcome.data, "failed": outcome.failed, "order": True},
        )
        if outcome.failed:
            return (
                f"The user asked the Content Farm for {job.action} '{job.topic}', and "
                f"the farm said: {outcome.text}\nTell the user that in a sentence or two."
            )
        return (
            "Studio already did this in the Content Farm; it is on the farm page "
            f"and in this chat:\n{outcome.text[:LAB_NOTE_CHARS]}\nTell the user in "
            "your own words in a few sentences. Don't use the farm tool for it again."
        )

    async def _hand_to_farm_agent(
        self, main: Agent, chat: Chat, producer: Agent, job: FarmJob
    ) -> str:
        task = farm_task(job)
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
        try:
            outcome = await crew.ask_agent(
                context, agent=producer.name, task=task, project="", background=True
            )
        except (ValueError, StudioError) as error:
            return f"The {producer.name} agent could not take the farm job: {error}"
        await self._store.append_message(
            chat_id=chat.id,
            role="tool",
            text=outcome.text,
            author="ask_agent",
            data={**outcome.data, "order": True, "task": task},
        )
        return (
            f"The Content Farm job went to the {producer.name} agent ({task}), which "
            "is doing it now and reports here when done. Tell the user that in a "
            "sentence; don't use the farm tool for it yourself."
        )

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
        all_tools: bool = True,
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
                "all_tools": all_tools,
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
                "all_tools",
            }
        }
        if "all_tools" in allowed:
            allowed["all_tools"] = allowed["all_tools"] is True
        if "tools" in allowed and isinstance(allowed["tools"], list):
            chosen = tuple(dict.fromkeys(str(item) for item in allowed["tools"]))
            unknown = [tool for tool in chosen if tool not in TOOL_SPEC_BY_NAME]
            if unknown:
                raise StudioError(f"Unknown tools: {', '.join(unknown)}.")
            # finish is how an agent says it is done, so it always stays.
            allowed["tools"] = (*(t for t in chosen if t != "finish"), "finish")
        updated = agent.model_copy(update={**allowed, "updated_at": now_ms()})
        await self._store.put(updated)
        return updated

    async def delete_agent(self, agent_id: str) -> JsonObject:
        """Delete one agent with everything that is only its own.

        Its running tasks stop, and its chats, classes, waiting commands, and
        memories go. It leaves the rooms it was in; a room left empty goes.
        Projects it built stay, and so does what it wrote to the team's
        shared memory. The main AI and the Guide stay.
        """
        agent = await self._store.require(Agent, agent_id)
        if agent.role in {MAIN_ROLE, "guide"}:
            raise StudioError(
                f"{agent.name} can't be deleted: "
                + (
                    "it runs the team. Give it another model in Team brains instead."
                    if agent.role == MAIN_ROLE
                    else "it explains the app."
                )
            )
        await self.stop_agent_work(agent_id)
        # Rooms are shared: the agent leaves them, and only an empty room goes.
        chats = [
            chat
            for chat in await self._store.find(Chat, where={"agent_id": agent_id})
            if chat.kind != "room"
        ]
        chats += await self._store.find(Chat, where={"partner_agent_id": agent_id})
        for room in await self._store.find(Chat, where={"kind": "room"}):
            if agent_id not in room.member_ids and room.agent_id != agent_id:
                continue
            members = tuple(m for m in room.member_ids if m != agent_id)
            if not members:
                chats.append(room)
                continue
            await self._store.put(
                room.model_copy(
                    update={
                        "member_ids": members,
                        "agent_id": members[0]
                        if room.agent_id == agent_id
                        else room.agent_id,
                        "updated_at": now_ms(),
                    }
                )
            )
        for field in ("teacher_agent_id", "student_agent_id"):
            await self._store.delete_where(Course, {field: agent_id})
        for chat in chats:
            await self._store.delete_where(Message, {"chat_id": chat.id})
            await self._store.delete(ChatNotes, chat.id)
            await self._store.delete(Chat, chat.id)
        await self._store.delete_where(AgentRun, {"agent_id": agent_id})
        await self._store.delete_where(
            CommandRequest, {"agent_id": agent_id, "status": "pending"}
        )
        memories = 0
        for owner in (agent_id, server_area(agent_id)):
            memories += await self._store.count(MemoryEntry, where={"agent_id": owner})
            await self._store.delete_where(MemoryEntry, {"agent_id": owner})
        await self._store.delete(Agent, agent_id)
        self._console_extras = None
        return {
            "deleted": True,
            "name": agent.name,
            "chats": len(chats),
            "memories": memories,
        }

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
            note = await self._room_note(run) if chat.parent_chat_id else ""
            async with self._working(agent.id):
                finished = await self._runner().run_task(
                    agent,
                    chat,
                    run,
                    note=note,
                    fallback_model=await self._fallback_model(agent),
                )
            if chat.parent_chat_id:
                await self._share_in_room(agent, finished)
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
        await self._note_report(parent_id, chat, agent, run)
        await self._main_follows_up(parent_id, agent, run)

    async def _fallback_model(self, agent: Agent) -> str | None:
        """The main AI's model, for an agent whose own model fails mid-job:
        the main AI answering the user is the surest sign a model works."""
        main = await self.main_agent()
        model = main.model or self.default_model
        own = agent.model or self.default_model
        return None if agent.id == main.id or model == own else model

    async def team_check(self) -> list[JsonObject]:
        """Test every agent's model with one tiny message and post the results
        in the team room, so a broken brain shows up before a job needs it."""
        results: list[JsonObject] = []
        lines: list[str] = []
        for agent in await self.agents():
            if agent.archived or agent.role in CLASS_ROLES:
                continue
            model = agent.model or self.default_model
            using = await self.effective_model(model)
            outcome = await self.test_model(using)
            ok = bool(outcome["ok"])
            message = str(outcome["message"])
            results.append(
                {"agent": agent.name, "model": using, "ok": ok, "message": message}
            )
            mark = "✓" if ok and message == "Works." else "⚠" if ok else "✗"
            label = model_label(using)
            lines.append(
                f"{mark} {agent.name} ({label}): {message}"
                if message != "Works."
                else f"{mark} {agent.name} ({label}) works"
            )
        await self._post_in_room(
            "Studio", "Team check\n" + "\n".join(lines), {"kind": "team_check"}
        )
        return results

    def _turn_lock(self, chat_id: str) -> asyncio.Lock:
        """One turn at a time in a chat: an answer and a follow-up never mix."""
        return self._chat_turns.setdefault(chat_id, asyncio.Lock())

    async def _main_follows_up(
        self, parent_id: str, agent: Agent, run: AgentRun
    ) -> None:
        """The main AI reads a teammate's full report and tells the user what
        it found, in its own words, without waiting to be asked."""
        parent = await self._store.get(Chat, parent_id)
        main = await self.main_agent()
        if parent is None or parent.agent_id != main.id:
            return  # An agent's own helper reported back; it reads it itself.
        result = (await self._plain_result(run) or run.error or "").strip()
        job = " ".join(
            run.goal.split("\n\nBriefing from ")[0].removeprefix("The job: ").split()
        )
        report = FOLLOW_UP_PROMPT.format(
            agent=agent.name,
            status="finished"
            if run.status == "succeeded"
            else f"stopped ({run.status})",
            job=job[:300],
            result=result[:FOLLOW_UP_REPORT_CHARS] or "(no report)",
        )
        lab = bool(parent.settings.get(LAB_CHAT_SETTING))
        farm = bool(parent.settings.get(FARM_CHAT_SETTING))
        if lab:
            self._lab_busy += 1
        elif farm:
            self._farm_busy += 1
        else:
            self._main_busy += 1
        try:
            # Wait until the main AI has finished what it is saying now.
            async with self._turn_lock(parent.id), self._working(main.id):
                await self._runner().follow_up(main, parent, report)
        except (StudioError, StudioNotFoundError) as error:
            logger.warning("Studio: the main AI could not follow up: {}", error)
        finally:
            if lab:
                self._lab_busy = max(0, self._lab_busy - 1)
            elif farm:
                self._farm_busy = max(0, self._farm_busy - 1)
            else:
                self._main_busy = max(0, self._main_busy - 1)

    async def _note_report(
        self, parent_id: str, chat: Chat, agent: Agent, run: AgentRun
    ) -> None:
        summary = (await self._plain_result(run) or run.error or "").strip()[:600]
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
        if agent.role == "coder":
            return max(settings.studio_coder_max_steps, settings.studio_agent_max_steps)
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
        lab = await self._carry_out_lab(main, chat, text)
        if not lab:
            lab = await self._carry_out_farm(main, chat, text)
        orders = "" if lab else await self._carry_out_orders(main, chat, text)
        learning = await self._carry_out_learning(chat, text, started_by=main.name)
        weather = await self._carry_out_weather(chat, text)
        # Studio did the job already: the playbook's tool examples would only
        # push a small model to do it a second time.
        done = any((lab, orders, learning, weather))
        playbook = await self._playbook_guide(text, rules_only=done)
        return "\n".join(
            part
            for part in (
                now_line(datetime.now()),
                lab,
                orders,
                learning,
                weather,
                playbook,
            )
            if part
        )

    async def _playbook_guide(self, text: str, *, rules_only: bool) -> str:
        if not self.settings.studio_jarvis_playbook:
            return ""
        try:
            return await self._playbook().guide(text, rules_only=rules_only)
        except OSError as error:
            logger.warning("Jarvis's playbook could not be read: {}", error)
            return ""

    async def _own_job(self, text: str) -> str:
        """The main AI's own tool for this message ('remind me...' is a to-do,
        not a job for the Helper), so the one-word router never hands it out."""
        notes = starter_notes()
        if self.settings.studio_jarvis_playbook:
            with contextlib.suppress(OSError):
                notes = await self._playbook().notes()
        return own_tool(notes, text)

    async def _learn_call(self, said: str, call: ToolCall) -> None:
        """A call the main AI made that worked becomes a playbook example."""
        try:
            await self._playbook().learn(call.name, said, call.arguments)
        except (OSError, PlaybookError) as error:
            logger.warning("Jarvis's playbook could not learn: {}", error)

    async def _weather(self, place: str, *, days: int = 3) -> str:
        if self.settings.studio_web_access == "off":
            raise ValueError("Web access is off in Studio settings.")
        try:
            return await forecast(place, days=days, transport=self._search_transport)
        except WeatherError as error:
            raise ValueError(str(error)) from error

    async def _carry_out_weather(self, chat: Chat, text: str) -> str:
        """'What's the weather in Sydney?' fetches it before the main AI answers."""
        place = weather_request(text)
        if place is None or self.settings.studio_web_access == "off":
            return ""
        try:
            report = await self._weather(place)
        except ValueError as error:
            return f"The weather for {place} could not be fetched: {error}"
        await self._store.append_message(
            chat_id=chat.id,
            role="tool",
            text=report,
            author="weather",
            data={"tool": "weather", "place": place, "order": True},
        )
        return f"{report}\nTell the user the weather they asked about in a sentence or two."

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
            case "manage_agent":
                return await self._manage_agent_tool(call, context)
            case "lab":
                return await self._lab_tool(call, context)
            case "farm":
                return await self._farm_tool(call, context)
            case "code_and_test":
                return await self._code_tool(call, context)
            case "skill":
                return await self._skill_tool(call)
            case "mcp":
                return await self._mcp_tool(call)
            case "weather":
                place = str(call.arguments.get("place") or "").strip()
                if not place:
                    raise ValueError("Say which town or city.")
                days = call.arguments.get("days")
                return ToolOutcome(
                    text=await self._weather(
                        place, days=days if isinstance(days, int) else 3
                    ),
                    data={"tool": "weather", "place": place},
                )
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
            await self._memory().context_block(
                main.id, goal, everyone=self.settings.studio_main_own_memory
            )
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

    # ------------------------------------------------------------ FCC Phone

    def phone_pairing_code(self) -> JsonObject:
        """A code to type into FCC Phone to pair it with this PC."""
        return {"code": self._phones.new_code(), "expires_in": PAIR_SECONDS}

    async def phone_links(self) -> JsonObject:
        """Paired phones, and the https address a phone can reach this PC on."""
        return {
            "phones": [link_view(link) for link in await self._phones.links()],
            "tailscale": await tailscale_address(),
        }

    async def phone_unlink(self, link_id: str) -> bool:
        return await self._phones.unlink(link_id)

    async def phone_auth(self, token: str) -> PhoneLink:
        return await self._phones.check(token)

    async def phone_pair(self, code: str, name: str) -> JsonObject:
        link, token = await self._phones.pair(code, name)
        return {"token": token, "link": link_view(link)} | await self.phone_hello(link)

    async def phone_hello(self, link: PhoneLink) -> JsonObject:
        """Who this PC is, and whether its main AI thinks on this PC."""
        main = await self.main_agent()
        model = await self.effective_model(main.model or self.default_model)
        return {
            "pc": socket.gethostname(),
            "version": package_version(),
            "main": main.name,
            "model": model,
            # Memory from the PC may only go to a brain that runs on the PC.
            "private": self.runs_on_this_pc(model),
            "phone": link.name,
        }

    async def phone_sync(self, link: PhoneLink, memories: JsonValue) -> JsonObject:
        """Take the phone's new memories into team memory; send the PC's back."""
        memory = self._memory()
        main = await self.main_agent()
        stored = 0
        for agent, text in incoming_memories(memories):
            kept = await memory.share(
                text,
                author=f"{agent} (phone)",
                tags=(PHONE_TAG,),
                source="phone",
            ) or await memory.remember(
                main.id, text, tags=(PHONE_TAG,), source="phone", author=agent
            )
            if kept is not None:
                stored += 1
        if stored:
            await self._after_memory_change([SHARED_MEMORY_ID, main.id], wait=False)
        await self._phones.note_sync(link, stored)
        owners = [SHARED_MEMORY_ID, main.id]
        pc: list[JsonObject] = []
        for owner in owners:
            for entry in await memory.entries(owner, scope="long_term"):
                if PHONE_TAG in entry.tags or SKILL_TAG in entry.tags:
                    continue  # the phone already has its own; skills are the PC's
                pc.append(
                    {
                        "id": entry.id,
                        "text": entry.text[:MAX_MEMORY_CHARS],
                        "author": entry.author
                        or (main.name if owner == main.id else "team"),
                        "created_at": entry.created_at,
                    }
                )
        pc.sort(key=lambda row: -int(str(row["created_at"])))
        return {
            "stored": stored,
            "pc_memories": list(pc[:MAX_PULL]),
            "private": (await self.phone_hello(link))["private"],
        }

    async def phone_search(self, link: PhoneLink, query: str) -> JsonObject:
        """Search the web with the PC's search setup, for a phone agent."""
        del link
        if self.settings.studio_web_access == "off":
            raise PhoneLinkError("Web access is off in Studio settings on the PC.")
        try:
            report = await self._search().search(query[:300], limit=6)
        except (SearchError, ValueError) as error:
            raise PhoneLinkError(f"Search failed: {error}") from error
        return {
            "provider": report.provider,
            "results": [
                {"title": hit.title, "url": hit.url, "snippet": hit.snippet}
                for hit in report.hits
            ],
        }

    async def phone_complete(self, link: PhoneLink, payload: JsonObject) -> JsonObject:
        """Think with the main AI's model on this PC, for the phone."""
        main = await self.main_agent()
        model = await self.effective_model(main.model or self.default_model)
        messages = chat_messages(payload.get("messages"))
        tools = tool_specs(payload.get("tools"))
        system = str(payload.get("system") or "")[:20_000]
        try:
            reply = await self._router.complete(
                messages,
                system=system,
                tools=tools,
                model=model,
                temperature=0.4,
                max_tokens=MAX_REPLY_TOKENS,
            )
        except StudioLLMError as error:
            raise PhoneLinkError(f"The PC's AI didn't answer: {error}") from error
        return reply_json(reply) | {"model": reply.model or model}

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
            *self.server_model_list(),
        ):
            if model and model not in known:
                known.append(model)
        return known

    def server_model_list(self) -> list[str]:
        """Models on the server AIs that have a key (from the provider list)."""
        try:
            return sorted(set(self._server_models()))
        except Exception as error:  # the list is a convenience, never fatal
            logger.info("Studio: server models unavailable: {}", error)
            return []

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
            "server": self.server_model_list(),
            "agents": rows,
            "local": await self.local_models(),
            "turns": self.settings.studio_local_model_turns,
            "private_memory": self.settings.studio_private_memory,
            "working": [model_label(m) for m in turns.working],
            "waiting": [model_label(m) for m in turns.waiting],
        }

    async def test_model(self, model: str) -> JsonObject:
        """Send one tiny message to a model, as Team brains' Test button does."""
        model = model.strip()
        if not model:
            raise StudioError("Pick a model to test.")
        try:
            await self._router.complete(
                [ChatMessage.user("Reply with the word OK.")],
                model=model,
                max_tokens=8,
                swap=False,
            )
        except StudioLLMError as error:
            text = str(error)
            return {
                "model": model,
                "ok": False,
                "message": "Not available for your key: the provider lists it "
                "but won't run it. Pick another."
                if model_missing(text)
                else text[:300],
            }
        room = await self._router.context_length(model)
        if room is not None and room < ROOM_NEEDED:
            return {
                "model": model,
                "ok": True,
                "message": f"Works, but LM Studio loaded it with room for only "
                f"{room} tokens; agents need {ROOM_NEEDED} or more, or replies come "
                "back empty or cut off. In LM Studio, reload it with Context Length "
                f"{ROOM_NEEDED}.",
            }
        return {"model": model, "ok": True, "message": "Works."}

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
        abilities: dict[str, set[str]] = {}
        with contextlib.suppress(OSError, EngineError):
            for found in await self._engine.models():
                can = {
                    ability
                    for ability, yes in (
                        ("tools", found.info.tools),
                        ("reasoning", found.info.reasoning),
                        ("vision", found.vision is not None),
                    )
                    if yes
                }
                abilities[f"{LOCAL_MODEL_PREFIX}{found.name}"] = can
        return suggest_mix(team, models, abilities)

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

    async def _manage_agent_tool(
        self, call: ToolCall, context: ToolContext | None = None
    ) -> ToolOutcome:
        """Control over agents' tools and memory: every agent for the main AI,
        the agents on server AIs for an agent on this PC."""
        action = str(call.arguments.get("action") or "show").strip().lower()
        spoken = str(call.arguments.get("agent") or "").strip()
        directs = context.directs if context is not None else None
        caller = context.agent_name if context is not None else "Jarvis"
        if action == "show" and not spoken:
            lines = []
            for member in await self.agents():
                if member.archived or (
                    context is not None and not context.may_direct(member.name)
                ):
                    continue
                using = await self.tools_in_use(member)
                where = (
                    "server AI, own memory area"
                    if await self.is_private_from(member)
                    else "this PC"
                )
                lines.append(
                    f"- {member.name} ({member.role}): {member.model}, {where}; "
                    + (
                        "every tool"
                        if self.has_every_tool(member)
                        else f"its own {len(using)} tools"
                    )
                    + f", about {tool_tokens(using):,} tokens of tools"
                )
            return ToolOutcome(
                text="The team:\n" + "\n".join(lines),
                data={"tool": "manage_agent", "action": "show"},
            )
        member = await self._find_team_member(spoken)
        if context is not None and not context.may_direct(member.name):
            mine = ", ".join(directs or ()) or "nobody right now"
            raise ValueError(
                f"{member.name} thinks on this PC; only the main AI manages "
                f"agents on this PC. You manage: {mine}."
            )
        private = await self.is_private_from(member)
        owner = server_area(member.id) if private else member.id
        where = (
            f"{member.name}'s own memory area" if private else f"{member.name}'s memory"
        )
        data: JsonObject = {
            "tool": "manage_agent",
            "action": action,
            "agent": member.name,
            "agent_id": member.id,
        }
        match action:
            case "show":
                entries = await self._memory().entries(owner)
                text = (
                    f"{member.name} ({member.role}) thinks with {member.model} "
                    + ("on a server AI. " if private else "on this PC. ")
                    + (
                        "It has every tool. "
                        if self.has_every_tool(member)
                        else f"It has its own tools: {', '.join(member.tools)}. "
                    )
                    + (
                        f"{where.capitalize()}:\n"
                        + "\n".join(f"- {entry.text[:200]}" for entry in entries[:20])
                        if entries
                        else f"{where.capitalize()} is empty."
                    )
                )
            case "every_tool_on" | "every_tool_off":
                on = action == "every_tool_on"
                await self.set_every_tool(member.id, on)
                text = (
                    f"{member.name} now has every tool."
                    if on
                    else f"{member.name} now uses only its own tools, which "
                    "uses fewer tokens."
                )
                if on and not self.settings.studio_all_tools:
                    text += (
                        " Every Agent Gets Every Tool is off in Settings, so it "
                        "takes effect when that is turned on."
                    )
            case "tool_on" | "tool_off":
                tool = str(call.arguments.get("tool") or "").strip()
                if tool not in TOOL_SPEC_BY_NAME or tool == "finish":
                    raise ValueError(f"No tool called {tool!r}.")
                if tool in MAIN_ONLY_TOOLS and member.role != MAIN_ROLE:
                    raise ValueError(f"Only the main AI has {tool}.")
                on = action == "tool_on"
                tools = [t for t in member.tools if t != tool]
                if on:
                    tools.append(tool)
                await self.update_agent(member.id, {"tools": tools})
                text = (
                    f"{member.name} {'has' if on else 'no longer has'} {tool}."
                    + (
                        " It has every tool right now, so this is what it keeps "
                        "when every tool is off."
                        if self.has_every_tool(member)
                        else ""
                    )
                    + (
                        " It runs on a server AI, so it can't use that one."
                        if on and private and tool in SEALED_TOOLS
                        else ""
                    )
                )
            case "add_memory":
                note = str(call.arguments.get("text") or "").strip()
                if not note:
                    raise ValueError("Say what to save.")
                entry = await self._memory().remember(
                    owner, note, source="main_ai", author=caller
                )
                if entry is None:
                    raise ValueError("Nothing to save.")
                await self._after_memory_change([owner])
                text = f"Saved to {where}: {entry.text}"
            case "forget":
                removed = await self._memory().clear(owner)
                await self._after_memory_change([owner])
                text = f"Cleared {where} ({removed} memories)."
            case _:
                raise ValueError(
                    "Use show, every_tool_on, every_tool_off, tool_on, tool_off, "
                    "add_memory, or forget."
                )
        return ToolOutcome(text=text, data=data)

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

    async def _carry_out_lab(self, main: Agent, chat: Chat, text: str) -> str:
        """Make or mix in the Lab before the main AI answers.

        'make shampoo in the lab' from the main chat goes to the Lab agent when
        the team has one; in the Lab's own chat, or with no Lab agent, Studio
        does it at once. Either way a small model never has to pick the tool.
        """
        in_lab = bool(chat.settings.get(LAB_CHAT_SETTING))
        job = lab_job(text, in_lab=in_lab)
        if job is None:
            return ""
        scientist = None if in_lab else await self._team_member("lab")
        if scientist is not None:
            return await self._hand_to_lab_agent(
                main, chat, scientist, job.request, job.action
            )
        arguments: JsonObject = {"action": job.action, "request": job.request}
        if job.action == "mix":
            arguments |= {"items": job.items, "heat": job.heat, "flame": job.flame}
        context = ToolContext(
            agent_id=main.id,
            chat_id=chat.id,
            site_id=chat.site_id,
            agent_name=main.name,
            agent_role=main.role,
        )
        outcome = await self._lab_tool(
            ToolCall(id="studio-lab", name="lab", arguments=arguments), context
        )
        await self._store.append_message(
            chat_id=chat.id,
            role="tool",
            text=outcome.text,
            author="lab",
            data={**outcome.data, "failed": outcome.failed, "order": True},
        )
        if outcome.failed:
            return (
                f"The user asked the Lab to {job.action} '{job.request}', and the Lab "
                f"said: {outcome.text}\nTell the user that in a sentence or two."
            )
        return (
            f"Studio already did this in the Lab ({job.action} '{job.request}'); it "
            f"is on the Lab bench and in this chat:\n{outcome.text[:LAB_NOTE_CHARS]}\n"
            "Tell the user the result in your own words in a few sentences. Don't "
            "use the lab tool for it again."
        )

    # ----------------------------------------------------------- extensions

    async def extensions(self) -> list[Extension]:
        """Every repo added from GitHub, plus servers added by hand."""
        return await self._extensions.all()

    async def add_extension(self, link: str) -> Extension:
        try:
            return await self._extensions.add_github(link)
        except ExtensionError as error:
            raise StudioError(str(error)) from error

    async def ensure_starters(self) -> list[Extension]:
        """Add every starter repo not added before; a removed one stays removed.

        A starter that came with FCC installs from its checked copy with no
        download. One whose licence keeps it out of FCC comes from GitHub and
        is kept in the vault; if GitHub can't be reached it is tried again on
        the next load."""
        if self._starter_folder is None or self._starters_checked:
            return []
        async with self._starters_lock:
            if self._starters_checked:
                return []
            if await self._store.get(StudioFlag, AGENT_RESCAN_FLAG) is None:
                # 6.61.0 counted any note in an agents folder as an agent.
                for extension in await self._extensions.all():
                    await self._extensions.rescan_agents(extension)
                await self._store.put(StudioFlag(id=AGENT_RESCAN_FLAG, value="1"))
            for flag, extra in (
                (OWN_MEMORY_FLAG, OWN_MEMORY_TOOLS),
                (TOOLSHED_FLAG, (TOOLSHED_TOOL,)),
            ):
                if await self._store.get(StudioFlag, flag) is None:
                    await self._give_repo_agents(extra)
                    await self._store.put(StudioFlag(id=flag, value="1"))
            added: list[Extension] = []
            waiting = False
            present = {e.source.lower(): e.id for e in await self._extensions.all()}
            for starter in load_starters(self._starter_folder):
                if await self._store.get(StudioFlag, starter.flag) is not None:
                    continue
                if starter.source.lower() in present:
                    # Added already (by hand, or a load cut short): never twice.
                    await self._store.put(
                        StudioFlag(
                            id=starter.flag, value=present[starter.source.lower()]
                        )
                    )
                    continue
                try:
                    extension = await self._add_starter(starter)
                except (ExtensionError, OSError) as error:
                    logger.warning(
                        "Starter repo {} not added: {}", starter.full_name, error
                    )
                    waiting = True
                    continue
                await self._store.put(StudioFlag(id=starter.flag, value=extension.id))
                added.append(extension)
            self._starters_checked = not waiting
            return added

    async def _give_repo_agents(self, extra: Sequence[str]) -> None:
        """Give the repo agents already on the team tools added since."""
        prompts = {
            (definition.name, definition.prompt.strip())
            for extension in await self._extensions.all()
            for definition in extension.agents
        }
        for agent in await self._store.find(Agent):
            if (
                agent.all_tools
                or (agent.name, agent.system_prompt.strip()) not in prompts
            ):
                continue
            missing = [tool for tool in extra if tool not in agent.tools]
            if missing:
                await self.update_agent(agent.id, {"tools": [*agent.tools, *missing]})

    async def _add_starter(self, starter: StarterRepo) -> Extension:
        folder = self._starter_folder
        if starter.bundled and folder is not None:
            data = await anyio.to_thread.run_sync(bundled_bytes, folder, starter)
            return await self._extensions.add_archive(
                owner=starter.owner,
                repo=starter.repo,
                data=data,
                origin="bundled",
                ref=starter.commit,
                source=starter.source,
                file_name=starter.file,
            )
        return await self._extensions.add_github(starter.source)

    async def starters(self) -> list[JsonObject]:
        """The repos that come with FCC, and whether each is added now."""
        added = {e.source.lower(): e for e in await self._extensions.all()}
        rows: list[JsonObject] = []
        for starter in load_starters(self._starter_folder):
            extension = added.get(starter.source.lower())
            rows.append(
                {
                    "name": starter.full_name,
                    "source": starter.source,
                    "about": starter.about,
                    "licence": starter.licence,
                    "commit": starter.commit,
                    "bundled": starter.bundled,
                    "left_out": starter.left_out,
                    "extension_id": extension.id if extension else "",
                    "skills": len(extension.skills) if extension else 0,
                }
            )
        return rows

    async def add_starter(self, name: str) -> Extension:
        """Add one starter repo again (after it was removed)."""
        wanted = name.strip().lower()
        starter = next(
            (
                s
                for s in load_starters(self._starter_folder)
                if s.full_name.lower() == wanted
            ),
            None,
        )
        if starter is None:
            raise StudioError(f"{name} isn't one of the repos that come with FCC.")
        try:
            extension = await self._add_starter(starter)
        except ExtensionError as error:
            raise StudioError(str(error)) from error
        await self._store.put(StudioFlag(id=starter.flag, value=extension.id))
        return extension

    async def upload_extension(self, file_name: str, data: bytes) -> Extension:
        """A repo zip from the user's PC, added like a GitHub link and kept in
        the vault so it can be added again later. Its files are only read:
        nothing in it runs, and its MCP servers start switched off."""
        stem = Path(file_name.replace("\\", "/")).name.rsplit(".", 1)[0]
        name = re.sub(r"[^\w.-]+", "-", stem).strip("-.")[:60] or "repo"
        try:
            return await self._extensions.add_archive(
                owner=UPLOAD_OWNER,
                repo=name,
                data=data,
                origin="upload",
                source=f"upload:{name}",
                file_name=f"{name}.zip",
            )
        except ExtensionError as error:
            raise StudioError(str(error)) from error

    async def restore_extension(self, item_id: str) -> Extension:
        """Add a repo again from its copy in the vault."""
        try:
            return await self._extensions.restore(item_id)
        except ExtensionError as error:
            raise StudioError(str(error)) from error

    async def remove_extension(self, ext_id: str) -> None:
        extension = await self._extension(ext_id)
        for server in extension.servers:
            await self._mcp.stop(f"{ext_id}/{server.name}")
        await self._extensions.remove(ext_id)

    async def _extension(self, ext_id: str) -> Extension:
        try:
            return await self._extensions.get(ext_id)
        except ExtensionError as error:
            raise StudioNotFoundError(str(error)) from error

    async def switch_server(self, ext_id: str, name: str, *, on: bool) -> Extension:
        """Turn one MCP server on or off; on means agents may start it."""
        extension = await self._extension(ext_id)
        server = next((s for s in extension.servers if s.name == name), None)
        if server is None:
            raise StudioNotFoundError(f"{extension.name} has no server {name}.")
        server.enabled = on
        if not on:
            await self._mcp.stop(f"{ext_id}/{name}")
        return await self._extensions.save(extension)

    async def add_server(
        self,
        *,
        name: str,
        command: str = "",
        args: Sequence[str] = (),
        url: str = "",
        env: Mapping[str, str] | None = None,
    ) -> Extension:
        """An MCP server the user typed in, switched on."""
        if not name.strip() or not (command.strip() or url.strip()):
            raise StudioError("A server needs a name and a command or a web address.")
        return await self._extensions.add_server(
            McpServer(
                name=name.strip(),
                command=command.strip(),
                args=[str(arg) for arg in args],
                url=url.strip(),
                env=dict(env or {}),
            )
        )

    async def check_server(self, ext_id: str, name: str) -> list[McpTool]:
        """Start one server and list its tools, so the user sees it works."""
        extension = await self._extension(ext_id)
        server = next((s for s in extension.servers if s.name == name), None)
        if server is None:
            raise StudioNotFoundError(f"{extension.name} has no server {name}.")
        try:
            return await self._mcp.tools(self._server_spec(extension, server))
        except McpError as error:
            raise StudioError(str(error)) from error

    def _server_spec(self, extension: Extension, server: McpServer) -> ServerSpec:
        files = self._extensions.folder / extension.id / "files"
        return ServerSpec(
            key=f"{extension.id}/{server.name}",
            name=server.name,
            command=server.command,
            args=tuple(server.args),
            env=tuple(server.env.items()),
            url=server.url,
            headers=tuple(server.headers.items()),
            cwd=str(files) if files.is_dir() else None,
        )

    async def add_extension_agent(self, ext_id: str, name: str) -> Agent:
        """Make one of a plugin's agents a member of the team."""
        extension = await self._extension(ext_id)
        found = next((a for a in extension.agents if a.name == name), None)
        if found is None:
            raise StudioNotFoundError(f"{extension.name} has no agent {name}.")
        # Someone else wrote its instructions, so it gets only the tools it
        # asks for, not every tool (the user can give it more on its card),
        # plus remember and recall for its own memory, and the toolshed to
        # pick up more for a job.
        tools = tuple(dict.fromkeys((*_studio_tools(found.tools), *REPO_AGENT_EXTRAS)))
        return await self.create_agent(
            name=found.name,
            role="agent",
            model=self.server_model,
            system_prompt=found.prompt,
            description=found.description or f"From {extension.name}.",
            tools=tools,
            all_tools=False,
        )

    async def _enabled_servers(self) -> list[tuple[Extension, McpServer]]:
        return [
            (extension, server)
            for extension in await self._extensions.all()
            for server in extension.servers
            if server.enabled
        ]

    async def _skill_tool(self, call: ToolCall) -> ToolOutcome:
        action = str(call.arguments.get("action") or "list").lower()
        if not self._starters_lock.locked():
            # Mid-install (on startup) the tool uses what's added so far.
            await self.ensure_starters()
        everything = [
            (extension, skill)
            for extension in await self._extensions.all()
            for skill in extension.skills
        ]
        if action == "search":
            return await self._skill_search(call, everything)
        repo = str(call.arguments.get("repo") or "").strip()
        file = str(call.arguments.get("file") or "").strip()
        if action == "read" and repo and file:
            line = call.arguments.get("line")
            around = (
                int(line)
                if isinstance(line, int | float | str) and str(line).isdigit()
                else 0
            )
            text = await self._extensions.read_file(repo, file, around=around)
            return ToolOutcome(
                text=f"{repo}/{file}"
                + (f" (around line {around})" if around else "")
                + f":\n{text}",
                data={"tool": "skill", "repo": repo, "file": file},
            )
        if action == "read":
            wanted = (
                str(call.arguments.get("name") or "").strip().lstrip("/").casefold()
            )
            match = next(
                (
                    pair
                    for pair in everything
                    if pair[1].name.lstrip("/").casefold() == wanted
                ),
                None,
            ) or next(
                (
                    pair
                    for pair in everything
                    if wanted and wanted in pair[1].name.casefold()
                ),
                None,
            )
            if match is None:
                raise ValueError(
                    f"No skill is called '{wanted}'. Use action list to see them."
                )
            extension, skill = match
            text = await self._extensions.skill_text(extension, skill)
            return ToolOutcome(
                text=f"Skill {skill.name} (from {extension.name}):\n{text}",
                data={"tool": "skill", "name": skill.name},
            )
        if not everything:
            return ToolOutcome(
                text="No skills are added yet. The user adds them on the More page "
                "(Add from GitHub).",
                data={"tool": "skill"},
            )
        if repo:
            everything = [
                pair
                for pair in everything
                if repo.casefold() in pair[0].name.casefold()
            ]
        if len(everything) <= 80:
            lines = [
                f"- {skill.name}: {skill.description or '(no description)'} [{extension.name}]"
                for extension, skill in everything
            ]
            return ToolOutcome(
                text="Skills:\n" + "\n".join(lines), data={"tool": "skill"}
            )
        # Big skill repos (hundreds of skills) are shown per repo; search finds
        # the right one.
        counts: dict[str, int] = {}
        for extension, _ in everything:
            counts[extension.name] = counts.get(extension.name, 0) + 1
        lines = [f"- {name}: {count} skills" for name, count in counts.items()]
        return ToolOutcome(
            text=f"{len(everything)} skills in {len(counts)} repos:\n"
            + "\n".join(lines)
            + "\nUse action search with a query to find the right skill or guide, "
            "or action list with repo to list one repo's skills.",
            data={"tool": "skill"},
        )

    async def _skill_search(
        self, call: ToolCall, everything: list[tuple[Extension, Skill]]
    ) -> ToolOutcome:
        query = str(call.arguments.get("query") or call.arguments.get("name") or "")
        words = [w for w in re.findall(r"[a-z0-9+#]+", query.casefold()) if len(w) > 1]
        if not words:
            raise ValueError("search needs a query, like 'kubernetes security'.")
        scored: list[tuple[int, Extension, Skill]] = []
        for extension, skill in everything:
            name = skill.name.casefold()
            blurb = skill.description.casefold()
            score = sum(3 for w in words if w in name) + sum(
                1 for w in words if w in blurb
            )
            if score:
                scored.append((score, extension, skill))
        scored.sort(key=lambda item: -item[0])
        parts: list[str] = []
        if scored:
            parts.append("Skills (read one with action read and its name):")
            parts += [
                f"- {skill.name}: {skill.description[:200] or '(no description)'} [{extension.name}]"
                for _, extension, skill in scored[:12]
            ]
        found = await self._extensions.search(query)
        if found:
            parts.append(
                "In the added repos' guides and lists (read more with action read, "
                "repo, file and line):"
            )
            parts += [
                f"- {hit['repo']}/{hit['file']}:{hit['line']}: {hit['text']}"
                for hit in found
            ]
        if not parts:
            return ToolOutcome(
                text=f"Nothing in the added repos matches '{query}'.",
                data={"tool": "skill"},
            )
        return ToolOutcome(text="\n".join(parts), data={"tool": "skill"})

    async def _mcp_tool(self, call: ToolCall) -> ToolOutcome:
        action = str(call.arguments.get("action") or "servers").lower()
        servers = await self._enabled_servers()
        if action == "servers" or not servers:
            if not servers:
                return ToolOutcome(
                    text="No MCP servers are switched on. The user adds and turns "
                    "them on on the More page (Add from GitHub).",
                    data={"tool": "mcp"},
                )
            lines = [
                f"- {server.name} [{extension.name}]" for extension, server in servers
            ]
            return ToolOutcome(
                text="MCP servers:\n" + "\n".join(lines), data={"tool": "mcp"}
            )
        wanted = str(call.arguments.get("server") or "").strip().casefold()
        pair = next((p for p in servers if p[1].name.casefold() == wanted), None) or (
            servers[0] if len(servers) == 1 and not wanted else None
        )
        if pair is None:
            raise ValueError(
                f"No switched-on server is called '{wanted}'. Servers: "
                + ", ".join(server.name for _, server in servers)
            )
        extension, server = pair
        spec = self._server_spec(extension, server)
        try:
            if action == "tools":
                tools = await self._mcp.tools(spec)
                lines = [
                    f"- {tool.name}: {tool.description[:200]}"
                    f"{short_arguments(tool.schema)}"
                    for tool in tools
                ]
                return ToolOutcome(
                    text=f"{server.name} tools:\n" + "\n".join(lines),
                    data={"tool": "mcp", "server": server.name},
                )
            tool = str(call.arguments.get("tool") or "").strip()
            if not tool:
                raise ValueError("Say which tool to call; list them with action tools.")
            arguments = call.arguments.get("arguments")
            text, failed = await self._mcp.call(
                spec, tool, arguments if isinstance(arguments, dict) else {}
            )
        except McpError as error:
            raise ValueError(str(error)) from error
        return ToolOutcome(
            text=text,
            data={"tool": "mcp", "server": server.name, "called": tool},
            failed=failed,
        )

    # ------------------------------------------------------------ agents API

    async def api_agents(self) -> list[Agent]:
        """The agents other apps may talk to: everyone but the archived."""
        await self.ensure_defaults()
        return [agent for agent in await self.agents() if not agent.archived]

    async def api_ask(
        self, name: str, text: str, *, conversation: str = "", wait: bool = False
    ) -> tuple[Agent, str]:
        """Send one message to an agent by name (or 'jarvis'/'main' for the main
        AI) in its API chat, and return the agent and its reply. With wait,
        the reply also carries what teammates reported back."""
        if not text.strip():
            raise StudioError("Send a message with some text.")
        wanted = name.strip().casefold()
        agents = await self.api_agents()
        agent = next((a for a in agents if a.name.casefold() == wanted), None)
        if agent is None and wanted in {"main", "jarvis", "studio", ""}:
            agent = await self.main_agent()
        if agent is None:
            raise StudioNotFoundError(
                f"No agent is called '{name}'. Agents: "
                + ", ".join(a.name for a in agents)
            )
        title = f"API · {conversation.strip()[:40] or 'default'}"
        chat = next(
            (
                c
                for c in await self._store.find(Chat, where={"agent_id": agent.id})
                if c.title == title
            ),
            None,
        ) or await self.create_chat(agent_id=agent.id, title=title, kind="chat")
        before = await self._store.transcript(chat.id)
        last = before[-1].sequence if before else 0
        result = await self.send(chat.id, text)
        if not wait:
            return agent, result.text
        await self.wait_for_background()
        said = [
            message.text
            for message in await self._store.transcript(chat.id, after=last)
            if message.role == "assistant" and message.text.strip()
        ]
        return agent, "\n\n".join(dict.fromkeys(said)) or result.text

    async def _team_member(self, role: str) -> Agent | None:
        """The first working agent with this role, if the team has one."""
        return next(
            (
                agent
                for agent in await self.agents()
                if agent.role == role and not agent.archived
            ),
            None,
        )

    async def _hand_to_lab_agent(
        self, main: Agent, chat: Chat, scientist: Agent, request: str, action: str
    ) -> str:
        task = f"{action.capitalize()} {request} in the Lab."
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
        try:
            outcome = await crew.ask_agent(
                context, agent=scientist.name, task=task, project="", background=True
            )
        except (ValueError, StudioError) as error:
            return f"The {scientist.name} agent could not take the Lab job: {error}"
        await self._store.append_message(
            chat_id=chat.id,
            role="tool",
            text=outcome.text,
            author="ask_agent",
            data={**outcome.data, "order": True, "task": task},
        )
        return (
            f"The Lab job went to the {scientist.name} agent ({action} '{request}'), "
            "which is doing it in the Lab now and reports here when done. Tell the "
            "user that in a sentence; don't use the lab tool for it yourself."
        )

    async def _code_tool(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        goal = str(call.arguments.get("goal") or "").strip()
        if not goal:
            raise ValueError("Say what to code.")
        line = await self.start_code_loop(
            goal,
            project=str(call.arguments.get("project") or ""),
            parent_chat_id=context.chat_id,
            caller=context,
        )
        return ToolOutcome(text=line, data={"tool": "code_and_test", "goal": goal})

    async def start_code_loop(
        self,
        goal: str,
        *,
        project: str = "",
        parent_chat_id: str | None,
        caller: ToolContext | None = None,
    ) -> str:
        """Start the Coder and the Tester on a job in the background; the
        sentence returned says who is doing what."""
        coder = await self._team_member("coder")
        tester = await self._team_member("tester")
        if coder is None or tester is None:
            raise StudioError(
                "The team needs a Coder and a Tester for this; add them with the + button."
            )
        key = " ".join(goal.casefold().split())
        if key in self._code_loops:
            return (
                f"{coder.name} and {tester.name} are already on this and will "
                "report here when done."
            )
        main = await self.main_agent()
        context = caller or ToolContext(
            agent_id=main.id,
            chat_id=parent_chat_id or "",
            agent_name=main.name,
            agent_role=main.role,
        )
        crew = Crew(
            store=self._store,
            host=self,
            helper_pipeline=self.settings.studio_helper_pipeline,
        )
        site = await crew.project_for(
            context, project or project_name(goal), task=goal, owner=coder
        )
        self._code_loops.add(key)
        self.spawn(self._code_loop_job(key, coder, tester, goal, site, parent_chat_id))
        rounds = self.settings.studio_code_test_rounds
        return (
            f"{coder.name} is coding it in the '{site.name}' project; then "
            f"{tester.name} tests it, fixes small bugs, and hands the rest back, up "
            f"to {rounds} round(s). They report here when done."
        )

    async def _code_loop_job(
        self,
        key: str,
        coder: Agent,
        tester: Agent,
        goal: str,
        site: SiteProject,
        parent_chat_id: str | None,
    ) -> None:
        async def run(agent: Agent, task: str) -> AgentRun:
            finished, _ = await self.run_agent_task(
                agent, task, site_id=site.id, parent_chat_id=parent_chat_id
            )
            return finished

        try:
            outcome = await code_and_test(
                coder=coder,
                tester=tester,
                goal=goal,
                project=site.name,
                run=run,
                rounds=self.settings.studio_code_test_rounds,
            )
            summary = outcome.summary(coder.name, tester.name)
            if parent_chat_id:
                await self._main_follows_up(
                    parent_chat_id,
                    coder,
                    outcome.last_coder.model_copy(
                        update={"result": summary, "goal": goal}
                    ),
                )
        except (StudioError, StudioNotFoundError, ValueError) as error:
            logger.warning("Studio: the Coder and Tester stopped: {}", error)
        finally:
            self._code_loops.discard(key)

    async def _carry_out_orders(self, main: Agent, chat: Chat, text: str) -> str:
        """Hand out the jobs the user told the main AI to give, before it answers.

        'Have Builder make a page', '@Researcher look into X', 'get an agent to
        ...', and 'stop Builder' are carried out right away, so an order never
        depends on a small model choosing to call a tool. So are 'research X'
        and 'go on the web and find X': the Researcher takes those.
        """
        team = [
            agent
            for agent in await self.agents()
            if not agent.archived and agent.role not in {MAIN_ROLE, "guide"}
        ]
        orders = parse_orders(text, [agent.name for agent in team], main.name)
        researcher = next((agent for agent in team if agent.role == "researcher"), None)
        task = "" if orders or researcher is None else web_request(text, main.name)
        if task and researcher is not None:
            orders = [Order(agent=researcher.name, task=task)]
        code = (
            ""
            if orders or not {"coder", "tester"} <= {agent.role for agent in team}
            else code_request(text, main.name)
        )
        if code:
            try:
                line = await self.start_code_loop(code, parent_chat_id=chat.id)
            except StudioError as error:
                return f"The coding job could not start: {error}"
            await self._store.append_message(
                chat_id=chat.id,
                role="tool",
                text=line,
                author="code_and_test",
                data={"tool": "code_and_test", "order": True, "task": code},
            )
            return (
                f"The coding job was handed out already: {line}\nDo not hand it "
                "out again or write the code yourself. Tell the user in a sentence "
                "or two who is doing what."
            )
        builder = next((agent for agent in team if agent.role == "builder"), None)
        job = "" if orders or builder is None else build_request(text, main.name)
        if job and builder is not None:
            orders = [Order(agent=builder.name, task=job)]
        if not orders and is_yes(text, main.name):
            orders = await self._accepted_offer(main, chat, team)
        if not orders and is_job(text, main.name):
            orders = await self._job_for_called_agent(main, chat, team, text)
        if (
            not orders
            and not chat.settings.get(LAB_CHAT_SETTING)
            and not chat.settings.get(FARM_CHAT_SETTING)
            and not await self._own_job(text)
        ):
            orders = await self._routed_by_model(main, team, text)
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

    async def _routed_by_model(
        self, main: Agent, team: Sequence[Agent], text: str
    ) -> list[Order]:
        """Any wording: ask the main AI's model one word, who should do this.

        A small model on this PC rarely picks the hand-off tool out of two
        dozen, but answers 'Researcher' or 'none' reliably; Studio then hands
        the job out itself. Server models choose their own tools well.
        """
        model = main.model or self.default_model
        if not self._is_local(await self.effective_model(model)):
            return []
        if not worth_routing(text, main.name):
            return []
        pairs = [(agent.name, agent.role) for agent in team]
        if not any(
            role in {"researcher", "builder", "helper", "tester"} for _, role in pairs
        ):
            return []
        try:
            reply = await self._router.complete(
                [ChatMessage.user(text)],
                model=model,
                system=route_prompt(pairs, main.name),
                temperature=0.0,
                max_tokens=16,
            )
        except StudioLLMError as error:
            logger.info("Studio: routing skipped: {}", error)
            return []
        name = routed_agent(reply.text, pairs)
        return [Order(name, text.strip())] if name else []

    async def _job_for_called_agent(
        self, main: Agent, chat: Chat, team: Sequence[Agent], text: str
    ) -> list[Order]:
        """'Call the Researcher' then, once asked what for, 'cheap TVs': the
        second message is the called agent's job."""
        recent = list(await self._store.transcript(chat.id, limit=8))
        if recent and recent[-1].role == "user":
            recent.pop()  # This message.
        said = [m for m in recent if m.role in {"user", "assistant", "tool"}]
        if not said or said[-1].role != "assistant":
            return []
        asked = next(
            (i for i in range(len(said) - 1, -1, -1) if said[i].role == "user"), None
        )
        if asked is None or any(m.data.get("order") for m in said[asked:]):
            return []
        name = called_agent(said[asked].text, [agent.name for agent in team], main.name)
        return [Order(name, text.strip())] if name else []

    async def _accepted_offer(
        self, main: Agent, chat: Chat, team: Sequence[Agent]
    ) -> list[Order]:
        """The job the main AI asked about, now that the user said yes.

        A small model on this PC often asks 'Shall I have the Researcher look
        into it?' instead of handing the job out; without this, 'yes' names
        no job and it asks again, round and round.
        """
        recent = list(await self._store.transcript(chat.id, limit=16))
        if recent and recent[-1].role == "user":
            recent.pop()  # The 'yes' itself.
        asked = next(
            (
                index
                for index in range(len(recent) - 1, -1, -1)
                if recent[index].role == "assistant"
            ),
            None,
        )
        if asked is None or "?" not in recent[asked].text:
            return []
        question = recent[asked].text
        request = next(
            (
                message
                for message in reversed(recent[:asked])
                if message.role == "user" and not is_yes(message.text, main.name)
            ),
            None,
        )
        since = recent[recent.index(request) :] if request is not None else recent
        if any(message.data.get("order") for message in since):
            return []  # That job was handed out already; don't start it twice.
        names = [agent.name for agent in team]
        orders = offered_orders(question, names)
        if not orders and request is not None:
            orders = parse_orders(request.text, names)
            task = "" if orders else web_request(request.text, main.name)
            if task:
                orders = [Order("", task)]
        researcher = next((agent for agent in team if agent.role == "researcher"), None)
        if (
            not orders
            and request is not None
            and researcher is not None
            and len(request.text.split()) >= 3
            and re.search(
                rf"\b(?:research|{re.escape(researcher.name)})", question, re.I
            )
        ):
            orders = [Order(researcher.name, request.text.strip())]
        return orders

    # ------------------------------------------------------------ team room

    async def _team_room(self) -> Chat:
        """The room the team shares: the latest one, or a new Team room."""
        # A job's post and its result can arrive together; open one room only.
        async with self._room_lock:
            rooms = await self._store.find(
                Chat, where={"kind": "room"}, order_by="updated_at DESC", limit=1
            )
            return rooms[0] if rooms else await self.create_room(title="Team room")

    async def _join_room(self, room_id: str, members: Sequence[str]) -> None:
        """Add agents to the room's member list (newer agents weren't in it)."""
        async with self._room_lock:
            room = await self._store.get(Chat, room_id)
            if room is None:
                return
            main = await self._store.find(Agent, where={"role": MAIN_ROLE}, limit=1)
            joining = [
                member
                for member in dict.fromkeys(members)
                if member
                and member not in room.member_ids
                and not (main and member == main[0].id)
            ]
            if joining:
                await self._store.put(
                    room.model_copy(update={"member_ids": (*room.member_ids, *joining)})
                )

    async def _post_in_room(
        self,
        author: str,
        text: str,
        data: JsonObject,
        *,
        members: Sequence[str] = (),
    ) -> None:
        """Write in the team room for everyone to read. Only a note: it starts
        no one talking, so a job handed out is never done twice. Agents who
        post join the room's member list (newer agents weren't in it)."""
        try:
            room = await self._team_room()
        except StudioError as error:
            logger.info("Studio: no team room to post in: {}", error)
            return
        if members:
            await self._join_room(room.id, members)
        await self._store.append_message(
            chat_id=room.id,
            role="assistant",
            text=text.strip()[:ROOM_POST_CHARS],
            author=author,
            data=data,
        )

    async def _post_handoff(
        self, worker: Agent, goal: str, parent_chat_id: str | None, run_id: str
    ) -> None:
        """Whoever handed the job out tells the room: '@Researcher: ...'."""
        if not parent_chat_id:
            return
        parent = await self._store.get(Chat, parent_chat_id)
        boss = (
            await self._store.get(Agent, parent.agent_id)
            if parent and parent.agent_id
            else None
        )
        task = _job_line(goal)
        await self._post_in_room(
            boss.name if boss else "Studio",
            f"@{worker.name}: {task}",
            {"kind": "handoff", "agent": worker.name, "run_id": run_id},
            members=(worker.id, boss.id if boss else ""),
        )

    async def _plain_result(self, run: AgentRun) -> str:
        """A job's result in words: a pasted file becomes a list of what was built."""
        result = (run.result or "").strip()
        code = "```" in result or re.search(r"<(?:!doctype|html)\b", result, re.I)
        if run.site_id and code:
            site = await self._store.get(SiteProject, run.site_id)
            if site is not None:
                files = sorted(
                    (f.path for f in await self.workspace.files(run.site_id)),
                    key=_file_rank,
                )
                listed = ", ".join(files[:6]) or "no files"
                if len(files) > 6:
                    listed += f" and {len(files) - 6} more files"
                return (
                    f"Built {listed} in the '{site.name}' project "
                    "(open it under Projects to see it)."
                )
        return result

    async def _share_in_room(self, agent: Agent, run: AgentRun) -> None:
        """When a handed-out job ends, its agent tells the team what came of it."""
        goal = _job_line(run.goal)[:160]
        if run.status == "succeeded":
            result = await self._plain_result(run) or "Done, with nothing to report."
            text = f"Done: {goal}\n{result}"
        else:
            text = f"Couldn't finish: {goal}\n{_plain_error(run)}"
        await self._post_in_room(
            agent.name,
            text,
            {"kind": "shared", "run_id": run.id, "status": run.status},
            members=(agent.id,),
        )

    async def _room_note(self, run: AgentRun) -> str:
        """What the team has shared in the room, for an agent starting a job."""
        rooms = await self._store.find(
            Chat, where={"kind": "room"}, order_by="updated_at DESC", limit=1
        )
        if not rooms:
            return ""
        lines = [
            f"- {message.author}: {' '.join(message.text.split())[:ROOM_NOTE_CHARS]}"
            for message in await self._store.transcript(rooms[0].id, limit=12)
            if message.role in {"user", "assistant"}
            and message.text.strip()
            and message.data.get("run_id") != run.id
        ][-8:]
        if not lines:
            return ""
        return (
            "What the team has shared in the team room (use what helps your job; "
            "your result is posted there for the others when you finish):\n"
            + "\n".join(lines)
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
        run = await self.start_task(
            agent_id=agent.id,
            goal=await self._briefed(agent, goal, parent_chat_id),
            site_id=site_id,
            parent_chat_id=parent_chat_id,
        )
        await self._post_handoff(agent, goal, parent_chat_id, run.id)
        return run

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
        await self._post_handoff(agent, goal, parent_chat_id, run.id)
        note = await self._room_note(run) if parent_chat_id else ""
        async with self._working(agent.id):
            finished = await self._runner().run_task(
                agent,
                chat,
                run,
                note=note,
                fallback_model=await self._fallback_model(agent),
            )
        if parent_chat_id:
            await self._share_in_room(agent, finished)
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
            async with self._turn_lock(chat_id):
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

    # ------------------------------------------------------------------ HQ

    async def hq(self) -> JsonObject:
        """The whole team as the pixel HQ shows it: who is at which station
        doing what, what each station has waiting, and the newest steps."""
        agents = [agent for agent in await self.agents() if not agent.archived]
        busy = await self._busy_agents(await self._active_runs())
        latest_run: dict[str, AgentRun] = {}
        for run in await self.runs(limit=60):
            latest_run.setdefault(run.agent_id, run)
        main = await self.main_agent()
        main_chat = await self.main_chat()
        people: list[JsonObject] = []
        feed: list[JsonObject] = []
        for agent in agents:
            if agent.id == main.id:
                chat: Chat | None = main_chat
            else:
                found = await self._store.find(
                    Chat,
                    where={"agent_id": agent.id},
                    order_by="updated_at DESC",
                    limit=1,
                )
                chat = found[0] if found else None
            recent = await self._store.transcript(chat.id, limit=8) if chat else ()
            if chat is not None and chat.kind == "room":
                recent = tuple(m for m in recent if m.author == agent.name)
            tool = ""
            for message in reversed(recent):
                if message.role == "tool":
                    tool = str(message.data.get("tool") or message.author or "")
                    break
            live = self._live_text.get(chat.id, "") if chat else ""
            working = agent.id in busy or bool(live)
            run = latest_run.get(agent.id)
            model = await self.effective_model(agent.model or self.default_model)
            people.append(
                {
                    "id": agent.id,
                    "name": agent.name,
                    "role": agent.role,
                    "main": agent.id == main.id,
                    "model": model,
                    "local": self.runs_on_this_pc(model),
                    "busy": working,
                    "tool": tool,
                    "station": station_for(agent.role, tool, working),
                    "live": live[-160:],
                    "task": run.goal[:200]
                    if run and run.status in {"queued", "running"}
                    else "",
                    "chat_id": chat.id if chat else "",
                }
            )
            feed += [
                {
                    "agent": agent.name,
                    "agent_id": agent.id,
                    "tool": str(message.data.get("tool") or message.author or ""),
                    "text": message.text[:140],
                    "failed": bool(message.data.get("failed")),
                    "at": message.created_at,
                }
                for message in recent[-3:]
                if message.role == "tool"
            ]
        counts: dict[str, int] = {}
        notes: dict[str, str] = {}
        pending = await self.pending_commands()
        counts["approvals"] = len(pending)
        if pending:
            notes["approvals"] = f"{len(pending)} command(s) waiting for your yes"
        studying = [
            s for s in await self.studies() if s.status in {"planning", "learning"}
        ]
        counts["school"] = len(studying)
        if studying:
            notes["school"] = f"Learning: {studying[0].topic}"[:120]
        todos = await self.todos()
        counts["mailroom"] = len(todos)
        making = await self._farm.posts(status="making")
        counts["studio"] = len(making)
        if making:
            notes["studio"] = (
                f"Making: {making[0].title} ({making[0].stage or 'working'})"[:120]
            )
        counts["toolshed"] = len(await self._extensions.all())
        models = sorted({str(p["model"]) for p in people})
        counts["servers"] = len(models)
        notes["servers"] = ", ".join(model_label(m) for m in models[:4])
        for person in people:
            station = str(person["station"])
            if station not in {
                "approvals",
                "school",
                "mailroom",
                "studio",
                "toolshed",
                "servers",
            }:
                counts[station] = counts.get(station, 0) + 1
        feed.sort(key=lambda item: -int(str(item["at"])))
        return {
            "agents": people,
            "stations": stations_view(counts, notes),
            "pending": [item.model_dump() for item in pending[:5]],
            "feed": feed[:14],
        }

    async def hq_say(self, agent_id: str, text: str) -> JsonObject:
        """Talk to one agent from the HQ; it answers in the background."""
        text = text.strip()
        if not text:
            raise StudioError("Write something first.")
        agent = await self.agent(agent_id)
        main = await self.main_agent()
        if agent.id == main.id:
            chat = await self.main_say(text)
            return {"accepted": True, "chat_id": chat.id}
        found = await self._store.find(
            Chat,
            where={"agent_id": agent.id, "kind": "chat"},
            order_by="updated_at DESC",
            limit=1,
        )
        chat = (
            found[0]
            if found
            else await self.create_chat(agent_id=agent.id, title=f"{agent.name} (HQ)")
        )

        async def answer() -> None:
            with contextlib.suppress(StudioError, StudioNotFoundError):
                await self.send(chat.id, text)

        self.spawn(answer())
        return {"accepted": True, "chat_id": chat.id}

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
        base_url = self._local_url()
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

    async def clear_memory_area(self, agent_id: str) -> int:
        """Empty the memory area an agent keeps while it runs on a server AI."""
        await self._store.require(Agent, agent_id)
        owner = server_area(agent_id)
        removed = await self._memory().clear(owner)
        await self._after_memory_change([owner])
        return removed

    async def remember(
        self, agent_id: str, text: str, *, scope: str = "long_term"
    ) -> MemoryEntry | None:
        """Write one memory by hand; ``shared`` writes to the team memory."""
        if agent_id == SHARED_MEMORY_ID:
            scope = "long_term"
        elif agent_id.startswith(SERVER_AREA_PREFIX):
            await self._store.require(Agent, agent_id.removeprefix(SERVER_AREA_PREFIX))
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

    # -------------------------------------------------------------- playbook

    def _playbook(self) -> Playbook:
        """The vault's Playbook folder once a vault is set (seeded from
        Studio's own folder, so nothing learned is lost), else Studio's."""
        vault = self._vault()
        if vault.configured:
            return Playbook(vault.base / PLAYBOOK_FOLDER, seed_from=self._playbook_home)
        return Playbook(self._playbook_home)

    async def playbook(self) -> tuple[str, bool, list[PlaybookNote]]:
        """Where Jarvis's playbook lives, whether it is in the vault, and its notes."""
        playbook = self._playbook()
        return (
            str(playbook.folder),
            self._vault().configured,
            await playbook.notes(),
        )

    async def playbook_note(self, tool: str) -> PlaybookNote:
        try:
            return await self._playbook().read(tool)
        except PlaybookError as error:
            raise StudioNotFoundError(str(error)) from error

    async def save_playbook_note(self, tool: str, text: str) -> PlaybookNote:
        try:
            return await self._playbook().save(tool, text)
        except PlaybookError as error:
            raise StudioError(str(error)) from error

    async def reset_playbook_note(self, tool: str) -> PlaybookNote:
        try:
            return await self._playbook().reset(tool)
        except PlaybookError as error:
            raise StudioError(str(error)) from error

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


def _size_label(size: int) -> str:
    if size >= 1_048_576:
        return f"{size / 1_048_576:.1f} MB"
    return f"{max(1, round(size / 1024))} KB"


def photo_view(photo: Photo) -> JsonObject:
    """One business photo for the app."""
    return photo.model_dump() | {"url": f"/studio/api/photos/{photo.id}/file"}
