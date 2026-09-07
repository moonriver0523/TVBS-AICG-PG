"""訊息內夾帶指令與逐字模式：每次消化都先讀指令，逐字模式壓過簡化模式。

優先序靠「位置＋明文 OVERRIDE」雙重表達（repo 既有慣例）：
區塊固定放最後（在 SIMPLIFIED MODE OVERRIDE 之後），且明文寫壓過它。
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import CHART_TYPE_CHOICES, build_digest_instructions  # noqa: E402


class PresenceTests(unittest.TestCase):
    def test_block_present_for_every_variant(self):
        for role in ("記者", "編輯"):
            for density in ("standard", "simplified", "verbatim"):
                for type_label in CHART_TYPE_CHOICES:
                    with self.subTest(role=role, density=density, type_label=type_label):
                        prompt = build_digest_instructions(role, density, type_label)
                        self.assertIn("USER INSTRUCTIONS INSIDE THE MATERIAL", prompt)

    def test_instructions_are_read_first_as_a_step(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("DO THIS FIRST, BEFORE APPLYING ANY RULE ABOVE", prompt)


class PrecedenceTests(unittest.TestCase):
    def test_block_is_last_and_beats_simplified(self):
        prompt = build_digest_instructions("記者", "simplified", "資料圖表")
        self.assertLess(
            prompt.index("SIMPLIFIED MODE OVERRIDE"),
            prompt.index("USER INSTRUCTIONS INSIDE THE MATERIAL"),
        )

    def test_verbatim_overrides_length_targets_explicitly(self):
        prompt = build_digest_instructions("編輯", "simplified", "資料圖表")
        self.assertIn(
            "INCLUDING THE SIMPLIFIED MODE OVERRIDE AND THE 150-180 CHARACTER TARGET",
            prompt,
        )

    def test_fidelity_still_wins_over_instructions(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("CONTENT FIDELITY above still wins", prompt)


class ContractTests(unittest.TestCase):
    def test_instruction_text_is_never_content(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("The instruction text is NEVER content", prompt)

    def test_explicit_markers_are_recognised(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("「指示:」", prompt)
        self.assertIn("「指令:」", prompt)

    def test_verbatim_mode_exists_with_exact_reproduction(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("VERBATIM MODE", prompt)
        self.assertIn("same characters, same order, same figures, same line breaks", prompt)


if __name__ == "__main__":
    unittest.main()
