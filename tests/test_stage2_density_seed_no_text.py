"""Stage 2 跨功能契約：D16、D2、seed 與無字檔。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import creativity  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402


class D16TitlePolicyTests(unittest.TestCase):
    def test_editor_title_template_only_allows_minimal_to_use_one_line(self):
        for density in ("minimal", "simplified", "standard", "maximum"):
            with self.subTest(density=density):
                prompt = main.build_digest_instructions("編輯", density, "資料圖表")
                self.assertIn("預設拆分為兩行", prompt)
                if density == "minimal":
                    self.assertIn("可依可讀性使用單行，但不強制單行", prompt)
                else:
                    self.assertIn("只有字極少 MODE 可依可讀性使用單行", prompt)

    def test_density_blocks_never_contain_editor_line_count_rules(self):
        """密度 block 為兩角色共用；行數只准存在編輯樣板，避免洩漏到記者版。"""
        density_blocks = (
            main.STANDARD_DENSITY_RULES,
            main.SIMPLIFIED_DENSITY_RULES,
            main.MINIMAL_DENSITY_RULES,
            main.MAXIMUM_DENSITY_RULES,
            main.VERBATIM_DENSITY_RULES,
        )
        for block in density_blocks:
            with self.subTest(block=block[:20]):
                self.assertNotRegex(block, r"(?i)\b(one|two|three|single)\s+lines?\b")

    def test_each_density_declares_the_visible_headline_cap(self):
        blocks = {
            10: main.MINIMAL_DENSITY_RULES,
            13: main.SIMPLIFIED_DENSITY_RULES,
            18: main.STANDARD_DENSITY_RULES,
            22: main.MAXIMUM_DENSITY_RULES,
        }
        for cap, block in blocks.items():
            with self.subTest(cap=cap):
                self.assertIn(f"{cap}", block)
                self.assertIn("[標題]", block)
                self.assertIn("whitespace", block)
                self.assertIn("<", block)
                self.assertIn(">", block)

    def test_broadcast_single_headline_rule_is_unchanged(self):
        for stamp_block in (
            editor_formats._BROADCAST_STAMP_ON,
            editor_formats._BROADCAST_STAMP_OFF,
        ):
            self.assertIn('exactly one [標題] line', stamp_block)


class D2ChromaKeySafetyTests(unittest.TestCase):
    def test_cg_chroma_key_rule_exists_at_creativity_zero_for_all_densities(self):
        for density in ("minimal", "simplified", "standard", "maximum"):
            with self.subTest(density=density):
                prompt = main.build_digest_instructions(
                    "編輯", density, "資料圖表", visual_creativity=0
                )
                self.assertIn("chroma-key green", prompt)
                self.assertNotIn("green-family colour", prompt)

    def test_cg_chroma_key_rule_keeps_directional_market_green(self):
        prompt = main.build_digest_instructions(
            "編輯", "standard", "資料圖表", visual_creativity=0
        )
        self.assertIn("下跌／減少／負向 = green", prompt)
        self.assertIn("non-chroma data green remains allowed", prompt)

    def test_cover_rule_no_longer_bans_olive_teal_or_mint(self):
        for rule in (
            editor_formats.COVER_NO_GREEN_RULE,
            editor_formats.COVER_NO_GREEN_ROW,
        ):
            self.assertIn("chroma-key green", rule)
            self.assertNotIn("green-family", rule)
            self.assertNotIn("teal", rule)
            self.assertNotIn("mint", rule)
            self.assertIn("olive green remain allowed", rule)
        self.assertNotIn("teal", creativity.COVER_CHROMA_KEY_BANNED_COLOUR_WORDS)
        self.assertNotIn("mint", creativity.COVER_CHROMA_KEY_BANNED_COLOUR_WORDS)
        self.assertNotIn("olive", creativity.COVER_CHROMA_KEY_BANNED_COLOUR_WORDS)

    def test_existing_cover_palettes_are_not_mutated_only_to_prove_permission(self):
        self.assertEqual(
            creativity.COVER_PALETTES,
            (
                ("white", "deep navy", "vivid red", "bright golden yellow"),
                ("white", "black", "bright golden yellow", "vivid red"),
                ("bright golden yellow", "white", "vivid red", "deep navy"),
                ("icy white-blue", "deep indigo", "hot orange", "white"),
                ("white", "electric cyan", "magenta", "black"),
                ("black", "white", "hot orange", "electric cyan"),
                ("white", "royal purple", "bright golden yellow", "hot orange"),
                ("pale gold", "deep crimson", "white", "black"),
                ("white", "hot orange", "electric cyan", "deep navy"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
