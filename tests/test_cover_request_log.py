"""封面與 YT 封面的落檔欄位（2026-09-07）。

守的紅線：
1. **落檔要記得下生圖模型。** 只記 provider 事後分不出是哪一版模型畫的。
2. **具名真人與照片出處要記。** 肖像這段靠 prompt 端列人名，會飄；沒有出處就分不出
   「附了維基照畫本人」與「模型憑空捏一張臉掛真名」。出處逐位對齊人名。
3. **失敗也要留一筆。** 以前生圖失敗只會 print，事後查不到是哪一則標題觸發的。
"""
import base64
import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import main  # noqa: E402
import photo_lookup  # noqa: E402
import request_log  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402

PHOTO = photo_lookup.ReferencePhoto(
    image_base64="cGhvdG8=", mime_type="image/jpeg",
    image_url="https://upload.wikimedia.org/merz.jpg",
    source_page="https://zh.wikipedia.org/wiki/梅爾茨", lang="zh",
)

DERIVED = {
    "visual_left": "梅爾茨在講台前正面半身", "visual_right": "柏林街頭",
    "portrait_subjects_left": ["梅爾茨"], "portrait_subjects_left_en": ["Friedrich Merz"],
    "portrait_subjects_right": [], "portrait_subjects_right_en": [],
    # YT 用的欄位（同一份假回應餵兩條線）
    "line1": "梅爾茨", "line2": "深感震驚", "visual": "梅爾茨在講台前正面半身",
    "portrait_subjects": ["梅爾茨"], "portrait_subjects_en": ["Friedrich Merz"],
}


def _completion(payload):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])


def _png_for(aspect_ratio: str) -> bytes:
    ratio = main.parse_aspect_ratio(aspect_ratio) or 1.0
    buffer = io.BytesIO()
    Image.new("RGB", (round(720 * ratio), 720), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _found(subjects, english=None):
    return {name: PHOTO for name in subjects}, []


class CoverLogFieldTests(unittest.TestCase):
    def _post(self, url, body, raw=None):
        logged, failed = [], []

        def fake_raw(image_req):
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake/image-model-v9",
            )

        with patch.object(main, "digest_completion", return_value=_completion(DERIVED)), \
             patch.object(main, "lookup_portrait_photos", side_effect=_found), \
             patch.object(main, "supports_reference_image", return_value=True), \
             patch.object(main, "generate_image_raw", side_effect=raw or fake_raw), \
             patch.object(request_log, "log_generation", side_effect=lambda **kw: logged.append(kw)), \
             patch.object(request_log, "log_failure", side_effect=lambda **kw: failed.append(kw)):
            res = client.post(url, json=body, headers=_headers())
        return res, logged, failed

    def test_split_cover_logs_image_model_and_portrait_fields(self):
        res, logged, _ = self._post("/api/editor/cover", {
            "title_left": "梅爾茨 深感震驚", "title_right": "柏林街頭 選舉海報",
            "layout": "split", "mode": "composite",
        })
        self.assertEqual(res.status_code, 200, res.text)
        entry = next(e for e in logged if e["source"] == "editor-cover")
        self.assertEqual(entry["image_model"], "fake/image-model-v9")
        self.assertEqual(entry["portrait_subject"], "梅爾茨")
        self.assertEqual(entry["portrait_photo_source"], PHOTO.source_page)

    def test_full_cover_logs_image_model_and_portrait_fields(self):
        res, logged, _ = self._post("/api/editor/cover", {
            "title_left": "梅爾茨 深感震驚", "layout": "full", "mode": "composite",
        })
        self.assertEqual(res.status_code, 200, res.text)
        entry = next(e for e in logged if e["source"] == "editor-cover-full")
        self.assertEqual(entry["image_model"], "fake/image-model-v9")
        self.assertEqual(entry["portrait_subject"], "梅爾茨")
        self.assertEqual(entry["portrait_photo_source"], PHOTO.source_page)

    def test_yt_cover_logs_portrait_fields(self):
        res, logged, _ = self._post("/api/editor/yt-cover", {"title": "梅爾茨 深感震驚", "title_mode": "composite"})
        self.assertEqual(res.status_code, 200, res.text)
        entry = logged[-1]
        self.assertEqual(entry["image_model"], "fake/image-model-v9")
        self.assertEqual(entry["portrait_subject"], "梅爾茨")
        self.assertEqual(entry["portrait_photo_source"], PHOTO.source_page)

    def test_generation_failure_is_logged_on_every_cover_endpoint(self):
        def boom(image_req):
            raise RuntimeError("上游安全過濾擋下")

        for url, body, source in (
            ("/api/editor/cover",
             {"title_left": "梅爾茨 深感震驚", "title_right": "柏林街頭 選舉海報", "layout": "split", "mode": "composite"},
             "editor-cover"),
            ("/api/editor/cover",
             {"title_left": "梅爾茨 深感震驚", "layout": "full", "mode": "composite"},
             "editor-cover-full"),
            ("/api/editor/yt-cover",
             {"title": "梅爾茨 深感震驚", "title_mode": "composite"},
             "editor-yt-cover-news-composite"),
        ):
            with self.subTest(source=source):
                logged: list = []
                with patch.object(main, "digest_completion", return_value=_completion(DERIVED)), \
                     patch.object(main, "lookup_portrait_photos", side_effect=_found), \
                     patch.object(main, "supports_reference_image", return_value=True), \
                     patch.object(main, "generate_image_raw", side_effect=boom), \
                     patch.object(request_log, "log_failure", side_effect=lambda **kw: logged.append(kw)):
                    with self.assertRaises(RuntimeError):
                        client.post(url, json=body, headers=_headers())
                self.assertTrue(logged, "沒有記到失敗")
                self.assertEqual(logged[-1]["source"], source)
                self.assertIn("上游安全過濾擋下", logged[-1]["error"])


if __name__ == "__main__":
    unittest.main()
