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
                               "WHOLE header band",
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
        """單調性：低一級不得先解放高一級才給的東西。

        2026-09-09 使用者看完 0–4 實拍梯子後改的級距：舊 2（1.2 倍那級）與舊 3
        「差距不大」，融成新 2；舊 4 下移成 3；最上面補一個更誇張的新 4。
        """
        # 整組 house style（行內關鍵詞換色、1.5–2 倍落差）：2 級才開
        self.assertNotIn("PULL", _clause(1))
        for level in (2, 3, 4):
            with self.subTest(level=level):
                self.assertIn("PULL", _clause(level))
                self.assertIn("one and a half to two times", _clause(level))
        # 版位自由與小圖示：3 級才開
        for level in (1, 2):
            with self.subTest(level=level):
                self.assertNotIn("pictograms", _clause(level))
                self.assertNotIn("place the block anywhere", _clause(level))
        for level in (3, 4):
            with self.subTest(level=level):
                self.assertIn("pictograms", _clause(level))
                self.assertIn("place the block anywhere", _clause(level))
        # 誇張幅度（傾斜、疊字、多層描邊、爆裂裝飾）：只有最高級
        for level in (1, 2, 3):
            with self.subTest(level=level):
                self.assertNotIn("GO FURTHER", _clause(level))
        self.assertIn("GO FURTHER", _clause(4))

    def test_each_step_changes_a_visible_shape_not_only_a_finish(self):
        """2026-09-10 使用者：「好像沒有這麼抖，尤其是 1、2 之間」。
        原因是每一級只多給一項自由、而且都落在字的表面。每一級都要有一個
        看得見形狀改變的必做項，否則相鄰兩級的成品又會長一樣。
        """
        # 1 級：每行各自的底板＋整塊放大（2026-09-10 第二輪：使用者說 1 太像 0，
        # 原本 1 只多了一塊方底板，形狀跟 0 幾乎一樣，所以把「每行各自的形狀」下放到 1）
        self.assertIn("EACH ROW SITS ON ITS OWN SHAPE", _clause(1))
        self.assertIn("MARKEDLY BIGGER", _clause(1))
        # 2 級起：錯位排列＋每行底板互不相同
        self.assertNotIn("THE STACK IS NO LONGER FLUSH", _clause(1))
        self.assertNotIn("THE ROWS NO LONGER MATCH", _clause(1))
        for level in (2, 3, 4):
            with self.subTest(level=level):
                self.assertIn("THE STACK IS NO LONGER FLUSH", _clause(level))
                self.assertIn("THE ROWS NO LONGER MATCH", _clause(level))
        # 3 級起：字級落差再拉一階（2→2.5 倍），4 級再到 2.5–3 倍
        for level in (1, 2):
            with self.subTest(level=level):
                self.assertNotIn("two to two and a half times", _clause(level))
        for level in (3, 4):
            with self.subTest(level=level):
                self.assertIn("two to two and a half times", _clause(level))
        # 3 級起：多層描邊立體＋與照片主體交錯（原本是 4 級獨有，往下放一級）
        for level in (1, 2):
            with self.subTest(level=level):
                self.assertNotIn("MULTI-LAYER EDGES", _clause(level))
                self.assertNotIn("ENGAGES THE PHOTOGRAPH", _clause(level))
        for level in (3, 4):
            with self.subTest(level=level):
                self.assertIn("MULTI-LAYER EDGES", _clause(level))
                self.assertIn("ENGAGES THE PHOTOGRAPH", _clause(level))

    def test_high_levels_require_reversed_out_words_and_wordless_side_artwork(self):
        """2026-09-10 使用者看實際成品後：「都沒有看到反色底字，例如胰臟癌可以反紅」，
        以及「除了標題之外，還允許多一些標籤或標題字以外的元素設計」。

        反色底字原本只是 2 級那條「換色／反白／加粗」三選一的其中一個選項，
        模型每次都挑最省事的換色。3 級起改成必做。
        額外元素一律**無字**：新增中文標籤等於讓模型自己編字上鏡，那是另一個等級的事故。
        """
        for level in (1, 2):
            with self.subTest(level=level):
                self.assertNotIn("REVERSE A KEY WORD OUT OF A SOLID BLOCK", _clause(level))
                self.assertNotIn("BUILD SUPPORTING ARTWORK", _clause(level))
        for level in (3, 4):
            with self.subTest(level=level):
                clause = _clause(level)
                self.assertIn("REVERSE A KEY WORD OUT OF A SOLID BLOCK", clause)
                self.assertIn("BUILD SUPPORTING ARTWORK", clause)
                self.assertIn("never captions", clause)
        # 4 級再加碼：第二個反白字＋額外元素升格成第二視覺重心
        self.assertIn("MORE THAN ONE WORD IS REVERSED OUT", _clause(4))
        self.assertIn("SECOND FOCAL POINT", _clause(4))
        self.assertNotIn("MORE THAN ONE WORD IS REVERSED OUT", _clause(3))

    def test_extra_artwork_never_licenses_extra_words(self):
        """FIXED (e) 仍然管著：清單以外的字一個都不准畫。"""
        for level in (3, 4):
            with self.subTest(level=level):
                self.assertIn("No text of any kind other than the listed strings", _clause(level))

    def test_the_loudest_level_makes_the_tilt_mandatory(self):
        """「可以傾斜」在第七批就證明推不動模型：許可句＝不會發生。"""
        self.assertIn("THE BLOCK TILTS OR ARCS — required here, not offered", _clause(4))
        self.assertIn("two and a half to three times", _clause(4))

    def test_level_two_says_out_loud_that_placement_still_binds(self):
        """2 級解放的是排法不是位置。只是「不提位置」不夠——
        前面 TYPOGRAPHY 有位置規則，但這一段整體宣告 OVERRIDE，不點名就會被順手當成解除。"""
        self.assertIn("THE PLACEMENT STILL BINDS", _clause(2))
        self.assertNotIn("THE PLACEMENT STILL BINDS", _clause(3))

    def test_the_loudest_level_repeats_the_legibility_guards(self):
        """幅度愈大，模型愈容易把字推到邊上、讓疊字蓋掉筆畫。
        4 級的加碼段自己要再講一次「完整可讀、不碰邊、不進帶、不跨格」。"""
        clause = _clause(4)
        self.assertIn("Loud is not the same as broken", clause)
        self.assertIn("every character stays complete, unobstructed and legible", clause)

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
