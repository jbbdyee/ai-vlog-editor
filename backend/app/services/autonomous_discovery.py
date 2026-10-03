from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import base64
import binascii
import zlib
from pathlib import Path
import re
from statistics import median
from typing import Callable, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    SceneAnalysisAttempt,
    SceneAnalysisAttemptStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkResultCandidate,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneDiscoveryMethod,
    SceneEvidence,
    SceneEvidenceModality,
    SourceVideo,
)
from backend.app.services.audio_boundary_refiner import (
    DEFAULT_AUDIO_BOUNDARY_CONFIG,
    build_audio_activity_intervals,
    read_pcm_frame_dbfs,
)
from backend.app.services.visual_motion_refiner import (
    DEFAULT_VISUAL_BOUNDARY_CONFIG,
    build_visual_activity_intervals,
    calculate_motion_scores,
    extract_grayscale_frames,
    median_smooth_motion_scores,
)
from backend.app.services.scene_fingerprints import canonical_fingerprint, canonical_json


VERSION = "autonomous-discovery-v0.1"
TRANSCRIPT_WORK = "TRANSCRIPT_EVIDENCE"
AUDIO_WORK = "AUDIO_EVIDENCE"
VISUAL_WORK = "VISUAL_EVIDENCE"
PROMOTION_WORK = "AUTONOMOUS_PROMOTION"


class AutonomousDiscoveryError(RuntimeError):
    """Safe application-level autonomous discovery failure."""


class AnalysisUnitType(str, Enum):
    TRANSCRIPT_SEGMENT = "TRANSCRIPT_SEGMENT"
    TRANSCRIPT_BLOCK = "TRANSCRIPT_BLOCK"
    AUDIO_ACTIVITY = "AUDIO_ACTIVITY"
    SILENCE = "SILENCE"
    VISUAL_ACTIVITY = "VISUAL_ACTIVITY"
    STATIC_INTERVAL = "STATIC_INTERVAL"


@dataclass(frozen=True)
class AnalysisInterval:
    source_video_id: UUID
    start_seconds: float
    end_seconds: float
    unit_type: AnalysisUnitType
    producer: str
    producer_version: str
    source_reference: str | None = None

    def __post_init__(self) -> None:
        start = _number(self.start_seconds, "Interval start")
        end = _number(self.end_seconds, "Interval end")
        if start < 0 or start >= end:
            raise ValueError("Analysis interval must have positive in-source duration.")


@dataclass(frozen=True)
class SignalEvidence:
    interval: AnalysisInterval
    modality: SceneEvidenceModality
    evidence_type: str
    payload: dict[str, object]


@dataclass(frozen=True)
class AutonomousConfig:
    transcript_gap_seconds: float = 2.0
    long_silence_seconds: float = 5.0
    static_interval_seconds: float = 5.0
    reaction_cues: tuple[str, ...] = ("우와", "와", "대박", "헐")
    interval_precision: int = 3
    maximum_manifest_intervals: int = 128


DEFAULT_CONFIG = AutonomousConfig()


@dataclass(frozen=True)
class ModalityAnalysis:
    evidences: tuple[SignalEvidence, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromotionProposal:
    start_seconds: float
    end_seconds: float
    rule_id: str
    evidence_indexes: tuple[int, ...]


@dataclass(frozen=True)
class AutonomousDiscoveryResult:
    source_video_id: UUID
    work_item_ids: tuple[UUID, ...]
    candidate_ids: tuple[UUID, ...]
    candidate_intervals: tuple[tuple[float, float], ...]
    evidence_counts: dict[str, int]
    runtime_quality_count: int
    warnings: tuple[str, ...]
    abstained: bool
    reused_candidate_count: int


SignalAnalyzer = Callable[[], ModalityAnalysis]


def analyze_transcript_structure(
    *,
    source_video_id: UUID,
    segments: object,
    duration_seconds: float,
    config: AutonomousConfig = DEFAULT_CONFIG,
) -> ModalityAnalysis:
    validated = _segments(segments, duration_seconds)
    evidence: list[SignalEvidence] = []
    for segment_id, start, end, text in validated:
        normalized = _normalize(text)
        cues = tuple(cue for cue in config.reaction_cues if cue in normalized)
        evidence.append(
            _fact(
                source_video_id,
                start,
                end,
                AnalysisUnitType.TRANSCRIPT_SEGMENT,
                SceneEvidenceModality.TRANSCRIPT,
                "TRANSCRIPT_STRUCTURE",
                {"segment_id": segment_id, "speech_present": True, "duration_seconds": round(end - start, 3)},
                "transcript-structure",
            )
        )
        if cues:
            evidence.append(
                _fact(
                    source_video_id,
                    start,
                    end,
                    AnalysisUnitType.TRANSCRIPT_SEGMENT,
                    SceneEvidenceModality.TRANSCRIPT,
                    "TRANSCRIPT_REACTION_CUE",
                    {"segment_id": segment_id, "cue_ids": list(cues[:4])},
                    "reaction-lexical-cues",
                )
            )
    return ModalityAnalysis(tuple(evidence))


def analyze_audio_wav(
    path: str | Path,
    *,
    source_video_id: UUID,
    duration_seconds: float,
    config: AutonomousConfig = DEFAULT_CONFIG,
) -> ModalityAnalysis:
    frames = read_pcm_frame_dbfs(Path(path), 0.0, duration_seconds, DEFAULT_AUDIO_BOUNDARY_CONFIG.frame_duration_ms)
    if not frames:
        raise AutonomousDiscoveryError("Audio analysis returned no frames.")
    levels = sorted(level if math.isfinite(level) else -96.0 for _, _, level in frames)
    noise_floor = median(levels[: max(1, math.ceil(len(levels) / 2))])
    threshold = min(0.0, noise_floor + DEFAULT_AUDIO_BOUNDARY_CONFIG.energy_margin_db)
    active = tuple(frame for frame in frames if frame[2] >= threshold)
    intervals = build_audio_activity_intervals(
        active,
        selected_start=0.0,
        selected_end=duration_seconds,
        minimum_duration=DEFAULT_AUDIO_BOUNDARY_CONFIG.minimum_activity_duration_seconds,
        maximum_gap=DEFAULT_AUDIO_BOUNDARY_CONFIG.maximum_quiet_gap_seconds,
    )
    activity_ranges = [(item.start_seconds, item.end_seconds) for item in intervals]
    evidence = [
        _fact(
            source_video_id,
            item.start_seconds,
            item.end_seconds,
            AnalysisUnitType.AUDIO_ACTIVITY,
            SceneEvidenceModality.AUDIO,
            "AUDIO_ACTIVITY",
            {"peak_dbfs": round(item.peak_dbfs, 3), "mean_dbfs": round(item.mean_dbfs, 3)},
            "pcm-rms-activity",
        )
        for item in intervals
    ]
    for start, end in _complement(activity_ranges, duration_seconds):
        kind = "LONG_SILENCE" if end - start >= config.long_silence_seconds else "SILENCE"
        modality = SceneEvidenceModality.QUALITY if kind == "LONG_SILENCE" else SceneEvidenceModality.AUDIO
        evidence.append(
            _fact(
                source_video_id,
                start,
                end,
                AnalysisUnitType.SILENCE,
                modality,
                kind,
                {"duration_seconds": round(end - start, 3)},
                "pcm-rms-activity",
            )
        )
    return ModalityAnalysis(tuple(evidence))


def analyze_visual_video(
    path: str | Path,
    *,
    source_video_id: UUID,
    duration_seconds: float,
    config: AutonomousConfig = DEFAULT_CONFIG,
    ffmpeg_executable: str = "ffmpeg",
) -> ModalityAnalysis:
    visual_config = DEFAULT_VISUAL_BOUNDARY_CONFIG
    decoded = extract_grayscale_frames(
        Path(path),
        search_start=0.0,
        search_end=duration_seconds,
        config=visual_config,
        ffmpeg_executable=ffmpeg_executable,
    )
    scores = median_smooth_motion_scores(
        calculate_motion_scores(decoded.frames, search_start=0.0, sample_fps=visual_config.sample_fps),
        visual_config.smoothing_window_frames,
    )
    values = tuple(item.score for item in scores)
    middle = median(values)
    mad = median(abs(value - middle) for value in values)
    threshold = math.nextafter(middle, math.inf) if mad == 0 else middle + visual_config.threshold_mad_multiplier * mad
    intervals, _ = build_visual_activity_intervals(
        tuple(item for item in scores if item.score >= threshold),
        block_start=0.0,
        block_end=duration_seconds,
        sample_fps=visual_config.sample_fps,
        minimum_duration=visual_config.minimum_motion_duration_seconds,
        maximum_gap=visual_config.maximum_quiet_gap_seconds,
    )
    activity_ranges = [(item.start_seconds, item.end_seconds) for item in intervals]
    evidence = [
        _fact(
            source_video_id,
            item.start_seconds,
            item.end_seconds,
            AnalysisUnitType.VISUAL_ACTIVITY,
            SceneEvidenceModality.VISUAL,
            "VISUAL_ACTIVITY",
            {"peak_frame_difference": round(item.peak_score, 6), "mean_frame_difference": round(item.mean_score, 6)},
            "ffmpeg-frame-difference",
        )
        for item in intervals
    ]
    for start, end in _complement(activity_ranges, duration_seconds):
        if end - start < config.static_interval_seconds:
            continue
        evidence.append(
            _fact(
                source_video_id,
                start,
                end,
                AnalysisUnitType.STATIC_INTERVAL,
                SceneEvidenceModality.QUALITY,
                "STATIC_INTERVAL",
                {"duration_seconds": round(end - start, 3)},
                "ffmpeg-frame-difference",
            )
        )
    return ModalityAnalysis(tuple(evidence))


def build_promotion_manifest(
    evidences: Iterable[SignalEvidence],
    *,
    duration_seconds: float,
    config: AutonomousConfig = DEFAULT_CONFIG,
) -> tuple[PromotionProposal, ...]:
    facts = tuple(evidences)
    if len(facts) > config.maximum_manifest_intervals:
        facts = facts[: config.maximum_manifest_intervals]
    drafts: list[PromotionProposal] = []
    for left_index, left in enumerate(facts):
        for right_index in range(left_index + 1, len(facts)):
            right = facts[right_index]
            if left.interval.source_video_id != right.interval.source_video_id:
                continue
            overlap = _overlap(left.interval, right.interval)
            if overlap is None:
                continue
            types = {left.evidence_type, right.evidence_type}
            modalities = {left.modality, right.modality}
            rule = None
            if "TRANSCRIPT_REACTION_CUE" in types and SceneEvidenceModality.AUDIO in modalities:
                rule = "REACTION_CUE_PLUS_AUDIO"
            elif "TRANSCRIPT_STRUCTURE" in types and "AUDIO_ACTIVITY" in types:
                rule = "TRANSCRIPT_STRUCTURE_PLUS_AUDIO"
            elif "AUDIO_ACTIVITY" in types and "VISUAL_ACTIVITY" in types:
                rule = "AUDIO_PLUS_VISUAL_ACTIVITY"
            if rule:
                start, end = (_quantize(value, config.interval_precision) for value in overlap)
                if 0 <= start < end <= duration_seconds:
                    drafts.append(PromotionProposal(start, end, rule, (left_index, right_index)))
    result: list[PromotionProposal] = []
    seen: set[tuple[float, float]] = set()
    for proposal in sorted(drafts, key=lambda item: (item.start_seconds, item.end_seconds, item.rule_id)):
        key = (proposal.start_seconds, proposal.end_seconds)
        if key not in seen:
            seen.add(key)
            result.append(proposal)
    return tuple(result)


def process_autonomous_discovery(
    session: Session,
    source_video_id: UUID,
    *,
    audio_analyzer: SignalAnalyzer | None = None,
    visual_analyzer: SignalAnalyzer | None = None,
    config: AutonomousConfig = DEFAULT_CONFIG,
) -> AutonomousDiscoveryResult:
    source = session.get(SourceVideo, source_video_id)
    if source is None or source.duration_seconds is None:
        raise AutonomousDiscoveryError("Source or source duration is unavailable.")
    duration = float(source.duration_seconds)
    modality_specs = _modality_specs(source, config)
    analyses: list[tuple[str, ModalityAnalysis | None, str | None, str, str]] = []
    analyzers: dict[str, tuple[SignalAnalyzer | None, str]] = {
        AUDIO_WORK: (audio_analyzer, "AUDIO_UNAVAILABLE"),
        VISUAL_WORK: (visual_analyzer, "VISUAL_UNAVAILABLE"),
    }
    for work_type in (TRANSCRIPT_WORK, AUDIO_WORK, VISUAL_WORK):
        modality_input, modality_config = modality_specs[work_type]
        cached = _cached_modality_work(
            session, source.id, work_type, modality_input, modality_config
        )
        cached_analysis = _decode_analysis(cached.result_reference) if cached else None
        if cached is not None and cached_analysis is not None:
            analyses.append((work_type, cached_analysis, None, modality_input, modality_config))
            continue
        if work_type == TRANSCRIPT_WORK:
            if source.transcript is None:
                analyses.append((work_type, None, "TRANSCRIPT_UNAVAILABLE", modality_input, modality_config))
            else:
                try:
                    result = analyze_transcript_structure(
                        source_video_id=source.id,
                        segments=source.transcript.segments,
                        duration_seconds=duration,
                        config=config,
                    )
                    analyses.append((work_type, result, None, modality_input, modality_config))
                except Exception:
                    analyses.append((work_type, None, "TRANSCRIPT_ANALYSIS_FAILED", modality_input, modality_config))
            continue
        analyzer, unavailable = analyzers[work_type]
        if analyzer is None:
            analyses.append((work_type, None, unavailable, modality_input, modality_config))
        else:
            try:
                analyses.append((work_type, analyzer(), None, modality_input, modality_config))
            except Exception:
                analyses.append((work_type, None, f"{work_type}_FAILED", modality_input, modality_config))
    if all(result is None for _, result, _, _, _ in analyses):
        raise AutonomousDiscoveryError("All autonomous modalities failed or were unavailable.")

    work_items: list[SceneAnalysisWorkItem] = []
    warnings: list[str] = []
    facts: list[SignalEvidence] = []
    modality_result_fingerprints: dict[str, str] = {}
    for work_type, result, warning, modality_input, modality_config in analyses:
        cached = _cached_modality_work(
            session, source.id, work_type, modality_input, modality_config
        )
        if cached is not None and result is not None:
            work = cached
        else:
            work, _ = _record_work(
                session,
                source,
                work_type,
                modality_input,
                modality_config,
                analysis=result,
                warning=warning,
            )
        work_items.append(work)
        modality_result_fingerprints[work_type] = work.result_fingerprint or canonical_fingerprint(
            {"work_type": work_type, "warning": warning}
        )
        if result:
            facts.extend(result.evidences)
            warnings.extend(result.warnings)
        if warning:
            warnings.append(warning)

    input_fingerprint = canonical_fingerprint(
        {"modality_results": modality_result_fingerprints}
    )
    config_fingerprint = canonical_fingerprint(
        {
            "interval_precision": config.interval_precision,
            "maximum_manifest_intervals": config.maximum_manifest_intervals,
            "promotion_version": VERSION,
        }
    )
    existing = session.scalar(
        select(SceneAnalysisWorkItem).where(
            SceneAnalysisWorkItem.source_video_id == source.id,
            SceneAnalysisWorkItem.work_type == PROMOTION_WORK,
            SceneAnalysisWorkItem.input_fingerprint == input_fingerprint,
            SceneAnalysisWorkItem.config_fingerprint == config_fingerprint,
            SceneAnalysisWorkItem.status == SceneAnalysisWorkStatus.COMPLETED,
        )
    )
    if existing:
        candidate_ids = tuple(
            session.scalars(
                select(SceneAnalysisWorkResultCandidate.scene_candidate_id)
                .where(SceneAnalysisWorkResultCandidate.work_item_id == existing.id)
                .order_by(SceneAnalysisWorkResultCandidate.scene_candidate_id)
            )
        )
        candidates = tuple(session.get(SceneCandidate, item) for item in candidate_ids)
        candidates = tuple(item for item in candidates if item is not None)
        return AutonomousDiscoveryResult(source.id, tuple(item.id for item in work_items) + (existing.id,), tuple(item.id for item in candidates), tuple((float(item.start_seconds), float(item.end_seconds)) for item in candidates), {}, 0, ("IDEMPOTENT_REUSE",), not candidates, len(candidates))

    promotion, promotion_attempt = _start_work(session, source, PROMOTION_WORK, input_fingerprint, config_fingerprint)
    work_items.append(promotion)
    session.commit()
    try:
        proposals = build_promotion_manifest(facts, duration_seconds=duration, config=config)
        candidate_ids: list[UUID] = []
        intervals: list[tuple[float, float]] = []
        reused_count = 0
        for proposal in proposals:
            candidate, reused = _promote(session, source, promotion, proposal, facts, input_fingerprint, config_fingerprint)
            if session.get(
                SceneAnalysisWorkResultCandidate, (promotion.id, candidate.id)
            ) is None:
                session.add(
                    SceneAnalysisWorkResultCandidate(
                        work_item_id=promotion.id, scene_candidate_id=candidate.id
                    )
                )
            candidate_ids.append(candidate.id)
            intervals.append((float(candidate.start_seconds), float(candidate.end_seconds)))
            reused_count += int(reused)
        promotion.status = SceneAnalysisWorkStatus.COMPLETED
        promotion.result_reference = f"autonomous:candidates:{len(candidate_ids)}"
        promotion.result_fingerprint = _fingerprint({"candidate_ids": [str(value) for value in candidate_ids], "warnings": sorted(warnings)})
        promotion_attempt.status = SceneAnalysisAttemptStatus.COMPLETED
        promotion_attempt.completed_at = datetime.now(timezone.utc)
        session.commit()
    except Exception as exc:
        session.rollback()
        promotion = session.get(SceneAnalysisWorkItem, promotion.id)
        promotion_attempt = session.get(SceneAnalysisAttempt, promotion_attempt.id)
        promotion.status = SceneAnalysisWorkStatus.FAILED
        promotion_attempt.status = SceneAnalysisAttemptStatus.FAILED
        promotion_attempt.completed_at = datetime.now(timezone.utc)
        promotion_attempt.safe_error_code = "AUTONOMOUS_PROMOTION_FAILED"
        promotion_attempt.safe_error_message = "Autonomous promotion failed."
        session.commit()
        raise AutonomousDiscoveryError("Autonomous promotion failed.") from exc

    counts: dict[str, int] = {}
    for fact in facts:
        counts[fact.modality.value] = counts.get(fact.modality.value, 0) + 1
    quality_count = sum(fact.modality is SceneEvidenceModality.QUALITY for fact in facts)
    return AutonomousDiscoveryResult(source.id, tuple(item.id for item in work_items), tuple(candidate_ids), tuple(intervals), counts, quality_count, tuple(sorted(set(warnings))), not candidate_ids, reused_count)


def _promote(session, source, work, proposal, facts, input_fingerprint, config_fingerprint):
    candidate = session.scalar(
        select(SceneCandidate).where(
            SceneCandidate.source_video_id == source.id,
            SceneCandidate.start_seconds == proposal.start_seconds,
            SceneCandidate.end_seconds == proposal.end_seconds,
        )
    )
    reused = candidate is not None
    if candidate is None:
        candidate = SceneCandidate(source_video_id=source.id, analysis_work_item_id=work.id, start_seconds=proposal.start_seconds, end_seconds=proposal.end_seconds, discovery_method=SceneDiscoveryMethod.AUTONOMOUS, confidence=None, input_fingerprint=input_fingerprint, result_fingerprint=_fingerprint(asdict(proposal)))
        session.add(candidate)
        session.flush()
    source_reference = f"autonomous-work:{work.id}"
    existing = set(session.scalars(select(SceneEvidence.result_fingerprint).where(SceneEvidence.scene_candidate_id == candidate.id, SceneEvidence.source_reference == source_reference)))
    selected_facts = [
        fact
        for fact in facts
        if _overlap(
            fact.interval,
            AnalysisInterval(
                source.id,
                proposal.start_seconds,
                proposal.end_seconds,
                fact.interval.unit_type,
                "promotion-manifest",
                VERSION,
            ),
        )
        is not None
    ]
    for fact in selected_facts:
        payload = dict(fact.payload)
        payload["promotion_rule"] = proposal.rule_id
        result_fingerprint = _fingerprint({"type": fact.evidence_type, "interval": [proposal.start_seconds, proposal.end_seconds], "payload": payload})
        if result_fingerprint in existing:
            continue
        session.add(SceneEvidence(scene_candidate_id=candidate.id, modality=fact.modality, evidence_type=fact.evidence_type, start_seconds=fact.interval.start_seconds, end_seconds=fact.interval.end_seconds, confidence=None, payload=payload, payload_schema_version="1", producer="autonomous-discovery", producer_version=VERSION, source_reference=source_reference, input_fingerprint=input_fingerprint, config_fingerprint=config_fingerprint, result_fingerprint=result_fingerprint))
    return candidate, reused


def _record_work(session, source, work_type, input_fingerprint, config_fingerprint, *, analysis, warning):
    work, attempt = _start_work(session, source, work_type, input_fingerprint, config_fingerprint)
    now = datetime.now(timezone.utc)
    if analysis is not None:
        work.status = SceneAnalysisWorkStatus.COMPLETED
        manifest = _analysis_manifest(analysis)
        work.result_reference = _encode_analysis(manifest)
        work.result_fingerprint = canonical_fingerprint(manifest)
        attempt.status = SceneAnalysisAttemptStatus.COMPLETED
    else:
        work.status = SceneAnalysisWorkStatus.FAILED
        attempt.status = SceneAnalysisAttemptStatus.FAILED
        attempt.safe_error_code = warning
        attempt.safe_error_message = "Autonomous modality was unavailable or failed."
    attempt.completed_at = now
    session.flush()
    return work, attempt


def _modality_specs(source, config):
    transcript_result = canonical_fingerprint(source.transcript.segments) if source.transcript else "TRANSCRIPT_UNAVAILABLE"
    return {
        TRANSCRIPT_WORK: (
            canonical_fingerprint({"transcript": transcript_result}),
            canonical_fingerprint({
                "transcript_gap_seconds": config.transcript_gap_seconds,
                "reaction_cues": config.reaction_cues,
                "interval_precision": config.interval_precision,
            }),
        ),
        AUDIO_WORK: (
            canonical_fingerprint({"source": source.fingerprint}),
            canonical_fingerprint({
                "long_silence_seconds": config.long_silence_seconds,
                "interval_precision": config.interval_precision,
                "audio_primitive": asdict(DEFAULT_AUDIO_BOUNDARY_CONFIG),
            }),
        ),
        VISUAL_WORK: (
            canonical_fingerprint({"source": source.fingerprint}),
            canonical_fingerprint({
                "static_interval_seconds": config.static_interval_seconds,
                "interval_precision": config.interval_precision,
                "visual_primitive": asdict(DEFAULT_VISUAL_BOUNDARY_CONFIG),
            }),
        ),
    }


def _cached_modality_work(session, source_id, work_type, input_fingerprint, config_fingerprint):
    return session.scalar(
        select(SceneAnalysisWorkItem)
        .where(
            SceneAnalysisWorkItem.source_video_id == source_id,
            SceneAnalysisWorkItem.work_type == work_type,
            SceneAnalysisWorkItem.input_fingerprint == input_fingerprint,
            SceneAnalysisWorkItem.config_fingerprint == config_fingerprint,
            SceneAnalysisWorkItem.status == SceneAnalysisWorkStatus.COMPLETED,
            SceneAnalysisWorkItem.result_fingerprint.is_not(None),
        )
        .order_by(SceneAnalysisWorkItem.created_at.desc())
    )


def _analysis_manifest(analysis):
    return {
        "schema": "autonomous-modality-result-v0.1",
        "evidences": [
            {
                "interval": {
                    "source_video_id": str(fact.interval.source_video_id),
                    "start_seconds": fact.interval.start_seconds,
                    "end_seconds": fact.interval.end_seconds,
                    "unit_type": fact.interval.unit_type.value,
                    "producer": fact.interval.producer,
                    "producer_version": fact.interval.producer_version,
                },
                "modality": fact.modality.value,
                "evidence_type": fact.evidence_type,
                "payload": fact.payload,
            }
            for fact in sorted(
                analysis.evidences,
                key=lambda item: (
                    item.interval.start_seconds,
                    item.interval.end_seconds,
                    item.modality.value,
                    item.evidence_type,
                ),
            )
        ],
        "warnings": sorted(analysis.warnings),
    }


def _decode_analysis(value):
    try:
        if value and value.startswith("zlib:"):
            payload = json.loads(
                zlib.decompress(base64.b64decode(value[5:])).decode("utf-8")
            )
        else:
            payload = json.loads(value or "")
        if payload.get("schema") != "autonomous-modality-result-v0.1":
            return None
        facts = []
        for item in payload["evidences"]:
            interval = item["interval"]
            facts.append(
                SignalEvidence(
                    AnalysisInterval(
                        UUID(interval["source_video_id"]),
                        float(interval["start_seconds"]),
                        float(interval["end_seconds"]),
                        AnalysisUnitType(interval["unit_type"]),
                        str(interval["producer"]),
                        str(interval["producer_version"]),
                    ),
                    SceneEvidenceModality(item["modality"]),
                    str(item["evidence_type"]),
                    dict(item["payload"]),
                )
            )
        return ModalityAnalysis(tuple(facts), tuple(payload.get("warnings", ())))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, zlib.error, binascii.Error):
        return None


def _encode_analysis(manifest):
    raw = canonical_json(manifest).encode("utf-8")
    encoded = "zlib:" + base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
    if len(encoded) > 1024:
        raise AutonomousDiscoveryError("Bounded modality result manifest is too large.")
    return encoded


def _start_work(session, source, work_type, input_fingerprint, config_fingerprint):
    work = SceneAnalysisWorkItem(project_id=source.project_id, source_video_id=source.id, work_type=work_type, status=SceneAnalysisWorkStatus.RUNNING, input_fingerprint=input_fingerprint, producer="autonomous-discovery", producer_version=VERSION, config_fingerprint=config_fingerprint)
    attempt = SceneAnalysisAttempt(work_item=work, attempt_number=1, status=SceneAnalysisAttemptStatus.RUNNING, started_at=datetime.now(timezone.utc))
    session.add_all([work, attempt])
    session.flush()
    return work, attempt


def _fact(source_id, start, end, unit_type, modality, evidence_type, payload, producer):
    return SignalEvidence(AnalysisInterval(source_id, start, end, unit_type, producer, VERSION), modality, evidence_type, payload)


def _segments(segments: object, duration: float):
    if not isinstance(segments, list):
        raise ValueError("Transcript segments must be a list.")
    result = []
    previous_end = 0.0
    for index, item in enumerate(segments, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("Transcript segment is malformed.")
        start, end = _number(item.get("start_seconds"), "Segment start"), _number(item.get("end_seconds"), "Segment end")
        if start < previous_end or start < 0 or start >= end or end > duration:
            raise ValueError("Transcript segment interval is invalid.")
        result.append((f"segment-{index:04d}", start, end, item["text"].strip()))
        previous_end = end
    return result


def _normalize(text: str) -> str:
    return "".join(re.findall(r"[0-9A-Za-z가-힣]+", text.casefold()))


def _overlap(left: AnalysisInterval, right: AnalysisInterval):
    start, end = max(left.start_seconds, right.start_seconds), min(left.end_seconds, right.end_seconds)
    return (start, end) if start < end else None


def _complement(intervals: list[tuple[float, float]], duration: float):
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([max(0.0, start), min(duration, end)])
        else:
            merged[-1][1] = max(merged[-1][1], min(duration, end))
    result = []
    cursor = 0.0
    for start, end in merged:
        if cursor < start:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        result.append((cursor, duration))
    return tuple(result)


def _quantize(value: float, precision: int) -> float:
    return round(float(value), precision)


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number
