"""地圖準確性規則：條件注入、豁免範圍、與既有禁令的共存。

豁免的自洽性靠三條護欄釘住：
1. 畫布幾何禁數字句在同一份 prompt 內原封不動（豁免只涵蓋真實世界地理）；
2. 座標永不印成可見標籤（「數字被畫進圖」的病灶保持關閉）；
3. CONTENT_FIDELITY_RULES 原有條款的實質內容與順序不被後續增修稀釋。
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
import news_prompt  # noqa: E402
from main import AUTO_TYPE_LABEL, CHART_TYPE_CHOICES, build_digest_instructions  # noqa: E402
from news_prompt import MAP_TYPE_LABEL, build_prompt  # noqa: E402

NON_MAP_TYPES = [t for t in CHART_TYPE_CHOICES if t != MAP_TYPE_LABEL]


def digest(type_label: str, role: str = "記者", density: str = "standard") -> str:
    return build_digest_instructions(role, density, type_label)


def image_prompt(type_label: str, role: str = "記者", engine: str = "gemini") -> str:
    return build_prompt(
        role=role, engine=engine, type_label=type_label,
        style="S", structure="T", variable="V", safe_frame=True,
    )


class DigestInjectionTests(unittest.TestCase):
    def test_map_type_gets_the_block(self):
        self.assertIn("MAP ACCURACY RULES", digest(MAP_TYPE_LABEL))

    def test_auto_type_gets_the_block(self):
        # 自動判斷組 prompt 時還不知道 AI 會選哪一類，須注入並靠文字自我限縮
        prompt = digest(AUTO_TYPE_LABEL)
        self.assertIn("MAP ACCURACY RULES", prompt)
        self.assertIn("ignore this whole block", prompt)

    def test_other_types_do_not_get_the_block(self):
        for type_label in NON_MAP_TYPES:
            with self.subTest(type_label=type_label):
                self.assertNotIn("MAP ACCURACY RULES", digest(type_label))

    def test_block_present_for_both_roles_and_densities(self):
        for role in ("記者", "編輯"):
            for density in ("standard", "simplified", "verbatim"):
                with self.subTest(role=role, density=density):
                    self.assertIn("MAP ACCURACY RULES", digest(MAP_TYPE_LABEL, role, density))

    def test_block_sits_after_content_fidelity(self):
        prompt = digest(MAP_TYPE_LABEL)
        self.assertLess(prompt.index("CONTENT FIDELITY"), prompt.index("MAP ACCURACY RULES"))


class ExemptionScopeTests(unittest.TestCase):
    def test_coordinate_exception_is_scoped_to_geography(self):
        prompt = digest(MAP_TYPE_LABEL)
        self.assertIn("SCOPED EXCEPTION TO THE NO-NUMBERS RULE", prompt)
        self.assertIn("positions, insets, gutters and sizes on the canvas", prompt)
        self.assertIn("SCOPED EXCEPTION TO CONTENT FIDELITY", prompt)

    def test_prompt_does_not_actively_request_coordinate_labels(self):
        # 2026-07-31 使用者裁決：座標入圖可以接受，但 prompt 不得主動要求列出。
        # 措辭是中性的「不要求」而非硬禁止——digest 不得指示 renderer 顯示座標。
        prompt = digest(MAP_TYPE_LABEL)
        self.assertIn("printing them is neither required nor requested", prompt)
        self.assertIn('"structure" must not instruct the renderer to display them', prompt)

    def test_layout_number_ban_survives_in_the_same_prompt(self):
        # 豁免的迴歸護欄：畫布幾何禁數字句必須原封不動仍在
        for full_bleed in (False, True):
            with self.subTest(full_bleed=full_bleed):
                prompt = build_digest_instructions("記者", "standard", MAP_TYPE_LABEL, full_bleed)
                self.assertIn("NEVER express any position", prompt)
                self.assertIn("percentage, pixel, ratio", prompt)

    def test_no_confidence_fallback_exists(self):
        prompt = digest(MAP_TYPE_LABEL)
        self.assertIn("Never invent islands, coastlines, landmasses or maritime boundaries", prompt)

    def test_disputed_zone_label_is_required(self):
        self.assertIn("主張範圍 示意", digest(MAP_TYPE_LABEL))


class DigestWordingTests(unittest.TestCase):
    """2026-09-04 基隆淹水圖的三個病灶，全在消化端措辭（見 docs/error-cases）。"""

    def test_legend_and_duplicate_place_lists_are_banned(self):
        # 病灶一：三個地名已經標在地圖上，又被寫成 [內文小標]，渲染成左下角圖例框
        prompt = digest(MAP_TYPE_LABEL)
        self.assertIn("NEVER BUILD A LEGEND", prompt)
        self.assertIn("圖例", prompt)

    def test_instruction_words_may_not_become_printed_text(self):
        # 病灶二：variable 寫成「標示<基隆廟口>」，renderer 逐字印出「標示 基隆廟口」
        prompt = digest(MAP_TYPE_LABEL)
        self.assertIn("標示", prompt)
        self.assertIn("INSTRUCTION WORD BECOME PRINTED TEXT", prompt)

    def test_gazetteer_form_stays_out_of_structure_and_variable(self):
        # 病灶三：查詢用的「基隆廟口夜市」被寫進 structure，畫面上與內文的「基隆廟口」不一致
        prompt = digest(MAP_TYPE_LABEL)
        self.assertIn("ONE PLACE, ONE NAME ON SCREEN", prompt)
        self.assertIn("基隆廟口夜市", prompt)

    def test_map_places_is_declared_never_rendered(self):
        self.assertIn("Nothing you write in this field is ever printed", digest(MAP_TYPE_LABEL))

    def test_the_new_rules_only_reach_map_and_auto_types(self):
        for type_label in NON_MAP_TYPES:
            with self.subTest(type_label=type_label):
                self.assertNotIn("NEVER BUILD A LEGEND", digest(type_label))
        self.assertIn("NEVER BUILD A LEGEND", digest(AUTO_TYPE_LABEL))


class ContentFidelityUntouchedTests(unittest.TestCase):
    """原有的忠實度條款不得被後續改動悄悄稀釋。

    原本是「本輪不修改 CONTENT_FIDELITY_RULES」的凍結測試。2026-09-05 使用者
    指示補上「版面類型名稱不是新聞」那條（見 HeadlineHasNoChartTypeTests），
    因此改成守住原有五條的實質內容與順序、以及 EXCEPTION 的墊底位置，
    而不是鎖死條數——鎖條數只會讓下一次正當的增修卡在這裡。
    """

    ORIGINAL_CLAUSES = (
        "Use ONLY facts, figures, names, dates and quotes",
        "NEVER invent or infer",
        "NEVER invent a data source",
        "If the source material is thin, produce fewer points",
        "Do not upgrade hedged wording into certainty",
    )

    def test_constant_starts_as_before(self):
        self.assertTrue(
            main.CONTENT_FIDELITY_RULES.startswith("\n\nCONTENT FIDELITY (NON-NEGOTIABLE")
        )

    def test_the_original_clauses_survive_in_order(self):
        rules = main.CONTENT_FIDELITY_RULES
        positions = [rules.find(text) for text in self.ORIGINAL_CLAUSES]
        self.assertNotIn(-1, positions, "原有條款被刪掉或改寫了")
        self.assertEqual(positions, sorted(positions), "原有條款的順序被打亂了")

    def test_the_exception_clause_stays_last(self):
        rules = main.CONTENT_FIDELITY_RULES.rstrip()
        exception = rules.rfind("EXCEPTION — supplementation is allowed")
        self.assertGreater(exception, 0)
        # EXCEPTION 是墊底的例外條款，後面不該再冒出新的編號條目
        self.assertNotRegex(rules[exception:], r"\n\d+\.")


class ImageStageTests(unittest.TestCase):
    def test_map_type_gets_the_image_block(self):
        for role in ("記者", "編輯"):
            for engine in ("gemini", "gpt"):
                with self.subTest(role=role, engine=engine):
                    self.assertIn("MAP ACCURACY RULES", image_prompt(MAP_TYPE_LABEL, role, engine))

    def test_non_map_types_do_not_get_the_image_block(self):
        for type_label in NON_MAP_TYPES:
            with self.subTest(type_label=type_label):
                self.assertNotIn("MAP ACCURACY RULES", image_prompt(type_label))

    def test_coordinates_are_positioning_only_at_image_stage(self):
        # 中性措辭：座標是定位指令、不要求印成標籤（但也不硬禁止，使用者裁決）
        prompt = image_prompt(MAP_TYPE_LABEL)
        self.assertIn("You are not asked to print them as labels", prompt)

    def test_map_type_label_constant_matches_choices(self):
        self.assertIn(news_prompt.MAP_TYPE_LABEL, CHART_TYPE_CHOICES)




class LookupablePlacesOnlyTests(unittest.TestCase):
    """map_places 只能放查得到的點，不能放模糊區域或里程位置。

    2026-09-05 實查：「北海岸」被 Nominatim 配到臺中市北屯區一家同名餐廳
    （離基隆 130 公里）、「低窪地區」配到臺北一家泰式餐廳。程式端已加可信度
    檢查（map_lookup._looks_like_the_place_asked_for），但「南部」「東海岸」
    這類本身就是地名的模糊區域擋不掉——那要靠消化端一開始就不要寫進來。
    """

    def _rules(self) -> str:
        return main.MAP_ACCURACY_RULES

    def test_vague_regions_are_named_as_forbidden(self):
        for word in ("北海岸", "南部", "市區", "低窪地區"):
            with self.subTest(word=word):
                self.assertIn(word, self._rules())

    def test_road_kilometre_positions_are_named_as_forbidden(self):
        self.assertIn("楊梅路段北向68公里", self._rules())

    def test_the_fallback_is_the_district(self):
        self.assertIn("桃園市 楊梅區", self._rules())

    def test_the_consequence_is_spelled_out(self):
        self.assertIn("wrong lookup puts a marker on the wrong town", self._rules())


class FacilityLookupNameTests(unittest.TestCase):
    """交流道／車站這種有名字的設施，前面不要冠道路或路線名。

    2026-09-05 實測：「國道1號中壢交流道」查無座標，但「中壢交流道」
    查得到（highway/motorway_junction, 24.9599/121.2024），
    「桃園市 中壢區 中壢交流道」也查得到。冠上道路名反而讓它查不到。
    """

    def test_the_road_prefix_is_called_out(self):
        self.assertIn("國道1號中壢交流道", main.MAP_ACCURACY_RULES)
        self.assertIn("中壢交流道", main.MAP_ACCURACY_RULES)

    def test_the_district_qualified_form_is_offered(self):
        self.assertIn("桃園市 中壢區 中壢交流道", main.MAP_ACCURACY_RULES)


class UnassignedFactTests(unittest.TestCase):
    """沒有綁定地點的事實，不准派給某一支標記。

    2026-09-05 實測（SOT2 第三輪，高雄積水）。消化端的 variable 是：
        [內文小標] 三民建工路 左營博愛二路 鳳山中山西路
                   最深積水40公分 多輛機車熄火
                   水利局出動抽水機
    「最深積水40公分 多輛機車熄火」自己一行、沒有指名哪一處，但成品把
    「最深積水 40 公分」掛在三民、「多輛機車熄火」掛在左營與鳳山。原文
    根本沒說是哪一處——這是生圖階段憑空生出來的歸屬，屬於內容真實性問題。
    消化端沒有錯（GCS 存檔的 prompt 可查），所以規則要加在圖面端。
    """

    def test_the_image_rules_forbid_assigning_a_loose_fact_to_one_marker(self):
        rules = news_prompt.MAP_ACCURACY_IMAGE_RULES
        self.assertIn("does not itself name a place", rules)
        self.assertIn("do not attach it to one marker", rules)


class StampNotADuplicateTests(unittest.TestCase):
    """蓋章不可以跟某條內文小標講同一句話。

    2026-09-05 實測（SOT2 第二輪，高雄積水）：內文小標「水利局出動抽水機
    預計傍晚前退水」與蓋章「水利局已出動抽水機 預計傍晚前退水」幾乎同句，
    成品上同一件事出現兩次。
    """

    def test_the_stamp_must_not_repeat_a_subhead(self):
        self.assertIn("MUST NOT REPEAT A 內文小標", main.STAMP_ON_RULES)


class HeadlineHasNoChartTypeTests(unittest.TestCase):
    """版面類型名稱不是新聞內容，不准寫進標題。

    2026-09-05 實測（SOT2 第二輪）：標題被寫成「台中火鍋店疑食物中毒 示意圖」，
    「示意圖」三個字以大黃字直接畫在標題尾巴。
    """

    def test_the_chart_type_name_is_banned_from_the_headline(self):
        rules = main.CONTENT_FIDELITY_RULES
        self.assertIn("示意圖", rules)
        self.assertIn("資料圖表", rules)
        self.assertIn("headline", rules.lower())


if __name__ == "__main__":
    unittest.main()
