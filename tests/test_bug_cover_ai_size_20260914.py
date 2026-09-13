# -*- coding: utf-8 -*-
"""2026-09-14 抓 bug 輪（測試 session 第四輪）bug 1：十點 AI 模式輸出 1280×720。"""
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


class CoverAiOutputSizeTests(unittest.TestCase):
    """bug 1：十點 AI 模式以前照模型原尺寸（1280×720）出去，合成版與 YT 都是 1920×1080。"""

    def test_fit_cover_canvas_upsizes_to_the_cover_canvas(self):
        out = compose.fit_cover_canvas(_png((1280, 720)))
        with Image.open(io.BytesIO(out)) as im:
            self.assertEqual(im.size, compose.COVER_CANVAS)

    def test_a_canvas_sized_input_is_returned_untouched(self):
        raw = _png(compose.COVER_CANVAS)
        self.assertIs(compose.fit_cover_canvas(raw), raw)

    def test_the_cover_ai_path_calls_it_before_pasting(self):
        """_cover_ai 的 _post_paste 先 fit 再貼 Logo：貼 Logo 收到的一定是定版尺寸。"""
        seen = []
        real = compose.paste_cover_logo

        def spy(raw, **kw):
            with Image.open(io.BytesIO(raw)) as im:
                seen.append(im.size)
            return real(raw, **kw)

        req = main.TenCoverRequest(
            title_left="測試", layout="full", mode="ai", provider="gpt", date_text="2026/09/14",
            background_image_base64=base64.b64encode(_png((1280, 720))).decode(),
            background_mime_type="image/png",
        )
        with patch.object(compose, "paste_cover_logo", side_effect=spy):
            main._cover_ai(req, "2026/09/14", main.CoverVisuals("測試", "測試"))
        self.assertEqual(seen, [compose.COVER_CANVAS])



if __name__ == "__main__":
    unittest.main()
