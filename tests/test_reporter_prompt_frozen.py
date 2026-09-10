"""記者的 prompt 一個字都不准變。

2026-08-17 為了編輯的安全框問題連續改了好幾輪 prompt，使用者明確要求
「記者的絕對不可以動到」。編輯與記者共用不少常數，改一邊很容易誤傷另一邊，
而且誤傷不會有任何執行期錯誤——只會讓記者悄悄出不一樣的圖。

所以把改動前的記者 prompt 原文存成快照逐字比對。這條紅了就是誤傷，
不要改快照，去改程式。真的要動記者 prompt 時，才連同快照一起更新。

快照更新記錄：
- 2026-09-09：使用者要求「字多」在**記者與編輯共通**放寬（資訊卡數量／密度／字數），
  density="standard" 因此開始注入 STANDARD_DENSITY_RULES，記者的 standard 兩份快照
  隨之更新。這是上面那句「真的要動記者 prompt 時」的情形，不是誤傷。
  simplified 兩份快照逐字元不變，可以拿來對照確認沒有波及其他檔位。
- 2026-09-10：非地圖類型改成一律注入 MAP_SCOPE_GUARD_RULES（原本只有兩段式分類成
  非地圖才注入，而那支旗標預設關，等於明確指定非地圖類型時一條地理約束都沒有）。
  四份快照因此都多了那一段。起因是 type_label=資訊卡 的高溫新聞畫出縣市界全錯的
  臺灣地圖，歸因見 docs/error-cases/2026-09-10-台灣行政區界-錯誤-分析.md。
  這同樣是「真的要動記者 prompt」的情形，不是誤傷。
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
