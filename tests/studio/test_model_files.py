"""Using a model file that is already on this PC."""

import os

import pytest

from free_claude_code.studio import StudioError
from free_claude_code.studio import service as service_module
from free_claude_code.studio.model_files import (
    ModelFileError,
    check_model_file,
    match_listed_model,
    place_in_lmstudio,
)
from free_claude_code.studio.models import Agent

from .test_stand_in import FakeLocal, build


def gguf(path, size=64):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + b"\0" * size)
    return path


def test_only_gguf_models_are_accepted(tmp_path):
    good = gguf(tmp_path / "Qwen2.5-7B-Instruct-Q4_K_M.gguf")
    assert check_model_file(good) == good

    with pytest.raises(ModelFileError, match=r"not a \.gguf"):
        check_model_file(gguf(tmp_path / "notes.txt"))
    fake = tmp_path / "fake.gguf"
    fake.write_bytes(b"MZ not a model")
    with pytest.raises(ModelFileError, match="does not look like"):
        check_model_file(fake)
    with pytest.raises(ModelFileError, match="is not a file"):
        check_model_file(tmp_path / "missing.gguf")


def test_the_file_is_linked_into_lm_studio_without_a_second_copy(tmp_path):
    source = gguf(tmp_path / "Downloads" / "My Model Q4.gguf")
    models = tmp_path / "lmstudio" / "models"

    placed = place_in_lmstudio(source, models)

    assert placed == models / "my-models" / "My-Model-Q4" / "My Model Q4.gguf"
    assert placed.read_bytes() == source.read_bytes()
    assert os.stat(placed).st_ino == os.stat(source).st_ino, "hard link, no copy"
    assert place_in_lmstudio(source, models) == placed, "a second pick reuses it"

    inside = gguf(models / "lmstudio-community" / "x" / "x-Q4_K_M.gguf")
    assert place_in_lmstudio(inside, models) == inside.resolve()


def test_the_listed_name_is_found_from_the_file_name(tmp_path):
    listed = ["tinyllama-1.1b-chat-v1.0", "qwen2.5-7b-instruct", "qwen2.5-7b"]

    found = match_listed_model(tmp_path / "Qwen2.5-7B-Instruct-Q4_K_M.gguf", listed)

    assert found == "qwen2.5-7b-instruct", "the longest, most specific match"
    assert match_listed_model(tmp_path / "phi-3.gguf", listed) is None


@pytest.mark.asyncio
async def test_a_picked_file_is_added_and_named(
    tmp_path, store, web_tools, studio_settings, monkeypatch
):
    models = tmp_path / "lm"
    models.mkdir()
    local = FakeLocal()
    local.served = ("qwen-4b", "my-coder-7b")
    studio, *_ = build(
        tmp_path,
        store,
        web_tools,
        studio_settings,
        local=local,
        STUDIO_LMSTUDIO_MODELS_DIR=str(models),
    )
    picked = gguf(tmp_path / "Downloads" / "my-coder-7b-Q4_K_M.gguf")

    async def choose():
        return picked

    monkeypatch.setattr(service_module, "pick_model_file", choose)
    result = await studio.pick_model_file()

    assert result["picked"] is True
    assert result["model"] == "local/my-coder-7b"
    assert (models / "my-models" / "my-coder-7b-Q4_K_M" / picked.name).is_file()

    async def cancel():
        return None

    monkeypatch.setattr(service_module, "pick_model_file", cancel)
    assert await studio.pick_model_file() == {"picked": False}

    with pytest.raises(StudioError, match=r"not a \.gguf"):
        await studio.add_model_file(gguf(tmp_path / "readme.md"))


@pytest.mark.asyncio
async def test_choosing_a_model_for_the_main_ai_or_everyone(
    tmp_path, store, web_tools, studio_settings
):
    studio, *_ = build(tmp_path, store, web_tools, studio_settings)
    await studio.ensure_defaults()

    assert await studio.choose_model("local/qwen-4b", everyone=False) == 1
    main = await studio.main_agent()
    assert main.model == "local/qwen-4b" and main.local_only
    builder = await studio.agent_by_name("Builder")
    assert isinstance(builder, Agent) and builder.model != "local/qwen-4b"

    changed = await studio.choose_model("local/qwen-4b", everyone=True)
    assert changed >= 6
    for agent in await studio.agents():
        assert agent.model == "local/qwen-4b", agent.name
    with pytest.raises(StudioError):
        await studio.choose_model("  ", everyone=True)
