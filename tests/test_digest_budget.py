"""消化輸出上限。

存在理由（2026-09-04 正式站實測）：「不消化」要模型把整篇原文一字不差抄進
variable，輸出長度等於輸入長度，但預算固定在 1500——943 字過關、1850 字連續
5 次 finish_reason=length 且 raw content 是空字串（推理模型的思考 token 也算進
max_completion_tokens，在吐出第一個字之前就用光），使用者等 90 秒收到 502。
固定預算對「輸出長度由輸入決定」的模式本質上是錯的，必須隨輸入縮放。
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import (  # noqa: E402
    DIGEST_MAX_TOKENS,
    MAP_DIGEST_MAX_TOKENS,
    VERBATIM_DIGEST_MAX_TOKENS,
    VERBATIM_DIGEST_OVERHEAD,
    VERBATIM_TOKENS_PER_CHAR,
    digest_token_budget,
)
from news_prompt import MAP_TYPE_LABEL  # noqa: E402

AUTO = "自動判斷"


class NonVerbatimUnchangedTests(unittest.TestCase):
    """非不消化的預算不能因為這次改動而變動——地圖那條是 2026-07-31 調出來的。"""

    def test_general_types_keep_the_old_constant(self):
        for density in ("standard", "simplified"):
            for label in ("資料圖表", "情境示意圖"):
                with self.subTest(density=density, label=label):
                    self.assertEqual(
                        digest_token_budget(label, density, "字" * 5000),
                        DIGEST_MAX_TOKENS,
                    )

    def test_map_and_auto_keep_the_map_constant(self):
        for label in (MAP_TYPE_LABEL, AUTO):
            with self.subTest(label=label):
                self.assertEqual(
                    digest_token_budget(label, "standard", "字" * 5000),
                    MAP_DIGEST_MAX_TOKENS,
                )

    def test_length_does_not_affect_non_verbatim(self):
        short = digest_token_budget("資料圖表", "simplified", "短")
        long = digest_token_budget("資料圖表", "simplified", "字" * 9000)
        self.assertEqual(short, long)


class VerbatimScalesWithInputTests(unittest.TestCase):
    def test_budget_grows_with_the_news_text(self):
        small = digest_token_budget("資料圖表", "verbatim", "字" * 100)
        big = digest_token_budget("資料圖表", "verbatim", "字" * 1800)
        self.assertGreater(big, small)

    def test_never_drops_below_the_general_floor(self):
        self.assertGreaterEqual(
            digest_token_budget("資料圖表", "verbatim", "短"), DIGEST_MAX_TOKENS
        )

    def test_the_reproduced_failure_now_gets_room(self):
        # 實測炸掉的那筆：1850 字，舊制給固定 1500
        news = "字" * 1850
        budget = digest_token_budget("資料圖表", "verbatim", news)
        # 逐字抄完整篇所需，外加 style/structure 與思考的開銷
        self.assertGreaterEqual(
            budget,
            len(news) * VERBATIM_TOKENS_PER_CHAR + VERBATIM_DIGEST_OVERHEAD,
        )
        # 當初炸掉的固定值是 1500，現在必須遠高於它
        self.assertGreater(budget, 1500 * 2)

    def test_overhead_covers_style_structure_and_thinking(self):
        # 取一個公式值明確高過固定底線的長度，才量得到 OVERHEAD 真的加上去了
        news = "字" * 1000
        needed = len(news) * VERBATIM_TOKENS_PER_CHAR + VERBATIM_DIGEST_OVERHEAD
        self.assertGreater(needed, DIGEST_MAX_TOKENS)
        self.assertEqual(digest_token_budget("資料圖表", "verbatim", news), needed)

    def test_map_floor_still_applies_to_verbatim(self):
        # 地圖＋不消化的短文，不該比地圖的固定加碼還少
        self.assertGreaterEqual(
            digest_token_budget(MAP_TYPE_LABEL, "verbatim", "短"),
            MAP_DIGEST_MAX_TOKENS,
        )

    def test_ceiling_holds_for_absurd_input(self):
        # news_text 上限 20000 字，照公式會算到 42500
        self.assertEqual(
            digest_token_budget("資料圖表", "verbatim", "字" * 20_000),
            VERBATIM_DIGEST_MAX_TOKENS,
        )


if __name__ == "__main__":
    unittest.main()
