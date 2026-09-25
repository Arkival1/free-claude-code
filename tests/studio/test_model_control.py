"""Model Control: Studio's built-in engine, like LM Studio inside the app."""

import io
import socket
import struct
import sys
import tarfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.core.json_types import JsonObject
from free_claude_code.studio.engine import (
    Engine,
    asset_pattern,
    find_model_files,
    model_name,
    presets_text,
)
from free_claude_code.studio.gguf_info import estimate_memory, read_gguf_info
from free_claude_code.studio.models import EngineModelSettings
from free_claude_code.studio.service import StudioService
from free_claude_code.studio.store import StudioStore
from tests.api.support import create_test_app

from .conftest import OFFLINE_SEARCH, RecordingWebTools

FAKE_SERVER = Path(__file__).with_name("fake_llama_server.py")


def fake_gguf(path: Path, *, layers: int = 28, pad: int = 0) -> Path:
    """Write a GGUF header like a 1.5B Qwen model's, with a tokenizer to skip."""

    def text(value: str) -> bytes:
        raw = value.encode()
        return struct.pack("<Q", len(raw)) + raw

    pairs = [
        ("general.architecture", 8, text("qwen2")),
        ("general.name", 8, text("Qwen2.5 Coder 1.5B Instruct")),
        ("general.size_label", 8, text("1.5B")),
        ("qwen2.block_count", 4, struct.pack("<I", layers)),
        ("qwen2.embedding_length", 4, struct.pack("<I", 1536)),
        ("qwen2.attention.head_count", 4, struct.pack("<I", 12)),
        ("qwen2.attention.head_count_kv", 4, struct.pack("<I", 2)),
        ("qwen2.context_length", 4, struct.pack("<I", 32768)),
        (
            "tokenizer.ggml.tokens",
            9,
            struct.pack("<IQ", 8, 3) + text("a") + text("b") + text("c"),
        ),
        (
            "tokenizer.ggml.scores",
            9,
            struct.pack("<IQ", 6, 3) + struct.pack("<3f", 0, 0, 0),
        ),
    ]
    header = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, len(pairs))
    body = b"".join(
        text(key) + struct.pack("<I", kind) + value for key, kind, value in pairs
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + body + b"\0" * pad)
    return path


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_right_download_for_each_pc():
    assert asset_pattern("vulkan", system="Windows", machine="AMD64").search(
        "llama-b9000-bin-win-vulkan-x64.zip"
    )
    assert asset_pattern("cpu", system="Windows", machine="AMD64").search(
        "llama-b9000-bin-win-cpu-x64.zip"
    )
    assert asset_pattern("vulkan", system="Linux", machine="x86_64").search(
        "llama-b9000-bin-ubuntu-vulkan-x64.tar.gz"
    )
    assert asset_pattern("vulkan", system="Darwin", machine="arm64").search(
        "llama-b9000-bin-macos-arm64.tar.gz"
    )
    assert not asset_pattern("vulkan", system="Windows", machine="AMD64").search(
        "cudart-llama-bin-win-cuda-12.4-x64.zip"
    )


def test_model_names_match_lm_studio_style():
    assert (
        model_name(Path("Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"))
        == "qwen2.5-coder-7b-instruct"
    )
    assert (
        model_name(Path("Llama-3.1-8B-Instruct-IQ4_XS.gguf")) == "llama-3.1-8b-instruct"
    )
    assert model_name(Path("big-00001-of-00003.gguf")) == "big"


def test_model_files_are_found_and_extras_skipped(tmp_path):
    studio = tmp_path / "models"
    fake_gguf(studio / "qwen-1.5b-q4_k_m.gguf")
    fake_gguf(studio / "lora" / "job" / "model.gguf")
    fake_gguf(studio / "engine" / "x.gguf")
    fake_gguf(tmp_path / "lm" / "pub" / "repo" / "mmproj-f16.gguf")
    fake_gguf(tmp_path / "lm" / "pub" / "repo" / "nomic-embed-text.gguf")
    fake_gguf(tmp_path / "lm" / "pub" / "repo" / "big-00002-of-00002.gguf")
    fake_gguf(tmp_path / "lm" / "pub" / "repo" / "big-00001-of-00002.gguf")

    found = find_model_files([("Studio", studio), ("LM Studio", tmp_path / "lm")])

    assert [(source, path.name) for source, path in found] == [
        ("Studio", "qwen-1.5b-q4_k_m.gguf"),
        ("LM Studio", "big-00001-of-00002.gguf"),
    ]


def test_the_header_gives_what_memory_depends_on(tmp_path):
    path = fake_gguf(tmp_path / "m.gguf", pad=1024**3 // 1024)
    info = read_gguf_info(path)
    assert (info.architecture, info.size_label, info.layers) == ("qwen2", "1.5B", 28)
    assert (info.heads, info.kv_heads, info.context_max) == (12, 2, 32768)

    full = estimate_memory(
        info, file_size=1024**3, context=16384, gpu_layers=-1, kv_cache="f16"
    )
    # 28 layers x 16384 tokens x 2 KV heads x (128 + 128) x 2 bytes.
    assert full["kv_gb"] == pytest.approx(0.44, abs=0.01)
    assert full["weights_gb"] == 1.0 and full["cpu_gb"] == 0.0
    half = estimate_memory(
        info, file_size=1024**3, context=16384, gpu_layers=14, kv_cache="q8_0"
    )
    assert half["gpu_gb"] < full["gpu_gb"] and half["cpu_gb"] > 0
    assert half["kv_gb"] < full["kv_gb"]


def test_presets_carry_each_models_settings(tmp_path):
    from free_claude_code.studio.engine import EngineModel

    model = EngineModel(
        name="qwen",
        path=fake_gguf(tmp_path / "q.gguf"),
        size=1,
        info=read_gguf_info(tmp_path / "q.gguf"),
        source="Studio",
    )
    text = presets_text(
        [model],
        {
            "qwen": EngineModelSettings(
                id="qwen", context=4096, gpu_layers=20, kv_cache="q8_0", threads=6
            )
        },
    )
    assert "[qwen]" in text and f"model = {tmp_path / 'q.gguf'}" in text
    assert "ctx-size = 4096" in text and "n-gpu-layers = 20" in text
    assert "cache-type-k = q8_0" in text and "threads = 6" in text
    default = presets_text([model], {})
    assert "n-gpu-layers = 999" in default and "cache-type-k" not in default


@pytest.mark.asyncio
async def test_install_downloads_the_build_for_this_pc(tmp_path, store):
    bundle = io.BytesIO()
    with tarfile.open(fileobj=bundle, mode="w:gz") as tar:
        program = b"#!/bin/sh\n"
        entry = tarfile.TarInfo("llama-b9000/llama-server")
        entry.size = len(program)
        tar.addfile(entry, io.BytesIO(program))
    release = {
        "tag_name": "b9000",
        "assets": [
            {
                "name": name,
                "size": len(bundle.getvalue()),
                "browser_download_url": f"https://dl.test/{name}",
            }
            for name in (
                "llama-b9000-bin-ubuntu-vulkan-x64.tar.gz",
                "llama-b9000-bin-win-vulkan-x64.zip",
                "llama-b9000-bin-macos-arm64.tar.gz",
            )
        ],
    }
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        if "api.github.com" in str(request.url):
            return httpx.Response(200, json=release)
        return httpx.Response(200, content=bundle.getvalue())

    engine = Engine(
        root=tmp_path / "engine",
        store=store,
        folders=lambda: [],
        port=lambda: free_port(),
        build=lambda: "vulkan",
        transport=httpx.MockTransport(handler),
    )
    assert engine.binary() is None

    tag = await engine.install()

    assert tag == "b9000" and engine.version() == "b9000"
    binary = engine.binary()
    assert binary is not None and binary.name == "llama-server"
    assert engine.install_state.state == "ready"
    assert engine.install_state.done == len(bundle.getvalue())
    assert fetched[1].startswith("https://dl.test/")
    assert asset_pattern("vulkan").search(fetched[1]), "the build for this PC"


@pytest.mark.asyncio
async def test_settings_are_checked_and_saved(tmp_path, store):
    fake_gguf(tmp_path / "models" / "qwen-q4_k_m.gguf")
    engine = Engine(
        root=tmp_path / "engine",
        store=store,
        folders=lambda: [("Studio", tmp_path / "models")],
        port=free_port,
    )
    saved = await engine.save_settings(
        "qwen", {"context": 16384, "kv_cache": "q8_0", "gpu_layers": -1}
    )
    assert (saved.context, saved.kv_cache, saved.gpu_layers) == (16384, "q8_0", -1)
    assert "ctx-size = 16384" in engine.presets_path.read_text()
    bad_values: list[JsonObject] = [
        {"context": 100},
        {"kv_cache": "q2"},
        {"flash_attention": "maybe"},
    ]
    for bad in bad_values:
        with pytest.raises(Exception, match="must be"):
            await engine.save_settings("qwen", bad)
    with pytest.raises(Exception, match="No model called"):
        await engine.save_settings("nope", {"context": 4096})


def engine_studio(tmp_path, studio_settings, *, port: int):
    folder = tmp_path / "gguf"
    fake_gguf(folder / "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf")
    program = tmp_path / "llama-server"
    program.write_text(f"#!{sys.executable}\n" + FAKE_SERVER.read_text())
    program.chmod(0o755)
    settings = studio_settings(
        STUDIO_ENGINE=True,
        STUDIO_ENGINE_PORT=port,
        STUDIO_ENGINE_PATH=str(program),
        STUDIO_ENGINE_FOLDERS=str(folder),
        STUDIO_MAIN_AGENT_MODEL="local/qwen2.5-coder-1.5b-instruct",
    )
    return StudioService(
        store=StudioStore(tmp_path / "studio.db"),
        web_tools=RecordingWebTools(),
        settings_provider=lambda: settings,
        models_dir=tmp_path / "models",
        sites_dir=tmp_path / "sites",
        search_transport=OFFLINE_SEARCH,
        voice_transport=OFFLINE_SEARCH,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="runs a POSIX script as the engine")
@pytest.mark.asyncio
async def test_studio_runs_models_with_the_built_in_engine(tmp_path, studio_settings):
    studio = engine_studio(tmp_path, studio_settings, port=free_port())
    name = "qwen2.5-coder-1.5b-instruct"
    try:
        status = await studio.engine_status()
        assert status["on"] and status["installed"] and not status["running"]
        (model,) = status["models"]
        assert (model["name"], model["params"], model["quant"]) == (
            name,
            "1.5B",
            "Q4_K_M",
        )
        assert model["state"] == "unloaded" and model["fits"]

        await studio.engine_settings(name, {"context": 4096})
        await studio.ensure_defaults()
        # The first local call starts the engine by itself.
        await studio.main_say("hello", background=False)
        chat = await studio.main_chat()
        assert (await studio.transcript(chat.id))[-1].text == f"Hi from {name}."

        status = await studio.engine_status()
        assert status["running"] and status["models"][0]["state"] == "loaded"
        assert status["models"][0]["speed"]["predicted_per_second"] == 42.5
        assert (await studio.local_models())["base_url"].endswith("/v1")
        await studio.engine_unload(name)
        assert (await studio.engine_status())["models"][0]["state"] == "unloaded"
        await studio.engine_load(name)
        assert any(line.startswith("$ ") for line in studio.engine_logs())
    finally:
        await studio.shutdown()
    assert not (await studio.engine_status())["running"]


@pytest.mark.asyncio
async def test_model_control_through_the_routes(make_studio, tmp_path):
    studio, _ = make_studio([], STUDIO_ENGINE_FOLDERS=str(tmp_path / "gguf"))
    fake_gguf(tmp_path / "gguf" / "tiny-q8_0.gguf")
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            status = (await client.get("/studio/api/engine")).json()
            assert status["installed"] is False and status["on"] is False
            assert [m["name"] for m in status["models"]] == ["tiny"]
            saved = await client.put(
                "/studio/api/engine/models/tiny", json={"context": 8192}
            )
            assert saved.status_code == 200 and saved.json()["context"] == 8192
            bad = await client.put(
                "/studio/api/engine/models/tiny", json={"context": 5}
            )
            assert bad.status_code == 422
            missing = await client.post("/studio/api/engine/start")
            assert missing.status_code == 400
            assert "not installed" in missing.json()["detail"]
            used = await client.post("/studio/api/engine/use", json={"on": True})
            assert used.status_code == 200
            values = await app.state.services.admin.admin_values()
            assert values["STUDIO_ENGINE"].value in {"true", True}
            assert (await client.get("/studio/api/engine/logs")).json() == {"lines": []}
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
