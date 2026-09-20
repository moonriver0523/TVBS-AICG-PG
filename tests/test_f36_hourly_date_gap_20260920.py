"""F36（2026-09-20 使用者裁決）：YT 整點直播創意 0 級的日期方塊與標題距離。

使用者原話：「日期方塊與標題距離可以拉近。這是因為怕字數太少，字級太大，蓋到日期
方塊，要改成自動判斷，字數太少→日期方塊現在的位置。字數多→日期方塊跟標題靠近」。

守的紅線：
1. **字數少（字級被放到起始／最大字級）時，日期牌位置一個像素都不准變**——這是
   使用者已經核可、正在播出的樣子，`test_date_time_bold_20260913.py` 釘死的短標題
   案例必須繼續byte-identical，這裡另外用一次「起始字級」的顯式檢查覆蓋同一件事。
2. **字數多（字級縮小）時，日期牌只准往下靠近標題，不准往上移**——GAP 是拿「起始
   字級時的位置」反推出來的，長標題的新位置理論上不可能小於預設位置。
3. **只有程式自己畫標題（draw_titles=True）時才套用這條規則**——AI 畫標題
   （draw_titles=False）時我們量不到 AI 實際畫的字級，硬套會是瞎猜，維持舊行為
   （日期牌釘在預設位置）。
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

W, H = compose.YT_CANVAS
DATE = "2026/09/20"


def _flat(colour=(60, 70, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (W, H), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _default_tab():
    box = compose.YT_HOURLY_DATE_TAB_BOX
    return (round(W * box[0]), round(H * box[1]), round(W * box[2]), round(H * box[3]))


def _tab_red_rows(img: Image.Image, x: int) -> tuple[int, int]:
    """沿 x 這一豎列掃出紅色日期牌實際佔用的 (top, bottom)，用來反推它被貼在哪裡。"""
    rows = [y for y in range(H) if img.getpixel((x, y))[0] > 150 and img.getpixel((x, y))[1] < 80]
    return min(rows), max(rows)


class ShortTitleKeepsTheDefaultPositionTests(unittest.TestCase):
    """字數少：字級會被放到起始／最大字級，日期牌維持現在的位置。"""

    def test_a_title_that_fits_at_the_starting_size_does_not_move_the_tab(self):
        tab = _default_tab()
        cx = (tab[0] + tab[2]) // 2
        png = compose.compose_yt_hourly_cover(
            _flat(), line1="股市創新高", line2="台股大漲", date_text=DATE, time_text="20:00",
        )
        img = Image.open(io.BytesIO(png))
        self.assertEqual(_tab_red_rows(img, cx), (tab[1], tab[3]))

    def test_the_font_actually_used_is_the_starting_size(self):
        """前提檢查：上面那組標題真的沒有被縮字級，不然這條測試沒驗到東西。"""
        width, height = compose.YT_CANVAS
        margin = round(width * compose.YT_MARGIN_RATIO)
        max_w = width - margin * 2
        start = round(height * compose.YT_HOURLY_TITLE_SIZE_RATIO)
        smallest = round(height * compose.YT_TITLE_MIN_SIZE_RATIO)
        font = compose._yt_shared_title_font(["股市創新高", "台股大漲"], max_w, start, smallest)
        self.assertEqual(font.size, start)


class LongTitleMovesTheTabCloserTests(unittest.TestCase):
    """字數多：字級縮小，日期牌跟標題靠近——只准往下移，不准往上。"""

    LINE1 = "尼泊爾洪災惡化家屬持續抗議聲浪擴大"
    LINE2 = "各國政府國際組織相繼表態關切呼籲救援"

    def test_a_long_title_shrinks_the_font_below_the_starting_size(self):
        width, height = compose.YT_CANVAS
        margin = round(width * compose.YT_MARGIN_RATIO)
        max_w = width - margin * 2
        start = round(height * compose.YT_HOURLY_TITLE_SIZE_RATIO)
        smallest = round(height * compose.YT_TITLE_MIN_SIZE_RATIO)
        font = compose._yt_shared_title_font([self.LINE1, self.LINE2], max_w, start, smallest)
        self.assertLess(font.size, start, "這組標題要真的觸發縮字級，不然驗不到位移")

    def test_the_tab_moves_down_towards_the_title_not_up(self):
        default_tab = _default_tab()
        cx = (default_tab[0] + default_tab[2]) // 2
        png = compose.compose_yt_hourly_cover(
            _flat(), line1=self.LINE1, line2=self.LINE2, date_text=DATE, time_text="20:00",
        )
        img = Image.open(io.BytesIO(png))
        top, bottom = _tab_red_rows(img, cx)
        self.assertGreater(top, default_tab[1], "字級縮小了，日期牌卻沒有跟著往下靠近")
        # 牌子本身的高度不變，只是整塊平移
        self.assertAlmostEqual(bottom - top, default_tab[3] - default_tab[1], delta=2)

    def test_the_tab_still_sits_above_the_title_ink_with_the_same_gap_as_the_default(self):
        """GAP 是拿「起始字級時的位置」反推出來的：長標題位移後，日期牌下緣到標題
        墨水上緣的距離要跟預設位置那組幾乎一樣（不是縮到貼在一起，也不是還留著
        沒動過的大縫）。"""
        default_tab = _default_tab()
        max_ink_top = round(H * compose._yt_hourly_title_ink_top_ratio(
            compose._font(round(H * compose.YT_HOURLY_TITLE_SIZE_RATIO)),
            compose.YT_HOURLY_LINE1_BASELINE_RATIO,
        ))
        default_gap = max_ink_top - default_tab[3]

        width = compose.YT_CANVAS[0]
        margin = round(width * compose.YT_MARGIN_RATIO)
        max_w = width - margin * 2
        start = round(H * compose.YT_HOURLY_TITLE_SIZE_RATIO)
        smallest = round(H * compose.YT_TITLE_MIN_SIZE_RATIO)
        font = compose._yt_shared_title_font([self.LINE1, self.LINE2], max_w, start, smallest)
        ink_top = round(H * compose._yt_hourly_title_ink_top_ratio(font, compose.YT_HOURLY_LINE1_BASELINE_RATIO))

        cx = (default_tab[0] + default_tab[2]) // 2
        png = compose.compose_yt_hourly_cover(
            _flat(), line1=self.LINE1, line2=self.LINE2, date_text=DATE, time_text="20:00",
        )
        img = Image.open(io.BytesIO(png))
        _, bottom = _tab_red_rows(img, cx)
        self.assertAlmostEqual((ink_top - 1) - bottom, default_gap, delta=3)


class AiDrawnTitlesKeepTheOldFixedBehaviourTests(unittest.TestCase):
    """draw_titles=False（AI 畫標題）：量不到 AI 實際畫的字級，維持舊的固定位置。"""

    def test_the_tab_stays_at_the_default_position_when_titles_are_ai_drawn(self):
        tab = _default_tab()
        cx = (tab[0] + tab[2]) // 2
        png = compose.compose_yt_hourly_cover(
            _flat(), line1="尼泊爾洪災惡化家屬持續抗議聲浪擴大",
            line2="各國政府國際組織相繼表態關切呼籲救援",
            date_text=DATE, time_text="20:00", draw_titles=False,
        )
        img = Image.open(io.BytesIO(png))
        self.assertEqual(_tab_red_rows(img, cx), (tab[1], tab[3]))


if __name__ == "__main__":
    unittest.main()
