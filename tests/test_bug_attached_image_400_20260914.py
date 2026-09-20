# -*- coding: utf-8 -*-
"""2026-09-14 抓 bug 輪（測試 session 第四輪）bug 2：壞的 data_url 炸 500。"""
import base64
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

from fastapi import HTTPException  # noqa: E402

import compose  # noqa: E402
import main  # noqa: E402


def _png(size=(1280, 720), colour=(40, 60, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


def _data_url(raw: bytes, mime="image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


class AttachedImageValidationTests(unittest.TestCase):
    """bug 2：data_url 不是圖片時以前一路炸到 compose 的 Image.open（對外 500）。"""

    def test_text_plain_is_rejected_with_400(self):
        with self.assertRaises(HTTPException) as ctx:
            main.decode_attached_image("data:text/plain;base64,aGVsbG8gd29ybGQ=")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("不是可讀的圖片檔", ctx.exception.detail)

    def test_broken_base64_is_rejected_with_400(self):
        with self.assertRaises(HTTPException) as ctx:
            main.decode_attached_image("data:image/png;base64,!!!not_valid_base64!!!===")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_not_a_data_url_is_rejected_with_400(self):
        with self.assertRaises(HTTPException) as ctx:
            main.decode_attached_image("https://example.com/a.png")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("不是 data URL", ctx.exception.detail)

    def test_a_real_image_round_trips(self):
        raw = _png((64, 36))
        self.assertEqual(main.decode_attached_image(_data_url(raw)), raw)

    def test_the_cover_endpoint_uses_it_for_slot_images(self):
        """滿版原圖放置走 ten_cover_full_asis_images：壞圖要在入口被擋成 400。"""
        req = main.TenCoverRequest(
            title_left="測試", layout="full", mode="composite", provider="gpt",
            slot_left=[{"data_url": "data:text/plain;base64,aGVsbG8=", "purpose": "asis"}],
        )
        with self.assertRaises(HTTPException) as ctx:
            main.ten_cover_full_asis_images(req)
        self.assertEqual(ctx.exception.status_code, 400)



if __name__ == "__main__":
    unittest.main()
