"""TODO 24: "이건 내 목소리" — tell my lines from other people's by voice (WeSpeaker ResNet34, onnx, local).

The user marks one or more transcript lines as their own voice. Their voice prints are averaged into one
"my voice" print. The voice step then scores every transcript line by how close it sounds to that print.
Everything is kept as small files next to the project's outputs (no database change):

  outputs/projects/<id>/my_voice.json            registered lines + their voice prints
  outputs/projects/<id>/speaker/<source_id>.json one score per transcript line, tagged with the voice version
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import UUID

import numpy as np

SAMPLE_RATE = 16000
MIN_LINE_SECONDS = 1.6  # shorter lines are widened around their middle before listening
MIN_FRAMES = 50  # ~0.5 s of speech; below this the line is "모름"
# score ≥ this → "나" (cosine similarity to my averaged voice print). Academy-day check (1 / 3 registered lines):
# 0.30 caught 58% / 73% of my lines while marking 0% / 1% of other people's lines as mine; 0.45 caught only 13% / 30%.
MY_VOICE_THRESHOLD = 0.30
MAX_SAMPLES = 10
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[3] / "assets" / "models" / "wespeaker_resnet34.onnx"


class SpeakerVoiceError(RuntimeError):
    pass


# ---------- voice prints ----------

def _mel_bank(n_fft: int = 512, n_mels: int = 80, lo: float = 20.0, hi: float = 8000.0) -> np.ndarray:
    def mel(f):
        return 1127.0 * np.log(1.0 + f / 700.0)

    points = np.linspace(mel(lo), mel(hi), n_mels + 2)
    fft_mel = mel(np.arange(n_fft // 2 + 1) * SAMPLE_RATE / n_fft)
    bank = np.zeros((n_mels, n_fft // 2 + 1), np.float32)
    for i in range(n_mels):
        left, center, right = points[i], points[i + 1], points[i + 2]
        bank[i] = np.maximum(0, np.minimum((fft_mel - left) / (center - left), (right - fft_mel) / (right - center)))
    return bank


_BANK = _mel_bank()
_WINDOW = np.power(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(400) / 399), 0.85).astype(np.float32)  # povey


def fbank(samples: np.ndarray) -> np.ndarray | None:
    """Kaldi-style 80-band log-mel features (25 ms window, 10 ms hop), mean-normalised — WeSpeaker's input."""
    if len(samples) < 400:
        return None
    count = 1 + (len(samples) - 400) // 160
    frames = samples[np.arange(400)[None, :] + 160 * np.arange(count)[:, None]].astype(np.float32)
    frames -= frames.mean(axis=1, keepdims=True)
    frames[:, 1:] -= 0.97 * frames[:, :-1]
    frames[:, 0] *= 0.03
    frames *= _WINDOW
    power = np.abs(np.fft.rfft(frames, n=512)) ** 2
    features = np.log(np.maximum(power @ _BANK.T, 1.19e-7))
    return (features - features.mean(axis=0, keepdims=True)).astype(np.float32)


class OnnxVoiceEmbedder:
    """Loads the model on first use (the server starts fine without the file; the voice step then reports it)."""

    def __init__(self, model_path: Path | None = None) -> None:
        self._path = Path(model_path or os.environ.get("CUTORY_SPEAKER_MODEL_PATH") or DEFAULT_MODEL_PATH)
        self._session = None
        self._lock = Lock()

    def available(self) -> bool:
        return self._path.is_file()

    def __call__(self, samples: np.ndarray) -> np.ndarray | None:
        features = fbank(samples)
        if features is None or len(features) < MIN_FRAMES:
            return None
        with self._lock:
            if self._session is None:
                if not self.available():
                    raise SpeakerVoiceError(f"목소리 모델 파일이 없습니다: {self._path}")
                import onnxruntime as ort

                self._session = ort.InferenceSession(str(self._path), providers=["CPUExecutionProvider"])
            session = self._session
        vector = session.run(None, {session.get_inputs()[0].name: features[None]})[0].flatten()
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else None


Embedder = Callable[[np.ndarray], "np.ndarray | None"]


def load_audio(media_path: Path, start: float | None = None, duration: float | None = None) -> np.ndarray:
    """Mono 16 kHz samples of a whole video (or one range of it) via FFmpeg."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    command = [ffmpeg, "-v", "error"]
    if start is not None:
        command += ["-ss", f"{max(0.0, start):.3f}"]
    command += ["-i", str(media_path)]
    if duration is not None:
        command += ["-t", f"{duration:.3f}"]
    command += ["-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        raise SpeakerVoiceError("영상에서 소리를 꺼내지 못했습니다.")
    return np.frombuffer(result.stdout, np.int16).astype(np.float32)  # int16 scale, as WeSpeaker's Kaldi features expect


def listen_range(start: float, end: float) -> tuple[float, float]:
    """Widens very short lines around their middle so there is enough voice to recognise."""
    if end - start >= MIN_LINE_SECONDS:
        return start, end
    middle = (start + end) / 2
    return max(0.0, middle - MIN_LINE_SECONDS / 2), middle + MIN_LINE_SECONDS / 2


# ---------- files ----------

def _project_dir(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class MyVoice:
    samples: tuple[dict, ...]
    centroid: np.ndarray | None
    version: str | None


def load_my_voice(output_root: Path, project_id: UUID) -> MyVoice:
    data = _read_json(_project_dir(output_root, project_id) / "my_voice.json") or {}
    samples = tuple(item for item in data.get("samples", []) if isinstance(item, dict) and item.get("embedding"))
    if not samples:
        return MyVoice((), None, None)
    centroid = np.mean([np.asarray(item["embedding"], np.float32) for item in samples], axis=0)
    centroid = centroid / np.linalg.norm(centroid)
    version = hashlib.sha1(json.dumps([item["embedding"] for item in samples]).encode()).hexdigest()[:12]
    return MyVoice(samples, centroid, version)


def add_my_voice_sample(output_root: Path, project_id: UUID, *, source_video_id: UUID, media_path: Path,
                        start: float, end: float, text: str, embedder: Embedder) -> MyVoice:
    a, b = listen_range(start, end)
    vector = embedder(load_audio(media_path, a, b - a))
    if vector is None:
        raise SpeakerVoiceError("이 줄은 너무 짧아서 목소리를 알아듣기 어렵습니다. 더 긴 줄을 골라 주세요.")
    path = _project_dir(output_root, project_id) / "my_voice.json"
    samples = [item for item in (_read_json(path) or {}).get("samples", [])
               if not (item.get("source_video_id") == str(source_video_id) and abs(float(item.get("start", -1)) - start) < 0.01)]
    samples.append({"source_video_id": str(source_video_id), "start": start, "end": end, "text": text[:200],
                    "embedding": [round(float(x), 6) for x in vector]})
    _write_json(path, {"samples": samples[-MAX_SAMPLES:], "updated_at": datetime.now(timezone.utc).isoformat()})
    return load_my_voice(output_root, project_id)


def clear_my_voice(output_root: Path, project_id: UUID) -> None:
    (_project_dir(output_root, project_id) / "my_voice.json").unlink(missing_ok=True)


def load_speaker_scores(output_root: Path, project_id: UUID, source_video_id: UUID) -> dict | None:
    data = _read_json(_project_dir(output_root, project_id) / "speaker" / f"{source_video_id}.json")
    return data if isinstance(data, dict) else None


def speaker_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    return "me" if score >= MY_VOICE_THRESHOLD else "other"


def score_source(output_root: Path, project_id: UUID, *, source_video_id: UUID, media_path: Path,
                 segments: Sequence[dict], my_voice: MyVoice, embedder: Embedder) -> list[float | None]:
    """Scores every transcript line of one video against my voice and saves the result file."""
    if my_voice.centroid is None:
        raise SpeakerVoiceError("내 목소리를 먼저 등록해 주세요.")
    audio = load_audio(media_path) if segments else np.zeros(0, np.float32)
    scores: list[float | None] = []
    for segment in segments:
        a, b = listen_range(float(segment["start_seconds"]), float(segment["end_seconds"]))
        vector = embedder(audio[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)])
        scores.append(None if vector is None else round(float(vector @ my_voice.centroid), 3))
    _write_json(_project_dir(output_root, project_id) / "speaker" / f"{source_video_id}.json",
                {"voice_version": my_voice.version, "scores": scores, "line_count": len(segments),
                 "updated_at": datetime.now(timezone.utc).isoformat()})
    return scores


def source_is_current(output_root: Path, project_id: UUID, source_video_id: UUID, line_count: int, version: str | None) -> bool:
    stored = load_speaker_scores(output_root, project_id, source_video_id)
    return bool(stored and version and stored.get("voice_version") == version and stored.get("line_count") == line_count)


# ---------- background run ----------

@dataclass(frozen=True)
class VoiceSource:
    source_video_id: UUID
    media_path: Path
    segments: tuple[dict, ...]


@dataclass(frozen=True)
class VoiceRunState:
    status: str = "IDLE"  # IDLE | RUNNING | COMPLETED | FAILED
    done: int = 0
    total: int = 0
    error: str | None = None


class VoiceRunRegistry:
    """Scores every transcribed video that is not up to date with the current "my voice", one at a time."""

    def __init__(self, executor: Executor, output_root: Path, embedder: Embedder | None = None) -> None:
        self._executor = executor
        self._output_root = Path(output_root)
        self.embedder: Embedder = embedder or OnnxVoiceEmbedder()
        self._lock = Lock()
        self._states: dict[UUID, VoiceRunState] = {}

    def state(self, project_id: UUID) -> VoiceRunState:
        with self._lock:
            return self._states.get(project_id, VoiceRunState())

    def pending(self, project_id: UUID, sources: Sequence[VoiceSource]) -> list[VoiceSource]:
        version = load_my_voice(self._output_root, project_id).version
        return [item for item in sources
                if not source_is_current(self._output_root, project_id, item.source_video_id, len(item.segments), version)]

    def start(self, project_id: UUID, sources_loader: Callable[[], Sequence[VoiceSource]]) -> bool:
        with self._lock:
            if self._states.get(project_id, VoiceRunState()).status == "RUNNING":
                return False
            self._states[project_id] = VoiceRunState(status="RUNNING")
        self._executor.submit(self._run, project_id, sources_loader)
        return True

    def _set(self, project_id: UUID, **changes) -> None:
        with self._lock:
            self._states[project_id] = replace(self._states[project_id], **changes)

    def _run(self, project_id: UUID, sources_loader: Callable[[], Sequence[VoiceSource]]) -> None:
        try:
            my_voice = load_my_voice(self._output_root, project_id)
            if my_voice.centroid is None:
                raise SpeakerVoiceError("내 목소리를 먼저 등록해 주세요. 대사 목록에서 내가 말한 줄의 [이건 내 목소리]를 누르면 됩니다.")
            todo = self.pending(project_id, sources_loader())
            self._set(project_id, total=len(todo))
            for index, item in enumerate(todo, start=1):
                score_source(self._output_root, project_id, source_video_id=item.source_video_id, media_path=item.media_path,
                             segments=item.segments, my_voice=my_voice, embedder=self.embedder)
                self._set(project_id, done=index)
            self._set(project_id, status="COMPLETED")
        except SpeakerVoiceError as error:
            self._set(project_id, status="FAILED", error=str(error))
        except Exception:
            self._set(project_id, status="FAILED", error="목소리 분석 중 예상하지 못한 오류가 났습니다. 다시 눌러 주세요.")
