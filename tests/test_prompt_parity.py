"""後端與 app.js 之間「兩份來源必須同步」的守門測試。

涵蓋兩組：
1. Prompt 規則：news_prompt.py ↔ app.js（同一套規則的兩個實作，
   網頁版在前端組、LINE Bot 在後端組）。
2. 置框長寬比：main.py ↔ app.js（**不同的呼叫路徑**——main.py 那組是
   LINE Bot 與 WorkCord 端點在用，app.js 那組是網頁版第一頁在用）。

兩組的共同問題是：只改一邊不會有任何執行期錯誤，只會讓兩條路徑悄悄出不一樣的圖。
所以用測試把「不同步」變成看得見的失敗。
"""

import io
import os
import pathlib
import re
import unittest

import news_prompt

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402

APP_JS = pathlib.Path(__file__).resolve().parent.parent / "app.js"


def js_source() -> str:
    return io.open(APP_JS, encoding="utf-8").read()


def js_template_literal(name: str, source: str) -> str | None:
    """取出 app.js 裡 const NAME = `...`; 的內容。"""
    match = re.search(r"const " + name + r"\s*=\s*\n?`(.*?)`;", source, re.S)
    return match.group(1) if match else None


def js_quoted_const(name: str, source: str) -> str | None:
    """取出 app.js 裡 const NAME = '...'; 或 "..."; 的內容（單/雙引號皆可）。"""
    match = re.search(
        r"const " + name + r"\s*=\s*(['\"])(.*?)\1\s*;", source
    )
    return match.group(2) if match else None


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

    def test_editor_full_bleed_rules(self):
        self.assert_same(
            "EDITOR_FULL_BLEED_RULES", news_prompt.EDITOR_FULL_BLEED_RULES
        )

    def _prompt(self, role: str, safe_frame: bool) -> str:
        return news_prompt.build_prompt(
            role=role, engine="gpt", type_label="資料圖表",
            style="S", structure="T", variable="V", safe_frame=safe_frame,
        )

    def test_editor_replaces_the_full_bleed_block_rather_than_appending(self):
        """編輯的拉伸路徑要換掉整段滿版規則，不能兩段並存。

        兩段並存實測只留 0-8px 背景帶：FULL_BLEED_RULES 開頭就寫「不准留白」
        並聲明 OVERRIDE 衝突指令，模型會聽它而不是後面的留邊要求。

        2026-08-19 起「哪一檔是拉伸」對調了——編輯的拉伸路徑改掛在 safe_frame=False
        （見 main.resolve_frame_plan）。規則本身沒變，斷言跟著換到對的那一檔，
        並補上「四種組合都不得並存」的檢查。
        """
        editor_stretch = self._prompt("編輯", False)  # 拉伸填滿對位框
        self.assertIn(news_prompt.EDITOR_FULL_BLEED_RULES, editor_stretch)
        self.assertNotIn(news_prompt.FULL_BLEED_RULES, editor_stretch)

        # 2% 薄框走 FIT 不拉伸，用與記者相同的滿版規則（不留背景帶）
        editor_thin = self._prompt("編輯", True)
        self.assertIn(news_prompt.FULL_BLEED_RULES, editor_thin)
        self.assertNotIn(news_prompt.EDITOR_FULL_BLEED_RULES, editor_thin)

        reporter = self._prompt("記者", True)
        self.assertIn(news_prompt.FULL_BLEED_RULES, reporter)
        self.assertNotIn(news_prompt.EDITOR_FULL_BLEED_RULES, reporter)

        for role in ("編輯", "記者"):
            for safe_frame in (True, False):
                with self.subTest(role=role, safe_frame=safe_frame):
                    prompt = self._prompt(role, safe_frame)
                    both = (
                        news_prompt.FULL_BLEED_RULES in prompt
                        and news_prompt.EDITOR_FULL_BLEED_RULES in prompt
                    )
                    self.assertFalse(both, "兩段滿版規則並存，模型會只聽前面那段")

    def test_editor_never_asks_the_model_to_shrink_and_centre(self):
        """編輯版兩檔都是滿版生成——縮小置中那條路 2026-08-19 已廢除。

        漏接的症狀很隱蔽：圖照樣出得來，只是模型自己留了厚邊、後端再壓一次框，
        變成雙重留白，不會有任何執行期錯誤。
        """
        for safe_frame in (True, False):
            with self.subTest(safe_frame=safe_frame):
                prompt = self._prompt("編輯", safe_frame)
                self.assertNotIn(news_prompt.EDITOR_SAFE_AREA, prompt)
                self.assertNotIn(news_prompt.REPORTER_SAFE_AREA, prompt)
                self.assertIn(news_prompt.CANVAS_FULL_BLEED_LINE, prompt)

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

    def test_real_world_rendering_rules(self):
        self.assert_same("REAL_WORLD_RENDERING_RULES", news_prompt.REAL_WORLD_RENDERING_RULES)

    def test_directional_colour_rules(self):
        self.assert_same("TW_DIRECTIONAL_COLOR_RULES", news_prompt.TW_DIRECTIONAL_COLOR_RULES)

    def test_map_accuracy_image_rules(self):
        self.assert_same("MAP_ACCURACY_IMAGE_RULES", news_prompt.MAP_ACCURACY_IMAGE_RULES)

    def test_map_type_label_matches(self):
        js_value = js_quoted_const("MAP_TYPE_LABEL", self.source)
        self.assertIsNotNone(js_value, "app.js 裡找不到 MAP_TYPE_LABEL")
        self.assertEqual(js_value, news_prompt.MAP_TYPE_LABEL)


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
            "REAL-WORLD ACCURACY (CRITICAL)",
            "DIRECTIONAL COLOUR CONVENTION (TAIWAN)",
            "FINAL OUTPUT RULE",
        ]
        positions = [prompt.index(m) for m in markers]
        self.assertEqual(positions, sorted(positions), "區塊順序與 app.js 不同")

    def test_map_block_lands_between_colour_and_final_rule(self):
        prompt = news_prompt.build_prompt(
            role="記者",
            engine="gemini",
            type_label=news_prompt.MAP_TYPE_LABEL,
            style="S",
            structure="T",
            variable="V",
        )
        self.assertLess(
            prompt.index("DIRECTIONAL COLOUR CONVENTION (TAIWAN)"),
            prompt.index("MAP ACCURACY RULES (CRITICAL)"),
        )
        self.assertLess(
            prompt.index("MAP ACCURACY RULES (CRITICAL)"),
            prompt.index("FINAL OUTPUT RULE"),
        )

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


class AspectRatioParityTests(unittest.TestCase):
    """置框長寬比：main.py 與 app.js 是兩條不同呼叫路徑，值必須一致。

    背景：2026-07-30 把 safe_frame 的預設長寬比切成 21:9 時只改了 main.py
    （LINE Bot／WorkCord 用的那條），網頁版第一頁走 app.js 自組 prompt 直打
    /api/images/generate 的另一條路徑、aspect_ratio 仍寫死 16:9——安全框開了
    但左右還是多出一倍留白，隔天才發現。這組測試就是把那次的漏改變成看得見的失敗。
    """

    def setUp(self):
        self.source = js_source()

    def test_safe_frame_aspect_ratio_matches(self):
        js_value = js_quoted_const("SAFE_FRAME_ASPECT_RATIO", self.source)
        self.assertIsNotNone(js_value, "app.js 裡找不到 SAFE_FRAME_ASPECT_RATIO")
        self.assertEqual(
            js_value,
            main.SAFE_FRAME_ASPECT_RATIO,
            "置框長寬比兩邊不一致：LINE／WorkCord 與網頁版會出不一樣比例的圖",
        )

    def test_default_aspect_ratio_matches(self):
        js_value = js_quoted_const("DEFAULT_ASPECT_RATIO", self.source)
        self.assertIsNotNone(js_value, "app.js 裡找不到 DEFAULT_ASPECT_RATIO")
        self.assertEqual(
            js_value,
            main.DEFAULT_ASPECT_RATIO,
            "未置框長寬比兩邊不一致",
        )

    def test_values_are_the_validated_ones(self):
        """釘住實測驗證過的值：21:9 是用 4 張真實生成圖驗過左右留白 4/4 落在
        官方需求 ±1pp 內才選定的。要改成別的比例得有人重跑驗證、明確決定，
        不能兩邊一起改就悄悄過關。"""
        self.assertEqual(main.SAFE_FRAME_ASPECT_RATIO, "21:9")
        self.assertEqual(main.DEFAULT_ASPECT_RATIO, "16:9")

    def test_backend_resolver_uses_the_constants(self):
        """resolve_aspect_ratio 必須真的回傳這兩個常數，不能另外寫死字面值。"""
        self.assertEqual(
            main.resolve_aspect_ratio(None, safe_frame=True),
            main.SAFE_FRAME_ASPECT_RATIO,
        )
        self.assertEqual(
            main.resolve_aspect_ratio(None, safe_frame=False),
            main.DEFAULT_ASPECT_RATIO,
        )
        self.assertEqual(
            main.resolve_aspect_ratio("4:3", safe_frame=True),
            "4:3",
            "呼叫端明確指定時必須尊重覆寫",
        )

    def test_frontend_sends_the_resolved_ratio_not_a_hardcoded_one(self):
        """網頁版送出的 payload 必須用 currentAspectRatio()，不能又退回寫死。

        這正是當初漏改的形態：常數定義好了、函式也寫了，但 fetch 裡仍是
        aspect_ratio: '16:9'，於是整組機制形同虛設。
        """
        self.assertIn("aspect_ratio: currentAspectRatio()", self.source)
        self.assertNotIn("aspect_ratio: '16:9'", self.source)

    def test_frontend_resolver_branches_on_safe_frame(self):
        """currentAspectRatio() 必須依 safeFrame 切換，且用的是那兩個常數。"""
        match = re.search(
            r"function currentAspectRatio\(\)\s*\{(.*?)\}", self.source, re.S
        )
        self.assertIsNotNone(match, "app.js 裡找不到 currentAspectRatio()")
        body = match.group(1)
        self.assertIn("state.safeFrame", body)
        self.assertIn("SAFE_FRAME_ASPECT_RATIO", body)
        self.assertIn("DEFAULT_ASPECT_RATIO", body)


if __name__ == "__main__":
    unittest.main()
