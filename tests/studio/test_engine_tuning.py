"""Model Control fits models to this PC: the card it finds, settings, speed, health."""

import asyncio
import sys

import httpx
import pytest

from free_claude_code.studio.engine_tuning import (
    Device,
    diagnose,
    parse_devices,
    suggest_settings,
)
from free_claude_code.studio.gguf_info import GGUFInfo
from tests.api.support import create_test_app

from .test_model_control import engine_studio, free_port

GB = 1024**3
RX_580 = "  Vulkan0: AMD Radeon RX 580 Series (8192 MiB, 7800 MiB free)"
QWEN_7B = GGUFInfo(layers=28, embedding=3584, heads=28, kv_heads=4, context_max=32768)
LLAMA_8B = GGUFInfo(layers=32, embedding=4096, heads=32, kv_heads=8, context_max=131072)
QWEN_14B = GGUFInfo(layers=48, embedding=5120, heads=40, kv_heads=8, context_max=32768)


def test_the_graphics_card_is_read_from_the_engine():
    (card,) = parse_devices(
        f"load_backend: loaded Vulkan\nAvailable devices:\n{RX_580}\n"
    )
    assert card == Device("Vulkan0", "AMD Radeon RX 580 Series", 8192, 7800)
    assert card.total_gb == 8.0
    assert parse_devices("Available devices:\n  (none)\n") == []


def test_models_are_fitted_to_an_8_gb_card():
    coder, why = suggest_settings("coder", QWEN_7B, size=int(4.36 * GB), gpu_gb=8.0)
    assert (coder.context, coder.gpu_layers, coder.kv_cache) == (16384, -1, "f16")
    assert "All 28 layers on the graphics card" in why

    llama, _ = suggest_settings("llama", LLAMA_8B, size=int(4.58 * GB), gpu_gb=8.0)
    assert (llama.context, llama.gpu_layers, llama.kv_cache) == (16384, -1, "q8_0")

    big, why = suggest_settings(
        "big", QWEN_14B, size=int(8.37 * GB), gpu_gb=8.0, cores=4
    )
    assert 0 < big.gpu_layers < 48 and big.threads == 4 and big.kv_cache == "q8_0"
    assert "Too big for 8.0 GB whole" in why

    small, _ = suggest_settings(
        "small",
        GGUFInfo(layers=28, embedding=1536, heads=12, kv_heads=2, context_max=4096),
        size=GB,
        gpu_gb=8.0,
    )
    assert small.context == 4096, "never more than the model was trained for"


def health(
    *,
    installed: bool = True,
    build: str = "vulkan",
    devices: list[Device] | None = None,
    logs: tuple[str, ...] = (),
    crashed: str = "",
    failed_models: tuple[str, ...] = (),
    too_big: tuple[str, ...] = (),
    lm_studio_running: bool = False,
) -> list[tuple[str, str]]:
    notes = diagnose(
        on=True,
        installed=installed,
        build=build,
        devices=[Device("Vulkan0", "AMD Radeon RX 580 Series", 8192, 7800)]
        if devices is None
        else devices,
        logs=logs,
        crashed=crashed,
        failed_models=failed_models,
        too_big=too_big,
        lm_studio_running=lm_studio_running,
    )
    return [(note["level"], note["text"]) for note in notes]


def test_the_health_check_explains_problems_plainly():
    assert health() == [
        (
            "ok",
            "Graphics card: AMD Radeon RX 580 Series, 8.0 GB (7.6 GB free right now).",
        )
    ]
    assert "can't see your graphics card" in health(devices=[])[0][1]
    assert (
        "can't see your graphics card"
        in health(
            logs=("warning: no usable GPU found, --gpu-layers option will be ignored",)
        )[0][1]
    )
    assert "processor only" in health(build="cpu")[0][1]
    assert "not installed" in health(installed=False)[0][1]
    assert (
        "change Engine Port"
        in health(crashed="exit code 1. bind: address already in use")[0][1]
    )
    assert "Full quality" in " ".join(
        text for _, text in health(logs=("V cache quantization requires flash_attn",))
    )
    texts = " ".join(
        text
        for _, text in health(
            failed_models=("coder",), too_big=("big",), lm_studio_running=True
        )
    )
    assert "coder failed to load" in texts and "big needs more graphics memory" in texts
    assert "LM Studio is running too" in texts


@pytest.mark.skipif(sys.platform == "win32", reason="runs a POSIX script as the engine")
@pytest.mark.asyncio
async def test_tune_speed_test_and_crash_report(tmp_path, studio_settings):
    studio = engine_studio(tmp_path, studio_settings, port=free_port())
    name = "qwen2.5-coder-1.5b-instruct"
    try:
        status = await studio.engine_status()
        assert status["gpu"][0]["description"] == "AMD Radeon RX 580 Series"
        assert status["gpu_budget_gb"] == 8.0
        assert status["diagnostics"][0]["level"] == "ok"
        (model,) = status["models"]
        assert model["auto"] and model["settings"]["context"] == 16384
        assert "All 28 layers on the graphics card" in model["advice"]

        (tuned,) = await studio.engine_tune()
        assert tuned["name"] == name
        assert not (await studio.engine_status())["models"][0]["auto"]

        result = await studio.engine_benchmark(name)
        assert result["predicted_per_second"] == 42.5 and result["seconds"] >= 0
        assert (await studio.engine_status())["models"][0]["benchmark"] == result

        # The engine dies on its own: the health check says so.
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPError):
                await client.post(f"{studio._engine.url}/crash")
        for _ in range(50):
            if not studio._engine.running:
                break
            await asyncio.sleep(0.05)
        status = await studio.engine_status()
        assert status["running"] is False
        assert "stopped unexpectedly: exit code 3" in status["diagnostics"][0]["text"]
        await studio.engine_start()
        assert not any(
            "unexpectedly" in note["text"]
            for note in (await studio.engine_status())["diagnostics"]
        )
    finally:
        await studio.shutdown()


@pytest.mark.asyncio
async def test_tune_through_the_routes(make_studio, tmp_path):
    from .test_model_control import fake_gguf

    studio, _ = make_studio([], STUDIO_ENGINE_FOLDERS=str(tmp_path / "gguf"))
    fake_gguf(tmp_path / "gguf" / "tiny-q8_0.gguf")
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            tuned = (
                await client.post("/studio/api/engine/tune", json={"name": "tiny"})
            ).json()
            assert tuned["tuned"][0]["name"] == "tiny"
            missing = await client.post(
                "/studio/api/engine/tune", json={"name": "nope"}
            )
            assert missing.status_code == 400
            bench = await client.post("/studio/api/engine/models/tiny/benchmark")
            assert (
                bench.status_code == 400 and "not installed" in bench.json()["detail"]
            )
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
