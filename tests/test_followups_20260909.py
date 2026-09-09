"""2026-09-09 使用者回饋批次的守門測試（見 docs/plan-20260909-user-feedback.md）。

五件事，五個類別：
1. AI 生成字的底色框要跟合成版對齊（只在第二行字後面、半透明）。
2. 「字多」要真的比較多——三檔裡以前只有它沒有 override 區塊。
3. 播出鏡面：蓋章改成跨全寬躺在挖空框底下那條空白帶。
4. 直標縮短：總長度有上限、色框置中偏上、欄寬由字級推導、同側下角開放放 Logo。
5. 畫面來源：「畫面來源：」自動補，位置四角可選且自動避開 Logo。
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


class VstripShorterTests(unittest.TestCase):
    """直標縮短（2026-09-09 使用者：太長、上下貼邊、字級與行距都要縮）。"""

    LONG_MAIN = "明早晚涼中午破30度"
    LONG_SUB = "北臺灣週三轉濕涼留意日夜溫差"

    def _layout(self, **kw):
        kw.setdefault("main_title", self.LONG_MAIN)
        kw.setdefault("sub_title", self.LONG_SUB)
        return compose.yt_vertical_layout(**kw)

    def test_the_column_can_never_run_the_whole_height(self):
        """最長的標題也不准從上緣長到下緣——那正是使用者說的「上下都貼邊」。"""
        height = compose.YT_CANVAS[1]
        for kw in ({}, {"variant": "original_audio"}, {"logo_corner": "bl"}):
            with self.subTest(**kw):
                layout = self._layout(title_side="left", **kw)
                self.assertLessEqual(
                    layout["column_height"] / height,
                    compose.VSTRIP_COLUMN_MAX_RATIO + 1e-9,
                )
                # 底緣離畫布底至少留一成
                self.assertLess(layout["box"][3] / height, 0.90)

    def test_the_block_floats_instead_of_hanging_from_the_top(self):
        """色框上緣不再釘死在 VSTRIP_TOP_RATIO：短標題會往下浮。"""
        height = compose.YT_CANVAS[1]
        short = compose.yt_vertical_layout(main_title="川普宣布關稅", sub_title="美股應聲下挫")
        self.assertGreater(short["box"][1] / height, compose.VSTRIP_TOP_RATIO)
        # 但永遠在 LIVE 章之下
        self.assertGreater(short["box"][1], short["live"][3])

    def test_column_width_follows_the_font_size(self):
        """行距＝欄寬。字級縮了欄寬要跟著縮，否則兩行之間的空白反而變大。"""
        long_title = self._layout(title_side="left")
        short = compose.yt_vertical_layout(main_title="川普宣布關稅", sub_title="美股應聲下挫")
        self.assertLess(long_title["cell_size"], short["cell_size"])
        wide = lambda layout: layout["main"][2] - layout["main"][0]  # noqa: E731
        self.assertLess(wide(long_title), wide(short))
        for layout in (long_title, short):
            self.assertEqual(
                wide(layout),
                max(1, round(layout["cell_size"] * compose.VSTRIP_COLUMN_WIDTH_EM)),
            )

    def test_font_is_smaller_than_the_old_fixed_column(self):
        """舊版欄寬固定 0.0445w≈85px、格距 0.080h；縮小後兩者都要變小。"""
        width, height = compose.YT_CANVAS
        layout = self._layout(title_side="left")
        self.assertLess(layout["main"][2] - layout["main"][0], round(width * 0.0445))
        self.assertLess(layout["pitch"], height * 0.080)

    def test_logo_bottom_corner_on_the_same_side_shortens_the_column(self):
        free = self._layout(title_side="left", logo_corner="tr")
        clashing = self._layout(title_side="left", logo_corner="bl")
        self.assertLess(clashing["box"][3], clashing["logo"][1])
        self.assertLessEqual(clashing["box"][3], free["box"][3])

    def test_logo_top_corner_on_the_same_side_is_still_refused(self):
        for side, corner in (("left", "tl"), ("right", "tr")):
            with self.subTest(side=side, corner=corner):
                with self.assertRaises(compose.ComposeError):
                    compose.compose_yt_overlay(
                        main_title=self.LONG_MAIN, sub_title=self.LONG_SUB,
                        title_side=side, logo_corner=corner,
                    )

    def test_the_longest_allowed_title_still_fits(self):
        """規格上限 12／14 格，配上最擠的選項組合也不能丟 ComposeError。"""
        main = "十二個格子滿滿滿的標題"
        sub = "十四個格子滿滿滿滿滿的標題喔"
        self.assertEqual(len(compose._vertical_cells(main)), 11)
        self.assertEqual(len(compose._vertical_cells(sub)), 14)
        compose.compose_yt_overlay(
            main_title=main, sub_title=sub, title_side="left",
            variant="original_audio", logo_corner="bl",
        )


class VstripSourceTests(unittest.TestCase):
    """畫面來源：自動補前綴＋四角可選（2026-09-09 使用者要求）。"""

    def test_prefix_is_added_to_a_bare_source_name(self):
        self.assertEqual(compose.vstrip_source_text("美聯社"), "畫面來源：美聯社")

    def test_prefix_is_not_doubled(self):
        for already in ("畫面來源：美聯社", "畫面來源 美聯社"):
            with self.subTest(already=already):
                self.assertEqual(compose.vstrip_source_text(already), already)

    def test_empty_stays_empty(self):
        for raw in ("", "   ", None):
            with self.subTest(raw=raw):
                self.assertEqual(compose.vstrip_source_text(raw), "")

    def test_is_idempotent(self):
        once = compose.vstrip_source_text("路透社")
        self.assertEqual(compose.vstrip_source_text(once), once)

    def test_every_corner_is_accepted_and_lands_there(self):
        width, height = compose.YT_CANVAS
        for corner in compose.VSTRIP_SOURCE_CORNERS:
            with self.subTest(corner=corner):
                layout = compose.yt_vertical_layout(
                    main_title="川普宣布關稅", sub_title="美股應聲下挫",
                    title_side="left", logo_corner="tr",
                    source_text="美聯社", source_corner=corner,
                )
                x0, y0, x1, y1 = layout["source"]
                self.assertEqual(layout["source_corner"], corner)
                if corner in ("tl", "bl"):
                    self.assertLess(x0, width / 2)
                else:
                    self.assertGreater(x1, width / 2)
                if corner in ("tl", "tr"):
                    self.assertLess(y0, height / 2)
                else:
                    self.assertGreater(y1, height / 2)

    def test_it_never_overlaps_the_logo_even_in_the_logo_corner(self):
        for corner in compose.VSTRIP_SOURCE_CORNERS:
            with self.subTest(corner=corner):
                layout = compose.yt_vertical_layout(
                    main_title="川普宣布關稅", sub_title="美股應聲下挫",
                    title_side="left", logo_corner=corner,
                    source_text="美聯社", source_corner=corner,
                )
                sx0, sy0, sx1, sy1 = layout["source"]
                lx0, ly0, lx1, ly1 = layout["logo"]
                overlaps = sx0 < lx1 and sx1 > lx0 and sy0 < ly1 and sy1 > ly0
                self.assertFalse(overlaps, f"{corner}: 來源句壓到 Logo")

    def test_bad_corner_is_refused_rather_than_silently_ignored(self):
        with self.assertRaises(compose.ComposeError):
            compose.vstrip_source_corner(source_corner="middle")

    def test_old_callers_behave_exactly_as_before(self):
        """沒帶 source_corner 的呼叫端要逐字元不變：跟 LIVE 章／跟 Logo。"""
        self.assertEqual(
            compose.vstrip_source_corner(title_side="left", logo_corner="tr"), "tl"
        )
        self.assertEqual(
            compose.vstrip_source_corner(title_side="right", logo_corner="tl"), "tr"
        )
        self.assertEqual(
            compose.vstrip_source_corner(
                title_side="left", logo_corner="br", source_follow_logo=True
            ),
            "br",
        )

    def test_api_and_ui_carry_the_new_field(self):
        self.assertIn("source_corner", main.YtOverlayRequest.model_fields)
        self.assertEqual(main.YtOverlayRequest.model_fields["source_corner"].default, "")
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("source_corner: v.sourceCorner", app_js)
        for corner in compose.VSTRIP_SOURCE_CORNERS:
            with self.subTest(corner=corner):
                self.assertIn(f'data-vstrip-source data-vstrip-value="{corner}"', index_html)
        # 提示改成只填來源名
        self.assertIn('placeholder="美聯社"', index_html)
