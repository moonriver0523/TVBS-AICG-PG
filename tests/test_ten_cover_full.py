"""十點不一樣（滿版）獨立版型（2026-09-07 使用者裁決：拆成滿版／雙切兩個版型）。

滿版＝一張圖鋪滿、一個標題；附圖有就放、沒有就生一張 16:9。雙切＝左右各自標題／附圖位。
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
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

RED, GREEN = (200, 30, 30), (30, 200, 30)


def _decode(data) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")


class FormatTableTests(unittest.TestCase):
    def test_two_independent_formats(self):
        self.assertEqual(editor_formats.cover_layout("ten_cover"), "split")
        self.assertEqual(editor_formats.cover_layout("ten_cover_full"), "full")
        self.assertEqual(editor_formats.cover_layout("default"), "")
        self.assertIn("滿版", editor_formats.get("ten_cover_full")["label"])
        self.assertIn("雙切", editor_formats.get("ten_cover")["label"])

    def test_full_prompt_has_one_photo_and_one_headline(self):
        text = editor_formats.COVER_AI_FULL_PROMPT_TEMPLATE.format(
            badge_text="ON AIR", date_text="2026/09/07",
            title_left_lines="  Line 1: 全球3100條\n  Line 2: 躍動冰川", visual_left="冰川崩落",
        )
        self.assertIn("ONE single photograph", text)
        self.assertNotIn("DIAGONAL seam", text)
        self.assertNotIn("RIGHT panel", text)
        self.assertIn("全球3100條", text)
        self.assertIn("躍動冰川", text)
        self.assertIn("do NOT write the programme name", text)


class FullEndpointTests(unittest.TestCase):
    def _post(self, body):
        calls = []

        def fake_full(visual, provider, references=None, *args, **kwargs):
            calls.append(visual)
            # 2026-09-07 起這幾支回 (bytes, 生圖模型名)，落檔要記 image_model
            return _png_bytes(size=(1600, 900), colour=GREEN), "fake-image-model"

        with patch.object(main, "_cover_full_image", side_effect=fake_full), \
             patch.object(main, "_cover_panel_image", side_effect=AssertionError("滿版不該生 1:1 格圖")), \
             patch.object(main, "resolve_cover_visuals", return_value=("冰川崩落", "冰川崩落")) as resolve, \
             patch.object(main, "generate_image_raw", side_effect=AssertionError("不該直接生圖")):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        return res, calls, resolve

    def test_full_with_asis_places_image_and_single_title_without_api(self):
        res, calls, resolve = self._post({
            "title_left": "全球3100條 躍動冰川 成氣候致命危機", "layout": "full", "mode": "ai",
            "asis_left": _data_url(_png_bytes(size=(1600, 900), colour=RED)),
        })
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["model"], "ten-cover-full:composite-asis")
        self.assertEqual(data["mode"], "composite")
        self.assertFalse(data["left_is_ai"])
        self.assertEqual(calls, [])
        self.assertFalse(resolve.called)
        img = _decode(data)
        w, h = img.size
        y = round(h * 0.30)
        for x in (w // 4, w // 2, 3 * w // 4):
            self.assertEqual(img.getpixel((x, y)), RED)          # 一張圖鋪滿，沒有斜線
        # 滿版標題橫跨整寬置中（2026-09-07 比照今日熱搜）：標題區左半、右半都要有字（白／黃／紅）
        def ink(box):
            raw = img.crop(box).tobytes()
            return sum(1 for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3]) if (r > 230 and g > 230) or (r > 200 and b < 90))
        title_zone = (round(h * 0.55), h - round(h * 0.06))
        self.assertGreater(ink((0, title_zone[0], w // 2, title_zone[1])), 2000)
        self.assertGreater(ink((w // 2, title_zone[0], w, title_zone[1])), 2000)

    def test_full_without_asis_generates_one_wide_image(self):
        res, calls, resolve = self._post({"title_left": "全球3100條 躍動冰川", "layout": "full", "mode": "composite"})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["model"], "ten-cover-full:composite")
        self.assertTrue(data["left_is_ai"])
        self.assertEqual(calls, ["冰川崩落"])
        self.assertTrue(resolve.called)
        img = _decode(data)
        w, h = img.size
        self.assertEqual(img.getpixel((w // 2, round(h * 0.30))), GREEN)

    def test_full_uses_supplied_visual_but_still_resolves_portraits(self):
        # 2026-09-07：描述有填仍打一次文字模型拿肖像名單；畫面描述採使用者填的
        res, calls, resolve = self._post({"title_left": "標題", "layout": "full", "mode": "composite", "visual_left": "冰川"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(calls, ["冰川"])
        self.assertTrue(resolve.called)
        self.assertEqual(res.json()["visual_left"], "冰川")

    def test_full_ai_mode_uses_full_template(self):
        seen = {}

        def fake_raw(image_req):
            seen["prompt"] = image_req.prompt
            seen["aspect"] = image_req.aspect_ratio
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_bytes(size=(1536, 864))).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "resolve_cover_visuals", return_value=("冰川崩落", "冰川崩落")):
            res = client.post("/api/editor/cover", json={"title_left": "全球3100條 躍動冰川", "layout": "full", "mode": "ai"}, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["model"], "ten-cover-full:ai")
        self.assertIn("ONE single photograph", seen["prompt"])
        self.assertEqual(seen["aspect"], "16:9")

    def test_split_still_requires_both_titles(self):
        res = client.post("/api/editor/cover", json={"title_left": "只有左", "layout": "split", "mode": "composite"}, headers=_headers())
        self.assertEqual(res.status_code, 400)

    def test_title_digest_target_full_returns_single_title(self):
        class R:
            choices = [type("C", (), {"message": type("M", (), {"content": '{"title": "全球3100條 躍動冰川 成致命危機"}'})()})()]

        with patch.object(main, "digest_completion", return_value=R()) as dc:
            res = client.post("/api/editor/cover-titles", json={"news_text": "全球超過三千條冰川正在快速移動，科學家警告。", "target": "ten_cover_full"}, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["title"], "全球3100條 躍動冰川 成致命危機")
        self.assertIn("single headline", dc.call_args.kwargs["system_prompt"])


if __name__ == "__main__":
    unittest.main()
