"""Very light tuning searches an instruction pack and proves it improved."""

import json

import httpx
import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.models import Agent, TunePack, TuneSample
from free_claude_code.studio.tuning import (
    CloudTuner,
    TuningError,
    pack_exemplars,
    pack_system_text,
    select_exemplars,
    split_samples,
    token_f1,
)


def test_token_f1_scores_overlap():
    assert token_f1("high tide at six", "high tide at six") == 1.0
    assert token_f1("completely different", "high tide") == 0.0
    assert 0.0 < token_f1("high tide soon", "high tide at six") < 1.0


def test_exemplar_selection_maximizes_coverage():
    samples = [
        TuneSample.model_validate(
            {"pack_id": "p", "prompt": "a", "completion": "moon"}
        ),
        TuneSample.model_validate(
            {"pack_id": "p", "prompt": "a", "completion": "moon"}
        ),
        TuneSample.model_validate({"pack_id": "p", "prompt": "b", "completion": "sun"}),
    ]
    chosen = select_exemplars(samples, limit=2)
    assert {item.completion for item in chosen} == {"moon", "sun"}


def test_split_holds_out_a_tail():
    samples = [
        TuneSample.model_validate(
            {"pack_id": "p", "prompt": f"q{index}", "completion": "a"}
        )
        for index in range(8)
    ]
    split = split_samples(samples)
    assert len(split.evaluation) == 2
    assert len(split.train) == 6


def test_split_honors_explicit_marks():
    train = TuneSample.model_validate(
        {"pack_id": "p", "prompt": "q", "completion": "a", "split": "train"}
    )
    held = TuneSample.model_validate(
        {"pack_id": "p", "prompt": "q2", "completion": "b", "split": "eval"}
    )
    split = split_samples([train, held])
    assert split.train == (train,)
    assert split.evaluation == (held,)


def test_pack_renders_as_prompt_material():
    pack = TunePack.model_validate(
        {
            "agent_id": "agt",
            "name": "p",
            "base_model": "m",
            "preamble": "Answer in one line.",
            "style_rules": ("Never pad.",),
            "exemplars": ({"prompt": "hi", "completion": "hello"},),
        }
    )
    text = pack_system_text(pack)
    assert "Answer in one line." in text
    assert "- Never pad." in text
    assert [message.content for message in pack_exemplars(pack)] == ["hi", "hello"]


@pytest.mark.asyncio
async def test_light_tuning_improves_and_activates_a_pack(make_studio):
    card = json.dumps(
        {"preamble": "Answer with the tide time only.", "rules": ["No prose."]}
    )

    def respond(system: str, prompt: str) -> LLMReply:
        if "tuning a small assistant" in system:
            return LLMReply(text=card)
        if "tide time only" in system:
            return LLMReply(text="06:12")
        return LLMReply(text="I think it might be around six in the morning.")

    studio, _ = make_studio(
        respond, STUDIO_LIGHT_TUNING_ENABLED=True, STUDIO_TUNING_ROUNDS=1
    )
    agent = await studio.create_agent(name="Tuned", tools=[])
    pack = await studio.create_pack(agent.id)
    await studio.add_samples(
        pack.id,
        [
            ("When is high tide?", "06:12"),
            ("When is the next high tide?", "18:40"),
            ("High tide today?", "06:12"),
        ],
    )

    job = await studio.start_tuning(pack.id)
    await studio.wait_for_background()

    finished = await studio.job(job.id)
    assert finished.status == "succeeded"
    assert finished.score is not None
    assert finished.baseline_score is not None
    assert finished.score > finished.baseline_score

    tuned = await studio.store.require(TunePack, pack.id)
    assert tuned.active is True
    assert tuned.preamble == "Answer with the tide time only."
    assert tuned.style_rules == ("No prose.",)
    assert tuned.metrics["method"] == "instruction-pack search (no gradients)"

    reloaded = await studio.store.require(Agent, agent.id)
    assert reloaded.tune_pack_id == pack.id


@pytest.mark.asyncio
async def test_tuned_pack_reaches_the_next_chat(make_studio):
    studio, model = make_studio([LLMReply(text="06:12")])
    agent = await studio.create_agent(name="Tuned", tools=[])
    pack = await studio.create_pack(agent.id)
    tuned = (await studio.store.require(TunePack, pack.id)).model_copy(
        update={
            "preamble": "Answer with the tide time only.",
            "active": True,
            "exemplars": ({"prompt": "High tide?", "completion": "06:12"},),
        }
    )
    await studio.store.put(tuned)
    await studio.update_agent(agent.id, {"tune_pack_id": pack.id})

    chat = await studio.create_chat(agent_id=agent.id)
    await studio.send(chat.id, "When is high tide?")

    call = model.calls[0]
    assert "Answer with the tide time only." in str(call["system"])
    assert any(message.content == "High tide?" for message in call["messages"])


@pytest.mark.asyncio
async def test_tuning_requires_examples_and_the_toggle(make_studio):
    studio, _ = make_studio([], STUDIO_LIGHT_TUNING_ENABLED=True)
    agent = await studio.create_agent(name="Bare", tools=[])
    pack = await studio.create_pack(agent.id)

    with pytest.raises(Exception, match="at least two examples"):
        await studio.start_tuning(pack.id)

    off, _ = make_studio([], STUDIO_LIGHT_TUNING_ENABLED=False)
    with pytest.raises(Exception, match="Light tuning is off"):
        await off.start_tuning(pack.id)


@pytest.mark.asyncio
async def test_cancelled_jobs_stop_the_run(make_studio):
    studio, _ = make_studio(
        lambda system, prompt: LLMReply(text="{}"),
        STUDIO_LIGHT_TUNING_ENABLED=True,
    )
    agent = await studio.create_agent(name="Stopper", tools=[])
    pack = await studio.create_pack(agent.id)
    await studio.add_samples(pack.id, [("a", "b"), ("c", "d"), ("e", "f")])
    job = await studio.start_tuning(pack.id, background=False)
    await studio.cancel_job(job.id)
    await studio.run_tuning(job.id)

    assert (await studio.job(job.id)).status == "cancelled"


def test_cloud_jsonl_is_chat_shaped():
    samples = [
        TuneSample.model_validate({"pack_id": "p", "prompt": "q", "completion": "a"})
    ]
    line = json.loads(CloudTuner.jsonl(samples, system="be brief"))
    assert [item["role"] for item in line["messages"]] == [
        "system",
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_cloud_backend_submits_and_polls():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json={"id": "file_1"})
        if request.method == "POST":
            return httpx.Response(200, json={"id": "job_1"})
        return httpx.Response(
            200, json={"status": "succeeded", "fine_tuned_model": "tuned-model"}
        )

    tuner = CloudTuner(
        base_url="https://trainer.test/v1",
        api_key="k",
        transport=httpx.MockTransport(handler),
    )
    samples = [
        TuneSample.model_validate({"pack_id": "p", "prompt": "q", "completion": "a"})
    ]

    job_id = await tuner.submit(base_model="base", samples=samples)
    status, model = await tuner.poll(job_id)

    assert job_id == "job_1"
    assert (status, model) == ("succeeded", "tuned-model")
    assert seen == [
        "POST /v1/files",
        "POST /v1/fine_tuning/jobs",
        "GET /v1/fine_tuning/jobs/job_1",
    ]


@pytest.mark.asyncio
async def test_cloud_backend_needs_configuration(make_studio):
    studio, _ = make_studio(
        [],
        STUDIO_LIGHT_TUNING_ENABLED=True,
        STUDIO_TUNING_BACKEND="cloud",
    )
    agent = await studio.create_agent(name="Cloudy", tools=[])
    pack = await studio.create_pack(agent.id)
    await studio.add_samples(pack.id, [("a", "b"), ("c", "d")])

    job = await studio.start_tuning(pack.id)
    await studio.wait_for_background()

    finished = await studio.job(job.id)
    assert finished.status == "failed"
    assert "Cloud tuning is not configured" in (finished.error or "")


def test_tuning_error_is_a_runtime_error():
    assert issubclass(TuningError, RuntimeError)
