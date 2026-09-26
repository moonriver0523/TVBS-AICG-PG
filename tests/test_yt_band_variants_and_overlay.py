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
from unittest import mock

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
        """2026-09-08 裁決：第 3 位置（第二行）＋上緣羽化。
        2026-09-09 使用者「羽化再多一點」：起點跟著第一行基線走（往上讓 LEAD 那一段），
        羽化 0.0365 → 0.052。寫成關係式而不是兩個裸數字——行距一動就要一起動。"""
        self.assertAlmostEqual(
            compose.YT_BAND_TOP_RATIO,
            compose.YT_LINE1_BASELINE_RATIO - compose.YT_BAND_LEAD_RATIO,
        )
        self.assertEqual(compose.YT_BAND_FADE_RATIO, 0.052)
        self.assertGreater(compose.YT_BAND_FADE_RATIO, 0.0365, "使用者要的是更長的斜坡")


class BandPlacementTests(unittest.TestCase):
    def test_the_band_does_not_tint_the_first_line_even_though_the_ramp_starts_higher(self):
        """2026-09-09：斜坡改成比第一行基線再高 LEAD 一段起跑，才有地方長羽化。

        會這樣做是因為 smoothstep 在 t 很小的時候幾乎是 0，那一段藏在白字腳下看不出來。
        「看不出來」不能用講的——這裡直接量：白字墨水那一帶的濃度要低到幾乎為零，
        全濃度處仍然壓在黃字墨水上緣之上（下一個測試）。"""
        self.assertLess(compose.YT_BAND_TOP_RATIO, compose.YT_LINE1_BASELINE_RATIO)
        span = compose.YT_LINE1_BASELINE_RATIO - compose.YT_BAND_TOP_RATIO
        self.assertLessEqual(span, 0.025, "起跑點拉太高，白字就真的坐進框裡了")
        ink_top = compose._yt_title_ink_top_ratio(compose.YT_LINE1_BASELINE_RATIO)
        t = max(0.0, (ink_top - compose.YT_BAND_TOP_RATIO) / compose.YT_BAND_FADE_RATIO)
        self.assertLess(t * t * (3 - 2 * t), 0.08, "白字墨水上緣已經有明顯底色")

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

    def test_the_first_line_is_always_the_left_column(self):
        """B111（2026-09-26 使用者裁決）：第一行一律在左欄、第二行在右欄——貼左緣時
        第一行是外側，貼右緣時是內側。兩欄都是深藍，像素分不出誰是誰，只能靠幾何驗。"""
        for side in compose.VSTRIP_SIDES:
            with self.subTest(side=side):
                layout = self._layout(title_side=side)
                self.assertLess(layout["main"][0], layout["sub"][0])
                self.assertEqual(layout["main"][0], layout["box"][0])
                self.assertEqual(layout["sub"][2], layout["box"][2])

    def test_the_two_columns_are_the_same_width(self):
        """同字級就得同寬，不然窄的那欄字會被 0.94 欄寬的上限壓小。

        2026-09-20（B80）色框寬度改成官方實測值（153px／154px），不是湊出來的偶數，
        對半分無法整除，容許 1px 差——比對半分本身的捨入誤差還小，看不出來。
        """
        layout = self._layout()
        main_w = layout["main"][2] - layout["main"][0]
        sub_w = layout["sub"][2] - layout["sub"][0]
        self.assertLessEqual(abs(main_w - sub_w), 1)

    def test_the_two_columns_touch_and_form_one_box(self):
        """同一個色框不拆開：兩欄之間沒有縫，左右緣與底緣都貼齊色框。

        2026-09-20 使用者看過樣張後要求「字不要黏在 LIVE 章下面」，所以**欄頂刻意比
        色框頂端低一個上內距**（`VSTRIP_TEXT_TOP_PAD_RATIO`）。舊斷言 `box == 兩欄聯集`
        把四個邊一起比，現在頂邊本來就該不一樣，改成分開驗：左右緣與底緣仍然嚴格貼齊
        色框（這才是「同一個色框不拆開」要守的），頂邊則驗「確實往下讓了，而且讓的量
        就是那個內距」——順便擋住有人把內距改成 0 又把這個 bug 放回來。
        """
        for side in ("left", "right"):
            with self.subTest(side=side):
                layout = self._layout(title_side=side)
                inner, outer = sorted((layout["main"], layout["sub"]), key=lambda r: r[0])
                self.assertEqual(inner[2], outer[0], "兩欄之間有縫")
                box = layout["box"]
                self.assertEqual((inner[0], outer[2]), (box[0], box[2]), "兩欄沒有填滿色框寬度")
                self.assertEqual(inner[3], box[3], "欄底沒有貼齊色框底緣")
                pad = round(compose.YT_CANVAS[1] * compose.VSTRIP_TEXT_TOP_PAD_RATIO)
                self.assertGreater(pad, 0, "上內距被改成 0，字會黏回 LIVE 章")
                self.assertEqual(inner[1], box[1] + pad, "欄頂讓開的量不等於上內距")

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

    def test_the_geometry_matches_the_official_artwork(self):
        """2026-09-20（B80）：色框幾何改成官方底圖的常數比例，不再由標題格數反推。
        上緣／高度是官方口頭量測的數字（171/1063、485/1063）；左緣／寬度官方口頭
        給的是「LIVE 章與色框合在一起」的外框（31/189），實測色框本身其實內縮、
        更窄（48/153，見 compose.py VSTRIP_BG_BOX_LEFT_RATIO 的註解），這裡用實測值，
        不是官方口頭數字。容許 0.003 的捨入誤差。"""
        width, height = compose.YT_CANVAS
        layout = self._layout(title_side="left")
        box = layout["box"]
        self.assertAlmostEqual(box[0] / width, 48 / 1914, delta=0.003)
        self.assertAlmostEqual(box[1] / height, 171 / 1063, delta=0.003)
        self.assertAlmostEqual((box[2] - box[0]) / width, 153 / 1914, delta=0.003)
        self.assertAlmostEqual((box[3] - box[1]) / height, 485 / 1063, delta=0.003)
        # 色框長度是常數了，跟標題格數無關——短標題與長標題量出來要一樣。
        short = self._layout(title_side="left", main_title="川普宣布關稅", sub_title="")
        self.assertEqual(short["box"], box)

    def test_the_labelled_geometry_matches_the_official_artwork(self):
        """同上，有小標版的色框實測左緣／寬度是 37/154，不是官方口頭給的合體框
        19/194（那個是 LIVE 章＋白底小標的外框，見 compose.py 註解）。"""
        width, height = compose.YT_CANVAS
        layout = self._layout(title_side="left", variant="original_audio")
        box = layout["box"]
        self.assertAlmostEqual(box[0] / width, 37 / 1905, delta=0.003)
        self.assertAlmostEqual(box[1] / height, 213 / 1070, delta=0.003)
        self.assertAlmostEqual((box[2] - box[0]) / width, 154 / 1905, delta=0.003)
        self.assertAlmostEqual((box[3] - box[1]) / height, 489 / 1070, delta=0.003)

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

    def test_the_box_has_zero_gap_below_the_live_badge_and_the_label(self):
        """2026-09-20（B46 隨 B80 一起改）：舊版留一道 VSTRIP_TOP_GAP_RATIO 的安全縫，
        是因為色框曾經貼著 LIVE 章往下長、字級一大就會吃到章。改用官方底圖之後，
        LIVE 章／小標／色框是同一份美術的三個固定區塊，天生貼合——沒勾小標時 LIVE
        與標題要黏合，正是 B46 的裁決；不再留任何安全縫。"""
        for variant in compose.VSTRIP_VARIANTS:
            with self.subTest(variant=variant):
                layout = self._layout(variant=variant)
                if variant in compose.VSTRIP_VARIANT_LABELS:
                    self.assertEqual(layout["live"][3], layout["label"][1], "LIVE 章與小標之間有縫")
                    self.assertEqual(layout["label"][3], layout["box"][1], "小標與色框之間有縫")
                else:
                    self.assertEqual(layout["live"][3], layout["box"][1], "LIVE 章與色框之間有縫")

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

    def test_the_longest_allowed_pair_still_fits_above_the_font_floor(self):
        """字數上限（12／14 格）跟字級下限（0.030h＝32px@1080）是兩條獨立規則，2026-09-20
        使用者裁決色框長度變常數之後，兩者剛好卡在邊界上——副標 14 格是最擠的情況，
        算出來的字級四捨五入正好等於下限，一點餘裕都沒有（見 compose.py 模組開頭
        VSTRIP_MIN_FONT_RATIO 的註解），所以直接驗 cell_size，不要驗會被浮點誤差
        坑到的 column_height/格數。"""
        layout = compose.yt_vertical_layout(
            main_title="一" * compose.VSTRIP_MAIN_MAX_CELLS,
            sub_title="一" * compose.VSTRIP_SUB_MAX_CELLS,
        )
        floor = round(compose.YT_CANVAS[1] * compose.VSTRIP_MIN_FONT_RATIO)
        self.assertGreaterEqual(layout["cell_size"], floor)

    def test_one_cell_more_than_the_floor_allows_is_refused(self):
        """規格上限本身（VSTRIP_SUB_MAX_CELLS=14）已經卡在字級下限上——這裡直接餵一個
        超過上限的格數（繞過格數檢查用內部函式），確認擠爆下限時是 ComposeError，
        不是默默吐一個比下限還小的字。"""
        oversized = "一" * (compose.VSTRIP_SUB_MAX_CELLS + 4)
        with mock.patch.object(compose, "VSTRIP_SUB_MAX_CELLS", compose.VSTRIP_SUB_MAX_CELLS + 4):
            with self.assertRaises(compose.ComposeError):
                compose.yt_vertical_layout(main_title=MAIN, sub_title=oversized)


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

    def test_the_box_has_no_transparent_gap_across_the_seam(self):
        """同一個色框：跨過兩欄交界的那一列不准有透明縫。

        2026-09-20（B80）改用官方去背 PNG 當固定層之後，兩欄交界本來就有官方美術
        自己的一道亮邊（漸層方向對接處），不再是程式畫的單色連續漸層——「顏色連續
        不超過 3」那條舊斷言驗的是程式畫圖的性質，用官方素材後不成立，改良只驗
        「沒有透明縫」，這才是這條測試原本要守的紅線（B46/B80 都不准開天窗）。
        取樣列改在色框垂直中點：官方 PNG 是真實美術，最外緣本來就會有 1～3px 的
        反鋸齒淡出（縮放貼上時 LANCZOS 又會再柔化一點），那是合理的邊緣，不是縫；
        真正該驗「沒有縫」的地方是兩欄交界，跟上下邊緣無關，中點最不會被邊緣汙染。
        """
        img = _vstrip()
        layout = compose.yt_vertical_layout(main_title=MAIN, sub_title=SUB)
        x0, y0, x1, y1 = layout["box"]
        y = (y0 + y1) // 2
        row = [img.getpixel((x, y)) for x in range(x0, x1)]
        # 門檻用 250 不是 255：官方 PNG 縮放貼上時 LANCZOS 在色框最右緣一行會留一兩個
        # alpha≈253 的像素（反鋸齒捨入），跟真的開了一條透明縫（alpha 接近 0）差得遠。
        self.assertTrue(all(px[3] >= 250 for px in row), "色框裡有透明縫")

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
        # 2026-09-20（B80）改用固定寬的官方色框之後，欄寬不再由字級反推，比字本身
        # 寬得多——「墨水寬度要佔欄寬一半」這個舊門檻已經量不出「橫著寫」，改驗
        # 墨水本身的長寬比：橫著寫的「30」一定比高還寬，直著拆成兩格就會反過來。
        self.assertGreater(box[2] - box[0], box[3] - box[1],
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
