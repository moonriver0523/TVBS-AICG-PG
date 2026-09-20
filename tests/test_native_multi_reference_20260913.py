"""原生 GPT 路徑也送得出多張參考圖（2026-09-13）。

2026-09-10 起 generate_gpt_image 有參考圖就走 images.edit，_native_reference_files 送整個
陣列；supports_multiple_reference_images 卻仍只認 OpenRouter，本機切 IMAGE_BACKEND=openai
後任何 AI改圖／實景參考直接 400。原生 Gemini 仍只送單張，維持擋。
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402


class NativeMultiReference(unittest.TestCase):
    def test_openrouter_without_key_falls_back_to_native_gpt(self):
        """沒有 key 時 generate_image_raw 走原生，GPT 仍送得出陣列（2026-09-16 更正）。

        原本這裡釘的是 False——那是把「OpenRouter 不能用」誤當成「送不出參考圖」。
        原生 GPT 走 images.edit 一樣送得出去，Gemini 才是真的只送得出單張。
        """
        with patch.dict(os.environ, {"IMAGE_BACKEND": "openrouter", "OPENROUTER_API_KEY": "k"}):
            self.assertTrue(main.supports_multiple_reference_images("gpt"))
        with patch.dict(os.environ, {"IMAGE_BACKEND": "openrouter", "OPENROUTER_API_KEY": ""}):
            self.assertTrue(main.supports_multiple_reference_images("gpt"))
            self.assertFalse(main.supports_multiple_reference_images("gemini"))

    def test_native_gpt_allowed(self):
        """兩種拼法都要算原生（2026-09-16 B65：dev-local-openai.sh 用的是 native）。"""
        for backend in ("openai", "native"):
            with self.subTest(backend=backend):
                with patch.dict(os.environ, {"IMAGE_BACKEND": backend, "OPENROUTER_API_KEY": ""}):
                    self.assertTrue(main.supports_multiple_reference_images("gpt"))
                    self.assertTrue(main.supports_multiple_reference_images())  # 舊呼叫端不帶 provider

    def test_native_gemini_still_blocked(self):
        for backend in ("openai", "native"):
            with self.subTest(backend=backend):
                with patch.dict(os.environ, {"IMAGE_BACKEND": backend, "OPENROUTER_API_KEY": ""}):
                    self.assertFalse(main.supports_multiple_reference_images("gemini"))

    def test_apply_references_passes_on_native_gpt(self):
        req = main.ImageGenerateRequest(
            prompt="x", provider="gpt",
            reference_images=[main.UserReferenceImage(data_url="data:image/png;base64,AAAA", purpose="aiedit")],
        )
        with patch.dict(os.environ, {"IMAGE_BACKEND": "openai", "OPENROUTER_API_KEY": ""}):
            out = main.apply_user_references_to_image_request(req)
        self.assertIn("REDRAW THIS SAME PICTURE", out.prompt)


if __name__ == "__main__":
    unittest.main()
