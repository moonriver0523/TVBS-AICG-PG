"""純 AI 版封面的標題分行改由程式決定（2026-09-07）。

以前合成版走 split_cover_title、AI 版讓模型自己拆，同一個標題在兩種模式下斷句不一樣，
使用者切模式比對時看到的是兩張不同版面的圖。現在兩邊共用 compose.cover_title_lines
（使用者自己分的行優先，超寬再由 wrap_cover_title_lines 防呆拆），模板只要模型照著印。
比照 YT ai-title 的 line1／line2。
"""
import base64
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
import editor_formats  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402


def _png_for(aspect_ratio: str) -> bytes:
    ratio = main.parse_aspect_ratio(aspect_ratio) or 1.0
    buffer = io.BytesIO()
    Image.new("RGB", (round(720 * ratio), 720), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


class TemplateTests(unittest.TestCase):
    def test_templates_no_longer_ask_the_model_to_split_the_headline(self):
        for name in ("COVER_AI_PROMPT_TEMPLATE", "COVER_AI_FULL_PROMPT_TEMPLATE"):
            with self.subTest(template=name):
                text = getattr(editor_formats, name)
                self.assertNotIn("yourself", text)
                self.assertIn("ALREADY split into lines", text)
                self.assertIn("do NOT re-split, merge or reorder", text)
                self.assertIn("the split is already decided", text)


class SharedSplitTests(unittest.TestCase):
    def test_user_supplied_split_is_kept_verbatim(self):
        self.assertEqual(
            compose.cover_title_lines("尼泊爾災區 無人機空拍 滅村慘況"),
            ["尼泊爾災區", "無人機空拍", "滅村慘況"],
        )

    def test_overlong_line_is_wrapped_by_the_same_guard_the_composite_uses(self):
        long_title = "政府明年勞保撥補上看一千三百億元創歷年新高"
        lines = compose.cover_title_lines(long_title)
        self.assertGreater(len(lines), 1)
        # 2026-09-08：雙切放寬到 4 行（拆得夠短，兩格的共同字級才撐得起來）
        self.assertLessEqual(len(lines), compose.COVER_MAX_TITLE_LINES_SPLIT)
        # 只切不改字
        self.assertEqual("".join(lines), long_title)

    def test_full_layout_gets_a_wider_panel_than_split(self):
        self.assertGreater(
            compose.cover_title_panel_width(True), compose.cover_title_panel_width(False)
        )


class AiPromptTests(unittest.TestCase):
    def _prompt(self, body):
        seen = {}

        def fake_raw(image_req):
            seen["prompt"] = image_req.prompt
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "resolve_cover_visuals", return_value=("左場景", "右場景")), \
             patch.object(main, "generate_image_raw", side_effect=fake_raw):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return seen["prompt"]

    def test_split_ai_prompt_carries_the_pre_split_lines(self):
        prompt = self._prompt({
            "title_left": "尼泊爾災區 無人機空拍 滅村慘況",
            "title_right": "台南易淹水 成氣候衝擊區",
            "layout": "split", "mode": "ai",
        })
        # 2026-09-08：行數與顏色逐行標在清單上（顏色依行序：白／黃／紅）
        for expected in (
            "(exactly 3 lines", "(exactly 2 lines",
            "Line 1 (white): 尼泊爾災區", "Line 2 (yellow): 無人機空拍", "Line 3 (red): 滅村慘況",
            "Line 1 (white): 台南易淹水", "Line 2 (yellow): 成氣候衝擊區",
        ):
            self.assertIn(expected, prompt)
        # 未分行的整條標題不再出現在 prompt 裡
        self.assertNotIn("尼泊爾災區 無人機空拍 滅村慘況", prompt)

    def test_full_ai_prompt_carries_the_pre_split_lines(self):
        prompt = self._prompt({"title_left": "全球3100條 躍動冰川", "layout": "full", "mode": "ai"})
        self.assertIn("Line 1 (white): 全球3100條", prompt)
        self.assertIn("Line 2 (yellow): 躍動冰川", prompt)


if __name__ == "__main__":
    unittest.main()
