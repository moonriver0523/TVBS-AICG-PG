"""網頁版生成歷史備份進 GCS：內容正確、且絕不影響生成請求本身。

同 request_log.py 的測試哲學（見 test_request_log.py）：歸檔是附帶效果，
上傳失敗不能讓一次成功的生成變成失敗。
"""

import base64
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import audit_archive  # noqa: E402
import gcs_archive  # noqa: E402


class ArchiveGenerationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(gcs_archive, "ENABLED", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        bucket_patcher = patch.object(gcs_archive, "_get_bucket")
        self.mock_get_bucket = bucket_patcher.start()
        self.addCleanup(bucket_patcher.stop)
        self.mock_bucket = MagicMock()
        self.mock_get_bucket.return_value = self.mock_bucket

    def _blobs_by_name(self) -> dict:
        return {
            call.args[0]: call.return_value
            for call in self.mock_bucket.blob.mock_calls
            if call.args
        }

    def test_uploads_image_and_metadata_sidecar(self):
        image_bytes = b"\x89PNG fake bytes"
        gcs_archive.archive_generation(
            request_id="abc123",
            image_base64=base64.b64encode(image_bytes).decode(),
            mime_type="image/png",
            source="web-image",
            prompt="P",
            news_text="休達湧入大批移民",
        )
        # 一張圖 + 一份 metadata json
        blob_calls = self.mock_bucket.blob.call_args_list
        self.assertEqual(len(blob_calls), 2)
        png_name = blob_calls[0].args[0]
        json_name = blob_calls[1].args[0]
        self.assertTrue(png_name.endswith(".png"))
        self.assertTrue(png_name.startswith("generations/"))
        self.assertTrue(json_name.endswith(".json"))
        self.assertIn("abc123", png_name)

        png_blob = self.mock_bucket.blob.return_value
        upload_calls = png_blob.upload_from_string.call_args_list
        # 第一次呼叫寫圖，第二次寫 json（同一個 mock 物件回收給兩次 blob() 呼叫）
        self.assertEqual(upload_calls[0].args[0], image_bytes)
        record = json.loads(upload_calls[1].args[0])
        self.assertEqual(record["request_id"], "abc123")
        self.assertEqual(record["news_text"], "休達湧入大批移民")
        self.assertEqual(record["prompt"], "P")

    def test_disabled_does_nothing(self):
        with patch.object(gcs_archive, "ENABLED", False):
            gcs_archive.archive_generation(
                request_id="x", image_base64="", mime_type="image/png"
            )
        self.mock_get_bucket.assert_not_called()

    def test_upload_failure_never_raises(self):
        self.mock_bucket.blob.side_effect = RuntimeError("network down")
        gcs_archive.archive_generation(
            request_id="x", image_base64=base64.b64encode(b"a").decode(),
            mime_type="image/png",
        )

    def test_jpeg_mime_type_uses_jpg_extension(self):
        gcs_archive.archive_generation(
            request_id="x", image_base64=base64.b64encode(b"a").decode(),
            mime_type="image/jpeg",
        )
        png_name = self.mock_bucket.blob.call_args_list[0].args[0]
        self.assertTrue(png_name.endswith(".jpg"))


class AuditArchiveTests(unittest.TestCase):
    """本機稽核歸檔：成功／失敗欄位、舊紀錄相容、分頁不重不漏（F30／F31）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        enabled = patch.object(audit_archive, "ENABLED", True)
        directory = patch.object(audit_archive, "ARCHIVE_DIR", self.root)
        enabled.start()
        directory.start()
        self.addCleanup(enabled.stop)
        self.addCleanup(directory.stop)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, filename: str, **fields) -> None:
        month = self.root / "2026-09"
        month.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": fields.pop("ts", "2026-09-16T12:00:00+08:00"),
            "request_id": fields.pop("request_id", filename.split(".")[0]),
            **fields,
        }
        (month / filename).write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )

    def test_success_round_trip_keeps_image_and_new_fields(self):
        image_bytes = b"\x89PNG fake"
        audit_archive.archive_generation(
            request_id="ok123",
            image_base64=base64.b64encode(image_bytes).decode(),
            mime_type="image/png",
            source="web-image",
            status="ok",
            duration_ms=1234,
            provider="gpt",
            retry_count=2,
            image_model="fake-model",
        )
        [record] = audit_archive.list_records()
        self.assertEqual(record["request_id"], "ok123")
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["duration_ms"], 1234)
        self.assertEqual(record["provider"], "gpt")
        self.assertEqual(record["retry_count"], 2)
        self.assertTrue(record["image_file"].endswith(".png"))
        stored = (self.root / record["_month"] / record["image_file"]).read_bytes()
        self.assertEqual(stored, image_bytes)

    def test_failure_does_not_require_an_image_and_is_marked_failed(self):
        audit_archive.archive_generation(
            request_id="fail123",
            status="failed",
            duration_ms=900,
            provider="gemini",
            retry_count=1,
            error_type="timeout",
            http_status=504,
            error_summary="太久沒有回應",
        )
        [record] = audit_archive.list_records()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["image_file"], "")
        self.assertEqual(record["error_type"], "timeout")
        self.assertEqual(record["http_status"], 504)
        self.assertEqual(record["error_summary"], "太久沒有回應")

    def test_error_summary_is_truncated_and_redacted(self):
        audit_archive.archive_generation(
            request_id="secret",
            status="failed",
            error_summary=(
                "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz "
                + "Z" * 400
            ),
        )
        [record] = audit_archive.list_records()
        self.assertLessEqual(
            len(record["error_summary"]), audit_archive.MAX_ERROR_SUMMARY_CHARS
        )
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", record["error_summary"])
        self.assertNotIn("Bearer", record["error_summary"])
        self.assertIn("[redacted]", record["error_summary"])

    def test_old_records_missing_new_fields_still_list(self):
        self._write(
            "20260907-101010-legacy.json",
            request_id="legacy",
            prompt="old prompt",
            source="web-image",
        )
        [record] = audit_archive.list_records()
        self.assertEqual(record["request_id"], "legacy")
        self.assertNotIn("status", record)
        self.assertEqual(audit_archive.record_status(record), "ok")
        self.assertEqual(audit_archive.record_type(record), "web-image")

    def test_corrupt_json_is_skipped_not_counted_as_failure(self):
        self._write("20260916-120000-ok.json", request_id="ok", status="ok")
        (self.root / "2026-09" / "broken.json").write_text("{not json", encoding="utf-8")
        records = audit_archive.list_records()
        summary = audit_archive.summarize_records()
        self.assertEqual([r["request_id"] for r in records], ["ok"])
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["ok"], 1)
        self.assertEqual(summary["failed"], 0)

    def test_pagination_offset_has_no_overlap_or_gap(self):
        for index in range(5):
            self._write(
                f"20260916-12000{index}-id{index}.json",
                request_id=f"id{index}",
                status="ok" if index % 2 == 0 else "failed",
            )
        page0 = audit_archive.list_records(limit=2, offset=0)
        page1 = audit_archive.list_records(limit=2, offset=2)
        page2 = audit_archive.list_records(limit=2, offset=4)
        ids = [r["request_id"] for r in page0 + page1 + page2]
        self.assertEqual(len(ids), 5)
        self.assertEqual(len(set(ids)), 5)
        self.assertEqual(set(ids), {f"id{i}" for i in range(5)})
        default = audit_archive.list_records()
        self.assertEqual(len(default), 5)

    def test_cursor_continues_after_last_item(self):
        for index in range(5):
            self._write(
                f"20260916-13000{index}-c{index}.json",
                request_id=f"c{index}",
                ts=f"2026-09-16T13:00:0{index}+08:00",
            )
        first = audit_archive.list_records(limit=2)
        second = audit_archive.list_records(limit=2, cursor=first[-1]["_cursor"])
        first_ids = {r["request_id"] for r in first}
        second_ids = {r["request_id"] for r in second}
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(len(first_ids | second_ids), 4)

    def test_summarize_uses_full_set_not_page_size(self):
        for index in range(5):
            self._write(
                f"20260916-14000{index}-s{index}.json",
                request_id=f"s{index}",
                status="failed" if index < 2 else "ok",
            )
        page = audit_archive.list_records(limit=2)
        summary = audit_archive.summarize_records()
        self.assertEqual(len(page), 2)
        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["ok"], 3)
        self.assertEqual(summary["failed"], 2)


if __name__ == "__main__":
    unittest.main()
