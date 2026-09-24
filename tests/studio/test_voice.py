"""The main AI's voice: built in and offline by default, or a voice server."""

import io
import json
import wave

import httpx
import pytest

from free_claude_code.studio import local_voice
from free_claude_code.studio import service as service_module
from free_claude_code.studio.local_voice import LocalVoice, LocalVoiceError, SetupState
from free_claude_code.studio.voice import VoiceError, VoiceService, speakable
from tests.api.support import create_test_app


def tiny_wav(seconds: float = 0.5, rate: int = 16_000, level: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = int(seconds * rate)
        out.writeframes(
            b"".join(
                int(level if (i // 20) % 2 else -level).to_bytes(
                    2, "little", signed=True
                )
                for i in range(frames)
            )
        )
    return buffer.getvalue()


def test_replies_are_cleaned_up_for_speaking():
    text = (
        "**Done.** See [the docs](https://x.test/a) and https://y.test/b [2].\n"
        "```python\nprint('hi')\n```\nThat's `all`."
    )
    assert speakable(text) == (
        "Done. See the docs and the link on screen. I've put the code on screen. "
        "That's all."
    )
    long = "One sentence here. " * 200
    cut = speakable(long, limit=100)
    assert len(cut) <= 100 and cut.endswith(".")


@pytest.mark.asyncio
async def test_a_voice_server_speaks_and_listens():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/audio/speech"):
            return httpx.Response(
                200, content=b"ID3mp3", headers={"content-type": "audio/mpeg"}
            )
        return httpx.Response(200, json={"text": "  status   report "})

    service = VoiceService(
        speak_url="http://tts.local/v1/",
        speak_key="k",
        voice="bm_lewis",
        listen_url="http://tts.local/v1",
        transport=httpx.MockTransport(handler),
    )

    speech = await service.speak("**Hello** there")
    heard = await service.transcribe(b"RIFFdata", content_type="audio/wav")

    assert (speech.audio, speech.content_type) == (b"ID3mp3", "audio/mpeg")
    body = json.loads(seen[0].content)
    assert body == {
        "model": "kokoro",
        "input": "Hello there",
        "voice": "bm_lewis",
        "response_format": "mp3",
    }
    assert seen[0].headers["authorization"] == "Bearer k"
    assert heard == "status report"
    assert seen[1].url.path == "/v1/audio/transcriptions"
    assert seen[1].headers["authorization"] == "Bearer k", "same server, same key"
    assert b'name="file"; filename="speech.wav"' in seen[1].content
    assert service.status()["speak"] == "server"


@pytest.mark.asyncio
async def test_voice_server_failures_are_explained():
    rejected = VoiceService(
        speak_url="http://tts.local/v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(401)),
    )
    with pytest.raises(VoiceError, match="rejected the key"):
        await rejected.speak("hi")
    with pytest.raises(VoiceError, match="No transcription server"):
        await rejected.transcribe(b"x", content_type="audio/wav")
    with pytest.raises(VoiceError, match="No speech server"):
        await VoiceService().speak("hi")


@pytest.mark.asyncio
async def test_the_built_in_voice_downloads_once_and_resumes(tmp_path, monkeypatch):
    model = b"M" * 3000
    voices = b"V" * 1000
    monkeypatch.setitem(local_voice.KOKORO_MODELS, "high", ("model.onnx", len(model)))
    monkeypatch.setattr(local_voice, "VOICES_FILE", ("voices.bin", len(voices)))
    monkeypatch.setattr(local_voice, "speech_package_ready", lambda: True)
    monkeypatch.setattr(local_voice, "listen_package_ready", lambda: False)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = model if request.url.path.endswith("model.onnx") else voices
        start = int(request.headers.get("range", "bytes=0-")[6:-1] or 0)
        if start:
            return httpx.Response(206, content=payload[start:])
        return httpx.Response(200, content=payload)

    voice = LocalVoice(tmp_path, transport=httpx.MockTransport(handler))
    (tmp_path / "model.onnx.part").write_bytes(model[:1200])
    assert voice.status()["download_bytes"] == len(model) + len(voices)
    updates: list[tuple[int, int, str]] = []

    async def progress(done: int, total: int, message: str) -> None:
        updates.append((done, total, message))

    state = SetupState(phase="running")
    await voice.setup(state, progress)

    assert state.errors == []
    assert (tmp_path / "model.onnx").read_bytes() == model
    assert (tmp_path / "voices.bin").read_bytes() == voices
    assert requests[0].headers["range"] == "bytes=1200-"
    assert updates[-1][0] == len(model) + len(voices) == updates[-1][1]
    assert voice.speech_files_ready() and voice.status()["download_bytes"] == 0

    requests.clear()
    await voice.setup(SetupState(phase="running"), progress)
    assert requests == [], "files already there are not downloaded again"


@pytest.mark.asyncio
async def test_a_truncated_download_is_reported(tmp_path, monkeypatch):
    monkeypatch.setitem(local_voice.KOKORO_MODELS, "high", ("model.onnx", 50))
    monkeypatch.setattr(local_voice, "VOICES_FILE", ("voices.bin", 10))
    monkeypatch.setattr(local_voice, "speech_package_ready", lambda: True)
    monkeypatch.setattr(local_voice, "listen_package_ready", lambda: False)
    voice = LocalVoice(
        tmp_path,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x")
        ),
    )
    state = SetupState()

    async def progress(done: int, total: int, message: str) -> None:
        return None

    await voice.setup(state, progress)

    assert "expected 50" in state.errors[0]
    assert not voice.speech_files_ready()
    with pytest.raises(LocalVoiceError, match="still downloading"):
        voice.synthesize("hello")


@pytest.mark.asyncio
async def test_studio_picks_the_built_in_voice_when_it_is_installed(
    make_studio, monkeypatch
):
    studio, _ = make_studio([])
    monkeypatch.setattr(service_module, "speech_package_ready", lambda: False)
    assert studio.voice_engines() == ("browser", "browser")

    monkeypatch.setattr(service_module, "speech_package_ready", lambda: True)
    monkeypatch.setattr(local_voice, "listen_package_ready", lambda: True)
    status = studio.voice_status()
    assert (status["speak"], status["listen"]) == ("builtin", "builtin")
    assert status["speak_ready"] is False
    assert status["setup"]["phase"] == "idle"
    assert status["builtin"]["voice"] == "jarvis"
    with pytest.raises(VoiceError, match="still downloading"):
        await studio.speak("hello")

    server, _ = make_studio(
        [],
        STUDIO_VOICE_ENGINE="server",
        STUDIO_VOICE_SPEAK_URL="http://tts.local/v1",
    )
    assert server.voice_engines() == ("server", "browser")
    assert server.voice().status()["voice"] == "bm_george", (
        "jarvis maps to a real voice"
    )
    browser, _ = make_studio([], STUDIO_VOICE_ENGINE="browser")
    assert browser.voice_engines() == ("browser", "browser")


@pytest.mark.asyncio
async def test_the_built_in_voice_speaks_and_hears(make_studio, monkeypatch):
    np = pytest.importorskip("numpy")
    studio, _ = make_studio([])
    monkeypatch.setattr(service_module, "speech_package_ready", lambda: True)
    monkeypatch.setattr(local_voice, "listen_package_ready", lambda: True)
    spoken: list[tuple[str, str]] = []

    class FakeKokoro:
        def get_voice_style(self, name):
            return np.full(4, 1.0 if name == "bm_george" else 3.0, dtype=np.float32)

        def create(self, text, *, voice, speed, lang):
            spoken.append((text, lang))
            assert np.allclose(voice, 0.6 * 1.0 + 0.4 * 3.0), "the Jarvis blend"
            assert speed == pytest.approx(1.05)
            t = np.arange(2400) / 24000
            return (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32), 24000

    class FakeWhisper:
        def transcribe(self, audio, **options):
            assert audio.dtype == np.float32 and audio.size == 8000
            assert options["language"] == "en"

            class Segment:
                text = " status report "

            return [Segment()], None

    monkeypatch.setattr(LocalVoice, "speech_files_ready", lambda self: True)
    monkeypatch.setattr(LocalVoice, "listen_files_ready", lambda self: True)
    monkeypatch.setattr(LocalVoice, "_speaker", lambda self: FakeKokoro())
    monkeypatch.setattr(LocalVoice, "_listener", lambda self: FakeWhisper())

    speech = await studio.speak("**Good evening.** See https://x.test")
    heard = await studio.transcribe(tiny_wav(), content_type="audio/wav")

    assert speech.content_type == "audio/wav"
    assert spoken == [("Good evening. See the link on screen", "en-gb")]
    with wave.open(io.BytesIO(speech.audio)) as audio:
        assert audio.getframerate() == 24000
        assert audio.getnframes() > 2400, "the room adds a short tail"
    assert heard == "status report"
    with pytest.raises(VoiceError, match="WAV"):
        await studio.transcribe(b"x", content_type="audio/mp4")


def test_the_jarvis_effect_adds_space_and_keeps_levels_safe():
    np = pytest.importorskip("numpy")
    rate = 24000
    t = np.arange(rate // 2) / rate
    dry = (0.9 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    wet = local_voice.jarvis_effect(dry, rate)

    assert wet.dtype == np.float32
    assert wet.size == dry.size + int(rate * 0.18)
    assert float(np.max(np.abs(wet))) == pytest.approx(0.89, abs=1e-3)
    assert float(np.max(np.abs(wet[dry.size :]))) > 0.01, "reflections ring on"
    assert local_voice.jarvis_effect(np.zeros(0, dtype=np.float32), rate).size == 0

    samples, got_rate = local_voice.read_wav(local_voice.wav_bytes(wet, rate))
    assert got_rate == rate and samples.size == wet.size
    halved = local_voice.resample(samples, rate, rate // 2)
    assert halved.size == samples.size // 2
    with pytest.raises(LocalVoiceError, match="not a WAV"):
        local_voice.read_wav(b"nope")


@pytest.mark.asyncio
async def test_voice_routes(make_studio, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/audio/speech"):
            return httpx.Response(
                200, content=b"ID3", headers={"content-type": "audio/mpeg"}
            )
        return httpx.Response(200, json={"text": "hello jarvis"})

    studio, _ = make_studio(
        [],
        STUDIO_VOICE_ENGINE="server",
        STUDIO_VOICE_SPEAK_URL="http://tts.local/v1",
        STUDIO_VOICE_LISTEN_URL="http://tts.local/v1",
        STUDIO_VOICE_SPEAK_KEY="secret-key",
    )
    studio._voice_transport = httpx.MockTransport(handler)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            status = (await client.get("/studio/api/voice")).json()
            assert (status["speak"], status["listen"]) == ("server", "server")
            assert "secret-key" not in json.dumps(status)
            console = (await client.get("/studio/api/main")).json()
            assert console["systems"]["voice"]["speak_ready"] is True

            spoken = await client.post("/studio/api/voice/speak", json={"text": "Hi."})
            assert spoken.status_code == 200
            assert spoken.headers["content-type"] == "audio/mpeg"
            assert spoken.content == b"ID3"

            heard = await client.post(
                "/studio/api/voice/transcribe",
                content=tiny_wav(),
                headers={"content-type": "audio/wav"},
            )
            assert heard.json() == {"text": "hello jarvis"}
            wrong = await client.post(
                "/studio/api/voice/transcribe",
                content=b"{}",
                headers={"content-type": "application/json"},
            )
            assert wrong.status_code == 415

            monkeypatch.setattr(service_module, "speech_package_ready", lambda: True)
            builtin = studio.settings.model_copy(
                update={"studio_voice_engine": "builtin"}
            )
            studio._settings_provider = lambda: builtin
            not_ready = await client.post(
                "/studio/api/voice/speak", json={"text": "Hi."}
            )
            assert not_ready.status_code == 409
            assert "still downloading" in not_ready.json()["detail"]
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
