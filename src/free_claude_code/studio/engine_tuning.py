"""Fit each model to this PC: find the graphics card, pick settings, explain problems.

The engine reports the graphics cards it can use with ``--list-devices``.
From the card's memory and a model's own header, ``suggest_settings`` picks
the largest context that still fits with every layer on the card (the fast
case), halving the memory for context before giving up layers.
``diagnose`` turns the engine's state into plain advice.
"""

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

from .gguf_info import GGUFInfo, estimate_memory
from .models import EngineModelSettings

HEADROOM_GB = 1.0
"""Graphics memory left free for Windows, the screen, and the driver."""
CONTEXT_CHOICES = (16384, 12288, 8192, 6144, 4096, 2048)
"""Tried largest first; more than 16k mostly slows a small card down."""
_DEVICE = re.compile(r"^\s*(\S+):\s+(.+?)\s+\((\d+) MiB,\s+(\d+) MiB free\)\s*$")


@dataclass(frozen=True, slots=True)
class Device:
    """One graphics card (or other accelerator) the engine can use."""

    name: str
    description: str
    total_mb: int
    free_mb: int

    @property
    def total_gb(self) -> float:
        return round(self.total_mb / 1024, 1)


def parse_devices(output: str) -> list[Device]:
    """The devices ``llama-server --list-devices`` printed."""
    devices: list[Device] = []
    for line in output.splitlines():
        found = _DEVICE.match(line)
        if found:
            devices.append(
                Device(
                    name=found.group(1),
                    description=found.group(2),
                    total_mb=int(found.group(3)),
                    free_mb=int(found.group(4)),
                )
            )
    return devices


def physical_cores() -> int:
    """A fair guess at the real cores: most desktop chips run two threads per core."""
    logical = os.cpu_count() or 4
    return max(1, logical // 2) if logical >= 4 else logical


def suggest_settings(
    name: str,
    info: GGUFInfo,
    *,
    size: int,
    gpu_gb: float,
    cores: int | None = None,
) -> tuple[EngineModelSettings, str]:
    """The best settings for one model on this card, and why, in a sentence."""
    room = max(0.5, gpu_gb - HEADROOM_GB)
    limit = info.context_max or 32768
    contexts = [size_ for size_ in CONTEXT_CHOICES if size_ <= limit] or [2048]
    for context in contexts:
        for kv_cache in ("f16", "q8_0"):
            need = estimate_memory(
                info, file_size=size, context=context, gpu_layers=-1, kv_cache=kv_cache
            )["gpu_gb"]
            if need <= room:
                memory = "full quality" if kv_cache == "f16" else "q8 (half memory)"
                return (
                    EngineModelSettings(
                        id=name, context=context, gpu_layers=-1, kv_cache=kv_cache
                    ),
                    f"All {info.layers or 'its'} layers on the graphics card, "
                    f"{context:,} tokens of context, {memory} context memory: "
                    f"about {need} GB of {gpu_gb} GB.",
                )
    # Too big for the card whole: keep a sensible context and split the layers.
    context = 8192 if 8192 in contexts else contexts[-1]
    layers = info.layers or 32
    fitted = 0
    for count in range(layers, -1, -1):
        need = estimate_memory(
            info, file_size=size, context=context, gpu_layers=count, kv_cache="q8_0"
        )["gpu_gb"]
        if need <= room:
            fitted = count
            break
    threads = cores or physical_cores()
    return (
        EngineModelSettings(
            id=name,
            context=context,
            gpu_layers=fitted,
            kv_cache="q8_0",
            threads=threads,
        ),
        f"Too big for {gpu_gb} GB whole: {fitted} of {layers} layers on the "
        f"graphics card, the rest on {threads} processor cores. Works, but a "
        "smaller model or quantization will be much faster.",
    )


def diagnose(
    *,
    on: bool,
    installed: bool,
    build: str,
    devices: Sequence[Device] | None,
    logs: Sequence[str],
    crashed: str,
    failed_models: Sequence[str],
    too_big: Sequence[str],
    lm_studio_running: bool,
) -> list[dict[str, str]]:
    """What is right and wrong with the engine, most urgent first."""
    notes: list[dict[str, str]] = []

    def note(level: str, text: str) -> None:
        notes.append({"level": level, "text": text})

    if not installed:
        if on:
            note(
                "error",
                "The engine is switched on but not installed. Press Install engine.",
            )
        return notes
    if crashed:
        hint = ""
        if re.search(r"bind|address already in use|in use", crashed, re.I):
            hint = " Another program is using its port: change Engine Port in Settings."
        note("error", f"The engine stopped unexpectedly: {crashed}{hint}")
    no_gpu = any("no usable GPU found" in line for line in logs)
    if build == "cpu":
        note(
            "warn",
            "Engine Build is 'processor only', so models run on the CPU. For your "
            "graphics card, set Engine Build to Vulkan in Settings and press "
            "Update engine.",
        )
    elif devices == [] or no_gpu:
        note(
            "error",
            "The engine can't see your graphics card, so models run on the "
            "processor (many times slower). Press Update engine to get the Vulkan "
            "build, and make sure the AMD driver is installed and up to date.",
        )
    elif devices:
        card = devices[0]
        note(
            "ok",
            f"Graphics card: {card.description}, {card.total_gb} GB "
            f"({round(card.free_mb / 1024, 1)} GB free right now).",
        )
    if any(
        re.search(
            r"V cache quantization requires|flash.?attn.*(?:not supported|unsupported)",
            line,
            re.I,
        )
        for line in logs
    ):
        note(
            "error",
            "This card can't use compressed context memory here. Open the model's "
            "Settings and set Memory for context to Full quality (or Flash "
            "attention to On), then Save.",
        )
    for name in failed_models:
        note(
            "error",
            f"{name} failed to load. Press Tune for my PC on it, then Load again; "
            "the Engine log shows the reason.",
        )
    for name in too_big:
        note(
            "warn",
            f"{name} needs more graphics memory than the card has at its "
            "settings. Tune for my PC fixes that.",
        )
    if on and lm_studio_running:
        note(
            "warn",
            "LM Studio is running too. If it has a model loaded, that model is "
            "using graphics memory the engine needs: unload it or close LM Studio.",
        )
    return notes
