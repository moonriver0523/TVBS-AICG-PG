"""播出鏡面「字多不豐富」（2026-09-08 使用者回饋 D）。

字多檔位以前在播出鏡面完全沒作用——第 6 條寫死「三張卡、每卡一句」，
消化再怎麼放寬，卡片還是一行。現在 density=standard 會多一段「每卡兩行」。
"""
import inspect
import re
import unittest

import editor_formats
import main

BROADCAST_KEYS = ("broadcast_left", "broadcast_right")
STAMP_CASES = (None, True, False)


class DensityRuleTests(unittest.TestCase):
    def test_standard_density_asks_for_two_line_cards(self):
        for key in BROADCAST_KEYS:
            for stamp in STAMP_CASES:
                with self.subTest(key=key, stamp=stamp):
                    rules = editor_formats.digest_rules(
                        key, "編輯", stamp=stamp, density="standard"
                    )
                    self.assertIn("TWO LINES INSTEAD OF ONE", rules)
                    self.assertIn("｜", rules)
                    self.assertIn("stacks its label above its supporting line", rules)
                    # 2026-09-09 使用者：字多的資訊量還是太少，卡數三張放寬到四張
                    self.assertIn("exactly four [內文小標] lines", rules)
                    self.assertNotIn("exactly three [內文小標] lines", rules)

    def test_other_densities_keep_three_cards(self):
        """放寬只發生在字多；其餘檔位仍是三張卡。"""
        for key in BROADCAST_KEYS:
            for density in ("simplified", "verbatim", None):
                for stamp in STAMP_CASES:
                    with self.subTest(key=key, density=density, stamp=stamp):
                        rules = editor_formats.digest_rules(
                            key, "編輯", stamp=stamp, density=density
                        )
                        self.assertIn("exactly three [內文小標] lines", rules)
                        self.assertNotIn("exactly four [內文小標] lines", rules)

    def test_standard_rewrites_the_point_rule_to_match(self):
        """第 6 條要求兩段時，第 7 條不能還寫「一句短事實」，否則兩條互相衝突。"""
        for key in BROADCAST_KEYS:
            for stamp in STAMP_CASES:
                with self.subTest(key=key, stamp=stamp):
                    rules = editor_formats.digest_rules(
                        key, "編輯", stamp=stamp, density="standard"
                    )
                    self.assertIn("短標｜補充細節", rules)
                    self.assertIn("the two parts rule six describes", rules)
                    self.assertIn("put those angle brackets in the 短標 part", rules)
                    # 原本的單句版整條不得留下
                    self.assertNotIn(
                        "Each [內文小標] line is one short scannable fact", rules
                    )

    def test_the_two_rules_speak_the_same_language(self):
        """第 6、7 條都要提到全形直線，措辭對得起來。"""
        for key in BROADCAST_KEYS:
            with self.subTest(key=key):
                rules = editor_formats.digest_rules(key, "編輯", density="standard")
                self.assertEqual(rules.count("full-width vertical bar 「｜」"), 2)

    def test_other_densities_keep_the_original_point_rule_verbatim(self):
        for key in BROADCAST_KEYS:
            for density in ("simplified", "verbatim", None):
                for stamp in STAMP_CASES:
                    with self.subTest(key=key, density=density, stamp=stamp):
                        rules = editor_formats.digest_rules(
                            key, "編輯", stamp=stamp, density=density
                        )
                        self.assertIn(
                            "7. Each [內文小標] line is one short scannable fact."
                            " Wrap the figure or the key phrase of each line in angle"
                            " brackets so it can be highlighted.",
                            rules,
                        )
                        self.assertNotIn("短標｜補充細節", rules)

    def test_other_densities_keep_the_single_line_card(self):
        for key in BROADCAST_KEYS:
            for density in ("simplified", "verbatim", None):
                for stamp in STAMP_CASES:
                    with self.subTest(key=key, density=density, stamp=stamp):
                        rules = editor_formats.digest_rules(
                            key, "編輯", stamp=stamp, density=density
                        )
                        self.assertNotIn("TWO LINES INSTEAD OF ONE", rules)
                        self.assertNotIn("｜", rules)

    def test_density_does_not_change_the_non_broadcast_formats(self):
        for key in ("default", "ten_cover", "yt_live_cover"):
            with self.subTest(key=key):
                self.assertEqual(
                    editor_formats.digest_rules(key, "編輯", density="standard"),
                    editor_formats.digest_rules(key, "編輯"),
                )

    def test_defaults_are_byte_identical_to_the_precomputed_rules(self):
        """density／stamp 都沒表態時，現算的結果要跟預先算好的那份一字不差。"""
        for key in BROADCAST_KEYS:
            with self.subTest(key=key):
                self.assertEqual(
                    editor_formats.digest_rules(key, "編輯"),
                    editor_formats.get(key)["digest_rules"],
                )

    def test_reporter_gets_nothing_whatever_the_density(self):
        for key in BROADCAST_KEYS:
            with self.subTest(key=key):
                self.assertEqual(
                    editor_formats.digest_rules(key, "記者", density="standard"), ""
                )


class HeadlineRuleTests(unittest.TestCase):
    def test_headline_must_carry_a_figure_or_an_outcome(self):
        for key in BROADCAST_KEYS:
            for density in ("standard", "simplified", "verbatim", None):
                for stamp in STAMP_CASES:
                    with self.subTest(key=key, density=density, stamp=stamp):
                        rules = editor_formats.digest_rules(
                            key, "編輯", stamp=stamp, density=density
                        )
                        self.assertIn(
                            "THE HEADLINE MUST CARRY THE KEY FIGURE OR THE OUTCOME",
                            rules,
                        )
                        self.assertIn("never a bare topic name", rules)


class NoDigitsTests(unittest.TestCase):
    """數字會被模型當文字畫進圖裡；新加的兩段也要守這條鐵律（條列編號不算）。"""

    def test_rules_still_carry_no_digits_at_every_density(self):
        for key in BROADCAST_KEYS:
            for density in ("standard", "simplified", "verbatim", None):
                for stamp in STAMP_CASES:
                    with self.subTest(key=key, density=density, stamp=stamp):
                        body = editor_formats.digest_rules(
                            key, "編輯", stamp=stamp, density=density
                        )
                        self.assertNotRegex(re.sub(r"(?m)^\d+\.", "", body), r"\d")


class WiringTests(unittest.TestCase):
    def test_digest_rules_accepts_density(self):
        params = inspect.signature(editor_formats.digest_rules).parameters
        self.assertIn("density", params)
        self.assertIsNone(params["density"].default)

    def test_main_passes_density_through(self):
        source = inspect.getsource(main.build_digest_instructions)
        self.assertRegex(
            source,
            r"editor_formats\.digest_rules\(\s*editor_format,\s*role,\s*stamp,\s*density",
        )

    def test_full_prompt_carries_the_two_line_cards_only_when_字多(self):
        standard = main.build_digest_instructions(
            role="編輯", density="standard", type_label="資料圖表",
            stamp=False, editor_format="broadcast_left",
        )
        self.assertIn("TWO LINES INSTEAD OF ONE", standard)
        simplified = main.build_digest_instructions(
            role="編輯", density="simplified", type_label="資料圖表",
            stamp=False, editor_format="broadcast_left",
        )
        self.assertNotIn("TWO LINES INSTEAD OF ONE", simplified)


if __name__ == "__main__":
    unittest.main()
