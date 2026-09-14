# -*- coding: utf-8 -*-
"""2026-09-14 B26＋D9：≥2 張原圖放置要走複數版措辭，明講張數、上傳順序、編號陷阱。"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import main  # noqa: E402
import news_prompt  # noqa: E402


def _refs(n, purpose="asis"):
    return [main.UserReferenceImage(data_url=f"data:image/png;base64,{i}AAA", purpose=purpose) for i in range(n)]


def _apply(refs):
    req = main.ImageGenerateRequest(
        prompt="CANVAS\n\n=== TEXT TO RENDER ===\nx",
        provider="gpt",
        reference_images=refs,
    )
    return main.apply_user_references_to_image_request(req).prompt


class AsisMultiPromptTests(unittest.TestCase):
    def test_one_asis_keeps_the_single_picture_wording(self):
        prompt = _apply(_refs(1))
        self.assertIn(news_prompt.USER_REFERENCE_ASIS_RULES, prompt)
        self.assertNotIn("PLACE ALL", prompt)
        self.assertIn("do not draw another copy of those marks", prompt)

    def test_two_or_more_asis_switch_to_the_multi_wording_with_the_count(self):
        for n in (2, 3, 4):
            prompt = _apply(_refs(n))
            self.assertIn(f"PLACE ALL {n} AS-IS", prompt)
            self.assertIn(f"Every one of the {n} images must be recognisably present", prompt)
            self.assertIn("user's upload order", prompt)
            self.assertIn("do NOT number them by the whole request's attached-file index", prompt)
            self.assertNotIn("One of the attached images must be placed", prompt)

    def test_mixed_purposes_count_only_asis(self):
        prompt = _apply(_refs(2) + _refs(1, "portrait"))
        self.assertIn("PLACE ALL 2 AS-IS", prompt)

    def test_chrome_clause_is_on_the_multi_block(self):
        prompt = _apply(_refs(2))
        self.assertIn("do not draw another copy of those marks", prompt)

    def test_scene_still_drops_the_disclaimer_when_nobody_is_named(self):
        prompt = _apply(_refs(2))
        self.assertIn(news_prompt.USER_REFERENCE_NO_DISCLAIMER_RULES, prompt)


if __name__ == "__main__":
    unittest.main()
