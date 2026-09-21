# -*- coding: utf-8 -*-
"""版型能力矩陣（2026-09-14 模組化第 1 步）。

後端 `editor_formats.FORMAT_CAPABILITIES` 是唯一真相；app.js 的靜態版型表（hides／slots）必須跟它
一致；`GET /api/editor/formats` 免 key 吐出同一份。這一步行為零變更：下面把接線當天 app.js 手寫的
hides 逐字列出來當期望值，證明「資料化」沒有偷偷改到任何一個版型。
"""
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import editor_formats as ef  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")

# 接線當天（2026-09-14）app.js 每個版型手寫的 hides——資料化後推導出來的必須一模一樣。
# 同日稍後對齊第 3 項：國內外新聞直播／今日熱搜改成一標一附圖位，refUpload 跟著收起來
#（這是刻意的行為變更，見 test_yt_shared_layouts_get_slots_20260914）。
# 2026-09-21 B70／F43：新增 disclaimer——「示意圖／畫面來源」標籤控制只有主流程 CG 有，
# 封面類一律收起來（它們走 compose 自己的 _draw_ai_note，不吃 disclaimer_* 欄位）。
# 同樣是刻意的行為變更，所以這份基準跟著更新而不是把新欄位排除在外。
HIDES_ON_2026_09_14 = {
    "default": {},
    "broadcast": {},
    "ten_cover": {"digestControls": True, "safeFrame": True, "stamp": True, "refUpload": True,
                  "disclaimer": True},
    "yt_live_cover": {"digestControls": True, "safeFrame": True, "stamp": True, "refUpload": True,
                      "disclaimer": True},
    "yt_vstrip": {"digestControls": True, "safeFrame": True, "stamp": True, "engine": True,
                  "instruction": True, "refUpload": True, "refine": True,
                  "disclaimer": True},
    "yt_hourly_cover": {"digestControls": True, "safeFrame": True, "stamp": True, "refUpload": True,
                        "disclaimer": True},
    "yt_live24_cover": {"digestControls": True, "safeFrame": True, "stamp": True, "refUpload": True,
                        "disclaimer": True},
    "yt_hot_cover": {"digestControls": True, "safeFrame": True, "stamp": True, "refUpload": True,
                     "disclaimer": True},
}


def _js_entries() -> dict[str, str]:
    block = APP_JS[APP_JS.index("const EDITOR_FORMATS = {"):]
    block = block[:block.index("\n};")]
    return {m.group(1): m.group(2) for m in re.finditer(r"^    (\w+): \{\n(.*?)^    \},", block, re.S | re.M)}


def _js_hides(entry: str) -> dict[str, bool]:
    m = re.search(r"hides:\s*\{([^}]*)\}", entry)
    if not m:
        return {}
    return {k.strip(): True for k in re.findall(r"(\w+):\s*true", m.group(1))}


class TableShape(unittest.TestCase):
    def test_every_format_and_alias_resolves(self):
        self.assertEqual(set(ef.FORMAT_CAPABILITIES), set(ef.EDITOR_FORMATS))
        for alias in ef.EDITOR_FORMAT_ALIAS_KEYS:
            self.assertIs(ef.capability_for(alias), ef.capability_for(alias.split("_left")[0].split("_right")[0].replace("ten_cover_full", "ten_cover")))
        self.assertIs(ef.capability_for("no_such_format"), ef.capability_for(ef.DEFAULT_FORMAT))
        self.assertIs(ef.capability_for(None), ef.capability_for(ef.DEFAULT_FORMAT))

    def test_every_yt_layout_maps_to_a_format(self):
        keys = {ef.yt_format_key(layout) for layout in ef.YT_COVER_LAYOUTS}
        self.assertEqual(keys, {"yt_live_cover", "yt_hourly_cover", "yt_live24_cover", "yt_hot_cover"})
        for key in keys:
            self.assertEqual(ef.EDITOR_FORMATS[key]["yt_layout"], next(l for l in ef.YT_COVER_LAYOUTS if ef.yt_format_key(l) == key))

    def test_hides_are_exactly_what_the_frontend_had_on_wiring_day(self):
        for key, expected in HIDES_ON_2026_09_14.items():
            with self.subTest(format=key):
                self.assertEqual(ef.hides_for(key), expected)

    def test_the_rulings_are_in_the_table(self):
        """今天之前的裁決都要看得到：創意 0 壓字（封面類）、原圖上限 4、只改文字（十點滿版／雙切、YT 合成版都有）、直標什麼都沒有。"""
        for key in ("ten_cover", "yt_live_cover", "yt_hourly_cover", "yt_live24_cover", "yt_hot_cover"):
            self.assertTrue(ef.capability_for(key).zero_program_text, key)
            self.assertEqual(ef.capability_for(key).asis_max, 4, key)
        for key in ("default", "broadcast", "yt_vstrip"):
            self.assertFalse(ef.capability_for(key).zero_program_text, key)
        self.assertEqual(ef.capability_for("ten_cover").text_only_recompose, ("full", "split"))   # 雙切 2026-09-14
        # YT 合成版單則／雙則的只改文字本來就有（ytCoverRecomposeBtn）；整點與 live24 有雙則
        self.assertEqual(ef.capability_for("yt_hourly_cover").text_only_recompose, ("single", "dual"))
        self.assertEqual(ef.capability_for("yt_live24_cover").text_only_recompose, ("single", "dual"))
        self.assertEqual(ef.capability_for("yt_live_cover").text_only_recompose, ("single",))
        self.assertEqual(ef.capability_for("yt_hot_cover").text_only_recompose, ("single",))
        self.assertEqual(ef.capability_for("yt_hourly_cover").creativity_scope, ef.CREATIVITY_SCOPE_TITLE_DATE)
        self.assertEqual(ef.capability_for("default").creativity_scope, ef.CREATIVITY_SCOPE_LAYOUT)
        v = ef.capability_for("yt_vstrip")
        self.assertFalse(any([v.slots, v.shared_refs, v.fusion, v.refine, v.instruction, v.engine]))
        self.assertIsNone(v.creativity_scope)

    def test_every_yt_layout_has_slots_after_the_alignment(self):
        """2026-09-14 對齊第 3 項：YT 四版型全部一標一附圖位（新聞直播／熱搜補上）。"""
        for key in ("yt_live_cover", "yt_hot_cover", "yt_hourly_cover", "yt_live24_cover"):
            self.assertTrue(ef.capability_for(key).slots, key)
            self.assertFalse(ef.capability_for(key).shared_refs, key)


class FrontendParity(unittest.TestCase):
    def test_app_js_hides_match_the_table(self):
        entries = _js_entries()
        self.assertEqual(set(entries), set(ef.EDITOR_FORMATS), "app.js 版型表與後端 key 不一致")
        for key in ef.EDITOR_FORMATS:
            with self.subTest(format=key):
                self.assertEqual(_js_hides(entries[key]), ef.hides_for(key))

    def test_app_js_slots_flag_matches_the_table(self):
        entries = _js_entries()
        for key, cap in ef.FORMAT_CAPABILITIES.items():
            with self.subTest(format=key):
                self.assertEqual("slots: true" in entries[key], cap.slots)

    def test_yt_slot_check_reads_the_table_not_a_hard_coded_list(self):
        self.assertNotIn("['hourly', 'live24'].includes", APP_JS)
        self.assertIn("return format.inputs === 'yt_cover' && !!format.slots;", APP_JS)

    def test_hints_no_longer_describe_the_checkbox_as_a_switch(self):
        entries = _js_entries()
        for key in ("ten_cover", "yt_live_cover", "yt_live24_cover"):
            self.assertNotIn("關閉「標題由 AI 生成」", entries[key], key)
            self.assertNotIn("創意階梯只影響底圖", entries[key], key)


class Catalogue(unittest.TestCase):
    def test_the_endpoint_is_public_and_mirrors_the_table(self):
        res = TestClient(main.app).get("/api/editor/formats")
        self.assertEqual(res.status_code, 200, res.text)
        rows = {row["key"]: row for row in res.json()}
        self.assertEqual(set(rows), set(ef.EDITOR_FORMATS))
        for key, row in rows.items():
            self.assertEqual(row["hides"], ef.hides_for(key))
            self.assertEqual(row["label"], ef.EDITOR_FORMATS[key]["label"])
            self.assertEqual(row["capabilities"]["slots"], ef.capability_for(key).slots)
            self.assertEqual(row["capabilities"]["text_only_recompose"], list(ef.capability_for(key).text_only_recompose))


class EndpointsReadTheTable(unittest.TestCase):
    def test_reject_excess_asis_takes_its_limit_from_the_caller(self):
        refs = [main.UserReferenceImage(data_url=f"data:image/png;base64,{i}AAA", purpose="asis") for i in range(5)]
        main.reject_excess_asis(refs, where="x", limit=0)          # 0＝規則不適用
        main.reject_excess_asis(refs, where="x", limit=5)
        with self.assertRaises(main.HTTPException) as ctx:
            main.reject_excess_asis(refs, where="滿版", limit=4)
        self.assertIn("最多 4 張", ctx.exception.detail)

    def test_endpoints_look_the_limit_up_in_the_table(self):
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('caps = editor_formats.capability_for("ten_cover")', src)
        self.assertIn("caps = editor_formats.capability_for(editor_formats.yt_format_key(req.layout))", src)
        self.assertEqual(src.count("limit=caps.asis_max"), 2)
        # 2026-09-14 晚：從「if 才強制」改成無條件定案、旗子當參數傳（明送就照辦）
        self.assertEqual(src.count("zero_program_text=caps.zero_program_text,"), 2)


if __name__ == "__main__":
    unittest.main()
