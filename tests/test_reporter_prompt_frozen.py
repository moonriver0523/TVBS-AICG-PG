"""記者的 prompt 一個字都不准變。

2026-08-17 為了編輯的安全框問題連續改了好幾輪 prompt，使用者明確要求
「記者的絕對不可以動到」。編輯與記者共用不少常數，改一邊很容易誤傷另一邊，
而且誤傷不會有任何執行期錯誤——只會讓記者悄悄出不一樣的圖。

所以把改動前的記者 prompt 原文存成快照逐字比對。這條紅了就是誤傷，
不要改快照，去改程式。真的要動記者 prompt 時，才連同快照一起更新。
"""

import os
import pathlib
import unittest

import news_prompt

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import build_digest_instructions  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def frozen(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ReporterDigestFrozenTests(unittest.TestCase):
    def test_digest_instructions_unchanged(self):
        for density in ("standard", "simplified"):
            for full_bleed in (True, False):
                tag = "fullbleed" if full_bleed else "safearea"
                with self.subTest(density=density, mode=tag):
                    self.assertEqual(
                        build_digest_instructions(
                            "記者", density, "資料圖表", full_bleed=full_bleed
                        ),
                        frozen(f"reporter-digest-{density}-{tag}.txt"),
                        "記者的消化指令被改到了",
                    )


class ReporterImagePromptFrozenTests(unittest.TestCase):
    def test_image_prompt_unchanged(self):
        for safe_frame in (True, False):
            tag = "safeframe" if safe_frame else "plain"
            with self.subTest(mode=tag):
                self.assertEqual(
                    news_prompt.build_prompt(
                        role="記者", engine="gpt", type_label="資料圖表",
                        style="[S]", structure="[T]", variable="[V]",
                        safe_frame=safe_frame,
                    ),
                    frozen(f"reporter-image-prompt-{tag}.txt"),
                    "記者的生圖 prompt 被改到了",
                )


if __name__ == "__main__":
    unittest.main()
