"""YT 24H LIVE 版型的合成（2026-09-13）。

角標是一張**定版的生成素材**，程式只在它的玻璃日期板上壓日期。日期框的比例是相對
那一份 2675×1225 裁切量的，所以這裡把素材尺寸釘死——有人重新去背／重裁 PNG 時
會當場失敗，而不是悄悄讓日期掉到鉚金屬框上（誰都不會注意到）。

規格與量測來源見 docs/plan-20260913-live24版型.md。
"""
import io
import pathlib
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import compose  # noqa: E402


def _bg(size=(1920, 1080), colour=(60, 72, 94)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _render(**kwargs) -> Image.Image:
    base = {"title": "東北季風剩1天 假日回溫", "date_text": "2026.09.13"}
    base.update(kwargs)
    png = compose.compose_yt_live24_cover(_bg(), **base)
    return Image.open(io.BytesIO(png)).convert("RGB")


class AssetTests(unittest.TestCase):
    def test_the_badge_asset_is_in_the_repo(self):
        """放 D:\\Downloads 的話 Cloud Run 上根本沒有這個檔。"""
        self.assertTrue(compose.LIVE24_BADGE.exists(), compose.LIVE24_BADGE)
        self.assertTrue(compose.TVBS_LOGO_NEWS_WHITE.exists(), compose.TVBS_LOGO_NEWS_WHITE)

    def test_the_badge_is_still_the_exact_crop_the_date_box_was_measured_against(self):
        with Image.open(compose.LIVE24_BADGE) as badge:
            self.assertEqual(badge.size, compose.LIVE24_BADGE_SIZE)

    def test_the_badge_has_an_alpha_channel(self):
        """去背沒了就會在封面上壓出一塊綠幕方塊。"""
        with Image.open(compose.LIVE24_BADGE) as badge:
            self.assertIn("A", badge.convert("RGBA").getbands())
            self.assertLess(
                min(badge.convert("RGBA").split()[3].getextrema()), 10,
                "角標四周應該是全透明的",
            )

    def test_a_resized_badge_is_rejected_rather_than_silently_misplacing_the_date(self):
        import unittest.mock as mock
        shrunk = Image.open(compose.LIVE24_BADGE).convert("RGBA").resize((1337, 612))
        with mock.patch.object(compose.Image, "open", return_value=shrunk):
            with self.assertRaises(compose.ComposeError) as cm:
                compose._paste_live24_badge(
                    Image.new("RGBA", (1920, 1080)), (0, 0), 595, "2026.09.13"
                )
        self.assertIn("重量", str(cm.exception))


class DateStampTests(unittest.TestCase):
    def test_the_date_lands_inside_the_glass_not_on_the_bezel(self):
        """日期框已內縮避開 V2 那圈粗鉚金屬框——壓到框上是這個版型最可能的走樣。"""
        with Image.open(compose.LIVE24_BADGE) as badge_file:
            badge = badge_file.convert("RGBA")
        stamped = compose._stamp_live24_date(badge, "2026.09.13")
        l, t, r, b = compose.LIVE24_BADGE_DATE_BOX
        w, h = stamped.size
        box = (round(w * l), round(h * t), round(w * r), round(h * b))
        # 白字只能出現在框內：框外多出來的白像素代表壓到框上或溢出板外
        before = badge.convert("RGB")
        after = stamped.convert("RGB")
        bp, ap = before.load(), after.load()
        outside = 0
        for y in range(0, h, 3):
            for x in range(0, w, 3):
                if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                    continue
                if bp[x, y] != ap[x, y]:
                    outside += 1
        self.assertEqual(outside, 0, f"日期在框外改了 {outside} 個取樣點")

    def test_an_empty_date_is_rejected(self):
        with Image.open(compose.LIVE24_BADGE) as badge_file:
            badge = badge_file.convert("RGBA")
        with self.assertRaises(compose.ComposeError):
            compose._stamp_live24_date(badge, "   ")

    def test_the_date_format_uses_dots_not_slashes(self):
        """hourly 是 %Y/%m/%d；照抄會跟實際播出不一致（2026-09-11 memo 明文警告）。"""
        self.assertEqual(compose.LIVE24_DATE_FORMAT, "%Y.%m.%d")


class CoverTests(unittest.TestCase):
    def test_it_renders_a_1920x1080_cover(self):
        self.assertEqual(_render().size, compose.YT_CANVAS)

    def test_an_empty_title_is_rejected(self):
        with self.assertRaises(compose.ComposeError):
            _render(title="   ")

    def test_a_title_too_long_for_one_line_is_rejected(self):
        """單行版型，縮到最小字級、壓到最扁還是塞不下就得擋——不能讓字被畫框裁掉。"""
        with self.assertRaises(compose.ComposeError) as cm:
            _render(title="東" * 30)
        self.assertIn("單行版型", str(cm.exception))

    def test_the_template_length_title_fits(self):
        """範本上那句就是這個版型的實際長度，它一定要過。"""
        _render(title="東北季風剩1天 假日回溫")

    def test_a_sixteen_character_title_still_fits_thanks_to_the_squeeze(self):
        """不壓縮的話 15 字就塞不下了——橫向壓縮就是為了撐到範本的字級與字數。"""
        _render(title="熱浪襲西班牙馬德里太陽門搭遮陽棚")

    def test_the_title_is_red_and_sits_in_the_lower_half(self):
        image = _render()
        w, h = image.size
        px = image.load()
        fill = compose.LIVE24_TITLE_FILL
        # 角標自己的立體紅 LIVE 也在這個紅色容差內，要先把左上那塊排掉
        badge_r = round(w * (compose.LIVE24_BADGE_LEFT_RATIO + compose.LIVE24_BADGE_WIDTH_RATIO))
        badge_b = round(h * 0.45)
        hits = [
            (x, y)
            for y in range(0, h, 4)
            for x in range(0, w, 4)
            if not (x <= badge_r and y <= badge_b)
            and all(abs(px[x, y][i] - fill[i]) <= 26 for i in range(3))
        ]
        self.assertGreater(len(hits), 200, "找不到標題紅字")
        self.assertGreater(min(y for _, y in hits) / h, 0.55, "標題不該爬到畫面上半")

    def test_the_title_slants_up_to_the_right(self):
        """範本量到 +3.5°。畫成水平的就不是這個版型。"""
        image = _render()
        w, h = image.size
        px = image.load()
        fill = compose.LIVE24_TITLE_FILL

        def top_of(x_range):
            for y in range(round(h * 0.5), h):
                for x in x_range:
                    if all(abs(px[x, y][i] - fill[i]) <= 26 for i in range(3)):
                        return y
            return None

        left = top_of(range(round(w * 0.06), round(w * 0.16)))
        right = top_of(range(round(w * 0.70), round(w * 0.80)))
        self.assertIsNotNone(left)
        self.assertIsNotNone(right)
        self.assertLess(right, left, "右端應該比左端高")

    def test_the_badge_and_the_logo_do_not_overlap(self):
        """角標在左上、Logo 在右上，兩者一碰就是版面壞掉。"""
        w = compose.YT_CANVAS[0]
        badge_right = round(w * compose.LIVE24_BADGE_LEFT_RATIO) + round(
            w * compose.LIVE24_BADGE_WIDTH_RATIO
        )
        logo_left = round(w * compose.LIVE24_LOGO_RIGHT_RATIO) - round(
            w * compose.LIVE24_LOGO_WIDTH_RATIO
        )
        self.assertLess(badge_right, logo_left)

    def test_the_ai_note_sits_on_the_left_under_the_badge(self):
        """右上被 Logo 佔走了，沿用 hourly 那支靠右的會直接壓在 Logo 上。"""
        plain = _render(ai_note=False)
        noted = _render(ai_note=True)
        w, h = plain.size
        pp, np_ = plain.load(), noted.load()
        changed = [
            (x, y)
            for y in range(0, h, 2)
            for x in range(0, w, 2)
            if pp[x, y] != np_[x, y]
        ]
        self.assertTrue(changed, "ai_note=True 應該要多畫東西")
        self.assertLess(max(x for x, _ in changed) / w, 0.5, "小標應該在畫面左半")
        self.assertLess(max(y for _, y in changed) / h, 0.5, "小標應該在上半，貼在角標下方")


if __name__ == "__main__":
    unittest.main()
