"""Project-wide recommended edit direction: group the scenes of all videos into a short story outline.

The LLM only *proposes* chapters (title, description, reason, scene numbers in play order). Scene numbers
are restricted to real candidates and re-checked here (unknown -> reject, duplicates -> first chapter wins,
empty chapters dropped). If no LLM is configured or anything fails, a rule-based outline is returned
(one chapter per video, file order), so the screen always has something to show. Nothing is saved.
File names are never sent to the LLM; videos are referred to as "영상 1, 2, ...".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import SourceVideo
from backend.app.services.llm_edit_interpreter import (EVIDENCE_LABELS, Completion, LLMEditError,
                                                       configured_engine)
from backend.app.services.project_scene_candidates import ActiveCandidateSummary, list_active_project_candidates

MAX_CHAPTERS = 6


class LLMChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=40, description="챕터 제목(한국어, 짧게)")
    description: str = Field(min_length=1, max_length=160, description="이 챕터에서 보여줄 내용")
    reason: str = Field(min_length=1, max_length=160, description="이 장면들을 이 순서로 묶은 이유")
    scenes: list[int] = Field(min_length=1, max_length=60, description="이 챕터에 넣을 장면 번호, 재생 순서대로")


class LLMStoryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=60, description="브이로그 전체 제목")
    summary: str = Field(min_length=1, max_length=240, description="전체 흐름을 한두 문장으로")
    chapters: list[LLMChapter] = Field(min_length=1, max_length=MAX_CHAPTERS)
    recommended_minutes: int | None = Field(default=None, ge=1, le=60, description="이 영상에 알맞은 완성 길이(분)")
    length_reason: str | None = Field(default=None, max_length=160, description="그 길이를 추천한 이유")


@dataclass(frozen=True)
class StoryScene:
    candidate: ActiveCandidateSummary
    source_index: int  # 1-based video number in file order
    source_filename: str


@dataclass(frozen=True)
class StoryChapter:
    title: str
    description: str
    reason: str
    scenes: tuple[StoryScene, ...]

    @property
    def total_seconds(self) -> float:
        return round(sum(float(s.candidate.end_seconds - s.candidate.start_seconds) for s in self.scenes), 3)


@dataclass(frozen=True)
class StoryDirection:
    title: str
    summary: str
    chapters: tuple[StoryChapter, ...]
    engine: str
    notes: tuple[str, ...] = ()
    fallback_reason: str | None = None
    recommended_minutes: int | None = None
    length_reason: str | None = None


SYSTEM_PROMPT = (
    "너는 브이로그 편집 감독이다. 여러 촬영 영상에서 찾은 장면 목록(번호, 영상 번호, 시간, 대사, AI가 본 화면 설명)을 받는다. "
    "이 장면들로 하나의 브이로그를 만든다면 어떤 순서로 어떤 이야기를 보여줄지 추천 편집 방향을 제안하라. "
    "챕터를 3~6개 만들되 장면이 적으면 더 적게 만든다. 각 챕터에는 짧은 제목, 보여줄 내용(description), "
    "그렇게 묶고 배치한 이유(reason), 재생 순서대로 장면 번호(scenes)를 적는다. "
    "한 장면은 한 챕터에만 넣고, 이야기에 맞지 않는 장면은 빼도 된다. 챕터 순서가 곧 영상의 흐름이다. "
    "보통은 시작(도착·준비) → 전개(주요 활동) → 마무리(정리·소감) 흐름이 자연스럽다. "
    "화면 설명이 없으면 대사와 시간 순서로 판단하고, 대사도 없으면 촬영 순서를 따른다. "
    "장면은 나중에 앞뒤로 넓혀서 쓰므로, 이야기에 쓸 만한 장면은 되도록 많이 넣는다. "
    "영상 내용과 목적을 보고 완성 영상에 알맞은 길이를 분 단위로 recommended_minutes에, 그 이유를 length_reason에 적는다 "
    "(보통 원본의 1/5~1/3, 예: 30분짜리 레슨은 5~10분). "
    "목록에 있는 번호만 쓴다. 모든 글은 한국어로 쓴다. JSON만 출력하라."
)


def load_story_inputs(session: Session, project_id: UUID) -> tuple[tuple[ActiveCandidateSummary, ...], dict[UUID, str]]:
    """Active candidates plus the file name of every source in the project (raises SceneProjectNotFoundError)."""
    candidates = list_active_project_candidates(session, project_id)
    names = dict(session.execute(
        select(SourceVideo.id, SourceVideo.original_filename).where(SourceVideo.project_id == project_id)).all())
    return candidates, names


def _ordered_scenes(candidates: Sequence[ActiveCandidateSummary], filenames: dict[UUID, str]) -> list[StoryScene]:
    source_ids = sorted({c.source_video_id for c in candidates},
                        key=lambda sid: ((filenames.get(sid) or "").casefold(), str(sid)))
    index = {sid: number for number, sid in enumerate(source_ids, start=1)}
    ordered = sorted(candidates, key=lambda c: (index[c.source_video_id], float(c.start_seconds), float(c.end_seconds)))
    return [StoryScene(c, index[c.source_video_id], filenames.get(c.source_video_id) or "이름 없는 영상") for c in ordered]


def _scene_table(scenes: Sequence[StoryScene]) -> str:
    rows, current = [], None
    for number, item in enumerate(scenes, start=1):
        if item.source_index != current:
            current = item.source_index
            rows.append(f"[영상 {current}]")
        c = item.candidate
        start, end = float(c.start_seconds), float(c.end_seconds)
        evidence = ", ".join(sorted({EVIDENCE_LABELS[e.evidence_type] for e in c.evidence if e.evidence_type in EVIDENCE_LABELS}))
        visual = (f" | 화면: {c.visual_caption} [{', '.join(c.visual_tags)}]") if c.visual_caption else ""
        rows.append(f"{number}. 영상 {item.source_index} {start:.1f}~{end:.1f}초 (길이 {end - start:.1f}초) | "
                    f"대사: {c.transcript_text or '(없음)'}{visual} | 근거: {evidence or '-'}")
    return "\n".join(rows)


def _constrained_schema(count: int) -> dict:
    schema = LLMStoryPlan.model_json_schema()
    schema["$defs"]["LLMChapter"]["properties"]["scenes"]["items"] = {"type": "integer", "enum": list(range(1, count + 1))}
    # Ask the model for a length every time; validation still accepts an answer without one (rule fallback).
    schema["properties"]["recommended_minutes"] = {"type": "integer", "minimum": 1, "maximum": 60}
    schema["properties"]["length_reason"] = {"type": "string", "maxLength": 160}
    schema["required"] = [*schema.get("required", []), "recommended_minutes", "length_reason"]
    return schema


class _PlanRejected(ValueError):
    pass


def _apply(plan: LLMStoryPlan, scenes: Sequence[StoryScene]) -> tuple[tuple[StoryChapter, ...], tuple[str, ...]]:
    count = len(scenes)
    if any(n < 1 or n > count for chapter in plan.chapters for n in chapter.scenes):
        raise _PlanRejected("LLM_UNKNOWN_SCENE")
    used: set[int] = set()
    chapters, duplicates = [], 0
    for chapter in plan.chapters:
        numbers = []
        for n in chapter.scenes:
            if n in used:
                duplicates += 1
                continue
            used.add(n)
            numbers.append(n)
        if numbers:
            chapters.append(StoryChapter(chapter.title.strip(), chapter.description.strip(), chapter.reason.strip(),
                                         tuple(scenes[n - 1] for n in numbers)))
    if not chapters:
        raise _PlanRejected("LLM_EMPTY_SELECTION")
    notes = []
    if duplicates:
        notes.append(f"여러 챕터에 겹친 장면 {duplicates}개는 처음 챕터에만 남겼습니다.")
    if len(used) < count:
        notes.append(f"추천 흐름에 넣지 않은 장면이 {count - len(used)}개 있습니다.")
    return tuple(chapters), tuple(notes)


def _rule_direction(scenes: Sequence[StoryScene], note: str, fallback_reason: str | None) -> StoryDirection:
    chapters = []
    for index in sorted({s.source_index for s in scenes}):
        group = tuple(s for s in scenes if s.source_index == index)
        seconds = sum(float(s.candidate.end_seconds - s.candidate.start_seconds) for s in group)
        chapters.append(StoryChapter(f"영상 {index}: {group[0].source_filename}",
                                     f"장면 {len(group)}개, 약 {seconds:.0f}초",
                                     "촬영 파일 순서대로 묶었습니다.", group))
    return StoryDirection("촬영 순서대로 보기", "영상 파일 순서대로 장면을 이어 붙인 기본 흐름입니다.",
                          tuple(chapters), "rule", (note,), fallback_reason)


def rebuild_direction(candidates: Sequence[ActiveCandidateSummary], filenames: dict[UUID, str], *, title: str,
                      summary: str, engine: str, chapters: Sequence[tuple[str, str, str, Sequence[UUID]]],
                      notes: Sequence[str] = (), recommended_minutes: int | None = None,
                      length_reason: str | None = None) -> StoryDirection:
    """Re-creates an earlier recommendation from its scene IDs, without asking the AI again (length change only)."""
    by_id = {s.candidate.candidate_id: s for s in _ordered_scenes(candidates, filenames)}
    used: set[UUID] = set()
    rebuilt, missing = [], 0
    for chapter_title, description, reason, candidate_ids in chapters:
        scenes = []
        for candidate_id in candidate_ids:
            if candidate_id in used:
                continue
            if candidate_id not in by_id:
                missing += 1
                continue
            used.add(candidate_id)
            scenes.append(by_id[candidate_id])
        if scenes:
            rebuilt.append(StoryChapter(chapter_title, description, reason, tuple(scenes)))
    if not rebuilt:
        raise ValueError("No scene of the earlier recommendation is still available.")
    extra = (f"지금은 없는 장면 {missing}개를 뺐습니다.",) if missing else ()
    return StoryDirection(title, summary, tuple(rebuilt), engine, tuple(notes) + extra, None,
                          recommended_minutes, length_reason)


def recommend_story_direction(candidates: Sequence[ActiveCandidateSummary], filenames: dict[UUID, str],
                              engine: tuple[str, str, Completion] | None = None,
                              footage_minutes: float | None = None) -> StoryDirection:
    scenes = _ordered_scenes(candidates, filenames)
    engine = engine if engine is not None else configured_engine()
    if engine is None:
        return _rule_direction(scenes, "AI 설정이 없어 영상 순서대로 묶었습니다.", None)
    provider, model, complete = engine
    try:
        footage = f"원본 영상 전체 길이: 약 {footage_minutes:.0f}분\n" if footage_minutes else ""
        raw = complete(SYSTEM_PROMPT, f"{footage}장면 목록(번호 1~{len(scenes)}, 영상 {len({s.source_index for s in scenes})}개):\n"
                                      f"{_scene_table(scenes)}", _constrained_schema(len(scenes)))
        plan = LLMStoryPlan.model_validate_json(raw)
        chapters, notes = _apply(plan, scenes)
        return StoryDirection(plan.title.strip(), plan.summary.strip(), chapters, f"llm:{provider}/{model}", notes,
                              None, plan.recommended_minutes, (plan.length_reason or "").strip() or None)
    except LLMEditError as error:
        reason = error.code
    except ValidationError:
        reason = "LLM_SCHEMA_INVALID"
    except _PlanRejected as error:
        reason = str(error)
    return _rule_direction(scenes, "AI 추천을 만들지 못해 영상 순서대로 묶었습니다.", reason)
