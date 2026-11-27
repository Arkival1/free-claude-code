"""JARVIS's own voice: Kokoro (82M neural TTS) running offline on this PC.

The default "jarvis" voice is the original blend of two British men
(George 60%, Lewis 40%) with a light "AI in the room" treatment: a close
doubled copy for sheen and a few early reflections. The model files
(about 120 MB) download once into FCC's config folder, then it works offline.
"""

import io
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

KOKORO_BASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
)
MODEL_FILE = ("kokoro-v1.0.int8.onnx", 92_361_271)
VOICES_FILE = ("voices-v1.0.bin", 28_214_398)
JARVIS_BLEND: tuple[tuple[str, float], ...] = (("bm_george", 0.6), ("bm_lewis", 0.4))
VOICE_CHOICES: tuple[str, ...] = (
    "jarvis",
    "bm_george",
    "bm_lewis",
    "bm_daniel",
    "bm_fable",
    "am_michael",
    "am_adam",
    "bf_emma",
    "af_heart",
)
MAX_SPEAK_CHARS = 1500
_CHUNK = 1 << 16


class VoiceError(RuntimeError):
    """The offline voice is missing its files or could not speak."""


def jarvis_effect(audio: Any, rate: int) -> Any:
    """Composed, slightly synthetic presence in a small bright room."""
    import numpy as np

    x = np.asarray(audio, dtype=np.float32)
    if x.size == 0:
        return x

    def smooth(signal: Any, width: int) -> Any:
        width = max(1, width)
        return np.convolve(signal, np.ones(width, dtype=np.float32) / width, "same")

    def delayed(signal: Any, seconds: float, length: int) -> Any:
        shift = int(rate * seconds)
        out = np.zeros(length, dtype=np.float32)
        out[shift : shift + signal.size] = signal[: max(0, length - shift)]
        return out

    x = x - 0.7 * smooth(x, rate // 160)  # less boom below ~160 Hz
    x = x + 0.3 * (x - smooth(x, rate // 3500))  # crisper consonants
    length = x.size + int(rate * 0.18)
    dry = np.zeros(length, dtype=np.float32)
    dry[: x.size] = x
    sheen = 0.2 * delayed(x, 0.009, length) + 0.1 * delayed(x, 0.017, length)
    room_source = smooth(x, rate // 5000)
    room = sum(
        gain * delayed(room_source, seconds, length)
        for seconds, gain in (
            (0.031, 0.16),
            (0.047, 0.12),
            (0.071, 0.09),
            (0.097, 0.06),
            (0.131, 0.04),
        )
    )
    mixed = dry + sheen + room
    peak = float(np.max(np.abs(mixed))) or 1.0
    return (mixed * (0.89 / peak)).astype(np.float32)


def wav_bytes(audio: Any, rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype(
        "<i2"
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _default_kokoro(model: str, voices: str) -> Any:
    from kokoro_onnx import Kokoro

    return Kokoro(model, voices)


class JarvisVoice:
    """Download once, then speak offline."""

    def __init__(
        self,
        root: Path,
        *,
        http: httpx.Client | None = None,
        kokoro_factory: Callable[[str, str], Any] = _default_kokoro,
        base_url: str = KOKORO_BASE,
    ) -> None:
        self.root = root
        self.voice = "jarvis"
        self.speed = 1.0
        self.effect = True
        self._http = http
        self._factory = kokoro_factory
        self._base_url = base_url
        self._speaker: Any = None
        self._styles: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._speak_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.progress = 0.0
        self.message = ""
        self.error = ""

    # ---------- files ----------
    def _path(self, name: str) -> Path:
        return self.root / name

    def files_ready(self) -> bool:
        return all(
            self._path(name).is_file() and self._path(name).stat().st_size == size
            for name, size in (MODEL_FILE, VOICES_FILE)
        )

    @property
    def downloading(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.files_ready(),
            "downloading": self.downloading,
            "progress": round(self.progress, 3),
            "message": self.message,
            "error": self.error,
            "voice": self.voice,
            "speed": self.speed,
            "effect": self.effect,
            "voices": list(VOICE_CHOICES),
            "download_mb": round((MODEL_FILE[1] + VOICES_FILE[1]) / 1e6),
        }

    def start_download(self) -> bool:
        """Fetch the model files in the background. False if nothing to do."""
        with self._lock:
            if self.files_ready() or self.downloading:
                return False
            self.error = ""
            self._thread = threading.Thread(
                target=self._download_all, name="orb-voice-download", daemon=True
            )
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _download_all(self) -> None:
        total = MODEL_FILE[1] + VOICES_FILE[1]
        done = 0
        client = self._http or httpx.Client(
            timeout=httpx.Timeout(60.0, read=120.0), follow_redirects=True
        )
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            for name, size in (VOICES_FILE, MODEL_FILE):
                target = self._path(name)
                if target.is_file() and target.stat().st_size == size:
                    done += size
                    continue
                self.message = f"Downloading {name}"
                part = target.with_suffix(target.suffix + ".part")
                got = 0
                with (
                    client.stream("GET", self._base_url + name) as response,
                    part.open("wb") as out,
                ):
                    response.raise_for_status()
                    for chunk in response.iter_bytes(_CHUNK):
                        out.write(chunk)
                        got += len(chunk)
                        self.progress = (done + got) / total
                if got != size:
                    part.unlink(missing_ok=True)
                    raise VoiceError(f"{name} downloaded {got} bytes, expected {size}.")
                part.replace(target)
                done += size
            self.progress = 1.0
            self.message = "Jarvis's voice is ready. It now works offline."
        except (httpx.HTTPError, OSError, VoiceError) as exc:
            self.error = f"The voice download failed: {exc}. Try again later."
            self.message = ""

    # ---------- speaking ----------
    def configure(
        self,
        *,
        voice: str | None = None,
        speed: float | None = None,
        effect: bool | None = None,
    ) -> None:
        if voice is not None:
            if voice not in VOICE_CHOICES:
                raise VoiceError(
                    f"Unknown voice {voice!r}. Choose one of {list(VOICE_CHOICES)}."
                )
            self.voice = voice
        if speed is not None:
            self.speed = min(1.5, max(0.6, float(speed)))
        if effect is not None:
            self.effect = bool(effect)

    def _load(self) -> Any:
        if not self.files_ready():
            raise VoiceError(
                "Jarvis's voice is not downloaded yet."
                if not self.downloading
                else "Jarvis's voice is still downloading."
            )
        with self._lock:
            if self._speaker is None:
                self._speaker = self._factory(
                    str(self._path(MODEL_FILE[0])), str(self._path(VOICES_FILE[0]))
                )
            return self._speaker

    def _style(self, speaker: Any) -> Any:
        if self.voice != "jarvis":
            return self.voice
        style = self._styles.get("jarvis")
        if style is None:
            style = sum(
                weight * speaker.get_voice_style(name) for name, weight in JARVIS_BLEND
            )
            self._styles["jarvis"] = style
        return style

    def synthesize(self, text: str) -> bytes:
        cleaned = " ".join((text or "").split())[:MAX_SPEAK_CHARS]
        if not cleaned:
            raise VoiceError("There is nothing to say.")
        speaker = self._load()
        import numpy as np

        lang = (
            "en-gb" if self.voice == "jarvis" or self.voice.startswith("b") else "en-us"
        )
        with self._speak_lock:
            samples, rate = speaker.create(
                cleaned, voice=self._style(speaker), speed=self.speed, lang=lang
            )
        audio = np.asarray(samples, dtype=np.float32)
        if self.effect:
            audio = jarvis_effect(audio, rate)
        return wav_bytes(audio, rate)
