"""追加修改（refine）的品牌與具名真人條款（2026-09-07）。

守的紅線：refine 是一次獨立的生圖呼叫，模型只看得到那支 prompt。少了這兩條，
一句「背景弄熱鬧一點」就能讓它在招牌上補真實品牌，或替本來是背影的具名真人補一張
憑空捏的臉——真名＋假臉是這個專案定義最糟的組合。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import news_prompt  # noqa: E402


class RefineRealWorldRulesTests(unittest.TestCase):
    def test_brand_clause_is_the_same_string_the_main_flow_uses(self):
        # 抽共用常數而不是複製貼上：兩條線對「什麼算品牌」的定義不能分岔
        self.assertIn(news_prompt.NO_UNSOURCED_BRANDS_RULE, news_prompt.REAL_WORLD_RENDERING_RULES)
        self.assertIn(news_prompt.NO_UNSOURCED_BRANDS_RULE, news_prompt.REFINE_REAL_WORLD_RULES)

    def test_both_refine_prompts_carry_brands_and_named_person_clauses(self):
        for text_free in (False, True):
            with self.subTest(text_free=text_free):
                prompt = news_prompt.build_refine_prompt("把背景弄熱鬧一點", text_free=text_free)
                self.assertIn(news_prompt.NO_UNSOURCED_BRANDS_RULE, prompt)
                self.assertIn("NAMED REAL PEOPLE", prompt)
                self.assertIn("MUST NOT draw or complete the face", prompt)
                # 條款要排在使用者指令之前，指令才不會反過來被當成後到的覆寫
                # rindex：IMAGE_REFINE_RULES 內文本來就提到 USER CHANGE REQUEST，這裡要的是那個標頭
                self.assertLess(prompt.index("NAMED REAL PEOPLE"), prompt.rindex("USER CHANGE REQUEST"))

    def test_named_person_clause_does_not_reference_absent_blocks(self):
        # refine 沒有 STRUCTURE／VARIABLE FIELDS 區塊，照搬主流程措辭會叫模型對照不存在的欄位
        self.assertNotIn("STRUCTURE", news_prompt.REFINE_REAL_WORLD_RULES.split("NAMED REAL PEOPLE")[1])


if __name__ == "__main__":
    unittest.main()
