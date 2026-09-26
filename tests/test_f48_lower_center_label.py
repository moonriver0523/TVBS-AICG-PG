"""F48（2026-09-26 使用者裁決）：來源標籤新增「正下方」＝記者／編輯安全框下緣置中。

- 位置：水平置中於安全框、底緣＝安全框下緣內縮 HOLE_INSET（1080p／2K、三種 profile）
- prompt：選正下方時留空提示跟著換位置，另注入一段底部置中留空；右下（預設）逐字不變
- 前端兩組按鈕都要有、字面值與後端一致（守在 test_b70_f43_disclaimer）
"""

import io
import os
import unittest

from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import main  # noqa: E402
import news_prompt  # noqa: E402
import safe_area_spec  # noqa: E402


def blank_png(size):
    buffer = io.BytesIO()
    Image.new("RGB", size, (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def plate_bbox(png, size):
    """找出半透明黑底板的外接框（白底上唯一變暗的區域）。"""
    image = Image.open(io.BytesIO(png)).convert("L")
    mask = image.point(lambda v: 255 if v < 200 else 0)
    return mask.getbbox()


class LowerCentreGeometryTests(unittest.TestCase):
    PROFILES = (
        safe_area_spec.REPORTER_PROFILE,
        safe_area_spec.EDITOR_PROFILE,
        safe_area_spec.EDITOR_FRAME_PROFILE,
    )

    def test_box_is_centred_on_safe_area_and_sits_on_its_bottom(self):
        for canvas in ((1920, 1080), (2560, 1440)):
            for profile in self.PROFILES:
                with self.subTest(canvas=canvas, profile=profile):
                    x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas, profile)
                    left, top, right, bottom = compose._disclaimer_box(
                        canvas, "lower_center", profile, 200, 50
                    )
                    self.assertLessEqual(abs((left + right) / 2 - (x0 + x1) / 2), 1)
                    inset = compose._scaled_pixel(compose.HOLE_INSET, canvas[1])
                    self.assertEqual(bottom, y1 - inset)
                    self.assertTrue(x0 <= left and right <= x1 and y0 <= top)

    def test_pasted_plate_lands_bottom_centre(self):
        canvas = (1920, 1080)
        png = compose.paste_disclaimer_note(
            blank_png(canvas), kind="source", source_text="畫面來源：美聯社",
            corner="lower_center", canvas=canvas,
        )
        left, top, right, bottom = plate_bbox(png, canvas)
        x0, _, x1, y1 = safe_area_spec.safe_rect(*canvas)
        self.assertLessEqual(abs((left + right) / 2 - (x0 + x1) / 2), 2)
        self.assertLessEqual(bottom, y1)
        self.assertGreater(top, 1080 // 2)

    def test_existing_corners_unchanged(self):
        canvas = (1920, 1080)
        x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas)
        inset = compose._scaled_pixel(compose.HOLE_INSET, canvas[1])
        self.assertEqual(
            compose._disclaimer_box(canvas, "lower_right", "記者", 200, 50),
            (x1 - inset - 200, y1 - inset - 50, x1 - inset, y1 - inset),
        )


class PromptPositionTests(unittest.TestCase):
    BLOCK = news_prompt.PORTRAIT_WITH_REFERENCE_RULES

    def test_default_corner_leaves_prompt_byte_identical(self):
        self.assertIs(
            news_prompt.localise_disclaimer_position(self.BLOCK, "lower_right", stamping=True),
            self.BLOCK,
        )

    def test_no_label_leaves_prompt_unchanged(self):
        self.assertIs(
            news_prompt.localise_disclaimer_position(self.BLOCK, "lower_center", stamping=False),
            self.BLOCK,
        )

    def test_lower_centre_rewrites_and_adds_hint(self):
        text = news_prompt.localise_disclaimer_position(self.BLOCK, "lower_center", stamping=True)
        self.assertNotIn("lower-right corner", text)
        self.assertIn("centred along the bottom of the frame", text)
        self.assertIn("BOTTOM-CENTRE LABEL AREA", text)

    def test_other_corners_follow_the_choice(self):
        text = news_prompt.localise_disclaimer_position(self.BLOCK, "upper_left", stamping=True)
        self.assertIn("at the upper-left corner of the frame", text)
        self.assertNotIn("lower-right corner", text)

    def test_hint_added_even_without_portrait_block(self):
        text = news_prompt.localise_disclaimer_position("plain prompt", "lower_center", stamping=True)
        self.assertIn("BOTTOM-CENTRE LABEL AREA", text)

    def test_generate_image_applies_it(self):
        import inspect

        self.assertIn("localise_disclaimer_position", inspect.getsource(main.generate_image))

    def test_backend_accepts_lower_centre_everywhere(self):
        for model in (main.ImageGenerateRequest, main.ImageRefineRequest, main.ImageRestampRequest):
            with self.subTest(model=model.__name__):
                allowed = model.model_fields["disclaimer_corner"].annotation.__args__
                self.assertIn("lower_center", allowed)


if __name__ == "__main__":
    unittest.main()
