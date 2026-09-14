# -*- coding: utf-8 -*-
"""2026-09-14 對齊第 3 項：YT 國內外新聞直播／今日熱搜補「一標一附圖位」。

整點 2026-09-10 改附圖位時這兩個沒跟上。後端單則「附圖位整份清單併進共用清單」那條路
（2026-09-13）本來就對所有 layout 生效，所以這裡驗的是：news／hot 走附圖位時
1 張整版／2 張雙切／3 張三切照走、AI改圖 進生圖、只改文字帶底圖回來零 API。
前台：版型表翻 slots、共用附圖區收起來。
"""
import base64
import io
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import compose  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)
RED, BLUE, GREEN, GREY = (200, 30, 30), (30, 30, 200), (30, 200, 30), (90, 90, 90)


def _headers() -> dict:
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}


def _png(size=(1280, 720), colour=GREY) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _ref(colour, purpose="asis") -> dict:
    return {"data_url": "data:image/png;base64," + base64.b64encode(_png(colour=colour)).decode("ascii"), "purpose": purpose}


def _decode(data) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")


def _is(pixel, colour, tol=40) -> bool:
    # 合成版會疊漸層暗化，只驗「還是那個顏色系」
    return all(abs(a - b) <= tol for a, b in zip(pixel, colour))


class _Harness(unittest.TestCase):
    def _post(self, body):
        calls = []

        def fake_raw(req):
            calls.append(req)
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png(colour=GREEN)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
                patch.object(main, "derive_yt_cover_plan", return_value={"visual": "景", "portrait_subjects": []}), \
                patch.object(main, "_archive_generation", lambda **k: None), \
                patch.object(main, "supports_multiple_reference_images", return_value=True):
            res = client.post("/api/editor/yt-cover", json={"title": "前段 後段", "date_text": "2026/09/14", **body}, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text[:300])
        return res.json(), calls


class SlotsOnNewsAndHot(_Harness):
    def test_one_asis_in_the_slot_fills_the_frame_without_any_image_call(self):
        for layout in ("news", "hot"):
            with self.subTest(layout=layout):
                data, calls = self._post({"layout": layout, "slot_left": [_ref(RED)]})
                self.assertEqual(calls, [])
                self.assertEqual(data["title_mode"], "composite")
                self.assertFalse(data["background_is_ai"])
                img = _decode(data)
                w, h = img.size
                self.assertTrue(_is(img.getpixel((w // 2, h // 3)), RED))

    def test_two_asis_in_the_slot_split_left_right(self):
        for layout in ("news", "hot"):
            with self.subTest(layout=layout):
                data, calls = self._post({"layout": layout, "slot_left": [_ref(RED), _ref(BLUE)]})
                self.assertEqual(calls, [])
                img = _decode(data)
                w, h = img.size
                self.assertTrue(_is(img.getpixel((w // 8, h // 3)), RED))
                self.assertTrue(_is(img.getpixel((w * 7 // 8, h // 3)), BLUE))

    def test_three_asis_in_the_slot_split_three_ways(self):
        data, calls = self._post({"layout": "news", "slot_left": [_ref(RED), _ref(BLUE), _ref(GREY)]})
        self.assertEqual(calls, [])
        img = _decode(data)
        w, h = img.size
        self.assertTrue(_is(img.getpixel((w // 12, h // 3)), RED))
        self.assertTrue(_is(img.getpixel((w * 11 // 12, h // 3)), GREY))

    def test_an_ai_edit_in_the_slot_reaches_the_image_model(self):
        for layout in ("news", "hot"):
            with self.subTest(layout=layout):
                data, calls = self._post({"layout": layout, "slot_left": [_ref(RED, "aiedit")]})
                self.assertEqual(len(calls), 1)
                self.assertEqual([r.purpose for r in calls[0].reference_images], ["aiedit"])
                self.assertTrue(data["background_is_ai"])

    def test_five_asis_in_the_slot_is_rejected_before_any_model_call(self):
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json={
                "title": "前段 後段", "layout": "hot", "slot_left": [_ref(RED)] * 5,
            }, headers=_headers())
        self.assertEqual(res.status_code, 400)
        self.assertIn("最多 4 張", res.json()["detail"])

    def test_text_only_recompose_with_a_background_makes_no_image_call(self):
        """只改文字（能力矩陣 text_only_recompose）：帶壓字前底圖回來，零 API 重疊文字。"""
        for layout in ("news", "hot"):
            with self.subTest(layout=layout):
                first, _ = self._post({"layout": layout, "slot_left": [_ref(RED)]})
                data, calls = self._post({
                    "layout": layout, "title": "換了 標題",
                    "title_mode": "composite",
                    "background_image_base64": first["source_image_base64"],
                    "background_mime_type": first["source_mime_type"],
                })
                self.assertEqual(calls, [])
                self.assertEqual(data["line1"], "換了")
                img = _decode(data)
                w, h = img.size
                self.assertTrue(_is(img.getpixel((w // 2, h // 3)), RED))


class DualTextOnlyRecompose(_Harness):
    """能力矩陣寫 hourly／live24 的 text_only_recompose 含 dual——旗子要有測試撐著，不是抄前台註解。"""

    def test_hourly_dual_with_two_slots_recomposes_over_the_returned_background(self):
        first, calls = self._post({
            "layout": "hourly", "title_second": "第二 標題", "time_text": "20:00",
            "slot_left": [_ref(RED)], "slot_right": [_ref(BLUE)],
        })
        self.assertEqual(calls, [])
        self.assertTrue(first["dual"])
        data, calls = self._post({
            "layout": "hourly", "title": "換了 第一則", "title_second": "換了 第二則", "time_text": "20:00",
            "title_mode": "composite",
            "slot_left": [_ref(RED)], "slot_right": [_ref(BLUE)],   # 前台重送時附圖位還在
            "background_image_base64": first["source_image_base64"],
            "background_mime_type": first["source_mime_type"],
        })
        self.assertEqual(calls, [])
        self.assertTrue(data["dual"])
        self.assertEqual(data["line1"], "換了 第一則")
        img = _decode(data)
        w, h = img.size
        self.assertTrue(_is(img.getpixel((w // 8, h // 3)), RED))
        self.assertTrue(_is(img.getpixel((w * 7 // 8, h // 3)), BLUE))

    def test_live24_blend_with_two_slots_recomposes_over_the_returned_background(self):
        first, calls = self._post({
            "layout": "live24", "title": "二十四小時直播", "live24_bg": "blend",
            "slot_left": [_ref(RED)], "slot_right": [_ref(BLUE)],
        })
        self.assertEqual(calls, [])
        self.assertTrue(first["dual"])
        data, calls = self._post({
            "layout": "live24", "title": "換了標題", "live24_bg": "blend", "title_mode": "composite",
            "slot_left": [_ref(RED)], "slot_right": [_ref(BLUE)],
            "background_image_base64": first["source_image_base64"],
            "background_mime_type": first["source_mime_type"],
        })
        self.assertEqual(calls, [])
        self.assertTrue(data["dual"])
        img = _decode(data)
        w, h = img.size
        self.assertTrue(_is(img.getpixel((w // 8, h // 2)), RED))
        self.assertTrue(_is(img.getpixel((w * 7 // 8, h // 2)), BLUE))


class Frontend(unittest.TestCase):
    APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")

    def _entry(self, key):
        return re.search(rf"{key}:\s*\{{(.*?)\n\s{{4}}\}},", self.APP_JS, re.S).group(1)

    def test_news_and_hot_now_carry_slots_and_hide_the_shared_upload_box(self):
        for key in ("yt_live_cover", "yt_hot_cover"):
            with self.subTest(format=key):
                entry = self._entry(key)
                self.assertIn("slots: true", entry)
                self.assertIn("refUpload: true", re.search(r"hides:\s*\{([^}]*)\}", entry).group(1))
                self.assertIn("附圖位", entry)

    def test_the_slot_row_is_shared_by_every_yt_layout(self):
        """附圖位那組 DOM 在 ytCoverInputs 裡，不是整點專屬——翻旗子就露出來，不用另做 DOM。"""
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        block = html[html.index('id="ytCoverInputs"'):html.index('id="ytCoverTitleSecondRow"')]
        self.assertIn('id="ytAsisLeftRow"', block)


if __name__ == "__main__":
    unittest.main()
