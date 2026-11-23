"""TODO 40-3: sound effects made by code (쿵·뿅·휙·띵·띠용·찰칵) and mixed into the finished video.

No downloads and no files kept: each render writes the sounds it needs into its temporary folder. A sound is mixed
``BELOW_SPEECH_DB`` under the video's measured speech level, so it never drowns the spoken lines. The audio fades
between cuts (TODO 38) are left as they are; only the finished track gets the extra sounds on top.
"""

from __future__ import annotations

import math
import random
import subprocess
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Sequence

RATE = 48_000
NAMES: tuple[str, ...] = ("쿵", "뿅", "휙", "띵", "띠용", "찰칵")
BELOW_SPEECH_DB = 8.0
QUIET_SPEECH_DB = -50.0  # below this the video has no real speech; sounds use MIN_DB
MIN_DB = -20.0  # quiet recordings (학원 하루 speech -33.9 dB) made "8 dB under" too faint; never below this (picked by ear)
PEAK = 0.9

def _sweep(frequency: Callable[[float], float], seconds: float) -> list[float]:
    """Phase of a tone whose pitch follows ``frequency(t)``."""
    phase, out = 0.0, []
    for index in range(int(seconds * RATE)):
        out.append(phase)
        phase += 2 * math.pi * frequency(index / RATE) / RATE
    return out

def _thud() -> list[float]:  # 쿵: a low drop that dies fast, with a soft knock at the start
    seconds, noise = 0.55, random.Random(1)
    phases = _sweep(lambda t: 45 + 110 * math.exp(-t * 9), seconds)
    knock, out = 0.0, []
    for index, phase in enumerate(phases):
        t = index / RATE
        knock += 0.15 * (noise.uniform(-1, 1) - knock)
        out.append(math.sin(phase) * math.exp(-t * 7) + knock * 2.5 * math.exp(-t * 90))
    return out

def _pop() -> list[float]:  # 뿅: a quick upward blip
    seconds = 0.22
    phases = _sweep(lambda t: 500 * (1600 / 500) ** min(t / 0.14, 1.0), seconds)
    return [(math.sin(p) + 0.3 * math.sin(3 * p)) * min(1.0, (i / RATE) / 0.005) * math.exp(-(i / RATE) * 14)
            for i, p in enumerate(phases)]

def _whoosh() -> list[float]:  # 휙: air passing by, its brightness rising then falling
    seconds, noise = 0.38, random.Random(2)
    low, out = 0.0, []
    for index in range(int(seconds * RATE)):
        t = index / seconds / RATE
        cutoff = 600 + 3400 * math.sin(math.pi * t) ** 2
        low += (1 - math.exp(-2 * math.pi * cutoff / RATE)) * (noise.uniform(-1, 1) - low)
        out.append(low * math.sin(math.pi * t) ** 2)
    return out

def _ding() -> list[float]:  # 띵: a small bell (partials 1 : 2.76 : 5.4 dying at different speeds)
    seconds, base = 1.0, 1568.0
    out = []
    for index in range(int(seconds * RATE)):
        t = index / RATE
        out.append(min(1.0, t / 0.002) * (math.sin(2 * math.pi * base * t) * math.exp(-t * 4)
                                          + 0.45 * math.sin(2 * math.pi * base * 2.76 * t) * math.exp(-t * 9)
                                          + 0.2 * math.sin(2 * math.pi * base * 5.4 * t) * math.exp(-t * 16)))
    return out

def _boing() -> list[float]:  # 띠용: a spring wobbling down
    seconds = 0.7
    phases = _sweep(lambda t: 330 * (1 - 0.4 * t / seconds) * (1 + 0.08 * math.sin(2 * math.pi * 11 * t)), seconds)
    return [(math.sin(p) + 0.35 * math.sin(2 * p)) * min(1.0, (i / RATE) / 0.004) * math.exp(-(i / RATE) * 3.2)
            for i, p in enumerate(phases)]

def _shutter() -> list[float]:  # 찰칵: two bright clicks, like a camera shutter opening and closing
    seconds, noise = 0.16, random.Random(3)
    out, last = [], 0.0
    for index in range(int(seconds * RATE)):
        t = index / RATE
        sample = noise.uniform(-1, 1)
        bright, last = sample - last, sample  # a rough high-pass: only the hiss is left
        envelope = math.exp(-t * 260) + 0.8 * (math.exp(-(t - 0.07) * 220) if t >= 0.07 else 0.0)
        out.append(bright * envelope + 0.3 * math.sin(2 * math.pi * 3200 * t) * envelope)
    return out

_MAKERS: dict[str, Callable[[], list[float]]] = {
    "쿵": _thud, "뿅": _pop, "휙": _whoosh, "띵": _ding, "띠용": _boing, "찰칵": _shutter,
}
_FILE_NAMES = {"쿵": "thud", "뿅": "pop", "휙": "whoosh", "띵": "ding", "띠용": "boing", "찰칵": "shutter"}

@dataclass(frozen=True)
class Sound:
    name: str
    samples: tuple[float, ...]  # peak = PEAK
    level_db: float  # RMS of the part you hear (samples above a tenth of the peak's envelope)

    @property
    def seconds(self) -> float:
        return len(self.samples) / RATE

def _db(value: float) -> float:
    return 20 * math.log10(max(value, 1e-9))

def make(name: str) -> Sound:
    raw = _MAKERS[name]()
    top = max(abs(sample) for sample in raw) or 1.0
    samples = [PEAK * sample / top for sample in raw]
    # Level of the audible body: 10 ms blocks louder than 1/10 of the loudest block.
    block = RATE // 100
    powers = [sum(s * s for s in samples[i:i + block]) / len(samples[i:i + block])
              for i in range(0, len(samples), block)]
    loud = [power for power in powers if power >= max(powers) / 100]
    return Sound(name, tuple(samples), round(_db(math.sqrt(sum(loud) / len(loud))), 2))

def write_wav(sound: Sound, path: Path) -> Path:
    data = array("h", (int(max(-1.0, min(1.0, sample)) * 32767) for sample in sound.samples))
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(data.tobytes())
    return path

def file_name(name: str) -> str:
    return f"sfx-{_FILE_NAMES[name]}.wav"

# --- mixing ----------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SoundEvent:
    name: str
    at: float  # seconds on the finished video

class SoundMixError(RuntimeError):
    pass

SPEECH_RATE = 8_000

def body_level(powers: Sequence[float]) -> float | None:
    """RMS (dBFS) of the audible part: 10 ms blocks within 20 dB of the loud end (95th percentile block), so pauses
    between lines do not pull the level down (학원 하루: plain mean -35.8 dB, speaking parts -33.9 dB)."""
    if not powers:
        return None
    ordered = sorted(powers)
    reference = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    loud = [power for power in powers if power >= reference / 100]
    return round(_db(math.sqrt(sum(loud) / len(loud))), 2) if loud and reference > 0 else None

def speech_level(video: Path, executable: str = "ffmpeg",
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> float | None:
    """Loudness (RMS, dBFS) of the speaking parts of the video's audio, or None when it cannot be measured.
    Measured the same way as each sound's level, so "8 dB under the speech" means what you hear."""
    try:
        result = run([executable, "-v", "error", "-nostdin", "-i", str(video), "-map", "0:a:0", "-ac", "1",
                      "-ar", str(SPEECH_RATE), "-f", "s16le", "-"], capture_output=True, check=False)
    except OSError:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    data = array("h")
    data.frombytes(result.stdout[:len(result.stdout) // 2 * 2])
    block = SPEECH_RATE // 100
    powers = []
    for start in range(0, len(data) - block + 1, block):
        chunk = data[start:start + block]
        powers.append(sum(value * value for value in chunk) / (block * 32768.0 ** 2))
    return body_level(powers)

def gain_for(sound: Sound, speech_db: float | None) -> float:
    """dB to add so the sound sits BELOW_SPEECH_DB under the speech (never below MIN_DB)."""
    target = speech_db - BELOW_SPEECH_DB if speech_db is not None and speech_db > QUIET_SPEECH_DB else MIN_DB
    target = max(target, MIN_DB)
    return round(min(target - sound.level_db, -_db(PEAK) - 1.0), 2)  # never past -1 dBFS at the peak

def mix_filter(events: Sequence[SoundEvent], gains: dict[str, float]) -> tuple[list[str], str]:
    """Inputs (sound names in input order, input 0 = the video) and the filter graph ending in ``[a]``."""
    names = list(dict.fromkeys(event.name for event in events))
    parts, labels = [], []
    for input_index, name in enumerate(names, start=1):
        times = [event.at for event in events if event.name == name]
        split = f"asplit={len(times)}" + "".join(f"[s{input_index}_{k}]" for k in range(len(times)))
        parts.append(f"[{input_index}:a]aformat=sample_rates={RATE}:channel_layouts=stereo,"
                     f"volume={gains[name]:.2f}dB,{split}")
        for k, at in enumerate(times):
            label = f"d{input_index}_{k}"
            parts.append(f"[s{input_index}_{k}]adelay={round(at * 1000)}:all=1[{label}]")
            labels.append(f"[{label}]")
    parts.append(f"[0:a]{''.join(labels)}amix=inputs={len(labels) + 1}:duration=first:dropout_transition=0:"
                 "normalize=0[a]")
    return names, ";".join(parts)

def mix_sounds(video: Path, events: Sequence[SoundEvent], executable: str = "ffmpeg",
               run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict[str, float]:
    """Mix ``events`` into ``video`` in place (picture copied, length unchanged). Returns the gain used per sound."""
    video = Path(video)
    if not events:
        return {}
    speech_db = speech_level(video, executable, run)
    with TemporaryDirectory(prefix="cut-sounds-", dir=video.parent) as directory:
        stage = Path(directory)
        sounds = {event.name: make(event.name) for event in events}
        gains = {name: gain_for(sound, speech_db) for name, sound in sounds.items()}
        names, graph = mix_filter(events, gains)
        command = [executable, "-v", "error", "-nostdin", "-y", "-i", str(video.resolve())]
        for name in names:
            command.extend(["-i", write_wav(sounds[name], stage / file_name(name)).name])
        output = stage / "output.mp4"
        command.extend(["-filter_complex", graph, "-map", "0:v:0", "-map", "[a]", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", output.name])
        try:
            result = run(command, cwd=stage, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         check=False)
        except OSError as error:
            raise SoundMixError(str(error)) from error
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            raise SoundMixError((result.stderr or "")[-800:])
        output.replace(video)
    return gains
