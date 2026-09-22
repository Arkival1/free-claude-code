"""The Studio facade: one object the HTTP layer and tests both drive."""

import asyncio
import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from free_claude_code.application.web_tools.ports import (
    WebFetchEgressPolicy,
    WebToolsPort,
    web_fetch_allowed_scheme_set,
)
from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject

from .agents import AgentRunner, TurnResult
from .downloads import CURATED_MODELS, ModelLibrary
from .guide import GuideAnswer, GuideAssistant, GuideState
from .llm import LocalOpenAILLM, ProxyLLM, StudioModelRouter
from .memory import MemoryService
from .models import (
    Agent,
    AgentRun,
    Chat,
    Course,
    ExamQuestion,
    Lesson,
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
from .school import School
from .sites import SiteWorkspace, slugify
from .store import StudioNotFoundError, StudioStore
from .tools import DEFAULT_TOOL_NAMES, AgentToolbox
from .tuning import CloudTuner, LightTuner, TuningError

GUIDE_AGENT_NAME = "Guide"
BUILDER_AGENT_NAME = "Builder"
TEACHER_AGENT_NAME = "Teacher"
STUDENT_AGENT_NAME = "Student"


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
    ) -> None:
        self._store = store
        self._web_tools = web_tools
        self._settings_provider = settings_provider
        self._sites = SiteWorkspace(sites_dir)
        self._library = ModelLibrary(store=store, models_dir=models_dir)
        self._router = router or self._build_router(settings_provider())
        self._tasks: set[asyncio.Task[object]] = set()

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

    def _build_router(self, settings: Settings) -> StudioModelRouter:
        proxy = ProxyLLM(
            base_url=f"http://127.0.0.1:{settings.port}",
            token=settings.proxy_auth_token if settings.proxy_auth_enabled else "",
            default_model=self.default_model,
        )
        local = LocalOpenAILLM(
            base_url=settings.studio_local_base_url,
            api_key=settings.studio_local_api_key or "",
        )
        return StudioModelRouter(proxy=proxy, local=local)

    @property
    def default_model(self) -> str:
        settings = self.settings
        return settings.studio_default_model or settings.model

    def _memory(self) -> MemoryService:
        settings = self.settings
        return MemoryService(
            self._store,
            working_limit=settings.studio_memory_working_limit,
            recall_limit=settings.studio_memory_recall_limit,
        )

    def _toolbox(self) -> AgentToolbox:
        settings = self.settings
        return AgentToolbox(
            web_tools=self._web_tools,
            sites=self._sites,
            memory=self._memory(),
            egress=WebFetchEgressPolicy(
                allow_private_network_targets=(
                    settings.web_fetch_allow_private_networks
                ),
                allowed_schemes=web_fetch_allowed_scheme_set(
                    settings.web_fetch_allowed_schemes
                ),
            ),
        )

    def _runner(self) -> AgentRunner:
        return AgentRunner(
            store=self._store,
            router=self._router,
            toolbox=self._toolbox(),
            memory=self._memory(),
            default_model=self.default_model,
            max_steps=self.settings.studio_agent_max_steps,
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
        )

    def _school(self) -> School:
        return School(
            store=self._store,
            router=self._router,
            memory=self._memory(),
            tuner=self._tuner(),
            default_model=self.default_model,
        )

    def _vault(self) -> ObsidianVault:
        settings = self.settings
        root = (
            Path(settings.studio_obsidian_vault).expanduser()
            if settings.studio_obsidian_vault
            else None
        )
        return ObsidianVault(root, folder=settings.studio_obsidian_folder)

    def _guide(self) -> GuideAssistant:
        return GuideAssistant(
            router=self._router, model=self.settings.studio_guide_model
        )

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
                "agent",
                self.default_model,
                "Research on the web and build complete, working websites.",
                _default_tools(),
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
        created: list[Agent] = []
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
    ) -> Agent:
        """Create one agent with its own model, tools, and memory."""
        if not name.strip():
            raise StudioError("An agent needs a name.")
        agent = Agent.model_validate(
            {
                "name": name.strip(),
                "role": role,
                "model": model or self.default_model,
                "system_prompt": system_prompt,
                "tools": tuple(tools) if tools is not None else _default_tools(),
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
        agent = await self._store.require(Agent, chat.agent_id)
        if agent.role == "guide":
            return await self._guide_turn(chat, agent, text)
        result = await self._runner().reply(agent, chat, text)
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

    # ------------------------------------------------------------ agent runs

    async def start_task(
        self,
        *,
        agent_id: str,
        goal: str,
        site_id: str | None = None,
        chat_id: str | None = None,
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
            await self._runner().run_task(agent, chat, run)
        except (StudioNotFoundError, StudioError) as error:
            logger.warning("Studio task {} failed to start: {}", run_id, error)

    async def runs(self, *, agent_id: str | None = None) -> tuple[AgentRun, ...]:
        """Return agent tasks, newest first."""
        where = {"agent_id": agent_id} if agent_id else None
        return await self._store.find(AgentRun, where=where, order_by="created_at DESC")

    async def run(self, run_id: str) -> AgentRun:
        """Return one agent task."""
        return await self._store.require(AgentRun, run_id)

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

    async def create_pack(self, agent_id: str, *, name: str = "") -> TunePack:
        """Create one tune pack for an agent."""
        agent = await self._store.require(Agent, agent_id)
        return await self._tuner().create_pack(
            agent, name=name, backend=self.settings.studio_tuning_backend
        )

    async def add_samples(
        self, pack_id: str, pairs: Sequence[tuple[str, str]], *, split: str = "train"
    ) -> int:
        """Add prompt/answer examples to a pack."""
        return await self._tuner().add_samples(pack_id, pairs, split=split)

    async def samples(self, pack_id: str) -> tuple[TuneSample, ...]:
        """Return the examples attached to a pack."""
        return await self._store.find(TuneSample, where={"pack_id": pack_id})

    async def start_tuning(self, pack_id: str, *, background: bool = True) -> TuneJob:
        """Queue one tuning run, starting it in the background by default."""
        if not self.settings.studio_light_tuning_enabled:
            raise StudioError(
                "Light tuning is off. Turn it on in Studio settings or from a "
                "chat's settings."
            )
        tuner = self._tuner()
        try:
            job = await tuner.start(pack_id)
        except TuningError as error:
            raise StudioError(str(error)) from error
        if background:
            self.spawn(tuner.run(job.id))
        return job

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
        self, *, topic: str, lesson_count: int = 3, start: bool = False
    ) -> Course:
        """Open a class between the teacher and student agents."""
        await self.ensure_defaults()
        teacher = await self.agent_by_name(TEACHER_AGENT_NAME)
        student = await self.agent_by_name(STUDENT_AGENT_NAME)
        if teacher is None or student is None:
            raise StudioError("The teacher and student agents are missing.")
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
        return await self._school().run_course(
            course_id, tune_on_pass=self.settings.studio_light_tuning_enabled
        )

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
        """Write one memory by hand."""
        await self._store.require(Agent, agent_id)
        return await self._memory().remember(agent_id, text, scope=scope, source="user")

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
        agent = await self._store.require(Agent, agent_id)
        entries = await self._memory().entries(agent_id)
        path = await self._vault().export_memory(agent, entries)
        return str(path)

    async def import_vault_notes(self, agent_id: str) -> int:
        """Read the vault Inbox into one agent's long-term memory."""
        agent = await self._store.require(Agent, agent_id)
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
        """Describe this install for the guide model."""
        settings = self.settings
        ready = await self._library.ready_models()
        return GuideState(
            agent_count=len(await self.agents()),
            site_count=len(await self.sites()),
            ready_models=len(ready),
            guide_model=settings.studio_guide_model,
            guide_model_ready=bool(ready),
            tuning_enabled=settings.studio_light_tuning_enabled,
            teacher_enabled=settings.studio_teacher_enabled,
            vault_configured=bool(settings.studio_obsidian_vault),
        )

    async def ask_guide(self, question: str) -> GuideAnswer:
        """Answer one question about the app with the small guide model."""
        return await self._guide().answer(question, await self.guide_state())

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
            },
        }
