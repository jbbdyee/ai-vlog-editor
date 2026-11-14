"""TODO 16: change a saved reel draft by talking to it ("3번 더 길게", "여기에 자막 '최애템' 추가").

Two steps, the same split as the rest of the reel code (Python owns every timestamp):
1. ``understand``: the sentence becomes a list of ``Edit`` objects. Common sentences are read by plain rules (fast,
   never wrong about numbers); anything else goes to the local AI, which only fills in the same small form.
2. ``apply_edits``: Python checks and applies each edit. A scene can only grow inside the shot it was cut from
   (the user's sources are already cut, so going past it would show the next cut), and never below 1 second.

Scene numbers are the numbers the screen shows (1 = the first scene of the reel). "여기 / 이 장면" is the scene the
user picked on the screen.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.services.llm_edit_interpreter import Completion, LLMEditError
from backend.app.services.reel_draft import ReelDraft, ReelScene, Shot, _line, _short
from backend.app.services.reel_modes import MIN_SHOT_SECONDS

DEFAULT_STEP_SECONDS = 1.0
Action = Literal["longer", "shorter", "caption", "clear_caption", "title", "remove", "move", "swap"]


@dataclass(frozen=True)
class Edit:
    action: Action
    scene: int | None = None  # 1-based position on the screen
    seconds: float | None = None
    text: str | None = None  # caption / title; None for "caption" means "write one for me"
    to: int | None = None  # move: new 1-based position


@dataclass(frozen=True)
class EditResult:
    draft: ReelDraft
    done: tuple[str, ...]
    skipped: tuple[str, ...]


class NotUnderstood(ValueError):
    pass


# --- 1. understanding the sentence ---------------------------------------------------------------------------------

_QUOTED = re.compile(r"['\"‘’“”「」『』](.+?)['\"‘’“”「」『』]")
_NUMBER = re.compile(r"(\d+)\s*번")
_SECONDS = re.compile(r"(\d+(?:\.\d+)?)\s*초")
_HERE = re.compile(r"여기|이\s*장면|이거|이\s*부분|요기")


def _scene_ref(text: str, selected: int | None, count: int) -> int | None:
    number = _NUMBER.search(text)
    if number:
        return int(number.group(1))
    if re.search(r"(마지막|맨\s*끝|끝)\s*장면", text):  # the small AI miscounts "the last one"
        return count
    if re.search(r"(첫|첫\s*번째|맨\s*앞)\s*장면(?!으로)", text):
        return 1
    return selected if (_HERE.search(text) or selected) else None


def _rule_edits(message: str, selected: int | None, count: int = 0) -> list[Edit]:
    """Plain rules for the sentences people actually type; [] when the sentence needs the AI."""
    text = message.strip()
    quoted = _QUOTED.search(text)
    words = text if not quoted else text.replace(quoted.group(0), " ")
    seconds = _SECONDS.search(words)
    amount = float(seconds.group(1)) if seconds else None
    if "제목" in words and quoted:
        return [Edit("title", text=quoted.group(1).strip())]
    numbers = [int(n) for n in _NUMBER.findall(words)]
    if len(numbers) == 2 and re.search(r"바꿔|바꾸|순서|자리", words) and not re.search(r"자막|문구", words):
        return [Edit("swap", numbers[0], to=numbers[1])]
    scene = _scene_ref(words, selected, count)
    if scene is None:
        return []
    if re.search(r"자막|문구|글자|멘트", words):
        if re.search(r"빼|지워|삭제|없애", words):
            return [Edit("clear_caption", scene)]
        if quoted:
            return [Edit("caption", scene, text=quoted.group(1).strip())]
        if re.search(r"추가|넣|달아|붙여|써|바꿔|다시", words):
            return [Edit("caption", scene)]
        return []
    if re.search(r"맨\s*앞|처음으로|첫\s*장면으로", words):
        return [Edit("move", scene, to=1)]
    if re.search(r"맨\s*뒤|마지막으로|끝으로", words):
        return [Edit("move", scene, to=-1)]
    if re.search(r"길게|늘려|늘리|더\s*보여|오래", words):
        return [Edit("longer", scene, amount)]
    if re.search(r"짧게|줄여|줄이|빨리", words):
        return [Edit("shorter", scene, amount)]
    if re.search(r"빼|지워|삭제|없애|제거", words):
        return [Edit("remove", scene)]
    return []


class _AIEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    scene: int | None = None
    seconds: float | None = None
    text: str | None = Field(default=None, max_length=40)
    to: int | None = None


class _AIEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edits: list[_AIEdit] = Field(min_length=1, max_length=8)


UNDERSTAND_SYSTEM_PROMPT = (
    "너는 릴스 편집 도우미다. 사용자의 말을 편집 목록(JSON)으로만 바꾼다. 장면 번호는 목록에 보이는 번호다. "
    "action: longer(장면 더 길게), shorter(더 짧게), caption(문구 넣기·바꾸기, 사용자가 문구를 말하지 않았으면 text는 null), "
    "clear_caption(문구 지우기), title(첫 화면 제목 바꾸기, text 필수), remove(장면 빼기), move(장면 옮기기, to는 새 번호, 맨 뒤는 -1), "
    "swap(두 장면 자리 바꾸기, scene과 to에 두 번호). "
    "seconds는 사용자가 초를 말했을 때만 쓴다. '여기'·'이 장면'은 고른 장면이다. 말하지 않은 편집은 넣지 마라."
)


def _ai_edits(message: str, draft: ReelDraft, selected: int | None, complete: Completion) -> list[Edit]:
    rows = "\n".join(f"{n}. 문구: {scene.caption or '(없음)'} | 화면: {scene.shot_caption or '설명 없음'}"
                     for n, scene in enumerate(draft.scenes, start=1))
    prompt = (f"첫 화면 제목: {draft.title_lead} {draft.title}\n장면 목록:\n{rows}\n"
              f"고른 장면: {selected or '없음'}\n\n사용자의 말: {message}")
    try:
        answer = _AIEdits.model_validate_json(complete(UNDERSTAND_SYSTEM_PROMPT, prompt, _AIEdits.model_json_schema()))
    except (LLMEditError, ValidationError, ValueError) as error:
        raise NotUnderstood(getattr(error, "code", "LLM_SCHEMA_INVALID")) from error
    edits = [Edit(e.action, e.scene, e.seconds, (e.text or "").strip() or None, e.to) for e in answer.edits]
    # The small AI adds edits nobody asked for ("제목 좀 신나게" with a scene picked also removed that scene).
    # An edit that changes a lot stays only when the sentence has a word for it.
    edits = [edit for edit in edits if edit.action not in _NEEDS_WORD or re.search(_NEEDS_WORD[edit.action], message)]
    if not edits:
        raise NotUnderstood("LLM_EDITS_UNASKED")
    return edits


_NEEDS_WORD = {
    "remove": r"빼|지워|지우|삭제|없애|제거",
    "clear_caption": r"빼|지워|지우|삭제|없애|제거",
    "title": r"제목",
    "move": r"옮|앞|뒤|순서|자리|처음|마지막",
    "swap": r"바꿔|바꾸|순서|자리",
}


def understand(message: str, draft: ReelDraft, selected: int | None, complete: Completion | None) -> tuple[list[Edit], str]:
    """Edits plus who read the sentence ("rule" or "ai")."""
    edits = _rule_edits(message, selected, len(draft.scenes))
    if edits:
        return edits, "rule"
    if complete is None:
        raise NotUnderstood("LLM_NOT_CONFIGURED")
    return _ai_edits(message, draft, selected, complete), "ai"


# --- 2. applying the edits -----------------------------------------------------------------------------------------

CAPTION_SYSTEM_PROMPT = (
    "너는 인스타그램 릴스 편집자다. 장면 하나에 화면에 띄울 한 줄 문구를 쓴다. 친구에게 말하듯 솔직한 구어체로, "
    "마침표·이모지 없이 12자 안팎. 화면에 보이는 동작·옷·상황만 말하고 앞뒤 장면 문구와 다른 말을 쓴다. JSON만 출력하라."
)


class _AICaption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caption: str = Field(min_length=1, max_length=40)


def _write_caption(scenes: list[ReelScene], position: int, draft: ReelDraft, complete: Completion | None) -> str:
    scene = scenes[position]
    if complete is not None:
        around = [scenes[p].caption for p in (position - 1, position + 1) if 0 <= p < len(scenes) and scenes[p].caption]
        prompt = (f"릴스 모드: {draft.mode_label}\n이 장면 화면: {scene.shot_caption or '설명 없음'}"
                  + (f"\n옷·물건: {scene.label}" if scene.label else "")
                  + (f"\n지금 문구(이것과 다르게): {scene.caption}" if scene.caption else "")
                  + (f"\n앞뒤 장면 문구: {' / '.join(around)}" if around else ""))
        try:
            caption = _line(_AICaption.model_validate_json(
                complete(CAPTION_SYSTEM_PROMPT, prompt, _AICaption.model_json_schema())).caption)
            if caption and caption != scene.caption:
                return caption
        except (LLMEditError, ValidationError, ValueError):
            pass
    return _short(scene.shot_caption) or (scene.label.split()[-1] if scene.label else "")


def _seconds(value: float) -> str:
    return f"{value:.1f}초"


def apply_edits(draft: ReelDraft, shots: Sequence[Shot], edits: Sequence[Edit], *,
                complete: Completion | None = None) -> EditResult:
    by_index = {shot.index: shot for shot in shots}
    scenes = list(draft.scenes)
    lead, title = draft.title_lead, draft.title
    done: list[str] = []
    skipped: list[str] = []
    for edit in edits:
        if edit.action == "title":
            new = _line(edit.text or "")
            if not new:
                skipped.append("새 제목을 따옴표 안에 써 주세요. 예: 제목을 '여름 꿀템 3가지'로")
                continue
            lead, title = ("", new) if "/" not in new else tuple(part.strip() for part in new.split("/", 1))
            done.append(f"제목을 '{new}'(으)로 바꿨어요")
            continue
        if edit.scene is None or not 1 <= edit.scene <= len(scenes):
            skipped.append(f"{edit.scene}번 장면이 없어요" if edit.scene else "어느 장면인지 몰라요. 장면 카드를 눌러 고르거나 '3번'처럼 번호를 써 주세요")
            continue
        position = edit.scene - 1
        scene = scenes[position]
        name = f"{edit.scene}번 장면"
        if edit.action in ("longer", "shorter"):
            step = abs(edit.seconds) if edit.seconds else DEFAULT_STEP_SECONDS
            shot = by_index.get(scene.shot_index)
            low, high = (shot.start_seconds, shot.end_seconds) if shot else (scene.start_seconds, scene.end_seconds)
            start, end = scene.start_seconds, scene.end_seconds
            before = end - start
            if edit.action == "longer":
                grow_end = min(step, high - end)
                end += grow_end
                start = max(low, start - (step - grow_end))
            else:
                end = max(start + MIN_SHOT_SECONDS, end - step)
            start, end = round(start, 3), round(end, 3)
            if abs((end - start) - before) < 0.05:
                skipped.append(f"{name}은 원래 컷이 {_seconds(high - low)}이라 더 늘릴 수 없어요" if edit.action == "longer"
                               else f"{name}은 이미 가장 짧아요({_seconds(MIN_SHOT_SECONDS)})")
                continue
            scenes[position] = replace(scene, start_seconds=start, end_seconds=end)
            done.append(f"{name} {_seconds(before)} → {_seconds(end - start)}")
        elif edit.action == "caption":
            caption = _line(edit.text) if edit.text else _write_caption(scenes, position, draft, complete)
            if not caption:
                skipped.append(f"{name}에 넣을 문구를 못 만들었어요. 따옴표 안에 직접 써 주세요")
                continue
            scenes[position] = replace(scene, caption=caption)
            done.append(f"{name} 문구 → '{caption}'")
        elif edit.action == "clear_caption":
            scenes[position] = replace(scene, caption="")
            done.append(f"{name} 문구를 지웠어요")
        elif edit.action == "remove":
            if len(scenes) <= 1:
                skipped.append("장면이 하나뿐이라 뺄 수 없어요")
                continue
            scenes.pop(position)
            done.append(f"{name}을 뺐어요")
        elif edit.action == "swap":
            if edit.to is None or not 1 <= edit.to <= len(scenes) or edit.to == edit.scene:
                skipped.append(f"{name}과 바꿀 장면 번호를 알려 주세요")
                continue
            scenes[position], scenes[edit.to - 1] = scenes[edit.to - 1], scenes[position]
            done.append(f"{edit.scene}번과 {edit.to}번 장면 자리를 바꿨어요")
        elif edit.action == "move":
            to = len(scenes) if edit.to in (None, -1) or edit.to > len(scenes) else max(1, edit.to)
            if to == edit.scene:
                skipped.append(f"{name}은 이미 그 자리에 있어요")
                continue
            scenes.insert(to - 1, scenes.pop(position))
            done.append(f"{name}을 {'맨 앞' if to == 1 else '맨 뒤' if to == len(scenes) else f'{to}번 자리'}으로 옮겼어요")
    # The first scene is always the hook: the title sits on it.
    scenes = [replace(scene, is_hook=number == 0) for number, scene in enumerate(scenes)]
    total = round(sum(scene.end_seconds - scene.start_seconds for scene in scenes), 3)
    new_draft = replace(draft, scenes=tuple(scenes), total_seconds=total, title=title, title_lead=lead)
    return EditResult(new_draft, tuple(done), tuple(skipped))
