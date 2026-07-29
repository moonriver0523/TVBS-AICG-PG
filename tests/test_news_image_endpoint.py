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
        result = generate_news_image(NewsImageGenerateRequest(news_text="素材"))
        self.assertEqual(result.image_data_base64, "ZmFrZQ==")
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual(result.model, "fake-model")
        self.assertEqual(result.title, "熊本強震重創九州")
        self.assertTrue(result.prompt_version)

    def test_prompt_sent_to_image_gen_includes_safe_area_rules(self):
        generate_news_image(NewsImageGenerateRequest(news_text="素材"))
        sent_prompt = self.mock_image.call_args[0][0].prompt
        self.assertIn("EMPTY MARGIN RULES", sent_prompt)
        self.assertIn("FORBIDDEN terms/effects", sent_prompt)

    def test_editor_role_uses_editor_text_rules(self):
        generate_news_image(NewsImageGenerateRequest(news_text="素材", role="編輯"))
        sent_prompt = self.mock_image.call_args[0][0].prompt
        self.assertIn("Must be split into exactly two lines", sent_prompt)

    def test_provider_is_forwarded_to_image_request(self):
        generate_news_image(NewsImageGenerateRequest(news_text="素材", provider="gpt"))
        sent_req = self.mock_image.call_args[0][0]
        self.assertEqual(sent_req.provider, "gpt")
        self.assertTrue(sent_req.prompt.startswith("Generate an image:"))


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
            json={"news_text": "素材"},
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
