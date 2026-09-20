"""B70／F43（2026-09-20）：具名肖像「示意圖」標籤改由程式端 Pillow 壓字，
新增互斥的「畫面來源」欄位。

B70 根因：標籤以前完全交給生圖模型自己畫進「variable」，沒有程式保證——4 張
具名肖像實拍裡 2 張不合格（一張整張找不到標籤，一張寫成錯字「示憊佪」，見
MASTER-列管清單.md）。2026-09-16 使用者裁定採甲案：改由程式後貼，模型只被
告知「這個角落留空」。

F43 追加「畫面來源」欄位，與「示意圖」互斥：圖是 AI 生成／被 AI 改過 → 標
「示意圖」；圖是使用者原圖且保證未被動過像素 → 標「畫面來源：○○○」。

三塊測試：
1. main.resolve_image_disclaimer 的互斥判定表
2. compose.paste_disclaimer_note 的貼字幾何與錯誤處理
3. main.generate_image／generate_news_image 的實際串接
"""

import base64
import io
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402
import main  # noqa: E402
import news_prompt  # noqa: E402
import safe_area_spec  # noqa: E402
from PIL import Image  # noqa: E402


def png_base64(width: int, height: int, colour=(40, 60, 90)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def fake_raw_response(image_base64: str) -> main.ImageGenerateResponse:
    return main.ImageGenerateResponse(
        image_data_base64=image_base64, mime_type="image/png", model="fake-model"
    )


class ResolveImageDisclaimerTests(unittest.TestCase):
    """互斥判定表：每一種 (portrait_mode, source_text) 組合恰好落在
    {"ai", "source", ""} 其中一種，AI 標籤永遠贏。"""

    AI_MODES = ("reference", "reference_multi", "entry_only")
    NON_AI_MODES = ("no_reference", "none", "", "unknown_future_mode")

    def test_ai_modes_always_win_regardless_of_source_text(self):
        for mode in self.AI_MODES:
            for source_text in ("", "美聯社", "  路透社  "):
                with self.subTest(mode=mode, source_text=source_text):
                    self.assertEqual(
                        main.resolve_image_disclaimer(mode, source_text),
                        ("ai", ""),
                    )

    def test_non_ai_modes_with_source_text_get_source(self):
        for mode in self.NON_AI_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(
                    main.resolve_image_disclaimer(mode, "美聯社"),
                    ("source", "美聯社"),
                )

    def test_non_ai_modes_without_source_text_get_nothing(self):
        for mode in self.NON_AI_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(main.resolve_image_disclaimer(mode, ""), ("", ""))

    def test_whitespace_only_source_text_counts_as_empty(self):
        self.assertEqual(main.resolve_image_disclaimer("none", "   "), ("", ""))

    def test_result_is_always_exactly_one_of_the_three_kinds(self):
        """明確釘住互斥——不可能同一次回傳同時暗示兩種標籤。"""
        for mode in self.AI_MODES + self.NON_AI_MODES:
            for source_text in ("", "來源名"):
                with self.subTest(mode=mode, source_text=source_text):
                    kind, text = main.resolve_image_disclaimer(mode, source_text)
                    self.assertIn(kind, ("", "ai", "source"))
                    if kind == "ai":
                        self.assertEqual(text, "")
                    if kind == "":
                        self.assertEqual(text, "")


class ComposePasteDisclaimerNoteTests(unittest.TestCase):
    def setUp(self):
        self.canvas = (1920, 1080)
        self.image_bytes = base64.b64decode(png_base64(*self.canvas))

    def test_ai_kind_draws_the_fixed_text(self):
        out = compose.paste_disclaimer_note(self.image_bytes, kind="ai")
        with Image.open(io.BytesIO(out)) as img:
            self.assertEqual(img.size, self.canvas)
            self.assertEqual(img.mode, "RGB")

    def test_source_kind_normalises_the_prefix(self):
        """沿用 vstrip_source_text：使用者只填來源名，「畫面來源：」自動補。"""
        with patch.object(
            compose, "vstrip_source_text", wraps=compose.vstrip_source_text
        ) as spy:
            compose.paste_disclaimer_note(
                self.image_bytes, kind="source", source_text="美聯社"
            )
        spy.assert_called_once_with("美聯社")

    def test_source_kind_with_empty_text_raises(self):
        with self.assertRaises(compose.ComposeError):
            compose.paste_disclaimer_note(self.image_bytes, kind="source", source_text="")

    def test_source_kind_with_whitespace_only_text_raises(self):
        with self.assertRaises(compose.ComposeError):
            compose.paste_disclaimer_note(self.image_bytes, kind="source", source_text="   ")

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(compose.ComposeError):
            compose.paste_disclaimer_note(self.image_bytes, kind="watermark")

    def test_unknown_corner_is_rejected(self):
        with self.assertRaises(compose.ComposeError):
            compose.paste_disclaimer_note(self.image_bytes, kind="ai", corner="middle")

    def test_every_corner_lands_inside_the_safe_area(self):
        """B70 動工前要釘的第②件事：自訂位置必須限制在安全框內。"""
        x0, y0, x1, y1 = safe_area_spec.safe_rect(
            *self.canvas, safe_area_spec.REPORTER_PROFILE
        )
        for corner in compose.PORTRAIT_DISCLAIMER_CORNERS:
            with self.subTest(corner=corner):
                left, top, right, bottom = compose._disclaimer_box(
                    self.canvas, corner, safe_area_spec.REPORTER_PROFILE,
                    box_w=200, box_h=60,
                )
                self.assertGreaterEqual(left, x0)
                self.assertLessEqual(right, x1)
                self.assertGreaterEqual(top, y0)
                self.assertLessEqual(bottom, y1)

    def test_corners_are_mutually_distinct_positions(self):
        boxes = {
            corner: compose._disclaimer_box(
                self.canvas, corner, safe_area_spec.REPORTER_PROFILE, 200, 60
            )
            for corner in compose.PORTRAIT_DISCLAIMER_CORNERS
        }
        self.assertEqual(len(set(boxes.values())), len(boxes))

    def test_output_canvas_size_is_unchanged(self):
        """貼標籤不能順便改動畫布尺寸——那是另一個 bug 類型（見安全框系列教訓）。"""
        for corner in compose.PORTRAIT_DISCLAIMER_CORNERS:
            with self.subTest(corner=corner):
                out = compose.paste_disclaimer_note(
                    self.image_bytes, kind="ai", corner=corner
                )
                with Image.open(io.BytesIO(out)) as img:
                    self.assertEqual(img.size, self.canvas)

    def test_actual_image_size_wins_over_the_default_canvas_argument(self):
        """理由同 apply_broadcast_hole：上游可能改了尺寸，不能硬信呼叫端傳的 canvas。"""
        smaller = base64.b64decode(png_base64(1280, 720))
        out = compose.paste_disclaimer_note(
            smaller, kind="ai", canvas=self.canvas
        )
        with Image.open(io.BytesIO(out)) as img:
            self.assertEqual(img.size, (1280, 720))


class GenerateImageWiringTests(unittest.TestCase):
    """generate_image() 實際串接：置框／挖空框跑完之後才貼標籤，
    且播出鏡面挖空框已經自己貼過一次，兩者不疊貼。"""

    def test_disclaimer_kind_empty_skips_stamping_entirely(self):
        raw = fake_raw_response(png_base64(1920, 1080))
        with patch.object(main, "generate_image_raw", return_value=raw), patch.object(
            compose, "paste_disclaimer_note"
        ) as spy:
            main.generate_image(main.ImageGenerateRequest(prompt="p", disclaimer_kind=""))
        spy.assert_not_called()

    def test_ai_disclaimer_is_stamped_after_safe_framing(self):
        raw = fake_raw_response(png_base64(1280, 720))
        with patch.object(main, "generate_image_raw", return_value=raw):
            result = main.generate_image(
                main.ImageGenerateRequest(
                    prompt="p", provider="gpt", safe_frame=True,
                    safe_frame_profile="記者", disclaimer_kind="ai",
                )
            )
        with Image.open(io.BytesIO(base64.b64decode(result.image_data_base64))) as img:
            self.assertEqual(img.size, safe_area_spec.BASE_CANVAS)

    def test_source_disclaimer_needs_source_text(self):
        raw = fake_raw_response(png_base64(1920, 1080))
        with patch.object(main, "generate_image_raw", return_value=raw):
            with self.assertRaises(main.HTTPException) as ctx:
                main.generate_image(
                    main.ImageGenerateRequest(
                        prompt="p", disclaimer_kind="source", disclaimer_source_text="",
                    )
                )
        self.assertEqual(ctx.exception.status_code, 500)

    def test_broadcast_hole_set_skips_the_new_stamp_to_avoid_double_stamping(self):
        """apply_broadcast_hole 已經在同一個安全區角落自己貼過一次「示意圖」浮水印
        （compose.WATERMARK_TEXT）；disclaimer_kind 同時有值時不重貼第二次。"""
        raw = fake_raw_response(png_base64(1280, 720))
        with patch.object(main, "generate_image_raw", return_value=raw), patch.object(
            compose, "paste_disclaimer_note"
        ) as spy:
            main.generate_image(
                main.ImageGenerateRequest(
                    prompt="p", provider="gpt", safe_frame=True,
                    safe_frame_profile="編輯", broadcast_hole="left",
                    disclaimer_kind="ai",
                )
            )
        spy.assert_not_called()

    def test_stamping_failure_raises_instead_of_downgrading(self):
        raw = fake_raw_response(png_base64(1920, 1080))
        with patch.object(main, "generate_image_raw", return_value=raw), patch.object(
            compose, "paste_disclaimer_note", side_effect=compose.ComposeError("boom")
        ):
            with self.assertRaises(main.HTTPException) as ctx:
                main.generate_image(
                    main.ImageGenerateRequest(prompt="p", disclaimer_kind="ai")
                )
        self.assertEqual(ctx.exception.status_code, 500)


class FullPipelineWiringTests(unittest.TestCase):
    """generate_news_image：portrait_mode 一路決定 disclaimer_kind 傳進
    ImageGenerateRequest，不用呼叫端自己算。"""

    def _run(self, portrait_mode: str):
        digest = main.GenerateResponse(
            style="S", structure="T", variable="[標題] X", chart_type="資料圖表"
        )
        image = fake_raw_response(png_base64(1536, 864))
        with (
            patch.object(main, "generate", return_value=digest),
            patch.object(main, "resolve_portraits", return_value=(portrait_mode, [])),
            patch.object(main, "generate_image", return_value=image) as mock_image,
        ):
            main.generate_news_image(
                main.NewsImageGenerateRequest(
                    news_text="颱風假消息滿天飛 氣象署嚴正闢謠並呼籲民眾勿轉傳"
                )
            )
        return mock_image.call_args[0][0]

    def test_reference_mode_asks_for_the_ai_disclaimer(self):
        self.assertEqual(self._run("reference").disclaimer_kind, "ai")

    def test_reference_multi_mode_asks_for_the_ai_disclaimer(self):
        self.assertEqual(self._run("reference_multi").disclaimer_kind, "ai")

    def test_entry_only_mode_asks_for_the_ai_disclaimer(self):
        self.assertEqual(self._run("entry_only").disclaimer_kind, "ai")

    def test_no_reference_mode_asks_for_nothing(self):
        self.assertEqual(self._run("no_reference").disclaimer_kind, "")

    def test_none_mode_asks_for_nothing(self):
        self.assertEqual(self._run("none").disclaimer_kind, "")


class PortraitPromptNoLongerAsksTheModelToDrawTheLabelTests(unittest.TestCase):
    """B70 甲案：三個「查得到怎麼畫」的肖像區塊改口——模型不再自己規劃／畫標籤，
    程式後貼。舊的被動措辭（「有給才畫、沒給就不畫」）必須整句換掉，不是並存。"""

    BLOCKS = (
        news_prompt.PORTRAIT_WITH_REFERENCE_RULES,
        news_prompt.PORTRAIT_MULTI_WITH_REFERENCE_RULES,
        news_prompt.PORTRAIT_ENTRY_ONLY_RULES,
    )

    def test_blocks_tell_the_model_not_to_draw_it_itself(self):
        for block in self.BLOCKS:
            with self.subTest(block=block[:50]):
                self.assertIn("Do NOT draw any 示意圖", block)
                self.assertIn("Software stamps the disclaimer afterwards", block)
                self.assertIn("OVERRIDES the general instruction", block)
                self.assertNotIn(
                    "If VARIABLE FIELDS supplies no such label, do not add one yourself",
                    block,
                )

    def test_position_is_expressed_as_a_direction_word_never_a_number(self):
        import re

        for block in self.BLOCKS:
            with self.subTest(block=block[:50]):
                self.assertIn("lower-right corner", block)
                self.assertNotRegex(block, r"\d")

    def test_frozen_baseline_reference_prompt_snapshot_is_untouched(self):
        """這三塊只在明確傳入非 none 的 portrait_mode 時才注入，凍結快照
        （tests/test_reporter_prompt_frozen.py）全部用 portrait_mode="none" 呼叫，
        不受這批影響——這裡直接重新確認一次，不去動那支凍結測試本身。"""
        plain = news_prompt.build_prompt(
            role="記者", engine="gpt", type_label="資料圖表",
            style="[S]", structure="[T]", variable="[V]",
        )
        for block in self.BLOCKS:
            self.assertNotIn(block, plain)


if __name__ == "__main__":
    unittest.main()
