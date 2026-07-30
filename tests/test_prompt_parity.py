"""news_prompt.py 與 app.js 的 Prompt 規則必須逐字一致。

這兩份是同一套規則的兩個實作（網頁版在前端組、LINE Bot 在後端組）。
只改一邊會讓 LINE 出的圖與網頁版不同，且不會有任何執行期錯誤——
所以用測試把「不同步」變成看得見的失敗。
"""

import io
import pathlib
import re
import unittest

import news_prompt

APP_JS = pathlib.Path(__file__).resolve().parent.parent / "app.js"


def js_source() -> str:
    return io.open(APP_JS, encoding="utf-8").read()


def js_template_literal(name: str, source: str) -> str | None:
    """取出 app.js 裡 const NAME = `...`; 的內容。"""
    match = re.search(r"const " + name + r"\s*=\s*\n?`(.*?)`;", source, re.S)
    return match.group(1) if match else None


class ConstantParityTests(unittest.TestCase):
    def setUp(self):
        self.source = js_source()

    def assert_same(self, name: str, python_value: str):
        js_value = js_template_literal(name, self.source)
        self.assertIsNotNone(js_value, f"app.js 裡找不到 {name}，移植來源可能被改名")
        self.assertEqual(
            js_value,
            python_value,
            f"{name} 與 app.js 不一致：改了一邊就要同步另一邊",
        )

    def test_reporter_text_rules(self):
        self.assert_same("REPORTER_TEXT_RULES", news_prompt.REPORTER_TEXT_RULES)

    def test_editor_text_rules(self):
        self.assert_same("EDITOR_TEXT_RULES", news_prompt.EDITOR_TEXT_RULES)

    def test_reporter_safe_area(self):
        self.assert_same("REPORTER_SAFE_AREA", news_prompt.REPORTER_SAFE_AREA)

    def test_editor_safe_area(self):
        self.assert_same("EDITOR_SAFE_AREA", news_prompt.EDITOR_SAFE_AREA)

    def test_full_bleed_rules(self):
        self.assert_same("FULL_BLEED_RULES", news_prompt.FULL_BLEED_RULES)

    def test_canvas_lines(self):
        for name, value in (
            ("CANVAS_MARGIN_LINE", news_prompt.CANVAS_MARGIN_LINE),
            ("CANVAS_FULL_BLEED_LINE", news_prompt.CANVAS_FULL_BLEED_LINE),
        ):
            with self.subTest(name=name):
                self.assert_same(name, value)

    def test_system_disclaimer(self):
        match = re.search(r"const SYSTEM_DISCLAIMER = '(.*?)';", self.source)
        self.assertIsNotNone(match, "app.js 裡找不到 SYSTEM_DISCLAIMER")
        self.assertEqual(match.group(1), news_prompt.SYSTEM_DISCLAIMER)


class BuiltPromptShapeTests(unittest.TestCase):
    """組裝結果的關鍵骨架——區塊順序或標頭被改動時要能發現。"""

    def build(self, role="記者", engine="gemini"):
        return news_prompt.build_prompt(
            role=role,
            engine=engine,
            type_label="資料圖表",
            style="STYLE-X",
            structure="STRUCT-Y",
            variable="VAR-Z",
        )

    def test_sections_in_expected_order(self):
        prompt = self.build()
        markers = [
            "CANVAS",
            "Text Rules",
            "STYLE (VISUAL LANGUAGE ONLY)",
            "STRUCTURE (LAYOUT RULES)",
            "VARIABLE FIELDS (USER INPUT)",
            "EMPTY MARGIN RULES (CRITICAL — MUST PRESERVE)",
            "FINAL OUTPUT RULE",
        ]
        positions = [prompt.index(m) for m in markers]
        self.assertEqual(positions, sorted(positions), "區塊順序與 app.js 不同")

    def test_user_content_is_embedded(self):
        prompt = self.build()
        for chunk in ("STYLE-X", "STRUCT-Y", "VAR-Z", "資料圖表"):
            self.assertIn(chunk, prompt)

    def test_gpt_and_gemini_have_different_openers(self):
        self.assertTrue(self.build(engine="gpt").startswith("Generate an image:"))
        self.assertTrue(self.build(engine="gemini").startswith("Create a professional"))

    def test_editor_role_uses_editor_rules(self):
        editor = self.build(role="編輯")
        self.assertIn("Must be split into exactly two lines", editor)
        self.assertNotIn("Must be split into exactly two lines", self.build())

    def test_safe_frame_mode_swaps_margin_rules_for_full_bleed(self):
        framed = news_prompt.build_prompt(
            role="記者",
            engine="gemini",
            type_label="資料圖表",
            style="S",
            structure="T",
            variable="V",
            safe_frame=True,
        )
        self.assertIn("FULL-FRAME RULES", framed)
        self.assertNotIn("EMPTY MARGIN RULES", framed)
        self.assertNotIn(news_prompt.CANVAS_MARGIN_LINE, framed)
        self.assertIn(news_prompt.CANVAS_FULL_BLEED_LINE, framed)

    def test_safe_frame_mode_has_no_numeric_margin_spec(self):
        """滿版規則同樣不得出現任何比例數字：數字會被模型畫進圖裡。"""
        self.assertFalse(
            any(ch.isdigit() for ch in news_prompt.FULL_BLEED_RULES),
        )

    def test_default_mode_output_unchanged_by_new_parameter(self):
        """新增參數不得改動既有預設輸出，否則現行流程會靜默漂移。"""
        kwargs = dict(
            role="記者",
            engine="gemini",
            type_label="資料圖表",
            style="S",
            structure="T",
            variable="V",
        )
        self.assertEqual(
            news_prompt.build_prompt(**kwargs),
            news_prompt.build_prompt(**kwargs, safe_frame=False, aspect_ratio="16:9"),
        )

    def test_aspect_ratio_is_configurable(self):
        prompt = news_prompt.build_prompt(
            role="記者",
            engine="gemini",
            type_label="資料圖表",
            style="S",
            structure="T",
            variable="V",
            aspect_ratio="21:9",
        )
        self.assertIn("- Aspect ratio: 21:9", prompt)

    def test_compose_variable_prefixes_disclaimer(self):
        composed = news_prompt.compose_variable("[標題]")
        self.assertTrue(composed.startswith(news_prompt.SYSTEM_DISCLAIMER))
        self.assertEqual(
            news_prompt.compose_variable(""), "[No Variables Defined]"
        )


if __name__ == "__main__":
    unittest.main()
