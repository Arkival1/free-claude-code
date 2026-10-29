"""Read what a GGUF model file says about itself, without loading it.

Only the header is read: the architecture, layer count, attention shape, and
trained context length, which is enough to estimate how much graphics memory
a model needs at a given context size.
"""

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_FIXED = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_FORMAT = {
    0: "<B",
    1: "<b",
    2: "<H",
    3: "<h",
    4: "<I",
    5: "<i",
    6: "<f",
    7: "<?",
    10: "<Q",
    11: "<q",
    12: "<d",
}
_STRING, _ARRAY = 8, 9
_WANTED = (
    "block_count",
    "embedding_length",
    "attention.head_count",
    "attention.head_count_kv",
    "attention.key_length",
    "attention.value_length",
    "context_length",
)
KV_BYTES = {"f16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32}
"""Bytes per cached value for each KV cache type."""


class GGUFError(ValueError):
    """The file is not a GGUF model this reader understands."""


@dataclass(frozen=True, slots=True)
class GGUFInfo:
    """The parts of a model's header that decide its memory use."""

    architecture: str = ""
    name: str = ""
    size_label: str = ""
    layers: int = 0
    embedding: int = 0
    heads: int = 0
    kv_heads: int = 0
    key_length: int = 0
    value_length: int = 0
    context_max: int = 0
    tools: bool = False
    """The chat template knows how to offer tools and read tool calls."""
    reasoning: bool = False
    """The model thinks before answering (a thinking mode in its template)."""


def read_gguf_info(path: Path) -> GGUFInfo:
    """Return the header facts of one GGUF file."""
    with path.open("rb") as handle:
        if handle.read(4) != b"GGUF":
            raise GGUFError(f"{path.name} is not a GGUF file.")
        (version,) = struct.unpack("<I", handle.read(4))
        if version < 2:
            raise GGUFError(f"{path.name} uses an old GGUF version ({version}).")
        _tensors, count = struct.unpack("<QQ", handle.read(16))
        values: dict[str, object] = {}
        for _ in range(min(count, 100_000)):
            key = _string(handle)
            (kind,) = struct.unpack("<I", handle.read(4))
            values[key] = _value(handle, kind, keep=_keeps(key))
    arch = str(values.get("general.architecture") or "")
    template = values.get("tokenizer.chat_template")
    template = template if isinstance(template, str) else ""

    def number(name: str) -> int:
        value = values.get(f"{arch}.{name}")
        if isinstance(value, list):
            value = max((v for v in value if isinstance(v, int)), default=0)
        return value if isinstance(value, int) else 0

    return GGUFInfo(
        architecture=arch,
        name=str(values.get("general.name") or ""),
        size_label=str(values.get("general.size_label") or ""),
        layers=number("block_count"),
        embedding=number("embedding_length"),
        heads=number("attention.head_count"),
        kv_heads=number("attention.head_count_kv"),
        key_length=number("attention.key_length"),
        value_length=number("attention.value_length"),
        context_max=number("context_length"),
        tools=supports_tools(template),
        reasoning=thinks(
            template, name=f"{values.get('general.name') or ''} {path.stem}"
        ),
    )


def _keeps(key: str) -> bool:
    return (
        key.startswith("general.")
        or key.endswith(_WANTED)
        or key == "tokenizer.chat_template"
    )


_TOOL_WORD = re.compile(r"\btools\b")
_TOOL_FORMAT = re.compile(
    r"tool_call|tool_response|TOOL_CALLS|TOOL_RESULTS|python_tag|ipython|"
    r"<function|\bfunction\b|tool\u2581call",
    re.I,
)
_THINKING = re.compile(
    r"<think>|enable_thinking|reasoning_content|reasoning_effort|<\|channel\|>analysis",
    re.I,
)
_REASONING_NAME = re.compile(
    r"(?:^|[-_ ./])(?:r1|qwq|reasoning|reasoner|thinking|magistral|gpt-oss)(?:$|[-_ .])",
    re.I,
)


def supports_tools(template: str) -> bool:
    """True when a chat template takes a tool list and has a way to call them."""
    return bool(_TOOL_WORD.search(template) and _TOOL_FORMAT.search(template))


def thinks(template: str, *, name: str = "") -> bool:
    """True for models that reason before answering."""
    return bool(_THINKING.search(template) or _REASONING_NAME.search(name))


def _string(handle: BinaryIO) -> str:
    (length,) = struct.unpack("<Q", handle.read(8))
    if length > 1 << 24:
        raise GGUFError("A header string is too long.")
    return handle.read(length).decode("utf-8", "replace")


def _value(handle: BinaryIO, kind: int, *, keep: bool) -> object:
    if kind == _STRING:
        return _string(handle)
    if kind == _ARRAY:
        inner, count = struct.unpack("<IQ", handle.read(12))
        if inner in _FIXED and not keep:
            handle.seek(_FIXED[inner] * count, 1)
            return None
        items = [_value(handle, inner, keep=keep) for _ in range(count)]
        return items if keep else None
    if kind in _FORMAT:
        (value,) = struct.unpack(_FORMAT[kind], handle.read(_FIXED[kind]))
        return value
    raise GGUFError(f"Unknown GGUF value type {kind}.")


def estimate_memory(
    info: GGUFInfo,
    *,
    file_size: int,
    context: int,
    gpu_layers: int,
    kv_cache: str,
) -> dict[str, float]:
    """Graphics and system memory a model needs, in GB, at these settings."""
    layers = info.layers or 32
    on_gpu = layers if gpu_layers < 0 else min(gpu_layers, layers)
    share = on_gpu / layers
    heads = info.heads or 32
    head_size = info.embedding // heads if info.embedding else 128
    key = info.key_length or head_size
    value = info.value_length or key
    kv_heads = info.kv_heads or heads
    per_value = KV_BYTES.get(kv_cache, 2.0)
    kv = layers * context * kv_heads * (key + value) * per_value
    # Scratch buffers grow with the context; a few hundred MB on top.
    overhead = 0.3e9 + context * max(info.embedding, 2048) * 4 * 1.5
    gpu = file_size * share + kv * share + (overhead if on_gpu else 0)
    cpu = file_size * (1 - share) + kv * (1 - share)
    gb = 1024**3
    return {
        "gpu_gb": round(gpu / gb, 2),
        "cpu_gb": round(cpu / gb, 2),
        "kv_gb": round(kv / gb, 2),
        "weights_gb": round(file_size / gb, 2),
    }
