"""視覺忠實度規則族（真實場景／品牌 LOGO／真實人物）：兩階段都要在。

CONTENT_FIDELITY_RULES 只管 variable 的文字數字，管不到 style/structure 委製的
畫面——這族規則補的就是那個洞，消化端管「可以委製什麼」，生圖端管「可以畫什麼」。
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import CHART_TYPE_CHOICES, build_digest_instructions  # noqa: E402
from news_prompt import build_prompt  # noqa: E402


def image_prompt(role: str = "記者", engine: str = "gemini", safe_frame: bool = True) -> str:
    return build_prompt(
        role=role, engine=engine, type_label="情境示意圖",
        style="S", structure="T", variable="V", safe_frame=safe_frame,
    )


class DigestStageTests(unittest.TestCase):
    def test_block_present_for_every_variant(self):
        for role in ("記者", "編輯"):
            for density in ("standard", "simplified"):
                for type_label in CHART_TYPE_CHOICES:
                    with self.subTest(role=role, density=density, type_label=type_label):
                        prompt = build_digest_instructions(role, density, type_label)
                        self.assertIn("REAL-WORLD ACCURACY", prompt)

    def test_key_clauses_present(self):
        # 2026-07-31 使用者裁決後的方向：場景盡量照真實畫、非真實必標「示意圖」。
        # 2026-08-01 修訂人物條款：消化端只負責判定「是不是具名真人肖像題」並回報
        # portrait_subject，畫法改由後端依有無參考照片決定（見 test_portrait_rules）。
        prompt = build_digest_instructions("記者", "standard", "情境示意圖")
        for phrase in (
            "NO UNSOURCED BRANDS",
            "NAMED REAL PEOPLE",
            "as faithfully to its real appearance as your knowledge allows",
            "LABEL WHAT IS NOT REAL",
            "示意圖",
            "you do NOT decide how the face is drawn",
            "portrait_subject",
            "An invented picture presented as real is as serious a defect as an invented number",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_block_sits_after_content_fidelity(self):
        prompt = build_digest_instructions("記者", "standard", "情境示意圖")
        self.assertLess(prompt.index("CONTENT FIDELITY"), prompt.index("REAL-WORLD ACCURACY"))


class ImageStageTests(unittest.TestCase):
    def test_block_present_for_role_engine_matrix(self):
        for role in ("記者", "編輯"):
            for engine in ("gemini", "gpt"):
                for safe_frame in (False, True):
                    with self.subTest(role=role, engine=engine, safe_frame=safe_frame):
                        self.assertIn("REAL-WORLD ACCURACY", image_prompt(role, engine, safe_frame))

    def test_key_clauses_present(self):
        prompt = image_prompt()
        for phrase in (
            "not even a small, faint, distant or background one",
            "do NOT draw a recognisable face for a named real person",
            "示意圖",
            "never drop or hide it",
            "SELF-CHECK before finalizing",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_block_precedes_final_output_rule(self):
        prompt = image_prompt()
        self.assertLess(prompt.index("REAL-WORLD ACCURACY"), prompt.index("FINAL OUTPUT RULE"))


if __name__ == "__main__":
    unittest.main()
