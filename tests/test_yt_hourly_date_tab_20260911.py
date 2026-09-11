"""整點直播的日期牌：撞標題的修正，以及日期牌創意階梯（2026-09-11）。

**事故**：AI 畫標題時紅色日期條壓到標題。根因不是日期條放錯位置，也不是標題太大——
程式貼日期條用的是固定絕對座標，而 prompt 只說「留一條在標題第一行**正上方**」，
那個位置由模型自己決定。同一份 prompt 的另外兩條保留區都錨在畫面角落，所以從來
沒撞過；只有日期這條沒有絕對錨點。

**創意階梯**（使用者裁決）：
- 0 級＝程式畫牌、程式壓字、位置固定（原行為，一個像素都沒變）。
- 1–4 級＝整個牌交給生圖模型：紅框、風格、位置、**連日期數字**都是它畫的。
  使用者知道這違反 compose.py 開頭第二條（日期只能是圖層合成），也知道代價
  ——日期畫錯一碼在成品上看起來完全正常。降風險的做法是把日期塞進
  TEXT TO RENDER 的逐字清單，並**拆掉**HARD CONSTRAINTS 裡那句「no dates」。
"""

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402

DATE = "2026/09/12"
BOX = compose.YT_HOURLY_DATE_TAB_BOX


def clause(level: int) -> str:
    return editor_formats.yt_hourly_date_clause(level, BOX, DATE)


def _band(text: str) -> tuple[float, float]:
    match = re.search(r"TOP edge at (\d+)% of the frame HEIGHT.*?BOTTOM edge at (\d+)%", text)
    assert match, "找不到保留區的高度範圍"
    return int(match.group(1)) / 100, int(match.group(2)) / 100


def _headline_floor() -> float:
    match = re.search(
        r"at or below (\d+)% of the frame height", editor_formats.YT_COVER_FULL_PROMPT_HOURLY
    )
    assert match, "找不到標題第一行的字頂下限"
    return int(match.group(1)) / 100


class LevelZeroReservationTests(unittest.TestCase):
    """0 級：程式貼牌，模型只要把那塊留白——而且留的要正好是程式貼的地方。"""

    def test_the_reserved_band_covers_where_the_tab_is_pasted(self):
        low, high = _band(clause(0))
        self.assertLessEqual(low, BOX[1], "保留區上緣比日期牌還低")
        self.assertGreaterEqual(high, BOX[3], "保留區下緣蓋不住日期牌")

    def test_the_reserved_band_is_wide_enough(self):
        match = re.search(r"RIGHT edge at (\d+)% of the WIDTH", clause(0))
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)) / 100, BOX[2])

    def test_the_headline_floor_sits_below_the_reserved_band(self):
        _, high = _band(clause(0))
        self.assertGreater(_headline_floor(), high)

    def test_the_model_is_still_forbidden_to_draw_a_date(self):
        self.assertIn("no dates", editor_formats.yt_hourly_date_ban(0))

    def test_the_date_is_not_in_the_verbatim_list(self):
        self.assertEqual(editor_formats.yt_hourly_date_text_line(0, DATE), "")

    def test_the_old_relative_wording_is_gone(self):
        """「directly above headline line 1」是相對位置，正是這次事故的根源。"""
        self.assertNotIn("directly above headline line 1", editor_formats.YT_COVER_FULL_PROMPT_HOURLY)
        self.assertNotIn("directly above headline line 1", clause(0))


class CreativeDatePlateTests(unittest.TestCase):
    """1–4 級：整個牌交給模型。"""

    def test_the_date_reaches_the_verbatim_render_list(self):
        """只在版面段描述牌長什麼樣是不夠的——那條「照抄、不准多寫」的約束綁在
        TEXT TO RENDER 清單上，日期沒進清單就吃不到。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                self.assertIn(DATE, editor_formats.yt_hourly_date_text_line(level, DATE))

    def test_the_no_dates_ban_is_removed_not_overridden(self):
        """矛盾要拆掉，不能靠後面覆蓋——2026-09-11 同一天踩過三次。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                self.assertEqual(editor_formats.yt_hourly_date_ban(level), "")

    def test_the_clause_quotes_the_exact_characters(self):
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                self.assertIn(DATE, clause(level))

    def test_placement_is_handed_over(self):
        """1 級起不再給座標——位置是模型的決定。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                self.assertNotIn("of the frame HEIGHT", clause(level))
                self.assertIn("YOURS TO DESIGN AND TO PLACE", clause(level))

    def test_the_paste_on_corners_stay_out_of_bounds(self):
        """位置自由不包括那兩塊——程式後貼的 Logo 與 LIVE 章會蓋掉畫在那裡的東西。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                self.assertIn("UPPER-LEFT corner", clause(level))
                self.assertIn("UPPER-RIGHT corner", clause(level))

    def test_each_level_gets_its_own_shape(self):
        shapes = {editor_formats._DATE_PLATE_STYLES[level] for level in (1, 2, 3, 4)}
        self.assertEqual(len(shapes), 4, "四級的造型描述要各自不同，否則拉桿沒有作用")
        self.assertEqual(
            len({clause(level) for level in (1, 2, 3, 4)}), 4, "造型沒有真的寫進條文"
        )

    def test_the_template_still_formats_with_every_field(self):
        """新增佔位符沒有接上呼叫端的話，format 會在線上才炸。"""
        rendered = editor_formats.YT_COVER_FULL_PROMPT_HOURLY.format(
            line1="第一行", line2="第二行", visual="場景", split_note="",
            date_clause=clause(3),
            date_text_line=editor_formats.yt_hourly_date_text_line(3, DATE),
            date_ban=editor_formats.yt_hourly_date_ban(3),
        )
        self.assertIn(DATE, rendered)
        self.assertNotIn("no dates", rendered)


class CompositeStillDrawsItTests(unittest.TestCase):
    """程式壓字那條路不能被這次改動弄壞。"""

    def _cover(self, **kwargs) -> bytes:
        import io
        from PIL import Image

        bg = Image.new("RGB", compose.YT_CANVAS, (60, 60, 60))
        buf = io.BytesIO()
        bg.save(buf, format="PNG")
        return compose.compose_yt_hourly_cover(
            buf.getvalue(), line1="東北季風剩1天", line2="假日回溫",
            date_text=DATE, **kwargs,
        )

    def _tab_has_red(self, png: bytes) -> bool:
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = img.size
        patch = img.crop((
            round(w * BOX[0]), round(h * BOX[1]), round(w * BOX[2]), round(h * BOX[3]),
        ))
        return any(
            r > 150 and g < 80 and b < 80 for r, g, b in patch.getdata()
        )

    def test_the_default_still_draws_the_tab(self):
        self.assertTrue(self._tab_has_red(self._cover()))

    def test_draw_date_false_leaves_the_area_alone(self):
        """創意 ≥1 的 AI 標題模式：牌是模型畫的，程式一筆都不能補上去。"""
        self.assertFalse(self._tab_has_red(self._cover(draw_date=False)))

    def test_the_composite_headline_never_overlaps_the_tab(self):
        """0 級兩者共存，位置必須錯開。"""
        width, height = compose.YT_CANVAS
        max_w = width - round(width * compose.YT_MARGIN_RATIO) * 2
        font = compose._yt_shared_title_font(
            ["東北季風剩1天", "假日回溫"], max_w,
            round(height * compose.YT_HOURLY_TITLE_SIZE_RATIO),
            round(height * compose.YT_TITLE_MIN_SIZE_RATIO),
        )
        baseline = round(height * compose.YT_HOURLY_LINE1_BASELINE_RATIO)
        ink_top = baseline - (font.getmetrics()[0] - font.getbbox("東北季風剩1天")[1])
        self.assertGreater(ink_top, round(height * BOX[3]), "程式壓字版的標題撞到日期牌")


if __name__ == "__main__":
    unittest.main()
