"""B72：後台稽核完全不記錄消化模型，出事查不出是哪支模型消化的。

背景（2026-09-16 使用者當面問「現在消化模型是？跟公司正式版一樣嗎？」查證發現）：
`request_log.log_generation()` 與 `audit_archive` 只有 `image_model`（生圖端模型），
沒有任何欄位記「哪支模型做了消化」（style/structure/variable 的來源）。正式站的
`model` 欄全是生圖模型，因此「正式站的消化模型是不是 anthropic/claude-sonnet-5」
只能用 `main.py:126` 的預設值推論，紀錄裡查不到。

修法：`resolve_digest_model()` 是純環境設定查詢（讀 DIGEST_MODEL／
OPENAI_DIGEST_MODEL／後端預設，不吃請求參數），任何時點呼叫都是同一個值，因此
不必逐一端點各自追蹤「這次是不是真的呼叫過消化」，只要在 `_outcome_meta()`——
成功／失敗共用、全部 8 個會落檔的端點都會經過的那支函式——塞這個值，就能一次
涵蓋全部端點，不會重演 F30 那次「新版型忘了接歸檔」。`generate()`（真正執行消化
的那支）額外把它寫進 JSONL 與 `_remember_digest()`，做法與 B72 帳本原文的建議
（「由 generate() 把 resolve_digest_model() 的結果傳進來」）一致。

這裡守三層：
1. 寫入層：`request_log.log_generation`／`log_failure` 收得下 `digest_model`。
2. 儲存層：`main._outcome_meta` 一定帶 `digest_model`，成功與失敗共用。
3. 顯示層：`admin_console._row` 印得出「消化模型」，缺值印「－」而不是消失
   （沿用 F39 的 `_params_line` 慣例——藏起來分不出「沒帶」與「不顯示」）。
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import admin_console  # noqa: E402
import main  # noqa: E402
import request_log  # noqa: E402


class RequestLogDigestModelTests(unittest.TestCase):
    """寫入層：JSONL 收得下 digest_model，不影響其他欄位。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = pathlib.Path(self._tmp.name)
        patcher = patch.object(request_log, "LOG_DIR", self.log_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _records(self) -> list[dict]:
        lines = []
        for path in self.log_dir.glob("generations-*.jsonl"):
            lines += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return lines

    def test_generation_record_carries_the_digest_model(self):
        request_log.log_generation(
            request_id="abc123", source="digest", news_text="測試新聞",
            digest_model="google/gemini-3.8-flash",
        )
        [record] = self._records()
        self.assertEqual(record["digest_model"], "google/gemini-3.8-flash")

    def test_failure_record_also_carries_the_digest_model(self):
        """失敗筆一樣要記，理由跟成功筆一樣：出事時才最需要知道是哪支模型消化的。"""
        request_log.log_failure(
            request_id="abc124", source="digest", news_text="測試新聞",
            error="上游逾時", digest_model="gpt-5.5",
        )
        [record] = self._records()
        self.assertEqual(record["digest_model"], "gpt-5.5")
        self.assertFalse(record["ok"])

    def test_missing_digest_model_defaults_to_empty_not_missing_key(self):
        """欄位一定要存在（即使是空字串），舊呼叫端沒帶時後台才分得出「沒帶」。"""
        request_log.log_generation(request_id="abc125", source="web-image", news_text="")
        [record] = self._records()
        self.assertIn("digest_model", record)
        self.assertEqual(record["digest_model"], "")


class OutcomeMetaDigestModelTests(unittest.TestCase):
    """儲存層：_outcome_meta 是成功／失敗共用的單一入口，8 個端點都靠它。"""

    def test_outcome_meta_carries_the_currently_configured_digest_model(self):
        with patch.object(main, "resolve_digest_model", return_value="anthropic/claude-sonnet-5"):
            meta = main._outcome_meta(main._generation_clock())
        self.assertEqual(meta["digest_model"], "anthropic/claude-sonnet-5")

    def test_failure_outcome_also_carries_it(self):
        """失敗路徑常常在 except 裡直接 return，最容易漏記——這裡守住它沒有漏。"""
        with patch.object(main, "resolve_digest_model", return_value="gpt-5.5"):
            meta = main._outcome_meta(
                main._generation_clock(), exc=RuntimeError("上游逾時")
            )
        self.assertEqual(meta["digest_model"], "gpt-5.5")
        self.assertEqual(meta["status"], "failed")

    def test_record_generation_failure_forwards_digest_model_to_both_sinks(self):
        """_record_generation_failure 是所有失敗端點共用的落檔函式——
        守住這一支就等於守住全部端點的失敗路徑，不必逐一端點重測。
        """
        logged, archived = [], []
        with patch.object(main, "resolve_digest_model", return_value="google/gemini-3.8-flash"), \
             patch.object(request_log, "log_failure", side_effect=lambda **kw: logged.append(kw)), \
             patch.object(main, "_archive_generation_failure", side_effect=lambda **kw: archived.append(kw)):
            main._record_generation_failure(
                "req-1", main._generation_clock(), RuntimeError("上游逾時"),
                source="web-image", news_text="",
            )
        self.assertEqual(logged[0]["digest_model"], "google/gemini-3.8-flash")
        self.assertEqual(archived[0]["digest_model"], "google/gemini-3.8-flash")


class AdminConsoleDigestModelTests(unittest.TestCase):
    """顯示層：後台看得到消化模型，缺值印「－」而不是整段消失（沿用 F39 慣例）。"""

    def test_the_row_shows_the_digest_model(self):
        row = admin_console._row({
            "ts": "2026-09-20T10:00:00", "image_model": "gpt-image-2",
            "digest_model": "google/gemini-3.8-flash",
        })
        self.assertIn("消化模型: google/gemini-3.8-flash", row)

    def test_missing_digest_model_shows_a_dash_instead_of_disappearing(self):
        row = admin_console._row({"ts": "2026-09-20T10:00:00"})
        self.assertIn("消化模型: －", row)


if __name__ == "__main__":
    unittest.main()
