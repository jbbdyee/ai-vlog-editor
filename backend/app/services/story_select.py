"""TODO 32-3: leave out the less important scenes when the chosen ones are too many for the length.

Before this, a shorter length only made every scene shorter: with 182 scenes an 8-minute edit is 2.6 s per scene and
nothing is ever left out. My own edit of the same day keeps fewer scenes and keeps them longer (64 cuts, 7.5 s).

Which scenes go first (no AI, from the TODO 24 voice marks):
  1. no speech  2. only other people's voices  3. scenes with my voice (never, with '내가 말하는 장면은 살린다')
Within the same kind, the scene goes from the video that still has the most seconds kept, so one long recording
(the 2-hour evening class) does not fill the edit. The first and the last scene of the day stay, unless my taste
scores (TODO 32-4) gave them 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

KEEP_RAW_RATIO = 0.6  # leave room so the kept scenes can still be widened to the length
NO_SPEECH, OTHERS, MINE = 0, 1, 2
# TODO 33-3: a few long cuts make the mean longer than the median (my 8-minute edit 6.7 / 5.6 s = 1.19, a reel
# 1.9 / 1.8 s = 1.07); with target / median alone 학원 하루 got 87 cuts at 4.5 s instead of 64 at 5.6 s
MEAN_OVER_MEDIAN = 1.15


@dataclass(frozen=True)
class SceneVoice:
    candidate_id: UUID
    source_video_id: UUID
    seconds: float
    mine: int = 0  # lines in my voice inside the scene
    others: int = 0  # lines in other voices
    taste: int | None = None  # TODO 32-4: 0~3 from my description + my edit's examples; replaces the voice order

    @property
    def kind(self) -> int:
        if self.taste is not None:
            return self.taste
        return MINE if self.mine else OTHERS if self.others else NO_SPEECH


def leave_out(scenes: Sequence[SceneVoice], target_seconds: float, keep_mine: bool = False,
              typical_cut: float | None = None) -> list[UUID]:
    """Scenes (in day order) to leave out so the rest takes about KEEP_RAW_RATIO of the target. Kept order is untouched.

    TODO 33-3: with a '한 컷은 M초 안팎' rule the count decides instead: about target / M scenes stay, so each one is
    widened to about M seconds; MEAN_OVER_MEDIAN below (a reference I like with short cuts keeps more, shorter scenes).
    """
    budget = target_seconds * KEEP_RAW_RATIO
    total = sum(scene.seconds for scene in scenes)
    keep_count = max(2, round(target_seconds / (typical_cut * MEAN_OVER_MEDIAN))) if typical_cut else None
    too_many = (lambda: len(scenes) - len(out) > keep_count) if keep_count else (lambda: total > budget)
    out: list[UUID] = []
    if not too_many() or len(scenes) <= 2:
        return []
    # the day's first and last scene stay, unless my taste scored it 0 (a shaky face, only a monitor)
    protected = {scene.candidate_id for scene in (scenes[0], scenes[-1]) if scene.taste != 0}
    if keep_mine and not any(scene.taste is not None for scene in scenes):  # taste scores already weigh my voice
        protected |= {scene.candidate_id for scene in scenes if scene.mine}
    kept_by_source: dict[UUID, float] = {}
    for scene in scenes:
        kept_by_source[scene.source_video_id] = kept_by_source.get(scene.source_video_id, 0.0) + scene.seconds
    left = [scene for scene in scenes if scene.candidate_id not in protected]
    while too_many() and left:
        # least important kind first, then the video with the most kept, then the later scene (stable)
        drop = min(left, key=lambda s: (s.kind, -kept_by_source[s.source_video_id], -left.index(s)))
        left.remove(drop)
        out.append(drop.candidate_id)
        kept_by_source[drop.source_video_id] -= drop.seconds
        total -= drop.seconds
    return out
