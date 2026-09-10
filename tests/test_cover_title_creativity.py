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


def _clause(level, seed=0):
    return editor_formats.cover_ai_title_style_clause(level)


def _brief(level, titles=("尼泊爾災區 無人機空拍",), seed=0):
    """CANVAS 正後方那塊設計綱要。2026-09-11 第二輪起數字全部住在這裡——
    第一輪放在 TYPOGRAPHY 段尾（prompt 第 8,000 字元之後），實拍四級長得一模一樣。
    招式是隨機抽的，所以比對綱要的測試一律釘 seed。"""
    return editor_formats.cover_design_brief(level, titles=titles, seed=seed)


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

        2026-09-11 第九批重訂級距（使用者：「1~4 都還可以更有變化」）：四級改綁三個
        **數字**主軸——標題塊佔畫面高度％、字級落差倍數、招式件數。形容詞會被圖模
        平均掉，數字不會（2026-09-10 斜切線那次的教訓）。
        """
        # 字級落差：1 級一種字級，2 級起才有階層
        self.assertIn("Every row is the SAME size", _brief(1))
        for level in (2, 3, 4):
            with self.subTest(level=level):
                self.assertIn("Row sizes differ", _brief(level))
        # 版位自由：3 級才開
        for level in (1, 2):
            with self.subTest(level=level):
                self.assertNotIn("PLACEMENT IS FREED", _clause(level))
        for level in (3, 4):
            with self.subTest(level=level):
                self.assertIn("PLACEMENT IS FREED", _clause(level))
        # 誇張幅度（傾斜、三層描邊、兩個反白塊、第二焦點）：只有最高級
        for level in (1, 2, 3):
            with self.subTest(level=level):
                self.assertNotIn("GO FURTHER", _clause(level))
        self.assertIn("GO FURTHER", _clause(4))

    def test_the_ladder_is_pinned_to_numbers_not_adjectives(self):
        """三個數字主軸每一級都要往上跳一階，而且要寫成數字。

        2026-09-10 那輪四級只差在字的表面（描邊層數、材質、色數），縮圖上看不出來。
        塊高％／落差倍數／招式件數三樣都是**可量測**的，模型照得動、人也看得出來。
        """
        self.assertEqual(_brief(0), "")
        for level, height in ((1, "25%"), (2, "35%"), (3, "45%"), (4, "55%")):
            with self.subTest(level=level):
                self.assertIn(f"about {height} of the frame height", _brief(level))
        self.assertIn("Every row is the SAME size", _brief(1))
        for level, ratio in ((2, "about 1.8 times"), (3, "about 2.5 times"), (4, "about 3 times")):
            with self.subTest(level=level):
                self.assertIn(ratio, _brief(level))
        # 招式件數：1 級 0 件（整段不出現）、2 級 1 件、3 級 2 件、4 級 3 件
        self.assertNotIn("supporting artwork", _brief(1))
        for level, count in ((2, "EXACTLY 1 piece"), (3, "EXACTLY 2 pieces"), (4, "EXACTLY 3 pieces")):
            with self.subTest(level=level):
                self.assertIn(count, _brief(level))
        # 綱要要短，模型才讀得進去。第一輪 L4 條文 7.7KB、坐在第 8,000 字元後，實拍全被無視。
        for level in range(1, 5):
            with self.subTest(level=level):
                self.assertLess(len(_brief(level)), 2200)

    def test_each_step_changes_a_visible_shape_not_only_a_finish(self):
        """2026-09-10 使用者：「好像沒有這麼抖，尤其是 1、2 之間」。
        每一級都要有一個看得見形狀改變的必做項，否則相鄰兩級的成品又會長一樣。
        """
        # 1 級：每行各自的底板（跟 0 的「一整塊方板」拉開），但仍齊排
        self.assertIn("Each row sits on its OWN plate", _brief(1))
        self.assertIn("Rows stay flush with one another", _brief(1))
        # 2 級起：錯位排列＋每行底板互不相同
        for level in (2, 3, 4):
            with self.subTest(level=level):
                self.assertIn("Rows are STAGGERED", _brief(level))
                self.assertIn("THE PLATES NO LONGER MATCH EACH OTHER", _clause(level))
        self.assertNotIn("THE PLATES NO LONGER MATCH EACH OTHER", _clause(1))
        # 3 級起：多層描邊立體＋與照片主體交錯
        for level in (1, 2):
            with self.subTest(level=level):
                self.assertNotIn("MULTI-LAYER EDGES", _clause(level))
                self.assertNotIn("INTERLOCKS WITH THE PHOTOGRAPH", _clause(level))
        for level in (3, 4):
            with self.subTest(level=level):
                self.assertIn("MULTI-LAYER EDGES", _clause(level))
                self.assertIn("INTERLOCKS WITH THE PHOTOGRAPH", _clause(level))

    def test_colour_is_freed_from_the_row_order_at_every_level(self):
        """2026-09-11 使用者：「標題的顏色其實也可以解放，不必綁住一定要白黃紅順序，
        也不用綁到同一句同一色」。

        寫成許可句（舊版：「白黃紅只是提示，可以忽略」）沒有用——第七批已證明。
        所以改成命令句＋明文禁止那個順序，而逐行要怎麼上色由 cover_line_annotation
        釘在資料行上（條文區離行清單太遠，壓不過釘在行上的東西）。
        """
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                brief = _brief(level)
                self.assertIn("COLOUR FOLLOWS MEANING, NEVER ROW ORDER", brief)
                self.assertIn("row 1 white, row 2 yellow and row 3 red is BANNED", brief)
        # 色數也跟著爬
        self.assertIn("TWO colours only", _brief(1))
        self.assertIn("THREE colours", _brief(2))
        self.assertIn("plus ONE accent drawn from the subject", _brief(3))
        self.assertIn("palette is fully open", _brief(4))
        # 模板裡那條逐行配色也要跟著解除，不能只靠後面 OVERRIDE：顏色標記拿掉後
        # 它會變成孤兒，模型就照 Line 1/2/3 硬套白黃紅（2026-09-11 第一輪實拍）。
        self.assertIn("COLOUR EACH LINE EXACTLY AS LABELLED",
                      editor_formats.cover_title_colour_rule(0))
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                rule = editor_formats.cover_title_colour_rule(level)
                self.assertNotIn("(yellow)", rule)
                self.assertIn("is NOT a colour order", rule)

    def test_high_levels_require_reversed_out_words_and_wordless_side_artwork(self):
        """2026-09-10 使用者看實際成品後：「都沒有看到反色底字，例如胰臟癌可以反紅」，
        以及「除了標題之外，還允許多一些標籤或標題字以外的元素設計」。

        額外元素一律**無字**：新增中文標籤等於讓模型自己編字上鏡，那是另一個等級的事故。
        2026-09-11 起額外元素改成「招式池」，件數由等級決定、抽哪幾件由程式抽——
        交給模型自己選，四級會塌回同一種。
        """
        self.assertNotIn("KNOCKED OUT", _brief(1))
        self.assertIn("1 word of the headline sit KNOCKED OUT", _brief(2))
        self.assertIn("1 word of the headline sit KNOCKED OUT", _brief(3))
        self.assertIn("2 words of the headline sit KNOCKED OUT", _brief(4))
        self.assertIn("each block a different colour", _brief(4))
        for level in (2, 3, 4):
            with self.subTest(level=level):
                brief = _brief(level)
                self.assertIn("supporting artwork", brief)
                self.assertIn("never captions", brief)
        # 4 級再加碼：其中一件招式升格成第二視覺重心
        self.assertIn("SECOND FOCAL POINT", _clause(4))
        self.assertNotIn("SECOND FOCAL POINT", _clause(3))

    def test_the_accessory_pool_rotates_so_the_same_level_is_not_one_look(self):
        """使用者要的「更有變化」：同一級重生要換一組招式。

        由程式抽而不是叫模型自己想——許可句推不動模型，它會每次挑最省事的同一件。
        """
        picks = {tuple(editor_formats.cover_accessories(4, seed=s)) for s in range(6)}
        self.assertGreater(len(picks), 1)
        # 同一個 seed 一定重現（測試與除錯都靠這個）
        self.assertEqual(editor_formats.cover_accessories(3, seed=7),
                         editor_formats.cover_accessories(3, seed=7))

    def test_no_accessory_claims_a_number_the_model_cannot_count(self):
        """2026-09-11 實拍：標題寫「6大」，程式把 6 算好寫進 prompt，模型只畫 3 個。

        「說 6 大卻畫 3 個」比沒有這排圖示更糟，而這個精度不是 prompt 壓得住的，
        所以數量呼應整個拿掉——招式一律不宣稱數字。
        """
        for _key, text in editor_formats.COVER_ACCESSORY_POOL:
            with self.subTest(text=text[:40]):
                self.assertNotRegex(text, r"EXACTLY \d")
                self.assertNotIn("matching the number in the headline", text)
        picked = editor_formats.cover_accessories(3, titles=("極端危機6種 代用貨幣",), seed=0)
        self.assertNotIn("matching the number", " ".join(picked))

    def test_supporting_artwork_keeps_out_of_the_pasted_label_corner(self):
        """2026-09-11 實拍 L4：放大鏡的紅圈壓到左上角，而那裡是 compose 後貼
        AI示意圖 的位置。側邊標籤那段早有這條幾何，招式段當初漏抄。"""
        brief = _brief(4)
        self.assertIn("NONE OF THEM MAY SIT IN EITHER OUTER TOP CORNER", brief)
        self.assertIn("TOP THIRD OF THE FRAME", brief)

    def test_line_annotations_pin_the_treatment_on_the_data_row(self):
        """顏色與強調的指示釘在**那一行後面**，不是寫在條文區——
        2026-09-10 反色底字那次已經證明：離行清單太遠的規則，模型讀行清單時看不到。"""
        self.assertEqual(editor_formats.cover_line_annotation("尼泊爾災區", 0), "")
        hook = editor_formats.cover_line_annotation("不放棄！", 2)
        self.assertIn("HOOK ROW", hook)
        figure = editor_formats.cover_line_annotation("恐迎5天豪雨", 2)
        self.assertIn("PULL THE FIGURE 5", figure)
        quoted = editor_formats.cover_line_annotation("「街道成河」", 2)
        self.assertIn("takes its own colour", quoted)
        plain = editor_formats.cover_line_annotation("搜救隊深入泥流區", 1)
        self.assertIn("must not be one flat colour", plain)

    def test_extra_artwork_never_licenses_extra_words(self):
        """FIXED (e) 仍然管著：清單以外的字一個都不准畫。"""
        for level in (3, 4):
            with self.subTest(level=level):
                self.assertIn("No text of any kind other than the listed strings", _clause(level))

    def test_the_loudest_level_makes_the_tilt_mandatory(self):
        """「可以傾斜」在第七批就證明推不動模型：許可句＝不會發生。"""
        self.assertIn("rotated 5 to 8 degrees off horizontal", _brief(4))
        for level in (1, 2, 3):
            with self.subTest(level=level):
                self.assertNotIn("rotated", _brief(level))

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


class SideLabelTests(unittest.TestCase):
    """側邊標籤（2026-09-10）：使用者自己打的短詞，畫成一排小籤。

    為什麼不讓 AI 自己想：那是新的中文字，交給模型等於讓它編字上鏡——
    與這條線一路在防的「憑空多一條警示帶」同一件事。
    """

    def test_empty_input_changes_nothing(self):
        self.assertEqual(editor_formats.cover_side_labels_block(""), "")
        self.assertEqual(editor_formats.cover_side_labels_block("   "), "")

    def test_separators_and_caps(self):
        labels = editor_formats.cover_side_labels(
            "食慾不振 體重下降、腹部不適／容易疲倦,血糖異常|黃疸 第七個"
        )
        self.assertEqual(len(labels), editor_formats.COVER_SIDE_LABEL_MAX)
        self.assertEqual(labels[0], "食慾不振")
        self.assertTrue(all(len(t) <= editor_formats.COVER_SIDE_LABEL_CHARS for t in labels))

    def test_the_block_lists_them_as_listed_text_not_decoration(self):
        block = editor_formats.cover_side_labels_block("食慾不振 體重下降")
        self.assertIn("食慾不振", block)
        self.assertIn("體重下降", block)
        self.assertIn("character for character", block)
        self.assertIn("not decoration you may edit, drop or add to", block)
        self.assertIn("never enter the header band", block)

    def test_the_request_carries_the_field_through_to_the_prompt(self):
        seen = {}

        def fake_raw(image_req):
            seen["prompt"] = image_req.prompt
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "generate_image_raw", fake_raw):
            main.editor_cover(main.TenCoverRequest(
                title_left="胰臟癌6大 前兆", title_right="徵才薪資面議 調高至5萬",
                layout="split", mode="ai", provider="gpt", title_creativity=4,
                side_labels="食慾不振 體重下降",
            ))
        self.assertIn("食慾不振", seen["prompt"])
        self.assertIn("COLUMN OF SMALL LABEL CHIPS", seen["prompt"])

    def test_low_creativity_does_not_draw_the_chips(self):
        """0–2 級一律不畫側標（2026-09-10 使用者裁決）。

        規矩／微設計／有設計那三級版面本來就滿，多一排籤會擠掉標題；
        功能也還在測試期，先只開給 3 級起。前端欄位同日也先藏起來。
        """
        for level in (0, 1, 2):
            with self.subTest(level=level):
                seen = {}

                def fake_raw(image_req):
                    seen["prompt"] = image_req.prompt
                    return main.ImageGenerateResponse(
                        image_data_base64=base64.b64encode(
                            _png_for(image_req.aspect_ratio)
                        ).decode("ascii"),
                        mime_type="image/png", model="fake",
                    )

                with patch.object(main, "generate_image_raw", fake_raw):
                    main.editor_cover(main.TenCoverRequest(
                        title_left="胰臟癌6大 前兆", title_right="徵才薪資面議 調高至5萬",
                        layout="split", mode="ai", provider="gpt", title_creativity=level,
                        side_labels="食慾不振 體重下降",
                    ))
                self.assertNotIn("食慾不振", seen["prompt"])
                self.assertNotIn("COLUMN OF SMALL LABEL CHIPS", seen["prompt"])

class InfoChipTests(unittest.TestCase):
    """畫面小籤（2026-09-11）：地點籤、數據徽章、危險標示那種散落在畫面上的小牌。

    範本裡的來源：03「日本・名古屋」、11「日本」「印尼」、10「52.3%」、
    15「門檻擬調高至5萬」、04「致命漏洞?」。全是**清單以外的中文字**，
    所以做法完全比照側邊標籤：字由使用者填，模型只負責畫。

    國旗刻意不做：使用者打「日本」畫的是那兩個字的小籤，不是叫模型畫國旗——
    FIXED (e) 擋國旗籤的理由是模型會自己編一面旗，那個理由沒有改變。
    """

    def test_empty_input_changes_nothing(self):
        self.assertEqual(editor_formats.cover_info_chips_block(""), "")
        self.assertEqual(editor_formats.cover_info_chips_block("   "), "")

    def test_slash_is_content_not_a_separator(self):
        """側邊標籤那支拆斜線（症狀短語不會帶斜線），小籤不能拆——
        「5萬/月」「降41%」「日本・名古屋」的斜線與間隔號都是內容的一部分。"""
        chips = editor_formats.cover_info_chips("日本・名古屋 5萬/月 降41%")
        self.assertEqual(chips, ["日本・名古屋", "5萬/月", "降41%"])

    def test_separators_and_caps(self):
        chips = editor_formats.cover_info_chips(
            "日本・名古屋 降41%、致命漏洞|門檻五萬,第五個"
        )
        self.assertEqual(len(chips), editor_formats.COVER_INFO_CHIP_MAX)
        self.assertTrue(all(len(c) <= editor_formats.COVER_INFO_CHIP_CHARS for c in chips))

    def test_the_block_lists_them_as_listed_text_not_decoration(self):
        block = editor_formats.cover_info_chips_block("日本・名古屋 降41%")
        self.assertIn("日本・名古屋", block)
        self.assertIn("降41%", block)
        self.assertIn("character for character", block)
        self.assertIn("not decoration you may edit, drop or add to", block)

    def test_chips_are_not_a_column_and_keep_out_of_the_pasted_label_corner(self):
        """側邊標籤是右側一整欄等寬小籤，畫面小籤是各自獨立的小牌——
        兩者共用同一個插槽，措辭要分得開，不然模型會把兩組排成同一欄。
        角落那條幾何則兩者相同：AI示意圖 是 compose 後貼的。"""
        block = editor_formats.cover_info_chips_block("日本・名古屋")
        self.assertIn("do NOT form a column", block)
        self.assertIn("NO CHIP MAY SIT IN EITHER OUTER TOP CORNER", block)
        self.assertIn("示意圖", block)

    def test_the_request_carries_the_field_through_to_the_prompt(self):
        seen = {}

        def fake_raw(image_req):
            seen["prompt"] = image_req.prompt
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "generate_image_raw", fake_raw):
            main.editor_cover(main.TenCoverRequest(
                title_left="日破紀錄豪雨 街道成河", title_right="胰臟癌6大 致命前兆",
                layout="split", mode="ai", provider="gpt", title_creativity=4,
                info_chips="日本・名古屋 降41%",
            ))
        self.assertIn("日本・名古屋", seen["prompt"])
        self.assertIn("INFORMATION CHIPS", seen["prompt"])

    def test_low_creativity_does_not_draw_the_chips(self):
        """與側邊標籤同一條線：0–2 級版面本來就滿，多一排籤會擠掉標題。"""
        for level in (0, 1, 2):
            with self.subTest(level=level):
                seen = {}

                def fake_raw(image_req):
                    seen["prompt"] = image_req.prompt
                    return main.ImageGenerateResponse(
                        image_data_base64=base64.b64encode(
                            _png_for(image_req.aspect_ratio)
                        ).decode("ascii"),
                        mime_type="image/png", model="fake",
                    )

                with patch.object(main, "generate_image_raw", fake_raw):
                    main.editor_cover(main.TenCoverRequest(
                        title_left="日破紀錄豪雨 街道成河", title_right="胰臟癌6大 致命前兆",
                        layout="split", mode="ai", provider="gpt", title_creativity=level,
                        info_chips="日本・名古屋",
                    ))
                self.assertNotIn("日本・名古屋", seen["prompt"])
                self.assertNotIn("INFORMATION CHIPS", seen["prompt"])

    def test_both_chip_fields_exist_and_are_wired(self):
        """2026-09-11 使用者裁決：側邊標籤與畫面小籤兩個一起打開，3 級起才顯示。
        09-10 先藏是因為功能還在測，現在兩者都驗過了。"""
        app_js = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")
        index_html = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="coverInfoChips"', index_html)
        self.assertIn("info_chips: val('coverInfoChips')", app_js)
        self.assertIn("state.coverTitleCreativity >= 3", app_js)
        for field in ("coverSideLabels", "coverInfoChips"):
            with self.subTest(field=field):
                self.assertIn(f"'{field}'", app_js)
