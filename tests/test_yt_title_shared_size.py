"""2026-09-08 使用者裁決：YT 三種封面的兩行標題一律同字級（取全域最小）。十點封面另議（TODO）。"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
from test_ten_cover import _png_bytes  # noqa: E402

SHORT, LONG = "澳洲擬立新法", "民眾可關閉社群媒體演算法還要再更長一點"


def _title_sizes(fn, **kw):
    """實際畫兩行標題時各用了多大的字：攔截兩種畫字入口，只收標題那兩句。"""
    seen = {}
    orig_line, orig_text = compose._draw_yt_title_line, compose._draw_text

    def spy_line(draw, xy, text, font, fill, *a, **k):
        if text in (SHORT, LONG):
            seen[text] = font.size
        return orig_line(draw, xy, text, font, fill, *a, **k)

    def spy_text(draw, xy, text, font, *a, **k):
        if text in (SHORT, LONG):
            seen[text] = font.size
        return orig_text(draw, xy, text, font, *a, **k)

    with patch.object(compose, "_draw_yt_title_line", side_effect=spy_line),          patch.object(compose, "_draw_text", side_effect=spy_text):
        fn(_png_bytes(size=(1920, 1080)), line1=SHORT, line2=LONG, **kw)
    return seen


class SharedSizeTests(unittest.TestCase):
    def test_helper_takes_global_min(self):
        start, smallest = 157, 92
        alone = compose._fit_font(LONG, 1700, start, smallest).size
        self.assertLess(alone, start)
        self.assertEqual(compose._yt_shared_title_font([SHORT, LONG], 1700, start, smallest).size, alone)
        self.assertEqual(compose._yt_shared_title_font([SHORT, SHORT], 1700, start, smallest).size, start)

    def test_all_three_covers_draw_both_lines_with_one_size(self):
        for fn, kw in (
            (compose.compose_yt_cover, {"date_text": "2026/09/08"}),
            (compose.compose_yt_hourly_cover, {"date_text": "2026/09/08"}),
            (compose.compose_yt_hot_cover, {}),
        ):
            with self.subTest(fn=fn.__name__):
                seen = _title_sizes(fn, **kw)
                self.assertEqual(set(seen), {SHORT, LONG})
                self.assertEqual(seen[SHORT], seen[LONG], "短行要跟著長行縮到同一字級")
                self.assertLess(seen[LONG], round(1080 * compose.YT_TITLE_SIZE_RATIO))

    def test_news_and_hot_refuse_a_line_that_cannot_fit_even_at_min_size(self):
        """審查建議（2026-09-08）：只有整點擋了「縮到最小仍超出」，國內外／熱搜也要擋，不能靜靜裁掉。"""
        too_long = "這是一行怎麼縮都塞不進一千九百二十像素寬度的超長標題文字內容再加幾個字"
        for fn, kw in ((compose.compose_yt_cover, {"date_text": "2026/09/08"}), (compose.compose_yt_hot_cover, {})):
            with self.subTest(fn=fn.__name__), self.assertRaises(compose.ComposeError) as cm:
                fn(_png_bytes(size=(1920, 1080)), line1=SHORT, line2=too_long, **kw)
            self.assertIn("請縮短這一行", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
