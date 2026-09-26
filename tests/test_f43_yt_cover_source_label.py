"""F43（2026-09-20 晚間補接）：「畫面來源」標籤推廣到 YT 封面四版型
（news／hourly／hot／live24）。

盤點依據見 docs/f43-source-label-inventory.md：`_yt_cover_background` 對 asis 圖
（`compose.crop_background_16x9`／`compose.split_backgrounds`）回傳 `is_ai=False`，
跟十點不一樣 composite 模式同一等級的保證——asis 圖直接進 compose 函式，完全不經
過任何生圖模型。歷史上 `title_mode="ai"` 未接；B107（2026-09-26 使用者裁決）已改成
AI 標題不影響 AI 標籤，完整的新矩陣見 test_b107_cover_original_no_ai_label.py。

三塊測試：
1. compose 層：四個合成函式的 source_text／ai_note 互斥判定
2. 端到端：四種 layout 各自的 asis + 來源名 / AI 生底圖時忽略
3. 回應欄位：source_text 只在 is_ai=False 時回顯
"""

import base64
import io
import os
import unittest
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "yt-f43-test-key")

import compose  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)
RED = (200, 30, 30)


def _headers() -> dict:
    # 整包跑時其他測試模組會在 import 期改寫 NEWS_IMAGE_API_KEY，執行時再讀才對得上
    # （同 tests/test_ten_cover.py 的 _headers() 慣例）。
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}


def _png_bytes(size=(1200, 700), colour=RED) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _asis_payload(**overrides):
    # 標題沿用既有測試用過、確認一個空格就能本地分段、不會落到 AI 斷句模型的例子
    # （見 tests/test_yt_cover.py::EndpointTests.test_asis_cover_end_to_end_without_any_model）。
    payload = {
        "title": "新北診所爆C肝群聚 11人確診疾管署說明",
        "title_mode": "composite",
        "reference_images": [{"data_url": _data_url(_png_bytes()), "purpose": "asis"}],
    }
    payload.update(overrides)
    return payload


class ComposeMutualExclusionTests(unittest.TestCase):
    """四個合成函式各自的 source_text／ai_note 互斥判定，不經 API。"""

    def test_compose_yt_cover_ai_wins(self):
        with patch.object(compose, "_draw_ai_note") as spy:
            compose.compose_yt_cover(
                _png_bytes(), line1="標題", line2="副標", date_text="2026/09/20",
                ai_note=True, source_text="美聯社",
            )
        texts = [call.kwargs.get("text", compose.YT_AI_NOTE) for call in spy.call_args_list]
        self.assertEqual(texts, [compose.YT_AI_NOTE])

    def test_compose_yt_cover_source_text_draws_when_not_ai(self):
        with patch.object(compose, "_draw_ai_note") as spy:
            compose.compose_yt_cover(
                _png_bytes(), line1="標題", line2="副標", date_text="2026/09/20",
                ai_note=False, source_text="美聯社",
            )
        self.assertEqual(spy.call_args.kwargs.get("text"), "畫面來源：美聯社")

    def test_compose_yt_cover_neither_draws_nothing(self):
        with patch.object(compose, "_draw_ai_note") as spy:
            compose.compose_yt_cover(
                _png_bytes(), line1="標題", line2="副標", date_text="2026/09/20",
                ai_note=False, source_text="",
            )
        spy.assert_not_called()

    def test_compose_yt_hourly_cover_mutual_exclusion(self):
        with patch.object(compose, "_draw_ai_note") as spy:
            compose.compose_yt_hourly_cover(
                _png_bytes(), line1="標題", line2="副標", date_text="2026/09/20",
                ai_note=True, source_text="路透社",
            )
        self.assertEqual(
            [c.kwargs.get("text", compose.YT_AI_NOTE) for c in spy.call_args_list],
            [compose.YT_AI_NOTE],
        )
        with patch.object(compose, "_draw_ai_note") as spy:
            compose.compose_yt_hourly_cover(
                _png_bytes(), line1="標題", line2="副標", date_text="2026/09/20",
                ai_note=False, source_text="路透社",
            )
        self.assertEqual(spy.call_args.kwargs.get("text"), "畫面來源：路透社")

    def test_compose_yt_hot_cover_mutual_exclusion(self):
        with patch.object(compose, "_draw_ai_note") as spy:
            compose.compose_yt_hot_cover(
                _png_bytes(), line1="標題", line2="副標",
                ai_note=True, source_text="法新社",
            )
        self.assertEqual(
            [c.kwargs.get("text", compose.YT_AI_NOTE) for c in spy.call_args_list],
            [compose.YT_AI_NOTE],
        )
        with patch.object(compose, "_draw_ai_note") as spy:
            compose.compose_yt_hot_cover(
                _png_bytes(), line1="標題", line2="副標",
                ai_note=False, source_text="法新社",
            )
        self.assertEqual(spy.call_args.kwargs.get("text"), "畫面來源：法新社")

    def test_compose_yt_live24_cover_mutual_exclusion(self):
        with patch.object(compose, "_draw_live24_ai_note") as spy:
            compose.compose_yt_live24_cover(
                _png_bytes(), title="標題", date_text="2026.09.20",
                ai_note=True, source_text="中央社",
            )
        self.assertEqual(
            [c.kwargs.get("text", compose.YT_AI_NOTE) for c in spy.call_args_list],
            [compose.YT_AI_NOTE],
        )
        with patch.object(compose, "_draw_live24_ai_note") as spy:
            compose.compose_yt_live24_cover(
                _png_bytes(), title="標題", date_text="2026.09.20",
                ai_note=False, source_text="中央社",
            )
        self.assertEqual(spy.call_args.kwargs.get("text"), "畫面來源：中央社")

    def test_source_text_prefix_not_duplicated(self):
        with patch.object(compose, "_draw_ai_note") as spy:
            compose.compose_yt_cover(
                _png_bytes(), line1="標題", line2="副標", date_text="2026/09/20",
                ai_note=False, source_text="畫面來源：本台記者拍攝",
            )
        self.assertEqual(spy.call_args.kwargs.get("text"), "畫面來源：本台記者拍攝")


class EndpointNewsLayoutTests(unittest.TestCase):
    def test_asis_with_source_text_gets_the_label(self):
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post(
                "/api/editor/yt-cover", json=_asis_payload(source_text="美聯社"), headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["background_is_ai"])
        self.assertEqual(data["source_text"], "美聯社")

    def test_asis_without_source_text_reports_empty(self):
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json=_asis_payload(), headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["source_text"], "")

    def test_ai_generated_background_ignores_source_text(self):
        fake = main.ImageGenerateResponse(
            image_data_base64=base64.b64encode(_png_bytes((1536, 864))).decode("ascii"),
            mime_type="image/png", model="fake-model",
        )
        with patch.object(main, "generate_image_raw", return_value=fake), patch.object(
            main, "derive_yt_cover_plan", return_value={"visual": "一個場景", "portrait_subjects": []},
        ):
            res = client.post(
                "/api/editor/yt-cover",
                json={"title": "前段 後段", "title_mode": "composite", "source_text": "美聯社"},
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["background_is_ai"])
        self.assertEqual(data["source_text"], "")


class EndpointOtherLayoutsTests(unittest.TestCase):
    def test_hourly_layout_asis_with_source_text(self):
        payload = _asis_payload(layout="hourly", time_text="20:00")
        payload["source_text"] = "路透社"
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), patch.object(
            main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")
        ):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["background_is_ai"])
        self.assertEqual(data["source_text"], "路透社")

    def test_hot_layout_asis_with_source_text(self):
        payload = _asis_payload(layout="hot")
        payload["source_text"] = "法新社"
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), patch.object(
            main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")
        ):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["background_is_ai"])
        self.assertEqual(data["source_text"], "法新社")

    def test_live24_layout_asis_with_source_text(self):
        payload = {
            "title": "東北季風剩1天 假日回溫",
            "layout": "live24",
            "date_text": "2026.09.20",
            "title_mode": "composite",
            "reference_images": [{"data_url": _data_url(_png_bytes()), "purpose": "asis"}],
            "source_text": "中央氣象署",
        }
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), patch.object(
            main, "derive_yt_cover_plan", return_value={},
        ), patch.object(main, "supports_multiple_reference_images", return_value=True):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["background_is_ai"])
        self.assertEqual(data["source_text"], "中央氣象署")


class SolReviewRound2Tests(unittest.TestCase):
    """2026-09-20 獨立複查（gpt-5.6-sol）第二輪針對 F43 的兩項。"""

    BASE = {
        "title": "測試 標題",
        "layout": "news",
        "date_text": "2026.09.20",
        "title_mode": "composite",
    }

    def _recompose(self, body):
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", return_value={}):
            return client.post("/api/editor/yt-cover", json=body, headers=_headers())

    # ---- 第一項：不能讓前端漏帶旗標就把 AI 圖標成「畫面來源」----

    def test_client_supplied_background_plus_source_text_needs_an_explicit_flag(self):
        """sol 逐步重現的序列：AI 生的成品被當底圖送回來、`background_is_ai` 沒帶，
        Pydantic 預設 False ⇒ 在 AI 圖上貼出「畫面來源：路透社」。
        那是對觀眾的正面宣稱（這張畫面沒被動過），不能靠預設值決定。"""
        res = self._recompose({
            **self.BASE,
            "background_image_base64": base64.b64encode(_png_bytes()).decode(),
            "source_text": "路透社",
        })
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("background_is_ai", res.text)

    def test_explicitly_declaring_it_is_ai_wins_and_drops_the_source_label(self):
        res = self._recompose({
            **self.BASE,
            "background_image_base64": base64.b64encode(_png_bytes()).decode(),
            "background_is_ai": True,
            "source_text": "路透社",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["source_text"], "", "AI 標籤要贏，來源名不該回顯")

    def test_explicitly_declaring_it_is_not_ai_is_still_honoured(self):
        """明確送 False 仍照信——那是既有的信任模型，改成後端自行判定是待裁事項。
        這一題釘住「擋的是預設值，不是把 recompose 整條路關掉」。"""
        res = self._recompose({
            **self.BASE,
            "background_image_base64": base64.b64encode(_png_bytes()).decode(),
            "background_is_ai": False,
            "source_text": "路透社",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["source_text"], "路透社")

    def test_a_request_without_a_source_name_is_untouched_by_the_guard(self):
        """沒有要標來源就沒有正面宣稱，維持原本行為（不要求帶旗標）。"""
        res = self._recompose({
            **self.BASE,
            "background_image_base64": base64.b64encode(_png_bytes()).decode(),
        })
        self.assertEqual(res.status_code, 200, res.text)

    # ---- 第三項：長來源名的版位護欄 ----

    def test_a_long_source_name_shrinks_instead_of_covering_the_live_badge(self):
        """實測：預設字級下「畫面來源：」＋40 個全形字的底板是 (259,216)-(1858,268)，
        橫跨畫布 83%，蓋掉左上角 LIVE 章與日期板 (50,54)-(486,349)。"""
        width = compose.YT_CANVAS[0]
        min_left = round(width * compose.YT_NOTE_MIN_LEFT_RATIO)
        x1 = width - round(width * compose.YT_MARGIN_RATIO) - 12
        for name in ("美聯社", "字" * 12, "字" * 40):
            with self.subTest(name=name):
                text = compose.vstrip_source_text(name)
                _font, note_w = compose._fit_note_font(
                    text, x1 - min_left - 24, "左上角的 LIVE 章與日期"
                )
                self.assertGreaterEqual(
                    x1 - note_w - 24, min_left,
                    f"「{text}」的底板左緣越過了 {min_left}，會壓到 LIVE 章",
                )

    def test_a_source_name_that_cannot_fit_even_at_the_floor_is_rejected(self):
        with self.assertRaises(compose.ComposeError) as ctx:
            compose._fit_note_font("字" * 200, 300, "左上角的 LIVE 章與日期")
        self.assertIn("太長", str(ctx.exception))

    def test_the_default_ai_note_is_not_shrunk_at_all(self):
        """「AI示意圖」五個字本來就塞得下，護欄不該讓既有成品的字級變小。"""
        width, height = compose.YT_CANVAS
        min_left = round(width * compose.YT_NOTE_MIN_LEFT_RATIO)
        x1 = width - round(width * compose.YT_MARGIN_RATIO) - 12
        font, _w = compose._fit_note_font(compose.YT_AI_NOTE, x1 - min_left - 24, "x")
        self.assertEqual(font.size, round(height * compose.YT_AI_NOTE_SIZE_RATIO))


if __name__ == "__main__":
    unittest.main()
