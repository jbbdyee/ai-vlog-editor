"""VLM scene understanding: per-candidate visual caption + tags, stored as non-authoritative SceneEvidence.

The VLM only describes what is visible in three frames (10/50/90 %) of an existing candidate
interval. It never chooses timestamps, candidates or the final plan; Python owns the interval, the
frames, validation (Pydantic) and persistence. Reuses ``attach_representative_frames``.

v0.2: the three frames are sent as separate images instead of one 1536x288 contact-sheet strip
(small subjects were downscaled away: a distant border collie was read as a cow), the prompt asks
for "동물" instead of guessing a species, and the VLM also returns coarse visual ``categories`` that
Python matches against request words ("음식", "동물", "풍경").
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from time import perf_counter
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import SceneCandidate, SceneEvidence, SceneEvidenceModality
from backend.app.services.scene_boundary_proposals import ProposalKind, SceneBoundaryProposal, attach_representative_frames

EVIDENCE_TYPE = "VLM_SCENE_CAPTION"
PRODUCER = "vlm-scene-captioner"
PRODUCER_VERSION = "v0.2"
DEFAULT_MODEL = "gemma3:4b"
TIMEOUT_SECONDS = 120.0

PROMPT = (
    "이 이미지들은 같은 영상 장면의 프레임 3장(시간 순서)이다. 화면에 실제로 보이는 것만 근거로 답하라. "
    "작게 보이는 대상도 확대해서 살펴보라. 동물의 종류가 확실하지 않으면 '동물'이라고 쓰고 추측하지 마라. 대사 내용은 쓰지 마라. "
    "caption: 장면을 설명하는 한국어 한 문장(40자 이내). "
    "tags: 화면에 보이는 핵심 사물·장소·동물·음식을 한국어 명사로 3~6개. "
    "categories: 화면에 분명히 보이는 분류를 음식(먹는 것)·음료(마시는 것)·동물·자연풍경·거리·실내·사람 중에서 모두 고른다. "
    "place: 실내/야외/알수없음 중 하나. mood: 분위기 하나. people_visible: 사람이 보이면 true. JSON만 출력하라."
)


class VLMSceneCaption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caption: str = Field(min_length=2, max_length=120)
    tags: list[str] = Field(min_length=1, max_length=8)
    categories: list[Literal["음식", "음료", "동물", "자연풍경", "거리", "실내", "사람"]] = Field(default_factory=list, max_length=7)
    place: Literal["실내", "야외", "알수없음"] = "알수없음"
    mood: Literal["잔잔함", "아늑함", "활기참", "감성적", "재미있음", "기타"] = "기타"
    people_visible: bool = False

    @field_validator("categories")
    @classmethod
    def _unique_categories(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(tag.strip()[:20] for tag in value if tag and tag.strip()))
        if not cleaned:
            raise ValueError("at least one non-empty tag")
        return cleaned


@dataclass(frozen=True)
class CaptionResult:
    caption: VLMSceneCaption
    latency_seconds: float
    frame_timestamps: tuple[float, ...]
    sheet_sha256: str
    model: str


class VLMCaptionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def vlm_model() -> str:
    return os.environ.get("CUTORY_VLM_MODEL") or DEFAULT_MODEL


def caption_interval(source_path: Path, start: float, end: float, *, model: str | None = None,
                     base_url: str | None = None, ffmpeg: str = "ffmpeg") -> CaptionResult:
    model = model or vlm_model()
    base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    proposal = SceneBoundaryProposal("scene", ProposalKind.RAW_BLOCK, float(start), float(end), "scene", (), (), (), ())
    try:
        framed = attach_representative_frames(source_path, (proposal,), ffmpeg_executable=ffmpeg)[0]
    except Exception as error:  # frame extraction / FFmpeg problems
        raise VLMCaptionError("VLM_FRAMES_FAILED") from error
    started = perf_counter()
    try:
        response = httpx.post(f"{base_url}/api/chat", timeout=TIMEOUT_SECONDS, json={
            "model": model, "stream": False, "format": VLMSceneCaption.model_json_schema(),
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT,
                          "images": [base64.b64encode(sample.jpeg_bytes).decode() for sample in framed.frame_samples]}]})
    except httpx.TimeoutException as error:
        raise VLMCaptionError("VLM_TIMEOUT") from error
    except httpx.HTTPError as error:
        raise VLMCaptionError("VLM_UNAVAILABLE") from error
    latency = perf_counter() - started
    if response.status_code != 200:
        raise VLMCaptionError("VLM_HTTP_ERROR")
    try:
        caption = VLMSceneCaption.model_validate_json(response.json()["message"]["content"])
    except (ValueError, KeyError, TypeError, ValidationError) as error:
        raise VLMCaptionError("VLM_SCHEMA_INVALID") from error
    frames = b"".join(sample.jpeg_bytes for sample in framed.frame_samples)
    return CaptionResult(caption, round(latency, 2), tuple(s.timestamp_seconds for s in framed.frame_samples),
                         hashlib.sha256(frames).hexdigest(), model)


def existing_caption(session: Session, candidate_id, model: str) -> SceneEvidence | None:
    return session.scalars(select(SceneEvidence).where(
        SceneEvidence.scene_candidate_id == candidate_id, SceneEvidence.evidence_type == EVIDENCE_TYPE,
        SceneEvidence.source_reference == _reference(model))).first()


def _reference(model: str) -> str:
    return f"vlm:{model}:{PRODUCER_VERSION}"


def store_caption(session: Session, candidate: SceneCandidate, result: CaptionResult) -> SceneEvidence:
    """Persist as non-authoritative VISUAL evidence over the candidate's own (Python-owned) interval."""
    payload = {"caption": result.caption.caption, "tags": result.caption.tags, "categories": result.caption.categories,
               "place": result.caption.place,
               "mood": result.caption.mood, "people_visible": result.caption.people_visible, "model": result.model,
               "frame_timestamps": list(result.frame_timestamps), "latency_seconds": result.latency_seconds,
               "authoritative": False}
    evidence = SceneEvidence(
        scene_candidate_id=candidate.id, modality=SceneEvidenceModality.VISUAL, evidence_type=EVIDENCE_TYPE,
        start_seconds=candidate.start_seconds, end_seconds=candidate.end_seconds, confidence=None, payload=payload,
        payload_schema_version="1", producer=PRODUCER, producer_version=PRODUCER_VERSION,
        source_reference=_reference(result.model), input_fingerprint=result.sheet_sha256,
        config_fingerprint=hashlib.sha256(f"{PRODUCER_VERSION}|{result.model}|{PROMPT}".encode()).hexdigest(),
        result_fingerprint=hashlib.sha256(repr(sorted(payload.items())).encode()).hexdigest())
    session.add(evidence)
    return evidence
