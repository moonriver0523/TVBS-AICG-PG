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
        stop = main.credits_exhausted_error(_FakeAPIError(self.REAL, 402))
        self.assertIsNotNone(stop)
        self.assertEqual(stop.status_code, 503)
        self.assertIn("額度不足", stop.detail)
        self.assertIn("can only afford 15030", stop.detail, "餘額數字要留著，才知道差多少")

    def test_other_statuses_keep_retrying(self):
        for status in (500, 502, 503, 403, 429):
            self.assertIsNone(
                main.credits_exhausted_error(_FakeAPIError("boom", status)),
                f"{status} 不該被當成額度不足",
            )

    def test_both_digest_paths_stop_before_the_retry(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("stop = credits_exhausted_error(exc)"), 2)
        # 停手要排在寫 last_detail 之前，不然還是會走完重試圈
        for block in source.split("except (APIConnectionError, APIError) as exc:")[1:]:
            head = block[: block.index("last_detail")]
            self.assertIn("credits_exhausted_error", head)


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


if __name__ == "__main__":
    unittest.main()
