"""品牌規則：素材提到就可畫真實 LOGO（2026-09-07 使用者裁決）。

取代 2026-08-xx 的「只能純文字、不得重現 logotype」。新聞本來就在講那個品牌，
把它的招牌塗白反而是失真。

守的紅線（兩半都要在，缺一半都是回歸）：
1. **素材有提到**：可畫真實 logo／wordmark，貼在屬於該品牌的物件上，不得張冠李戴。
2. **素材沒提到**：一律去識別化，措辭強度不放寬——模型只要覺得「畫個 logo 比較像真的」
   就會替沒提到的店家捏一個牌子出來。
3. 消化端要把允許名單明寫進 structure；前後端規則逐字一致（test_prompt_parity 另有比對）。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import news_prompt  # noqa: E402
from main import build_digest_instructions  # noqa: E402


class ImageStageBrandRuleTests(unittest.TestCase):
    def test_rule_allows_a_real_logo_for_a_named_brand(self):
        rule = news_prompt.SOURCE_BRANDS_RULE
        self.assertIn("BRANDS: ONLY THOSE IN THE SOURCE", rule)
        self.assertIn("real logo, wordmark or brand text", rule)
        self.assertIn("as faithfully to the real mark as your knowledge allows", rule)

    def test_rule_still_de_identifies_everything_the_source_does_not_name(self):
        rule = news_prompt.SOURCE_BRANDS_RULE
        self.assertIn("Every OTHER sign, storefront, banner", rule)
        self.assertIn("blank or carry a generic non-readable mark", rule)
        self.assertIn("not even a small, faint, distant or background one", rule)
        self.assertIn("never invent one", rule)

    def test_rule_forbids_putting_one_brands_mark_on_another_brands_object(self):
        self.assertIn("never put one brand's mark on another brand's object", news_prompt.SOURCE_BRANDS_RULE)

    def test_old_plain_text_only_contract_is_gone_everywhere(self):
        for name in ("SOURCE_BRANDS_RULE", "REAL_WORLD_RENDERING_RULES", "REFINE_REAL_WORLD_RULES"):
            with self.subTest(constant=name):
                text = getattr(news_prompt, name)
                self.assertNotIn("never as a reproduced logotype", text)
                self.assertNotIn("only as plain typeset text", text)

    def test_self_check_only_blanks_unnamed_brands(self):
        self.assertIn(
            "readable branding for a brand the source material does not name, blank it",
            news_prompt.REAL_WORLD_RENDERING_RULES,
        )

    def test_refine_carries_the_same_rule_verbatim(self):
        self.assertIn(news_prompt.SOURCE_BRANDS_RULE, news_prompt.REAL_WORLD_RENDERING_RULES)
        self.assertIn(news_prompt.SOURCE_BRANDS_RULE, news_prompt.REFINE_REAL_WORLD_RULES)


class AttachedReferenceBrandTests(unittest.TestCase):
    def test_attached_image_may_carry_a_named_brands_mark(self):
        # 舊規則要模型「不得複製附圖裡任何 logo」；素材提到的品牌現在可以複製
        rules = news_prompt.USER_REFERENCE_SCENE_RULES + news_prompt.USER_REFERENCE_ASIS_RULES
        self.assertIn("except a brand the source material names", rules)
        self.assertNotIn("NO UNSOURCED BRANDS", rules)


class DigestStageBrandRuleTests(unittest.TestCase):
    def test_digest_rule_names_the_allowed_brands_in_structure(self):
        prompt = build_digest_instructions("記者", "standard", "情境示意圖")
        self.assertIn("BRANDS: ONLY THOSE IN THE SOURCE", prompt)
        self.assertIn("MAY be shown with its real logo", prompt)
        self.assertIn("WHICH brands the source material names", prompt)
        self.assertIn("every other brandable surface stays de-identified", prompt)
        self.assertNotIn("never as a reproduced logotype", prompt)


if __name__ == "__main__":
    unittest.main()
