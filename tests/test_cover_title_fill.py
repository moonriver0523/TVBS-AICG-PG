"""雙切標題：拆行到夠短、兩格同字級、配色依段落（2026-09-08 使用者兩次回報）。

第一次：「字太小、只有白黃兩行沒有紅字」→ 版位 0.84→0.90、補字數拆行規則。
第二次（看了正式站成品）：「兩邊字不一樣大」→ 雙切放棄逐行各自撐滿，改成兩格同一字級；
拆行門檻降到 7 字、上限放寬到 4 行（拆得夠短，共同字級才撐得起來）；顏色改成**依段落**
（第 1 段白、第 2 段黃、第 3 段紅），拆出來的行繼承該段顏色。

守的紅線：
1. **拆行只切不改字。** 拆完接回去必須等於拆之前接起來的字串。
2. **兩格所有行同一字級。**
3. **顏色跟著段落走，不是跟著行序。** 連續兩行同色是正常的。
4. **滿版不套雙切那套。** 它整寬置中、逐行各自撐滿、上限仍是 3 行。
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

# 使用者實際回報的兩則
LEFT = "澳洲擬立新法 民眾可關閉社群媒體演算法"
RIGHT = "菲律賓前眾議長涉貪被捕 與總統小馬可仕為表兄弟"
SHORT = "勞保撥補 上看1300億"
WHITE, YELLOW, RED = compose.COVER_TITLE_LINE_COLOURS


def _png(size=(640, 640), colour=(30, 60, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


class SplitRuleTests(unittest.TestCase):
    def test_reported_pair_splits_the_way_the_user_asked_for(self):
        self.assertEqual(
            compose.cover_title_line_pairs(LEFT),
            [("澳洲擬立新法", 0), ("民眾可關閉社", 1), ("群媒體演算法", 1)],
        )
        self.assertEqual(
            compose.cover_title_line_pairs(RIGHT),
            [("菲律賓前眾", 0), ("議長涉貪被捕", 0), ("與總統小馬", 1), ("可仕為表兄弟", 1)],
        )

    def test_split_never_changes_a_character(self):
        for title in (LEFT, RIGHT, SHORT):
            with self.subTest(title=title):
                lines = compose.cover_title_lines(title)
                self.assertEqual("".join(lines), title.replace(" ", ""))

    def test_short_title_stays_two_lines(self):
        self.assertEqual(compose.cover_title_lines(SHORT), ["勞保撥補", "上看1300億"])

    def test_split_allows_four_lines_full_width_only_three(self):
        self.assertEqual(compose.COVER_MAX_TITLE_LINES_SPLIT, 4)
        self.assertEqual(compose.COVER_MAX_TITLE_LINES, 3)
        self.assertEqual(len(compose.cover_title_line_pairs(RIGHT)), 4)
        self.assertLessEqual(len(compose.cover_title_line_pairs(RIGHT, full_width=True)), 3)

    def test_fill_threshold_is_seven_characters(self):
        self.assertEqual(compose.COVER_TITLE_FILL_MIN_CHARS, 7)
        keep = "字" * compose.COVER_TITLE_FILL_MIN_CHARS
        cut = "字" * (compose.COVER_TITLE_FILL_MIN_CHARS + 1)
        self.assertEqual(compose._fill_pairs([("短", 0), (keep, 1)], 4), [("短", 0), (keep, 1)])
        self.assertEqual(len(compose._fill_pairs([("短", 0), (cut, 1)], 4)), 3)

    def test_split_lines_inherit_their_segment_colour_index(self):
        """拆出來的兩行都繼承原段落的索引——顏色是段落的屬性，不是行的。"""
        pairs = compose._fill_pairs([("一二三四五六七八九十", 1)], 4)
        self.assertGreater(len(pairs), 1)
        self.assertTrue(all(seg == 1 for _, seg in pairs))


class SharedSizeTests(unittest.TestCase):
    def test_both_panels_get_one_common_size(self):
        panel_w = compose.cover_title_panel_width(False)
        left = compose.cover_panel_title_size(compose.cover_title_line_pairs(LEFT), panel_w)
        right = compose.cover_panel_title_size(compose.cover_title_line_pairs(RIGHT), panel_w)
        self.assertEqual(left, right)

    def test_a_long_line_drags_its_own_panel_size_down(self):
        """沒有拆行的話共同字級會被長行拖垮——這正是要拆到 7 字以內的理由。"""
        panel_w = compose.cover_title_panel_width(False)
        short = compose.cover_panel_title_size([("菲律賓前眾", 0)], panel_w)
        long = compose.cover_panel_title_size([("菲律賓前眾議長涉貪被捕", 0)], panel_w)
        self.assertGreater(short, long)

    def test_vertical_cap_keeps_four_lines_under_the_header_band(self):
        height = compose.COVER_CANVAS[1]
        size = compose._cover_title_vertical_cap(4, 10_000)
        top = (height - round(height * compose.COVER_TITLE_BOTTOM_RATIO)) - round(size * compose.COVER_TITLE_LINE_GAP) * 3 - size
        self.assertGreaterEqual(top, round(height * compose.COVER_HEADER_RATIO))

    def test_spread_constant_is_gone(self):
        """逐行不同字級的做法退場，常數不該還留著讓人以為它有效。"""
        self.assertFalse(hasattr(compose, "COVER_TITLE_LINE_SIZE_SPREAD"))


class RenderedTests(unittest.TestCase):
    def _cover(self, **kw):
        defaults = dict(title_left=LEFT, title_right=RIGHT, date_text="2026/09/08")
        defaults.update(kw)
        out = compose.compose_ten_cover(_png(colour=(200, 30, 30)), _png(colour=(30, 30, 200)), **defaults)
        return Image.open(io.BytesIO(out)).convert("RGB")

    def _colours(self, img, box):
        raw = img.crop(box).tobytes()
        return set(zip(raw[0::3], raw[1::3], raw[2::3]))

    def test_two_segment_titles_are_white_and_yellow_with_no_red(self):
        img = self._cover()
        w, h = img.size
        for name, box in (("左格", (0, round(h * 0.5), w // 2 - 80, h - round(h * 0.06))),
                          ("右格", (w // 2 + 80, round(h * 0.5), w, h - round(h * 0.06)))):
            with self.subTest(panel=name):
                colours = self._colours(img, box)
                self.assertIn(WHITE, colours)
                self.assertIn(YELLOW, colours)
                self.assertNotIn(RED, colours)   # 只有兩段，沒有第三段就沒有紅字

    def test_three_segment_title_still_gets_red(self):
        """紅字靠消化端一律 3 段（已上線）；有第三段就有紅字。"""
        img = self._cover(title_left="尼泊爾災區 無人機空拍 滅村慘況", title_right="台南易淹水 成氣候衝擊區")
        w, h = img.size
        self.assertIn(RED, self._colours(img, (0, round(h * 0.5), w // 2 - 80, h - round(h * 0.06))))


if __name__ == "__main__":
    unittest.main()
