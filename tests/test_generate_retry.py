"""/api/generate 的重試行為：上游偶發失敗與不合格式回傳都必須在後端吸收。

對照組是 hybrid_digest——重試圈涵蓋「呼叫＋解析」全程，
金鑰／用量類錯誤則不重試（重試也不會變好）。
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from openai import APIConnectionError, AuthenticationError

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import GenerateRequest, generate  # noqa: E402

VALID_PAYLOAD = {
    "style": "cinematic broadcast style",
    "structure": "three panels",
    "variable": "[標題]\n[內文]",
    "chart_type": "資料圖表",
}


def ok_response(payload=None):
    content = json.dumps(payload if payload is not None else VALID_PAYLOAD)
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def bad_json_response():
    message = SimpleNamespace(content="這不是 JSON，上游截斷了")
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="length")])


def connection_error():
    return APIConnectionError(request=httpx.Request("POST", "https://openrouter.ai/api/v1"))


def auth_error():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1")
    response = httpx.Response(401, request=request)
    return AuthenticationError("invalid key", response=response, body=None)


def quality_fail_response(field, finish_reason="stop"):
    payload = dict(VALID_PAYLOAD)
    payload[field] = ""
    return ok_response(payload) if finish_reason == "stop" else SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload)),
                finish_reason=finish_reason,
            )
        ]
    )


def length_truncated_response(payload=None):
    content = json.dumps(payload if payload is not None else VALID_PAYLOAD)
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="length")])


def _dump_call(call):
    return json.dumps(call.kwargs, sort_keys=True, ensure_ascii=False, default=str)


def _system_prompt(call):
    return call.kwargs["messages"][0]["content"]


def _user_message(call):
    return call.kwargs["messages"][1]["content"]


def _reasoning_max(call):
    extra = call.kwargs.get("extra_body") or {}
    return (extra.get("reasoning") or {}).get("max_tokens")


class GenerateRetryTests(unittest.TestCase):
    def setUp(self):
        self.request = GenerateRequest(news_text="素材", type_label="資料圖表")
        # 重試間隔在測試裡沒有意義，避免每個案例真的睡 3 秒
        sleep_patcher = patch.object(main.time, "sleep")
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def call_with(self, side_effect):
        with patch.object(
            main.openai_client.chat.completions, "create", side_effect=side_effect
        ) as create:
            try:
                result = generate(self.request)
            except HTTPException as exc:
                return None, exc, create
            return result, None, create

    def test_recovers_from_transient_api_error(self):
        result, exc, create = self.call_with(
            [connection_error(), connection_error(), ok_response()]
        )
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 3)
        self.assertEqual(result.chart_type, "資料圖表")
        self.assertEqual(result.structure, "three panels")

    def test_recovers_from_unparseable_response(self):
        # 只重試呼叫是不夠的：上游回 200 但內容不是 JSON 也必須重來
        result, exc, create = self.call_with([bad_json_response(), ok_response()])
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(result.style, "cinematic broadcast style")

    def test_gives_up_after_the_configured_number_of_attempts(self):
        result, exc, create = self.call_with(
            [connection_error()] * main.DIGEST_ATTEMPTS
        )
        self.assertIsNone(result)
        self.assertEqual(create.call_count, main.DIGEST_ATTEMPTS)
        self.assertEqual(exc.status_code, 502)
        self.assertIn("無法連線", exc.detail)

    def test_parse_failure_reports_parse_detail(self):
        result, exc, create = self.call_with(
            [bad_json_response()] * main.DIGEST_ATTEMPTS
        )
        self.assertIsNone(result)
        self.assertEqual(create.call_count, main.DIGEST_ATTEMPTS)
        self.assertEqual(exc.status_code, 502)
        self.assertEqual(exc.detail, "AI 回傳格式無法解析")

    def test_auth_error_is_not_retried(self):
        result, exc, create = self.call_with([auth_error(), ok_response()])
        self.assertIsNone(result)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(exc.status_code, 503)

    def test_every_call_carries_a_timeout(self):
        """單次呼叫一定要有上限（2026-09-10 線上事故）。

        沒有的話走 SDK 預設 600 秒——比整體死線 230 秒與 Cloud Run 的 300 秒都長，
        一通卡住的上游請求就會讓前端停在 35%（消化階段的上限值）永遠不動，
        連錯誤訊息都沒有。死線只在兩次 attempt 之間檢查，擋不住第一通就卡死。
        """
        _, _, create = self.call_with([ok_response()])
        timeout = create.call_args.kwargs.get("timeout")
        self.assertIsNotNone(timeout, "消化呼叫沒帶 timeout，卡住就會拖到 Cloud Run 斷線")
        self.assertLessEqual(timeout, main.DIGEST_DEADLINE_SECONDS)

    def test_a_hung_upstream_still_returns_an_error_in_time(self):
        """每一通都跑滿 timeout 時，要在 Cloud Run 的 300 秒之前回一個看得懂的錯誤。

        用假時鐘讓每次 attempt 真的花掉 DIGEST_TIMEOUT_SECONDS，才驗得到死線有沒有
        在「這一次跑滿也來不及」的時候停手——DIGEST_ATTEMPTS(5) × 90 秒是 450 秒，
        照跑就會撞上 Cloud Run 的 300 秒斷線，使用者看到的就是進度條卡在 35%。
        """
        from openai import APITimeoutError

        now = [0.0]

        def tick(*_args, **_kwargs):
            now[0] += main.DIGEST_TIMEOUT_SECONDS
            raise APITimeoutError(request=httpx.Request("POST", "https://openrouter.ai/api/v1"))

        with patch.object(main.time, "monotonic", lambda: now[0]):
            result, exc, create = self.call_with(tick)
        self.assertIsNone(result)
        self.assertIsNotNone(exc)
        self.assertLess(now[0], 300, "重試跑太久，會撞上 Cloud Run 的 300 秒斷線")
        self.assertLess(create.call_count, main.DIGEST_ATTEMPTS, "死線沒有提早停手")

    def test_success_on_first_try_does_not_sleep(self):
        result, exc, create = self.call_with([ok_response()])
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 1)
        self.sleep.assert_not_called()

    def test_sdk_retries_are_disabled(self):
        self.assertEqual(main.openai_client.max_retries, 0)
        self.assertEqual(main.OPENAI_MAX_RETRIES, 0)

    def test_deadline_is_checked_before_attempt_zero(self):
        # 新請求自己算 deadline 時，attempt 0 永遠還有 230 秒，擋不到。
        # 第二次 generate() 沿用已耗掉的 deadline 才是這條守門的意義。
        token = main._digest_deadline.set(0.0)
        try:
            with patch.object(main.time, "monotonic", lambda: 0.0):
                result, exc, create = self.call_with([ok_response()])
        finally:
            main._digest_deadline.reset(token)
        self.assertIsNone(result)
        self.assertEqual(exc.status_code, 503)
        self.assertEqual(create.call_count, 0)
        self.assertIn("太久沒有回應", exc.detail)

    def test_photo_availability_retry_reuses_the_same_deadline(self):
        now = [0.0]
        calls = {"n": 0}

        def tick(*_args, **_kwargs):
            if calls["n"] == 0:
                now[0] = 200.0
                calls["n"] += 1
                return ok_response({**VALID_PAYLOAD, "portrait_subjects": ["吳軒彤"]})
            calls["n"] += 1
            return ok_response()

        with patch.object(main.time, "monotonic", lambda: now[0]), patch.object(
            main, "lookup_portrait_photos", return_value=({}, ["吳軒彤"])
        ), patch.object(main, "_remember_digest"):
            result, exc, create = self.call_with(tick)
        self.assertIsNone(result)
        self.assertEqual(exc.status_code, 503)
        self.assertEqual(create.call_count, 1)

    def test_photo_availability_retry_still_runs_when_budget_remains(self):
        now = [0.0]

        def tick(*_args, **_kwargs):
            now[0] += 10.0
            subjects = [] if now[0] > 10.0 else ["吳軒彤"]
            return ok_response({**VALID_PAYLOAD, "portrait_subjects": subjects})

        with patch.object(main.time, "monotonic", lambda: now[0]), patch.object(
            main, "lookup_portrait_photos", return_value=({}, ["吳軒彤"])
        ), patch.object(main, "_remember_digest"), patch.object(
            main.request_log, "log_generation"
        ):
            result, exc, create = self.call_with(tick)
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(result.portrait_subjects, [])

    def test_markdown_fenced_json_is_accepted_without_retry(self):
        fenced = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
                    ),
                    finish_reason="stop",
                )
            ]
        )
        result, exc, create = self.call_with([fenced])
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(result.chart_type, "資料圖表")


class GenerateRetryContextTests(GenerateRetryTests):
    """B50：每次 retry 的 request 必須帶上一輪失敗原因，length 時縮小思考預算。"""

    def setUp(self):
        super().setUp()
        backend = patch.object(main, "DIGEST_BACKEND", "openrouter")
        backend.start()
        self.addCleanup(backend.stop)
        reasoning = patch.object(main, "DIGEST_REASONING_MAX_TOKENS", 2000)
        reasoning.start()
        self.addCleanup(reasoning.stop)

    def test_quality_retries_are_not_byte_identical_and_carry_prior_failure(self):
        result, exc, create = self.call_with(
            [
                quality_fail_response("style"),
                quality_fail_response("structure"),
                ok_response(),
            ]
        )
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 3)
        bodies = [_dump_call(c) for c in create.call_args_list]
        self.assertEqual(len(set(bodies)), 3)
        users = [_user_message(c) for c in create.call_args_list]
        self.assertNotIn("[Retry context]", users[0])
        self.assertIn("category=quality", users[1])
        self.assertIn("style 為空", users[1])
        self.assertIn("Previous attempt 1", users[1])
        self.assertIn("category=quality", users[2])
        self.assertIn("structure 為空", users[2])
        self.assertIn("Previous attempt 2", users[2])
        systems = [_system_prompt(c) for c in create.call_args_list]
        self.assertEqual(systems[0], systems[1])
        self.assertEqual(systems[1], systems[2])

    def test_length_failure_lowers_reasoning_max_tokens_on_retry(self):
        result, exc, create = self.call_with(
            [length_truncated_response(), ok_response()]
        )
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(_reasoning_max(create.call_args_list[0]), 2000)
        self.assertEqual(_reasoning_max(create.call_args_list[1]), 1024)
        self.assertIn("category=truncated", _user_message(create.call_args_list[1]))

    def test_non_length_quality_failure_does_not_lower_reasoning(self):
        result, exc, create = self.call_with(
            [quality_fail_response("style"), ok_response()]
        )
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(_reasoning_max(create.call_args_list[0]), 2000)
        self.assertEqual(_reasoning_max(create.call_args_list[1]), 2000)
        self.assertIn("category=quality", _user_message(create.call_args_list[1]))

    def test_upstream_retry_carries_attempt_context(self):
        result, exc, create = self.call_with([connection_error(), ok_response()])
        self.assertIsNone(exc)
        self.assertEqual(create.call_count, 2)
        bodies = [_dump_call(c) for c in create.call_args_list]
        self.assertNotEqual(bodies[0], bodies[1])
        user = _user_message(create.call_args_list[1])
        self.assertIn("category=upstream", user)
        self.assertIn("attempt 1", user)
        self.assertEqual(_reasoning_max(create.call_args_list[1]), 2000)

    def test_system_prompt_is_unchanged_across_retries(self):
        result, exc, create = self.call_with(
            [connection_error(), quality_fail_response("variable"), ok_response()]
        )
        self.assertIsNone(exc)
        systems = [_system_prompt(c) for c in create.call_args_list]
        self.assertEqual(len(systems), 3)
        self.assertEqual(systems[0], systems[1])
        self.assertEqual(systems[1], systems[2])
        self.assertTrue(systems[0])

    def test_digest_output_budget_is_12000_and_other_caps_unchanged(self):
        self.assertEqual(main.DIGEST_MAX_TOKENS, 12000)
        self.assertEqual(main.DIGEST_REASONING_HEADROOM, 2500)
        self.assertEqual(main.DIGEST_REASONING_MIN_TOKENS, 1024)
        self.assertEqual(main.DIGEST_ATTEMPTS, 5)
        self.assertEqual(main.DIGEST_TIMEOUT_SECONDS, 90.0)
        self.assertEqual(main.DIGEST_DEADLINE_SECONDS, 230.0)
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), patch.object(
            main, "DIGEST_REASONING_MAX_TOKENS", 2000
        ):
            body = main.digest_reasoning_body(main.DIGEST_MAX_TOKENS)
        self.assertEqual(body["reasoning"]["max_tokens"], 2000)

    def test_retry_note_summary_is_capped(self):
        note = main.digest_retry_note(1, "quality", "Q" * 500)
        self.assertIn("category=quality", note)
        self.assertIn("Previous attempt 1", note)
        self.assertLessEqual(note.count("Q"), 300)
        self.assertIn("…", note)
        self.assertNotIn("Q" * 301, note)

    def test_long_quality_problem_is_clipped_in_retry_user_message(self):
        with patch.object(main, "digest_quality_problem", side_effect=["P" * 500, ""]):
            result, exc, create = self.call_with([ok_response(), ok_response()])
        self.assertIsNone(exc)
        retry_user = _user_message(create.call_args_list[1])
        self.assertIn("category=quality", retry_user)
        self.assertLessEqual(retry_user.count("P"), 300)
        self.assertIn("…", retry_user)


if __name__ == "__main__":
    unittest.main()
