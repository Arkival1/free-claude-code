import io
import wave

import httpx
import numpy as np
import pytest

from free_claude_code.application.orb import voice as voice_mod
from free_claude_code.application.orb.voice import (
    JarvisVoice,
    VoiceError,
    jarvis_effect,
)


class FakeKokoro:
    def __init__(self, model, voices):
        self.paths = (model, voices)
        self.calls = []

    def get_voice_style(self, name):
        return np.full(4, {"bm_george": 1.0, "bm_lewis": 2.0}[name], dtype=np.float32)

    def create(self, text, *, voice, speed, lang):
        self.calls.append((text, voice, speed, lang))
        return np.sin(np.linspace(0, 200, 2400)).astype(np.float32) * 0.5, 24000


@pytest.fixture
def small_files(monkeypatch):
    monkeypatch.setattr(voice_mod, "MODEL_FILE", ("model.onnx", 10))
    monkeypatch.setattr(voice_mod, "VOICES_FILE", ("voices.bin", 6))


def serve(files):
    def handler(request):
        name = request.url.path.rsplit("/", 1)[-1]
        if name not in files:
            return httpx.Response(404)
        return httpx.Response(200, content=files[name])

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_downloads_once_then_speaks_with_the_jarvis_blend(tmp_path, small_files):
    made = []

    def factory(model, voices):
        made.append(FakeKokoro(model, voices))
        return made[-1]

    voice = JarvisVoice(
        tmp_path,
        http=serve({"model.onnx": b"m" * 10, "voices.bin": b"v" * 6}),
        kokoro_factory=factory,
        base_url="https://files.invalid/",
    )
    assert voice.status()["ready"] is False
    with pytest.raises(VoiceError, match="not downloaded"):
        voice.synthesize("hello")
    assert voice.start_download() is True
    voice.wait(10)
    assert voice.status()["ready"] and voice.status()["progress"] == 1.0
    assert voice.start_download() is False  # nothing left to fetch
    wav = voice.synthesize("  Good   evening, sir.  ")
    with wave.open(io.BytesIO(wav)) as audio:
        assert audio.getframerate() == 24000 and audio.getnchannels() == 1
    text, style, speed, lang = made[0].calls[0]
    assert text == "Good evening, sir." and lang == "en-gb" and speed == 1.0
    assert np.allclose(style, 0.6 * 1.0 + 0.4 * 2.0)  # 60% George + 40% Lewis
    voice.configure(voice="am_adam", speed=9, effect=False)
    voice.synthesize("hi")
    assert made[0].calls[-1][1:] == ("am_adam", 1.5, "en-us")
    assert len(made) == 1  # model loaded once
    with pytest.raises(VoiceError, match="Unknown voice"):
        voice.configure(voice="hal9000")


def test_short_or_failed_download_is_reported_and_retryable(tmp_path, small_files):
    voice = JarvisVoice(
        tmp_path,
        http=serve({"voices.bin": b"v" * 6, "model.onnx": b"m" * 3}),
        kokoro_factory=FakeKokoro,
        base_url="https://files.invalid/",
    )
    voice.start_download()
    voice.wait(10)
    assert "expected 10" in voice.status()["error"]
    assert not (tmp_path / "model.onnx").exists()
    assert (tmp_path / "voices.bin").is_file()  # the good file is kept
    voice._http = serve({"model.onnx": b"m" * 10})
    voice.start_download()
    voice.wait(10)
    assert voice.status()["ready"] and voice.status()["error"] == ""


def test_jarvis_effect_adds_room_tail_and_stays_in_range():
    rate = 24000
    dry = np.sin(np.linspace(0, 600, rate)).astype(np.float32)
    wet = jarvis_effect(dry, rate)
    assert wet.size == dry.size + int(rate * 0.18)
    assert float(np.max(np.abs(wet))) == pytest.approx(0.89, abs=1e-3)
    assert float(np.abs(wet[dry.size + 100 :]).max()) > 0  # reflections ring on
    assert jarvis_effect(np.zeros(0), rate).size == 0
