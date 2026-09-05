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


class PairingFactsWithPlacesTests(unittest.TestCase):
    """原文沒有把事實配給某個地點時，消化端也不准自己配。

    2026-09-05 第四輪實測（SOT2）。圖面端的規則已擋住生圖模型自行分派，
    但消化端這次自己在 variable 裡配好了：
        [內文小標]三民區建工路 積水影響通行
        [內文小標]左營區博愛二路 多輛機車熄火
        [內文小標]鳳山區中山西路 水利局搶救排水
    原文只說三處先後積水、最深 40 公分、多輛機車熄火、水利局出動抽水機，
    沒說哪一處機車熄火、哪一處在排水。生圖照著畫，畫面上就成了報導事實。
    圖面端擋得住模型自己亂配，擋不住消化端已經配好的。
    """

    def test_the_digest_may_not_pair_a_fact_with_a_place(self):
        rules = main.CONTENT_FIDELITY_RULES
        self.assertIn("PAIRING A FACT WITH A PLACE IS ITSELF A CLAIM", rules)
        self.assertIn("多輛機車熄火", rules)

    def test_the_rule_reaches_every_chart_type(self):
        for type_label in (*NON_MAP_TYPES, MAP_TYPE_LABEL, AUTO_TYPE_LABEL):
            with self.subTest(type_label=type_label):
                self.assertIn("PAIRING A FACT WITH A PLACE", digest(type_label))


class CalloutBelongsToItsPinTests(unittest.TestCase):
    """callout 要接到同一個地名的那支 pin，而且 pin 旁一定要有地名。

    2026-09-05 第四輪實測：國道車禍圖三支 pin 都壓在正確橘點上，但 pin 本身
    沒有地名標籤，leader line 又接錯——中壢交流道那支接到「楊梅北向68公里」，
    楊梅那支接到「中壢南向62公里」。觀眾只看得到 callout，等於兩起事故互換。
    位置畫對了，意思還是錯的。
    """

    def test_every_pin_must_carry_its_place_name(self):
        rules = news_prompt.MAP_ACCURACY_IMAGE_RULES
        self.assertIn("EVERY MARKER CARRIES ITS OWN PLACE NAME", rules)

    def test_the_leader_line_must_match_the_place_name(self):
        rules = news_prompt.MAP_ACCURACY_IMAGE_RULES
        self.assertIn("leader line", rules)
        self.assertIn("NAMES THE SAME PLACE", rules)


class PairingRuleIsNotABlanketBanTests(unittest.TestCase):
    """禁止「自己配」不等於禁止「照抄原文已經配好的」。

    2026-09-05 第五輪實測（SOT2）：規則加上去之後，國道車禍那則的三段
    「楊梅路段砂石車追撞2人受傷」「中壢交流道4車連環1人輕傷」
    「湖口路段貨櫃車起火駕駛脫困」全部從 variable 消失——這些是原文本來就
    綁好地點的事實，第四輪（加規則前）都有寫。地圖類最有價值的「哪裡發生
    什麼」整個不見了，是我的措辭寫太寬造成的回歸。
    """

    def test_the_rule_says_to_keep_what_the_source_already_paired(self):
        rules = main.CONTENT_FIDELITY_RULES
        self.assertIn("KEEP EVERY PAIRING THE SOURCE ALREADY MADE", rules)
        self.assertIn("楊梅路段砂石車追撞", rules)

    def test_the_rule_still_forbids_inventing_a_pairing(self):
        self.assertIn("PAIRING A FACT WITH A PLACE IS ITSELF A CLAIM",
                      main.CONTENT_FIDELITY_RULES)


class NoMarkerOfAnyShapeTests(unittest.TestCase):
    """沒有橘點的地點，換什麼形狀的標記都不准畫。

    2026-09-05 第五輪實測：規則只講 pin，模型改用紅色三角形警示圖示加標籤框
    加引線，照樣把「國道1號北向68公里」釘在國道路面上——而那幾個字根本不在
    variable 裡。措辭只要指名某一種形狀，模型就換一種繞過去。
    """

    def test_the_ban_covers_any_marker_not_just_pins(self):
        rules = news_prompt.USER_REFERENCE_MAP_RULES
        self.assertIn("marker, icon, arrow, triangle, leader line", rules)
        self.assertIn("whatever shape", rules)


class BasemapLabelsAreAuthoritativeTests(unittest.TestCase):
    """底圖橘點旁烙上的地名，就是那個點的身分，不准重新配對。

    2026-09-05 第四、五輪連續兩輪同一稿：pin 位置照橘點畫對了，名字卻配錯
    （最北的橘點是中壢交流道，成品標成楊梅）。根因是底圖只有橘點、沒有身分
    線索，模型只能自己猜。程式端改成把地名烙在點旁邊，prompt 端要告訴模型
    那些字是權威來源——否則會撞到既有的「標籤只能來自 VARIABLE FIELDS」。
    """

    def test_the_burned_in_names_are_declared_authoritative(self):
        rules = news_prompt.USER_REFERENCE_MAP_RULES
        self.assertIn("THE NAME PRINTED BESIDE A DOT IS THAT DOT'S IDENTITY", rules)

    def test_it_carves_an_exception_to_the_no_text_from_the_map_rule(self):
        rules = news_prompt.USER_REFERENCE_MAP_RULES
        # 既有規則說「附圖裡的文字一律不可入圖」，這裡是唯一例外，必須講明
        self.assertIn("the one exception", rules.lower())


class LeaderLineStaysOffTheBasemapTests(unittest.TestCase):
    """引線的兩端都不能落在底圖上。

    2026-09-05 第六輪實測：規則改成「任何形狀的標記都不准」之後，模型不再畫
    三角形了，卻留下一條黃色虛線，從文字框連到卡車插圖、再往左延伸進底圖，
    末端停在某條道路上——沒有標記形狀，位置照樣被指定了。
    """

    def test_no_end_of_a_leader_line_may_land_on_the_map(self):
        rules = news_prompt.USER_REFERENCE_MAP_RULES
        self.assertIn("NEITHER END OF A LEADER LINE", rules)


class EachLineRendersOnceTests(unittest.TestCase):
    """同一段文字只畫一次；蓋章句不准同時出現在內文列。

    2026-09-05 第六輪實測，兩種重複同時出現：
      規則 B 那則的「國道1號北向68公里處…」文字框在右上與右下各畫了一次；
      高雄那則的蓋章句「水利局已出動抽水機 預計傍晚前退水」被多畫成一列
      內文小標（variable 裡沒有這一行），蓋章條再出現一次同句。
    這是圖面端自己複製的，消化端的規則管不到。
    """

    def test_every_variable_line_is_rendered_exactly_once(self):
        self.assertIn("EXACTLY ONCE", news_prompt.TEXT_PLACEMENT_RULES)

    def test_the_stamp_line_belongs_only_to_the_stamp_bar(self):
        rules = news_prompt.TEXT_PLACEMENT_RULES
        self.assertIn("蓋章", rules)
        self.assertIn("never also as a body line", rules)

    def test_the_block_reaches_both_roles(self):
        for role in ("記者", "編輯"):
            with self.subTest(role=role):
                self.assertIn("EXACTLY ONCE", image_prompt("資料圖表", role))


class StampKeepsTheHedgeTests(unittest.TestCase):
    """原文有保留語時，蓋章不准改成斷定。

    2026-09-05 第五、六輪連兩輪：原文「上午9點半才陸續排除」→蓋章
    「9點半後 車流恢復順暢」；原文「疑與濃霧及路面濕滑有關」→蓋章
    「濃霧路滑肇禍」。蓋章是全圖唯一被做成色塊強調的一句，斷語成本最高。
    """

    def test_the_stamp_rules_name_the_hedge_words(self):
        rules = main.STAMP_ON_RULES
        self.assertIn("疑", rules)
        self.assertIn("陸續", rules)
        self.assertIn("THE STAMP MAY NOT SHARPEN WHAT THE SOURCE HEDGED", rules)


class NoInventedRelationshipTests(unittest.TestCase):
    """幾件各自獨立的事，不准寫成互為因果或連鎖。

    2026-09-05 第六輪實測：兩起機車自摔加一起貨車爆胎，彼此無關，
    標題卻寫成「桃園今晨連環車禍」。「連環」是模型加的關聯。
    """

    def test_the_rule_names_the_relationship_words(self):
        rules = main.CONTENT_FIDELITY_RULES
        self.assertIn("連環", rules)
        self.assertIn("SEPARATE EVENTS STAY SEPARATE", rules)


class ChartTypeNameNotInSubheadsTests(unittest.TestCase):
    """「示意圖」不只不能進標題，任何一行都不行。

    2026-09-05 第六輪實測：規則寫「least of all trailing the 標題 line」，
    模型就改塞到 [內文小標] 的結尾（「…駕駛獲救 示意圖」）。
    """

    def test_the_ban_names_the_subhead_case_too(self):
        self.assertIn("nor at the end of a 內文小標", main.CONTENT_FIDELITY_RULES)


if __name__ == "__main__":
    unittest.main()
