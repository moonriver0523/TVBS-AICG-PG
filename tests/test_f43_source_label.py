"""F43（2026-09-20 晚間接線）：「畫面來源」標籤推廣到十點不一樣（composite 模式）。

範圍見 docs/f43-source-label-inventory.md 的盤點結論：只接進「程式保證原圖像素
未被 AI 動過」的路徑——十點不一樣 mode="composite" 且那一格是原圖放置（is_ai=False）。
mode="ai"（含 asis 參考圖，仍會被模型整張重畫）與 YT 封面各版型都**不在這批範圍**，
理由見盤點文件；這裡只測「有接的那一半」。

三塊測試：
1. compose.compose_ten_cover 的貼字邏輯（互斥、正規化前綴）
2. /api/editor/cover 滿版（layout=full）端到端
3. /api/editor/cover 雙切（layout=split）端到端，含「只改文字」recompose carry-forward
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
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

RED, BLUE = (200, 30, 30), (30, 60, 200)


def _decode(data) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")


class ComposeTenCoverSourceLabelTests(unittest.TestCase):
    """單元測試直接打 compose.compose_ten_cover，不經 API，驗證貼字邏輯本身。"""

    def _call(self, **overrides):
        kwargs = dict(
            left_image=_png_bytes(size=(1600, 900), colour=RED),
            right_image=None,
            title_left="標題",
            title_right="",
            date_text="2026/09/20",
            left_is_ai=False,
            right_is_ai=False,
        )
        kwargs.update(overrides)
        return compose.compose_ten_cover(**kwargs)

    def test_ai_wins_when_both_is_ai_and_source_text_are_set(self):
        """互斥：is_ai=True 時 source_text 被忽略，只畫「AI示意圖」。"""
        with patch.object(compose, "_draw_cover_ai_note") as spy:
            self._call(left_is_ai=True, left_source_text="美聯社")
        texts = [call.kwargs.get("text", compose.COVER_AI_NOTE) for call in spy.call_args_list]
        self.assertIn(compose.COVER_AI_NOTE, texts)
        self.assertNotIn(compose.vstrip_source_text("美聯社"), texts)

    def test_source_text_draws_when_not_ai(self):
        with patch.object(compose, "_draw_cover_ai_note") as spy:
            self._call(left_is_ai=False, left_source_text="美聯社")
        texts = [call.kwargs.get("text") for call in spy.call_args_list]
        self.assertIn("畫面來源：美聯社", texts)

    def test_source_text_prefix_is_not_duplicated(self):
        """沿用 vstrip_source_text：已經自己打「畫面來源」開頭的原樣回傳。"""
        with patch.object(compose, "_draw_cover_ai_note") as spy:
            self._call(left_is_ai=False, left_source_text="畫面來源：路透社")
        texts = [call.kwargs.get("text") for call in spy.call_args_list]
        self.assertIn("畫面來源：路透社", texts)
        self.assertNotIn("畫面來源：畫面來源：路透社", texts)

    def test_neither_is_ai_nor_source_text_draws_nothing(self):
        """現行行為：asis 沒填來源名時維持零標籤，不是新增的退步。"""
        with patch.object(compose, "_draw_cover_ai_note") as spy:
            self._call(left_is_ai=False, left_source_text="")
        spy.assert_not_called()

    def test_left_and_right_are_independent(self):
        with patch.object(compose, "_draw_cover_ai_note") as spy:
            self._call(
                right_image=_png_bytes(size=(1600, 900), colour=BLUE),
                title_right="右標題",
                left_is_ai=True, left_source_text="",
                right_is_ai=False, right_source_text="路透社",
            )
        calls_by_align_right = {call.kwargs.get("align_right"): call.kwargs.get("text", compose.COVER_AI_NOTE) for call in spy.call_args_list}
        self.assertEqual(calls_by_align_right[False], compose.COVER_AI_NOTE)
        self.assertEqual(calls_by_align_right[True], "畫面來源：路透社")

    def test_whitespace_only_source_text_counts_as_not_set(self):
        with patch.object(compose, "_draw_cover_ai_note") as spy:
            self._call(left_is_ai=False, left_source_text="   ")
        spy.assert_not_called()


class TenCoverFullEndpointSourceLabelTests(unittest.TestCase):
    """滿版（layout=full, mode=composite）端到端。"""

    def _post(self, **overrides):
        body = {
            "title_left": "標題", "layout": "full", "mode": "composite",
            "asis_left": _data_url(_png_bytes(size=(1600, 900), colour=RED)),
        }
        body.update(overrides)
        return client.post("/api/editor/cover", json=body, headers=_headers())

    def test_asis_with_source_left_gets_the_label(self):
        res = self._post(source_left="美聯社")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["left_is_ai"])
        self.assertEqual(data["source_left"], "美聯社")

    def test_asis_without_source_left_reports_empty(self):
        res = self._post()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["source_left"], "")

    def test_ai_generated_background_ignores_source_left(self):
        """沒有 asis 附圖＝AI 生底圖（is_ai=True），就算填了來源名也不能標——
        那不是使用者提供的真實素材。"""
        with patch.object(
            main, "_cover_full_image",
            return_value=(_png_bytes(size=(1600, 900), colour=RED), "fake-model"),
        ), patch.object(main, "resolve_cover_visuals", return_value=("視覺", "視覺")):
            res = self._post(asis_left="", source_left="美聯社")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["left_is_ai"])
        self.assertEqual(data["source_left"], "")

    def test_pure_ai_mode_ignores_source_left_even_with_asis(self):
        """mode="ai"：即使附了原圖，那張圖只是生圖參考，成品像素仍是模型重繪的——
        這條路一律不接 F43。B55 修法甲（2026-09-20）把 provider="gpt" 的保護路徑
        換成透明底標題圖層（三道閘，見 compose.overlay_title_layer_over_cover_band），
        不是本測試要驗的東西；改用 provider="gemini" 走舊的差異遮罩路徑
        （compose.restore_photo_outside_title_band），patch 掉讓它單純直通，只驗證
        source_left 有沒有被忽略——像素保證的機制細節見
        docs/f43-source-label-inventory.md。"""
        def fake_raw(image_req):
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(
                    _png_bytes(size=(1536, 864))
                ).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_raw), patch.object(
            main, "resolve_cover_visuals", return_value=("視覺", "視覺")
        ), patch.object(
            compose, "restore_photo_outside_title_band", side_effect=lambda base_png, ai_png, **kw: ai_png
        ):
            res = self._post(mode="ai", provider="gemini", source_left="美聯社")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["source_left"], "")


class TenCoverSplitEndpointSourceLabelTests(unittest.TestCase):
    """雙切（layout=split, mode=composite）端到端，含「只改文字」recompose。"""

    def _post(self, **overrides):
        body = {
            "title_left": "左標題", "title_right": "右標題", "layout": "split", "mode": "composite",
            "asis_left": _data_url(_png_bytes(size=(1600, 900), colour=RED)),
            "asis_right": _data_url(_png_bytes(size=(1600, 900), colour=BLUE)),
        }
        body.update(overrides)
        return client.post("/api/editor/cover", json=body, headers=_headers())

    def test_both_panels_can_carry_independent_sources(self):
        res = self._post(source_left="美聯社", source_right="路透社")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["left_is_ai"])
        self.assertFalse(data["right_is_ai"])
        self.assertEqual(data["source_left"], "美聯社")
        self.assertEqual(data["source_right"], "路透社")

    def test_one_ai_panel_ignores_its_own_source_text_only(self):
        """左格生底圖（is_ai=True）、右格原圖放置：互斥判定各自獨立。"""
        with patch.object(
            main, "_cover_panel_image",
            return_value=(_png_bytes(size=(1600, 900), colour=RED), "fake-model"),
        ), patch.object(main, "resolve_cover_visuals", return_value=("左視覺", "右視覺")):
            res = self._post(asis_left="", source_left="美聯社", source_right="路透社")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["left_is_ai"])
        self.assertFalse(data["right_is_ai"])
        self.assertEqual(data["source_left"], "")
        self.assertEqual(data["source_right"], "路透社")

    def test_recompose_only_changing_text_keeps_the_source_label(self):
        """「只改文字」：前端把上一次的壓字前底圖與 background_is_ai 原樣帶回，
        source_left／source_right 是使用者自己打的字段，同一欄位重送即可
        （不像 background_is_ai 需要另開一個 carry-forward 欄位，見 TenCoverRequest
        的欄位註解）。"""
        first = self._post(source_left="美聯社", source_right="路透社")
        self.assertEqual(first.status_code, 200, first.text)
        first_data = first.json()
        second = client.post(
            "/api/editor/cover",
            json={
                "title_left": "改過的左標題", "title_right": "右標題",
                "layout": "split", "mode": "composite",
                "background_image_base64": first_data["background_image_base64"],
                "background_mime_type": first_data["background_mime_type"],
                "background_is_ai": first_data["left_is_ai"],
                "background_right_is_ai": first_data["right_is_ai"],
                "source_left": "美聯社", "source_right": "路透社",
            },
            headers=_headers(),
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_data = second.json()
        self.assertEqual(second_data["model"], "ten-cover:recomposite")
        self.assertEqual(second_data["source_left"], "美聯社")
        self.assertEqual(second_data["source_right"], "路透社")


if __name__ == "__main__":
    unittest.main()
