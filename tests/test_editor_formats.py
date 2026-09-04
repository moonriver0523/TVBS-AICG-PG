"""編輯專屬版型（2026-09-03）：防呆、幾何、與 app.js 的同步。

三條紅線：
1. **記者不可以拿到編輯的版型規則。** 這是使用者提需求時第一個講的顧慮。
   前端有兩層（下拉不顯示、切回記者重置），這裡守後端那層。
2. **挖空框必須剛好 16:9。** 那個框的整個存在意義就是給後製放影片對位，
   1.7785 這種「差不多」會讓影片邊緣露出底圖。
3. **前後端版型清單必須同步。** 只改一邊不會有執行期錯誤，只會讓使用者選了
   一個後端不認得的 key，然後靜靜退回 default——圖出來少一個洞卻沒人知道。
"""

import io
import os
import pathlib
import re
import unittest

from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import safe_area_spec  # noqa: E402
from main import build_digest_instructions  # noqa: E402

APP_JS = pathlib.Path(__file__).resolve().parent.parent / "app.js"
BROADCAST_MARKER = "BROADCAST INSERT LAYOUT"


class RoleGuardTests(unittest.TestCase):
    def test_reporter_never_gets_editor_rules(self):
        for key in editor_formats.EDITOR_FORMAT_KEYS:
            with self.subTest(key=key):
                self.assertEqual(editor_formats.digest_rules(key, "記者"), "")
                self.assertIsNone(editor_formats.hole_side(key, "記者"))

    def test_reporter_digest_prompt_is_untouched(self):
        plain = build_digest_instructions("記者", "standard", "資料圖表")
        for key in editor_formats.EDITOR_FORMAT_KEYS:
            with self.subTest(key=key):
                self.assertEqual(
                    build_digest_instructions("記者", "standard", "資料圖表", editor_format=key),
                    plain,
                    "記者的消化指令不得因為編輯版型而改變一個字",
                )

    def test_editor_default_injects_nothing(self):
        self.assertEqual(
            build_digest_instructions("編輯", "standard", "資料圖表"),
            build_digest_instructions(
                "編輯", "standard", "資料圖表", editor_format=editor_formats.DEFAULT_FORMAT
            ),
        )

    def test_unknown_format_falls_back_to_default(self):
        self.assertEqual(editor_formats.get("no-such-format"), editor_formats.get(None))
        self.assertEqual(editor_formats.digest_rules("no-such-format", "編輯"), "")


class BroadcastDigestRulesTests(unittest.TestCase):
    def test_only_broadcast_formats_inject_the_block(self):
        for key in editor_formats.EDITOR_FORMAT_KEYS:
            with self.subTest(key=key):
                text = build_digest_instructions("編輯", "simplified", "資料圖表", editor_format=key)
                self.assertEqual(BROADCAST_MARKER in text, key.startswith("broadcast_"))

    def test_each_side_talks_about_its_own_side(self):
        left = build_digest_instructions("編輯", "simplified", "資料圖表", editor_format="broadcast_left")
        right = build_digest_instructions("編輯", "simplified", "資料圖表", editor_format="broadcast_right")
        self.assertIn("the left half of the frame, centred vertically", left)
        self.assertIn("the right half of the frame, centred vertically", right)
        self.assertNotIn("the right half of the frame, centred vertically", left)
        self.assertNotIn("the left half of the frame, centred vertically", right)

    def test_hole_is_vertically_centred(self):
        # 2026-09-03 使用者裁決：不要置底，往上靠中間
        for side in compose.BROADCAST_SIDES:
            with self.subTest(side=side):
                _, y0, _, y1 = compose.broadcast_hole_rect(safe_area_spec.BASE_CANVAS, side)
                self.assertLess(
                    abs((y0 + y1) // 2 - safe_area_spec.BASE_CANVAS[1] // 2), 6,
                    "挖空框的垂直中心應該貼近畫布中心",
                )

    def test_rules_carry_no_digits(self):
        # 數字會被模型當文字畫進圖裡（docs/error-cases/2026-07-23-像素安全框-分析.md）。
        # 條列編號本身不算，只檢查句子內容。
        for key in ("broadcast_left", "broadcast_right"):
            with self.subTest(key=key):
                body = editor_formats.get(key)["digest_rules"]
                sentences = re.sub(r"(?m)^\d+\.", "", body)
                # 三點的「three」刻意用英文字，不用阿拉伯數字
                self.assertNotRegex(sentences, r"\d", "版型規則裡不得出現任何數字")

    def test_rules_override_the_centred_layout_sentence(self):
        text = editor_formats.get("broadcast_left")["digest_rules"]
        self.assertIn("FOR THIS FORMAT IT IS NOT CENTRED", text)


class HoleGeometryTests(unittest.TestCase):
    CANVAS = safe_area_spec.BASE_CANVAS

    def test_hole_is_exactly_16_by_9(self):
        for side in compose.BROADCAST_SIDES:
            with self.subTest(side=side):
                x0, y0, x1, y1 = compose.broadcast_hole_rect(self.CANVAS, side)
                width, height = x1 - x0, y1 - y0
                self.assertEqual(width * 9, height * 16, f"{width}x{height} 不是剛好 16:9")

    def test_hole_stays_inside_the_safe_area(self):
        sx0, sy0, sx1, sy1 = safe_area_spec.safe_rect(
            *self.CANVAS, safe_area_spec.EDITOR_FRAME_PROFILE
        )
        for side in compose.BROADCAST_SIDES:
            with self.subTest(side=side):
                x0, y0, x1, y1 = compose.broadcast_hole_rect(self.CANVAS, side)
                self.assertGreaterEqual(x0, sx0)
                self.assertGreaterEqual(y0, sy0)
                self.assertLessEqual(x1, sx1)
                self.assertLessEqual(y1, sy1)

    def test_sides_land_on_opposite_halves(self):
        left = compose.broadcast_hole_rect(self.CANVAS, "left")
        right = compose.broadcast_hole_rect(self.CANVAS, "right")
        self.assertLess(left[2], self.CANVAS[0] / 2 + 1)
        self.assertGreater(right[0], self.CANVAS[0] / 2 - 1)

    def test_unknown_side_is_rejected(self):
        with self.assertRaises(compose.ComposeError):
            compose.broadcast_hole_rect(self.CANVAS, "middle")


def _solid(size, colour=(20, 30, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


class ComposeOutputTests(unittest.TestCase):
    def test_hole_is_actually_painted(self):
        holed = compose.apply_broadcast_hole(_solid(safe_area_spec.BASE_CANVAS), "left")
        with Image.open(io.BytesIO(holed)) as image:
            x0, y0, x1, y1 = compose.broadcast_hole_rect(image.size, "left")
            centre = image.convert("RGB").getpixel(((x0 + x1) // 2, (y0 + y1) // 2))
            self.assertEqual(centre, compose.HOLE_FILL)
            # 對側同高度必須還是原本的底圖，不能整條被蓋掉
            outside = image.convert("RGB").getpixel((image.width - 60, (y0 + y1) // 2))
            self.assertEqual(outside, (20, 30, 60))

    def test_cover_output_is_full_hd(self):
        cover = compose.compose_ten_cover(
            _solid((512, 512), (40, 60, 90)),
            _solid((512, 512), (90, 40, 40)),
            title_left="政府明年勞保撥補上看1300億",
            title_right="病理醫師月薪65萬仍缺工",
            date_text="2026/09/03",
        )
        with Image.open(io.BytesIO(cover)) as image:
            self.assertEqual(image.size, compose.COVER_CANVAS)

    def test_cover_rejects_unknown_badge(self):
        with self.assertRaises(compose.ComposeError):
            compose.compose_ten_cover(
                _solid((64, 64)), _solid((64, 64)),
                title_left="A", title_right="B", date_text="", badge="nope",
            )

    def test_logo_is_the_dotted_wordmark_from_the_reference(self):
        # 2026-09-03 使用者指定改用範例圖上那顆（帶點陣圖樣），不是純字標。
        # 純字標仍留在 tvbs-logo-white-plain.png 當備援。
        with Image.open(compose.TVBS_LOGO_WHITE) as logo:
            ratio = logo.width / logo.height
        self.assertLess(ratio, 2.35, "看起來還是舊的純字標（比例太寬）")
        self.assertTrue(
            (compose.BRAND_DIR / "tvbs-logo-white-plain.png").exists(),
            "舊的純字標備援不見了",
        )

    def test_white_logo_asset_exists_and_is_white(self):
        self.assertTrue(compose.TVBS_LOGO_WHITE.exists(), "白色 Logo 素材不見了")
        with Image.open(compose.TVBS_LOGO_WHITE) as logo:
            self.assertEqual(logo.mode, "RGBA", "Logo 必須去背，否則會帶一塊方底")
            opaque = [px for px in logo.convert("RGBA").getdata() if px[3] > 200]
            self.assertTrue(opaque, "Logo 沒有任何不透明像素")
            # 使用者指定要白色版本，不是原始的藍色
            self.assertTrue(
                all(px[0] > 240 and px[1] > 240 and px[2] > 240 for px in opaque),
                "Logo 不是白色的",
            )


class CoverPromptTests(unittest.TestCase):
    """純 prompt 版封面（2026-09-03 取代合成版當預設）。

    唯一的後製只剩 Logo，所以 prompt 必須自己扛住兩件事：
    使用者給的字要逐字畫出來、而且不准模型自己畫台標。
    """

    def render(self, **overrides):
        fields = {
            "badge_text": "ON AIR",
            "date_text": "2026/09/03",
            "title_left": "政府明年勞保撥補上看1300億",
            "title_right": "病理醫師月薪65萬仍缺工",
            "visual_left": "政府大樓與金幣",
            "visual_right": "病理科實驗室",
        }
        fields.update(overrides)
        return editor_formats.COVER_AI_PROMPT_TEMPLATE.format(**fields)

    def test_every_user_string_reaches_the_prompt(self):
        prompt = self.render()
        for needle in (
            "十點不一樣", "ON AIR", "2026/09/03", "AI示意圖",
            "政府明年勞保撥補上看1300億", "病理醫師月薪65萬仍缺工",
            "政府大樓與金幣", "病理科實驗室",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, prompt)

    def test_prompt_forbids_the_model_drawing_a_logo(self):
        prompt = self.render()
        self.assertIn("NO television channel logo", prompt)
        self.assertIn("upper-LEFT corner", prompt)

    def test_programme_name_is_not_metallic(self):
        # 2026-09-03 使用者裁決：十點不一樣不要金屬材質，照範例圖的平面白字
        prompt = self.render()
        self.assertIn("FLAT, SOLID WHITE", prompt)
        for banned in ("metallic", "chrome", "bevelled", "3-D extruded"):
            with self.subTest(banned=banned):
                self.assertIn(banned, prompt.split("=== IMAGERY ===")[0])

    def test_headlines_must_vary_colour_per_line(self):
        # 範例圖的標題是分行、每行不同顏色（白／紅／金），不是整段一個顏色
        prompt = self.render()
        self.assertIn("STACKED LINES", prompt)
        self.assertIn("COLOUR EACH LINE DIFFERENTLY", prompt)
        self.assertIn("Never render a whole headline in one flat colour", prompt)

    def test_prompt_forbids_extra_text(self):
        self.assertIn("Do not translate them", self.render())
        self.assertIn("No text other than the strings listed above", self.render())

    def test_ai_mode_is_the_default_cover(self):
        self.assertEqual(
            editor_formats.cover_mode("ten_cover"), editor_formats.COVER_MODE_AI
        )
        self.assertEqual(
            editor_formats.cover_mode("ten_cover_composite"),
            editor_formats.COVER_MODE_COMPOSITE,
        )

    def test_composite_version_is_still_reachable(self):
        # 使用者要求「現在的架構先另存」——這條紅了代表備援被順手刪掉了
        self.assertIn("ten_cover_composite", editor_formats.EDITOR_FORMAT_KEYS)
        self.assertTrue(hasattr(compose, "compose_ten_cover"))


class CoverVisualFallbackTests(unittest.TestCase):
    """畫面描述改選填（2026-09-03 使用者要求）：留空由 AI 依標題補，有填照使用者的。"""

    def req(self, **kw):
        from main import TenCoverRequest
        fields = {"title_left": "政府明年勞保撥補上看1300億", "title_right": "病理醫師月薪65萬仍缺工"}
        fields.update(kw)
        return TenCoverRequest(**fields)

    def test_both_fields_are_optional(self):
        request = self.req()
        self.assertEqual(request.visual_left, "")
        self.assertEqual(request.visual_right, "")

    def test_both_supplied_skips_the_api_entirely(self):
        import main
        called = []
        original = main.digest_completion
        main.digest_completion = lambda **kw: called.append(kw)
        try:
            result = main.resolve_cover_visuals(
                self.req(visual_left="政府大樓", visual_right="實驗室")
            )
        finally:
            main.digest_completion = original
        self.assertEqual(result, ("政府大樓", "實驗室"))
        self.assertEqual(called, [], "兩欄都有值時不該打 API")

    def test_user_value_wins_over_the_derived_one(self):
        import main
        original = main.digest_completion

        class _Fake:
            choices = [type("C", (), {"message": type("M", (), {"content": '{"visual_left":"AI左","visual_right":"AI右"}'})()})()]

        main.digest_completion = lambda **kw: _Fake()
        try:
            left, right = main.resolve_cover_visuals(self.req(visual_left="使用者左"))
        finally:
            main.digest_completion = original
        self.assertEqual(left, "使用者左", "使用者填的不可以被 AI 蓋掉")
        self.assertEqual(right, "AI右")

    def test_api_failure_falls_back_to_the_headline(self):
        import main
        original = main.digest_completion

        def boom(**kw):
            raise RuntimeError("upstream down")

        main.digest_completion = boom
        try:
            left, right = main.resolve_cover_visuals(self.req())
        finally:
            main.digest_completion = original
        # 補描述失敗不該讓整張封面失敗
        self.assertEqual(left, "政府明年勞保撥補上看1300億")
        self.assertEqual(right, "病理醫師月薪65萬仍缺工")

    def test_derive_prompt_forbids_text_in_the_photo(self):
        prompt = editor_formats.COVER_VISUAL_DERIVE_SYSTEM
        self.assertIn("NEVER mention text", prompt)
        self.assertIn("Do not restate the headline", prompt)
        self.assertIn("If a side's description is already supplied", prompt)

    def test_response_reports_the_visuals_actually_used(self):
        from main import TenCoverResponse
        response = TenCoverResponse(
            image_data_base64="x", mime_type="image/png", model="m",
            visual_left="L", visual_right="R",
        )
        self.assertEqual((response.visual_left, response.visual_right), ("L", "R"))


class FrontendParityTests(unittest.TestCase):
    """app.js 的 EDITOR_FORMATS 與 editor_formats.py 必須同步。"""

    def js_entries(self) -> dict[str, str]:
        """把 app.js 的 EDITOR_FORMATS 切成 {key: 那一筆的原始文字}。

        刻意先切成一筆一筆再各自比對：整段一起 findall 會讓 .*? 跨越好幾筆，
        把後面那筆的欄位配到前面那個 key 上（實測就是這樣紅的）。
        """
        source = io.open(APP_JS, encoding="utf-8").read()
        block = re.search(r"const EDITOR_FORMATS = \{(.*?)\n\};", source, re.S)
        self.assertIsNotNone(block, "app.js 裡找不到 EDITOR_FORMATS")
        body = block.group(1)
        headers = list(re.finditer(r"(?m)^    (\w+):\s*\{", body))
        entries = {}
        for index, match in enumerate(headers):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(body)
            entries[match.group(1)] = body[match.start():end]
        return entries

    def js_formats(self) -> dict[str, str]:
        return {
            key: re.search(r"label:\s*'([^']+)'", text).group(1)
            for key, text in self.js_entries().items()
        }

    def test_keys_match(self):
        self.assertEqual(
            sorted(self.js_formats()), sorted(editor_formats.EDITOR_FORMAT_KEYS)
        )

    def test_labels_match(self):
        for key, label in self.js_formats().items():
            with self.subTest(key=key):
                self.assertEqual(label, editor_formats.EDITOR_FORMATS[key]["label"])

    def test_cover_modes_match(self):
        for key, text in self.js_entries().items():
            found = re.search(r"coverMode:\s*'(\w+)'", text)
            with self.subTest(key=key):
                self.assertEqual(
                    found.group(1) if found else "", editor_formats.cover_mode(key)
                )

    def test_hole_sides_match(self):
        for key, text in self.js_entries().items():
            raw = re.search(r"hole:\s*(null|'\w+')", text).group(1)
            with self.subTest(key=key):
                self.assertEqual(
                    None if raw == "null" else raw.strip("'"),
                    editor_formats.EDITOR_FORMATS[key]["hole_side"],
                )



class LockScopeTests(FrontendParityTests):
    """2026-09-04 使用者回報「播出鏡面下面的按鈕全都不能選」。

    查下來我當初鎖了四個，只有版面形式是真的必要——它跟挖空框互相打架。
    安全框（ON／OFF 都是合法安全區，挖空框都算得出正確位置）、蓋章、字多字少
    都只是建議值，鎖住是我鎖過頭。使用者裁決：只鎖版面形式。
    """

    def test_broadcast_locks_only_the_chart_type(self):
        for key in ("broadcast_left", "broadcast_right"):
            with self.subTest(key=key):
                entry = self.js_entries()[key]
                locks = re.search(r"locks:\s*\{([^}]*)\}", entry).group(1)
                self.assertIn("chartType", locks)
                for freed in ("safeFrame", "stamp", "density"):
                    self.assertNotIn(freed, locks, f"{freed} 不該再被鎖住")

    def test_broadcast_still_presets_the_recommended_values(self):
        # 解鎖不等於不幫忙：切過去仍要幫使用者調好，只是調完可以改
        for key in ("broadcast_left", "broadcast_right"):
            with self.subTest(key=key):
                presets = re.search(r"presets:\s*\{([^}]*)\}", self.js_entries()[key])
                self.assertIsNotNone(presets, "播出鏡面應該還有預設值")
                for field in ("safeFrame", "stamp", "density"):
                    self.assertIn(field, presets.group(1))

    def test_cover_hides_the_controls_it_cannot_use(self):
        # /api/editor/cover 不收 density／stamp／safe_frame／tone，
        # 留一排點不動的灰按鈕只會被當成壞掉——收起來，不是鎖起來
        for key in ("ten_cover", "ten_cover_composite"):
            with self.subTest(key=key):
                entry = self.js_entries()[key]
                hides = re.search(r"hides:\s*\{([^}]*)\}", entry)
                self.assertIsNotNone(hides, "封面應該把用不到的控制項收起來")
                for field in ("digestControls", "safeFrame", "stamp"):
                    self.assertIn(field, hides.group(1))
                self.assertNotIn("chartType", re.search(r"locks:\s*\{([^}]*)\}", entry).group(1))

    def test_default_format_locks_and_hides_nothing(self):
        entry = self.js_entries()["default"]
        self.assertNotIn("hides", entry)
        self.assertEqual(re.search(r"locks:\s*\{([^}]*)\}", entry).group(1).strip(), "")

    def test_cover_still_lets_the_user_pick_the_engine(self):
        # provider 是 TenCoverRequest 真的會用到的欄位，不可以一起收掉
        for key in ("ten_cover", "ten_cover_composite"):
            with self.subTest(key=key):
                hides = re.search(r"hides:\s*\{([^}]*)\}", self.js_entries()[key]).group(1)
                self.assertNotIn("engine", hides)

if __name__ == "__main__":
    unittest.main()
