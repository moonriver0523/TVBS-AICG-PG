"""B39：`/api/generate` 改成 NDJSON 串流＋心跳，讓 Cloudflare 不再對長工 524。

這支只測「串流這層」（generate_stream／_generate_ndjson_lines）：心跳、
result／error 的收斂、以及最關鍵的「狀態碼一旦開始串流就定死是 200」。
generate() 本身的重試/死線/品質檢查邏輯不動、不重測——那是
tests/test_generate_retry.py 的範圍，generate() 對外行為完全沒變
（仍是同一個可直接呼叫、會 raise HTTPException 的純函式，見 main.py 的
generate_news_image／apply_photo_availability／這三支既有測試檔，全部
直接呼叫 main.generate()，不經 HTTP，串流只是外面那層 wire format）。
"""

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import GenerateResponse, app  # noqa: E402

client = TestClient(app)

NEWS = "素材"
HEADERS = {"X-API-Key": "test-internal-key"}

FAKE_DIGEST = GenerateResponse(
    style="S",
    structure="T",
    variable="[標題] 測試\n[內文]",
    chart_type="資料圖表",
)


def _read_ndjson_lines(response):
    lines = []
    for raw in response.iter_lines():
        line = raw.strip() if isinstance(raw, str) else raw.decode("utf-8").strip()
        if line:
            lines.append(json.loads(line))
    return lines


class GenerateStreamTests(unittest.TestCase):
    def setUp(self):
        # 全域環境變數，其他測試檔也在讀——用 patch.dict 確保測完自動還原，
        # 不會因為覆寫留著沒收，污染同一個 pytest 行程裡之後才跑的測試檔。
        patcher = patch.dict(os.environ, {"NEWS_IMAGE_API_KEY": "test-internal-key"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_success_ends_with_a_result_line(self):
        with patch.object(main, "generate", return_value=FAKE_DIGEST):
            with client.stream(
                "POST", "/api/generate",
                json={"news_text": NEWS, "type_label": "資料圖表"},
                headers=HEADERS,
            ) as response:
                self.assertEqual(response.status_code, 200)
                self.assertIn("x-ndjson", response.headers.get("content-type", ""))
                lines = _read_ndjson_lines(response)
        self.assertTrue(lines, "串流沒有送出任何一行")
        self.assertEqual(lines[-1]["type"], "result")
        self.assertEqual(lines[-1]["chart_type"], "資料圖表")
        self.assertEqual(lines[-1]["variable"], FAKE_DIGEST.variable)

    def test_backend_error_ends_with_an_error_line_carrying_the_original_detail(self):
        # 524 本身不會出現在這裡——那是 Cloudflare 在連線靜默時才送的，串流不會讓
        # 後端自己產生 524。這裡驗的是 generate() 原本就會拋的 HTTPException
        # （例如死線到了的 503）能不能正確被編進串流內容，而不是遺失或被吞掉。
        detail = "AI 服務這次太久沒有回應，請縮短新聞內容或稍後重試"
        with patch.object(main, "generate", side_effect=HTTPException(status_code=503, detail=detail)):
            with client.stream(
                "POST", "/api/generate",
                json={"news_text": NEWS, "type_label": "資料圖表"},
                headers=HEADERS,
            ) as response:
                # ⚠ 這是 B39 最重要的一條斷言：即使 generate() 內部丟的是 503，
                # 一旦開始串流，HTTP 狀態碼就已經定死是 200——前端不能再看
                # response.ok，只能看串流內容的最後一行判斷成敗。
                self.assertEqual(response.status_code, 200)
                lines = _read_ndjson_lines(response)
        self.assertEqual(lines[-1]["type"], "error")
        self.assertEqual(lines[-1]["status"], 503)
        self.assertEqual(lines[-1]["detail"], detail)

    def test_unexpected_exception_still_ends_with_an_error_line_not_a_hang(self):
        """背景執行緒丟出非 HTTPException 的例外也不能讓連線靜默卡死。"""
        with patch.object(main, "generate", side_effect=RuntimeError("boom")):
            with client.stream(
                "POST", "/api/generate",
                json={"news_text": NEWS, "type_label": "資料圖表"},
                headers=HEADERS,
            ) as response:
                self.assertEqual(response.status_code, 200)
                lines = _read_ndjson_lines(response)
        self.assertEqual(lines[-1]["type"], "error")
        self.assertEqual(lines[-1]["status"], 500)

    def test_a_long_job_sends_heartbeats_before_the_result(self):
        """長工期間要確實送出心跳，連線才不會在 CF 眼裡看起來像斷線。"""
        import time as time_mod

        def slow_generate(_req):
            time_mod.sleep(0.25)
            return FAKE_DIGEST

        with patch.object(main, "DIGEST_HEARTBEAT_SECONDS", 0.05), patch.object(
            main, "generate", side_effect=slow_generate
        ):
            with client.stream(
                "POST", "/api/generate",
                json={"news_text": NEWS, "type_label": "資料圖表"},
                headers=HEADERS,
            ) as response:
                lines = _read_ndjson_lines(response)
        pings = [line for line in lines if line["type"] == "ping"]
        self.assertGreaterEqual(len(pings), 2, "長工期間應該送出多行心跳，不是只有結果那一行")
        self.assertEqual(lines[-1]["type"], "result")

    def test_wrong_api_key_is_rejected_before_streaming_starts(self):
        # 驗證還沒過就不會進到 generator，狀態碼此時還沒定死，仍照 HTTP 語意回 401。
        with client.stream(
            "POST", "/api/generate",
            json={"news_text": NEWS, "type_label": "資料圖表"},
            headers={"X-API-Key": "wrong-key"},
        ) as response:
            self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
