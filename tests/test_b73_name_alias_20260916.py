# -*- coding: utf-8 -*-
"""B73（2026-09-16 使用者裁決：譯名解析＋放行第三層，兩個都做）。

真因不是第三層規則太嚴，是查詢字串對不上維基條目名：實測「鮑爾」「葉倫」
「鮑威爾」全部落第 4 層，而「傑羅姆·鮑威爾」「珍妮特·耶倫」一查就中第 2 層。

這一份**不打網路**：對照表本身逐條實查過（結果記在 MASTER B73），
測試只釘「表在、順序對、開關有效」這些程式契約。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import main  # noqa: E402
import photo_lookup  # noqa: E402


class NameAliasTableTests(unittest.TestCase):
    def test_the_case_that_started_this_is_covered(self):
        self.assertEqual(photo_lookup.resolve_tw_name_alias("鮑爾"), "傑羅姆·鮑威爾")
        self.assertEqual(photo_lookup.resolve_tw_name_alias("葉倫"), "珍妮特·耶倫")

    def test_the_four_names_the_old_comment_called_permanently_stuck(self):
        """photo_lookup 舊註解說這幾位「整類國際新聞的肖像都卡在這裡」，現在有解。"""
        for short in ("卡利巴夫", "阿拉奇", "瓦希迪"):
            with self.subTest(short=short):
                self.assertIsNotNone(photo_lookup.resolve_tw_name_alias(short))

    def test_unknown_names_are_left_alone(self):
        self.assertIsNone(photo_lookup.resolve_tw_name_alias("某位不存在的人物甲"))
        self.assertIsNone(photo_lookup.resolve_tw_name_alias(""))
        self.assertIsNone(photo_lookup.resolve_tw_name_alias("川普"))   # 本來就查得到，不必收

    def test_alias_is_tried_after_the_raw_name_and_before_english(self):
        """順序有意義：原名 → 對照表（實查過）→ 英文名（消化端給的，可能空或錯）。"""
        tried: list[str] = []

        def fake(candidate, lang, timeout):
            tried.append(candidate)
            return False, None

        photo_lookup.clear_photo_lookup_cache()
        with patch.object(photo_lookup, "_lookup_lang", fake):
            photo_lookup.find_portrait_outcome("鮑爾", alt_names=("Jerome Powell",))
        # 每個候選都會被兩個語系各試一次，取不重複的順序
        order = list(dict.fromkeys(tried))
        self.assertEqual(order, ["鮑爾", "傑羅姆·鮑威爾", "Jerome Powell"])

    def test_every_entry_maps_to_a_different_string(self):
        """映射到自己等於沒映射，多半是寫表時複製貼上留下的。"""
        for short, formal in photo_lookup.TW_PORTRAIT_NAME_ALIASES.items():
            with self.subTest(short=short):
                self.assertTrue(formal.strip())
                self.assertNotEqual(short, formal)


class NoEntryFallbackTests(unittest.TestCase):
    """B73 第二半：連條目都查不到時仍走第 3 層，讓生圖模型依語境自畫。"""

    @staticmethod
    def _mk(entry_found):   # 不可叫 _outcome，會蓋掉 TestCase 內部的同名屬性
        return photo_lookup.PortraitLookupOutcome(
            photo=None, entry_found=entry_found, matched_name=None, language=None
        )

    def test_no_entry_now_falls_through_to_entry_only(self):
        outcomes = {"吳軒彤": self._mk(False)}
        with patch.object(main, "PORTRAIT_NO_ENTRY_FALLBACK", True):
            mode, photos = main.resolve_portraits(
                ["吳軒彤"], "gpt", photos={}, outcomes=outcomes
            )
        self.assertEqual(mode, "entry_only")
        self.assertEqual(photos, [])

    def test_the_switch_restores_the_old_no_reference_behaviour(self):
        """出事時第一個關的開關。關掉要逐字元回到舊行為。"""
        outcomes = {"吳軒彤": self._mk(False)}
        with patch.object(main, "PORTRAIT_NO_ENTRY_FALLBACK", False):
            mode, photos = main.resolve_portraits(
                ["吳軒彤"], "gpt", photos={}, outcomes=outcomes
            )
        self.assertEqual(mode, "no_reference")
        self.assertEqual(photos, [])

    def test_the_hard_caps_still_win_over_the_fallback(self):
        """放行的是「查不到」，不是「人太多」——超過上限仍然不畫臉。"""
        names = [f"某甲{i}" for i in range(main.MAX_PORTRAIT_FACES + 1)]
        outcomes = {name: self._mk(False) for name in names}
        with patch.object(main, "PORTRAIT_NO_ENTRY_FALLBACK", True):
            mode, _ = main.resolve_portraits(names, "gpt", photos={}, outcomes=outcomes)
        self.assertEqual(mode, "no_reference")


if __name__ == "__main__":
    unittest.main()
