"""TODO 32-4: scenes scored from my own description and the scenes my own edit kept or left out."""

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from backend.app.services import taste_score as ts
from backend.app.services.longform_chat import Line
from backend.app.services.story_select import SceneVoice, leave_out

SOURCE = uuid4()


def row(start, end, speech="", caption="", clock="09:00"):
    return ts.SceneRow(uuid4(), SOURCE, start, end, clock, speech, caption)


class TasteScoreTests(TestCase):
    def test_kept_when_my_edit_used_the_source_nearby(self):
        near, far, other_video = row(10, 14), row(60, 64), ts.SceneRow(uuid4(), uuid4(), 10, 14, "", "", "")
        kept = ts.kept_by_my_edit([near, far, other_video],
                                  [{"source_id": str(SOURCE), "source_start": 15.0, "source_end": 20.0}])
        self.assertEqual([kept[near.candidate_id], kept[far.candidate_id], kept[other_video.candidate_id]],
                         [True, False, False])

    def test_speech_marks_me_and_others_and_clock_from_file_name(self):
        lines = (Line(0, 2, "제 생각엔", "me"), Line(2, 4, "좋아요", "other"), Line(9, 10, "밖", "me"))
        self.assertEqual(ts.speech_text(lines, 0, 5), "[나] 제 생각엔 / [남] 좋아요")
        self.assertEqual(ts.filmed_clock("DJI_20261112085851_0793_D.MP4", 125), "09:00")
        self.assertEqual(ts.filmed_clock("IMG_0001.MOV", 5), "")

    def test_request_has_my_description_examples_and_every_scene(self):
        example, scene = row(0, 5, "[나] 발표할게요"), row(0, 6, caption="하늘")
        system, user = ts.build_request("회의에서 내 의견은 꼭 남김", [(example, True)], [scene])
        self.assertIn("가장 중요한 기준", system)
        self.assertIn("회의에서 내 의견은 꼭 남김", user)
        self.assertIn("1. 09:00 길이 5초 | 대사: [나] 발표할게요 | 화면: (없음) | 내 편집에서 남김", user)
        self.assertIn("점수 매길 장면(번호 1~1", user)

    def test_scores_are_read_back_and_bad_numbers_skipped(self):
        rows = [row(0, 5), row(5, 9)]
        reply = json.dumps({"scores": [{"n": 1, "score": 3, "why": "내 발표"}, {"n": 2, "score": 0, "why": "흔들림"},
                                       {"n": 7, "score": 2, "why": "없는 번호"}]})
        scores, used_in, used_out = ts.score("", [], rows, lambda system, user, schema: (reply, 100, 20))
        self.assertEqual(scores, {rows[0].candidate_id: (3, "내 발표"), rows[1].candidate_id: (0, "흔들림")})
        self.assertEqual((used_in, used_out), (100, 20))
        with tempfile.TemporaryDirectory() as root:
            project = uuid4()
            ts.save_scores(Path(root), project, scores, model="m", input_tokens=1, output_tokens=1, usd=0.0, examples=0)
            self.assertEqual(ts.load_scores(Path(root), project), scores)
            self.assertEqual(ts.save_brief(Path(root), "  옆모습이 예쁨  "), "옆모습이 예쁨")
            self.assertEqual(ts.load_brief(Path(root)), "옆모습이 예쁨")

    def test_low_taste_scores_leave_first_even_with_my_voice(self):
        first, last = SceneVoice(uuid4(), SOURCE, 10, taste=2), SceneVoice(uuid4(), SOURCE, 10, taste=2)
        stammer = SceneVoice(uuid4(), SOURCE, 10, mine=3, taste=0)  # my voice, but my description says leave it
        meeting = SceneVoice(uuid4(), SOURCE, 10, others=2, mine=1, taste=3)
        out = leave_out([first, stammer, meeting, last], 50, keep_mine=True)  # 40 s, budget 30 s -> one goes
        self.assertEqual(out, [stammer.candidate_id])
