"""WP3（2026-09-08）：底色框位置三變體 ＋ YT 直播 PNG 壓標原型。

守的紅線：
1. **預設一個像素都不能變。** 使用者還沒挑位置，band 起點只是多了可傳的參數，
   不傳就要跟改動前 byte 完全一樣。
2. **漸入不准疊到字。** 帶子往下移之後漸入高度沒跟著縮，半透明的漸層會蓋在標題
   筆畫上把字糊掉。上界用**最大字級**的 ascent 算，不是拿某一句長標題 fit 完的字級
   ——短標題不縮字，ink 更高，用長標題量的上界會放行一個實際會糊字的設定。
3. **直標是透明底。** 疊在直播訊號上的東西，畫布不透明就等於把訊號整片蓋掉。
4. **主標在內側、副標在外側。** 兩欄都是深藍，像素分不出誰是誰，只能驗幾何。
5. **直排不是把整行轉 90°。** 標點要換直排字形（「→﹁、、→︑），而且 ﹁ 與 ︑ 要待在
   格子的角落——拿 getbbox 把墨水置中就會把它們拖到正中間，直排標點就白換了。
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
    def test_not_passing_the_new_kwargs_is_byte_identical_to_passing_the_old_constants(self):
        for name, fn in (("news", _news), ("hot", _hot)):
            for band in (False, True):
                with self.subTest(layout=name, bottom_band=band):
                    self.assertEqual(
                        fn(bottom_band=band),
                        fn(bottom_band=band,
                           band_top_ratio=compose.YT_BAND_TOP_RATIO,
                           band_fade_ratio=compose.YT_BAND_FADE_RATIO),
                    )

    def test_the_shipped_constants_are_still_the_ones_the_channel_signed_off(self):
        self.assertEqual(compose.YT_BAND_TOP_RATIO, 0.60)
        self.assertEqual(compose.YT_BAND_FADE_RATIO, 0.06)


class BandVariantTests(unittest.TestCase):
    def test_there_are_exactly_the_three_variants_the_user_has_to_choose_between(self):
        self.assertEqual(set(compose.YT_BAND_VARIANTS), {"line1_top", "between", "line2_top"})

    def test_the_fade_never_reaches_the_title_ink_below_it(self):
        line1_top = compose._yt_title_ink_top_ratio(compose.YT_LINE1_BASELINE_RATIO)
        line2_top = compose._yt_title_ink_top_ratio(compose.YT_LINE2_BASELINE_RATIO)
        bounds = {"line1_top": line1_top, "between": line2_top, "line2_top": line2_top}
        for name, (top, fade) in compose.YT_BAND_VARIANTS.items():
            with self.subTest(variant=name):
                self.assertLessEqual(
                    top + fade, bounds[name],
                    f"{name} 的漸入結尾 {top + fade:.4f} 蓋到 {bounds[name]:.4f} 的字",
                )

    def test_every_variant_starts_below_the_shipped_default(self):
        """使用者要的是「再往下調」，往上跑的變體不是他要的東西。"""
        for name, (top, _) in compose.YT_BAND_VARIANTS.items():
            with self.subTest(variant=name):
                self.assertGreater(top, compose.YT_BAND_TOP_RATIO)

    def test_no_variant_starts_below_the_second_line(self):
        """裁決原文：不超過第二行標題。起點掉到第二行墨水以下就違反了。"""
        line2_top = compose._yt_title_ink_top_ratio(compose.YT_LINE2_BASELINE_RATIO)
        for name, (top, _) in compose.YT_BAND_VARIANTS.items():
            with self.subTest(variant=name):
                self.assertLessEqual(top, line2_top)

    def test_each_variant_paints_a_visibly_different_row_set(self):
        """三張樣張要真的不一樣，不然使用者沒得挑。"""
        height = compose.YT_CANVAS[1]
        painted = {}
        for name, (top, fade) in compose.YT_BAND_VARIANTS.items():
            img = Image.open(io.BytesIO(_news(bottom_band=True, band_top_ratio=top,
                                              band_fade_ratio=fade))).convert("RGB")
            painted[name] = frozenset(
                y for y in range(round(height * 0.55), height)
                if img.getpixel((PROBE_X, y)) != BASE
            )
        self.assertEqual(len(set(painted.values())), 3, "有兩個變體畫出同一條帶")
        for name, rows in painted.items():
            with self.subTest(variant=name):
                self.assertTrue(rows, f"{name} 根本沒畫出帶")

    def test_a_variant_leaves_the_photo_alone_where_the_default_would_have_covered_it(self):
        """「往下調」的意思就是原本被吃掉的那一段照片要露出來。"""
        top, fade = compose.YT_BAND_VARIANTS["between"]
        probe_y = round(compose.YT_CANVAS[1] * 0.70)   # 預設帶內、變體帶外
        default = Image.open(io.BytesIO(_news(bottom_band=True))).convert("RGB")
        moved = Image.open(io.BytesIO(_news(bottom_band=True, band_top_ratio=top,
                                            band_fade_ratio=fade))).convert("RGB")
        self.assertNotEqual(default.getpixel((PROBE_X, probe_y)), BASE)
        self.assertEqual(moved.getpixel((PROBE_X, probe_y)), BASE)

    def test_both_colours_accept_the_variant(self):
        for name, fn, fill in (("news", _news, compose.YT_BAND_FILL),
                               ("hot", _hot, compose.YT_HOT_BAND_FILL)):
            for variant, (top, fade) in compose.YT_BAND_VARIANTS.items():
                with self.subTest(layout=name, variant=variant):
                    img = Image.open(io.BytesIO(fn(bottom_band=True, band_top_ratio=top,
                                                   band_fade_ratio=fade))).convert("RGB")
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

    def test_the_main_column_is_the_wider_one(self):
        layout = self._layout()
        self.assertGreater(layout["main"][2] - layout["main"][0],
                           layout["sub"][2] - layout["sub"][0])

    def test_both_columns_share_a_top_and_a_bottom(self):
        """截圖量出來就是等長：ref1 兩欄都是 y 67→358。"""
        layout = self._layout()
        self.assertEqual(layout["main"][1], layout["sub"][1])
        self.assertEqual(layout["main"][3], layout["sub"][3])

    def test_the_column_with_more_cells_gets_the_smaller_pitch(self):
        layout = self._layout()
        height = layout["column_height"]
        self.assertGreater(height / len(layout["main_cells"]),
                           height / len(layout["sub_cells"]))

    def test_the_geometry_matches_the_screenshot_within_a_percent(self):
        """ref1（718×404）：直標 x 19..77、y 67..358。換算成比例要對得上。"""
        width, height = compose.YT_CANVAS
        layout = self._layout(title_side="left")
        strip_x0, strip_x1 = layout["sub"][0], layout["main"][2]
        self.assertAlmostEqual(strip_x0 / width, 19 / 718, delta=0.006)
        self.assertAlmostEqual(strip_x1 / width, 77 / 718, delta=0.006)
        self.assertAlmostEqual(layout["main"][1] / height, 67 / 404, delta=0.006)
        self.assertAlmostEqual(layout["main"][3] / height, 358 / 404, delta=0.010)

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

    def test_a_logo_on_the_same_side_as_the_strip_is_refused_rather_than_drawn_over_it(self):
        for side, corner in (("left", "tl"), ("left", "bl"), ("right", "tr"), ("right", "br")):
            with self.subTest(side=side, corner=corner):
                with self.assertRaises(compose.ComposeError):
                    compose.compose_yt_overlay(main_title=MAIN, sub_title=SUB,
                                               title_side=side, logo_corner=corner)

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
        pitch = layout["column_height"] / len(cells)
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

    def test_following_a_top_logo_puts_it_under_the_logo(self):
        for corner, side in (("tr", "left"), ("tl", "right")):
            with self.subTest(corner=corner):
                box = self._box(logo_corner=corner, title_side=side, source_follow_logo=True)
                logo = compose.yt_vertical_layout(main_title=MAIN, sub_title=SUB,
                                                  logo_corner=corner, title_side=side)["logo"]
                self.assertGreaterEqual(box[1], logo[3])

    def test_following_a_bottom_logo_puts_it_above_the_logo(self):
        for corner, side in (("br", "left"), ("bl", "right")):
            with self.subTest(corner=corner):
                box = self._box(logo_corner=corner, title_side=side, source_follow_logo=True)
                logo = compose.yt_vertical_layout(main_title=MAIN, sub_title=SUB,
                                                  logo_corner=corner, title_side=side)["logo"]
                self.assertLessEqual(box[3], logo[1])

    def test_blank_source_text_draws_nothing(self):
        self.assertEqual(_vstrip(source_text="   ").tobytes(), _vstrip().tobytes())


if __name__ == "__main__":
    unittest.main()
