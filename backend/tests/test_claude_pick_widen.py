import unittest
from uuid import uuid4

from backend.app.services import claude_scene_pick as pick
from backend.app.services.story_length import SourceTiming


def _s(number, video, start, end, score=2, clip=None):
    clip_start, clip_end = clip or (start, end)
    return {"number": number, "candidate_id": str(uuid4()), "source_video_id": str(video), "clock": "",
            "scene_start": start, "scene_end": end, "clip_start": clip_start, "clip_end": clip_end,
            "score": score, "what": "", "why": ""}


class WidenPickTest(unittest.TestCase):
    def test_back_to_back_scenes_become_one_cut(self):
        video = uuid4()
        a, b, c = _s(1, video, 10, 13), _s(2, video, 13.5, 16.5), _s(3, video, 40, 43)
        result = {"chapters": [{"scenes": [a, b, c]}], "left_out": []}
        out = pick.widen(result, {video: SourceTiming(100.0)}, 9.5)
        self.assertEqual(out["cuts"], 2)
        self.assertEqual(out["merged"], 1)
        self.assertEqual(out["clips"][0]["numbers"], [1, 2])
        self.assertEqual(out["clips"][0]["candidate_id"], a["candidate_id"])

    def test_scenes_with_a_left_out_scene_between_stay_apart(self):
        video = uuid4()
        a, gap, b = _s(1, video, 10, 13), _s(2, video, 13.2, 13.8, score=1), _s(3, video, 14, 17)
        out = pick.widen({"chapters": [{"scenes": [a, b]}], "left_out": [gap]}, {video: SourceTiming(100.0)}, 6)
        self.assertEqual(out["cuts"], 2)

    def test_widens_to_the_usual_cut_but_not_into_a_zero_scene(self):
        video = uuid4()
        zero = _s(1, video, 5, 8, score=0)
        a = _s(2, video, 10, 13, score=3, clip=(10.5, 12.5))
        b = _s(3, video, 50, 53, score=2)
        out = pick.widen({"chapters": [{"scenes": [a, b]}], "left_out": [zero]}, {video: SourceTiming(100.0)}, 11)
        first = out["clips"][0]
        self.assertGreaterEqual(first["start"], 8.0)  # never into the scene Claude said to leave out
        self.assertLess(first["start"], 10.5)
        self.assertAlmostEqual(out["total_seconds"], 11, delta=0.6)
        self.assertEqual((first["picked_start"], first["picked_end"]), (10.5, 12.5))

    def test_too_many_cuts_drop_low_scores_but_keep_my_voice(self):
        video = uuid4()
        scenes = [_s(i + 1, video, i * 20, i * 20 + 3, score=3) for i in range(10)]
        scenes[3]["score"], scenes[5]["score"] = 0, 0
        mine = {__import__("uuid").UUID(scenes[5]["candidate_id"])}
        result = {"chapters": [{"scenes": scenes}], "left_out": []}
        out = pick.widen(result, {video: SourceTiming(300.0)}, 6 * 5.5 * 1.15, typical_cut=5.5, mine=mine)
        self.assertEqual(out["cuts"], 6)
        numbers = [n for clip in out["clips"] for n in clip["numbers"]]
        self.assertNotIn(4, numbers)  # Claude's 0
        self.assertIn(6, numbers)  # a 0 where I talk stays
        self.assertEqual(out["left_out"], 4)

    def test_nothing_picked(self):
        self.assertIsNone(pick.widen({"chapters": [], "left_out": []}, {}, 60))


if __name__ == "__main__":
    unittest.main()
