import unittest

from backend.app.services import edit_rules, reference_style


class ReferenceStyleTest(unittest.TestCase):
    def test_cut_lengths_merge_changes_closer_than_the_minimum(self):
        # 0.1s flash after 3.0 and a change right at the end are not cuts
        lengths = reference_style.cut_lengths([3.0, 3.1, 5.0, 11.0, 11.9], 12.0)
        self.assertEqual(lengths, [3.0, 2.0, 6.0, 1.0])

    def test_stats_numbers(self):
        numbers = reference_style.stats([1.0, 1.5, 3.0, 4.0, 10.0])
        self.assertEqual(numbers["cut_count"], 5)
        self.assertEqual(numbers["median_cut"], 3.0)
        self.assertEqual(numbers["short_share"], 0.4)
        self.assertEqual(numbers["long_share"], 0.2)
        self.assertEqual(numbers["cuts_per_minute"], 15.4)

    def test_candidates_are_read_by_the_existing_rule_reader(self):
        numbers = reference_style.stats([1.0, 1.5, 1.8, 3.0, 4.0, 5.2, 6.0, 7.5])
        candidates = reference_style.rule_candidates(numbers)
        texts = [item["text"] for item in candidates]
        self.assertEqual(texts[0], "한 컷은 7초 넘지 않게")
        self.assertIn("한 컷은 3.5초 안팎", texts)
        self.assertIn("2초 안 되는 짧은 컷을 자주 섞기", texts)
        self.assertEqual(edit_rules.max_cut_seconds([texts[0]]), 7.0)
        # "M초 안팎" is a hint for the AI, not a hard limit
        self.assertIsNone(edit_rules.max_cut_seconds(["한 컷은 3.5초 안팎"]))

    def test_too_few_cuts_give_no_candidates(self):
        self.assertEqual(reference_style.rule_candidates(reference_style.stats([30.0, 40.0])), [])


if __name__ == "__main__":
    unittest.main()
