"""B94（2026-09-22）：消化失敗要把上游的真話帶進紀錄。

DEV 後台 18:28–18:54 連倒五筆，後台看得到的只有
`provider_5xx · HTTP 502: AI 服務處理失敗，請確認模型權限或稍後重試`——
那句話是我們自己寫死的，OpenRouter 真正回了什麼整個被吞掉（只 print 到
stdout）。結果是額度不足、模型沒權限、provider 掛了三種完全不同的故障
長得一模一樣，每次都要再跑一次才能猜。

生圖那條早就把 OpenRouter 的 JSON 原文帶進訊息（2026-09-17 那筆 safety
system 的紀錄就看得到），消化這條補上同樣的待遇。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import main  # noqa: E402


class _FakeAPIError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class UpstreamErrorDetailTests(unittest.TestCase):
    def test_status_and_body_reach_the_message(self):
        detail = main.upstream_error_detail(
            _FakeAPIError('{"error":{"message":"Provider returned error","code":502}}', 502)
        )
        self.assertIn("上游 502", detail)
        self.assertIn("Provider returned error", detail)
        self.assertIn("AI 服務處理失敗", detail, "原本那句話要留著，只是後面多了證據")

    def test_the_three_failures_no_longer_look_identical(self):
        credits = main.upstream_error_detail(_FakeAPIError("Insufficient credits", 402))
        permission = main.upstream_error_detail(_FakeAPIError("Model not allowed for this key", 403))
        provider = main.upstream_error_detail(_FakeAPIError("Provider returned error", 502))
        self.assertEqual(len({credits, permission, provider}), 3)

    def test_connection_error_keeps_its_own_wording(self):
        from openai import APIConnectionError

        exc = APIConnectionError.__new__(APIConnectionError)
        self.assertEqual(main.upstream_error_detail(exc), "無法連線至 AI 服務，請稍後再試")

    def test_a_key_shaped_string_is_redacted(self):
        detail = main.upstream_error_detail(
            _FakeAPIError("bad key sk-or-v1-0123456789abcdef used", 401)
        )
        self.assertNotIn("sk-or-v1-0123456789abcdef", detail)
        self.assertIn("[已遮蔽]", detail)

    def test_a_huge_body_is_truncated(self):
        detail = main.upstream_error_detail(_FakeAPIError("x" * 5000, 502))
        self.assertLess(len(detail), main.UPSTREAM_DETAIL_MAX_CHARS + 120)
        self.assertTrue(detail.rstrip("）").endswith("…"))

    def test_newlines_are_flattened_so_the_admin_row_stays_one_line(self):
        detail = main.upstream_error_detail(_FakeAPIError("line one\n\n  line two", 502))
        self.assertNotIn("\n", detail)
        self.assertIn("line one line two", detail)

    def test_generic_upstream_status_survives_the_outer_proxy_status(self):
        from fastapi import HTTPException

        for upstream_status, outer_status, expected_type in (
            (403, 503, "provider_4xx"),
            (502, 503, "provider_5xx"),
        ):
            with self.subTest(upstream_status=upstream_status):
                detail = main.upstream_error_detail(
                    _FakeAPIError("provider detail", upstream_status)
                )
                self.assertIn(f"（{upstream_status}）", detail)
                meta = main.classify_generation_error(
                    HTTPException(status_code=outer_status, detail=detail)
                )
                self.assertEqual(meta["http_status"], upstream_status)
                self.assertEqual(meta["error_type"], expected_type)


class CreditsExhaustedStopsRetryingTests(unittest.TestCase):
    """B95：B94 上線後第一筆 DEV 失敗就寫出了真因——

        上游 402 · This request requires more credits, or fewer max_tokens.
        You requested up to 16000 tokens, but can only afford 15030.

    DEV 那把 OpenRouter 金鑰餘額見底，跟 B91 的 prompt 無關。但它走通用的
    APIError 分支，被當成「上游間歇脫軌」重試滿 DIGEST_ATTEMPTS——餘額不會
    因為重試變多，那五次是純粹的等待。
    """

    REAL = (
        "Error code: 402 - {'error': {'message': \"This request requires more credits, "
        "or fewer max_tokens. You requested up to 16000 tokens, but can only afford 15030.\"}}"
    )

    def test_402_produces_a_stop(self):
        stop = main.non_retryable_upstream_error(_FakeAPIError(self.REAL, 402))
        self.assertIsNotNone(stop)
        self.assertEqual(stop.status_code, 503)
        self.assertIn("額度不足", stop.detail)
        self.assertIn("餘額只夠 15030", stop.detail, "餘額數字要留著，才知道差多少")
        self.assertIn("本次需要 16000", stop.detail)
        self.assertIn("國際組許岱軒", stop.detail, "B119：要告訴使用者找誰儲值")

    def test_transient_statuses_keep_retrying(self):
        for status in (408, 429, 500, 502, 503):
            self.assertIsNone(
                main.non_retryable_upstream_error(_FakeAPIError("boom", status)),
                f"{status} 不該被當成額度不足",
            )

    def test_other_deterministic_4xx_stop_with_upstream_detail(self):
        for status in (400, 401, 403, 404):
            stop = main.non_retryable_upstream_error(_FakeAPIError("model not allowed", status))
            self.assertIsNotNone(stop)
            self.assertIn("model not allowed", stop.detail)

    def test_both_digest_paths_stop_before_the_retry(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("stop = non_retryable_upstream_error(exc)"), 2)
        # 停手要排在寫 last_detail 之前，不然還是會走完重試圈
        for block in source.split("except (APIConnectionError, APIError) as exc:")[1:]:
            head = block[: block.index("last_detail")]
            self.assertIn("non_retryable_upstream_error", head)


class BothDigestPathsUseItTests(unittest.TestCase):
    """generate() 與 hybrid_digest() 兩條都要改到——使用者踩到的是前者，
    但兩條的 APIError 分支本來是同一段複製貼上的死字串。"""

    def test_no_digest_path_still_hardcodes_the_blind_message(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        hardcoded = source.count('"AI 服務處理失敗，請確認模型權限或稍後重試"')
        self.assertEqual(
            hardcoded, 4,
            "只該剩下四處：upstream_error_detail 的 base、generate()／hybrid_digest() "
            "兩處 last_detail 初值、以及 generate-stream 背景執行緒的未預期例外"
            "（那條不是上游錯誤）。APIError 分支不准再寫死。",
        )

    def test_the_helper_is_called_on_both_paths(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("last_detail = upstream_error_detail(exc)"), 2)



class FriendlyUpstreamMessageTests(unittest.TestCase):
    """B119：安全系統擋題材與額度不足，前端 toast 要是看得懂的中文。"""

    SAFETY_BODY = (
        '{"error":{"message":"Your request was rejected by the safety system. If you believe '
        'this is an error, contact us at help.openai.com and include the request ID req_x"}}'
    )

    def test_safety_rejection_tells_the_user_to_retry(self):
        detail = main.friendly_image_http_error("OpenRouter", 400, self.SAFETY_BODY)
        self.assertIn("安全系統", detail)
        self.assertIn("再按一次", detail)
        self.assertNotIn("help.openai.com", detail)

    def test_safety_rejection_still_groups_as_provider_4xx(self):
        from fastapi import HTTPException

        detail = main.friendly_image_http_error("OpenRouter", 400, self.SAFETY_BODY)
        meta = main.classify_generation_error(HTTPException(status_code=502, detail=detail))
        self.assertEqual(meta["error_type"], "provider_4xx")
        self.assertEqual(meta["http_status"], 400)

    def test_image_402_names_who_to_contact(self):
        body = '{"error":{"message":"You requested up to 16000 tokens, but can only afford 4829."}}'
        detail = main.friendly_image_http_error("OpenRouter", 402, body)
        self.assertIn("額度不足", detail)
        self.assertIn("國際組許岱軒", detail)
        self.assertIn("餘額只夠 4829", detail)
        self.assertNotIn("can only afford", detail)

    def test_digest_402_is_chinese_and_still_provider_4xx(self):
        from fastapi import HTTPException

        stop = main.non_retryable_upstream_error(
            _FakeAPIError(CreditsExhaustedStopsRetryingTests.REAL, 402)
        )
        self.assertNotIn("can only afford", stop.detail)
        meta = main.classify_generation_error(stop)
        self.assertEqual(meta["error_type"], "provider_4xx")

    def test_other_errors_keep_the_raw_body(self):
        detail = main.friendly_image_http_error("OpenRouter", 500, "Provider returned error")
        self.assertEqual(detail, "OpenRouter 圖片生成失敗（500）：Provider returned error")

    def test_empty_body_still_preserves_the_upstream_status(self):
        from fastapi import HTTPException

        detail = main.friendly_image_http_error("OpenRouter", 403, "")
        self.assertIn("（403）", detail)
        meta = main.classify_generation_error(
            HTTPException(status_code=502, detail=detail)
        )
        self.assertEqual((meta["error_type"], meta["http_status"]), ("provider_4xx", 403))

    def test_upstream_status_survives_for_the_admin_grouping(self):
        from fastapi import HTTPException

        image_402 = main.friendly_image_http_error("OpenRouter", 402, "can only afford 1")
        meta = main.classify_generation_error(HTTPException(status_code=502, detail=image_402))
        self.assertEqual((meta["error_type"], meta["http_status"]), ("provider_4xx", 402))
        digest_402 = main.non_retryable_upstream_error(
            _FakeAPIError(CreditsExhaustedStopsRetryingTests.REAL, 402)
        )
        meta = main.classify_generation_error(digest_402)
        self.assertEqual((meta["error_type"], meta["http_status"]), ("provider_4xx", 402))

    def test_digest_safety_rejection_is_chinese_and_grouped_as_400(self):
        stop = main.non_retryable_upstream_error(_FakeAPIError(self.SAFETY_BODY, 400))
        self.assertIn("安全系統", stop.detail)
        self.assertNotIn("help.openai.com", stop.detail)
        meta = main.classify_generation_error(stop)
        self.assertEqual((meta["error_type"], meta["http_status"]), ("provider_4xx", 400))

    def test_cover_titles_forwards_credits_and_safety_stops(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        block = source.split('print(f"[cover-titles] 消化標題失敗')[1][:600]
        self.assertIn("non_retryable_upstream_error(exc)", block)
        self.assertIn("raise friendly from exc", block)

    def test_hybrid_ui_shows_the_backend_detail(self):
        source = (Path(main.__file__).parent / "hybrid.js").read_text(encoding="utf-8")
        self.assertIn("data.detail", source)
        self.assertNotIn("throw new Error('HTTP ' + res.status)", source)
        self.assertNotIn("throw new Error('消化失敗 HTTP ' + res.status)", source)


if __name__ == "__main__":
    unittest.main()
