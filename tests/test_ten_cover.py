"""十點不一樣封面（2026-09-06 斜切全幅版）：標題分行、逐行配色、原圖放置、端點。

守的紅線：
1. **標題只切不改字。** 分行後接回去必須等於原標題去掉分隔符。
2. **原圖放置不進生圖模型。** 有 asis 一律合成版；兩格都 asis 時一次 API 都不打。
3. **只有 AI 底圖那格印「AI示意圖」。**
"""

import base64
import io
import os
import unittest
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["NEWS_IMAGE_API_KEY"] = "ten-test-key"

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def _headers() -> dict:
    # 整包跑時其他測試模組會在 import 期改寫 NEWS_IMAGE_API_KEY，執行時再讀才對得上
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}


def _png_bytes(size=(640, 640), colour=(30, 60, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _highlight_tag_box(w: int, h: int) -> tuple[int, int, int, int]:
    """「精華」紅刷筆標籤在畫布上的方框（與 compose._draw_cover_highlight_stamp 同一套推導）。"""
    band_h = round(h * compose.COVER_HEADER_RATIO)
    line_h = max(2, round(h * compose.COVER_HEADER_LINE_RATIO))
    tag_h = round(band_h * compose.COVER_STAMP_BAND_RATIO)
    with Image.open(compose.TEN_HIGHLIGHT_TAG) as tpl:
        tag_w = round(tpl.width * tag_h / tpl.height)
    y0 = (band_h - line_h - tag_h) // 2
    return ((w - tag_w) // 2, y0, (w - tag_w) // 2 + tag_w, y0 + tag_h)


def _ai_note_region_is_plate(img: Image.Image, align_right: bool) -> bool:
    """「AI示意圖」小標位置是否有半透明黑底（比底圖暗很多）。"""
    w, h = img.size
    band_h = round(h * compose.COVER_HEADER_RATIO)
    y = band_h + round(h * 0.025) + 8
    x = (w - compose.COVER_MARGIN - 20) if align_right else (compose.COVER_MARGIN + 20)
    r, g, b = img.getpixel((x, y))
    return (r + g + b) < 200


class SplitTitleTests(unittest.TestCase):
    def test_space_separated_lines_kept_verbatim(self):
        self.assertEqual(editor_formats.split_cover_title("尼泊爾災區 無人機空拍 滅村慘況"), ["尼泊爾災區", "無人機空拍", "滅村慘況"])

    def test_fullwidth_space_and_newline_also_split(self):
        self.assertEqual(editor_formats.split_cover_title("台南易淹水　成氣候衝擊區"), ["台南易淹水", "成氣候衝擊區"])
        self.assertEqual(editor_formats.split_cover_title("台南易淹水\n成氣候衝擊區"), ["台南易淹水", "成氣候衝擊區"])

    def test_long_unsplit_title_is_halved_without_changing_characters(self):
        title = "政府明年勞保撥補上看1300億"
        lines = editor_formats.split_cover_title(title)
        self.assertEqual(len(lines), 2)
        self.assertEqual("".join(lines), title)

    def test_short_title_stays_one_line(self):
        self.assertEqual(editor_formats.split_cover_title("滅村慘況"), ["滅村慘況"])

    def test_more_than_three_segments_merge_into_last_line(self):
        lines = editor_formats.split_cover_title("一 二 三 四 五")
        self.assertEqual(lines, ["一", "二", "三四五"])

    def test_empty_title_gives_no_lines(self):
        self.assertEqual(editor_formats.split_cover_title("   "), [])


class ComposeTests(unittest.TestCase):
    def _cover(self, **kw):
        defaults = dict(
            title_left="尼泊爾災區 無人機空拍 滅村慘況",
            title_right="台南易淹水 成氣候衝擊區",
            date_text="2026/09/06",
        )
        defaults.update(kw)
        out = compose.compose_ten_cover(_png_bytes(colour=(200, 30, 30)), _png_bytes(colour=(30, 30, 200)), **defaults)
        return Image.open(io.BytesIO(out)).convert("RGB")

    def test_full_bleed_slanted_split(self):
        img = self._cover()
        w, h = img.size
        self.assertEqual(img.size, compose.COVER_CANVAS)
        # 中高度、遠離標題與標頭：左紅右藍，中線是白色斜線
        y = round(h * 0.30)
        self.assertEqual(img.getpixel((w // 4, y)), (200, 30, 30))
        self.assertEqual(img.getpixel((3 * w // 4, y)), (30, 30, 200))
        slant = round(w * compose.YT_SPLIT_SLANT_RATIO)
        x_line = round(w / 2 + slant / 2 - slant * (y / h))
        self.assertTrue(all(c >= 240 for c in img.getpixel((x_line, y))))

    def test_header_band_and_bottom_line_are_drawn(self):
        img = self._cover()
        w, h = img.size
        self.assertEqual(img.getpixel((w // 2, 6)), compose.COVER_HEADER_FILL)
        # 底部飾帶模板：最底一列是深藍（不是底圖的紅／藍純色）
        r, g, b = img.getpixel((w // 4, h - 3))
        self.assertGreater(b, r)
        self.assertNotEqual((r, g, b), (200, 30, 30))

    def test_ai_note_only_on_ai_panels(self):
        both = self._cover(left_is_ai=True, right_is_ai=True)
        self.assertTrue(_ai_note_region_is_plate(both, align_right=False))
        self.assertTrue(_ai_note_region_is_plate(both, align_right=True))
        right_only = self._cover(left_is_ai=False, right_is_ai=True)
        self.assertFalse(_ai_note_region_is_plate(right_only, align_right=False))
        self.assertTrue(_ai_note_region_is_plate(right_only, align_right=True))

    def test_title_lines_use_white_yellow_red(self):
        # 左格三行：畫面下方左側應同時出現白、黃、紅三色的字
        img = self._cover()
        w, h = img.size
        region = img.crop((0, round(h * 0.55), w // 2 - 80, h - round(h * 0.06)))
        raw = region.tobytes()
        colours = set(zip(raw[0::3], raw[1::3], raw[2::3]))
        self.assertIn((255, 255, 255), colours)
        self.assertIn(compose.COVER_TITLE_LINE_COLOURS[1], colours)
        self.assertIn(compose.COVER_TITLE_LINE_COLOURS[2], colours)

    def test_rejects_unknown_badge(self):
        with self.assertRaises(compose.ComposeError):
            self._cover(badge="nope")

    def test_ai_cover_paste_fits_logo_and_tag_inside_header_band(self):
        """2026-09-07：AI 整張版的 Logo 原本寬佔 18.5%，在一成高的標頭帶裡爆出來壓到照片。
        改成跟合成版同一套幾何：Logo＋節目標籤都貼在標頭帶左半、不超出帶高。"""
        w, h = 1536, 864
        base = Image.new("RGB", (w, h), (12, 20, 60))          # 整張深藍，模擬模型留白的標頭帶
        buf = io.BytesIO(); base.save(buf, format="PNG")
        out = Image.open(io.BytesIO(
            compose.paste_cover_logo(buf.getvalue(), date_text="2026/09/10")
        )).convert("RGB")
        band_h = round(h * compose.COVER_AI_HEADER_RATIO)
        px = list(out.getdata())
        def count(box, pred):
            x0, y0, x1, y1 = box
            return sum(1 for y in range(y0, y1) for x in range(x0, x1) if pred(px[y * w + x]))
        white = lambda p: p[0] > 220 and p[1] > 220 and p[2] > 220
        gold = lambda p: p[0] > 170 and p[1] > 120 and p[2] < 110
        red = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90
        # 帶內左半有 Logo 白點與標籤金「十」
        self.assertGreater(count((0, 0, w // 2, band_h), white), 800)
        self.assertGreater(count((0, 0, w // 2, band_h), gold), 100)
        # 帶下方（照片區）完全沒被貼到
        self.assertEqual(count((0, band_h + 2, w, h), lambda p: p != (12, 20, 60)), 0)
        # 右半帶：2026-09-10 起日期與 ON AIR 紅標也由程式貼（原本交給模型畫，
        # 補帶會把它們切成上下兩截），所以這一半現在該有紅底與白字
        self.assertGreater(count((w // 2, 0, w, band_h), red), 500)
        self.assertGreater(count((w // 2, 0, w, band_h), white), 200)

    def test_thickening_a_thin_band_no_longer_slices_the_date_and_on_air(self):
        """使用者回報：十點封面的 ON AIR 與日期被切斷，下面還留一截殘影。

        機制：模型畫的帶太薄時 ensure_ai_header_band 會把帶補厚——帶底那條邊往下搬、
        中間用帶身填滿。日期與紅標若是模型畫在薄帶裡的，就會被填進去的那幾列切掉上半，
        被往下搬的邊再把下半重新貼出來。改成程式在補帶「之後」才畫，補多厚都不影響。
        這條測試盯的就是那個順序：紅標必須是一整塊、不得有橫向斷層。
        """
        w, h = 1536, 864
        photo = (90, 90, 90)
        canvas = Image.new("RGB", (w, h), photo)
        thin = round(h * compose.COVER_AI_HEADER_RATIO) // 2   # 模型只畫了一半厚的帶
        canvas.paste(Image.new("RGB", (w, thin), (12, 20, 60)), (0, 0))
        canvas.paste(Image.new("RGB", (w, 3), (40, 160, 255)), (0, thin - 3))  # 帶底亮藍細線
        buf = io.BytesIO(); canvas.save(buf, format="PNG")

        out = Image.open(io.BytesIO(
            compose.paste_cover_logo(buf.getvalue(), date_text="2026/09/10")
        )).convert("RGB")
        band_h = round(h * compose.COVER_AI_HEADER_RATIO)
        px = list(out.getdata())
        red = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90

        rows = [y for y in range(h) if any(red(px[y * w + x]) for x in range(w // 2, w))]
        self.assertTrue(rows, "標頭帶右端找不到 ON AIR 紅標")
        # 一整塊：紅色列必須連續，中間不得有被填掉的空檔（那就是「被切斷」）
        self.assertEqual(rows, list(range(rows[0], rows[-1] + 1)), f"紅標被切斷：{rows}")
        # 而且整塊都在補完後的帶內，照片區不得有殘影
        self.assertLess(rows[-1], band_h, "紅標掉出標頭帶外")

    def test_the_date_carries_a_black_outline_so_a_thin_band_cannot_hide_it(self):
        """2026-09-10 使用者裁決：模型畫的藍帶厚度會飄，帶一薄，白色日期就落在照片上。
        與其追著把帶補到剛好（帶厚是模型決定的），不如給日期一圈黑描邊：
        落在帶上或落在亮照片上都讀得到。
        """
        w, h = 1536, 864
        canvas = Image.new("RGB", (w, h), (235, 235, 235))     # 整張亮底＝最壞情況
        buf = io.BytesIO(); canvas.save(buf, format="PNG")
        out = Image.open(io.BytesIO(
            compose.paste_cover_logo(buf.getvalue(), date_text="2026/09/10")
        )).convert("RGB")
        band_h = round(h * compose.COVER_AI_HEADER_RATIO)
        px = list(out.getdata())
        # 日期在紅標左側：取紅標左緣以左、帶內的那塊
        red_x = min(
            (x for y in range(band_h) for x in range(w // 2, w)
             if px[y * w + x][0] > 150 and px[y * w + x][1] < 90 and px[y * w + x][2] < 90),
            default=w,
        )
        dark = sum(
            1 for y in range(band_h) for x in range(w // 2, red_x)
            if max(px[y * w + x]) < 60
        )
        self.assertGreater(dark, 100, "日期沒有黑色字框，薄帶時會消失在亮照片上")

    def test_highlight_badge_pastes_red_brush_tag_in_the_header_band(self):
        """精華：標頭仍 ON AIR，標頭帶中段貼紅色刷筆標籤（模板），非精華時該區維持深藍。

        2026-09-08 使用者兩次裁決：先是原本的深藍圓章跨在底部標題區上會壓到標題，
        接著整個樣式換成紅色刷筆底＋白字的橫式標籤，位置改到標頭帶中段。
        """
        on_air = self._cover(badge="on_air")
        highlight = self._cover(badge="highlight")
        w, h = highlight.size
        box = _highlight_tag_box(w, h)

        def pixels(img):
            raw = img.crop(box).tobytes()
            return list(zip(raw[0::3], raw[1::3], raw[2::3]))

        hi, base = pixels(highlight), pixels(on_air)
        changed = sum(1 for a, b in zip(hi, base) if a != b) / len(hi)
        self.assertGreater(changed, 0.5)          # 標籤確實蓋在這個區域
        red = sum(1 for r, g, b in hi if r > 140 and g < 90 and b < 90) / len(hi)
        self.assertGreater(red, 0.2)              # 紅色刷筆底
        white = sum(1 for r, g, b in hi if r > 225 and g > 225 and b > 225) / len(hi)
        self.assertGreater(white, 0.01)           # 白字「精華」
        # 非精華時同一塊是標頭帶的深藍
        self.assertEqual(on_air.getpixel((w // 2, round(h * compose.COVER_HEADER_RATIO * 0.5))), compose.COVER_HEADER_FILL)
        # 標頭右側仍是 ON AIR 紅標（精華不再是標頭紅字）
        band_h = round(h * compose.COVER_HEADER_RATIO)
        head = highlight.crop((w - 300, 0, w, band_h)).tobytes()
        reds = sum(1 for r, g, b in zip(head[0::3], head[1::3], head[2::3]) if r > 180 and g < 60)
        self.assertGreater(reds, 500)

    def test_highlight_tag_clears_the_title_area_and_the_header_contents(self):
        """標籤只能待在標頭帶中段：標題區與標頭帶左右兩端都不能被動到。

        使用者實測回報的正是「壓到標題」；標頭帶左半是 Logo＋節目標籤、右端是日期＋ON AIR。
        """
        on_air, highlight = self._cover(badge="on_air"), self._cover(badge="highlight")
        w, h = highlight.size
        band_h = round(h * compose.COVER_HEADER_RATIO)
        x0, _, x1, y1 = _highlight_tag_box(w, h)
        for name, box in (
            ("標題區", (0, round(h * 0.55), w, h)),
            ("標頭帶以下", (0, band_h + 2, w, h)),
            ("標頭帶左半（Logo／節目標籤）", (0, 0, x0 - 2, band_h)),
            ("標頭帶右端（日期／ON AIR）", (x1 + 2, 0, w, band_h)),
        ):
            with self.subTest(zone=name):
                self.assertEqual(highlight.crop(box).tobytes(), on_air.crop(box).tobytes())


class EndpointTests(unittest.TestCase):
    def _payload(self, asis: int, mode="ai"):
        refs = [{"data_url": _data_url(_png_bytes(colour=c)), "purpose": "asis"} for c in [(200, 30, 30), (30, 30, 200)][:asis]]
        return {
            "title_left": "尼泊爾災區 無人機空拍 滅村慘況",
            "title_right": "台南易淹水 成氣候衝擊區",
            "mode": mode,
            "reference_images": refs,
        }

    def test_two_asis_images_fill_both_panels_without_any_api_call(self):
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "digest_completion", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/cover", json=self._payload(2), headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["mode"], "composite")
        self.assertEqual(data["model"], "ten-cover:composite-asis2")
        self.assertFalse(data["left_is_ai"])
        self.assertFalse(data["right_is_ai"])
        img = Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")
        w, h = img.size
        y = round(h * 0.30)
        self.assertEqual(img.getpixel((w // 4, y)), (200, 30, 30))
        self.assertEqual(img.getpixel((3 * w // 4, y)), (30, 30, 200))
        self.assertFalse(_ai_note_region_is_plate(img, align_right=False))
        self.assertFalse(_ai_note_region_is_plate(img, align_right=True))

    def test_single_asis_is_full_bleed_without_any_api_call(self):
        # 2026-09-06 使用者裁決：只上傳一張原圖就是整版鋪滿，不切左右格、不生另一格
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "digest_completion", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/cover", json=self._payload(1), headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["model"], "ten-cover:composite-asis1")
        self.assertFalse(data["left_is_ai"])
        self.assertFalse(data["right_is_ai"])
        img = Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")
        w, h = img.size
        y = round(h * 0.30)
        # 左、中、右都是同一張圖，中間沒有白色斜線
        for x in (w // 4, w // 2, 3 * w // 4):
            self.assertEqual(img.getpixel((x, y)), (200, 30, 30), x)
        self.assertFalse(_ai_note_region_is_plate(img, align_right=False))
        self.assertFalse(_ai_note_region_is_plate(img, align_right=True))

    def test_no_asis_keeps_requested_ai_mode(self):
        def fake_generate(req):
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_bytes(size=(1280, 720))).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_generate), \
             patch.object(main, "resolve_cover_visuals", return_value=("左", "右")):
            res = client.post("/api/editor/cover", json=self._payload(0), headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["mode"], "ai")
        self.assertTrue(res.json()["left_is_ai"])


    def test_ai_mode_passes_scene_reference_to_the_image_model(self):
        seen = {}

        def fake_generate(req):
            seen["refs"] = list(req.reference_images)
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_bytes(size=(1280, 720))).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        payload = self._payload(0)
        payload["reference_images"] = [{"data_url": _data_url(_png_bytes()), "purpose": "scene"}]
        with patch.object(main, "generate_image_raw", side_effect=fake_generate),              patch.object(main, "resolve_cover_visuals", return_value=("左", "右")):
            res = client.post("/api/editor/cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["mode"], "ai")
        self.assertEqual(len(seen["refs"]), 1)
        self.assertEqual(seen["refs"][0].purpose, "scene")


class TitleDigestTests(unittest.TestCase):
    """貼新聞內文 → 回填標題，不接生圖（2026-09-06 使用者裁決）。"""

    @staticmethod
    def _completion(payload: dict):
        from types import SimpleNamespace
        import json
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])

    def test_ten_cover_titles_fill_back_and_do_not_generate(self):
        seen = {}

        def fake_digest(**kw):
            seen.update(kw)
            return self._completion({"title_left": "尼泊爾災區 無人機空拍 滅村慘況", "title_right": "台南易淹水 成氣候衝擊區"})

        with patch.object(main, "digest_completion", side_effect=fake_digest), \
             patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/cover-titles", json={"news_text": "尼泊爾山區暴雨引發土石流，數個村落遭掩埋，臺南多處低窪地區也傳出淹水。", "target": "ten_cover"}, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["title_left"], "尼泊爾災區 無人機空拍 滅村慘況")
        self.assertEqual(res.json()["title_right"], "台南易淹水 成氣候衝擊區")
        # 忠實度規則要跟著 system prompt 進去
        self.assertIn("CONTENT FIDELITY", seen["system_prompt"])
        self.assertIn("title_left", seen["schema"]["properties"])

    def test_yt_cover_title_fills_back(self):
        with patch.object(main, "digest_completion", return_value=self._completion({"title": "尼泊爾洪災罹難破千人 直擊現場救援情況"})):
            res = client.post("/api/editor/cover-titles", json={"news_text": "尼泊爾洪災造成上千人罹難，救援人員持續在災區搜救。", "target": "yt_cover"}, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["title"], "尼泊爾洪災罹難破千人 直擊現場救援情況")

    def test_model_failure_is_a_502_not_a_500(self):
        with patch.object(main, "digest_completion", side_effect=RuntimeError("boom")):
            res = client.post("/api/editor/cover-titles", json={"news_text": "這是一段夠長的測試新聞內文，用來觸發失敗路徑。", "target": "ten_cover"}, headers=_headers())
        self.assertEqual(res.status_code, 502)

    def test_ten_titles_are_clipped_to_field_limits(self):
        with patch.object(main, "digest_completion", return_value=self._completion({"title_left": "字" * 80, "title_right": "右 標題"})):
            res = client.post("/api/editor/cover-titles", json={"news_text": "這是一段夠長的測試新聞內文，用來檢查裁切。", "target": "ten_cover"}, headers=_headers())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["title_left"]), 40)


class PromptSyncTests(unittest.TestCase):
    """純 AI 版的 prompt 要跟合成版畫的同一個版面（斜切全幅、標頭帶、白黃紅逐行）。"""

    def test_prompt_describes_diagonal_full_bleed_layout(self):
        # 2026-09-09（第二輪）使用者：「藍框區域稍微變大一點點」——帶不再叫 THIN，
        # 高度也不再手寫，改成從 compose.COVER_AI_HEADER_RATIO 推（見
        # test_followups_20260909c.HeaderBandPromptTests）。
        prompt = editor_formats.COVER_AI_PROMPT_TEMPLATE
        self.assertIn("DIAGONAL seam", prompt)
        self.assertIn("deep-navy header band", prompt)
        self.assertIn("glowing straight blue light line", prompt)

    def test_prompt_colour_names_match_the_composite_table(self):
        """2026-09-08：顏色改成逐行標記（white／yellow／red），模板只講怎麼讀標記。"""
        prompt = editor_formats.COVER_AI_PROMPT_TEMPLATE
        self.assertIn("(white) = solid white", prompt)
        self.assertIn("(yellow) = bright golden yellow", prompt)
        self.assertIn("(red) = vivid red with a white outline", prompt)
        self.assertEqual(compose.COVER_TITLE_LINE_COLOURS[0], (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
