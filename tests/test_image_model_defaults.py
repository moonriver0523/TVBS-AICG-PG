"""生圖模型預設值與 aspect_ratio 防呼差（2026-08-01 清查後補上）。

背景：OpenRouter 與原生兩條路徑原本預設不同的 GPT 模型，而 payload 帶了模型不支援的
aspect_ratio 時 OpenRouter 靜靜忽略、不報錯——安全框要 21:9 卻拿回 3:2，查了整晚。
這組測試釘住兩件事：兩條路徑是同一個模型、做不到的比例一定當場失敗。
"""

import os
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from main import ImageGenerateRequest  # noqa: E402


class ModelDefaultsTests(unittest.TestCase):
    def test_both_transports_use_the_same_gpt_model(self):
        """切 IMAGE_BACKEND 不可以連模型一起換掉。"""
        self.assertEqual(
            main.OPENROUTER_GPT_IMAGE_MODEL, f"openai/{main.NATIVE_GPT_IMAGE_MODEL}"
        )

    def test_both_transports_use_the_same_gemini_model(self):
        self.assertEqual(
            main.OPENROUTER_GEMINI_IMAGE_MODEL, f"google/{main.NATIVE_GEMINI_IMAGE_MODEL}"
        )

    def test_default_gpt_model_can_actually_do_the_safe_frame_ratio(self):
        """安全框是 21:9，預設模型做不到的話整條流程的前提就不成立。"""
        self.assertIn(
            main.SAFE_FRAME_ASPECT_RATIO,
            main.MODEL_ASPECT_RATIOS[main.OPENROUTER_GPT_IMAGE_MODEL],
        )
        self.assertIn(
            main.SAFE_FRAME_ASPECT_RATIO,
            main.MODEL_ASPECT_RATIOS[main.OPENROUTER_GEMINI_IMAGE_MODEL],
        )


class AspectRatioGuardTests(unittest.TestCase):
    def setUp(self):
        # 放行開關必須是乾淨的，否則擋不擋得住測不出來
        patcher = patch.dict(os.environ, {"ALLOW_UNSUPPORTED_ASPECT_RATIO": ""}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_model_without_aspect_ratio_parameter_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            main.assert_aspect_ratio_supported("openai/gpt-5.4-image-2", "21:9")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("21:9", ctx.exception.detail)

    def test_model_with_narrower_enum_is_rejected(self):
        with self.assertRaises(HTTPException):
            main.assert_aspect_ratio_supported("openai/gpt-image-1", "21:9")

    def test_supported_ratio_passes(self):
        main.assert_aspect_ratio_supported("openai/gpt-image-2", "21:9")
        main.assert_aspect_ratio_supported("google/gemini-3-pro-image", "16:9")

    def test_unknown_model_is_warned_but_not_blocked(self):
        """表上沒有不等於不支援，擋下來會誤傷新模型。"""
        main.assert_aspect_ratio_supported("some-vendor/brand-new-image", "21:9")

    def test_env_escape_hatch_allows_unsupported_ratio(self):
        with patch.dict(os.environ, {"ALLOW_UNSUPPORTED_ASPECT_RATIO": "1"}, clear=False):
            main.assert_aspect_ratio_supported("openai/gpt-5.4-image-2", "21:9")

    def test_openrouter_call_fails_before_spending_money(self):
        """擋要擋在送出之前——生圖是付費的，送出去才發現就來不及了。"""

        def exploding_urlopen(*args, **kwargs):
            raise AssertionError("不支援的比例不該真的送出請求")

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}, clear=False):
            with patch.object(main, "urlopen", exploding_urlopen):
                with self.assertRaises(HTTPException):
                    main.generate_via_openrouter(
                        "openai/gpt-5.4-image-2",
                        ImageGenerateRequest(prompt="p", aspect_ratio="21:9"),
                    )


class NativeGptSizeTests(unittest.TestCase):
    def test_sizes_match_their_declared_ratio(self):
        for ratio, size in main.NATIVE_GPT_IMAGE_SIZES.items():
            with self.subTest(ratio=ratio):
                width, height = (int(v) for v in size.split("x"))
                w_ratio, h_ratio = (int(v) for v in ratio.split(":"))
                self.assertEqual(Fraction(width, height), Fraction(w_ratio, h_ratio))

    def test_sizes_are_multiples_of_16(self):
        """gpt-image-2 只接受 16 的倍數。"""
        for ratio, size in main.NATIVE_GPT_IMAGE_SIZES.items():
            with self.subTest(ratio=ratio):
                width, height = (int(v) for v in size.split("x"))
                self.assertEqual((width % 16, height % 16), (0, 0))
                self.assertLessEqual(max(width, height), 2560)

    def test_safe_frame_ratio_is_available_natively(self):
        self.assertIn(main.SAFE_FRAME_ASPECT_RATIO, main.NATIVE_GPT_IMAGE_SIZES)

    def test_requested_ratio_reaches_the_api_instead_of_a_hardcoded_size(self):
        captured = {}

        class FakeImages:
            def generate(self, **kwargs):
                captured.update(kwargs)
                raise HTTPException(status_code=599, detail="stop here")

        class FakeClient:
            images = FakeImages()

        with patch.object(main, "openai_client", FakeClient()):
            with self.assertRaises(HTTPException):
                main.generate_gpt_image(ImageGenerateRequest(prompt="p", aspect_ratio="21:9"))
        self.assertEqual(captured.get("size"), "1680x720")

    def test_unmappable_ratio_fails_loudly(self):
        with self.assertRaises(HTTPException) as ctx:
            main.generate_gpt_image(ImageGenerateRequest(prompt="p", aspect_ratio="5:4"))
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
