"""Use a model file that is already on this computer.

The user picks a .gguf file in a normal file dialog; Studio links (or copies)
it into LM Studio's models folder so LM Studio can load it, then finds the name
LM Studio lists it under.
"""

import asyncio
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

MODEL_SUFFIX = ".gguf"
IMPORT_PUBLISHER = "my-models"


class ModelFileError(Exception):
    """A chosen model file could not be used."""


async def pick_model_file() -> Path | None:
    """Open the file dialog on this computer; None when the user cancels."""
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "free_claude_code.studio.native_file_dialog",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError as error:
        raise ModelFileError(f"Could not open the file picker: {error}") from error
    try:
        stdout, _ = await process.communicate()
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    try:
        result = json.loads(stdout or b"{}")
    except ValueError:
        result = {}
    if process.returncode != 0 or not isinstance(result, dict) or "path" not in result:
        raise ModelFileError(
            "Could not open the file picker on this computer. Put the model in "
            "LM Studio yourself, then pick it from the list."
        )
    path = result["path"]
    return Path(path) if isinstance(path, str) and path else None


def check_model_file(path: Path) -> Path:
    """Make sure the chosen file is a readable GGUF model."""
    if not path.is_file():
        raise ModelFileError(f"{path} is not a file.")
    if path.suffix.lower() != MODEL_SUFFIX:
        raise ModelFileError(
            f"{path.name} is not a .gguf model file. LM Studio models end in .gguf."
        )
    with path.open("rb") as handle:
        if handle.read(4) != b"GGUF":
            raise ModelFileError(f"{path.name} does not look like a GGUF model.")
    return path


def place_in_lmstudio(source: Path, models_dir: Path) -> Path:
    """Put the model where LM Studio finds it, without copying when possible."""
    source = source.resolve()
    with suppress(ValueError):
        source.relative_to(models_dir.resolve())
        return source  # already in LM Studio's folder
    target = models_dir / IMPORT_PUBLISHER / _stem(source) / source.name
    if target.exists() and target.stat().st_size == source.stat().st_size:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.hardlink_to(source)
    except OSError:
        # Different drive: copy, since LM Studio needs its own copy there.
        shutil.copy2(source, target)
    return target


def _stem(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-") or "model"


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


_QUANT = re.compile(r"[-_.](i?q\d[\w]*|f16|f32|bf16|fp16)$", re.IGNORECASE)


def match_listed_model(path: Path, listed: Sequence[str]) -> str | None:
    """Find the name the local server lists a model file under."""
    stem = path.stem
    candidates = {_squash(stem), _squash(_QUANT.sub("", stem))}
    best: str | None = None
    for name in listed:
        short = _squash(name.rsplit("/", 1)[-1])
        if not short:
            continue
        matches = any(short in each for each in candidates)
        if matches and (
            best is None or len(short) > len(_squash(best.rsplit("/", 1)[-1]))
        ):
            best = name
    return best
