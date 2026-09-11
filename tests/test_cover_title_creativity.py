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
        # 2026-09-11 收尾降尺寸：25/35/45/55% → 18/24/30/36%。使用者回報字偏大、
        # 照片被擠掉，拿他自己的範本量，實際成品的標題塊只佔畫面高度約 18–25%。
        for level, height in ((1, "18%"), (2, "24%"), (3, "30%"), (4, "36%")):
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
        # 量最壞的那個 seed：招式是隨機抽的，只量一個 seed 會讓長的那幾件溜過去。
        # 上限一路放寬的理由都記在這：2,200 →（第三輪，每件招式各掛一句幾何）2,600
        # →（第四輪，加進字體／落點兩條變化軸）3,000。
        # 3,000 仍是失效那版（7.7KB、坐在第 8,000 字元後）的不到一半，而且照樣坐在
        # CANVAS 正後方——真正決定生死的是位置，長度只是別把自己稀釋掉。
        # 2026-09-11 第十批（配件不看題材）加了 icon 類招式的共通指示，把 L4 最壞值
        # 從遠低於 3,000 一路推到 2,978——上限只剩約 22 字元餘裕。**下一個要在
        # cover_design_brief／cover_accessories 加字的人，先從別處拿掉等量的字，
        # 不是再放寬一次上限**：上限每次放寬都是為了一件具體的新變化軸，不是給文字
        # 鋪陳用的預算；上一次砍字（把 guidance 從方法＋反例兩句砍成電報體一句）
        # 就是在證明「先砍字」是做得到的。
        for level in range(1, 5):
            with self.subTest(level=level):
                worst = max(
                    len(editor_formats.cover_design_brief(level, seed=s, full_width=f))
                    for s in range(40)
                    for f in (False, True)
                )
                self.assertLess(worst, 3000)

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
        # 2026-09-11 第四輪：色數仍然照級距爬，但「哪幾個顏色」改由 COVER_PALETTES 抽。
        # 原本 3 級那句「accent drawn from the subject（天氣配冰藍…）」跟抽出來的
        # 配色互相矛盾，矛盾要拆掉不是覆蓋——留著模型只會認那一句。
        self.assertIn("plus ONE accent", _brief(3))
        self.assertNotIn("drawn from the subject", _brief(3))
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
        self.assertIn("1 word of the headline sits KNOCKED OUT", _brief(2))
        self.assertIn("1 word of the headline sits KNOCKED OUT", _brief(3))
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

    def test_every_accessory_carries_its_own_placement_note(self):
        """2026-09-11 實拍（創意梯子-260911-ef）：E_L4 的放大鏡貼在右格右上角、
        壓到 AI示意圖 貼紙；F_L3 的箭頭頂進上三分之一。排除區條文**當時已經寫在**
        共用那條 bullet 裡了，模型照樣犯——它坐在一長串否定句中間。
        顏色那邊已經證過同一件事：指示要釘在編號清單那幾行後面。"""
        for level in (2, 3, 4):
            with self.subTest(level=level):
                for text in editor_formats.cover_accessories(level, seed=1):
                    self.assertIn("MIDDLE OR LOWER AREA ONLY", text)
                    self.assertIn("never the top third", text)

    def test_the_bubble_cluster_hangs_off_the_headline_not_the_subject(self):
        """2026-09-11 實拍（變化池-260911 L3_1）：這排小插圖跑到右格右上角、
        壓住 AI示意圖 貼紙。根因在敘述本身——原文寫「arcing beside the main subject」，
        而主體（手機、人臉）常常就在上半部，模型照著長就往上跑，跟後面那句
        MIDDLE OR LOWER 打架。同一個教訓：矛盾要拆掉，不是靠另一句壓。"""
        pool = dict(editor_formats.COVER_ACCESSORY_POOL)
        self.assertIn("HEADLINE BLOCK", pool["bubbles"])
        self.assertNotIn("arcing beside the main subject", pool["bubbles"])

    def test_the_seam_note_only_appears_on_the_split_layout(self):
        """E_L2 那排圖示橫跨切線正中央，兩格共用一排。切線是雙切才有的東西，
        版面是程式知道的事——不該叫模型自己判斷這張有沒有切線。"""
        split = editor_formats.cover_accessories(4, seed=1, full_width=False)
        full = editor_formats.cover_accessories(4, seed=1, full_width=True)
        self.assertTrue(all("never across the centre seam" in x for x in split))
        self.assertTrue(all("centre seam" not in x for x in full))
        # 滿版仍然要擋上三分之一（F_L3 的箭頭就是這樣頂上去的）
        self.assertTrue(all("MIDDLE OR LOWER AREA ONLY" in x for x in full))

    def test_accessory_shapes_rotate_instead_of_always_being_circles(self):
        """2026-09-11 使用者：「配件圖示的形狀也不一定只有圓形可以用吧。」
        原本 magnifier／bubbles／iconrow 三件把 CIRCULAR／ROUND 寫死，
        同一級重生只換配色不換形狀。形狀跟招式共用同一個 seeded RNG。"""
        self.assertNotIn("{shape}", " ".join(editor_formats.cover_accessories(4, seed=0)))
        shaped = set()
        for seed in range(40):
            for text in editor_formats.cover_accessories(4, seed=seed):
                for shape in editor_formats.COVER_ACCESSORY_SHAPES:
                    if shape in text:
                        shaped.add(shape)
        self.assertGreater(len(shaped), 3, shaped)
        # 形狀池不准夾帶數字——延續「招式不宣稱數字」那條
        for shape in editor_formats.COVER_ACCESSORY_SHAPES:
            with self.subTest(shape=shape):
                self.assertNotRegex(shape, r"\d")

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
        # 2026-09-11：原本釘的是無條件禁令「must not be one flat colour」。實拍證明
        # 那句跟「名詞不准切開」正面矛盾——「哈拉德」整行就是一個詞，遵守換色就
        # 必然切開名字，模型在 L1 選了聽換色那句。禁令已拆掉（不是覆蓋），所以這裡
        # 改釘同一件事的新形狀：仍然要求「中途換色」這個預設行為在。
        self.assertIn("switch colour PART-WAY THROUGH this row", plain)

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


class VariationAxisTests(unittest.TestCase):
    """變化池（2026-09-11 第四輪）。使用者：「除了配件之外，字型、底色框的形狀、
    標題配色……是不是都可以放進 RNG 池？」

    可以，而且理由跟形狀那次一樣：**許可句推不動模型**。「You choose the typeface」
    「PLACEMENT IS FREED」寫了七批，成品每次都同一種黑體、同一個左下角——
    模型沒有偏好，它有預設值。要它變就要每次給一個不一樣的命令，而命令由程式抽。
    """

    #: 軸名 → (池子, 從綱要裡撈出該軸用字的函式)
    AXES = {
        "plate": (lambda: editor_formats.COVER_PLATE_SHAPES, 4),
        "stagger": (lambda: editor_formats.COVER_STAGGER_PATTERNS, 4),
        "typeface": (lambda: editor_formats.COVER_TYPEFACES, 4),
        "anchor": (lambda: editor_formats.COVER_ANCHORS, 4),
    }

    def _seen(self, pool, level, seeds=60):
        found = set()
        for seed in range(seeds):
            brief = editor_formats.cover_design_brief(level, seed=seed)
            for item in pool:
                if item in brief:
                    found.add(item)
        return found

    def test_every_axis_actually_rotates(self):
        """一軸只要退化成固定值，這一級的成品就又會每次長一樣。"""
        for name, (pool, level) in self.AXES.items():
            with self.subTest(axis=name):
                seen = self._seen(pool(), level)
                self.assertGreater(len(seen), 2, (name, seen))

    def test_one_seed_reproduces_the_whole_look(self):
        """所有軸共用同一顆 rng：同一個 seed 一定重現，否則出了事沒得追。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                self.assertEqual(editor_formats.cover_design_brief(level, seed=11),
                                 editor_formats.cover_design_brief(level, seed=11))
        self.assertNotEqual(editor_formats.cover_design_brief(4, seed=11),
                            editor_formats.cover_design_brief(4, seed=12))

    def test_the_rng_changes_style_never_loudness(self):
        """**梯子不准被抽掉**。塊高％／字級落差／招式件數／反白字數是使用者剛認可的
        梯度；只要其中一樣進了池子，L2 偶爾就會比 L3 還吵，四級又糊在一起。
        """
        fixed = {
            1: ("about 18% of the frame height", "Every row is the SAME size"),
            2: ("about 24% of the frame height", "about 1.8 times", "EXACTLY 1 piece",
                "1 word of the headline sits KNOCKED OUT"),
            3: ("about 30% of the frame height", "about 2.5 times", "EXACTLY 2 pieces",
                "1 word of the headline sits KNOCKED OUT"),
            4: ("about 36% of the frame height", "about 3 times", "EXACTLY 3 pieces",
                "2 words of the headline sit KNOCKED OUT"),
        }
        for level, pinned in fixed.items():
            for seed in range(30):
                brief = editor_formats.cover_design_brief(level, seed=seed)
                for text in pinned:
                    with self.subTest(level=level, seed=seed, text=text):
                        self.assertIn(text, brief)

    def test_the_quiet_levels_stay_quiet(self):
        """1 級是「規矩」那一端：不抽字體、不抽落點、不傾斜，板形整排統一。
        這裡放進去等於把 1 級推向 2 級，梯子最左邊就不見了。"""
        for seed in range(20):
            brief = editor_formats.cover_design_brief(1, seed=seed)
            self.assertNotIn("Letterforms:", brief)
            self.assertNotIn("The headline block sits", brief)
            self.assertNotIn("rotated 5 to 8 degrees", brief)
            self.assertIn("all cut the same way", brief)
        # 2 級開字體、還不開落點（落點要等 3 級條文 PLACEMENT IS FREED）
        two = editor_formats.cover_design_brief(2, seed=0)
        self.assertIn("Letterforms:", two)
        self.assertNotIn("The headline block sits", two)

    def test_no_pool_smuggles_in_a_number_or_a_font_name(self):
        """數字：延續「招式不宣稱數字」——程式算得出來的數，模型畫不準。
        字體名：給名字模型會直接拿英文字體來套，中文標題就崩了，所以只描述字形骨架。"""
        pools = (editor_formats.COVER_PLATE_SHAPES, editor_formats.COVER_STAGGER_PATTERNS,
                 editor_formats.COVER_TYPEFACES, editor_formats.COVER_ANCHORS,
                 editor_formats.COVER_ACCESSORY_SHAPES)
        for pool in pools:
            for item in pool:
                with self.subTest(item=item):
                    self.assertNotRegex(item, r"\d")
        for face in editor_formats.COVER_TYPEFACES:
            with self.subTest(face=face):
                for named in ("Helvetica", "Impact", "Arial", "Noto", "思源", "微軟"):
                    self.assertNotIn(named, face)

    def test_the_anchor_pool_never_sends_the_block_up_top(self):
        """上緣是 compose 後貼 示意圖 的位置——放大鏡那次已經踩過一遍。"""
        for anchor in editor_formats.COVER_ANCHORS:
            with self.subTest(anchor=anchor):
                self.assertNotIn("top", anchor)
                self.assertTrue("low" in anchor or "middle" in anchor, anchor)

    def test_the_palette_rolls_but_the_meaning_rule_still_picks_the_word(self):
        """池子決定用哪幾色，意義決定顏色落在誰身上。少了後半段就會退回白→黃→紅。"""
        seen = set()
        for seed in range(60):
            brief = editor_formats.cover_design_brief(3, seed=seed)
            self.assertIn("on the word that carries the news", brief)
            self.assertIn("COLOUR FOLLOWS MEANING, NEVER ROW ORDER", brief)
            for palette in editor_formats.COVER_PALETTES:
                if f"{palette[0]} dominant" in brief:
                    seen.add(palette)
        self.assertGreater(len(seen), 2, seen)

    def test_house_style_is_not_in_the_pool(self):
        """描邊＋硬投影＋平塗是台裡的招牌長相，不是每次可以換的東西。"""
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("saturated FLAT poster colour", clause)
        self.assertIn("hard offset drop shadow", clause)
