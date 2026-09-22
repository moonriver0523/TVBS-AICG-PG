"""B82：「川習會」這類簡稱標題推導不出人名 → 零參考照 → 生圖模型自己編臉。

2026-09-21 使用者回報正式站 11:01:35 那筆（`50d0f78baccd`，十點不一樣雙切，
標題「全球矚目　本周川習會」）「川習」根本畫錯人了。

查證結論：不是生圖模型亂畫，是餵給它的畫面描述本身就沒講是誰。
同一則新聞連生三次，對照組自己就把因果講完了——

    11:01:35  R＝「國際會議廳內並排陳列兩國國旗，**兩位領導人**握手致意」→ 沒有名字
    11:03:52  R＝「國際會議廳外兩國旗幟並列，各國媒體長焦鏡頭群嚴陣以待」→ 乾脆沒有人
    10:57:44  R＝「**川普**在講台上面容嚴肅正視前方演說」→ 有名字

三筆輸入都只有標題（46／46／47 字），沒有新聞內文。

修法是查表，不是放寬護欄：VERBATIM 規則擋的是模型腦補，程式查表是確定性的。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
import name_aliases  # noqa: E402


class AliasTableShapeTests(unittest.TestCase):
    def test_the_first_batch_is_exactly_what_the_user_asked_for(self):
        """2026-09-21 使用者：「川習會 → 川普＋習近平，拜習會、普習會同理　<-第一批納入」"""
        self.assertEqual(name_aliases.NAME_ALIASES["川習會"], ("川普", "習近平"))
        self.assertEqual(name_aliases.NAME_ALIASES["拜習會"], ("拜登", "習近平"))
        self.assertEqual(name_aliases.NAME_ALIASES["普習會"], ("普欽", "習近平"))

    def test_every_value_is_a_bare_personal_name(self):
        """夾帶頭銜或組織就會被整串塞進 portrait_subjects，然後拿去查照片查不到。
        具名真人規則講得很明白：名字要 no title, no organisation。"""
        banned = ("總統", "主席", "國家", "美國", "中國", "俄羅斯", "先生", "女士", " ")
        for alias, names in name_aliases.NAME_ALIASES.items():
            for person in names:
                with self.subTest(alias=alias, person=person):
                    for bad in banned:
                        self.assertNotIn(bad, person)
                    self.assertLessEqual(len(person), 4)

    def test_taiwan_transliterations_only(self):
        """臺灣譯名鐵則：川普／普欽，不是特朗普／普京／普丁。"""
        everyone = {p for names in name_aliases.NAME_ALIASES.values() for p in names}
        for wrong in ("特朗普", "普京", "普丁", "拜習", "奧巴馬"):
            with self.subTest(wrong=wrong):
                self.assertNotIn(wrong, everyone)

    def test_no_single_character_entries(self):
        """刻意不做單字展開：「川普」這兩個字本身也是「四川腔國語」，
        「習」更是常用字（學習、習慣）。單字比對會製造比原本更難查的誤判。

        2026-09-22：下限從 3 放寬到 2（使用者指定收「川習」）。**兩個字的條目
        一律要有阻擋字表**，見下一條——沒有的話就等於開了跨詞邊界的誤判閘門。
        """
        for alias in name_aliases.NAME_ALIASES:
            with self.subTest(alias=alias):
                self.assertGreaterEqual(len(alias), 2)

    def test_every_two_character_entry_has_a_blocking_list(self):
        """三個字以上的簡稱（「川習會」）幾乎不可能跨詞碰撞；兩個字的會。
        「四川習俗」「四川習近平視察」裡都有「川習」——沒擋的話會把川普畫進
        一則四川新聞裡，比畫成背影嚴重得多。"""
        for alias in name_aliases.NAME_ALIASES:
            if len(alias) <= 2:
                with self.subTest(alias=alias):
                    self.assertTrue(
                        name_aliases.BLOCKING_PREFIXES.get(alias),
                        f"兩個字的條目「{alias}」沒有登記阻擋字",
                    )

    def test_the_second_batch_is_exactly_what_the_user_asked_for(self):
        """2026-09-22 使用者：「B88 "川習" 也要列入條目」"""
        self.assertEqual(name_aliases.NAME_ALIASES["川習"], ("川普", "習近平"))


class FindAliasesTests(unittest.TestCase):
    def test_it_finds_the_abbreviation_inside_a_real_headline(self):
        """出事那張的標題原文。"""
        hits = name_aliases.find_aliases("全球矚目　本周川習會")
        self.assertEqual(hits, [("川習會", ("川普", "習近平"))])

    def test_nothing_matches_when_the_abbreviation_is_absent(self):
        self.assertEqual(name_aliases.find_aliases("半年狂燒1.4兆　美軍死亡低報?"), [])
        self.assertEqual(name_aliases.find_aliases(""), [])
        self.assertEqual(name_aliases.find_aliases("", "", ""), [])

    def test_a_bare_surname_does_not_match(self):
        """10:57:44 那筆的標題是「川劍指中國」——單字「川」不在表上，不可以命中。
        它那次拿到名字是模型自己補的（正是護欄要擋的行為），不是這張表的功勞。"""
        self.assertEqual(name_aliases.find_aliases("川劍指中國　誰贏AI贏天下"), [])
        self.assertEqual(name_aliases.find_aliases("學習歷程檔案上路"), [])

    def test_it_looks_across_every_field_it_is_given(self):
        """雙切兩格各有標題，簡稱可能只出現在其中一格。"""
        hits = name_aliases.find_aliases("台北生存戰", "本周川習會")
        self.assertEqual([a for a, _ in hits], ["川習會"])

    def test_the_two_character_entry_catches_the_headlines_the_long_one_misses(self):
        """使用者要「川習」的理由：標題常寫「川習通話」「川習互動」，
        三個字的「川習會」比對不到，B88 接好了照樣落空。"""
        for headline in ("川習通話登場", "川習互動熱絡", "本周川習登場"):
            with self.subTest(headline=headline):
                hits = name_aliases.find_aliases(headline)
                self.assertEqual(hits, [("川習", ("川普", "習近平"))])

    def test_a_cross_word_coincidence_does_not_count(self):
        """「四川習俗」「四川習近平視察」裡的「川習」是跨詞邊界的巧合。
        誤命中的代價是把川普畫進一則四川新聞裡——比畫成背影嚴重得多。"""
        for text in ("四川習俗大不同", "四川習近平視察災區", "銀川習俗巡禮"):
            with self.subTest(text=text):
                self.assertEqual(name_aliases.find_aliases(text), [])

    def test_a_real_mention_still_counts_even_next_to_a_coincidence(self):
        """同一篇裡既有巧合也有真的提到時，真的那次要贏——阻擋是逐次判定，
        不是「整篇出現過巧合就整條放棄」。"""
        hits = name_aliases.find_aliases("川習互動熱絡，四川習俗也入鏡")
        self.assertEqual(hits, [("川習", ("川普", "習近平"))])

    def test_the_long_and_short_forms_do_not_both_fire(self):
        """「川習會」的素材當然也含「川習」，兩條指向同一組人。
        兩條都回會讓同一組名字在素材裡出現兩次，模型讀起來像兩件事。"""
        hits = name_aliases.find_aliases("全球矚目　本周川習會")
        self.assertEqual(hits, [("川習會", ("川普", "習近平"))])

    def test_the_order_is_the_tables_order_and_there_are_no_duplicates(self):
        hits = name_aliases.find_aliases("川習會前瞻", "回顧拜習會", "又一次川習會")
        self.assertEqual([a for a, _ in hits], ["川習會", "拜習會"])


class AliasHintBlockTests(unittest.TestCase):
    def test_no_hit_means_byte_identical_material(self):
        """硬要求：沒命中就必須完全不動素材，否則既有 rng_pins fixture 與
        各版型的 prompt 比對測試會整批失效。"""
        self.assertEqual(name_aliases.alias_hint_block("今日天氣"), "")
        self.assertEqual(name_aliases.alias_hint_block(""), "")

    def test_the_block_states_it_is_a_table_not_an_inference(self):
        """這是整張表正當性的所在：護欄擋的是模型腦補，不是程式查表。
        如果這段話讓模型以為「可以自己推」，那就等於放寬了 VERBATIM。"""
        block = name_aliases.alias_hint_block("本周川習會")
        self.assertIn("human-maintained lookup table", block)
        self.assertIn("not a guess", block)
        self.assertIn("established fact", block)

    def test_the_block_authorises_naming_only_for_listed_people(self):
        block = name_aliases.alias_hint_block("本周川習會")
        self.assertIn("川普", block)
        self.assertIn("習近平", block)
        self.assertIn("as if it were written out in full", block)
        # 其餘人仍受原規則拘束——少了這句，模型會把授權讀成全面解禁。
        self.assertIn("the verbatim rule stands unchanged", block)
        self.assertIn("never expand an abbreviation", block)

    def test_only_the_matched_rows_appear(self):
        block = name_aliases.alias_hint_block("本周川習會")
        self.assertNotIn("拜登", block)
        self.assertNotIn("普欽", block)


class CoverDeriveWiringTests(unittest.TestCase):
    """兩條封面推導路徑都要接上；一條沒接就有一種版型照樣畫錯人。"""

    def _ten_material(self, **kw) -> str:
        captured = {}

        def fake_digest(**kwargs):
            captured["material"] = kwargs["news_text"]
            raise RuntimeError("stop here — 只要素材，不打模型")

        req = main.TenCoverRequest(
            title_left=kw.get("title_left", "台北生存戰"),
            title_right=kw.get("title_right", "全球矚目 本周川習會"),
        )
        original = main.digest_completion
        main.digest_completion = fake_digest
        try:
            main.resolve_cover_visuals(req)
        finally:
            main.digest_completion = original
        return captured["material"]

    def _yt_material(self, title: str) -> str:
        captured = {}

        def fake_digest(**kwargs):
            captured["material"] = kwargs["news_text"]
            raise RuntimeError("stop here")

        original = main.digest_completion
        main.digest_completion = fake_digest
        try:
            main.derive_yt_cover_plan(title, None)
        finally:
            main.digest_completion = original
        return captured["material"]

    def test_the_ten_cover_material_carries_the_glossary(self):
        material = self._ten_material()
        self.assertIn("川普", material)
        self.assertIn("習近平", material)
        self.assertIn("human-maintained lookup table", material)

    def test_the_yt_cover_material_carries_the_glossary(self):
        material = self._yt_material("全球矚目 本周川習會")
        self.assertIn("川普", material)
        self.assertIn("human-maintained lookup table", material)

    def test_both_paths_leave_unrelated_material_untouched(self):
        """沒有簡稱的稿子，素材必須跟加這張表之前逐字相同。"""
        ten = self._ten_material(title_left="台北生存戰", title_right="身體亮紅燈")
        self.assertNotIn("glossary", ten)
        self.assertNotIn("川普", ten)
        yt = self._yt_material("台北生存戰 4.5萬不夠活")
        self.assertNotIn("glossary", yt)

    def _general_material(self, news_text: str, **kw) -> str:
        """一般 CG（`/api/generate`）這條路送進消化端的素材。"""
        captured = {}

        def fake_digest(**kwargs):
            captured["material"] = kwargs["news_text"]
            raise RuntimeError("stop here")

        kw.setdefault("type_label", "資料圖表")
        req = main.GenerateRequest(news_text=news_text, **kw)
        original = main.digest_completion
        main.digest_completion = fake_digest
        try:
            main.generate(req)
        except Exception:
            pass
        finally:
            main.digest_completion = original
        return captured.get("material", "")

    def test_the_general_cg_material_carries_the_glossary(self):
        """B88（2026-09-22 使用者回報「川習被畫成背影」）：一般 CG 以前完全沒接
        這張表，B82 的因果鏈在記者／編輯CG 上原封不動重演一次。

        這條路的終點是 `portrait_subjects`：交白卷就查不到參考照，
        `news_prompt.py:334`「沒有附照片的具名真人必須畫成背影或剪影」就生效。
        """
        material = self._general_material("全球矚目，本周川習會登場，兩國領導人將會晤。")
        self.assertIn("川普", material)
        self.assertIn("習近平", material)
        self.assertIn("human-maintained lookup table", material)

    def test_the_general_cg_material_is_untouched_without_an_abbreviation(self):
        material = self._general_material("今天北部有雨，氣溫下探十五度。")
        self.assertNotIn("glossary", material)
        self.assertNotIn("川普", material)

    def test_the_glossary_wording_is_path_neutral(self):
        """措辭原本照十點雙切寫（「the side whose headline」）。一般 CG 沒有 side
        也沒有 headline，照搬過去模型讀不出這段在講哪一塊。"""
        block = name_aliases.alias_hint_block("本周川習會")
        self.assertNotIn("the side whose headline", block)
        self.assertIn("in the material above", block)

    def test_the_glossary_sits_before_the_editor_instruction(self):
        """使用者指令欄講的是「畫面長什麼樣」，必須留在最後一段——
        中間插東西會讓模型把指令讀成對照表的一部分。"""
        captured = {}

        def fake_digest(**kwargs):
            captured["material"] = kwargs["news_text"]
            raise RuntimeError("stop here")

        req = main.TenCoverRequest(
            title_left="台北生存戰", title_right="全球矚目 本周川習會",
            instruction="畫面要明亮一點",
        )
        original = main.digest_completion
        main.digest_completion = fake_digest
        try:
            main.resolve_cover_visuals(req)
        finally:
            main.digest_completion = original
        material = captured["material"]
        self.assertLess(material.index("川普"), material.index("畫面要明亮一點"))


class SystemPromptsAcknowledgeTheGlossaryTests(unittest.TestCase):
    """B91（2026-09-22）：三份推導 system prompt 都必須承認這張對照表的存在。

    真因紀錄（DEV 後台 2026-09-22 17:29:22，`bce3a1f6206c`，操作者 許岱軒）：
    對照表**有生效**——消化輸出的內文小標寫「川普與習近平會談成未知數」，而
    「習近平」三個字新聞原文一次都沒出現（原文只有「納入川習之間」），模型不
    可能逐字抄。但同一次的 `portrait_subjects` 交白卷，STRUCTURE 還寫了
    `The named figures appear strictly via typography and data callouts without
    rendered photographic portraits.`——最終 prompt 裡因此沒有 NAMED REAL PERSON
    區塊，通則接手「沒有那個區塊就畫背影或剪影」，成品就是川普與習近平的背影。

    模型會這樣折衷，是因為對照表放在**使用者素材**裡說「當作已寫明」，而
    system prompt 的規則 5 寫著絕對禁令「never infer a person from … an event」
    ——「川習會」正是 event。於是名字敢寫進文字，不敢列進 portrait_subjects。

    這裡釘的不是措辭，是**兩邊對得上**：對照表區塊的標題字串一旦在
    `name_aliases` 改掉而 prompt 沒跟著改，例外條款就會靜默失效，而症狀又會長
    得像生圖模型的問題（背影），查起來一樣貴。
    """

    HEADING = "Abbreviation glossary supplied by the newsroom"

    def test_the_heading_in_the_block_is_the_one_the_prompts_quote(self):
        block = name_aliases.alias_hint_block("本周川習會登場")
        self.assertIn(self.HEADING, block)

    def test_the_news_cg_rule_five_carries_the_exception(self):
        rules = main.REAL_WORLD_FIDELITY_RULES
        self.assertIn(self.HEADING, rules)
        # 例外只能放行對照表上的名字，不能變成整條 VERBATIM 護欄的後門
        self.assertIn("ONE EXCEPTION", rules)
        self.assertIn("the verbatim rule stands unchanged", rules)

    def test_both_cover_derive_prompts_carry_the_exception(self):
        import editor_formats

        with open(editor_formats.__file__, encoding="utf-8") as handle:
            text = handle.read()
        # 十點雙切與 YT 封面各一份，兩份都要有——只改一份的話另一份會重演本案
        self.assertEqual(text.count(self.HEADING), 2)

    def test_the_exception_forbids_the_hedge_that_caused_this(self):
        """釘住這一案的具體病灶：名字寫進文字、人卻不進 portrait_subjects。"""
        rules = main.REAL_WORLD_FIDELITY_RULES
        self.assertIn("Do not hedge", rules)
        self.assertIn("via typography only", rules)


if __name__ == "__main__":
    unittest.main()
