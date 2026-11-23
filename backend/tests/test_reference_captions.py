import unittest

from backend.app.services import edit_rules, reference_captions as rc


def frame(*lines):
    return [{"text": text, "y": y, "h": h} for text, y, h in lines]


class ReferenceCaptionsTest(unittest.TestCase):
    def test_garbled_and_too_short_reads_are_not_subtitles(self):
        self.assertEqual(rc.hangul_only("(이 자막은 제가 넣은 거)"), "이자막은제가넣은거")
        self.assertIsNone(rc.hangul_only("1넣\\수(&법翁수k힣1쉬ib"))
        self.assertIsNone(rc.hangul_only("가"))

    def test_screen_recording_app_text_is_dropped_and_subtitles_followed(self):
        app = [("댓글 추가...", 1450, 28), ("X 관심 없음", 1320, 22), ("#제작지원 이 영상에서 실제", 1236, 40)]
        raw = []
        words = ["목소리 소름", "이건 다른 버전", "분위기까지 바꿨어요"]
        for index in range(12):
            caption = (words[index // 4], 870, 60)
            small = ("설정 커넥터 맞춤", 700, 30)  # app screen inside the reel: too small
            raw.append({"height": 1564, "lines": frame(*app, caption, small)})
        raw[2]["lines"] = frame(*app)  # OCR misses one frame: still the same subtitle
        found = rc.tracks(rc.frames_from_ocr(raw), 0.5)
        self.assertEqual([(t["start"], t["end"], t["zone"], t["text"]) for t in found],
                         [(0.0, 1.5, "가운데", "목소리소름"), (2.0, 3.5, "가운데", "이건다른버전"),
                          (4.0, 5.5, "가운데", "분위기까지바꿨어요")])

    def test_bottom_subtitles_count_when_it_is_not_a_screen_recording(self):
        words = ["오늘은 학원 가는 날", "점심은 김밥", "저녁 수업 시작"]
        raw = [{"height": 1080, "lines": frame((words[index // 2], 960, 50))} for index in range(6)]
        found = rc.tracks(rc.frames_from_ocr(raw), 1.0)
        self.assertEqual([t["start"] for t in found], [0.0, 2.0, 4.0])
        self.assertEqual({t["zone"] for t in found}, {"아래"})

    def test_numbers_and_candidates(self):
        found = [{"start": 0.0, "end": 0.5, "zone": "가운데", "text": "가나다라"},
                 {"start": 1.0, "end": 2.0, "zone": "가운데", "text": "가나다라마바"},
                 {"start": 2.0, "end": 2.5, "zone": "위", "text": "가나"},
                 {"start": 4.0, "end": 5.0, "zone": "가운데", "text": "가나다라마"}]
        numbers = rc.caption_stats(found, 10.0, 0.5)
        self.assertEqual(numbers["change_count"], 4)
        self.assertEqual(numbers["median_gap"], 1.0)
        self.assertEqual(numbers["median_chars"], 4.5)
        self.assertEqual(numbers["zone_share"]["가운데"], 0.75)
        self.assertEqual(numbers["on_screen_share"], 0.45)
        texts = [item["text"] for item in rc.caption_candidates(numbers)]
        self.assertEqual(texts, ["자막은 1초쯤마다 바꾸기", "자막 한 번에 4글자 안팎", "자막은 화면 가운데에"])
        # a subtitle rule is never read as a cut-length limit
        self.assertIsNone(edit_rules.max_cut_seconds(texts))

    def test_too_few_subtitles_give_no_candidates(self):
        self.assertEqual(rc.caption_candidates(rc.caption_stats([], 10.0, 0.5)), [])


if __name__ == "__main__":
    unittest.main()
