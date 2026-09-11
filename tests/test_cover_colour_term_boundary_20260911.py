"""配色的換色點必須落在詞的邊界上（2026-09-11 使用者回報）。

實拍把「哈拉德」切成「哈拉」＋變色的「德」——那是國王的名字，拆開讀起來
像兩件事。使用者：「名詞應該整個套色 不是單一字套色 不合邏輯」。

根因跟 2026-09-11 稍早「葉門青年運動」被斷句腰斬完全一樣：中文沒有空格，
條文只說「換一個 word」的話，模型沒有邊界可依，就退回按字數切。修法也一樣
——明講**邊界怎麼找**（用讀的，不是用數的）並附上那個實際錯例。

條文放在 cover_title_colour_rule 本體而不是逐行註解：逐行註解有三個分支
（數字／引號／預設），只補預設那支的話，另外兩支照樣會從詞中間切。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import editor_formats as ef  # noqa: E402


class TermBoundaryRuleTests(unittest.TestCase):
    def test_every_designed_level_carries_the_boundary_rule(self):
        """1–4 級都要有——配色從行序解放的是 1 級起，錯也是 1 級起才會發生。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                rule = ef.cover_title_colour_rule(level)
                self.assertIn("A COLOUR CHANGE FALLS ON A TERM BOUNDARY, NEVER INSIDE A TERM", rule)
                self.assertIn("every character of it takes the SAME colour", rule)

    def test_the_rule_says_how_to_find_the_boundary(self):
        """光說「不要切在詞中間」沒用——中文沒空格，要講清楚邊界怎麼找。"""
        rule = ef.cover_title_colour_rule(2)
        self.assertIn("without spaces between words", rule)
        self.assertIn("by READING it, not by counting characters", rule)

    def test_the_rule_carries_the_real_failure_as_an_example(self):
        """附實際錯例：抽象規則模型會平均掉，具體反例才擋得住（同斷句那次）。"""
        rule = ef.cover_title_colour_rule(2)
        self.assertIn("哈拉德", rule)
        self.assertIn("哈拉", rule)
        self.assertIn("德", rule)

    def test_level_zero_is_untouched(self):
        """0 級是逐行白／黃／紅，整行同色，本來就不會從詞中間切——不加條文。"""
        plain = ef.cover_title_colour_rule(0)
        self.assertNotIn("TERM BOUNDARY", plain)
        self.assertIn("COLOUR EACH LINE EXACTLY AS LABELLED", plain)


class LineAnnotationTests(unittest.TestCase):
    def test_the_default_note_asks_for_a_whole_term(self):
        """預設那支原本寫 the one word——在中文裡沒有邊界可依，改成 TERM 並明講整詞。"""
        note = ef.cover_line_annotation("哈拉德辭世", 2)
        self.assertIn("the one TERM that carries the news", note)
        self.assertIn("colour EVERY character of that term, never part of it", note)
        self.assertNotIn("the one word that carries", note)

    def test_level_zero_still_emits_nothing(self):
        self.assertEqual(ef.cover_line_annotation("哈拉德辭世", 0), "")


if __name__ == "__main__":
    unittest.main()
