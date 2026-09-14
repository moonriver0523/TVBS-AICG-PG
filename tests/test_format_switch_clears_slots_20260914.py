# -*- coding: utf-8 -*-
"""換版型清附圖位（2026-09-14 使用者裁決，第八輪 U8）。

十點與 YT 的附圖位 DOM 在版型之間共用，以前切到別的版型再切回來，兩張圖與「AI改圖」鎖定
原樣殘留。現在 setEditorFormat 真的換了版型就清四個附圖位；重按同一個版型不清（不能把剛
上傳的圖洗掉）；標題欄不清（使用者只裁附圖位）。
"""
import unittest
from pathlib import Path

APP_JS = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")


class SwitchingFormatClearsSlots(unittest.TestCase):
    def test_switching_format_clears_every_slot_only_when_the_format_changed(self):
        body = APP_JS[APP_JS.index("function setEditorFormat(key) {"):]
        body = body[:body.index("\n}\n")]
        self.assertIn("const changed = next !== state.editorFormat;", body)
        block = body[body.index("if (changed) {"):]
        block = block[:block.index("}")]
        for call in ("clearCoverAsis('left')", "clearCoverAsis('right')", "clearYtAsis('left')", "clearYtAsis('right')"):
            self.assertIn(call, block)



if __name__ == "__main__":
    unittest.main()
