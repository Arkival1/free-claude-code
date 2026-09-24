"""The main AI's built-in voice and ears: runs on this PC, no server, offline.

Speech is Kokoro (an 82M-parameter neural voice) through ONNX Runtime; hearing
is Whisper through faster-whisper. Both download their model files once, then
never need the internet again. The default voice blends two of Kokoro's
British men and adds a light "AI in the room" treatment: a synthetic double
and a short, bright room.
"""

import importlib.util
import io
import threading
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio.to_thread
import httpx

from free_claude_code.core.json_types import JsonObject

KOKORO_BASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
)
KOKORO_MODELS = {
    "high": ("kokoro-v1.0.onnx", 325_532_387),
    "compact": ("kokoro-v1.0.int8.onnx", 92_361_271),
}
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
WHISPER_SIZES = ("tiny.en", "base.en", "small.en", "medium.en")
LISTEN_RATE = 16_000
MAX_SPEAK_CHARS = 1_500
_CHUNK = 1 << 16
_LOCK = threading.Lock()
_SPEAKERS: dict[str, Any] = {}
_LISTENERS: dict[str, Any] = {}

type ProgressFn = Callable[[int, int, str], Awaitable[None]]


class LocalVoiceError(RuntimeError):
    """Raised when the built-in voice is missing a package or its files."""


def speech_package_ready() -> bool:
    """Whether the Kokoro package is installed in this Python."""
    return importlib.util.find_spec("kokoro_onnx") is not None


def listen_package_ready() -> bool:
    """Whether faster-whisper is installed in this Python."""
    return importlib.util.find_spec("faster_whisper") is not None


@dataclass(slots=True)
class SetupState:
    """Progress of the one-time voice download."""

    phase: str = "idle"
    done: int = 0
    total: int = 0
    message: str = ""
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> JsonObject:
        return {
            "phase": self.phase,
            "done": self.done,
            "total": self.total,
            "progress": round(self.done / self.total, 3) if self.total else 0.0,
            "message": self.message,
            "errors": list(self.errors),
        }


def jarvis_effect(audio: Any, rate: int) -> Any:
    """Give a dry voice a composed, slightly synthetic presence in a room.

    Everything is a feed-forward filter, so it is vectorized and cheap:
    trim rumble, lift the consonants, add a close doubled copy for sheen, and
    a handful of early reflections for space. Output is peak-normalized.
    """
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
    tail = int(rate * 0.18)
    length = x.size + tail
    dry = np.zeros(length, dtype=np.float32)
    dry[: x.size] = x
    sheen = 0.2 * delayed(x, 0.009, length) + 0.1 * delayed(x, 0.017, length)
    room_source = smooth(x, rate // 5000)  # reflections are a touch darker
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
    """Encode mono float samples as 16-bit PCM WAV."""
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


def read_wav(data: bytes) -> tuple[Any, int]:
    """Decode a 16-bit PCM WAV into mono float samples."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())
    except (wave.Error, EOFError) as error:
        raise LocalVoiceError(f"The recording is not a WAV file: {error}") from error
    if width != 2:
        raise LocalVoiceError("The recording must be 16-bit PCM.")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def resample(samples: Any, rate: int, target: int) -> Any:
    """Linear resampling, plenty for speech recognition."""
    import numpy as np

    if rate == target or samples.size == 0:
        return samples.astype(np.float32)
    count = int(samples.size * target / rate)
    positions = np.linspace(0, samples.size - 1, count)
    return np.interp(positions, np.arange(samples.size), samples).astype(np.float32)


class LocalVoice:
    """Speak and listen with models stored under one folder on this PC."""

    def __init__(
        self,
        root: Path,
        *,
        quality: str = "high",
        voice: str = "jarvis",
        speed: float = 1.0,
        effect: str = "jarvis",
        whisper_size: str = "base.en",
        language: str = "en",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._root = root
        self._model_name, self._model_size = KOKORO_MODELS.get(
            quality, KOKORO_MODELS["high"]
        )
        self._voice = voice or "jarvis"
        self._speed = min(1.6, max(0.6, speed))
        self._effect = effect
        self._whisper_size = (
            whisper_size if whisper_size in WHISPER_SIZES else "base.en"
        )
        self._language = language
        self._transport = transport

    # ------------------------------------------------------------------ files

    @property
    def model_path(self) -> Path:
        return self._root / self._model_name

    @property
    def voices_path(self) -> Path:
        return self._root / VOICES_FILE[0]

    @property
    def whisper_root(self) -> Path:
        return self._root / "whisper"

    def speech_files_ready(self) -> bool:
        return (
            self.model_path.is_file()
            and self.model_path.stat().st_size == self._model_size
            and self.voices_path.is_file()
            and self.voices_path.stat().st_size == VOICES_FILE[1]
        )

    def listen_files_ready(self) -> bool:
        folder = (
            self.whisper_root / f"models--Systran--faster-whisper-{self._whisper_size}"
        )
        return any(folder.glob("snapshots/*/model.bin"))

    def speech_ready(self) -> bool:
        return speech_package_ready() and self.speech_files_ready()

    def listen_ready(self) -> bool:
        return listen_package_ready() and self.listen_files_ready()

    def status(self) -> JsonObject:
        return {
            "speech_package": speech_package_ready(),
            "listen_package": listen_package_ready(),
            "speech_ready": self.speech_ready(),
            "listen_ready": self.listen_ready(),
            "voice": self._voice,
            "effect": self._effect,
            "whisper": self._whisper_size,
            "download_bytes": self._missing_bytes(),
        }

    def _missing_bytes(self) -> int:
        missing = 0
        for path, size in (
            (self.model_path, self._model_size),
            (self.voices_path, VOICES_FILE[1]),
        ):
            have = path.stat().st_size if path.is_file() else 0
            missing += max(0, size - have)
        return missing

    async def setup(self, state: SetupState, progress: ProgressFn) -> None:
        """Download whatever is missing: the voice, then the ears."""
        state.errors.clear()
        if speech_package_ready():
            files = [
                (self.model_path, self._model_size),
                (self.voices_path, VOICES_FILE[1]),
            ]
            state.total = sum(size for _, size in files)
            done = sum(
                size
                for path, size in files
                if path.is_file() and path.stat().st_size == size
            )
            for path, size in files:
                if path.is_file() and path.stat().st_size == size:
                    continue
                base = done

                async def report(got: int, base: int = base) -> None:
                    await progress(base + got, state.total, "Downloading the voice")

                try:
                    await self._download(
                        f"{KOKORO_BASE}{path.name}", path, size, report
                    )
                except (httpx.HTTPError, OSError, LocalVoiceError) as error:
                    state.errors.append(f"Voice download failed: {error}")
                    break
                done += size
        else:
            state.errors.append(
                "The voice package is not installed (install the studio_voice extra)."
            )
        if listen_package_ready():
            await progress(state.done, state.total, "Downloading speech recognition")
            try:
                await anyio.to_thread.run_sync(self._listener)
            except Exception as error:  # faster-whisper raises many kinds
                state.errors.append(f"Speech recognition download failed: {error}")

    async def _download(
        self,
        url: str,
        target: Path,
        size: int,
        report: Callable[[int], Awaitable[None]],
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f"{target.name}.part")
        have = partial.stat().st_size if partial.is_file() else 0
        headers = {"range": f"bytes={have}-"} if have else {}
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, read=120.0),
                follow_redirects=True,
                transport=self._transport,
            ) as client,
            client.stream("GET", url, headers=headers) as response,
        ):
            if response.status_code == 200:
                have = 0
            elif response.status_code != 206:
                response.raise_for_status()
            mode = "ab" if have else "wb"
            handle = await anyio.to_thread.run_sync(lambda: partial.open(mode))
            try:
                async for chunk in response.aiter_bytes(_CHUNK):
                    await anyio.to_thread.run_sync(handle.write, chunk)
                    have += len(chunk)
                    await report(have)
            finally:
                await anyio.to_thread.run_sync(handle.close)
        if partial.stat().st_size != size:
            raise LocalVoiceError(
                f"{target.name} is {partial.stat().st_size} bytes, expected {size}."
            )
        partial.replace(target)

    # ------------------------------------------------------------------ voice

    def _speaker(self) -> Any:
        if not speech_package_ready():
            raise LocalVoiceError(
                "Install the studio_voice extra for the built-in voice."
            )
        if not self.speech_files_ready():
            raise LocalVoiceError("The voice is still downloading.")
        key = str(self.model_path)
        with _LOCK:
            speaker = _SPEAKERS.get(key)
            if speaker is None:
                from kokoro_onnx import Kokoro

                speaker = Kokoro(str(self.model_path), str(self.voices_path))
                _SPEAKERS[key] = speaker
        return speaker

    def _style(self, speaker: Any) -> Any:
        if self._voice != "jarvis":
            return self._voice
        return sum(
            weight * speaker.get_voice_style(name) for name, weight in JARVIS_BLEND
        )

    def synthesize(self, text: str) -> bytes:
        """Speak one piece of text and return it as WAV (runs on a thread)."""
        cleaned = " ".join(text.split())[:MAX_SPEAK_CHARS]
        if not cleaned:
            raise LocalVoiceError("There is nothing to say.")
        # Check the voice is installed and downloaded before touching numpy,
        # so a missing voice says so instead of failing on an import.
        speaker = self._speaker()
        import numpy as np

        language = (
            "en-gb"
            if self._voice == "jarvis" or self._voice.startswith("b")
            else "en-us"
        )
        samples, rate = speaker.create(
            cleaned, voice=self._style(speaker), speed=self._speed, lang=language
        )
        audio = np.asarray(samples, dtype=np.float32)
        if self._effect == "jarvis":
            audio = jarvis_effect(audio, rate)
        return wav_bytes(audio, rate)

    async def speak(self, text: str) -> bytes:
        return await anyio.to_thread.run_sync(lambda: self.synthesize(text))

    # ------------------------------------------------------------------ ears

    def _listener(self) -> Any:
        if not listen_package_ready():
            raise LocalVoiceError("Install the studio_voice extra to talk to the AI.")
        key = f"{self.whisper_root}:{self._whisper_size}"
        with _LOCK:
            listener = _LISTENERS.get(key)
            if listener is None:
                from faster_whisper import WhisperModel

                local = self.listen_files_ready()
                listener = WhisperModel(
                    self._whisper_size,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(self.whisper_root),
                    local_files_only=local,
                )
                _LISTENERS[key] = listener
        return listener

    def recognize(self, wav: bytes) -> str:
        """Turn a WAV recording into text (runs on a thread)."""
        samples, rate = read_wav(wav)
        audio = resample(samples, rate, LISTEN_RATE)
        if audio.size < LISTEN_RATE // 4:
            return ""
        listener = self._listener()
        segments, _ = listener.transcribe(
            audio,
            language=self._language or None,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    async def transcribe(self, wav: bytes) -> str:
        return await anyio.to_thread.run_sync(lambda: self.recognize(wav))
