"""十點封面左右上傳位（2026-09-07 使用者裁決）。

原本附圖不分左右（依順序：1 張＝全版、2 張＝左右格），使用者上傳真實照片時分不清哪張是左。
改成 asis_left／asis_right 各自一個位子：有圖的格直接上版，沒圖的格生底圖，
左有右無就只生右格。舊的 reference_images asis 順序規則保留給舊呼叫端。
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
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

RED, BLUE, GREEN = (200, 30, 30), (30, 30, 200), (30, 200, 30)


def _payload(left=None, right=None, **extra):
    body = {
        "title_left": "尼泊爾災區 無人機空拍 滅村慘況",
        "title_right": "台南易淹水 成氣候衝擊區",
        "mode": "ai",
        "asis_left": _data_url(_png_bytes(colour=left)) if left else "",
        "asis_right": _data_url(_png_bytes(colour=right)) if right else "",
    }
    body.update(extra)
    return body


def _decode(data) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")


class SlotTests(unittest.TestCase):
    def _post(self, body, panel_colour=GREEN, visuals=("左景", "右景")):
        calls = []

        def fake_panel(visual, provider, references=None, *args):
            calls.append(visual)
            return _png_bytes(colour=panel_colour)

        with patch.object(main, "_cover_panel_image", side_effect=fake_panel), \
             patch.object(main, "resolve_cover_visuals", return_value=visuals) as resolve, \
             patch.object(main, "generate_image_raw", side_effect=AssertionError("不該直接生圖")):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        return res, calls, resolve

    def test_both_slots_place_images_without_any_generation(self):
        res, calls, resolve = self._post(_payload(left=RED, right=BLUE))
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["model"], "ten-cover:composite-asisLR")
        self.assertEqual(calls, [])
        self.assertFalse(resolve.called, "兩格都有圖不該補畫面描述")
        self.assertFalse(data["left_is_ai"])
        self.assertFalse(data["right_is_ai"])
        img = _decode(data)
        w, h = img.size
        self.assertEqual(img.getpixel((w // 4, round(h * 0.3))), RED)
        self.assertEqual(img.getpixel((3 * w // 4, round(h * 0.3))), BLUE)

    def test_left_only_generates_right_panel(self):
        res, calls, resolve = self._post(_payload(left=RED))
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["model"], "ten-cover:composite-asisL")
        self.assertEqual(calls, ["右景"], "只該生右格，而且用右格的畫面描述")
        self.assertFalse(data["left_is_ai"])
        self.assertTrue(data["right_is_ai"])
        img = _decode(data)
        w, h = img.size
        self.assertEqual(img.getpixel((w // 4, round(h * 0.3))), RED)
        self.assertEqual(img.getpixel((3 * w // 4, round(h * 0.3))), GREEN)
        # 有圖的左格畫面描述用標題佔位，不留空讓模型亂補
        self.assertEqual(resolve.call_args.args[0].visual_left, "尼泊爾災區 無人機空拍 滅村慘況")

    def test_right_only_generates_left_panel(self):
        res, calls, resolve = self._post(_payload(right=BLUE))
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["model"], "ten-cover:composite-asisR")
        self.assertEqual(calls, ["左景"])
        self.assertTrue(data["left_is_ai"])
        self.assertFalse(data["right_is_ai"])
        img = _decode(data)
        w, h = img.size
        self.assertEqual(img.getpixel((w // 4, round(h * 0.3))), GREEN)
        self.assertEqual(img.getpixel((3 * w // 4, round(h * 0.3))), BLUE)

    def test_one_slot_still_forces_composite_even_with_ai_title(self):
        res, _, _ = self._post(_payload(left=RED, mode="ai"))
        self.assertEqual(res.json()["mode"], "composite")

    def test_visual_supplied_for_generated_side_skips_the_text_model(self):
        res, calls, resolve = self._post(_payload(left=RED, visual_right="淹水街道"), visuals=("x", "x"))
        self.assertEqual(res.status_code, 200, res.text)
        # resolve_cover_visuals 是真函式時兩欄都有值就不打 API；這裡驗證的是傳進去的欄位都已填滿
        req = resolve.call_args.args[0]
        self.assertEqual(req.visual_left, "尼泊爾災區 無人機空拍 滅村慘況")
        self.assertEqual(req.visual_right, "淹水街道")

    def test_slots_take_precedence_over_legacy_asis_list(self):
        body = _payload(left=RED)
        body["reference_images"] = [{"data_url": _data_url(_png_bytes(colour=BLUE)), "purpose": "asis"}]
        res, calls, _ = self._post(body)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["model"], "ten-cover:composite-asisL")
        self.assertEqual(calls, ["右景"])

    def test_bad_slot_data_url_is_400(self):
        res, _, _ = self._post(_payload(left=RED, asis_right="not-a-data-url"))
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
