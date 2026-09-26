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

    def test_material_is_plain_lines_without_numbering(self):
        payload = '{"segments": []}'
        with patch.object(main, "digest_completion", return_value=_response(payload)) as call:
            main.segment_titles_for_breaks(["Q3營收上看9000億", "歐洲熱浪台灣豪雨"])
        self.assertEqual(call.call_args.kwargs["news_text"], "Q3營收上看9000億\n歐洲熱浪台灣豪雨")

    def test_list_numbering_echoed_by_small_models_is_stripped(self):
        """2026-09-14 實測：gpt-5.4-mini 回 "1. 台積電…"＋詞組 "1."，nano 回 "1. "；照抄的話整段被丟。"""
        mini = (
            '{"segments": [{"text": "1. 台積電法說會Q3營收上看9000億",'
            ' "phrases": ["1.", "台積電", "法說會", "Q3", "營收", "上看9000億"]}]}'
        )
        nano = (
            '{"segments": [{"text": "1. 台積電法說會Q3營收上看9000億",'
            ' "phrases": ["1. ", "台積電", "法說會", "Q3", "營收上看9000億"]}]}'
        )
        glued = (
            '{"segments": [{"text": "2. 歐洲熱浪台灣豪雨",'
            ' "phrases": ["2. 歐洲熱浪", "台灣豪雨"]}]}'
        )
        with patch.object(main, "digest_completion", return_value=_response(mini)):
            self.assertEqual(
                main.segment_titles_for_breaks(["台積電法說會Q3營收上看9000億"]),
                {"台積電法說會Q3營收上看9000億": ["台積電", "法說會", "Q3", "營收", "上看9000億"]},
            )
        with patch.object(main, "digest_completion", return_value=_response(nano)):
            self.assertEqual(
                main.segment_titles_for_breaks(["台積電法說會Q3營收上看9000億"]),
                {"台積電法說會Q3營收上看9000億": ["台積電", "法說會", "Q3", "營收上看9000億"]},
            )
        with patch.object(main, "digest_completion", return_value=_response(glued)):
            self.assertEqual(
                main.segment_titles_for_breaks(["歐洲熱浪台灣豪雨"]),
                {"歐洲熱浪台灣豪雨": ["歐洲熱浪", "台灣豪雨"]},
            )

    def test_a_segment_starting_with_a_decimal_is_not_mistaken_for_numbering(self):
        payload = '{"segments": [{"text": "1.2兆資本支出上看新高", "phrases": ["1.2兆", "資本支出", "上看新高"]}]}'
        with patch.object(main, "digest_completion", return_value=_response(payload)):
            self.assertEqual(
                main.segment_titles_for_breaks(["1.2兆資本支出上看新高"]),
                {"1.2兆資本支出上看新高": ["1.2兆", "資本支出", "上看新高"]},
            )

    def test_break_model_is_the_small_one_and_env_overrides(self):
        with patch.dict(os.environ, {"TITLE_BREAK_MODEL": ""}):
            self.assertEqual(main.resolve_title_break_model(), main.DEFAULT_TITLE_BREAK_MODEL)
        with patch.dict(os.environ, {"TITLE_BREAK_MODEL": "gpt-5.4-nano"}):
            self.assertEqual(main.resolve_title_break_model(), "gpt-5.4-nano")
        # 主消化的覆寫不能滲進來（可能是 OpenRouter slug）
        with patch.dict(os.environ, {"TITLE_BREAK_MODEL": "", "DIGEST_MODEL": "anthropic/claude-sonnet-5"}):
            self.assertEqual(main.resolve_title_break_model(), main.DEFAULT_TITLE_BREAK_MODEL)
        payload = '{"segments": []}'
        with patch.dict(os.environ, {"TITLE_BREAK_MODEL": "gpt-5.4-nano"}), \
                patch.object(main, "digest_completion", return_value=_response(payload)) as call:
            main.segment_titles_for_breaks(["Q3營收上看9000億"])
        self.assertEqual(call.call_args.kwargs["model"], "gpt-5.4-nano")
        # 逾時值搬到 test_break_timeout_was_widened_to_ten_seconds 專門釘
        # （2026-09-16 從 8.0 放寬到 10.0，理由見該題與常數上方的註解）
        self.assertEqual(
            call.call_args.kwargs["timeout"], main.TITLE_BREAK_TIMEOUT_SECONDS
        )

    def test_default_break_model_is_gemini_and_rolls_back_independently(self):
        """2026-09-16：斷句預設換成 gemini-3.8-flash，依斷句自己的 156 次實測。

        釘住兩件事：①預設值真的換了（換回去會轉紅，逼人說明為什麼）；
        ②退路是 TITLE_BREAK_MODEL，而且**不會被 DIGEST_MODEL 連動**——
        兩條線要能分開回退，否則主消化回退 Claude 時會把斷句一起拖走。
        """
        # 2026-09-16 Codex 複查：原本寫成 `if 後端是 openrouter: assertEqual`，
        # 在 native 環境會整題靜默跳過、什麼都沒釘到。改成三個後端都各自斷言，
        # 沒有一條路徑能無聲通過。
        expected = {
            "openrouter.ai": "google/gemini-3.8-flash",
            "generativelanguage.googleapis.com": main.DEFAULT_DIGEST_MODEL,
        }.get(main.openai_client.base_url.host, "gpt-5.4-mini")
        self.assertEqual(main.DEFAULT_TITLE_BREAK_MODEL, expected)
        # 回退指引推薦的 slug 帶 /，非 openrouter 後端必須擋掉（否則送進
        # api.openai.com 一定失敗，而失敗被吃掉不會有人發現）
        with patch.dict(os.environ, {"TITLE_BREAK_MODEL": "openai/gpt-5.4-mini"}):
            on_openrouter = main.openai_client.base_url.host == "openrouter.ai"
            self.assertEqual(
                main.resolve_title_break_model(),
                "openai/gpt-5.4-mini" if on_openrouter else main.DEFAULT_TITLE_BREAK_MODEL,
            )
        with patch.dict(os.environ, {"TITLE_BREAK_MODEL": "gpt-5.4-mini"}):
            self.assertEqual(main.resolve_title_break_model(), "gpt-5.4-mini")
        # 主消化回退 Claude 時，斷句不准被連動（用不帶 / 的值才能在所有後端斷言）
        with patch.dict(os.environ, {
            "TITLE_BREAK_MODEL": "gpt-5.4-mini",
            "DIGEST_MODEL": "anthropic/claude-sonnet-5",
        }):
            self.assertEqual(main.resolve_title_break_model(), "gpt-5.4-mini")

    def test_ai_title_mode_calls_the_model_for_pre_split_prompt_lines(self):
        """B109（2026-09-26）：撤回 B75；AI prompt 會讀預切列，故也要詞組邊界。"""
        payload = '{"segments": [{"text": "Q3營收上看9000億", "phrases": ["Q3營收", "上看9000億"]}]}'
        with patch.object(main, "digest_completion", return_value=_response(payload)) as call:
            main.apply_title_break_hints("台積電法說會 Q3營收上看9000億", "")
        call.assert_called_once()
        self.assertEqual(main.compose._BREAK_HINTS.get(), {"Q3營收上看9000億": (4,)})

    def test_composite_callers_still_get_registered_boundaries(self):
        """B109 不能回歸原有 composite 路徑：Pillow 仍要讀同一份詞組邊界。"""
        payload = '{"segments": [{"text": "Q3營收上看9000億", "phrases": ["Q3營收", "上看", "9000億"]}]}'
        with patch.object(main, "digest_completion", return_value=_response(payload)) as call:
            main.apply_title_break_hints("台積電法說會 Q3營收上看9000億", "")
        call.assert_called_once()
        self.assertEqual(main.compose._BREAK_HINTS.get(), {"Q3營收上看9000億": (4, 6)})

    def test_break_timeout_was_widened_to_ten_seconds(self):
        """2026-09-16 使用者裁定 8 → 10 秒：gemini 6 次失敗有 4 次撞在 8.0 這道牆上。"""
        self.assertEqual(main.TITLE_BREAK_TIMEOUT_SECONDS, 10.0)

    def test_apply_skips_the_model_when_nothing_could_be_split(self):
        with patch.object(main, "digest_completion") as call:
            main.apply_title_break_hints("葉門青年運動 奪下紅海咽喉", "")
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
