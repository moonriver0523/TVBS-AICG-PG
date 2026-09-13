"""程式壓的日期標／時間標一律粗體（2026-09-13 使用者：「現行都偏細」）。

涵蓋三處（全部的程式壓字日期／時間）：
  * 十點封面薄標頭帶的日期（compose._draw_cover_header）
  * AI 標頭補帶後貼上的日期（compose.paste_cover_header_right，另有黑外框）
  * YT 國內外直播的日期白條、YT 整點的日期紅條與整點時間白帶

字型本來就是台北黑體 Bold，沒有更粗的字重，所以用同色描邊把字幹撐開。描邊是對稱
長出來的，會把字撐寬也撐高，因此同時釘住「不准爆出牌子」。
"""
import io
import os
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402

W, H = 1920, 1080
DATE = "2026/09/14"


def _flat(colour=(60, 70, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (W, H), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _ink(img: Image.Image, box, pred):
    """box 內符合 pred 的像素座標。"""
    px = img.convert("RGB").load()
    return [
        (x, y)
        for y in range(box[1], box[3])
        for x in range(box[0], box[2])
        if pred(px[x, y])
    ]


_WHITE = lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200  # noqa: E731


class BoldHelperTests(unittest.TestCase):
    def test_the_stroke_scales_with_the_type_size(self):
        """固定像素寬的描邊會把小字糊成一團，所以按字級等比例。"""
        self.assertLess(
            compose._bold_stroke(compose._font(24)),
            compose._bold_stroke(compose._font(80)),
        )
        self.assertGreaterEqual(compose._bold_stroke(compose._font(12)), 1)

    def test_the_fit_counts_the_stroke_it_is_about_to_add(self):
        """不算進去就會爆框：字級是照剛好塞滿量的，描邊再往外撐 2×stroke。"""
        text = "2026/09/14"
        plain = compose._fit_font(text, 440, 80, 30)
        bold = compose._fit_font_bold(text, 440, 80, 30)
        self.assertLessEqual(bold.size, plain.size)
        self.assertLessEqual(
            bold.getbbox(text)[2] + 2 * compose._bold_stroke(bold), 440
        )

    def test_vertical_centring_uses_the_ink_not_the_font_metrics(self):
        """數字沒有降部，照 ascent／descent 置中會整片偏下（實測上 20 下 4）。"""
        font = compose._font(80)
        # 日期的斜線還會伸到基線以下，墨跡整片偏低 → 要往上補（負值）
        self.assertLess(compose._ink_centre_shift(font, DATE), 0)
        # 中文字本來就填滿度量框，兩種置中法幾乎沒有差
        self.assertEqual(compose._ink_centre_shift(font, "壞"), 0)


class HourlyDateAndTimeTests(unittest.TestCase):
    def setUp(self):
        png = compose.compose_yt_hourly_cover(
            _flat(), line1="東北季風", line2="今起增強",
            date_text=DATE, time_text="20:00",
        )
        self.img = Image.open(io.BytesIO(png))

    def _tab(self):
        b = compose.YT_HOURLY_DATE_TAB_BOX
        return (round(W * b[0]), round(H * b[1]), round(W * b[2]), round(H * b[3]))

    def test_the_date_is_visibly_bolder_than_a_hairline(self):
        """字幹佔紅條的比例：細體版實測 0.184，粗體後 0.35。取 0.27 當門檻。"""
        tab = self._tab()
        area = (tab[2] - tab[0]) * (tab[3] - tab[1])
        self.assertGreater(len(_ink(self.img, tab, _WHITE)) / area, 0.27)

    def test_the_bold_date_stays_inside_the_red_tab(self):
        """2026-09-13 第一版沒改垂直置中，字底壓在紅條下緣上（20 個像素）。"""
        tab = self._tab()
        ring = (tab[0] - 4, tab[1] - 4, tab[2] + 4, tab[3] + 4)
        outside = [p for p in _ink(self.img, ring, _WHITE)
                   if not (tab[0] <= p[0] < tab[2] and tab[1] <= p[1] < tab[3])]
        self.assertEqual(outside, [])

    def test_the_hour_band_is_bold_too(self):
        """整點時間帶是白底紅字，同樣要粗。"""
        badge_w = round(W * compose.YT_HOURLY_BADGE_WIDTH_RATIO)
        x0 = W - round(W * compose.YT_MARGIN_RATIO) - badge_w
        band = (x0, round(H * 0.10), x0 + badge_w, round(H * 0.22))
        red = [p for p in _ink(self.img, band, lambda c: c[0] > 150 and c[1] < 90 and c[2] < 90)]
        self.assertGreater(len(red), 0)


class OtherLayoutsAreBoldToo(unittest.TestCase):
    def test_the_live_cover_date_tab(self):
        png = compose.compose_yt_cover(
            _flat(), line1="挪威國王哈拉德辭世", line2="開放公眾瞻仰遺容", date_text=DATE)
        img = Image.open(io.BytesIO(png))
        box = (round(W * 0.02), round(H * 0.19), round(W * 0.26), round(H * 0.33))
        red = _ink(img, box, lambda c: c[0] > 150 and c[1] < 90 and c[2] < 90)
        area = (box[2] - box[0]) * (box[3] - box[1])
        # 細體版實測 0.309，粗體後 0.394（白條本身也算進紅字以外的面積）
        self.assertGreater(len(red) / area, 0.35)

    def test_the_ten_cover_header_date(self):
        png = compose.compose_ten_cover(
            _flat(), _flat((90, 70, 60)),
            title_left="東北季風 今起增強", title_right="全臺有雨 慎防強風", date_text=DATE)
        img = Image.open(io.BytesIO(png))
        box = (round(W * 0.60), 0, round(W * 0.86), round(H * 0.09))
        area = (box[2] - box[0]) * (box[3] - box[1])
        # 細體版實測 0.068，粗體後 0.125
        self.assertGreater(len(_ink(img, box, _WHITE)) / area, 0.10)


if __name__ == "__main__":
    unittest.main()
