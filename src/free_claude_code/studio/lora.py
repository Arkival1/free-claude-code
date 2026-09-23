"""LoRA weight training: teacher-written data, a worker anywhere, and Ollama install."""

import asyncio
import json
import os
import random
import secrets
import shutil
import sys
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import anyio.to_thread
from loguru import logger
from pydantic import ValidationError

from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject

from .downloads import DownloadError, extract_archive
from .jsonish import extract_json
from .llm import (
    LOCAL_MODEL_PREFIX,
    ChatMessage,
    StudioLLMError,
    StudioModelRouter,
    tool_protocol_instructions,
)
from .models import (
    Agent,
    Course,
    ExamQuestion,
    Lesson,
    LoraJob,
    ModelAsset,
    TunePack,
    TuneSample,
    now_ms,
)
from .sites import slugify
from .store import StudioStore
from .tools import TOOL_SPECS

WORKER_PATH = Path(__file__).with_name("lora_worker.py")
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
SOURCES = frozenset({"examples", "classes", "topics", "tools"})
UPLOAD_NAMES = frozenset({"adapter.zip", "adapter.gguf"})
MAX_UPLOAD_BYTES = 8 * 1024**3
MAX_TOPICS = 20
MAX_PER_TOPIC = 50
MIN_TRAIN_EXAMPLES = 4
LOSS_CURVE_LIMIT = 600

EXPERT_PROMPT = (
    "You are an expert engineer and designer writing the ideal answer a strong "
    "assistant would give. Be correct and complete but concise. Use code blocks "
    "for code. This answer will be used to train a smaller model."
)
REQUESTS_PROMPT = (
    "You are writing a training curriculum for a smaller coding assistant. "
    "Reply with a JSON array of strings only: {count} varied, realistic requests "
    "a user might send about the topic below, from beginner to advanced. Each "
    "request must stand alone."
)
TOOL_REQUESTS_PROMPT = (
    "You are writing training data that teaches a smaller agent to call tools. "
    "The agent has these tools:\n{tools}\n\nReply with a JSON array only: {count} "
    'objects like {{"request": "...", "tool": "<tool name>", "arguments": {{...}}}} '
    "where the tool call is the best first step for the request. Cover every "
    "tool, including writing complete files."
)


class LoraError(RuntimeError):
    """Raised when a LoRA job cannot be created, run, or installed."""


class LoraAuthError(LoraError):
    """Raised when a worker presents the wrong job token."""


@dataclass(frozen=True, slots=True)
class LoraBase:
    """A trainable Hugging Face model and the Ollama build of the same weights."""

    repo: str
    ollama: str
    size: str
    note: str
    gated: bool = False


KNOWN_BASES: tuple[LoraBase, ...] = (
    LoraBase(
        "Qwen/Qwen2.5-Coder-7B-Instruct",
        "qwen2.5-coder:7b",
        "7B",
        "Best pick for code, websites, and tools. Needs a GPU with 12 GB+.",
    ),
    LoraBase(
        "Qwen/Qwen3-8B",
        "qwen3:8b",
        "8B",
        "Strong general model with tool use. Needs a GPU with 12 GB+.",
    ),
    LoraBase(
        "meta-llama/Llama-3.1-8B-Instruct",
        "llama3.1:8b",
        "8B",
        "Gated: accept Meta's license on Hugging Face and set a token first.",
        gated=True,
    ),
    LoraBase(
        "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "qwen2.5-coder:1.5b",
        "1.5B",
        "Small coder. Trains on a modest GPU; slow but possible on a CPU.",
    ),
    LoraBase(
        "Qwen/Qwen2.5-0.5B-Instruct",
        "qwen2.5:0.5b",
        "0.5B",
        "Tiny. Trains on a plain CPU in minutes; use it to try the pipeline.",
    ),
)
BASE_BY_REPO = {base.repo: base for base in KNOWN_BASES}

type Spawner = Callable[[Coroutine[object, object, object]], object]


def chat_row(prompt: str, answer: str, *, system: str = "") -> JsonObject:
    """Return one chat-format training example."""
    messages: list[JsonObject] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt.strip()})
    messages.append({"role": "assistant", "content": answer.strip()})
    return {"messages": messages}


def _prompt_of(row: JsonObject) -> str:
    messages = row.get("messages")
    if isinstance(messages, list) and len(messages) >= 2:
        prompt = messages[-2]
        if isinstance(prompt, dict):
            return str(prompt.get("content", "")).strip().casefold()
    return ""


def split_rows(rows: Sequence[JsonObject], *, seed: int = 7) -> tuple[list, list]:
    """Shuffle deterministically and hold out about a tenth for evaluation."""
    ordered = list(rows)
    random.Random(seed).shuffle(ordered)
    held = max(1, len(ordered) // 10) if len(ordered) >= 10 else 0
    return ordered[held:], ordered[:held]


class LoraTrainer:
    """Own LoRA jobs, their files, and any trainer process on this machine."""

    def __init__(
        self,
        *,
        store: StudioStore,
        router: StudioModelRouter,
        jobs_dir: Path,
        settings_provider: Callable[[], Settings],
        spawn: Spawner,
    ) -> None:
        self._store = store
        self._router = router
        self._jobs_dir = jobs_dir
        self._settings = settings_provider
        self._spawn = spawn
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._probe_cache: tuple[float, JsonObject] | None = None

    # ------------------------------------------------------------ files

    def job_dir(self, job_id: str) -> Path:
        """Return one job's folder, refusing identifiers that are not ours."""
        if not job_id.startswith("lora_") or not job_id[5:].isalnum():
            raise LoraError("Invalid LoRA job id.")
        return self._jobs_dir / job_id

    def file_path(self, job_id: str, name: str) -> Path:
        """Return a downloadable job file."""
        allowed = {
            "train.jsonl",
            "eval.jsonl",
            "worker.log",
            "Modelfile",
            *UPLOAD_NAMES,
        }
        if name not in allowed:
            raise LoraError("That file is not part of a LoRA job.")
        path = self.job_dir(job_id) / name
        if not path.is_file():
            raise LoraError(f"{name} does not exist for this job yet.")
        return path

    # ------------------------------------------------------------ jobs

    async def create(
        self,
        *,
        agent_id: str,
        base_model: str,
        runner: str = "local",
        sources: Sequence[str] = ("examples", "classes"),
        topics: Sequence[str] = (),
        examples_per_topic: int = 8,
        teacher_model: str | None = None,
        ollama_base: str = "",
        hyper: Mapping[str, object] | None = None,
    ) -> LoraJob:
        """Record a job and start building its training set in the background."""
        agent = await self._store.require(Agent, agent_id)
        base = base_model.strip()
        if not base or base.startswith(LOCAL_MODEL_PREFIX) or " " in base:
            raise LoraError(
                "Choose the Hugging Face model to train, e.g. Qwen/Qwen2.5-Coder-7B-Instruct."
            )
        if runner not in {"local", "remote"}:
            raise LoraError("Train on this computer or on a remote worker.")
        chosen = tuple(dict.fromkeys(source for source in sources if source in SOURCES))
        if not chosen:
            raise LoraError("Pick at least one source of training data.")
        cleaned_topics = tuple(topic.strip() for topic in topics if topic.strip())[
            :MAX_TOPICS
        ]
        if "topics" in chosen and not cleaned_topics:
            raise LoraError(
                "Add at least one topic for the teacher to write lessons on."
            )
        known = BASE_BY_REPO.get(base)
        values: dict[str, object] = {
            "agent_id": agent.id,
            "base_model": base,
            "ollama_base": ollama_base.strip() or (known.ollama if known else ""),
            "runner": runner,
            "sources": chosen,
            "topics": cleaned_topics,
            "examples_per_topic": max(1, min(MAX_PER_TOPIC, examples_per_topic)),
            "teacher_model": teacher_model or self._default_teacher(),
            "worker_token": secrets.token_urlsafe(32),
            "message": "Building the training set",
        }
        for key in (
            "rank",
            "alpha",
            "epochs",
            "learning_rate",
            "max_seq_len",
            "batch_size",
            "grad_accum",
            "quantize",
        ):
            if hyper and hyper.get(key) not in {None, ""}:
                values[key] = hyper[key]
        try:
            job = LoraJob.model_validate(values)
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors()
            )
            raise LoraError(f"Invalid training settings: {problems}") from error
        await self._store.put(job)
        self._spawn(self._prepare(job.id))
        return job

    def _default_teacher(self) -> str:
        settings = self._settings()
        return (
            settings.studio_teacher_model
            or settings.studio_default_model
            or settings.model
        )

    async def _prepare(self, job_id: str) -> None:
        try:
            await self.build_dataset(job_id)
            job = await self._store.require(LoraJob, job_id)
            if job.status == "cancelled":
                return
            if job.runner == "local":
                await self.start_local(job_id)
            else:
                await self._update(
                    job,
                    message="Training set ready. Run the worker command on your GPU "
                    "machine; it will pick this job up.",
                )
        except (LoraError, StudioLLMError, OSError) as error:
            logger.warning("Studio LoRA job {} failed to prepare: {}", job_id, error)
            await self.fail(job_id, str(error))

    async def build_dataset(self, job_id: str) -> LoraJob:
        """Collect examples, have the teacher write more, and save the split."""
        job = await self._store.require(LoraJob, job_id)
        agent = await self._store.require(Agent, job.agent_id)
        rows: list[JsonObject] = []
        if "examples" in job.sources:
            rows.extend(await self._pack_rows(agent))
        if "classes" in job.sources:
            rows.extend(await self._class_rows(job, agent))
        if "topics" in job.sources:
            rows.extend(await self._topic_rows(job))
        if "tools" in job.sources:
            rows.extend(await self._tool_rows(job))
        unique: dict[str, JsonObject] = {}
        for row in rows:
            key = _prompt_of(row)
            if key and key not in unique:
                unique[key] = row
        if len(unique) < MIN_TRAIN_EXAMPLES:
            raise LoraError(
                f"Only {len(unique)} usable examples; LoRA needs at least "
                f"{MIN_TRAIN_EXAMPLES}. Add examples, classes, or teacher topics."
            )
        train, evaluation = split_rows(list(unique.values()))
        folder = self.job_dir(job.id)

        def write() -> None:
            folder.mkdir(parents=True, exist_ok=True)
            for name, part in (("train.jsonl", train), ("eval.jsonl", evaluation)):
                (folder / name).write_text(
                    "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in part),
                    encoding="utf-8",
                )

        await anyio.to_thread.run_sync(write)
        note = " (small set: expect a modest change)" if len(train) < 40 else ""
        return await self._update(
            await self._store.require(LoraJob, job.id),
            dataset_ready=True,
            train_examples=len(train),
            eval_examples=len(evaluation),
            message=f"Training set ready: {len(train)} examples, {len(evaluation)} held out{note}",
        )

    async def _pack_rows(self, agent: Agent) -> list[JsonObject]:
        rows: list[JsonObject] = []
        for pack in await self._store.find(TunePack, where={"agent_id": agent.id}):
            samples = await self._store.find(TuneSample, where={"pack_id": pack.id})
            rows.extend(
                chat_row(sample.prompt, sample.completion) for sample in samples
            )
        return rows

    async def _class_rows(self, job: LoraJob, agent: Agent) -> list[JsonObject]:
        rows: list[JsonObject] = []
        courses = await self._store.find(Course, where={"student_agent_id": agent.id})
        for course in courses:
            lessons = {
                lesson.id: lesson
                for lesson in await self._store.find(
                    Lesson, where={"course_id": course.id}
                )
            }
            for message in await self._store.transcript(course.chat_id):
                lesson = lessons.get(str(message.data.get("lesson_id") or ""))
                if message.data.get("kind") == "lesson" and lesson is not None:
                    prompt = (
                        f"Teach me about {lesson.topic}. {lesson.objective}".strip()
                    )
                    rows.append(chat_row(prompt, message.text))
            questions = await self._store.find(
                ExamQuestion, where={"course_id": course.id}, order_by="ordinal ASC"
            )
            for index, question in enumerate(questions, start=1):
                await self._update(
                    job,
                    message=f"Teacher answering test questions ({index}/{len(questions)})",
                )
                answer = await self._teach(
                    job,
                    question.prompt,
                    extra=f"A correct answer must cover: {question.rubric}"
                    if question.rubric
                    else "",
                )
                if answer:
                    rows.append(chat_row(question.prompt, answer))
        return rows

    async def _topic_rows(self, job: LoraJob) -> list[JsonObject]:
        rows: list[JsonObject] = []
        planned = len(job.topics) * job.examples_per_topic
        done = 0
        for topic in job.topics:
            requests = await self._requests(job, topic)
            for request in requests[: job.examples_per_topic]:
                done += 1
                await self._update(
                    job, message=f"Teacher writing lessons ({done}/{planned}): {topic}"
                )
                answer = await self._teach(job, request)
                if answer:
                    rows.append(chat_row(request, answer))
        return rows

    async def _requests(self, job: LoraJob, topic: str) -> list[str]:
        reply = await self._router.complete(
            [ChatMessage.user(f"Topic: {topic}")],
            model=job.teacher_model or self._default_teacher(),
            system=REQUESTS_PROMPT.format(count=job.examples_per_topic),
            temperature=0.8,
            max_tokens=2000,
        )
        payload = extract_json(reply.text)
        if not isinstance(payload, list):
            return []
        return [str(item).strip() for item in payload if str(item).strip()]

    async def _tool_rows(self, job: LoraJob) -> list[JsonObject]:
        await self._update(job, message="Teacher writing tool-use lessons")
        specs = list(TOOL_SPECS)
        names = {spec.name for spec in specs}
        catalog = "\n".join(
            f"- {spec.name}: {spec.description} "
            f"arguments={json.dumps(spec.parameters.get('properties', {}))}"
            for spec in specs
        )
        count = max(job.examples_per_topic, len(specs))
        reply = await self._router.complete(
            [ChatMessage.user("Write the examples now.")],
            model=job.teacher_model or self._default_teacher(),
            system=TOOL_REQUESTS_PROMPT.format(tools=catalog, count=count),
            temperature=0.7,
            max_tokens=4000,
        )
        payload = extract_json(reply.text)
        system = tool_protocol_instructions(specs)
        rows: list[JsonObject] = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            tool = item.get("tool")
            arguments = item.get("arguments")
            request = str(item.get("request", "")).strip()
            if tool in names and isinstance(arguments, dict) and request:
                call = json.dumps(
                    {"tool": tool, "arguments": arguments}, ensure_ascii=False
                )
                rows.append(chat_row(request, call, system=system))
        return rows

    async def _teach(self, job: LoraJob, prompt: str, *, extra: str = "") -> str:
        try:
            reply = await self._router.complete(
                [ChatMessage.user(prompt)],
                model=job.teacher_model or self._default_teacher(),
                system=f"{EXPERT_PROMPT}\n\n{extra}".strip(),
                temperature=0.3,
                max_tokens=2000,
            )
        except StudioLLMError as error:
            logger.warning("Studio LoRA teacher call failed: {}", error)
            return ""
        return reply.text.strip()

    # ------------------------------------------------------- local runner

    async def probe(self, *, refresh: bool = False) -> JsonObject:
        """Report what this computer can train with, and what can serve results."""
        loop = asyncio.get_running_loop()
        if (
            self._probe_cache
            and not refresh
            and loop.time() - self._probe_cache[0] < 120
        ):
            return self._probe_cache[1]
        settings = self._settings()
        python = settings.studio_lora_python or sys.executable
        report: JsonObject = {"python": python}
        try:
            process = await asyncio.create_subprocess_exec(
                python,
                str(WORKER_PATH),
                "--probe",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), 120)
            if process.returncode == 0:
                report.update(json.loads(stdout.decode("utf-8")))
            else:
                report["error"] = stderr.decode("utf-8", "replace")[-400:]
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            report["error"] = str(error)
        torch_ready = bool(
            report.get("torch") and report.get("transformers") and report.get("peft")
        )
        report["ready"] = torch_ready
        report["accelerator"] = (
            f"GPU: {report.get('gpu')} ({report.get('gpu_memory_gb')} GB)"
            if report.get("cuda")
            else "Apple GPU (MPS)"
            if report.get("mps")
            else "CPU only"
        )
        report["ollama"] = self._ollama() or ""
        llama_cpp = settings.studio_lora_llama_cpp or ""
        report["llama_cpp"] = llama_cpp
        report["llama_cpp_ready"] = bool(
            llama_cpp
            and (Path(llama_cpp).expanduser() / "convert_lora_to_gguf.py").is_file()
        )
        self._probe_cache = (loop.time(), report)
        return report

    def _ollama(self) -> str | None:
        configured = self._settings().studio_lora_ollama
        if configured:
            return configured if Path(configured).expanduser().exists() else None
        return shutil.which("ollama")

    async def start_local(self, job_id: str) -> LoraJob:
        """Run the worker on this computer as a child process."""
        job = await self._store.require(LoraJob, job_id)
        if not job.dataset_ready:
            raise LoraError("The training set is not ready yet.")
        settings = self._settings()
        folder = self.job_dir(job.id)
        folder.mkdir(parents=True, exist_ok=True)
        command = [
            settings.studio_lora_python or sys.executable,
            str(WORKER_PATH),
            "--studio",
            local_proxy_root_url(settings),
            "--job",
            job.id,
            "--workdir",
            str(folder / "work"),
        ]
        if settings.studio_lora_llama_cpp:
            command += [
                "--llama-cpp",
                str(Path(settings.studio_lora_llama_cpp).expanduser()),
            ]
        # The token travels in the environment, not argv, so other programs on
        # this computer cannot read it from the process list.
        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "STUDIO_LORA_TOKEN": job.worker_token,
        }
        if settings.huggingface_api_key:
            env["HF_TOKEN"] = settings.huggingface_api_key
        log = (folder / "worker.log").open("ab")
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(folder),
                env=env,
            )
        except OSError as error:
            log.close()
            raise LoraError(f"Could not start the trainer: {error}") from error
        self._processes[job.id] = process
        self._spawn(self._watch(job.id, process, log))
        return await self._update(
            job, status="running", message="Trainer starting on this computer"
        )

    async def _watch(
        self, job_id: str, process: asyncio.subprocess.Process, log
    ) -> None:
        try:
            code = await process.wait()
        finally:
            log.close()
            self._processes.pop(job_id, None)
        job = await self._store.get(LoraJob, job_id)
        if job is not None and job.status not in TERMINAL:
            tail = await anyio.to_thread.run_sync(lambda: self._log_tail(job_id))
            await self.fail(
                job_id, f"The trainer stopped (exit {code}). {tail}".strip()
            )

    def _log_tail(self, job_id: str, limit: int = 1200) -> str:
        path = self.job_dir(job_id) / "worker.log"
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()

    # -------------------------------------------------------- worker API

    async def authorize(self, job_id: str, token: str) -> LoraJob:
        """Return the job only when the worker presents its own token."""
        job = (
            await self._store.get(LoraJob, job_id)
            if job_id.startswith("lora_")
            else None
        )
        if (
            job is None
            or not job.worker_token
            or not secrets.compare_digest(
                token.encode("utf-8"), job.worker_token.encode("utf-8")
            )
        ):
            raise LoraAuthError("Unknown job or wrong worker token.")
        return job

    def spec(self, job: LoraJob) -> JsonObject:
        """Everything a worker needs to train, and nothing secret."""
        return {
            "job": job.id,
            "base_model": job.base_model,
            "rank": job.rank,
            "alpha": job.alpha,
            "epochs": job.epochs,
            "learning_rate": job.learning_rate,
            "max_seq_len": job.max_seq_len,
            "batch_size": job.batch_size,
            "grad_accum": job.grad_accum,
            "quantize": job.quantize,
            "train_examples": job.train_examples,
            "eval_examples": job.eval_examples,
        }

    async def dataset_path(self, job: LoraJob, split: str) -> Path:
        """Return a split's JSONL once the training set is ready."""
        if not job.dataset_ready:
            raise LoraError("The training set is still being written.")
        if split not in {"train", "eval"}:
            raise LoraError("Split must be train or eval.")
        return self.file_path(job.id, f"{split}.jsonl")

    async def report(self, job: LoraJob, payload: JsonObject) -> JsonObject:
        """Record a worker's progress; tell it to stop if the job was cancelled."""
        current = await self._store.require(LoraJob, job.id)
        if current.status in TERMINAL:
            return {"cancel": True}
        updates: dict[str, object] = {"status": "running", "heartbeat_at": now_ms()}
        metrics: JsonObject = dict(current.metrics)
        step = payload.get("step")
        if isinstance(step, int) and step >= 0:
            updates["step"] = step
        total = payload.get("total")
        if isinstance(total, int) and total >= 0:
            updates["total_steps"] = total
        loss = payload.get("loss")
        if isinstance(loss, int | float):
            updates["loss"] = float(loss)
            existing = metrics.get("loss_curve")
            curve = list(existing) if isinstance(existing, list) else []
            at = step if isinstance(step, int) else current.step
            curve.append([at, round(float(loss), 5)])
            metrics["loss_curve"] = curve[-LOSS_CURVE_LIMIT:]
        before = payload.get("eval_loss_before")
        if isinstance(before, int | float):
            updates["eval_loss_before"] = float(before)
        for key in ("device", "trainable_parameters", "worker", "epoch"):
            if key in payload:
                metrics[key] = payload[key]
        message = payload.get("message")
        if isinstance(message, str) and message:
            updates["message"] = message[:300]
        updates["metrics"] = metrics
        await self._update(current, **updates)
        return {"cancel": False}

    async def receive(
        self, job: LoraJob, name: str, chunks: AsyncIterator[bytes]
    ) -> int:
        """Stream one uploaded result file into the job folder."""
        if name not in UPLOAD_NAMES:
            raise LoraError("Only adapter.zip and adapter.gguf can be uploaded.")
        current = await self._store.require(LoraJob, job.id)
        if current.status in TERMINAL:
            raise LoraError("This job is already finished.")
        folder = self.job_dir(job.id)
        folder.mkdir(parents=True, exist_ok=True)
        partial = folder / f"{name}.part"
        written = 0
        handle = await anyio.to_thread.run_sync(lambda: partial.open("wb"))
        try:
            async for chunk in chunks:
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise LoraError("That upload is larger than the 8 GB limit.")
                await anyio.to_thread.run_sync(handle.write, chunk)
        finally:
            await anyio.to_thread.run_sync(handle.close)
        if written == 0:
            partial.unlink(missing_ok=True)
            raise LoraError("The upload was empty.")
        await anyio.to_thread.run_sync(lambda: partial.replace(folder / name))
        return written

    async def finish(self, job: LoraJob, metrics: JsonObject) -> LoraJob:
        """Accept a finished adapter, register it, and try to serve it."""
        folder = self.job_dir(job.id)
        archive = folder / "adapter.zip"
        if not archive.is_file():
            raise LoraError("Upload adapter.zip before finishing.")
        try:
            await anyio.to_thread.run_sync(
                lambda: extract_archive(archive, folder / "adapter")
            )
        except DownloadError as error:
            raise LoraError(str(error)) from error
        current = await self._store.require(LoraJob, job.id)
        merged = {
            **current.metrics,
            **{k: v for k, v in metrics.items() if k != "loss_curve"},
        }
        after = metrics.get("eval_loss_after")
        before = metrics.get("eval_loss_before")
        finished = await self._update(
            current,
            status="succeeded",
            step=current.total_steps or current.step,
            eval_loss_after=float(after) if isinstance(after, int | float) else None,
            eval_loss_before=(
                float(before)
                if isinstance(before, int | float)
                else current.eval_loss_before
            ),
            metrics=merged,
            message="Trained. Installing the adapter",
        )
        gguf = folder / "adapter.gguf"
        agent = await self._store.get(Agent, job.agent_id)
        await self._store.put(
            ModelAsset.model_validate(
                {
                    "name": f"{agent.name if agent else 'Agent'} LoRA ({job.base_model})",
                    "source_url": f"lora://{job.id}",
                    "path": str(gguf if gguf.is_file() else folder / "adapter"),
                    "kind": "adapter",
                    "status": "ready",
                }
            )
        )
        self._spawn(self.install(job.id))
        return finished

    async def fail(self, job_id: str, error: str) -> LoraJob:
        """Mark a job failed unless it already ended."""
        job = await self._store.require(LoraJob, job_id)
        if job.status in TERMINAL:
            return job
        return await self._update(
            job, status="failed", error=error[:2000], message="Training failed"
        )

    async def cancel(self, job_id: str) -> LoraJob:
        """Stop a job; a local trainer is terminated, a remote one is told to stop."""
        job = await self._store.require(LoraJob, job_id)
        if job.status in TERMINAL:
            return job
        cancelled = await self._update(job, status="cancelled", message="Cancelled")
        process = self._processes.get(job_id)
        if process is not None and process.returncode is None:
            process.terminate()
        return cancelled

    # ----------------------------------------------------------- serving

    def ollama_name(self, job: LoraJob, agent: Agent | None) -> str:
        """Return the Ollama model name a job installs as."""
        return (
            f"studio-{slugify(agent.name if agent else 'agent')}-{job.id[-6:]}".lower()
        )

    def modelfile(self, job: LoraJob) -> str:
        gguf = self.job_dir(job.id) / "adapter.gguf"
        return f"FROM {job.ollama_base}\nADAPTER {gguf}\n"

    async def install(self, job_id: str) -> LoraJob:
        """Load the adapter into Ollama and point the student at it, when possible."""
        job = await self._store.require(LoraJob, job_id)
        agent = await self._store.get(Agent, job.agent_id)
        folder = self.job_dir(job.id)
        gguf = folder / "adapter.gguf"
        if not gguf.is_file():
            return await self._update(
                job,
                message="Trained. To run it in Ollama it needs a GGUF copy: set the "
                "llama.cpp folder in Studio settings (or pass --llama-cpp to the "
                "worker) and train again, or convert adapter.zip yourself.",
            )
        if not job.ollama_base:
            return await self._update(
                job,
                message="Trained. Tell Studio which Ollama model matches the base to "
                "install it, or load adapter.gguf into llama.cpp yourself.",
            )
        name = self.ollama_name(job, agent)
        await anyio.to_thread.run_sync(
            lambda: (folder / "Modelfile").write_text(
                self.modelfile(job), encoding="utf-8"
            )
        )
        ollama = self._ollama()
        if ollama is None:
            return await self._update(
                job,
                served_model="",
                message=f'Trained. Install Ollama, then run: ollama create {name} -f "{folder / "Modelfile"}"',
            )
        for step, args, timeout in (
            (
                "Downloading the base model in Ollama",
                [ollama, "pull", job.ollama_base],
                7200,
            ),
            (
                "Creating the tuned model in Ollama",
                [ollama, "create", name, "-f", str(folder / "Modelfile")],
                1800,
            ),
        ):
            job = await self._update(job, message=step)
            code, output = await _run(args, timeout=timeout, cwd=folder)
            if code != 0:
                return await self._update(
                    job, message=f"Trained, but Ollama refused it: {output[-300:]}"
                )
        job = await self._update(job, served_model=name)
        return await self._switch_agent(job, name)

    async def _switch_agent(self, job: LoraJob, name: str) -> LoraJob:
        agent = await self._store.get(Agent, job.agent_id)
        if agent is None:
            return job
        try:
            served = await self._router.local_models()
        except StudioLLMError:
            served = ()
        match = next((model for model in served if model.split(":")[0] == name), None)
        if match is None:
            return await self._update(
                job,
                message=f"Installed in Ollama as {name}. Point Local Model Server at "
                "Ollama (http://localhost:11434/v1) to use it.",
            )
        previous = agent.model
        await self._store.put(
            agent.model_copy(
                update={"model": f"{LOCAL_MODEL_PREFIX}{match}", "updated_at": now_ms()}
            )
        )
        return await self._update(
            job,
            previous_model=previous,
            message=f"Installed as {match}. {agent.name} now runs the tuned weights.",
        )

    async def revert(self, job_id: str) -> LoraJob:
        """Point the student back at the model it used before this job."""
        job = await self._store.require(LoraJob, job_id)
        agent = await self._store.require(Agent, job.agent_id)
        if not job.previous_model:
            raise LoraError("This job did not change the agent's model.")
        await self._store.put(
            agent.model_copy(
                update={"model": job.previous_model, "updated_at": now_ms()}
            )
        )
        return await self._update(
            job, message=f"{agent.name} is back on {job.previous_model}."
        )

    def worker_commands(self, job: LoraJob, studio_url: str) -> JsonObject:
        """Commands that run this job on another machine, e.g. a rented GPU."""
        url = studio_url.rstrip("/")
        run = f'--studio "{url}" --job {job.id} --token {job.worker_token} --llama-cpp llama.cpp'
        packages = "torch transformers peft accelerate bitsandbytes"
        return {
            "studio_url": url,
            "bash": "\n".join(
                [
                    f'curl -fsSL "{url}/studio/lora/worker.py" -o lora_worker.py',
                    f"pip install -q {packages}",
                    "git clone --depth 1 https://github.com/ggml-org/llama.cpp",
                    f"python lora_worker.py {run}",
                ]
            ),
            "powershell": "\n".join(
                [
                    f'irm "{url}/studio/lora/worker.py" -OutFile lora_worker.py',
                    f"pip install -q {packages}",
                    "git clone --depth 1 https://github.com/ggml-org/llama.cpp",
                    f"python lora_worker.py {run}",
                ]
            ),
        }

    async def _update(self, job: LoraJob, **values: object) -> LoraJob:
        current = await self._store.require(LoraJob, job.id)
        updated = current.model_copy(update={**values, "updated_at": now_ms()})
        await self._store.put(updated)
        return updated


async def _run(args: Sequence[str], *, timeout: float, cwd: Path) -> tuple[int, str]:
    """Run a helper program and return its exit code and combined output."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as error:
        return 127, str(error)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        return 124, f"{args[0]} took longer than {int(timeout)} seconds."
    return process.returncode or 0, stdout.decode("utf-8", "replace")
