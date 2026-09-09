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
    def test_five_steps_left_to_right(self):
        self.assertEqual(main.DIGEST_DENSITY_ORDER,
                         ("verbatim", "minimal", "simplified", "standard", "maximum"))

    def test_the_default_is_still_the_middle_one(self):
        """使用者：「預設還是一樣字少」。五段裡字少剛好是正中間。"""
        self.assertEqual(main.DIGEST_DENSITY_ORDER.index("simplified"), 2)
        self.assertRegex(APP_JS, r"digestDensity:\s*'simplified'")

    def test_the_frontend_order_matches_the_backend(self):
        js = APP_JS.split("const DENSITY_ORDER = [")[1].split("]")[0]
        self.assertEqual([s.strip().strip("'") for s in js.split(",")],
                         list(main.DIGEST_DENSITY_ORDER))

    def test_every_step_has_a_label(self):
        block = APP_JS.split("const DENSITY_LABELS = {")[1].split("};")[0]
        for key, label in (("verbatim", "不改字"), ("minimal", "字極少"),
                           ("simplified", "字少"), ("standard", "字多"),
                           ("maximum", "字超多")):
            with self.subTest(key=key):
                self.assertIn(f"{key}: '{label}'", block)

    def test_the_slider_spans_all_five_and_starts_in_the_middle(self):
        self.assertIn('id="digestDensityRange" type="range" min="0" max="4" step="1" value="2"',
                      INDEX_HTML)
        self.assertIn(">不改字</span>", INDEX_HTML)
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
        self.assertIn("up to EIGHT", main.MAXIMUM_DENSITY_RULES)
        self.assertIn("LICENSES NOTHING NEW", main.MAXIMUM_DENSITY_RULES)
        self.assertIn("it does not set a quota", main.MAXIMUM_DENSITY_RULES)

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


if __name__ == "__main__":
    unittest.main()
