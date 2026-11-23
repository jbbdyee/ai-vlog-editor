"""TODO 27: "내 편집 규칙" saved from the chat, shared by every project, read by the story direction."""
import json
import tempfile
import unittest
from pathlib import Path

from backend.app.services import edit_rules, story_direction


class RuleFileTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "projects"  # like outputs/projects

    def test_add_strips_stamp_dedupes_and_deletes(self):
        rules = edit_rules.add_rule(self.root, "[01:00]  한 컷은 8초   넘지 않게")
        self.assertEqual([rule["text"] for rule in rules], ["한 컷은 8초 넘지 않게"])
        self.assertTrue((self.root.parent / "me" / "edit_rules.json").is_file())
        self.assertEqual(len(edit_rules.add_rule(self.root, "한 컷은 8초 넘지 않게")), 1)
        self.assertEqual(edit_rules.delete_rule(self.root, rules[0]["id"]), [])
        with self.assertRaises(edit_rules.EditRuleError):
            edit_rules.add_rule(self.root, "  ")

    def test_max_cut_seconds(self):
        self.assertEqual(edit_rules.max_cut_seconds(["한 컷은 8초 넘지 않게", "친구 수다는 살려"]), 8.0)
        self.assertEqual(edit_rules.max_cut_seconds(["컷은 10초 이하로", "5초를 넘기지 마"]), 5.0)
        self.assertIsNone(edit_rules.max_cut_seconds(["공항 장면은 꼭 넣어"]))

    def test_typical_cut_seconds(self):
        self.assertEqual(edit_rules.typical_cut_seconds(["한 컷은 5.5초 안팎", "한 컷은 8초 넘지 않게"]), 5.5)
        self.assertIsNone(edit_rules.typical_cut_seconds(["한 컷은 8초 넘지 않게"]))
        self.assertIsNone(edit_rules.typical_cut_seconds(["자막은 1초쯤마다 바꾸기", "자막 한 번에 6글자 안팎"]))
        self.assertIsNone(edit_rules.max_cut_seconds(["한 컷은 5.5초 안팎"]))


class StoryPromptTests(unittest.TestCase):
    def test_rules_go_into_the_prompt(self):
        seen = {}

        def complete(system, user, schema):
            seen["user"] = user
            return "not json"  # falls back to the rule direction; the prompt is what matters here
        story_direction.recommend_story_direction([], {}, ("ollama", "test", complete), None, "",
                                                  ["한 컷은 8초 넘지 않게"])
        self.assertIn("내 편집 규칙", seen["user"])
        self.assertIn("- 한 컷은 8초 넘지 않게", seen["user"])


class MyVoiceRuleTests(unittest.TestCase):
    def test_my_voice_rule_is_recognised(self):
        # TODO 32-2: the rule candidate from TODO 29 turns it on; the friend-chat rule does not
        self.assertTrue(edit_rules.keeps_my_voice(["내가 말하는 장면은 살린다"]))
        self.assertTrue(edit_rules.keeps_my_voice(["내 목소리 나오는 장면 살려줘"]))
        self.assertFalse(edit_rules.keeps_my_voice(["다른 사람 목소리가 나오는 장면(친구 수다)은 살린다", "한 컷은 8초 넘지 않게"]))
