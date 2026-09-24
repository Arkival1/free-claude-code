"""The Studio facade: one object the HTTP layer and tests both drive."""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
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
from free_claude_code.core.json_types import JsonObject

from . import system_monitor
from .agents import AgentRunner, TurnResult
from .commands import CommandBroker, CommandError
from .connectivity import Connectivity
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
from .llm import (
    LOCAL_MODEL_PREFIX,
    ChatMessage,
    LocalOpenAILLM,
    ProxyLLM,
    StudioLLMError,
    StudioModelRouter,
)
from .local_voice import LocalVoice, SetupState, speech_package_ready
from .lora import LoraTrainer
from .memory import SHARED_MEMORY_ID, SKILL_TAG, MemoryService
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
    CommandRequest,
    Course,
    ExamQuestion,
    Lesson,
    LoraJob,
    MemoryEntry,
    Message,
    ModelAsset,
    SiteProject,
    TuneJob,
    TunePack,
    TuneSample,
    now_ms,
)
from .obsidian import ObsidianVault, VaultStatus
from .platforms import PlatformError, PlatformReader, platform_of
from .presets import (
    BUILDER_PROMPT,
    HELPER_PROMPT,
    HELPER_TOOLS,
    PROMPT_UPGRADES,
    RESEARCHER_PROMPT,
    RESEARCHER_TOOLS,
    agent_options,
)
from .research import ResearchMix
from .rooms import RoomError, RoomOutcome, RoomService
from .school import School
from .search import SearchError, StudioSearch
from .sites import SiteWorkspace, slugify
from .store import StudioNotFoundError, StudioStore
from .tools import (
    DEFAULT_TOOL_NAMES,
    MAIN_ROLE,
    MAIN_TOOL_NAMES,
    TOOL_SPEC_BY_NAME,
    AgentToolbox,
)
from .tuning import CloudTuner, LightTuner, TuningError
from .voice import SpeechAudio, VoiceError, VoiceService, speakable

GUIDE_AGENT_NAME = "Guide"
BUILDER_AGENT_NAME = "Builder"
TEACHER_AGENT_NAME = "Teacher"
STUDENT_AGENT_NAME = "Student"
RESEARCHER_AGENT_NAME = "Researcher"
HELPER_AGENT_NAME = "Helper"
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
    ),
    RESEARCHER_AGENT_NAME: RESEARCHER_TOOLS,
    HELPER_AGENT_NAME: HELPER_TOOLS,
}
_DEFAULT_ROLES = {
    BUILDER_AGENT_NAME: "builder",
    RESEARCHER_AGENT_NAME: "researcher",
    HELPER_AGENT_NAME: "helper",
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
        self._router.use_stand_in(self._stand_in_model)

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
            audio = await self.local_voice().speak(speakable(text))
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
        )

    def _runner(self) -> AgentRunner:
        return AgentRunner(
            store=self._store,
            router=self._router,
            toolbox=self._toolbox(),
            memory=self._memory(),
            default_model=self.default_model,
            max_steps=self.settings.studio_agent_max_steps,
            live=self._live_text,
            temperature=self.settings.studio_agent_temperature,
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
            result = await self._runner().reply(agent, chat, text)
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
        """Delete one chat and its transcript."""
        await self._store.delete_where(Message, {"chat_id": chat_id})
        return await self._store.delete(Chat, chat_id)

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
                "max_steps": self.settings.studio_agent_max_steps,
            }
        )
        await self._store.put(run)
        self.spawn(self._run_task(agent.id, chat.id, run.id))
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
            goal=goal,
            site_id=site_id,
            parent_chat_id=parent_chat_id,
        )

    async def runs(self, *, agent_id: str | None = None) -> tuple[AgentRun, ...]:
        """Return agent tasks, newest first."""
        where = {"agent_id": agent_id} if agent_id else None
        return await self._store.find(AgentRun, where=where, order_by="created_at DESC")

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
                "max_steps": self.settings.studio_agent_max_steps,
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
        """The admin's Main AI Model setting always decides the main AI's model."""
        wanted = self.settings.studio_main_agent_model
        if not wanted or wanted == agent.model:
            return agent
        agent = agent.model_copy(
            update={
                "model": wanted,
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
        runs = await self.runs()
        busy = agent_id in await self._busy_agents(runs)
        own_runs = [run for run in runs if run.agent_id == agent_id]
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
        agent = await self.main_agent()
        chat = await self.main_chat()
        messages = (
            await self._store.transcript(chat.id, after=after)
            if after
            else await self._store.transcript(chat.id, limit=80)
        )
        runs = await self.runs()
        running = await self._busy_agents(runs)
        team = [
            {
                "id": member.id,
                "name": member.name,
                "role": member.role,
                "model": member.model,
                "busy": member.id in running,
                "local": member.model.startswith(LOCAL_MODEL_PREFIX),
            }
            for member in await self.agents()
            if member.id != agent.id and not member.archived
        ]
        shared = await self._store.find(
            MemoryEntry,
            where={"agent_id": SHARED_MEMORY_ID},
            order_by="used_at DESC",
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
                "count": len(shared),
                "recent": [entry.model_dump() for entry in shared[:8]],
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
            "room": await self._room_snapshot(),
            **await self._dashboard_extras(
                runs,
                {str(member["id"]): str(member["name"]) for member in team},
                len(shared),
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
        entries = await self._store.find(MemoryEntry)
        agents_with_memory = {
            entry.agent_id for entry in entries if entry.agent_id != SHARED_MEMORY_ID
        }
        return {
            "memories": len(entries),
            "shared": shared,
            "skills": sum(1 for entry in entries if SKILL_TAG in entry.tags),
            "agents": len(agents_with_memory),
            "conversations": len(await self._store.find(Chat)),
            "projects": len(await self._store.find(SiteProject)),
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
        busy = await self._busy_agents(await self.runs())
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
            "runs": [run.model_dump() for run in (await self.runs())[:10]],
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
