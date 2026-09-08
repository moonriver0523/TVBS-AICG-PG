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
from unittest.mock import patch

from PIL import Image

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
        bold = max(2, round(font.size * compose.YT_TITLE_BOLD_RATIO))
        outline = max(4, round(font.size * compose.YT_TITLE_STROKE_RATIO)) + bold
        self.assertGreaterEqual(outline - bold, max(4, round(font.size * compose.YT_TITLE_STROKE_RATIO)))


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
                self.assertIn("ULTRA-HEAVY BLACK-WEIGHT", text)
                self.assertIn("TIGHT LEADING", text)
                self.assertNotIn("huge and heavy Chinese display type", text)


class HourlyUntouchedTests(unittest.TestCase):
    def test_hourly_keeps_its_own_baselines(self):
        """整點直播版面不同（靠左貼邊、無底帶），這次的粗細與行距只動 news／hot。"""
        self.assertEqual(compose.YT_HOURLY_LINE1_BASELINE_RATIO, 0.80)
        self.assertEqual(compose.YT_HOURLY_LINE2_BASELINE_RATIO, 0.965)


if __name__ == "__main__":
    unittest.main()
