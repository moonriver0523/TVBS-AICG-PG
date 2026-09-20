# -*- coding: utf-8 -*-
"""2026-09-14 抓 bug 輪（測試 session 第四輪）bug 3：yt-cover 標題太長回 500 而非 4xx。"""
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


class YtCoverTooLongTitleTests(unittest.TestCase):
    """bug 3：yt-cover 標題排不下以前回 500；是使用者改得掉的輸入問題，比照十點回 400。"""

    def test_title_that_cannot_fit_returns_400(self):
        req = main.YtCoverRequest(
            title="測試標題六十字元邊界測試測試標題六十字元邊界測試",
            layout="hourly", title_mode="composite", provider="gpt",
            date_text="2026/09/14", time_text="21:00",
            slot_left=[{"data_url": _data_url(_png((1920, 1080))), "purpose": "asis"}],
        )
        boom = compose.ComposeError("標題太長，縮到最小字級仍超出版面：「測試」（請縮短這一行）")
        with patch.object(main, "_archive_generation", lambda **k: None),                 patch.object(compose, "compose_yt_hourly_cover", side_effect=boom):
            with self.assertRaises(HTTPException) as ctx:
                main.editor_yt_cover(req)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("標題太長", ctx.exception.detail)



if __name__ == "__main__":
    unittest.main()
