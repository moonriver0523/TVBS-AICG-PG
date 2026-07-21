import os
import unittest

from pydantic import ValidationError

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import (  # noqa: E402
    AUTO_TYPE_LABEL,
    CHART_TYPE_CHOICES,
    DIGEST_OUTPUT_SCHEMA,
    GenerateRequest,
    GenerateResponse,
    ImageGenerateRequest,
    build_digest_instructions,
)


class DigestPromptTests(unittest.TestCase):
    def test_density_defaults_to_standard(self):
        request = GenerateRequest(news_text="素材", type_label="資料圖表")
        self.assertEqual(request.density, "standard")

    def test_invalid_density_is_rejected(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                news_text="素材",
                type_label="資料圖表",
                density="verbose",
            )

    def test_reporter_standard_does_not_include_simplified_override(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertNotIn("SIMPLIFIED MODE OVERRIDE", prompt)
        self.assertIn("The current chart type is", prompt)

    def test_reporter_simplified_includes_focus_rules(self):
        prompt = build_digest_instructions("記者", "simplified", "資料圖表")
        self.assertIn("SIMPLIFIED MODE OVERRIDE", prompt)
        self.assertIn("dynamically select only 1 to 3 key points", prompt)
        self.assertIn("ONE dominant visual focus", prompt)
        self.assertIn("do not force three points", prompt.lower())

    def test_editor_simplified_makes_stamp_optional(self):
        prompt = build_digest_instructions("編輯", "simplified", "資料圖表")
        self.assertIn("ignore the earlier 150-180 character target", prompt)
        self.assertIn("<蓋章> is optional", prompt)
        self.assertIn("counts as one of the maximum three points", prompt)

    def test_specified_type_pins_chart_type_and_has_no_auto_rules(self):
        prompt = build_digest_instructions("記者", "standard", "地圖／位置")
        self.assertIn('The "chart_type" field MUST be exactly "地圖／位置"', prompt)
        self.assertNotIn("CHART TYPE AUTO-SELECTION", prompt)
        # 指定類型時，類型字樣要真的出現在設計指令裡
        self.assertIn('The current chart type is: "地圖／位置"', prompt)

    def test_auto_type_adds_selection_rules_with_all_four_choices(self):
        prompt = build_digest_instructions("記者", "standard", AUTO_TYPE_LABEL)
        self.assertIn("CHART TYPE AUTO-SELECTION", prompt)
        for choice in CHART_TYPE_CHOICES:
            self.assertIn(choice, prompt)
        # 不可把 sentinel 當成真的類型名稱塞進指令
        self.assertNotIn('The current chart type is: "自動判斷"', prompt)
        self.assertNotIn('MUST be exactly "自動判斷"', prompt)

    def test_auto_type_works_for_editor_role_too(self):
        prompt = build_digest_instructions("編輯", "simplified", AUTO_TYPE_LABEL)
        self.assertIn("CHART TYPE AUTO-SELECTION", prompt)
        self.assertIn("SIMPLIFIED MODE OVERRIDE", prompt)
        self.assertNotIn("圖表類型：自動判斷", prompt)

    def test_schema_requires_chart_type_restricted_to_known_choices(self):
        self.assertIn("chart_type", DIGEST_OUTPUT_SCHEMA["required"])
        self.assertEqual(
            DIGEST_OUTPUT_SCHEMA["properties"]["chart_type"]["enum"],
            CHART_TYPE_CHOICES,
        )

    def test_generate_response_chart_type_is_optional(self):
        response = GenerateResponse(style="s", structure="t", variable="v")
        self.assertEqual(response.chart_type, "")

    def test_image_request_defaults_to_1k(self):
        request = ImageGenerateRequest(prompt="test")
        self.assertEqual(request.image_size, "1K")


if __name__ == "__main__":
    unittest.main()
