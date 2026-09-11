"""整點直播：AI 畫標題時紅色日期條壓到標題（2026-09-11 使用者回報）。

根因不是日期條放錯位置，也不是標題太大。程式貼日期條用的是**固定絕對座標**
（YT_HOURLY_DATE_TOP_RATIO 起算），而 AI 版的 prompt 只說「留一條在標題第一行
**正上方**」——那個位置由模型自己決定。模型把標題畫高一點，它認定的「上方」
就跑到日期條的高度以上，程式照樣貼在絕對位置，兩者就疊在一起。

同一份 prompt 的另外兩條保留區（左上角 Logo、右上角 LIVE 章）都錨在畫面的角落，
所以從來沒撞過；只有日期這條沒有絕對錨點。修法是給它絕對座標，並明講標題第一行
的字頂不得高於某個比例。

這裡的測試把 prompt 裡的數字釘回 compose 的常數：以後誰動了日期條的位置而忘了
改 prompt，就會紅在這裡，而不是紅在使用者的成品上。
"""

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402

PROMPT = editor_formats.YT_COVER_FULL_PROMPT_HOURLY


def _reserved_band() -> tuple[float, float]:
    """prompt 宣告的保留區上下緣（佔畫面高度的比例）。"""
    match = re.search(r"from (\d+)% to (\d+)% of the frame HEIGHT", PROMPT)
    assert match, "prompt 裡找不到日期條保留區的高度範圍"
    return int(match.group(1)) / 100, int(match.group(2)) / 100


def _headline_floor() -> float:
    match = re.search(r"at or below (\d+)% of the frame height", PROMPT)
    assert match, "prompt 裡找不到標題第一行的字頂下限"
    return int(match.group(1)) / 100


class DateTabReservationTests(unittest.TestCase):
    def test_the_reserved_band_actually_covers_where_the_tab_is_pasted(self):
        """保留區必須整個包住程式真正貼上去的那塊，否則等於沒留。"""
        low, high = _reserved_band()
        tab_top = compose.YT_HOURLY_DATE_TOP_RATIO
        tab_bottom = tab_top + compose.YT_HOURLY_DATE_TAB_HEIGHT_RATIO
        self.assertLessEqual(low, tab_top, "保留區上緣比日期條還低")
        self.assertGreaterEqual(high, tab_bottom, "保留區下緣蓋不住日期條")

    def test_the_reserved_band_is_wide_enough_for_the_tab(self):
        match = re.search(r"to (\d+)% of the frame WIDTH", PROMPT)
        self.assertIsNotNone(match, "prompt 裡找不到保留區寬度")
        reserved = int(match.group(1)) / 100
        tab_right = compose.YT_MARGIN_RATIO + compose.YT_HOURLY_DATE_TAB_WIDTH_RATIO
        self.assertGreaterEqual(reserved, tab_right)

    def test_the_headline_floor_sits_below_the_reserved_band(self):
        """標題第一行的字頂要低於保留區下緣，中間還要留得下呼吸空間。"""
        _, high = _reserved_band()
        self.assertGreater(_headline_floor(), high)

    def test_the_headline_floor_matches_what_the_composite_does(self):
        """AI 版與程式壓字版要長得一樣高——不然同一個版型兩條路兩種結果。

        程式壓字版第一行的墨跡頂實測落在畫面 68.7%，prompt 要求 ≤66%，
        模型畫得略低於或等於那個位置都不會撞到日期條。
        """
        width, height = compose.YT_CANVAS
        max_w = width - round(width * compose.YT_MARGIN_RATIO) * 2
        font = compose._yt_shared_title_font(
            ["東北季風剩1天", "假日回溫"], max_w,
            round(height * compose.YT_HOURLY_TITLE_SIZE_RATIO),
            round(height * compose.YT_TITLE_MIN_SIZE_RATIO),
        )
        baseline = round(height * compose.YT_HOURLY_LINE1_BASELINE_RATIO)
        ink_top = baseline - (font.getmetrics()[0] - font.getbbox("東北季風剩1天")[1])
        self.assertGreaterEqual(ink_top / height, _headline_floor() - 0.05)

    def test_the_old_relative_wording_is_gone(self):
        """「directly above headline line 1」是相對位置，正是這次事故的根源。"""
        self.assertNotIn("directly above headline line 1", PROMPT)

    def test_the_composite_path_never_overlaps(self):
        """程式壓字那條路本來就沒事，順便釘住，改 baseline 時不要弄壞。"""
        _, height = compose.YT_CANVAS
        tab_bottom = round(height * compose.YT_HOURLY_DATE_TOP_RATIO) + round(
            height * compose.YT_HOURLY_DATE_TAB_HEIGHT_RATIO
        )
        width = compose.YT_CANVAS[0]
        max_w = width - round(width * compose.YT_MARGIN_RATIO) * 2
        font = compose._yt_shared_title_font(
            ["東北季風剩1天", "假日回溫"], max_w,
            round(height * compose.YT_HOURLY_TITLE_SIZE_RATIO),
            round(height * compose.YT_TITLE_MIN_SIZE_RATIO),
        )
        baseline = round(height * compose.YT_HOURLY_LINE1_BASELINE_RATIO)
        ink_top = baseline - (font.getmetrics()[0] - font.getbbox("東北季風剩1天")[1])
        self.assertGreater(ink_top, tab_bottom, "程式壓字版的標題撞到日期條")


if __name__ == "__main__":
    unittest.main()
