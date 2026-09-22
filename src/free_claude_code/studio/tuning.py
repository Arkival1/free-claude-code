"""Very light, phone-sized tuning plus delegation to a cloud trainer."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from loguru import logger

from free_claude_code.core.json_types import JsonObject

from .llm import ChatMessage, StudioLLMError, StudioModelRouter
from .models import Agent, TuneJob, TunePack, TuneSample, now_ms
from .store import StudioStore

MAX_EXEMPLARS = 4
MAX_EVAL_SAMPLES = 6
DEFAULT_ROUNDS = 3
_WORD_PATTERN = re.compile(r"[a-z0-9']+")

STYLE_REQUEST = (
    "You are tuning a small assistant. Read the example request/response pairs "
    "and write the shortest instruction card that would make a model answer the "
    "same way. Reply with JSON only:\n"
    '{"preamble": "<one or two sentences>", "rules": ["<rule>", "..."]}\n'
    "Rules must be concrete and observable (length, tone, format, vocabulary). "
    "Use at most 5 rules."
)


class TuningError(RuntimeError):
    """Raised when a tuning run cannot start or cannot continue."""


def tokens(text: str) -> list[str]:
    """Return comparable lowercase tokens for overlap scoring."""
    return _WORD_PATTERN.findall(text.lower())


def token_f1(prediction: str, target: str) -> float:
    """Return the token overlap F1 between a prediction and its target."""
    predicted = tokens(prediction)
    expected = tokens(target)
    if not predicted or not expected:
        return 1.0 if predicted == expected else 0.0
    counts: dict[str, int] = {}
    for token in expected:
        counts[token] = counts.get(token, 0) + 1
    shared = 0
    for token in predicted:
        if counts.get(token, 0) > 0:
            counts[token] -= 1
            shared += 1
    if shared == 0:
        return 0.0
    precision = shared / len(predicted)
    recall = shared / len(expected)
    return 2 * precision * recall / (precision + recall)


def select_exemplars(
    samples: Sequence[TuneSample], *, limit: int = MAX_EXEMPLARS
) -> tuple[TuneSample, ...]:
    """Greedily pick the samples that cover the most distinct vocabulary."""
    chosen: list[TuneSample] = []
    covered: set[str] = set()
    remaining = list(samples)
    while remaining and len(chosen) < limit:
        best = max(
            remaining,
            key=lambda sample: len(
                set(tokens(f"{sample.prompt} {sample.completion}")) - covered
            ),
        )
        remaining.remove(best)
        covered |= set(tokens(f"{best.prompt} {best.completion}"))
        chosen.append(best)
    return tuple(chosen)


def pack_system_text(pack: TunePack) -> str:
    """Render a tune pack as system guidance for the tuned agent."""
    parts: list[str] = []
    if pack.preamble.strip():
        parts.append(pack.preamble.strip())
    if pack.style_rules:
        rules = "\n".join(f"- {rule}" for rule in pack.style_rules)
        parts.append(f"Always follow these tuned rules:\n{rules}")
    return "\n\n".join(parts)


def pack_exemplars(pack: TunePack) -> list[ChatMessage]:
    """Render a tune pack's exemplars as prior conversation turns."""
    messages: list[ChatMessage] = []
    for exemplar in pack.exemplars:
        prompt = exemplar.get("prompt")
        completion = exemplar.get("completion")
        if isinstance(prompt, str) and isinstance(completion, str):
            messages.append(ChatMessage.user(prompt))
            messages.append(ChatMessage.assistant(completion))
    return messages


@dataclass(frozen=True, slots=True)
class SplitSamples:
    """Training and held-out evaluation pairs for one run."""

    train: tuple[TuneSample, ...]
    evaluation: tuple[TuneSample, ...]


def split_samples(samples: Sequence[TuneSample]) -> SplitSamples:
    """Split samples, honoring explicit splits and holding out a tail otherwise."""
    explicit_eval = tuple(item for item in samples if item.split == "eval")
    explicit_train = tuple(item for item in samples if item.split == "train")
    if explicit_eval and explicit_train:
        return SplitSamples(explicit_train, explicit_eval[:MAX_EVAL_SAMPLES])
    ordered = tuple(samples)
    if len(ordered) < 2:
        return SplitSamples(ordered, ordered)
    held = max(1, min(MAX_EVAL_SAMPLES, len(ordered) // 4))
    return SplitSamples(ordered[:-held], ordered[-held:])


class CloudTuner:
    """Submit and poll an OpenAI-compatible fine-tuning job."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        headers = {}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, headers=headers
        )

    @staticmethod
    def jsonl(samples: Sequence[TuneSample], *, system: str = "") -> str:
        """Render samples as chat fine-tuning JSONL."""
        lines: list[str] = []
        for sample in samples:
            messages: list[JsonObject] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": sample.prompt})
            messages.append({"role": "assistant", "content": sample.completion})
            lines.append(json.dumps({"messages": messages}))
        return "\n".join(lines)

    async def submit(
        self, *, base_model: str, samples: Sequence[TuneSample], system: str = ""
    ) -> str:
        """Upload training data, create a job, and return the remote job id."""
        payload = self.jsonl(samples, system=system).encode("utf-8")
        async with self._client() as client:
            upload = await client.post(
                f"{self._base_url}/files",
                files={"file": ("studio-tuning.jsonl", payload, "application/jsonl")},
                data={"purpose": "fine-tune"},
            )
            if upload.status_code >= 400:
                raise TuningError(
                    f"Cloud trainer rejected the dataset ({upload.status_code})."
                )
            file_id = str(upload.json().get("id", ""))
            if not file_id:
                raise TuningError("Cloud trainer returned no file id.")
            created = await client.post(
                f"{self._base_url}/fine_tuning/jobs",
                json={"training_file": file_id, "model": base_model},
            )
            if created.status_code >= 400:
                raise TuningError(
                    f"Cloud trainer rejected the job ({created.status_code})."
                )
            job_id = str(created.json().get("id", ""))
        if not job_id:
            raise TuningError("Cloud trainer returned no job id.")
        return job_id

    async def poll(self, remote_job_id: str) -> tuple[str, str | None]:
        """Return the remote job status and the tuned model when finished."""
        async with self._client() as client:
            response = await client.get(
                f"{self._base_url}/fine_tuning/jobs/{remote_job_id}"
            )
        if response.status_code >= 400:
            raise TuningError(
                f"Cloud trainer status check failed ({response.status_code})."
            )
        body = response.json()
        model = body.get("fine_tuned_model")
        return str(body.get("status", "unknown")), (
            str(model) if isinstance(model, str) else None
        )


class LightTuner:
    """Tune by search over a tiny instruction pack, not by gradient descent."""

    def __init__(
        self,
        *,
        store: StudioStore,
        router: StudioModelRouter,
        default_model: str,
        rounds: int = DEFAULT_ROUNDS,
        cloud: CloudTuner | None = None,
    ) -> None:
        self._store = store
        self._router = router
        self._default_model = default_model
        self._rounds = max(1, min(rounds, 8))
        self._cloud = cloud

    async def create_pack(
        self,
        agent: Agent,
        *,
        name: str = "",
        backend: str = "local_light",
        base_model: str = "",
    ) -> TunePack:
        """Create an inactive pack the user can fill with examples."""
        pack = TunePack.model_validate(
            {
                "agent_id": agent.id,
                "name": name or f"{agent.name} light tune",
                "base_model": base_model or agent.model or self._default_model,
                "backend": backend,
            }
        )
        await self._store.put(pack)
        return pack

    async def add_samples(
        self, pack_id: str, pairs: Sequence[tuple[str, str]], *, split: str = "train"
    ) -> int:
        """Attach prompt/completion pairs to a pack."""
        pack = await self._store.require(TunePack, pack_id)
        samples = [
            TuneSample.model_validate(
                {
                    "pack_id": pack.id,
                    "prompt": prompt.strip(),
                    "completion": completion.strip(),
                    "split": split,
                }
            )
            for prompt, completion in pairs
            if prompt.strip() and completion.strip()
        ]
        return await self._store.put_many(samples)

    async def start(self, pack_id: str) -> TuneJob:
        """Create a queued job for one pack."""
        pack = await self._store.require(TunePack, pack_id)
        samples = await self._store.find(TuneSample, where={"pack_id": pack.id})
        if len(samples) < 2:
            raise TuningError("Add at least two examples before tuning.")
        job = TuneJob.model_validate(
            {
                "pack_id": pack.id,
                "agent_id": pack.agent_id,
                "backend": pack.backend,
                "total_steps": self._rounds + 1 if pack.backend == "local_light" else 3,
                "message": "Queued",
            }
        )
        await self._store.put(job)
        return job

    async def run(self, job_id: str) -> TuneJob:
        """Execute one queued job and return its final state."""
        job = await self._store.require(TuneJob, job_id)
        if job.status not in {"queued", "running"}:
            return job
        try:
            if job.backend == "cloud":
                return await self._run_cloud(job)
            return await self._run_local(job)
        except (TuningError, StudioLLMError, httpx.HTTPError) as error:
            logger.warning("Studio tuning job {} failed: {}", job.id, error)
            return await self._fail(job, str(error))

    async def _fail(self, job: TuneJob, message: str) -> TuneJob:
        failed = job.model_copy(
            update={
                "status": "failed",
                "error": message,
                "message": "Tuning failed",
                "updated_at": now_ms(),
            }
        )
        await self._store.put(failed)
        return failed

    async def _progress(
        self, job: TuneJob, *, step: int, message: str, score: float | None = None
    ) -> TuneJob:
        current = await self._store.require(TuneJob, job.id)
        if current.status == "cancelled":
            raise TuningError("Tuning was cancelled.")
        updated = current.model_copy(
            update={
                "status": "running",
                "step": step,
                "message": message,
                "score": score if score is not None else current.score,
                "updated_at": now_ms(),
            }
        )
        await self._store.put(updated)
        return updated

    async def _run_local(self, job: TuneJob) -> TuneJob:
        pack = await self._store.require(TunePack, job.pack_id)
        samples = await self._store.find(TuneSample, where={"pack_id": pack.id})
        split = split_samples(samples)
        model = pack.base_model or self._default_model
        job = await self._progress(job, step=1, message="Measuring the base model")
        baseline = await self._evaluate(model, "", (), split.evaluation)
        best_preamble = ""
        best_rules: tuple[str, ...] = ()
        best_exemplars = select_exemplars(split.train)
        best_score = await self._evaluate(model, "", best_exemplars, split.evaluation)
        for round_index in range(1, self._rounds + 1):
            job = await self._progress(
                job,
                step=1 + round_index,
                message=f"Round {round_index} of {self._rounds}",
                score=best_score,
            )
            preamble, rules = await self._propose(model, split.train, round_index)
            candidate = await self._evaluate(
                model,
                _render_card(preamble, rules),
                best_exemplars,
                split.evaluation,
            )
            if candidate > best_score:
                best_score, best_preamble, best_rules = candidate, preamble, rules
        tuned = pack.model_copy(
            update={
                "preamble": best_preamble,
                "style_rules": best_rules,
                "exemplars": tuple(
                    {"prompt": item.prompt, "completion": item.completion}
                    for item in best_exemplars
                ),
                "metrics": {
                    "baseline_score": round(baseline, 4),
                    "score": round(best_score, 4),
                    "rounds": self._rounds,
                    "train_samples": len(split.train),
                    "eval_samples": len(split.evaluation),
                    "method": "instruction-pack search (no gradients)",
                },
                "version": pack.version + 1,
                "active": True,
                "updated_at": now_ms(),
            }
        )
        current = await self._store.require(TuneJob, job.id)
        if current.status == "cancelled":
            return current
        await self._store.put(tuned)
        await self._activate(tuned)
        finished = job.model_copy(
            update={
                "status": "succeeded",
                "step": job.total_steps,
                "baseline_score": round(baseline, 4),
                "score": round(best_score, 4),
                "message": (
                    f"Tuned: {baseline:.2f} → {best_score:.2f} "
                    f"on {len(split.evaluation)} held-out examples"
                ),
                "updated_at": now_ms(),
            }
        )
        await self._store.put(finished)
        return finished

    async def _propose(
        self, model: str, train: Sequence[TuneSample], round_index: int
    ) -> tuple[str, tuple[str, ...]]:
        rendered = "\n\n".join(
            f"Request: {sample.prompt}\nResponse: {sample.completion}"
            for sample in train[:8]
        )
        hint = (
            "Write a different, sharper card than an obvious first attempt."
            if round_index > 1
            else ""
        )
        reply = await self._router.complete(
            [ChatMessage.user(f"{rendered}\n\n{hint}".strip())],
            model=model,
            system=STYLE_REQUEST,
            temperature=0.3 + 0.2 * round_index,
            max_tokens=512,
        )
        return _parse_card(reply.text)

    async def _evaluate(
        self,
        model: str,
        card: str,
        exemplars: Sequence[TuneSample],
        evaluation: Sequence[TuneSample],
    ) -> float:
        if not evaluation:
            return 0.0
        history: list[ChatMessage] = []
        for exemplar in exemplars:
            history.append(ChatMessage.user(exemplar.prompt))
            history.append(ChatMessage.assistant(exemplar.completion))
        total = 0.0
        for sample in evaluation:
            reply = await self._router.complete(
                [*history, ChatMessage.user(sample.prompt)],
                model=model,
                system=card,
                temperature=0.0,
                max_tokens=384,
            )
            total += token_f1(reply.text, sample.completion)
        return total / len(evaluation)

    async def _activate(self, pack: TunePack) -> None:
        agent = await self._store.get(Agent, pack.agent_id)
        if agent is None:
            return
        await self._store.put(
            agent.model_copy(update={"tune_pack_id": pack.id, "updated_at": now_ms()})
        )
        for other in await self._store.find(
            TunePack, where={"agent_id": pack.agent_id}
        ):
            if other.id != pack.id and other.active:
                await self._store.put(other.model_copy(update={"active": False}))

    async def _run_cloud(self, job: TuneJob) -> TuneJob:
        if self._cloud is None:
            raise TuningError(
                "Cloud tuning is not configured. Set the cloud trainer URL and key."
            )
        pack = await self._store.require(TunePack, job.pack_id)
        samples = await self._store.find(TuneSample, where={"pack_id": pack.id})
        job = await self._progress(job, step=1, message="Uploading training data")
        remote_id = await self._cloud.submit(
            base_model=pack.base_model or self._default_model,
            samples=samples,
            system=pack.preamble,
        )
        await self._store.put(
            pack.model_copy(update={"remote_job_id": remote_id, "updated_at": now_ms()})
        )
        job = await self._progress(job, step=2, message="Training in the cloud")
        status, tuned_model = await self._cloud.poll(remote_id)
        if status in {"failed", "cancelled"}:
            raise TuningError(f"Cloud trainer reported status {status}.")
        if tuned_model:
            updated = await self._store.require(TunePack, pack.id)
            await self._store.put(
                updated.model_copy(
                    update={
                        "remote_model": tuned_model,
                        "active": True,
                        "updated_at": now_ms(),
                    }
                )
            )
        finished = job.model_copy(
            update={
                "status": "succeeded" if tuned_model else "running",
                "step": 3 if tuned_model else 2,
                "message": (
                    f"Cloud model ready: {tuned_model}"
                    if tuned_model
                    else f"Cloud job {remote_id} is {status}"
                ),
                "updated_at": now_ms(),
            }
        )
        await self._store.put(finished)
        return finished


def _render_card(preamble: str, rules: Sequence[str]) -> str:
    parts = [preamble.strip()]
    if rules:
        parts.append("\n".join(f"- {rule}" for rule in rules))
    return "\n\n".join(part for part in parts if part)


def _parse_card(text: str) -> tuple[str, tuple[str, ...]]:
    """Read a proposed style card, tolerating prose around the JSON."""
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            preamble = payload.get("preamble")
            rules = payload.get("rules")
            return (
                preamble.strip() if isinstance(preamble, str) else "",
                tuple(
                    str(rule).strip()
                    for rule in (rules if isinstance(rules, list) else [])
                    if str(rule).strip()
                )[:5],
            )
    stripped = text.strip()
    return (stripped[:400], ()) if stripped else ("", ())
