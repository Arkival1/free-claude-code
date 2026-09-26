"""The built-in engine: Studio runs local models itself, like LM Studio.

Studio downloads the official llama.cpp server once and starts it in router
mode: one process that loads and unloads models on request, each with its
own settings (context size, layers on the graphics card, flash attention,
KV cache type, threads) written to a presets file. It finds model files in
Studio's own models folder, LM Studio's folder, and any folders the user
adds, so nothing has to be downloaded twice.
"""

import asyncio
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import zipfile
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

import anyio.to_thread
import httpx
from loguru import logger

from free_claude_code.core.json_types import JsonObject, JsonValue

from .gguf_info import GGUFError, GGUFInfo, estimate_memory, read_gguf_info
from .models import EngineModelSettings, now_ms
from .store import StudioStore

RELEASES_URL = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
LOG_LINES = 400
START_SECONDS = 60.0
FLASH_CHOICES = ("auto", "on", "off")
KV_CHOICES = ("f16", "q8_0", "q4_0")
CONTEXT_RANGE = (1024, 131_072)
_QUANT = re.compile(r"[-_.](i?q\d[\w]*|f16|f32|bf16|fp16)$", re.IGNORECASE)
_SHARD = re.compile(r"-(\d{5})-of-(\d{5})$")
_EMPTY_LINE = re.compile(r"\[\d+\]\s*")


class EngineError(Exception):
    """The built-in engine could not do what was asked."""


@dataclass(frozen=True, slots=True)
class EngineModel:
    """One model file the engine can run."""

    name: str
    path: Path
    size: int
    info: GGUFInfo
    source: str


@dataclass
class InstallState:
    """How far the engine download has got."""

    state: str = "idle"
    done: int = 0
    total: int = 0
    version: str = ""
    error: str = ""


@dataclass
class _Running:
    process: asyncio.subprocess.Process
    reader: asyncio.Task[None]
    started: float = field(default_factory=time.monotonic)


def asset_pattern(
    build: str, *, system: str = "", machine: str = ""
) -> re.Pattern[str]:
    """The release file for this PC: Vulkan on Windows and Linux by default."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arm = machine in {"arm64", "aarch64"}
    if system == "windows":
        arch = "arm64" if arm else "x64"
        kind = "cpu" if build == "cpu" or arm else "vulkan"
        return re.compile(rf"-bin-win-{kind}-{arch}\.zip$")
    if system == "darwin":
        return re.compile(rf"-bin-macos-{'arm64' if arm else 'x64'}\.tar\.gz$")
    arch = "arm64" if arm else "x64"
    middle = "" if build == "cpu" else "vulkan-"
    return re.compile(rf"-bin-ubuntu-{middle}{arch}\.tar\.gz$")


def model_name(path: Path) -> str:
    """'qwen2.5-coder-7b-instruct' for 'Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf'."""
    stem = _SHARD.sub("", path.stem)
    return re.sub(r"[^a-z0-9._-]+", "-", _QUANT.sub("", stem).lower()).strip("-")


def find_model_files(folders: Iterable[tuple[str, Path]]) -> list[tuple[str, Path]]:
    """Every chat model file in these folders, as (source, path) pairs."""
    found: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for source, folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.gguf")):
            # Studio's own folder also holds the engine and LoRA training runs.
            inside = path.relative_to(folder).parts
            if inside and inside[0] in {"engine", "lora"}:
                continue
            lowered = path.name.lower()
            shard = _SHARD.search(path.stem)
            if (
                lowered.startswith("mmproj")
                or "embed" in lowered
                or (shard is not None and shard.group(1) != "00001")
            ):
                continue
            resolved = path.resolve()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            found.append((source, path))
    return found


def presets_text(
    models: Sequence[EngineModel], settings: dict[str, EngineModelSettings]
) -> str:
    """The llama.cpp presets file: one section per model with its settings."""
    lines = [
        "; Written by FCC Studio. Change these on Model Control.",
        "version = 1",
        "",
        "[*]",
        "jinja = true",
        "",
    ]
    for model in models:
        chosen = settings.get(model.name) or EngineModelSettings(id=model.name)
        lines.append(f"[{model.name}]")
        lines.append(f"model = {model.path}")
        lines.append(f"ctx-size = {chosen.context}")
        layers = 999 if chosen.gpu_layers < 0 else chosen.gpu_layers
        lines.append(f"n-gpu-layers = {layers}")
        lines.append(f"flash-attn = {chosen.flash_attention}")
        if chosen.kv_cache != "f16":
            lines.append(f"cache-type-k = {chosen.kv_cache}")
            lines.append(f"cache-type-v = {chosen.kv_cache}")
        if chosen.threads > 0:
            lines.append(f"threads = {chosen.threads}")
        lines.append("")
    return "\n".join(lines)


class Engine:
    """Install, start, stop, and steer the built-in llama.cpp engine."""

    def __init__(
        self,
        *,
        root: Path,
        store: StudioStore,
        folders: Callable[[], Sequence[tuple[str, Path]]],
        port: Callable[[], int],
        build: Callable[[], str] = lambda: "vulkan",
        binary_override: Callable[[], str] = lambda: "",
        models_at_once: Callable[[], int] = lambda: 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._root = root
        self._store = store
        self._folders = folders
        self._port = port
        self._build = build
        self._binary_override = binary_override
        self._models_at_once = models_at_once
        self._transport = transport
        self._running: _Running | None = None
        self._log: deque[str] = deque(maxlen=LOG_LINES)
        self._lock = asyncio.Lock()
        self._models: list[EngineModel] = []
        self._scanned = 0.0
        self.install_state = InstallState()

    # ---------------------------------------------------------------- places

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port()}"

    @property
    def presets_path(self) -> Path:
        return self._root / "presets.ini"

    def binary(self) -> Path | None:
        """The llama-server program, when it is installed."""
        chosen = self._binary_override().strip()
        if chosen:
            path = Path(chosen).expanduser()
            return path if path.is_file() else None
        folder = self._root / "bin"
        if not folder.is_dir():
            return None
        names = {"llama-server.exe", "llama-server"}
        return next(
            (
                path
                for path in folder.rglob("*")
                if path.name in names and path.is_file()
            ),
            None,
        )

    def version(self) -> str:
        marker = self._root / "version.txt"
        with suppress(OSError):
            return marker.read_text(encoding="utf-8").strip()
        return "your own build" if self._binary_override().strip() else ""

    @property
    def running(self) -> bool:
        return self._running is not None and self._running.process.returncode is None

    def logs(self, limit: int = 200) -> list[str]:
        return list(self._log)[-limit:]

    # --------------------------------------------------------------- install

    async def install(self) -> str:
        """Download and unpack the latest llama.cpp server for this PC."""
        state = self.install_state
        if state.state in {"checking", "downloading", "unpacking"}:
            raise EngineError("The engine is already being downloaded.")
        self.install_state = state = InstallState(state="checking")
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=120.0),
                follow_redirects=True,
                transport=self._transport,
            ) as client:
                release = await client.get(
                    RELEASES_URL, headers={"accept": "application/vnd.github+json"}
                )
                if release.status_code >= 400:
                    raise EngineError(
                        f"GitHub answered {release.status_code} when asked for "
                        "the latest llama.cpp release."
                    )
                body = release.json()
                tag = str(body.get("tag_name") or "")
                pattern = asset_pattern(self._build())
                asset = next(
                    (
                        item
                        for item in body.get("assets") or []
                        if isinstance(item, dict)
                        and pattern.search(str(item.get("name") or ""))
                    ),
                    None,
                )
                if asset is None:
                    raise EngineError(
                        f"The llama.cpp release {tag} has no build for this PC "
                        f"({pattern.pattern})."
                    )
                state.state, state.version = "downloading", tag
                state.total = int(asset.get("size") or 0)
                self._root.mkdir(parents=True, exist_ok=True)
                archive = self._root / str(asset["name"])
                async with client.stream(
                    "GET", str(asset["browser_download_url"])
                ) as response:
                    if response.status_code >= 400:
                        raise EngineError(
                            f"The download answered {response.status_code}."
                        )
                    with archive.open("wb") as handle:
                        async for chunk in response.aiter_bytes(1 << 20):
                            await anyio.to_thread.run_sync(handle.write, chunk)
                            state.done += len(chunk)
            state.state = "unpacking"
            if self.running:
                await self.stop()
            await anyio.to_thread.run_sync(lambda: self._unpack(archive, tag))
            state.state = "ready"
            return tag
        except (httpx.HTTPError, OSError, ValueError, EngineError) as error:
            state.state, state.error = "failed", str(error)
            raise EngineError(str(error)) from error

    def _unpack(self, archive: Path, tag: str) -> None:
        target = self._root / "bin"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(target)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(target, filter="data")
        archive.unlink(missing_ok=True)
        binary = self.binary()
        if binary is None:
            raise EngineError("The download has no llama-server program in it.")
        if os.name != "nt":
            for path in binary.parent.iterdir():
                if path.is_file():
                    path.chmod(path.stat().st_mode | 0o755)
        (self._root / "version.txt").write_text(tag, encoding="utf-8")

    # ---------------------------------------------------------------- models

    async def models(self, *, fresh: bool = False) -> list[EngineModel]:
        """The model files the engine can run, read at most every few seconds."""
        if fresh or time.monotonic() - self._scanned > 10 or not self._models:
            self._models = await anyio.to_thread.run_sync(self._scan)
            self._scanned = time.monotonic()
        return self._models

    def _scan(self) -> list[EngineModel]:
        models: list[EngineModel] = []
        taken: set[str] = set()
        for source, path in find_model_files(self._folders()):
            try:
                info = read_gguf_info(path)
            except (GGUFError, OSError, ValueError) as error:
                logger.info("Studio engine: skipped {}: {}", path.name, error)
                continue
            name = model_name(path)
            if name in taken:
                name = re.sub(r"[^a-z0-9._-]+", "-", path.stem.lower())
            if name in taken:
                continue
            taken.add(name)
            models.append(
                EngineModel(
                    name=name,
                    path=path,
                    size=path.stat().st_size,
                    info=info,
                    source=source,
                )
            )
        return models

    async def model_settings(self) -> dict[str, EngineModelSettings]:
        return {row.id: row for row in await self._store.find(EngineModelSettings)}

    async def write_presets(self) -> None:
        text = presets_text(await self.models(fresh=True), await self.model_settings())
        self._root.mkdir(parents=True, exist_ok=True)
        await anyio.to_thread.run_sync(
            lambda: self.presets_path.write_text(text, encoding="utf-8")
        )

    async def save_settings(self, name: str, values: JsonObject) -> EngineModelSettings:
        """Change how one model runs; a loaded model reloads with it."""
        if name not in {model.name for model in await self.models()}:
            raise EngineError(f"No model called {name} on this PC.")
        current = (await self.model_settings()).get(name) or EngineModelSettings(
            id=name
        )
        update: dict[str, object] = {"updated_at": now_ms()}
        if "context" in values:
            context = _whole(values["context"], "Context")
            low, high = CONTEXT_RANGE
            if not low <= context <= high:
                raise EngineError(f"Context must be {low} to {high} tokens.")
            update["context"] = context
        if "gpu_layers" in values:
            update["gpu_layers"] = max(
                -1, min(999, _whole(values["gpu_layers"], "Layers"))
            )
        if "flash_attention" in values:
            update["flash_attention"] = _choice(
                values["flash_attention"], FLASH_CHOICES, "Flash attention"
            )
        if "kv_cache" in values:
            update["kv_cache"] = _choice(values["kv_cache"], KV_CHOICES, "KV cache")
        if "threads" in values:
            update["threads"] = max(0, min(256, _whole(values["threads"], "Threads")))
        saved = current.model_copy(update=update)
        await self._store.put(saved)
        await self.write_presets()
        if self.running:
            states = await self.states()
            await self._request("GET", "/models?reload=1")
            if states.get(name) == "loaded":
                await self.unload(name)
                await self.load(name)
        return saved

    # --------------------------------------------------------------- process

    async def start(self) -> None:
        """Start the engine and wait until it answers."""
        async with self._lock:
            if self.running:
                return
            binary = self.binary()
            if binary is None:
                raise EngineError(
                    "The built-in engine is not installed yet. Press Install on "
                    "Model Control."
                )
            await self.write_presets()
            args = [
                str(binary),
                "--models-preset",
                str(self.presets_path),
                "--models-max",
                str(max(1, self._models_at_once())),
                "--host",
                "127.0.0.1",
                "--port",
                str(self._port()),
            ]
            await anyio.to_thread.run_sync(self._stop_leftover)
            self._log.append(f"$ {' '.join(args)}")
            windows = sys.platform == "win32"
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(binary.parent),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                    if windows
                    else 0
                ),
                # Its own process group, so stopping it also stops every
                # model it started.
                start_new_session=not windows,
            )
            with suppress(OSError):
                self._pid_path.write_text(str(process.pid), encoding="utf-8")
            reader = asyncio.ensure_future(self._read_output(process))
            self._running = _Running(process=process, reader=reader)
        deadline = time.monotonic() + START_SECONDS
        while time.monotonic() < deadline:
            if not self.running:
                tail = " ".join(self.logs(5))
                raise EngineError(f"The engine stopped while starting. {tail[-400:]}")
            with suppress(httpx.HTTPError):
                health = await self._request("GET", "/health", timeout=2.0)
                if health.status_code < 400:
                    return
            await asyncio.sleep(0.3)
        raise EngineError("The engine did not answer within a minute.")

    async def _read_output(self, process: asyncio.subprocess.Process) -> None:
        stream = process.stdout
        if stream is None:
            return
        while line := await stream.readline():
            text = line.decode("utf-8", "replace").rstrip()
            # Model instances prefix every line with their port, even blank ones.
            if text and not _EMPTY_LINE.fullmatch(text):
                self._log.append(text)
        code = await process.wait()
        self._log.append(f"(engine stopped, exit code {code})")

    async def stop(self) -> None:
        async with self._lock:
            running, self._running = self._running, None
            if running is None:
                return
            process = running.process
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 10.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            # Models the router started must not outlive it and hold memory.
            await anyio.to_thread.run_sync(lambda: _stop_tree(process.pid))
            running.reader.cancel()
            with suppress(asyncio.CancelledError):
                await running.reader
            self._pid_path.unlink(missing_ok=True)

    @property
    def _pid_path(self) -> Path:
        return self._root / "engine.pid"

    def _stop_leftover(self) -> None:
        """Stop an engine left running when Studio last closed without stopping it."""
        try:
            pid = int(self._pid_path.read_text(encoding="utf-8").strip())
        except OSError, ValueError:
            return
        if _is_engine_process(pid):
            self._log.append(f"(stopping an engine left running before, pid {pid})")
            _stop_tree(pid)
        self._pid_path.unlink(missing_ok=True)

    async def ensure_running(self) -> None:
        if not self.running:
            await self.start()

    # ------------------------------------------------------------ the router

    async def states(self) -> dict[str, str]:
        """Each model's state in the engine: loaded, loading, or unloaded."""
        if not self.running:
            return {}
        try:
            response = await self._request("GET", "/models", timeout=5.0)
            body = response.json()
        except httpx.HTTPError, ValueError:
            return {}
        rows = body.get("data") if isinstance(body, dict) else None
        states: dict[str, str] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            status = row.get("status")
            value = status.get("value") if isinstance(status, dict) else None
            failed = isinstance(status, dict) and status.get("failed") is True
            states[str(row.get("id"))] = (
                "failed" if failed else str(value or "unloaded")
            )
        return states

    async def load(self, name: str) -> None:
        await self.ensure_running()
        await self._command("/models/load", name)

    async def unload(self, name: str) -> None:
        if self.running:
            await self._command("/models/unload", name)

    async def _command(self, path: str, name: str) -> None:
        try:
            response = await self._request("POST", path, json={"model": name})
        except httpx.HTTPError as error:
            raise EngineError(f"The engine did not answer: {error}") from error
        if response.status_code >= 400:
            raise EngineError(
                f"The engine refused: {response.text[:300] or response.status_code}"
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: JsonObject | None = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            timeout=timeout, transport=self._transport
        ) as client:
            return await client.request(method, f"{self.url}{path}", json=json)

    # ---------------------------------------------------------------- status

    async def status(
        self,
        *,
        gpu_budget_gb: float,
        speeds: dict[str, dict[str, float]] | None = None,
        on: bool = False,
    ) -> JsonObject:
        """Everything Model Control shows."""
        models = await self.models()
        chosen = await self.model_settings()
        states = await self.states()
        speeds = speeds or {}
        rows: list[JsonValue] = []
        for model in models:
            setting = chosen.get(model.name) or EngineModelSettings(id=model.name)
            estimate = estimate_memory(
                model.info,
                file_size=model.size,
                context=setting.context,
                gpu_layers=setting.gpu_layers,
                kv_cache=setting.kv_cache,
            )
            quant = _QUANT.search(_SHARD.sub("", model.path.stem))
            rows.append(
                {
                    "name": model.name,
                    "file": model.path.name,
                    "path": str(model.path),
                    "source": model.source,
                    "size_gb": round(model.size / 1024**3, 2),
                    "params": model.info.size_label,
                    "architecture": model.info.architecture,
                    "quant": quant.group(1).upper() if quant else "",
                    "layers": model.info.layers,
                    "shape": {
                        "size": model.size,
                        "layers": model.info.layers,
                        "embedding": model.info.embedding,
                        "heads": model.info.heads,
                        "kv_heads": model.info.kv_heads,
                        "key_length": model.info.key_length,
                        "value_length": model.info.value_length,
                    },
                    "context_max": model.info.context_max,
                    "state": states.get(model.name, "unloaded"),
                    "settings": setting.model_dump(
                        exclude={"created_at", "updated_at"}
                    ),
                    "estimate": estimate,
                    "fits": estimate["gpu_gb"] <= gpu_budget_gb,
                    "speed": speeds.get(model.name, {}),
                }
            )
        install = self.install_state
        return {
            "on": on,
            "installed": self.binary() is not None,
            "version": self.version(),
            "running": self.running,
            "url": self.url,
            "build": self._build(),
            "gpu_budget_gb": gpu_budget_gb,
            "models_at_once": self._models_at_once(),
            "folders": [
                {"source": source, "path": str(path), "exists": path.is_dir()}
                for source, path in self._folders()
            ],
            "install": {
                "state": install.state,
                "done": install.done,
                "total": install.total,
                "version": install.version,
                "error": install.error,
            },
            "models": rows,
        }


def _whole(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise EngineError(f"{label} must be a whole number.")
    try:
        return int(value)
    except ValueError as error:
        raise EngineError(f"{label} must be a whole number.") from error


def _choice(value: object, choices: Sequence[str], label: str) -> str:
    text = str(value).strip().lower()
    if text not in choices:
        raise EngineError(f"{label} must be one of {', '.join(choices)}.")
    return text


def _is_engine_process(pid: int) -> bool:
    """True when this process id is still a llama-server, not a reused id."""
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            listed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
            return "llama-server" in listed.lower()
        command = Path(f"/proc/{pid}/cmdline")
        if command.exists():
            return b"llama-server" in command.read_bytes()
        listed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        return "llama-server" in listed
    except OSError, subprocess.SubprocessError:
        return False


def _stop_tree(pid: int) -> None:
    """Stop a process and everything it started."""
    if sys.platform == "win32":
        with suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        return
    killpg = getattr(os, "killpg", None)
    if killpg is not None:
        with suppress(ProcessLookupError, PermissionError):
            killpg(pid, signal.SIGKILL)
    with suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGKILL)
