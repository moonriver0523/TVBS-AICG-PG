"""MAP_ACCURACY_RULES 條號與交叉引用的機械守門。

2026-09-05 把 16 條合併成 11 條時重編了號。prompt 裡「use two maps (rule 6)」
「the rule 3 positioning data」這類引用是 prompt 自己在指路，不是測試在講究格式：
重編號後若指錯，模型會被叫去遵守一條不存在或講別件事的規則，而且不會有任何
測試紅、也不會在單次驗收裡現形——只會讓某條規則悄悄失效。這裡把「指錯」變成
看得見的失敗：條號必須從 1 連續編到最後一條，每個 rule N 引用都要落在實際範圍內。
"""

import os
import re
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402

RULE_LINE = re.compile(r"^(\d+)\. ", re.M)
RULE_REF = re.compile(r"\brule (\d+)\b")


def rule_numbers() -> list[int]:
    return [int(n) for n in RULE_LINE.findall(main.MAP_ACCURACY_RULES)]


class MapRuleNumberingTests(unittest.TestCase):
    def test_rules_are_numbered_contiguously_from_one(self):
        numbers = rule_numbers()
        self.assertTrue(numbers, "找不到任何編號條文")
        self.assertEqual(
            numbers, list(range(1, len(numbers) + 1)), f"條號不連續或重號：{numbers}"
        )

    def test_every_cross_reference_points_at_an_existing_rule(self):
        numbers = set(rule_numbers())
        refs = [int(n) for n in RULE_REF.findall(main.MAP_ACCURACY_RULES)]
        self.assertTrue(refs, "沒有任何 rule N 引用——若刻意拿掉，請一併更新此測試")
        for ref in refs:
            with self.subTest(ref=ref):
                self.assertIn(ref, numbers, f"引用了不存在的 rule {ref}")

    def test_cross_references_land_on_the_rule_they_mean(self):
        # 引用不只要存在，還要指到「講那件事」的那條；每個引用點名一個關鍵片語。
        text = main.MAP_ACCURACY_RULES
        lines = {
            int(m.group(1)): text[m.end():].split("\n", 1)[0]
            for m in RULE_LINE.finditer(text)
        }
        expectations = {
            "use two maps (rule 6)": "two map levels",
            "the only map furniture allowed (rule 9)": "NEVER BUILD A LEGEND",
            "the rule 3 positioning data": "POSITIONING DATA",
        }
        for ref_text, phrase in expectations.items():
            with self.subTest(ref=ref_text):
                self.assertIn(ref_text, text)
                n = int(RULE_REF.search(ref_text).group(1))
                self.assertIn(phrase, lines[n])


if __name__ == "__main__":
    unittest.main()
