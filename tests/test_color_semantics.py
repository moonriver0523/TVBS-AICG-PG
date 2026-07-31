"""台灣漲跌配色慣例（漲紅跌綠）：兩階段都要在，且明確宣告顏色屬內容非版面幾何。"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import build_digest_instructions  # noqa: E402
from news_prompt import build_prompt  # noqa: E402


class DigestStageTests(unittest.TestCase):
    def test_block_present_for_every_variant(self):
        for role in ("記者", "編輯"):
            for density in ("standard", "simplified"):
                with self.subTest(role=role, density=density):
                    prompt = build_digest_instructions(role, density, "資料圖表")
                    self.assertIn("DIRECTIONAL COLOUR CONVENTION", prompt)
                    self.assertIn("上漲／增加／正向 = red", prompt)

    def test_colour_is_declared_content_not_layout(self):
        # TODO.md 的疑問：禁數字條款會不會讓模型連方向語意都不敢寫——明文澄清
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("CONTENT, not layout geometry", prompt)


class ImageStageTests(unittest.TestCase):
    def test_block_present_for_role_engine_matrix(self):
        for role in ("記者", "編輯"):
            for engine in ("gemini", "gpt"):
                with self.subTest(role=role, engine=engine):
                    prompt = build_prompt(
                        role=role, engine=engine, type_label="資料圖表",
                        style="S", structure="T", variable="V", safe_frame=True,
                    )
                    self.assertIn("DIRECTIONAL COLOUR CONVENTION (TAIWAN)", prompt)
                    self.assertIn("Rise, gain, increase, positive = RED", prompt)


if __name__ == "__main__":
    unittest.main()
