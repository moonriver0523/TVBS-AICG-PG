import json
import os
import pathlib
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-key")

import info_layout  # noqa: E402
import main  # noqa: E402


FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


class SelectorTests(unittest.TestCase):
    def select(self, text, *, type_label="資訊卡", point_count=4):
        return info_layout.select_info_layout(
            text, type_label, "simplified", "記者", "default", point_count
        ).mode

    def test_timeline_has_two_positive_and_two_negative_examples(self):
        positives = [
            "9月1日上午9時宣布停班，9月2日下午3時恢復交通，9月3日完成清理。",
            "首先封閉道路，接著疏散住戶，隨後檢查建物，最後開放返家。",
        ]
        negatives = [
            "補助對象：青年；資格：設籍；金額：3萬元。",
            "預算達120億元，受惠8萬人，涵蓋3縣市。",
        ]
        self.assertTrue(all(self.select(text) == "timeline" for text in positives))
        self.assertTrue(all(self.select(text) != "timeline" for text in negatives))

    def test_comparison_has_two_positive_and_two_negative_examples(self):
        positives = [
            "台灣與日本相比，支持率45%與38%，席次30席與25席，台灣領先。",
            "今年和去年相較，營收80億元與72億元，員工1200人與1100人，皆有成長。",
        ]
        negatives = [
            "台灣與日本相比，支持率45%與38%，但沒有第二個共同量綱。",
            "甲、乙、丙三隊對比，得分依序為80點、75點、70點，席次各有3席、2席、1席。",
        ]
        self.assertTrue(all(self.select(text) == "comparison" for text in positives))
        self.assertTrue(all(self.select(text) != "comparison" for text in negatives))

    def test_hero_number_has_two_positive_and_two_negative_examples(self):
        positives = [
            "預算達120億元，計畫涵蓋3縣市、受惠8萬人、設置40站。",
            "投票率攀升至72%，共有4區、18萬人投票，開出320個票所。",
            "台積電本月營收達5148億元，前月4675億元，去年同期3357億元，主角仍是本月新高。",
        ]
        negatives = [
            "兩案預算分別為120億元與80億元，沒有唯一主數字。",
            "日本富士山山難，一名44歲男子登山時倒地，送醫後不治。",
            "調查列出12人、8戶、7件、6家、5次，數字過多且沒有主次。",
        ]
        self.assertTrue(all(self.select(text) == "hero_number" for text in positives))
        self.assertTrue(all(self.select(text) != "hero_number" for text in negatives))

    def test_annotated_subject_has_two_positive_and_two_negative_examples(self):
        positives = [
            "市長陳美玲表示改革主張，提出新方案並推動執行，最後完成協商。",
            "王志豪擔任教練，指出訓練目標，率領球隊調整戰術，結果獲得冠軍。",
            "拓元售票系統回應登入異常，說明影響範圍並宣布修復計畫，完成後將通知會員。",
            "尼泊爾崩塌冰川持續退縮，造成坡面失去支撐並帶來崩塌風險。",
        ]
        negatives = [
            "市長陳美玲表示主張，部長林志強提出方案，兩人共同完成協商。",
            "市長陳美玲表示改革主張，提出方案並完成協商，但本圖固定需要6點。",
            "南韓、美國與日本展開演習，總統川普表示支持並宣布照常進行。",
        ]
        self.assertTrue(all(self.select(text) == "annotated_subject" for text in positives))
        self.assertNotEqual(self.select(negatives[0]), "annotated_subject")
        self.assertNotEqual(self.select(negatives[1], point_count=6), "annotated_subject")

    def test_icon_grid_has_two_positive_and_two_negative_examples(self):
        positives = [
            "對象：青年；資格：設籍；金額：3萬元；上路：明年；影響：5萬人。",
            "包括醫療、教育、交通、托育、住宅五項服務。",
            "救災4大困難 地形險峻：道路中斷；水勢不穩：船艇難行；堰塞湖威脅：仍待監測；通訊受阻：回報延遲。",
        ]
        negatives = [
            "對象：青年；資格：設籍。",
            "- 甲\n- 乙\n- 丙\n- 丁\n- 戊\n- 己\n- 庚",
        ]
        self.assertTrue(all(self.select(text) == "icon_grid" for text in positives))
        self.assertTrue(all(self.select(text) != "icon_grid" for text in negatives))

    def test_feature_spread_has_positive_and_negative_examples(self):
        positives = [
            "台中凌晨發生死亡車禍，護理師過馬路時遭轎車撞擊，駕駛肇事後逃逸，警方調閱監視器追查並逮捕嫌犯。家屬要求釐清責任，檢警持續調查事故原因，附近店家也提供行車紀錄與監視畫面協助還原現場。",
            "金門一座寺廟發生神明金牌竊案，嫌犯凌晨進入廟內搜刮金牌後逃逸，警方到場發現沿途掉落的贓物，循線逮捕嫌犯，並在租屋處找回已被燒熔與輾壓的金牌，廟方後續清點損失並加強夜間巡查。",
        ]
        negatives = [
            "政府今天說明新措施。",
            "第一章：合約爭議。第二章：刑事責任。第三章：民事求償。第四章：後續監督。",
        ]
        self.assertTrue(all(self.select(text) == "feature_spread" for text in positives))
        self.assertTrue(all(self.select(text) != "feature_spread" for text in negatives))

    def test_feature_spread_is_not_a_renamed_card_stack(self):
        decision = info_layout.InfoLayoutDecision("feature_spread", "test")
        prompt = info_layout.structure_instruction(decision)
        self.assertIn("one dominant, concrete scene or subject", prompt)
        self.assertIn("different scale and width", prompt)
        self.assertIn("must look like an editorial feature composition", prompt)
        self.assertIn("do not align them into equal columns, rows, tiles, panels", prompt)

    def test_relaxation_keeps_known_false_positives_out(self):
        cases = [
            (
                "第一則：【現場篇】合約零容忍 vs. 檢方0.753%。第二則：【責任篇】作假日誌。第三則：【利益篇】追查款項。",
                "cards",
            ),
            (
                "川習會行程 07:00嘉賓入場 08:30致詞 12:00午宴 14:00記者會，各段均待白宮確認。",
                "cards",
            ),
            (
                "違反道路交通管理處罰條例第44條，處1200元以上6000元以下罰鍰；另依第63條記點。",
                "cards",
            ),
            (
                "美股三大指數收黑，市場預期Fed升息1碼，殖利率突破5%，油價維持高檔。您怎麼看今晚決策前盤勢與科技股表現？",
                "cards",
            ),
        ]
        for text, expected in cases:
            with self.subTest(text=text[:20]):
                self.assertEqual(self.select(text), expected)

    def test_cards_has_two_positive_and_two_negative_examples(self):
        positives = ["政府今天說明新措施。", "地方舉辦活動，民眾陸續到場。"]
        negatives = [
            "9月1日先封路，9月2日再開放。",
            "對象：青年；資格：設籍；金額：3萬元；上路：明年。",
        ]
        self.assertTrue(all(self.select(text) == "cards" for text in positives))
        self.assertTrue(all(self.select(text) != "cards" for text in negatives))

    def test_fixed_priority_prefers_timeline_over_other_evidence(self):
        text = "9月1日預算達120億元，9月2日涵蓋3縣市，最後有8萬人受惠。"
        self.assertEqual(self.select(text), "timeline")


class RepresentativeDistributionTests(unittest.TestCase):
    CASES = {
        "timeline": [
            "9月1日上午9時封閉道路，9月2日下午3時恢復通行，9月3日完成清理。",
            "首先查扣帳戶，接著通知被害人，隨後移送偵辦，最後由法院裁定。",
        ],
        "hero_number": [
            "市場拋售公債，美國10年期公債殖利率衝上4.78%，創下19個月新高。",
            "Apple台灣官網公布換電池要4490元，比前代貴340元，創歷代新高。",
        ],
        "annotated_subject": [
            "拓元售票系統回應登入異常，說明影響範圍並宣布修復計畫，完成後通知會員。",
            "尼泊爾崩塌冰川持續退縮，造成坡面失去支撐並帶來崩塌風險。",
        ],
        "icon_grid": [
            "救災4大困難 地形險峻：道路中斷；水勢不穩：船艇難行；堰塞湖：持續監測；通訊受阻：回報延遲。",
            "預估出貨分為基準情境、樂觀情境、保守情境三種方案。",
        ],
        "feature_spread": [
            "台中凌晨發生死亡車禍，護理師過馬路時遭轎車撞擊，駕駛肇事後逃逸，警方調閱監視器追查並逮捕嫌犯。家屬要求釐清責任，附近店家也提供行車紀錄與監視畫面協助還原現場，檢警持續調查事故原因與駕駛責任。",
            "德語網站遭大量AI代理人異常操作，研究人員發現帳號反覆改寫技術條目，平台已封鎖可疑帳號並回復內容，後續仍在清查受影響頁面與操作來源。網站管理員同步檢查編輯紀錄，避免錯誤資料再度出現。",
        ],
        "cards": [
            "第一章：合約爭議。第二章：刑事責任。第三章：民事求償。第四章：後續監督。",
            "兩案預算分別為120億元與80億元，只有一個量綱，無法形成完整雙方比較。",
        ],
    }

    def test_representative_backend_samples_keep_the_intended_distribution(self):
        actual = Counter()
        for expected, texts in self.CASES.items():
            for text in texts:
                decision = info_layout.select_info_layout(
                    text, "資訊卡", "simplified", "記者", "default", 4
                )
                with self.subTest(expected=expected, text=text[:20]):
                    self.assertEqual(decision.mode, expected)
                actual[decision.mode] += 1
        self.assertEqual(actual, Counter({mode: 2 for mode in self.CASES}))


class PromptInjectionTests(unittest.TestCase):
    CASES = {
        "timeline": "9月1日上午9時宣布，9月2日下午3時執行，9月3日完成。",
        "comparison": "台灣與日本相比，支持率45%與38%，席次30席與25席，台灣領先。",
        "hero_number": "預算達120億元，涵蓋3縣市、受惠8萬人、設置40站。",
        "annotated_subject": "市長陳美玲表示改革主張，提出方案並推動執行，最後完成協商。",
        "icon_grid": "對象：青年；資格：設籍；金額：3萬元；上路：明年；影響：5萬人。",
        "feature_spread": (
            "台中凌晨發生死亡車禍，護理師過馬路時遭轎車撞擊，駕駛肇事後逃逸，"
            "警方調閱監視器追查並逮捕嫌犯。家屬要求釐清責任，檢警持續調查事故原因，"
            "附近店家也提供行車紀錄與監視畫面協助還原現場。"
        ),
        "cards": "政府今天說明新措施。",
    }

    def prompt(self, text, **kwargs):
        defaults = dict(
            role="記者", density="simplified", type_label="資訊卡", news_text=text
        )
        defaults.update(kwargs)
        with patch.dict(os.environ, {"INFO_LAYOUT_MODE": "on"}, clear=False):
            return main.build_digest_instructions(**defaults)

    def test_every_mode_injects_its_structure_and_core_wording(self):
        fragments = {
            "timeline": "ordered nodes on one clear event path",
            "comparison": "exactly two opposing fields",
            "hero_number": "single selected main figure",
            "annotated_subject": "make the one subject the visual centre",
            "icon_grid": "three points form a triangle",
            "feature_spread": "one dominant, concrete scene or subject",
            "cards": "retain the current safe row/card behaviour",
        }
        for mode, text in self.CASES.items():
            with self.subTest(mode=mode):
                prompt = self.prompt(text)
                self.assertIn(f"selected {mode.upper()}", prompt)
                self.assertIn(fragments[mode], prompt)
                self.assertIn("`[內文小標]` 是內容單位，不是卡片邊界", prompt)

    def test_icon_grid_contains_all_fixed_geometries_and_unframed_permission(self):
        prompt = self.prompt(self.CASES["icon_grid"])
        for geometry in (
            "three points form a triangle",
            "four form a two-by-two grid",
            "five form a two-over-three arrangement",
            "six form a three-by-two grid",
            "may be unframed or use only local background colour",
        ):
            self.assertIn(geometry, prompt)

    def test_broadcast_uses_narrow_variants_and_removes_physical_card_wording(self):
        timeline = self.prompt(
            self.CASES["timeline"], role="編輯", editor_format="broadcast", hole_side="left"
        )
        self.assertIn("narrow vertical timeline", timeline)
        self.assertIn("right half under the headline", timeline)
        self.assertNotIn("stacked from top to bottom under the headline", timeline)
        self.assertNotIn("this format's card stack has", timeline)

        comparison = self.prompt(
            self.CASES["comparison"], role="編輯", editor_format="broadcast", hole_side="left"
        )
        self.assertIn("each shared dimension on one compact paired line", comparison)
        self.assertIn("if a clean paired line is impossible", comparison)

        feature = self.prompt(
            self.CASES["feature_spread"], role="編輯", editor_format="broadcast",
            hole_side="left",
        )
        self.assertIn("crop one strong scene or subject into the narrow content half", feature)
        self.assertIn("never convert the labels into a vertical stack of equal cards", feature)

    def test_verbatim_and_explicit_keep_wording_requests_do_not_enable_layout(self):
        with patch.dict(os.environ, {"INFO_LAYOUT_MODE": "on"}, clear=False):
            verbatim = main.build_digest_instructions(
                "記者", "verbatim", "資訊卡", news_text=self.CASES["timeline"]
            )
            explicit = main.build_digest_instructions(
                "記者", "simplified", "資訊卡", news_text=self.CASES["timeline"],
                user_instruction="這是完稿，請逐字保留",
            )
        self.assertNotIn("PROGRAM-SELECTED INFORMATION PRESENTATION MODE", verbatim)
        self.assertNotIn("PROGRAM-SELECTED INFORMATION PRESENTATION MODE", explicit)

    def test_environment_is_read_for_each_call(self):
        kwargs = dict(
            role="記者", density="simplified", type_label="資訊卡",
            news_text=self.CASES["timeline"],
        )
        with patch.dict(os.environ, {"INFO_LAYOUT_MODE": "off"}, clear=False):
            off = main.build_digest_instructions(**kwargs)
        with patch.dict(os.environ, {"INFO_LAYOUT_MODE": "on"}, clear=False):
            on = main.build_digest_instructions(**kwargs)
        self.assertNotIn("PROGRAM-SELECTED INFORMATION PRESENTATION MODE", off)
        self.assertIn("PROGRAM-SELECTED INFORMATION PRESENTATION MODE", on)


class OffCompatibilityTests(unittest.TestCase):
    def test_off_is_byte_for_byte_equal_to_pre_feature_fixtures(self):
        with patch.dict(os.environ, {"INFO_LAYOUT_MODE": "off"}, clear=False):
            for role, fixture_role in (("記者", "reporter"), ("編輯", "editor")):
                for density in ("standard", "simplified"):
                    for full_bleed in (True, False):
                        tag = "fullbleed" if full_bleed else "safearea"
                        name = f"{fixture_role}-digest-{density}-{tag}.txt"
                        with self.subTest(name=name):
                            expected = (FIXTURES / "info-layout-off" / name).read_text(
                                encoding="utf-8"
                            )
                            actual = main.build_digest_instructions(
                                role, density, "資料圖表", full_bleed=full_bleed
                            )
                            self.assertEqual(actual, expected)


class AuditTests(unittest.TestCase):
    def test_digest_archive_records_mode_and_rule(self):
        payload = {
            "style": "clean",
            "structure": "grid",
            "variable": (
                "[標題] 青年補助上路\n"
                "[內文小標] 對象 青年\n"
                "[內文小標] 資格 設籍\n"
                "[內文小標] 金額 <3萬元>\n"
                "[內文小標] 影響 <5萬人>"
            ),
            "visual_context": "青年申請補助的服務場景",
            "chart_type": "資料圖表",
            "portrait_subjects": [],
            "portrait_subjects_en": [],
            "portrait_subjects_en_guess": [],
            "map_places": [],
        }
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
            )]
        )
        archived = []
        req = main.GenerateRequest(
            news_text="對象：青年；資格：設籍；金額：3萬元；上路：明年；影響：5萬人。",
            type_label=main.AUTO_TYPE_LABEL,
            role="記者",
            density="simplified",
            stamp=False,
            seed=20260928,
        )
        with patch.dict(os.environ, {"INFO_LAYOUT_MODE": "on"}, clear=False), \
             patch.object(main, "digest_completion", return_value=response), \
             patch.object(main, "_archive_generation", side_effect=lambda **kw: archived.append(kw)), \
             patch.object(main.request_log, "log_generation"), \
             patch.object(main, "_remember_digest"):
            result = main.generate(req)
        self.assertEqual(result.info_layout_mode, "icon_grid")
        self.assertIn("規則五", result.info_layout_rule)
        self.assertEqual(archived[0]["info_layout_mode"], "icon_grid")
        self.assertEqual(archived[0]["info_layout_rule"], result.info_layout_rule)


if __name__ == "__main__":
    unittest.main()
