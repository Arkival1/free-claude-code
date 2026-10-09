"""The image engine: stable-diffusion.cpp and a style, installed once (and
from the vault when the originals are gone), then painting pictures."""

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio import image_engine
from free_claude_code.studio.image_engine import (
    ImageEngine,
    ImageEngineError,
    ModelFile,
    Picture,
    Style,
    asset_pattern,
)
from free_claude_code.studio.vault import RepoVault

FAKE_SD = f"""#!{sys.executable}
import sys
args = sys.argv[1:]
out = args[args.index("-o") + 1]
open(sys.argv[0] + ".args", "w").write("\\n".join(args))
for step in range(1, 5):
    print(f"  |=====>     | {{step}}/4 - 1.20s/it", flush=True)
print("generate_image completed", flush=True)
from PIL import Image
Image.new("RGB", (64, 64), (255, 255, 255)).save(out)
"""


def sd_zip(name: str = "sd-cli") -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        bundle.writestr(name, FAKE_SD)
        bundle.writestr("stable-diffusion.cpp.txt", "MIT License")
    return data.getvalue()


def model_file(name: str, data: bytes, repo: str = "someone/cartoon") -> ModelFile:
    return ModelFile(
        repo=repo,
        name=name,
        revision="abc123",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        licence="openrail++",
        local=name,
    )


MODEL = b"pretend model weights " * 50
LORA = b"pretend style lora " * 40


@pytest.fixture
def tiny_style(monkeypatch):
    style = Style(
        key="tiny",
        label="Tiny test style",
        model=model_file("model.gguf", MODEL),
        loras=((model_file("toon.safetensors", LORA, "someone/toon"), 0.8),),
        prompt="cartoon",
        negative="photo",
    )
    monkeypatch.setitem(image_engine.STYLES, "tiny", style)
    return style


def this_pc_name() -> str:
    for name in (
        "sd-master-1-abc-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip",
        "sd-master-1-abc-bin-Linux-Ubuntu-24.04-aarch64-vulkan.zip",
        "sd-master-1-abc-bin-Darwin-macOS-15.6-arm64.zip",
        "sd-master-1-abc-bin-win-vulkan-x64.zip",
    ):
        if asset_pattern("vulkan").search(name):
            return name
    pytest.skip("no test build for this PC")


def hub(
    files: dict[str, bytes], *, github: bool = True, hf: bool = True
) -> httpx.MockTransport:
    name = this_pc_name()
    release = [
        {
            "tag_name": "master-1-abc",
            "assets": [
                {
                    "name": "sd-master-1-abc-bin-win-cuda12-x64.zip",
                    "size": 1,
                    "browser_download_url": "https://dl.test/cuda.zip",
                },
                {
                    "name": name,
                    "size": len(files[name]),
                    "browser_download_url": f"https://dl.test/{name}",
                },
            ],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "huggingface.co" in url:
            if not hf:
                return httpx.Response(404)
            return httpx.Response(200, content=files[url.rsplit("/", 1)[-1]])
        if not github:
            return httpx.Response(404)
        if "api.github.com" in url:
            return httpx.Response(200, json=release)
        return httpx.Response(200, content=files[url.rsplit("/", 1)[-1]])

    return httpx.MockTransport(handler)


def engine(root: Path, transport, vault: RepoVault | None = None) -> ImageEngine:
    return ImageEngine(root, style=lambda: "tiny", transport=transport, vault=vault)


def test_each_pc_gets_its_own_build():
    win = asset_pattern("vulkan", system="Windows", machine="AMD64")
    assert win.search("sd-master-948-228c707-bin-win-vulkan-x64.zip")
    assert not win.search("sd-master-948-228c707-bin-win-cuda12-x64.zip")
    cpu = asset_pattern("cpu", system="Windows", machine="AMD64")
    assert cpu.search("sd-master-948-228c707-bin-win-cpu-x64.zip")
    linux = asset_pattern("vulkan", system="Linux", machine="x86_64")
    assert linux.search(
        "sd-master-948-228c707-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip"
    )
    assert not linux.search("sd-master-948-228c707-bin-Linux-Ubuntu-24.04-x86_64.zip")
    mac = asset_pattern("vulkan", system="Darwin", machine="arm64")
    assert mac.search("sd-master-948-228c707-bin-Darwin-macOS-15.6-arm64.zip")


@pytest.mark.asyncio
async def test_set_up_installs_the_engine_and_the_style_then_paints(
    tmp_path, tiny_style
):
    files = {this_pc_name(): sd_zip(), "model.gguf": MODEL, "toon.safetensors": LORA}
    vault = RepoVault(tmp_path / "vault")
    paint = engine(tmp_path / "a", hub(files), vault)
    assert not paint.ready()
    assert await paint.install() == "master-1-abc"
    await paint.setup_style()
    assert paint.ready()
    assert paint.status()["style_ready"]

    out = await paint.make(
        Picture(prompt="a hero", width=1000, height=700, seed=5), tmp_path / "p.png"
    )
    assert out.is_file()
    args = Path(str(paint.binary()) + ".args").read_text().splitlines()
    prompt = args[args.index("-p") + 1]
    assert prompt.startswith("cartoon, a hero") and "<lora:toon:0.8>" in prompt
    assert args[args.index("-W") + 1] == "1024" and args[args.index("-H") + 1] == "704"
    assert args[args.index("--negative-prompt") + 1] == "photo"
    assert "generate_image completed" in paint.logs()
    # Everything downloaded is kept in the vault.
    kept = {item.name for item in await vault.items()}
    assert {this_pc_name(), "model.gguf", "toon.safetensors"} <= kept


@pytest.mark.asyncio
async def test_it_installs_from_the_vault_after_github_and_hugging_face_lose_it(
    tmp_path, tiny_style
):
    files = {this_pc_name(): sd_zip(), "model.gguf": MODEL, "toon.safetensors": LORA}
    vault = RepoVault(tmp_path / "vault")
    first = engine(tmp_path / "a", hub(files), vault)
    await first.install()
    await first.setup_style()

    later = engine(tmp_path / "b", hub(files, github=False, hf=False), vault)
    await later.install()
    await later.setup_style()
    assert later.ready()
    assert (tmp_path / "b" / "models" / "model.gguf").read_bytes() == MODEL


@pytest.mark.asyncio
async def test_a_damaged_download_is_refused(tmp_path, tiny_style):
    files = {
        this_pc_name(): sd_zip(),
        "model.gguf": b"x" * len(MODEL),
        "toon.safetensors": LORA,
    }
    paint = engine(tmp_path, hub(files))
    with pytest.raises(ImageEngineError, match="damaged"):
        await paint.setup_style()
    assert paint.setup_state.state == "failed"
    assert not (tmp_path / "models" / "model.gguf").exists()


@pytest.mark.asyncio
async def test_painting_needs_the_engine_set_up(tmp_path, tiny_style):
    paint = engine(tmp_path, hub({this_pc_name(): sd_zip()}))
    with pytest.raises(ImageEngineError, match="Set up the image engine"):
        await paint.make(Picture(prompt="x"), tmp_path / "x.png")


@pytest.mark.asyncio
async def test_a_release_file_from_the_user_installs(tmp_path, tiny_style):
    archive = tmp_path / "sd-master-2-def-bin-win-vulkan-x64.zip"
    archive.write_bytes(sd_zip("sd-cli.exe"))
    paint = engine(tmp_path / "root", hub({this_pc_name(): sd_zip()}))
    assert await paint.install_archive(archive) == "master-2-def"
    binary = paint.binary()
    assert binary is not None and binary.name == "sd-cli.exe"
    with pytest.raises(ImageEngineError, match="release file"):
        await paint.install_archive(tmp_path / "something.zip")


@pytest.mark.asyncio
async def test_changing_a_picture_starts_from_it(tmp_path, tiny_style):
    files = {this_pc_name(): sd_zip(), "model.gguf": MODEL, "toon.safetensors": LORA}
    paint = engine(tmp_path, hub(files))
    await paint.install()
    await paint.setup_style()
    start = tmp_path / "start.png"
    start.write_bytes(b"png")
    command = paint.command(
        Picture(prompt="talking", start_from=start, strength=0.3), tmp_path / "o.png"
    )
    assert command[command.index("--init-img") + 1] == str(start)
    assert command[command.index("--strength") + 1] == "0.30"


def test_the_styles_are_pinned_to_exact_files():
    for style in image_engine.STYLES.values():
        for model in style.files():
            assert len(model.revision) == 40 and len(model.sha256) == 64
            assert model.revision in model.url and model.size > 0


@pytest.mark.asyncio
async def test_the_image_engine_through_the_routes(make_studio, tmp_path):
    from tests.api.support import create_test_app

    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            status = (await client.get("/studio/api/image-engine")).json()
            assert not status["ready"] and status["source"] == "pc"
            assert status["cartoon_art"] == "auto" and not status["painting_ready"]
            assert not studio.paints_cartoons()
            refused = await client.post("/studio/api/image-engine/sample", json={})
            assert refused.status_code >= 400
            missing = await client.get("/studio/api/image-engine/sample.png")
            assert missing.status_code == 404
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_only_the_pc_itself_can_set_up_the_image_engine(make_studio):
    from tests.api.support import create_test_app

    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    transport = httpx.ASGITransport(app=app, client=("192.168.1.20", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://pc") as client:
        try:
            refused = await client.post("/studio/api/image-engine/install")
            assert refused.status_code == 403
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_an_online_image_service_paints_when_chosen(make_studio, tmp_path):
    import base64

    from free_claude_code.studio.farm.cartoon.aiart import ArtError

    sent: list[httpx.Request] = []

    def service(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(b"\x89PNG fake").decode()}]}
        )

    studio, _ = make_studio(
        [],
        STUDIO_IMAGE_SOURCE="cloud",
        STUDIO_IMAGE_CLOUD_URL="https://images.test/v1",
        STUDIO_IMAGE_CLOUD_KEY="k-123",
    )
    studio.image_transport = httpx.MockTransport(service)
    try:
        assert studio.painting_ready() and studio.paints_cartoons()
        out = await studio.paint("a teen hero", (832, 1216), 1, tmp_path / "hero.png")
        assert out.read_bytes() == b"\x89PNG fake"
        request = sent[0]
        assert str(request.url) == "https://images.test/v1/images/generations"
        assert request.headers["authorization"] == "Bearer k-123"
        body = request.read().decode()
        assert "dcaustyle" in body and "1024x1536" in body
        # The farm sees failures as art errors, so it can draw instead.
        studio.image_transport = httpx.MockTransport(lambda _: httpx.Response(500))
        with pytest.raises(ArtError, match="500"):
            await studio._farm_paint("x", (10, 10), 1, tmp_path / "y.png", None, 0.5)
    finally:
        await studio.shutdown()


@pytest.mark.asyncio
async def test_a_stopped_picture_stops_the_painter(tmp_path, tiny_style):
    import asyncio
    import os

    slow = FAKE_SD.replace("for step in range(1, 5):", "import time\ntime.sleep(30)\nfor step in range(1, 5):")
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        bundle.writestr("sd-cli", slow)
    files = {this_pc_name(): data.getvalue(), "model.gguf": MODEL, "toon.safetensors": LORA}
    paint = engine(tmp_path, hub(files))
    await paint.install()
    await paint.setup_style()
    job = asyncio.ensure_future(paint.make(Picture(prompt="x"), tmp_path / "x.png"))
    await asyncio.sleep(1.0)
    pids = [p for p in os.listdir("/proc") if p.isdigit()] if os.path.isdir("/proc") else []
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    await asyncio.sleep(0.3)
    still = []
    for pid in pids:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                if str(paint.binary()).encode() in handle.read():
                    with open(f"/proc/{pid}/stat") as stat:
                        if stat.read().split()[2] != "Z":
                            still.append(pid)
        except OSError:
            continue
    assert not still
    assert not paint.status()["busy"]


def test_the_settings_offer_every_style():
    from free_claude_code.config.settings import IMAGE_STYLES

    assert tuple(image_engine.STYLES) == IMAGE_STYLES
