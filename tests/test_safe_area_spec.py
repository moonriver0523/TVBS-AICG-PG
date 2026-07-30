"""安全框規格與量測工具的幾何正確性。

安全框數值是後續所有驗收與（Phase A）程式化置框的基準，算錯會讓整條驗收線失效，
所以用官方文件的原始像素座標當回歸基準。量測工具則用合成圖驗證——
合成圖的內容邊界是已知真值，可以精確斷言。
"""

import importlib.util
import pathlib
import tempfile
import unittest

from PIL import Image, ImageDraw

import safe_area_spec

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    """scripts/ 不是套件，用路徑載入。"""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measure_safe_area = _load("measure_safe_area")
make_safe_frame_guide = _load("make_safe_frame_guide")


class SpecGeometryTests(unittest.TestCase):
    def test_base_canvas_matches_official_pixels(self):
        """1920×1080 換算回去必須正好等於官方座標 X=140 Y=109 W=1634 H=751。"""
        x0, y0, x1, y1 = safe_area_spec.safe_rect(1920, 1080)
        self.assertEqual((x0, y0), (140, 109))
        self.assertEqual((x1 - x0, y1 - y0), (1634, 751))

    def test_vertical_fractions_use_height_not_width(self):
        """上下留白必須按高度換算。

        docs/examples/tvbs-safe-frame-locked-tool.md 第 31 行的 1280×720 換算
        （上≈129／下≈261）是把垂直比例乘到寬度上的算錯結果，這裡釘住正確值。
        """
        margins = safe_area_spec.required_margins_px(1280, 720)
        self.assertEqual(margins, {"top": 73, "left": 93, "right": 97, "bottom": 147})

    def test_bottom_margin_is_deepest(self):
        fractions = safe_area_spec.MARGIN_FRACTIONS
        self.assertGreater(fractions["bottom"], fractions["top"])
        self.assertGreater(fractions["bottom"], fractions["left"])
        self.assertGreater(fractions["bottom"], fractions["right"])


class VerdictTests(unittest.TestCase):
    def test_content_inside_safe_area_passes(self):
        self.assertEqual(safe_area_spec.verdict_for_edge("bottom", 0.21), "pass")

    def test_content_intruding_fails(self):
        # 實測案例：docs/error-cases/2026-07-29-LINE-GPT烏克蘭 底部僅 10.1%
        self.assertEqual(safe_area_spec.verdict_for_edge("bottom", 0.101), "fail")

    def test_excessive_margin_flagged_wasteful(self):
        # 實測案例：恩智浦左右 26%，需求 7.29%
        self.assertEqual(safe_area_spec.verdict_for_edge("left", 0.26), "wasteful")

    def test_tolerance_absorbs_edge_noise(self):
        just_under = safe_area_spec.MARGIN_FRACTIONS["top"] - 0.002
        self.assertEqual(safe_area_spec.verdict_for_edge("top", just_under), "pass")

    def test_summary_reports_failed_edges_only(self):
        measured = {"top": 0.15, "left": 0.10, "right": 0.10, "bottom": 0.05}
        summary = safe_area_spec.summarize(measured)
        self.assertEqual(summary["failed_edges"], ["bottom"])
        self.assertEqual(summary["overall"], "fail")


class MeasurementTests(unittest.TestCase):
    def measure_synthetic(self, box: tuple[int, int, int, int], size=(1280, 720)):
        """畫一個已知座標的白色方塊在黑底上，量回來的 bbox 應該對得上。"""
        img = Image.new("RGB", size, (0, 0, 0))
        ImageDraw.Draw(img).rectangle(box, fill=(255, 255, 255))
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "synthetic.png"
            img.save(path)
            return measure_safe_area.measure(path)

    def test_detects_known_content_box(self):
        result = self.measure_synthetic((200, 150, 900, 500))
        left, top, right, bottom = result["content_bbox"]
        # 邊緣濾波會讓邊界落在方塊輪廓上，容許 ±2 像素
        self.assertAlmostEqual(left, 200, delta=2)
        self.assertAlmostEqual(top, 150, delta=2)
        self.assertAlmostEqual(right, 900, delta=2)
        self.assertAlmostEqual(bottom, 500, delta=2)

    def test_content_inside_safe_rect_passes_all_edges(self):
        x0, y0, x1, y1 = safe_area_spec.safe_rect(1280, 720)
        result = self.measure_synthetic((x0 + 5, y0 + 5, x1 - 5, y1 - 5))
        self.assertEqual(result["overall"], "pass", result["measured_pct"])

    def test_content_breaking_bottom_line_fails(self):
        x0, y0, x1, _ = safe_area_spec.safe_rect(1280, 720)
        result = self.measure_synthetic((x0 + 5, y0 + 5, x1 - 5, 700))
        self.assertEqual(result["verdicts"]["bottom"], "fail")
        self.assertEqual(result["overall"], "fail")

    def test_blank_image_reports_error_instead_of_bogus_numbers(self):
        img = Image.new("RGB", (640, 360), (20, 20, 20))
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "blank.png"
            img.save(path)
            self.assertIn("error", measure_safe_area.measure(path))


class GuideImageTests(unittest.TestCase):
    def test_wireframe_blocks_stay_inside_safe_area(self):
        """引導圖自己若違規，整個實驗就無效——這是最基本的自我一致性檢查。"""
        img = make_safe_frame_guide.make_wireframe(1280, 720)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "wireframe.png"
            img.save(path)
            result = measure_safe_area.measure(path)
        self.assertEqual(result["failed_edges"], [], result["measured_pct"])

    def test_edit_mask_is_transparent_exactly_inside_safe_area(self):
        """遮罩透明區＝允許作畫區，必須正好等於安全框。"""
        mask = make_safe_frame_guide.make_edit_mask(1280, 720)
        x0, y0, x1, y1 = safe_area_spec.safe_rect(1280, 720)
        alpha = mask.getchannel("A")
        self.assertEqual(alpha.getpixel((x0 + 1, y0 + 1)), 0)
        self.assertEqual(alpha.getpixel((x1 - 2, y1 - 2)), 0)
        self.assertEqual(alpha.getpixel((x0 - 5, y0 - 5)), 255)
        self.assertEqual(alpha.getpixel((x1 + 5, y1 + 5)), 255)

    def test_guide_images_contain_no_text(self):
        """引導圖只由純色矩形組成，顏色種類極少；若日後有人加上文字會立刻被抓到。"""
        for variant in ("twotone", "chroma", "wireframe"):
            img = make_safe_frame_guide.build(variant, 1280, 720)
            self.assertLessEqual(
                len(img.convert("RGB").getcolors(maxcolors=256) or []),
                3,
                f"{variant} 顏色數異常，引導圖不得含文字或漸層",
            )


if __name__ == "__main__":
    unittest.main()
