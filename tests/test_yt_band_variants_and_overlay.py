"""WP3（2026-09-08）：底色框定版（第 3 位置＋上緣羽化） ＋ YT 直播 PNG 壓標原型。

守的紅線：
1. **定版就是預設。** 使用者從三個位置樣張挑了「第二行」並要求上緣羽化，不傳參數
   就要得到那個版本；覆寫參數只留給出樣張用。
2. **漸入不准疊到字。** 帶子往下移之後漸入高度沒跟著縮，半透明的漸層會蓋在標題
   筆畫上把字糊掉。上界用**最大字級**的 ascent 算，不是拿某一句長標題 fit 完的字級
   ——短標題不縮字，ink 更高，用長標題量的上界會放行一個實際會糊字的設定。
3. **直標是透明底。** 疊在直播訊號上的東西，畫布不透明就等於把訊號整片蓋掉。
4. **主標在內側、副標在外側。** 兩欄都是深藍，像素分不出誰是誰，只能驗幾何。
4b. **兩欄同字級、同底色、同一塊色框**（2026-09-08 使用者裁決）：格距由字多的那欄決定、
   兩欄同寬、中間沒有縫、底色一個顏色畫整塊；字少的那欄早點結束。
5. **直排不是把整行轉 90°。** 標點要換直排字形（「→﹁、、→︑）。字級照格距算，em 框
   比格距高一點，相鄰的字會些微溢出格子，所以「裁一格出來量墨水位置」會量到隔壁的
   筆畫——字形這件事改用整張比對驗：清掉對照表重畫，兩張圖必須不一樣。
6. **連續英數字是一格（縱中橫）。** 「30度」的 30 併成一格橫著寫，字數上限照格數算。
7. **兩欄等長。** 參考截圖量出來就是同一個上緣同一個下緣，格數多的那欄字自動縮小。
"""
import io
import os
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402

BASE = (20, 120, 20)
LINE1 = "澳洲擬立新法"
LINE2 = "民眾可關閉社群媒體演算法"
SOURCE = "畫面來源：路透社"
MAIN = "週五變天北、東轉雨"
SUB = "明早晚涼「中午仍破30度」"
# 帶子區、但遠離置中標題的筆畫：最左緣
PROBE_X = 12


def _png(colour=BASE) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", compose.YT_CANVAS, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _news(**kw) -> bytes:
    return compose.compose_yt_cover(_png(), line1=LINE1, line2=LINE2,
                                    date_text="2026/09/08", **kw)


def _hot(**kw) -> bytes:
    return compose.compose_yt_hot_cover(_png(), line1=LINE1, line2=LINE2, **kw)


def _vstrip(**kw) -> Image.Image:
    kw.setdefault("main_title", MAIN)
    kw.setdefault("sub_title", SUB)
    return Image.open(io.BytesIO(compose.compose_yt_overlay(**kw))).convert("RGBA")


class BandDefaultTests(unittest.TestCase):
    def test_not_passing_the_kwargs_is_byte_identical_to_passing_the_constants(self):
        for name, fn in (("news", _news), ("hot", _hot)):
            for band in (False, True):
                with self.subTest(layout=name, bottom_band=band):
                    self.assertEqual(
                        fn(bottom_band=band),
                        fn(bottom_band=band,
                           band_top_ratio=compose.YT_BAND_TOP_RATIO,
                           band_fade_ratio=compose.YT_BAND_FADE_RATIO),
                    )

    def test_the_shipped_constants_are_the_ones_the_user_picked(self):
        """2026-09-08 裁決：第 3 位置（第二行）＋上緣羽化。"""
        self.assertEqual(compose.YT_BAND_TOP_RATIO, 0.778)
        self.assertEqual(compose.YT_BAND_FADE_RATIO, 0.0365)


class BandPlacementTests(unittest.TestCase):
    def test_the_band_starts_at_the_first_line_baseline_not_above_it(self):
        """羽化從第一行字底開始：再往上就會蓋到第一行的筆畫。"""
        self.assertGreaterEqual(compose.YT_BAND_TOP_RATIO, compose.YT_LINE1_BASELINE_RATIO)

    def test_the_fade_reaches_full_strength_before_the_second_line_ink(self):
        """裁決原文：不超過第二行標題。羽化結尾要壓在第二行墨水上緣之上。"""
        line2_top = compose._yt_title_ink_top_ratio(compose.YT_LINE2_BASELINE_RATIO)
        end = compose.YT_BAND_TOP_RATIO + compose.YT_BAND_FADE_RATIO
        self.assertLessEqual(end, line2_top, f"羽化結尾 {end:.4f} 蓋到 {line2_top:.4f} 的字")

    def test_the_top_edge_is_feathered_not_a_hard_line(self):
        """使用者要求「框上邊的邊緣界線要漸層羽化」：帶子上緣的 alpha 要單調漸增、
        而且首尾都貼近 0／全濃度（smoothstep），不能一行就跳到全濃度。"""
        height = compose.YT_CANVAS[1]
        top = round(height * compose.YT_BAND_TOP_RATIO)
        fade = round(height * compose.YT_BAND_FADE_RATIO)
        self.assertGreaterEqual(fade, 30, "羽化太薄，肉眼就是一條硬邊")
        img = Image.open(io.BytesIO(_news(bottom_band=True))).convert("RGB")
        base_r = BASE[0]
        # 帶子是深藍，蓋上去 R 通道只會往下走；沿 x=PROBE_X 從帶子上緣往下量
        reds = [img.getpixel((PROBE_X, y))[0] for y in range(top - 1, top + fade + 1)]
        self.assertEqual(reds[0], base_r, "帶子上緣之上不該有顏色")
        for earlier, later in zip(reds, reds[1:]):
            self.assertGreaterEqual(earlier, later, "羽化不是單調漸變")
        drop_total = reds[0] - reds[-1]
        self.assertGreater(drop_total, 0)
        # 前 20% 與後 20% 的變化都要平緩（各不到總落差的 15%）：這就是 smoothstep 跟直線的差別
        fifth = max(1, len(reds) // 5)
        self.assertLess(reds[0] - reds[fifth], drop_total * 0.15)
        self.assertLess(reds[-1 - fifth] - reds[-1], drop_total * 0.15)

    def test_the_photo_above_the_first_line_is_left_alone(self):
        """舊預設從 0.60 起就壓照片；定版後第一行之上一律露出原圖。"""
        img = Image.open(io.BytesIO(_news(bottom_band=True))).convert("RGB")
        for ratio in (0.60, 0.66, 0.72, 0.77):
            with self.subTest(ratio=ratio):
                self.assertEqual(img.getpixel((PROBE_X, round(compose.YT_CANVAS[1] * ratio))), BASE)

    def test_both_colours_are_semi_transparent_at_the_bottom(self):
        for name, fn, fill in (("news", _news, compose.YT_BAND_FILL),
                               ("hot", _hot, compose.YT_HOT_BAND_FILL)):
            with self.subTest(layout=name):
                img = Image.open(io.BytesIO(fn(bottom_band=True))).convert("RGB")
                pixel = img.getpixel((PROBE_X, compose.YT_CANVAS[1] - 6))
                self.assertNotEqual(pixel, BASE)
                self.assertNotEqual(pixel, fill, "半透明沒了")


class VerticalCellTests(unittest.TestCase):
    """直排的分格：標點換直排字形、連續英數字併成一格。"""

    def test_a_run_of_letters_or_digits_is_one_cell(self):
        self.assertEqual(
            compose._vertical_cells("明早晚涼「中午仍破30度」"),
            ["明", "早", "晚", "涼", "﹁", "中", "午", "仍", "破", "30", "度", "﹂"],
        )
        self.assertEqual(
            compose._vertical_cells("「AI想像力的未來」"),
            ["﹁", "AI", "想", "像", "力", "的", "未", "來", "﹂"],
        )

    def test_the_reference_titles_have_the_cell_counts_measured_off_the_screenshots(self):
        """參考截圖：主標 9 格、副標 12 格，欄高一樣。格數對不上就代表分格錯了。"""
        self.assertEqual(len(compose._vertical_cells("週五變天北、東轉雨")), 9)
        self.assertEqual(len(compose._vertical_cells("明早晚涼「中午仍破30度」")), 12)

    def test_punctuation_is_swapped_for_its_vertical_form(self):
        for flat, upright in (("「", "﹁"), ("」", "﹂"), ("、", "︑"), ("。", "︒"), ("，", "︐")):
            with self.subTest(char=flat):
                self.assertEqual(compose._vertical_cells(f"天{flat}地"), ["天", upright, "地"])

    def test_every_vertical_form_has_a_real_glyph_in_the_bundled_font(self):
        """換成沒字形的碼位＝畫出豆腐，比不換還糟。"""
        font = compose._font(48)
        for upright in set(compose.VERTICAL_PUNCTUATION.values()):
            with self.subTest(char=upright):
                self.assertFalse(compose._is_tofu(upright, font))


class VerticalLayoutTests(unittest.TestCase):
    def _layout(self, **kw):
        kw.setdefault("main_title", MAIN)
        kw.setdefault("sub_title", SUB)
        return compose.yt_vertical_layout(**kw)

    def test_the_main_column_is_the_one_nearer_the_middle_of_the_frame(self):
        """兩欄都是深藍，像素分不出誰是誰——主標在內側只能靠幾何驗。"""
        width = compose.YT_CANVAS[0]
        for side in compose.VSTRIP_SIDES:
            with self.subTest(side=side):
                layout = self._layout(title_side=side)
                main_cx = (layout["main"][0] + layout["main"][2]) / 2
                sub_cx = (layout["sub"][0] + layout["sub"][2]) / 2
                self.assertLess(abs(main_cx - width / 2), abs(sub_cx - width / 2))

    def test_the_two_columns_are_the_same_width(self):
        """同字級就得同寬，不然窄的那欄字會被 0.94 欄寬的上限壓小。"""
        layout = self._layout()
        self.assertEqual(layout["main"][2] - layout["main"][0],
                         layout["sub"][2] - layout["sub"][0])

    def test_the_two_columns_touch_and_form_one_box(self):
        """同一個色框不拆開：兩欄之間沒有縫，box 就是兩欄的聯集。"""
        for side in ("left", "right"):
            with self.subTest(side=side):
                layout = self._layout(title_side=side)
                inner, outer = sorted((layout["main"], layout["sub"]), key=lambda r: r[0])
                self.assertEqual(inner[2], outer[0], "兩欄之間有縫")
                self.assertEqual(layout["box"], (inner[0], inner[1], outer[2], inner[3]))

    def test_both_columns_share_a_top_and_a_bottom(self):
        """截圖量出來就是等長：ref1 兩欄都是 y 67→358。"""
        layout = self._layout()
        self.assertEqual(layout["main"][1], layout["sub"][1])
        self.assertEqual(layout["main"][3], layout["sub"][3])

    def test_both_columns_share_one_pitch_set_by_the_longer_title(self):
        """兩行直標字級一樣大：格距只有一個，由格數多的那欄決定。"""
        layout = self._layout()
        most = max(len(layout["main_cells"]), len(layout["sub_cells"]))
        self.assertAlmostEqual(layout["pitch"], layout["column_height"] / most, places=6)
        # 主標 9 格比副標 12 格短：主標用同一個格距，只佔欄高的 9/12
        self.assertLess(len(layout["main_cells"]), most)
        self.assertLess(layout["pitch"] * len(layout["main_cells"]), layout["column_height"])

    def test_the_geometry_matches_the_screenshot_within_a_percent(self):
        """ref1（718×404）：直標 x 19..77、y 67..358。換算成比例要對得上。"""
        width, height = compose.YT_CANVAS
        layout = self._layout(title_side="left")
        strip_x0, strip_x1 = layout["sub"][0], layout["main"][2]
        self.assertAlmostEqual(strip_x0 / width, 19 / 718, delta=0.006)
        # 2026-09-09 使用者要求「兩行之間的行距縮小」：欄寬改由字級推導，整組比截圖窄。
        # 外緣不動，右緣只驗「不寬於截圖的 19+32×2」與「還放得下字」。
        self.assertLessEqual(strip_x1 / width, 83 / 718 + 1e-9)
        self.assertGreater(strip_x1, strip_x0)
        # 2026-09-09：色框不再貼著 LIVE 章往下長，而是在可用範圍內置中偏上，
        # 所以上緣一定低於截圖的 67/404，但仍在 LIVE 章之下、可用範圍之內。
        self.assertGreaterEqual(layout["main"][1] / height, 67 / 404 - 0.006)
        self.assertGreater(layout["main"][1], layout["live"][3])
        # 總長度有硬上限（VSTRIP_COLUMN_MAX_RATIO），底緣不得破可用範圍下緣
        self.assertLessEqual(layout["main"][3] / height, compose.VSTRIP_BOTTOM_MAX_RATIO + 1e-9)
        self.assertLessEqual(
            layout["column_height"] / height, compose.VSTRIP_COLUMN_MAX_RATIO + 1e-9
        )

    def test_the_strip_sits_on_the_side_it_was_told_to(self):
        width = compose.YT_CANVAS[0]
        left = self._layout(title_side="left")
        right = self._layout(title_side="right")
        self.assertLess(left["main"][2], width / 2)
        self.assertGreater(right["main"][0], width / 2)

    def test_the_label_variants_push_the_columns_down_and_the_badge_up(self):
        plain = self._layout(variant="normal")
        for variant in ("original_audio", "ai_translation"):
            with self.subTest(variant=variant):
                labelled = self._layout(variant=variant)
                self.assertGreater(labelled["main"][1], plain["main"][1])
                self.assertLess(labelled["live"][1], plain["live"][1])
                self.assertGreater(labelled["label"][3], labelled["label"][1])

    def test_the_box_keeps_a_gap_below_the_live_badge_and_the_label(self):
        """2026-09-08 使用者：直標頂部跟 LIVE 章靠太近，頂上兩個字快被吃掉。
        色框上緣要在 LIVE 章（有小標時是小標）底下留一段空隙。"""
        height = compose.YT_CANVAS[1]
        gap = round(height * compose.VSTRIP_TOP_GAP_RATIO)
        for variant in compose.VSTRIP_VARIANTS:
            with self.subTest(variant=variant):
                layout = self._layout(variant=variant)
                stack_bottom = layout["label"][3] if variant in compose.VSTRIP_VARIANT_LABELS                     else layout["live"][3]
                self.assertGreaterEqual(layout["box"][1] - stack_bottom, gap)
                self.assertGreaterEqual(gap, 10, "空隙小到看不出來")

    def test_the_plain_variant_has_no_label_box(self):
        layout = self._layout(variant="normal")
        self.assertEqual(layout["label"], (0, 0, 0, 0))

    def test_a_title_longer_than_the_limit_is_refused(self):
        with self.assertRaises(compose.ComposeError):
            compose.yt_vertical_layout(main_title="一" * (compose.VSTRIP_MAIN_MAX_CELLS + 1))
        with self.assertRaises(compose.ComposeError):
            compose.yt_vertical_layout(main_title=MAIN, sub_title="一" * (compose.VSTRIP_SUB_MAX_CELLS + 1))

    def test_an_empty_main_title_is_refused(self):
        with self.assertRaises(compose.ComposeError):
            compose.yt_vertical_layout(main_title="")

    def test_the_longest_allowed_pair_still_fits_above_the_minimum_pitch(self):
        """字數上限跟最小字級是兩條規則，撞在一起就會出現「合法字數卻畫不出來」。"""
        layout = compose.yt_vertical_layout(
            main_title="一" * compose.VSTRIP_MAIN_MAX_CELLS,
            sub_title="一" * compose.VSTRIP_SUB_MAX_CELLS,
        )
        floor = compose.YT_CANVAS[1] * compose.VSTRIP_MIN_PITCH_RATIO
        for key in ("main", "sub"):
            self.assertGreaterEqual(layout["column_height"] / len(layout[f"{key}_cells"]), floor)


class VerticalCanvasTests(unittest.TestCase):
    def test_the_canvas_is_rgba_and_mostly_transparent(self):
        img = _vstrip(source_text=SOURCE)
        self.assertEqual(img.mode, "RGBA")
        ratio = img.getchannel("A").histogram()[0] / (img.width * img.height)
        self.assertGreater(ratio, 0.6, f"透明像素只有 {ratio:.1%}，蓋掉太多直播畫面")

    def test_the_middle_of_the_frame_is_untouched(self):
        img = _vstrip(source_text=SOURCE)
        middle = img.crop((round(img.width * 0.25), round(img.height * 0.25),
                           round(img.width * 0.8), round(img.height * 0.8)))
        self.assertEqual(middle.getchannel("A").getextrema(), (0, 0))

    def test_the_painted_pixels_land_on_the_chosen_side(self):
        width = compose.YT_CANVAS[0]
        for side, expect_left in (("left", True), ("right", False)):
            with self.subTest(side=side):
                corner = "tr" if side == "left" else "tl"
                alpha = _vstrip(title_side=side, logo_corner=corner).getchannel("A")
                strip = alpha.crop((0, round(alpha.height * 0.2), width, round(alpha.height * 0.9)))
                mask = strip.point(lambda v: 255 if v > 0 else 0)
                left = sum(mask.crop((0, 0, width // 2, mask.height)).histogram()[255:])
                right = sum(mask.crop((width // 2, 0, width, mask.height)).histogram()[255:])
                if expect_left:
                    self.assertGreater(left, right * 10)
                else:
                    self.assertGreater(right, left * 10)

    def test_the_columns_are_actually_painted_navy(self):
        img = _vstrip()
        layout = compose.yt_vertical_layout(main_title=MAIN, sub_title=SUB)
        for key in ("main", "sub"):
            with self.subTest(column=key):
                x0, y0, x1, y1 = layout[key]
                # 取欄的最底一列、避開字：底色一定在
                r, g, b, a = img.getpixel(((x0 + x1) // 2, y1 - 3))
                self.assertEqual(a, 255)
                self.assertGreater(b, r + 25, "欄底色不是藍的")

    def test_the_box_is_one_continuous_colour_across_the_seam(self):
        """同一個色框：跨過兩欄交界的那一列，顏色連續（沒有縫、沒有兩種藍）。"""
        img = _vstrip()
        layout = compose.yt_vertical_layout(main_title=MAIN, sub_title=SUB)
        x0, _, x1, y1 = layout["box"]
        y = y1 - 3
        row = [img.getpixel((x, y)) for x in range(x0, x1)]
        self.assertTrue(all(px[3] == 255 for px in row), "色框裡有透明縫")
        for left, right in zip(row, row[1:]):
            self.assertLessEqual(max(abs(left[i] - right[i]) for i in range(3)), 3,
                                 "相鄰兩個像素跳色：色框被拆成兩塊")

    def test_both_titles_are_drawn_at_the_same_glyph_size(self):
        """兩行直標字級一樣大：拿同一個字在兩欄各畫一格，墨水高度要一樣。"""
        img = _vstrip(main_title="國國國", sub_title="國國國國國國")
        layout = compose.yt_vertical_layout(main_title="國國國", sub_title="國國國國國國")
        pitch = layout["pitch"]
        heights = {}
        for key in ("main", "sub"):
            x0, y0, x1, _ = layout[key]
            cell = img.crop((x0 + 2, y0, x1 - 2, y0 + round(pitch))).convert("L")
            # 白字在深藍上：亮度高的就是墨水
            ink = cell.point(lambda v: 255 if v > 160 else 0).getbbox()
            self.assertIsNotNone(ink, f"{key} 第一格沒有字")
            heights[key] = ink[3] - ink[1]
        self.assertLessEqual(abs(heights["main"] - heights["sub"]), 2, heights)

    def test_a_logo_on_the_same_side_top_corner_is_refused_rather_than_drawn_over_it(self):
        """同側的**上**角有 LIVE 章與色框頂，照舊擋掉（2026-09-09 起只擋上角）。"""
        for side, corner in (("left", "tl"), ("right", "tr")):
            with self.subTest(side=side, corner=corner):
                with self.assertRaises(compose.ComposeError):
                    compose.compose_yt_overlay(main_title=MAIN, sub_title=SUB,
                                               title_side=side, logo_corner=corner)

    def test_a_logo_on_the_same_side_bottom_corner_is_allowed_and_the_strip_makes_room(self):
        """2026-09-09 使用者：直標縮短後左下／右下要能跟直標同側，色框自己讓開。"""
        for side, corner in (("left", "bl"), ("right", "br")):
            with self.subTest(side=side, corner=corner):
                layout = compose.yt_vertical_layout(
                    main_title=MAIN, sub_title=SUB, title_side=side, logo_corner=corner
                )
                self.assertLess(layout["box"][3], layout["logo"][1], "色框壓到同側下角的 Logo")
                # 真的畫得出來，不是只有幾何算得過
                self.assertTrue(compose.compose_yt_overlay(
                    main_title=MAIN, sub_title=SUB, title_side=side, logo_corner=corner
                ))

    def test_it_refuses_sizes_and_options_it_cannot_draw(self):
        for kw in ({"size": (3840, 2160)}, {"variant": "karaoke"},
                   {"logo_corner": "middle"}, {"title_side": "centre"}):
            with self.subTest(**kw):
                with self.assertRaises(compose.ComposeError):
                    compose.compose_yt_overlay(main_title=MAIN, sub_title=SUB, **kw)

    def test_turning_live_off_removes_the_badge(self):
        box = compose.yt_vertical_layout(main_title=MAIN, sub_title=SUB)["live"]
        on = _vstrip(live=True).crop(box).getchannel("A").histogram()[255]
        off = _vstrip(live=False).crop(box).getchannel("A").histogram()[255]
        self.assertGreater(on, off)


class VerticalGlyphTests(unittest.TestCase):
    """直排字形有沒有真的走到畫圖那一步。

    注意：字級是照格距算的，em 框比格距高一點，所以相鄰的字會些微溢出格子——
    用「裁一格出來量墨水位置」的方式驗字形位置會量到隔壁的筆畫，不可靠。
    這裡改成整張比對：關掉標點對照表重畫一次，兩張圖必須不一樣。
    """

    def _render(self, mapping=None) -> bytes:
        original = compose.VERTICAL_PUNCTUATION
        if mapping is not None:
            compose.VERTICAL_PUNCTUATION = mapping
        try:
            return compose.compose_yt_overlay(main_title=MAIN, sub_title=SUB)
        finally:
            compose.VERTICAL_PUNCTUATION = original

    def test_the_vertical_forms_actually_reach_the_canvas(self):
        """把對照表清空（標點維持橫排字形）畫出來的圖，必須跟正常的不一樣。

        只驗 _vertical_cells 的回傳值，驗不到中間有人又把 cell 換回橫排字形。
        """
        self.assertNotEqual(self._render(), self._render(mapping={}),
                            "清掉直排標點對照表卻畫出同一張圖，代表換字形沒有生效")

    def test_the_titles_under_test_really_do_contain_mapped_punctuation(self):
        """上面那條比對要有意義，前提是標題裡真的有被換掉的標點。"""
        self.assertIn("︑", compose._vertical_cells(MAIN))
        self.assertIn("﹁", compose._vertical_cells(SUB))
        self.assertIn("﹂", compose._vertical_cells(SUB))

    def test_the_digits_pair_stays_horizontal_inside_one_cell(self):
        """30 是縱中橫：一格、橫著寫，所以那一格的墨水比高還寬。

        這一格上下的鄰居是 破 與 度，溢出的筆畫在左右不在上下，量寬高仍然可靠。
        """
        layout = compose.yt_vertical_layout(main_title=MAIN, sub_title=SUB)
        cells = layout["sub_cells"]
        index = cells.index("30")
        x0, y0, x1, _ = layout["sub"]
        pitch = layout["pitch"]
        # 只取格子中間六成，避開上下鄰居溢出來的筆畫
        top = y0 + round((index + 0.2) * pitch)
        bottom = y0 + round((index + 0.8) * pitch)
        ink = _vstrip().crop((x0, top, x1, bottom)).convert("RGB").point(
            lambda v: 255 if v > 200 else 0)
        box = ink.getbbox()
        self.assertIsNotNone(box, "30 那一格沒畫出東西")
        self.assertGreater(box[2] - box[0], (x1 - x0) * 0.5,
                           "30 沒有橫著佔滿格寬，可能被排成上下兩格")

    def test_a_latin_run_is_one_cell_so_the_column_does_not_get_longer(self):
        """縱中橫的重點是省格數：超 微 AMD 總 經 理 是 6 格，不是 8 格。"""
        with_latin = compose.yt_vertical_layout(main_title="超微AMD總經理")
        self.assertEqual(with_latin["main_cells"], ["超", "微", "AMD", "總", "經", "理"])


class VerticalSourceTextTests(unittest.TestCase):
    def _box(self, **kw):
        from PIL import ImageChops
        without = _vstrip(**kw).getchannel("A")
        with_text = _vstrip(source_text=SOURCE, **kw).getchannel("A")
        return ImageChops.difference(with_text, without).getbbox()

    def test_by_default_it_sits_beside_the_live_badge(self):
        layout = compose.yt_vertical_layout(main_title=MAIN, sub_title=SUB, source_text=SOURCE)
        live = layout["live"]
        box = self._box()
        self.assertIsNotNone(box)
        self.assertGreaterEqual(box[0], live[2], "來源句沒有落在 LIVE 章右邊")
        # 跟 LIVE 章同一列：垂直中心相差不到章高的一半
        self.assertLess(abs((box[1] + box[3]) / 2 - (live[1] + live[3]) / 2),
                        (live[3] - live[1]) / 2 + 8)

    def _layout(self, **kw):
        return compose.yt_vertical_layout(main_title=MAIN, sub_title=SUB,
                                          source_text=SOURCE, **kw)

    def test_sharing_the_logo_corner_stands_beside_it_not_stacked(self):
        """2026-09-09（第三批）使用者：「都選右下會黏在一起」。

        舊做法是疊在 Logo 正上／正下、只隔 15px 而且左右完全重疊。現在改成排在 Logo
        內側的同一列，中間至少讓開一個 Logo 留白的寬度——Logo 一律不動。
        """
        pad = round(compose.YT_CANVAS[0] * compose.VSTRIP_SOURCE_LOGO_GAP_RATIO)
        for corner, side in (("tr", "left"), ("tl", "right"),
                             ("br", "left"), ("bl", "right")):
            with self.subTest(corner=corner):
                drawn = self._box(logo_corner=corner, title_side=side, source_follow_logo=True)
                layout = self._layout(logo_corner=corner, title_side=side,
                                      source_follow_logo=True)
                logo = layout["logo"]
                if corner in ("tr", "br"):   # Logo 靠右 → 句子在它左邊
                    self.assertAlmostEqual(logo[0] - drawn[2], pad, delta=8)
                else:                        # Logo 靠左 → 句子在它右邊
                    self.assertAlmostEqual(drawn[0] - logo[2], pad, delta=8)
                # 同一列：垂直範圍落在 Logo 之內（所以色框只要讓開 Logo 就夠）
                self.assertGreaterEqual(drawn[1], logo[1] - 8)
                self.assertLessEqual(drawn[3], logo[3] + 8)
                # 幾何跟畫出來的要對得上，不能一個算一套
                self.assertAlmostEqual(drawn[1], layout["source"][1], delta=8)

    def test_the_two_modes_put_the_line_in_different_places(self):
        """兩種模式要真的不一樣，不然「跟著 Logo」這個開關等於沒接。"""
        beside = self._layout(logo_corner="br", title_side="left")["source"]
        follow = self._layout(logo_corner="br", title_side="left",
                              source_follow_logo=True)["source"]
        self.assertNotEqual(beside, follow)

    def test_blank_source_text_draws_nothing(self):
        self.assertEqual(_vstrip(source_text="   ").tobytes(), _vstrip().tobytes())


if __name__ == "__main__":
    unittest.main()
