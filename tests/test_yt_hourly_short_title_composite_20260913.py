"""整點 0 級的極短標題強制走程式壓字（2026-09-13 使用者裁決）。

prompt 端的字高上限實拍擋不住：4＋4 字的成品字頂落在 61.6%，日期紅條下緣 61.5%
——餘裕 1 個像素，而且修正前那張也剛好沒撞，那批連「有沒有變好」都證明不出來。
所以改由程式保證：極短標題直接切成 composite，程式壓字版字頂固定 66%，物理上不會撞。

判定只看字夠不夠少，不看使用者怎麼輸入（使用者補充：只填第一行、靠空格自動斷句成
兩行的「東北季風 今起增強」同樣是字太少），所以單則看整句總寬。
"""
import base64
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)
HEADERS = {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}

NEEDS = editor_formats.yt_hourly_short_title_needs_composite


def _png(size=(1536, 864), colour=(30, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


class PredicateTests(unittest.TestCase):
    def test_a_single_title_that_auto_splits_into_two_short_lines(self):
        """使用者只填第一行、用空格斷句——分隔用的空白不算字，8 個字就是 8。"""
        self.assertTrue(NEEDS("hourly", 0, "ai", "東北季風 今起增強"))
        self.assertTrue(NEEDS("hourly", 0, "ai", "東北季風今起增強"))
        self.assertTrue(NEEDS("hourly", 0, "ai", "東北季風　今起增強"))  # 全形空白

    def test_a_normal_length_title_is_left_alone(self):
        self.assertFalse(NEEDS("hourly", 0, "ai", "東北季風 今起增強大"))
        self.assertFalse(NEEDS("hourly", 0, "ai", "挪威國王哈拉德辭世 開放公眾瞻仰遺容"))

    def test_dual_looks_at_each_line_on_its_own(self):
        """雙則的兩行是兩則不同新聞，不會互相補長度，所以各自量。"""
        self.assertTrue(NEEDS("hourly", 0, "ai", "東北季風", "今起增強"))
        self.assertFalse(NEEDS("hourly", 0, "ai", "東北季風", "今起增強大"))

    def test_it_only_applies_to_level_zero_hourly_ai(self):
        """1 級起日期牌是模型自己畫、明令貼著標題走，沒有這個碰撞；
        在那邊強制 composite 等於把整條創意階梯關掉。"""
        for args in (
            ("hourly", 1, "ai", "東北季風 今起增強"),
            ("news", 0, "ai", "東北季風 今起增強"),
            ("hot", 0, "ai", "東北季風 今起增強"),
            ("hourly", 0, "composite", "東北季風 今起增強"),
        ):
            with self.subTest(args=args):
                self.assertFalse(NEEDS(*args))


class EndpointTests(unittest.TestCase):
    def _post(self, payload):
        fake = main.ImageGenerateResponse(
            image_data_base64=base64.b64encode(_png()).decode("ascii"),
            mime_type="image/png", model="fake-model",
        )
        with patch.object(main, "generate_image_raw", return_value=fake), \
             patch.object(main, "derive_yt_cover_plan",
                          return_value={"visual": "一個場景", "portrait_subjects": []}), \
             patch.object(compose, "compose_yt_hourly_cover",
                          wraps=compose.compose_yt_hourly_cover) as hourly:
            res = client.post("/api/editor/yt-cover", json=payload, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json(), hourly

    def test_a_short_hourly_title_comes_back_as_composite(self):
        data, hourly = self._post({
            "title": "東北季風 今起增強", "title_mode": "ai", "layout": "hourly",
            "date_text": "2026/09/14", "time_text": "20:00",
        })
        self.assertEqual(data["title_mode"], "composite")
        self.assertTrue(hourly.call_args.kwargs["draw_titles"])

    def test_a_normal_hourly_title_still_gets_the_ai_headline(self):
        data, hourly = self._post({
            "title": "挪威國王哈拉德辭世 開放公眾瞻仰遺容", "title_mode": "ai",
            "layout": "hourly", "date_text": "2026/09/14",
        })
        self.assertEqual(data["title_mode"], "ai")
        self.assertFalse(hourly.call_args.kwargs["draw_titles"])

    def test_a_reworked_image_is_never_flipped(self):
        """追加修改回來的圖標題已經畫在上面，改成 composite 會疊成兩層。"""
        payload = {
            "title": "東北季風 今起增強", "title_mode": "ai", "layout": "hourly",
            "background_image_base64": base64.b64encode(_png()).decode("ascii"),
            "background_is_ai": True, "date_text": "2026/09/14",
        }
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")), \
             patch.object(compose, "compose_yt_hourly_cover",
                          wraps=compose.compose_yt_hourly_cover) as hourly:
            res = client.post("/api/editor/yt-cover", json=payload, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(hourly.call_args.kwargs["draw_titles"])


class ItActuallyClearsTheTabTests(unittest.TestCase):
    def test_the_composite_title_top_clears_the_date_tab(self):
        """這才是這條規則的目的：程式壓字版的字頂離紅條有真實距離。"""
        tab_bottom = (compose.YT_HOURLY_DATE_TOP_RATIO
                      + compose.YT_HOURLY_DATE_TAB_HEIGHT_RATIO)
        png = compose.compose_yt_hourly_cover(
            _png((1920, 1080), (60, 70, 90)), line1="東北季風", line2="今起增強",
            date_text="2026/09/14", time_text="20:00")
        img = Image.open(io.BytesIO(png)).convert("RGB")
        px = img.load()
        w, h = img.size
        tab_px = round(h * tab_bottom)
        top = next(
            y for y in range(tab_px + 1, h)
            if sum(1 for x in range(0, round(w * 0.55)) if px[x, y][0] > 240
                   and px[x, y][1] > 240 and px[x, y][2] > 220) >= 40
        )
        self.assertGreater(top / h - tab_bottom, 0.02)  # 實測餘裕遠大於 AI 版的 1px


if __name__ == "__main__":
    unittest.main()
