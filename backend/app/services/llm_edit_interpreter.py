"""LLM interpretation of a natural-language edit request into a validated scene suggestion.

The LLM only *proposes* (numbered scenes to include/exclude, order, target length, mood, reasons).
Everything it returns is validated with Pydantic and then re-checked deterministically against the
active candidates (unknown numbers, exclusions, length cap). Any failure falls back to the existing
rule-based ``suggest_edit``. Nothing is saved: the user still applies and saves the plan.

Providers (``CUTORY_EDIT_LLM_PROVIDER``): ``ollama`` (local, default model ``gemma3:4b``; scene text
never leaves the machine) or ``openai`` (``OPENAI_API_KEY``/``OPENAI_MODEL``). Unset/other = rule only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
import re
from typing import Callable, Literal, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.services.edit_request import (EditRequestIntent, EditSuggestion, SuggestedScene, _matches, _stem,
                                                parse_edit_request, suggest_edit)
from backend.app.services.project_scene_candidates import ActiveCandidateSummary

DEFAULT_OLLAMA_MODEL = "gemma3:4b"
TIMEOUT_SECONDS = 90.0
EVIDENCE_LABELS = {"TRANSCRIPT_REACTION_CUE": "리액션 발화", "TRANSCRIPT_STRUCTURE": "말하는 구간",
                   "AUDIO_ACTIVITY": "소리 활동", "VISUAL_ACTIVITY": "화면 움직임"}


class SceneReason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene: int = Field(ge=1, le=500)
    reason: str = Field(min_length=1, max_length=80)


class LLMEditPlan(BaseModel):
    """Structured interpretation the LLM must return (validated; extra keys rejected)."""
    model_config = ConfigDict(extra="forbid")
    interpretation: str = Field(min_length=1, max_length=200, description="요청을 한 문장으로 요약한 한국어 해석")
    selected_scenes: list[int] = Field(max_length=50, description="최종 영상에 넣을 장면 번호, 재생 순서대로")
    excluded_scenes: list[int] = Field(default_factory=list, max_length=50, description="요청 때문에 뺀 장면 번호")
    target_seconds: float | None = Field(default=None, gt=0, le=3600, description="요청한 목표 길이(초), 없으면 null")
    mood: Literal["any", "calm", "cozy", "lively", "emotional", "fun"] = "any"
    order: Literal["chronological", "reverse", "custom"] = "chronological"
    reasons: list[SceneReason] = Field(default_factory=list, max_length=50)


@dataclass(frozen=True)
class LLMEditResult:
    suggestion: EditSuggestion
    engine: str
    interpretation: str | None = None
    mood: str | None = None
    fallback_reason: str | None = None


class LLMEditError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


Completion = Callable[[str, str, dict], str]  # (system, user, json_schema) -> raw JSON text


def configured_engine() -> tuple[str, str, Completion] | None:
    provider = os.environ.get("CUTORY_EDIT_LLM_PROVIDER", "").strip().lower()
    if provider == "ollama":
        model = os.environ.get("CUTORY_EDIT_LLM_MODEL") or DEFAULT_OLLAMA_MODEL
        base = (os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        return "ollama", model, _ollama_completion(base, model)
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        model = os.environ.get("CUTORY_EDIT_LLM_MODEL") or os.environ.get("OPENAI_MODEL") or ""
        if not key or not model:
            return None
        return "openai", model, _openai_completion(key, model)
    return None


def _ollama_completion(base: str, model: str) -> Completion:
    def call(system: str, user: str, schema: dict) -> str:
        try:
            response = httpx.post(f"{base}/api/chat", timeout=TIMEOUT_SECONDS, json={
                "model": model, "stream": False, "format": schema, "options": {"temperature": 0},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        except httpx.TimeoutException as error:
            raise LLMEditError("LLM_TIMEOUT") from error
        except httpx.HTTPError as error:
            raise LLMEditError("LLM_UNAVAILABLE") from error
        if response.status_code != 200:
            raise LLMEditError("LLM_HTTP_ERROR")
        try:
            return response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as error:
            raise LLMEditError("LLM_BAD_RESPONSE") from error
    return call


def _openai_completion(key: str, model: str) -> Completion:
    def call(system: str, user: str, schema: dict) -> str:
        from openai import APIError, APITimeoutError, OpenAI
        try:
            client = OpenAI(api_key=key, timeout=TIMEOUT_SECONDS, max_retries=0)
            response = client.chat.completions.create(
                model=model, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system + "\nJSON schema: " + json.dumps(schema, ensure_ascii=False)},
                          {"role": "user", "content": user}])
        except APITimeoutError as error:
            raise LLMEditError("LLM_TIMEOUT") from error
        except APIError as error:
            raise LLMEditError("LLM_HTTP_ERROR") from error
        return response.choices[0].message.content or ""
    return call


SYSTEM_PROMPT = (
    "너는 브이로그 편집 보조다. 사용자의 한국어 편집 요청과 번호가 붙은 장면 후보 목록을 받는다. "
    "각 장면의 대사·화면 설명(AI가 본 화면)·근거를 보고 요청에 맞는 장면을 골라 재생 순서대로 selected_scenes에 넣어라. "
    "보이는 것(동물·음식·장소)에 대한 요청은 화면 설명을 우선하고, 대사는 참고만 한다. "
    "음식·디저트·동물·풍경처럼 대사에 직접 없는 표현도 대사 의미로 판단하되, 요청한 범주에 실제로 속하는 장면만 고르고 "
    "범주가 다른 장면(예: 디저트를 요청했는데 음료)은 넣지 마라. 특정 장면을 요청하지 않았으면 모든 장면을 고른다. "
    "요청이 빼라고 한 장면은 excluded_scenes에 넣고 selected_scenes에서 제외한다. "
    "목표 길이가 있으면 target_seconds에 초 단위로 적고, 장면 길이 합이 그 이하가 되게 고른다. "
    "순서: 언급이 없으면 order=chronological, '거꾸로/역순'이면 reverse, 'A 먼저/A부터 그다음 B'처럼 순서를 말하면 "
    "order=custom으로 하고 selected_scenes를 말한 순서대로 적는다. 'X부터'는 시작점이라는 뜻이지 X만 고르라는 뜻이 아니다. "
    "mood에는 요청의 분위기(잔잔=calm, 아늑=cozy, 활기=lively, 감성=emotional, 재미=fun, 없으면 any)를 적는다. "
    "목록에 있는 번호만 쓴다. reasons에는 고른 장면마다 짧은 한국어 이유를 적어라. JSON만 출력하라."
)


def _constrained_schema(count: int) -> dict:
    """Pydantic schema with scene numbers restricted to real candidates (grammar-constrained decoders obey enums)."""
    schema = LLMEditPlan.model_json_schema()
    allowed = {"type": "integer", "enum": list(range(1, count + 1))}
    for key in ("selected_scenes", "excluded_scenes"):
        schema["properties"][key]["items"] = allowed
    schema["$defs"]["SceneReason"]["properties"]["scene"] = allowed
    return schema


def _scene_table(candidates: Sequence[ActiveCandidateSummary]) -> str:
    rows = []
    for number, candidate in enumerate(candidates, start=1):
        start, end = float(candidate.start_seconds), float(candidate.end_seconds)
        evidence = ", ".join(sorted({EVIDENCE_LABELS[e.evidence_type] for e in candidate.evidence if e.evidence_type in EVIDENCE_LABELS}))
        visual = (f" | 화면: {candidate.visual_caption} [{', '.join(candidate.visual_tags)}]"
                  + (f" 분류: {', '.join(candidate.visual_categories)}" if candidate.visual_categories else "")) if candidate.visual_caption else ""
        rows.append(f"{number}. {start:.1f}~{end:.1f}초 (길이 {end - start:.1f}초) | 대사: {candidate.transcript_text or '(없음)'}{visual} | 근거: {evidence or '-'}")
    return "\n".join(rows)


def interpret_with_llm(text: str, candidates: Sequence[ActiveCandidateSummary],
                       engine: tuple[str, str, Completion] | None = None) -> LLMEditResult:
    """LLM suggestion when configured and valid; otherwise the rule-based suggestion with a reason."""
    ordered = sorted(candidates, key=lambda c: (str(c.source_video_id), float(c.start_seconds)))
    engine = engine if engine is not None else configured_engine()
    if engine is None:
        return LLMEditResult(_guard_visual_request(text, ordered, suggest_edit(text, ordered)), "rule")
    provider, model, complete = engine
    try:
        raw = complete(SYSTEM_PROMPT, f"편집 요청: {text}\n\n장면 후보(번호 1~{len(ordered)}):\n{_scene_table(ordered)}",
                       _constrained_schema(len(ordered)))
        plan = LLMEditPlan.model_validate_json(raw)
        return LLMEditResult(_guard_visual_request(text, ordered, _apply_plan(plan, ordered, text)),
                             f"llm:{provider}/{model}", plan.interpretation, plan.mood)
    except LLMEditError as error:
        reason = error.code
    except ValidationError:
        reason = "LLM_SCHEMA_INVALID"
    except _PlanRejected as error:
        reason = str(error)
    rule = suggest_edit(text, ordered)
    rule = _guard_visual_request(text, ordered, rule)
    return LLMEditResult(replace(rule, notes=rule.notes + ("AI 해석을 사용할 수 없어 규칙 기반으로 제안했습니다.",)),
                         "rule", fallback_reason=reason)


# Conservative vocabulary for explicit visual categories. This is a safety gate, not a
# quality classifier: unknown objects stay unmatched rather than inheriting an LLM guess.
VISUAL_CATEGORIES = {
    "음식": ("음식", "요리", "식사", "디저트", "케이크", "빵", "과자", "피자", "햄버거", "샌드위치", "국수"),
    "동물": ("동물", "강아지", "고양이", "반려견", "반려묘", "토끼", "새끼 고양이"),
    "풍경": ("풍경", "노을", "석양", "단풍", "나무", "산책로", "하늘", "바다", "호수", "구름"),
}
VISUAL_OBJECTS = {"강아지": ("강아지", "반려견"), "노을": ("노을", "석양")}


def _guard_visual_request(text: str, candidates: Sequence[ActiveCandidateSummary],
                          suggestion: EditSuggestion) -> EditSuggestion:
    requested = {_stem(word) for word in parse_edit_request(text).keywords}
    categories = [name for name in VISUAL_CATEGORIES if name in requested]
    # A named object followed by "장면" is also a visual request; ordinary dialogue or
    # ordering instructions mentioning the same noun keep their existing behavior.
    if "장면" in text:
        categories += [name for name in VISUAL_OBJECTS if name in requested]
    if not categories:
        return suggestion
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    scenes = []
    for scene in suggestion.scenes:
        candidate = by_id.get(scene.candidate_id)
        if candidate is None:
            continue
        caption = candidate.visual_caption or ""
        if any(cue in caption for cue in ("불확실", "확인되지", "알 수 없", "추정", "일 수 있", "아닐 수")):
            continue
        evidence = []
        for name in categories:
            terms = VISUAL_CATEGORIES.get(name) or VISUAL_OBJECTS[name]
            for field, value in (("화면 설명", candidate.visual_caption or ""),
                                 ("화면 태그", " ".join(candidate.visual_tags)),
                                 ("화면 분류", " ".join(candidate.visual_categories))):
                term = next((term for term in terms if term in value), None)
                if term and not re.search(rf"{re.escape(term)}.{{0,8}}(?:없|보이지 않|아니)", caption):
                    evidence.append(f"시각 조건 '{name}' 근거: {term} ({field})")
                    break
        if evidence:
            scenes.append(SuggestedScene(scene.candidate_id, tuple(evidence)))
    dropped = len(suggestion.scenes) - len(scenes)
    notes = suggestion.notes
    if dropped:
        notes += (f"화면 근거가 확인되지 않은 장면 {dropped}개를 제외했습니다.",)
    if not scenes:
        notes += ("요청한 시각 조건을 확인할 수 없어 장면을 제안하지 않았습니다. 화면 분석 결과를 확인해 주세요.",)
    return replace(suggestion, scenes=tuple(scenes),
                   total_seconds=round(sum(float(by_id[s.candidate_id].end_seconds - by_id[s.candidate_id].start_seconds)
                                           for s in scenes), 3), notes=notes)


class _PlanRejected(ValueError):
    pass


def _apply_plan(plan: LLMEditPlan, ordered: Sequence[ActiveCandidateSummary], text: str = "") -> EditSuggestion:
    """LLM picks scenes by meaning; explicit constraints parsed by the rule parser are enforced by code."""
    count = len(ordered)
    numbers = plan.selected_scenes + plan.excluded_scenes + [item.scene for item in plan.reasons]
    if any(n < 1 or n > count for n in numbers):
        raise _PlanRejected("LLM_UNKNOWN_SCENE")
    rule = parse_edit_request(text)
    speech = lambda n: " ".join([ordered[n - 1].transcript_text or "", ordered[n - 1].visual_caption or "",
                                 *ordered[n - 1].visual_tags, *ordered[n - 1].visual_categories])  # noqa: E731
    hits = lambda word: [n for n in range(1, count + 1) if _matches(word, speech(n))]  # noqa: E731
    notes: list[str] = []
    # Greedy word + josa stripping: a lazy match cut "노을 먼저" into "노" + "을" and "노" matched "뛰어노는".
    first = [_stem(word) for word in re.findall(r"([가-힣A-Za-z0-9]+)\s*(?:먼저|부터)", text)]
    start_points = re.findall(r"([가-힣A-Za-z0-9]+?)부터", text)
    # A word used only as a start point ("노을부터 거꾸로") is not a content filter; "X 먼저" still includes X.
    filters = [w for w in rule.keywords if text.count(_stem(w)) > sum(_stem(f) == _stem(w) for f in start_points)]
    literal = {word: hits(word) for word in filters if hits(word)}
    literal_scenes = {n for found in literal.values() for n in found}
    rule_excluded = {n for word in rule.excluded for n in hits(word)}
    # LLM exclusions are advisory: they never remove a scene the request names verbatim.
    excluded = rule_excluded | (set(plan.excluded_scenes) - literal_scenes)
    picked = [n for i, n in enumerate(plan.selected_scenes) if n not in excluded and n not in plan.selected_scenes[:i]]
    if literal and len(literal) == len(filters):
        # Every requested word appears verbatim in some scene: the matching scenes are the selection.
        wanted = {n for found in literal.values() for n in found} - excluded
        dropped = [n for n in picked if n not in wanted]
        picked = [n for n in picked if n in wanted] + sorted(wanted - set(picked))
        if dropped:
            notes.append(f"요청한 단어와 맞지 않는 AI 선택 {len(dropped)}개를 뺐습니다.")
    elif literal:
        missing = sorted({n for found in literal.values() for n in found} - set(picked) - excluded)
        picked += missing
    if not picked:
        raise _PlanRejected("LLM_EMPTY_SELECTION")
    if rule.order == "reverse" or plan.order == "reverse":
        picked.sort(reverse=True); order = "reverse"
    elif first and any(hits(w) for w in first) or plan.order == "custom":
        lead = [n for w in first for n in hits(w) if n in picked]
        rest = [n for n in picked if n not in lead]
        picked = list(dict.fromkeys(lead + (rest if plan.order == "custom" else sorted(rest)))); order = "custom"
    else:
        picked.sort(); order = "chronological"
    if rule.max_count is not None and len(picked) > rule.max_count:
        picked = picked[: rule.max_count]
    # Length limits come only from numbers the user actually wrote (the LLM sometimes invents one).
    target = rule.target_seconds
    length = lambda n: float(ordered[n - 1].end_seconds) - float(ordered[n - 1].start_seconds)  # noqa: E731
    if target is not None:  # keep order priority, drop what overflows
        kept, total = [], 0.0
        for n in picked:
            if not kept or total + length(n) <= target + 1e-6:
                kept.append(n); total += length(n)
        if len(kept) < len(picked):
            notes.append(f"목표 {target:g}초에 맞추려고 {len(picked) - len(kept)}개 장면을 뺐습니다.")
        picked = kept
    reasons = {item.scene: item.reason for item in plan.reasons}
    def why(n):
        words = [w for w, found in literal.items() if n in found]
        candidate = ordered[n - 1]
        evidence = []
        for word in words:
            if _matches(word, candidate.transcript_text or ""):
                evidence.append(f"'{word}' 대사 일치")
            if _matches(word, candidate.visual_caption or ""):
                evidence.append(f"'{word}' 화면 설명 일치")
            elif _matches(word, " ".join(candidate.visual_tags)):
                evidence.append(f"'{word}' 화면 태그 일치")
            elif _matches(word, " ".join(candidate.visual_categories)):
                evidence.append(f"'{word}' 화면 분류 일치")
        if evidence:
            return tuple(evidence)
        return (reasons.get(n) or "AI가 요청과 관련 있다고 판단",)
    scenes = tuple(SuggestedScene(ordered[n - 1].candidate_id, why(n)) for n in picked)
    intent = EditRequestIntent(target_seconds=target, max_count=rule.max_count, keywords=rule.keywords,
                               excluded=rule.excluded + tuple(f"장면 {n}" for n in sorted(set(plan.excluded_scenes))),
                               order="reverse" if order == "reverse" else "chronological")
    return EditSuggestion(intent, scenes, round(sum(length(n) for n in picked), 3), tuple(notes))
