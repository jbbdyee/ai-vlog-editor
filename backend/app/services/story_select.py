"""TODO 32-3: leave out the less important scenes when the chosen ones are too many for the length.

Before this, a shorter length only made every scene shorter: with 182 scenes an 8-minute edit is 2.6 s per scene and
nothing is ever left out. My own edit of the same day keeps fewer scenes and keeps them longer (64 cuts, 7.5 s).

Which scenes go first (no AI, from the TODO 24 voice marks):
  1. no speech  2. only other people's voices  3. scenes with my voice (never, with '내가 말하는 장면은 살린다')
Within the same kind, the scene goes from the video that still has the most seconds kept, so one long recording
(the 2-hour evening class) does not fill the edit. The first and the last scene of the day always stay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

KEEP_RAW_RATIO = 0.6  # leave room so the kept scenes can still be widened to the length
NO_SPEECH, OTHERS, MINE = 0, 1, 2


@dataclass(frozen=True)
class SceneVoice:
    candidate_id: UUID
    source_video_id: UUID
    seconds: float
    mine: int = 0  # lines in my voice inside the scene
    others: int = 0  # lines in other voices

    @property
    def kind(self) -> int:
        return MINE if self.mine else OTHERS if self.others else NO_SPEECH


def leave_out(scenes: Sequence[SceneVoice], target_seconds: float, keep_mine: bool = False) -> list[UUID]:
    """Scenes (in day order) to leave out so the rest takes about KEEP_RAW_RATIO of the target. Kept order is untouched."""
    budget = target_seconds * KEEP_RAW_RATIO
    total = sum(scene.seconds for scene in scenes)
    if total <= budget or len(scenes) <= 2:
        return []
    protected = {scenes[0].candidate_id, scenes[-1].candidate_id}
    if keep_mine:
        protected |= {scene.candidate_id for scene in scenes if scene.mine}
    kept_by_source: dict[UUID, float] = {}
    for scene in scenes:
        kept_by_source[scene.source_video_id] = kept_by_source.get(scene.source_video_id, 0.0) + scene.seconds
    left = [scene for scene in scenes if scene.candidate_id not in protected]
    out: list[UUID] = []
    while total > budget and left:
        # least important kind first, then the video with the most kept, then the later scene (stable)
        drop = min(left, key=lambda s: (s.kind, -kept_by_source[s.source_video_id], -left.index(s)))
        left.remove(drop)
        out.append(drop.candidate_id)
        kept_by_source[drop.source_video_id] -= drop.seconds
        total -= drop.seconds
    return out
