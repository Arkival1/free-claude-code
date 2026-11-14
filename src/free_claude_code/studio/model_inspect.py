"""Say what a file is and, for a model, what it can do on this PC.

A file's first bytes tell what it is, so Studio can answer before a large
upload starts. For a GGUF model the report covers tool use, vision, and
reasoning, whether it fits the graphics card, its best settings, and which
agents it suits.
"""

import re
import struct

from free_claude_code.core.json_types import JsonObject

from .engine_tuning import suggest_settings
from .gguf_info import GGUFInfo, estimate_memory
from .team_models import model_kind, model_size

HEAD_BYTES = 64
"""Enough of a file's start to tell what it is."""

_KINDS: tuple[tuple[bytes, str, str], ...] = (
    (b"GGUF", "gguf", "GGUF model"),
    (b"%PDF", "pdf", "PDF document"),
    (b"\x89PNG", "image", "PNG image"),
    (b"\xff\xd8\xff", "image", "JPEG image"),
    (b"GIF8", "image", "GIF image"),
    (b"PK\x03\x04", "zip", "ZIP archive"),
    (b"\x1f\x8b", "archive", "GZIP archive"),
    (b"7z\xbc\xaf", "archive", "7-Zip archive"),
    (b"Rar!", "archive", "RAR archive"),
    (b"MZ", "program", "Windows program"),
    (b"\x80\x02", "pytorch", "PyTorch weights"),
)
_OFFICE = {
    ".docx": "Word document",
    ".xlsx": "Excel spreadsheet",
    ".pptx": "PowerPoint deck",
}


def identify(head: bytes, name: str) -> tuple[str, str]:
    """(kind, label) from a file's first bytes and its name."""
    lowered = name.lower()
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "WebP image"
    for magic, kind, label in _KINDS:
        if head.startswith(magic):
            if kind == "zip":
                for ext, office in _OFFICE.items():
                    if lowered.endswith(ext):
                        return "document", office
                if lowered.endswith((".pt", ".pth", ".bin")):
                    return "pytorch", "PyTorch weights"
            return kind, label
    if len(head) >= 10:
        (length,) = struct.unpack("<Q", head[:8])
        if 0 < length < 100_000_000 and head[8:10] in (b'{"', b"{ "):
            return "safetensors", "safetensors model weights"
    if lowered.endswith(".onnx"):
        return "onnx", "ONNX model"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return "unknown", "file"
    return "text", "text file"


def file_advice(kind: str, label: str, name: str) -> str:
    """What to do with a file that is not a model Studio can run."""
    stem = re.sub(r"\.[^.]+$", "", name)
    advice = {
        "safetensors": (
            f"This is a raw model ({label}). Studio and LM Studio run GGUF files: "
            f"search Hugging Face for '{stem} GGUF' and download a Q4_K_M file."
        ),
        "pytorch": (
            f"These are raw {label}. Look for a GGUF version of the model on "
            "Hugging Face (a Q4_K_M file suits an 8 GB card)."
        ),
        "onnx": (
            "This is an ONNX model, which the engine can't run. Look for a GGUF "
            "version of the same model."
        ),
        "zip": (
            "This is a ZIP archive. If a model is inside, unzip it and add the "
            ".gguf file."
        ),
        "archive": "This is a compressed archive. Unpack it and add the .gguf file inside.",
        "image": (
            f"This is a {label}, not a model. To show pictures to an AI you need "
            "a model with the Vision badge."
        ),
        "document": (
            f"This is a {label}, not a model. Attach it in a chat instead and "
            "the agent reads it."
        ),
        "pdf": "This is a PDF document, not a model. Attach it in a chat instead.",
        "text": (
            "This is a text file, not a model. Attach it in a chat instead and the "
            "agent reads it."
        ),
        "program": "This is a program, not a model. Studio only adds .gguf model files.",
    }
    return advice.get(
        kind, f"{name} is not a model file Studio can run (models end in .gguf)."
    )


def best_for(name: str, info: GGUFInfo, *, vision: bool) -> list[str]:
    """Which starter agents a model suits, strongest reason first."""
    kind = model_kind(name)
    size = model_size(name) or model_size(info.size_label or "") or 7.0
    picks: list[str] = []
    if kind == "coder" or (info.tools and "coder" in name.lower()):
        picks += ["Builder", "Tester"]
    if info.reasoning:
        picks.append("Helper")
    if info.tools and kind != "coder":
        picks += ["Jarvis", "Researcher"]
    if size <= 4:
        picks.append("Guide")
    if not picks:
        picks.append("Jarvis")
    if vision:
        picks.append("looking at images")
    return list(dict.fromkeys(picks))


def model_report(
    *,
    name: str,
    file: str,
    info: GGUFInfo,
    size: int,
    vision: bool,
    gpu_gb: float,
) -> JsonObject:
    """Everything worth knowing about one model on this PC, in plain words."""
    settings, reason = suggest_settings(name, info, size=size, gpu_gb=gpu_gb)
    estimate = estimate_memory(
        info,
        file_size=size,
        context=settings.context,
        gpu_layers=settings.gpu_layers,
        kv_cache=settings.kv_cache,
    )
    whole = settings.gpu_layers < 0
    can = [
        {
            "what": "Use tools",
            "yes": info.tools,
            "about": (
                "Trained to call tools. Studio's agents use tools like write_file, "
                "web_search, run_command, and research, and this model follows those "
                "steps well."
                if info.tools
                else "Not trained for tools. Studio still lets it use them through "
                "its text format, but less reliably: better for chatting than building."
            ),
        },
        {
            "what": "See images",
            "yes": vision,
            "about": (
                "Its image part (an mmproj file) is beside it, so it can look at "
                "pictures."
                if vision
                else "Text only. Vision models come with an mmproj file."
            ),
        },
        {
            "what": "Reason step by step",
            "yes": info.reasoning,
            "about": (
                "Thinks before answering, which helps with hard problems. Fast "
                "Local Replies skips the thinking when speed matters more."
                if info.reasoning
                else "Answers straight away, which keeps replies quick."
            ),
        },
        {
            "what": "Fit on your graphics card",
            "yes": whole,
            "about": reason,
        },
    ]
    return {
        "is_model": True,
        "kind": "gguf",
        "label": "GGUF model",
        "name": name,
        "file": file,
        "size_gb": round(size / 1024**3, 2),
        "params": info.size_label,
        "architecture": info.architecture,
        "context_max": info.context_max,
        "capabilities": {
            "tools": info.tools,
            "vision": vision,
            "reasoning": info.reasoning,
        },
        "can": can,
        "settings": settings.model_dump(exclude={"created_at", "updated_at"}),
        "estimate": estimate,
        "best_for": best_for(name, info, vision=vision),
        "message": f"{name} is ready on Model Control. {reason}",
    }
