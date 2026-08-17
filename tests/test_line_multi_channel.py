"""綁多支 LINE bot：每個頻道用自己的 secret 與 token，彼此不串線。

會出人命的是「串線」——B bot 的訊息用 A bot 的 token 回覆，會直接回到錯的
官方帳號去，所以這裡每一項都盯著「用到的是哪個頻道的憑證」。
"""

import base64
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["LINE_CHANNEL_SECRET"] = "test-secret"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "test-token"
os.environ["LINE_CHANNEL_SECRET_BOT2"] = "bot2-secret"
os.environ["LINE_CHANNEL_ACCESS_TOKEN_BOT2"] = "bot2-token"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"

from fastapi.testclient import TestClient  # noqa: E402

import line_bot  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


def sign(body: bytes, secret: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()


def text_event(text: str = "台積電法說會宣布擴廠"):
    return {
        "type": "message",
        "replyToken": "reply-token-123",
        "source": {"type": "user", "userId": "U123"},
        "message": {"type": "text", "text": text},
    }


def post(path: str, secret: str, events: list | None = None):
    body = json.dumps({"events": events if events is not None else [text_event()]}).encode()
    return client.post(path, content=body, headers={"X-Line-Signature": sign(body, secret)})


class ChannelEnvNamingTests(unittest.TestCase):
    def test_default_channel_keeps_unsuffixed_names(self):
        # 第一支 bot 的部署設定不能因為加了第二支就得跟著改
        self.assertEqual(
            line_bot._channel_env("LINE_CHANNEL_SECRET", line_bot.DEFAULT_CHANNEL),
            "LINE_CHANNEL_SECRET",
        )

    def test_named_channel_gets_uppercase_suffix(self):
        self.assertEqual(
            line_bot._channel_env("LINE_CHANNEL_ACCESS_TOKEN", "bot2"),
            "LINE_CHANNEL_ACCESS_TOKEN_BOT2",
        )

    def test_hyphen_becomes_underscore(self):
        # 路徑允許連字號，但環境變數名不能有
        self.assertEqual(
            line_bot._channel_env("LINE_CHANNEL_SECRET", "news-desk"),
            "LINE_CHANNEL_SECRET_NEWS_DESK",
        )


class ChannelRoutingTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(line_bot, "generate_and_push")
        self.task = patcher.start()
        self.addCleanup(patcher.stop)

    def test_second_channel_accepts_its_own_signature(self):
        response = post("/line/webhook/bot2", "bot2-secret")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.task.call_args.args[3], "bot2")

    def test_default_channel_still_works_and_reports_default(self):
        response = post("/line/webhook", "test-secret")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.task.call_args.args[3], line_bot.DEFAULT_CHANNEL)

    def test_first_bot_secret_cannot_sign_for_second_bot(self):
        # 串線的第一道防線：拿 A 的 secret 簽名打 B 的路徑要被擋
        response = post("/line/webhook/bot2", "test-secret")
        self.assertEqual(response.status_code, 403)
        self.task.assert_not_called()

    def test_second_bot_secret_cannot_sign_for_first_bot(self):
        response = post("/line/webhook", "bot2-secret")
        self.assertEqual(response.status_code, 403)
        self.task.assert_not_called()

    def test_unconfigured_channel_reports_missing_env(self):
        response = post("/line/webhook/nosuchbot", "whatever")
        self.assertEqual(response.status_code, 503)
        self.assertIn("LINE_CHANNEL_SECRET_NOSUCHBOT", response.json()["detail"])

    def test_illegal_channel_name_is_404(self):
        response = post("/line/webhook/../etc", "whatever")
        self.assertIn(response.status_code, (404, 307))
        self.task.assert_not_called()


class ChannelCredentialTests(unittest.TestCase):
    """實際送出的 API 呼叫要帶對應頻道的 token。"""

    def _captured_token(self, channel):
        with patch.object(line_bot.httpx, "post") as post_mock:
            post_mock.return_value.status_code = 200
            line_bot.push_text("U123", "hi", channel)
        return post_mock.call_args.kwargs["headers"]["Authorization"]

    def test_default_channel_uses_default_token(self):
        self.assertEqual(self._captured_token(line_bot.DEFAULT_CHANNEL), "Bearer test-token")

    def test_second_channel_uses_its_own_token(self):
        self.assertEqual(self._captured_token("bot2"), "Bearer bot2-token")

    def test_reply_and_push_image_also_honour_channel(self):
        for call in (
            lambda: line_bot.reply_text("rt", "hi", "bot2"),
            lambda: line_bot.push_image("U123", "https://a/x.png", "https://a/y.jpg", "bot2"),
        ):
            with patch.object(line_bot.httpx, "post") as post_mock:
                post_mock.return_value.status_code = 200
                call()
                self.assertEqual(
                    post_mock.call_args.kwargs["headers"]["Authorization"],
                    "Bearer bot2-token",
                )


class ChannelStateIsolationTests(unittest.TestCase):
    """同一個 provider 下兩支 bot 會拿到同一個 userId，角色狀態不能互相污染。"""

    def setUp(self):
        line_bot.reset_role_state()
        self.addCleanup(line_bot.reset_role_state)

    def test_role_switch_on_one_channel_does_not_leak_to_the_other(self):
        with patch.object(line_bot, "reply_text"):
            line_bot.generate_and_push("rt", "U123", "編輯", "bot2")
        self.assertEqual(line_bot._role_by_client.get("bot2:U123"), "編輯")
        self.assertIsNone(line_bot._role_by_client.get("U123"))

    def test_default_channel_key_stays_bare_user_id(self):
        # 既有的 log／限流資料是用純 userId 記的，不能因為改版就整批對不上
        self.assertEqual(line_bot._client_key(line_bot.DEFAULT_CHANNEL, "U123"), "U123")
        self.assertEqual(line_bot._client_key("bot2", "U123"), "bot2:U123")


if __name__ == "__main__":
    unittest.main()
