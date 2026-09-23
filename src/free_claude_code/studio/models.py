"""Persisted records for Studio agents, chats, memory, tuning, and school."""

import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from free_claude_code.core.json_types import JsonObject

type AgentRole = Literal["assistant", "agent", "teacher", "student", "guide"]
type ChatKind = Literal["chat", "agent", "classroom", "guide", "room"]
type MessageRole = Literal["user", "assistant", "system", "tool", "event"]
type MemoryScope = Literal["working", "long_term"]
type AssetStatus = Literal[
    "queued", "downloading", "extracting", "ready", "failed", "cancelled"
]
type AssetKind = Literal["gguf", "archive", "adapter", "file"]
type TuneBackend = Literal["local_light", "cloud"]
type JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
type RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
type CourseStatus = Literal[
    "planning", "teaching", "examining", "passed", "failed", "cancelled"
]
type SampleSplit = Literal["train", "eval"]
type LoraRunner = Literal["local", "remote"]
type Quantize = Literal["auto", "4bit", "none"]
type CommandStatus = Literal["pending", "approved", "denied", "ran", "expired"]

ACTIVE_JOB_STATUSES = frozenset({"queued", "running"})
"""Job states that still hold a worker."""


def now_ms() -> int:
    """Return the current wall-clock time in milliseconds."""
    return time.time_ns() // 1_000_000


def new_id(prefix: str) -> str:
    """Return a short, sortable-enough identifier for one record."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Record(BaseModel):
    """Immutable persisted row shared by every Studio table."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Agent(Record):
    """One named persona with its own model, tools, memory, and tuning."""

    id: str = Field(default_factory=lambda: new_id("agt"))
    name: str
    role: AgentRole = "assistant"
    model: str
    system_prompt: str = ""
    description: str = ""
    tools: tuple[str, ...] = ()
    memory_enabled: bool = True
    tune_pack_id: str | None = None
    local_only: bool = False
    archived: bool = False
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class Chat(Record):
    """A conversation thread bound to one agent or to a classroom pair."""

    id: str = Field(default_factory=lambda: new_id("cht"))
    title: str = "New chat"
    kind: ChatKind = "chat"
    agent_id: str | None = None
    partner_agent_id: str | None = None
    member_ids: tuple[str, ...] = ()
    parent_chat_id: str | None = None
    course_id: str | None = None
    site_id: str | None = None
    settings: JsonObject = Field(default_factory=dict)
    archived: bool = False
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class Message(Record):
    """One transcript entry, including tool calls and classroom events."""

    id: str = Field(default_factory=lambda: new_id("msg"))
    chat_id: str
    sequence: int
    role: MessageRole
    author: str = ""
    text: str = ""
    data: JsonObject = Field(default_factory=dict)
    created_at: int = Field(default_factory=now_ms)


class MemoryEntry(Record):
    """A single remembered fact owned by one agent."""

    id: str = Field(default_factory=lambda: new_id("mem"))
    agent_id: str
    scope: MemoryScope = "long_term"
    text: str
    tags: tuple[str, ...] = ()
    source: str = ""
    chat_id: str | None = None
    hits: int = 0
    created_at: int = Field(default_factory=now_ms)
    used_at: int = Field(default_factory=now_ms)


class ModelAsset(Record):
    """A downloadable model file or archive tracked on local disk."""

    id: str = Field(default_factory=lambda: new_id("ast"))
    name: str
    source_url: str
    path: str = ""
    kind: AssetKind = "gguf"
    status: AssetStatus = "queued"
    bytes_done: int = 0
    bytes_total: int = 0
    sha256: str | None = None
    extracted_dir: str | None = None
    preloaded: bool = False
    error: str | None = None
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    @property
    def progress(self) -> float:
        """Return completion between 0 and 1, or 0 when the size is unknown."""
        if self.bytes_total <= 0:
            return 1.0 if self.status == "ready" else 0.0
        return min(1.0, self.bytes_done / self.bytes_total)


class TuneSample(Record):
    """One supervised prompt/completion pair used by a tuning run."""

    id: str = Field(default_factory=lambda: new_id("smp"))
    pack_id: str
    prompt: str
    completion: str
    split: SampleSplit = "train"
    source: str = ""
    created_at: int = Field(default_factory=now_ms)


class TunePack(Record):
    """A very light adapter pack: preamble, rules, and chosen exemplars."""

    id: str = Field(default_factory=lambda: new_id("pak"))
    agent_id: str
    name: str
    base_model: str
    teacher_model: str | None = None
    backend: TuneBackend = "local_light"
    preamble: str = ""
    style_rules: tuple[str, ...] = ()
    exemplars: tuple[JsonObject, ...] = ()
    metrics: JsonObject = Field(default_factory=dict)
    remote_job_id: str | None = None
    remote_model: str | None = None
    opted_in: bool = False
    version: int = 1
    active: bool = False
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class TuneJob(Record):
    """One tuning run, local-light or delegated to a cloud trainer."""

    id: str = Field(default_factory=lambda: new_id("job"))
    pack_id: str
    agent_id: str
    backend: TuneBackend = "local_light"
    status: JobStatus = "queued"
    step: int = 0
    total_steps: int = 0
    baseline_score: float | None = None
    score: float | None = None
    message: str = ""
    error: str | None = None
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    @property
    def progress(self) -> float:
        """Return completion between 0 and 1 for progress meters."""
        if self.status in {"succeeded", "failed", "cancelled"}:
            return 1.0
        if self.total_steps <= 0:
            return 0.0
        return min(1.0, self.step / self.total_steps)


class AgentRun(Record):
    """One autonomous agent task with a bounded tool budget."""

    id: str = Field(default_factory=lambda: new_id("run"))
    agent_id: str
    chat_id: str
    goal: str
    status: RunStatus = "queued"
    step: int = 0
    max_steps: int = 12
    site_id: str | None = None
    result: str = ""
    error: str | None = None
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class SiteProject(Record):
    """A website workspace an agent can write to and the user can preview."""

    id: str = Field(default_factory=lambda: new_id("site"))
    name: str
    slug: str
    description: str = ""
    agent_id: str | None = None
    file_count: int = 0
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class Course(Record):
    """A teacher-led class taken by one student agent."""

    id: str = Field(default_factory=lambda: new_id("crs"))
    topic: str
    teacher_agent_id: str
    student_agent_id: str
    chat_id: str
    status: CourseStatus = "planning"
    lesson_total: int = 0
    lesson_done: int = 0
    score: float | None = None
    pass_mark: float = 0.7
    passed: bool = False
    tune_job_id: str | None = None
    error: str | None = None
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    @property
    def progress(self) -> float:
        """Return lesson completion between 0 and 1."""
        if self.lesson_total <= 0:
            return 0.0
        return min(1.0, self.lesson_done / self.lesson_total)


class Lesson(Record):
    """One unit of a course, taught and then reviewed by the teacher."""

    id: str = Field(default_factory=lambda: new_id("lsn"))
    course_id: str
    ordinal: int
    topic: str
    objective: str = ""
    status: Literal["pending", "teaching", "done", "failed"] = "pending"
    notes: str = ""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class ExamQuestion(Record):
    """One graded end-of-class question with the teacher's rubric."""

    id: str = Field(default_factory=lambda: new_id("exq"))
    course_id: str
    ordinal: int
    prompt: str
    rubric: str = ""
    answer: str = ""
    score: float | None = None
    feedback: str = ""
    created_at: int = Field(default_factory=now_ms)


class LoraJob(Record):
    """One LoRA weight-training run for a local student model."""

    id: str = Field(default_factory=lambda: new_id("lora"))
    agent_id: str
    base_model: str
    ollama_base: str = ""
    runner: LoraRunner = "local"
    status: JobStatus = "queued"
    sources: tuple[str, ...] = ()
    teacher_model: str | None = None
    topics: tuple[str, ...] = ()
    examples_per_topic: int = 8
    rank: int = 16
    alpha: int = 32
    epochs: int = 2
    learning_rate: float = 2e-4
    max_seq_len: int = 1024
    batch_size: int = 1
    grad_accum: int = 4
    quantize: Quantize = "auto"
    dataset_ready: bool = False
    train_examples: int = 0
    eval_examples: int = 0
    step: int = 0
    total_steps: int = 0
    loss: float | None = None
    eval_loss_before: float | None = None
    eval_loss_after: float | None = None
    metrics: JsonObject = Field(default_factory=dict)
    worker_token: str = ""
    served_model: str = ""
    previous_model: str = ""
    message: str = ""
    error: str | None = None
    heartbeat_at: int | None = None
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    @property
    def progress(self) -> float:
        """Return training completion between 0 and 1."""
        if self.status == "succeeded":
            return 1.0
        if self.total_steps <= 0:
            return 0.0
        return min(1.0, self.step / self.total_steps)


class CommandRequest(Record):
    """A shell command an agent asked to run in its project."""

    id: str = Field(default_factory=lambda: new_id("cmd"))
    agent_id: str
    chat_id: str
    site_id: str
    command: str
    status: CommandStatus = "pending"
    exit_code: int | None = None
    output: str = ""
    created_at: int = Field(default_factory=now_ms)
    decided_at: int | None = None
