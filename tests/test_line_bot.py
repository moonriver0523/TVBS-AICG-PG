"""LINE webhook 的驗簽與事件分派。

背景任務 generate_and_push 一律以 patch 取代——它會呼叫付費的消化與生圖 API，
測試絕不能真的打出去。
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
os.environ["PUBLIC_BASE_URL"] = "https://example.test"

from fastapi.testclient import TestClient  # noqa: E402

import line_bot  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


def sign(body: bytes, secret: str = "test-secret") -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def text_event(text: str = "台積電法說會宣布擴廠", **source):
    return {
        "type": "message",
        "replyToken": "reply-token-123",
        "source": source or {"type": "user", "userId": "U123"},
        "message": {"type": "text", "text": text},
    }


def post(events: list, signature: str | None = None):
    body = json.dumps({"events": events}).encode()
    headers = {"X-Line-Signature": signature if signature is not None else sign(body)}
    return client.post("/line/webhook", content=body, headers=headers)


class SignatureTests(unittest.TestCase):
    def test_accepts_correct_signature(self):
        body = b'{"events":[]}'
        self.assertTrue(line_bot.valid_signature("test-secret", body, sign(body)))

    def test_rejects_tampered_body(self):
        signature = sign(b'{"events":[]}')
        self.assertFalse(
            line_bot.valid_signature("test-secret", b'{"events":[{"hacked":1}]}', signature)
        )

    def test_rejects_empty_signature(self):
        self.assertFalse(line_bot.valid_signature("test-secret", b"{}", ""))


class WebhookTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(line_bot, "generate_and_push")
        self.task = patcher.start()
        self.addCleanup(patcher.stop)

    def test_bad_signature_is_rejected(self):
        response = post([text_event()], signature="deadbeef")
        self.assertEqual(response.status_code, 403)
        self.task.assert_not_called()

    def test_text_message_schedules_generation(self):
        response = post([text_event("熊本強震")])
        self.assertEqual(response.status_code, 200)
        self.task.assert_called_once_with("reply-token-123", "U123", "熊本強震")

    def test_group_message_targets_group_id(self):
        event = text_event("新聞內容", type="group", groupId="G999", userId="U123")
        post([event])
        self.assertEqual(self.task.call_args.args[1], "G999")

    def test_non_text_events_are_ignored(self):
        sticker = {
            "type": "message",
            "replyToken": "r",
            "source": {"userId": "U1"},
            "message": {"type": "sticker", "packageId": "1"},
        }
        follow = {"type": "follow", "replyToken": "r", "source": {"userId": "U1"}}
        response = post([sticker, follow])
        self.assertEqual(response.status_code, 200)
        self.task.assert_not_called()

    def test_blank_text_is_ignored(self):
        post([text_event("   ")])
        self.task.assert_not_called()

    def test_line_verify_empty_events_returns_200(self):
        # LINE Console 的 Verify 會送出空 events，必須正常回 200
        response = post([])
        self.assertEqual(response.status_code, 200)
        self.task.assert_not_called()

    def test_multiple_events_each_scheduled(self):
        post([text_event("第一則"), text_event("第二則")])
        self.assertEqual(self.task.call_count, 2)


class TargetTests(unittest.TestCase):
    def test_room_id_used_when_no_user_or_group(self):
        self.assertEqual(line_bot.target_of({"source": {"roomId": "R1"}}), "R1")

    def test_empty_when_source_missing(self):
        self.assertEqual(line_bot.target_of({}), "")


if __name__ == "__main__":
    unittest.main()
