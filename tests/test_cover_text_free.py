"""十點封面合成版的無文字覆寫（2026-09-07）。

守的紅線：合成版的兩條生圖路徑（雙切每格 1:1、滿版 16:9）都是**無文字底圖**，
文字全部由 Pillow 疊。肖像規則與附圖用途規則都寫著「示意圖標籤要保持可見」，
不在最後壓一段 override，模型會自己在底圖上畫一個「示意圖」字樣，程式疊的字蓋不掉。
AI 整張版相反——那條線就是要模型畫字，不能壓。與 YT 直播封面同一段 override。
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

import editor_formats  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402


def _png_for(aspect_ratio: str) -> bytes:
    """依請求比例回一張對應尺寸的圖，才過得了成圖比例驗證。"""
    ratio = main.parse_aspect_ratio(aspect_ratio) or 1.0
    height = 720
    buffer = io.BytesIO()
    Image.new("RGB", (round(height * ratio), height), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


class CoverTextFreeOverrideTests(unittest.TestCase):
    def _run(self, body):
        seen = []

        def fake_raw(image_req):
            seen.append(image_req)
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "resolve_cover_visuals", return_value=("左場景", "右場景")), \
             patch.object(main, "generate_image_raw", side_effect=fake_raw):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return seen

    def test_split_composite_panels_end_with_the_text_free_override(self):
        seen = self._run({
            "title_left": "尼泊爾災區 滅村慘況", "title_right": "台南易淹水 成氣候衝擊區",
            "layout": "split", "mode": "composite",
        })
        self.assertEqual(len(seen), 2)
        for req in seen:
            self.assertEqual(req.aspect_ratio, "1:1")
            self.assertTrue(
                req.prompt.rstrip().endswith(editor_formats.YT_COVER_TEXT_FREE_OVERRIDE),
                req.prompt[-400:],
            )

    def test_full_composite_background_ends_with_the_text_free_override(self):
        seen = self._run({"title_left": "尼泊爾災區 滅村慘況", "layout": "full", "mode": "composite"})
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].aspect_ratio, "16:9")
        self.assertTrue(
            seen[0].prompt.rstrip().endswith(editor_formats.YT_COVER_TEXT_FREE_OVERRIDE),
            seen[0].prompt[-400:],
        )

    def test_ai_mode_is_never_told_to_stay_text_free(self):
        for body in (
            {"title_left": "尼泊爾災區 滅村慘況", "title_right": "台南易淹水 成氣候衝擊區", "layout": "split", "mode": "ai"},
            {"title_left": "尼泊爾災區 滅村慘況", "layout": "full", "mode": "ai"},
        ):
            with self.subTest(layout=body["layout"]):
                seen = self._run(body)
                self.assertEqual(len(seen), 1)
                self.assertNotIn(editor_formats.YT_COVER_TEXT_FREE_OVERRIDE, seen[0].prompt)


if __name__ == "__main__":
    unittest.main()
