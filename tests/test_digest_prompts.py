import os
import unittest

from pydantic import ValidationError

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import (  # noqa: E402
    AUTO_TYPE_LABEL,
    CHART_TYPE_CHOICES,
    DIGEST_OUTPUT_SCHEMA,
    GenerateRequest,
    GenerateResponse,
    ImageGenerateRequest,
    ImageGenerateResponse,
    build_digest_instructions,
    generate_image,
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
        # 不能只斷言「SIMPLIFIED MODE OVERRIDE」字樣不存在——USER_INSTRUCTION_RULES
        # 的逐字模式明文引用它宣告優先序（每種模式都在）。改斷言簡化區塊
        # 本身的獨特條款沒被注入。
        self.assertNotIn("dynamically select only 1 to 3 key points", prompt)
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


class ImageBackendRoutingTests(unittest.TestCase):
    """驗證 backend 開關與模型對應，不呼叫任何付費 API。"""

    @staticmethod
    def fake_image(model):
        """假成圖要是真的能解析的 16:9 圖——generate_image 現在會量成圖比例，
        隨手塞 'x' 會被那道關卡以 502 擋下，測不到路由本身。"""
        import base64
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (1280, 720), (0, 0, 0)).save(buffer, format="PNG")
        return ImageGenerateResponse(
            image_data_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
            mime_type="image/png",
            model=model,
        )

    def setUp(self):
        # 攔截真正的 OpenRouter / 原生呼叫，只記錄被指派的模型
        self.calls = {}

        def fake_openrouter(model, req):
            self.calls["openrouter"] = model
            return self.fake_image(model)

        def fake_gpt(req):
            self.calls["native"] = "gpt"
            return self.fake_image("native-gpt")

        def fake_gemini(req):
            self.calls["native"] = "gemini"
            return self.fake_image("native-gemini")

        self._orig = (main.generate_via_openrouter, main.generate_gpt_image, main.generate_gemini_image)
        main.generate_via_openrouter = fake_openrouter
        main.generate_gpt_image = fake_gpt
        main.generate_gemini_image = fake_gemini
        self._saved_env = {k: os.environ.get(k) for k in
                           ("IMAGE_BACKEND", "OPENROUTER_API_KEY", "OPENROUTER_GPT_MODEL", "OPENROUTER_GEMINI_MODEL")}

    def tearDown(self):
        main.generate_via_openrouter, main.generate_gpt_image, main.generate_gemini_image = self._orig
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _run(self, provider):
        return generate_image(ImageGenerateRequest(prompt="p", provider=provider))

    def test_openrouter_backend_maps_gpt_to_gpt_image_2(self):
        os.environ["IMAGE_BACKEND"] = "openrouter"
        os.environ["OPENROUTER_API_KEY"] = "test-or-key"
        os.environ.pop("OPENROUTER_GPT_MODEL", None)
        self._run("gpt")
        self.assertEqual(self.calls.get("openrouter"), "openai/gpt-image-2")

    def test_openrouter_backend_maps_gemini_to_pro(self):
        os.environ["IMAGE_BACKEND"] = "openrouter"
        os.environ["OPENROUTER_API_KEY"] = "test-or-key"
        os.environ.pop("OPENROUTER_GEMINI_MODEL", None)
        self._run("gemini")
        self.assertEqual(self.calls.get("openrouter"), "google/gemini-3-pro-image")

    def test_native_backend_bypasses_openrouter(self):
        os.environ["IMAGE_BACKEND"] = "native"
        os.environ["OPENROUTER_API_KEY"] = "test-or-key"
        self._run("gpt")
        self.assertNotIn("openrouter", self.calls)
        self.assertEqual(self.calls.get("native"), "gpt")

    def test_openrouter_without_key_falls_back_to_native(self):
        os.environ["IMAGE_BACKEND"] = "openrouter"
        os.environ.pop("OPENROUTER_API_KEY", None)
        self._run("gemini")
        self.assertNotIn("openrouter", self.calls)
        self.assertEqual(self.calls.get("native"), "gemini")


if __name__ == "__main__":
    unittest.main()
