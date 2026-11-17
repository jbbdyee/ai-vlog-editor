"""TODO 28: the chat choices are recorded, undo takes them back, and repeated choices become rule candidates."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

from backend.app.services import longform_chat as chat
from backend.app.services import taste_log
from backend.tests.test_chat_choices import Store


def _root() -> Path:
    root = Path(tempfile.mkdtemp()) / "projects"
    root.mkdir()
    return root


def _choice(how, tag, seconds=5.0, before=None):
    return taste_log.Choice(how, uuid4().hex, (tag,), seconds, before)


class TagTests(unittest.TestCase):
    def test_speech_tags(self):
        lines = [chat.Line(0, 3, "안녕", "other"), chat.Line(3, 6, "응", "me"), chat.Line(20, 22, "음", None)]
        self.assertEqual(taste_log.scene_tags(lines, 0, 6), ["other_voice", "my_voice"])
        self.assertEqual(taste_log.scene_tags(lines, 3.5, 5), ["my_voice"])
        self.assertEqual(taste_log.scene_tags(lines, 20, 21), ["talk"])
        self.assertEqual(taste_log.scene_tags(lines, 10, 15), ["quiet"])


class CandidateTests(unittest.TestCase):
    def test_three_keeps_make_a_candidate_and_undo_takes_one_back(self):
        root = _root()
        project = uuid4()
        taste_log.record(root, project, "m1", [_choice("picked", "other_voice"), _choice("passed", "quiet")])
        taste_log.record(root, project, "m2", [_choice("kept", "other_voice")])
        self.assertEqual(taste_log.candidates(root), [])
        taste_log.record(root, project, "m3", [_choice("inserted", "other_voice")])
        found = taste_log.candidates(root)
        self.assertEqual([item.key for item in found], ["other_voice:keep"])
        self.assertIn("친구 수다", found[0].text)
        self.assertIn("3번 살렸고", found[0].why)
        taste_log.mark_undone(root, ["m3"])
        self.assertEqual(taste_log.candidates(root), [])

    def test_mixed_choices_and_passes_alone_make_none(self):
        root = _root()
        project = uuid4()
        taste_log.record(root, project, "a", [_choice("picked", "quiet")] * 3 + [_choice("removed", "quiet")] * 2)
        taste_log.record(root, project, "b", [_choice("passed", "my_voice")] * 8)
        self.assertEqual(taste_log.candidates(root), [])

    def test_drops_and_answer_hides(self):
        root = _root()
        taste_log.record(root, uuid4(), "a", [_choice("removed", "quiet"), _choice("replaced", "quiet"),
                                              _choice("removed", "quiet"), _choice("passed", "quiet")])
        found = taste_log.candidates(root)
        self.assertEqual([item.text for item in found], ["말 없는 장면은 뺀다"])
        self.assertNotIn("안 고름", found[0].why)  # passed pictures are recorded, not counted
        self.assertEqual(taste_log.candidates(root, ["말 없는 장면은 뺀다"]), [])  # already a rule
        taste_log.answer(root, "quiet:drop", False)
        self.assertEqual(taste_log.candidates(root), [])

    def test_shortened_cuts_suggest_a_length_rule(self):
        root = _root()
        taste_log.record(root, uuid4(), "a", [_choice("shortened", "talk", seconds, 12.0) for seconds in (5.2, 6.1, 4.0)])
        found = [item for item in taste_log.candidates(root) if item.key == "max_cut"]
        self.assertEqual(found[0].text, "한 컷은 5초 넘지 않게")
        self.assertEqual([item.key for item in taste_log.candidates(root, max_cut_rule=8.0) if item.key == "max_cut"], ["max_cut"])
        self.assertEqual([item.key for item in taste_log.candidates(root, max_cut_rule=5.0) if item.key == "max_cut"], [])


class ChatRecordsTests(unittest.TestCase):
    def setUp(self):
        self.root = _root()
        self.project = uuid4()
        first, second = uuid4(), uuid4()
        scenes, cuts = {}, []
        for start, end in [(2.0, 8.0), (20.0, 24.0)]:
            candidate = uuid4()
            scenes[candidate] = chat.SceneInfo(candidate, first, "0789.MP4", 1, start, end, None)
            cuts.append(chat.Cut(candidate, start, end))
        for index in range(2):
            candidate = uuid4()
            scenes[candidate] = chat.SceneInfo(candidate, second, "0801.MP4", 2, 5.0 + index * 10, 9.0 + index * 10, None)
        lines = {second: (chat.Line(4, 30, "야 이거 봐", "other"),), first: ()}
        self.store = Store(chat.ChatInputs(scenes, tuple(cuts), {first: 60.0, second: 60.0}, lines))
        for patch in (mock.patch.object(chat, "load_inputs", self.store.load),
                      mock.patch.object(chat, "_save_plan", self.store.save)):
            patch.start()
            self.addCleanup(patch.stop)

    def _events(self):
        return [(event["how"], event["tags"], bool(event.get("undone"))) for event in taste_log.load_log(self.root)["events"]]

    def test_pick_keep_remove_are_recorded_and_undo_marks_them(self):
        chat.send_message(None, self.root, self.project, "1번 다른 장면으로", None, None)
        offer = chat.load_chat(self.root, self.project)["messages"][-1]
        chat.pick_choice(None, self.root, self.project, offer["id"], 0)
        events = self._events()
        self.assertIn(("picked", ["other_voice"], False), events)
        self.assertIn(("replaced", ["quiet"], False), events)
        self.assertTrue(any(how == "passed" for how, _, _ in events))
        chat.undo(None, self.root, self.project)
        self.assertTrue(all(undone for _, _, undone in self._events()))

        chat.send_message(None, self.root, self.project, "2번 다른 장면으로", None, None)
        offer = chat.load_chat(self.root, self.project)["messages"][-1]
        chat.pick_choice(None, self.root, self.project, offer["id"], -1)
        self.assertIn(("kept", ["quiet"], False), self._events())
        chat.send_message(None, self.root, self.project, "2번 빼", None, None)
        self.assertEqual(self._events()[-1], ("removed", ["quiet"], False))


if __name__ == "__main__":
    unittest.main()
