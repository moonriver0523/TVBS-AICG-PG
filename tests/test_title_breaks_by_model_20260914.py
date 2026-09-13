# -*- coding: utf-8 -*-
"""2026-09-14 使用者裁決：斷句交給消化模型，規則只當退路。"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402


def _response(payload: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])


class ComposeHintTests(unittest.TestCase):
    def setUp(self):
        compose.clear_break_hints()

    def tearDown(self):
        compose.clear_break_hints()

    def test_no_hints_falls_back_to_the_rules(self):
        self.assertEqual(compose._split_line_near_middle("歐洲熱浪台灣豪雨"), ("歐洲熱浪", "台灣豪雨"))

    def test_the_hint_nearest_the_middle_wins(self):
        compose.set_break_hints({"台積電法說會Q3營收上看9000億": ["台積電", "法說會", "Q3營收", "上看9000億"]})
        self.assertEqual(
            compose._split_line_near_middle("台積電法說會Q3營收上看9000億"),
            ("台積電法說會", "Q3營收上看9000億"),
        )

    def test_a_substring_of_a_registered_segment_reuses_its_boundaries(self):
        """拆過一次的行再拆（wrap 會連拆），位移要對得回去：以前這裡切成「上／看」。"""
        compose.set_break_hints({"台積電法說會Q3營收上看9000億": ["台積電", "法說會", "Q3營收", "上看9000億"]})
        self.assertEqual(compose._split_line_near_middle("Q3營收上看9000億"), ("Q3營收", "上看9000億"))

    def test_unfaithful_phrases_are_ignored(self):
        compose.set_break_hints({"歐洲熱浪台灣豪雨": ["歐洲熱浪", "臺灣豪雨"]})
        self.assertEqual(compose._hint_cuts("歐洲熱浪台灣豪雨"), [])
        self.assertEqual(compose._split_line_near_middle("歐洲熱浪台灣豪雨"), ("歐洲熱浪", "台灣豪雨"))

    def test_a_hint_inside_a_number_is_still_refused(self):
        compose.set_break_hints({"投資產業184億元計畫": ["投資產業18", "4億元計畫"]})
        head, tail = compose._split_line_near_middle("投資產業184億元計畫")
        self.assertFalse(head.endswith("18") and tail.startswith("4"))

    def test_cover_title_lines_follow_the_hints_end_to_end(self):
        compose.set_break_hints({"台積電法說會Q3營收上看9000億": ["台積電", "法說會", "Q3營收", "上看9000億"]})
        lines = compose.cover_title_lines("台積電法說會Q3營收上看9000億 台灣豪雨警報")
        self.assertNotIn("上", [ln[-1] for ln in lines if ln.endswith("上")])
        for ln in lines:
            self.assertNotIn(ln, ("Q3營收上", "看9000億"))

    def test_yt_fallback_split_uses_the_same_engine(self):
        compose.set_break_hints({"川普宣布對加拿大課徵關稅": ["川普", "宣布", "對加拿大", "課徵關稅"]})
        self.assertEqual(editor_formats.fallback_split_title("川普宣布對加拿大課徵關稅"), ("川普宣布", "對加拿大課徵關稅"))


class SegmentationCallTests(unittest.TestCase):
    def setUp(self):
        compose.clear_break_hints()

    def tearDown(self):
        compose.clear_break_hints()

    def test_short_segments_never_reach_the_model(self):
        self.assertEqual(main.title_break_inputs("葉門青年運動 奪下紅海咽喉"), [])
        self.assertEqual(main.title_break_inputs("台積電法說會 Q3營收上看9000億"), ["Q3營收上看9000億"])

    def test_faithful_phrases_are_kept_and_unfaithful_dropped(self):
        payload = (
            '{"segments": [{"text": "Q3營收上看9000億", "phrases": ["Q3營收", "上看9000億"]},'
            ' {"text": "歐洲熱浪台灣豪雨", "phrases": ["歐洲熱浪", "臺灣豪雨"]},'
            ' {"text": "不在清單裡的段", "phrases": ["不在", "清單裡的段"]}]}'
        )
        with patch.object(main, "digest_completion", return_value=_response(payload)) as call:
            out = main.segment_titles_for_breaks(["Q3營收上看9000億", "歐洲熱浪台灣豪雨"])
        self.assertEqual(out, {"Q3營收上看9000億": ["Q3營收", "上看9000億"]})
        self.assertEqual(call.call_args.kwargs["site"], "title-break")
        self.assertEqual(call.call_args.kwargs["timeout"], main.TITLE_BREAK_TIMEOUT_SECONDS)

    def test_a_model_failure_falls_back_to_the_rules_silently(self):
        with patch.object(main, "digest_completion", side_effect=TimeoutError("slow")):
            self.assertEqual(main.segment_titles_for_breaks(["Q3營收上看9000億"]), {})

    def test_apply_registers_hints_for_compose(self):
        payload = '{"segments": [{"text": "Q3營收上看9000億", "phrases": ["Q3營收", "上看9000億"]}]}'
        with patch.object(main, "digest_completion", return_value=_response(payload)):
            main.apply_title_break_hints("台積電法說會 Q3營收上看9000億", "")
        self.assertEqual(compose._split_line_near_middle("Q3營收上看9000億"), ("Q3營收", "上看9000億"))

    def test_apply_skips_the_model_when_nothing_could_be_split(self):
        with patch.object(main, "digest_completion") as call:
            main.apply_title_break_hints("葉門青年運動 奪下紅海咽喉", "")
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
