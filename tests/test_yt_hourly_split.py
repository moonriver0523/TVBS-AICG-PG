"""YT 整點直播「雙切」合成（WP2 第一階段，2026-09-08 使用者裁決）。

守的紅線：
1. **四行同一字級。** 使用者對「兩邊字不一樣大」零容忍；長短標題混在一起時，
   四行一律吃四者的最小值，不是各自撐滿自己那一行。
2. **每格的標題留在自己半格。** 靠左貼各自半格的左緣，右緣（含描邊）不得越過中線；
   縮到最小字級仍塞不下時要當場丟 ComposeError，不能默默伸進另一格。
3. **日期紅條只畫一次、在左半格。** 右半格整條掃不到日期紅。
4. 兩格各自的「AI示意圖」：左格那個要收在左半格內。
"""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compose  # noqa: E402

WIDTH, HEIGHT = compose.YT_CANVAS
MID = WIDTH // 2


def _panel(colour: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (800, 800), colour)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


BLACK = _panel((0, 0, 0))
GREY = _panel((40, 40, 40))

BASE = dict(
    left_line1="尼泊爾洪災逾1380死",
    left_line2="家屬赴總理府抗議",
    right_line1="直播帶貨美國爆紅",
    right_line2="砸數十億美元",
    date_text="2026/09/08",
    time_text="20:00",
)


def _compose(**overrides) -> bytes:
    kwargs = dict(BASE)
    kwargs.update(overrides)
    return compose.compose_yt_hourly_split_cover(BLACK, GREY, **kwargs)


def _capture(**overrides):
    """攔下四次標題繪製，回傳 [(x, baseline, text, font), ...]（不畫，只記）。"""
    calls = []

    def record(draw, xy, text, font, fill, anchor="ms"):
        calls.append((xy[0], xy[1], text, font, fill, anchor))

    with patch.object(compose, "_draw_yt_title_line", record):
        _compose(**overrides)
    return calls


class HourlySplitLayoutTest(unittest.TestCase):
    def test_canvas_size(self):
        with Image.open(io.BytesIO(_compose())) as image:
            self.assertEqual(image.size, compose.YT_CANVAS)

    def test_four_lines_share_one_font_size(self):
        calls = _capture()
        self.assertEqual(len(calls), 4)
        sizes = {font.size for _, _, _, font, _, _ in calls}
        self.assertEqual(len(sizes), 1, f"四行字級不一致：{sizes}")

    def test_shared_size_is_the_smallest_that_fits(self):
        """最長的那一行決定四行的字級：其他三行短也不會各自撐大。"""
        all_short = {
            font.size for _, _, _, font, _, _ in
            _capture(left_line1="洪災", left_line2="抗議", right_line1="帶貨", right_line2="爆紅")
        }
        one_long = {font.size for _, _, _, font, _, _ in _capture(left_line2="抗議", right_line2="爆紅")}
        self.assertEqual(len(all_short), 1)
        self.assertEqual(len(one_long), 1)
        self.assertLess(one_long.pop(), all_short.pop())

    def test_each_panel_title_stays_in_its_own_half(self):
        calls = _capture()
        gap = round(WIDTH * compose.YT_HOURLY_SPLIT_GAP_RATIO)
        margin = round(WIDTH * compose.YT_MARGIN_RATIO)
        for x, _, text, font, _, anchor in calls:
            self.assertEqual(anchor, "ls", "標題靠自己半格的左緣")
            right = x + font.getbbox(text)[2]
            if text.startswith(("尼泊爾", "家屬")):
                self.assertEqual(x, margin)
                self.assertLessEqual(right, MID - gap)
            else:
                self.assertEqual(x, MID + gap)
                self.assertLessEqual(right, WIDTH - margin)

    def test_two_lines_per_panel_use_the_hourly_baselines(self):
        calls = _capture()
        baselines = sorted({y for _, y, _, _, _, _ in calls})
        self.assertEqual(baselines, [
            round(HEIGHT * compose.YT_HOURLY_LINE1_BASELINE_RATIO),
            round(HEIGHT * compose.YT_HOURLY_LINE2_BASELINE_RATIO),
        ])

    def test_line_colours_white_then_yellow_in_both_panels(self):
        calls = _capture()
        by_baseline = {}
        for _, y, _, _, fill, _ in calls:
            by_baseline.setdefault(y, set()).add(fill)
        line1, line2 = sorted(by_baseline)
        self.assertEqual(by_baseline[line1], {compose.YT_LINE1_FILL})
        self.assertEqual(by_baseline[line2], {compose.YT_LINE2_FILL})

    def test_title_too_long_raises(self):
        with self.assertRaises(compose.ComposeError) as ctx:
            _compose(right_line1="直播帶貨在美國爆紅砸下數十億美元行銷預算搶佔市場")
        self.assertIn("半格", str(ctx.exception))

    def test_missing_line_raises(self):
        with self.assertRaises(compose.ComposeError) as ctx:
            _compose(right_line2="  ")
        self.assertIn("right_line2", str(ctx.exception))

    def test_missing_date_raises(self):
        with self.assertRaises(compose.ComposeError):
            _compose(date_text="")


class HourlySplitPixelTest(unittest.TestCase):
    @staticmethod
    def _image(**overrides) -> Image.Image:
        return Image.open(io.BytesIO(_compose(**overrides))).convert("RGB")

    def test_date_tab_only_in_left_half(self):
        image = self._image()
        rows = [y for y in range(round(HEIGHT * 0.45), round(HEIGHT * 0.80))]
        left = right = 0
        for y in rows:
            for x in range(0, WIDTH, 3):
                if image.getpixel((x, y)) == compose.YT_HOURLY_DATE_FILL:
                    if x < MID:
                        left += 1
                    else:
                        right += 1
        self.assertGreater(left, 0, "左半格應該有日期紅條")
        self.assertEqual(right, 0, "右半格不該出現日期紅條")

    def test_date_tab_sits_above_the_first_title_line(self):
        image = self._image()
        margin = round(WIDTH * compose.YT_MARGIN_RATIO)
        column = margin + 4
        reds = [y for y in range(HEIGHT) if image.getpixel((column, y)) == compose.YT_HOURLY_DATE_FILL]
        self.assertTrue(reds)
        self.assertLess(max(reds), round(HEIGHT * compose.YT_HOURLY_LINE1_BASELINE_RATIO))

    def test_white_divider_on_the_centre_line(self):
        image = self._image()
        self.assertEqual(image.getpixel((MID, 10)), compose.YT_SPLIT_LINE_FILL)
        self.assertEqual(image.getpixel((MID, HEIGHT - 10)), compose.YT_SPLIT_LINE_FILL)

    def test_each_half_keeps_its_own_background(self):
        """左格黑、右格灰：分別在兩格上方（沒有任何元素）取樣。"""
        image = self._image()
        self.assertEqual(image.getpixel((MID // 2, round(HEIGHT * 0.45))), (0, 0, 0))
        self.assertEqual(image.getpixel((MID + MID // 2, round(HEIGHT * 0.45))), (40, 40, 40))

    def test_ai_note_per_panel(self):
        """左格標、右格不標時，AI 小標的字只出現在左半格。"""
        gap = round(WIDTH * compose.YT_HOURLY_SPLIT_GAP_RATIO)
        rows = range(round(HEIGHT * compose.YT_HOURLY_AI_NOTE_TOP_RATIO),
                     round(HEIGHT * compose.YT_HOURLY_AI_NOTE_TOP_RATIO + HEIGHT * 0.06))
        plain = self._image()
        left_only = self._image(left_ai_note=True)
        right_only = self._image(right_ai_note=True)

        def changed(image, x0, x1):
            return sum(
                1 for y in rows for x in range(x0, x1, 2)
                if image.getpixel((x, y)) != plain.getpixel((x, y))
            )

        self.assertGreater(changed(left_only, 0, MID - gap), 0)
        self.assertEqual(changed(left_only, MID, WIDTH), 0)
        self.assertGreater(changed(right_only, MID, WIDTH), 0)
        self.assertEqual(changed(right_only, 0, MID), 0)

    def test_time_band_optional(self):
        """不給整點時間就不畫時間帶（LIVE 章下方維持底圖色）。"""
        with_time = self._image()
        without = self._image(time_text="")
        badge_w = round(WIDTH * compose.YT_HOURLY_BADGE_WIDTH_RATIO)
        x = WIDTH - round(WIDTH * compose.YT_MARGIN_RATIO) - badge_w // 2
        band_y = round(HEIGHT * (compose.YT_HOURLY_BADGE_TOP_RATIO + 0.20))
        self.assertEqual(without.getpixel((x, band_y)), (40, 40, 40))
        self.assertNotEqual(with_time.getpixel((x, band_y)), (40, 40, 40))


class AiNoteSignatureTest(unittest.TestCase):
    def test_existing_callers_unaffected(self):
        """`_draw_ai_note` 新增的 x1 是選填：不帶時仍貼畫面右側（滿版版型靠這個）。"""
        canvas = Image.new("RGBA", compose.YT_CANVAS, (0, 0, 0, 255))
        compose._draw_ai_note(canvas, 200)
        margin = round(WIDTH * compose.YT_MARGIN_RATIO)
        strip = canvas.convert("RGB").crop((WIDTH - margin - 200, 200, WIDTH - margin, 260))
        self.assertNotEqual(
            strip.tobytes(), Image.new("RGB", strip.size, (0, 0, 0)).tobytes(), "右側應該畫了 AI 小標"
        )


if __name__ == "__main__":
    unittest.main()
