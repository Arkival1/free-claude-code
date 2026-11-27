"""JARVIS's ears: Whisper (faster-whisper) running on this PC.

Your voice is recorded in the orb window and turned into text here, on your
own processor. Nothing is sent to Microsoft, Google or anyone else. The model
(base.en, about 145 MB) downloads once into FCC's config folder.
"""

import io
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

WHISPER_SIZE = "base.en"
MAX_AUDIO_BYTES = 12 * 1024 * 1024
DOWNLOAD_MB = 145


class EarsError(RuntimeError):
    """The offline ears are missing their model or could not understand audio."""


def _default_download(size: str, output_dir: str) -> str:
    from faster_whisper import download_model

    return download_model(size, output_dir=output_dir)


def decode_audio(audio: bytes, rate: int = 16_000) -> Any:
    """Any common recording (webm/opus, wav, ogg...) to mono 16 kHz float samples."""
    import av
    import numpy as np

    pieces = []
    try:
        with av.open(io.BytesIO(audio), mode="r") as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
            for frame in container.decode(audio=0):
                pieces.extend(f.to_ndarray() for f in resampler.resample(frame))
            pieces.extend(f.to_ndarray() for f in resampler.resample(None))
    except (av.FFmpegError, ValueError, IndexError) as exc:
        raise EarsError(f"That recording could not be read: {exc}") from exc
    if not pieces:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(pieces, axis=1).reshape(-1).astype(np.float32) / 32768.0


def _default_model(path: str) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(path, device="cpu", compute_type="int8")


class LocalEars:
    def __init__(
        self,
        root: Path,
        *,
        size: str = WHISPER_SIZE,
        downloader: Callable[[str, str], str] = _default_download,
        model_factory: Callable[[str], Any] = _default_model,
        decoder: Callable[[bytes], Any] = decode_audio,
    ) -> None:
        self.root = root
        self.size = size
        self._downloader = downloader
        self._factory = model_factory
        self._decode = decoder
        self._model: Any = None
        self._lock = threading.Lock()
        self._listen_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.error = ""

    @property
    def model_dir(self) -> Path:
        return self.root / self.size

    def ready(self) -> bool:
        return (self.model_dir / "model.bin").is_file()

    @property
    def downloading(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.ready(),
            "downloading": self.downloading,
            "error": self.error,
            "model": self.size,
            "download_mb": DOWNLOAD_MB,
        }

    def start_download(self) -> bool:
        with self._lock:
            if self.ready() or self.downloading:
                return False
            self.error = ""
            self._thread = threading.Thread(
                target=self._download, name="orb-ears-download", daemon=True
            )
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _download(self) -> None:
        try:
            self.model_dir.mkdir(parents=True, exist_ok=True)
            self._downloader(self.size, str(self.model_dir))
            if not self.ready():
                raise EarsError("the model files did not arrive")
        except Exception as exc:  # network, disk or hub errors all mean "try later"
            self.error = f"The ears download failed: {exc}. Try again later."

    def transcribe(self, audio: bytes) -> str:
        """Audio in any common format (webm/opus, wav...) to English text."""
        if not audio:
            raise EarsError("No sound was recorded.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise EarsError("That recording is too long. Keep it under a minute.")
        if not self.ready():
            raise EarsError(
                "JARVIS's ears are still downloading."
                if self.downloading
                else "JARVIS's ears are not downloaded yet."
            )
        with self._lock:
            if self._model is None:
                self._model = self._factory(str(self.model_dir))
            model = self._model
        samples = self._decode(audio)
        if len(samples) < 1600:  # under 0.1 s: nothing was said
            return ""
        try:
            with self._listen_lock:
                segments, _info = model.transcribe(
                    samples, language="en", beam_size=1, vad_filter=True
                )
                text = " ".join(segment.text.strip() for segment in segments)
        except EarsError:
            raise
        except Exception as exc:
            raise EarsError(f"Could not understand that recording: {exc}") from exc
        return " ".join(text.split())
