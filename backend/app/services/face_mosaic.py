"""TODO 25: "다른 사람 얼굴 가리기" — mosaic every face except mine (YuNet finds faces, SFace compares them, local).

The user uploads 3~5 photos of their own face once. Every project shares them (no database change):

  outputs/me/face/my_face.json      registered photos + one SFace print each
  outputs/me/face/<photo_id>.jpg    the photo (long side ≤ 1280) and <photo_id>_face.jpg, the found face

Blurring reads a finished video frame by frame, finds every face, keeps faces that look like me and pixelates the rest.
A face that cannot be compared (too small, the comparison is unsure) is pixelated: hiding too much is the safe side.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import UUID

import numpy as np

log = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parents[3] / "assets" / "models"
# A face becomes "나" once its smoothed similarity to my registered faces reaches this, over at least ME_MIN_LOOKS
# frames, and then stays "나" while it is followed (so turning to the side does not hide me). One frame is never
# enough: on the academy edit a teammate scored 0.60 in one frame (0.15~0.38 around it) while my front face
# scored 0.53~0.76 and my side face 0.08~0.38. The first try (one frame ≥ 0.36) showed that teammate and hid my side face.
SIM_ME = 0.52
ME_MIN_LOOKS = 2
CUT_DIFFERENCE = 40.0  # mean grey-level change between frames above this = a cut in the edit → forget every face
DETECT_LONG_SIDE = 1280  # faces are found and compared on a frame of this size (the experiment's scale)
MIN_COMPARE_PX = 28  # smaller faces (at DETECT_LONG_SIDE) cannot be compared → always hidden
OUTPUT_LONG_SIDE = 1920
OUTPUT_FPS = 30
HOLD_FRAMES = 8  # a hidden face that the finder misses for a moment stays hidden this many frames (~0.27 s)
SMOOTHING = 0.35  # how fast a face's "looks like me" score follows a new frame
MAX_PHOTOS = 8
PHOTO_LONG_SIDE = 1280
VIDEO_NAME = "vlog-faces.mp4"
INFO_NAME = "vlog-faces.json"


class FaceMosaicError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message


# ---------- models ----------

class FaceModels:
    """Loads OpenCV and the two model files on first use; the server starts fine without them."""

    def __init__(self, model_dir: Path | None = None) -> None:
        directory = Path(model_dir or os.environ.get("CUTORY_FACE_MODEL_DIR") or MODEL_DIR)
        self.detector_path = directory / "yunet.onnx"
        self.recognizer_path = directory / "sface.onnx"
        self._lock = Lock()
        self._loaded = None

    def available(self) -> bool:
        if not (self.detector_path.is_file() and self.recognizer_path.is_file()):
            return False
        try:
            import cv2  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        with self._lock:
            if self._loaded is None:
                if not self.available():
                    raise FaceMosaicError("FACE_MODEL_MISSING", "얼굴 모델 파일이나 OpenCV가 없습니다.")
                import cv2

                detector = cv2.FaceDetectorYN.create(str(self.detector_path), "", (320, 320), 0.6, 0.3, 5000)
                recognizer = cv2.FaceRecognizerSF.create(str(self.recognizer_path), "")
                self._loaded = (detector, recognizer, Lock())
            return self._loaded

    def detect(self, image: np.ndarray) -> np.ndarray:
        detector, _, lock = self._load()
        height, width = image.shape[:2]
        with lock:
            detector.setInputSize((width, height))
            _, faces = detector.detect(image)
        return np.zeros((0, 15), np.float32) if faces is None else faces

    def embed(self, image: np.ndarray, face: np.ndarray) -> np.ndarray:
        _, recognizer, lock = self._load()
        with lock:
            vector = recognizer.feature(recognizer.alignCrop(image, face)).flatten().astype(np.float32)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else vector


def _fit(image: np.ndarray, long_side: int) -> np.ndarray:
    import cv2

    height, width = image.shape[:2]
    scale = long_side / max(height, width)
    if scale >= 1:
        return image
    return cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)


# ---------- my face (shared by every project) ----------

def face_dir(project_output_root: Path) -> Path:
    """outputs/projects → outputs/me/face"""
    return Path(project_output_root).parent / "me" / "face"


def _read_store(directory: Path) -> dict:
    try:
        data = json.loads((directory / "my_face.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_store(directory: Path, photos: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "my_face.tmp"
    temporary.write_text(json.dumps({"photos": photos, "updated_at": datetime.now(timezone.utc).isoformat()},
                                    ensure_ascii=False), encoding="utf-8")
    temporary.replace(directory / "my_face.json")


@dataclass(frozen=True)
class MyFace:
    photos: tuple[dict, ...]  # {id, filename, embedding, added_at}

    @property
    def prints(self) -> np.ndarray | None:
        if not self.photos:
            return None
        return np.vstack([np.asarray(item["embedding"], np.float32) for item in self.photos])


def load_my_face(directory: Path) -> MyFace:
    photos = [item for item in _read_store(directory).get("photos", [])
              if isinstance(item, dict) and item.get("id") and item.get("embedding")]
    return MyFace(tuple(photos))


def add_photo(directory: Path, data: bytes, filename: str, models: FaceModels) -> MyFace:
    import cv2

    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FaceMosaicError("FACE_PHOTO_INVALID", "사진 파일을 읽지 못했습니다. JPG나 PNG 사진을 올려 주세요.")
    image = _fit(image, PHOTO_LONG_SIDE)
    faces = models.detect(image)
    if len(faces) == 0:
        raise FaceMosaicError("FACE_NOT_FOUND", "이 사진에서 얼굴을 찾지 못했습니다. 얼굴이 정면으로 크게 나온 사진을 골라 주세요.")
    face = max(faces, key=lambda f: float(f[2] * f[3]))  # the biggest face is me
    if face[2] < 60:
        raise FaceMosaicError("FACE_TOO_SMALL", "사진 속 얼굴이 너무 작습니다. 얼굴이 크게 나온 사진을 골라 주세요.")
    current = list(load_my_face(directory).photos)
    if len(current) >= MAX_PHOTOS:
        raise FaceMosaicError("FACE_TOO_MANY", f"사진은 {MAX_PHOTOS}장까지 등록할 수 있습니다. 하나를 지운 뒤 올려 주세요.")
    photo_id = uuid.uuid4().hex[:12]
    directory.mkdir(parents=True, exist_ok=True)
    x, y, w, h = (int(v) for v in face[:4])
    pad = int(max(w, h) * 0.25)
    crop = image[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
    cv2.imwrite(str(directory / f"{photo_id}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    cv2.imwrite(str(directory / f"{photo_id}_face.jpg"), _fit(crop, 320), [cv2.IMWRITE_JPEG_QUALITY, 88])
    current.append({"id": photo_id, "filename": Path(filename or "photo").name[:120],
                    "embedding": [round(float(v), 6) for v in models.embed(image, face)],
                    "added_at": datetime.now(timezone.utc).isoformat()})
    _write_store(directory, current)
    return load_my_face(directory)


def remove_photo(directory: Path, photo_id: str) -> MyFace:
    current = list(load_my_face(directory).photos)
    kept = [item for item in current if item["id"] != photo_id]
    if len(kept) == len(current):
        raise FaceMosaicError("FACE_PHOTO_MISSING", "그 사진은 이미 없습니다.")
    _write_store(directory, kept)
    for name in (f"{photo_id}.jpg", f"{photo_id}_face.jpg"):
        (directory / name).unlink(missing_ok=True)
    return load_my_face(directory)


def face_image(directory: Path, photo_id: str) -> Path | None:
    if not any(item["id"] == photo_id for item in load_my_face(directory).photos):
        return None
    path = directory / f"{photo_id}_face.jpg"
    return path if path.is_file() else None


# ---------- following faces from frame to frame ----------

@dataclass
class _Track:
    box: tuple[float, float, float, float]  # x, y, w, h at detection scale
    score: float | None  # smoothed similarity to me; None until the face could be compared once
    missed: int = 0
    looks: int = 0  # frames in which this face could be compared
    is_me: bool = False  # once true, stays true while the face is followed

    def look(self, sim: float | None) -> None:
        if sim is None:
            return
        self.looks += 1
        self.score = sim if self.score is None else (1 - SMOOTHING) * self.score + SMOOTHING * sim
        if self.looks >= ME_MIN_LOOKS and self.score >= SIM_ME:
            self.is_me = True


def _overlap(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


@dataclass
class FaceFollower:
    """Decides per frame which boxes to hide. Keeps a face's identity while it turns away for a moment."""

    prints: np.ndarray
    tracks: list[_Track] = field(default_factory=list)

    def similarity(self, vector: np.ndarray) -> float:
        # the average over all my photos, not the closest one: with 4 photos the closest one also flattered a
        # look-alike teammate (0.53~0.59, my front face 0.55~0.76); the average split us (0.43~0.50 vs 0.55~0.64)
        return float(np.mean(self.prints @ vector))

    def step(self, detections: Sequence[tuple[tuple[float, float, float, float], float | None]]) -> tuple[list, int]:
        """detections: (box, similarity or None). Returns (boxes to hide, how many of the found faces are me)."""
        used: set[int] = set()
        fresh: list[_Track] = []
        for box, sim in detections:
            best, best_overlap = None, 0.3
            for index, track in enumerate(self.tracks):
                if index in used:
                    continue
                value = _overlap(box, track.box)
                if value > best_overlap:
                    best, best_overlap = index, value
            if best is None:
                track = _Track(box, None)
                track.look(sim)
                fresh.append(track)
                continue
            used.add(best)
            track = self.tracks[best]
            track.box, track.missed = box, 0
            track.look(sim)
        for index, track in enumerate(self.tracks):
            if index not in used:
                track.missed += 1
        self.tracks = [t for t in self.tracks if t.missed <= HOLD_FRAMES] + fresh
        hide = [t.box for t in self.tracks if not t.is_me]
        me = sum(1 for t in self.tracks if t.missed == 0 and t.is_me)
        return hide, me

    def cut(self) -> None:
        """A new shot starts: nobody carries over (a stranger must not inherit my place in the frame)."""
        self.tracks = []


def pixelate(frame: np.ndarray, box, scale: float) -> None:
    """Mosaics one face (box at detection scale) in place; the box grows a bit so hair and chin are covered too."""
    import cv2

    x, y, w, h = (v * scale for v in box)
    grow_x, grow_top, grow_bottom = w * 0.2, h * 0.35, h * 0.15
    height, width = frame.shape[:2]
    left, right = int(max(0, x - grow_x)), int(min(width, x + w + grow_x))
    top, bottom = int(max(0, y - grow_top)), int(min(height, y + h + grow_bottom))
    if right - left < 2 or bottom - top < 2:
        return
    region = frame[top:bottom, left:right]
    blocks = 9
    small = cv2.resize(region, (blocks, max(1, round(blocks * (bottom - top) / (right - left)))), interpolation=cv2.INTER_AREA)
    frame[top:bottom, left:right] = cv2.resize(small, (right - left, bottom - top), interpolation=cv2.INTER_NEAREST)


# ---------- the video ----------

@dataclass(frozen=True)
class BlurStats:
    frames: int
    frames_hidden: int  # frames where at least one face was hidden
    faces_hidden: int  # hidden boxes summed over all frames
    frames_with_me: int


@dataclass(frozen=True)
class BlurredVideo:
    path: Path
    render_id: str
    duration_seconds: float
    file_size_bytes: int
    stats: BlurStats
    photo_count: int


Progress = Callable[[int, int], None]


def _probe(video: Path, ffprobe: str) -> tuple[int, int, float, bool]:
    command = [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,width,height:stream_side_data=rotation:format=duration",
               "-of", "json", str(video)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode != 0:
        raise FaceMosaicError("FACE_VIDEO_INVALID", result.stderr.strip()[-400:])
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise FaceMosaicError("FACE_VIDEO_INVALID", "no video stream")
    width, height = int(video_stream["width"]), int(video_stream["height"])
    rotation = next((abs(int(item.get("rotation", 0))) for item in video_stream.get("side_data_list", []) if "rotation" in item), 0)
    if rotation in (90, 270):
        width, height = height, width
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return width, height, float(data.get("format", {}).get("duration") or 0), has_audio


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def blur_video(video: Path, destination: Path, prints: np.ndarray, models: FaceModels, *,
               ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", on_progress: Progress | None = None) -> BlurStats:
    """Writes ``destination`` (H.264, ≤1920 px, 30 fps, original sound) with every face but mine pixelated."""
    import cv2

    progress = on_progress or (lambda done, total: None)
    width, height, duration, has_audio = _probe(Path(video), ffprobe)
    scale = min(1.0, OUTPUT_LONG_SIDE / max(width, height))
    out_w, out_h = _even(width * scale), _even(height * scale)
    det_scale = min(1.0, DETECT_LONG_SIDE / max(out_w, out_h))
    det_w, det_h = round(out_w * det_scale), round(out_h * det_scale)
    total = max(1, int(duration * OUTPUT_FPS))
    frame_bytes = out_w * out_h * 3

    reader = subprocess.Popen([ffmpeg, "-v", "error", "-nostdin", "-i", str(video), "-vf",
                               f"fps={OUTPUT_FPS},scale={out_w}:{out_h}:flags=bicubic", "-f", "rawvideo",
                               "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    writer_command = [ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                      "-s", f"{out_w}x{out_h}", "-r", str(OUTPUT_FPS), "-i", "-"]
    if has_audio:
        writer_command += ["-i", str(video), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
    writer_command += ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-shortest",
                       "-movflags", "+faststart", str(destination)]
    writer = subprocess.Popen(writer_command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    follower = FaceFollower(prints)
    previous_thumb = None
    frames = frames_hidden = faces_hidden = frames_with_me = 0
    try:
        while True:
            raw = reader.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, np.uint8).reshape(out_h, out_w, 3).copy()
            small = frame if det_scale == 1.0 else cv2.resize(frame, (det_w, det_h), interpolation=cv2.INTER_AREA)
            thumb = cv2.resize(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)
            if previous_thumb is not None and float(np.abs(thumb - previous_thumb).mean()) > CUT_DIFFERENCE:
                follower.cut()
            previous_thumb = thumb
            detections = []
            for face in models.detect(small):
                box = tuple(float(v) for v in face[:4])
                sim = follower.similarity(models.embed(small, face)) if face[2] >= MIN_COMPARE_PX else None
                detections.append((box, sim))
            hide, me = follower.step(detections)
            for box in hide:
                pixelate(frame, box, 1 / det_scale)
            frames += 1
            frames_hidden += bool(hide)
            faces_hidden += len(hide)
            frames_with_me += bool(me)
            writer.stdin.write(frame.tobytes())
            if frames % 30 == 0:
                progress(frames, total)
        writer.stdin.close()
        error = writer.stderr.read().decode("utf-8", "replace")
        if writer.wait() != 0:
            raise FaceMosaicError("FACE_ENCODE_FAILED", error.strip()[-600:])
    finally:
        reader.kill()
        reader.wait()
        reader.stdout.close()
        if writer.poll() is None:
            writer.kill()
            writer.wait()
        writer.stderr.close()
    if frames == 0:
        raise FaceMosaicError("FACE_VIDEO_INVALID", "no frames were read")
    progress(total, total)
    return BlurStats(frames, frames_hidden, faces_hidden, frames_with_me)


# ---------- the project's blurred render ----------

def output_dir(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "faces"


def saved_video(directory: Path) -> BlurredVideo | None:
    path, info = directory / VIDEO_NAME, directory / INFO_NAME
    if not path.is_file() or not info.is_file():
        return None
    try:
        data = json.loads(info.read_text(encoding="utf-8"))
        return BlurredVideo(path, str(data["render_id"]), float(data["duration_seconds"]), path.stat().st_size,
                            BlurStats(**data["stats"]), int(data.get("photo_count", 0)))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def blur_render(video: Path, render_id: str, output: Path, my_face: MyFace, models: FaceModels, *,
                blur=None, on_progress: Progress | None = None, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> BlurredVideo:
    if my_face.prints is None:
        raise FaceMosaicError("FACE_NOT_REGISTERED", "내 얼굴 사진을 먼저 등록해 주세요.")
    if not Path(video).is_file():
        raise FaceMosaicError("FACE_RENDER_MISSING")
    output.mkdir(parents=True, exist_ok=True)
    staging = output / f"working-{uuid.uuid4().hex[:8]}.mp4"
    try:
        stats = (blur or blur_video)(Path(video), staging, my_face.prints, models, ffmpeg=ffmpeg, ffprobe=ffprobe,
                                     on_progress=on_progress)
        _, _, duration, _ = _probe(staging, ffprobe)
        _, _, source_duration, _ = _probe(Path(video), ffprobe)
        if abs(duration - source_duration) > 0.5:
            raise FaceMosaicError("FACE_OUTPUT_INVALID", f"{duration} vs {source_duration}")
        destination = output / VIDEO_NAME
        staging.replace(destination)
    finally:
        staging.unlink(missing_ok=True)
    done = BlurredVideo(destination, render_id, round(duration, 2), destination.stat().st_size, stats, len(my_face.photos))
    (output / INFO_NAME).write_text(json.dumps({
        "render_id": render_id, "duration_seconds": done.duration_seconds, "photo_count": done.photo_count,
        "stats": vars(stats)}, ensure_ascii=False), encoding="utf-8")
    return done


@dataclass
class FaceJob:
    status: str = "IDLE"  # IDLE | RUNNING | COMPLETED | FAILED
    done: int = 0
    total: int = 0
    error_code: str | None = None


_jobs: dict[UUID, FaceJob] = {}
_jobs_lock = threading.Lock()


def job_state(project_id: UUID) -> FaceJob:
    with _jobs_lock:
        job = _jobs.get(project_id)
        return FaceJob(**vars(job)) if job else FaceJob()


def any_running() -> bool:
    with _jobs_lock:
        return any(job.status == "RUNNING" for job in _jobs.values())


def start_blurring(project_id: UUID, video: Path, render_id: str, output_root: Path, my_face: MyFace, models: FaceModels,
                   *, blur=None, background: bool = True) -> str | None:
    """None when started, otherwise a reason code."""
    with _jobs_lock:
        if project_id in _jobs and _jobs[project_id].status == "RUNNING":
            return "FACE_RUNNING"
        _jobs[project_id] = FaceJob(status="RUNNING")

    def update(**changes) -> None:
        with _jobs_lock:
            for key, value in changes.items():
                setattr(_jobs[project_id], key, value)

    def work() -> None:
        try:
            blur_render(video, render_id, output_dir(output_root, project_id), my_face, models, blur=blur,
                        ffmpeg=shutil.which("ffmpeg") or "ffmpeg", ffprobe=shutil.which("ffprobe") or "ffprobe",
                        on_progress=lambda done, total: update(done=done, total=total))
            update(status="COMPLETED")
        except FaceMosaicError as error:
            log.warning("face mosaic failed: %s", error)
            update(status="FAILED", error_code=error.code)
        except Exception:  # noqa: BLE001 - the screen shows a safe code; details stay in the server log
            log.exception("face mosaic failed")
            update(status="FAILED", error_code="FACE_FAILED")

    if background:
        threading.Thread(target=work, name=f"faces-{project_id}", daemon=True).start()
    else:
        work()
    return None
