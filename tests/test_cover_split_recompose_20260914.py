# -*- coding: utf-8 -*-
"""十點不一樣（雙切）合成版的「只改文字」（2026-09-14 使用者裁決，補齊能力矩陣最後一格）。

雙切合成版的成品是「兩格拼好的底圖＋Pillow 壓上去的兩個標題／標頭」。以前改標題要整張
重生（兩格各一次生圖），現在回應把**拼好但還沒壓字**的底圖帶回前端，改字時原樣帶回來，
後端只重壓文字（compose_ten_cover prebuilt_split=True），零生圖、零文字模型。

紅線：
1. 雙切合成版回應帶 background_image_base64／background_is_ai（左格）＋right_is_ai（右格），
   source_image_base64 仍留空（那格是 refine 用的）。
2. 帶 background 回來：附圖位就算重送、就算有一格沒放原圖，也一次生圖、一次文字模型都不打；
   model 記 ten-cover:recomposite；AI示意圖照帶回的 left/right 旗子印。
3. 同標題重壓的成品要跟第一次**逐像素相同**——證明斜切內框、兩格暗化、同字級全走同一條路。
4. 版面對不上（滿版底圖配雙切標題、或反過來）明講 400，不默默壓錯版。
"""
import base64
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

RED, BLUE, GREEN = (200, 30, 30), (30, 30, 200), (30, 200, 30)
TITLES = {"title_left": "尼泊爾災區 滅村慘況", "title_right": "臺南易淹水 成氣候衝擊區"}
NEW_TITLES = {"title_left": "換了 第一標題", "title_right": "換了 第二標題"}


def _decode(field, data) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data[field]))).convert("RGB")


def _slot(colour):
    return [{"data_url": _data_url(_png_bytes(size=(900, 900), colour=colour)), "purpose": "asis"}]


def _post(body, *, calls=None):
    def fake_raw(req):
        (calls if calls is not None else []).append(req)
        return main.ImageGenerateResponse(
            image_data_base64=base64.b64encode(_png_bytes(size=(1024, 1024), colour=GREEN)).decode("ascii"),
            mime_type="image/png", model="fake",
        )

    with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
            patch.object(main, "resolve_cover_visuals", return_value=(TITLES["title_left"], TITLES["title_right"])), \
            patch.object(main, "_archive_generation", lambda **k: None):
        return client.post("/api/editor/cover", json={
            "layout": "split", "mode": "composite", "date_text": "2026/09/14", **body,
        }, headers=_headers())


class SplitCompositeReturnsBackground(unittest.TestCase):
    def test_two_asis_slots_return_the_stitched_background_and_no_source(self):
        res = _post({**TITLES, "slot_left": _slot(RED), "slot_right": _slot(BLUE)})
        self.assertEqual(res.status_code, 200, res.text[:300])
        data = res.json()
        self.assertEqual(data["source_image_base64"], "")
        self.assertTrue(data["background_image_base64"])
        self.assertEqual(data["background_mime_type"], "image/png")
        self.assertFalse(data["background_is_ai"])
        self.assertFalse(data["right_is_ai"])
        bg = _decode("background_image_base64", data)
        self.assertEqual(bg.size, compose.COVER_CANVAS)
        w, h = bg.size
        self.assertEqual(bg.getpixel((w // 8, h // 2)), RED)
        self.assertEqual(bg.getpixel((w * 7 // 8, h // 2)), BLUE)
        # 壓字前底圖不能已經有標頭帶：最頂端一列還是原圖顏色
        self.assertEqual(bg.getpixel((w // 8, 2)), RED)

    def test_one_ai_panel_marks_the_right_flag(self):
        calls = []
        res = _post({**TITLES, "slot_left": _slot(RED)}, calls=calls)
        self.assertEqual(res.status_code, 200, res.text[:300])
        self.assertEqual(len(calls), 1)
        data = res.json()
        self.assertFalse(data["background_is_ai"])   # 左格是原圖
        self.assertTrue(data["right_is_ai"])         # 右格是生的


class SplitRecomposeIsZeroApi(unittest.TestCase):
    def _first(self):
        res = _post({**TITLES, "slot_left": _slot(RED), "slot_right": _slot(BLUE)})
        self.assertEqual(res.status_code, 200, res.text[:300])
        return res.json()

    def _recompose(self, first, body):
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
                patch.object(main, "resolve_cover_visuals", side_effect=AssertionError("不該打文字模型")), \
                patch.object(main, "_archive_generation", lambda **k: None):
            return client.post("/api/editor/cover", json={
                "layout": "split", "mode": "composite", "date_text": "2026/09/14",
                "background_image_base64": first["background_image_base64"],
                "background_mime_type": first["background_mime_type"],
                "background_is_ai": first["background_is_ai"],
                "background_right_is_ai": first["right_is_ai"],
                "background_layout": "split",
                **body,
            }, headers=_headers())

    def test_same_titles_reproduce_the_first_cover_pixel_for_pixel(self):
        first = self._first()
        res = self._recompose(first, TITLES)
        self.assertEqual(res.status_code, 200, res.text[:300])
        data = res.json()
        self.assertEqual(data["model"], "ten-cover:recomposite")
        diff = ImageChops.difference(_decode("image_data_base64", first), _decode("image_data_base64", data))
        self.assertIsNone(diff.getbbox(), "只改文字重壓出來的成品跟第一次不是逐像素相同")
        # 底圖原樣再回來，前端可以一直改
        self.assertEqual(data["background_image_base64"], first["background_image_base64"])

    def test_new_titles_change_the_cover_but_keep_the_panels(self):
        first = self._first()
        res = self._recompose(first, {**NEW_TITLES, "slot_left": _slot(RED)})   # 右格附圖位空著也不能生圖
        self.assertEqual(res.status_code, 200, res.text[:300])
        data = res.json()
        img = _decode("image_data_base64", data)
        w, h = img.size
        self.assertEqual(img.getpixel((w // 8, round(h * 0.30))), RED)
        self.assertEqual(img.getpixel((w * 7 // 8, round(h * 0.30))), BLUE)
        self.assertIsNotNone(ImageChops.difference(_decode("image_data_base64", first), img).getbbox())

    def test_ai_flags_are_passed_through_to_the_compositor(self):
        first = self._first()
        with patch.object(main.compose, "compose_ten_cover", wraps=compose.compose_ten_cover) as spy:
            res = self._recompose(first, {**TITLES, "background_is_ai": False, "background_right_is_ai": True})
        self.assertEqual(res.status_code, 200, res.text[:300])
        kwargs = spy.call_args.kwargs
        self.assertTrue(kwargs["prebuilt_split"])
        self.assertFalse(kwargs["left_is_ai"])
        self.assertTrue(kwargs["right_is_ai"])
        self.assertIsNone(spy.call_args.args[1])
        self.assertTrue(res.json()["right_is_ai"])


class LayoutMismatchIsRejected(unittest.TestCase):
    def test_full_background_with_a_second_title_is_400(self):
        raw = base64.b64encode(_png_bytes(size=(1920, 1080), colour=RED)).decode("ascii")
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/cover", json={
                **TITLES, "mode": "composite",
                "background_image_base64": raw, "background_layout": "full",
            }, headers=_headers())
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("版面變了", res.json()["detail"])

    def test_split_background_without_a_second_title_is_400(self):
        raw = base64.b64encode(_png_bytes(size=(1920, 1080), colour=RED)).decode("ascii")
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/cover", json={
                "title_left": TITLES["title_left"], "mode": "composite",
                "background_image_base64": raw, "background_layout": "split",
            }, headers=_headers())
        self.assertEqual(res.status_code, 400, res.text)

    def test_old_callers_without_the_layout_field_are_not_checked(self):
        raw = base64.b64encode(_png_bytes(size=(1920, 1080), colour=RED)).decode("ascii")
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
                patch.object(main, "_archive_generation", lambda **k: None):
            res = client.post("/api/editor/cover", json={
                "title_left": TITLES["title_left"], "mode": "composite",
                "background_image_base64": raw,
            }, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text[:300])


class Compositor(unittest.TestCase):
    def test_prebuilt_split_refuses_a_second_image(self):
        with self.assertRaises(compose.ComposeError):
            compose.compose_ten_cover(
                _png_bytes(), _png_bytes(), title_left="a", title_right="b", date_text="d", prebuilt_split=True,
            )


class Frontend(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent
    APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_the_button_is_no_longer_hidden_on_split_and_checks_the_layout(self):
        self.assertNotIn("recompose.classList.toggle('hidden', !fullLayout)", self.APP_JS)
        self.assertIn("recompose.disabled = !(bg && bg.layout === coverLayoutNow());", self.APP_JS)
        self.assertIn("background_right_is_ai: background.rightIsAi", self.APP_JS)
        self.assertIn("background_layout: background.layout", self.APP_JS)
        self.assertNotIn("const usable = coverLayoutNow() === 'full'", self.APP_JS)

    def test_the_html_button_title_no_longer_says_full_only(self):
        html = (self.ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("滿版程式壓字版專用", html)


if __name__ == "__main__":
    unittest.main()
