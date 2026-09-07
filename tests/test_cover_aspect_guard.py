"""封面／YT 封面的成圖比例驗證（2026-09-07）。

守的紅線：封面這幾條線直呼 `generate_image_raw`，繞過 `finalize_image_result`，
以前生成端間歇性降級（要 16:9 回 3:2）不會被發現，圖照樣合成、照樣上鏡。
現在每條線拿到 result 就驗一次，降級當場變成錯誤回應而不是一張裁壞的封面。
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

import main  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402


def _three_by_two() -> bytes:
    """模型降級後實際回來的尺寸（2026-08-01 的真實案例：要 21:9 回 3:2）。"""
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 800), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _degraded(image_req):
    return main.ImageGenerateResponse(
        image_data_base64=base64.b64encode(_three_by_two()).decode("ascii"),
        mime_type="image/png", model="fake-degraded",
    )


class CoverAspectGuardTests(unittest.TestCase):
    def _post(self, url, body):
        with patch.object(main, "resolve_cover_visuals", return_value=("左場景", "右場景")), \
             patch.object(main, "resolve_yt_cover_plan", return_value=(("前段", "後段"), "場景", [], [])), \
             patch.object(main, "generate_image_raw", side_effect=_degraded):
            return client.post(url, json=body, headers=_headers())

    def test_split_composite_panel_degrade_is_an_error_not_a_cover(self):
        res = self._post("/api/editor/cover", {
            "title_left": "尼泊爾災區 滅村慘況", "title_right": "台南易淹水 成氣候衝擊區",
            "layout": "split", "mode": "composite",
        })
        self.assertEqual(res.status_code, 502, res.text)
        self.assertIn("比例不符", res.json()["detail"])

    def test_full_composite_background_degrade_is_an_error(self):
        res = self._post("/api/editor/cover", {
            "title_left": "尼泊爾災區 滅村慘況", "layout": "full", "mode": "composite",
        })
        self.assertEqual(res.status_code, 502, res.text)

    def test_ai_cover_degrade_is_an_error(self):
        res = self._post("/api/editor/cover", {
            "title_left": "尼泊爾災區 滅村慘況", "title_right": "台南易淹水 成氣候衝擊區",
            "layout": "split", "mode": "ai",
        })
        self.assertEqual(res.status_code, 502, res.text)

    def test_yt_cover_background_degrade_is_an_error(self):
        res = self._post("/api/editor/yt-cover", {"title": "前段 後段", "title_mode": "composite"})
        self.assertEqual(res.status_code, 502, res.text)

    def test_yt_cover_ai_title_degrade_is_an_error(self):
        res = self._post("/api/editor/yt-cover", {"title": "前段 後段", "title_mode": "ai"})
        self.assertEqual(res.status_code, 502, res.text)


if __name__ == "__main__":
    unittest.main()
