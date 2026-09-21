"""F36：YT 整點直播創意 0 級的日期方塊與標題距離。

**2026-09-21 定案版**（取代 09-20 那版，原始檔名保留不改，免得追不到歷史）。

09-20 使用者原話：「日期方塊與標題距離可以拉近。這是因為怕字數太少，字級太大，蓋到
日期方塊，要改成自動判斷，字數太少→日期方塊現在的位置。字數多→日期方塊跟標題靠近」。
當天實作成「字級被縮小才靠近」，09-21 使用者實機驗收 **「F36 沒成功」**——真因是
整點直播的標題幾乎都 4~8 字，永遠塞得下、字級永遠不縮，那條規則從來沒被觸發過。
使用者要的「字數多」被實作成「字級小」，兩者在這個版型幾乎不重疊。

09-21 定案：先問「≥6 字要用多少」答 40px，再看 104／80／60／40 四張短標題樣張後，
<6 字也挑 40px——兩邊同一個數字，於是「字數門檻」不必存在，規則收斂成一句話：
**日期牌下緣一律離第一行標題墨水上緣 40px**。

守的紅線：
1. 短標題（字級最大）也要往下靠——這正是 09-20 那版驗收失敗的那一格。
2. 長標題（字級縮小）跟著再往下，永遠維持同一個間距。
3. 間距就是 YT_HOURLY_DATE_TAB_GAP_RATIO，不是任何反推值。
4. 只有程式自己畫標題（draw_titles=True）時才套用——AI 畫標題時量不到它實際用的
   字級，硬套是瞎猜，維持舊行為（日期牌釘在預設位置）。
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
GAP = round(H * compose.YT_HOURLY_DATE_TAB_GAP_RATIO)


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


def _font_for(line1: str, line2: str):
    margin = round(W * compose.YT_MARGIN_RATIO)
    return compose._yt_shared_title_font(
        [line1, line2], W - margin * 2,
        round(H * compose.YT_HOURLY_TITLE_SIZE_RATIO),
        round(H * compose.YT_TITLE_MIN_SIZE_RATIO),
    )


def _ink_top_for(line1: str, line2: str) -> int:
    return round(H * compose._yt_hourly_title_ink_top_ratio(
        _font_for(line1, line2), compose.YT_HOURLY_LINE1_BASELINE_RATIO,
    ))


def _rendered_tab_bottom(line1: str, line2: str) -> int:
    tab = _default_tab()
    png = compose.compose_yt_hourly_cover(
        _flat(), line1=line1, line2=line2, date_text=DATE, time_text="20:00",
    )
    img = Image.open(io.BytesIO(png))
    return _tab_red_rows(img, (tab[0] + tab[2]) // 2)[1]


class TheGapIsAlwaysTheSameTests(unittest.TestCase):
    """不分字數，日期牌下緣到標題墨水上緣永遠是 GAP。"""

    CASES = [
        ("俄國大選", "開票中"),                                  # 4／3 字，字級最大
        ("股市創新高", "台股大漲"),                               # 5／4 字，字級最大
        ("俄羅斯國會大選", "執政黨估維持主導"),                     # 7／8 字，字級最大
        ("尼泊爾洪災惡化家屬持續抗議聲浪擴大",
         "各國政府國際組織相繼表態關切呼籲救援"),                   # 17／18 字，字級縮小
    ]

    def test_every_title_length_lands_on_the_same_gap(self):
        for line1, line2 in self.CASES:
            with self.subTest(line1=line1):
                bottom = _rendered_tab_bottom(line1, line2)
                self.assertAlmostEqual(_ink_top_for(line1, line2) - (bottom + 1), GAP, delta=3)


class ShortTitlesMoveTooTests(unittest.TestCase):
    """09-20 那版驗收失敗的那一格：短標題也必須往下靠，不能原地不動。"""

    LINE1, LINE2 = "俄國大選", "開票中"

    def test_the_short_title_really_does_not_shrink_the_font(self):
        """前提檢查：這組標題字級沒被縮，才驗得到「字級沒變也會移動」。"""
        start = round(H * compose.YT_HOURLY_TITLE_SIZE_RATIO)
        self.assertEqual(_font_for(self.LINE1, self.LINE2).size, start)

    def test_the_tab_moves_down_even_at_the_largest_font(self):
        default_tab = _default_tab()
        png = compose.compose_yt_hourly_cover(
            _flat(), line1=self.LINE1, line2=self.LINE2, date_text=DATE, time_text="20:00",
        )
        img = Image.open(io.BytesIO(png))
        top, bottom = _tab_red_rows(img, (default_tab[0] + default_tab[2]) // 2)
        self.assertGreater(
            top, default_tab[1],
            "短標題的日期牌沒有往下靠——這正是 09-20 那版被驗收退回的原因",
        )
        # 牌子本身的高度不變，只是整塊平移
        self.assertAlmostEqual(bottom - top, default_tab[3] - default_tab[1], delta=2)


class LongerTitlesMoveFurtherTests(unittest.TestCase):
    """標題越長→字級越小→墨水上緣越低→日期牌跟著越往下。"""

    def test_a_longer_title_pushes_the_tab_lower_than_a_short_one(self):
        short = _rendered_tab_bottom("俄國大選", "開票中")
        long_ = _rendered_tab_bottom(
            "尼泊爾洪災惡化家屬持續抗議聲浪擴大", "各國政府國際組織相繼表態關切呼籲救援",
        )
        self.assertGreater(long_, short)


class TheGapIsAConstantNotADerivedValueTests(unittest.TestCase):
    """間距要是一個看得到、改得動的常數，不是從成品反推出來的數字。"""

    def test_the_constant_exists_and_is_forty_pixels_at_1080(self):
        self.assertAlmostEqual(round(H * compose.YT_HOURLY_DATE_TAB_GAP_RATIO), 40, delta=1)

    def test_changing_the_constant_changes_the_rendered_position(self):
        """防呆：常數被繞過（例如某天又被改回反推）的話這條會掛。"""
        original = compose.YT_HOURLY_DATE_TAB_GAP_RATIO
        baseline = _rendered_tab_bottom("俄國大選", "開票中")
        try:
            compose.YT_HOURLY_DATE_TAB_GAP_RATIO = original * 2
            widened = _rendered_tab_bottom("俄國大選", "開票中")
        finally:
            compose.YT_HOURLY_DATE_TAB_GAP_RATIO = original
        self.assertLess(widened, baseline, "把間距調大，日期牌應該往上退")


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
