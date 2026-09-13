# -*- coding: utf-8 -*-
"""2026-09-14 使用者裁決：滿版原圖放置最多 4 張，第 5 張回 400，不再默默只取前 4 張。"""
import base64
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import main  # noqa: E402

def _headers() -> dict:
    # 整包跑時其他測試模組會在 import 期改寫 NEWS_IMAGE_API_KEY，執行時再讀才對得上
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}


def _photo(colour):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), colour).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _slot(n, purpose="asis"):
    return [{"data_url": _photo((i * 40 % 255, 80, 120)), "purpose": purpose} for i in range(n)]


class TenCoverFullCapTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_five_asis_on_full_layout_is_400_before_any_model_call(self):
        with patch.object(main, "apply_title_break_hints") as breaks, \
                patch.object(main, "_editor_cover_full") as full:
            res = self.client.post("/api/editor/cover", headers=_headers(), json={
                "title_left": "滿版五張測試", "layout": "full", "mode": "composite",
                "slot_left": _slot(5),
            })
        self.assertEqual(res.status_code, 400)
        self.assertIn("最多 4 張", res.json()["detail"])
        self.assertIn("收到 5 張", res.json()["detail"])
        breaks.assert_not_called()
        full.assert_not_called()

    def test_four_asis_still_pass_the_gate(self):
        with patch.object(main, "apply_title_break_hints"), \
                patch.object(main, "_editor_cover_full", return_value=main.TenCoverResponse(
                    image_data_base64="", mime_type="image/png", model="x", prompt="")) as full:
            res = self.client.post("/api/editor/cover", headers=_headers(), json={
                "title_left": "滿版四張測試", "layout": "full", "mode": "composite",
                "slot_left": _slot(4),
            })
        self.assertEqual(res.status_code, 200, res.text)
        full.assert_called_once()

    def test_old_shared_list_is_capped_too(self):
        refs = [{"data_url": _photo((10, 20, 30)), "purpose": "asis"} for _ in range(5)]
        res = self.client.post("/api/editor/cover", headers=_headers(), json={
            "title_left": "舊清單五張", "layout": "full", "mode": "composite", "reference_images": refs,
        })
        self.assertEqual(res.status_code, 400)

    def test_split_half_slots_are_not_governed_by_this_gate(self):
        """雙切半格 ≥2 張走 lock_half_slot_asis 鎖成 AI改圖，不歸這道 400 管。"""
        self.assertEqual(
            main.reject_excess_asis(main.lock_half_slot_asis(
                [main.UserReferenceImage(data_url=_photo((1, 2, 3)), purpose="asis") for _ in range(5)]
            ), where="半格"),
            None,
        )


class YtSingleCapTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_five_asis_on_single_topic_is_400(self):
        with patch.object(main, "apply_title_break_hints") as breaks:
            res = self.client.post("/api/editor/yt-cover", headers=_headers(), json={
                "title": "整點單則 五張測試", "layout": "hourly", "title_mode": "composite",
                "slot_left": _slot(5),
            })
        self.assertEqual(res.status_code, 400)
        self.assertIn("單則原圖放置最多 4 張", res.json()["detail"])
        breaks.assert_not_called()


if __name__ == "__main__":
    unittest.main()
