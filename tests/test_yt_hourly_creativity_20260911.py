"""YT 整點的創意階梯（2026-09-11 使用者：「整個生圖都套用創意階梯 1~4，
包括標題構圖全都在創意設計範圍，跟十點不一樣對齊」）。

機制照搬十點（同一批變化池、同一顆 rng、同樣的抽籤順序），**數字自己量**——
十點的 18/24/30/36% 是量十點成品訂的。實測（已排除日期牌）：程式壓字版的兩行
標題佔畫面高 29.2%，模型自己畫 32.7–36.2% 且四級之間沒有單調趨勢，證實在此之前
拉桿對標題構圖完全沒有作用。使用者裁決塊高 26/31/36/41%、字級落差照搬十點。
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats as ef  # noqa: E402

LINES = ("東北季風剩1天", "假日回溫")
LEVELS = (1, 2, 3, 4)


def brief(level: int, seed="s") -> str:
    return ef.yt_hourly_design_brief(level, lines=LINES, seed=seed)


class BlockHeightLadderTests(unittest.TestCase):
    def test_the_ladder_is_monotonic(self):
        heights = [ef._yt_block_height(level) for level in LEVELS]
        self.assertEqual(heights, sorted(heights))
        self.assertEqual(len(set(heights)), 4, "有兩級塊高一樣＝那一段拉桿沒有作用")

    def test_the_ladder_is_anchored_to_the_measured_broadcast_block(self):
        """實測程式壓字版（已驗收的播出標準）是 29.2%。L1 要比它小（讓照片突出）、
        L4 要明顯比它大，否則這條拉桿只是在原地抖動。"""
        measured = 0.292
        self.assertLess(ef._yt_block_height(1), measured)
        self.assertGreater(ef._yt_block_height(4), measured * 1.3)

    def test_the_title_top_follows_the_block_height(self):
        """塊高變，標題頂就得跟著變——兩者寫死成各自的數字就會互相矛盾。"""
        for level in LEVELS:
            with self.subTest(level=level):
                self.assertAlmostEqual(
                    ef.yt_hourly_title_top(level),
                    ef.YT_HOURLY_TITLE_BOTTOM_RATIO - ef._yt_block_height(level),
                    places=4,
                )

    def test_level_zero_is_untouched(self):
        self.assertEqual(ef.yt_hourly_title_top(0), 0.66)
        self.assertEqual(brief(0), "")
        self.assertEqual(ef.yt_hourly_fixed_block(0), "")


class RngContractTests(unittest.TestCase):
    """與十點同一份契約：一顆 seed ＝ 一種長相，而且 RNG 只換風格不換響度。"""

    def test_the_same_seed_gives_the_same_look(self):
        for level in LEVELS:
            with self.subTest(level=level):
                self.assertEqual(brief(level, "seed-a"), brief(level, "seed-a"))

    def test_different_seeds_give_different_looks(self):
        looks = {brief(3, f"seed-{i}") for i in range(12)}
        self.assertGreater(len(looks), 1, "換 seed 長相沒變＝變化池沒有接上")

    def test_the_rng_changes_style_never_loudness(self):
        """塊高、字級落差、反白字數是梯子本身，不准跟著 seed 變。"""
        for level in LEVELS:
            spec = ef.YT_HOURLY_BRIEF_SPECS[level]
            for seed in ("a", "b", "c", "d"):
                text = brief(level, seed)
                with self.subTest(level=level, seed=seed):
                    self.assertIn(spec["height"], text)
                    if spec["ratio"]:
                        self.assertIn(spec["ratio"], text)
                    if spec["knockouts"]:
                        self.assertIn("KNOCKED OUT", text)
                    else:
                        self.assertNotIn("KNOCKED OUT", text)


class BriefContentTests(unittest.TestCase):
    def test_the_brief_sits_right_after_the_canvas_block(self):
        """鐵律一：數字釘在 prompt 前段才存在，寫在條文區等於不存在。"""
        template = ef.YT_COVER_FULL_PROMPT_HOURLY
        self.assertLess(
            template.index("{design_brief}"), template.index("=== LAYOUT ==="),
        )

    def test_the_date_tab_never_joins_the_palette(self):
        """配色池會遞四個顏色過去，日期牌是頻道識別，不跟著抽——不然會出現藍色日期牌。"""
        for level in LEVELS:
            with self.subTest(level=level):
                self.assertIn("THE DATE TAB IS NOT PART OF THAT PALETTE", brief(level))

    def test_row_order_colouring_is_banned(self):
        for level in LEVELS:
            with self.subTest(level=level):
                self.assertIn("COLOUR FOLLOWS MEANING, NEVER ROW ORDER", brief(level))

    def test_the_tilt_carries_the_date_tab_with_it(self):
        """L4 整塊傾斜時日期牌必須跟著轉，否則牌會浮在斜掉的標題旁邊。"""
        self.assertIn("THE DATE TAB ROTATES WITH IT", brief(4))
        self.assertNotIn("rotated 5 to 8 degrees", brief(1))

    def test_accessories_stay_out_of_the_paste_on_areas(self):
        """2026-09-11 `73ae198` 的教訓：排除句埋在一長串否定句中間模型會照犯。"""
        text = brief(4)
        self.assertIn("NONE OF THEM MAY SIT IN EITHER TOP CORNER OR ON THE DATE TAB", text)


class StyleClauseTests(unittest.TestCase):
    """質感條文。2026-09-11 使用者驗收 L1：「只有紅標有設計，其他都跟 0 沒有兩樣。」

    根因：這段原本整段不存在。L1 的 spec 旗標全是關的，塊高 26% 跟 0 級的 29% 又
    看不太出來，所以少了質感條文就真的沒有差別。而且 0 級那句
    「Flat type: no gradient, no metallic, no 3-D」在 1 級起被拆掉，卻沒換上正面的
    命令——**拆禁令必須配下命令**，不然模型維持原樣。
    """

    def test_every_level_carries_a_finish_clause(self):
        for level in LEVELS:
            with self.subTest(level=level):
                self.assertIn("- FINISH (level", ef.yt_hourly_layout_rules(level))

    def test_level_one_is_visibly_different_from_level_zero(self):
        """L1 至少要有「字面材質」與「底板」兩件事，否則它就只是 0 級換個塊高。"""
        text = ef.yt_hourly_layout_rules(1)
        self.assertIn("SURFACE MATERIAL", text)
        self.assertIn("own plate", text)

    def test_the_flat_type_ban_is_gone_and_replaced_by_an_order(self):
        """0 級禁材質、1 級起要材質——拆掉禁令的同時必須下正面命令。"""
        self.assertIn("Flat type: no gradient", ef.yt_hourly_layout_rules(0))
        for level in LEVELS:
            with self.subTest(level=level):
                text = ef.yt_hourly_layout_rules(level)
                self.assertNotIn("Flat type: no gradient", text)
                self.assertIn("Required, not offered", text)

    def test_each_level_has_its_own_finish(self):
        looks = {ef._YT_HOURLY_STYLE_CLAUSES[level] for level in LEVELS}
        self.assertEqual(len(looks), 4, "有兩級質感條文一樣＝那一段拉桿沒有作用")

    def test_the_loudest_level_still_protects_legibility(self):
        self.assertIn("Loud is not the same as broken", ef._YT_HOURLY_STYLE_CLAUSES[4])


class FixedBlockTests(unittest.TestCase):
    """YT 在此之前**一條都沒有**——十點有 (a)–(g)、CG 有 (a)–(i)，只有 YT 裸奔。"""

    def test_the_fixed_block_exists_from_level_one(self):
        for level in LEVELS:
            with self.subTest(level=level):
                self.assertIn("WHAT THE CREATIVITY SETTING NEVER CHANGES", ef.yt_hourly_fixed_block(level))

    def test_it_covers_the_things_the_ladder_must_not_touch(self):
        text = ef.yt_hourly_fixed_block(4)
        for needle in (
            "THE CHARACTERS",            # 不准改字
            "THE DATE IS A FACT",        # 日期數字
            "NO NEW TEXT OF ANY KIND",   # 不准生字
            "COMPLETE, UNOBSTRUCTED AND LEGIBLE",
            "TWO RESERVED CORNERS STAY CLEAN",
            "Traditional Chinese",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


class GeometryParityTests(unittest.TestCase):
    """editor_formats 不 import compose（會循環），所以兩邊各持一份幾何常數。"""

    def test_the_date_tab_height_matches_compose(self):
        self.assertEqual(
            ef.YT_HOURLY_DATE_TAB_HEIGHT_RATIO, compose.YT_HOURLY_DATE_TAB_HEIGHT_RATIO
        )

    def test_the_left_margin_matches_compose(self):
        self.assertEqual(ef.COVER_YT_MARGIN_RATIO, compose.YT_MARGIN_RATIO)


if __name__ == "__main__":
    unittest.main()
