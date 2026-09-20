# -*- coding: utf-8 -*-
"""B71：DIGEST_NON_TW_CHARS 漏網簡體字（2026-09-16 實測）。

2026-09-16 實測抓到消化輸出「川普稱AI是骗局 北京示警風險」直接印到成品——
「骗」（U+9A97）不在 DIGEST_NON_TW_CHARS（main.py:2367 附近）裡，通用檢查
（拉丁字母比例／異常字元數）也攔不到單一個中文字，於是這篇簡體字原樣通過。

B71 尚未獲裁定動工，程式還沒修，所以本檔第一個測試**現在是紅燈**——用
unittest.expectedFailure 標記，記錄現況而不是讓整套測試變紅。
⚠ B71 修好（骗被收進 DIGEST_NON_TW_CHARS 或改用更完整的機制）之後，
要把 @unittest.expectedFailure 這個裝飾器拿掉，讓它變回正常的綠燈迴歸測試。

第二個測試盤點漏網規模（見 tests/b71_char_scan.py 與
docs/b71-simplified-char-gap-scan.md），用來估算 B71 的真實範圍——
「漏一個字」和「漏三百個字」修法完全不同。
"""
import os
import sys
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import digest_quality_problem  # noqa: E402

# 讓這個測試檔不只在 `unittest discover -s tests` 底下能 import——直接
# `python -m unittest tests.test_b71_...` 或其他 runner 從 repo 根目錄跑時，
# tests/ 不會自動在 sys.path 上。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b71_char_scan import CANDIDATES, scan  # noqa: E402

GOOD = {
    "style": "Geographically accurate simplified cartography with a restrained palette.",
    "structure": "Use a north-up locator overview across the upper area with a scale bar.",
    "variable": "[標題]摩洛哥移民湧入西班牙飛地休達\n[內文小標]經陸路及海路進入",
}


def with_field(field: str, value: str) -> dict:
    data = dict(GOOD)
    data[field] = value
    return data


class B71ObservedLeakTests(unittest.TestCase):
    @unittest.expectedFailure
    def test_the_observed_leak_pian_is_not_yet_rejected(self):
        """2026-09-16 實測案例的最小重現。

        期待行為（B71 修好後）：「骗局」應該跟其他簡體字一樣被品質閘擋下，
        problem 字串要點名 variable 與「骗」。
        現況：DIGEST_NON_TW_CHARS 沒收「骗」，這個檢查目前會失敗——
        expectedFailure 讓它記錄現況而不拖垮整套測試的綠燈。
        """
        leaked = with_field("variable", GOOD["variable"] + "\n[內文小標]AI是骗局")
        problem = digest_quality_problem(leaked, "stop")
        self.assertIn("variable", problem)
        self.assertIn("骗", problem)

    def test_pian_is_confirmed_absent_from_the_current_charset(self):
        """不靠 expectedFailure、直接釘住「現在的字元集裡沒有骗」這個事實本身。

        這一條不會因為 digest_quality_problem 的其他判斷邏輯變動而跟著變化，
        專門盯著 B71 的根因常數。
        """
        self.assertNotIn("骗", main.DIGEST_NON_TW_CHARS)


class B71GapScanTests(unittest.TestCase):
    """規模盤點：漏的是「一個字」還是「一大片」，決定 B71 怎麼修。"""

    def test_scan_confirms_the_gap_is_systemic_not_a_single_character(self):
        """候選字是刻意挑「目前不在清單裡」的字，所以漏網比例在候選字表裡

        恆為 100%——那不是「簡體字整體漏網率」，比例本身沒有意義（見
        docs/b71-simplified-char-gap-scan.md 的方法論說明）。有意義、且會隨
        main.py 修 B71 而變化的是絕對數字：漏網數至少有多少個字、相對於現行
        清單規模有多大。這裡釘住的是「規模跟現有清單同一個量級」，不是比例。
        """
        present, missing = scan()
        total = len(present) + len(missing)
        self.assertGreaterEqual(
            total, 50, "候選字表太小，量不出規模——先擴充 tests/b71_char_scan.py"
        )
        current_list_size = len(main.DIGEST_NON_TW_CHARS)
        self.assertGreaterEqual(
            len(missing),
            50,
            "漏網數掉到 50 字以下了——B71 的規模判斷（見 "
            "docs/b71-simplified-char-gap-scan.md）要重新檢查是不是清單已經被補過",
        )
        self.assertGreaterEqual(
            len(missing) / current_list_size,
            0.5,
            "漏網數相對現行清單規模的比例大幅下降了，同上要重新檢查",
        )

    def test_the_observed_b71_character_is_in_the_missing_list(self):
        present, missing = scan()
        missing_chars = {simp for simp, _trad, _word in missing}
        self.assertIn("骗", missing_chars)

    def test_candidate_table_excludes_characters_identical_in_both_scripts(self):
        # 同形字排入候選表會製造假結論（漏網比例被灌水），候選表本身要乾淨
        for simp, trad, word in CANDIDATES:
            with self.subTest(word=word):
                self.assertNotEqual(simp, trad)


if __name__ == "__main__":
    unittest.main()
