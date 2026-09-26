import unittest
from types import SimpleNamespace
from unittest.mock import patch

import compose
import editor_formats
import main


def _response(payload: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
    )


class B108ModelPhraseTests(unittest.TestCase):
    def setUp(self):
        compose.clear_break_hints()

    def tearDown(self):
        compose.clear_break_hints()

    def test_model_may_mark_a_long_segment_as_one_unbreakable_phrase(self):
        payload = (
            '{"segments":[{"text":"中華民國中央銀行",'
            '"phrases":["中華民國中央銀行"]}]}'
        )
        with patch.object(main, "digest_completion", return_value=_response(payload)):
            phrases = main.segment_titles_for_breaks(["中華民國中央銀行"])

        self.assertEqual(phrases, {"中華民國中央銀行": ["中華民國中央銀行"]})

    def test_prompt_puts_word_integrity_before_phrase_length_preferences(self):
        prompt = editor_formats.TITLE_BREAK_SYSTEM
        self.assertIn("word integrity", prompt.lower())
        self.assertIn("higher priority", prompt.lower())
        self.assertIn("layout engine", prompt.lower())

    def test_safe_fullwidth_mismatch_is_realigned_to_original_characters(self):
        payload = (
            '{"segments":[{"text":"台積電:法說會展望",'
            '"phrases":["台積電:","法說會","展望"]}]}'
        )
        with patch.object(main, "digest_completion", return_value=_response(payload)):
            phrases = main.segment_titles_for_breaks(["台積電：法說會展望"])

        self.assertEqual(
            phrases,
            {"台積電：法說會展望": ["台積電：", "法說會", "展望"]},
        )


class B108ComposeBreakTests(unittest.TestCase):
    def setUp(self):
        compose.clear_break_hints()

    def tearDown(self):
        compose.clear_break_hints()

    def test_ten_full_keeps_a_long_model_phrase_even_when_it_exceeds_width(self):
        compose.set_break_hints({"中華民國中央銀行": ["中華民國中央銀行"]})
        with patch.object(compose, "_cover_title_metrics", return_value=(100, 100, 1)):
            lines = compose.cover_title_lines(
                "中華民國中央銀行 宣布升息", full_width=True
            )

        self.assertIn("中華民國中央銀行", lines)
        self.assertNotIn("中華民國中", lines)
        self.assertNotIn("央銀行", lines)

    def test_ten_split_keeps_a_long_model_phrase_before_character_limit(self):
        compose.set_break_hints({"歐洲中央銀行總部": ["歐洲中央銀行總部"]})
        with patch.object(compose, "_cover_title_metrics", return_value=(100, 100, 1)):
            lines = compose.cover_title_lines(
                "歐洲中央銀行總部 宣布升息", full_width=False
            )

        self.assertIn("歐洲中央銀行總部", lines)
        self.assertNotIn("歐洲中央", lines)
        self.assertNotIn("銀行總部", lines)

    def test_single_long_phrase_shrinks_below_normal_minimum_instead_of_splitting(self):
        phrase = "中華民國中央銀行"
        compose.set_break_hints({phrase: [phrase]})

        font = compose._fit_title_font(phrase, 100, 100, 80)

        self.assertLess(font.size, 80)
        self.assertLessEqual(font.getbbox(phrase)[2], 100)

    def test_yt_news_fallback_uses_model_boundaries_and_keeps_person_name(self):
        title = "王鴻薇揭露歐洲中央銀行政策"
        compose.set_break_hints(
            {title: ["王鴻薇", "揭露", "歐洲中央銀行", "政策"]}
        )

        line1, line2 = editor_formats.fallback_split_title(title)

        self.assertEqual(line1 + line2, title)
        self.assertTrue(line1.startswith("王鴻薇") or line2.startswith("王鴻薇"))
        self.assertNotEqual((line1, line2), ("王鴻", "薇揭露歐洲中央銀行政策"))

    def test_yt_planning_model_cannot_override_registered_word_boundaries(self):
        title = "王鴻薇揭露歐洲中央銀行政策"
        compose.set_break_hints(
            {title: ["王鴻薇", "揭露", "歐洲中央銀行", "政策"]}
        )

        self.assertFalse(compose.title_split_respects_hints(title, "王鴻"))
        self.assertTrue(compose.title_split_respects_hints(title, "王鴻薇揭露"))

    def test_yt_single_unbreakable_phrase_stays_on_one_shrunk_line(self):
        phrase = "中華民國中央銀行"
        compose.set_break_hints({phrase: [phrase]})

        self.assertEqual(editor_formats.fallback_split_title(phrase), (phrase, ""))
        font = compose._yt_shared_title_font([phrase, ""], 100, 100, 80)
        self.assertLess(font.size, 80)
        self.assertLessEqual(font.getbbox(phrase)[2], 100)

    def test_mismatched_hints_fallback_still_keeps_number_and_full_unit(self):
        title = "政府投資1234萬美元打造設施"
        compose.set_break_hints(
            {title: ["政府投資", "1234萬美金", "打造設施"]}
        )

        line1, line2 = compose._split_line_near_middle(title)

        self.assertEqual(line1 + line2, title)
        self.assertNotEqual((line1, line2), ("政府投資1234萬", "美元打造設施"))
        self.assertTrue("1234萬美元" in line1 or "1234萬美元" in line2)

    def test_fallback_keeps_latin_alphanumeric_token(self):
        title = "白宮全面封殺COVID-19研究報告"

        line1, line2 = compose._split_line_near_middle(title)

        self.assertEqual(line1 + line2, title)
        self.assertTrue("COVID-19" in line1 or "COVID-19" in line2)


if __name__ == "__main__":
    unittest.main()
