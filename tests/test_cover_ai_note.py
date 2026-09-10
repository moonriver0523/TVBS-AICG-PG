"""純 AI 版封面的「AI示意圖」小標改由程式壓（2026-09-07）。

根因：模板本來要模型自己畫這個小標，但只要使用者附了實景參考圖，
apply_user_references_to_image_request 就會追加「Do NOT render any 示意圖 label」——
位置在後又是明文 OVERRIDE，模型照做，標籤整個消失。

裁決：標籤一律由程式壓（比照 YT ai-title 的固定元素後貼）。兩個 AI 模板改成
明文要模型不要畫、把位置留乾淨。
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

# 亮底圖：小標的半透明黑底才驗得出來（暗底圖本來就過門檻）
BRIGHT = (235, 235, 235)


def _png_for(aspect_ratio: str) -> bytes:
    ratio = main.parse_aspect_ratio(aspect_ratio) or 1.0
    buffer = io.BytesIO()
    Image.new("RGB", (round(720 * ratio), 720), BRIGHT).save(buffer, format="PNG")
    return buffer.getvalue()


def _note_region_is_plate(img: Image.Image, align_right: bool) -> bool:
    """AI 版標籤位置是否有半透明黑底（比亮底圖暗很多）。幾何同 paste_cover_ai_note。"""
    w, h = img.size
    y = round(h * compose.COVER_AI_HEADER_RATIO) + round(h * 0.025) + 8
    margin = round(w * compose.COVER_MARGIN / compose.COVER_CANVAS[0])
    # 探在小標的內距（pad ≈ 1.2% 畫面高）裡，不要探到白色字身上
    x = (w - margin - 4) if align_right else (margin + 4)
    r, g, b = img.getpixel((x, y))
    return (r + g + b) < sum(BRIGHT) - 150


class TemplateTests(unittest.TestCase):
    def test_templates_no_longer_ask_the_model_to_draw_the_label(self):
        for name in ("COVER_AI_PROMPT_TEMPLATE", "COVER_AI_FULL_PROMPT_TEMPLATE"):
            with self.subTest(template=name):
                text = getattr(editor_formats, name)
                self.assertNotIn("label just below the header band", text)
                self.assertNotIn("The AI示意圖 label is small", text)
                self.assertIn("Do NOT draw any 示意圖 label", text)
                self.assertIn("Software adds that label afterwards", text)


class AiCoverNoteTests(unittest.TestCase):
    def _cover(self, body):
        def fake_raw(image_req):
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "resolve_cover_visuals", return_value=("左場景", "右場景")), \
             patch.object(main, "generate_image_raw", side_effect=fake_raw):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return Image.open(io.BytesIO(base64.b64decode(res.json()["image_data_base64"]))).convert("RGB")

    def test_split_ai_cover_gets_a_label_on_both_outer_corners(self):
        img = self._cover({
            "title_left": "尼泊爾災區 滅村慘況", "title_right": "台南易淹水 成氣候衝擊區",
            "layout": "split", "mode": "ai",
        })
        self.assertTrue(_note_region_is_plate(img, align_right=False))
        self.assertTrue(_note_region_is_plate(img, align_right=True))

    def test_full_ai_cover_gets_one_label_top_left_only(self):
        img = self._cover({"title_left": "尼泊爾災區 滅村慘況", "layout": "full", "mode": "ai"})
        self.assertTrue(_note_region_is_plate(img, align_right=False))
        self.assertFalse(_note_region_is_plate(img, align_right=True))


class PasteGeometryTests(unittest.TestCase):
    def test_label_geometry_follows_the_model_image_resolution(self):
        # 模型回什麼解析度都要壓得上（合成版固定 1920×1080，AI 版不是）
        for size in ((1280, 720), (1536, 864)):
            with self.subTest(size=size):
                buffer = io.BytesIO()
                Image.new("RGB", size, BRIGHT).save(buffer, format="PNG")
                out = compose.paste_cover_ai_note(buffer.getvalue(), split=True)
                img = Image.open(io.BytesIO(out)).convert("RGB")
                self.assertEqual(img.size, size)
                self.assertTrue(_note_region_is_plate(img, align_right=False))
                self.assertTrue(_note_region_is_plate(img, align_right=True))


if __name__ == "__main__":
    unittest.main()
