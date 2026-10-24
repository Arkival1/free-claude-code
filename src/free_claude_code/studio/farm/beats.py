"""Hear a song's beat, and plan an edit that cuts on it.

The song is decoded with ffmpeg, then numpy finds where notes start (the
"onset" strength: how much louder each sliver of sound got, band by band),
the tempo (the gap the onsets repeat at), and every beat (a path through the
onsets that keeps to that tempo). Beats that start a bar are downbeats. Loud
parts get a cut on every beat, quieter ones every two or four, and the big
hits get a punch zoom and a flash, the way fan edits are cut.
"""

import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .render import _NO_WINDOW, find_ffmpeg

RATE = 22_050
HOP = 512
WINDOW = 2_048
MIN_BPM = 60
MAX_BPM = 200
MIN_CUT = 0.32
"""Shortest cut, in seconds: faster is a blur."""


class BeatError(RuntimeError):
    """The song couldn't be read."""


@dataclass(frozen=True, slots=True)
class Beats:
    tempo: float
    beats: tuple[float, ...]
    downbeats: tuple[float, ...]
    strength: tuple[float, ...]
    """How hard each beat hits, 0 to 1."""
    energy: tuple[float, ...]
    """How loud the music is around each beat, 0 to 1."""
    duration: float


@dataclass(frozen=True, slots=True)
class Cut:
    start: float
    end: float
    punch: bool = False
    """A zoom that settles, on a hard hit."""
    flash: bool = False
    shake: bool = False

    @property
    def length(self) -> float:
        return self.end - self.start


def numpy_ready() -> bool:
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def decode(
    path: Path, *, start: float = 0.0, length: float = 0.0, rate: int = RATE
) -> bytes:
    """The song as mono 16-bit samples at `rate`."""
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise BeatError("ffmpeg isn't installed (the studio_video extra).")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if start > 0:
        command += ["-ss", f"{start:.3f}"]
    command += ["-i", str(path)]
    if length > 0:
        command += ["-t", f"{length:.3f}"]
    command += ["-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            timeout=300,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BeatError(f"ffmpeg couldn't read the song: {error}") from error
    if done.returncode != 0 or not done.stdout:
        detail = done.stderr.decode("utf-8", "replace").strip()[-300:]
        raise BeatError(f"ffmpeg couldn't read the song: {detail or 'no sound in it'}")
    return done.stdout


def cut_song(
    path: Path, out: Path, *, start: float, length: float, fade: float = 0.6
) -> None:
    """The part of the song the edit uses, faded out at its end, as a WAV."""
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise BeatError("ffmpeg isn't installed (the studio_video extra).")
    fade = min(fade, length / 4)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{max(0.0, start):.3f}", "-i", str(path), "-t", f"{length:.3f}",
        "-vn", "-af", f"afade=t=in:d=0.02,afade=t=out:st={max(0.0, length - fade):.3f}:d={fade:.3f}",
        "-ac", "2", "-ar", "44100", str(out),
    ]  # fmt: skip
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            timeout=300,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BeatError(f"ffmpeg couldn't cut the song: {error}") from error
    if done.returncode != 0 or not out.is_file():
        detail = done.stderr.decode("utf-8", "replace").strip()[-300:]
        raise BeatError(f"ffmpeg couldn't cut the song: {detail or 'no reason'}")


def onsets(samples: bytes) -> tuple[list[float], list[float]]:
    """Onset strength and loudness per hop (HOP / RATE seconds each)."""
    if not numpy_ready():
        raise BeatError("Beat detection needs numpy (the studio_video extra).")
    import numpy as np

    signal = np.frombuffer(samples, dtype=np.int16).astype(np.float32) / 32768.0
    if signal.size < WINDOW * 4:
        raise BeatError("The song is too short to find a beat in.")
    frames = 1 + (signal.size - WINDOW) // HOP
    index = np.arange(WINDOW)[None, :] + HOP * np.arange(frames)[:, None]
    window = np.hanning(WINDOW).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(signal[index] * window, axis=1))
    # Mel-ish: only the bands where rhythm lives, compressed like ears hear.
    spectrum = np.log1p(1_000.0 * spectrum[:, : WINDOW // 4])
    flux = np.maximum(0.0, np.diff(spectrum, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    # Take away the slow swell so only the hits stand out.
    smooth = np.convolve(flux, np.ones(16) / 16, mode="same")
    strength = np.maximum(0.0, flux - smooth)
    peak = float(strength.max()) or 1.0
    loud = np.sqrt((signal[index] ** 2).mean(axis=1))
    loud_peak = float(np.percentile(loud, 98)) or 1.0
    return (strength / peak).tolist(), np.clip(loud / loud_peak, 0, 1).tolist()


def tempo_of(strength: list[float]) -> float:
    """Beats per minute: the lag the onsets repeat at, near 120 preferred."""
    import numpy as np

    envelope = np.asarray(strength, dtype=np.float64)
    envelope = envelope - envelope.mean()
    fps = RATE / HOP
    lags = np.arange(int(fps * 60 / MAX_BPM), int(fps * 60 / MIN_BPM) + 1)
    corr = np.array([float(np.dot(envelope[:-lag], envelope[lag:])) for lag in lags])
    bpm = 60.0 * fps / lags
    prior = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2)
    best = int(lags[int(np.argmax(corr * prior))])
    # A slow pick is often half the real tempo: the beats between the
    # strong ones are there too when the half lag still lines up well.
    half = best // 2
    if 60.0 * fps / best < 95 and half >= lags[0]:
        near = [lag for lag in range(half - 1, half + 2) if lags[0] <= lag <= lags[-1]]
        if near:
            strong = max(near, key=lambda lag: corr[lag - lags[0]])
            if corr[strong - lags[0]] >= 0.35 * corr[best - lags[0]]:
                best = strong
    return round(60.0 * fps / best, 2)


def track(
    strength: list[float], tempo: float, *, tightness: float = 100.0
) -> list[int]:
    """Beat frames: the path through the onsets that best keeps the tempo
    (dynamic programming, as in Ellis 2007)."""
    import numpy as np

    envelope = np.asarray(strength, dtype=np.float64)
    period = (RATE / HOP) * 60.0 / tempo
    score = envelope.copy()
    back = np.full(envelope.size, -1)
    low, high = round(period / 2), round(period * 2)
    for frame in range(low, envelope.size):
        start = max(0, frame - high)
        stop = frame - low
        if stop <= start:
            continue
        gaps = frame - np.arange(start, stop)
        penalty = -tightness * np.log(gaps / period) ** 2
        candidates = score[start:stop] + penalty
        best = int(np.argmax(candidates))
        score[frame] = envelope[frame] + candidates[best]
        back[frame] = start + best
    # End on the strongest beat in the last period, then walk back.
    tail = max(0, envelope.size - int(period))
    frame = tail + int(np.argmax(score[tail:]))
    path = [frame]
    while back[frame] >= 0:
        frame = int(back[frame])
        path.append(frame)
    path.reverse()
    return path


def analyse(path: Path, *, start: float = 0.0, length: float = 0.0) -> Beats:
    """Tempo, beats, downbeats, and loudness of a song (or part of one)."""
    samples = decode(path, start=start, length=length)
    strength, loud = onsets(samples)
    tempo = tempo_of(strength)
    frames = track(strength, tempo)
    seconds = HOP / RATE
    beats = [round(frame * seconds, 3) for frame in frames]
    hits = [strength[frame] for frame in frames]
    energy = [
        sum(loud[max(0, f - 4) : f + 5]) / len(loud[max(0, f - 4) : f + 5])
        for f in frames
    ]
    # The bar starts where every fourth beat hits hardest.
    phases = [sum(hits[phase::4]) for phase in range(4)] if len(hits) >= 8 else [1.0]
    phase = phases.index(max(phases))
    downbeats = beats[phase::4] if len(hits) >= 8 else beats[:1]
    return Beats(
        tempo=tempo,
        beats=tuple(beats),
        downbeats=tuple(downbeats),
        strength=tuple(round(h, 3) for h in hits),
        energy=tuple(round(e, 3) for e in energy),
        duration=round(len(samples) / 2 / RATE, 3),
    )


def best_window(beats: Beats, seconds: float) -> tuple[float, float]:
    """The loudest stretch of a song this long, starting on a downbeat (the
    chorus, usually), for an edit shorter than the song."""
    if beats.duration <= seconds + 1:
        return 0.0, beats.duration
    best, chosen = -1.0, 0.0
    for start in beats.downbeats or beats.beats:
        if start + seconds > beats.duration:
            break
        inside = [
            energy
            for beat, energy in zip(beats.beats, beats.energy, strict=True)
            if start <= beat < start + seconds
        ]
        level = sum(inside) / len(inside) if inside else 0.0
        if level > best:
            best, chosen = level, start
    return chosen, chosen + seconds


def plan_cuts(
    beats: Beats, *, start: float = 0.0, end: float = 0.0, pace: str = "auto"
) -> list[Cut]:
    """Where the edit cuts, between start and end (song seconds, made
    relative): every beat when the music is loud, every two when it's in
    between, every bar when it's quiet. pace fast or slow overrides that."""
    end = end or beats.duration
    downbeats = set(beats.downbeats)
    # Fast songs are cut on every other beat at most; slow ones on every beat.
    base = 2 if beats.tempo >= 100 else 1
    step_for = {"fast": base, "medium": base * 2, "slow": base * 4}
    marks: list[tuple[float, bool, float]] = []
    count = 0
    for beat, hit, energy in zip(
        beats.beats, beats.strength, beats.energy, strict=True
    ):
        if not start <= beat < end:
            continue
        step = step_for.get(pace) or (
            base if energy > 0.7 else base * 2 if energy > 0.35 else base * 4
        )
        if count % step == 0 or (beat in downbeats and step <= 2):
            marks.append((beat, beat in downbeats, hit))
        count += 1
    times = [start] + [beat for beat, _, _ in marks if beat - start >= MIN_CUT]
    cuts: list[Cut] = []
    hits = {beat: (down, hit) for beat, down, hit in marks}
    for here, after in zip(times, [*times[1:], end], strict=True):
        if after - here < MIN_CUT and cuts:
            previous = cuts[-1]
            cuts[-1] = Cut(
                previous.start,
                after - start,
                previous.punch,
                previous.flash,
                previous.shake,
            )
            continue
        down, hit = hits.get(here, (True, 1.0))
        cuts.append(
            Cut(
                start=round(here - start, 3),
                end=round(after - start, 3),
                # Punch in on the bar's big hits only: on every cut it's just noise.
                punch=(down and hit > 0.55) or hit > 0.92,
                flash=down and hit > 0.5,
                shake=hit > 0.9,
            )
        )
    return cuts


# ------------------------------------------------------------------ lyrics


@dataclass(frozen=True, slots=True)
class Sung:
    """One word of the lyrics and when it is sung (seconds into the edit)."""

    text: str
    start: float
    end: float


@dataclass(slots=True)
class Lyrics:
    words: list[Sung] = field(default_factory=list)
    big: list[Sung] = field(default_factory=list)
    """Words spelled out huge, letter by letter: the hook, names, shouts."""


def spread_lyrics(text: str, beats: Beats, *, start: float, end: float) -> list[Sung]:
    """Pasted lyrics with no timings: one word per beat, line by line, over
    the louder beats (a rough fit; Whisper timings are better)."""
    words = [word for line in text.splitlines() for word in line.split()]
    slots = [
        b - start
        for b, e in zip(beats.beats, beats.energy, strict=True)
        if start <= b < end and e > 0.25
    ]
    if not words or not slots:
        return []
    # Two words a beat when there are more words than beats.
    per = max(1, math.ceil(len(words) / len(slots)))
    sung: list[Sung] = []
    for number, word in enumerate(words):
        slot = number // per
        if slot >= len(slots):
            break
        here = slots[slot] + (number % per) * 0.5 * (60 / beats.tempo) / per * 2
        nxt = slots[slot + 1] if slot + 1 < len(slots) else here + 60 / beats.tempo
        sung.append(
            Sung(word, round(here, 3), round(min(nxt, here + 60 / beats.tempo), 3))
        )
    return sung


def align(heard: list[Sung], text: str) -> list[Sung]:
    """Whisper's timings with the pasted lyrics' spelling."""
    import difflib

    written = [word for line in text.splitlines() for word in line.split()]
    if not written:
        return heard
    key = [w.text.lower().strip(".,!?'\"") for w in heard]
    want = [w.lower().strip(".,!?'\"") for w in written]
    matcher = difflib.SequenceMatcher(a=key, b=want, autojunk=False)
    out: list[Sung] = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and a1 - a0 == b1 - b0):
            out += [
                Sung(written[b0 + i], heard[a0 + i].start, heard[a0 + i].end)
                for i in range(a1 - a0)
            ]
        elif tag == "replace" and a1 > a0:
            span = (heard[a1 - 1].end - heard[a0].start) / max(1, b1 - b0)
            out += [
                Sung(
                    written[b0 + i],
                    round(heard[a0].start + i * span, 3),
                    round(heard[a0].start + (i + 1) * span, 3),
                )
                for i in range(b1 - b0)
            ]
        elif tag == "delete":
            out += heard[a0:a1]
    return out


def pick_big(words: list[Sung], chosen: list[str] | None = None) -> list[Sung]:
    """Which words go huge: the ones asked for, else repeated and long ones,
    names, and shouts, never two at once."""
    if not words:
        return []
    clean = [w.text.strip(".,?'\"").upper() for w in words]
    counts: dict[str, int] = {}
    for word in clean:
        counts[word] = counts.get(word, 0) + 1
    wanted = {w.upper().strip() for w in (chosen or []) if w.strip()}
    big: list[Sung] = []
    last_end = -1.0
    for word, sung in zip(clean, words, strict=True):
        letters = word.strip("!")
        score = (
            3
            if word in wanted
            else 2
            if counts[word] >= 3 and len(letters) >= 3
            else 2
            if sung.text[:1].isupper() and len(letters) >= 4 and sung is not words[0]
            else 1
            if word.endswith("!") or len(letters) >= 7
            else 0
        )
        if score >= (3 if wanted else 2) and sung.start >= last_end:
            end = max(sung.end, sung.start + 0.6)
            big.append(Sung(word, sung.start, round(end, 3)))
            last_end = end
    return big
