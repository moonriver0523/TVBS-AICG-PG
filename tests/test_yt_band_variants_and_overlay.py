"""WP3（2026-09-08）：底色框位置三變體 ＋ YT 直播 PNG 壓標原型。

守的紅線：
1. **預設一個像素都不能變。** 使用者還沒挑位置，band 起點只是多了可傳的參數，
   不傳就要跟改動前 byte 完全一樣。
2. **漸入不准疊到字。** 帶子往下移之後漸入高度沒跟著縮，半透明的漸層會蓋在標題
   筆畫上把字糊掉。上界用**最大字級**的 ascent 算，不是拿某一句長標題 fit 完的字級
   ——短標題不縮字，ink 更高，用長標題量的上界會放行一個實際會糊字的設定。
3. **壓標是透明底。** 疊在直播訊號上的東西，畫布不透明就等於把訊號整片蓋掉。
4. **標題條不准壓到斜標籤。** 八種組合裡有四種是「Logo 在下、標題條同一側」，
   幾何上一定會撞；要靠讓位算出來，不是靠叫使用者別選那幾種。
5. **來源句跟著 Logo 走。** Logo 在上→句子在標籤下方，Logo 在下→在標籤上方。
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


def _overlay(**kw) -> Image.Image:
    kw.setdefault("line1", LINE1)
    kw.setdefault("line2", LINE2)
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


class OverlayCanvasTests(unittest.TestCase):
    def test_the_canvas_is_rgba_and_mostly_transparent(self):
        img = _overlay(source_text=SOURCE)
        self.assertEqual(img.mode, "RGBA")
        alpha = img.getchannel("A")
        clear = alpha.histogram()[0]
        ratio = clear / (img.width * img.height)
        self.assertGreater(ratio, 0.6, f"透明像素只有 {ratio:.1%}，蓋掉太多直播畫面")

    def test_nothing_is_painted_across_the_middle_of_the_frame(self):
        """畫面正中央是主播／受訪者，壓標不能碰。"""
        img = _overlay(source_text=SOURCE)
        band = img.crop((round(img.width * 0.3), round(img.height * 0.3),
                         round(img.width * 0.7), round(img.height * 0.55)))
        self.assertEqual(band.getchannel("A").getextrema(), (0, 0))

    def test_it_refuses_sizes_it_cannot_actually_draw(self):
        with self.assertRaises(compose.ComposeError):
            compose.compose_yt_overlay(line1=LINE1, line2=LINE2, size=(3840, 2160))

    def test_it_refuses_unknown_corners_and_sides(self):
        with self.assertRaises(compose.ComposeError):
            compose.compose_yt_overlay(line1=LINE1, line2=LINE2, logo_corner="middle")
        with self.assertRaises(compose.ComposeError):
            compose.compose_yt_overlay(line1=LINE1, line2=LINE2, title_side="centre")

    def test_dropping_the_band_leaves_the_titles(self):
        with_band = _overlay(band=True)
        without = _overlay(band=False)
        self.assertLess(
            without.getchannel("A").histogram()[255],
            with_band.getchannel("A").histogram()[255],
            "關掉底塊反而畫得更滿",
        )
        # 標題本身還在：條的位置仍有不透明筆畫
        bar = compose.yt_overlay_layout("tr", "left")["bar"]
        self.assertGreater(without.crop(bar).getchannel("A").getextrema()[1], 0)


class OverlayLayoutTests(unittest.TestCase):
    def test_the_bar_never_overlaps_the_tab_in_any_of_the_eight_combinations(self):
        for corner in compose.YT_OVERLAY_CORNERS:
            for side in compose.YT_OVERLAY_TITLE_SIDES:
                with self.subTest(corner=corner, side=side):
                    layout = compose.yt_overlay_layout(corner, side, SOURCE)
                    for name in ("tab", "source"):
                        self.assertFalse(
                            _intersects(layout["bar"], layout[name]),
                            f"{corner}/{side}：標題條壓到 {name}",
                        )

    def test_the_bar_stays_inside_the_frame_in_every_combination(self):
        width, height = compose.YT_CANVAS
        for corner in compose.YT_OVERLAY_CORNERS:
            for side in compose.YT_OVERLAY_TITLE_SIDES:
                with self.subTest(corner=corner, side=side):
                    x0, y0, x1, y1 = compose.yt_overlay_layout(corner, side, SOURCE)["bar"]
                    self.assertGreaterEqual(x0, 0)
                    self.assertGreaterEqual(y0, 0)
                    self.assertLessEqual(x1, width)
                    self.assertLessEqual(y1, height)

    def test_the_bar_is_about_fifty_five_percent_wide(self):
        x0, _, x1, _ = compose.yt_overlay_layout("tr", "left")["bar"]
        self.assertAlmostEqual((x1 - x0) / compose.YT_CANVAS[0], 0.55, places=2)

    def test_the_title_side_actually_picks_a_side(self):
        width = compose.YT_CANVAS[0]
        for side, expect_left in (("left", True), ("right", False)):
            with self.subTest(side=side):
                img = _overlay(logo_corner="tr", title_side=side)
                alpha = img.getchannel("A")
                bottom = alpha.crop((0, round(img.height * 0.6), width, img.height))
                left = sum(bottom.crop((0, 0, width // 2, bottom.height)).point(lambda v: v > 0 and 255).histogram()[255:])
                right = sum(bottom.crop((width // 2, 0, width, bottom.height)).point(lambda v: v > 0 and 255).histogram()[255:])
                if expect_left:
                    self.assertGreater(left, right * 4)
                else:
                    self.assertGreater(right, left * 4)


class OverlaySourceTextTests(unittest.TestCase):
    def _source_box(self, corner: str, side: str):
        """有無來源句的 alpha 差集，就是來源句自己畫出來的範圍。"""
        without = _overlay(logo_corner=corner, title_side=side).getchannel("A")
        with_text = _overlay(logo_corner=corner, title_side=side,
                             source_text=SOURCE).getchannel("A")
        from PIL import ImageChops
        return ImageChops.difference(with_text, without).getbbox()

    def test_a_top_logo_puts_the_source_line_below_the_tab(self):
        for corner in ("tr", "tl"):
            side = "left" if corner == "tr" else "right"   # 挑不會讓標題條移動的組合
            with self.subTest(corner=corner):
                box = self._source_box(corner, side)
                tab = compose.yt_overlay_layout(corner, side, SOURCE)["tab"]
                self.assertIsNotNone(box)
                self.assertGreaterEqual(box[1], tab[3], "來源句沒有落在標籤下方")

    def test_a_bottom_logo_puts_the_source_line_above_the_tab(self):
        for corner in ("br", "bl"):
            side = "left" if corner == "br" else "right"
            with self.subTest(corner=corner):
                box = self._source_box(corner, side)
                tab = compose.yt_overlay_layout(corner, side, SOURCE)["tab"]
                self.assertIsNotNone(box)
                self.assertLessEqual(box[3], tab[1], "來源句沒有落在標籤上方")

    def test_the_source_line_hugs_the_same_edge_as_the_logo(self):
        width = compose.YT_CANVAS[0]
        for corner, on_right in (("tr", True), ("br", True), ("tl", False), ("bl", False)):
            side = "left" if on_right else "right"
            with self.subTest(corner=corner):
                box = self._source_box(corner, side)
                centre = (box[0] + box[2]) / 2
                if on_right:
                    self.assertGreater(centre, width * 0.6)
                else:
                    self.assertLess(centre, width * 0.4)

    def test_no_source_text_means_no_source_pixels(self):
        blank = _overlay(logo_corner="tr", title_side="left", source_text="   ")
        none = _overlay(logo_corner="tr", title_side="left")
        self.assertEqual(blank.tobytes(), none.tobytes())


class OverlayLiveBadgeTests(unittest.TestCase):
    def test_the_live_badge_moves_out_of_the_way_when_the_logo_takes_the_top_left(self):
        width = compose.YT_CANVAS[0]
        for corner, badge_on_left in (("tr", True), ("br", True), ("bl", True), ("tl", False)):
            with self.subTest(corner=corner):
                img = _overlay(logo_corner=corner, title_side="left" if corner != "bl" else "right")
                strip = img.crop((0, round(img.height * 0.04), width, round(img.height * 0.16)))
                alpha = strip.getchannel("A").point(lambda v: 255 if v > 0 else 0)
                left = sum(alpha.crop((0, 0, width // 2, strip.height)).histogram()[255:])
                right = sum(alpha.crop((width // 2, 0, width, strip.height)).histogram()[255:])
                self.assertGreater(left if badge_on_left else right, 0)

    def test_turning_live_off_removes_it(self):
        on = _overlay(live=True).getchannel("A").histogram()[255]
        off = _overlay(live=False).getchannel("A").histogram()[255]
        self.assertLess(off, on)


def _intersects(a, b) -> bool:
    if b[1] >= b[3] or b[0] >= b[2]:
        return False
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


if __name__ == "__main__":
    unittest.main()
