"""地圖準確性規則：條件注入、豁免範圍、與既有禁令的共存。

豁免的自洽性靠三條護欄釘住：
1. 畫布幾何禁數字句在同一份 prompt 內原封不動（豁免只涵蓋真實世界地理）；
2. 座標永不印成可見標籤（「數字被畫進圖」的病灶保持關閉）；
3. CONTENT_FIDELITY_RULES 常數一字未改（使用者指示本輪不動它，另案檢視）。
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
            for density in ("standard", "simplified"):
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


class ContentFidelityUntouchedTests(unittest.TestCase):
    """使用者指示本輪不修改 CONTENT_FIDELITY_RULES 的機械保證。"""

    def test_constant_starts_and_ends_as_before(self):
        rules = main.CONTENT_FIDELITY_RULES
        self.assertTrue(rules.startswith("\n\nCONTENT FIDELITY (NON-NEGOTIABLE"))
        self.assertIn("6. EXCEPTION", rules)

    def test_constant_has_exactly_six_numbered_rules(self):
        rules = main.CONTENT_FIDELITY_RULES
        numbers = [f"\n{i}." for i in range(1, 8)]
        present = [n for n in numbers if n in rules]
        self.assertEqual(present, [f"\n{i}." for i in range(1, 7)])


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


if __name__ == "__main__":
    unittest.main()
