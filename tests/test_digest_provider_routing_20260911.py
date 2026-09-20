"""消化的 provider 路由（2026-09-11 起，2026-09-16 D21 改法)。

使用者回報消化階段常撞上游過載，選定的對策是「同模型換 provider」而不是換模型
（換模型才有品質風險——2026-09-05 實測 gpt-5.6-terra 會頻道洩漏＋吐賭博垃圾字串）。

2026-09-11 版本寫死一份 Anthropic 家族端點白名單；2026-09-16 D21 換主模型成
google/gemini-3.8-flash 後，那份白名單完全對不上，改用 OpenRouter 的統一參數
provider.require_parameters：讓它自己只挑真的吃得下本次請求參數（reasoning、
strict json_schema 等）的端點，不用替每個新模型重新盤點白名單。這同時解掉帳本
B74——舊白名單裡的 azure/global、amazon-bedrock/global 兩個端點其實不支援
structured_outputs，過載 fallback 過去時 strict schema 會被靜默丟棄。
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
        model="google/gemini-3.8-flash",
    )


def reasoning_rejected():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1")
    response = httpx.Response(400, request=request)
    return BadRequestError(
        "unsupported parameter: reasoning", response=response, body=None
    )


class ProviderRequireParametersTests(unittest.TestCase):
    def test_require_parameters_is_sent(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"):
            body = main.digest_provider_body()
        self.assertIs(body["provider"]["require_parameters"], True)

    def test_fallbacks_stay_open(self):
        """關掉 fallback 等於把「過載時還有別條路」這個唯一的好處丟掉。"""
        with patch.object(main, "DIGEST_BACKEND", "openrouter"):
            body = main.digest_provider_body()
        self.assertIs(body["provider"]["allow_fallbacks"], True)

    def test_no_hardcoded_endpoint_whitelist_remains(self):
        """D21 的重點就是不要再維護一份會跟著換模型過期的端點清單。"""
        self.assertFalse(hasattr(main, "DIGEST_PROVIDER_ORDER"))

    def test_non_openrouter_backends_send_nothing(self):
        """provider 是 OpenRouter 的路由欄位，送給原生 OpenAI／Gemini 會 400。"""
        for backend in ("native", "gemini"):
            with self.subTest(backend=backend):
                with patch.object(main, "DIGEST_BACKEND", backend):
                    self.assertEqual(main.digest_provider_body(), {})

    def test_disabling_the_flag_turns_it_off(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), \
                patch.object(main, "DIGEST_PROVIDER_REQUIRE_PARAMETERS", False):
            self.assertEqual(main.digest_provider_body(), {})


class ProviderReachesTheCallTests(unittest.TestCase):
    """組好的 provider body 真的要送出去——常數對但沒接上等於沒做。"""

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
                model="google/gemini-3.8-flash",
                system_prompt="s",
                news_text="n",
                max_output_tokens=main.DIGEST_MAX_TOKENS,
                schema_name="x",
                schema={"type": "object"},
            )
        return calls

    def test_the_provider_body_is_sent(self):
        calls = self.call_once([ok_response()])
        self.assertEqual(
            calls[0]["extra_body"]["provider"],
            {"require_parameters": True, "allow_fallbacks": True},
        )

    def test_reasoning_rides_along_in_the_same_extra_body(self):
        calls = self.call_once([ok_response()])
        extra = calls[0]["extra_body"]
        self.assertIn("provider", extra)
        self.assertIn("reasoning", extra)

    def test_dropping_the_reasoning_effort_keeps_the_provider_body(self):
        """模型不吃 reasoning effort 時舊碼整包 pop extra_body，會把換 provider 的
        能力一起丟掉——而那正是撞過載時唯一還有用的東西。"""
        calls = self.call_once([reasoning_rejected(), ok_response()])
        self.assertNotIn("reasoning", calls[1]["extra_body"])
        self.assertEqual(
            calls[1]["extra_body"]["provider"],
            {"require_parameters": True, "allow_fallbacks": True},
        )


if __name__ == "__main__":
    unittest.main()
