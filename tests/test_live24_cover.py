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


class EndpointTests(unittest.TestCase):
    """/api/editor/yt-cover 的 live24 分支。"""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("OPENAI_API_KEY", "test-key")
        os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

    def _post(self, payload):
        import base64
        import os
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        import main

        base = {
            "title": "東北季風剩1天 假日回溫",
            "layout": "live24",
            "date_text": "2026.09.13",
        }
        base.update(payload)

        def fake(req):
            size = (1080, 1080) if req.aspect_ratio == "1:1" else (1920, 1080)
            buffer = io.BytesIO()
            Image.new("RGB", size, (70, 80, 100)).save(buffer, format="PNG")
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
                mime_type="image/png", model="fake-model",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake) as raw, \
             patch.object(main, "supports_multiple_reference_images", return_value=True), \
             patch.object(main, "derive_yt_cover_plan", return_value={}), \
             patch.object(main, "_archive_generation", lambda **k: None):
            res = TestClient(main.app).post(
                "/api/editor/yt-cover", json=base,
                headers={"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]},
            )
        return res, raw

    def _ref(self, colour=(30, 30, 30)):
        import base64
        buffer = io.BytesIO()
        Image.new("RGB", (640, 640), colour).save(buffer, format="PNG")
        return {
            "data_url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
            "purpose": "asis",
        }

    def test_the_layout_is_registered(self):
        import editor_formats
        self.assertIn("live24", editor_formats.YT_COVER_LAYOUTS)
        self.assertEqual(
            editor_formats.EDITOR_FORMATS["yt_live24_cover"]["yt_layout"], "live24"
        )

    def test_a_plain_request_renders_a_cover(self):
        res, _ = self._post({})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["image_data_base64"])

    def test_it_defaults_to_composite_when_no_title_mode_is_sent(self):
        """預設合成版：標題規格精確到模型打不中，0 級不走 AI 標題路徑。

        2026-09-14 晚放寬後這條只管**預設**——明送 title_mode="ai" 會照辦（使用者自己勾的），
        那條在 test_creativity_zero_composite_20260914.YtCover 驗。
        """
        res, raw = self._post({})
        self.assertEqual(res.status_code, 200, res.text)
        # 合成版走的是**無文字底圖**那條 prompt；整張 AI 版不會有這段覆寫。
        # （標題本身仍會以「畫什麼場景」的身分出現在 Subject 裡，那不算模型要畫的字。）
        for call in raw.call_args_list:
            self.assertIn("TEXT-FREE BACKGROUND", call.args[0].prompt)

    def test_one_slot_only_stays_full_bleed(self):
        """2026-09-13 使用者裁決：只放一格＝滿版，不切。"""
        res, raw = self._post({"slot_left": [self._ref()]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["image_data_base64"])

    def test_both_slots_filled_goes_dual(self):
        res, _ = self._post({
            "slot_left": [self._ref((180, 40, 40))],
            "slot_right": [self._ref((40, 60, 180))],
        })
        self.assertEqual(res.status_code, 200, res.text)

    def test_a_second_title_does_not_make_it_dual(self):
        """hourly 靠第二標題判雙則，live24 只有一行——帶了也不該改變版面。"""
        alone, _ = self._post({})
        withsecond, _ = self._post({"title_second": "假日回溫"})
        self.assertEqual(alone.status_code, 200)
        self.assertEqual(withsecond.status_code, 200)
        self.assertEqual(
            alone.json()["image_data_base64"], withsecond.json()["image_data_base64"]
        )

    def test_a_title_too_long_is_reported_not_silently_cropped(self):
        res, _ = self._post({"title": "東" * 30})
        self.assertEqual(res.status_code, 400)  # 2026-09-14：標題太長是輸入問題，比照十點回 400
        self.assertIn("單行版型", res.json()["detail"])


class InsetBackgroundTests(unittest.TestCase):
    """雙切疊圖：大底圖鋪滿＋右側白框斜照片。"""

    def _bg2(self, size, colour):
        buffer = io.BytesIO()
        Image.new("RGB", size, colour).save(buffer, format="PNG")
        return buffer.getvalue()

    def _out(self):
        png = compose.compose_live24_inset_background(
            self._bg2((1920, 1080), (20, 50, 110)),
            self._bg2((1200, 675), (220, 180, 140)),
        )
        return Image.open(io.BytesIO(png)).convert("RGB")

    def test_it_returns_a_16x9_background(self):
        self.assertEqual(self._out().size, compose.YT_CANVAS)

    def test_the_inset_lands_on_the_right_half(self):
        """範本上那塊在右上；跑到左邊會直接壓到 24H LIVE 角標。"""
        image = self._out()
        w, h = image.size
        px = image.load()
        hits = [
            x for y in range(0, h, 6) for x in range(0, w, 6)
            if abs(px[x, y][0] - 220) < 60 and px[x, y][0] > px[x, y][2] + 40
        ]
        self.assertTrue(hits, "找不到疊上去的照片")
        self.assertGreater(min(hits) / w, 0.40, "疊圖不該伸進畫面左半的角標區")

    def test_the_inset_stops_above_the_title(self):
        """4:3 會算到 0.83、整塊蓋過標題（第一版就是這樣錯的）。"""
        image = self._out()
        w, h = image.size
        px = image.load()
        ys = [
            y for y in range(0, h, 4) for x in range(0, w, 6)
            if abs(px[x, y][0] - 220) < 60 and px[x, y][0] > px[x, y][2] + 40
        ]
        self.assertLess(max(ys) / h, 0.80, "疊圖底緣壓到標題區了")

    def test_it_has_a_white_border(self):
        image = self._out()
        w, h = image.size
        px = image.load()
        whites = [
            (x, y) for y in range(0, h, 4) for x in range(round(w * 0.40), w, 4)
            if all(c > 235 for c in px[x, y])
        ]
        self.assertGreater(len(whites), 80, "找不到白框")

    def test_the_top_edge_tilts_counter_clockwise(self):
        """範本量到 -8.7°：右端比左端高。畫成水平就不是這個版面。"""
        image = self._out()
        w, h = image.size
        px = image.load()

        def top_white(x):
            for y in range(0, h):
                if all(c > 235 for c in px[x, y]):
                    return y
            return None

        left = top_white(round(w * 0.52))
        right = top_white(round(w * 0.88))
        self.assertIsNotNone(left)
        self.assertIsNotNone(right)
        self.assertLess(right, left, "右端應該比左端高")


class BackgroundModeTests(unittest.TestCase):
    """底圖模式（2026-09-13 使用者裁決「前台加一題底圖模式」）。

    漸層與疊圖都要「兩格都有圖」，共用同一個觸發訊號分不開，所以獨立一欄。
    """

    def _post(self, payload):
        import base64
        import os
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        import main

        base = {"title": "東北季風剩1天 假日回溫", "layout": "live24", "date_text": "2026.09.13"}
        base.update(payload)

        def fake(req):
            size = (1080, 1080) if req.aspect_ratio == "1:1" else (1920, 1080)
            buffer = io.BytesIO()
            Image.new("RGB", size, (70, 80, 100)).save(buffer, format="PNG")
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
                mime_type="image/png", model="fake-model",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake), \
             patch.object(main, "supports_multiple_reference_images", return_value=True), \
             patch.object(main, "derive_yt_cover_plan", return_value={}), \
             patch.object(main, "_archive_generation", lambda **k: None), \
             patch.object(main.compose, "blend_backgrounds_lr",
                          wraps=main.compose.blend_backgrounds_lr) as blend, \
             patch.object(main.compose, "compose_live24_inset_background",
                          wraps=main.compose.compose_live24_inset_background) as inset:
            res = TestClient(main.app).post(
                "/api/editor/yt-cover", json=base,
                headers={"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]},
            )
        return res, blend, inset

    def _ref(self, colour=(30, 30, 30)):
        import base64
        buffer = io.BytesIO()
        Image.new("RGB", (640, 640), colour).save(buffer, format="PNG")
        return {
            "data_url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
            "purpose": "asis",
        }

    def _both(self):
        return {"slot_left": [self._ref((180, 40, 40))], "slot_right": [self._ref((40, 60, 180))]}

    def test_blend_is_the_default(self):
        import main
        self.assertEqual(main.YtCoverRequest(title="x").live24_bg, "blend")

    def test_blend_mode_uses_the_feathered_join(self):
        res, blend, inset = self._post(self._both())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(blend.call_count, 1)
        self.assertEqual(inset.call_count, 0)

    def test_inset_mode_uses_the_inset_compositor(self):
        res, blend, inset = self._post({**self._both(), "live24_bg": "inset"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(inset.call_count, 1)
        self.assertEqual(blend.call_count, 0)

    def test_full_mode_never_splits_even_with_two_slots(self):
        """選了滿版就是滿版，不能因為兩格都有圖又偷偷切開。"""
        res, blend, inset = self._post({**self._both(), "live24_bg": "full"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(blend.call_count, 0)
        self.assertEqual(inset.call_count, 0)

    def test_one_slot_falls_back_to_full_even_in_inset_mode(self):
        """半塊空白的疊圖不是使用者要的東西。"""
        res, blend, inset = self._post({"slot_left": [self._ref()], "live24_bg": "inset"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(inset.call_count, 0)

    def test_the_front_end_offers_all_three_and_matches_the_backend(self):
        import re
        import editor_formats
        html = pathlib.Path(__file__).resolve().parent.parent.joinpath("index.html").read_text("utf-8")
        block = re.search(r'<select id="live24BgMode".*?</select>', html, re.S)
        self.assertIsNotNone(block, "index.html 沒有底圖模式下拉")
        values = re.findall(r'value="([a-z]+)"', block.group(0))
        self.assertEqual(sorted(values), sorted(editor_formats.LIVE24_BG_MODES))


class BackgroundCreativityTests(unittest.TestCase):
    """合成版底圖的創意階梯（2026-09-13）。

    在此之前 YT 的拉桿**只接在 AI 標題那條路**，合成版底圖的模板一個創意變數都沒有，
    所以 live24 這種純合成版的版型，拉桿等於完全沒作用。
    """

    def _prompt(self, **payload):
        import base64
        import os
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        import main

        base = {"title": "東北季風剩1天 假日回溫", "layout": "live24", "date_text": "2026.09.13"}
        base.update(payload)

        def fake(req):
            buffer = io.BytesIO()
            Image.new("RGB", (1920, 1080), (70, 80, 100)).save(buffer, format="PNG")
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
                mime_type="image/png", model="fake-model",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake) as raw, \
             patch.object(main, "derive_yt_cover_plan", return_value={}), \
             patch.object(main, "_archive_generation", lambda **k: None):
            res = TestClient(main.app).post(
                "/api/editor/yt-cover", json=base,
                headers={"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]},
            )
        self.assertEqual(res.status_code, 200, res.text)
        return raw.call_args_list[0].args[0].prompt

    def test_level_zero_changes_nothing(self):
        """0 級一律等於改動前的行為，不然這次改動就動到既有版型的成品。"""
        import editor_formats
        self.assertEqual(editor_formats.yt_background_creativity(0), "")
        self.assertNotIn("LOOK (level", self._prompt(creativity=0))

    def test_every_level_above_zero_reaches_the_background_prompt(self):
        """用 hourly＋composite 測：live24 在 1 級起改走 AI 標題，沒有合成版底圖。

        底圖階梯本身是**所有合成版共用**的，不是 live24 專屬——用還留在合成版的
        版型來測，才測得到 1–4 級。
        """
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                prompt = self._prompt(layout="hourly", title_mode="composite",
                                      creativity=level)
                self.assertIn(f"LOOK (level {level})", prompt)

    def test_the_levels_are_all_different(self):
        import editor_formats
        texts = [editor_formats.yt_background_creativity(n) for n in range(5)]
        self.assertEqual(len(set(texts)), 5)

    def test_every_level_restates_the_overlay_keep_out(self):
        """放大戲劇性最容易換來的就是主體壓進下三分之一、蓋掉標題區。"""
        import editor_formats
        for level in (2, 3, 4):
            with self.subTest(level=level):
                self.assertIn("overlay areas below still stay clear",
                              editor_formats.yt_background_creativity(level))

    def test_live24_is_told_the_headline_is_one_line(self):
        """共用模板本來寫死 two lines，live24 是一行——講錯會留錯地方的白。"""
        self.assertIn("one line of large headline type", self._prompt())

    def test_the_other_layouts_still_say_two_lines(self):
        prompt = self._prompt(layout="hourly", title_mode="composite",
                              title="東北季風剩1天 假日回溫")
        self.assertIn("two lines of large headline type", prompt)

    def test_an_out_of_range_level_is_clamped_not_crashed(self):
        import editor_formats
        self.assertEqual(editor_formats.yt_background_creativity(99),
                         editor_formats.yt_background_creativity(4))
        self.assertEqual(editor_formats.yt_background_creativity(-3),
                         editor_formats.yt_background_creativity(0))


class AiTitleLadderTests(unittest.TestCase):
    """live24 的標題要吃到創意階梯（2026-09-13 使用者：「標題完全沒有被創意階梯影響 這是錯的」）。

    原本我把 live24 裁成純合成版，理由是標題規格太精確怕模型打不中——那是使用者
    沒要求過的限縮，而且跟十點／整點／熱搜不一致，那三個的階梯都是靠標題生效的。
    裁決：跟其他版型一樣走 AI 標題，0 級維持程式壓字。
    """

    def _run(self, **payload):
        import base64
        import os
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        import main

        base = {"title": "東北季風剩1天 假日回溫", "layout": "live24", "date_text": "2026.09.13"}
        base.update(payload)

        def fake(req):
            buffer = io.BytesIO()
            Image.new("RGB", (1920, 1080), (70, 80, 100)).save(buffer, format="PNG")
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
                mime_type="image/png", model="fake-model",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake) as raw, \
             patch.object(main, "derive_yt_cover_plan", return_value={}), \
             patch.object(main, "_archive_generation", lambda **k: None), \
             patch.object(main.compose, "_draw_live24_title",
                          wraps=main.compose._draw_live24_title) as stamp:
            res = TestClient(main.app).post(
                "/api/editor/yt-cover", json=base,
                headers={"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]},
            )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json(), raw.call_args_list[0].args[0].prompt, stamp

    def test_level_zero_still_stamps_the_title_in_code(self):
        """0 級＝規矩：位置／字級／斜度／顏色都是量到的，像素級精準且零錯字。"""
        body, prompt, stamp = self._run(creativity=0)
        self.assertEqual(body["title_mode"], "composite")
        # 2026-09-27：同一版再合成一張「固定元素完成、尚未貼來源標籤」的乾淨底圖，
        # 供成圖後自由拖曳重貼；兩次都是 Pillow，沒有多打一個生圖或文字模型。
        self.assertEqual(stamp.call_count, 2)

    def test_level_one_and_above_hand_the_title_to_the_model(self):
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                body, prompt, stamp = self._run(creativity=level)
                self.assertEqual(body["title_mode"], "ai")
                self.assertEqual(stamp.call_count, 0, "AI 畫過了就不該再壓一次")
                self.assertIn("東北季風剩1天 假日回溫", prompt)

    def test_the_title_wording_actually_changes_between_levels(self):
        """階梯要真的影響標題，不是只換一個旗標。"""
        prompts = [self._run(creativity=n)[1] for n in (1, 2, 3, 4)]
        self.assertEqual(len(set(prompts)), 4)

    def test_the_prompt_never_asks_for_two_rows(self):
        """共用的 brief／LAYOUT 原本整段為兩行寫的，跟「ONE line」直接打架。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                prompt = self._run(creativity=level)[1]
                for banned in ("Both headline lines", "The two rows", "Both rows",
                               "rows GROW FROM TOP TO BOTTOM"):
                    self.assertNotIn(banned, prompt)
                self.assertIn("ONE ROW", prompt)

    def test_the_badge_and_logo_corners_are_reserved_the_right_way_round(self):
        """live24 是 hourly 的鏡像：角標左上、Logo 右上。講反了就會直接撞。"""
        prompt = self._run(creativity=2)[1]
        badge_at = prompt.index("24H LIVE badge carrying the date")
        logo_at = prompt.index("a channel logo is pasted there")
        self.assertIn("UPPER-LEFT", prompt[:badge_at][-200:])
        self.assertIn("UPPER-RIGHT", prompt[:logo_at][-200:])

    def test_the_model_is_told_not_to_draw_the_date_or_the_mark(self):
        """日期與 24H LIVE 都是程式後貼的，模型畫了就是重複。"""
        prompt = self._run(creativity=3)[1]
        self.assertIn('NO date', prompt)
        self.assertIn('NO "24H"', prompt)

    def test_the_badge_keep_out_is_computed_from_the_real_asset(self):
        """手打的保留區比實際小時，標題會爬上去撞（2026-09-11 在 hourly 踩過）。"""
        height = compose.live24_badge_keep_out_height()
        self.assertGreater(height, compose.LIVE24_BADGE_TOP_RATIO)
        self.assertLess(height, 0.5)

    def test_the_whole_headline_reaches_the_model_not_just_the_first_segment(self):
        """lines 是依空格拆出來的兩段。live24 只列 line1 的話後半段整段消失——
        2026-09-13 實拍抓到：四級全被畫成「東北季風剩1天」，「假日回溫」不見了。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                prompt = self._run(creativity=level)[1]
                head = prompt[:prompt.index("=== LAYOUT")]
                self.assertIn("東北季風剩1天 假日回溫", head)
                self.assertNotIn("Headline line 2", head)
