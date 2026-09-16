"""成功請求落檔：內容正確、能回查、且絕不影響請求本身。

這個機制是為了 2026-07-31 休達案例那種情境存在的——使用者拿一張有問題的成圖來
問，後端要能回答那張圖是哪段文字生的。因此測試重點有二：紀錄裡真的有回查所需的
欄位，以及寫檔失敗時請求照樣成功（記 log 是附帶效果，不是功能的一部分）。
"""

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
import request_log  # noqa: E402


class LogWritingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = pathlib.Path(self._tmp.name)
        patcher = patch.object(request_log, "LOG_DIR", self.log_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def records(self) -> list[dict]:
        lines = []
        for path in self.log_dir.glob("generations-*.jsonl"):
            lines += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return lines

    def test_generation_record_carries_what_a_replay_needs(self):
        request_log.log_generation(
            request_id="abc123", source="line", news_text="休達湧入大批移民",
            style="S", structure="T", variable="[標題]休達大批移民湧入",
            prompt="P", chart_type="地圖／位置", provider="gpt",
        )
        [record] = self.records()
        for field in ("ts", "request_id", "source", "news_text", "style",
                      "structure", "variable", "prompt", "chart_type", "provider"):
            with self.subTest(field=field):
                self.assertIn(field, record)
        self.assertEqual(record["news_text"], "休達湧入大批移民")
        self.assertEqual(record["source"], "line")

    def test_image_file_record_links_back_to_the_request(self):
        request_log.log_image_file(
            request_id="abc123", image_name="20260731-230612-a1b2c3.png"
        )
        [record] = self.records()
        self.assertEqual(record["request_id"], "abc123")
        self.assertEqual(record["image_name"], "20260731-230612-a1b2c3.png")

    def test_long_prompt_is_truncated(self):
        request_log.log_generation(
            request_id="x", source="test", news_text="n",
            prompt="P" * (request_log.MAX_PROMPT_CHARS + 500),
        )
        [record] = self.records()
        self.assertEqual(len(record["prompt"]), request_log.MAX_PROMPT_CHARS)

    def test_write_failure_never_raises(self):
        # 記 log 失敗不該把一次成功的生成變成失敗
        with patch.object(request_log, "_write", side_effect=OSError("disk full")):
            request_log.log_generation(request_id="x", source="test", news_text="n")
            request_log.log_image_file(request_id="x", image_name="a.png")

    def test_disabled_writes_nothing(self):
        with patch.object(request_log, "ENABLED", False):
            request_log.log_generation(request_id="x", source="test", news_text="n")
        self.assertEqual(self.records(), [])

    def test_failure_record_carries_error_and_is_marked_not_ok(self):
        request_log.log_failure(
            request_id="abc123", source="line", news_text="生物疫情圖表",
            error="[OpenRouter image HTTPError] 400: rejected by the safety system",
            style="S", structure="T", variable="V", prompt="P",
            chart_type="資料圖表", provider="gpt",
        )
        [record] = self.records()
        self.assertEqual(record["ok"], False)
        self.assertEqual(record["news_text"], "生物疫情圖表")
        self.assertIn("safety system", record["error"])

    def test_failure_write_failure_never_raises(self):
        with patch.object(request_log, "_write", side_effect=OSError("disk full")):
            request_log.log_failure(request_id="x", source="test", news_text="n", error="e")

    def test_retention_sweep_removes_stale_files(self):
        stale = self.log_dir / "generations-20200101.jsonl"
        stale.write_text("{}\n", encoding="utf-8")
        old = 0  # epoch，遠早於任何保留期
        os.utime(stale, (old, old))
        request_log.log_generation(request_id="x", source="test", news_text="n")
        self.assertFalse(stale.exists())


class DigestEndpointLoggingTests(unittest.TestCase):
    """/api/generate 走網頁版，後端看不到最終 prompt，但仍要留下輸入與消化結果。"""

    def test_failed_generation_logs_failure_and_still_raises(self):
        fake_digest = main.GenerateResponse(
            style="S", structure="T", variable="[標題]生物疫情圖表",
            chart_type="資料圖表", portrait_subjects=[],
        )
        with patch.object(main, "check_input") as check_input, \
                patch.object(main, "generate", return_value=fake_digest), \
                patch.object(main, "resolve_portrait", return_value=("none", None)), \
                patch.object(main, "build_prompt", return_value="最終 PROMPT"), \
                patch.object(main, "generate_image", side_effect=RuntimeError("safety system 400")), \
                patch.object(request_log, "log_failure") as failed, \
                patch.object(request_log, "log_generation") as logged:
            check_input.return_value = type("V", (), {"accepted": True, "user_message": ""})()
            with self.assertRaises(RuntimeError):
                main.generate_news_image(
                    main.NewsImageGenerateRequest(news_text="生物疫情圖表", source="line")
                )
        failed.assert_called_once()
        self.assertEqual(failed.call_args.kwargs["news_text"], "生物疫情圖表")
        self.assertEqual(failed.call_args.kwargs["prompt"], "最終 PROMPT")
        self.assertIn("safety system", failed.call_args.kwargs["error"])
        logged.assert_not_called()

    def test_digest_is_logged_once_when_called_directly(self):
        with patch.object(request_log, "log_generation") as logged, \
                patch.object(main, "digest_completion") as completion:
            completion.return_value = _fake_completion()
            main.generate(main.GenerateRequest(news_text="休達湧入大批移民", type_label="資料圖表"))
        self.assertEqual(logged.call_count, 1)
        self.assertEqual(logged.call_args.kwargs["source"], "digest")
        self.assertEqual(logged.call_args.kwargs["news_text"], "休達湧入大批移民")

    def test_digest_is_not_logged_separately_inside_the_full_pipeline(self):
        # generate_news_image 自己會記一筆含最終 prompt 的完整紀錄，
        # 內層 generate() 再記一次只會製造半套的重複紀錄
        token = main._inside_pipeline.set(True)
        try:
            with patch.object(request_log, "log_generation") as logged, \
                    patch.object(main, "digest_completion") as completion:
                completion.return_value = _fake_completion()
                main.generate(main.GenerateRequest(news_text="休達湧入大批移民", type_label="資料圖表"))
            self.assertEqual(logged.call_count, 0)
        finally:
            main._inside_pipeline.reset(token)

    def test_pipeline_flag_is_reset_afterwards(self):
        self.assertFalse(main._inside_pipeline.get())


class GenerationOutcomeTests(unittest.TestCase):
    """同一 request id 的 log／audit 口徑一致；失敗只歸檔一次；摘要去敏。"""

    def test_failure_log_and_archive_share_request_id_and_happen_once(self):
        fake_digest = main.GenerateResponse(
            style="S", structure="T", variable="[標題]生物疫情圖表",
            chart_type="資料圖表", portrait_subjects=[],
        )
        failures, archives = [], []
        with patch.object(main, "check_input") as check_input, \
                patch.object(main, "generate", return_value=fake_digest), \
                patch.object(main, "resolve_portrait", return_value=("none", None)), \
                patch.object(main, "build_prompt", return_value="最終 PROMPT"), \
                patch.object(main, "generate_image", side_effect=RuntimeError("safety system 400")), \
                patch.object(request_log, "log_failure", side_effect=lambda **kw: failures.append(kw)), \
                patch.object(request_log, "log_generation") as logged, \
                patch.object(main, "_archive_generation_failure", side_effect=lambda **kw: archives.append(kw)), \
                patch.object(main, "_archive_generation") as archived_ok:
            check_input.return_value = type("V", (), {"accepted": True, "user_message": ""})()
            with self.assertRaises(RuntimeError):
                main.generate_news_image(
                    main.NewsImageGenerateRequest(news_text="生物疫情圖表", source="web")
                )
        self.assertEqual(len(failures), 1)
        self.assertEqual(len(archives), 1)
        self.assertEqual(failures[0]["request_id"], archives[0]["request_id"])
        self.assertEqual(archives[0]["status"], "failed")
        self.assertEqual(archives[0]["error_type"], "unknown")
        logged.assert_not_called()
        archived_ok.assert_not_called()

    def test_error_summary_is_capped_and_does_not_leak_authorization(self):
        secret = (
            "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz "
            + "TRACE " + "Z" * 400
        )
        fake_digest = main.GenerateResponse(
            style="S", structure="T", variable="[標題]生物疫情圖表",
            chart_type="資料圖表", portrait_subjects=[],
        )
        archives = []
        with patch.object(main, "check_input") as check_input, \
                patch.object(main, "generate", return_value=fake_digest), \
                patch.object(main, "resolve_portrait", return_value=("none", None)), \
                patch.object(main, "build_prompt", return_value="最終 PROMPT"), \
                patch.object(main, "generate_image", side_effect=RuntimeError(secret)), \
                patch.object(request_log, "log_failure"), \
                patch.object(main, "_archive_generation_failure", side_effect=lambda **kw: archives.append(kw)):
            check_input.return_value = type("V", (), {"accepted": True, "user_message": ""})()
            with self.assertRaises(RuntimeError):
                main.generate_news_image(
                    main.NewsImageGenerateRequest(news_text="生物疫情圖表")
                )
        summary = archives[0]["error_summary"]
        self.assertLessEqual(len(summary), 300)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", summary)
        self.assertNotIn("Bearer", summary)
        self.assertNotIn("Authorization", summary)

    def test_success_duration_comes_from_shared_clock(self):
        fake_digest = main.GenerateResponse(
            style="S", structure="T", variable="[標題]休達大批移民湧入",
            chart_type="資料圖表", portrait_subjects=[],
        )
        fake_image = main.ImageGenerateResponse(
            image_data_base64="ZmFrZQ==", mime_type="image/png", model="fake-model"
        )
        now = [10.0]
        archives = []

        def fake_generate_image(req):
            now[0] = 12.25
            return fake_image

        with patch.object(main, "check_input") as check_input, \
                patch.object(main, "generate", return_value=fake_digest), \
                patch.object(main, "resolve_portrait", return_value=("none", None)), \
                patch.object(main, "lookup_portrait_photos", return_value=({}, [])), \
                patch.object(main, "build_prompt", return_value="最終 PROMPT"), \
                patch.object(main, "generate_image", side_effect=fake_generate_image), \
                patch.object(main.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(request_log, "log_generation"), \
                patch.object(main, "_archive_generation", side_effect=lambda **kw: archives.append(kw)):
            check_input.return_value = type("V", (), {"accepted": True, "user_message": ""})()
            main.generate_news_image(
                main.NewsImageGenerateRequest(news_text="休達湧入大批移民 當地疏散逾21萬人")
            )
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0]["status"], "ok")
        self.assertEqual(archives[0]["duration_ms"], 2250)
        self.assertEqual(archives[0]["provider"], "gemini")
        self.assertEqual(archives[0]["image_model"], "fake-model")

    def test_provider_http_error_is_grouped_by_upstream_status(self):
        from fastapi import HTTPException
        meta = main.classify_generation_error(
            HTTPException(
                status_code=502,
                detail="OpenRouter 圖片生成失敗（400）：rejected by the safety system",
            )
        )
        self.assertEqual(meta["error_type"], "provider_4xx")
        self.assertEqual(meta["http_status"], 400)
        self.assertIn("safety system", meta["error_summary"])


def _fake_completion():
    class Message:
        content = json.dumps({
            "style": "S", "structure": "T",
            "variable": "[標題]休達大批移民湧入", "chart_type": "資料圖表",
        })

    class Choice:
        message = Message()
        finish_reason = "stop"

    class Response:
        choices = [Choice()]

    return Response()


if __name__ == "__main__":
    unittest.main()
