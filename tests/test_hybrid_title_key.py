"""hybrid_digest 的 title_key 正規化：前端靠字串比對定位上色，
對不上主標題的重點詞一律丟棄，寧可整條白字也不要比對失敗。

配色本身不在測試範圍——顏色由前端 PALETTE 決定，AI 只負責指出語意。
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import HybridDigestRequest, hybrid_digest  # noqa: E402

BASE_PAYLOAD = {
    "title": "美國臨時關稅將到期",
    "title_key": "關稅",
    "subtitle": "本月二十四日",
    "items": [
        {"label": "現行稅率", "value": "10%", "change": "", "direction": "flat"},
        {"label": "預期新稅率", "value": "12.5%", "change": "2.5%", "direction": "up"},
        {"label": "到期日", "value": "24日", "change": "", "direction": "flat"},
    ],
    "source": "資料來源：Reuters",
    "visual_subject": "美國國會大廈外觀，深藍色調",
}


def response_with(**overrides):
    payload = dict(BASE_PAYLOAD, **overrides)
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")]
    )


class HybridTitleKeyTests(unittest.TestCase):
    def setUp(self):
        self.request = HybridDigestRequest(news_text="素材")

    def digest_with(self, response):
        with patch.object(
            main.openai_client.chat.completions, "create", return_value=response
        ):
            return hybrid_digest(self.request)

    def test_keeps_key_that_is_substring_of_title(self):
        result = self.digest_with(response_with())
        self.assertEqual(result.title_key, "關稅")

    def test_drops_key_the_model_rephrased(self):
        # 模型改寫成標題裡沒有的詞，前端會找不到位置
        result = self.digest_with(response_with(title_key="臨時關稅措施"))
        self.assertEqual(result.title_key, "")

    def test_drops_key_wrapped_in_brackets(self):
        # 括號標記是這個專案的老問題，加了標記就不再是子字串
        result = self.digest_with(response_with(title_key="<關稅>"))
        self.assertEqual(result.title_key, "")

    def test_missing_key_becomes_empty_string(self):
        payload = dict(BASE_PAYLOAD)
        del payload["title_key"]
        message = SimpleNamespace(content=json.dumps(payload))
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")]
        )
        result = self.digest_with(response)
        self.assertEqual(result.title_key, "")

    def test_whitespace_only_key_becomes_empty_string(self):
        result = self.digest_with(response_with(title_key="  "))
        self.assertEqual(result.title_key, "")


if __name__ == "__main__":
    unittest.main()
