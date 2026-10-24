"""Server tuning and local tuning are separate choices, and both finish."""

import json

import httpx
import pytest

from free_claude_code.studio.llm import (
    LLMReply,
    LocalModelsUnavailable,
    LocalOpenAILLM,
    StudioModelRouter,
)
from free_claude_code.studio.models import Agent, TuneJob, TunePack
from free_claude_code.studio.tuning import CloudTuner, LightTuner
from tests.studio.conftest import ScriptedLLM


def trainer(statuses: list[str], *, model: str = "ft:tiny:studio"):
    """A fake fine-tuning API that reports each status in turn."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json={"id": "file_1"})
        if request.method == "POST":
            return httpx.Response(200, json={"id": "job_1"})
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        body = {"status": status}
        if status == "succeeded":
            body["fine_tuned_model"] = model
        return httpx.Response(200, json=body)

    return CloudTuner(
        base_url="https://trainer.test/v1", transport=httpx.MockTransport(handler)
    ), seen


async def cloud_setup(store, router, statuses, **tuner_options):
    cloud, seen = trainer(statuses)
    tuner = LightTuner(
        store=store,
        router=router,
        default_model="p/base",
        cloud=cloud,
        poll_interval=0,
        **tuner_options,
    )
    agent = Agent.model_validate({"name": "Tuned", "model": "openai/base"})
    await store.put(agent)
    pack = await tuner.create_pack(agent, backend="cloud")
    await tuner.add_samples(pack.id, [("q1", "a1"), ("q2", "a2")])
    job = await tuner.start(pack.id)
    return tuner, agent, pack, job, seen


@pytest.mark.asyncio
async def test_server_tuning_waits_for_the_trainer_and_switches_the_agent(
    make_studio, store
):
    studio, _ = make_studio([])
    tuner, agent, pack, job, seen = await cloud_setup(
        store,
        studio._router,
        ["validating_files", "running", "succeeded"],
        cloud_provider="openai",
    )

    finished = await tuner.run(job.id)

    assert finished.status == "succeeded"
    assert finished.progress == 1.0
    assert seen.count("GET /v1/fine_tuning/jobs/job_1") == 3
    reloaded = await store.require(Agent, agent.id)
    assert reloaded.model == "openai/ft:tiny:studio"
    assert reloaded.tune_pack_id == pack.id
    tuned = await store.require(TunePack, pack.id)
    assert tuned.remote_model == "ft:tiny:studio"


@pytest.mark.asyncio
async def test_server_tuning_without_a_provider_reports_the_model(make_studio, store):
    studio, _ = make_studio([])
    tuner, agent, _, job, _ = await cloud_setup(store, studio._router, ["succeeded"])

    finished = await tuner.run(job.id)

    assert finished.status == "succeeded"
    assert "ft:tiny:studio" in finished.message
    assert (await store.require(Agent, agent.id)).model == "openai/base"


@pytest.mark.asyncio
async def test_a_failed_server_run_is_reported(make_studio, store):
    studio, _ = make_studio([])
    tuner, _, _, job, _ = await cloud_setup(store, studio._router, ["failed"])

    finished = await tuner.run(job.id)

    assert finished.status == "failed"
    assert "failed" in (finished.error or "")


@pytest.mark.asyncio
async def test_a_long_server_run_can_be_refreshed_later(make_studio, store):
    studio, _ = make_studio([])
    statuses = ["running"]
    tuner, _, _, job, _ = await cloud_setup(store, studio._router, statuses, max_wait=0)

    waiting = await tuner.run(job.id)
    assert waiting.status == "running"
    assert "Refresh" in waiting.message

    statuses[0] = "succeeded"
    refreshed = await tuner.refresh(job.id)
    assert refreshed.status == "succeeded"


@pytest.mark.asyncio
async def test_the_backend_is_chosen_per_run(make_studio):
    studio, _ = make_studio(
        [],
        STUDIO_LIGHT_TUNING_ENABLED=True,
        STUDIO_CLOUD_TUNING_BASE_URL="https://trainer.test/v1",
    )
    agent = await studio.create_agent(name="Both", tools=[])
    pack = await studio.create_pack(agent.id)
    await studio.add_samples(pack.id, [("a", "b"), ("c", "d")])

    job = await studio.start_tuning(pack.id, backend="cloud", background=False)

    assert job.backend == "cloud"
    assert (await studio.store.require(TunePack, pack.id)).backend == "cloud"
    options = studio.tuning_options()
    assert options["local"]["enabled"] and options["server"]["enabled"]


@pytest.mark.asyncio
async def test_the_chat_toggle_alone_enables_local_tuning(make_studio):
    studio, _ = make_studio(
        lambda system, prompt: LLMReply(text="{}"), STUDIO_LIGHT_TUNING_ENABLED=False
    )
    agent = await studio.create_agent(name="Small", model="local/tiny", tools=[])
    chat = await studio.create_chat(agent_id=agent.id)

    result = await studio.update_chat_settings(chat.id, {"light_tuning": True})
    assert result.opened_chat is not None
    pack_id = str(result.opened_chat.settings["pack_id"])
    pack = await studio.store.require(TunePack, pack_id)
    assert pack.opted_in is True
    assert pack.teacher_model == "nvidia_nim/test-model"  # the server coaches

    await studio.add_samples(pack_id, [("a", "b"), ("c", "d")])
    job = await studio.start_tuning(pack_id, background=False)
    assert job.status == "queued"


@pytest.mark.asyncio
async def test_a_server_teacher_writes_the_cards_the_local_student_is_scored_on(
    make_studio,
):
    card = json.dumps({"preamble": "Answer with the time only.", "rules": []})

    def respond(system: str, prompt: str) -> LLMReply:
        if "tuning a small assistant" in system:
            return LLMReply(text=card)
        return LLMReply(text="06:12")

    studio, model = make_studio(
        respond, STUDIO_LIGHT_TUNING_ENABLED=True, STUDIO_TUNING_ROUNDS=1
    )
    student = await studio.create_agent(name="Student2", model="local/tiny", tools=[])
    pack = await studio.create_pack(student.id, teacher_model="nvidia_nim/big")
    await studio.add_samples(pack.id, [("High tide?", "06:12"), ("Next?", "06:12")])

    job = await studio.start_tuning(pack.id, background=False)
    finished = await studio.run_tuning(job.id)

    assert finished.status == "succeeded"
    proposals = [
        call for call in model.calls if "tuning a small assistant" in call["system"]
    ]
    evaluations = [call for call in model.calls if call not in proposals]
    assert {call["model"] for call in proposals} == {"nvidia_nim/big"}
    assert {call["model"] for call in evaluations} == {"tiny"}


@pytest.mark.asyncio
async def test_local_models_are_listed_from_the_runtime():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200, json={"data": [{"id": "qwen3-0.6b"}, {"id": "llama-3.2-1b"}]}
        )

    client = LocalOpenAILLM(
        base_url="http://127.0.0.1:1234/v1", transport=httpx.MockTransport(handler)
    )
    assert await client.list_models() == ("qwen3-0.6b", "llama-3.2-1b")


@pytest.mark.asyncio
async def test_an_unreachable_runtime_is_reported_not_raised(make_studio):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = LocalOpenAILLM(
        base_url="http://127.0.0.1:1234/v1", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(LocalModelsUnavailable):
        await client.list_models()

    studio, _ = make_studio([])
    report = await studio.local_models()  # the scripted router has no lister
    assert report["reachable"] is True and report["models"] == []


@pytest.mark.asyncio
async def test_jobs_keep_their_backend(store):
    job = TuneJob.model_validate({"pack_id": "p", "agent_id": "a", "backend": "cloud"})
    await store.put(job)
    assert (await store.require(TuneJob, job.id)).backend == "cloud"


def test_the_trainer_gets_the_bare_model_name(store):
    router = StudioModelRouter(proxy=ScriptedLLM([]), local=ScriptedLLM([]))
    tuner = LightTuner(
        store=store, router=router, default_model="p/m", cloud_provider="together"
    )
    assert tuner.trainer_model("openai/gpt-4o-mini") == "gpt-4o-mini"
    assert (
        tuner.trainer_model("together/meta-llama/Llama-3-8b") == "meta-llama/Llama-3-8b"
    )
    assert tuner.trainer_model("meta-llama/Llama-3-8b") == "meta-llama/Llama-3-8b"
    assert tuner.trainer_model("gpt-4o-mini") == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_server_tuning_refuses_local_models(make_studio):
    studio, _ = make_studio([], STUDIO_CLOUD_TUNING_BASE_URL="https://trainer.test/v1")
    agent = await studio.create_agent(name="Pocket", model="local/tiny", tools=[])
    pack = await studio.create_pack(agent.id)
    await studio.add_samples(pack.id, [("a", "b"), ("c", "d")])

    with pytest.raises(Exception, match="local model"):
        await studio.start_tuning(pack.id, backend="cloud")
