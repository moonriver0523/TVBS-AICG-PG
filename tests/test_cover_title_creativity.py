"""標題創意拉桿 0–4（2026-09-09 第八批）。

使用者：「AI 消化的創意奔放程度，能不能設為好幾個等級，讓使用者自己選擇。
前台 UI 做成像調整 AI effort 的拉 bar，最左邊是創意最低，最右邊是創意最高。」

這一批守的紅線：

1. **中間幾級不能是擺設。** 第七批才證明條文寫成許可句推不動模型；中間級若寫成
   「你可以…」，成品會跟 0 或 4 長一樣，拉桿就是騙人的。每一級都要有**命令句**。
2. **拉桿只調設計自由度，不調內容與版面規約。** FIXED (a)–(g)（一字不改、正體中文、
   程式後貼的三塊區域、不得跨格）每一級都要原樣附上，不隨等級鬆綁。
3. **自由度單調遞增。** 高一級解放的東西，低一級不得先解放。
4. **0 是預設，而且完全不追加。**
5. 舊的 plain／designed 兩檔還要能用（舊呼叫端／回填），對應到兩端。
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

import editor_formats  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402

LEVELS = range(editor_formats.COVER_AI_TITLE_LEVEL_MIN,
               editor_formats.COVER_AI_TITLE_LEVEL_MAX + 1)


def _clause(level):
    return editor_formats.cover_ai_title_style_clause(level)


class LadderTests(unittest.TestCase):
    def test_level_zero_adds_nothing(self):
        """0＝現行排版。追加任何一句都會讓「最左邊」不等於今天的成品。"""
        self.assertEqual(_clause(0), "")

    def test_every_level_above_zero_keeps_the_whole_fixed_block(self):
        """拉桿調的是設計自由度。內容與版面規約不隨等級鬆綁——
        少了任何一條，高創意就會開始改字或壓到程式後貼的區域。"""
        for level in range(1, editor_formats.COVER_AI_TITLE_LEVEL_MAX + 1):
            with self.subTest(level=level):
                clause = _clause(level)
                for pinned in ("character for character",
                               "never add, drop, translate, abbreviate, reorder or substitute",
                               "never break a listed line in the middle",
                               "9/12",
                               "NO part of the headline may sit inside them or overlap them",
                               "LEFT HALF of the header band",
                               "示意圖",
                               "ENTIRELY INSIDE ITS OWN PANEL",
                               "never crosses the diagonal seam"):
                    self.assertIn(pinned, clause)

    def test_every_level_is_written_as_orders_not_permissions(self):
        """第七批的教訓：許可句推不動模型，它會走阻力最小的路＝交出跟低一級一樣的圖。
        所以每一級都要有 OVERRIDE 宣告，而且自己講明白這一級長什麼樣。"""
        for level in range(1, editor_formats.COVER_AI_TITLE_LEVEL_MAX + 1):
            with self.subTest(level=level):
                clause = _clause(level)
                self.assertIn("OVERRIDE EVERY TYPOGRAPHY INSTRUCTION ABOVE", clause)
                self.assertIn(f"level {level} of 4", clause)

    def test_each_level_is_actually_different_from_its_neighbour(self):
        """相鄰兩級的條文若一樣，拉桿就有一格是白拉的。"""
        seen = {level: _clause(level) for level in LEVELS}
        self.assertEqual(len(set(seen.values())), len(seen))

    def test_freedoms_only_ever_grow(self):
        """單調性：低一級不得先解放高一級才給的東西。"""
        # 行內關鍵詞換色：2 級才開
        self.assertNotIn("PULL", _clause(1))
        for level in (2, 3, 4):
            self.assertIn("PULL", _clause(level))
        # 大小落差 1.5–2 倍（house style）：3 級才開；2 級只有 1.2 倍
        self.assertIn("1.2 times", _clause(2))
        for level in (3, 4):
            self.assertIn("one and a half to two times", _clause(level))
        # 版位自由與小圖示：只有最高級
        for level in (1, 2, 3):
            with self.subTest(level=level):
                self.assertNotIn("pictograms", _clause(level))
                self.assertNotIn("place the block anywhere", _clause(level))
        self.assertIn("pictograms", _clause(4))
        self.assertIn("place the block anywhere", _clause(4))

    def test_level_three_says_out_loud_that_placement_still_binds(self):
        """3 級解放的是排法不是位置。只是「不提位置」不夠——
        前面 TYPOGRAPHY 有位置規則，但這一段整體宣告 OVERRIDE，不點名就會被順手當成解除。"""
        self.assertIn("THE PLACEMENT STILL BINDS", _clause(3))

    def test_the_named_constant_is_still_the_top_level(self):
        """第七批以前的呼叫端與測試都指名這個常數。"""
        self.assertEqual(editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE,
                         _clause(editor_formats.COVER_AI_TITLE_LEVEL_MAX))


def _png_for(aspect_ratio: str) -> bytes:
    ratio = main.parse_aspect_ratio(aspect_ratio) or 1.0
    buffer = io.BytesIO()
    Image.new("RGB", (round(720 * ratio), 720), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


class RequestTests(unittest.TestCase):
    def _prompt(self, **kw):
        seen = {}

        def fake_raw(image_req):
            seen["prompt"] = image_req.prompt
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        body = {"title_left": "尼泊爾災區 無人機空拍", "title_right": "臺南易淹水 成氣候衝擊區",
                "layout": "split", "mode": "ai"}
        body.update(kw)
        with patch.object(main, "resolve_cover_visuals", return_value=("左場景", "右場景")), \
             patch.object(main, "generate_image_raw", side_effect=fake_raw):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return seen["prompt"]

    def test_each_level_reaches_the_prompt(self):
        for level in range(1, editor_formats.COVER_AI_TITLE_LEVEL_MAX + 1):
            with self.subTest(level=level):
                self.assertIn(f"level {level} of 4", self._prompt(title_creativity=level))

    def test_default_is_level_zero(self):
        self.assertNotIn("DESIGNED TITLE", self._prompt())

    def test_out_of_range_is_rejected(self):
        for bad in (-1, 5):
            with self.subTest(level=bad):
                res = client.post("/api/editor/cover",
                                  json={"title_left": "尼泊爾災區 無人機空拍", "layout": "full",
                                        "mode": "ai", "title_creativity": bad},
                                  headers=_headers())
                self.assertEqual(res.status_code, 422)

    def test_the_old_two_position_switch_still_maps_to_the_ends(self):
        """舊呼叫端與回填帶的是 title_style；沒有這條對應，它們會靜靜掉回 0。"""
        self.assertNotIn("DESIGNED TITLE", self._prompt(title_style="plain"))
        self.assertIn("level 4 of 4", self._prompt(title_style="designed"))

    def test_the_slider_wins_when_both_are_sent(self):
        self.assertIn("level 2 of 4", self._prompt(title_style="designed", title_creativity=2))


if __name__ == "__main__":
    unittest.main()
