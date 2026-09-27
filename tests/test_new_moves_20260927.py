"""2026-09-27：十五個非方向性創意元素正式入池。"""
from fractions import Fraction
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import creativity  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402


EXPECTED_IDS = (
    "detail_sidebar",
    "duotone_subject_separation",
    "frosted_data_panel",
    "timeline_bead_chain",
    "depth_card_shelf",
    "diagonal_light_focus",
    "newspaper_halftone",
    "folder_index_tabs",
    "contact_sheet",
    "negative_space_aperture",
    "selective_depth_of_field",
    "signal_glitch_edge",
    "concentric_impact_rings",
    "proportion_block_wall",
    "motion_echo_slices",
)


class PoolAndProbabilityTests(unittest.TestCase):
    def test_all_fifteen_ids_are_in_one_fixed_unique_pool(self):
        ids = tuple(key for key, _text in creativity.NON_DIRECTIONAL_ELEMENT_POOL)
        self.assertEqual(ids, EXPECTED_IDS)
        self.assertEqual(len(ids), 15)
        self.assertEqual(len(set(ids)), 15)

    def test_ui_level_probability_table_is_exact(self):
        """每一舊招與每一新元素的最終入選率；UI 1–5 對應內部 0–4。"""
        expected = {
            # old count, gate, each old item, each new item, expected new share
            1: (0, Fraction(0), Fraction(0), Fraction(0), Fraction(0)),
            2: (0, Fraction(0), Fraction(0), Fraction(0), Fraction(0)),
            3: (1, Fraction(1, 3), Fraction(2, 27), Fraction(1, 45), Fraction(1, 3)),
            4: (2, Fraction(1, 2), Fraction(1, 6), Fraction(1, 30), Fraction(1, 4)),
            5: (3, Fraction(2, 3), Fraction(7, 27), Fraction(2, 45), Fraction(2, 9)),
        }
        for ui_level, values in expected.items():
            old_count, gate, old_probability, new_probability, new_share = values
            level = ui_level - 1
            with self.subTest(ui_level=ui_level):
                self.assertEqual(creativity.COVER_ACCESSORY_COUNTS[level], old_count)
                numerator, denominator = creativity.NON_DIRECTIONAL_ELEMENT_GATE[level]
                self.assertEqual(Fraction(numerator, denominator), gate)
                calculated_old = Fraction(old_count, 9) - gate * Fraction(1, 9)
                calculated_new = gate * Fraction(1, 15)
                calculated_share = gate / old_count if old_count else Fraction(0)
                self.assertEqual(calculated_old, old_probability)
                self.assertEqual(calculated_new, new_probability)
                self.assertEqual(calculated_share, new_share)

    def test_new_pool_never_outnumbers_the_old_pool(self):
        for level in range(5):
            with self.subTest(level=level):
                numerator, denominator = creativity.NON_DIRECTIONAL_ELEMENT_GATE[level]
                gate = Fraction(numerator, denominator)
                old_count = creativity.COVER_ACCESSORY_COUNTS[level]
                expected_old_slots = Fraction(old_count) - gate
                self.assertLessEqual(gate, expected_old_slots)

    def test_output_count_keeps_the_existing_ladder(self):
        for level in range(5):
            with self.subTest(level=level):
                self.assertEqual(
                    len(creativity.accessories(level, seed=20260927, direction_context="靜態產品發表")),
                    creativity.COVER_ACCESSORY_COUNTS[level],
                )

    def test_every_new_element_explicitly_bans_new_writing_and_logo(self):
        for key, text in creativity.NON_DIRECTIONAL_ELEMENT_POOL:
            with self.subTest(key=key):
                self.assertIn("text, digits or Logo", text)


class StrengthenedCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = dict(creativity.NON_DIRECTIONAL_ELEMENT_POOL)

    def test_the_seven_weak_trials_now_name_visible_features(self):
        required = {
            "duotone_subject_separation": ("UNMISTAKABLE", "strongly contrasting", "crisp visible boundary"),
            "frosted_data_panel": ("CLEARLY VISIBLE", "milky translucent blur", "area outside stays sharp"),
            "depth_card_shelf": ("largest and razor-sharp", "partly occluded", "progressively softer"),
            "diagonal_light_focus": ("HIGH-CONTRAST", "entering from one side", "brightest core"),
            "folder_index_tabs": ("protruding", "folder lips", "layered paper edges"),
            "contact_sheet": ("wide, medium and detail crops", "distinct film-like frame", "consistent gutters"),
            "signal_glitch_edge": ("broken scan lines", "channel splitting", "digital tears"),
        }
        for key, phrases in required.items():
            with self.subTest(key=key):
                for phrase in phrases:
                    self.assertIn(phrase, self.pool[key])

    def test_contact_sheet_no_longer_requires_multiple_source_images(self):
        text = self.pool["contact_sheet"]
        self.assertIn("photograph or photographs", text)
        self.assertIn("Different crops of one source", text)
        self.assertNotIn("distinct genuine photographs", text)

    def test_rings_are_only_abstract_geometry_and_never_anchor_a_contour(self):
        text = self.pool["concentric_impact_rings"]
        self.assertIn("ONLY ABSTRACT, PERFECTLY GEOMETRIC CONCENTRIC CIRCLES", text)
        self.assertNotIn("outline", text.lower())
        for forbidden_subject in ("country", "island", "coast", "region", "territory", "landmass"):
            with self.subTest(subject=forbidden_subject):
                self.assertIn(forbidden_subject, text.lower())


class ConditionalElementTests(unittest.TestCase):
    def _condition(self, key: str, content: str, type_label: str = "") -> str:
        text = dict(creativity.NON_DIRECTIONAL_ELEMENT_POOL)[key]
        return creativity.condition_non_directional_element(
            key, text, content_context=content, type_label=type_label
        )

    def assertEligible(self, key: str, content: str, type_label: str = "") -> None:
        self.assertEqual(
            self._condition(key, content, type_label),
            dict(creativity.NON_DIRECTIONAL_ELEMENT_POOL)[key],
        )

    def assertIneligible(self, key: str, content: str, type_label: str = "") -> None:
        self.assertEqual(
            self._condition(key, content, type_label),
            creativity.NON_DIRECTIONAL_CONDITION_FALLBACK,
        )

    def test_timeline_positive_and_negative_examples(self):
        for content in (
            "二月先盤點，四月檢核，六月上路",
            "地方先初審，再送中央複核",
            "The first stage is followed by a June review",
        ):
            self.assertEligible("timeline_bead_chain", content)
        self.assertIneligible("timeline_bead_chain", "市府公布三款新產品")

    def test_proportion_positive_and_negative_examples(self):
        for content in (
            "公共運輸占40%，人行改善占30%",
            "公共運輸占四成，自行車占三成，道路占兩成",
            "甲案100人、乙案200人",
        ):
            self.assertEligible("proportion_block_wall", content)
        self.assertIneligible("proportion_block_wall", "活動在2026年9月舉行")
        self.assertIneligible("proportion_block_wall", "基地面積三千坪")

    def test_rings_positive_and_negative_examples(self):
        self.assertEligible("concentric_impact_rings", "東部近海地震，最大震度四級")
        self.assertEligible("concentric_impact_rings", "污染影響範圍半徑三公里")
        self.assertIneligible("concentric_impact_rings", "介紹臺灣東部海岸風景")

    def test_motion_positive_and_negative_examples(self):
        self.assertEligible("motion_echo_slices", "第四棒彎道加速衝刺並超越兩隊")
        self.assertEligible("motion_echo_slices", "球員射門得分", "運動")
        self.assertIneligible("motion_echo_slices", "市府公布明年度交通預算")

    def test_missing_context_is_a_deterministic_same_slot_fallback(self):
        for key in creativity._NON_DIRECTIONAL_ELIGIBILITY:
            with self.subTest(key=key):
                self.assertIneligible(key, "")

    def test_contact_sheet_has_no_multi_image_gate(self):
        self.assertNotIn("contact_sheet", creativity._NON_DIRECTIONAL_ELIGIBILITY)
        self.assertEligible("contact_sheet", "只有一張現場照片")


class SharedPathAndCompatibilityTests(unittest.TestCase):
    @staticmethod
    def _contains_new_element(output: str) -> bool:
        candidates = (
            *(text for _key, text in creativity.NON_DIRECTIONAL_ELEMENT_POOL),
            creativity.NON_DIRECTIONAL_CONDITION_FALLBACK,
        )
        return any(text in output for text in candidates)

    def test_general_cg_broadcast_ten_and_yt_all_draw_from_the_new_pool(self):
        context = "市府公布靜態產品"
        builders = {
            "general": lambda seed: main.build_digest_instructions(
                "編輯", "simplified", "資料圖表", visual_creativity=3,
                seed=seed, direction_context=context,
            ),
            "broadcast": lambda seed: main.build_digest_instructions(
                "編輯", "simplified", "資料圖表", editor_format="broadcast",
                visual_creativity=3, seed=seed, direction_context=context,
            ),
            "ten": lambda seed: editor_formats.cover_design_brief(
                3, titles=("標題",), seed=seed, direction_context=context,
            ),
            "yt": lambda seed: editor_formats.yt_design_brief(
                3, lines=("標題", "副標"), seed=seed, direction_context=context,
            ),
        }
        for name, builder in builders.items():
            with self.subTest(path=name):
                outputs = [builder(seed) for seed in range(60)]
                self.assertTrue(any(self._contains_new_element(output) for output in outputs))

    def test_b55_layer_mode_still_disables_both_pools(self):
        for brief in (
            editor_formats.cover_design_brief(4, titles=("標題",), seed=7, layer_mode=True),
            editor_formats.yt_design_brief(4, lines=("標題", "副標"), seed=7, layer_mode=True),
        ):
            self.assertNotIn("supporting artwork", brief)
            for _key, text in creativity.NON_DIRECTIONAL_ELEMENT_POOL:
                self.assertNotIn(text, brief)

    def test_b114_arrow_replacement_does_not_change_the_new_slot(self):
        unconditional = {
            text for key, text in creativity.NON_DIRECTIONAL_ELEMENT_POOL
            if key not in creativity._NON_DIRECTIONAL_ELIGIBILITY
        }
        found = False
        for seed in range(500):
            eligible = creativity.accessories(4, seed=seed, direction_context="營收年增兩成")
            ineligible = creativity.accessories(4, seed=seed, direction_context="公司公布產品")
            new_in_eligible = [text for text in eligible if text in unconditional]
            new_in_ineligible = [text for text in ineligible if text in unconditional]
            if new_in_eligible and new_in_eligible == new_in_ineligible:
                if eligible != ineligible:
                    found = True
                    break
        self.assertTrue(found, "應找到箭頭換字、但第二池同槽內容不變的 seed")


if __name__ == "__main__":
    unittest.main()
