from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterable
from uuid import UUID
import zlib

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models import (
    SceneAnalysisAttempt,
    SceneAnalysisAttemptStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneEvidence,
    SceneEvidenceModality,
    SourceVideo,
)
from backend.app.services.scene_fingerprints import canonical_fingerprint
from backend.app.services.scene_processing_state import (
    SHOT_EVIDENCE,
    SceneWorkSpec,
    active_candidate_ids,
    claim_scene_work,
    snapshot_still_matches,
)


SHOT_DETECTOR_VERSION = "ffmpeg-scdet-v0.1"
SHOT_RESULT_SCHEMA = "shot-structure-result-v0.1"
SHOT_EVIDENCE_TYPE = "SHOT_CHANGE"
SHOT_EVIDENCE_PAYLOAD_VERSION = "1"
_TIME_PRECISION = 3
_SCDET_LINE = re.compile(
    r"lavfi\.scd\.score:\s*(?P<score>[0-9]+(?:\.[0-9]+)?)"
    r".*?lavfi\.scd\.time:\s*(?P<time>[0-9]+(?:\.[0-9]+)?)"
)


class ShotStructureError(RuntimeError):
    """A safe deterministic shot-analysis failure."""


@dataclass(frozen=True)
class ShotDetectionConfig:
    threshold_percent: float = 10.0
    minimum_shot_duration_seconds: float = 0.5
    timeout_seconds: float = 600.0
    maximum_boundaries: int = 256


DEFAULT_SHOT_DETECTION_CONFIG = ShotDetectionConfig()


@dataclass(frozen=True)
class ShotBoundary:
    source_video_id: UUID
    timestamp_seconds: float
    score: float | None
    producer: str = "ffmpeg-scdet"
    producer_version: str = SHOT_DETECTOR_VERSION


@dataclass(frozen=True)
class ShotInterval:
    source_video_id: UUID
    start_seconds: float
    end_seconds: float
    start_boundary_seconds: float | None
    end_boundary_seconds: float | None


@dataclass(frozen=True)
class ShotStructureResult:
    source_video_id: UUID
    duration_seconds: float
    boundaries: tuple[ShotBoundary, ...]
    intervals: tuple[ShotInterval, ...]
    producer: str = "ffmpeg-scdet"
    producer_version: str = SHOT_DETECTOR_VERSION


@dataclass(frozen=True)
class ShotEvidenceProcessingResult:
    work_item_id: UUID
    attempt_id: UUID
    source_video_id: UUID
    result_fingerprint: str
    boundary_count: int
    interval_count: int
    evidence_count: int
    reused: bool


ShotAnalyzer = Callable[[UUID, float], ShotStructureResult]


def detect_shot_structure(
    source_video_path: str | Path,
    *,
    source_video_id: UUID,
    duration_seconds: float,
    config: ShotDetectionConfig = DEFAULT_SHOT_DETECTION_CONFIG,
    ffmpeg_executable: str = "ffmpeg",
) -> ShotStructureResult:
    """Observe hard/jump cuts with FFmpeg scdet; do not judge scene value."""
    source_path = Path(source_video_path)
    duration = _duration(duration_seconds)
    _validate_config(config)
    if not source_path.is_file():
        raise ShotStructureError("Source video is unavailable.")
    command = [
        ffmpeg_executable,
        "-hide_banner",
        "-nostats",
        "-nostdin",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"scdet=threshold={config.threshold_percent:.6f}",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=config.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ShotStructureError("FFmpeg shot detection timed out.") from exc
    except OSError as exc:
        raise ShotStructureError("Could not start FFmpeg shot detection.") from exc
    if completed.returncode != 0:
        raise ShotStructureError("FFmpeg shot detection failed.")
    measurements = tuple(
        (float(match.group("time")), float(match.group("score")))
        for match in _SCDET_LINE.finditer(completed.stderr)
    )
    return build_shot_structure_result(
        source_video_id,
        duration,
        measurements,
        config=config,
    )


def build_shot_structure_result(
    source_video_id: UUID,
    duration_seconds: float,
    measurements: Iterable[tuple[float, float | None]],
    *,
    config: ShotDetectionConfig = DEFAULT_SHOT_DETECTION_CONFIG,
) -> ShotStructureResult:
    duration = _duration(duration_seconds)
    _validate_config(config)
    normalized: dict[float, float | None] = {}
    for raw_timestamp, raw_score in measurements:
        timestamp = _finite(raw_timestamp, "Boundary timestamp")
        if timestamp < 0:
            raise ShotStructureError("Boundary timestamp must not be negative.")
        timestamp = min(round(timestamp, _TIME_PRECISION), duration)
        if timestamp <= 0 or timestamp >= duration:
            continue
        score = None if raw_score is None else _finite(raw_score, "Boundary score")
        if score is not None and score < 0:
            raise ShotStructureError("Boundary score must not be negative.")
        previous = normalized.get(timestamp)
        normalized[timestamp] = (
            score if previous is None else max(value for value in (previous, score) if value is not None)
        ) if previous is not None or score is not None else None
    ordered = sorted(normalized.items())
    accepted: list[tuple[float, float | None]] = []
    for timestamp, score in ordered:
        if timestamp - (accepted[-1][0] if accepted else 0.0) < config.minimum_shot_duration_seconds:
            continue
        if duration - timestamp < config.minimum_shot_duration_seconds:
            continue
        accepted.append((timestamp, score))
    if len(accepted) > config.maximum_boundaries:
        raise ShotStructureError("Shot result exceeds the bounded manifest limit.")
    boundaries = tuple(
        ShotBoundary(source_video_id, timestamp, score)
        for timestamp, score in accepted
    )
    edges = (0.0,) + tuple(item.timestamp_seconds for item in boundaries) + (duration,)
    intervals = tuple(
        ShotInterval(
            source_video_id,
            edges[index],
            edges[index + 1],
            None if index == 0 else edges[index],
            None if index + 1 == len(edges) - 1 else edges[index + 1],
        )
        for index in range(len(edges) - 1)
    )
    result = ShotStructureResult(source_video_id, duration, boundaries, intervals)
    validate_shot_result(result)
    return result


def validate_shot_result(result: ShotStructureResult) -> None:
    duration = _duration(result.duration_seconds)
    if not isinstance(result.source_video_id, UUID):
        raise ShotStructureError("Shot result source ID is invalid.")
    timestamps = tuple(item.timestamp_seconds for item in result.boundaries)
    if timestamps != tuple(sorted(set(timestamps))):
        raise ShotStructureError("Shot boundaries must be sorted and unique.")
    if any(timestamp <= 0 or timestamp >= duration for timestamp in timestamps):
        raise ShotStructureError("Shot boundary is outside the source duration.")
    if len(result.intervals) != len(result.boundaries) + 1:
        raise ShotStructureError("Shot intervals do not cover the boundary manifest.")
    cursor = 0.0
    for interval in result.intervals:
        if interval.source_video_id != result.source_video_id:
            raise ShotStructureError("Shot interval source does not match.")
        if interval.start_seconds != cursor or interval.end_seconds <= interval.start_seconds:
            raise ShotStructureError("Shot intervals are not contiguous and ordered.")
        cursor = interval.end_seconds
    if cursor != duration:
        raise ShotStructureError("Shot intervals do not cover the source duration.")


def shot_input_fingerprint(source: SourceVideo) -> str:
    return canonical_fingerprint(
        {
            "source_video_id": source.id,
            "source_fingerprint": source.fingerprint,
            "duration_seconds": None
            if source.duration_seconds is None
            else round(float(source.duration_seconds), _TIME_PRECISION),
        }
    )


def shot_config_fingerprint(config: ShotDetectionConfig) -> str:
    _validate_config(config)
    return canonical_fingerprint(
        {"detector_version": SHOT_DETECTOR_VERSION, "config": asdict(config)}
    )


def shot_result_manifest(result: ShotStructureResult) -> dict[str, object]:
    validate_shot_result(result)
    return {
        "schema": SHOT_RESULT_SCHEMA,
        "source_video_id": str(result.source_video_id),
        "duration_seconds": result.duration_seconds,
        "producer": result.producer,
        "producer_version": result.producer_version,
        "boundaries": [
            {"timestamp_seconds": item.timestamp_seconds, "score": item.score}
            for item in result.boundaries
        ],
        "intervals": [
            {"start_seconds": item.start_seconds, "end_seconds": item.end_seconds}
            for item in result.intervals
        ],
    }


def encode_shot_manifest(manifest: dict[str, object]) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = "zlib:" + base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
    if len(encoded) > 1024:
        raise ShotStructureError("Shot result reference exceeds its bounded storage limit.")
    return encoded


def decode_shot_manifest(reference: str) -> dict[str, object]:
    try:
        raw = zlib.decompress(base64.b64decode(reference.removeprefix("zlib:")))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, zlib.error) as exc:
        raise ShotStructureError("Shot result reference is invalid.") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SHOT_RESULT_SCHEMA:
        raise ShotStructureError("Shot result schema is invalid.")
    return payload


def validate_shot_work_result(work: SceneAnalysisWorkItem) -> bool:
    try:
        payload = decode_shot_manifest(work.result_reference or "")
        source_id = UUID(str(payload["source_video_id"]))
        duration = _duration(payload["duration_seconds"])
        boundaries_raw = payload["boundaries"]
        if not isinstance(boundaries_raw, list):
            return False
        result = build_shot_structure_result(
            source_id,
            duration,
            (
                (item["timestamp_seconds"], item.get("score"))
                for item in boundaries_raw
                if isinstance(item, dict)
            ),
            config=ShotDetectionConfig(
                minimum_shot_duration_seconds=0.0,
                maximum_boundaries=256,
            ),
        )
        manifest = shot_result_manifest(result)
        return manifest == payload and canonical_fingerprint(payload) == work.result_fingerprint
    except (KeyError, TypeError, ValueError, ShotStructureError):
        return False


def process_shot_evidence(
    session: Session,
    source_video_id: UUID,
    *,
    analyzer: ShotAnalyzer,
    config: ShotDetectionConfig = DEFAULT_SHOT_DETECTION_CONFIG,
) -> ShotEvidenceProcessingResult:
    source = session.get(SourceVideo, source_video_id)
    if source is None or source.duration_seconds is None or source.fingerprint is None:
        raise ShotStructureError("Source is missing duration or fingerprint metadata.")
    input_fingerprint = shot_input_fingerprint(source)
    config_fingerprint = shot_config_fingerprint(config)
    spec = SceneWorkSpec(
        source.project_id,
        SHOT_EVIDENCE,
        input_fingerprint,
        config_fingerprint,
        "shot-structure",
        SHOT_DETECTOR_VERSION,
        source.id,
    )
    work, attempt, claimed = claim_scene_work(session, spec)
    if not claimed:
        payload = decode_shot_manifest(work.result_reference or "")
        return ShotEvidenceProcessingResult(
            work.id,
            attempt.id,
            source.id,
            work.result_fingerprint or "",
            len(payload["boundaries"]),
            len(payload["intervals"]),
            _shot_evidence_count(session, source.id),
            True,
        )
    try:
        result = analyzer(source.id, float(source.duration_seconds))
        validate_shot_result(result)
        if result.source_video_id != source.id:
            raise ShotStructureError("Analyzer returned a result for another source.")
        if result.duration_seconds != round(float(source.duration_seconds), _TIME_PRECISION):
            raise ShotStructureError("Analyzer duration does not match the source.")
        snapshot_still_matches(
            input_fingerprint,
            lambda: shot_input_fingerprint(session.get(SourceVideo, source.id)),
        )
        manifest = shot_result_manifest(result)
        reference = encode_shot_manifest(manifest)
        result_fingerprint = canonical_fingerprint(manifest)
        evidence_count = _replace_candidate_shot_evidence(
            session,
            source,
            work,
            result,
            input_fingerprint,
            config_fingerprint,
            result_fingerprint,
        )
        work.status = SceneAnalysisWorkStatus.COMPLETED
        work.result_reference = reference
        work.result_fingerprint = result_fingerprint
        attempt.status = SceneAnalysisAttemptStatus.COMPLETED
        attempt.completed_at = datetime.now(timezone.utc)
        session.commit()
        return ShotEvidenceProcessingResult(
            work.id,
            attempt.id,
            source.id,
            result_fingerprint,
            len(result.boundaries),
            len(result.intervals),
            evidence_count,
            False,
        )
    except Exception as exc:
        session.rollback()
        failed_work = session.get(SceneAnalysisWorkItem, work.id)
        failed_attempt = session.get(SceneAnalysisAttempt, attempt.id)
        if failed_work is not None and failed_attempt is not None:
            failed_work.status = SceneAnalysisWorkStatus.FAILED
            failed_attempt.status = SceneAnalysisAttemptStatus.FAILED
            failed_attempt.completed_at = datetime.now(timezone.utc)
            failed_attempt.safe_error_code = (
                "INPUT_CHANGED_DURING_EXECUTION"
                if "INPUT_CHANGED_DURING_EXECUTION" in str(exc)
                else "SHOT_DETECTION_FAILED"
            )
            failed_attempt.safe_error_message = "Shot structure analysis did not complete."
            session.commit()
        if isinstance(exc, ShotStructureError):
            raise
        raise ShotStructureError("Shot structure analysis did not complete.") from exc


def _replace_candidate_shot_evidence(
    session: Session,
    source: SourceVideo,
    work: SceneAnalysisWorkItem,
    result: ShotStructureResult,
    input_fingerprint: str,
    config_fingerprint: str,
    result_fingerprint: str,
) -> int:
    active_ids = active_candidate_ids(session, source.project_id)
    candidates = tuple(
        session.scalars(
            select(SceneCandidate)
            .where(
                SceneCandidate.id.in_(active_ids),
                SceneCandidate.source_video_id == source.id,
            )
            .order_by(SceneCandidate.start_seconds, SceneCandidate.end_seconds, SceneCandidate.id)
        )
    ) if active_ids else ()
    if candidates:
        session.execute(
            delete(SceneEvidence).where(
                SceneEvidence.scene_candidate_id.in_(item.id for item in candidates),
                SceneEvidence.modality == SceneEvidenceModality.SHOT,
                SceneEvidence.producer == "shot-structure",
            )
        )
    count = 0
    for candidate in candidates:
        start, end = float(candidate.start_seconds), float(candidate.end_seconds)
        relevant = tuple(
            boundary for boundary in result.boundaries if start <= boundary.timestamp_seconds <= end
        )
        if not relevant:
            continue
        enclosing = next(
            (
                interval
                for interval in result.intervals
                if interval.start_seconds <= start < interval.end_seconds
            ),
            result.intervals[-1],
        )
        previous = max(
            (boundary.timestamp_seconds for boundary in result.boundaries if boundary.timestamp_seconds <= start),
            default=None,
        )
        following = min(
            (boundary.timestamp_seconds for boundary in result.boundaries if boundary.timestamp_seconds >= end),
            default=None,
        )
        payload = {
            "relevant_boundary_count": len(relevant),
            "nearest_previous_boundary": previous,
            "nearest_next_boundary": following,
            "overlap_shot_interval": [enclosing.start_seconds, enclosing.end_seconds],
            "detector_version": SHOT_DETECTOR_VERSION,
            "config_fingerprint": config_fingerprint,
        }
        session.add(
            SceneEvidence(
                scene_candidate_id=candidate.id,
                modality=SceneEvidenceModality.SHOT,
                evidence_type=SHOT_EVIDENCE_TYPE,
                start_seconds=start,
                end_seconds=end,
                confidence=None,
                payload=payload,
                payload_schema_version=SHOT_EVIDENCE_PAYLOAD_VERSION,
                producer="shot-structure",
                producer_version=SHOT_DETECTOR_VERSION,
                source_reference=f"shot-work:{work.id}",
                input_fingerprint=input_fingerprint,
                config_fingerprint=config_fingerprint,
                result_fingerprint=canonical_fingerprint(
                    {"shot_result": result_fingerprint, "candidate": candidate.id, "payload": payload}
                ),
            )
        )
        count += 1
    return count


def _shot_evidence_count(session: Session, source_id: UUID) -> int:
    return len(
        tuple(
            session.scalars(
                select(SceneEvidence.id)
                .join(SceneCandidate)
                .where(
                    SceneCandidate.source_video_id == source_id,
                    SceneEvidence.modality == SceneEvidenceModality.SHOT,
                    SceneEvidence.producer == "shot-structure",
                )
            )
        )
    )


def _validate_config(config: ShotDetectionConfig) -> None:
    threshold = _finite(config.threshold_percent, "Threshold")
    minimum = _finite(config.minimum_shot_duration_seconds, "Minimum shot duration")
    timeout = _finite(config.timeout_seconds, "Timeout")
    if not 0 <= threshold <= 100:
        raise ShotStructureError("Threshold must be between 0 and 100.")
    if minimum < 0 or timeout <= 0:
        raise ShotStructureError("Shot duration and timeout configuration is invalid.")
    if isinstance(config.maximum_boundaries, bool) or config.maximum_boundaries < 1:
        raise ShotStructureError("Maximum boundary count must be positive.")


def _duration(value: object) -> float:
    duration = _finite(value, "Source duration")
    if duration <= 0:
        raise ShotStructureError("Source duration must be positive.")
    return round(duration, _TIME_PRECISION)


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ShotStructureError(f"{label} must be finite.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ShotStructureError(f"{label} must be finite.") from exc
    if not math.isfinite(number):
        raise ShotStructureError(f"{label} must be finite.")
    return number
