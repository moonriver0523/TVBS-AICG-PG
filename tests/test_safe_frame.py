"""safe_frame：生成後程式化置入 TVBS 安全框。

這支模組是整條安全框路線的最終手段——prompt 四輪實驗全數失敗後，改由數學保證。
因此測試重點不是「大致看起來對」，而是逐邊斷言結果一定合格：
只要這裡綠燈，任何來源尺寸、任何模型畫成什麼樣，輸出都必定落在安全框內。
"""

import io
import os
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import safe_area_spec
import safe_frame

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import (  # noqa: E402
    ImageGenerateRequest,
    ImageGenerateResponse,
    build_digest_instructions,
    generate_image,
)

def full_bleed_image(size: tuple[int, int]) -> bytes:
    """做一張「滿版」測試圖：內容一路畫到四邊，模擬滿版模式的模型輸出。"""
    img = Image.new("RGB", size, (18, 26, 48))
    draw = ImageDraw.Draw(img)
    width, height = size
    draw.rectangle([0, 0, width - 1, height - 1], outline=(255, 255, 255), width=6)
    draw.rectangle(
        [width // 8, height // 8, width * 7 // 8, height * 7 // 8], fill=(230, 230, 230)
    )
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


class PlacementGeometryTests(unittest.TestCase):
    def test_fit_placement_never_leaves_the_safe_area(self):
        safe = safe_area_spec.safe_rect(*safe_frame.DEFAULT_CANVAS)
        for source in ((1280, 720), (1376, 768), (1920, 1080), (2048, 858), (1000, 1000)):
            with self.subTest(source=source):
                left, top, right, bottom = safe_frame.plan_placement(source)
                self.assertGreaterEqual(left, safe[0])
                self.assertGreaterEqual(top, safe[1])
                self.assertLessEqual(right, safe[2])
                self.assertLessEqual(bottom, safe[3])

    def test_fit_preserves_source_aspect_ratio(self):
        left, top, right, bottom = safe_frame.plan_placement((1280, 720))
        self.assertAlmostEqual((right - left) / (bottom - top), 1280 / 720, places=2)

    def test_fit_is_centred_within_the_safe_area(self):
        x0, y0, x1, y1 = safe_area_spec.safe_rect(*safe_frame.DEFAULT_CANVAS)
        left, top, right, bottom = safe_frame.plan_placement((1280, 720))
        self.assertAlmostEqual(left - x0, x1 - right, delta=1)

    def test_cover_fills_the_safe_area_on_both_axes(self):
        x0, y0, x1, y1 = safe_area_spec.safe_rect(*safe_frame.DEFAULT_CANVAS)
        left, top, right, bottom = safe_frame.plan_placement(
            (1280, 720), mode=safe_frame.COVER
        )
        self.assertGreaterEqual(right - left, x1 - x0)
        self.assertGreaterEqual(bottom - top, y1 - y0)

    def test_rejects_degenerate_source(self):
        with self.assertRaises(ValueError):
            safe_frame.plan_placement((0, 720))


class FramedOutputTests(unittest.TestCase):
    """置框結果用確定性像素斷言驗證，不用啟發式量測。

    理由：scripts/measure_safe_area.py 是給「未知的生成圖」用的啟發式工具，
    它假設留白區平滑；而 blur-fill 背景本身帶有模糊的亮暗塊，拿它來驗自己的輸出
    會把背景誤判成內容。置框是純幾何運算，本來就能逐像素斷言，不需要猜。
    """

    def framed(self, source_size: tuple[int, int], **kwargs) -> Image.Image:
        data = safe_frame.apply_safe_frame(full_bleed_image(source_size), **kwargs)
        with Image.open(io.BytesIO(data)) as img:
            return img.convert("RGB").copy()

    def test_output_is_official_canvas_size(self):
        self.assertEqual(self.framed((1280, 720)).size, safe_area_spec.BASE_CANVAS)

    def test_content_lands_exactly_on_the_planned_box(self):
        """貼上去的內容必須與「縮放後的來源圖」逐像素相同，位置與規劃框一致。"""
        for source_size in ((1280, 720), (1376, 768), (1920, 1080), (2048, 858)):
            with self.subTest(source=source_size):
                box = safe_frame.plan_placement(source_size)
                output = self.framed(source_size)
                with Image.open(io.BytesIO(full_bleed_image(source_size))) as src:
                    expected = src.convert("RGB").resize(
                        (box[2] - box[0], box[3] - box[1]), Image.LANCZOS
                    )
                self.assertEqual(output.crop(box).tobytes(), expected.tobytes())

    def test_content_box_is_inside_the_safe_area_for_every_source(self):
        safe = safe_area_spec.safe_rect(*safe_frame.DEFAULT_CANVAS)
        for source_size in ((1280, 720), (1376, 768), (1920, 1080), (2048, 858)):
            with self.subTest(source=source_size):
                left, top, right, bottom = safe_frame.plan_placement(source_size)
                margins = {
                    "top": top / safe_frame.DEFAULT_CANVAS[1],
                    "left": left / safe_frame.DEFAULT_CANVAS[0],
                    "right": (safe_frame.DEFAULT_CANVAS[0] - right)
                    / safe_frame.DEFAULT_CANVAS[0],
                    "bottom": (safe_frame.DEFAULT_CANVAS[1] - bottom)
                    / safe_frame.DEFAULT_CANVAS[1],
                }
                summary = safe_area_spec.summarize(margins)
                self.assertEqual(summary["failed_edges"], [], summary["measured_pct"])
                self.assertLessEqual(right, safe[2])
                self.assertLessEqual(bottom, safe[3])

    def test_bottom_margin_is_deeper_than_top(self):
        """底部必須比上方深——這是安全框的重點（下方字卡蓋台區）。"""
        _, top, _, bottom = safe_frame.plan_placement((1280, 720))
        canvas_h = safe_frame.DEFAULT_CANVAS[1]
        self.assertGreater(canvas_h - bottom, top)

    def test_every_background_mode_fills_the_margins(self):
        """留白區必須有底，不能是純黑或未填的空白（看起來會像黑邊）。"""
        for background in safe_frame.BACKGROUNDS:
            with self.subTest(background=background):
                output = self.framed((1280, 720), background=background)
                corner = output.getpixel((5, 5))
                self.assertGreater(sum(corner), 30, "四角過黑，看起來會像黑邊")

    def test_default_background_is_backdrop(self):
        """預設值是使用者 2026-07-30 看實圖對照後選定的；改動要有人明確決定。"""
        self.assertEqual(safe_frame.DEFAULT_BACKGROUND, safe_frame.BACKDROP)
        self.assertEqual(
            self.framed((1280, 720)).tobytes(),
            self.framed((1280, 720), background=safe_frame.BACKDROP).tobytes(),
        )

    def test_clamp_margin_matches_content_edge_exactly(self):
        """clamp 的賣點是接縫不可見——邊界外一像素必須等於邊界內一像素。"""
        output = self.framed((1280, 720), background=safe_frame.CLAMP)
        left, top, right, bottom = safe_frame.plan_placement((1280, 720))
        mid_y = (top + bottom) // 2
        self.assertEqual(output.getpixel((left - 1, mid_y)), output.getpixel((left, mid_y)))
        self.assertEqual(output.getpixel((right, mid_y)), output.getpixel((right - 1, mid_y)))

    def test_backdrop_is_darker_at_the_bottom(self):
        """襯底是上亮下暗的漸層；反了會讓下方字卡區搶視覺。"""
        output = self.framed((1280, 720), background=safe_frame.BACKDROP)
        width, height = output.size
        top_strip = sum(output.getpixel((width // 2, 4)))
        bottom_strip = sum(output.getpixel((width // 2, height - 5)))
        self.assertGreater(top_strip, bottom_strip)

    def test_cover_mode_uses_more_of_the_safe_area_than_fit(self):
        fit = safe_frame.plan_placement((1280, 720), mode=safe_frame.FIT)
        cover = safe_frame.plan_placement((1280, 720), mode=safe_frame.COVER)
        self.assertGreater(cover[2] - cover[0], fit[2] - fit[0])

    def test_rejects_unknown_options(self):
        image = full_bleed_image((1280, 720))
        with self.assertRaises(ValueError):
            safe_frame.apply_safe_frame(image, mode="stretch")
        with self.assertRaises(ValueError):
            safe_frame.apply_safe_frame(image, background="rainbow")
        with self.assertRaises(ValueError):
            safe_frame.apply_safe_frame(image, background="solid")  # 已被 backdrop 取代


class EndpointWiringTests(unittest.TestCase):
    """safe_frame 旗標必須真的一路生效，且失敗時不得默默回傳沒置框的圖。"""

    def raw_response(self, source_size=(1280, 720)) -> ImageGenerateResponse:
        import base64

        return ImageGenerateResponse(
            image_data_base64=base64.b64encode(full_bleed_image(source_size)).decode(),
            mime_type="image/png",
            model="fake-model",
        )

    def test_flag_off_returns_image_untouched(self):
        raw = self.raw_response()
        with patch.object(main, "generate_image_raw", return_value=raw):
            result = generate_image(ImageGenerateRequest(prompt="p"))
        self.assertEqual(result.image_data_base64, raw.image_data_base64)

    def test_flag_on_reframes_to_official_canvas(self):
        import base64

        with patch.object(main, "generate_image_raw", return_value=self.raw_response()):
            result = generate_image(ImageGenerateRequest(prompt="p", safe_frame=True))
        with Image.open(io.BytesIO(base64.b64decode(result.image_data_base64))) as img:
            self.assertEqual(img.size, safe_area_spec.BASE_CANVAS)
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual(result.model, "fake-model")

    def test_framing_failure_raises_instead_of_downgrading(self):
        broken = ImageGenerateResponse(
            image_data_base64="bm90LWFuLWltYWdl", mime_type="image/png", model="m"
        )
        from fastapi import HTTPException

        with patch.object(main, "generate_image_raw", return_value=broken):
            with self.assertRaises(HTTPException) as caught:
                generate_image(ImageGenerateRequest(prompt="p", safe_frame=True))
        self.assertEqual(caught.exception.status_code, 500)


class DigestFullBleedTests(unittest.TestCase):
    def test_full_bleed_replaces_the_safe_area_layout_rule(self):
        safe = build_digest_instructions("記者", "standard", "資料圖表")
        full = build_digest_instructions("記者", "standard", "資料圖表", full_bleed=True)
        self.assertIn("BROADCAST SAFE AREA", safe)
        self.assertNotIn("BROADCAST SAFE AREA", full)
        self.assertIn("FULL-FRAME LAYOUT", full)
        self.assertNotIn("FULL-FRAME LAYOUT", safe)

    def test_editor_role_gets_the_stamp_wording_in_full_bleed(self):
        full = build_digest_instructions("編輯", "standard", "資料圖表", full_bleed=True)
        self.assertIn("<蓋章> stamp banner", full)

    def test_both_modes_still_ban_numeric_positioning(self):
        """去掉安全框敘述時不能連「不准用數字定位」一起去掉——那是已修好的病灶。"""
        for full_bleed in (False, True):
            with self.subTest(full_bleed=full_bleed):
                prompt = build_digest_instructions(
                    "記者", "standard", "資料圖表", full_bleed=full_bleed
                )
                self.assertIn("NEVER express any position", prompt)
                self.assertIn("percentage, pixel, ratio", prompt)

    def test_no_unformatted_placeholder_leaks(self):
        for role in ("記者", "編輯"):
            for full_bleed in (False, True):
                prompt = build_digest_instructions(
                    role, "standard", "資料圖表", full_bleed=full_bleed
                )
                self.assertNotIn("{layout_rule}", prompt)


if __name__ == "__main__":
    unittest.main()
