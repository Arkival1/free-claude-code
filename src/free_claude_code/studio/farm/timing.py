"""When each word is said, and which words share the screen.

The voice reads one scene at a time, so each scene's length is known; inside
a scene, a word takes time in proportion to its letters, which is close to
how speech runs. Captions show a few words at once and light up the one
being said, the way the big short-video accounts do.
"""

import io
import re
import wave
from dataclasses import dataclass
from pathlib import Path

from .formats import WORDS_PER_SECOND

GAP = 0.18
"""A breath between scenes, in seconds."""
MIN_SCENE = 1.6
CHUNK_WORDS = 3


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class Chunk:
    words: tuple[Word, ...]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


def reading_time(text: str) -> float:
    """How long a line takes to say when there is no voice to time it."""
    return max(MIN_SCENE, len(text.split()) / WORDS_PER_SECOND + 0.4)


def spread_words(text: str, start: float, length: float) -> tuple[Word, ...]:
    """Each word's start and end inside a scene of a known length."""
    words = text.split()
    if not words:
        return ()
    weights = [len(word) + 2 for word in words]
    total = sum(weights)
    timed: list[Word] = []
    at = start
    for word, weight in zip(words, weights, strict=True):
        span = length * weight / total
        timed.append(Word(word, round(at, 3), round(at + span, 3)))
        at += span
    return tuple(timed)


_BREAK = re.compile(r"[.!?,;:]$")


def chunks(words: tuple[Word, ...], size: int = CHUNK_WORDS) -> tuple[Chunk, ...]:
    """Words in screenfuls of up to `size`, never across a full stop or comma."""
    out: list[Chunk] = []
    current: list[Word] = []
    for word in words:
        current.append(word)
        if len(current) >= size or _BREAK.search(word.text):
            out.append(Chunk(tuple(current)))
            current = []
    if current:
        out.append(Chunk(tuple(current)))
    return tuple(out)


def wav_length(data: bytes) -> float:
    """Seconds of audio in a WAV file."""
    with wave.open(io.BytesIO(data)) as reader:
        rate = reader.getframerate() or 1
        return reader.getnframes() / rate


def join_wavs(parts: list[bytes], gaps: list[float]) -> bytes:
    """One WAV from many of the same format, with silence after each."""
    if not parts:
        raise ValueError("There is no audio to join.")
    out = io.BytesIO()
    with wave.open(io.BytesIO(parts[0])) as first:
        params = first.getparams()
    frame_bytes = params.sampwidth * params.nchannels
    with wave.open(out, "wb") as writer:
        writer.setnchannels(params.nchannels)
        writer.setsampwidth(params.sampwidth)
        writer.setframerate(params.framerate)
        for data, gap in zip(parts, gaps, strict=True):
            with wave.open(io.BytesIO(data)) as reader:
                if (reader.getframerate(), reader.getsampwidth()) != (
                    params.framerate,
                    params.sampwidth,
                ):
                    raise ValueError("The voice clips don't match.")
                writer.writeframes(reader.readframes(reader.getnframes()))
            writer.writeframes(b"\0" * frame_bytes * round(params.framerate * gap))
    return out.getvalue()


def silent_wav(seconds: float, rate: int = 24_000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\0\0" * round(rate * max(0.0, seconds)))
    return out.getvalue()


def write_joined(
    parts: list[Path | None], lengths: list[float], gap: float, out: Path
) -> None:
    """One WAV file from many, streamed, so two hours never sit in memory.

    A missing part (no voice) becomes silence of its scene's length.
    """
    rate, width, channels = 24_000, 2, 1
    for part in parts:
        if part is not None:
            with wave.open(str(part)) as reader:
                rate = reader.getframerate()
                width = reader.getsampwidth()
                channels = reader.getnchannels()
            break
    frame = width * channels
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        for part, length in zip(parts, lengths, strict=True):
            written = 0
            if part is not None:
                with wave.open(str(part)) as reader:
                    if (reader.getframerate(), reader.getsampwidth()) == (rate, width):
                        while chunk := reader.readframes(65_536):
                            writer.writeframes(chunk)
                            written += len(chunk) // frame
            missing = round(rate * length) - written
            if missing > 0:
                writer.writeframes(b"\0" * frame * missing)
            writer.writeframes(b"\0" * frame * round(rate * gap))
