"""news／hot 補上「標題要落到底部邊緣」的數字化約束（2026-09-11 第十批）。

實拍：熱搜（hot）四級標題塊底緣都停在 88% 左右，但 DESIGN BRIEF 只說
"baseline near the bottom edge"（一個沒有數字的形容詞），唯一有數字的是 TOP。
同一份 prompt 裡「不准碰邊」反覆出現三次（HARD CONSTRAINTS 一次、FIXED 區塊
兩次），模型挑了最保守的那句、自己抓了一段安全距離。

hourly 版型本來就有等價的一句（`{title_top:.0%}` 佔位符 + 「both headline lines
fit between there and the bottom edge」），實測底緣落在 94.8–96.7%，證實這句
數字化約束有效。這批把同一個機制搬到 news／hot——**不改 hourly 那句一個字**，
只在 news／hot 補上同源但拿掉日期牌用語的版本，兩個版型共用同一個字串常數
`editor_formats._YT_TITLE_REACHES_BOTTOM_CLAUSE`（不是各寫一次，理由跟
`_YT_PLAIN_LAYOUT["hot"] = _YT_PLAIN_LAYOUT["news"]` 那行一樣：這兩個版型的
標題規格本來就刻意釘成一樣，各寫一次遲早會悄悄分岔）。

這個常數插在原始模板字串裡（YT_COVER_FULL_PROMPT_NEWS／_HOT 的 LAYOUT 段），
不是 yt_design_brief() 的回傳值，所以完全不動 RNG fixture——重新產生過
`yt_design_brief_rng_pins_20260911.json` 核對，156 筆全部逐字元相同。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats as ef  # noqa: E402

LEVELS = (0, 1, 2, 3, 4)

# 兩個模板需要的佔位符不只 title_top——這裡只關心底部邊緣那句，其餘欄位餵空字串
# 或最小值，比照 test_yt_hourly_date_tab_20260911.py 的做法。
_COMMON_KWARGS = dict(
    line1="A", line2="B", design_brief="", layout_rules="", band_clause="",
    visual="v", fixed_block="", band_imagery_tail="",
)


def render_news(level: int) -> str:
    return ef.YT_COVER_FULL_PROMPT_NEWS.format(title_top=ef.yt_title_top(level), **_COMMON_KWARGS)


def render_hot(level: int) -> str:
    return ef.YT_COVER_FULL_PROMPT_HOT.format(title_top=ef.yt_title_top(level), **_COMMON_KWARGS)


class SharedConstantTests(unittest.TestCase):
    def test_news_and_hot_use_the_same_string_object(self):
        """不是各寫一次——同一個常數插進兩個模板，改一次兩邊都改到。"""
        self.assertIn(ef._YT_TITLE_REACHES_BOTTOM_CLAUSE, ef.YT_COVER_FULL_PROMPT_NEWS)
        self.assertIn(ef._YT_TITLE_REACHES_BOTTOM_CLAUSE, ef.YT_COVER_FULL_PROMPT_HOT)

    def test_the_clause_names_a_number_not_just_an_adjective(self):
        """根因是「底部」原本只有形容詞、沒有數字——新句子必須帶 {title_top} 佔位符。"""
        self.assertIn("{title_top:.0%}", ef._YT_TITLE_REACHES_BOTTOM_CLAUSE)

    def test_the_clause_reconciles_with_the_no_edge_touch_rule_by_name(self):
        """不是又一句會被「不准碰邊」壓過去的形容詞——這句直接點名兩者的關係，
        講清楚「貼近」跟「不准碰邊」給的是同一種細縫，不是另外留一段安全邊界。"""
        self.assertIn("nothing touches or is clipped by any edge", ef._YT_TITLE_REACHES_BOTTOM_CLAUSE)
        self.assertIn("not a wide safety gap", ef._YT_TITLE_REACHES_BOTTOM_CLAUSE)

    def test_the_clause_does_not_mention_a_date_tab_or_live_badge(self):
        """news／hot 都沒有日期牌可提，不能照抄 hourly 那句的收尾。"""
        self.assertNotIn("date tab", ef._YT_TITLE_REACHES_BOTTOM_CLAUSE)
        self.assertNotIn("LIVE", ef._YT_TITLE_REACHES_BOTTOM_CLAUSE)


class HourlyUnchangedTests(unittest.TestCase):
    """hourly 那句已經驗過有效，這批不准動一個字。"""

    def test_the_hourly_clause_text_is_byte_for_byte_the_same(self):
        self.assertIn(
            "- BECAUSE OF THAT, HEADLINE LINE 1 STARTS LOW: the TOP of its characters"
            " must sit at or below {title_top:.0%} of the frame height, and both"
            " headline lines fit between there and the bottom edge. Setting the"
            " headline higher runs it into the date tab.",
            ef.YT_COVER_FULL_PROMPT_HOURLY,
        )


class PlaceholderIsWiredFromTheRealFunctionTests(unittest.TestCase):
    """百分比必須是 yt_title_top() 代入的，不是手打——這個 repo 已經因為手打的
    百分比跟程式實際值對不上撞過一次（Logo 保留區碰撞事故），這裡不能重蹈。"""

    def test_the_rendered_percentage_matches_yt_title_top_for_every_level(self):
        for level in LEVELS:
            expected = f"{ef.yt_title_top(level):.0%}"
            with self.subTest(level=level, layout="news"):
                self.assertIn(f"lands at or below {expected} of the frame height", render_news(level))
            with self.subTest(level=level, layout="hot"):
                self.assertIn(f"lands at or below {expected} of the frame height", render_hot(level))

    def test_the_percentage_changes_when_the_block_height_ladder_changes(self):
        """不是釘死的字面——換一級，落在模板裡的數字要跟著換，不是「不管哪一級都
        印出同一個數字」這種手打殘留。"""
        rendered_percentages = {
            f"{ef.yt_title_top(level):.0%}"
            for level in LEVELS
            if f"lands at or below {ef.yt_title_top(level):.0%}" in render_news(level)
        }
        self.assertEqual(len(rendered_percentages), len({ef.yt_title_top(l) for l in LEVELS}))


class FixtureUnaffectedTests(unittest.TestCase):
    """這句插在原始模板字串裡，不是 yt_design_brief() 的回傳值——不動 RNG fixture。"""

    def test_yt_design_brief_does_not_mention_the_new_clause(self):
        brief = ef.yt_design_brief(3, lines=("A", "B"), seed=0, layout="hot")
        self.assertNotIn("THE BLOCK REACHES DOWN NEAR THE BOTTOM EDGE", brief)


if __name__ == "__main__":
    unittest.main()
