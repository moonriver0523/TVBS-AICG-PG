"""/api/news-image/generate：一次到位端點（給 WorkCord 等外部整合方呼叫）。

這支端點與 LINE Bot 共用同一個 generate_news_image()，測試重點：
1. API key 驗證（未設定 fail-closed、錯誤金鑰拒絕、正確金鑰放行）
2. 組出的 prompt 確實含安全框規則（不是把 /api/generate 的半成品直接丟給生圖）
3. title 從 variable 的 [標題] 行正確擷取

背景函式全程 patch main.generate / main.generate_image，不呼叫任何付費 API。
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import (  # noqa: E402
    GenerateResponse,
    ImageGenerateResponse,
    NewsImageGenerateRequest,
    _extract_title,
    app,
    generate_news_image,
)

client = TestClient(app)

# 長度須通過 input_filter 的最短門檻（15 個資訊性字元）
NEWS = "熊本強震重創九州 當地疏散逾21萬人 多處道路中斷"

FAKE_DIGEST = GenerateResponse(
    style="S",
    structure="T",
    variable="[標題] 熊本強震重創九州\n[內文小標] 疏散逾21萬人",
    chart_type="資料圖表",
)
FAKE_IMAGE = ImageGenerateResponse(
    image_data_base64="ZmFrZQ==", mime_type="image/png", model="fake-model"
)


class TitleExtractionTests(unittest.TestCase):
    def test_extracts_title_line(self):
        self.assertEqual(_extract_title("[標題] 熊本強震重創九州\n下一行"), "熊本強震重創九州")

    def test_missing_title_returns_empty_string(self):
        self.assertEqual(_extract_title("沒有標題標記的內容"), "")


class GenerateNewsImageTests(unittest.TestCase):
    def setUp(self):
        patcher_generate = patch.object(main, "generate", return_value=FAKE_DIGEST)
        patcher_image = patch.object(main, "generate_image", return_value=FAKE_IMAGE)
        self.mock_generate = patcher_generate.start()
        self.mock_image = patcher_image.start()
        self.addCleanup(patcher_generate.stop)
        self.addCleanup(patcher_image.stop)

    def test_response_fields_populated(self):
        result = generate_news_image(NewsImageGenerateRequest(news_text=NEWS))
        self.assertEqual(result.image_data_base64, "ZmFrZQ==")
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual(result.model, "fake-model")
        self.assertEqual(result.title, "熊本強震重創九州")
        self.assertTrue(result.prompt_version)

    def test_prompt_sent_to_image_gen_includes_safe_area_rules(self):
        generate_news_image(NewsImageGenerateRequest(news_text=NEWS))
        sent_prompt = self.mock_image.call_args[0][0].prompt
        self.assertIn("EMPTY MARGIN RULES", sent_prompt)
        self.assertIn("FORBIDDEN terms/effects", sent_prompt)

    def test_editor_role_uses_editor_text_rules(self):
        generate_news_image(NewsImageGenerateRequest(news_text=NEWS, role="編輯"))
        sent_prompt = self.mock_image.call_args[0][0].prompt
        self.assertIn("Must be split into exactly two lines", sent_prompt)

    def test_provider_is_forwarded_to_image_request(self):
        generate_news_image(NewsImageGenerateRequest(news_text=NEWS, provider="gpt"))
        sent_req = self.mock_image.call_args[0][0]
        self.assertEqual(sent_req.provider, "gpt")
        self.assertTrue(sent_req.prompt.startswith("Generate an image:"))

    def test_safe_frame_defaults_to_21x9(self):
        """2026-07-30：用 4 個真實生成樣本驗證過——safe_frame 開啟時 21:9 的左右
        留白穩定落在官方需求 ±1pp 內，取代 16:9 慣性多出一倍的左右留白，
        使用者已拍板接受切換。這裡釘住『沒有明確指定時』的自動選擇邏輯。"""
        generate_news_image(NewsImageGenerateRequest(news_text=NEWS, safe_frame=True))
        sent_req = self.mock_image.call_args[0][0]
        self.assertEqual(sent_req.aspect_ratio, "21:9")
        self.assertIn("Aspect ratio: 21:9", sent_req.prompt)

    def test_non_safe_frame_stays_at_16x9(self):
        """safe_frame=False 時沒有後端置框，21:9 的幾何優勢不適用，不該跟著改。"""
        generate_news_image(NewsImageGenerateRequest(news_text=NEWS, safe_frame=False))
        sent_req = self.mock_image.call_args[0][0]
        self.assertEqual(sent_req.aspect_ratio, "16:9")

    def test_explicit_aspect_ratio_overrides_the_safe_frame_default(self):
        """呼叫端明確指定時必須尊重那個值，自動選擇只在沒指定時生效。"""
        generate_news_image(
            NewsImageGenerateRequest(news_text=NEWS, safe_frame=True, aspect_ratio="4:3")
        )
        sent_req = self.mock_image.call_args[0][0]
        self.assertEqual(sent_req.aspect_ratio, "4:3")

    def test_editor_safe_frame_uses_16x9_gpt_and_editor_profile(self):
        generate_news_image(
            NewsImageGenerateRequest(
                news_text=NEWS, role="編輯", safe_frame=True, provider="gemini"
            )
        )
        sent_req = self.mock_image.call_args[0][0]
        self.assertEqual(sent_req.aspect_ratio, "16:9")
        self.assertEqual(sent_req.provider, "gpt")
        self.assertEqual(sent_req.safe_frame_profile, "編輯")
        self.assertIn("Aspect ratio: 16:9", sent_req.prompt)


class InputFilterGuardTests(unittest.TestCase):
    """垃圾輸入必須在任何付費呼叫（digest／生圖）之前就被 400 擋下。"""

    def setUp(self):
        import input_filter

        input_filter.reset_state()
        self.addCleanup(input_filter.reset_state)
        patcher_generate = patch.object(main, "generate", return_value=FAKE_DIGEST)
        patcher_image = patch.object(main, "generate_image", return_value=FAKE_IMAGE)
        self.mock_generate = patcher_generate.start()
        patcher_image.start()
        self.addCleanup(patcher_generate.stop)
        self.addCleanup(patcher_image.stop)

    def test_garbage_input_is_rejected_before_any_paid_call(self):
        from fastapi import HTTPException

        for bad in ("短", "😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀"):
            with self.subTest(bad=bad):
                with self.assertRaises(HTTPException) as ctx:
                    generate_news_image(NewsImageGenerateRequest(news_text=bad))
                self.assertEqual(ctx.exception.status_code, 400)
        self.mock_generate.assert_not_called()

    def test_no_client_id_means_no_rate_limit(self):
        # LINE 路徑刻意不傳 client_id（已在 line_bot 做過頻率限制），連打不受限
        generate_news_image(NewsImageGenerateRequest(news_text=NEWS))
        generate_news_image(NewsImageGenerateRequest(news_text=NEWS))
        self.assertEqual(self.mock_generate.call_count, 2)

    def test_client_id_opts_into_rate_limiting(self):
        from fastapi import HTTPException

        generate_news_image(NewsImageGenerateRequest(news_text=NEWS, client_id="workcord"))
        with self.assertRaises(HTTPException) as ctx:
            generate_news_image(NewsImageGenerateRequest(news_text=NEWS, client_id="workcord"))
        self.assertEqual(ctx.exception.status_code, 400)
        self.mock_generate.assert_called_once()


class EndpointAuthTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("NEWS_IMAGE_API_KEY")
        patcher_generate = patch.object(main, "generate", return_value=FAKE_DIGEST)
        patcher_image = patch.object(main, "generate_image", return_value=FAKE_IMAGE)
        patcher_generate.start()
        patcher_image.start()
        self.addCleanup(patcher_generate.stop)
        self.addCleanup(patcher_image.stop)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("NEWS_IMAGE_API_KEY", None)
        else:
            os.environ["NEWS_IMAGE_API_KEY"] = self._saved

    def call(self, headers=None):
        return client.post(
            "/api/news-image/generate",
            json={"news_text": NEWS},
            headers=headers or {},
        )

    def test_unset_key_fails_closed(self):
        os.environ.pop("NEWS_IMAGE_API_KEY", None)
        response = self.call()
        self.assertEqual(response.status_code, 503)

    def test_wrong_key_is_rejected(self):
        os.environ["NEWS_IMAGE_API_KEY"] = "correct-key"
        response = self.call(headers={"X-API-Key": "wrong-key"})
        self.assertEqual(response.status_code, 401)

    def test_missing_key_header_is_rejected(self):
        os.environ["NEWS_IMAGE_API_KEY"] = "correct-key"
        response = self.call()
        self.assertEqual(response.status_code, 401)

    def test_correct_key_succeeds(self):
        os.environ["NEWS_IMAGE_API_KEY"] = "correct-key"
        response = self.call(headers={"X-API-Key": "correct-key"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["title"], "熊本強震重創九州")
        self.assertEqual(body["image_data_base64"], "ZmFrZQ==")


if __name__ == "__main__":
    unittest.main()
