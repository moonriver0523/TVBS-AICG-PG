"""/api/generate 的重試行為：上游偶發失敗與不合格式回傳都必須在後端吸收。

對照組是 hybrid_digest——重試圈涵蓋「呼叫＋解析」全程，
金鑰／用量類錯誤則不重試（重試也不會變好）。
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from openai import APIConnectionError, AuthenticationError

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import GenerateRequest, generate  # noqa: E402

VALID_PAYLOAD = {
    "style": "cinematic broadcast style",
    "structure": "three panels",
    "variable": "[標題]\n[內文]",
    "chart_type": "資料圖表",
}


def ok_response(payload=None):
    content = json.dumps(payload if payload is not None else VALID_PAYLOAD)
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def bad_json_response():
    message = SimpleNamespace(content="這不是 JSON，上游截斷了")
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="length")])


def connection_error():
    return APIConnectionError(request=httpx.Request("POST", "https://openrouter.ai/api/v1"))


def auth_error():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1")
    response = httpx.Response(401, request=request)
    return AuthenticationError("invalid key", response=response, body=None)


class GenerateRetryTests(unittest.TestCase):
    def setUp(self):
        self.request = GenerateRequest(news_text="素材", type_label="資料圖表")
        # 重試間隔在測試裡沒有意義，避免每個案例真的睡 3 秒
        sleep_patcher = patch.object(main.time, "sleep")
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def call_with(self, side_effect):
        with patch.object(
            main.openai_client.chat.completions, "create", side_effect=side_effect
        ) as create:
            try:
                result = generate(self.request)
            except HTTPException as exc:
                return None, exc, create
            return result, None, create

    def test_recovers_from_transient_api_error(self):
        result, exc, create = self.call_with(
            [connection_error(), connection_error(), ok_response()]
        )
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 3)
        self.assertEqual(result.chart_type, "資料圖表")
        self.assertEqual(result.structure, "three panels")

    def test_recovers_from_unparseable_response(self):
        # 只重試呼叫是不夠的：上游回 200 但內容不是 JSON 也必須重來
        result, exc, create = self.call_with([bad_json_response(), ok_response()])
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(result.style, "cinematic broadcast style")

    def test_gives_up_after_the_configured_number_of_attempts(self):
        result, exc, create = self.call_with(
            [connection_error()] * main.DIGEST_ATTEMPTS
        )
        self.assertIsNone(result)
        self.assertEqual(create.call_count, main.DIGEST_ATTEMPTS)
        self.assertEqual(exc.status_code, 502)
        self.assertIn("無法連線", exc.detail)

    def test_parse_failure_reports_parse_detail(self):
        result, exc, create = self.call_with(
            [bad_json_response()] * main.DIGEST_ATTEMPTS
        )
        self.assertIsNone(result)
        self.assertEqual(create.call_count, main.DIGEST_ATTEMPTS)
        self.assertEqual(exc.status_code, 502)
        self.assertEqual(exc.detail, "AI 回傳格式無法解析")

    def test_auth_error_is_not_retried(self):
        result, exc, create = self.call_with([auth_error(), ok_response()])
        self.assertIsNone(result)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(exc.status_code, 503)

    def test_success_on_first_try_does_not_sleep(self):
        result, exc, create = self.call_with([ok_response()])
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 1)
        self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
