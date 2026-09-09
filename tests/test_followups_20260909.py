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

    def test_band_is_described_relative_to_the_two_coloured_lines(self):
        """2026-09-09（第四批）：改用顏色點名兩條線——白字的基線是上緣，黃字的上緣是
        全飽和處。比「上面那一行／下面那一行」具體，模型跟得動。"""
        for clause in self.CLAUSES:
            with self.subTest(clause=clause[:40]):
                self.assertIn("BASELINE (the feet) of the WHITE upper headline line", clause)
                self.assertIn("just above the top of the GOLDEN YELLOW lower line", clause)

    def test_the_clause_overrides_the_templates_lower_40_percent_figure(self):
        """2026-09-09（第三批）實測根因：模板下一行的「lower 40%」被拿去撐色框。

        第三批把百分比整個拿掉、只留關係式，使用者實測仍然太高（附圖）——模型手上
        就只剩那個 40% 可抄。第四批把合成版的真實數字寫回去，數字與關係式並存。
        """
        for clause in self.CLAUSES:
            with self.subTest(clause=clause[:40]):
                self.assertIn("NOT FROM THE 「lower 40%」 FIGURE ABOVE", clause)
                self.assertIn("sizes the TEXT BLOCK and says nothing about the band", clause)
                self.assertIn("TOP EDGE IS AT 78% OF THE FRAME HEIGHT", clause)
                self.assertIn("ONLY THE BOTTOM 22%", clause)
                self.assertIn("NOT the lower 40%", clause)

    def test_the_number_in_the_clause_matches_the_composite_band(self):
        """條文寫的 78%／22% 就是合成版的 compose.YT_BAND_TOP_RATIO，不能各寫各的。"""
        top = round(compose.YT_BAND_TOP_RATIO * 100)
        for clause in self.CLAUSES:
            with self.subTest(clause=clause[:40]):
                self.assertIn(f"AT {top}% OF THE FRAME HEIGHT", clause)
                self.assertIn(f"ONLY THE BOTTOM {100 - top}%", clause)

    def test_the_clause_comes_after_the_headline_bullet_not_before(self):
        """這個 repo 的慣例是位置在後＋明文 OVERRIDE 才贏；放在 40% 前面等於被壓掉。"""
        for template in (editor_formats.YT_COVER_FULL_PROMPT_NEWS,
                         editor_formats.YT_COVER_FULL_PROMPT_HOT):
            with self.subTest(template=template[:40]):
                self.assertLess(
                    template.index("lower 40% of the frame"),
                    template.index("{band_clause}"),
                    "色框條必須排在標題那條之後",
                )

    def test_translucency_is_still_spelled_out(self):
        for clause in self.CLAUSES:
            with self.subTest(clause=clause[:40]):
                self.assertIn("translucent", clause)
                self.assertIn("about 60% opaque", clause)

    def test_the_band_stays_the_same_order_as_the_composite_one(self):
        """合成版框上緣 0.778＝畫面下方兩成多；條文的相對量要落在同一個量級。"""
        self.assertLess(1 - compose.YT_BAND_TOP_RATIO, 0.25)
        for clause in self.CLAUSES:
            self.assertIn("shallow strip about one fifth of the picture", clause)

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
        """apply_broadcast_hole 事後會在安全區右下角蓋「示意圖」，會壓到跨全寬的條。

        關鍵是那個角**不鏡射**：不管挖空在左還在右，浮水印永遠畫在
        (x1 - HOLE_INSET, y1 - HOLE_INSET)，也就是安全區的右下角。兩個版型都要說
        lower-RIGHT，跟著 opposite_en 翻邊的話 broadcast_right 會叫模型留錯角。
        """
        self.assertEqual(compose.WATERMARK_TEXT, "示意圖")
        for key in self.KEYS:
            with self.subTest(key=key):
                rules = editor_formats.digest_rules(key, "編輯", stamp=True)
                self.assertIn("extreme lower-RIGHT corner", rules)
                self.assertNotIn("extreme lower-left corner", rules)

    def test_the_watermark_really_is_at_the_bottom_right_for_both_sides(self):
        """上一條的前提：浮水印座標寫死在安全區右下角，與挖空側無關。"""
        import inspect

        source = inspect.getsource(compose.apply_broadcast_hole)
        self.assertIn("(x1 - HOLE_INSET, y1 - HOLE_INSET)", source)
        self.assertIn('anchor="rs"', source)

    def test_rule_three_no_longer_contradicts_rule_five(self):
        for key in self.KEYS:
            with self.subTest(key=key):
                on = editor_formats.digest_rules(key, "編輯", stamp=True)
                self.assertIn("closing <蓋章> banner is the one other full-width element", on)
                off = editor_formats.digest_rules(key, "編輯", stamp=False)
                self.assertIn("<底帶> line is the one other full-width element", off)

    def test_stamp_off_fills_the_bottom_strip_with_its_own_marked_line(self):
        """2026-09-09（第三批＋第四批）使用者：「沒有開蓋章，其他資訊還是可以放底下」。

        第三批寫成「最後一張卡下移到底帶」，使用者實測（蓋章 OFF ＋字多）底部仍然全空：
        那張卡在 variable 裡跟其他卡一模一樣，模型沒有依據把它挑出來。第四批改成給它
        自己的標記 <底帶>，比照 <蓋章>（那個開著就做得到）。使用者同時開放底帶跨版。
        """
        for key in self.KEYS:
            with self.subTest(key=key):
                rules = editor_formats.digest_rules(key, "編輯", stamp=False)
                self.assertIn("THERE IS NO STAMP BANNER IN THIS GRAPHIC", rules)
                self.assertIn("THE LOW STRIP UNDER THE RESERVED AREA IS STILL FILLED", rules)
                self.assertIn("BY A <底帶> LINE INSTEAD", rules)
                self.assertIn("BELOW the reserved area", rules)
                # variable 的收尾必須是那一行，才有東西可以擺到底帶
                self.assertIn("then exactly one line beginning with the marker <底帶>", rules)
                # 使用者：底部元素可跨版（就像標題可跨版）
                self.assertIn("it crosses both halves", rules)
                # 不能被讀成又要生一條蓋章
                self.assertIn("do not put a <蓋章> line", rules)
                self.assertIn("NOT as a closing slogan", rules)
                # 浮水印一樣蓋在右下角，OFF 也要留位
                self.assertIn("extreme lower-RIGHT corner", rules)

    def test_the_reserved_window_is_described_as_wide_and_short(self):
        """第 1 條原本寫「filling most of the half」，模型畫成整片高牆，底下那條帶
        根本不存在（使用者附圖）。實際的挖空框是寬扁的橫幅視窗、垂直置中
        （compose.apply_broadcast_hole：寬佔安全區四成五、比例 16:9）。"""
        for key in self.KEYS:
            for stamp in (True, False):
                with self.subTest(key=key, stamp=stamp):
                    rules = editor_formats.digest_rules(key, "編輯", stamp=stamp)
                    self.assertIn("WIDE, SHORT rectangle", rules)
                    self.assertIn("much wider than it is tall", rules)
                    self.assertIn("deeper clear strip is left BELOW it", rules)
                    self.assertIn("does NOT reach the bottom of the frame", rules)
                    self.assertNotIn("filling most of the", rules)

    def test_the_backstop_promotes_the_last_card_when_the_model_forgets(self):
        """prompt 只是勸告，第三批就是敗在這裡。漏寫 <底帶> 就把最後一張卡升級。"""
        variable = "[標題] 甲\n[內文小標] 乙\n[內文小標] 丙\n[內文小標] 丁"
        self.assertEqual(
            main.ensure_bottom_band_line(variable),
            "[標題] 甲\n[內文小標] 乙\n[內文小標] 丙\n<底帶> 丁",
        )

    def test_the_backstop_leaves_a_compliant_result_alone(self):
        variable = "[標題] 甲\n[內文小標] 乙\n<底帶> 丙"
        self.assertEqual(main.ensure_bottom_band_line(variable), variable)

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
        main = "十二個格子滿滿滿滿的標題"
        sub = "十四個格子滿滿滿滿滿的標題喔"
        self.assertEqual(len(compose._vertical_cells(main)), compose.VSTRIP_MAIN_MAX_CELLS)
        self.assertEqual(len(compose._vertical_cells(sub)), compose.VSTRIP_SUB_MAX_CELLS)
        # 最擠：有小標（上緣被壓低）＋ Logo 同側下角（下緣被壓高）＋ 來源句也在那一角
        compose.compose_yt_overlay(
            main_title=main, sub_title=sub, title_side="left",
            variant="original_audio", logo_corner="bl",
            source_text="美聯社", source_corner="bl",
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

    def test_nothing_crowds_anything_in_any_combination(self):
        """來源句 × Logo × 色框 × LIVE 章，兩兩都要留出可見的距離——窮舉所有合法組合。

        2026-09-09（第三批）升級：舊版只驗「沒有像素重疊」，所以 Logo 與來源句同角時
        只隔 15px、左右完全對齊也算過關，使用者一眼就看出「黏在一起」。現在改驗最小淨距。
        """
        import itertools

        def clearance(a, b):
            """兩個矩形的最小淨距；有重疊回傳負值。"""
            dx = max(a[0] - b[2], b[0] - a[2])
            dy = max(a[1] - b[3], b[1] - a[3])
            return max(dx, dy) if (dx >= 0 or dy >= 0) else -1

        # 來源句貼在 LIVE 章旁邊是截圖本來的做法，門檻低一點；其餘要看得出是兩個元素
        limits = (("source", "logo", 30), ("source", "box", 20),
                  ("logo", "box", 20), ("source", "live", 12))
        titles = [("明早晚涼中午破30度", "北臺灣週三轉濕涼留意日夜溫差"),
                  ("十二個格子滿滿滿滿的標題", "十四個格子滿滿滿滿滿的標題喔"),
                  ("川普宣布關稅", "")]
        for side, logo, corner, variant in itertools.product(
            compose.VSTRIP_SIDES, compose.VSTRIP_CORNERS,
            compose.VSTRIP_SOURCE_CORNERS, compose.VSTRIP_VARIANTS,
        ):
            if logo == ("tl" if side == "left" else "tr"):
                continue  # 同側上角本來就擋掉
            for main_title, sub_title in titles:
                with self.subTest(side=side, logo=logo, corner=corner,
                                  variant=variant, cells=len(main_title)):
                    layout = compose.yt_vertical_layout(
                        main_title=main_title, sub_title=sub_title, title_side=side,
                        logo_corner=logo, variant=variant,
                        source_text="美聯社", source_corner=corner,
                    )
                    for a, b, floor in limits:
                        self.assertGreaterEqual(
                            clearance(layout[a], layout[b]), floor,
                            f"{a} 與 {b} 太近（{layout[a]} vs {layout[b]}）")

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
