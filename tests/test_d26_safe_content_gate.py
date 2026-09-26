"""D26（2026-09-26 使用者裁決）：記者＋安全框 ON 的「延伸背景」模式。

- 守門：文字偵測框全在記者安全框內才算合格；無法確認一律不合格
- 不合格（2026-09-26 使用者改裁）：圖照常交付＋「警告：超出安全框」通知，不退回置框、不重生
- 勾選後一律 2K（使用者裁決），交付 2560×1440
- 只開給記者＋安全框 ON；預設空字串時所有路徑與改動前相同
- 4 張真實生成圖回放（tests/fixtures/d26/）
"""

import base64
import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
import news_prompt  # noqa: E402
import safe_area_spec  # noqa: E402
import safe_content_gate  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "d26"


def fixed_detector(boxes):
    return lambda image: list(boxes)


class GateRulesTests(unittest.TestCase):
    CANVAS = (1920, 1080)  # 記者安全框 (140,109)-(1774,860)

    def check(self, boxes, **kw):
        image = Image.new("RGB", self.CANVAS)
        return safe_content_gate.check_text_inside_safe_area(
            image, detector=fixed_detector(boxes), **kw
        )

    def test_all_boxes_inside_passes(self):
        self.assertTrue(self.check([(200, 200, 900, 300), (150, 700, 1700, 850)]).passed)

    def test_box_crossing_any_edge_fails(self):
        for box in [(130, 200, 900, 300), (200, 100, 900, 300),
                    (200, 200, 1780, 300), (200, 800, 900, 870)]:
            with self.subTest(box=box):
                result = self.check([(200, 200, 900, 300), box])
                self.assertFalse(result.passed)
                self.assertEqual(result.outside, [box])

    def test_no_text_is_unverifiable_unless_no_text_density(self):
        self.assertFalse(self.check([]).passed)
        self.assertTrue(self.check([], allow_no_text=True).passed)

    def test_detector_exception_fails(self):
        def boom(image):
            raise RuntimeError("onnx missing")

        image = Image.new("RGB", self.CANVAS)
        result = safe_content_gate.check_text_inside_safe_area(image, detector=boom)
        self.assertFalse(result.passed)
        self.assertIn("RuntimeError", result.reason)

    def test_rect_scales_with_2k_canvas(self):
        image = Image.new("RGB", (2560, 1440))
        result = safe_content_gate.check_text_inside_safe_area(
            image, detector=fixed_detector([(300, 300, 2000, 1000)])
        )
        self.assertEqual(result.rect, safe_area_spec.safe_rect(2560, 1440))
        self.assertTrue(result.passed)


class RealImageReplayTests(unittest.TestCase):
    """真實生成圖：T1／T2／字多記者（文字都在框內）與編輯實驗（標題、底部橫幅出框）。"""

    def test_replay(self):
        for path in sorted(FIXTURES.glob("*.jpg")):
            with self.subTest(image=path.name):
                result = safe_content_gate.check_text_inside_safe_area(Image.open(path))
                self.assertEqual(result.passed, path.stem.endswith("_pass"), result.reason)

    def test_fixture_set_is_complete(self):
        self.assertEqual(len(list(FIXTURES.glob("*_pass.jpg"))), 3)
        self.assertEqual(len(list(FIXTURES.glob("*_fail.jpg"))), 1)


def png_response(size, color=(20, 40, 90)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return main.ImageGenerateResponse(
        image_data_base64=base64.b64encode(buffer.getvalue()).decode(),
        mime_type="image/png",
        model="test",
    )


def decoded_size(b64):
    return Image.open(io.BytesIO(base64.b64decode(b64))).size


class FinalizeModelExtensionTests(unittest.TestCase):
    def setUp(self):
        main.reset_portrait_notices()

    def run_finalize(self, boxes, size=(2560, 1440)):
        with patch.object(
            safe_content_gate, "detect_text_boxes", side_effect=lambda img: list(boxes)
        ):
            return main.finalize_model_extension(
                png_response(size), aspect_ratio="16:9", canvas=(2560, 1440)
            )

    def test_pass_delivers_model_image_at_canvas_size(self):
        result = self.run_finalize([(400, 300, 2000, 1000)], size=(2752, 1548))
        self.assertEqual(decoded_size(result.image_data_base64), (2560, 1440))
        # 追加修改要拿模型原圖
        self.assertEqual(decoded_size(result.source_image_base64), (2752, 1548))
        self.assertEqual(main.collected_portrait_notices(), [])

    def test_fail_still_delivers_model_image_with_warning(self):
        """使用者：「不要退回置框 還是生圖給使用者 但訊息跳出 警告:超出安全框」"""
        with patch.object(main, "frame_image_response") as framed:
            result = self.run_finalize([(400, 20, 2000, 200)], size=(2752, 1548))
        framed.assert_not_called()
        self.assertEqual(decoded_size(result.image_data_base64), (2560, 1440))
        self.assertEqual(decoded_size(result.source_image_base64), (2752, 1548))
        notices = main.collected_portrait_notices()
        self.assertEqual(len(notices), 1)
        self.assertIn("警告：超出安全框", notices[0])
        self.assertIn("重新生成", notices[0])

    def test_undecodable_image_is_returned_as_is_with_warning(self):
        broken = main.ImageGenerateResponse(
            image_data_base64=base64.b64encode(b"not an image").decode(),
            mime_type="image/png", model="test",
        )
        with patch.object(main, "verify_output_aspect_ratio"):
            result = main.finalize_model_extension(
                broken, aspect_ratio="16:9", canvas=(2560, 1440)
            )
        self.assertIs(result, broken)
        self.assertIn("警告：超出安全框", main.collected_portrait_notices()[0])


class ActivationMatrixTests(unittest.TestCase):
    def test_only_reporter_with_safe_frame_on(self):
        on = main.model_extension_active
        self.assertTrue(on("記者", True, "model_extension"))
        self.assertFalse(on("記者", False, "model_extension"))
        self.assertFalse(on("編輯", True, "model_extension"))
        self.assertFalse(on("記者", True, ""))

    def test_extension_forces_2k_for_every_density(self):
        for density in main.DIGEST_DENSITY_ORDER:
            with self.subTest(density=density):
                req = main.ImageGenerateRequest(
                    prompt="x", provider="gpt", aspect_ratio="16:9", density=density,
                    safe_frame=True, safe_frame_profile="記者", frame_strategy="model_extension",
                )
                self.assertEqual(main.image_generation_size(req), ("2560x1440", (2560, 1440)))
                gemini = req.model_copy(update={"provider": "gemini", "image_size": "1K"})
                self.assertEqual(main.image_generation_size(gemini)[0], "2K")

    def test_default_strategy_keeps_existing_sizes(self):
        req = main.ImageGenerateRequest(
            prompt="x", provider="gpt", aspect_ratio="21:9", density="simplified",
            safe_frame=True, safe_frame_profile="記者",
        )
        self.assertEqual(main.image_generation_size(req), ("1680x720", safe_area_spec.BASE_CANVAS))

    def test_digest_layout_goes_central_only_when_active(self):
        seen = []
        real = main.build_digest_instructions

        def spy(*a, **kw):
            seen.append(kw.get("full_bleed"))
            return real(*a, **kw)

        class Stop(Exception):
            pass

        for strategy, expected in (("model_extension", False), ("", True)):
            req = main.GenerateRequest(
                news_text="測試", type_label="資料圖表", role="記者",
                safe_frame=True, frame_strategy=strategy,
            )
            with patch.object(main, "build_digest_instructions", side_effect=spy), \
                 patch.object(main, "digest_completion", side_effect=Stop):
                with self.assertRaises(Exception):
                    main.generate(req)
            self.assertEqual(seen[-1], expected, strategy)


class GenerateImageBranchTests(unittest.TestCase):
    def request(self, **kw):
        base = dict(
            prompt="x", provider="gpt", aspect_ratio="16:9", density="simplified",
            safe_frame=True, safe_frame_profile="記者", frame_strategy="model_extension",
        )
        base.update(kw)
        return main.ImageGenerateRequest(**base)

    def test_extension_request_uses_gate_path(self):
        with patch.object(main, "generate_image_raw", return_value=png_response((2560, 1440))), \
             patch.object(safe_content_gate, "detect_text_boxes",
                          side_effect=lambda img: [(400, 300, 2000, 1000)]), \
             patch.object(main, "frame_image_response") as framed, \
             patch.object(main, "_archive_generation"):
            result = main.generate_image(self.request())
        framed.assert_not_called()
        self.assertEqual(decoded_size(result.image_data_base64), (2560, 1440))

    def test_editor_ignores_strategy(self):
        with patch.object(main, "generate_image_raw", return_value=png_response((1280, 720))), \
             patch.object(main, "finalize_model_extension") as ext, \
             patch.object(main, "_archive_generation"):
            main.generate_image(self.request(safe_frame_profile="編輯"))
        ext.assert_not_called()


class PromptOverrideTests(unittest.TestCase):
    def test_override_avoids_empty_margin_wording(self):
        text = news_prompt.MODEL_EXTENSION_IMAGE_OVERRIDE
        self.assertNotIn("empty margin", text)
        self.assertIn("four edges", text)
        self.assertIn("top of the foreground group", text)

    def test_line_builder_does_not_use_it(self):
        """LINE 短期不做：後端 build_prompt 不接，否則會出一種沒有守門的圖。"""
        prompt = news_prompt.build_prompt(
            role="記者", engine="gpt", type_label="資料圖表", style="s",
            structure="t", variable="v", safe_frame=True,
        )
        self.assertNotIn("EXTENDED BACKGROUND SAFE LAYOUT", prompt)


if __name__ == "__main__":
    unittest.main()
