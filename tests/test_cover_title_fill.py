"""雙切標題「補到 3 行」與版位放寬（2026-09-08 使用者回報：字太小、只有白黃兩行沒有紅字）。

守的紅線：
1. **補行只切不改字。** 補完接回去必須等於補之前接起來的字串。
2. **滿版不套這條規則。** 滿版整寬置中，一行塞得下就不該硬拆。
3. **合成版與 AI 版共用同一份行。** `cover_title_lines`（AI 版組 prompt 用）與
   `_draw_cover_title`（合成版）都要走同一支 `_fill_cover_title_lines`，
   不然同一個標題在兩種模式下斷句又會不一樣。
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

# 使用者實際回報的那一則
REPORTED = "澳洲擬立新法 民眾可關閉社群媒體演算法"
SHORT = "勞保撥補 上看1300億"


def _png(size=(640, 640), colour=(30, 60, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


class FillRuleTests(unittest.TestCase):
    def test_long_line_is_split_until_three_lines(self):
        filled = compose._fill_cover_title_lines(["勞保撥補", "上看1300億元明年上路"])
        self.assertEqual(len(filled), compose.COVER_MAX_TITLE_LINES)
        self.assertEqual("".join(filled), "勞保撥補上看1300億元明年上路")

    def test_short_lines_are_left_alone(self):
        self.assertEqual(compose._fill_cover_title_lines(["勞保撥補", "上看1300億"]), ["勞保撥補", "上看1300億"])

    def test_threshold_is_the_named_constant(self):
        self.assertEqual(compose.COVER_TITLE_FILL_MIN_CHARS, 9)
        just_under = "字" * (compose.COVER_TITLE_FILL_MIN_CHARS - 1)
        just_over = "字" * compose.COVER_TITLE_FILL_MIN_CHARS
        self.assertEqual(compose._fill_cover_title_lines(["短", just_under]), ["短", just_under])
        self.assertEqual(len(compose._fill_cover_title_lines(["短", just_over])), 3)

    def test_already_three_lines_are_untouched(self):
        lines = ["一二三四五六七八九", "甲乙丙丁戊己庚辛壬", "子丑寅卯辰巳午未申"]
        self.assertEqual(compose._fill_cover_title_lines(lines), lines)


class CoverTitleLinesTests(unittest.TestCase):
    def test_reported_title_renders_three_lines(self):
        lines = compose.cover_title_lines(REPORTED)
        self.assertEqual(len(lines), 3)
        self.assertEqual("".join(lines), REPORTED.replace(" ", ""))

    def test_short_title_stays_two_lines(self):
        self.assertEqual(compose.cover_title_lines(SHORT), ["勞保撥補", "上看1300億"])

    def test_full_width_does_not_get_the_fill_rule(self):
        """滿版：兩行都塞得進整寬時維持兩行（雙切才補到 3 行）。"""
        panel_w = compose.cover_title_panel_width(True)
        max_w, size, _ = compose._cover_title_metrics(panel_w, True)
        font = compose._font(size)
        # 每行都塞得進整寬、且長度過了補行門檻——雙切會補、滿版不補
        line = "一二三四五六七八九"
        self.assertLessEqual(font.getbbox(line)[2], max_w)
        self.assertEqual(compose.cover_title_lines(f"{line} {line}", full_width=True), [line, line])


class TitleWidthTests(unittest.TestCase):
    def test_panel_width_ratio_is_widened(self):
        self.assertEqual(compose.COVER_TITLE_WIDTH_RATIO, 0.90)
        panel_w = compose.cover_title_panel_width(False)
        max_w, _, _ = compose._cover_title_metrics(panel_w, False)
        self.assertEqual(max_w, round(panel_w * 0.90))

    def test_wider_panel_gives_a_bigger_font_for_a_line_that_has_to_shrink(self):
        """放寬版位的實際效果：塞不進起始字級的行，縮完的字級比 0.84 時大。"""
        panel_w = compose.cover_title_panel_width(False)
        max_w, size, min_size = compose._cover_title_metrics(panel_w, False)
        old_max_w = round(panel_w * 0.84)
        line = "澳洲擬立新法民"        # 7 字：起始字級塞不進，要縮
        self.assertGreater(
            compose._fit_font(line, max_w, size, min_size).size,
            compose._fit_font(line, old_max_w, size, min_size).size,
        )

    def test_line_size_spread_is_widened(self):
        self.assertEqual(compose.COVER_TITLE_LINE_SIZE_SPREAD, 1.5)


class RenderedTitleTests(unittest.TestCase):
    def test_reported_title_draws_a_red_third_line(self):
        out = compose.compose_ten_cover(
            _png(colour=(200, 30, 30)), _png(colour=(30, 30, 200)),
            title_left=REPORTED, title_right="台南易淹水 成氣候衝擊區", date_text="2026/09/08",
        )
        img = Image.open(io.BytesIO(out)).convert("RGB")
        w, h = img.size
        region = img.crop((0, round(h * 0.55), w // 2 - 80, h - round(h * 0.06)))
        raw = region.tobytes()
        colours = set(zip(raw[0::3], raw[1::3], raw[2::3]))
        self.assertIn(compose.COVER_TITLE_LINE_COLOURS[2], colours)   # 第三行紅字


if __name__ == "__main__":
    unittest.main()
