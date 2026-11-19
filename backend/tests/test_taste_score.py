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

    def test_first_and_last_scene_go_when_my_taste_gave_them_zero(self):
        shaky, monitor = SceneVoice(uuid4(), SOURCE, 10, taste=0), SceneVoice(uuid4(), SOURCE, 10, taste=0)
        middle = [SceneVoice(uuid4(), SOURCE, 10, taste=2) for _ in range(3)]
        out = leave_out([shaky, *middle, monitor], 50, keep_mine=True)  # 50 s, budget 30 s -> two go
        self.assertEqual(sorted(map(str, out)), sorted([str(shaky.candidate_id), str(monitor.candidate_id)]))


class TastePictureTests(TestCase):
    """TODO 32-4b: scenes go to Claude with two pictures each, 40 scenes per request."""

    def test_pictures_go_with_each_scene_in_chunks(self):
        rows = [row(index * 10, index * 10 + 6) for index in range(45)]
        self.assertEqual(ts.picture_times(rows[1]), (12.0, 14.0))
        with tempfile.TemporaryDirectory() as root:
            picture = Path(root) / "a.jpg"
            picture.write_bytes(b"\xff\xd8jpeg")
            pictures = {r.candidate_id: [picture, picture] for r in rows}
            sent = []

            def ask(system, blocks, schema):
                sent.append(blocks)
                count = sum(1 for block in blocks if block["type"] == "text") - 1
                return json.dumps({"scores": [{"n": n, "score": 2, "why": "옆모습"} for n in range(1, count + 1)]}), 10, 5

            scores, used_in, used_out = ts.score_with_pictures("옆모습이 예쁨", [], rows, pictures, ask)
        self.assertEqual([sum(1 for b in blocks if b["type"] == "image") for blocks in sent], [80, 10])
        self.assertIn("옆모습이 예쁨", sent[0][0]["text"])
        self.assertIn("점수 매길 장면(번호 1~5", sent[1][0]["text"])
        self.assertEqual(len(scores), 45)
        self.assertEqual((used_in, used_out), (20, 10))

    def test_estimate_counts_pictures_and_repeated_header(self):
        system, user = ts.build_request("취향", [], [row(0, 5) for _ in range(80)])
        text_only = ts.estimate_tokens(system, user, 80)
        with_pictures = ts.estimate_tokens(system, user, 80, pictures=160)
        self.assertGreater(with_pictures[0], text_only[0] + 160 * ts.IMAGE_TOKENS - 1)
