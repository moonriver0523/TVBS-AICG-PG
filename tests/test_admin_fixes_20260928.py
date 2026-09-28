import contextlib
import io
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import admin_console
import clerk_auth
import info_layout
import main


def _decision(text: str, *, point_count: int = 4) -> str:
    return info_layout.select_info_layout(
        text,
        "記者",
        "simplified",
        "資料圖表",
        point_count=point_count,
    ).mode


def _clerk_response(status_code: int, data: dict | None = None) -> Mock:
    response = Mock(status_code=status_code)
    if data is not None:
        response.json.return_value = data
    return response


class ClerkAuditIdentityTests(unittest.TestCase):
    def setUp(self):
        clerk_auth._user_cache.clear()

    def tearDown(self):
        clerk_auth._user_cache.clear()

    def test_transient_non_200_is_logged_with_user_and_retried_once(self):
        responses = [
            _clerk_response(503),
            _clerk_response(
                200,
                {
                    "primary_email_address_id": "mail_1",
                    "email_addresses": [
                        {"id": "mail_1", "email_address": "reporter@example.com"}
                    ],
                    "first_name": "Audit",
                    "last_name": "Reporter",
                },
            ),
        ]
        output = io.StringIO()
        with patch.object(clerk_auth, "SECRET_KEY", "sk_test_must_not_leak"), \
             patch.object(clerk_auth.httpx, "get", side_effect=responses) as get, \
             contextlib.redirect_stdout(output):
            info = clerk_auth._fetch_user("user_retry")

        self.assertEqual(get.call_count, 2)
        self.assertEqual(info["email"], "reporter@example.com")
        self.assertIn("status=503", output.getvalue())
        self.assertIn("user_id=user_retry", output.getvalue())
        self.assertNotIn("sk_test_must_not_leak", output.getvalue())
        self.assertLessEqual(get.call_args.kwargs["timeout"], 3.0)

    def test_exception_is_logged_with_user_and_stops_after_one_retry(self):
        output = io.StringIO()
        with patch.object(clerk_auth, "SECRET_KEY", "sk_test_must_not_leak"), \
             patch.object(
                 clerk_auth.httpx,
                 "get",
                 side_effect=[RuntimeError("temporary"), RuntimeError("still down")],
             ) as get, contextlib.redirect_stdout(output):
            info = clerk_auth._fetch_user("user_exception")

        self.assertEqual(info, {})
        self.assertEqual(get.call_count, 2)
        self.assertEqual(output.getvalue().count("user_id=user_exception"), 2)
        self.assertIn("RuntimeError", output.getvalue())
        self.assertNotIn("sk_test_must_not_leak", output.getvalue())

    def test_expired_success_is_used_when_refresh_fails(self):
        stale = {
            "user_id": "user_stale",
            "email": "known@example.com",
            "name": "Known Reporter",
        }
        clerk_auth._user_cache["user_stale"] = (
            time.time() - clerk_auth._USER_CACHE_TTL - 30,
            stale,
        )
        with patch.object(clerk_auth, "_fetch_user", return_value={}):
            self.assertEqual(clerk_auth._user_info("user_stale"), stale)

    def test_first_lookup_failure_still_returns_traceable_user_id(self):
        with patch.object(clerk_auth, "_fetch_user", return_value={}):
            info = clerk_auth._user_info("user_first_failure")
        self.assertEqual(info["user_id"], "user_first_failure")
        self.assertEqual(info["name"], "user_first_failure")
        self.assertEqual(info["email"], "")

    def test_domain_allowlist_stays_fail_closed_without_email(self):
        client = Mock()
        client.get_signing_key_from_jwt.return_value = SimpleNamespace(key="public-key")
        with patch.object(clerk_auth, "ENABLED", True), \
             patch.object(clerk_auth, "ALLOWED_EMAIL_DOMAINS", ("example.com",)), \
             patch.object(clerk_auth, "_get_jwk_client", return_value=client), \
             patch.object(clerk_auth.jwt, "decode", return_value={"sub": "user_no_email"}), \
             patch.object(
                 clerk_auth,
                 "_user_info",
                 return_value={
                     "user_id": "user_no_email",
                     "name": "user_no_email",
                     "email": "",
                 },
             ):
            self.assertIsNone(clerk_auth.verify_token("valid-token"))

    def test_admin_uses_user_id_only_when_human_identity_is_missing(self):
        row = admin_console._row({"user_id": "user_legacy", "request_id": "req-1"})
        unsigned = admin_console._row({"request_id": "req-2"})
        self.assertIn("user_legacy", row)
        self.assertNotIn("（未署名）", row)
        self.assertIn("（未署名）", unsigned)

    def test_api_key_dependency_does_not_refetch_user_after_middleware(self):
        with patch.object(clerk_auth, "ENABLED", True), \
             patch.object(main, "current_user", return_value={"user_id": "user_known"}), \
             patch.object(clerk_auth, "verify_token") as verify_token:
            main.verify_internal_api_key(
                x_api_key="",
                authorization="Bearer already-verified-token",
            )
        verify_token.assert_not_called()

    def test_api_key_dependency_still_verifies_without_middleware_context(self):
        with patch.object(clerk_auth, "ENABLED", True), \
             patch.object(main, "current_user", return_value={}), \
             patch.object(
                 clerk_auth,
                 "verify_token",
                 return_value={"user_id": "user_direct"},
             ) as verify_token:
            main.verify_internal_api_key(
                x_api_key="",
                authorization="Bearer direct-token",
            )
        verify_token.assert_called_once_with("direct-token")


class SlashDateTimelineTests(unittest.TestCase):
    def test_common_slash_dates_are_timeline_nodes(self):
        cases = [
            "南天宮9/11出借，原定9/28歸還，在9/20繞境當天使用。",
            "展期自9/11～9/28，預計10/1恢復開放。",
            "2026/9/11公告，2026/9/28正式生效。",
            "2026/3/2比賽開打，2026/4/3公布比分。",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(_decision(text), "timeline")

    def test_scores_ratios_always_on_and_urls_are_not_dates(self):
        cases = [
            "系列賽比分3/2、4/3，另一場則是2/1，主隊連勝。",
            "系統維持24/7運作，抽樣比例3/2與5/4，結果沒有日期意義。",
            "資料在https://example.com/9/11/news與https://example.com/9/28/news。",
            "錯誤輸入13/40、0/12、12/32都不是合理日期。",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertNotEqual(_decision(text), "timeline")


class ParallelRankingTests(unittest.TestCase):
    def test_front_five_same_unit_ranking_uses_icon_grid(self):
        text = (
            "常見公車爭議 據台北市公共運輸處資料 "
            "115年1-5月申訴公車服務品質優缺失成案數統計表》 前五名 "
            "過站不停：544 件 脫班：513 件 服務態度欠佳：221 件 "
            "未依規定站位停靠：223 件 任意變換車道：194 件"
        )
        self.assertEqual(_decision(text), "icon_grid")

    def test_unranked_same_unit_labels_are_still_parallel_data(self):
        text = "北區：18件 中區：16件 南區：12件 東區：9件，均為同一統計口徑。"
        self.assertEqual(_decision(text), "icon_grid")

    def test_incidental_numbers_in_one_scene_remain_feature_spread(self):
        text = (
            "台中凌晨發生死亡車禍，護理師過馬路時遭轎車撞擊，駕駛肇事後逃逸，"
            "警方調閱監視器追查並逮捕嫌犯。家屬要求釐清責任，檢警持續調查事故原因，"
            "附近店家也提供行車紀錄與監視畫面協助還原現場。"
        )
        self.assertEqual(_decision(text), "feature_spread")


if __name__ == "__main__":
    unittest.main()
