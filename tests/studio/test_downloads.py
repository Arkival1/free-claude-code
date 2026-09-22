"""Model downloads resume, verify, extract, and report progress."""

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio.downloads import (
    CATALOG_BY_ID,
    DownloadError,
    ModelLibrary,
    default_guide_entry,
    extract_archive,
    filename_for,
    is_archive,
)
from free_claude_code.studio.models import ModelAsset


def _library(store, tmp_path, handler) -> ModelLibrary:
    return ModelLibrary(
        store=store,
        models_dir=tmp_path / "models",
        transport=httpx.MockTransport(handler),
    )


def test_filenames_are_derived_safely():
    assert filename_for("https://host/models/Qwen3-0.6B-Q4_K_M.gguf") == (
        "Qwen3-0.6B-Q4_K_M.gguf"
    )
    assert filename_for("https://host/../../etc/passwd") == "passwd"
    assert filename_for("https://host/") == "model.bin"
    assert is_archive("bundle.tar.gz") is True
    assert is_archive("model.gguf") is False


def test_the_guide_model_is_in_the_catalog():
    entry = default_guide_entry()
    assert entry.guide is True
    assert CATALOG_BY_ID[entry.id] is entry


@pytest.mark.asyncio
async def test_download_tracks_progress_and_completes(store, tmp_path):
    payload = b"gguf-bytes" * 2048

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=payload, headers={"content-length": str(len(payload))}
        )

    library = _library(store, tmp_path, handler)
    queued = await library.queue(url="https://host/model.gguf", name="Tiny")
    assert queued.status == "queued"

    finished = await library.download(queued.id)

    assert finished.status == "ready"
    assert finished.bytes_done == len(payload)
    assert finished.progress == 1.0
    assert Path(finished.path).read_bytes() == payload


@pytest.mark.asyncio
async def test_download_resumes_from_a_partial_file(store, tmp_path):
    head, tail = b"first-half", b"second-half"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("range", ""))
        return httpx.Response(
            206,
            content=tail,
            headers={"content-range": f"bytes 10-20/{len(head) + len(tail)}"},
        )

    library = _library(store, tmp_path, handler)
    asset = await library.queue(url="https://host/model.gguf")
    target = Path(asset.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(head)

    finished = await library.download(asset.id)

    assert seen == ["bytes=10-"]
    assert finished.status == "ready"
    assert target.read_bytes() == head + tail


@pytest.mark.asyncio
async def test_failed_checksum_is_reported(store, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-the-model")

    library = _library(store, tmp_path, handler)
    asset = await library.queue(
        url="https://host/model.gguf", sha256=hashlib.sha256(b"other").hexdigest()
    )

    finished = await library.download(asset.id)

    assert finished.status == "failed"
    assert finished.error == "Checksum did not match."


@pytest.mark.asyncio
async def test_http_failures_do_not_raise(store, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    library = _library(store, tmp_path, handler)
    asset = await library.queue(url="https://host/missing.gguf")

    finished = await library.download(asset.id)

    assert finished.status == "failed"
    assert "404" in (finished.error or "")


@pytest.mark.asyncio
async def test_archives_are_extracted_after_download(store, tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("adapter/config.json", "{}")
    payload = buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    library = _library(store, tmp_path, handler)
    asset = await library.queue(url="https://host/adapter.zip")
    assert asset.kind == "archive"

    finished = await library.download(asset.id)

    assert finished.status == "ready"
    assert finished.extracted_dir is not None
    assert (Path(finished.extracted_dir) / "adapter/config.json").is_file()


def test_unsafe_archive_members_are_refused(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "nope")

    with pytest.raises(DownloadError):
        extract_archive(archive, tmp_path / "out")


def test_tar_archives_extract(tmp_path):
    source = tmp_path / "file.txt"
    source.write_text("model", encoding="utf-8")
    archive = tmp_path / "bundle.tar"
    with tarfile.open(archive, "w") as bundle:
        bundle.add(source, arcname="inner/file.txt")

    assert extract_archive(archive, tmp_path / "out") == 1
    assert (tmp_path / "out/inner/file.txt").read_text(encoding="utf-8") == "model"


@pytest.mark.asyncio
async def test_only_http_urls_are_accepted(store, tmp_path):
    library = _library(store, tmp_path, lambda request: httpx.Response(200))

    with pytest.raises(DownloadError):
        await library.queue(url="file:///etc/passwd")


@pytest.mark.asyncio
async def test_hand_copied_models_are_adopted(store, tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "local-model.gguf").write_bytes(b"weights")
    library = _library(store, tmp_path, lambda request: httpx.Response(200))

    adopted = await library.scan_directory()

    assert [asset.name for asset in adopted] == ["local-model.gguf"]
    assert (await library.ready_models())[0].status == "ready"
    assert await store.find(ModelAsset)


@pytest.mark.asyncio
async def test_catalog_downloads_are_not_repeated(store, tmp_path):
    library = _library(store, tmp_path, lambda request: httpx.Response(200))
    entry = default_guide_entry()

    first = await library.queue_catalog(entry.id)
    ready = first.model_copy(update={"status": "ready"})
    await store.put(ready)
    second = await library.queue_catalog(entry.id)

    assert second.id == first.id
