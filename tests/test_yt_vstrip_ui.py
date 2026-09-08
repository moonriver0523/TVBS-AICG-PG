"""YT 直播「直標」的端點與前端接線（2026-09-08 WP3）。

直標跟三種 YT 封面不是同一件事：**沒有底圖、不生圖、不打任何模型**，
就是把欄位交給 compose.compose_yt_overlay 畫一張 1920×1080 的透明底 PNG。

守的紅線：
1. **底一定要是透明的。** 回 RGB 就等於帶了一塊黑底，疊到直播訊號上會蓋掉畫面。
2. **格數超標要回 400 且指名是哪一個標題。** 上限寫在 compose，訊息原樣往前端送；
   若 pydantic 先用 max_length 擋掉會變 422，使用者只會看到一句無意義的 validation error。
3. **Logo 不能跟直標同側。** 同側＝白色字標壓在標題字上，成品直接報廢。
4. **LIVE 章可取消。** live=False 時那塊矩形要一個像素都沒有。
5. **前端與後端的版型清單順序一致。** 下拉順序＝物件字面的順序，直標排在整點直播正下方。
"""
import base64
import io
import os
import re
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402

APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GUIDE = ROOT / "docs" / "user-guide-page1.html"

ENDPOINT = "/api/editor/yt-overlay"
MAIN_TITLE = "明早晚涼「中午仍破30度」"      # 12 格（30 併成一格）
SUB_TITLE = "北臺灣週三轉濕涼留意溫差"        # 12 格


def _post(**overrides):
    payload = {"title": MAIN_TITLE}
    payload.update(overrides)
    return client.post(ENDPOINT, json=payload, headers=_headers())


def _image(response) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(response.json()["image_base64"])))


def _alpha_sum(image: Image.Image, box) -> int:
    """一塊矩形裡的 alpha 總和。0＝那一塊完全沒東西。"""
    return sum(image.crop(tuple(box)).getchannel("A").getdata())


class OverlayEndpointTests(unittest.TestCase):
    def test_returns_a_transparent_rgba_png(self):
        res = _post(title_second=SUB_TITLE, source_text="畫面來源：路透社")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["mime_type"], "image/png")
        self.assertEqual((body["width"], body["height"]), compose.YT_CANVAS)
        image = _image(res)
        self.assertEqual(image.mode, "RGBA", "直標必須是 RGBA——RGB 等於帶了一塊不透明底")
        self.assertEqual(image.size, compose.YT_CANVAS)
        # 直標貼左緣，右半中間一定是空的；不空就代表底其實不透明
        width, height = compose.YT_CANVAS
        self.assertEqual(
            _alpha_sum(image, (width // 2, height // 3, width // 2 + 200, height // 3 + 200)),
            0,
            "沒有畫東西的地方 alpha 必須是 0",
        )

    def test_layout_reports_the_cell_counts(self):
        layout = _post(title_second=SUB_TITLE).json()["layout"]
        self.assertEqual(layout["main_cells_count"], len(compose._vertical_cells(MAIN_TITLE)))
        self.assertEqual(layout["sub_cells_count"], len(compose._vertical_cells(SUB_TITLE)))
        # 連續英數字併成一格：「30」是一格不是兩格，前端的提示才跟後端對得起來
        self.assertIn("30", layout["main_cells"])
        self.assertEqual(layout["main_max_cells"], compose.VSTRIP_MAIN_MAX_CELLS)
        self.assertEqual(layout["sub_max_cells"], compose.VSTRIP_SUB_MAX_CELLS)

    def test_main_title_over_the_limit_is_a_400_naming_the_field(self):
        over = "一" * (compose.VSTRIP_MAIN_MAX_CELLS + 1)
        res = _post(title=over)
        self.assertEqual(res.status_code, 400, res.text)
        detail = res.json()["detail"]
        self.assertIn("第一標題", detail)
        self.assertIn(str(compose.VSTRIP_MAIN_MAX_CELLS), detail)

    def test_second_title_over_the_limit_is_a_400_naming_the_field(self):
        over = "一" * (compose.VSTRIP_SUB_MAX_CELLS + 1)
        res = _post(title_second=over)
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("第二標題", res.json()["detail"])

    def test_logo_on_the_same_side_as_the_strip_is_rejected(self):
        for side, corner in (("left", "tl"), ("left", "bl"), ("right", "tr"), ("right", "br")):
            with self.subTest(side=side, corner=corner):
                res = _post(title_side=side, logo_corner=corner)
                self.assertEqual(res.status_code, 400, res.text)
                self.assertIn("直標", res.json()["detail"])

    def test_logo_on_the_far_side_is_accepted(self):
        for side, corner in (("left", "tr"), ("left", "br"), ("right", "tl"), ("right", "bl")):
            with self.subTest(side=side, corner=corner):
                self.assertEqual(_post(title_side=side, logo_corner=corner).status_code, 200)

    def test_live_false_leaves_the_badge_rectangle_empty(self):
        layout = compose.yt_vertical_layout(main_title=MAIN_TITLE)
        box = layout["live"]
        with_badge = _image(_post(live=True))
        without = _image(_post(live=False))
        self.assertGreater(_alpha_sum(with_badge, box), 0, "live=True 應該貼得出 LIVE 章")
        self.assertEqual(_alpha_sum(without, box), 0, "live=False 不准留下任何一個像素")

    def test_variant_label_only_appears_when_asked(self):
        plain = compose.yt_vertical_layout(main_title=MAIN_TITLE, variant="normal")
        self.assertEqual(tuple(plain["label"]), (0, 0, 0, 0))
        labelled = _post(variant="original_audio").json()["layout"]
        self.assertNotEqual(tuple(labelled["label"]), (0, 0, 0, 0))

    def test_unknown_variant_is_rejected_by_the_schema(self):
        self.assertEqual(_post(variant="karaoke").status_code, 422)


class FormatWiringTests(unittest.TestCase):
    """版型清單：後端、前端、下載短名三邊要對得起來。"""

    def test_backend_lists_the_new_format_right_after_the_hourly_one(self):
        keys = list(editor_formats.EDITOR_FORMAT_KEYS)
        self.assertIn("yt_vstrip", keys)
        self.assertEqual(keys[keys.index("yt_hourly_cover") + 1], "yt_vstrip")
        entry = editor_formats.EDITOR_FORMATS["yt_vstrip"]
        self.assertEqual(entry["label"], "YT直播直標")
        self.assertEqual(entry["pipeline"], editor_formats.PIPELINE_YT_OVERLAY)
        self.assertIsNone(entry["hole_side"])

    def _js_format_order(self) -> list[str]:
        block = re.search(r"const EDITOR_FORMATS = \{(.*?)\n\};", APP_JS, re.S)
        self.assertIsNotNone(block, "app.js 裡找不到 EDITOR_FORMATS")
        return re.findall(r"(?m)^    (\w+):\s*\{", block.group(1))

    def test_frontend_dropdown_order_matches_the_backend(self):
        # 下拉順序＝物件字面的順序（renderEditorFormats 走 Object.entries）
        self.assertEqual(self._js_format_order(), list(editor_formats.EDITOR_FORMAT_KEYS))

    def test_frontend_puts_the_new_format_below_the_hourly_one(self):
        order = self._js_format_order()
        self.assertEqual(order[order.index("yt_hourly_cover") + 1], "yt_vstrip")

    def test_frontend_entry_hides_everything_the_format_cannot_use(self):
        entry = re.search(r"(?ms)^    yt_vstrip:\s*\{(.*?)^    \},", APP_JS).group(1)
        self.assertIn("inputs: 'yt_vstrip'", entry)
        hides = re.search(r"hides:\s*\{([^}]*)\}", entry).group(1)
        for field in ("digestControls", "safeFrame", "stamp", "engine", "instruction",
                      "refUpload", "refine"):
            self.assertIn(field, hides, f"{field} 應該對直標收起來")
        # 追加修改整區要真的收掉：只把按鈕 disabled 的話，輸入框還是在那裡等人打字
        self.assertIn("_hide(document.getElementById('refineBox'), !!hides.refine);", APP_JS)

    def test_download_short_name(self):
        self.assertRegex(APP_JS, r"yt_vstrip:\s*'YT直標'")

    def test_cell_counting_helper_exists_in_the_frontend(self):
        self.assertIn("function vstripCells(", APP_JS)
        # 前端要自己擋，不然使用者要按下去才知道超格
        self.assertIn("VSTRIP_MAIN_MAX_CELLS", APP_JS)
        self.assertIn("第一標題超過", APP_JS)

    def test_generate_button_text(self):
        self.assertIn("生成直標（透明 PNG）", APP_JS)

    def test_generate_dispatch(self):
        self.assertIn("handleYtVstripGenerate", APP_JS)
        self.assertIn("/api/editor/yt-overlay", APP_JS)


class MarkupTests(unittest.TestCase):
    """index.html：三個欄位、五組按鈕、一個勾選框。"""

    def test_the_block_is_a_sibling_not_nested_in_the_cover_block(self):
        self.assertIn('id="ytVstripInputs"', INDEX_HTML)
        cover = INDEX_HTML.index('id="ytCoverInputs"')
        vstrip = INDEX_HTML.index('id="ytVstripInputs"')
        self.assertLess(cover, vstrip, "直標欄位要排在 YT 封面欄位之後")

    def test_three_text_fields(self):
        for field in ("vstripTitle", "vstripTitleSecond", "vstripSource"):
            with self.subTest(field=field):
                self.assertIn(f'id="{field}"', INDEX_HTML)

    def test_five_button_groups(self):
        for attribute, values in (
            ("data-vstrip-variant", ("normal", "original_audio", "ai_translation")),
            ("data-vstrip-side", ("left", "right")),
            ("data-vstrip-corner", ("tr", "br", "tl", "bl")),
            ("data-vstrip-source", ("live", "logo")),
        ):
            for value in values:
                with self.subTest(attribute=attribute, value=value):
                    self.assertRegex(
                        INDEX_HTML, rf'{attribute} data-vstrip-value="{value}"'
                    )

    def test_live_badge_checkbox_defaults_to_checked(self):
        checkbox = re.search(r'<input id="vstripLive"[^>]*>', INDEX_HTML).group(0)
        self.assertIn("checked", checkbox)
        self.assertIn("toggleVstripLive", checkbox)

    def test_engine_row_has_an_id_so_it_can_be_hidden(self):
        self.assertIn('id="p1EngineRow"', INDEX_HTML)

    def test_transparent_preview_backdrop_exists(self):
        self.assertIn(".transparent-preview", INDEX_HTML)
        self.assertIn("transparent-preview", APP_JS)


class ManualTests(unittest.TestCase):
    def test_manual_covers_the_seventh_format(self):
        text = GUIDE.read_text(encoding="utf-8")
        self.assertIn("七種版型", text)
        # 標題與側欄不能還停在改版前的「六種版型」
        self.assertNotIn("六種版型", text)
        self.assertIn("YT直播直標", text)
        # 只有標題改了不算：新版型自己那一節要在
        self.assertIn("透明背景", text)


if __name__ == "__main__":
    unittest.main()
