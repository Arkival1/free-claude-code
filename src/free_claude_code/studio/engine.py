"""The built-in engine: Studio runs local models itself, like LM Studio.

Studio downloads the official llama.cpp server once and starts it in router
mode: one process that loads and unloads models on request, each with its
own settings (context size, layers on the graphics card, flash attention,
KV cache type, threads) written to a presets file. It finds model files in
Studio's own models folder, LM Studio's folder, and any folders the user
adds, so nothing has to be downloaded twice.
"""

import asyncio
import contextlib
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
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

import anyio.to_thread
import httpx
from loguru import logger

from free_claude_code.core.json_types import JsonObject, JsonValue

from .engine_speed import (
    BATCH_CHOICES,
    BETTER_BY,
    DEFAULT_BATCH,
    STAGES,
    SpeedHunt,
    alternatives,
    filler_prompt,
    plan_size,
    quant_advice,
    record,
    split_advice,
    turn_seconds,
)
from .engine_tuning import Device, diagnose, parse_devices, suggest_settings
from .gguf_info import GGUFError, GGUFInfo, estimate_memory, read_gguf_info
from .model_inspect import HEAD_BYTES, file_advice, identify, model_report
from .models import EngineModelSettings, now_ms
from .store import StudioStore
from .vault import RepoVault, VaultError, VaultItem

ENGINE_OWNER, ENGINE_REPO = "ggml-org", "llama.cpp"
RELEASES_URL = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
RECENT_RELEASES_URL = (
    "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=8"
)
LATEST_PAGE_URL = "https://github.com/ggml-org/llama.cpp/releases/latest"
DOWNLOAD_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{name}"
ENGINE_ARCHIVE = re.compile(
    r"^llama-(b\d+)-bin-[\w.-]+\.(?:zip|tar\.gz)$", re.IGNORECASE
)
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
    vision: Path | None = None
    """The image encoder (mmproj file) beside it, for a model that can see."""


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


def asset_name(build: str, tag: str, *, system: str = "", machine: str = "") -> str:
    """The release file's name for this PC, the same one asset_pattern finds."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arm = machine in {"arm64", "aarch64"}
    arch = "arm64" if arm else "x64"
    if system == "windows":
        kind = "cpu" if build == "cpu" or arm else "vulkan"
        return f"llama-{tag}-bin-win-{kind}-{arch}.zip"
    if system == "darwin":
        return f"llama-{tag}-bin-macos-{arch}.tar.gz"
    middle = "" if build == "cpu" else "vulkan-"
    return f"llama-{tag}-bin-ubuntu-{middle}{arch}.tar.gz"


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
        # Reuse cached reading of a prompt even when a middle part changed
        # (a new memory note), instead of reading it all again.
        "cache-reuse = 256",
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
        if chosen.batch != DEFAULT_BATCH:
            lines.append(f"ubatch-size = {chosen.batch}")
            lines.append(f"batch-size = {max(2048, chosen.batch)}")
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
        gpu_gb: Callable[[], float] = lambda: 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
        vault: RepoVault | None = None,
    ) -> None:
        self._vault = vault
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
        self._gpu_gb = gpu_gb
        self._headers: dict[tuple[str, int, int], GGUFInfo] = {}
        self._devices: tuple[tuple[str, float], list[Device] | None] | None = None
        self.crashed = ""
        """Why the engine stopped when nobody asked it to, until it starts again."""
        self.benchmarks: dict[str, dict[str, float]] = {}
        self.speed_hunts: dict[str, SpeedHunt] = {}
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
            try:
                tag, archive = await self._download(state)
            except (httpx.HTTPError, OSError, ValueError, EngineError) as error:
                # GitHub is down, or the release is gone: use the kept copy.
                kept = await self._kept_build()
                if kept is None:
                    raise
                logger.info("Studio: engine from the vault ({}): {}", kept.name, error)
                tag, archive = await self._from_vault(kept)
            state.state = "unpacking"
            if self.running:
                await self.stop()
            await anyio.to_thread.run_sync(lambda: self._unpack(archive, tag))
            state.state = "ready"
            return tag
        except (httpx.HTTPError, OSError, ValueError, EngineError) as error:
            state.state = "failed"
            state.error = f"{error} {self.manual_hint()}"
            raise EngineError(str(error)) from error

    async def _download(self, state: InstallState) -> tuple[str, Path]:
        """Download this PC's build from GitHub, keeping a copy in the vault."""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=120.0),
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            tag, url, size = await self._find_download(client)
            state.state, state.version, state.total = "downloading", tag, size
            self._root.mkdir(parents=True, exist_ok=True)
            archive = self._root / url.rsplit("/", 1)[-1]
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise EngineError(f"The download answered {response.status_code}.")
                if not state.total:
                    length = response.headers.get("content-length", "")
                    state.total = int(length) if length.isdigit() else 0
                # Into a new file, then moved into place: the old one may be
                # linked to the vault's copy, which must never be overwritten.
                partial = archive.with_name(archive.name + ".part")
                partial.unlink(missing_ok=True)
                with partial.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1 << 20):
                        await anyio.to_thread.run_sync(handle.write, chunk)
                        state.done += len(chunk)
                archive.unlink(missing_ok=True)
                partial.replace(archive)
        if self._vault is not None:
            try:
                await self._vault.keep_file(
                    owner=ENGINE_OWNER,
                    repo=ENGINE_REPO,
                    kind="release",
                    path=archive,
                    url=url,
                    ref=tag,
                )
            except (OSError, VaultError) as error:
                logger.info("Studio: could not keep the engine in the vault: {}", error)
        return tag, archive

    async def _kept_build(self) -> VaultItem | None:
        """The newest intact vault copy of a build for this PC."""
        if self._vault is None:
            return None
        pattern = asset_pattern(self._build())
        for item in await self._vault.items():
            if (
                item.full_name.lower() == f"{ENGINE_OWNER}/{ENGINE_REPO}"
                and item.kind == "release"
                and pattern.search(item.name)
                and ENGINE_ARCHIVE.match(item.name)
                and await self._vault.intact(item)
            ):
                return item
        return None

    async def _from_vault(self, item: VaultItem) -> tuple[str, Path]:
        assert self._vault is not None
        found = ENGINE_ARCHIVE.match(item.name)
        tag = found.group(1).lower() if found else item.ref
        try:
            archive = await self._vault.restore_file(item, self._root / item.name)
        except VaultError as error:
            raise EngineError(str(error)) from error
        return tag, archive

    def manual_hint(self) -> str:
        """How to install the engine by hand when the download can't run."""
        name = asset_name(self._build(), "bXXXX")
        return (
            "You can also install it yourself: open "
            "github.com/ggml-org/llama.cpp/releases, download the file named "
            f"like {name}, and drop that file on Model Control."
        )

    async def _find_download(self, client: httpx.AsyncClient) -> tuple[str, str, int]:
        """(tag, url, size) of the build for this PC.

        GitHub's API first (the latest release, then the last few, since a
        new release can be published before every build is uploaded). When
        the API is blocked or rate limited, the latest release page gives the
        tag and the file's address is built from it.
        """
        pattern = asset_pattern(self._build())
        problems: list[str] = []
        for url in (RELEASES_URL, RECENT_RELEASES_URL):
            try:
                answer = await client.get(
                    url, headers={"accept": "application/vnd.github+json"}
                )
            except httpx.HTTPError as error:
                problems.append(f"GitHub couldn't be reached ({error})")
                break
            if answer.status_code >= 400:
                problems.append(f"GitHub's API answered {answer.status_code}")
                break
            body = answer.json()
            for release in body if isinstance(body, list) else [body]:
                if not isinstance(release, dict):
                    continue
                for item in release.get("assets") or []:
                    if isinstance(item, dict) and pattern.search(
                        str(item.get("name") or "")
                    ):
                        return (
                            str(release.get("tag_name") or ""),
                            str(item["browser_download_url"]),
                            int(item.get("size") or 0),
                        )
            problems.append("no build for this PC in the newest release")
        try:
            page = await client.get(LATEST_PAGE_URL)
        except httpx.HTTPError as error:
            problems.append(f"github.com couldn't be reached ({error})")
            raise EngineError("; ".join(problems) + ".") from error
        found = re.search(r"/releases/tag/(b\d+)", str(page.url)) or re.search(
            r"/releases/tag/(b\d+)", page.text[:200_000]
        )
        if found is None:
            problems.append("the latest release page didn't name a version")
            raise EngineError("; ".join(problems) + ".")
        tag = found.group(1)
        name = asset_name(self._build(), tag)
        return tag, DOWNLOAD_URL.format(tag=tag, name=name), 0

    async def install_archive(self, archive: Path) -> str:
        """Install a llama.cpp release file the user downloaded themselves."""
        found = ENGINE_ARCHIVE.match(archive.name)
        if found is None:
            raise EngineError(
                "That isn't a llama.cpp release file (llama-b1234-bin-….zip)."
            )
        tag = found.group(1).lower()
        self.install_state = state = InstallState(state="unpacking", version=tag)
        try:
            if self.running:
                await self.stop()
            await anyio.to_thread.run_sync(lambda: self._unpack(archive, tag))
        except (
            OSError,
            ValueError,
            EngineError,
            zipfile.BadZipFile,
            tarfile.TarError,
        ) as error:
            state.state, state.error = "failed", str(error)
            raise EngineError(f"It couldn't be unpacked: {error}") from error
        state.state = "ready"
        return tag

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
                stat = path.stat()
                key = (str(path), stat.st_size, stat.st_mtime_ns)
                info = self._headers.get(key)
                if info is None:
                    # Reading a header walks the whole tokenizer; do it once.
                    info = read_gguf_info(path)
                    self._headers[key] = info
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
                    vision=_image_encoder(path),
                )
            )
        return models

    @property
    def added_dir(self) -> Path:
        """Where models added on Model Control go (inside Studio's models folder)."""
        return self._root.parent / "added"

    async def report(self, name: str) -> JsonObject:
        """What one model can do on this PC."""
        model = next((m for m in await self.models() if m.name == name), None)
        if model is None:
            raise EngineError(f"No model called {name} on this PC.")
        return model_report(
            name=model.name,
            file=model.path.name,
            info=model.info,
            size=model.size,
            vision=model.vision is not None,
            gpu_gb=await self.budget_gb(),
        )

    async def add_file(self, source: Path) -> JsonObject:
        """Add a model file from this PC, then report on it (or on what it is)."""
        head = await anyio.to_thread.run_sync(lambda: _head(source))
        kind, label = identify(head, source.name)
        if kind != "gguf":
            return not_a_model(kind, label, source.name)
        target = self.added_dir / _safe_name(source.name)
        await anyio.to_thread.run_sync(lambda: _link_or_copy(source, target))
        return await self._report_file(target)

    async def receive(
        self, name: str, chunks: AsyncIterator[bytes], *, size: int | None
    ) -> JsonObject:
        """Save an uploaded model file as it arrives, then report on it."""
        target = self.added_dir / _safe_name(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if size:
            free = (
                await anyio.to_thread.run_sync(shutil.disk_usage, target.parent)
            ).free
            if free < size + 512 * 1024**2:
                raise EngineError(
                    f"Not enough disk space: the file needs {round(size / 1024**3, 1)} GB "
                    f"and {round(free / 1024**3, 1)} GB is free."
                )
        part = target.with_name(f"{target.name}.part")
        head = b""
        handle = await anyio.to_thread.run_sync(part.open, "wb")
        try:
            async for chunk in chunks:
                if len(head) < HEAD_BYTES:
                    head += chunk[: HEAD_BYTES - len(head)]
                    if len(head) >= 4 and not head.startswith(b"GGUF"):
                        kind, label = identify(head, name)
                        raise _NotModel(not_a_model(kind, label, name))
                await anyio.to_thread.run_sync(handle.write, chunk)
        except _NotModel as refused:
            await anyio.to_thread.run_sync(handle.close)
            part.unlink(missing_ok=True)
            return refused.report
        except BaseException:
            await anyio.to_thread.run_sync(handle.close)
            part.unlink(missing_ok=True)
            raise
        await anyio.to_thread.run_sync(handle.close)
        if not head.startswith(b"GGUF"):
            part.unlink(missing_ok=True)
            return not_a_model(*identify(head, name), name)
        await anyio.to_thread.run_sync(part.replace, target)
        return await self._report_file(target)

    async def _report_file(self, path: Path) -> JsonObject:
        wanted = path.resolve()
        for model in await self.models(fresh=True):
            if model.path.resolve() == wanted:
                if self.running:
                    await self.write_presets()
                    with suppress(httpx.HTTPError):
                        await self._request("GET", "/models?reload=1")
                return await self.report(model.name)
        raise EngineError(f"{path.name} could not be read as a model.")

    async def model_settings(self) -> dict[str, EngineModelSettings]:
        return {row.id: row for row in await self._store.find(EngineModelSettings)}

    async def devices(self, *, fresh: bool = False) -> list[Device] | None:
        """The graphics cards the engine can use; None until it is installed."""
        binary = self.binary()
        if binary is None:
            return None
        key = (str(binary), binary.stat().st_mtime)
        if not fresh and self._devices is not None and self._devices[0] == key:
            return self._devices[1]
        try:
            process = await asyncio.create_subprocess_exec(
                str(binary),
                "--list-devices",
                cwd=str(binary.parent),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )
            output, _ = await asyncio.wait_for(process.communicate(), 60.0)
        except (OSError, TimeoutError) as error:
            logger.info("Studio engine: could not list devices: {}", error)
            return None
        text = output.decode("utf-8", "replace")
        found = parse_devices(text) if "Available devices" in text else None
        self._devices = (key, found)
        return found

    async def budget_gb(self) -> float:
        """The graphics card's memory: found by the engine, else the setting."""
        found = await self.devices()
        if found:
            return max(device.total_gb for device in found)
        return self._gpu_gb()

    async def effective_settings(
        self,
    ) -> tuple[dict[str, EngineModelSettings], dict[str, str]]:
        """Each model's settings: the ones saved, or ones fitted to this PC."""
        saved = await self.model_settings()
        budget = await self.budget_gb()
        chosen: dict[str, EngineModelSettings] = {}
        advice: dict[str, str] = {}
        for model in await self.models():
            suggestion, reason = suggest_settings(
                model.name, model.info, size=model.size, gpu_gb=budget
            )
            advice[model.name] = reason
            chosen[model.name] = saved.get(model.name) or suggestion
        return chosen, advice

    async def tune(self, names: Sequence[str] | None = None) -> list[JsonObject]:
        """Save the settings fitted to this PC for these models (or all)."""
        budget = await self.budget_gb()
        done: list[JsonObject] = []
        wanted = set(names) if names else None
        for model in await self.models(fresh=True):
            if wanted is not None and model.name not in wanted:
                continue
            suggestion, reason = suggest_settings(
                model.name, model.info, size=model.size, gpu_gb=budget
            )
            await self._store.put(suggestion)
            done.append({"name": model.name, "reason": reason})
        if wanted and not done:
            raise EngineError(
                f"No model called {', '.join(sorted(wanted))} on this PC."
            )
        await self._reload([str(item["name"]) for item in done])
        return done

    async def benchmark(self, name: str, *, long: bool = False) -> dict[str, float]:
        """Load one model and time a reply: reading and writing speed.

        long reads about a thousand tokens first, like an agent's turn, so
        the reading speed is measured on a realistic prompt.
        """
        if name not in {model.name for model in await self.models()}:
            raise EngineError(f"No model called {name} on this PC.")
        await self.load(name)
        deadline = time.monotonic() + 300
        while (state := (await self.states()).get(name)) != "loaded":
            if state == "failed" or time.monotonic() > deadline:
                raise EngineError(f"{name} did not load; the Engine log shows why.")
            await asyncio.sleep(0.5)
        prompt = (
            filler_prompt()
            if long
            else "Write a short paragraph about why fresh bread smells good, then "
            "list three tips for keeping it fresh."
        )
        started = time.monotonic()
        try:
            response = await self._request(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": name,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 128,
                    "temperature": 0,
                    "cache_prompt": False,
                    # Always write all 128 tokens, so the speed is measured
                    # on the same amount of writing every time.
                    "ignore_eos": True,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=300.0,
            )
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EngineError(f"The speed test failed: {error}") from error
        timings = body.get("timings") if isinstance(body, dict) else None
        if not isinstance(timings, dict):
            raise EngineError("The engine did not report its speed.")
        result = {
            key: round(float(value), 1)
            for key in ("prompt_per_second", "predicted_per_second", "predicted_n")
            if isinstance(value := timings.get(key), (int, float))
        }
        result["seconds"] = round(time.monotonic() - started, 1)
        self.benchmarks[name] = result
        return result

    async def find_fastest(self, name: str) -> SpeedHunt:
        """Try the settings that change speed on this card and keep the best.

        Each try reloads the model and times a real reply; a setting is kept
        only when it makes a typical agent turn faster. The winner is saved,
        so every agent on the model uses it from then on.
        """
        models = {model.name: model for model in await self.models(fresh=True)}
        model = models.get(name)
        if model is None:
            raise EngineError(f"No model called {name} on this PC.")
        if self.binary() is None:
            raise EngineError(
                "The built-in engine is not installed yet. Press Install on "
                "Model Control."
            )
        running = self.speed_hunts.get(name)
        if running is not None and running.state == "running":
            return running
        saved = (await self.model_settings()).get(name)
        suggestion, _ = suggest_settings(
            name, model.info, size=model.size, gpu_gb=await self.budget_gb()
        )
        start = saved or suggestion
        layers = model.info.layers or 0
        hunt = SpeedHunt(model=name, total=plan_size(start, layers))
        self.speed_hunts[name] = hunt

        async def timed(label: str, settings: EngineModelSettings) -> float | None:
            hunt.step = label
            await self._store.put(settings.model_copy(update={"updated_at": now_ms()}))
            try:
                await self._reload([name])
                result = await self.benchmark(name, long=True)
            except EngineError as error:
                hunt.trials.append(record(label, settings, None, str(error)))
                hunt.done += 1
                return None
            hunt.trials.append(record(label, settings, result))
            hunt.done += 1
            return turn_seconds(result)

        best = start
        best_time = await timed("Your settings now", start)
        if best_time is not None:
            hunt.before = hunt.trials[-1]
        try:
            for stage in STAGES:
                for label, change in alternatives(stage, best, layers=layers):
                    trying = best.model_copy(update=change)
                    took = await timed(label, trying)
                    if took is not None and (
                        best_time is None or took * BETTER_BY < best_time
                    ):
                        best, best_time = trying, took
        finally:
            if best_time is None:
                # Nothing ran: put back what was there.
                if saved is not None:
                    await self._store.put(saved)
                else:
                    await self._store.delete(EngineModelSettings, name)
            else:
                await self._store.put(best.model_copy(update={"updated_at": now_ms()}))
            with contextlib.suppress(EngineError, httpx.HTTPError):
                await self._reload([name])
        if best_time is None:
            hunt.state = "failed"
            hunt.error = (
                str(hunt.trials[0].get("failed") or "The model did not load.")
                if hunt.trials
                else "The model did not load."
            )
            hunt.step = "Could not time it"
            return hunt
        hunt.best = next(
            (
                trial
                for trial in hunt.trials
                if trial.get("settings")
                == best.model_dump(exclude={"id", "created_at", "updated_at"})
                and "failed" not in trial
            ),
            None,
        )
        quant = _QUANT.search(_SHARD.sub("", model.path.stem))
        hunt.advice = [
            text
            for text in (
                split_advice(best, layers),
                quant_advice(quant.group(1)) if quant else "",
            )
            if text
        ]
        hunt.state = "done"
        hunt.step = "Saved the fastest settings"
        return hunt

    async def _reload(self, names: Sequence[str]) -> None:
        """Write the presets and reload any of these models that are loaded."""
        await self.write_presets()
        if not self.running:
            return
        states = await self.states()
        await self._request("GET", "/models?reload=1")
        for name in names:
            if states.get(name) == "loaded":
                await self.unload(name)
                await self.load(name)

    async def write_presets(self) -> None:
        await self.models(fresh=True)
        chosen, _ = await self.effective_settings()
        text = presets_text(self._models, chosen)
        self._root.mkdir(parents=True, exist_ok=True)
        await anyio.to_thread.run_sync(
            lambda: self.presets_path.write_text(text, encoding="utf-8")
        )

    async def save_settings(self, name: str, values: JsonObject) -> EngineModelSettings:
        """Change how one model runs; a loaded model reloads with it."""
        if name not in {model.name for model in await self.models()}:
            raise EngineError(f"No model called {name} on this PC.")
        current = (await self.effective_settings())[0].get(name) or (
            EngineModelSettings(id=name)
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
        if "batch" in values:
            batch = _whole(values["batch"], "Reading batch")
            if batch not in BATCH_CHOICES:
                raise EngineError(
                    "Reading batch must be one of "
                    + ", ".join(str(choice) for choice in BATCH_CHOICES)
                    + "."
                )
            update["batch"] = batch
        saved = current.model_copy(update=update)
        await self._store.put(saved)
        await self._reload([name])
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
            self.crashed = ""
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
        running = self._running
        if running is not None and running.process is process:
            # Nobody asked it to stop.
            tail = " ".join(line for line in list(self._log)[-6:-1])
            self.crashed = f"exit code {code}. {tail[-300:]}".strip()

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
        speeds: dict[str, dict[str, float]] | None = None,
        on: bool = False,
        lm_studio_running: bool = False,
    ) -> JsonObject:
        """Everything Model Control shows."""
        models = await self.models()
        devices = await self.devices()
        gpu_budget_gb = await self.budget_gb()
        saved = await self.model_settings()
        chosen, advice = await self.effective_settings()
        states = await self.states()
        speeds = speeds or {}
        rows: list[JsonValue] = []
        too_big: list[str] = []
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
                    "benchmark": self.benchmarks.get(model.name, {}),
                    "speed_hunt": self.speed_hunts[model.name].view()
                    if model.name in self.speed_hunts
                    else None,
                    "capabilities": {
                        "tools": model.info.tools,
                        "vision": model.vision is not None,
                        "reasoning": model.info.reasoning,
                    },
                    "auto": model.name not in saved,
                    "advice": advice.get(model.name, ""),
                }
            )
            if estimate["gpu_gb"] > gpu_budget_gb:
                too_big.append(model.name)
        install = self.install_state
        installed = self.binary() is not None
        diagnostics = diagnose(
            on=on,
            installed=installed,
            build=self._build(),
            devices=devices,
            logs=self.logs(LOG_LINES),
            crashed=self.crashed,
            failed_models=[name for name, state in states.items() if state == "failed"],
            too_big=too_big,
            lm_studio_running=lm_studio_running,
        )
        return {
            "gpu": [
                {
                    "name": device.name,
                    "description": device.description,
                    "total_gb": device.total_gb,
                    "free_gb": round(device.free_mb / 1024, 1),
                }
                for device in devices or []
            ],
            "gpu_checked": devices is not None,
            "diagnostics": list(diagnostics),
            "on": on,
            "installed": installed,
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


def _image_encoder(path: Path) -> Path | None:
    """The mmproj file a vision model keeps beside it, if any.

    LM Studio keeps one model per folder, so an mmproj there is its own. In
    a folder of several models, the mmproj must also name the model.
    """
    with suppress(OSError):
        files = sorted(path.parent.glob("*.gguf"))
        encoders = [f for f in files if f.name.lower().startswith("mmproj")]
        models = [f for f in files if f not in encoders]
        if len(models) <= 1:
            return encoders[0] if encoders else None
        family = re.split(r"[-_.]", model_name(path))[0]
        name = model_name(path)
        for encoder in encoders:
            label = encoder.stem.lower()
            if name in label or (len(family) > 2 and family in label):
                return encoder
    return None


def not_a_model(kind: str, label: str, name: str) -> JsonObject:
    """The report for a file that is not a model the engine can run."""
    return {
        "is_model": False,
        "kind": kind,
        "label": label,
        "file": name,
        "message": file_advice(kind, label, name),
    }


def _head(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(HEAD_BYTES)


def _safe_name(name: str) -> str:
    """A plain file name: no folders, no odd characters, ending in .gguf."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).name).strip("-.") or "model"
    return stem if stem.lower().endswith(".gguf") else f"{stem}.gguf"


def _link_or_copy(source: Path, target: Path) -> None:
    """Put the model in place without a second copy when the drive allows."""
    source = source.resolve()
    if target.exists() and target.stat().st_size == source.stat().st_size:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.hardlink_to(source)
    except OSError:
        shutil.copy2(source, target)


class _NotModel(Exception):
    def __init__(self, report: JsonObject) -> None:
        super().__init__(str(report.get("message") or "not a model"))
        self.report = report
