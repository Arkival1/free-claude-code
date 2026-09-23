"""LoRA jobs: teacher-written data, the worker protocol, and installing results."""

import io
import json
import os
import stat
import zipfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.core.json_types import JsonObject
from free_claude_code.studio import lora_worker
from free_claude_code.studio.llm import LLMReply, StudioModelRouter
from free_claude_code.studio.lora import split_rows
from free_claude_code.studio.models import Agent, LoraJob, ModelAsset, TuneSample
from tests.api.support import create_test_app
from tests.studio.conftest import ScriptedLLM


def teacher(system: str, prompt: str) -> LLMReply:
    if "training curriculum" in system:
        return LLMReply(text=json.dumps([f"{prompt} question {i}" for i in range(4)]))
    if "call tools" in system:
        return LLMReply(
            text=json.dumps(
                [
                    {
                        "request": "Make a page",
                        "tool": "write_file",
                        "arguments": {"path": "index.html", "content": "<h1>x</h1>"},
                    },
                    {
                        "request": "Hack the planet",
                        "tool": "not_a_tool",
                        "arguments": {},
                    },
                ]
            )
        )
    return LLMReply(text=f"Ideal answer for: {prompt}")


async def lora_job(studio, **overrides):
    student = await studio.create_agent(name="Pocket", model="local/tiny", tools=[])
    values = {
        "agent_id": student.id,
        "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
        "runner": "remote",
        "sources": ["topics", "tools"],
        "topics": ["Python", "CSS"],
        "examples_per_topic": 4,
    }
    values.update(overrides)
    job = await studio.lora.create(**values)
    await studio.wait_for_background()
    return student, await studio.store.require(LoraJob, job.id)


def test_held_out_split_is_deterministic():
    rows: list[JsonObject] = [{"i": index} for index in range(20)]
    train, held = split_rows(rows)
    assert len(held) == 2 and len(train) == 18
    assert split_rows(rows) == (train, held)
    assert split_rows(rows[:5])[1] == []


@pytest.mark.asyncio
async def test_the_teacher_writes_a_training_set(make_studio):
    studio, model = make_studio(teacher)
    _student, job = await lora_job(studio)

    assert job.dataset_ready is True
    assert job.ollama_base == "qwen2.5:0.5b"
    assert job.teacher_model == "nvidia_nim/test-model"
    assert (
        job.train_examples + job.eval_examples == 9
    )  # 8 topic lessons + 1 valid tool call
    rows = [
        json.loads(line)
        for line in studio.lora.file_path(job.id, "train.jsonl")
        .read_text()
        .splitlines()
    ]
    tool_rows = [row for row in rows if row["messages"][0]["role"] == "system"]
    for row in rows:
        assert row["messages"][-1]["role"] == "assistant"
    if tool_rows:
        assert (
            json.loads(tool_rows[0]["messages"][-1]["content"])["tool"] == "write_file"
        )
    assert "Run the worker command" in job.message
    assert {call["model"] for call in model.calls} == {"nvidia_nim/test-model"}


@pytest.mark.asyncio
async def test_examples_and_classes_feed_the_set_too(make_studio):
    studio, _ = make_studio(teacher)
    student = await studio.create_agent(name="Pocket", model="local/tiny", tools=[])
    pack = await studio.create_pack(student.id)
    await studio.add_samples(pack.id, [(f"q{i}", f"a{i}") for i in range(5)])

    job = await studio.lora.create(
        agent_id=student.id,
        base_model="Qwen/Qwen2.5-0.5B-Instruct",
        runner="remote",
        sources=["examples"],
    )
    await studio.wait_for_background()

    stored = await studio.store.require(LoraJob, job.id)
    assert stored.train_examples + stored.eval_examples == 5


@pytest.mark.asyncio
async def test_too_little_data_fails_clearly(make_studio):
    studio, _ = make_studio(teacher)
    student = await studio.create_agent(name="Pocket", model="local/tiny", tools=[])
    job = await studio.lora.create(
        agent_id=student.id,
        base_model="Qwen/Qwen2.5-0.5B-Instruct",
        sources=["examples"],
    )
    await studio.wait_for_background()

    stored = await studio.store.require(LoraJob, job.id)
    assert stored.status == "failed"
    assert "at least 4" in (stored.error or "")


@pytest.mark.asyncio
async def test_bad_requests_are_refused(make_studio):
    studio, _ = make_studio(teacher)
    student = await studio.create_agent(name="Pocket", tools=[])
    for kwargs, match in (
        ({"base_model": "local/tiny"}, "Hugging Face"),
        ({"base_model": "Qwen/Qwen3-8B", "runner": "cloud"}, "remote worker"),
        ({"base_model": "Qwen/Qwen3-8B", "sources": ["nope"]}, "source"),
        ({"base_model": "Qwen/Qwen3-8B", "sources": ["topics"]}, "topic"),
        (
            {"base_model": "Qwen/Qwen3-8B", "hyper": {"quantize": "8bit"}},
            "Invalid training settings",
        ),
    ):
        with pytest.raises(Exception, match=match):
            await studio.lora.create(agent_id=student.id, **kwargs)


def adapter_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("adapter_config.json", "{}")
        bundle.writestr("adapter_model.safetensors", b"\x00" * 64)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_the_worker_protocol_end_to_end(make_studio, tmp_path):
    studio, _ = make_studio(teacher)
    _student, job = await lora_job(studio)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        view = (await client.get(f"/studio/api/lora/jobs/{job.id}")).json()
        assert "worker_token" not in view
        assert job.worker_token in view["commands"]["bash"]
        assert "lora_worker.py" in view["commands"]["powershell"]

        base = f"/studio/api/lora/worker/{job.id}"
        denied = await client.get(f"{base}/spec", headers={"x-lora-token": "nope"})
        assert denied.status_code == 401
        headers = {"x-lora-token": job.worker_token}
        spec = (await client.get(f"{base}/spec", headers=headers)).json()
        assert (
            spec["base_model"] == "Qwen/Qwen2.5-0.5B-Instruct"
            and "worker_token" not in spec
        )
        train = await client.get(f"{base}/dataset?split=train", headers=headers)
        assert train.status_code == 200 and train.text.count("\n") == job.train_examples

        for step, loss in ((1, 2.0), (2, 1.2)):
            reply = await client.post(
                f"{base}/progress",
                headers=headers,
                json={"step": step, "total": 2, "loss": loss, "eval_loss_before": 2.5},
            )
            assert reply.json() == {"cancel": False}
        uploaded = await client.put(
            f"{base}/files/adapter.zip", headers=headers, content=adapter_zip()
        )
        assert uploaded.json()["bytes"] > 0
        sneaky = await client.put(
            f"{base}/files/..%2Fevil.py", headers=headers, content=b"x"
        )
        assert sneaky.status_code in {400, 404}
        done = await client.post(
            f"{base}/finish", headers=headers, json={"eval_loss_after": 0.9, "steps": 2}
        )
        assert done.json()["status"] == "succeeded"
        await studio.wait_for_background()

        finished = (await client.get(f"/studio/api/lora/jobs/{job.id}")).json()
        assert finished["metrics"]["loss_curve"] == [[1, 2.0], [2, 1.2]]
        assert (finished["eval_loss_before"], finished["eval_loss_after"]) == (2.5, 0.9)
        assert "GGUF" in finished["message"]
        assert "commands" not in finished
        assets = await studio.store.find(ModelAsset, where={"kind": "adapter"})
        assert len(assets) == 1

        late = await client.post(f"{base}/progress", headers=headers, json={"step": 3})
        assert late.json() == {"cancel": True}
        script = await client.get("/studio/lora/worker.py")
        assert "def train(" in script.text
    await studio.shutdown()
    await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_cancelling_tells_the_worker_to_stop(make_studio):
    studio, _ = make_studio(teacher)
    _, job = await lora_job(studio)

    await studio.lora.cancel(job.id)

    assert (await studio.lora.report(job, {"step": 1})) == {"cancel": True}


@pytest.mark.skipif(os.name == "nt", reason="fake ollama is a shell script")
@pytest.mark.asyncio
async def test_a_finished_gguf_is_installed_into_ollama(make_studio, tmp_path):
    calls = tmp_path / "calls.log"
    fake = tmp_path / "ollama"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n', encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    studio, _ = make_studio(teacher, STUDIO_LORA_OLLAMA=str(fake))

    class ServedLocally(ScriptedLLM):
        async def list_models(self):
            return ("studio-pocket-" + job_suffix[0] + ":latest",)

    job_suffix = [""]
    student, job = await lora_job(studio)
    job_suffix[0] = job.id[-6:]
    studio._router = StudioModelRouter(proxy=ScriptedLLM([]), local=ServedLocally([]))
    studio.lora._router = studio._router
    folder = studio.lora.job_dir(job.id)
    (folder / "adapter.gguf").write_bytes(b"GGUF" + b"\x00" * 16)

    installed = await studio.lora.install(job.id)

    assert installed.served_model == f"studio-pocket-{job.id[-6:]}"
    log = calls.read_text().splitlines()
    assert log[0] == "pull qwen2.5:0.5b"
    assert log[1].startswith(f"create studio-pocket-{job.id[-6:]} -f ")
    assert "ADAPTER" in (folder / "Modelfile").read_text()
    agent = await studio.store.require(Agent, student.id)
    assert agent.model == f"local/studio-pocket-{job.id[-6:]}:latest"
    assert "now runs the tuned weights" in installed.message

    reverted = await studio.lora.revert(job.id)
    assert (await studio.store.require(Agent, student.id)).model == "local/tiny"
    assert "back on local/tiny" in reverted.message


@pytest.mark.skipif(os.name == "nt", reason="fake python is a shell script")
@pytest.mark.asyncio
async def test_a_local_trainer_that_dies_marks_the_job_failed(make_studio, tmp_path):
    fake = tmp_path / "python"
    fake.write_text(
        '#!/bin/sh\necho "$@"\necho "CUDA out of memory"\nexit 3\n', encoding="utf-8"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    studio, _ = make_studio(teacher, STUDIO_LORA_PYTHON=str(fake))

    _, job = await lora_job(studio, runner="local")

    assert job.status == "failed"
    assert "exit 3" in (job.error or "") and "CUDA out of memory" in (job.error or "")
    command_line = (studio.lora.job_dir(job.id) / "worker.log").read_text()
    assert job.worker_token not in command_line


class CharTokenizer:
    """A tokenizer double: one id per character, no chat template."""

    chat_template = None
    eos_token = "#"

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(char) for char in text]}


def test_the_worker_trains_only_on_the_answer():
    row = {
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ]
    }

    encoded = lora_worker.encode(CharTokenizer(), row, max_len=512)

    assert encoded is not None
    trained = "".join(
        chr(i)
        for i, label in zip(encoded["input_ids"], encoded["labels"], strict=True)
        if label != -100
    )
    assert trained == "yo\n#"
    assert (
        lora_worker.encode(
            CharTokenizer(), {"messages": row["messages"][:1]}, max_len=512
        )
        is None
    )


def test_the_worker_probe_reports_missing_libraries(capsys):
    assert lora_worker.main(["--probe"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "python" in report and "torch" in report


def test_samples_are_records(store):
    assert TuneSample.model_validate({"pack_id": "p", "prompt": "q", "completion": "a"})
    assert isinstance(Path(lora_worker.__file__).name, str)


def test_long_prompts_are_trimmed_from_the_front_not_dropped():
    row = {
        "messages": [
            {"role": "system", "content": "instructions " * 40},
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "done"},
        ]
    }

    encoded = lora_worker.encode(CharTokenizer(), row, max_len=60)

    assert encoded is not None and len(encoded["input_ids"]) == 60
    trained = "".join(
        chr(token)
        for token, label in zip(encoded["input_ids"], encoded["labels"], strict=True)
        if label != -100
    )
    assert trained == "done\n#"


def test_an_answer_longer_than_the_limit_keeps_its_beginning():
    row = {
        "messages": [
            {"role": "user", "content": "q" * 50},
            {"role": "assistant", "content": "a" * 200},
        ]
    }

    encoded = lora_worker.encode(CharTokenizer(), row, max_len=100)

    assert encoded is not None and len(encoded["input_ids"]) == 100
    assert encoded["labels"].count(-100) == 25  # a quarter kept as context
