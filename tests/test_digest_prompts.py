import os
import unittest

from pydantic import ValidationError

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import (  # noqa: E402
    GenerateRequest,
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

    def test_image_request_defaults_to_1k(self):
        request = ImageGenerateRequest(prompt="test")
        self.assertEqual(request.image_size, "1K")


if __name__ == "__main__":
    unittest.main()
