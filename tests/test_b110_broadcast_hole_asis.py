"""B110：播出鏡面挖空版面與白色壓框是兩個獨立契約。"""

import base64
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402
import main  # noqa: E402
import safe_area_spec  # noqa: E402


def _png_base64(size=(320, 180), colour=(18, 52, 86)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class BroadcastHolePromptTests(unittest.TestCase):
    def _generated_prompt(self, side: str, purpose: str | None) -> str:
        refs = []
        if purpose:
            refs = [
                main.UserReferenceImage(
                    data_url="data:image/png;base64,AAAA", purpose=purpose
                )
            ]
        seen = []

        def fake_raw(req):
            seen.append(req)
            return main.ImageGenerateResponse(
                image_data_base64=_png_base64(), mime_type="image/png", model="fake"
            )

        request = main.ImageGenerateRequest(
            prompt="BASE PROMPT",
            provider="gpt",
            aspect_ratio="16:9",
            safe_frame=False,
            safe_frame_profile="編輯",
            hole_side=side,
            reference_images=refs,
        )
        with patch.object(main, "generate_image_raw", side_effect=fake_raw), patch.object(
            main, "supports_multiple_reference_images", return_value=True
        ):
            main.generate_image(request)
        self.assertEqual(len(seen), 1)
        return seen[0].prompt

    def test_left_and_right_asis_aiedit_and_no_image_stay_out_of_hole(self):
        for side, content_side in (("left", "right"), ("right", "left")):
            for purpose in ("asis", "aiedit", None):
                with self.subTest(side=side, purpose=purpose or "no-image"):
                    prompt = self._generated_prompt(side, purpose)
                    # 使用者 2026-09-26 實拍後修正：只有 16:9 影片區留空，標題與底帶照舊跨全寬；
                    # 原圖必須出現在另一側內容區，不准被省略。
                    self.assertIn(f"16:9 area on the {side} side of the frame", prompt)
                    self.assertIn("Inside the video zone: background ONLY", prompt)
                    self.assertIn(
                        "No attached image, generated subject, text, number, card, chart, logo, badge or callout may enter or overlap the video zone",
                        prompt,
                    )
                    self.assertIn(f"goes in the {content_side} half", prompt)
                    self.assertIn("PLACE AS-IS image MUST appear there", prompt)
                    self.assertIn("headline at the top and the bottom band may still span the full width", prompt)

    def test_frontend_sends_layout_side_independently_from_pressure_frame(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        layout_helper = source.split("function broadcastLayoutHoleForApi()", 1)[1].split(
            "}", 1
        )[0]
        self.assertIn("return state.holeSide;", layout_helper)
        self.assertNotIn("state.hole ||", layout_helper)
        self.assertGreaterEqual(
            source.count("hole_side: broadcastLayoutHoleForApi(),"), 2
        )


class BroadcastHoleFinalizerTests(unittest.TestCase):
    def test_pressure_frame_is_applied_without_safe_frame_and_source_is_preserved(self):
        original = _png_base64()
        for density in ("standard", "maximum"):
            for side in ("left", "right"):
                with self.subTest(density=density, side=side):
                    raw = main.ImageGenerateResponse(
                        image_data_base64=original,
                        mime_type="image/png",
                        model="fake",
                    )
                    request = main.ImageGenerateRequest(
                        prompt="p",
                        provider="gpt",
                        aspect_ratio="16:9",
                        density=density,
                        safe_frame=False,
                        safe_frame_profile="編輯",
                        broadcast_hole=side,
                    )
                    with patch.object(main, "generate_image_raw", return_value=raw):
                        result = main.generate_image(request)

                    self.assertEqual(result.source_image_base64, original)
                    self.assertEqual(result.source_mime_type, "image/png")
                    self.assertNotEqual(result.image_data_base64, original)
                    x0, y0, x1, y1 = compose.broadcast_hole_rect(
                        (320, 180), side, safe_area_spec.EDITOR_PROFILE
                    )
                    with Image.open(
                        io.BytesIO(base64.b64decode(result.image_data_base64))
                    ) as image:
                        self.assertEqual(
                            image.convert("RGB").getpixel(((x0 + x1) // 2, (y0 + y1) // 2)),
                            compose.HOLE_FILL,
                        )


if __name__ == "__main__":
    unittest.main()
