"""消化的 provider 路由（2026-09-11）。

使用者回報消化階段常撞上游過載，選定的對策是「同模型換 provider」：
claude-sonnet-5 在 OpenRouter 上有九個端點，第一方過載時讓 AWS／Azure／Bedrock
接手，換 provider 不換模型，品質零風險（換模型才有風險——2026-09-05 實測
gpt-5.6-terra 會頻道洩漏＋吐賭博垃圾字串）。
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import BadRequestError

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402


def ok_response():
    message = SimpleNamespace(content=json.dumps({"ok": 1}))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=None,
        model="anthropic/claude-sonnet-5",
    )


def reasoning_rejected():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1")
    response = httpx.Response(400, request=request)
    return BadRequestError(
        "unsupported parameter: reasoning", response=response, body=None
    )


class ProviderOrderTests(unittest.TestCase):
    def test_the_first_party_endpoint_leads_the_order(self):
        """預設路由以價格優先，實測 2026-09-11 連三次都落在 claude-on-aws。
        要診斷就得先讓「正常情況走哪一條」是確定的。"""
        with patch.object(main, "DIGEST_BACKEND", "openrouter"):
            body = main.digest_provider_body()
        self.assertEqual(body["provider"]["order"][0], "anthropic")

    def test_fallbacks_stay_open(self):
        """關掉 fallback 等於把「過載時還有別條路」這個唯一的好處丟掉。"""
        with patch.object(main, "DIGEST_BACKEND", "openrouter"):
            body = main.digest_provider_body()
        self.assertIs(body["provider"]["allow_fallbacks"], True)

    def test_more_than_one_endpoint_is_listed(self):
        """只列一條 = 沒有換 provider 這回事，整條修正就白做了。"""
        self.assertGreater(len(main.DIGEST_PROVIDER_ORDER), 1)

    def test_vertex_is_not_in_the_list(self):
        """實查 /models/anthropic/claude-sonnet-5/endpoints：三個 google-vertex
        端點的 supported_parameters 都沒有 structured_outputs，而這條線全程用
        strict json_schema。OpenRouter 文件說參數偏好「永遠不會把模型從候選清單
        移除」，所以不能賭它會自己避開。"""
        for slug in main.DIGEST_PROVIDER_ORDER:
            self.assertNotIn("vertex", slug)

    def test_non_openrouter_backends_send_nothing(self):
        """provider 是 OpenRouter 的路由欄位，送給原生 OpenAI／Gemini 會 400。"""
        for backend in ("native", "gemini"):
            with self.subTest(backend=backend):
                with patch.object(main, "DIGEST_BACKEND", backend):
                    self.assertEqual(main.digest_provider_body(), {})

    def test_an_empty_setting_disables_it(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), \
                patch.object(main, "DIGEST_PROVIDER_ORDER", []):
            self.assertEqual(main.digest_provider_body(), {})


class ProviderReachesTheCallTests(unittest.TestCase):
    """組好的順序真的要送出去——常數對但沒接上等於沒做。"""

    def call_once(self, side_effect):
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=None))
        )
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            outcome = side_effect[len(calls) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        client.chat.completions.create = create
        with patch.object(main, "openai_client", client), \
                patch.object(main, "DIGEST_BACKEND", "openrouter"), \
                patch.object(main, "log_digest_usage", lambda *a, **k: None):
            main.digest_completion(
                model="anthropic/claude-sonnet-5",
                system_prompt="s",
                news_text="n",
                max_output_tokens=main.DIGEST_MAX_TOKENS,
                schema_name="x",
                schema={"type": "object"},
            )
        return calls

    def test_the_provider_order_is_sent(self):
        calls = self.call_once([ok_response()])
        self.assertEqual(
            calls[0]["extra_body"]["provider"]["order"], main.DIGEST_PROVIDER_ORDER
        )

    def test_reasoning_rides_along_in_the_same_extra_body(self):
        calls = self.call_once([ok_response()])
        extra = calls[0]["extra_body"]
        self.assertIn("provider", extra)
        self.assertIn("reasoning", extra)

    def test_dropping_the_reasoning_cap_keeps_the_provider_order(self):
        """模型不吃 reasoning 上限時舊碼整包 pop extra_body，會把換 provider 的
        能力一起丟掉——而那正是撞過載時唯一還有用的東西。"""
        calls = self.call_once([reasoning_rejected(), ok_response()])
        self.assertNotIn("reasoning", calls[1]["extra_body"])
        self.assertEqual(
            calls[1]["extra_body"]["provider"]["order"], main.DIGEST_PROVIDER_ORDER
        )


if __name__ == "__main__":
    unittest.main()
