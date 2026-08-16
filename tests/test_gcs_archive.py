"""網頁版生成歷史備份進 GCS：內容正確、且絕不影響生成請求本身。

同 request_log.py 的測試哲學（見 test_request_log.py）：歸檔是附帶效果，
上傳失敗不能讓一次成功的生成變成失敗。
"""

import base64
import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

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


if __name__ == "__main__":
    unittest.main()
