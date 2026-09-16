"""A8（2026-09-16 使用者裁決）：封面版型隱藏的安全框／蓋章開關不得偷渡殘值。

背景：`ten_cover`／`yt_live_cover`／`yt_hourly_cover`／`yt_live24_cover`／`yt_hot_cover`
五個封面版型的 `hides` 都寫了 `safeFrame: true`、`stamp: true`，使用者在封面版型下看不到
也改不了那兩顆開關；但 `state.safeFrame`／`state.stamp` 不會因為切版型而重置，殘值會被
`handleRefine()`／`handleImageGeneration()` 當成「現在」的選擇送進請求。

使用者裁決：切到封面版型時強制歸零；切回一般編輯版（該欄位重新可見）要恢復原偏好，
不能讓使用者的既有設定被封面模式吃掉——這裡沒有後端可以打，是純前端狀態機，
所以比照 `tests/test_yt_vstrip_ui.py` 的做法，對 `app.js` 原始碼做靜態斷言。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")

COVER_FORMAT_KEYS = [
    "ten_cover",
    "yt_live_cover",
    "yt_hourly_cover",
    "yt_live24_cover",
    "yt_hot_cover",
]


def _format_block(key):
    m = re.search(rf"(?ms)^    {re.escape(key)}:\s*\{{(.*?)^    \}},", APP_JS)
    assert m, f"app.js 裡找不到 {key} 這個版型"
    return m.group(1)


def _function_body(name):
    m = re.search(rf"(?s)function {re.escape(name)}\(\) \{{(.*?)\n\}}\n", APP_JS)
    assert m, f"app.js 裡找不到 {name}()"
    return m.group(1)


class CoverFormatsHideBothTogglesTests(unittest.TestCase):
    """先確認 B51 盤查出的五個版型確實都藏了這兩顆開關——A8 的前提。"""

    def test_all_five_covers_hide_safe_frame_and_stamp(self):
        for key in COVER_FORMAT_KEYS:
            with self.subTest(key=key):
                block = _format_block(key)
                hides = re.search(r"hides:\s*\{([^}]*)\}", block)
                self.assertIsNotNone(hides, f"{key} 沒有 hides 區塊")
                self.assertIn("safeFrame: true", hides.group(1))
                self.assertIn("stamp: true", hides.group(1))


class StateStashFieldsTests(unittest.TestCase):
    def test_state_has_stash_fields_initialized_to_null(self):
        self.assertRegex(APP_JS, r"coverSafeFrameStash:\s*null")
        self.assertRegex(APP_JS, r"coverStampStash:\s*null")


class ApplyEditorFormatLocksResetTests(unittest.TestCase):
    """靜態核對 applyEditorFormatLocks() 的歸零＋復原邏輯，三個行為都要在：
    1. 隱藏且開著＝歸零並記住原值。
    2. 沒隱藏且有暫存值＝復原（除非 preset 已經接手）。
    3. 復原後清空暫存，不會殘留舊值一直復原。
    """

    def setUp(self):
        self.body = _function_body("applyEditorFormatLocks")

    def test_forces_safe_frame_off_when_hidden(self):
        self.assertRegex(
            self.body,
            r"if \(hides\.safeFrame\) \{\s*if \(state\.safeFrame\) \{\s*"
            r"state\.coverSafeFrameStash = true;\s*toggleSafeFrame\(\);",
        )

    def test_forces_stamp_off_when_hidden(self):
        self.assertRegex(
            self.body,
            r"if \(hides\.stamp\) \{\s*if \(state\.stamp\) \{\s*"
            r"state\.coverStampStash = true;\s*toggleStamp\(\);",
        )

    def test_restores_safe_frame_when_no_longer_hidden(self):
        self.assertIn("} else if (state.coverSafeFrameStash) {", self.body)
        self.assertRegex(
            self.body,
            r"state\.coverSafeFrameStash = null;\s*"
            r"if \(typeof presets\.safeFrame !== 'boolean' && !state\.safeFrame\) toggleSafeFrame\(\);",
        )

    def test_restores_stamp_when_no_longer_hidden(self):
        self.assertIn("} else if (state.coverStampStash) {", self.body)
        self.assertRegex(
            self.body,
            r"state\.coverStampStash = null;\s*"
            r"if \(typeof presets\.stamp !== 'boolean' && !state\.stamp\) toggleStamp\(\);",
        )

    def test_preset_still_wins_over_restore(self):
        # presets 判斷（既有邏輯）必須排在歸零/復原邏輯之前，broadcast 這種有
        # presets.safeFrame 的版型才不會被 A8 的復原邏輯蓋掉。
        preset_idx = self.body.index("typeof presets.safeFrame === 'boolean'")
        hide_idx = self.body.index("if (hides.safeFrame)")
        self.assertLess(preset_idx, hide_idx, "presets 必須先套用，A8 的歸零/復原邏輯才不會蓋掉 preset")


if __name__ == "__main__":
    unittest.main()
