# -*- coding: utf-8 -*-
"""B112：refine 不白打斷句模型，稽核記錄保存實際生圖 prompt。"""

import base64
import io
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "b112-test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "b112-internal-key")

import compose  # noqa: E402
import main  # noqa: E402


CLIENT = TestClient(main.app)


def _headers() -> dict:
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}


def _png(size=(1920, 1080), colour=(40, 70, 100)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _encoded_png() -> str:
    return base64.b64encode(_png()).decode("ascii")


def _data_url() -> str:
    return "data:image/png;base64," + base64.b64encode(_png((640, 640))).decode("ascii")


def _fake_image(req):
    return main.ImageGenerateResponse(
        image_data_base64=base64.b64encode(_png((1536, 864))).decode("ascii"),
        mime_type="image/png",
        model="b112-fake-image",
    )


class BreakHintRoutingTests(unittest.TestCase):
    TEN_TITLE = "王鴻薇揭露歐洲中央銀行政策"
    YT_TITLE = "王鴻薇揭露歐洲中央銀行政策"

    def _post_ten(self, *, mode: str, with_background: bool):
        body = {
            "title_left": self.TEN_TITLE,
            "layout": "full",
            "mode": mode,
            "title_creativity": 1,
        }
        if with_background:
            body["background_image_base64"] = _encoded_png()
        with patch.object(main, "segment_titles_for_breaks", return_value={}) as segment, \
             patch.object(main, "resolve_cover_visuals", return_value=("本地假場景", "")), \
             patch.object(main, "generate_image_raw", side_effect=_fake_image), \
             patch.object(main, "_archive_generation"):
            response = CLIENT.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(response.status_code, 200, response.text)
        return segment

    def _post_yt(self, *, mode: str, with_background: bool):
        body = {
            "title": self.YT_TITLE,
            "layout": "news",
            "title_mode": mode,
            "creativity": 1,
        }
        if with_background:
            body.update({
                "background_image_base64": _encoded_png(),
                "background_is_ai": True,
            })
        plan = main.YtCoverPlan((("王鴻薇揭露", "歐洲中央銀行政策")), "本地假場景", [], [])
        with patch.object(main, "segment_titles_for_breaks", return_value={}) as segment, \
             patch.object(main, "resolve_yt_cover_plan", return_value=plan), \
             patch.object(main, "generate_image_raw", side_effect=_fake_image), \
             patch.object(main, "_archive_generation"):
            response = CLIENT.post("/api/editor/yt-cover", json=body, headers=_headers())
        self.assertEqual(response.status_code, 200, response.text)
        return segment

    def test_ten_ai_refine_skips_break_model_and_clears_hints(self):
        with patch.object(compose, "set_break_hints") as set_hints:
            segment = self._post_ten(mode="ai", with_background=True)
        segment.assert_not_called()
        set_hints.assert_called_with({})

    def test_ten_composite_recomposite_still_calls_break_model(self):
        self._post_ten(mode="composite", with_background=True).assert_called_once()

    def test_ten_ai_without_background_still_calls_break_model(self):
        self._post_ten(mode="ai", with_background=False).assert_called_once()

    def test_yt_ai_refine_skips_break_model_and_clears_hints(self):
        with patch.object(compose, "set_break_hints") as set_hints:
            segment = self._post_yt(mode="ai", with_background=True)
        segment.assert_not_called()
        set_hints.assert_called_with({})

    def test_yt_composite_recomposite_still_calls_break_model(self):
        self._post_yt(mode="composite", with_background=True).assert_called_once()

    def test_yt_ai_without_background_still_calls_break_model(self):
        self._post_yt(mode="ai", with_background=False).assert_called_once()


class PromptAuditTests(unittest.TestCase):
    def test_ten_request_logs_use_the_sent_prompt_for_full_and_split(self):
        for layout in ("full", "split"):
            with self.subTest(layout=layout):
                archived = []
                logged = []
                sent = []

                def capture_image(req):
                    sent.append(req.prompt)
                    return _fake_image(req)

                body = {
                    "title_left": "王鴻薇揭露歐洲中央銀行政策",
                    "layout": layout,
                    "mode": "ai",
                    "title_creativity": 1,
                }
                if layout == "split":
                    body["title_right"] = "全球市場震盪"
                with patch.object(main, "segment_titles_for_breaks", return_value={}), \
                     patch.object(main, "resolve_cover_visuals", return_value=("左側畫面", "右側畫面")), \
                     patch.object(main, "generate_image_raw", side_effect=capture_image), \
                     patch.object(main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)), \
                     patch.object(main.request_log, "log_generation", side_effect=lambda **kw: logged.append(kw)):
                    response = CLIENT.post("/api/editor/cover", json=body, headers=_headers())

                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(len(sent), 1)
                actual_prompt = main.ensure_final_image_baseline(sent[0])
                self.assertEqual(archived[-1]["prompt"], actual_prompt)
                self.assertEqual(logged[-1]["prompt"], actual_prompt)

    def test_yt_ai_title_gate_fallback_archives_the_sent_image_prompt(self):
        archived = []
        logged = []
        sent = []

        def opaque_title_layer(req):
            sent.append(req.prompt)
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png()).decode("ascii"),
                mime_type="image/png",
                model="b112-fake-image",
            )

        body = {
            "title": "王鴻薇揭露 歐洲中央銀行政策",
            "layout": "news",
            "title_mode": "ai",
            "creativity": 1,
            "provider": "gpt",
            "reference_images": [{"data_url": _data_url(), "purpose": "asis"}],
        }
        plan = main.YtCoverPlan(
            (("王鴻薇揭露", "歐洲中央銀行政策")), "本地假場景", [], []
        )
        with patch.object(main, "segment_titles_for_breaks", return_value={}), \
             patch.object(main, "resolve_yt_cover_plan", return_value=plan), \
             patch.object(main, "generate_image_raw", side_effect=opaque_title_layer), \
             patch.object(main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)), \
             patch.object(main.request_log, "log_generation", side_effect=lambda **kw: logged.append(kw)):
            response = CLIENT.post("/api/editor/yt-cover", json=body, headers=_headers())

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["title_mode"], "composite")
        self.assertEqual(len(sent), 1)
        actual_prompt = main.ensure_final_image_baseline(sent[0])
        self.assertEqual(archived[-1]["prompt"], actual_prompt)
        self.assertEqual(logged[-1]["prompt"], actual_prompt)

    def test_yt_composite_archive_and_request_log_keep_the_original_prompt(self):
        archived = []
        logged = []
        plan = main.YtCoverPlan((("王鴻薇揭露", "歐洲中央銀行政策")), "既有畫面描述", [], [])
        body = {
            "title": "王鴻薇揭露歐洲中央銀行政策",
            "layout": "news",
            "title_mode": "composite",
            "background_image_base64": _encoded_png(),
            "background_is_ai": True,
        }
        with patch.object(main, "segment_titles_for_breaks", return_value={}), \
             patch.object(main, "resolve_yt_cover_plan", return_value=plan), \
             patch.object(main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)), \
             patch.object(main.request_log, "log_generation", side_effect=lambda **kw: logged.append(kw)):
            response = CLIENT.post("/api/editor/yt-cover", json=body, headers=_headers())

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(archived[-1]["prompt"], "既有畫面描述")
        self.assertEqual(logged[-1]["prompt"], "既有畫面描述")


if __name__ == "__main__":
    unittest.main()
