"""2026-09-09 第五批使用者回饋的守門測試（第 1、2、6 項）。

第 3 項在 test_yt_vstrip_ui、第 4 項在 test_yt_band_variants_and_overlay 與
test_yt_title_weight、第 5 項在 test_cover_title_style。
"""

import io
import os
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class PlaceholderItalicTests(unittest.TestCase):
    """第 1 項：欄位「內」的提示文字全部斜體，使用者才知道那是提示不是已填的值。"""

    def test_the_rule_covers_both_inputs_and_textareas(self):
        self.assertIn("input::placeholder", INDEX_HTML)
        self.assertIn("textarea::placeholder", INDEX_HTML)

    def test_it_is_one_global_rule_not_a_class_on_each_field(self):
        """逐個欄位加 class 的話，之後新增欄位一定有人忘了帶。"""
        css = INDEX_HTML[INDEX_HTML.index("input::placeholder"):]
        css = css[:css.index("}") + 1]
        self.assertIn("font-style: italic", css)
        self.assertNotIn("placeholder:italic", INDEX_HTML)


class HourlyBadgeTests(unittest.TestCase):
    """第 2 項：整點直播右上的 LIVE 章與整點白框「再縮小一點點」。"""

    OLD_BADGE = 0.25
    OLD_BAND = 0.095

    def test_both_shrank_but_only_a_little(self):
        for name, now, before in (
            ("badge", compose.YT_HOURLY_BADGE_WIDTH_RATIO, self.OLD_BADGE),
            ("time band", compose.YT_HOURLY_TIME_BAND_HEIGHT_RATIO, self.OLD_BAND),
        ):
            with self.subTest(part=name):
                self.assertLess(now, before)
                self.assertGreater(now / before, 0.85, "使用者說的是「一點點」")

    def test_the_time_band_keeps_its_proportion_to_the_badge(self):
        """時間帶的寬度是從章寬推的，高度要跟著一起收，不然會變成一塊過胖的白框。"""
        self.assertAlmostEqual(
            compose.YT_HOURLY_TIME_BAND_HEIGHT_RATIO / compose.YT_HOURLY_BADGE_WIDTH_RATIO,
            self.OLD_BAND / self.OLD_BADGE,
            places=2,
        )

    def test_the_badge_still_clears_the_frame_edge(self):
        width = compose.YT_CANVAS[0]
        margin = round(width * compose.YT_MARGIN_RATIO)
        badge_w = round(width * compose.YT_HOURLY_BADGE_WIDTH_RATIO)
        self.assertGreater(width - margin - badge_w, width * 0.5, "章不該吃掉右半以上")


class AiHeaderBandMeasureTests(unittest.TestCase):
    """第 6 項：Logo 掉出標頭帶。

    根因不是 Logo 太大，是模型畫的帶比 prompt 說的一成薄（實測 62/720 = 8.6%），
    貼圖卻按寫死的 10% 算。所以量出來再貼——與挖空框同一個原則：不靠模型自律。
    """

    @staticmethod
    def _canvas(band_ratio: float, *, band=(7, 18, 56), photo=(200, 170, 120)) -> Image.Image:
        img = Image.new("RGB", (1280, 720), photo)
        band_h = round(720 * band_ratio)
        Image.new("RGB", (1280, band_h), band).convert("RGB")
        img.paste(Image.new("RGB", (1280, band_h), band), (0, 0))
        return img.convert("RGBA")

    def test_it_measures_a_band_thinner_than_the_prompt_asked_for(self):
        self.assertEqual(compose.measure_ai_header_band(self._canvas(0.086)), round(720 * 0.086))

    def test_it_measures_a_band_thicker_than_the_prompt_asked_for(self):
        self.assertEqual(compose.measure_ai_header_band(self._canvas(0.125)), round(720 * 0.125))

    def test_an_absurd_result_falls_back_to_the_prompt_figure(self):
        """量到 2% 或 30% 就是量錯了（模型多畫了裝飾，或帶跟照片同色）。
        寧可退回寫死的一成，也不要把 Logo 貼成一條線或蓋掉半張圖。"""
        fallback = round(720 * compose.COVER_AI_HEADER_RATIO)
        for ratio in (0.02, 0.30):
            with self.subTest(ratio=ratio):
                self.assertEqual(compose.measure_ai_header_band(self._canvas(ratio)), fallback)

    def test_a_band_that_never_departs_falls_back_too(self):
        """整張都同一個深藍（模型把照片也畫暗了）：量不到邊界就退回一成。"""
        plain = Image.new("RGB", (1280, 720), (7, 18, 56)).convert("RGBA")
        self.assertEqual(
            compose.measure_ai_header_band(plain), round(720 * compose.COVER_AI_HEADER_RATIO)
        )

    def test_the_logo_lands_inside_the_measured_band(self):
        """真正要守的東西：貼完之後 Logo 的下緣還在帶子裡面。"""
        band_ratio = 0.086
        canvas = self._canvas(band_ratio)
        buffer = io.BytesIO()
        canvas.convert("RGB").save(buffer, format="PNG")
        out = Image.open(io.BytesIO(compose.paste_cover_logo(buffer.getvalue()))).convert("RGB")
        band_h = round(720 * band_ratio)
        # 帶子底下那一列（照片區）在貼圖前後都該是照片色——Logo 沒有戳出去
        for y in range(band_h + 1, band_h + 12):
            for x in range(4, 400, 37):
                with self.subTest(x=x, y=y):
                    self.assertEqual(out.getpixel((x, y)), (200, 170, 120))

    def test_the_ai_note_also_follows_the_measured_band(self):
        """「AI示意圖」小標貼在帶子下方，用的必須是同一個量出來的高度，
        不然帶薄的時候小標會浮在帶子裡面。"""
        source = (ROOT / "compose.py").read_text(encoding="utf-8")
        note = source[source.index("def paste_cover_ai_note"):]
        note = note[:note.index("def paste_cover_highlight_stamp")]
        self.assertIn("measure_ai_header_band(canvas)", note)
        self.assertNotIn("height * COVER_AI_HEADER_RATIO", note)


if __name__ == "__main__":
    unittest.main()
