"""B106（2026-09-26 使用者裁決）：「不改字」的承諾落在消化文字層。

使用者原話：「不改文字不加文字 使用者貼的全部文字都要 但要排除使用者參雜的指令文字
所以還是要消化」。所以：
- 正文一字不改、不增不減——第五次比對不符**不再放行**，改回一個看得懂的錯誤；
- 專用指令欄有字**不再**讓逐字比對整個關掉；
- 以「指示:」「指令:」開頭的行保證是指令（USER_INSTRUCTION_RULES 第 2 條），
  比對前先從原文剔除，模型正確排掉它不能被判成掉字；
- 蓋章 OFF 的後製在不改字模式下只拿掉 `<蓋章>` 標記、保留那一行正文；
- 使用者貼的完稿本身帶 [標題] 之類的標記時，兩邊用同一套規則剝，不因標記判不符。
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import GenerateRequest, generate  # noqa: E402

SRC = "台北市今天下午出現強降雨\n氣象署發布大雨特報"


def response(variable):
    payload = {
        "style": "clean broadcast style",
        "structure": "one panel",
        "variable": variable,
        "chart_type": "資料圖表",
    }
    message = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


class _GenerateHarness(unittest.TestCase):
    def setUp(self):
        sleep_patcher = patch.object(main.time, "sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def run_generate(self, request, side_effect):
        with patch.object(
            main.openai_client.chat.completions, "create", side_effect=side_effect
        ) as create:
            try:
                return generate(request), None, create
            except HTTPException as exc:
                return None, exc, create


class FinalAttemptNoLongerPassesTests(_GenerateHarness):
    def test_mismatch_on_every_attempt_is_an_error_not_a_delivery(self):
        request = GenerateRequest(news_text=SRC, type_label="資料圖表", density="verbatim")
        result, exc, create = self.run_generate(
            request, [response("[標題] 台北市今天下午出現強降雨")] * main.DIGEST_ATTEMPTS
        )
        self.assertIsNone(result)
        self.assertEqual(create.call_count, main.DIGEST_ATTEMPTS)
        self.assertEqual(exc.status_code, 400)
        self.assertIn("不改字", exc.detail)
        self.assertIn("指示:", exc.detail)

    def test_exact_copy_still_passes(self):
        request = GenerateRequest(news_text=SRC, type_label="資料圖表", density="verbatim")
        result, exc, _ = self.run_generate(
            request, [response("[標題] 台北市今天下午出現強降雨\n[內文小標] 氣象署發布大雨特報")]
        )
        self.assertIsNone(exc)
        self.assertIn("氣象署發布大雨特報", result.variable)


class DedicatedInstructionDoesNotDisableGateTests(_GenerateHarness):
    def test_gate_still_runs_when_instruction_field_has_text(self):
        request = GenerateRequest(
            news_text=SRC, type_label="資料圖表", density="verbatim", user_instruction="用紅色"
        )
        result, exc, create = self.run_generate(
            request,
            [response("台北市今天下午出現強降雨")]
            + [response("台北市今天下午出現強降雨\n氣象署發布大雨特報")],
        )
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 2)
        self.assertIn("氣象署發布大雨特報", result.variable)


class InstructionLinesAreExcludedTests(unittest.TestCase):
    def test_marked_instruction_line_is_not_required_in_output(self):
        for marker in ("指示:", "指示：", "指令:", " 指令： "):
            with self.subTest(marker=marker):
                news = f"{SRC}\n{marker}用手繪風"
                self.assertEqual(main.verbatim_fidelity_problem(SRC, news), "")

    def test_instruction_text_leaking_into_output_is_reported(self):
        news = f"{SRC}\n指示:用手繪風"
        self.assertNotEqual(main.verbatim_fidelity_problem(f"{SRC}\n用手繪風", news), "")

    def test_unmarked_line_is_still_content(self):
        news = f"{SRC}\n用手繪風"
        self.assertNotEqual(main.verbatim_fidelity_problem(SRC, news), "")


class MarkersNormalisedOnBothSidesTests(unittest.TestCase):
    def test_user_pasted_script_with_markers(self):
        news = "[標題] 台北強降雨\n[內文小標] 氣象署發布大雨特報\n<蓋章> 午後雷雨"
        variable = "[標題] 台北強降雨\n[內文小標] 氣象署發布大雨特報\n<蓋章> 午後雷雨"
        self.assertEqual(main.verbatim_fidelity_problem(variable, news), "")

    def test_angle_brackets_in_user_text(self):
        news = "指數 A<B 且 C>D"
        self.assertEqual(main.verbatim_fidelity_problem("指數 A<B 且 C>D", news), "")


class StampOffKeepsVerbatimTextTests(_GenerateHarness):
    def test_stamp_line_body_survives_in_verbatim_mode(self):
        news = "台北市今天下午出現強降雨\n午後雷雨請注意"
        request = GenerateRequest(
            news_text=news, type_label="資料圖表", density="verbatim", stamp=False
        )
        result, exc, _ = self.run_generate(
            request, [response("[標題] 台北市今天下午出現強降雨\n<蓋章> 午後雷雨請注意")]
        )
        self.assertIsNone(exc)
        self.assertNotIn("<蓋章>", result.variable)
        self.assertIn("午後雷雨請注意", result.variable)
        # 後製完的成品仍要守住逐字承諾
        self.assertEqual(main.verbatim_fidelity_problem(result.variable, news), "")

    def test_stamp_line_still_dropped_outside_verbatim(self):
        self.assertEqual(
            main.drop_stamp_lines("[標題] 甲\n<蓋章> 乙"), "[標題] 甲"
        )


if __name__ == "__main__":
    unittest.main()
