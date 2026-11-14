"""Whatever Studio downloads from GitHub is kept, and installs from the
kept copy when GitHub no longer has it."""

import io
import tarfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio import local_voice
from free_claude_code.studio.engine import Engine, asset_pattern
from free_claude_code.studio.local_voice import LocalVoice, SetupState
from free_claude_code.studio.vault import RepoVault


def engine_build(tag: str) -> bytes:
    bundle = io.BytesIO()
    with tarfile.open(fileobj=bundle, mode="w:gz") as tar:
        program = b"#!/bin/sh\n"
        entry = tarfile.TarInfo(f"llama-{tag}/llama-server")
        entry.size = len(program)
        tar.addfile(entry, io.BytesIO(program))
    return bundle.getvalue()


def this_pc_build(tag: str) -> str:
    for name in (
        f"llama-{tag}-bin-ubuntu-vulkan-x64.tar.gz",
        f"llama-{tag}-bin-ubuntu-vulkan-arm64.tar.gz",
        f"llama-{tag}-bin-macos-arm64.tar.gz",
        f"llama-{tag}-bin-macos-x64.tar.gz",
    ):
        if asset_pattern("vulkan").search(name):
            return name
    pytest.skip("this test's builds are for Linux and macOS")


def github(release: dict | None, files: dict[str, bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if release is None:
            return httpx.Response(404)
        if "api.github.com" in str(request.url):
            return httpx.Response(200, json=release)
        return httpx.Response(200, content=files[str(request.url).rsplit("/", 1)[-1]])

    return httpx.MockTransport(handler)


def engine(tmp_path: Path, store, vault: RepoVault, transport) -> Engine:
    return Engine(
        root=tmp_path / "engine",
        store=store,
        folders=lambda: [],
        port=lambda: 1,
        build=lambda: "vulkan",
        transport=transport,
        vault=vault,
    )


@pytest.mark.asyncio
async def test_the_engine_installs_from_the_vault_when_its_release_is_gone(
    tmp_path, store
):
    vault = RepoVault(tmp_path / "vault")
    name = this_pc_build("b9000")
    data = engine_build("b9000")
    release = {
        "tag_name": "b9000",
        "assets": [
            {
                "name": name,
                "size": len(data),
                "browser_download_url": f"https://dl.test/{name}",
            }
        ],
    }
    first = engine(tmp_path / "a", store, vault, github(release, {name: data}))
    assert await first.install() == "b9000"
    kept = await vault.items()
    assert [(item.owner, item.repo, item.kind, item.name) for item in kept] == [
        ("ggml-org", "llama.cpp", "release", name)
    ]
    assert vault.path(kept[0]).read_bytes() == data, "the exact bytes"

    gone = engine(tmp_path / "b", store, vault, github(None, {}))
    assert await gone.install() == "b9000"
    binary = gone.binary()
    assert binary is not None and binary.name == "llama-server"
    assert gone.install_state.state == "ready"
    assert await vault.intact(kept[0]), "installing doesn't use up the vault copy"


@pytest.mark.asyncio
async def test_with_nothing_kept_a_missing_engine_release_still_says_so(
    tmp_path, store
):
    lost = engine(tmp_path, store, RepoVault(tmp_path / "vault"), github(None, {}))
    with pytest.raises(Exception, match="404"):
        await lost.install()
    assert lost.install_state.state == "failed"


@pytest.mark.asyncio
async def test_the_voice_installs_from_the_vault_when_its_release_is_gone(
    tmp_path, monkeypatch
):
    model, voices = b"M" * 3000, b"V" * 1000
    monkeypatch.setitem(local_voice.KOKORO_MODELS, "high", ("model.onnx", len(model)))
    monkeypatch.setattr(local_voice, "VOICES_FILE", ("voices.bin", len(voices)))
    monkeypatch.setattr(local_voice, "speech_package_ready", lambda: True)
    monkeypatch.setattr(local_voice, "listen_package_ready", lambda: False)
    vault = RepoVault(tmp_path / "vault")

    def released(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=model if request.url.path.endswith("model.onnx") else voices
        )

    async def progress(done: int, total: int, message: str) -> None:
        return None

    first = LocalVoice(
        tmp_path / "pc1", transport=httpx.MockTransport(released), vault=vault
    )
    await first.setup(SetupState(phase="running"), progress)
    assert {item.name for item in await vault.items()} == {"model.onnx", "voices.bin"}

    gone = httpx.MockTransport(lambda request: httpx.Response(404))
    second = LocalVoice(tmp_path / "pc2", transport=gone, vault=vault)
    state = SetupState(phase="running")
    await second.setup(state, progress)
    assert state.errors == []
    assert (tmp_path / "pc2" / "model.onnx").read_bytes() == model
    assert second.speech_files_ready()

    third = LocalVoice(
        tmp_path / "pc3", transport=gone, vault=RepoVault(tmp_path / "empty")
    )
    state = SetupState(phase="running")
    await third.setup(state, progress)
    assert state.errors and "Voice download failed" in state.errors[0]


@pytest.mark.asyncio
async def test_a_damaged_vault_copy_is_never_installed(tmp_path):
    vault = RepoVault(tmp_path / "vault")
    source = tmp_path / "file.bin"
    source.write_bytes(b"good bytes")
    item = await vault.keep_file(
        owner="o", repo="r", kind="release", path=source, url="https://x.test/f"
    )
    again = await vault.keep_file(
        owner="o", repo="r", kind="release", path=source, url="https://x.test/f"
    )
    assert again.id == item.id, "kept once"
    source.unlink()
    vault.path(item).write_bytes(b"bad bytes!")
    assert not await vault.intact(item)
    with pytest.raises(Exception, match="damaged"):
        await vault.restore_file(item, tmp_path / "out.bin")


@pytest.mark.asyncio
async def test_keeps_at_the_same_time_are_all_listed(tmp_path):
    import asyncio

    vault = RepoVault(tmp_path / "vault")
    files = []
    for n in range(6):
        path = tmp_path / f"file{n}.bin"
        path.write_bytes(f"bytes {n}".encode())
        files.append(path)
    await asyncio.gather(
        *(
            vault.keep_file(owner="o", repo=f"r{n}", kind="release", path=path, url="u")
            for n, path in enumerate(files)
        )
    )
    assert len(await vault.items()) == 6
    assert vault.has("o", "r3", name="file3.bin", size=len(b"bytes 3"))
    assert not vault.has("o", "r3", name="file3.bin", size=1)
