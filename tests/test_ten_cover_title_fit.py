"""十點封面標題防呆（2026-09-07 使用者回報：超線、字太小、只有白黃）。

- 超寬的段落先拆行（不切在數字中間、偏好切在數量詞後），總行數 ≤ 3；
- 逐行各自撐滿格寬、短行最多比最寬行大 SPREAD 倍；起始字級 8.5% → 11%；
- 行距用當前行字級算，逐行不同字級不得重疊；
- 拆完縮到最小字級仍塞不進 → ComposeError → 端點 400。
"""
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402
import main  # noqa: E402
from editor_formats import split_cover_title  # noqa: E402
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

W, H = compose.COVER_CANVAS
PANEL_MAX_W = round((W // 2 - compose.COVER_MARGIN) * compose.COVER_TITLE_WIDTH_RATIO)
START = round(H * compose.COVER_TITLE_SIZE_RATIO)
MIN = round(H * compose.COVER_TITLE_MIN_SIZE_RATIO)
LONG_LEFT = "韓法攜手5年各自投資影視產業184億元 提升軟實力"
LONG_RIGHT = "大型資料中心覓址難 科技公司看上阿根廷巴塔哥尼亞"


class WrapTests(unittest.TestCase):
    def test_long_segment_is_wrapped_after_quantity_word_not_inside_digits(self):
        lines = compose.wrap_cover_title_lines(split_cover_title(LONG_LEFT), PANEL_MAX_W, START)
        self.assertEqual(lines, ["韓法攜手5年", "各自投資影視產業184億元", "提升軟實力"])

    def test_wrap_never_exceeds_three_lines_and_prefers_widest(self):
        lines = compose.wrap_cover_title_lines(split_cover_title(LONG_RIGHT), PANEL_MAX_W, START)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "大型資料中心覓址難")
        self.assertEqual("".join(lines[1:]), "科技公司看上阿根廷巴塔哥尼亞")
        three = compose.wrap_cover_title_lines(["很長很長很長很長很長很長的一段", "第二段", "第三段"], PANEL_MAX_W, START)
        self.assertEqual(len(three), 3, "已經 3 段就不再拆")

    def test_short_lines_untouched(self):
        self.assertEqual(compose.wrap_cover_title_lines(["勞保撥補", "上看1300億"], PANEL_MAX_W, START), ["勞保撥補", "上看1300億"])

    def test_split_keeps_digit_runs_together(self):
        head, tail = compose._split_line_near_middle("投資產業184億元計畫")
        self.assertFalse(head[-1:].isdigit() and tail[:1].isdigit())


class FitTests(unittest.TestCase):
    def test_start_size_is_larger_than_before(self):
        self.assertGreaterEqual(compose.COVER_TITLE_SIZE_RATIO, 0.11)

    def _fonts(self, lines):
        lines = compose.wrap_cover_title_lines(lines, PANEL_MAX_W, START)
        fonts = [compose._fit_font(ln, PANEL_MAX_W, START, MIN) for ln in lines]
        cap = min(START, round(min(f.size for f in fonts) * compose.COVER_TITLE_LINE_SIZE_SPREAD))
        return lines, [compose._font(cap) if f.size > cap else f for f in fonts]

    def test_every_line_fits_panel_and_spread_is_bounded(self):
        for title in (LONG_LEFT, LONG_RIGHT, "勞保撥補 上看1300億"):
            lines, fonts = self._fonts(split_cover_title(title))
            for ln, f in zip(lines, fonts):
                self.assertLessEqual(f.getbbox(ln)[2], PANEL_MAX_W, ln)
            sizes = [f.size for f in fonts]
            self.assertLessEqual(max(sizes) / min(sizes), compose.COVER_TITLE_LINE_SIZE_SPREAD + 0.05)

    def test_rendered_title_has_three_colours_and_stays_inside_panel(self):
        png = compose.compose_ten_cover(
            _png_bytes(size=(1024, 1024), colour=(40, 60, 90)), _png_bytes(size=(1024, 1024), colour=(60, 70, 80)),
            title_left=LONG_LEFT, title_right=LONG_RIGHT, date_text="2026/09/07",
        )
        img = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = img.size
        zone = img.crop((0, round(h * 0.62), w, h - round(h * 0.06)))
        raw = zone.tobytes()
        px = list(zip(raw[0::3], raw[1::3], raw[2::3]))
        white = sum(1 for r, g, b in px if r > 235 and g > 235 and b > 235)
        yellow = sum(1 for r, g, b in px if r > 220 and g > 180 and b < 80)
        red = sum(1 for r, g, b in px if r > 190 and g < 70 and b < 80)
        for name, n in (("white", white), ("yellow", yellow), ("red", red)):
            self.assertGreater(n, 3000, name)
        # 左格標題不得越過中線右側 4%、右格不得貼到畫面右緣：取字元色在最外側的 x
        def ink_cols(box):
            crop = img.crop(box)
            cols = set()
            for x in range(crop.width):
                for y in range(0, crop.height, 6):
                    r, g, b = crop.getpixel((x, y))
                    # 只認黃／紅字：白色會被斜切縫的白線干擾
                    if (r > 220 and g > 180 and b < 80) or (r > 190 and g < 70 and b < 80):
                        cols.add(x); break
            return cols
        left_cols = ink_cols((0, round(h * 0.62), w // 2, h - round(h * 0.06)))
        self.assertLess(max(left_cols), w // 2 - compose.COVER_MARGIN + 8)
        right_cols = ink_cols((w // 2, round(h * 0.62), w, h - round(h * 0.06)))
        self.assertGreater(min(right_cols), 0)
        self.assertLess(max(right_cols) + w // 2, w - compose.COVER_MARGIN + 8)

    def test_lines_do_not_overlap(self):
        # 行距用當前行字級：上一行 baseline 必須高於這一行的字頂
        lines, fonts = self._fonts(split_cover_title(LONG_LEFT))
        baseline = H
        prev_top = None
        for idx in range(len(lines) - 1, -1, -1):
            top = baseline - fonts[idx].size
            if prev_top is not None:
                self.assertLessEqual(baseline, prev_top, f"第 {idx + 1} 行壓到第 {idx + 2} 行")
            prev_top = top
            baseline -= round(fonts[idx].size * compose.COVER_TITLE_LINE_GAP)


class TooLongTests(unittest.TestCase):
    def test_hopeless_title_returns_400_not_overflowing_image(self):
        body = {
            "title_left": "這是一段完全沒有空格也沒有數量詞可以拆的超級無敵長標題文字測試用途", "title_right": "右格 標題",
            "mode": "composite", "layout": "split",
            "asis_left": _data_url(_png_bytes(size=(1024, 1024))), "asis_right": _data_url(_png_bytes(size=(1024, 1024))),
        }
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("標題太長", res.json()["detail"])


if __name__ == "__main__":
    unittest.main()
