"""AI 標題疊在程式拼好的底圖上（2026-09-13 使用者裁決，三條合一）：

1. 原圖放置＋AI 標題不再強制程式壓字：原圖裁滿版（N 張切格）當唯一附圖，模型只畫字。
2. 雙切（十點／YT 雙則）附圖位有 AI改圖 或原圖＋AI 標題 → 兩段生圖：每格各自取得後拼底圖，
   再整張送模型畫字。以前整張 AI 版把兩格參考混進同一張 16:9（雙切各自 AI改圖 失效的真因），
   YT 雙則更是直接丟掉附圖位（附圖=0）。
3. 滿版合成版放幾張原圖就自動切幾格（以前只放第 1 張）。

釘句 AI_TITLE_BASE_IMAGE_NOTE 插在第一個 TEXT TO RENDER 之前，不做模板佔位。
"""

import base64
import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

RED, BLUE, GREEN = (200, 30, 30), (30, 30, 200), (30, 200, 30)


def _ref(colour, purpose):
    return {"data_url": _data_url(_png_bytes(colour=colour)), "purpose": purpose}


def _decode(data) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")


def _base_image(req) -> Image.Image:
    """第二段送模型的底圖（JPEG data URL，見 main._base_data_url）。"""
    return Image.open(io.BytesIO(base64.b64decode(req.reference_images[0].data_url.split(",", 1)[1]))).convert("RGB")


def _near(pixel, colour, tol=3) -> bool:
    # 底圖走 JPEG q=90，純色塊會差 1–2
    return all(abs(a - b) <= tol for a, b in zip(pixel, colour))


class _Harness(unittest.TestCase):
    def _run(self, url, body):
        calls = []

        def fake_raw(req):
            calls.append(req)
            w, h = {"1:1": (1024, 1024)}.get(req.aspect_ratio, (1280, 720))
            return SimpleNamespace(
                image_data_base64=base64.b64encode(_png_bytes(size=(w, h), colour=GREEN)).decode(),
                model="fake", mime_type="image/png",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
                patch.object(main, "resolve_cover_visuals", return_value=("左景", "右景")), \
                patch.object(main, "derive_yt_cover_plan", return_value={"visual": "景"}), \
                patch.object(main, "_archive_generation", lambda **k: None), \
                patch.object(main, "supports_multiple_reference_images", return_value=True):
            res = client.post(url, json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text[:300])
        return res.json(), calls


class NoteInjection(unittest.TestCase):
    def test_note_goes_before_first_text_to_render(self):
        prompt = "=== CANVAS ===\nx\n\n=== TEXT TO RENDER ===\ny\n=== TEXT TO RENDER ===\nz"
        out = editor_formats.with_base_image_note(prompt, True)
        self.assertEqual(out.count(editor_formats.AI_TITLE_BASE_IMAGE_NOTE), 1)
        self.assertLess(out.index("FINISHED PICTURE"), out.index("=== TEXT TO RENDER"))
        self.assertGreater(out.index("FINISHED PICTURE"), out.index("=== CANVAS ==="))

    def test_without_base_prompt_is_untouched(self):
        self.assertEqual(editor_formats.with_base_image_note("abc", False), "abc")

    def test_templates_still_format_without_the_note(self):
        # 不做模板佔位：既有直接 format 模板的測試一個都不用改
        self.assertNotIn("{base_image_note}", editor_formats.COVER_AI_PROMPT_TEMPLATE)
        self.assertNotIn("{base_image_note}", editor_formats.YT_COVER_FULL_PROMPT_HOURLY)


class TenCoverOverBase(_Harness):
    BASE = {"title_left": "川普發布「擴張版」美國地圖", "provider": "gpt", "date_text": "2026/09/13"}

    def test_full_single_asis_ai_title_one_call_with_only_the_photo(self):
        data, calls = self._run("/api/editor/cover", {
            **self.BASE, "title_right": "", "layout": "full", "mode": "ai",
            "slot_left": [_ref(RED, "asis")],
        })
        self.assertEqual(data["mode"], "ai")
        self.assertEqual(len(calls), 1)
        req = calls[0]
        self.assertEqual(req.aspect_ratio, "16:9")
        self.assertEqual([r.purpose for r in req.reference_images], ["aiedit"])
        self.assertEqual(req.portrait_subjects, [])
        self.assertIn("THE ATTACHED IMAGE IS THE FINISHED PICTURE", req.prompt)
        self.assertIn(main.USER_REFERENCE_MODES["aiedit"], req.prompt)
        # 唯一附圖就是那張原圖裁滿版
        base = _base_image(req)
        self.assertEqual(base.size, compose.COVER_CANVAS)
        self.assertTrue(_near(base.getpixel((base.width // 2, base.height // 2)), RED))

    def test_full_two_asis_ai_title_base_is_a_two_panel_grid(self):
        data, calls = self._run("/api/editor/cover", {
            **self.BASE, "title_right": "", "layout": "full", "mode": "ai",
            "slot_left": [_ref(RED, "asis"), _ref(BLUE, "asis")],
        })
        self.assertEqual(len(calls), 1)
        base = _base_image(calls[0])
        w, h = base.size
        self.assertTrue(_near(base.getpixel((w // 4, h // 2)), RED))
        self.assertTrue(_near(base.getpixel((3 * w // 4, h // 2)), BLUE))

    def test_split_asis_left_aiedit_right_two_stage(self):
        data, calls = self._run("/api/editor/cover", {
            **self.BASE, "title_right": "涵蓋加墨格陵蘭冰島等", "layout": "split", "mode": "ai",
            "slot_left": [_ref(RED, "asis")], "slot_right": [_ref(BLUE, "aiedit")],
        })
        self.assertEqual(data["mode"], "ai")
        self.assertEqual([c.aspect_ratio for c in calls], ["1:1", "16:9"])
        self.assertEqual([r.purpose for r in calls[0].reference_images], ["aiedit"], "右格帶自己的 AI改圖")
        self.assertEqual([r.purpose for r in calls[1].reference_images], ["aiedit"], "第二段只收拼好的底圖")
        base = _base_image(calls[1])
        w, h = base.size
        self.assertTrue(_near(base.getpixel((w // 4, h // 2)), RED), "左格＝原圖")
        self.assertTrue(_near(base.getpixel((3 * w // 4, h // 2)), GREEN), "右格＝生出來的圖")
        self.assertIn("THE ATTACHED IMAGE IS THE FINISHED PICTURE", calls[1].prompt)

    def test_split_each_side_aiedit_gets_its_own_reference(self):
        left, right = _ref(RED, "aiedit"), _ref(BLUE, "aiedit")
        data, calls = self._run("/api/editor/cover", {
            **self.BASE, "title_right": "涵蓋加墨格陵蘭冰島等", "layout": "split", "mode": "ai",
            "slot_left": [left], "slot_right": [right],
        })
        self.assertEqual(len(calls), 3)
        urls = [[r.data_url for r in c.reference_images] for c in calls[:2]]
        self.assertIn([left["data_url"]], urls)
        self.assertIn([right["data_url"]], urls)

    def test_split_no_attachments_stays_single_call(self):
        data, calls = self._run("/api/editor/cover", {
            **self.BASE, "title_right": "涵蓋加墨格陵蘭冰島等", "layout": "split", "mode": "ai",
        })
        self.assertEqual(len(calls), 1)
        self.assertNotIn("FINISHED PICTURE", calls[0].prompt)

    def test_full_mixed_asis_and_aiedit_becomes_all_aiedit_single_call(self):
        """任一張選 AI改圖 → 整版鎖 AI改圖、合成一張：原圖那張不再搶先裁滿版把 AI改圖 丟掉。"""
        data, calls = self._run("/api/editor/cover", {
            **self.BASE, "title_right": "", "layout": "full", "mode": "ai",
            "slot_left": [_ref(RED, "asis"), _ref(BLUE, "aiedit")],
        })
        self.assertEqual(len(calls), 1)
        self.assertEqual([r.purpose for r in calls[0].reference_images], ["aiedit", "aiedit"])
        self.assertNotIn("FINISHED PICTURE", calls[0].prompt, "沒有程式底圖，模型自己合成")

    def test_full_mixed_in_composite_generates_with_both_as_aiedit(self):
        data, calls = self._run("/api/editor/cover", {
            **self.BASE, "title_right": "", "layout": "full", "mode": "composite",
            "slot_left": [_ref(RED, "asis"), _ref(BLUE, "aiedit")],
        })
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].aspect_ratio, "16:9")
        self.assertEqual([r.purpose for r in calls[0].reference_images], ["aiedit", "aiedit"])
        self.assertTrue(data["left_is_ai"])

    def test_stage_two_does_not_carry_the_instruction_again(self):
        data, calls = self._run("/api/editor/cover", {
            **self.BASE, "title_right": "涵蓋加墨格陵蘭冰島等", "layout": "split", "mode": "ai",
            "instruction": "改成夜景",
            "slot_left": [_ref(RED, "asis")], "slot_right": [_ref(BLUE, "aiedit")],
        })
        self.assertEqual(calls[0].editor_instruction, "改成夜景", "第一段那格吃指令")
        self.assertEqual(calls[1].editor_instruction, "", "第二段不再對底圖改畫面")

    def test_full_composite_two_asis_auto_grid(self):
        data, calls = self._run("/api/editor/cover", {
            **self.BASE, "title_right": "", "layout": "full", "mode": "composite",
            "slot_left": [_ref(RED, "asis"), _ref(BLUE, "asis")],
        })
        self.assertEqual(calls, [])
        img = _decode(data)
        w, h = img.size
        y = round(h * 0.30)
        self.assertEqual(img.getpixel((w // 4, y)), RED)
        self.assertEqual(img.getpixel((3 * w // 4, y)), BLUE)
        self.assertFalse(data["left_is_ai"])


class YtCoverOverBase(_Harness):
    def test_dual_ai_title_forwards_each_slot_then_draws_over_base(self):
        left, right = _ref(RED, "aiedit"), _ref(BLUE, "asis")
        data, calls = self._run("/api/editor/yt-cover", {
            # 標題要夠長：整點極短標題（首段 ≤5 格）本來就強制程式壓字，別讓那條規則混進來
            "title": "川普發布擴張版美國地圖", "title_second": "涵蓋加墨格陵蘭冰島等地", "layout": "hourly", "title_mode": "ai",
            "date_text": "2026/09/13", "slot_left": [left], "slot_right": [right],
        })
        self.assertEqual(data["title_mode"], "ai")
        self.assertEqual([c.aspect_ratio for c in calls], ["1:1", "16:9"])
        self.assertEqual([r.data_url for r in calls[0].reference_images], [left["data_url"]])
        self.assertEqual([r.purpose for r in calls[1].reference_images], ["aiedit"])
        self.assertIn("THE ATTACHED IMAGE IS THE FINISHED PICTURE", calls[1].prompt)

    def test_single_two_asis_ai_title_base_is_split_grid(self):
        data, calls = self._run("/api/editor/yt-cover", {
            "title": "前段 後段", "layout": "news", "title_mode": "ai", "date_text": "2026/09/13",
            "reference_images": [_ref(RED, "asis"), _ref(BLUE, "asis")],
        })
        self.assertEqual(len(calls), 1)
        base = _base_image(calls[0])
        w, h = base.size
        self.assertTrue(_near(base.getpixel((w // 4, h // 2)), RED))
        self.assertTrue(_near(base.getpixel((3 * w // 4, h // 2)), BLUE))

    def test_single_mixed_slot_becomes_all_aiedit(self):
        data, calls = self._run("/api/editor/yt-cover", {
            "title": "川普發布擴張版美國地圖 涵蓋加墨格陵蘭冰島", "layout": "hourly", "title_mode": "ai",
            "date_text": "2026/09/13",
            "slot_left": [_ref(RED, "asis"), _ref(BLUE, "aiedit")],
        })
        self.assertEqual(len(calls), 1)
        self.assertEqual([r.purpose for r in calls[0].reference_images], ["aiedit", "aiedit"])
        self.assertNotIn("FINISHED PICTURE", calls[0].prompt)

    def test_refine_return_trip_does_not_rebuild_the_base(self):
        # 追加修改帶 background 回來：只重貼固定元素，不該再打模型
        data, calls = self._run("/api/editor/yt-cover", {
            "title": "前段 後段", "layout": "news", "title_mode": "ai", "date_text": "2026/09/13",
            "reference_images": [_ref(RED, "asis")],
            "background_image_base64": base64.b64encode(_png_bytes(size=(1280, 720))).decode(),
            "background_is_ai": True,
        })
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
