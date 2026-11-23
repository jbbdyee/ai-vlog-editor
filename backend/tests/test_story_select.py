"""TODO 32-3: leave out the less important scenes for the length instead of making every scene shorter."""

from unittest import TestCase
from uuid import uuid4

from backend.app.services.story_select import SceneVoice, leave_out

MORNING, EVENING = uuid4(), uuid4()


def scene(source, seconds=10.0, mine=0, others=0):
    return SceneVoice(uuid4(), source, seconds, mine, others)


class LeaveOutTests(TestCase):
    def test_nothing_goes_when_it_already_fits(self):
        scenes = [scene(MORNING) for _ in range(5)]
        self.assertEqual(leave_out(scenes, 120), [])  # 50 s <= 0.6 x 120 s

    def test_silent_scenes_go_first_then_others_and_my_voice_stays(self):
        first, last = scene(MORNING), scene(EVENING)
        mine = scene(MORNING, mine=2)
        chat = scene(EVENING, others=3)
        silent = [scene(MORNING), scene(EVENING)]
        scenes = [first, mine, *silent, chat, last]
        out = leave_out(scenes, 60)  # budget 36 s of 60 s total -> 3 scenes go
        self.assertEqual(set(out[:2]), {s.candidate_id for s in silent})
        self.assertEqual(out[2], chat.candidate_id)
        self.assertNotIn(first.candidate_id, out)
        self.assertNotIn(last.candidate_id, out)

    def test_same_kind_goes_from_the_video_with_most_kept(self):
        evening = [scene(EVENING) for _ in range(6)]
        morning = [scene(MORNING) for _ in range(2)]
        scenes = [scene(MORNING, mine=1), *morning, *evening, scene(EVENING, mine=1)]
        out = leave_out(scenes, 100)  # 100 s total, budget 60 s -> 4 go, all from the long evening video
        self.assertEqual(len(out), 4)
        self.assertTrue(set(out) <= {s.candidate_id for s in evening})

    def test_typical_cut_rule_keeps_target_over_m_scenes(self):
        scenes = [scene(MORNING, seconds=4.0) for _ in range(30)]  # 120 s: under the 60% budget of 480 s
        self.assertEqual(leave_out(scenes, 480), [])
        out = leave_out(scenes, 69, typical_cut=5.0)  # 69 s / (5 s x 1.15) -> 12 stay
        self.assertEqual(len(scenes) - len(out), 12)
        self.assertNotIn(scenes[0].candidate_id, out)
        self.assertNotIn(scenes[-1].candidate_id, out)
        self.assertEqual(leave_out(scenes[:10], 69, typical_cut=5.0), [])  # already fewer than 12

    def test_my_voice_rule_never_leaves_my_scenes_out(self):
        mine = [scene(MORNING, mine=1) for _ in range(6)]
        scenes = [scene(MORNING), *mine, scene(EVENING)]
        self.assertEqual(leave_out(scenes, 10, keep_mine=True), [])
        self.assertTrue(leave_out(scenes, 10, keep_mine=False))
