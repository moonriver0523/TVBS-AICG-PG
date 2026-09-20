# -*- coding: utf-8 -*-
"""2026-09-14 使用者：單槽多圖 AI 融合是需求。≥2 張 AI改圖 要走融合版措辭，明講張數、每張都要在。"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import main  # noqa: E402
import news_prompt  # noqa: E402


def _refs(n, purpose="aiedit"):
    return [main.UserReferenceImage(data_url=f"data:image/png;base64,{i}AAA", purpose=purpose) for i in range(n)]


def _apply(refs, instruction=""):
    req = main.ImageGenerateRequest(
        prompt="CANVAS\n\n=== TEXT TO RENDER ===\nx", provider="gpt",
        reference_images=refs, editor_instruction=instruction,
    )
    return main.apply_user_references_to_image_request(req).prompt


class FusionPromptTests(unittest.TestCase):
    def test_one_aiedit_keeps_the_single_picture_wording(self):
        prompt = _apply(_refs(1))
        self.assertIn(news_prompt.USER_REFERENCE_AIEDIT_RULES, prompt)
        self.assertNotIn("FUSE ALL", prompt)

    def test_two_or_more_aiedit_switch_to_the_fusion_wording_with_the_count(self):
        for n in (2, 3, 4):
            prompt = _apply(_refs(n))
            self.assertIn(f"FUSE ALL {n} OF THEM INTO ONE PICTURE", prompt)
            self.assertIn(f"Every one of the {n} images must be recognisably present", prompt)
            self.assertNotIn("One of the attached images is the picture", prompt)

    def test_mixed_purposes_count_only_aiedit(self):
        prompt = _apply(_refs(2) + _refs(1, "portrait"))
        self.assertIn("FUSE ALL 2 OF THEM", prompt)

    def test_editor_instruction_still_follows_the_fusion_block(self):
        prompt = _apply(_refs(3), "改成夜晚")
        self.assertIn("FUSE ALL 3 OF THEM", prompt)
        self.assertIn("THE EDITOR'S INSTRUCTION FOR THIS REDRAW", prompt)
        self.assertLess(prompt.index("FUSE ALL 3"), prompt.index("THE EDITOR'S INSTRUCTION"))

    def test_ai_note_label_is_still_kept_for_fusion(self):
        prompt = _apply(_refs(2))
        self.assertNotIn(news_prompt.USER_REFERENCE_NO_DISCLAIMER_RULES, prompt)


if __name__ == "__main__":
    unittest.main()
