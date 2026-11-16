"""TODO 27: "다른 장면으로" choices, picking one, undo marks and honest replies in the longform chat."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

from backend.app.services import longform_chat as chat
from backend.app.services.edit_brain import Brain, BrainReply


def _inputs(unused=2, duration=60.0):
    first, second = uuid4(), uuid4()
    scenes, cuts = {}, []
    for index, (start, end) in enumerate([(2.0, 8.0), (20.0, 24.0)]):
        candidate = uuid4()
        scenes[candidate] = chat.SceneInfo(candidate, first, "0789.MP4", 1, start, end, f"장면 {index + 1}")
        cuts.append(chat.Cut(candidate, start, end))
    for index in range(unused):
        candidate = uuid4()
        scenes[candidate] = chat.SceneInfo(candidate, second, "0801.MP4", 2, 5.0 + index * 10, 9.0 + index * 10, "웃음")
    return chat.ChatInputs(scenes, tuple(cuts), {first: duration, second: duration}, {})


class Store:
    """The plan lives in memory instead of the database."""

    def __init__(self, inputs):
        self.inputs = inputs

    def load(self, session, root, project_id):
        return self.inputs

    def save(self, session, project_id, cuts):
        self.inputs = chat.ChatInputs(self.inputs.scenes, tuple(cuts), self.inputs.durations, self.inputs.lines)


class ReplaceRequestTests(unittest.TestCase):
    def test_words(self):
        self.assertEqual(chat.replace_request("[01:00] 다른 장면으로", 9), 9)
        self.assertEqual(chat.replace_request("3번 다른 거로 바꿔 줘", None), 3)
        self.assertEqual(chat.replace_request("이거 바꿔 줘", 4), 4)
        self.assertIsNone(chat.replace_request("다른 장면으로", None))
        self.assertIs(chat.replace_request("3번이랑 4번 바꿔", None), False)
        self.assertIs(chat.replace_request("안 쓴 장면 1 넣어 줘", None), False)
        self.assertIs(chat.replace_request("이 장면 짧게", 2), False)


class ChoiceTests(unittest.TestCase):
    def test_unused_first_then_same_video_parts(self):
        inputs = _inputs()
        choices = chat.replacement_choices(inputs, 0)
        self.assertEqual([c.kind for c in choices[:2]], ["unused", "unused"])
        same = [c for c in choices if c.kind == "same"]
        self.assertTrue(same)
        for choice in same:
            self.assertEqual(choice.candidate_id, inputs.cuts[0].candidate_id)
            self.assertAlmostEqual(choice.end - choice.start, 6.0)
            for cut in inputs.cuts:  # never overlaps a cut that is already used
                self.assertTrue(choice.end <= cut.start + 1e-6 or choice.start >= cut.end - 1e-6)
        self.assertLessEqual(len(choices), chat.MAX_CHOICES)


class SendAndPickTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.project = uuid4()
        self.store = Store(_inputs())
        patches = [mock.patch.object(chat, "load_inputs", self.store.load),
                   mock.patch.object(chat, "_save_plan", self.store.save)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_pick_replaces_and_undo_reopens(self):
        before = self.store.inputs.cuts
        chat.send_message(None, self.root, self.project, "1번 다른 장면으로", None, None)
        offer = chat.load_chat(self.root, self.project)["messages"][-1]
        self.assertEqual(offer["for_cut"], 1)
        self.assertEqual(self.store.inputs.cuts, before)  # nothing changes until a picture is picked
        chat.pick_choice(None, self.root, self.project, offer["id"], 0)
        self.assertEqual(str(self.store.inputs.cuts[0].candidate_id), offer["choices"][0]["candidate_id"])
        with self.assertRaises(chat.ChatEditError):
            chat.pick_choice(None, self.root, self.project, offer["id"], 1)
        chat.undo(None, self.root, self.project)
        self.assertEqual(self.store.inputs.cuts, before)
        messages = chat.load_chat(self.root, self.project)["messages"]
        self.assertIsNone(next(m for m in messages if m["id"] == offer["id"])["picked"])
        self.assertTrue(any(m.get("undone") for m in messages))

    def test_undone_request_is_not_sent_again_and_no_change_is_said(self):
        seen = []

        def ask(system, user, schema):
            seen.append(user)
            return BrainReply('{"edits": [{"action": "remove", "cut": 9, "seconds": null, "to": null, "scene": null}], '
                              '"reply": "9번 컷을 뺐어"}')
        brain = Brain("ollama", "test", ask)
        chat.send_message(None, self.root, self.project, "1번 빼", None, brain)  # rule
        chat.undo(None, self.root, self.project)
        chat.send_message(None, self.root, self.project, "곰 인형 컷 빼 줘", None, brain)
        self.assertNotIn("1번 빼", seen[-1])
        last = chat.load_chat(self.root, self.project)["messages"][-1]
        self.assertTrue(last["no_change"])
        self.assertTrue(last["text"].startswith("바뀐 것 없음"))
        self.assertNotIn("뺐어", last["text"])
