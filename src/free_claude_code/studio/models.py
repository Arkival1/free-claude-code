"""Persisted records for Studio agents, chats, memory, tuning, and school."""

import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from free_claude_code.core.json_types import JsonObject

type AgentRole = Literal[
    "assistant",
    "agent",
    "builder",
    "researcher",
    "helper",
    "tester",
    "coder",
    "lab",
    "farm",
    "teacher",
    "student",
    "guide",
    "main",
]
AGENT_ROLES: tuple[str, ...] = (
    "assistant",
    "agent",
    "builder",
    "researcher",
    "helper",
    "tester",
    "coder",
    "lab",
    "farm",
    "teacher",
    "student",
    "guide",
    "main",
)
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
type LoraExport = Literal["merged", "adapter"]
type GgufQuant = Literal["Q4_K_M", "Q5_K_M", "Q8_0"]
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
    model_setting: str = ""
    """The Main AI Model setting this agent last followed (main AI only)."""
    all_tools: bool = True
    """Whether this agent gets every tool (when the setting allows it)."""
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
    """A single remembered fact owned by one agent, or by the whole team."""

    id: str = Field(default_factory=lambda: new_id("mem"))
    agent_id: str
    scope: MemoryScope = "long_term"
    text: str
    tags: tuple[str, ...] = ()
    source: str = ""
    author: str = ""
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
    export: LoraExport = "merged"
    gguf_quant: GgufQuant = "Q4_K_M"
    lmstudio_path: str = ""
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


type VideoSource = Literal["research", "user", "agent"]


class VideoNote(Record):
    """A YouTube video turned into notes the agents can use and look back at."""

    id: str = Field(default_factory=lambda: new_id("vid"))
    video_id: str
    url: str
    title: str
    summary: str = ""
    points: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    cautions: tuple[str, ...] = ()
    focus: str = ""
    source: VideoSource = "agent"
    studied_by: str = ""
    segments: tuple[tuple[int, str], ...] = ()
    memory_id: str = ""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class TodoItem(Record):
    """Something on the user's to-do list, with an optional reminder time."""

    id: str = Field(default_factory=lambda: new_id("todo"))
    text: str
    due_at: int | None = None
    done: bool = False
    reminded: bool = False
    added_by: str = ""
    created_at: int = Field(default_factory=now_ms)
    done_at: int | None = None


class ChatNotes(Record):
    """The running notes on one long conversation; the id is the chat's id."""

    id: str
    text: str = ""
    until: int = 0
    updated_at: int = Field(default_factory=now_ms)


type StudyStatus = Literal["planning", "learning", "done", "failed", "cancelled"]
type StudyDepth = Literal["quick", "normal", "deep"]


class Study(Record):
    """A subject the main AI is teaching itself, lesson by lesson."""

    id: str = Field(default_factory=lambda: new_id("stu"))
    topic: str
    focus: str = ""
    depth: StudyDepth = "normal"
    status: StudyStatus = "planning"
    plan: tuple[str, ...] = ()
    done: int = 0
    progress: float = 0.0
    step: str = ""
    understanding: float | None = None
    summary: str = ""
    error: str | None = None
    started_by: str = ""
    memory_id: str = ""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class StudyLesson(Record):
    """One lesson of a study: the notes written, the self-check, the sources."""

    id: str = Field(default_factory=lambda: new_id("lsn"))
    study_id: str
    ordinal: int
    title: str
    notes: str = ""
    quiz: tuple[tuple[str, str], ...] = ()
    score: float = 0.0
    sources: tuple[str, ...] = ()
    memory_id: str = ""
    created_at: int = Field(default_factory=now_ms)


class EngineModelSettings(Record):
    """How the built-in engine runs one model, set on Model Control."""

    id: str
    """The model's name in the engine."""
    context: int = 8192
    gpu_layers: int = -1
    """Layers on the graphics card; -1 puts them all there."""
    flash_attention: str = "auto"
    kv_cache: str = "f16"
    threads: int = 0
    """CPU threads; 0 lets the engine choose."""
    batch: int = 512
    """Tokens read per step on the graphics card (llama.cpp's ubatch)."""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class PhoneLink(Record):
    """A phone running FCC Phone, paired with this PC to share memory."""

    id: str = Field(default_factory=lambda: new_id("phn"))
    name: str = "Phone"
    token_hash: str
    """SHA-256 of the phone's secret; the secret itself lives on the phone."""
    last_seen: int = 0
    last_sync: int = 0
    memories_in: int = 0
    """Memories this phone has sent to the PC."""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class Photo(Record):
    """A photo of the user's business, sent to the agents with a note."""

    id: str = Field(default_factory=lambda: new_id("pho"))
    name: str
    file: str
    """The file's name in the photo folder."""
    content_type: str = "image/jpeg"
    width: int = 0
    height: int = 0
    size: int = 0
    note: str = ""
    """What the user said about it: what it shows, prices, hours, anything."""
    chat_id: str | None = None
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class LabProject(Record):
    """Something made in the Lab: a mix, a product, a material, or a build."""

    id: str = Field(default_factory=lambda: new_id("lab"))
    name: str
    kind: str = "mix"
    """mix, product, material, or build."""
    request: str = ""
    """What was asked for, e.g. 'make shampoo'."""
    data: JsonObject = Field(default_factory=dict)
    made_by: str = "You"
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class LabChemical(Record):
    """A chemical the Lab looked up (on PubChem) and keeps on its shelf."""

    id: str = Field(default_factory=lambda: new_id("chm"))
    name: str
    formula: str = ""
    molar_mass: float = 0.0
    iupac: str = ""
    cid: int = 0
    state: str = "solid"
    colour: str = "#e8f4ff"
    note: str = ""
    created_at: int = Field(default_factory=now_ms)


class FarmChannel(Record):
    """One account the Content Farm makes videos for: a niche and a style."""

    id: str = Field(default_factory=lambda: new_id("fch"))
    name: str
    niche: str = ""
    """What the account is about, e.g. 'space facts' or 'gym motivation'."""
    platform: str = "youtube"
    """youtube, tiktok, or instagram: where the videos go."""
    style: str = "facts"
    """The video format: facts, story, motivation, tips, ai_art, explainer, news."""
    look: str = "bold"
    """The caption style: bold, clean, neon, or cinema."""
    visuals: str = "auto"
    """Where pictures come from: auto, library, photos, ai, text, or none (see
    farm.formats.VISUALS)."""
    voice: str = "am_michael"
    """The built-in voice that reads the script, or 'none' for captions only."""
    seconds: int = 30
    posts_per_day: int = 1
    post_times: tuple[str, ...] = ("18:00",)
    hashtags: tuple[str, ...] = ()
    call_to_action: str = ""
    notes: str = ""
    """Anything else the writer should know: the tone, words to avoid."""
    autopilot: bool = False
    """Keep a day of videos ready on its own."""
    fandom: str = ""
    """The show, movie, or game the channel is about, for lore and pictures."""
    wiki: str = ""
    """Its Fandom wiki's address, when the farm can't find it by name."""
    ai_media: bool = True
    """Allow pictures made by AI; off means only real clips, stills, and stock."""
    ai_polish: bool = True
    """Let the AI edit each short's script once more before it is made."""
    background: str = ""
    """A library clip (gameplay) to play under every short."""
    minutes: int = 120
    """How long a long (sleep) video runs."""
    captions: bool = True
    cast: tuple[str, ...] = ()
    """Characters (FarmCharacter ids) in a cartoon channel's stories."""
    series: str = ""
    """The title box over a cartoon, e.g. 'Most Epic Comebacks in History'."""
    texture: str = "wood"
    """What a tall cartoon sits on: wood, paper, dark, brick, or none."""
    song: str = ""
    """A library song: the beat edit's music, or a cartoon's quiet bed."""
    theme: str = "#ff5fc8"
    """The colour of a beat edit's big words."""
    shape: str = "tall"
    """tall (9:16, for Shorts) or wide (16:9) for cartoons and beat edits."""
    pace: str = "auto"
    """How often a beat edit cuts: auto, fast, medium, or slow."""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class FarmCharacter(Record):
    """A cartoon character: how they look and sound. Anything left blank is
    chosen from the name, so they always look the same."""

    id: str = Field(default_factory=lambda: new_id("fcr"))
    name: str
    description: str = ""
    """Who they are, for the writer: 'a brave young king who couldn't walk'."""
    skin: str = ""
    hair: str = ""
    hair_colour: str = ""
    wear: str = ""
    """Something on the head: wrap, crown, turban, cap, hood, helmet, ..."""
    wear_colour: str = ""
    age: str = "adult"
    """kid, adult, or old."""
    beard: bool = False
    earrings: bool = False
    glasses: bool = False
    head_asset: str = ""
    """A library picture used as the head instead of a drawn one."""
    voice: str = ""
    """Their own voice for lines they say; blank uses the narrator's."""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class FarmPost(Record):
    """One video on the farm, from idea to posted."""

    id: str = Field(default_factory=lambda: new_id("fpo"))
    channel_id: str
    title: str
    """The idea, e.g. '5 facts about black holes'."""
    status: str = "idea"
    """idea, making, ready, posted, or failed."""
    stage: str = ""
    """What the farm is doing now, while making: writing, voicing, pictures, video."""
    progress: int = 0
    data: JsonObject = Field(default_factory=dict)
    """The script (hook, scenes, caption, hashtags) and the files made."""
    error: str = ""
    made_by: str = "You"
    scheduled_at: int = 0
    posted_at: int = 0
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class FarmAsset(Record):
    """A clip or picture in the Content Farm's media library.

    Uploads are copied into the library; a linked folder's files stay where
    they are (a clip library can be hundreds of gigabytes).
    """

    id: str = Field(default_factory=lambda: new_id("fma"))
    name: str
    kind: str = "image"
    """image, video, or audio (a song for beat edits)."""
    file: str = ""
    """The file's name in the library folder, for uploads."""
    path: str = ""
    """The file's full path on this PC, for linked folders."""
    tags: tuple[str, ...] = ()
    note: str = ""
    """What it shows: who, where, which episode."""
    show: str = ""
    """The show, movie, or game it is from."""
    background: bool = False
    """Gameplay or footage meant to play under a whole short."""
    source: str = "upload"
    """upload, folder, fandom, wikipedia, openverse, or ai."""
    credit: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    size: int = 0
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class StudioFlag(Record):
    """A one-time change Studio has made, so it never repeats (by name)."""

    id: str
    value: str = ""
    updated_at: int = Field(default_factory=now_ms)
