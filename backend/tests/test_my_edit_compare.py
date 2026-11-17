"""TODO 29: my own edit is found in the sources (cuts, '원본에 없음'), compared with the plan and fed to taste candidates."""
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import numpy as np

from backend.app.services import my_edit_compare as mec
from backend.app.services import taste_log

STEP = 1 / mec.EDIT_FPS


def _pictures(count: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, size=(count, mec.SIG_W * mec.SIG_H), dtype=np.uint8)


def _source(seconds: float, seed: int) -> tuple[mec.Frames, np.ndarray]:
    raw = _pictures(int(seconds * 2), seed)  # key frames every 0.5 s
    return mec.Frames(np.arange(len(raw)) * 0.5, mec.normalise(raw)), raw


def _edit(parts: list[tuple[np.ndarray | None, float, float]]) -> mec.Frames:
    """parts: (source raw pictures or None = a picture from nowhere, start, seconds), 4 pictures a second."""
    rows = []
    rng = np.random.default_rng(99)
    for raw, start, seconds in parts:
        for index in range(int(round(seconds * mec.EDIT_FPS))):
            if raw is None:
                rows.append(rng.integers(0, 256, size=mec.SIG_W * mec.SIG_H, dtype=np.uint8))
                continue
            picture = raw[int((start + index * STEP) * 2)].astype(np.int16)
            graded = np.clip(picture * 0.8 + 30 + rng.normal(0, 6, picture.shape), 0, 255)  # colour grading + noise
            rows.append(graded.astype(np.uint8))
    return mec.Frames(np.arange(len(rows)) * STEP, mec.normalise(np.stack(rows)))


class FrameTests(unittest.TestCase):
    def test_flat_pictures_are_not_compared(self):
        sigs = mec.normalise(np.vstack([np.full(mec.SIG_W * mec.SIG_H, 12, np.uint8), _pictures(1, 1)[0]]))
        self.assertFalse(sigs[0].any())
        self.assertAlmostEqual(float(np.linalg.norm(sigs[1])), 1.0, places=4)

    def test_portrait_video_can_be_read_as_its_middle_band_only(self):
        """TODO 31: a portrait reel shows the landscape picture in its middle; only that band is compared."""
        plain = mec._frames_command(Path("a.mp4"), False, 4.0, "ffmpeg", False)
        band = mec._frames_command(Path("a.mp4"), False, 4.0, "ffmpeg", False, mec.CENTER_BAND)
        plain_filters = plain[plain.index("-vf") + 1].split(",")
        band_filters = band[band.index("-vf") + 1].split(",")
        self.assertFalse(any(part.startswith("crop=") for part in plain_filters))
        self.assertEqual(band_filters[:3], ["fps=4", "crop=iw:iw*9/16", f"scale={mec.SIG_W}:{mec.SIG_H}:flags=area"])


class MatchTests(unittest.TestCase):
    def setUp(self):
        (self.a, self.raw_a), (self.b, self.raw_b) = _source(60, 1), _source(40, 2)
        self.sources = [mec.Source(uuid4(), 1, "a.MP4", 60.0), mec.Source(uuid4(), 2, "b.MP4", 40.0)]

    def _cuts(self, edit):
        matches = mec.match_frames(edit, [self.a, self.b])
        return mec.build_cuts(list(edit.times), matches)

    def test_cuts_follow_the_sources_and_unknown_parts_are_not_found(self):
        edit = _edit([(self.raw_a, 10.0, 3.0), (self.raw_b, 5.0, 2.0), (None, 0, 4.0), (self.raw_a, 40.0, 2.5)])
        cuts, gaps = self._cuts(edit)
        self.assertEqual([(cut.source, cut.length) for cut in cuts], [(0, 3.0), (1, 2.0), (0, 2.5)])
        self.assertAlmostEqual(cuts[0].source_start, 10.0, delta=0.5)
        self.assertAlmostEqual(cuts[2].source_start, 40.0, delta=0.5)
        self.assertEqual([(gap.edit_start, gap.edit_end) for gap in gaps], [(5.0, 9.0)])

    def test_a_jump_inside_one_source_is_a_new_cut(self):
        cuts, _ = self._cuts(_edit([(self.raw_a, 5.0, 2.0), (self.raw_a, 30.0, 2.0)]))
        self.assertEqual(len(cuts), 2)

    def test_short_unknown_bits_are_transitions(self):
        _, gaps = self._cuts(_edit([(self.raw_a, 5.0, 2.0), (None, 0, 0.5), (self.raw_a, 30.0, 2.0)]))
        self.assertEqual(gaps, [])


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.sources = [mec.Source(uuid4(), 1, "a.MP4", 100.0), mec.Source(uuid4(), 2, "b.MP4", 50.0)]
        self.mine = [mec.MyCut(0, 2, 0, 10, 12, 0.9), mec.MyCut(2, 4, 1, 20, 22, 0.9), mec.MyCut(4, 6, 1, 40, 42, 0.9)]
        self.plan = [mec.PlanCut("p1", 0, 9, 15), mec.PlanCut("p2", 0, 60, 66), mec.PlanCut("p3", 1, 0, 6)]
        self.tags = lambda source, start, end: ["other_voice"] if source == 1 else ["quiet"]

    def test_numbers_for_the_card(self):
        out = mec.compare(self.sources, self.mine, [mec.Gap(6, 9)], self.plan, 9.0, self.tags)
        self.assertEqual((out["mine"]["cut_count"], out["mine"]["median_cut"]), (3, 2.0))
        self.assertEqual((out["cutory"]["cut_count"], out["cutory"]["median_cut"]), (3, 6.0))
        self.assertEqual(out["overlap_seconds"], 2.0)
        self.assertEqual(out["mine_spans"][1], [120.0, 122.0])  # source 2 starts after source 1's 100 s
        self.assertEqual(out["tags"]["other_voice"], {"mine": 4.0, "cutory": 6.0})
        self.assertEqual([cut["in_cutory"] for cut in out["cuts"]], [True, False, False])
        self.assertEqual(out["not_found_seconds"], 3.0)

    def test_taste_lines_only_count_plan_cuts_and_my_extra_cuts(self):
        choices = mec.taste_choices(self.sources, self.mine, self.plan, self.tags)
        self.assertEqual([(c.how, c.tags) for c in choices], [
            ("my_edit_used", ("quiet",)), ("my_edit_unused", ("quiet",)), ("my_edit_unused", ("other_voice",)),
            ("my_edit_used", ("other_voice",)), ("my_edit_used", ("other_voice",))])


class TasteTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "projects"
        self.root.mkdir()

    def _record(self, project, how_tags, mine_median=2.0, cutory_median=6.0):
        choices = [taste_log.Choice(how, uuid4().hex, (tag,), 3.0) for how, tag in how_tags]
        taste_log.record_my_edit(self.root, project, choices, {"cut_count": 20, "median_cut": mine_median},
                                 {"cut_count": 31, "median_cut": cutory_median})

    def test_my_edit_lines_become_candidates_and_comparing_again_replaces_them(self):
        project = uuid4()
        self._record(project, [("my_edit_used", "other_voice")] * 4)
        found = {item.key: item for item in taste_log.candidates(self.root)}
        self.assertIn("other_voice:keep", found)
        self.assertIn("내 편집본에서 씀 4", found["other_voice:keep"].why)
        self.assertEqual(found["my_edit_max_cut"].text, "한 컷은 2초 넘지 않게")
        self.assertIn("Cutory 편집안은 6.0초", found["my_edit_max_cut"].why)
        self._record(project, [("my_edit_used", "other_voice")])  # compared again: the old lines are gone
        self.assertEqual(len(taste_log.load_log(self.root)["events"]), 1)
        self.assertNotIn("other_voice:keep", {item.key for item in taste_log.candidates(self.root)})

    def test_no_cut_length_candidate_when_not_much_shorter_or_already_a_rule(self):
        self._record(uuid4(), [], mine_median=5.0, cutory_median=6.0)
        self.assertEqual(taste_log.candidates(self.root), [])
        self._record(uuid4(), [], mine_median=2.0, cutory_median=6.0)
        self.assertEqual(taste_log.candidates(self.root, ["한 컷은 2초 넘지 않게"]), [])
        self.assertEqual(taste_log.candidates(self.root, [], max_cut_rule=2.0), [])
        taste_log.answer(self.root, "my_edit_max_cut", False)
        self.assertEqual(taste_log.candidates(self.root), [])


if __name__ == "__main__":
    unittest.main()
