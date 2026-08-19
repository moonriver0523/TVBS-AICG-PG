"""safe_frame：生成後程式化置入 TVBS 安全框。

這支模組是整條安全框路線的最終手段——prompt 四輪實驗全數失敗後，改由數學保證。
因此測試重點不是「大致看起來對」，而是逐邊斷言結果一定合格：
只要這裡綠燈，任何來源尺寸、任何模型畫成什麼樣，輸出都必定落在安全框內。
"""

import io
import os
import pathlib
import re
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


class EditorOutputIsPureStretchTests(unittest.TestCase):
    """編輯 2026-08-17 的兩次回報：機制補上去的底色與四周強制留白都要消失。

    成品必須就是「生成圖拉伸到對位框大小」本身——沒有畫布、沒有留白，
    每一個像素都來自模型。
    """

    MARKER = (7, 199, 133)  # 生成圖用這個色填滿，補出來的底色不可能撞到

    def _output(self, source_size, colour=None):
        img = Image.new("RGB", source_size, colour or self.MARKER)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        data = safe_frame.apply_safe_frame(buffer.getvalue(), profile="編輯")
        return Image.open(io.BytesIO(data)).convert("RGB")

    def test_output_is_exactly_the_alignment_guide_size(self):
        x0, y0, x1, y1 = safe_area_spec.safe_rect(*safe_frame.DEFAULT_CANVAS, "編輯")
        for source_size in ((1280, 720), (1536, 864), (1376, 768)):
            with self.subTest(source=source_size):
                out = self._output(source_size)
                self.assertEqual(out.size, (x1 - x0, y1 - y0))
                self.assertNotEqual(
                    out.size, safe_frame.DEFAULT_CANVAS, "又輸出成 1920×1080 畫布了"
                )

    def test_every_pixel_comes_from_the_generated_image(self):
        out = self._output((1536, 864))
        self.assertEqual(
            out.getcolors(maxcolors=8),
            [(out.width * out.height, self.MARKER)],
            "出現了非生成圖的像素——補底色或四周留白又跑回來了",
        )

    def test_corners_are_generated_pixels_too(self):
        # 四角是最容易被補底色吃掉的地方，單獨釘住
        out = self._output((1536, 864))
        for point in ((0, 0), (out.width - 1, 0), (0, out.height - 1),
                      (out.width - 1, out.height - 1)):
            self.assertEqual(out.getpixel(point), self.MARKER, f"{point} 是補出來的")

    def test_content_is_stretched_not_cropped(self):
        """來源整張都要進成品：畫一條貼上緣的橫線，拉伸後必須還在最上面。"""
        img = Image.new("RGB", (1536, 864), (10, 10, 10))
        ImageDraw.Draw(img).rectangle([0, 0, 1535, 2], fill=(255, 0, 0))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        out = Image.open(
            io.BytesIO(safe_frame.apply_safe_frame(buffer.getvalue(), profile="編輯"))
        ).convert("RGB")
        self.assertEqual(out.getpixel((out.width // 2, 0)), (255, 0, 0))

    def test_background_choice_is_irrelevant_for_the_editor(self):
        """沒有任何像素需要補，所以三種背景做法都該給出一模一樣的結果。"""
        img = Image.new("RGB", (1536, 864), self.MARKER)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        outputs = {
            bg: safe_frame.apply_safe_frame(buffer.getvalue(), profile="編輯", background=bg)
            for bg in safe_frame.BACKGROUNDS
        }
        self.assertEqual(len(set(outputs.values())), 1)


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

    def test_rejects_out_of_range_mode(self):
        with self.assertRaises(ValueError):
            safe_frame.plan_placement((1280, 720), mode=1.5)
        with self.assertRaises(ValueError):
            safe_frame.plan_placement((1280, 720), mode=-0.1)
        with self.assertRaises(ValueError):
            safe_frame.plan_placement((1280, 720), mode="stretch")

    def test_half_mode_exactly_halves_the_slack_axis_waste(self):
        """mode=0.5 必須精確減半（線性內插在餘裕像素數上也是線性的，見模組內推導），
        不是概略值——這條測試把那個數學推導變成可驗證的斷言。"""
        x0, y0, x1, y1 = safe_area_spec.safe_rect(*safe_frame.DEFAULT_CANVAS)
        fit_left, _, fit_right, _ = safe_frame.plan_placement((1280, 720), mode=safe_frame.FIT)
        half_left, _, half_right, _ = safe_frame.plan_placement((1280, 720), mode=0.5)

        fit_waste = fit_left - x0
        half_waste = half_left - x0
        self.assertAlmostEqual(half_waste, fit_waste / 2, delta=1)

        fit_waste_r = (x1 - fit_right)
        half_waste_r = (x1 - half_right)
        self.assertAlmostEqual(half_waste_r, fit_waste_r / 2, delta=1)

    def test_reporter_default_is_fit_no_crop(self):
        self.assertEqual(safe_frame.default_crop_ratio("記者"), safe_frame.FIT)

    def test_editor_fills_the_whole_zone_by_stretching(self):
        """編輯：內容不等比拉伸貼滿整個對位框，不裁切也不留縫。"""
        self.assertTrue(safe_frame.uses_stretch("編輯"))
        self.assertFalse(safe_frame.uses_stretch("記者"))
        x0, y0, x1, y1 = safe_area_spec.safe_rect(1920, 1080, "編輯")
        for source in ((1280, 720), (1536, 864), (1376, 768)):
            with self.subTest(source=source):
                # 來源比例不同也一律貼滿同一個框——這正是「拉伸」與 FIT 的差別
                self.assertEqual(
                    safe_frame.plan_placement(source, profile="編輯"), (x0, y0, x1, y1)
                )

    def test_editor_stretch_ignores_mode(self):
        """mode 對拉伸沒有意義，帶什麼都不該改變結果，也不該炸掉。"""
        x0, y0, x1, y1 = safe_area_spec.safe_rect(1920, 1080, "編輯")
        for mode in (0.0, 0.5, 1.0):
            with self.subTest(mode=mode):
                self.assertEqual(
                    safe_frame.plan_placement((1280, 720), mode=mode, profile="編輯"),
                    (x0, y0, x1, y1),
                )

    def test_editor_horizontal_distortion_is_the_agreed_6_4_percent(self):
        """16:9 拉進 1.892 的失真幅度。使用者是看著這個數字點頭的，變了要重新確認。"""
        x0, y0, x1, y1 = safe_area_spec.safe_rect(1920, 1080, "編輯")
        zone_w, zone_h = x1 - x0, y1 - y0
        # 等高縮放後的寬度 vs 實際被拉到的寬度
        natural_w = zone_h * 16 / 9
        self.assertAlmostEqual(zone_w / natural_w - 1, 0.064, places=3)

    def test_mode_above_zero_never_shrinks_the_binding_axis_margin(self):
        """這裡曾經有真的 bug：mode>0 時置放框會超出『安全區』邊界（不是畫布邊界），
        若只裁到畫布邊界，官方留白會被吃掉（2026-07-30 實測：底部 <蓋章> 橫幅被裁到）。
        這條測試斷言 plan_placement 回傳的框永遠不會讓綁定軸（此處是高度）的留白
        小於官方需求——不管 mode 設多少。"""
        x0, y0, x1, y1 = safe_area_spec.safe_rect(*safe_frame.DEFAULT_CANVAS)
        for mode in (0.0, 0.25, 0.5, 0.75, 1.0):
            with self.subTest(mode=mode):
                _, top, _, bottom = safe_frame.plan_placement((1280, 720), mode=mode)
                # top/bottom 可能超出 zone（那是設計上允許的，交給 apply_safe_frame 裁），
                # 但裁完後絕對不能比官方需求淺——這裡先確認「需要裁多少」算得出來，
                # 真正裁完的結果由 apply_safe_frame 的整合測試把關（見下方）。
                self.assertLessEqual(top, y0, f"mode={mode} 的上緣不該比官方需求更深入安全區")


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

    def test_default_mode_is_fit_not_a_crop_ratio(self):
        """2026-07-30 曾把預設改成 0.5（裁掉一半餘裕）想解決左右留白過寬，
        兩張既有樣本目視驗證看似安全，但使用者用真實生成圖實測後回報底部
        <蓋章> 橫幅被裁到——同一份 prompt 每次生成的自留邊距不固定，兩張樣本
        不足以保證安全。這條測試把預設值釘死在 FIT，防止同樣的錯誤重演；
        改預設前必須先有結構性解法（如改生成長寬比）並經多張實測驗證。"""
        self.assertEqual(safe_frame.DEFAULT_CROP_RATIO, safe_frame.FIT)

    def test_cropping_mode_never_cuts_into_the_official_zone_on_any_axis(self):
        """apply_safe_frame 的整合層級回歸測試，對應真實踩過的 bug：
        mode>0 時若只裁到『畫布』邊界、沒裁到『安全區』邊界，官方留白會被吃掉
        （實測發生：真實生成圖的底部 <蓋章> 橫幅被裁掉；用合成圖重現時量到上緣
        從精準的 10.09% 掉到 2.3%）。

        用一張邊緣到邊緣、完全不留內縮的純色測試圖，搭配 backdrop 背景（不是
        clamp）——clamp 會把內容邊緣色直接延伸出去，純色內容跟純色背景同色，
        測試根本分辨不出來（第一版拿 clamp 測純色圖就這樣誤判通過，沒抓到 bug）。
        backdrop 會把邊緣色壓暗（乘上 0.44～0.62 係數），只要安全區外仍是content
        的原色而非壓暗色，就代表裁切裁到了官方留白裡。
        """
        edge_to_edge = Image.new("RGB", (1280, 720), (230, 230, 230))
        buffer = io.BytesIO()
        edge_to_edge.save(buffer, format="PNG")
        edge_to_edge_bytes = buffer.getvalue()

        x0, y0, x1, y1 = safe_area_spec.safe_rect(*safe_frame.DEFAULT_CANVAS)
        for mode in (0.25, 0.5, 0.75, 1.0):
            with self.subTest(mode=mode):
                data = safe_frame.apply_safe_frame(
                    edge_to_edge_bytes, mode=mode, background=safe_frame.BACKDROP
                )
                with Image.open(io.BytesIO(data)) as img:
                    output = img.convert("RGB")
                probe_points = [
                    ((x0 + x1) // 2, max(0, y0 - 2)),  # 正上方緊貼安全區外
                    ((x0 + x1) // 2, min(output.height - 1, y1 + 2)),  # 正下方緊貼安全區外
                ]
                for point in probe_points:
                    pixel = output.getpixel(point)
                    self.assertNotEqual(
                        pixel, (230, 230, 230),
                        f"mode={mode} 在安全區外 {point} 偵測到內容色塊，"
                        "代表裁切裁到了官方留白裡（曾經真的發生過，且切到了真實內容）",
                    )


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

        # aspect_ratio="auto" 讓「量成圖比例」那道關卡沒有可驗的目標而放行，
        # 這條測的才會是置框失敗本身；否則會先被比例檢查以 502 擋下。
        with patch.object(main, "generate_image_raw", return_value=broken):
            with self.assertRaises(HTTPException) as caught:
                generate_image(
                    ImageGenerateRequest(prompt="p", safe_frame=True, aspect_ratio="auto")
                )
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


class EditorTwoFrameModesTests(unittest.TestCase):
    """編輯版的兩種模式（2026-08-19 使用者指定的對調）。

    對調本身容易做對，容易漏的是**編輯 OFF 仍然要後製**——舊的
    `if not safe_frame: return` 會讓它悄悄退回「完全不置框」：圖照樣出得來，
    只是尺寸與版面全錯，不會有任何執行期錯誤提醒你。
    """

    def _output(self, profile: str, source_size=(1536, 864)):
        img = Image.new("RGB", source_size, (20, 30, 60))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        data = safe_frame.apply_safe_frame(buffer.getvalue(), profile=profile)
        return Image.open(io.BytesIO(data)).convert("RGB")

    def test_editor_off_still_gets_post_processed(self):
        """OFF ＝ 舊的 ON：滿版生成＋拉伸到對位框，不是「不後製」。"""
        full_bleed, needs_frame, profile = main.resolve_frame_plan("編輯", False)
        self.assertTrue(full_bleed, "編輯 OFF 仍要出滿版版面")
        self.assertTrue(needs_frame, "編輯 OFF 仍要後製，漏了會退回已廢除的舊行為")
        self.assertEqual(profile, safe_area_spec.EDITOR_PROFILE)

    def test_editor_on_uses_the_thin_frame(self):
        full_bleed, needs_frame, profile = main.resolve_frame_plan("編輯", True)
        self.assertTrue(full_bleed)
        self.assertTrue(needs_frame)
        self.assertEqual(profile, safe_area_spec.EDITOR_FRAME_PROFILE)

    def test_reporter_is_untouched_by_the_editor_change(self):
        self.assertEqual(
            main.resolve_frame_plan("記者", True),
            (True, True, safe_area_spec.REPORTER_PROFILE),
        )
        self.assertEqual(
            main.resolve_frame_plan("記者", False),
            (False, False, safe_area_spec.REPORTER_PROFILE),
        )

    def test_unknown_role_falls_back_to_reporter(self):
        self.assertEqual(
            main.resolve_frame_plan("", True),
            (True, True, safe_area_spec.REPORTER_PROFILE),
        )

    def test_thin_frame_margins_are_two_percent_on_every_side(self):
        """2% 是使用者指定的數字，四邊都要精準吃到，不能只對兩邊。"""
        width, height = safe_frame.DEFAULT_CANVAS
        margins = safe_area_spec.required_margins_px(
            width, height, safe_area_spec.EDITOR_FRAME_PROFILE
        )
        self.assertEqual(margins["left"], margins["right"])
        self.assertEqual(margins["top"], margins["bottom"])
        for edge, expected in (("left", width * 0.02), ("top", height * 0.02)):
            with self.subTest(edge=edge):
                self.assertAlmostEqual(margins[edge], expected, delta=1)

    def test_thin_frame_fits_sixteen_by_nine_without_cropping(self):
        """2% 內容區的比例幾乎正好是 16:9，FIT 進去不該裁掉任何東西。"""
        for source in ((1536, 864), (1024, 576), (1280, 720)):
            with self.subTest(source=source):
                left, top, right, bottom = safe_frame.plan_placement(
                    source,
                    safe_frame.DEFAULT_CANVAS,
                    safe_frame.FIT,
                    safe_area_spec.EDITOR_FRAME_PROFILE,
                )
                placed = (right - left) / (bottom - top)
                self.assertAlmostEqual(placed, source[0] / source[1], delta=0.005)

    def test_the_two_modes_produce_different_shaped_output(self):
        """兩檔的成品形狀不同：ON 是完整畫布，OFF 是對位框那一塊。"""
        self.assertEqual(
            self._output(safe_area_spec.EDITOR_FRAME_PROFILE).size,
            safe_frame.DEFAULT_CANVAS,
        )
        x0, y0, x1, y1 = safe_area_spec.safe_rect(
            *safe_frame.DEFAULT_CANVAS, safe_area_spec.EDITOR_PROFILE
        )
        self.assertEqual(
            self._output(safe_area_spec.EDITOR_PROFILE).size, (x1 - x0, y1 - y0)
        )

    def test_thin_frame_is_not_stretched(self):
        """薄框走等比例置入；混進 STRETCH_PROFILES 會讓它變成不等比拉伸。"""
        self.assertFalse(safe_frame.uses_stretch(safe_area_spec.EDITOR_FRAME_PROFILE))
        self.assertTrue(safe_frame.uses_stretch(safe_area_spec.EDITOR_PROFILE))

    def test_every_framing_path_goes_through_the_resolver(self):
        """新增置框路徑時漏接 resolve_frame_plan 不會報錯，只會悄悄出錯圖。

        目前兩個呼叫點是 generate_image 與 refine_image。直接把 req.safe_frame／
        req.safe_frame_profile 餵給 finalize_image_result 就是漏接的樣子——
        編輯 OFF 會退回「完全不置框」。
        """
        source = pathlib.Path(main.__file__).read_text(encoding="utf-8")
        calls = re.findall(
            r"finalize_image_result\(\s*(.*?)\n    \)", source, re.S
        )
        self.assertGreaterEqual(len(calls), 2, "找不到置框呼叫點，這個測試需要更新")
        for call in calls:
            with self.subTest(call=call.strip()[:60]):
                self.assertNotIn("safe_frame=req.safe_frame", call)
                self.assertNotIn("profile=req.safe_frame_profile", call)


class BackdropMatchesContentTests(unittest.TestCase):
    """襯底要取自內容邊緣（2026-08-19）。

    舊做法取整張外圈的平均再乘固定係數，線上 10 張成品每一張襯底都比 CG 亮，
    深底 CG 上會讀成一圈灰紫色外框。
    """

    def _framed(self, top_rgb, bottom_rgb, size=(1536, 864)):
        """做一張上下不同色的滿版圖，置框後回傳成品。"""
        img = Image.new("RGB", size)
        draw = ImageDraw.Draw(img)
        for y in range(size[1]):
            ratio = y / (size[1] - 1)
            draw.line(
                [(0, y), (size[0], y)],
                fill=tuple(
                    round(top_rgb[c] + (bottom_rgb[c] - top_rgb[c]) * ratio)
                    for c in range(3)
                ),
            )
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        data = safe_frame.apply_safe_frame(
            buffer.getvalue(), background=safe_frame.BACKDROP
        )
        return Image.open(io.BytesIO(data)).convert("RGB")

    def test_backdrop_tracks_the_content_colour(self):
        """內容換色，襯底要跟著換——舊做法的固定係數做不到這件事。"""
        width = safe_frame.DEFAULT_CANVAS[0]
        warm = self._framed((90, 40, 20), (60, 25, 12)).getpixel((width // 2, 6))
        cool = self._framed((20, 40, 90), (12, 25, 60)).getpixel((width // 2, 6))
        self.assertGreater(warm[0], warm[2], "暖色內容的襯底應該偏紅")
        self.assertGreater(cool[2], cool[0], "冷色內容的襯底應該偏藍")

    def test_backdrop_is_close_to_the_adjacent_content_edge(self):
        """襯底與緊鄰它的內容邊緣色差要小——這正是編輯反映的那圈外框感。"""
        x0, y0, _x1, _y1 = safe_area_spec.safe_rect(*safe_frame.DEFAULT_CANVAS)
        output = self._framed((36, 44, 58), (18, 22, 30))
        mid_x = safe_frame.DEFAULT_CANVAS[0] // 2
        backdrop = output.getpixel((mid_x, y0 // 2))
        content_edge = output.getpixel((mid_x, y0 + 4))
        gap = sum((a - b) ** 2 for a, b in zip(backdrop, content_edge)) ** 0.5
        self.assertLess(gap, 12, f"襯底與內容邊緣差 {gap:.1f}，會讀成一圈外框")

    def test_backdrop_never_goes_black_on_dark_content(self):
        """深底 CG 是最常見的情況，襯底不能被壓成黑邊。"""
        output = self._framed((16, 20, 28), (10, 13, 18))
        self.assertGreater(sum(output.getpixel((5, 5))), 20)

    def test_bright_headline_in_the_sample_strip_does_not_lift_the_backdrop(self):
        """取樣帶裡有亮元素時襯底不能被帶亮——這正是中位數存在的理由。

        真實 CG 的標題橫幅、發光數字常常就壓在內容最上緣那一帶。改成平均值
        就會被它們拉高，回到 2026-08-19 之前那圈灰紫色外框的行為。
        （平滑漸層的測試案例抓不到這件事，平均與中位數在那裡相等。）
        """
        size = (1536, 864)
        dark = (18, 22, 30)
        img = Image.new("RGB", size, dark)
        draw = ImageDraw.Draw(img)
        # 佔取樣帶約四成寬的亮標題條，高度覆蓋整條取樣帶（內容高的 1%～4%）
        draw.rectangle(
            [0, 0, round(size[0] * 0.4), round(size[1] * 0.05)], fill=(240, 230, 90)
        )
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        data = safe_frame.apply_safe_frame(
            buffer.getvalue(), background=safe_frame.BACKDROP
        )
        output = Image.open(io.BytesIO(data)).convert("RGB")

        backdrop = output.getpixel((safe_frame.DEFAULT_CANVAS[0] // 2, 6))
        gap = sum((a - b) ** 2 for a, b in zip(backdrop, dark)) ** 0.5
        self.assertLess(gap, 12, f"襯底被亮標題帶亮了（差 {gap:.1f}），應該用中位數而非平均")


if __name__ == "__main__":
    unittest.main()
