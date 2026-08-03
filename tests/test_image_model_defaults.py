"""生圖模型預設值與 aspect_ratio 防呼差（2026-08-01 清查後補上）。

背景：OpenRouter 與原生兩條路徑原本預設不同的 GPT 模型，而 payload 帶了模型不支援的
aspect_ratio 時 OpenRouter 靜靜忽略、不報錯——安全框要 21:9 卻拿回 3:2，查了整晚。
這組測試釘住兩件事：兩條路徑是同一個模型、做不到的比例一定當場失敗。
"""

import base64
import io
import os
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from main import ImageGenerateRequest, ImageGenerateResponse  # noqa: E402
from PIL import Image  # noqa: E402


def image_response(size: tuple[int, int], model: str = "openai/gpt-image-2") -> ImageGenerateResponse:
    """做一張指定尺寸的假成圖，用來驗「量成圖比例」這道關卡。"""
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buffer, format="PNG")
    return ImageGenerateResponse(
        image_data_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
        mime_type="image/png",
        model=model,
    )


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


class OutputAspectRatioTests(unittest.TestCase):
    """量成圖比例：擋「宣告支援卻回別的尺寸」這種間歇性降級（2026-08-01 實際發生過）。"""

    def test_matching_ratio_passes(self):
        main.verify_output_aspect_ratio(image_response((1792, 768)), "21:9")

    def test_small_deviation_is_tolerated(self):
        """模型不保證小數點精確，1808x768=2.354 只差 0.9%，不該擋。"""
        main.verify_output_aspect_ratio(image_response((1808, 768)), "21:9")

    def test_three_by_two_when_twentyone_by_nine_was_requested_fails(self):
        """8/1 實際拿回的就是這個尺寸，當時沒有任何機制發現。"""
        with self.assertRaises(HTTPException) as ctx:
            main.verify_output_aspect_ratio(image_response((1536, 1024)), "21:9")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("1536x1024", ctx.exception.detail)

    def test_auto_has_no_target_to_verify(self):
        main.verify_output_aspect_ratio(image_response((1536, 1024)), "auto")

    def test_parse_aspect_ratio_handles_bad_input(self):
        self.assertIsNone(main.parse_aspect_ratio("auto"))
        self.assertIsNone(main.parse_aspect_ratio(""))
        self.assertIsNone(main.parse_aspect_ratio("21:0"))
        self.assertAlmostEqual(main.parse_aspect_ratio("21:9"), 21 / 9)

    def test_unreadable_image_fails_instead_of_passing_silently(self):
        broken = ImageGenerateResponse(
            image_data_base64="bm90LWFuLWltYWdl", mime_type="image/png", model="m"
        )
        with self.assertRaises(HTTPException):
            main.verify_output_aspect_ratio(broken, "21:9")

    def test_check_runs_before_framing_and_covers_every_provider(self):
        """置框會把畫布改成 1920x1080，驗證必須在那之前；且不分 provider 都要驗。"""
        for provider in ("gpt", "gemini"):
            with self.subTest(provider=provider):
                with patch.object(main, "generate_image_raw", return_value=image_response((1536, 1024))):
                    with patch.object(main, "frame_image_response") as framed:
                        with self.assertRaises(HTTPException):
                            main.generate_image(
                                ImageGenerateRequest(
                                    prompt="p",
                                    provider=provider,
                                    aspect_ratio="21:9",
                                    safe_frame=True,
                                )
                            )
                        framed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
