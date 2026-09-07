"""十點不一樣（滿版）合成版的「只改文字」（2026-09-08）。

合成版的成品＝一張底圖＋Pillow 壓上去的標題／日期／Logo。改標題本來要重生一次底圖
（30–90 秒＋一次生圖 API），但底圖根本沒變——所以回應把**壓字前的底圖**帶回前端，
下次只改文字時原樣送回來，零 API 重壓一次字。比照 YT 直播封面的 yt-cover:recomposite。

守的紅線：
1. 滿版合成版回應帶 background_image_base64／background_mime_type／background_is_ai，
   而且**不是** source_image_base64（那格是給 /api/images/refine 的，合成版一律留空，
   見 tests/test_cover_refine.py 的紅線 1）。
2. 帶 background 回來：一次生圖、一次文字模型都不打，model 記 ten-cover-full:recomposite，
   底圖原樣沿用、標題換成新的。
3. 雙切合成版不支援（左右兩格拼完分不回去），帶 background 回 400。
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import main  # noqa: E402
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

RED, GREEN = (200, 30, 30), (30, 200, 30)


def _decode(data) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")


def _background(data) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data["background_image_base64"]))).convert("RGB")


def _title_ink(img: Image.Image) -> int:
    """標題區的白／黃字像素量（同 test_ten_cover_full 的判定）。"""
    w, h = img.size
    box = (0, round(h * 0.55), w, h - round(h * 0.06))
    raw = img.crop(box).tobytes()
    return sum(
        1 for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3])
        if (r > 230 and g > 230) or (r > 200 and b < 90)
    )


class FullCompositeReturnsBackgroundTests(unittest.TestCase):
    """紅線 1：滿版合成版把壓字前底圖帶回來，AI 底圖與附圖底圖的 background_is_ai 要分得開。"""

    def _post(self, body):
        def fake_full(visual, provider, references=None, *args):
            return _png_bytes(size=(1600, 900), colour=GREEN), "fake-image-model"

        with patch.object(main, "_cover_full_image", side_effect=fake_full), \
             patch.object(main, "resolve_cover_visuals", return_value=("冰川崩落", "冰川崩落")), \
             patch.object(main, "generate_image_raw", side_effect=AssertionError("不該直接生圖")):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_ai_background_is_returned_and_flagged_ai(self):
        data = self._post({"title_left": "全球3100條 躍動冰川", "layout": "full", "mode": "composite"})
        self.assertTrue(data["background_image_base64"])
        self.assertEqual(data["background_mime_type"], "image/png")
        self.assertTrue(data["background_is_ai"])
        # 帶回來的是**壓字前**的底圖：整張都還是生圖模型給的底色，沒有 Logo 也沒有標題
        background = _background(data)
        w, h = background.size
        for xy in ((w // 4, h // 4), (w // 2, h // 2), (3 * w // 4, round(h * 0.8))):
            self.assertEqual(background.getpixel(xy), GREEN)
        self.assertEqual(_title_ink(background), 0)
        self.assertGreater(_title_ink(_decode(data)), 2000)

    def test_asis_background_is_returned_and_flagged_not_ai(self):
        data = self._post({
            "title_left": "全球3100條 躍動冰川", "layout": "full", "mode": "composite",
            "asis_left": _data_url(_png_bytes(size=(1600, 900), colour=RED)),
        })
        self.assertTrue(data["background_image_base64"])
        self.assertFalse(data["background_is_ai"])
        self.assertEqual(_background(data).getpixel((800, 450)), RED)

    def test_background_is_not_the_refine_source(self):
        # source_image_base64 的語意是「餵回 /api/images/refine 的原圖」，合成版一律留空。
        # 兩者混用會讓前端的「修改」鈕誤以為合成版可以 refine（見 app.js refineSourceFromResponse）。
        data = self._post({"title_left": "全球3100條 躍動冰川", "layout": "full", "mode": "composite"})
        self.assertEqual(data["source_image_base64"], "")
        self.assertEqual(data["source_mime_type"], "")

    def test_ai_mode_does_not_return_a_background(self):
        # AI 整張版走的是 source_image_base64（後貼前的模型圖），不吃「只改文字」這條
        def fake_raw(image_req):
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_bytes(size=(1536, 864))).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "resolve_cover_visuals", return_value=("冰川崩落", "冰川崩落")):
            res = client.post(
                "/api/editor/cover",
                json={"title_left": "全球3100條 躍動冰川", "layout": "full", "mode": "ai"},
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["background_image_base64"], "")
        self.assertEqual(data["background_mime_type"], "")
        self.assertFalse(data["background_is_ai"])
        self.assertTrue(data["source_image_base64"])


class FullCompositeRecompositeTests(unittest.TestCase):
    """紅線 2：帶 background 回來＝零 API，只換標題。"""

    def _recomposite(self, body):
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "_cover_full_image", side_effect=AssertionError("不該生底圖")), \
             patch.object(main, "resolve_cover_visuals", side_effect=AssertionError("不該補描述")), \
             patch.object(main, "digest_completion", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _body(self, **extra):
        raw = _png_bytes(size=(1600, 900), colour=RED)
        return {
            "title_left": "尼泊爾災區 滅村慘況", "layout": "full", "mode": "composite",
            "background_image_base64": base64.b64encode(raw).decode("ascii"),
            "background_mime_type": "image/png",
            **extra,
        }

    def test_supplied_background_reuses_image_and_redraws_the_new_title(self):
        data = self._recomposite(self._body(background_is_ai=True))
        self.assertEqual(data["model"], "ten-cover-full:recomposite")
        self.assertEqual(data["mode"], "composite")
        self.assertTrue(data["left_is_ai"])
        img = _decode(data)
        w, h = img.size
        # 底圖原樣沿用（畫面上半仍是帶回來的那張紅圖），標題區有新標題的字
        self.assertEqual(img.getpixel((w // 2, round(h * 0.30))), RED)
        self.assertGreater(_title_ink(img), 2000)
        # 底圖再帶回來一次，下一輪「只改文字」才接得下去
        self.assertEqual(_background(data).getpixel((w // 2, h // 2)), RED)
        self.assertTrue(data["background_is_ai"])

    def test_background_is_ai_false_keeps_the_ai_note_off(self):
        # background_is_ai＝要不要壓「AI示意圖」；附圖底圖回來時不能自己變成 AI 圖
        data = self._recomposite(self._body(background_is_ai=False))
        self.assertFalse(data["background_is_ai"])
        self.assertFalse(data["left_is_ai"])
        self.assertEqual(data["model"], "ten-cover-full:recomposite")
        # 同一張底圖、同一個標題，只差 background_is_ai：AI 版多壓一枚「AI示意圖」，
        # 所以整張的白字量一定比較多。旗標若被吃掉這條會失敗。
        ai = _decode(self._recomposite(self._body(background_is_ai=True)))
        plain = _decode(data)

        def white(img):
            raw = img.tobytes()
            return sum(1 for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3]) if r > 230 and g > 230 and b > 230)

        self.assertGreater(white(ai), white(plain))

    def test_background_wins_over_a_supplied_asis_image(self):
        # 使用者按的是「只改文字」：附圖還掛在表單上也不重新取，一律用帶回來的底圖
        data = self._recomposite(self._body(
            background_is_ai=True,
            asis_left=_data_url(_png_bytes(size=(1600, 900), colour=GREEN)),
        ))
        self.assertEqual(data["model"], "ten-cover-full:recomposite")
        img = _decode(data)
        self.assertEqual(img.getpixel((img.size[0] // 2, round(img.size[1] * 0.30))), RED)


class SplitRejectsBackgroundTests(unittest.TestCase):
    """紅線 3：雙切合成版帶 background 回 400，不要默默忽略後重生兩張底圖。"""

    def test_split_composite_with_background_is_rejected(self):
        raw = base64.b64encode(_png_bytes(size=(1600, 900), colour=RED)).decode("ascii")
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "resolve_cover_visuals", side_effect=AssertionError("不該補描述")):
            res = client.post("/api/editor/cover", json={
                "title_left": "尼泊爾災區 滅村慘況", "title_right": "台南易淹水 成氣候衝擊區",
                "layout": "split", "mode": "composite",
                "background_image_base64": raw, "background_mime_type": "image/png",
            }, headers=_headers())
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("只改文字", res.json()["detail"])

    def test_split_ai_overlay_still_works(self):
        # AI 版的後貼路徑（ten-cover:overlay）不受影響，只有合成版被擋
        raw = base64.b64encode(_png_bytes(size=(1600, 900), colour=RED)).decode("ascii")
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "digest_completion", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/cover", json={
                "title_left": "尼泊爾災區 滅村慘況", "title_right": "台南易淹水 成氣候衝擊區",
                "layout": "split", "mode": "ai",
                "background_image_base64": raw, "background_mime_type": "image/png",
            }, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["model"], "ten-cover:ai")


if __name__ == "__main__":
    unittest.main()
