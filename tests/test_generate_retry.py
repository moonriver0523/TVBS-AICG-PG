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

    def test_every_call_carries_a_timeout(self):
        """單次呼叫一定要有上限（2026-09-10 線上事故）。

        沒有的話走 SDK 預設 600 秒——比整體死線 230 秒與 Cloud Run 的 300 秒都長，
        一通卡住的上游請求就會讓前端停在 35%（消化階段的上限值）永遠不動，
        連錯誤訊息都沒有。死線只在兩次 attempt 之間檢查，擋不住第一通就卡死。
        """
        _, _, create = self.call_with([ok_response()])
        timeout = create.call_args.kwargs.get("timeout")
        self.assertIsNotNone(timeout, "消化呼叫沒帶 timeout，卡住就會拖到 Cloud Run 斷線")
        self.assertLessEqual(timeout, main.DIGEST_DEADLINE_SECONDS)

    def test_a_hung_upstream_still_returns_an_error_in_time(self):
        """每一通都跑滿 timeout 時，要在 Cloud Run 的 300 秒之前回一個看得懂的錯誤。

        用假時鐘讓每次 attempt 真的花掉 DIGEST_TIMEOUT_SECONDS，才驗得到死線有沒有
        在「這一次跑滿也來不及」的時候停手——DIGEST_ATTEMPTS(5) × 90 秒是 450 秒，
        照跑就會撞上 Cloud Run 的 300 秒斷線，使用者看到的就是進度條卡在 35%。
        """
        from openai import APITimeoutError

        now = [0.0]

        def tick(*_args, **_kwargs):
            now[0] += main.DIGEST_TIMEOUT_SECONDS
            raise APITimeoutError(request=httpx.Request("POST", "https://openrouter.ai/api/v1"))

        with patch.object(main.time, "monotonic", lambda: now[0]):
            result, exc, create = self.call_with(tick)
        self.assertIsNone(result)
        self.assertIsNotNone(exc)
        self.assertLess(now[0], 300, "重試跑太久，會撞上 Cloud Run 的 300 秒斷線")
        self.assertLess(create.call_count, main.DIGEST_ATTEMPTS, "死線沒有提早停手")

    def test_success_on_first_try_does_not_sleep(self):
        result, exc, create = self.call_with([ok_response()])
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 1)
        self.sleep.assert_not_called()

    def test_markdown_fenced_json_is_accepted_without_retry(self):
        fenced = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
                    ),
                    finish_reason="stop",
                )
            ]
        )
        result, exc, create = self.call_with([fenced])
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(result.chart_type, "資料圖表")


if __name__ == "__main__":
    unittest.main()
