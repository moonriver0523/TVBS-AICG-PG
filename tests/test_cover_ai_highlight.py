"""十點 AI 整張版選「精華」要貼圓章（2026-09-07 使用者回報：選了還是只有 ON AIR）。

合成版由 compose_ten_cover 貼圓章；AI 版標頭刻意維持 ON AIR，圓章要在後貼那串補上，
追加修改回來的 overlay 路徑走同一串。
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
import main  # noqa: E402
from test_ten_cover import _headers, _png_bytes, client  # noqa: E402

GREY = (90, 90, 90)


def _stamp_zone_ink(img: Image.Image) -> int:
    """圓章區（水平正中、頂端貼齊畫面上緣）裡非底色的像素數。"""
    w, h = img.size
    d = round(h * compose.COVER_STAMP_HEIGHT_RATIO)
    top = round(h * compose.COVER_STAMP_TOP_RATIO)
    zone = img.crop((w // 2 - d // 2, top, w // 2 + d // 2, min(h, top + d))).convert("RGB")
    raw = zone.tobytes()
    return sum(1 for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3]) if abs(r - GREY[0]) + abs(g - GREY[1]) + abs(b - GREY[2]) > 60)


class PasteStampTests(unittest.TestCase):
    def test_paste_stamp_marks_top_centre_and_scales_to_canvas(self):
        for size in ((1920, 1080), (1536, 864)):
            base = _png_bytes(size=size, colour=GREY)
            before = Image.open(io.BytesIO(base))
            after = Image.open(io.BytesIO(compose.paste_cover_highlight_stamp(base)))
            self.assertEqual(after.size, size)
            self.assertGreater(_stamp_zone_ink(after), _stamp_zone_ink(before) + 5000, size)
            # 左上角（Logo 區）不受影響
            self.assertEqual(after.convert("RGB").getpixel((10, size[1] // 2)), GREY)


class AiEndpointTests(unittest.TestCase):
    def _post(self, body):
        def fake_raw(image_req):
            ratio = main.parse_aspect_ratio(image_req.aspect_ratio) or 1.0
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_bytes(size=(round(864 * ratio), 864), colour=GREY)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "resolve_cover_visuals", return_value=("畫面", "畫面")):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return Image.open(io.BytesIO(base64.b64decode(res.json()["image_data_base64"])))

    def test_ai_full_highlight_gets_stamp_on_air_does_not(self):
        base = {"title_left": "測試 標題", "layout": "full", "mode": "ai"}
        on_air = self._post(dict(base, badge="on_air"))
        highlight = self._post(dict(base, badge="highlight"))
        self.assertGreater(_stamp_zone_ink(highlight), _stamp_zone_ink(on_air) + 5000)

    def test_ai_split_highlight_gets_stamp(self):
        base = {"title_left": "測試 標題", "title_right": "右邊 標題", "layout": "split", "mode": "ai"}
        on_air = self._post(dict(base, badge="on_air"))
        highlight = self._post(dict(base, badge="highlight"))
        self.assertGreater(_stamp_zone_ink(highlight), _stamp_zone_ink(on_air) + 5000)

    def test_overlay_path_after_refine_keeps_stamp(self):
        raw = base64.b64encode(_png_bytes(size=(1536, 864), colour=GREY)).decode("ascii")
        body = {"title_left": "測試 標題", "layout": "full", "mode": "ai", "badge": "highlight",
                "background_image_base64": raw, "background_mime_type": "image/png"}
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("overlay 不該生圖")):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        img = Image.open(io.BytesIO(base64.b64decode(res.json()["image_data_base64"])))
        self.assertGreater(_stamp_zone_ink(img), 5000)


if __name__ == "__main__":
    unittest.main()
