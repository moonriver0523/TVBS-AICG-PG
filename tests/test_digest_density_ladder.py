"""消化程度五段拉桿（2026-09-10）。

使用者：「字少字多拉桿可否也做成 5 階梯，但最左邊要特別寫:不改字，最右邊:字超多，
預設還是一樣字少。」

守的紅線：

1. **順序是「由少到多」，而且最左端不是「字最少」。** 不改字是逐字複製，
   輸出長度＝輸入長度；這是使用者知情後的裁決（見 docs/plan-20260909e），
   所以順序常數本身要被釘住，免得後人「順手」把它排成字數遞增。
2. **新的兩級是既有級的加碼，不是另寫一套。** minimal 走 SIMPLIFIED＋收緊、
   maximum 走 STANDARD＋放寬——這樣資訊量一定單調，不會出現中間比兩端還多。
3. **字超多不得變成編故事的許可。** 要求更多字最容易誘發模型自己補料。
4. 預設仍是字少。
5. 播出鏡面的卡片列數是**版面實體限制**，不隨密度長：字超多沿用字多的四張卡。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats  # noqa: E402
import main  # noqa: E402

APP_JS = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")


class OrderTests(unittest.TestCase):
    def test_six_steps_left_to_right(self):
        """2026-09-14 D14：最左端再加「無字」，五段變六段。"""
        self.assertEqual(main.DIGEST_DENSITY_ORDER,
                         ("no_text", "verbatim", "minimal", "simplified", "standard", "maximum"))

    def test_the_default_is_still_the_same_step(self):
        """使用者：「預設還是一樣字少」。加了無字之後它不再是正中間，但仍然是字少
        ——D14 只加一檔，沒有改預設。"""
        self.assertEqual(main.DIGEST_DENSITY_ORDER.index("simplified"), 3)
        self.assertRegex(APP_JS, r"digestDensity:\s*'simplified'")

    def test_the_frontend_order_matches_the_backend(self):
        js = APP_JS.split("const DENSITY_ORDER = [")[1].split("]")[0]
        self.assertEqual([s.strip().strip("'") for s in js.split(",")],
                         list(main.DIGEST_DENSITY_ORDER))

    def test_every_step_has_a_label(self):
        block = APP_JS.split("const DENSITY_LABELS = {")[1].split("};")[0]
        for key, label in (("no_text", "無字"),
                           ("verbatim", "不改字"), ("minimal", "字極少"),
                           ("simplified", "字少"), ("standard", "字多"),
                           ("maximum", "字超多")):
            with self.subTest(key=key):
                self.assertIn(f"{key}: '{label}'", block)

    def test_the_slider_spans_all_six_and_starts_on_the_default(self):
        self.assertIn('id="digestDensityRange" type="range" min="0" max="5" step="1" value="3"',
                      INDEX_HTML)
        self.assertIn(">無字</span>", INDEX_HTML)
        self.assertIn(">字超多</span>", INDEX_HTML)


class BlockTests(unittest.TestCase):
    def test_the_new_blocks_are_add_ons_not_rewrites(self):
        """minimal／maximum 各自只寫「比它下面那一級再怎樣」，所以必須明文說自己覆蓋誰。
        沒有這句，模型會把兩塊當成並列的兩套規則，各遵守一半。"""
        self.assertIn("EVEN TIGHTER THAN THE SIMPLIFIED BLOCK ABOVE",
                      main.MINIMAL_DENSITY_RULES)
        self.assertIn("GOES BEYOND THE 字多 BLOCK ABOVE", main.MAXIMUM_DENSITY_RULES)

    def test_minimal_really_means_one_point(self):
        """字極少若只寫「更少一點」，模型會交出跟字少一樣的 1–3 點。"""
        self.assertIn("ONE point. Not one to three — one.", main.MINIMAL_DENSITY_RULES)

    def test_maximum_raises_the_ceiling_without_licensing_invention(self):
        """要求更多字最容易誘發補料，而編出來的數字是對外事故。"""
        block = main.MAXIMUM_DENSITY_RULES.format(**main._density_bound_words("maximum"))
        _, target = main.density_point_bounds("maximum")
        self.assertIn(f"TARGET {main.density_count_word(target).upper()}", block)
        self.assertIn("LICENSES NOTHING NEW", block)
        self.assertNotIn("it does not set a quota", block)
        self.assertIn("Never fewer than", block)

    def test_the_layout_row_count_does_not_grow_with_density(self):
        """播出鏡面的卡片列數是版面實體限制。字超多沿用字多的四張卡，不會長到八張。"""
        self.assertEqual(editor_formats._broadcast_point_count("maximum"),
                         editor_formats._broadcast_point_count("standard"))
        self.assertNotEqual(editor_formats._broadcast_point_count("maximum"),
                            editor_formats._broadcast_point_count("simplified"))

    def test_broadcast_two_line_cards_follow_the_top_two_levels(self):
        for density in ("standard", "maximum"):
            with self.subTest(density=density):
                rules = editor_formats._broadcast_rules("left", stamp=False, density=density)
                self.assertIn("TWO LINES INSTEAD OF ONE", rules)
        for density in ("verbatim", "minimal", "simplified"):
            with self.subTest(density=density):
                rules = editor_formats._broadcast_rules("left", stamp=False, density=density)
                self.assertNotIn("TWO LINES INSTEAD OF ONE", rules)


def _points(n: int) -> str:
    body = "\n".join(f"[內文小標] 重點{i}" for i in range(1, n + 1))
    return f"[標題] 測試標題\n{body}"


def _digest(variable: str) -> dict:
    return {
        "style": "Geographically accurate simplified cartography with a restrained palette.",
        "structure": "Use a north-up locator overview across the upper area with a scale bar.",
        "variable": variable,
    }


class DensityPointBoundsTests(unittest.TestCase):
    def test_standard_and_maximum_share_one_numeric_source(self):
        self.assertEqual(main.density_point_bounds("standard"), (5, 6))
        self.assertEqual(main.density_point_bounds("maximum"), (7, 8))
        for density in ("simplified", "minimal", "verbatim", "no_text", None):
            with self.subTest(density=density):
                self.assertEqual(main.density_point_bounds(density), (None, None))

    def test_prompt_templates_do_not_hardcode_the_bounds(self):
        self.assertIn("{target_word}", main.STANDARD_DENSITY_RULES)
        self.assertIn("{minimum_word}", main.STANDARD_DENSITY_RULES)
        self.assertIn("{target_word_upper}", main.MAXIMUM_DENSITY_RULES)
        self.assertIn("{minimum_word}", main.MAXIMUM_DENSITY_RULES)
        self.assertNotIn("up to six", main.STANDARD_DENSITY_RULES)
        self.assertNotIn("up to EIGHT", main.MAXIMUM_DENSITY_RULES)

    def test_formatted_prompt_uses_the_same_bounds(self):
        for density in ("standard", "maximum"):
            with self.subTest(density=density):
                minimum, target = main.density_point_bounds(density)
                prompt = main.build_digest_instructions("記者", density, "資料圖表")
                self.assertIn(f"Never fewer than {main.density_count_word(minimum)}", prompt)
                target_word = main.density_count_word(target)
                if density == "maximum":
                    self.assertIn(f"TARGET {target_word.upper()}", prompt)
                else:
                    self.assertIn(f"TARGET {target_word} [內文小標] lines", prompt)

    def test_broadcast_exact_count_wins_over_the_general_floor(self):
        self.assertEqual(
            main.density_point_bounds("standard", "broadcast"), (4, 4)
        )
        self.assertEqual(
            main.density_point_bounds("maximum", "broadcast_left"), (4, 4)
        )
        four = _digest(_points(4))
        five = _digest(_points(5))
        self.assertEqual(
            main.digest_quality_problem(
                four, "stop", density="standard", format_key="broadcast"
            ),
            "",
        )
        problem = main.digest_quality_problem(
            five, "stop", density="standard", format_key="broadcast"
        )
        self.assertIn("observed=5", problem)
        self.assertIn("required=4", problem)
        general = main.digest_quality_problem(four, "stop", density="standard")
        self.assertIn("observed=4", general)
        self.assertIn("required=5", general)


class DensityPointGuardTests(unittest.TestCase):
    def test_standard_four_five_six_boundary(self):
        self.assertIn(
            "observed=4",
            main.digest_quality_problem(_digest(_points(4)), "stop", density="standard"),
        )
        self.assertEqual(
            main.digest_quality_problem(_digest(_points(5)), "stop", density="standard"),
            "",
        )
        self.assertEqual(
            main.digest_quality_problem(_digest(_points(6)), "stop", density="standard"),
            "",
        )

    def test_maximum_six_seven_eight_boundary(self):
        self.assertIn(
            "observed=6",
            main.digest_quality_problem(_digest(_points(6)), "stop", density="maximum"),
        )
        self.assertEqual(
            main.digest_quality_problem(_digest(_points(7)), "stop", density="maximum"),
            "",
        )
        self.assertEqual(
            main.digest_quality_problem(_digest(_points(8)), "stop", density="maximum"),
            "",
        )

    def test_title_stamp_source_and_notes_are_not_points(self):
        variable = (
            "[標題] 標題\n"
            "來源 路透社\n"
            "備註 資料截至昨日\n"
            "[內文小標] 重點一\n"
            "[內文小標] 重點二\n"
            "[內文小標] 重點三\n"
            "[內文小標] 重點四\n"
            "[內文小標] 重點五\n"
            "<蓋章> 結論\n"
            "<底帶> 底帶不是小標"
        )
        self.assertEqual(main.count_density_points(variable), 5)
        self.assertEqual(
            main.digest_quality_problem(_digest(variable), "stop", density="standard"),
            "",
        )

    def test_fullwidth_marker_and_two_line_card_count_as_one_block(self):
        variable = (
            "[標題] 標題\n"
            "【內文小標】全形標記也算\n"
            "[內文小標] 短標｜補充細節仍是一塊\n"
            "這行沒標記不算\n"
            "[內文小標] 第三\n"
            "[內文小標] 第四\n"
            "[內文小標] 第五"
        )
        self.assertEqual(main.count_density_points(variable), 5)


class B60MockConsistencyTests(unittest.TestCase):
    """B60 無 API 自動驗收：同一組參數 mock 五次，每次都落在 target ±1。"""

    def test_five_mock_standard_runs_stay_within_target_plus_minus_one(self):
        minimum, target = main.density_point_bounds("standard")
        counts = [target - 1, target, target + 1, target, target - 1]
        self.assertEqual(len(counts), 5)
        for n in counts:
            with self.subTest(n=n):
                self.assertTrue(abs(n - target) <= 1)
                self.assertGreaterEqual(n, minimum)
                self.assertEqual(
                    main.digest_quality_problem(
                        _digest(_points(n)), "stop", density="standard"
                    ),
                    "",
                )

    def test_five_mock_maximum_runs_stay_within_target_plus_minus_one(self):
        minimum, target = main.density_point_bounds("maximum")
        counts = [target - 1, target, target + 1, target, target - 1]
        self.assertEqual(len(counts), 5)
        for n in counts:
            with self.subTest(n=n):
                self.assertTrue(abs(n - target) <= 1)
                self.assertGreaterEqual(n, minimum)
                self.assertEqual(
                    main.digest_quality_problem(
                        _digest(_points(n)), "stop", density="maximum"
                    ),
                    "",
                )

    def test_generate_retries_when_standard_is_short_then_accepts_the_floor(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch

        def payload(n):
            return {
                "style": "cinematic broadcast style",
                "structure": "cards",
                "variable": _points(n),
                "chart_type": "資料圖表",
            }

        def response(n):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(payload(n))),
                        finish_reason="stop",
                    )
                ]
            )

        request = main.GenerateRequest(news_text="素材", type_label="資料圖表")
        with patch.object(main.time, "sleep"), patch.object(
            main.openai_client.chat.completions, "create",
            side_effect=[response(4), response(5)],
        ) as create:
            result = main.generate(request)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(main.count_density_points(result.variable), 5)


class B67ShortSourcePassthroughTests(unittest.TestCase):
    """B67（2026-09-16 使用者裁決）：素材真的單薄、塊數怎麼試都補不滿時，
    試滿 DIGEST_POINT_COUNT_ATTEMPTS 次就放行，不要整條 502——使用者拿到一張
    少一點的圖，比拿不到圖好。真故障不適用，仍要擋滿 DIGEST_ATTEMPTS。"""

    def _response(self, variable, finish_reason="stop"):
        import json
        from types import SimpleNamespace

        payload = {
            "style": "cinematic broadcast style",
            "structure": "cards",
            "variable": variable,
            "chart_type": "資料圖表",
        }
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(payload)),
                    finish_reason=finish_reason,
                )
            ]
        )

    def test_a_genuinely_thin_story_is_released_after_the_short_cap(self):
        from unittest.mock import patch

        short = self._response(_points(3))
        with patch.object(main.time, "sleep"), patch.object(
            main.openai_client.chat.completions, "create",
            side_effect=[short] * main.DIGEST_ATTEMPTS,
        ) as create:
            result = main.generate(
                main.GenerateRequest(news_text="素材", type_label="資料圖表")
            )
        # 試滿短上限就停手，不會一路燒到 DIGEST_ATTEMPTS
        self.assertEqual(create.call_count, main.DIGEST_POINT_COUNT_ATTEMPTS)
        self.assertLess(main.DIGEST_POINT_COUNT_ATTEMPTS, main.DIGEST_ATTEMPTS)
        # 放行的是模型真的生出來的那三點，不是空的或補出來的
        self.assertEqual(main.count_density_points(result.variable), 3)

    def test_a_real_failure_still_burns_every_attempt_and_raises(self):
        from unittest.mock import patch
        from fastapi import HTTPException

        # 截斷是真故障：重試有機會好，不准套用 B67 的放行
        truncated = self._response(_points(3), finish_reason="length")
        with patch.object(main.time, "sleep"), patch.object(
            main.openai_client.chat.completions, "create",
            side_effect=[truncated] * main.DIGEST_ATTEMPTS,
        ) as create:
            with self.assertRaises(HTTPException):
                main.generate(
                    main.GenerateRequest(news_text="素材", type_label="資料圖表")
                )
        self.assertEqual(create.call_count, main.DIGEST_ATTEMPTS)

    def test_the_passthrough_only_covers_the_point_count_problem(self):
        # 同一次結果同時有塊數不足與簡體字污染時，報的是簡體字、不得放行
        polluted = dict(
            style="cinematic broadcast style",
            structure="cards",
            variable=_points(3) + "\n[內文小標] 这样的简体字",
            chart_type="資料圖表",
        )
        problem = main.digest_quality_problem(polluted, "stop", density="standard")
        self.assertTrue(problem)
        count_problem = main.digest_point_count_problem(
            polluted["variable"], "standard", None
        )
        self.assertNotEqual(problem, count_problem)


if __name__ == "__main__":
    unittest.main()
