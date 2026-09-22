"""Download, verify, and extract local model files the user picks."""

import hashlib
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import anyio.to_thread
import httpx
from loguru import logger

from .models import ModelAsset, now_ms
from .store import StudioStore

PROGRESS_INTERVAL_BYTES = 2_000_000
CHUNK_BYTES = 262_144
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2")


class DownloadError(RuntimeError):
    """Raised when a model file cannot be downloaded or unpacked."""


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One curated, small model that runs comfortably on a phone or laptop."""

    id: str
    name: str
    url: str
    parameters: str
    quantization: str
    approx_bytes: int
    note: str
    guide: bool = False


CURATED_MODELS: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="qwen3-0.6b-q4",
        name="Qwen3 0.6B Instruct (Q4_K_M)",
        url=(
            "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/"
            "Qwen3-0.6B-Q4_K_M.gguf"
        ),
        parameters="0.6B",
        quantization="Q4_K_M",
        approx_bytes=460_000_000,
        note="Default in-app guide. Small enough for an iPhone.",
        guide=True,
    ),
    CatalogEntry(
        id="smollm2-360m-q8",
        name="SmolLM2 360M Instruct (Q8_0)",
        url=(
            "https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct-GGUF/"
            "resolve/main/smollm2-360m-instruct-q8_0.gguf"
        ),
        parameters="360M",
        quantization="Q8_0",
        approx_bytes=390_000_000,
        note="The lightest guide option; fastest to download.",
    ),
    CatalogEntry(
        id="llama-3.2-1b-q4",
        name="Llama 3.2 1B Instruct (Q4_K_M)",
        url=(
            "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/"
            "resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
        ),
        parameters="1B",
        quantization="Q4_K_M",
        approx_bytes=810_000_000,
        note="Good student model for very light tuning.",
    ),
    CatalogEntry(
        id="qwen2.5-3b-q4",
        name="Qwen2.5 3B Instruct (Q4_K_M)",
        url=(
            "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/"
            "qwen2.5-3b-instruct-q4_k_m.gguf"
        ),
        parameters="3B",
        quantization="Q4_K_M",
        approx_bytes=2_000_000_000,
        note="Capable teacher model for on-device classes.",
    ),
    CatalogEntry(
        id="qwen2.5-coder-7b-q4",
        name="Qwen2.5 Coder 7B (Q4_K_M)",
        url=(
            "https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/"
            "resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
        ),
        parameters="7B",
        quantization="Q4_K_M",
        approx_bytes=4_700_000_000,
        note="Desktop-class agent for building websites offline.",
    ),
)

CATALOG_BY_ID = {entry.id: entry for entry in CURATED_MODELS}


def default_guide_entry() -> CatalogEntry:
    """Return the curated model preloaded as the in-app guide."""
    return next(entry for entry in CURATED_MODELS if entry.guide)


def filename_for(url: str) -> str:
    """Return a safe local filename derived from a download URL."""
    name = Path(unquote(urlparse(url).path)).name
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in name
    ).strip("._")
    return cleaned[:96] or "model.bin"


def is_archive(name: str) -> bool:
    """Return whether a filename looks like a supported archive."""
    lowered = name.lower()
    return any(lowered.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _safe_member(name: str) -> bool:
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts


def extract_archive(archive: Path, destination: Path) -> int:
    """Unpack one archive, refusing members that escape the destination."""
    destination.mkdir(parents=True, exist_ok=True)
    extracted = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            members = [name for name in bundle.namelist() if _safe_member(name)]
            if len(members) != len(bundle.namelist()):
                raise DownloadError("The archive contains unsafe paths.")
            bundle.extractall(destination)
            extracted = len(members)
        return extracted
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as bundle:
            members = [item for item in bundle.getmembers() if _safe_member(item.name)]
            if len(members) != len(bundle.getmembers()):
                raise DownloadError("The archive contains unsafe paths.")
            bundle.extractall(destination, members=members, filter="data")
            extracted = len(members)
        return extracted
    raise DownloadError("Only zip and tar archives can be extracted.")


class ModelLibrary:
    """Own the on-disk model directory and every download tracked for it."""

    def __init__(
        self,
        *,
        store: StudioStore,
        models_dir: Path,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._store = store
        self._dir = models_dir
        self._transport = transport
        self._timeout = timeout

    @property
    def directory(self) -> Path:
        return self._dir

    async def queue(
        self,
        *,
        url: str,
        name: str = "",
        sha256: str | None = None,
        preloaded: bool = False,
    ) -> ModelAsset:
        """Record one requested download without starting it."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DownloadError("Model downloads must use an http(s) URL.")
        filename = filename_for(url)
        asset = ModelAsset.model_validate(
            {
                "name": name or filename,
                "source_url": url,
                "path": str(self._dir / filename),
                "kind": "archive" if is_archive(filename) else "gguf",
                "sha256": sha256,
                "preloaded": preloaded,
            }
        )
        await self._store.put(asset)
        return asset

    async def queue_catalog(self, catalog_id: str) -> ModelAsset:
        """Queue one curated model by catalog identifier."""
        entry = CATALOG_BY_ID.get(catalog_id)
        if entry is None:
            raise DownloadError(f"Unknown model '{catalog_id}'.")
        existing = await self._store.find(ModelAsset, where={"source_url": entry.url})
        ready = next((item for item in existing if item.status == "ready"), None)
        if ready is not None:
            return ready
        return await self.queue(url=entry.url, name=entry.name, preloaded=entry.guide)

    async def download(self, asset_id: str) -> ModelAsset:
        """Download one queued asset, resuming a partial file when present."""
        asset = await self._store.require(ModelAsset, asset_id)
        if asset.status == "ready":
            return asset
        target = Path(asset.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.stat().st_size if target.is_file() else 0
        headers = {"Range": f"bytes={existing}-"} if existing else {}
        asset = await self._mark(
            asset, status="downloading", bytes_done=existing, error=None
        )
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self._timeout,
                    transport=self._transport,
                    follow_redirects=True,
                ) as client,
                client.stream("GET", asset.source_url, headers=headers) as response,
            ):
                if response.status_code == 416:
                    return await self._finish(asset, target)
                if response.status_code >= 400:
                    raise DownloadError(
                        f"Download failed with HTTP {response.status_code}."
                    )
                resuming = response.status_code == 206 and existing > 0
                written = existing if resuming else 0
                total = _total_bytes(response, offset=written)
                asset = await self._mark(asset, status="downloading", bytes_total=total)
                mode = "ab" if resuming else "wb"
                marker = written
                with target.open(mode) as handle:
                    async for chunk in response.aiter_bytes(CHUNK_BYTES):
                        handle.write(chunk)
                        written += len(chunk)
                        if written - marker >= PROGRESS_INTERVAL_BYTES:
                            marker = written
                            asset = await self._mark(
                                asset, status="downloading", bytes_done=written
                            )
            return await self._finish(asset, target)
        except (httpx.HTTPError, OSError, DownloadError) as error:
            logger.warning("Studio model download failed: {}", error)
            return await self._mark(asset, status="failed", error=str(error))

    async def _finish(self, asset: ModelAsset, target: Path) -> ModelAsset:
        size = target.stat().st_size if target.is_file() else 0
        if asset.sha256:
            digest = await anyio.to_thread.run_sync(lambda: _sha256(target))
            if digest.lower() != asset.sha256.lower():
                return await self._mark(
                    asset, status="failed", error="Checksum did not match."
                )
        if asset.kind == "archive":
            asset = await self._mark(asset, status="extracting", bytes_done=size)
            destination = target.with_suffix("")
            try:
                await anyio.to_thread.run_sync(
                    lambda: extract_archive(target, destination)
                )
            except (DownloadError, OSError, tarfile.TarError) as error:
                return await self._mark(asset, status="failed", error=str(error))
            return await self._mark(
                asset,
                status="ready",
                bytes_done=size,
                bytes_total=size,
                extracted_dir=str(destination),
            )
        return await self._mark(
            asset, status="ready", bytes_done=size, bytes_total=max(size, 1)
        )

    async def _mark(self, asset: ModelAsset, **updates: object) -> ModelAsset:
        current = await self._store.get(ModelAsset, asset.id) or asset
        updated = current.model_copy(update={**updates, "updated_at": now_ms()})
        await self._store.put(updated)
        return updated

    async def cancel(self, asset_id: str) -> ModelAsset:
        """Mark one download cancelled; a partial file stays for resuming."""
        asset = await self._store.require(ModelAsset, asset_id)
        return await self._mark(asset, status="cancelled")

    async def remove(self, asset_id: str) -> bool:
        """Delete one asset's files and its record."""
        asset = await self._store.get(ModelAsset, asset_id)
        if asset is None:
            return False

        def work() -> None:
            path = Path(asset.path)
            if path.is_file():
                path.unlink()

        await anyio.to_thread.run_sync(work)
        return await self._store.delete(ModelAsset, asset_id)

    async def assets(self) -> tuple[ModelAsset, ...]:
        """Return every tracked download, newest first."""
        return await self._store.find(ModelAsset, order_by="created_at DESC")

    async def ready_models(self) -> tuple[ModelAsset, ...]:
        """Return the assets that can back a local model reference."""
        return tuple(item for item in await self.assets() if item.status == "ready")

    async def scan_directory(self) -> tuple[ModelAsset, ...]:
        """Adopt model files the user copied into the models directory by hand."""

        def listing() -> list[Path]:
            if not self._dir.is_dir():
                return []
            return sorted(path for path in self._dir.glob("*.gguf") if path.is_file())

        found = await anyio.to_thread.run_sync(listing)
        known = {item.path for item in await self.assets()}
        adopted: list[ModelAsset] = []
        for path in found:
            if str(path) in known:
                continue
            asset = ModelAsset.model_validate(
                {
                    "name": path.name,
                    "source_url": path.as_uri(),
                    "path": str(path),
                    "kind": "gguf",
                    "status": "ready",
                    "bytes_done": path.stat().st_size,
                    "bytes_total": path.stat().st_size,
                }
            )
            await self._store.put(asset)
            adopted.append(asset)
        return tuple(adopted)


def _total_bytes(response: httpx.Response, *, offset: int) -> int:
    content_range = response.headers.get("content-range")
    if content_range and "/" in content_range:
        tail = content_range.rsplit("/", 1)[1].strip()
        if tail.isdigit():
            return int(tail)
    length = response.headers.get("content-length")
    if length and length.isdigit():
        return offset + int(length)
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()
