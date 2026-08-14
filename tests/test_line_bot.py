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


class InputFilterWiringTests(unittest.TestCase):
    """generate_and_push 的前置過濾：被擋訊息回覆原因、跳過付費呼叫、不 push。"""

    def setUp(self):
        import input_filter

        input_filter.reset_state()
        self.addCleanup(input_filter.reset_state)

    def test_rejected_message_replies_and_skips_generation(self):
        with (
            patch.object(line_bot, "reply_text") as reply,
            patch.object(line_bot, "push_image") as push_img,
            patch.object(line_bot, "push_text") as push_txt,
            patch("main.generate_news_image") as generate,
        ):
            line_bot.generate_and_push("rt", "U123", "短")
        generate.assert_not_called()
        push_img.assert_not_called()
        push_txt.assert_not_called()
        reply.assert_called_once()
        self.assertIn("太短", reply.call_args.args[1])

    def test_accepted_message_still_acks_then_generates(self):
        from main import NewsImageGenerateResponse

        fake = NewsImageGenerateResponse(
            image_data_base64=base64.b64encode(b"img").decode(), mime_type="image/png", model="m"
        )
        with (
            patch.object(line_bot, "reply_text") as reply,
            patch.object(line_bot, "push_image"),
            patch.object(line_bot, "save_image", return_value=("a.png", "b.jpg")),
            patch("main.generate_news_image", return_value=fake) as generate,
        ):
            line_bot.generate_and_push("rt", "U123", "台積電法說會宣布擴廠 資本支出上調至新高")
        generate.assert_called_once()
        self.assertIn("收到", reply.call_args.args[1])

    def test_duplicate_within_60s_is_rejected_second_time(self):
        from main import NewsImageGenerateResponse

        fake = NewsImageGenerateResponse(
            image_data_base64=base64.b64encode(b"img").decode(), mime_type="image/png", model="m"
        )
        text = "台積電法說會宣布擴廠 資本支出上調至新高"
        with (
            patch.object(line_bot, "reply_text") as reply,
            patch.object(line_bot, "push_image"),
            patch.object(line_bot, "save_image", return_value=("a.png", "b.jpg")),
            patch("main.generate_news_image", return_value=fake) as generate,
        ):
            line_bot.generate_and_push("rt1", "U123", text)
            line_bot.generate_and_push("rt2", "U123", text)
        generate.assert_called_once()  # 第二次被 dedup 擋下
        self.assertIn("重骰", reply.call_args.args[1])


class ParseLineRoleTests(unittest.TestCase):
    """預設記者；只有明確指令才走編輯。新聞內文的「編輯部」不能誤判。"""

    def test_plain_news_defaults_to_reporter(self):
        role, news, standalone = line_bot.parse_line_role(
            "台積電法說會宣布擴廠 資本支出上調至新高"
        )
        self.assertEqual(role, "記者")
        self.assertIn("台積電", news)
        self.assertFalse(standalone)

    def test_editor_prefix_with_colon(self):
        role, news, standalone = line_bot.parse_line_role(
            "編輯：台積電法說會宣布擴廠 資本支出上調至新高"
        )
        self.assertEqual((role, standalone), ("編輯", False))
        self.assertTrue(news.startswith("台積電"))

    def test_editor_prefix_with_newline(self):
        role, news, standalone = line_bot.parse_line_role(
            "編輯\n台積電法說會宣布擴廠 資本支出上調至新高"
        )
        self.assertEqual(role, "編輯")
        self.assertTrue(news.startswith("台積電"))

    def test_instruction_line_switches_role(self):
        role, news, standalone = line_bot.parse_line_role(
            "指示: 編輯\n台積電法說會宣布擴廠 資本支出上調至新高"
        )
        self.assertEqual((role, standalone), ("編輯", False))
        self.assertNotIn("指示", news)
        self.assertIn("台積電", news)

    def test_newsroom_compound_is_not_an_instruction(self):
        text = "編輯部今天公布人事異動案 社長改由副社長接任"
        role, news, standalone = line_bot.parse_line_role(text)
        self.assertEqual((role, news, standalone), ("記者", text, False))

    def test_standalone_editor_does_not_leave_news_text(self):
        role, news, standalone = line_bot.parse_line_role("編輯")
        self.assertEqual((role, news, standalone), ("編輯", "", True))

    def test_previous_role_is_kept_when_no_new_instruction(self):
        role, news, standalone = line_bot.parse_line_role(
            "台積電法說會宣布擴廠 資本支出上調至新高", previous="編輯"
        )
        self.assertEqual((role, standalone), ("編輯", False))
        self.assertIn("台積電", news)


class LineRoleWiringTests(unittest.TestCase):
    def setUp(self):
        import input_filter

        input_filter.reset_state()
        line_bot.reset_role_state()
        self.addCleanup(input_filter.reset_state)
        self.addCleanup(line_bot.reset_role_state)

    def _fake_image(self):
        from main import NewsImageGenerateResponse

        return NewsImageGenerateResponse(
            image_data_base64=base64.b64encode(b"img").decode(),
            mime_type="image/png",
            model="m",
        )

    def test_plain_news_sends_reporter_role(self):
        with (
            patch.object(line_bot, "reply_text"),
            patch.object(line_bot, "push_image"),
            patch.object(line_bot, "save_image", return_value=("a.png", "b.jpg")),
            patch("main.generate_news_image", return_value=self._fake_image()) as generate,
        ):
            line_bot.generate_and_push(
                "rt", "U123", "台積電法說會宣布擴廠 資本支出上調至新高"
            )
        req = generate.call_args.args[0]
        self.assertEqual(req.role, "記者")

    def test_editor_prefix_sends_editor_role_and_standard_density(self):
        with (
            patch.object(line_bot, "reply_text") as reply,
            patch.object(line_bot, "push_image"),
            patch.object(line_bot, "save_image", return_value=("a.png", "b.jpg")),
            patch("main.generate_news_image", return_value=self._fake_image()) as generate,
        ):
            line_bot.generate_and_push(
                "rt", "U123", "編輯\n台積電法說會宣布擴廠 資本支出上調至新高"
            )
        req = generate.call_args.args[0]
        self.assertEqual(req.role, "編輯")
        self.assertEqual(req.density, "standard")
        self.assertEqual(req.news_text, "台積電法說會宣布擴廠 資本支出上調至新高")
        self.assertIn("編輯", reply.call_args.args[1])

    def test_standalone_editor_replies_and_skips_generation(self):
        with (
            patch.object(line_bot, "reply_text") as reply,
            patch.object(line_bot, "push_image") as push_img,
            patch("main.generate_news_image") as generate,
        ):
            line_bot.generate_and_push("rt", "U123", "編輯")
        generate.assert_not_called()
        push_img.assert_not_called()
        reply.assert_called_once()
        self.assertIn("編輯", reply.call_args.args[1])

    def test_remembered_editor_applies_to_next_plain_news(self):
        with (
            patch.object(line_bot, "reply_text"),
            patch.object(line_bot, "push_image"),
            patch.object(line_bot, "save_image", return_value=("a.png", "b.jpg")),
            patch("main.generate_news_image", return_value=self._fake_image()) as generate,
        ):
            line_bot.generate_and_push("rt1", "U123", "編輯")
            line_bot.generate_and_push(
                "rt2", "U123", "台積電法說會宣布擴廠 資本支出上調至新高"
            )
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(generate.call_args.args[0].role, "編輯")


class TargetTests(unittest.TestCase):
    def test_room_id_used_when_no_user_or_group(self):
        self.assertEqual(line_bot.target_of({"source": {"roomId": "R1"}}), "R1")

    def test_empty_when_source_missing(self):
        self.assertEqual(line_bot.target_of({}), "")


if __name__ == "__main__":
    unittest.main()
