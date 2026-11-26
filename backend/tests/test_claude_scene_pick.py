import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

from backend.app.services import claude_scene_pick as pick


def _line(start, end, text, speaker):
    return SimpleNamespace(start=start, end=end, text=text, speaker=speaker)


def _scene(source, filename, number, start, end, caption=""):
    return SimpleNamespace(candidate_id=uuid4(), source_video_id=source, filename=filename, video_number=number,
                           found_start=start, found_end=end, caption=caption)


class ScenePickEstimateTest(unittest.TestCase):
    def test_rows_in_filming_order_with_timed_speech(self):
        morning, evening = uuid4(), uuid4()
        late = _scene(evening, "DJI_20261112185614_0817_D.MP4", 2, 10.0, 20.0, "강의실")
        early = _scene(morning, "DJI_20261112071842_0786_D.MP4", 1, 30.0, 36.0)
        inputs = SimpleNamespace(scenes={late.candidate_id: late, early.candidate_id: early},
                                 lines={evening: (_line(12.5, 14.0, "단체 멘토링만", "me"), _line(19.0, 22.0, "끝", "other"),
                                                  _line(30.0, 31.0, "밖", None))})
        rows = pick.scene_rows(inputs)
        self.assertEqual([row.candidate_id for row in rows], [early.candidate_id, late.candidate_id])
        self.assertEqual([row.number for row in rows], [1, 2])
        self.assertEqual(rows[0].clock, "07:19")
        self.assertEqual(rows[1].speech, "[나 2.5] 단체 멘토링만 / [남 9.0] 끝")
        self.assertIn("2번 장면 18:56 길이 10.0초", rows[1].line())
        self.assertIn("대사: (없음)", rows[0].line())

    def test_two_pictures_inside_the_scene(self):
        row = pick.SceneRow(1, uuid4(), uuid4(), 10.0, 16.0, "", "", "")
        self.assertEqual(pick.picture_times(row), (12.0, 14.0))

    def test_header_carries_length_rules_brief_and_day_note(self):
        header = pick.header_text(["한 컷은 5.5초 안팎"], "내가 웃는 장면", "저녁은 치킨", ["한 컷 가운데 값 5.6초"], 8)
        for words in ("목표 길이: 약 8분", "- 한 컷은 5.5초 안팎", "내가 웃는 장면", "저녁은 치킨", "- 한 컷 가운데 값 5.6초"):
            self.assertIn(words, header)

    def test_estimate_counts_two_steps_and_price(self):
        rows = [pick.SceneRow(n, uuid4(), uuid4(), 0.0, 20.0, "", "가" * 100, "") for n in range(1, 183)]
        guess = pick.estimate("claude-sonnet-5-5", "머리글" * 100, rows)
        self.assertEqual(guess.pictures, 364)
        self.assertEqual(guess.chunks, 4)  # 50 + 50 + 50 + 32 scenes, at most 100 pictures per request
        step1 = 4 * (len(pick.SYSTEM_STEP1) + 300) + sum(len(row.line()) for row in rows)
        step2 = len(pick.SYSTEM_STEP1) + 300 + 70 * 182
        self.assertEqual(guess.input_tokens, step1 + step2 + 364 * pick.IMAGE_TOKENS)
        self.assertEqual(guess.output_tokens, 182 * (70 + 12) + 600)
        self.assertAlmostEqual(guess.usd_low, (guess.input_tokens * 2 + guess.output_tokens * 10) / 1e6, places=4)
        self.assertGreater(guess.usd_high, guess.usd_low)


def _rows(count, length=20.0):
    return [pick.SceneRow(n, uuid4(), uuid4(), 100.0, 100.0 + length, f"0{7 + n // 60}:{n % 60:02d}", "", "")
            for n in range(1, count + 1)]


class ScenePickRunTest(unittest.TestCase):
    def test_step1_keeps_valid_notes_and_fills_missing_scenes(self):
        rows = _rows(3)
        answer = json.dumps({"scenes": [
            {"n": 1, "score": 3, "use_from": 2.0, "use_to": 9.5, "what": "만두 없다에 빵 터짐", "why": "내가 크게 웃음"},
            {"n": 2, "score": 0, "use_from": 5.0, "use_to": 5.2, "what": "하늘", "why": "흔들림"},  # too short -> whole
            {"n": 2, "score": 3, "use_from": 0, "use_to": 1, "what": "중복", "why": ""},  # second answer ignored
            {"n": 9, "score": 2, "use_from": 0, "use_to": 3, "what": "없는 장면", "why": ""},
        ]})
        notes = pick.read_step1(answer, rows)
        self.assertEqual(sorted(notes), [1, 2, 3])
        self.assertEqual((notes[1].score, notes[1].use_from, notes[1].use_to), (3, 2.0, 9.5))
        self.assertEqual((notes[2].score, notes[2].use_from, notes[2].use_to), (0, 0.0, 20.0))
        self.assertEqual((notes[3].score, notes[3].why), (1, "답 없음"))
        self.assertIn("1. 07:01 | 3점 | 쓸 구간 7.5초 | 만두 없다에 빵 터짐 | 내가 크게 웃음", notes[1].line())

    def test_step2_keeps_known_scenes_once_in_filming_order(self):
        rows = _rows(4)
        notes = pick.read_step1(json.dumps({"scenes": [
            {"n": n, "score": 2, "use_from": 1.0, "use_to": 6.0, "what": "", "why": ""} for n in range(1, 5)]}), rows)
        answer = json.dumps({"title": "학원 하루", "summary": "아침부터 저녁까지", "chapters": [
            {"title": "저녁", "description": "", "reason": "", "scenes": [4, 3, 3]},
            {"title": "아침", "description": "", "reason": "", "scenes": [1, 4, 7]},
            {"title": "빈 챕터", "description": "", "reason": "", "scenes": [99]}]})
        result = pick.read_step2(answer, notes)
        self.assertEqual([c["title"] for c in result["chapters"]], ["아침", "저녁"])
        self.assertEqual([[s["number"] for s in c["scenes"]] for c in result["chapters"]], [[1], [3, 4]])
        self.assertEqual([s["number"] for s in result["left_out"]], [2])
        first = result["chapters"][0]["scenes"][0]
        self.assertEqual((first["clip_start"], first["clip_end"]), (101.0, 106.0))  # source seconds

    def test_pick_sends_100_pictures_at_most_then_one_text_step(self):
        rows = _rows(120)
        pictures = {row.candidate_id: [Path("a.jpg"), Path("b.jpg")] for row in rows}
        sent = []

        def ask(system, content, schema):
            sent.append((system, content))
            if system == pick.SYSTEM_STEP1:
                numbers = [int(block["text"].split("번")[0]) for block in content[1:] if block["type"] == "text"]
                return json.dumps({"scenes": [{"n": n, "score": 3, "use_from": 0, "use_to": 5, "what": "", "why": ""}
                                              for n in numbers]}), 1000, 100
            return json.dumps({"title": "t", "summary": "s", "chapters": [
                {"title": "c", "description": "", "reason": "", "scenes": [1, 2]}]}), 500, 50

        with mock.patch.object(pick, "_image_block", lambda path: {"type": "image"}):
            done = pick.pick("머리글", rows, pictures, 480, ask)
        self.assertEqual(len(sent), 4)  # 50 + 50 + 20 scenes, then step 2
        self.assertTrue(all(sum(b["type"] == "image" for b in content) <= 100 for _, content in sent[:3]))
        self.assertIsInstance(sent[3][1], str)
        self.assertIn("목표 길이(480초)", sent[3][1])
        self.assertIn("메모 전체의 합은 600초", sent[3][1])
        self.assertEqual((done.input_tokens, done.output_tokens, done.pictures), (3500, 350, 240))
        self.assertEqual(len(done.result["left_out"]), 118)

    def test_saved_result_reads_back_with_total_and_price(self):
        done = pick.Picked({"title": "t", "summary": "s", "left_out": [], "chapters": [
            {"title": "c", "description": "", "reason": "", "scenes": [{"clip_start": 1.0, "clip_end": 6.5}]}]},
            100000, 10000, 364)
        with tempfile.TemporaryDirectory() as root:
            project = uuid4()
            pick.save_result(Path(root), project, done, model="claude-sonnet-5-5", target_minutes=8)
            saved = pick.load_result(Path(root), project)
        self.assertEqual((saved["total_seconds"], saved["usd"], saved["target_minutes"]), (5.5, 0.3, 8))
        self.assertIsNone(pick.load_result(Path("없는폴더"), project))


if __name__ == "__main__":
    unittest.main()
