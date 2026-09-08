"""YT 國內外新聞直播（news）與今日熱搜（hot）的標題字級必須一致（2026-09-08）。

使用者回報 news 的標題字級比 hot 大。查下來兩條線的**合成版**推導本來就完全相同
（同一組 YT_TITLE_* 常數、同一段 max_w、同一組 baseline），AI 版兩個模板描述字級的
措辭也一字不差，所以沒有可對齊的差值——這支測試把「相同」釘死，以後任何一邊調字級
都會被擋下來，不會再默默分岔。

實測差異只可能來自 AI 標題模式：字級由模型決定，同一段措辭每張略有差異
（見 docs/yt-live-cover-spec.md「試做紀錄」）。
"""
import io
import os
import re
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402

LINE1 = "挪威國王哈拉德辭世"
LINE2 = "開放公眾瞻仰遺容"


def _flat_png(colour=(40, 40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _title_ink_box(img: Image.Image):
    """底半部白色像素（第一行標題）的外框。"""
    px = img.load()
    xs, ys = [], []
    for y in range(round(img.height * 0.55), img.height, 2):
        for x in range(0, img.width, 2):
            r, g, b = px[x, y]
            if r > 240 and g > 240 and b > 240:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


class CompositeParityTests(unittest.TestCase):
    def test_the_two_layouts_render_the_title_identically(self):
        bg = _flat_png()
        news = Image.open(io.BytesIO(compose.compose_yt_cover(
            bg, line1=LINE1, line2=LINE2, date_text="2026/09/08"))).convert("RGB")
        hot = Image.open(io.BytesIO(compose.compose_yt_hot_cover(
            bg, line1=LINE1, line2=LINE2))).convert("RGB")
        box = _title_ink_box(news)
        self.assertIsNotNone(box)
        self.assertEqual(box, _title_ink_box(hot))

    def test_size_constants_are_shared_not_copied(self):
        """兩條線都直接讀同一組常數——不是各自抄一份數值。"""
        source = Path(__file__).resolve().parent.parent.joinpath("compose.py").read_text(encoding="utf-8")
        for name in ("YT_TITLE_SIZE_RATIO", "YT_TITLE_MIN_SIZE_RATIO",
                     "YT_LINE1_BASELINE_RATIO", "YT_LINE2_BASELINE_RATIO"):
            with self.subTest(constant=name):
                # 只有一處定義（其餘都是引用），hot 沒有自己的 YT_HOT_TITLE_* 覆寫
                self.assertEqual(len(re.findall(rf"^{name} = ", source, re.M)), 1)
                self.assertFalse(hasattr(compose, name.replace("YT_", "YT_HOT_")))


class AiPromptParityTests(unittest.TestCase):
    # 2026-09-08 使用者回饋「字體再粗一點、行距略縮」，兩個模板一起改
    TYPE_CLAUSE = "ULTRA-HEAVY BLACK-WEIGHT Chinese display type filling almost the full width"

    def test_both_templates_describe_the_type_size_the_same_way(self):
        for name in ("YT_COVER_FULL_PROMPT_NEWS", "YT_COVER_FULL_PROMPT_HOT"):
            with self.subTest(template=name):
                self.assertIn(self.TYPE_CLAUSE, getattr(editor_formats, name))

    def test_both_templates_ask_for_tight_leading(self):
        for name in ("YT_COVER_FULL_PROMPT_NEWS", "YT_COVER_FULL_PROMPT_HOT"):
            with self.subTest(template=name):
                self.assertIn("TIGHT LEADING", getattr(editor_formats, name))

    def test_both_templates_use_the_same_line_colours(self):
        for name in ("YT_COVER_FULL_PROMPT_NEWS", "YT_COVER_FULL_PROMPT_HOT"):
            with self.subTest(template=name):
                text = getattr(editor_formats, name)
                self.assertIn("Line 1: solid white. Line 2: bright golden yellow.", text)


if __name__ == "__main__":
    unittest.main()
