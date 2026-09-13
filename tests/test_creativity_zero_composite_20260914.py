# -*- coding: utf-8 -*-
"""創意 0 → 一律程式壓字（2026-09-14 使用者裁決）。

十點／整點／新聞直播／熱搜／live24 全套：拉桿是唯一開關，0 級不管有沒有附圖、附圖是原圖放置
還是 AI改圖，標題（整點連日期牌）都由程式畫；1 級起才送生圖畫標題。追加修改帶回底圖的請求
不動（標題已經畫在上面）。取代 live24 專屬的 creativity<1 與整點極短標題兩條局部規則。
"""
import base64
import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

RED, BLUE, GREEN = (200, 30, 30), (30, 30, 200), (30, 200, 30)
TITLE_L, TITLE_R = "尼泊爾災區 滅村慘況", "台南易淹水 成氣候衝擊區"


def _ref(colour, purpose):
    return {"data_url": _data_url(_png_bytes(colour=colour)), "purpose": purpose}


def _decode(data) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")


class _Harness(unittest.TestCase):
    def _run(self, url, body, expect=200):
        calls = []

        def fake_raw(req):
            calls.append(req)
            w, h = {"1:1": (1024, 1024)}.get(req.aspect_ratio, (1280, 720))
            return SimpleNamespace(
                image_data_base64=base64.b64encode(_png_bytes(size=(w, h), colour=GREEN)).decode(),
                model="fake", mime_type="image/png",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
                patch.object(main, "resolve_cover_visuals", return_value=("左景", "右景")), \
                patch.object(main, "derive_yt_cover_plan", return_value={"visual": "景"}), \
                patch.object(main, "_archive_generation", lambda **k: None), \
                patch.object(main, "supports_multiple_reference_images", return_value=True):
            res = client.post(url, json=body, headers=_headers())
        self.assertEqual(res.status_code, expect, res.text[:300])
        return res.json(), calls


class Predicate(unittest.TestCase):
    def test_zero_forces_composite_and_one_keeps_the_request(self):
        f = editor_formats.title_mode_for_creativity
        self.assertEqual(f(0, "ai", False), "composite")
        self.assertEqual(f(0, "composite", False), "composite")
        for level in (1, 2, 3, 4):
            self.assertEqual(f(level, "ai", False), "ai")
            self.assertEqual(f(level, "composite", False), "composite")

    def test_a_request_carrying_a_background_is_left_alone(self):
        """追加修改帶回底圖：標題已畫在上面，改成 composite 會再壓一層。"""
        self.assertEqual(editor_formats.title_mode_for_creativity(0, "ai", True), "ai")

    def test_the_hourly_short_title_special_case_is_gone(self):
        """整點極短標題那條局部規則被全域規則涵蓋，連函式一起移除。"""
        self.assertFalse(hasattr(editor_formats, "yt_hourly_short_title_needs_composite"))
        self.assertFalse(hasattr(editor_formats, "yt_hourly_first_line"))


class TenCover(_Harness):
    URL = "/api/editor/cover"

    def test_full_zero_creativity_is_program_text_even_when_ai_was_asked(self):
        data, calls = self._run(self.URL, {"title_left": TITLE_L, "layout": "full", "mode": "ai"})
        self.assertEqual(data["mode"], "composite")
        self.assertEqual(len(calls), 1, "只生一張無字底圖")
        self.assertNotIn("TEXT TO RENDER", calls[0].prompt)

    def test_full_one_creativity_still_lets_the_model_draw_the_title(self):
        data, calls = self._run(self.URL, {"title_left": TITLE_L, "layout": "full", "mode": "ai", "title_creativity": 1})
        self.assertEqual(data["mode"], "ai")
        self.assertIn("TEXT TO RENDER", calls[-1].prompt)

    def test_split_zero_creativity_keeps_the_asis_panel_pixel_exact(self):
        """裁決 3：一邊原圖一邊 AI改圖 在創意 0 下，原圖那格根本不送進模型。

        證據是生圖只打一次、而且是 AI改圖 那格的 1:1；成品左格取樣只驗「還是那張紅圖」
        （程式壓字會疊暗化層，不做逐值相等）。
        """
        data, calls = self._run(self.URL, {
            "title_left": TITLE_L, "title_right": TITLE_R, "layout": "split", "mode": "ai",
            "slot_left": [_ref(RED, "asis")], "slot_right": [_ref(BLUE, "aiedit")],
        })
        self.assertEqual(data["mode"], "composite")
        self.assertEqual(len(calls), 1, "只有 AI改圖 那格生圖，沒有第二段整張畫字")
        self.assertEqual(calls[0].aspect_ratio, "1:1")
        self.assertIn("aiedit", [r.purpose for r in calls[0].reference_images])
        img = _decode(data)
        w, h = img.size
        # 程式壓字會在照片上疊半透明暗化層，所以看的是「還是那張紅圖」而不是逐值相等
        r, g, b = img.getpixel((w // 6, h // 2))
        self.assertTrue(r > 150 and g < 60 and b < 60, (r, g, b))
        self.assertFalse(data["left_is_ai"])
        self.assertTrue(data["right_is_ai"])

    def test_split_one_creativity_goes_two_stage_and_the_model_gets_the_base(self):
        data, calls = self._run(self.URL, {
            "title_left": TITLE_L, "title_right": TITLE_R, "layout": "split", "mode": "ai", "title_creativity": 1,
            "slot_left": [_ref(RED, "asis")], "slot_right": [_ref(BLUE, "aiedit")],
        })
        self.assertEqual(data["mode"], "ai")
        self.assertEqual(len(calls), 2)
        self.assertIn("TEXT TO RENDER", calls[-1].prompt)

    def test_full_all_asis_zero_creativity_makes_no_image_call(self):
        data, calls = self._run(self.URL, {
            "title_left": TITLE_L, "layout": "full", "mode": "ai",
            "slot_left": [_ref(RED, "asis"), _ref(BLUE, "asis")],
        })
        self.assertEqual(data["mode"], "composite")
        self.assertEqual(calls, [])

    def test_a_refine_round_trip_with_a_background_keeps_ai_mode(self):
        """追加修改回來（帶 background）：只重貼固定元素，不能被改成 composite（雙切會 400）。"""
        bg = base64.b64encode(_png_bytes(size=(1280, 720), colour=GREEN)).decode()
        data, calls = self._run(self.URL, {
            "title_left": TITLE_L, "title_right": TITLE_R, "layout": "split", "mode": "ai",
            "background_image_base64": bg, "background_mime_type": "image/png",
        })
        self.assertEqual(data["mode"], "ai")
        self.assertEqual(calls, [])


class YtCover(_Harness):
    URL = "/api/editor/yt-cover"

    def test_every_layout_at_zero_is_program_text(self):
        for layout in ("hourly", "news", "hot", "live24"):
            with self.subTest(layout=layout):
                data, _ = self._run(self.URL, {"title": "前段 後段", "layout": layout, "title_mode": "ai"})
                self.assertEqual(data["title_mode"], "composite")

    def test_every_layout_at_one_keeps_ai_title(self):
        for layout in ("hourly", "news", "hot", "live24"):
            with self.subTest(layout=layout):
                data, calls = self._run(self.URL, {
                    "title": "前段 後段", "layout": layout, "title_mode": "ai", "creativity": 1})
                self.assertEqual(data["title_mode"], "ai")
                self.assertIn("TEXT TO RENDER", calls[-1].prompt)

    def test_hourly_dual_at_zero_is_program_text(self):
        data, _ = self._run(self.URL, {
            "title": "前段 後段", "title_second": "第二 標題", "layout": "hourly", "title_mode": "ai",
            "time_text": "20:00",
        })
        self.assertEqual(data["title_mode"], "composite")

    def test_hourly_short_title_at_one_is_no_longer_forced(self):
        """以前「首段 ≤5 格」的整點 0 級會被改壓字；規則收進創意 0 後，1 級的極短標題照交模型。"""
        data, _ = self._run(self.URL, {
            "title": "東北季風冷 今起增強", "layout": "hourly", "title_mode": "ai", "creativity": 1})
        self.assertEqual(data["title_mode"], "ai")

    def test_single_asis_at_zero_makes_no_image_call_and_keeps_the_photo(self):
        data, calls = self._run(self.URL, {
            "title": "前段 後段", "layout": "news", "title_mode": "ai",
            "reference_images": [_ref(RED, "asis")],
        })
        self.assertEqual(data["title_mode"], "composite")
        self.assertEqual(calls, [])
        img = _decode(data)
        w, h = img.size
        r, g, b = img.getpixel((w // 2, h // 3))
        self.assertTrue(r > 150 and g < 60 and b < 60, (r, g, b))

    def test_a_refine_round_trip_with_a_background_keeps_ai_mode(self):
        bg = base64.b64encode(_png_bytes(size=(1280, 720), colour=GREEN)).decode()
        data, calls = self._run(self.URL, {
            "title": "前段 後段", "layout": "news", "title_mode": "ai",
            "background_image_base64": bg, "background_mime_type": "image/png",
        })
        self.assertEqual(data["title_mode"], "ai")
        self.assertEqual(calls, [])


class Frontend(unittest.TestCase):
    APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
    INDEX = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_payloads_derive_the_mode_from_the_slider_not_the_checkbox(self):
        self.assertIn("const composite = state.coverTitleCreativity === 0", self.APP_JS)
        self.assertIn("title_mode: state.ytCreativity >= 1 ? 'ai' : 'composite'", self.APP_JS)
        self.assertNotIn("document.getElementById('coverAiTitle')?.checked === false", self.APP_JS)
        self.assertNotIn("document.getElementById('ytCoverAiTitle')?.checked === false", self.APP_JS)

    def test_the_checkboxes_are_read_only_mirrors_of_the_slider(self):
        import re
        for box_id, state in (("coverAiTitle", "coverTitleCreativity"), ("ytCoverAiTitle", "ytCreativity")):
            with self.subTest(box=box_id):
                tag = re.search(rf'<input id="{box_id}"[^>]*>', self.INDEX).group(0)
                self.assertIn("disabled", tag)
                self.assertNotIn("checked", tag)
                self.assertIn(f"aiBox.checked = state.{state} >= 1", self.APP_JS)

    def test_the_sliders_are_no_longer_hidden_behind_the_checkbox(self):
        self.assertNotIn("|| !aiMode", self.APP_JS)


if __name__ == "__main__":
    unittest.main()
