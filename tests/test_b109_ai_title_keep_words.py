# -*- coding: utf-8 -*-
"""B109（2026-09-26）：AI 標題也要詞語完整優先，並留下可回查的最終 prompt。"""
import base64
import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402


def _completion(payload: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
    )


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1280, 720), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


class AiTitleWordIntegrityTests(unittest.TestCase):
    def test_ten_ai_title_final_prompt_uses_model_phrase_boundaries(self):
        """關鍵交叉測試：斷句模型的詞組邊界必須一路進到實際生圖 prompt。"""
        captured = {}
        archived = []
        break_payload = (
            '{"segments":[{"text":"王鴻薇揭露歐洲中央銀行政策",'
            '"phrases":["王鴻薇","揭露","歐洲中央銀行","政策"]}]}'
        )

        def fake_generate(req):
            captured["prompt"] = req.prompt
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png()).decode("ascii"),
                mime_type="image/png",
                model="fake-image",
            )

        with patch.object(
            main, "digest_completion", return_value=_completion(break_payload)
        ) as digest, patch.object(
            main, "resolve_cover_visuals", return_value=("立法院記者會", "國際金融畫面")
        ), patch.object(
            main, "generate_image_raw", side_effect=fake_generate
        ), patch.object(
            main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)
        ):
            response = client.post(
                "/api/editor/cover",
                json={
                    "title_left": "王鴻薇揭露歐洲中央銀行政策",
                    "title_right": "全球市場震盪",
                    "layout": "split",
                    "mode": "ai",
                    "title_creativity": 1,
                },
                headers=_headers(),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(digest.call_args.kwargs["site"], "title-break")
        prompt = captured["prompt"]
        self.assertIn("Line 1: 王鴻薇揭露", prompt)
        self.assertIn("Line 2: 歐洲中央銀行", prompt)
        self.assertIn("Line 3: 政策", prompt)
        self.assertNotIn("王鴻薇揭\n", prompt)
        self.assertNotIn("露歐洲中", prompt)
        self.assertEqual(archived[-1]["prompt"], main.ensure_final_image_baseline(prompt))
        self.assertIn("王鴻薇揭露\n歐洲中央銀行\n政策", archived[-1]["variable"])

    def test_manual_half_width_space_still_fixes_the_two_yt_rows(self):
        self.assertEqual(
            editor_formats.split_live_title("王鴻薇揭露 歐洲中央銀行政策"),
            ("王鴻薇揭露", "歐洲中央銀行政策"),
        )


class PromptContractTests(unittest.TestCase):
    def test_yt_digest_prompts_prioritise_word_integrity_over_target_length(self):
        for prompt in (
            editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT,
            editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT_HOURLY,
        ):
            with self.subTest(prompt=prompt[:40]):
                self.assertIn("Word integrity has higher priority", prompt)
                self.assertIn("5–12", prompt)
        self.assertIn("at most 18 characters", editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT_HOURLY)

    def test_final_yt_prompts_lock_line1_and_line2_but_live24_is_unchanged(self):
        for prompt in (
            editor_formats.YT_COVER_FULL_PROMPT_NEWS,
            editor_formats.YT_COVER_FULL_PROMPT_HOURLY,
            editor_formats.YT_COVER_FULL_PROMPT_HOT,
        ):
            with self.subTest(prompt=prompt[:55]):
                self.assertIn("FINAL ROWS", prompt)
                self.assertIn("Never reflow, merge or split", prompt)
                self.assertIn("shrink the type", prompt)
        self.assertNotIn("FINAL ROWS", editor_formats.YT_COVER_FULL_PROMPT_LIVE24)


class AuditTests(unittest.TestCase):
    def test_digest_archive_keeps_both_titles(self):
        archived = []
        with patch.object(
            main,
            "digest_completion",
            return_value=_completion(
                '{"topics":2,"title":"第一則完整標題","title_second":"第二則完整標題"}'
            ),
        ), patch.object(
            main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)
        ):
            response = client.post(
                "/api/editor/cover-titles",
                json={"news_text": "第一則測試新聞以及第二則測試新聞內容", "target": "yt_hourly"},
                headers=_headers(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(archived[-1]["variable"], "第一則完整標題\n第二則完整標題")

    def test_ten_digest_archive_keeps_the_right_title(self):
        archived = []
        with patch.object(
            main,
            "digest_completion",
            return_value=_completion(
                '{"topics":2,"title_left":"左側新聞 完整標題","title_right":"右側新聞 完整標題",'
                '"side_labels":[],"info_chips":[]}'
            ),
        ), patch.object(
            main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)
        ):
            response = client.post(
                "/api/editor/cover-titles",
                json={"news_text": "第一則測試新聞以及第二則測試新聞內容", "target": "ten_cover"},
                headers=_headers(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(archived[-1]["variable"], "左側新聞 完整標題\n右側新聞 完整標題")

    def test_yt_ai_title_archive_uses_sent_prompt_and_final_rows(self):
        archived = []
        captured = {}

        def fake_generate(req):
            captured["prompt"] = req.prompt
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png()).decode("ascii"),
                mime_type="image/png",
                model="fake-image",
            )

        with patch.object(
            main,
            "derive_yt_cover_plan",
            return_value={"visual": "中央銀行外觀", "portrait_subjects": []},
        ), patch.object(
            main, "segment_titles_for_breaks", return_value={}
        ), patch.object(
            main, "generate_image_raw", side_effect=fake_generate
        ), patch.object(
            main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)
        ):
            response = client.post(
                "/api/editor/yt-cover",
                json={
                    "title": "王鴻薇揭露 歐洲中央銀行政策",
                    "title_mode": "ai",
                    "creativity": 1,
                },
                headers=_headers(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            archived[-1]["prompt"], main.ensure_final_image_baseline(captured["prompt"])
        )
        self.assertEqual(archived[-1]["variable"], "王鴻薇揭露\n歐洲中央銀行政策")


if __name__ == "__main__":
    unittest.main()
