"""Pictures made on this PC: stable-diffusion.cpp with a cartoon style.

Studio downloads the official stable-diffusion.cpp build for this PC once
(the Vulkan build on Windows and Linux, so AMD, NVIDIA and Intel graphics
cards all work; Apple's on a Mac), and a style's model files from Hugging
Face once. Every download is checked against its SHA-256 and kept in the
Repo vault, so a new install still works after the originals are deleted.
A picture is one run of sd-cli: a prompt in, a PNG out.
"""

import asyncio
import contextlib
import os
import platform
import re
import shutil
import time
import zipfile
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import anyio.to_thread
import httpx
from loguru import logger

from free_claude_code.core.json_types import JsonObject

from .vault import RepoVault, VaultError, VaultItem, _file_sha256

SD_OWNER, SD_REPO = "leejet", "stable-diffusion.cpp"
RELEASES_URL = f"https://api.github.com/repos/{SD_OWNER}/{SD_REPO}/releases?per_page=6"
LATEST_PAGE_URL = f"https://github.com/{SD_OWNER}/{SD_REPO}/releases/latest"
ASSETS_PAGE_URL = (
    f"https://github.com/{SD_OWNER}/{SD_REPO}/releases/expanded_assets/{{tag}}"
)
DOWNLOAD_URL = (
    f"https://github.com/{SD_OWNER}/{SD_REPO}/releases/download/{{tag}}/{{name}}"
)
ARCHIVE = re.compile(r"^sd-[\w.-]+-bin-[\w.-]+\.zip$", re.IGNORECASE)
HF_FILE_URL = "https://huggingface.co/{repo}/resolve/{revision}/{name}"
LOG_LINES = 200
PICTURE_SECONDS = 30 * 60
"""The longest one picture may take (a slow CPU at a big size)."""
_PROGRESS = re.compile(r"\|\s*(\d+)/(\d+)\s*-")
_CHUNK = 1 << 20

type Progress = Callable[[int, int, str], Awaitable[None]]


class ImageEngineError(RuntimeError):
    """The image engine could not do what was asked."""


@dataclass(frozen=True, slots=True)
class ModelFile:
    """One file a style needs, pinned to a Hugging Face commit and checksum."""

    repo: str
    name: str
    revision: str
    size: int
    sha256: str
    licence: str
    local: str
    """The file's name on this PC (LoRAs are named as the prompt calls them)."""

    @property
    def url(self) -> str:
        return HF_FILE_URL.format(
            repo=self.repo, revision=self.revision, name=self.name
        )

    @property
    def owner_repo(self) -> tuple[str, str]:
        owner, _, repo = self.repo.partition("/")
        return owner, repo


@dataclass(frozen=True, slots=True)
class Style:
    """A look for the pictures: its model files and how to ask for it."""

    key: str
    label: str
    model: ModelFile
    loras: tuple[tuple[ModelFile, float], ...]
    prompt: str
    negative: str
    steps: int = 8
    cfg: float = 1.0
    sampler: str = "euler"
    scheduler: str = "sgm_uniform"
    about: str = ""

    def files(self) -> tuple[ModelFile, ...]:
        return (self.model, *(lora for lora, _ in self.loras))

    def download_size(self) -> int:
        return sum(f.size for f in self.files())


PONY = "offgrid-ai/pony-diffusion-v6-xl-GGUF"
PONY_REVISION = "b952fe9fad7fe6f6973c6f74a9d179a6fe4f77eb"
DCAU = ModelFile(
    repo="Muapi/dcau-style-dc-animated-justice-league-unlimited",
    name="dcau-style-dc-animated-justice-league-unlimited.safetensors",
    revision="84252046701bc3134203f57f52d6e9bd34e9ca87",
    size=228_507_836,
    sha256="0119f265e05e71253445a830b9f8fbf0aa6fd9fdb64ecfe86d9b7d40f21cc405",
    licence="openrail++",
    local="dcau.safetensors",
)
LIGHTNING = ModelFile(
    repo="ByteDance/SDXL-Lightning",
    name="sdxl_lightning_8step_lora.safetensors",
    revision="c9a24f48e1c025556787b0c58dd67a091ece2e44",
    size=393_854_592,
    sha256="5aa30d94cdf7950a8b53a693682650ee061eddb128c5435a8f88defea73b2ac6",
    licence="openrail++",
    local="lightning8.safetensors",
)
SUPERHERO_PROMPT = (
    "score_9, score_8_up, score_7_up, source_cartoon, dcaustyle, "
    "2000s superhero cartoon, cel shading, clean thin black lineart, "
    "flat colors with hard shadows, rim light"
)
SUPERHERO_NEGATIVE = (
    "score_4, score_5, score_6, realistic, photo, 3d, cgi, blurry, lowres, "
    "jpeg artifacts, bad anatomy, bad hands, extra fingers, missing fingers, "
    "deformed, text, watermark, signature, logo, sketch, monochrome"
)


def _pony(quant: str, size: int, sha: str) -> ModelFile:
    return ModelFile(
        repo=PONY,
        name=f"pony-diffusion-v6-xl-{quant}.gguf",
        revision=PONY_REVISION,
        size=size,
        sha256=sha,
        licence="creativeml-openrail-m",
        local=f"pony-diffusion-v6-xl-{quant}.gguf",
    )


STYLES: dict[str, Style] = {
    style.key: style
    for style in (
        Style(
            key="superhero",
            label="2000s superhero cartoon (Teen Titans x Ben 10)",
            model=_pony(
                "Q8_0",
                4_180_186_816,
                "d5a3a5204e4ac9043f2e42c616ef6884457c450da0f8cb6f69982ef4649e5ddf",
            ),
            loras=((DCAU, 0.9), (LIGHTNING, 1.0)),
            prompt=SUPERHERO_PROMPT,
            negative=SUPERHERO_NEGATIVE,
            about="Best quality: needs about 8 GB on the graphics card.",
        ),
        Style(
            key="superhero-small",
            label="2000s superhero cartoon, smaller (for 4-6 GB cards)",
            model=_pony(
                "Q4_K",
                2_797_752_960,
                "f25f621cc552b35a0340b7915093ecbb7d02acc7963f89a86fa3e7c3baaf26e4",
            ),
            loras=((DCAU, 0.9), (LIGHTNING, 1.0)),
            prompt=SUPERHERO_PROMPT,
            negative=SUPERHERO_NEGATIVE,
            about="A little softer, about two thirds of the memory.",
        ),
    )
}
DEFAULT_STYLE = "superhero"


# ------------------------------------------------------------------ builds


def asset_pattern(
    build: str, *, system: str = "", machine: str = ""
) -> re.Pattern[str]:
    """This PC's release file: Vulkan on Windows and Linux unless asked for CPU."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    cpu = build == "cpu"
    if system == "windows":
        return re.compile(rf"-bin-win-{'cpu' if cpu else 'vulkan'}-x64\.zip$", re.I)
    if system == "darwin":
        return re.compile(r"-bin-Darwin-macOS-[\w.]+-arm64\.zip$", re.I)
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    tail = "" if cpu else "-vulkan"
    return re.compile(rf"-bin-Linux-Ubuntu-[\d.]+-{arch}{tail}\.zip$", re.I)


@dataclass
class InstallState:
    state: str = "idle"
    """idle, checking, downloading, unpacking, ready, or failed."""
    done: int = 0
    total: int = 0
    version: str = ""
    message: str = ""
    error: str = ""

    def as_json(self) -> JsonObject:
        return {
            "state": self.state,
            "done": self.done,
            "total": self.total,
            "progress": round(self.done / self.total, 3) if self.total else 0.0,
            "version": self.version,
            "message": self.message,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class Picture:
    """One picture to make."""

    prompt: str
    width: int = 1024
    height: int = 1024
    seed: int = 42
    negative: str = ""
    start_from: Path | None = None
    """Change this picture instead of starting from noise (img2img)."""
    strength: float = 0.5
    """How much of start_from to change, 0 (none) to 1 (all)."""


@dataclass
class _Job:
    started: float = field(default_factory=time.monotonic)
    step: int = 0
    steps: int = 0


class ImageEngine:
    """Install stable-diffusion.cpp and a style, then make pictures."""

    def __init__(
        self,
        root: Path,
        *,
        build: Callable[[], str] = lambda: "vulkan",
        style: Callable[[], str] = lambda: DEFAULT_STYLE,
        threads: Callable[[], int] = lambda: max(1, (os.cpu_count() or 4) - 1),
        transport: httpx.AsyncBaseTransport | None = None,
        vault: RepoVault | None = None,
    ) -> None:
        self._root = root
        self._build = build
        self._style = style
        self._threads = threads
        self._transport = transport
        self._vault = vault
        self._lock = asyncio.Lock()
        self._log: deque[str] = deque(maxlen=LOG_LINES)
        self._job: _Job | None = None
        self.install_state = InstallState()
        self.setup_state = InstallState()

    # ---------------------------------------------------------------- places

    @property
    def models_dir(self) -> Path:
        return self._root / "models"

    def style(self) -> Style:
        return STYLES.get(self._style(), STYLES[DEFAULT_STYLE])

    def binary(self) -> Path | None:
        folder = self._root / "bin"
        if not folder.is_dir():
            return None
        names = {"sd-cli.exe", "sd-cli", "sd.exe", "sd"}
        return next(
            (p for p in sorted(folder.rglob("*")) if p.name in names and p.is_file()),
            None,
        )

    def version(self) -> str:
        with contextlib.suppress(OSError):
            return (self._root / "version.txt").read_text(encoding="utf-8").strip()
        return ""

    def style_ready(self, style: Style | None = None) -> bool:
        style = style or self.style()
        return all(self._has(f) for f in style.files())

    def _has(self, model: ModelFile) -> bool:
        path = self.models_dir / model.local
        return path.is_file() and path.stat().st_size == model.size

    def ready(self) -> bool:
        return self.binary() is not None and self.style_ready()

    def logs(self, limit: int = 60) -> list[str]:
        return list(self._log)[-limit:]

    def status(self) -> JsonObject:
        style = self.style()
        job = self._job
        return {
            "installed": self.binary() is not None,
            "version": self.version(),
            "style": style.key,
            "style_label": style.label,
            "style_ready": self.style_ready(style),
            "style_size": style.download_size(),
            "styles": [
                {
                    "key": s.key,
                    "label": s.label,
                    "about": s.about,
                    "size": s.download_size(),
                    "ready": self.style_ready(s),
                }
                for s in STYLES.values()
            ],
            "ready": self.ready(),
            "install": self.install_state.as_json(),
            "setup": self.setup_state.as_json(),
            "busy": job is not None,
            "step": job.step if job else 0,
            "steps": job.steps if job else 0,
            "log": self.logs(20),
        }

    # --------------------------------------------------------------- install

    async def install(self) -> str:
        """Download and unpack stable-diffusion.cpp for this PC."""
        if self.install_state.state in {"checking", "downloading", "unpacking"}:
            raise ImageEngineError("The image engine is already downloading.")
        state = self.install_state = InstallState(state="checking")
        try:
            try:
                tag, archive = await self._download_build(state)
            except (httpx.HTTPError, OSError, ImageEngineError) as error:
                kept = await self._kept_build()
                if kept is None:
                    raise
                logger.info("Studio: image engine from the vault: {}", error)
                tag, archive = await self._from_vault(kept)
            state.state = "unpacking"
            await anyio.to_thread.run_sync(lambda: self._unpack(archive, tag))
            state.state, state.version = "ready", tag
            return tag
        except (
            httpx.HTTPError,
            OSError,
            ImageEngineError,
            zipfile.BadZipFile,
        ) as error:
            state.state, state.error = "failed", f"{error} {self.manual_hint()}"
            raise ImageEngineError(str(error)) from error

    def manual_hint(self) -> str:
        kind = "cpu" if self._build() == "cpu" else "vulkan"
        return (
            "You can also download it yourself: open "
            f"github.com/{SD_OWNER}/{SD_REPO}/releases, download the file named "
            f"like sd-master-…-bin-win-{kind}-x64.zip, and drop it on the Image "
            "engine card."
        )

    async def _find_build(self, client: httpx.AsyncClient) -> tuple[str, str, int]:
        """(tag, url, size) of the newest build for this PC."""
        pattern = asset_pattern(self._build())
        problems: list[str] = []
        try:
            answer = await client.get(
                RELEASES_URL, headers={"accept": "application/vnd.github+json"}
            )
            if answer.status_code < 400 and isinstance(answer.json(), list):
                for release in answer.json():
                    for item in release.get("assets") or []:
                        name = str(item.get("name") or "")
                        if pattern.search(name) and ARCHIVE.match(name):
                            return (
                                str(release.get("tag_name") or ""),
                                str(item["browser_download_url"]),
                                int(item.get("size") or 0),
                            )
                problems.append("no build for this PC in the newest releases")
            else:
                problems.append(f"GitHub's API answered {answer.status_code}")
        except (httpx.HTTPError, ValueError) as error:
            problems.append(f"GitHub's API couldn't be reached ({error})")
        # The API is limited to 60 calls an hour: the release pages work too.
        try:
            page = await client.get(LATEST_PAGE_URL)
            found = re.search(r"/releases/tag/([\w.-]+)", str(page.url))
            if found:
                tag = found.group(1)
                assets = await client.get(ASSETS_PAGE_URL.format(tag=tag))
                for name in re.findall(
                    r"/releases/download/[^/\"]+/([^\"/]+\.zip)", assets.text
                ):
                    if pattern.search(name) and ARCHIVE.match(name):
                        return tag, DOWNLOAD_URL.format(tag=tag, name=name), 0
            problems.append("the latest release page has no build for this PC")
        except httpx.HTTPError as error:
            problems.append(f"github.com couldn't be reached ({error})")
        raise ImageEngineError("; ".join(problems) + ".")

    async def _download_build(self, state: InstallState) -> tuple[str, Path]:
        async with self._client() as client:
            tag, url, size = await self._find_build(client)
            state.state, state.version, state.total = "downloading", tag, size
            archive = self._root / url.rsplit("/", 1)[-1]
            await self._fetch(client, url, archive, state)
        if self._vault is not None:
            try:
                await self._vault.keep_file(
                    owner=SD_OWNER,
                    repo=SD_REPO,
                    kind="release",
                    path=archive,
                    url=url,
                    ref=tag,
                )
            except (OSError, VaultError) as error:
                logger.info("Studio: could not keep the image engine: {}", error)
        return tag, archive

    async def _kept_build(self) -> VaultItem | None:
        if self._vault is None:
            return None
        pattern = asset_pattern(self._build())
        for item in await self._vault.items():
            if (
                item.full_name.lower() == f"{SD_OWNER}/{SD_REPO}".lower()
                and item.kind == "release"
                and pattern.search(item.name)
                and await self._vault.intact(item)
            ):
                return item
        return None

    async def _from_vault(self, item: VaultItem) -> tuple[str, Path]:
        assert self._vault is not None
        try:
            archive = await self._vault.restore_file(item, self._root / item.name)
        except VaultError as error:
            raise ImageEngineError(str(error)) from error
        return item.ref or "kept copy", archive

    async def install_archive(self, archive: Path) -> str:
        """Install a release file the user downloaded themselves."""
        if not ARCHIVE.match(archive.name):
            raise ImageEngineError(
                "That isn't a stable-diffusion.cpp release file (sd-…-bin-….zip)."
            )
        tag = archive.name.removeprefix("sd-").split("-bin-")[0]
        self.install_state = InstallState(state="unpacking", version=tag)
        try:
            await anyio.to_thread.run_sync(lambda: self._unpack(archive, tag))
        except (OSError, zipfile.BadZipFile, ImageEngineError) as error:
            self.install_state.state = "failed"
            self.install_state.error = str(error)
            raise ImageEngineError(f"It couldn't be unpacked: {error}") from error
        self.install_state.state = "ready"
        return tag

    def _unpack(self, archive: Path, tag: str) -> None:
        target = self._root / "bin"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        root = target.resolve()
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                path = (root / member.filename).resolve()
                if not path.is_relative_to(root):
                    raise ImageEngineError(f"Unsafe path in the zip: {member.filename}")
            bundle.extractall(target)
        binary = self.binary()
        if binary is None:
            raise ImageEngineError("The download has no sd-cli program in it.")
        if os.name != "nt":
            for path in binary.parent.iterdir():
                if path.is_file():
                    path.chmod(path.stat().st_mode | 0o755)
        (self._root / "version.txt").write_text(tag, encoding="utf-8")

    # --------------------------------------------------------------- styles

    async def setup_style(self, key: str = "") -> None:
        """Download the style's model files (checked, and kept in the vault)."""
        style = STYLES.get(key) or self.style()
        if self.setup_state.state == "downloading":
            raise ImageEngineError("The style is already downloading.")
        state = self.setup_state = InstallState(
            state="downloading", total=style.download_size(), version=style.key
        )
        try:
            async with self._client() as client:
                for model in style.files():
                    path = self.models_dir / model.local
                    state.message = f"Downloading {model.name}"
                    if not self._has(model) and not await self._from_kept(model, path):
                        try:
                            await self._fetch(
                                client, model.url, path, state, model.size
                            )
                            await self._check(model, path)
                        except httpx.HTTPError, OSError, ImageEngineError:
                            if not await self._from_kept(model, path):
                                raise
                    else:
                        state.done += model.size
                    await self._keep_model(model, path)
            state.state, state.message = "ready", ""
        except (httpx.HTTPError, OSError, ImageEngineError) as error:
            state.state, state.error = "failed", str(error)
            raise ImageEngineError(
                f"The style couldn't be downloaded: {error}"
            ) from error

    async def _check(self, model: ModelFile, path: Path) -> None:
        digest = await anyio.to_thread.run_sync(lambda: _file_sha256(path))
        if digest != model.sha256:
            path.unlink(missing_ok=True)
            raise ImageEngineError(f"{model.name} arrived damaged (checksum differs).")

    async def _keep_model(self, model: ModelFile, path: Path) -> None:
        if self._vault is None:
            return
        owner, repo = model.owner_repo
        if self._vault.has(owner, repo, name=path.name, size=model.size):
            return
        try:
            await self._vault.keep_file(
                owner=owner,
                repo=repo,
                kind="model",
                path=path,
                url=model.url,
                ref=model.revision,
            )
        except (OSError, VaultError) as error:
            logger.info("Studio: could not keep {} in the vault: {}", model.name, error)

    async def _from_kept(self, model: ModelFile, path: Path) -> bool:
        if self._vault is None:
            return False
        owner, repo = model.owner_repo
        kept = await self._vault.latest(owner, repo, kind="model", name=path.name)
        if kept is None or kept.sha256 != model.sha256:
            return False
        try:
            await self._vault.restore_file(kept, path)
        except VaultError, OSError:
            return False
        return True

    # ------------------------------------------------------------- pictures

    def command(
        self, picture: Picture, out: Path, style: Style | None = None
    ) -> list[str]:
        """The sd-cli command for one picture."""
        style = style or self.style()
        binary = self.binary()
        if binary is None:
            raise ImageEngineError("Install the image engine first.")
        loras = " ".join(
            f"<lora:{Path(lora.local).stem}:{weight:g}>" for lora, weight in style.loras
        )
        command = [
            str(binary),
            "-m", str(self.models_dir / style.model.local),
            "--lora-model-dir", str(self.models_dir),
            "-p", f"{style.prompt}, {picture.prompt} {loras}".strip(),
            "--negative-prompt", ", ".join(x for x in (style.negative, picture.negative) if x),
            "-W", str(_multiple(picture.width)),
            "-H", str(_multiple(picture.height)),
            "--steps", str(style.steps),
            "--cfg-scale", f"{style.cfg:g}",
            "--sampling-method", style.sampler,
            "--scheduler", style.scheduler,
            "-s", str(picture.seed),
            "-t", str(self._threads()),
            "--vae-tiling",
            "-o", str(out),
        ]  # fmt: skip
        if picture.start_from is not None:
            command += [
                "--init-img", str(picture.start_from),
                "--strength", f"{max(0.05, min(1.0, picture.strength)):.2f}",
            ]  # fmt: skip
        return command

    async def make(self, picture: Picture, out: Path) -> Path:
        """Make one picture (one at a time: each uses the whole graphics card)."""
        if not self.ready():
            raise ImageEngineError(
                "Set up the image engine first (Settings → Image engine)."
            )
        command = self.command(picture, out)
        out.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            self._job = job = _Job(steps=self.style().steps)
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=self._root,
                )
                try:
                    await asyncio.wait_for(self._read(process, job), PICTURE_SECONDS)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                    raise ImageEngineError(
                        "The picture took too long and was stopped."
                    ) from None
                except asyncio.CancelledError:
                    # Studio is closing or the video was stopped: the
                    # painter must not keep the graphics card busy.
                    if process.returncode is None:
                        process.kill()
                    raise
            finally:
                self._job = None
        if process.returncode != 0 or not out.is_file():
            tail = " ".join(self.logs(3))
            raise ImageEngineError(
                f"The image engine stopped (code {process.returncode}). {tail}"
            )
        return out

    async def _read(self, process: asyncio.subprocess.Process, job: _Job) -> None:
        assert process.stdout is not None
        buffer = b""
        while chunk := await process.stdout.read(4096):
            buffer += chunk
            *lines, buffer = re.split(rb"[\r\n]", buffer)
            for raw in lines:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                found = _PROGRESS.search(line)
                if found:
                    job.step, job.steps = int(found.group(1)), int(found.group(2))
                    continue
                self._log.append(line)
        await process.wait()

    # ---------------------------------------------------------------- shared

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=120.0),
            follow_redirects=True,
            transport=self._transport,
        )

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        url: str,
        target: Path,
        state: InstallState,
        size: int = 0,
    ) -> None:
        """Download into a .part file (resuming one left half-done), then
        move it into place."""
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        have = partial.stat().st_size if partial.is_file() else 0
        if size and have > size:
            partial.unlink()
            have = 0
        headers = {"range": f"bytes={have}-"} if have else {}
        base = state.done
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code == 200:
                have = 0
            elif response.status_code != 206:
                raise ImageEngineError(f"The download answered {response.status_code}.")
            if not state.total:
                length = response.headers.get("content-length", "")
                state.total = int(length) if length.isdigit() else 0
            handle = await anyio.to_thread.run_sync(
                lambda: partial.open("ab" if have else "wb")
            )
            try:
                async for chunk in response.aiter_bytes(_CHUNK):
                    await anyio.to_thread.run_sync(handle.write, chunk)
                    have += len(chunk)
                    state.done = base + have
            finally:
                await anyio.to_thread.run_sync(handle.close)
        if size and partial.stat().st_size != size:
            raise ImageEngineError(
                f"{target.name} is {partial.stat().st_size} bytes, expected {size}."
            )
        target.unlink(missing_ok=True)
        partial.replace(target)


def _multiple(value: int, step: int = 64) -> int:
    """Picture sides are multiples of 64, between 256 and 2048."""
    return max(256, min(2048, round(value / step) * step))


def style_choices() -> Sequence[str]:
    return tuple(STYLES)
