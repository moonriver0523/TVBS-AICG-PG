"""整點時間帶 XX:XX 用 Times New Roman Bold（2026-09-13 使用者裁決）。

字型檔直接包在 static/fonts/timesbd.ttf——Cloud Run 沒有系統 Times，沒包進 repo 正式站看不到。
"""

import io
import os
import unittest
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402


def _flat(size=(1280, 720)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (40, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


class HourlyTimeFont(unittest.TestCase):
    def test_bundled_font_is_times_new_roman_bold(self):
        self.assertTrue(compose.TIME_FONT_PATH.exists(), compose.TIME_FONT_PATH)
        family, style = compose._time_font(40).getname()
        self.assertEqual(family, "Times New Roman")
        self.assertEqual(style, "Bold")

    def test_time_band_uses_time_font_not_title_font(self):
        with patch.object(compose, "_time_font", wraps=compose._time_font) as time_font:
            compose.compose_yt_hourly_cover(
                _flat(), line1="東北季風", line2="今起增強", date_text="2026/09/13", time_text="20:00",
            )
        self.assertTrue(time_font.called)
        self.assertTrue(all(c.args and c.args[0] > 0 for c in time_font.call_args_list))

    def test_no_time_text_never_touches_time_font(self):
        with patch.object(compose, "_time_font", side_effect=AssertionError("不該載入")):
            compose.compose_yt_hourly_cover(
                _flat(), line1="東北季風", line2="今起增強", date_text="2026/09/13", time_text="",
            )

    def test_fit_font_bold_default_loader_unchanged(self):
        font = compose._fit_font_bold("20:00", 400, 80, 30)
        self.assertEqual(font.getname()[0], compose._font(30).getname()[0])


if __name__ == "__main__":
    unittest.main()
