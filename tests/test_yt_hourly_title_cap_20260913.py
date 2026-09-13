"""YT 整點 0 級標題字高上限（2026-09-13 使用者回報）。

回報：「標題如果字少時字級太大會被日期紅BAR蓋到」。實拍為證（東北季風／今起增強，
4＋4 字，字頂爬到約 60%，而程式壓的日期紅條下緣在 61.5%）。

根因不是漏了約束，是**現行條文正面叫模型放大**：「Choose that size from the LONGER
line — it is the size at which the LONGER line spans almost the full width」。兩行一樣
長時「短行不准撐大」不會觸發，而「長行撐到接近滿寬」還在生效，四個字撐滿 1920 就必然
巨大。原本唯一的防線是位置框（字頂 ≤66%），而模型不遵守百分比框是本專案的定論。

所以改成絕對字高上限，並**明寫它贏過「撐滿寬」**——矛盾句不能留著讓新規則去壓。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402


class HourlyTitleCapTests(unittest.TestCase):
    def test_the_cap_is_the_number_the_composite_path_already_uses(self):
        """不是新編的數字：程式壓字版就是 15%，產出的 29.2% 塊高是驗收過的播出標準。

        editor_formats 不能 import compose（會循環），兩邊各持一份，這裡釘住相等。
        """
        self.assertEqual(
            editor_formats.YT_HOURLY_TITLE_CAP_RATIO,
            compose.YT_HOURLY_TITLE_SIZE_RATIO,
        )

    def test_level_zero_hourly_states_the_ceiling_and_who_wins(self):
        rules = editor_formats.yt_layout_rules(0, "hourly")
        self.assertIn("no character is taller than 15% of the frame height", rules)
        # 明寫誰贏，不留兩句矛盾讓模型自己挑
        self.assertIn("CEILING BEATS 'spans almost the full width'", rules)
        # 直接點名使用者回報的情境
        self.assertIn("three or four characters", rules)

    def test_the_shorter_line_rule_survives_intact(self):
        """上限是**加**上去的，原本擋「短行被撐大」那條不准被擠掉。

        第一版把上限塞進那條的破折號中間，「then set the SHORTER line」被推到三行
        之後——跟拆編號那次同一個病。改成自成一條。
        """
        rules = editor_formats.yt_layout_rules(0, "hourly")
        self.assertIn("Choose that size from the LONGER line", rules)
        self.assertIn("NEVER enlarge the shorter line", rules)
        self.assertIn("- THAT SIZE HAS A CEILING", rules)

    def test_news_and_hot_are_untouched(self):
        """那兩個版型沒有程式壓的日期條可撞，而且模板另有一句「從字頂填到底緣」，
        加上限就是製造新矛盾。送出去的字必須一個都沒變。"""
        for layout in ("news", "hot"):
            with self.subTest(layout=layout):
                self.assertNotIn("CEILING", editor_formats.yt_layout_rules(0, layout))

    def test_the_ladder_levels_are_untouched(self):
        """1 級起塊高由 DESIGN BRIEF 訂、日期牌跟著標題走，不歸這條管。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                self.assertNotIn("CEILING", editor_formats.yt_layout_rules(level, "hourly"))

    def test_the_cap_clears_the_date_tab(self):
        """上限推出來的塊高必須讓字頂落在日期條下緣之下（留得住呼吸空間）。"""
        cap = editor_formats.YT_HOURLY_TITLE_CAP_RATIO
        tab_bottom = compose.YT_HOURLY_DATE_TOP_RATIO + compose.YT_HOURLY_DATE_TAB_HEIGHT_RATIO
        # 兩行字、字底貼近 98%，塊高約兩倍字高（行距已含在 baseline 差裡）
        title_top = editor_formats.YT_HOURLY_TITLE_BOTTOM_RATIO - cap * 2
        self.assertGreater(title_top, tab_bottom)
        # 也不該比模板那句「字頂 ≤66%」還低太多，否則兩條指示又互相打架
        self.assertAlmostEqual(title_top, editor_formats.yt_title_top(0), delta=0.03)


if __name__ == "__main__":
    unittest.main()
