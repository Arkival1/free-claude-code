from types import SimpleNamespace

import pytest

from free_claude_code.application.orb import OrbStudio
from free_claude_code.application.orb.ears import EarsError, LocalEars
from free_claude_code.application.orb.studio import is_local_model


class FakeWhisper:
    def __init__(self, path):
        self.path = path
        self.calls = 0

    def transcribe(self, audio, *, language, beam_size, vad_filter):
        self.calls += 1
        assert len(audio) == 16000 and language == "en" and vad_filter
        return iter(
            [SimpleNamespace(text=" What's the "), SimpleNamespace(text="weather? ")]
        ), None


def fake_download(size, output_dir):
    (__import__("pathlib").Path(output_dir) / "model.bin").write_bytes(b"x")
    return output_dir


def test_ears_download_once_and_transcribe_locally(tmp_path):
    models = []

    def factory(path):
        models.append(FakeWhisper(path))
        return models[-1]

    ears = LocalEars(
        tmp_path,
        downloader=fake_download,
        model_factory=factory,
        decoder=lambda audio: [0.0] * 16000,
    )
    with pytest.raises(EarsError, match="not downloaded"):
        ears.transcribe(b"webm-bytes")
    assert ears.start_download() is True
    ears.wait(5)
    assert ears.status()["ready"] and ears.start_download() is False
    assert ears.transcribe(b"webm-bytes") == "What's the weather?"
    ears.transcribe(b"webm-bytes")
    assert len(models) == 1 and models[0].calls == 2
    with pytest.raises(EarsError, match="No sound"):
        ears.transcribe(b"")
    with pytest.raises(EarsError, match="too long"):
        ears.transcribe(b"x" * (12 * 1024 * 1024 + 1))


def test_ears_download_failure_is_reported(tmp_path):
    def broken(size, output_dir):
        raise OSError("no internet")

    ears = LocalEars(tmp_path, downloader=broken, model_factory=FakeWhisper)
    ears.start_download()
    ears.wait(5)
    assert "no internet" in ears.status()["error"] and not ears.ready()


def test_local_only_is_default_and_blocks_api_advisors():
    assert is_local_model("lmstudio/qwen3.5-4b") and is_local_model("Ollama/llama3")
    assert not is_local_model("claude-sonnet") and not is_local_model("open_router/x")
    studio = OrbStudio(lambda: "http://127.0.0.1:1234/v1", toolbox_factory=lambda: None)
    assert studio.local_only is True
    with pytest.raises(ValueError, match="Local only is on"):
        studio.set_advisor("claude-sonnet")
    studio.set_advisor("lmstudio/qwen3.5-4b")
    assert studio.advisor_model == "lmstudio/qwen3.5-4b"
    studio.set_local_only(False)
    studio.set_advisor("claude-sonnet")
    assert studio.advisor_model == "claude-sonnet"
    studio.set_local_only(True)  # switching back on drops the API advisor
    assert studio.advisor_model is None and studio.status()["local_only"] is True


def test_decode_audio_reads_real_wav_and_rejects_junk():
    import io
    import wave

    import numpy as np

    from free_claude_code.application.orb.ears import decode_audio

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(24000)
        out.writeframes(
            (np.sin(np.linspace(0, 300, 24000)) * 9000).astype("<i2").tobytes()
        )
    samples = decode_audio(buffer.getvalue())
    assert abs(len(samples) - 16000) < 400 and samples.dtype == np.float32
    assert 0.2 < float(np.max(np.abs(samples))) < 0.3
    with pytest.raises(EarsError, match="could not be read"):
        decode_audio(b"not audio at all")
