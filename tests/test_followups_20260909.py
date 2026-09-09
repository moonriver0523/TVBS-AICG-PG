"""2026-09-09 使用者回饋批次的守門測試（見 docs/plan-20260909-user-feedback.md）。

三件事，三個類別：
1. AI 生成字的底色框要跟合成版對齊（只在第二行字後面、半透明）。
2. 「字多」要真的比較多——三檔裡以前只有它沒有 override 區塊。
3. 播出鏡面：蓋章改成跨全寬躺在挖空框底下那條空白帶。
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
import safe_area_spec  # noqa: E402


class AiBandClauseTests(unittest.TestCase):
    """底色框：AI 版的 prompt 要描述成「只在下面那一行字後面」，不再是 lower 40%。"""

    CLAUSES = (
        editor_formats.YT_COVER_BAND_CLAUSE_NEWS_ON,
        editor_formats.YT_COVER_BAND_CLAUSE_HOT_ON,
    )

    def test_band_is_described_relative_to_the_lower_headline_line(self):
        for clause in self.CLAUSES:
            with self.subTest(clause=clause[:40]):
                self.assertIn("BEHIND THE LOWER HEADLINE LINE ONLY", clause)
                self.assertIn("BASELINE of the upper headline line", clause)

    def test_the_old_lower_40_percent_wording_is_gone(self):
        """0.778 的合成版框只佔畫面下方兩成多；40% 是這次回報的根因。"""
        for clause in self.CLAUSES:
            with self.subTest(clause=clause[:40]):
                self.assertNotIn("lower 40% of the frame is", clause)
                self.assertIn("never the bottom half", clause)

    def test_translucency_is_still_spelled_out(self):
        for clause in self.CLAUSES:
            with self.subTest(clause=clause[:40]):
                self.assertIn("translucent", clause)
                self.assertIn("about 60% opaque", clause)

    def test_the_percentage_matches_the_composite_band(self):
        """prompt 寫「下方五分之一」，合成版是 1 - 0.778 = 0.222——同一個量級。"""
        self.assertLess(1 - compose.YT_BAND_TOP_RATIO, 0.25)
        for clause in self.CLAUSES:
            self.assertIn("bottom fifth of the frame", clause)

    def test_off_clause_untouched(self):
        self.assertIn("NO solid colour band", editor_formats.YT_COVER_BAND_CLAUSE_OFF)


class StandardDensityTests(unittest.TestCase):
    """字多：以前完全沒有 override 區塊，選了跟沒選一樣。"""

    def _instructions(self, role: str, density: str, **kw) -> str:
        return main.build_digest_instructions(
            role=role, density=density, type_label="資料圖表", **kw
        )

    def test_standard_now_injects_a_block_for_both_roles(self):
        for role in ("編輯", "記者"):
            with self.subTest(role=role):
                self.assertIn("字多 MODE", self._instructions(role, "standard"))

    def test_other_densities_do_not_get_it(self):
        for role in ("編輯", "記者"):
            for density in ("simplified", "verbatim"):
                with self.subTest(role=role, density=density):
                    self.assertNotIn("字多 MODE", self._instructions(role, density))

    def test_editor_block_names_the_limits_it_lifts(self):
        text = self._instructions("編輯", "standard")
        # 編輯版樣板真的寫著這兩句，指名蓋掉才壓得住
        self.assertIn("總字數嚴禁超過 150-180 個字", text)
        self.assertIn("每行不超過 15 字", text)
        self.assertIn("「每行不超過 15 字」 limit above is LIFTED", text)
        self.assertIn("150-180 個字」 target above is LIFTED", text)

    def test_reporter_block_does_not_name_limits_that_do_not_exist(self):
        """記者版樣板沒有那兩個上限，指名一個不存在的句子只會讓模型去找它。"""
        text = self._instructions("記者", "standard")
        self.assertIn("There is no per-line character cap at this setting.", text)
        self.assertIn("There is no total-length cap at this setting.", text)
        self.assertNotIn("「每行不超過 15 字」 limit above is LIFTED", text)

    def test_block_loosens_count_length_and_density(self):
        text = self._instructions("編輯", "standard")
        self.assertIn("up to six [內文小標] lines", text)
        self.assertIn("about twenty-four characters", text)
        self.assertIn("two hundred and forty to three hundred and twenty", text)

    def test_block_still_forbids_padding_and_invention(self):
        """放寬長度不等於可以掰——這條紅了就是把守門條款刪掉了。"""
        text = self._instructions("編輯", "standard")
        self.assertIn("THIS LICENSES NOTHING NEW", text)
        self.assertIn("Do not invent a figure", text)

    def test_layout_specific_counts_still_win(self):
        """播出鏡面的卡數是版面實體限制，不得被「最多六點」蓋掉。"""
        text = self._instructions(
            "編輯", "standard", stamp=True, editor_format="broadcast_left"
        )
        self.assertIn("A LATER BLOCK MAY FIX AN EXACT COUNT", text)
        self.assertIn("exactly four [內文小標] lines", text)
        self.assertLess(
            text.index("up to six [內文小標] lines"),
            text.index("exactly four [內文小標] lines"),
            "版型區塊必須排在字多區塊之後，位置與明文 OVERRIDE 要同向",
        )


class BroadcastBottomStripTests(unittest.TestCase):
    """播出鏡面：挖空框底下那條空白帶要拿來放蓋章。"""

    KEYS = ("broadcast_left", "broadcast_right")

    def test_there_really_is_a_free_strip_under_the_hole(self):
        """先確認幾何：框垂直置中，底下留的那條帶夠放一行字。"""
        for side in ("left", "right"):
            with self.subTest(side=side):
                _, y0, _, y1 = safe_area_spec.safe_rect(
                    *safe_area_spec.BASE_CANVAS, safe_area_spec.EDITOR_FRAME_PROFILE
                )
                rect = compose.broadcast_hole_rect(
                    safe_area_spec.BASE_CANVAS, side, safe_area_spec.EDITOR_FRAME_PROFILE
                )
                self.assertGreater(y1 - rect[3], 100, "框底到安全區底的空白帶不見了")
                # 垂直置中：上下兩條帶一樣高（差一個 round 的像素以內）
                self.assertLessEqual(abs((rect[1] - y0) - (y1 - rect[3])), 1)

    def test_stamp_on_puts_the_banner_full_width_below_the_hole(self):
        for key in self.KEYS:
            with self.subTest(key=key):
                rules = editor_formats.digest_rules(key, "編輯", stamp=True)
                self.assertIn("RUNS THE FULL WIDTH ALONG THE VERY BOTTOM", rules)
                self.assertIn("BELOW the reserved area", rules)
                self.assertNotIn("THE CLOSING <蓋章> BANNER IS NOT FULL WIDTH", rules)

    def test_stamp_on_leaves_the_watermark_corner_clear(self):
        """apply_broadcast_hole 事後會在安全區右下角蓋「示意圖」，會壓到跨全寬的條。"""
        self.assertEqual(compose.WATERMARK_TEXT, "示意圖")
        for key, opposite in (("broadcast_left", "right"), ("broadcast_right", "left")):
            with self.subTest(key=key):
                rules = editor_formats.digest_rules(key, "編輯", stamp=True)
                self.assertIn(f"extreme lower-{opposite} corner", rules)

    def test_rule_three_no_longer_contradicts_rule_five(self):
        for key in self.KEYS:
            with self.subTest(key=key):
                on = editor_formats.digest_rules(key, "編輯", stamp=True)
                self.assertIn("the one other full-width element", on)
                off = editor_formats.digest_rules(key, "編輯", stamp=False)
                self.assertNotIn("the one other full-width element", off)

    def test_stamp_off_still_keeps_everything_in_the_content_half(self):
        """OFF 沒有橫幅可以放，那條帶仍然空著（已知缺口，記在 plan 文件）。"""
        for key in self.KEYS:
            with self.subTest(key=key):
                rules = editor_formats.digest_rules(key, "編輯", stamp=False)
                self.assertIn("THERE IS NO STAMP BANNER IN THIS GRAPHIC", rules)
                self.assertNotIn("RUNS THE FULL WIDTH ALONG THE VERY BOTTOM", rules)

    def test_still_no_digits_anywhere(self):
        import re

        for key in self.KEYS:
            for stamp in (None, True, False):
                for density in ("standard", "simplified", None):
                    with self.subTest(key=key, stamp=stamp, density=density):
                        body = editor_formats.digest_rules(
                            key, "編輯", stamp=stamp, density=density
                        )
                        self.assertNotRegex(re.sub(r"(?m)^\d+\.", "", body), r"\d")


if __name__ == "__main__":
    unittest.main()
