"""YT 直播封面（2026-09-05）：分段規則、合成幾何、三條底圖路徑、端點。

守的紅線：
1. **標題一個字都不能改。** AI 分段回來的兩行去空白後必須等於原標題，改字就退路。
2. **能不打 API 就不打。** 標題已分好＋有 asis 附圖（或帶了現成底圖）時零 API 呼叫。
3. **附圖不標 AI示意圖、AI 底圖一律標。**（使用者裁決 2026-09-05）
4. **追加修改走無文字 refine 規則**，不能沿用帶文字 CG 的那套。
"""

import base64
import io
import os
import re
import unittest
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["NEWS_IMAGE_API_KEY"] = "yt-test-key"

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
import news_prompt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)
HEADERS = {"X-API-Key": "yt-test-key"}


def _png_bytes(size=(640, 480), colour=(30, 60, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


class TitleSplitTests(unittest.TestCase):
    def test_exactly_one_space_splits_there(self):
        self.assertEqual(
            editor_formats.split_live_title("挪威國王哈拉德辭世 開放公眾瞻仰遺容"),
            ("挪威國王哈拉德辭世", "開放公眾瞻仰遺容"),
        )

    def test_multiple_spaces_collapse_to_one_boundary(self):
        self.assertEqual(
            editor_formats.split_live_title("前段   後段"), ("前段", "後段")
        )

    def test_zero_or_two_plus_boundaries_defer_to_ai(self):
        # 範例 C 肝那張第二行本身就含空格，「遇到空格就切」不成立
        self.assertIsNone(editor_formats.split_live_title("新北診所爆C肝群聚 11人確診 疾管署說明"))
        self.assertIsNone(editor_formats.split_live_title("沒有空格的標題"))

    def test_faithful_split_keeps_every_character(self):
        title = "新北診所爆C肝群聚 11人確診 疾管署說明"
        self.assertTrue(
            editor_formats.title_split_is_faithful(title, "新北診所爆C肝群聚", "11人確診 疾管署說明")
        )
        self.assertFalse(
            editor_formats.title_split_is_faithful(title, "新北診所爆C肝群聚", "十一人確診 疾管署說明")
        )
        self.assertFalse(editor_formats.title_split_is_faithful(title, "", title))

    def test_fallback_uses_first_space_then_midpoint(self):
        self.assertEqual(
            editor_formats.fallback_split_title("新北診所爆C肝群聚 11人確診 疾管署說明"),
            ("新北診所爆C肝群聚", "11人確診 疾管署說明"),
        )
        self.assertEqual(editor_formats.fallback_split_title("一二三四五六"), ("一二三", "四五六"))


class ComposeTests(unittest.TestCase):
    def test_output_is_full_hd_png(self):
        cover = compose.compose_yt_cover(
            _png_bytes(), line1="第一行標題", line2="第二行標題",
            date_text="2026/09/05", original_audio=True, ai_translation=True, ai_note=True,
        )
        with Image.open(io.BytesIO(cover)) as image:
            self.assertEqual(image.size, compose.YT_CANVAS)
            self.assertEqual(image.format, "PNG")

    def test_ai_note_only_when_asked(self):
        # 標籤所在的右側區域：有標籤時會多出半透明黑底＋白字，像素分布不同
        def region(ai_note):
            cover = compose.compose_yt_cover(
                _png_bytes(colour=(200, 200, 200)), line1="一", line2="二",
                date_text="2026/09/05", ai_note=ai_note,
            )
            with Image.open(io.BytesIO(cover)) as image:
                y0 = round(compose.YT_CANVAS[1] * compose.YT_AI_NOTE_TOP_RATIO)
                return image.crop((1500, y0, 1900, y0 + 60)).tobytes()

        self.assertNotEqual(region(True), region(False))

    def test_original_audio_label_sits_above_badge(self):
        # 原音呈現：章往下讓位，章上方那塊多出白字紅邊；沒勾時那塊只有底圖
        def region(flag):
            cover = compose.compose_yt_cover(
                _png_bytes(colour=(120, 120, 120)), line1="一", line2="二",
                date_text="2026/09/05", original_audio=flag,
            )
            with Image.open(io.BytesIO(cover)) as image:
                h = compose.YT_CANVAS[1]
                return image.crop((40, round(h * 0.03), 600, round(h * 0.12))).tobytes()

        self.assertNotEqual(region(True), region(False))

    def test_ai_translation_label_sits_below_date(self):
        def region(flag):
            cover = compose.compose_yt_cover(
                _png_bytes(colour=(120, 120, 120)), line1="一", line2="二",
                date_text="2026/09/05", ai_translation=flag,
            )
            with Image.open(io.BytesIO(cover)) as image:
                h = compose.YT_CANVAS[1]
                y0 = round(h * (compose.YT_TOP_RATIO + 0.20))
                return image.crop((40, y0, 600, y0 + round(h * 0.12))).tobytes()

        self.assertNotEqual(region(True), region(False))

    def test_draw_titles_false_leaves_bottom_untouched(self):
        # AI 標題模式：底帶與標題都不畫，底部只剩底圖
        def bottom(draw_titles):
            cover = compose.compose_yt_cover(
                _png_bytes(colour=(90, 90, 90)), line1="第一行", line2="第二行",
                date_text="2026/09/05", draw_titles=draw_titles,
            )
            with Image.open(io.BytesIO(cover)) as image:
                return image.crop((300, 800, 1600, 1060)).tobytes()

        self.assertNotEqual(bottom(True), bottom(False))
        with Image.open(io.BytesIO(compose.compose_yt_cover(
            _png_bytes(colour=(90, 90, 90)), line1="一", line2="二", date_text="2026/09/05", draw_titles=False,
        ))) as image:
            self.assertEqual(image.getpixel((960, 1000)), (90, 90, 90))

    def test_rejects_missing_line_or_date(self):
        with self.assertRaises(compose.ComposeError):
            compose.compose_yt_cover(_png_bytes(), line1="只有一行", line2="", date_text="2026/09/05")
        with self.assertRaises(compose.ComposeError):
            compose.compose_yt_cover(_png_bytes(), line1="一", line2="二", date_text="")

    def test_live_badge_asset_exists(self):
        self.assertTrue(compose.LIVE_BADGE.exists(), compose.LIVE_BADGE)

    def test_crop_background_is_16x9(self):
        raw = compose.crop_background_16x9(_png_bytes(size=(1000, 1000)))
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.size, compose.YT_CANVAS)


class TopLineTests(unittest.TestCase):
    """頻道實際版每張新聞直播封面最頂端都有一道窄藍線（2026-09-06 對照型錄補上）。"""

    def test_top_edge_is_blue_across_full_width(self):
        out = compose.compose_yt_cover(
            _png_bytes(colour=(120, 40, 40)), line1="標題一", line2="標題二", date_text="2026/09/06"
        )
        img = Image.open(io.BytesIO(out)).convert("RGB")
        w, h = img.size
        for x in (0, w // 4, w // 2, (3 * w) // 4 - 40):
            r, g, b = img.getpixel((x, 1))
            self.assertGreater(b, 180, f"x={x} 頂端不是藍色：{(r, g, b)}")
            self.assertLess(r, 80)
        # 線很窄：往下一點就回到底圖（紅棕色）
        r, g, b = img.getpixel((w // 4, round(h * 0.06)))
        self.assertGreater(r, b)


class HourlyComposeTests(unittest.TestCase):
    def test_output_is_full_hd_png(self):
        cover = compose.compose_yt_hourly_cover(
            _png_bytes(), line1="遭撞趴引擎蓋一路載走200公尺", line2="護理師滿身傷稱被尋仇自導自演",
            date_text="2026/09/01", time_text="20:00", ai_note=True,
        )
        with Image.open(io.BytesIO(cover)) as image:
            self.assertEqual(image.size, compose.YT_CANVAS)
            self.assertEqual(image.format, "PNG")

    def test_time_band_only_when_given(self):
        # 時間帶掛在右上 LIVE 章正下方；沒填時間那塊只有底圖
        def region(time_text):
            cover = compose.compose_yt_hourly_cover(
                _png_bytes(colour=(200, 200, 200)), line1="一", line2="二",
                date_text="2026/09/01", time_text=time_text,
            )
            with Image.open(io.BytesIO(cover)) as image:
                w, h = compose.YT_CANVAS
                y0 = round(h * compose.YT_HOURLY_BADGE_TOP_RATIO) + 130
                return image.crop((w - 400, y0, w - 40, y0 + 80)).tobytes()

        self.assertNotEqual(region("20:00"), region(""))

    def test_rejects_missing_line_or_date(self):
        with self.assertRaises(compose.ComposeError):
            compose.compose_yt_hourly_cover(_png_bytes(), line1="只有一行", line2="", date_text="2026/09/01")
        with self.assertRaises(compose.ComposeError):
            compose.compose_yt_hourly_cover(_png_bytes(), line1="一", line2="二", date_text="")


class PlanTests(unittest.TestCase):
    def req(self, title, refs=(), background="", title_mode="composite"):
        # PlanTests 驗的是壓字路線的省 API 邏輯；AI 標題模式一律要畫面描述，另測
        return main.YtCoverRequest(
            title=title,
            title_mode=title_mode,
            reference_images=[main.UserReferenceImage(data_url=_data_url(_png_bytes()), purpose=p) for p in refs],
            background_image_base64=background,
        )

    def test_ai_title_mode_needs_visual_even_with_asis(self):
        with patch.object(main, "derive_yt_cover_plan", return_value={"visual": "場景", "portrait_subjects": []}) as derive:
            lines, visual, _, _ = main.resolve_yt_cover_plan(self.req("前段 後段", refs=("asis",), title_mode="ai"))
        self.assertEqual(derive.call_count, 1)
        self.assertEqual(visual, "場景")
        self.assertEqual(lines, ("前段", "後段"))

    def test_no_api_call_when_split_and_background_are_settled(self):
        with patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打 API")):
            lines, visual, subjects, english = main.resolve_yt_cover_plan(
                self.req("前段 後段", refs=("asis",))
            )
        self.assertEqual(lines, ("前段", "後段"))
        self.assertEqual((visual, subjects, english), ("", [], []))

    def test_ai_split_is_used_only_when_faithful(self):
        title = "新北診所爆C肝群聚 11人確診 疾管署說明"
        faithful = {"line1": "新北診所爆C肝群聚", "line2": "11人確診 疾管署說明", "visual": "", "portrait_subjects": [], "portrait_subjects_en": []}
        with patch.object(main, "derive_yt_cover_plan", return_value=faithful):
            lines, *_ = main.resolve_yt_cover_plan(self.req(title, refs=("asis",)))
        self.assertEqual(lines, ("新北診所爆C肝群聚", "11人確診 疾管署說明"))

        # AI 常把第二行的空格吃掉：字沒改就採用分段點，但字元從原標題切、空格保留
        squeezed = dict(faithful, line2="11人確診疾管署說明")
        with patch.object(main, "derive_yt_cover_plan", return_value=squeezed):
            lines, *_ = main.resolve_yt_cover_plan(self.req(title, refs=("asis",)))
        self.assertEqual(lines, ("新北診所爆C肝群聚", "11人確診 疾管署說明"))

        rewritten = dict(faithful, line2="十一人確診 疾管署說明")
        with patch.object(main, "derive_yt_cover_plan", return_value=rewritten):
            lines, *_ = main.resolve_yt_cover_plan(self.req(title, refs=("asis",)))
        self.assertEqual(lines, editor_formats.fallback_split_title(title))

    def test_visual_and_portraits_come_from_ai_when_generating(self):
        data = {
            "line1": "挪威國王哈拉德辭世", "line2": "開放公眾瞻仰遺容",
            "visual": "燭光中的鑲框肖像照，黑色緞帶斜掛框角",
            "portrait_subjects": ["哈拉德"], "portrait_subjects_en": ["Harald V"],
        }
        with patch.object(main, "derive_yt_cover_plan", return_value=data):
            lines, visual, subjects, english = main.resolve_yt_cover_plan(
                self.req("挪威國王哈拉德辭世 開放公眾瞻仰遺容")
            )
        self.assertEqual(lines, ("挪威國王哈拉德辭世", "開放公眾瞻仰遺容"))
        self.assertEqual(visual, data["visual"])
        self.assertEqual(subjects, ["哈拉德"])
        self.assertEqual(english, ["Harald V"])

    def test_derive_failure_still_yields_a_cover_plan(self):
        with patch.object(main, "derive_yt_cover_plan", return_value={}):
            lines, visual, *_ = main.resolve_yt_cover_plan(self.req("沒有空格的標題"))
        self.assertEqual(lines, ("沒有空", "格的標題"))
        self.assertEqual(visual, "沒有空格的標題")


class BackgroundPathTests(unittest.TestCase):
    def test_asis_reference_is_cropped_not_generated(self):
        req = main.YtCoverRequest(
            title="前段 後段",
            reference_images=[main.UserReferenceImage(data_url=_data_url(_png_bytes((800, 800))), purpose="asis")],
        )
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            raw, mime, is_ai, model = main._yt_cover_background(req, "", [], [])
        self.assertFalse(is_ai)
        self.assertEqual(model, "yt-cover:asis")
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.size, compose.YT_CANVAS)

    def test_existing_background_is_reused_verbatim(self):
        raw = _png_bytes()
        req = main.YtCoverRequest(
            title="前段 後段",
            background_image_base64=base64.b64encode(raw).decode("ascii"),
            background_is_ai=True,
        )
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            out, mime, is_ai, model = main._yt_cover_background(req, "", [], [])
        self.assertEqual(out, raw)
        self.assertTrue(is_ai)

    def test_generated_background_prompt_is_text_free_and_marked_ai(self):
        captured = {}

        def fake_generate(image_req):
            captured["req"] = image_req
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_bytes()).decode("ascii"),
                mime_type="image/png", model="fake-image",
            )

        req = main.YtCoverRequest(title="前段 後段")
        with patch.object(main, "generate_image_raw", side_effect=fake_generate), \
             patch.object(main, "apply_portrait_to_image_request", side_effect=lambda r: r):
            _, _, is_ai, model = main._yt_cover_background(req, "燭光中的肖像", [], [])
        self.assertTrue(is_ai)
        self.assertEqual(model, "fake-image")
        prompt = captured["req"].prompt
        self.assertIn("燭光中的肖像", prompt)
        self.assertTrue(prompt.rstrip().endswith(editor_formats.YT_COVER_TEXT_FREE_OVERRIDE.rstrip()))
        self.assertEqual(captured["req"].aspect_ratio, "16:9")
        self.assertFalse(captured["req"].safe_frame)


class SplitBackgroundTests(unittest.TestCase):
    """2026-09-06：原圖放置附圖 2 張＝雙切、3 張＝三切，斜切＋白色細分隔線。"""

    def _split(self, colours):
        out = compose.split_backgrounds([_png_bytes((900, 900), c) for c in colours])
        return Image.open(io.BytesIO(out)).convert("RGB")

    def test_two_images_fill_left_and_right(self):
        img = self._split([(200, 30, 30), (30, 30, 200)])
        w, h = img.size
        self.assertEqual(img.size, compose.YT_CANVAS)
        self.assertEqual(img.getpixel((w // 4, h // 2)), (200, 30, 30))
        self.assertEqual(img.getpixel((3 * w // 4, h // 2)), (30, 30, 200))

    def test_three_images_fill_three_panels(self):
        img = self._split([(200, 30, 30), (30, 200, 30), (30, 30, 200)])
        w, h = img.size
        self.assertEqual(img.getpixel((w // 6, h // 2)), (200, 30, 30))
        self.assertEqual(img.getpixel((w // 2, h // 2)), (30, 200, 30))
        self.assertEqual(img.getpixel((5 * w // 6, h // 2)), (30, 30, 200))

    def test_divider_is_slanted_white_line(self):
        img = self._split([(200, 30, 30), (30, 30, 200)])
        w, h = img.size
        slant = round(w * compose.YT_SPLIT_SLANT_RATIO)
        # 頂端分隔線偏右、底端偏左、正中央（高度一半）都是白線（反鋸齒邊緣允許略低於 255）
        for x, y in ((w // 2 + slant // 2, 2), (w // 2 - slant // 2, h - 3), (w // 2, h // 2)):
            self.assertTrue(all(c >= 240 for c in img.getpixel((x, y))), (x, y, img.getpixel((x, y))))
        # 分隔線是斜的：頂端偏左那點、底端偏右那點都還是原圖顏色
        self.assertEqual(img.getpixel((w // 2 - slant, 2)), (200, 30, 30))
        self.assertEqual(img.getpixel((w // 2 + slant, h - 3)), (30, 30, 200))

    def test_single_image_degrades_to_plain_crop(self):
        out = compose.split_backgrounds([_png_bytes((900, 900), (10, 20, 30))])
        self.assertEqual(out, compose.crop_background_16x9(_png_bytes((900, 900), (10, 20, 30))))

    def test_more_than_three_only_takes_the_first_three(self):
        img = self._split([(200, 30, 30), (30, 200, 30), (30, 30, 200), (250, 250, 30)])
        w, h = img.size
        self.assertEqual(img.getpixel((5 * w // 6, h // 2)), (30, 30, 200))

    def test_two_asis_references_split_without_generating(self):
        req = main.YtCoverRequest(
            title="前段 後段",
            reference_images=[
                main.UserReferenceImage(data_url=_data_url(_png_bytes((800, 800), (200, 30, 30))), purpose="asis"),
                main.UserReferenceImage(data_url=_data_url(_png_bytes((800, 800), (30, 30, 200))), purpose="asis"),
            ],
        )
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            raw, mime, is_ai, model = main._yt_cover_background(req, "", [], [])
        self.assertFalse(is_ai)
        self.assertEqual(model, "yt-cover:asis-split2")
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = img.size
        self.assertEqual(img.getpixel((w // 4, h // 2)), (200, 30, 30))
        self.assertEqual(img.getpixel((3 * w // 4, h // 2)), (30, 30, 200))

    def test_endpoint_forces_composite_title_when_splitting(self):
        payload = {
            "title": "閃兵案第四波 14人自首遭起訴",
            "title_mode": "ai",
            "reference_images": [
                {"data_url": _data_url(_png_bytes((800, 800), (200, 30, 30))), "purpose": "asis"},
                {"data_url": _data_url(_png_bytes((800, 800), (30, 30, 200))), "purpose": "asis"},
                {"data_url": _data_url(_png_bytes((800, 800), (30, 200, 30))), "purpose": "asis"},
            ],
        }
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["title_mode"], "composite")
        self.assertFalse(data["background_is_ai"])
        with Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))) as image:
            self.assertEqual(image.size, compose.YT_CANVAS)


class EndpointTests(unittest.TestCase):
    def test_asis_cover_end_to_end_without_any_model(self):
        payload = {
            "title": "新北診所爆C肝群聚 11人確診疾管署說明",
            "title_mode": "composite",
            "original_audio": True,
            "ai_translation": True,
            "date_text": "2026/09/05",
            "reference_images": [{"data_url": _data_url(_png_bytes((1200, 700))), "purpose": "asis"}],
        }
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual((data["line1"], data["line2"]), ("新北診所爆C肝群聚", "11人確診疾管署說明"))
        self.assertFalse(data["background_is_ai"])
        self.assertTrue(data["source_image_base64"], "追加修改需要無文字底圖")
        with Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))) as image:
            self.assertEqual(image.size, compose.YT_CANVAS)

    def test_hourly_layout_ignores_subtitle_and_takes_time(self):
        payload = {
            "title": "遭撞趴引擎蓋一路載走200公尺 護理師滿身傷稱被尋仇自導自演",
            "layout": "hourly",
            "title_mode": "composite",
            "original_audio": True,        # 整點版沒有這兩個標示，後端直接忽略
            "time_text": "20:00",
            "reference_images": [{"data_url": _data_url(_png_bytes((1200, 700))), "purpose": "asis"}],
        }
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")), \
             patch.object(compose, "compose_yt_hourly_cover", wraps=compose.compose_yt_hourly_cover) as hourly, \
             patch.object(compose, "compose_yt_cover", side_effect=AssertionError("整點版不該走新聞版合成")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(hourly.call_args.kwargs["time_text"], "20:00")
        self.assertEqual(res.json()["line1"], "遭撞趴引擎蓋一路載走200公尺")

    def test_ai_title_mode_generates_whole_cover_with_text(self):
        payload = {"title": "前段 後段", "title_mode": "ai", "original_audio": True, "date_text": "2026/09/06"}
        fake = main.ImageGenerateResponse(
            image_data_base64=base64.b64encode(_png_bytes((1536, 864), colour=(30, 30, 30))).decode("ascii"),
            mime_type="image/png", model="fake-model",
        )
        with patch.object(main, "generate_image_raw", return_value=fake) as gen, \
             patch.object(main, "derive_yt_cover_plan", return_value={"visual": "一個場景", "portrait_subjects": []}), \
             patch.object(compose, "compose_yt_cover", wraps=compose.compose_yt_cover) as news:
            res = client.post("/api/editor/yt-cover", json=payload, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        prompt = gen.call_args.args[0].prompt
        self.assertIn("前段", prompt)
        self.assertIn("後段", prompt)
        self.assertNotIn("TEXT-FREE BACKGROUND", prompt)
        self.assertFalse(news.call_args.kwargs["draw_titles"])
        data = res.json()
        self.assertEqual(data["title_mode"], "ai")
        self.assertTrue(data["background_is_ai"])
        # 追加修改的源圖＝模型原圖（還沒貼固定元素）
        self.assertEqual(data["source_image_base64"], fake.image_data_base64)

    def test_ai_title_mode_with_background_only_overlays(self):
        payload = {
            "title": "前段 後段", "title_mode": "ai", "layout": "hourly", "time_text": "20:00",
            "background_image_base64": base64.b64encode(_png_bytes((1536, 864))).decode("ascii"),
            "background_is_ai": True,
        }
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")), \
             patch.object(compose, "compose_yt_hourly_cover", wraps=compose.compose_yt_hourly_cover) as hourly:
            res = client.post("/api/editor/yt-cover", json=payload, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(hourly.call_args.kwargs["draw_titles"])
        self.assertEqual(hourly.call_args.kwargs["time_text"], "20:00")

    def test_default_title_mode_is_ai(self):
        self.assertEqual(main.YtCoverRequest(title="前段 後段").title_mode, editor_formats.YT_COVER_TITLE_MODE_AI)

    def test_unknown_layout_is_rejected(self):
        res = client.post("/api/editor/yt-cover", json={"title": "前段 後段", "layout": "weekly"}, headers=HEADERS)
        self.assertEqual(res.status_code, 422)

    def test_news_layout_passes_flags_to_compose(self):
        payload = {
            "title": "前段 後段", "title_mode": "composite", "original_audio": True, "ai_translation": False,
            "reference_images": [{"data_url": _data_url(_png_bytes((1200, 700))), "purpose": "asis"}],
        }
        with patch.object(compose, "compose_yt_cover", wraps=compose.compose_yt_cover) as news:
            res = client.post("/api/editor/yt-cover", json=payload, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(news.call_args.kwargs["original_audio"])
        self.assertFalse(news.call_args.kwargs["ai_translation"])

    def test_requires_api_key(self):
        res = client.post("/api/editor/yt-cover", json={"title": "前段 後段"})
        self.assertEqual(res.status_code, 401)


class RefinePromptTests(unittest.TestCase):
    def test_text_free_refine_uses_its_own_rules(self):
        prompt = news_prompt.build_refine_prompt("把背景換成夜景", text_free=True)
        self.assertIn(news_prompt.TEXT_FREE_REFINE_RULES, prompt)
        self.assertNotIn(news_prompt.IMAGE_REFINE_RULES, prompt)
        self.assertIn("把背景換成夜景", prompt)

    def test_default_refine_is_unchanged(self):
        prompt = news_prompt.build_refine_prompt("把標題改紅色")
        self.assertIn(news_prompt.IMAGE_REFINE_RULES, prompt)
        self.assertNotIn(news_prompt.TEXT_FREE_REFINE_RULES, prompt)


class FrontendParityTests(unittest.TestCase):
    APP_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.js")
    INDEX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")

    def test_format_registered_on_both_sides(self):
        self.assertEqual(editor_formats.get("yt_live_cover")["pipeline"], editor_formats.PIPELINE_YT_COVER)
        with open(self.APP_JS, encoding="utf-8") as fh:
            js = fh.read()
        entry = re.search(r"yt_live_cover:\s*\{(.*?)\n\s{4}\},", js, re.S).group(1)
        self.assertIn("inputs: 'yt_cover'", entry)
        for field in ("digestControls", "safeFrame", "stamp"):
            self.assertIn(field, re.search(r"hides:\s*\{([^}]*)\}", entry).group(1))
        self.assertIn("text_free: ytTextFree", js, "追加修改：壓字模式走無文字 refine")
        self.assertIn("state.ytCoverTitleMode !== 'ai'", js)
        with open(self.INDEX, encoding="utf-8") as fh:
            html = fh.read()
        self.assertRegex(html, r'id="ytCoverAiTitle"[^>]*checked', "預設標題由 AI 生成（使用者裁決）")

    def test_hot_format_registered_on_both_sides(self):
        # 2026-09-06 型錄 H 類「今日熱搜」
        self.assertEqual(editor_formats.get("yt_hot_cover")["yt_layout"], editor_formats.YT_COVER_LAYOUT_HOT)
        self.assertIn(editor_formats.YT_COVER_LAYOUT_HOT, editor_formats.YT_COVER_LAYOUTS)
        with open(self.APP_JS, encoding="utf-8") as fh:
            js = fh.read()
        entry = re.search(r"yt_hot_cover:\s*\{(.*?)\n\s{4}\},", js, re.S).group(1)
        self.assertIn("inputs: 'yt_cover'", entry)
        self.assertIn("ytLayout: 'hot'", entry)

    def test_hourly_format_registered_on_both_sides(self):
        self.assertEqual(editor_formats.get("yt_hourly_cover")["yt_layout"], editor_formats.YT_COVER_LAYOUT_HOURLY)
        self.assertEqual(editor_formats.get("yt_live_cover")["yt_layout"], editor_formats.YT_COVER_LAYOUT_NEWS)
        with open(self.APP_JS, encoding="utf-8") as fh:
            js = fh.read()
        for key, layout in (("yt_hourly_cover", "hourly"), ("yt_live_cover", "news")):
            entry = re.search(key + r":\s*\{(.*?)\n\s{4}\},", js, re.S).group(1)
            self.assertIn("inputs: 'yt_cover'", entry)
            self.assertIn(f"ytLayout: '{layout}'", entry)
        with open(self.INDEX, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('id="ytCoverTime"', html)

    def test_flag_labels_match_backend(self):
        with open(self.INDEX, encoding="utf-8") as fh:
            html = fh.read()
        block = re.search(r'id="ytCoverFlags".*?</div>', html, re.S).group(0)
        self.assertIn('id="ytCoverOriginalAudio"', block)
        self.assertIn('id="ytCoverAiTranslation"', block)
        self.assertIn(editor_formats.YT_COVER_ORIGINAL_AUDIO_LABEL, block)
        self.assertIn(editor_formats.YT_COVER_AI_TRANSLATION_LABEL, block)
        self.assertEqual(compose.YT_ORIGINAL_AUDIO_LABEL, editor_formats.YT_COVER_ORIGINAL_AUDIO_LABEL)
        self.assertEqual(compose.YT_AI_TRANSLATION_LABEL, editor_formats.YT_COVER_AI_TRANSLATION_LABEL)
        self.assertNotIn("原音重現", html, "頻道實際用字是「原音呈現」")


if __name__ == "__main__":
    unittest.main()


class HotCoverTests(unittest.TestCase):
    """今日熱搜（2026-09-06）：紅色標頭、無日期無 LIVE、底部深紅帶兩行標題。"""

    def _cover(self, **kw):
        out = compose.compose_yt_hot_cover(_png_bytes((800, 450), (20, 120, 20)), line1="大象來了", line2="10萬人塞爆士林", **kw)
        return Image.open(io.BytesIO(out)).convert("RGB")

    def test_red_top_strip_and_red_logo_tab(self):
        img = self._cover()
        w, h = img.size
        r, g, b = img.getpixel((w // 2, 2))
        self.assertGreater(r, 120); self.assertLess(g, 60); self.assertLess(b, 60)
        # 右上斜標是紅的，不是新聞版的藍
        r, g, b = img.getpixel((w - 40, round(h * 0.10)))
        self.assertGreater(r, g + 60)

    def test_hot_tag_has_red_and_white_parts(self):
        img = self._cover()
        w, h = img.size
        tag_h = round(h * compose.YT_HOT_TAG_HEIGHT_RATIO)
        y = round(h * compose.YT_HOT_TAG_TOP_RATIO) + tag_h // 2
        x0 = round(w * compose.YT_HOT_TAG_LEFT_RATIO)
        r, g, b = img.getpixel((x0 + 8, y))
        self.assertGreater(r, g + 100, "今日 段應為紅底")
        # 標籤右半白底：從標籤右側往左找到白色
        whites = [x for x in range(x0 + 60, x0 + 700) if all(c > 240 for c in img.getpixel((x, y)))]
        self.assertTrue(whites, "熱搜 段應有白底")

    def test_band_is_crimson_not_navy(self):
        img = self._cover()
        w, h = img.size
        r, g, b = img.getpixel((w // 2, round(h * 0.995)))
        self.assertGreater(r, b, "底帶應偏紅")

    def test_requires_two_lines(self):
        with self.assertRaises(compose.ComposeError):
            compose.compose_yt_hot_cover(_png_bytes(), line1="只有一行", line2="")

    def test_endpoint_hot_layout_with_asis_needs_no_date_and_no_api(self):
        payload = {
            "title": "大象來了 10萬人塞爆士林",
            "layout": "hot",
            "title_mode": "composite",
            "original_audio": True,
            "reference_images": [{"data_url": _data_url(_png_bytes((800, 450), (20, 120, 20))), "purpose": "asis"}],
        }
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["line1"], "大象來了")
        self.assertFalse(data["background_is_ai"])
        img = Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")
        r, g, b = img.getpixel((img.width // 2, 2))
        self.assertGreater(r, 120)

    def test_ai_title_mode_uses_hot_prompt(self):
        seen = {}

        def fake_generate(req):
            seen["prompt"] = req.prompt
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_bytes((1280, 720))).decode("ascii"), mime_type="image/png", model="fake",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_generate), \
             patch.object(main, "derive_yt_cover_plan", return_value={"visual": "夜間廣場人潮", "portrait_subjects": [], "portrait_subjects_en": []}):
            res = client.post("/api/editor/yt-cover", json={"title": "大象來了 10萬人塞爆士林", "layout": "hot", "title_mode": "ai"}, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("trending", seen["prompt"])
        self.assertIn("no LIVE word", seen["prompt"])
