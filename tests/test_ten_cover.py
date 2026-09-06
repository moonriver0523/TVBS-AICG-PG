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

    def test_header_band_and_wave_are_drawn(self):
        img = self._cover()
        w, h = img.size
        self.assertEqual(img.getpixel((w // 2, 6)), compose.COVER_HEADER_FILL)
        # 底部波紋飾條：最底一列是藍色系（不是底圖的紅／藍純色）
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
    """純 AI 版的 prompt 要跟合成版畫的同一個版面（斜切全幅、薄標頭帶、白黃紅逐行）。"""

    def test_prompt_describes_diagonal_full_bleed_layout(self):
        prompt = editor_formats.COVER_AI_PROMPT_TEMPLATE
        self.assertIn("DIAGONAL seam", prompt)
        self.assertIn("THIN deep-navy header band", prompt)
        self.assertIn("decorative wave strip", prompt)

    def test_prompt_colour_order_matches_composite_table(self):
        prompt = editor_formats.COVER_AI_PROMPT_TEMPLATE
        self.assertIn("FIRST line solid white", prompt)
        self.assertIn("SECOND line bright golden yellow", prompt)
        self.assertIn("THIRD line (if any) vivid red", prompt)
        self.assertEqual(compose.COVER_TITLE_LINE_COLOURS[0], (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
