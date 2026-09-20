"""十點封面 AI 版的追加修改（2026-09-07）。

成品＝「模型畫的整張圖＋程式後貼的 Logo／節目標籤／AI示意圖」。refine 要改的是
**後貼前的模型原圖**——把貼過 Logo 的成品餵回生圖模型，模型會把 Logo 一起重畫，
那是播出事故（與主流程「refine 送置框前原圖」同一個道理）。

守的紅線：
1. AI 版回應帶 source_image_base64（後貼前的原圖），合成版不帶。
2. 帶 background_image_base64 回來只重貼固定元素：一次生圖、一次文字模型都不打。

比照 YT 封面的 background_image_base64／yt-cover:overlay 那條路。
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
import photo_lookup  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402

RAW_COLOUR = (17, 99, 200)


def _png_for(aspect_ratio: str) -> bytes:
    ratio = main.parse_aspect_ratio(aspect_ratio) or 1.0
    buffer = io.BytesIO()
    Image.new("RGB", (round(720 * ratio), 720), RAW_COLOUR).save(buffer, format="PNG")
    return buffer.getvalue()


SPLIT = {"title_left": "尼泊爾災區 滅村慘況", "title_right": "台南易淹水 成氣候衝擊區", "layout": "split"}
FULL = {"title_left": "尼泊爾災區 滅村慘況", "layout": "full"}


class CoverRefineSourceTests(unittest.TestCase):
    def _post(self, body):
        def fake_raw(image_req):
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "resolve_cover_visuals", return_value=("左場景", "右場景")), \
             patch.object(main, "generate_image_raw", side_effect=fake_raw):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_ai_mode_returns_the_pre_paste_model_image(self):
        for layout in (SPLIT, FULL):
            with self.subTest(layout=layout["layout"]):
                data = self._post({**layout, "mode": "ai", "title_creativity": 1})
                self.assertTrue(data["source_image_base64"])
                self.assertEqual(data["source_mime_type"], "image/png")
                source = Image.open(io.BytesIO(base64.b64decode(data["source_image_base64"]))).convert("RGB")
                # 源圖是模型原圖：還沒貼 Logo，左上角仍是原本的底色
                self.assertEqual(source.getpixel((source.size[0] // 2, source.size[1] // 2)), RAW_COLOUR)
                # 成品則已經貼過（同一個位置的畫面已被 Logo／標頭元素改寫或至少不同於源圖）
                cover = Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")
                self.assertEqual(cover.size, compose.COVER_CANVAS)  # 2026-09-14：AI 路徑一律放大到定版

    def test_composite_mode_has_no_refine_source(self):
        for layout in (SPLIT, FULL):
            with self.subTest(layout=layout["layout"]):
                data = self._post({**layout, "mode": "composite"})
                self.assertEqual(data["source_image_base64"], "")
                self.assertEqual(data["source_mime_type"], "")


class CoverRecompositeTests(unittest.TestCase):
    def _recomposite(self, body):
        raw = _png_for("16:9")
        payload = {
            **body, "mode": "ai", "title_creativity": 1,
            "background_image_base64": base64.b64encode(raw).decode("ascii"),
            "background_mime_type": "image/png",
        }
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "digest_completion", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return res.json(), raw

    def test_supplied_background_only_repastes_fixed_elements(self):
        for layout in (SPLIT, FULL):
            with self.subTest(layout=layout["layout"]):
                data, raw = self._recomposite(layout)
                # 源圖原樣回傳，下一輪修改接得上
                self.assertEqual(base64.b64decode(data["source_image_base64"]), raw)
                cover = Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")
                self.assertEqual(cover.size, compose.COVER_CANVAS)  # 2026-09-14：AI 路徑一律放大到定版
                # 後貼確實跑了：「AI示意圖」小標壓在左上
                w, h = cover.size
                y = round(h * compose.COVER_AI_HEADER_RATIO) + round(h * 0.025) + 8
                x = round(w * compose.COVER_MARGIN / compose.COVER_CANVAS[0]) + 4
                self.assertNotEqual(cover.getpixel((x, y)), RAW_COLOUR)


class NamedFaceReplacementTests(unittest.TestCase):
    def _post(self, body, outcome=None):
        captured = {}

        def fake_raw(image_req):
            captured["request"] = image_req
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for("16:9")).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        outcome_patch = patch.object(
            main,
            "lookup_portrait_outcomes",
            return_value={body["replacement_person"]: outcome} if outcome else {},
        )
        with outcome_patch, patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "_archive_generation"), \
             patch.object(main.request_log, "log_generation"):
            response = client.post(
                "/api/images/refine",
                json={"source_image_base64": "QUJD", **body},
                headers=_headers(),
            )
        return response, captured.get("request")

    def test_user_portrait_has_priority(self):
        response, image_request = self._post(
            {
                "instruction": "把甲的臉換掉",
                "replacement_person": "甲",
                "reference_images": [
                    {"data_url": "data:image/png;base64,QUJD", "purpose": "portrait"}
                ],
            },
            outcome=None,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(image_request.reference_images), 1)
        self.assertIn("supplied by the user", image_request.prompt)

    def test_wikipedia_photo_is_attached_as_reference(self):
        photo = photo_lookup.ReferencePhoto(
            image_base64="QUJD", mime_type="image/jpeg", image_url="https://example.test/a.jpg",
            source_page="https://example.test/wiki/A", lang="en",
        )
        outcome = photo_lookup.PortraitLookupOutcome(
            photo=photo, entry_found=True, matched_name="甲", language="en"
        )
        response, image_request = self._post(
            {"instruction": "把甲的臉換掉", "replacement_person": "甲"}, outcome
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(image_request.reference_images), 1)
        self.assertEqual(image_request.reference_images[0].purpose, "portrait")
        self.assertIn("Wikipedia portrait photograph", image_request.prompt)

    def test_entry_only_allows_model_face_and_returns_notice(self):
        outcome = photo_lookup.PortraitLookupOutcome(
            photo=None, entry_found=True, matched_name="甲", language="zh"
        )
        response, image_request = self._post(
            {"instruction": "把甲的臉換掉", "replacement_person": "甲"}, outcome
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(image_request.reference_images, [])
        self.assertIn("no qualifying portrait photograph", image_request.prompt)
        self.assertEqual(len(response.json()["notices"]), 1)

    def test_no_entry_returns_400_without_generating(self):
        outcome = photo_lookup.PortraitLookupOutcome(
            photo=None, entry_found=False, matched_name=None, language=None
        )
        response, image_request = self._post(
            {"instruction": "把甲的臉換掉", "replacement_person": "甲"}, outcome
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Wikipedia", response.json()["detail"])
        self.assertIn("原圖放置", response.json()["detail"])
        self.assertIsNone(image_request)

    def test_empty_replacement_keeps_general_refine_prompt(self):
        response, image_request = self._post(
            {"instruction": "把標題改成紅色", "replacement_person": ""}, outcome=None
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("MUST NOT draw or complete the face", image_request.prompt)
        self.assertNotIn("NAMED FACE REPLACEMENT SCOPE", image_request.prompt)


if __name__ == "__main__":
    unittest.main()
