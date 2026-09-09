"""2026-09-09 第五批使用者回饋的守門測試（第 1、2、6 項）。

第 3 項在 test_yt_vstrip_ui、第 4 項在 test_yt_band_variants_and_overlay 與
test_yt_title_weight、第 5 項在 test_cover_title_style。
"""

import io
import os
import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

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


class AiHeaderBandTests(unittest.TestCase):
    """第 6 項：Logo 掉出標頭帶。

    第一版量到帶薄（實測 58/720 = 8.1%）就把 Logo 縮小去遷就，使用者退回：
    「應該要藍框區域稍微變大一點點，你現在變成把 LOGO 那些縮太小才是問題。」
    所以改成把**帶補厚**到 COVER_AI_HEADER_RATIO，Logo 照補完的帶高算。
    """

    BAND = (7, 18, 56)
    RULE = (20, 150, 250)
    PHOTO = (200, 170, 120)

    @classmethod
    def _canvas(cls, band_ratio: float, *, rule: int = 3) -> Image.Image:
        img = Image.new("RGB", (1280, 720), cls.PHOTO)
        top = round(720 * band_ratio)
        img.paste(Image.new("RGB", (1280, top), cls.BAND), (0, 0))
        img.paste(Image.new("RGB", (1280, rule), cls.RULE), (0, top))
        return img.convert("RGBA")

    @staticmethod
    def _bytes(canvas: Image.Image) -> bytes:
        buffer = io.BytesIO()
        canvas.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()

    # ---- 量 ----

    def test_it_measures_the_bottom_of_the_band_including_its_hairline(self):
        """量的是**帶底**（含底部亮線），不是帶身結束處——後面壓小標／圓章的都靠這個。"""
        canvas = self._canvas(0.086)
        self.assertEqual(compose.measure_ai_header_band(canvas), round(720 * 0.086) + 3)

    def test_an_absurd_result_falls_back_to_the_prompt_figure(self):
        fallback = round(720 * compose.COVER_AI_HEADER_RATIO)
        for ratio in (0.02, 0.30):
            with self.subTest(ratio=ratio):
                self.assertEqual(compose.measure_ai_header_band(self._canvas(ratio)), fallback)

    def test_a_band_that_never_departs_falls_back_too(self):
        plain = Image.new("RGB", (1280, 720), self.BAND).convert("RGBA")
        self.assertIsNone(compose._probe_ai_header_band(plain))
        self.assertEqual(
            compose.measure_ai_header_band(plain), round(720 * compose.COVER_AI_HEADER_RATIO)
        )

    # ---- 補 ----

    def test_a_thin_band_is_filled_out_to_the_target(self):
        canvas = self._canvas(0.081)
        target = round(720 * compose.COVER_AI_HEADER_RATIO)
        self.assertEqual(compose.ensure_ai_header_band(canvas), target)
        px = canvas.convert("RGB").load()
        self.assertEqual(px[640, target - 2], self.RULE, "底部亮線要整條搬下來，不是被填掉")
        self.assertEqual(px[640, target - 12], self.BAND, "中間補的是帶身色")
        self.assertEqual(px[640, target + 2], self.PHOTO, "照片只被吃掉最上面那幾列")

    def test_a_band_the_model_drew_thick_enough_is_left_alone(self):
        canvas = self._canvas(0.13)
        before = canvas.tobytes()
        self.assertEqual(compose.ensure_ai_header_band(canvas), round(720 * 0.13) + 3)
        self.assertEqual(canvas.tobytes(), before, "夠厚就不要動它")

    def test_nothing_is_painted_when_the_band_cannot_be_measured(self):
        """量不到就不准動手畫：連帶在哪裡都不知道，補一塊深藍很可能蓋掉模型畫的東西。"""
        canvas = Image.new("RGB", (1280, 720), self.BAND).convert("RGBA")
        before = canvas.tobytes()
        self.assertEqual(
            compose.ensure_ai_header_band(canvas), round(720 * compose.COVER_AI_HEADER_RATIO)
        )
        self.assertEqual(canvas.tobytes(), before)

    def test_the_fill_does_not_smear_wide_colour_blocks_downwards(self):
        """帶裡有紅標與白日期。只換「太亮」的不夠（字邊的抗鋸齒比帶身還暗），
        只做中位濾波也不夠（紅標比濾波窗寬），兩道都要在。"""
        canvas = self._canvas(0.081)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([1040, 8, 1260, 50], fill=(250, 5, 5))       # ON AIR 紅標
        draw.rectangle([900, 20, 1020, 40], fill=(255, 255, 255))   # 日期
        compose.ensure_ai_header_band(canvas)
        px = canvas.convert("RGB").load()
        target = round(720 * compose.COVER_AI_HEADER_RATIO)
        for x in (910, 980, 1100, 1200):
            with self.subTest(x=x):
                self.assertEqual(px[x, target - 12], self.BAND, "寬色塊被往下拉成一片了")

    # ---- 貼 ----

    def test_the_logo_is_not_smaller_than_before_this_fix(self):
        """260909-03 的帶高寫死一成（720 → 72），Logo 50、標籤 58。
        這次是把帶補厚，不是把 Logo 縮小——所以只能更大，不能更小。"""
        band = round(720 * compose.COVER_AI_HEADER_RATIO)
        inner = band - round(band * compose.COVER_AI_HEADER_CLEARANCE)
        self.assertGreaterEqual(round(inner * 0.70), 50)
        self.assertGreaterEqual(round(inner * 0.80), 58)
        self.assertGreater(compose.COVER_AI_HEADER_RATIO, 0.10, "藍框要比原本大一點點")

    def test_the_logo_lands_inside_the_thickened_band(self):
        out = Image.open(
            io.BytesIO(compose.paste_cover_logo(self._bytes(self._canvas(0.081))))
        ).convert("RGB")
        target = round(720 * compose.COVER_AI_HEADER_RATIO)
        px = out.load()
        for y in range(target + 4, target + 16):
            for x in range(4, 400, 37):
                with self.subTest(x=x, y=y):
                    self.assertEqual(px[x, y], self.PHOTO, "Logo 或標籤戳出帶外了")
        ink = [y for y in range(target) if any(sum(px[x, y]) > 400 for x in range(4, 400, 3))]
        self.assertTrue(ink, "左半根本沒貼上東西")
        self.assertGreater(max(ink) - min(ink), 40, "Logo／標籤被縮小了")

    def test_the_ai_note_and_stamp_follow_the_thickened_band(self):
        """三支是串起來跑的（main.py 3616→3620→3624）：Logo 補厚之後，
        小標與圓章再量一次要拿到補完的新帶底，不是原本那條薄帶。"""
        canvas = self._canvas(0.081)
        after_logo = compose.paste_cover_logo(self._bytes(canvas))
        measured = compose.measure_ai_header_band(
            Image.open(io.BytesIO(after_logo)).convert("RGBA")
        )
        self.assertEqual(measured, round(720 * compose.COVER_AI_HEADER_RATIO))


class HeaderBandPromptTests(unittest.TestCase):
    """prompt 裡的帶高不准手寫——compose 補帶用的是常數，兩邊各寫各的就會脫鉤。"""

    def test_both_templates_quote_the_constant(self):
        import editor_formats

        wanted = f"about {round(compose.COVER_AI_HEADER_RATIO * 100)}% of the frame height"
        for name in ("COVER_AI_PROMPT_TEMPLATE", "COVER_AI_FULL_PROMPT_TEMPLATE"):
            with self.subTest(template=name):
                template = getattr(editor_formats, name)
                self.assertIn(wanted, template)
                self.assertNotIn("one tenth", template)
                self.assertNotIn("%HEADER_BAND%", template)


if __name__ == "__main__":
    unittest.main()
