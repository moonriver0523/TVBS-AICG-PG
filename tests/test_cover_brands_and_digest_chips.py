"""封面線的品牌商標，與消化順便建議兩個籤（2026-09-11）。

一、品牌商標。使用者：「Logo 早就鬆綁了，難道規則都沒改嗎？」
查證結果：鬆綁的是 CG 那條線（main.CG_STRUCTURE 的 BRANDS 規則），十點封面沒跟上。
擋住封面的不是那句「NO television channel logo」——那句管的是 TVBS 台標、節目名、
浮水印，是程式後貼的東西。真正擋住的是畫面描述那句「NEVER mention … logos」，
以及硬規則「清單以外的字一個都不准」（會把機身上的 amazon 一起掃掉）。

範本佐證：04 的 amazon 貨機、05 的 GAP 店面、13 的 TikTok Shop、03 的 iPhone，
品牌都長在照片裡的真實物件上。範本 03 標題行首那個 Apple 標是畫上去的裝飾，不開。

所以縫要開得剛好夠：**照片裡實體物件本身帶的**品牌標記可以出現，畫上去的裝飾性
標記、地名、國名、警語一律照舊擋死。

二、消化建議兩個籤。使用者：「側邊開放選填，但使用者可能懶得填，
可以讓 AI 消化自己決定嗎？」

這不違反「不讓 AI 自己編字」那條紅線：紅線防的是**生圖那一步**憑空多字（沒有人看得到、
也沒有稿可以對）。消化這一步讀的是編輯貼進來的內文、吃同一套忠實度規則，結果回填到
欄位讓編輯看過再按生成——標題本來就是這樣產的。生圖那一步一個字都沒放鬆。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats  # noqa: E402
import main  # noqa: E402

APP_JS = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")


class BrandTests(unittest.TestCase):
    def test_the_shot_description_may_now_name_a_brand(self):
        """畫面描述不提品牌，生圖端就無從畫起——這是第一道擋住的門。"""
        system = editor_formats.COVER_VISUAL_DERIVE_SYSTEM
        self.assertIn("BRANDS: ONLY THOSE THE HEADLINE OR THE SUPPLIED DESCRIPTION NAMES", system)
        self.assertNotIn("charts, logos or watermarks", system)

    def test_unnamed_brands_stay_de_identified(self):
        """照抄 CG 那條的安全邊界：沒點名的品牌一律去識別化，絕不憑空生一個牌子。"""
        system = editor_formats.COVER_VISUAL_DERIVE_SYSTEM
        for pinned in ("stays de-identified", "never an invented one",
                       "never a readable brand name the story does not name",
                       "Never put one brand's mark on another brand's object"):
            with self.subTest(pinned=pinned):
                self.assertIn(pinned, system)

    def test_the_no_extra_text_rule_opens_only_for_marks_on_real_objects(self):
        """縫要窄：機身上的 amazon 可以，畫在標題旁邊的品牌標不行。"""
        for name in ("COVER_AI_PROMPT_TEMPLATE", "COVER_AI_FULL_PROMPT_TEMPLATE"):
            with self.subTest(template=name):
                text = getattr(editor_formats, name)
                self.assertIn("ONE NARROW EXCEPTION", text)
                self.assertIn("physically belongs to an object in the photograph", text)
                self.assertIn("no brand mark beside or inside the headline", text)
                # 台標那條完全沒動：那是程式後貼的，跟品牌無關
                self.assertIn("NO television channel logo", text)

    def test_the_fixed_block_says_a_brand_mark_is_not_a_decorative_mark(self):
        """FIXED (e) 若原封不動，高創意那幾級會把機身上的字當成違規清掉。"""
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("is not one of your decorative marks", clause)
        self.assertIn("never migrates onto the headline", clause)
        # 其餘禁令一字不動
        for banned in ("no country names", "no place labels", "no flag chips", "no map insets"):
            with self.subTest(banned=banned):
                self.assertIn(banned, clause)


class DigestChipTests(unittest.TestCase):
    def test_both_ten_digest_prompts_ask_for_the_two_chip_fields(self):
        for name in ("COVER_TITLE_DIGEST_SYSTEM_TEN", "COVER_TITLE_DIGEST_SYSTEM_TEN_FULL"):
            with self.subTest(prompt=name):
                text = getattr(editor_formats, name)
                self.assertIn('"side_labels"', text)
                self.assertIn('"info_chips"', text)

    def test_an_empty_field_is_declared_correct_not_a_failure(self):
        """湊出來的籤是封面上一條沒人查得到的假資訊。寧可回空。"""
        text = editor_formats.COVER_TITLE_DIGEST_SYSTEM_TEN
        self.assertIn("an empty field is correct and normal, a padded one is a defect", text)
        self.assertIn("Never invent or round a figure, never guess a place", text)

    def test_side_labels_are_only_for_articles_that_actually_enumerate(self):
        text = editor_formats.COVER_TITLE_DIGEST_SYSTEM_TEN
        self.assertIn("ONLY when the article actually enumerates parallel items", text)

    def test_both_schemas_require_the_fields(self):
        """strict schema 下省略欄位會被退，所以「這篇沒有」用空陣列表達。"""
        for schema in (editor_formats.COVER_TITLE_DIGEST_SCHEMA_TEN,
                       editor_formats.COVER_TITLE_DIGEST_SCHEMA_TEN_FULL):
            with self.subTest(schema=sorted(schema["properties"])):
                for field in ("side_labels", "info_chips"):
                    self.assertIn(field, schema["properties"])
                    self.assertIn(field, schema["required"])

    def test_the_full_layout_no_longer_borrows_the_yt_schema(self):
        """滿版以前借 YT 那個 schema（只有 title），籤欄位塞不進去。"""
        self.assertNotIn("side_labels", editor_formats.COVER_TITLE_DIGEST_SCHEMA_YT["properties"])
        self.assertIn("side_labels", editor_formats.COVER_TITLE_DIGEST_SCHEMA_TEN_FULL["properties"])

    def test_an_overlong_chip_is_dropped_never_truncated(self):
        """截斷 AI 產的籤會變成假資訊：「病例超過三千二百人」砍成「病例超過三千二百」，
        數字就被改了，而封面上的數字沒人查得到出處。使用者自己打的截斷沒關係
        （他看得到自己打了什麼），AI 產的一律整個丟掉。"""
        text = main._digest_chips(
            ["食慾不振", " 體重下降 ", "病例超過三千二百人", "黃疸"], limit=6, chars=6,
        )
        self.assertEqual(text, "食慾不振 體重下降 黃疸")
        self.assertNotIn("病例超過三千二百", text)

    def test_the_count_cap_still_holds(self):
        text = main._digest_chips(["一", "二", "三", "四", "五", "六", "七"], limit=6, chars=6)
        self.assertEqual(len(text.split(" ")), 6)

    def test_non_list_input_is_ignored(self):
        for bad in (None, "食慾不振", 5, {}):
            with self.subTest(bad=bad):
                self.assertEqual(main._digest_chips(bad, limit=6, chars=6), "")

    def test_chip_limits_track_the_editor_formats_constants(self):
        """上限手抄一份遲早跟欄位對不上。"""
        fields = main._digest_chip_fields({
            "side_labels": ["一"] * 20,
            "info_chips": ["二"] * 20,
        })
        self.assertEqual(len(fields["side_labels"].split(" ")),
                         editor_formats.COVER_SIDE_LABEL_MAX)
        self.assertEqual(len(fields["info_chips"].split(" ")),
                         editor_formats.COVER_INFO_CHIP_MAX)

    def test_the_response_model_carries_them(self):
        res = main.CoverTitleDigestResponse(title_left="甲 乙 丙", side_labels="食慾不振",
                                            info_chips="臺南")
        self.assertEqual(res.side_labels, "食慾不振")
        self.assertEqual(res.info_chips, "臺南")
        # 沒帶就是空字串，前端照樣清空欄位
        self.assertEqual(main.CoverTitleDigestResponse().side_labels, "")

    def test_the_frontend_fills_both_fields_back(self):
        self.assertIn("data.side_labels", APP_JS)
        self.assertIn("data.info_chips", APP_JS)


if __name__ == "__main__":
    unittest.main()
