"""B72／F31 正式站實查（2026-09-20）：消化階段完全沒有落檔，後台看不到真實故障率。

背景：team-lead 派人撈了正式站 aicg.tvbs.ai 後台 2026-09-18～09-20 的真實紀錄
（91 筆，全月 360 筆），失敗數是 0——查證後發現 `audit_archive` **只歸檔生圖端點**，
消化階段（`/api/generate`、`/api/hybrid/digest`、`/api/editor/cover-titles`）的
502／524（Cloudflare 逾時）／認證失敗全部直接往前端丟 `HTTPException`，完全沒有
寫進 `request_log` 或 `audit_archive`。成功那半邊也一樣：以前只寫 `request_log`
的 JSONL（14 天會被掃、重新部署即清空），沒有寫進 `audit_archive`，後台連
「消化階段總共跑了幾次」這個分母都答不出來，「成功率 100%」是假的。

同一輪實查也發現：91 筆裡有 36 筆（39.6%）其實是追加修改（`/api/images/refine`，
prompt 開頭是 `IMAGE REFINE RULES`），但後台 `type` 欄只有 1 筆標成 `web-refine`，
其餘 35 筆被 `_enrich_archive_fields()`／`_recall_digest()` 回填成「使用者最近一次
消化」的內容分類（例如「自動判斷」「資料圖表」）——那個回填對「這張圖畫的是什麼
內容」是正確的，只是不該拿來判斷「這是不是追加修改」，兩者是不同的問題。

這裡守三件事：
1. 消化階段（generate／hybrid_digest／editor_cover_titles）失敗與成功都要落檔，
   而且巢狀呼叫（apply_photo_availability 的第 4 層補救）不能重複記。
2. `audit_archive.record_action()` 能正確分辨「新生成／追加修改／消化／合成」，
   不受 `type_label` 回填影響。
3. `_archive_generation` 對沒有圖的呼叫（消化階段本來就沒有圖）不能因為
   `gcs_archive.archive_generation` 的必填參數而整個炸掉。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from openai import APIConnectionError, AuthenticationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import admin_console  # noqa: E402
import audit_archive  # noqa: E402
import gcs_archive  # noqa: E402
import main  # noqa: E402
import request_log  # noqa: E402
from main import GenerateRequest, HybridDigestRequest, generate, hybrid_digest  # noqa: E402


def connection_error():
    return APIConnectionError(request=httpx.Request("POST", "https://openrouter.ai/api/v1"))


class DigestFailureIsRecordedTests(unittest.TestCase):
    """`/api/generate` 背後那支 generate()：以前完全沒有失敗落檔。"""

    def setUp(self):
        self.request = GenerateRequest(news_text="素材測試新聞", type_label="資料圖表")
        sleep_patcher = patch.object(main.time, "sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def _call_and_capture(self, side_effect):
        logged, archived = [], []
        with patch.object(
            main.openai_client.chat.completions, "create", side_effect=side_effect
        ), patch.object(
            request_log, "log_failure", side_effect=lambda **kw: logged.append(kw)
        ), patch.object(
            main, "_archive_generation_failure", side_effect=lambda **kw: archived.append(kw)
        ):
            with self.assertRaises(HTTPException) as ctx:
                generate(self.request)
        return ctx.exception, logged, archived

    def test_exhausted_retries_are_logged_as_a_failure(self):
        exc, logged, archived = self._call_and_capture(
            [connection_error()] * main.DIGEST_ATTEMPTS
        )
        self.assertEqual(exc.status_code, 502)
        self.assertEqual(len(logged), 1, "消化重試燒完仍然沒有記到失敗")
        self.assertEqual(logged[0]["source"], "digest")
        self.assertEqual(logged[0]["news_text"], "素材測試新聞")
        self.assertTrue(logged[0]["digest_model"], "失敗筆也要看得出當時的消化模型")
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["status"], "failed")
        # team-lead 點名要驗證這兩個真的寫得進去，不是只有 status 一個空殼欄位。
        # APIConnectionError 燒完重試後的 last_detail 是「無法連線至 AI 服務」，
        # classify_generation_error() 靠文字比對歸成 timeout（見 _error_type_from_http）。
        self.assertEqual(archived[0]["error_type"], "timeout")
        self.assertEqual(archived[0]["http_status"], 502)

    def test_deadline_hit_is_logged(self):
        """Cloud Run／Cloudflare 逾時走的正是這條路徑——B39 524 的真因。"""
        token = main._digest_deadline.set(0.0)
        try:
            with patch.object(main.time, "monotonic", lambda: 0.0):
                exc, logged, archived = self._call_and_capture([])
        finally:
            main._digest_deadline.reset(token)
        self.assertEqual(exc.status_code, 503)
        self.assertIn("太久沒有回應", exc.detail)
        self.assertEqual(len(logged), 1)
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["error_type"], "timeout")
        self.assertEqual(archived[0]["http_status"], 503)

    def test_auth_failure_is_logged(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1")
        response = httpx.Response(401, request=request)
        exc, logged, _ = self._call_and_capture(
            [AuthenticationError("invalid key", response=response, body=None)]
        )
        self.assertEqual(exc.status_code, 503)
        self.assertEqual(len(logged), 1)


class DigestSuccessIsArchivedTests(unittest.TestCase):
    """成功也要進 audit_archive，不能只靠會被掃掉的 request_log JSONL。"""

    VALID_PAYLOAD = {
        "style": "S", "structure": "T",
        "variable": "[標題] 測試標題\n[內文小標] 一\n[內文小標] 二\n[內文小標] 三",
        "chart_type": "資料圖表",
    }

    def _ok_response(self):
        import json
        from types import SimpleNamespace
        content = json.dumps(self.VALID_PAYLOAD)
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])

    def test_successful_digest_writes_an_audit_record_with_no_image(self):
        request = GenerateRequest(news_text="素材測試新聞", type_label="資料圖表")
        archived = []
        with patch.object(
            main.openai_client.chat.completions, "create", return_value=self._ok_response()
        ), patch.object(
            main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)
        ):
            generate(request)
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["source"], "digest")
        self.assertNotIn("image_base64", archived[0])

    def test_archive_generation_skips_gcs_when_there_is_no_image(self):
        """gcs_archive.archive_generation 的 image_base64／mime_type 是必填，
        沒圖時 **kwargs 展開會在 ENABLED 判斷之前就丟 TypeError（B72／F31 修法時
        發現的坑）——這裡釘住不能回歸。"""
        with patch.object(gcs_archive, "ENABLED", True), patch.object(
            gcs_archive, "archive_generation"
        ) as mock_gcs:
            main._archive_generation(
                request_id="abc", source="digest", news_text="測試", status="ok",
            )
        mock_gcs.assert_not_called()


class HybridDigestFailureIsRecordedTests(unittest.TestCase):
    """`/api/hybrid/digest`：跟 generate() 同一個根因，以前也完全沒有落檔。"""

    def setUp(self):
        sleep_patcher = patch.object(main.time, "sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def test_exhausted_retries_are_logged_as_a_failure(self):
        request = HybridDigestRequest(news_text="美股三大指數收黑")
        logged, archived = [], []
        with patch.object(
            main.openai_client.chat.completions,
            "create",
            side_effect=[connection_error()] * 3,
        ), patch.object(
            request_log, "log_failure", side_effect=lambda **kw: logged.append(kw)
        ), patch.object(
            main, "_archive_generation_failure", side_effect=lambda **kw: archived.append(kw)
        ):
            with self.assertRaises(HTTPException) as ctx:
                hybrid_digest(request)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["source"], "hybrid-digest")
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["error_type"], "timeout")
        self.assertEqual(archived[0]["http_status"], 502)


class CoverTitlesDigestAuditTests(unittest.TestCase):
    """`/api/editor/cover-titles`：同一個根因的第三個端點，一樣完全沒有落檔過。"""

    def _completion(self, payload):
        import json
        from types import SimpleNamespace
        content = json.dumps(payload, ensure_ascii=False)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    def test_success_writes_a_record(self):
        from main import CoverTitleDigestRequest, editor_cover_titles

        request = CoverTitleDigestRequest(
            news_text="梅爾茨深感震驚，柏林街頭湧入示威群眾", target="yt_hourly",
        )
        logged, archived = [], []
        with patch.object(
            main, "digest_completion",
            return_value=self._completion({"title": "測試標題", "topics": 1}),
        ), patch.object(
            request_log, "log_generation", side_effect=lambda **kw: logged.append(kw)
        ), patch.object(
            main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)
        ):
            result = editor_cover_titles(request)
        self.assertEqual(result.title, "測試標題")
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["source"], "cover-titles")
        self.assertEqual(len(archived), 1)

    def test_failure_is_logged(self):
        from main import CoverTitleDigestRequest, editor_cover_titles

        request = CoverTitleDigestRequest(
            news_text="梅爾茨深感震驚，柏林街頭湧入示威群眾", target="yt_hourly",
        )
        logged, archived = [], []
        with patch.object(
            main, "digest_completion", side_effect=RuntimeError("上游炸了"),
        ), patch.object(
            request_log, "log_failure", side_effect=lambda **kw: logged.append(kw)
        ), patch.object(
            main, "_archive_generation_failure", side_effect=lambda **kw: archived.append(kw)
        ):
            with self.assertRaises(HTTPException) as ctx:
                editor_cover_titles(request)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["source"], "cover-titles")
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["error_type"], "provider_5xx")
        self.assertEqual(archived[0]["http_status"], 502)


class LoggingItselfMustNotSwallowTheOriginalErrorTests(unittest.TestCase):
    """team-lead 點名（正確）：`_outcome_meta`／`classify_generation_error` 以前
    完全沒有包 try，記錄失敗這件事本身可能把原本要往外丟的例外蓋掉——使用者
    原本該看到消化逾時的 503，不能因為分類例外訊息時自己又炸出一個無關的 500。
    """

    def test_a_broken_classifier_does_not_replace_the_original_exception(self):
        request = GenerateRequest(news_text="素材測試新聞", type_label="資料圖表")
        with patch.object(
            main.openai_client.chat.completions,
            "create",
            side_effect=[connection_error()] * main.DIGEST_ATTEMPTS,
        ), patch.object(
            main.time, "sleep"
        ), patch.object(
            main, "classify_generation_error", side_effect=RuntimeError("落檔本身壞了")
        ):
            with self.assertRaises(HTTPException) as ctx:
                generate(request)
        # 使用者拿到的仍然是消化重試燒完的 502，不是落檔壞掉炸出來的 500。
        self.assertEqual(ctx.exception.status_code, 502)

    def test_a_broken_archive_sink_does_not_replace_the_original_exception(self):
        request = HybridDigestRequest(news_text="美股三大指數收黑")
        with patch.object(
            main.openai_client.chat.completions,
            "create",
            side_effect=[connection_error()] * 3,
        ), patch.object(
            main.time, "sleep"
        ), patch.object(
            main, "_archive_generation_failure", side_effect=RuntimeError("落檔本身壞了")
        ):
            with self.assertRaises(HTTPException) as ctx:
                hybrid_digest(request)
        self.assertEqual(ctx.exception.status_code, 502)


class ActionColumnTests(unittest.TestCase):
    """`record_action()`：跟 record_type() 回答不同的問題，不能靠 type_label 猜。"""

    def test_web_refine_is_an_append_edit_regardless_of_backfilled_type(self):
        record = {"source": "web-refine", "type_label": "資料圖表"}
        self.assertEqual(audit_archive.record_action(record), "追加修改")

    def test_digest_sources_are_classified_as_digest(self):
        for source in ("digest", "hybrid-digest", "cover-titles"):
            with self.subTest(source=source):
                self.assertEqual(audit_archive.record_action({"source": source}), "消化")

    def test_yt_overlay_is_compose_only(self):
        record = {"source": "editor-yt-overlay-news-left"}
        self.assertEqual(audit_archive.record_action(record), "合成")

    def test_everything_else_defaults_to_new_generation(self):
        for source in ("web-image", "news-image", "editor-cover", "editor-cover-full", ""):
            with self.subTest(source=source):
                self.assertEqual(audit_archive.record_action({"source": source}), "新生成")

    def test_explicit_action_wins_over_the_fallback_table(self):
        record = {"source": "web-refine", "action": "自訂分類"}
        self.assertEqual(audit_archive.record_action(record), "自訂分類")

    def test_the_row_and_header_render_the_action_column(self):
        row = admin_console._row({"source": "web-refine", "ts": "2026-09-20T10:00:00"})
        self.assertIn("追加修改", row)
        page = admin_console._page(
            records=[{"source": "web-refine", "ts": "2026-09-20T10:00:00"}],
            months=["2026-09"], month="", user="",
            types=["web-refine"], type_label="",
        )
        self.assertIn("<th>動作</th>", page)


if __name__ == "__main__":
    unittest.main()
