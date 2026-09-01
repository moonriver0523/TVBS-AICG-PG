"""小孩肖像過審率規則：記者／編輯兩版消化指令都要注入。

生圖供應商對寫實風格畫兒童的安全過濾器誤殺率高，2026-09-01 使用者實測發現
把兒童角色改成卡通／插畫風格就能過關。消化端負責判斷場景是否有兒童並在
"style"/"structure" 交代這個畫風切換，其餘版面維持原本選定的 style。
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import CHART_TYPE_CHOICES, build_digest_instructions  # noqa: E402


class ChildDepictionStyleTests(unittest.TestCase):
    def test_block_present_for_every_variant(self):
        for role in ("記者", "編輯"):
            for density in ("standard", "simplified"):
                for type_label in CHART_TYPE_CHOICES:
                    with self.subTest(role=role, density=density, type_label=type_label):
                        prompt = build_digest_instructions(role, density, type_label)
                        self.assertIn("CHILD DEPICTION STYLE", prompt)

    def test_key_clauses_present(self):
        prompt = build_digest_instructions("記者", "standard", "情境示意圖")
        for phrase in (
            "CARTOON / CHILDREN'S-BOOK ILLUSTRATION style",
            "never photorealistic",
            "Every other element of the graphic",
            "does not relax the NAMED REAL PEOPLE",
            "If no child or minor would be shown",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)


if __name__ == "__main__":
    unittest.main()
