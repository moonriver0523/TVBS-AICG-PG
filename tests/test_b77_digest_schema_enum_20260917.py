"""B77：消化 schema 不准把 enum 掛在非字串型別上，以及這條路徑的有界重試。

2026-09-17 線上故障。D21 把消化主模型換成 google/gemini-3.8-flash、並加上
provider.require_parameters=true（強制路由到真的照 schema 執行的端點）之後，
十點雙切與 YT 整點的 AI 消化標題每次都回 502，其餘版型正常。

受控 A/B（同一段新聞、同一端點、相隔數秒）把變因隔離乾淨：
- 有 "topics": {"type": "integer", "enum": [1, 2]} 的兩個 schema → 502，2.6 秒
- 無 enum 但有陣列欄位的 ten_cover_full → 200
- 無 enum 但有兩個字串標題欄位的 yt_vstrip → 200
Gemini 的 responseSchema 子集只吃字串 enum，strict 之下整包請求被上游退成 400。

當時沒有任何測試擋得住，因為 cover-titles 的測試全是 mock，沒有人檢查送出去的
schema 長什麼樣。所以這裡守的是**整類問題**（任何非字串型別上的 enum），
不是只釘 topics 這一個欄位。
"""

import os
import unittest
from unittest.mock import patch

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import editor_formats  # noqa: E402
import main  # noqa: E402


def _status_error(cls, status):
    request = httpx.Request("POST", "https://openrouter.ai/api/v1")
    response = httpx.Response(status, request=request)
    return cls("boom", response=response, body=None)


def _walk(node, path="$"):
    """走訪 JSON schema，回傳 (路徑, 子 schema) 每一個節點。"""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


DIGEST_SCHEMAS = {
    "ten_cover": editor_formats.COVER_TITLE_DIGEST_SCHEMA_TEN,
    "ten_cover_full": editor_formats.COVER_TITLE_DIGEST_SCHEMA_TEN_FULL,
    "yt_hourly": editor_formats.COVER_TITLE_DIGEST_SCHEMA_YT_HOURLY,
    "yt_vstrip": editor_formats.VSTRIP_TITLE_DIGEST_SCHEMA,
    "yt_news": editor_formats.COVER_TITLE_DIGEST_SCHEMA_YT,
}


class SchemaEnumTests(unittest.TestCase):
    def test_no_enum_on_non_string_type(self):
        for name, schema in DIGEST_SCHEMAS.items():
            for path, node in _walk(schema):
                if "enum" not in node:
                    continue
                self.assertEqual(
                    node.get("type"),
                    "string",
                    f"{name} 的 {path} 把 enum 掛在 {node.get('type')!r} 上；"
                    "Gemini 的 responseSchema 只吃字串 enum，strict 之下會被退成 400",
                )

    def test_topics_still_declared_and_required(self):
        """拿掉的是 enum，不是欄位——prompt 拿 topics 當「先決定幾則」的腳手架。"""
        for name in ("ten_cover", "yt_hourly"):
            schema = DIGEST_SCHEMAS[name]
            self.assertEqual(schema["properties"]["topics"], {"type": "integer"}, name)
            self.assertIn("topics", schema["required"], name)


class TransientClassificationTests(unittest.TestCase):
    def test_deterministic_errors_are_not_retried(self):
        for status, cls in ((400, BadRequestError),):
            with self.subTest(status=status):
                self.assertFalse(main._is_transient_upstream(_status_error(cls, status)))

    def test_rate_limit_is_not_retried(self):
        exc = _status_error(RateLimitError, 429)
        self.assertFalse(main._is_transient_upstream(exc))

    def test_upstream_5xx_and_connection_errors_are_retried(self):
        self.assertTrue(main._is_transient_upstream(_status_error(InternalServerError, 500)))
        request = httpx.Request("POST", "https://openrouter.ai/api/v1")
        self.assertTrue(main._is_transient_upstream(APIConnectionError(request=request)))

    def test_timeout_is_not_retried(self):
        """APITimeoutError 是 APIConnectionError 的子類，必須先擋下來。

        放行的話一次耗盡＝3 × 90 秒＋backoff ≈ 272 秒，外層字數重試再來一輪會破
        460 秒，直接撞破 Zeabur 的 300 秒上限（2026-09-10 已經出過這個事故）。
        """
        request = httpx.Request("POST", "https://openrouter.ai/api/v1")
        self.assertFalse(main._is_transient_upstream(APITimeoutError(request=request)))


class CoverTitleRetryTests(unittest.TestCase):
    def test_transient_failure_is_retried_then_succeeds(self):
        calls = []

        def flaky(**kwargs):
            calls.append(kwargs)
            if len(calls) < 3:
                raise _status_error(InternalServerError, 502)
            return "ok"

        with patch.object(main, "digest_completion", flaky), \
                patch.object(main.time, "sleep", lambda _s: None):
            self.assertEqual(main._cover_title_completion(model="m"), "ok")
        self.assertEqual(len(calls), 3)

    def test_schema_400_fails_immediately_without_retry(self):
        calls = []

        def always_400(**kwargs):
            calls.append(kwargs)
            raise _status_error(BadRequestError, 400)

        with patch.object(main, "digest_completion", always_400), \
                patch.object(main.time, "sleep", lambda _s: None):
            with self.assertRaises(BadRequestError):
                main._cover_title_completion(model="m")
        self.assertEqual(len(calls), 1, "確定性錯誤重試只會白等並多燒額度")

    def test_retry_budget_is_capped(self):
        calls = []

        def always_502(**kwargs):
            calls.append(kwargs)
            raise _status_error(InternalServerError, 502)

        with patch.object(main, "digest_completion", always_502), \
                patch.object(main.time, "sleep", lambda _s: None):
            with self.assertRaises(InternalServerError):
                main._cover_title_completion(model="m")
        self.assertEqual(len(calls), main.COVER_TITLE_UPSTREAM_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
