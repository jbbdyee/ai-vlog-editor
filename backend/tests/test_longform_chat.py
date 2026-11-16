import json
import tempfile
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.services import longform_chat as chat
from backend.app.services.edit_brain import Brain, BrainReply


def _inputs(lengths=(6.0, 4.0, 8.0, 5.0), unused=1, duration=60.0):
    source = uuid4()
    scenes, cuts = {}, []
    at = 0.0
    for index, length in enumerate(lengths):
        candidate = uuid4()
        scenes[candidate] = chat.SceneInfo(candidate, source, "0789.MP4", 1, at + 1, at + 4, f"장면 {index + 1}")
        cuts.append(chat.Cut(candidate, at, at + length))
        at += length + 2
    for index in range(unused):
        candidate = uuid4()
        scenes[candidate] = chat.SceneInfo(candidate, source, "0801.MP4", 1, 50.0 + index, 53.0 + index, "웃음")
    lines = {source: (chat.Line(0.5, 3.0, "아니 저 오늘 일찍 나왔거든요?", "me"), chat.Line(8.0, 9.5, "안녕하세요", "other"))}
    return chat.ChatInputs(scenes, tuple(cuts), {source: duration}, lines)


class RuleTests(unittest.TestCase):
    def test_paused_here_shorter_uses_paused_cut(self):
        edits = chat.rule_edits("[00:07] 이 장면 짧게", here=2, count=4)
        self.assertEqual(edits, [chat.Edit("shorter", cut=2)])

    def test_number_remove_and_compound(self):
        self.assertEqual(chat.rule_edits("3번 빼고 1번 2초 늘려줘", None, 4),
                         [chat.Edit("remove", cut=3), chat.Edit("longer", cut=1, seconds=2.0)])

    def test_swap_and_move(self):
        self.assertEqual(chat.rule_edits("3번이랑 4번 순서 바꿔", None, 4), [chat.Edit("swap", cut=3, to=4)])
        self.assertEqual(chat.rule_edits("2번을 맨 뒤로", None, 4), [chat.Edit("move", cut=2, to=-1)])

    def test_insert_unused(self):
        self.assertEqual(chat.rule_edits("안 쓴 장면 1 맨 앞에 넣어줘", None, 4), [chat.Edit("insert", scene=1, to=1)])

    def test_content_request_goes_to_brain(self):
        self.assertIsNone(chat.rule_edits("친구 얼굴만 나오는 데 줄여 줘", None, 4))

    def test_cut_at(self):
        inputs = _inputs()
        self.assertEqual(chat.cut_at(inputs.cuts, 7.0), (1, 1.0))
        self.assertEqual(chat.cut_at(inputs.cuts, 999.0)[0], 3)


class ApplyTests(unittest.TestCase):
    def test_shorter_keeps_middle_and_minimum(self):
        inputs = _inputs()
        result = chat.apply_edits(inputs, [chat.Edit("shorter", cut=1, seconds=3)])
        self.assertAlmostEqual(result.cuts[0].length, 3.0)
        self.assertAlmostEqual((result.cuts[0].start + result.cuts[0].end) / 2, 3.0)
        result = chat.apply_edits(inputs, [chat.Edit("set_length", cut=1, seconds=0.2)])
        self.assertAlmostEqual(result.cuts[0].length, chat.MIN_CUT_SECONDS)

    def test_longer_stays_inside_video(self):
        inputs = _inputs(duration=7.0)
        result = chat.apply_edits(inputs, [chat.Edit("longer", cut=1, seconds=10)])
        self.assertEqual((result.cuts[0].start, result.cuts[0].end), (0.0, 7.0))

    def test_numbers_mean_plan_before_message(self):
        inputs = _inputs()
        third = inputs.cuts[2].candidate_id
        result = chat.apply_edits(inputs, [chat.Edit("remove", cut=1), chat.Edit("shorter", cut=3, seconds=2)])
        self.assertEqual(len(result.cuts), 3)
        self.assertEqual(result.cuts[1].candidate_id, third)
        self.assertAlmostEqual(result.cuts[1].length, 6.0)

    def test_trim_end_at_paused_point(self):
        inputs = _inputs()
        edit = chat._fill_here(chat.Edit("trim_end", cut=3), (2, 2.5), 3)
        result = chat.apply_edits(inputs, [edit])
        self.assertAlmostEqual(result.cuts[2].length, 2.5)

    def test_swap_move_insert(self):
        inputs = _inputs()
        ids = [cut.candidate_id for cut in inputs.cuts]
        swapped = chat.apply_edits(inputs, [chat.Edit("swap", cut=1, to=2)])
        self.assertEqual([c.candidate_id for c in swapped.cuts][:2], [ids[1], ids[0]])
        moved = chat.apply_edits(inputs, [chat.Edit("move", cut=1, to=-1)])
        self.assertEqual(moved.cuts[-1].candidate_id, ids[0])
        inserted = chat.apply_edits(inputs, [chat.Edit("insert", scene=1, to=2)])
        self.assertEqual(len(inserted.cuts), 5)
        self.assertEqual(inserted.cuts[1].candidate_id, inputs.unused()[0].candidate_id)

    def test_unknown_number_is_skipped(self):
        result = chat.apply_edits(_inputs(), [chat.Edit("remove", cut=9)])
        self.assertEqual(result.done, ())
        self.assertTrue(result.skipped)


class BrainTests(unittest.TestCase):
    def _brain(self, payload, seen=None):
        def ask(system, user, schema):
            if seen is not None:
                seen.update(system=system, user=user, schema=schema)
            return BrainReply(json.dumps(payload, ensure_ascii=False), 1000, 100)
        return Brain("claude", "claude-haiku-5-5", ask)

    def test_brain_reads_content_request_without_file_names(self):
        seen = {}
        brain = self._brain({"edits": [{"action": "shorter", "cut": 2, "seconds": None, "to": None, "scene": None}],
                             "reply": "다른 사람이 말하는 2번을 줄였어"}, seen)
        understood = chat.understand("다른 사람이 말하는 컷 줄여 줘", _inputs(), None, brain)
        self.assertEqual(understood.edits, (chat.Edit("shorter", cut=2),))
        self.assertEqual(understood.engine, "llm:claude/claude-haiku-5-5")
        self.assertNotIn("0789", seen["system"])
        self.assertIn("[나] 아니 저 오늘", seen["system"])

    def test_remove_needs_a_removing_word(self):
        brain = self._brain({"edits": [{"action": "remove", "cut": 1, "seconds": None, "to": None, "scene": None},
                                       {"action": "longer", "cut": 2, "seconds": 2, "to": None, "scene": None}],
                             "reply": ""})
        understood = chat.understand("웃는 장면 좀 더 보여줘 길게", _inputs(), None, brain)
        self.assertEqual([edit.action for edit in understood.edits], ["longer"])

    def test_no_brain_for_hard_sentence(self):
        with self.assertRaises(chat.ChatEditError):
            chat.understand("친구 얼굴만 나오는 데 줄여 줘", _inputs(), None, None)


class ChatFileTests(unittest.TestCase):
    def test_history_is_capped(self):
        with tempfile.TemporaryDirectory() as root:
            project = uuid4()
            data = chat.load_chat(Path(root), project)
            data["history"] = [{"ids": [], "ranges": [], "label": str(i)} for i in range(15)]
            chat.save_chat(Path(root), project, data)
            again = chat.load_chat(Path(root), project)
            self.assertEqual(len(again["history"]), chat.MAX_HISTORY)
            self.assertEqual(again["history"][-1]["label"], "14")


if __name__ == "__main__":
    unittest.main()
