"""TODO 16: change a reel draft by talking to it."""

import json
import unittest

from backend.app.services.reel_chat import Edit, NotUnderstood, apply_edits, understand
from backend.app.services.reel_draft import HISTORY_KEY, PREVIOUS_KEY, ReelDraft, ReelScene, Shot, draft_from_json

SOURCE = "22222222-2222-4222-8222-222222222222"


def shot(index, start, end, caption="연습실에서 춤을 춘다"):
    return Shot(index, SOURCE, "dance.mp4", start, end, caption)


SHOTS = [shot(1, 0, 4), shot(2, 4, 6), shot(3, 6, 12, "거울 앞에서 브라운 스커트를 입고 돈다")]


def scene(index, start, end, caption, hook=False):
    return ReelScene(index, SOURCE, "dance.mp4", start, end, caption, "", hook, SHOTS[index - 1].caption)


def draft():
    scenes = (scene(3, 8, 10, "제목 장면", True), scene(1, 1, 3, "처음 뵙겠습니다"), scene(2, 4, 6, "카운트 맞추는 중"))
    return ReelDraft("short", "challenge", "도전기·연습 기록", "fast", "빠르게", 15, 6.0, "첫 댄스곡 도전기",
                     "llm:ollama/gemma3:4b", scenes, 3, title_lead="나만 아는 가수의")


def read(message, selected=None):
    edits, who = understand(message, draft(), selected, None)
    return edits


class RuleReadingTest(unittest.TestCase):
    def test_common_sentences_need_no_ai(self):
        self.assertEqual(read("3번 더 길게"), [Edit("longer", 3)])
        self.assertEqual(read("2번 2초 줄여줘"), [Edit("shorter", 2, 2.0)])
        self.assertEqual(read("여기에 자막 '최애템' 추가", selected=2), [Edit("caption", 2, text="최애템")])
        self.assertEqual(read("이 장면 자막 추가해줘", selected=1), [Edit("caption", 1)])
        self.assertEqual(read("2번 자막 빼줘"), [Edit("clear_caption", 2)])
        self.assertEqual(read("3번 빼"), [Edit("remove", 3)])
        self.assertEqual(read("3번을 맨 앞으로"), [Edit("move", 3, to=1)])
        self.assertEqual(read("제목을 '여름 꿀템 3가지'로 바꿔줘"), [Edit("title", text="여름 꿀템 3가지")])

    def test_last_scene_and_swap(self):
        self.assertEqual(read("마지막 장면 좀 줄여줘"), [Edit("shorter", 3)])  # the AI counted 6 of 7 here
        self.assertEqual(read("마지막 장면을 맨 앞으로"), [Edit("move", 3, to=1)])
        self.assertEqual(read("4번이랑 5번 순서 바꿔줘"), [Edit("swap", 4, to=5)])
        result = apply_edits(draft(), SHOTS, [Edit("swap", 1, to=3)])
        self.assertEqual([s.shot_index for s in result.draft.scenes], [2, 1, 3])
        self.assertTrue(result.draft.scenes[0].is_hook)

    def test_number_in_quotes_is_not_a_scene(self):
        self.assertEqual(read("여기 자막 '3번 입어봄' 넣어", selected=1), [Edit("caption", 1, text="3번 입어봄")])

    def test_unknown_sentence_goes_to_the_ai(self):
        with self.assertRaises(NotUnderstood):
            understand("좀 더 신나게 해줘", draft(), None, None)
        answer = json.dumps({"edits": [{"action": "shorter", "scene": 2, "seconds": None, "text": None, "to": None}]})
        edits, who = understand("2번 지루해", draft(), None, lambda system, user, schema: answer)
        self.assertEqual((edits, who), ([Edit("shorter", 2)], "ai"))

    def test_ai_edits_nobody_asked_for_are_dropped(self):
        # Seen on the real screen: "제목 좀 더 신나게 바꿔줘" with scene 3 picked also removed scene 3.
        answer = json.dumps({"edits": [{"action": "title", "scene": None, "seconds": None, "text": "신나는 첫 도전!", "to": None},
                                       {"action": "remove", "scene": 3, "seconds": None, "text": None, "to": None}]})
        edits, _ = understand("제목 좀 더 신나게 바꿔줘", draft(), 3, lambda system, user, schema: answer)
        self.assertEqual(edits, [Edit("title", text="신나는 첫 도전!")])


class ApplyTest(unittest.TestCase):
    def test_longer_stays_inside_the_cut(self):
        result = apply_edits(draft(), SHOTS, [Edit("longer", 2, 5.0)])
        first = result.draft.scenes[1]
        self.assertEqual((first.start_seconds, first.end_seconds), (0, 4))  # shot 1 is 0-4 s
        self.assertEqual(result.draft.total_seconds, 8.0)
        again = apply_edits(result.draft, SHOTS, [Edit("longer", 2)])
        self.assertEqual(again.done, ())
        self.assertIn("더 늘릴 수 없어요", again.skipped[0])

    def test_shorter_keeps_one_second(self):
        result = apply_edits(draft(), SHOTS, [Edit("shorter", 3, 9.0)])
        self.assertEqual(result.draft.scenes[2].end_seconds - result.draft.scenes[2].start_seconds, 1.0)

    def test_caption_title_and_hook(self):
        result = apply_edits(draft(), SHOTS, [Edit("caption", 2, text="최애템이에요."), Edit("move", 3, to=1),
                                              Edit("title", text="오늘의 / 연습 일지")])
        scenes = result.draft.scenes
        self.assertEqual([s.shot_index for s in scenes], [2, 3, 1])
        self.assertEqual([s.is_hook for s in scenes], [True, False, False])
        self.assertEqual(scenes[2].caption, "최애템이에요")
        self.assertEqual((result.draft.title_lead, result.draft.title), ("오늘의", "연습 일지"))

    def test_caption_without_words_is_written(self):
        ai = lambda system, user, schema: json.dumps({"caption": "빙글 도는 중 ✨"})  # noqa: E731
        result = apply_edits(draft(), SHOTS, [Edit("caption", 1)], complete=ai)
        self.assertEqual(result.draft.scenes[0].caption, "빙글 도는 중")
        result = apply_edits(draft(), SHOTS, [Edit("caption", 1)])  # no AI: the screen description, cut short
        self.assertEqual(result.draft.scenes[0].caption, "거울 앞에서 브라운 스커트를")

    def test_remove_and_missing_scene(self):
        result = apply_edits(draft(), SHOTS, [Edit("remove", 1), Edit("longer", 9), Edit("longer", None)])
        self.assertEqual([s.shot_index for s in result.draft.scenes], [1, 2])
        self.assertTrue(result.draft.scenes[0].is_hook)
        self.assertEqual(len(result.skipped), 2)

    def test_saved_previous_draft_is_ignored_when_reading(self):
        data = {**draft().to_json(), PREVIOUS_KEY: draft().to_json(), HISTORY_KEY: [{"draft": draft().to_json()}]}
        self.assertEqual(draft_from_json(data), draft())


# TODO 18: cuts 4 and 5 are not in the draft
MORE_SHOTS = [*SHOTS, shot(4, 12, 20, "바닥에 앉아 물을 마신다"), shot(5, 20, 22)]


class InsertTest(unittest.TestCase):
    def test_reading_put_back_sentences(self):
        self.assertEqual(read("12번 컷 넣어줘"), [Edit("insert", shot=12)])
        self.assertEqual(read("컷 4 2번 뒤에 넣어줘"), [Edit("insert", to=3, shot=4)])
        self.assertEqual(read("4번 컷 맨 앞에 추가"), [Edit("insert", to=1, shot=4)])
        self.assertEqual(read("4번 컷 여기 뒤에 넣어", selected=2), [Edit("insert", to=3, shot=4)])
        self.assertEqual(read("아까 뺀 장면 다시 넣어줘"), [Edit("insert")])
        self.assertEqual(read("여기 자막 다시 써줘", selected=1), [Edit("caption", 1)])  # not a cut

    def test_new_cut_goes_in_filmed_order_with_a_caption(self):
        result = apply_edits(draft(), MORE_SHOTS, [Edit("insert", shot=4)])
        self.assertEqual([s.shot_index for s in result.draft.scenes], [3, 1, 2, 4])
        new = result.draft.scenes[3]
        self.assertEqual((new.start_seconds, new.end_seconds), (15.1, 16.9))  # "빠르게" pace: 1.8 s from the middle
        self.assertEqual(new.caption, "바닥에 앉아 물을 마신다")
        self.assertIn("컷 4을 4번 장면으로 넣었어요", result.done[0])

    def test_put_back_where_asked_and_refuse_used_or_missing(self):
        result = apply_edits(draft(), MORE_SHOTS, [Edit("insert", to=2, shot=5), Edit("insert", shot=1),
                                                   Edit("insert", shot=9)])
        self.assertEqual([s.shot_index for s in result.draft.scenes], [3, 5, 1, 2])
        self.assertEqual(result.skipped, ("컷 1은 이미 3번 장면이에요", "컷 9이 없어요 (컷은 1~5번)"))

    def test_removed_scene_comes_back_as_it_was(self):
        before = draft()
        removed = apply_edits(before, MORE_SHOTS, [Edit("remove", 2)]).draft
        back = apply_edits(removed, MORE_SHOTS, [Edit("insert")], earlier=[before])
        self.assertEqual(back.draft.scenes, before.scenes)
        nothing = apply_edits(before, MORE_SHOTS, [Edit("insert")])
        self.assertIn("다시 넣을 장면을 못 찾았어요", nothing.skipped[0])
        same_turn = apply_edits(before, MORE_SHOTS, [Edit("remove", 3), Edit("insert", to=1)])
        self.assertEqual([s.shot_index for s in same_turn.draft.scenes], [2, 3, 1])


class NextTitleTest(unittest.TestCase):
    """TODO 20: "다른 제목" goes through the AI's title candidates."""

    def test_next_title_cycles_and_needs_candidates(self):
        from dataclasses import replace
        from backend.app.services.reel_draft import TitleOption
        self.assertEqual(read("다른 제목으로 바꿔줘"), [Edit("next_title")])
        options = (TitleOption("나만 아는 가수의", "첫 댄스곡 도전기", "모드"), TitleOption("처음인데", "칭찬 폭격", "반전"),
                   TitleOption("", "춤은 무조건 거울 앞", "단언"))
        current = replace(draft(), title_options=options)
        once = apply_edits(current, SHOTS, [Edit("next_title")])
        self.assertEqual((once.draft.title_lead, once.draft.title), ("처음인데", "칭찬 폭격"))
        self.assertEqual(once.done, ("제목을 '처음인데 / 칭찬 폭격'(으)로 바꿨어요",))
        twice = apply_edits(apply_edits(once.draft, SHOTS, [Edit("next_title")]).draft, SHOTS, [Edit("next_title")])
        self.assertEqual(twice.draft.title, "첫 댄스곡 도전기", "back to the first after the last")
        none = apply_edits(draft(), SHOTS, [Edit("next_title")])
        self.assertEqual(none.draft.title, "첫 댄스곡 도전기")
        self.assertIn("다른 제목 후보가 없어요", none.skipped[0])


if __name__ == "__main__":
    unittest.main()
