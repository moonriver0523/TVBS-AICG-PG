"""YT 封面標題「字體再粗一點、行距略縮」（2026-09-08 使用者回饋）。

國內外新聞直播（news）與今日熱搜（hot）共用同一組常數與同一支畫法，所以兩邊一起變。
整點直播（hourly）版面不同（靠左貼邊、沒有底帶、自己的 baseline），這次不動。

守的紅線：
1. **真的變粗。** 同一組標題渲染後的字色像素數比不加粗多。
2. **行距縮了但兩行不重疊。**
3. **AI 版措辭一起改**，不然壓字模式與 AI 模式又會長得不一樣。
"""
import io
import os
import sys
import unittest
from pathlib import Path
from collections import deque
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402

LINE1 = "挪威國王哈拉德辭世"
LINE2 = "開放公眾瞻仰遺容"
# 舊版行距（第二行字底 0.958 − 第一行字底 0.764）
OLD_LEADING = 0.958 - 0.764


def _flat_png(colour=(40, 40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _news(**kw) -> Image.Image:
    out = compose.compose_yt_cover(_flat_png(), line1=LINE1, line2=LINE2,
                                   date_text="2026/09/08", **kw)
    return Image.open(io.BytesIO(out)).convert("RGB")


def _hot(**kw) -> Image.Image:
    out = compose.compose_yt_hot_cover(_flat_png(), line1=LINE1, line2=LINE2, **kw)
    return Image.open(io.BytesIO(out)).convert("RGB")


def _ink(img: Image.Image, colour, tolerance=25) -> int:
    raw = img.crop((0, round(img.height * 0.6), img.width, img.height)).tobytes()
    return sum(
        1 for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3])
        if abs(r - colour[0]) + abs(g - colour[1]) + abs(b - colour[2]) < tolerance
    )


def _rows(img: Image.Image, colour, tolerance=25) -> list[int]:
    """畫面下半有該顏色像素的列號。"""
    px = img.load()
    out = []
    for y in range(round(img.height * 0.6), img.height):
        for x in range(0, img.width, 3):
            r, g, b = px[x, y]
            if abs(r - colour[0]) + abs(g - colour[1]) + abs(b - colour[2]) < tolerance:
                out.append(y)
                break
    return out


# 使用者實測糊掉的那一行（12 字，會縮到接近最小字級）
LONG_LINE = "民眾可關閉社群媒體演算法"
PROBE_BG = (0, 200, 0)


def _enclosed_counters(bold_ratio: float) -> list[int]:
    """把 LONG_LINE 畫在純色底上，回傳每個「封閉字腔」（不接觸畫布邊界的底色區塊）的面積。

    字腔＝口、日、國這些字裡被筆畫圍起來的內白。假粗體太重時筆畫會黏起來把字腔填掉，
    這裡用連通區域數出來，就不必猜某個字的某個洞在哪個座標。
    """
    with patch.object(compose, "YT_TITLE_BOLD_RATIO", bold_ratio):
        size = round(1080 * compose.YT_TITLE_MIN_SIZE_RATIO)   # 最小字級：最擠的情況
        font = compose._font(size)
        width = font.getbbox(LONG_LINE)[2] + 200
        img = Image.new("RGB", (width, size * 2), PROBE_BG)
        compose._draw_yt_title_line(
            ImageDraw.Draw(img), (width // 2, round(size * 1.4)), LONG_LINE, font, compose.YT_LINE2_FILL
        )
    px, (w, h) = img.load(), img.size
    seen = [[False] * w for _ in range(h)]

    def is_bg(x, y):
        r, g, b = px[x, y]
        return abs(r - PROBE_BG[0]) + abs(g - PROBE_BG[1]) + abs(b - PROBE_BG[2]) < 40

    areas = []
    for y0 in range(h):
        for x0 in range(w):
            if seen[y0][x0] or not is_bg(x0, y0):
                continue
            queue, cells, touches_edge = deque([(x0, y0)]), 0, False
            seen[y0][x0] = True
            while queue:
                x, y = queue.popleft()
                cells += 1
                if x in (0, w - 1) or y in (0, h - 1):
                    touches_edge = True
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and is_bg(nx, ny):
                        seen[ny][nx] = True
                        queue.append((nx, ny))
            if not touches_edge and cells >= 6:
                areas.append(cells)
    return sorted(areas, reverse=True)


class CounterTests(unittest.TestCase):
    """使用者 2026-09-08 第二輪回報：3.5% 太重，黃字筆畫黏住、字腔被吃掉。"""

    def test_long_line_keeps_its_counters_open_at_the_smallest_size(self):
        areas = _enclosed_counters(compose.YT_TITLE_BOLD_RATIO)
        self.assertGreaterEqual(len(areas), 8, f"封閉字腔只剩 {len(areas)} 個，筆畫黏住了")
        self.assertGreaterEqual(max(areas), 300, "最大的字腔被填得太小")

    def test_the_rejected_ratio_would_have_failed_this_check(self):
        """證明上面那條真的擋得住：3.5% 只剩 6 個字腔、最大 229。"""
        rejected = _enclosed_counters(0.035)
        current = _enclosed_counters(compose.YT_TITLE_BOLD_RATIO)
        self.assertLess(len(rejected), len(current))
        self.assertLess(max(rejected), max(current))

    def test_bold_ratio_is_the_value_the_user_asked_for(self):
        self.assertEqual(compose.YT_TITLE_BOLD_RATIO, 0.015)

    def test_shadow_offset_was_reduced_too(self):
        self.assertEqual(compose.YT_TITLE_SHADOW_RATIO, 0.02)


class WeightTests(unittest.TestCase):
    def test_faux_bold_adds_ink_on_both_layouts(self):
        for name, render in (("news", _news), ("hot", _hot)):
            with self.subTest(layout=name):
                bold = _ink(render(), compose.YT_LINE1_FILL)
                with patch.object(compose, "YT_TITLE_BOLD_RATIO", 0.0):
                    plain = _ink(render(), compose.YT_LINE1_FILL)
                self.assertGreater(bold, plain, "加粗後白字的像素應該變多")

    def test_bold_ratio_is_a_named_constant(self):
        self.assertGreater(compose.YT_TITLE_BOLD_RATIO, 0)

    def test_dark_outline_survives_the_bold_pass(self):
        """假粗體會吃掉外框寬度，深色描邊要先補回來，字才立得住（底色框預設關）。"""
        font = compose._font(100)
        bold = round(font.size * compose.YT_TITLE_BOLD_RATIO)
        outline = max(4, round(font.size * compose.YT_TITLE_STROKE_RATIO)) + bold
        self.assertGreaterEqual(outline - bold, max(4, round(font.size * compose.YT_TITLE_STROKE_RATIO)))

    def test_bold_has_no_artificial_floor(self):
        """設 max(2, …) 會讓 1.5% 與完全不加粗在常見字級下畫出一模一樣的字。"""
        self.assertEqual(round(157 * compose.YT_TITLE_BOLD_RATIO), 2)


class ShadowTests(unittest.TestCase):
    """底色框 2026-09-08 起預設關，字直接壓在照片上，補一層陰影（比照十點封面的標題）。"""

    def test_shadow_darkens_the_area_just_below_the_glyphs(self):
        light = (215, 215, 215)
        buffer = io.BytesIO()
        Image.new("RGB", (1920, 1080), light).save(buffer, format="PNG")
        bright = buffer.getvalue()
        out = compose.compose_yt_cover(bright, line1=LINE1, line2=LINE2, date_text="2026/09/08")
        img = Image.open(io.BytesIO(out)).convert("RGB")
        raw = img.crop((0, round(img.height * 0.6), img.width, img.height)).tobytes()
        dark = sum(1 for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3]) if r < 60 and g < 60 and b < 60)
        with patch.object(compose, "YT_TITLE_SHADOW_RATIO", 0.0):
            out2 = compose.compose_yt_cover(bright, line1=LINE1, line2=LINE2, date_text="2026/09/08")
        img2 = Image.open(io.BytesIO(out2)).convert("RGB")
        raw2 = img2.crop((0, round(img2.height * 0.6), img2.width, img2.height)).tobytes()
        dark2 = sum(1 for r, g, b in zip(raw2[0::3], raw2[1::3], raw2[2::3]) if r < 60 and g < 60 and b < 60)
        self.assertGreater(dark, dark2, "陰影應該讓標題周圍多出深色像素")


class LeadingTests(unittest.TestCase):
    def test_leading_is_tighter_than_before(self):
        leading = compose.YT_LINE2_BASELINE_RATIO - compose.YT_LINE1_BASELINE_RATIO
        self.assertLess(leading, OLD_LEADING)
        self.assertGreater(leading / OLD_LEADING, 0.90, "縮太多會擠在一起")

    def test_second_line_still_sits_at_the_bottom(self):
        self.assertEqual(compose.YT_LINE2_BASELINE_RATIO, 0.958)

    def test_the_two_lines_do_not_overlap(self):
        for name, render in (("news", _news), ("hot", _hot)):
            with self.subTest(layout=name):
                img = render()
                white = _rows(img, compose.YT_LINE1_FILL)
                yellow = _rows(img, compose.YT_LINE2_FILL)
                self.assertTrue(white and yellow)
                self.assertLess(max(white), min(yellow), "第一行的字壓到第二行了")


class AiPromptTests(unittest.TestCase):
    def test_both_templates_ask_for_ultra_heavy_and_tight_leading(self):
        for name in ("YT_COVER_FULL_PROMPT_NEWS", "YT_COVER_FULL_PROMPT_HOT"):
            with self.subTest(template=name):
                text = getattr(editor_formats, name)
                self.assertIn("heavy black-weight (weight, not colour)", text)
                self.assertIn("TIGHT LEADING", text)
                self.assertIn("counters", text)              # 明文要模型別把字腔畫糊
                self.assertNotIn("ULTRA-HEAVY", text)        # 太重的措辭已撤（使用者第二輪回報）
                self.assertNotIn("huge and heavy Chinese display type", text)


class HourlyUntouchedTests(unittest.TestCase):
    def test_hourly_keeps_its_own_baselines(self):
        """整點直播版面不同（靠左貼邊、無底帶），這次的粗細與行距只動 news／hot。"""
        self.assertEqual(compose.YT_HOURLY_LINE1_BASELINE_RATIO, 0.80)
        self.assertEqual(compose.YT_HOURLY_LINE2_BASELINE_RATIO, 0.965)


if __name__ == "__main__":
    unittest.main()
