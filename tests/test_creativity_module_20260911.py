"""創意拉桿模組化 P1（2026-09-11）：creativity.py 收進 FIXED 段的持有權。

三處拉桿（CG／十點／YT）各自帶一段「拉桿不准碰的東西」，原本各寫一份，
改一處很容易忘了改另外兩處——2026-09-11 YT 那批就是手動抄十點的措辭抄漏
一部分才長出來的。這批把持有權收進 creativity.py，這裡守兩條紅線：

1. **三處都要真的從 creativity.fixed_block() 取字，不是各自留一份副本再
   湊巧長得像。** 直接改 creativity.py 的常數，斷言三處呼叫端的輸出跟著變——
   這樣以後才會真的「改一處，三處一起變」，而不是測試通過但其實沒接上。
2. **creativity.py 原始碼裡不准出現版面尺寸的百分比或像素數字。**
   這支模組只管「拉桿不准碰的東西」，不管拉桿本身要調的版面尺寸；
   那些數字屬於各自呼叫端的 DESIGN BRIEF，抽到這裡來連號碼一起被抽掉，
   就是 docs/plan-20260911-創意拉桿模組化.md 風險 3 點名的那種誤傷。
"""
import os
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import creativity  # noqa: E402
import editor_formats as ef  # noqa: E402
import main  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class SharedSourceTests(unittest.TestCase):
    """三個呼叫端的常數都是模組載入時算好的（正常的 Python 模組行為，跟
    editor_formats.py 其餘常數同一套慣例），不會在執行期重新讀 creativity.py，
    所以這裡不動態改 creativity 的屬性，而是雙重驗證：
    (1) 比對 creativity.fixed_block() 現在算出來的文字，是不是逐字元出現在
    三個呼叫端的輸出裡；(2) 靜態檢查原始碼真的寫了轉呼叫的呼叫式，
    而不是複製一份「湊巧長得一樣」的常數混過 (1)。
    """

    def test_cg_digest_reads_from_creativity_module(self):
        """CG 那段（target="digest"）要是逐字轉呼叫，不是各自留一份副本。"""
        self.assertIn(creativity.fixed_block(target="digest"), main.cg_creativity_rules(1))

    def test_cover_title_reads_from_creativity_module(self):
        """十點不一樣（target="image"）與 creativity.py 逐字元一致。"""
        self.assertIn(
            creativity.fixed_block(target="image"),
            ef.cover_ai_title_style_clause(1, titles=(), seed=1),
        )

    def test_yt_fixed_block_reads_from_creativity_module(self):
        """YT 三版型（target="image"）跟十點共用同一份，不是各自抄一份像的。"""
        for layout in ("hourly", "news", "hot"):
            with self.subTest(layout=layout):
                self.assertIn(creativity.fixed_block(target="image"), ef.yt_fixed_block(1, layout))

    def test_source_actually_calls_creativity_fixed_block(self):
        """靜態檢查呼叫端的原始碼，避免「輸出湊巧一致，其實是各自複製一份常數」
        混過上面幾條 assertIn。真正的轉呼叫必須在原始碼裡出現
        `creativity.fixed_block(target=...)` 這個呼叫式；不用 importlib.reload
        驗證是因為 main / editor_formats 是整個測試套件共用的模組物件，
        reload 會換掉其他測試檔手上 `from main import X` 拿到的舊物件identity，
        在完整套件裡跑會撞壞不相干的測試（曾經試過，main.py 的 pydantic
        schema 物件 identity 因此對不上，見 test_map_reference_wiring.py）。
        """
        main_source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        ef_source = (REPO_ROOT / "editor_formats.py").read_text(encoding="utf-8")
        self.assertIn('creativity.fixed_block(target="digest")', main_source)
        self.assertIn('creativity.fixed_block(target="image")', ef_source)
        # 十點與 YT 都要出現這個呼叫式，不能其中一個偷偷留了自己的副本。
        self.assertEqual(ef_source.count('creativity.fixed_block(target="image")'), 2)

    def test_unknown_target_is_rejected(self):
        with self.assertRaises(ValueError):
            creativity.fixed_block(target="not-a-real-target")


class NoLayoutNumbersInSharedModuleTests(unittest.TestCase):
    """風險 3：拉桿要調的版面尺寸數字，一個都不該漏進這支「不准碰」的檔案。"""

    def setUp(self):
        self.source = (REPO_ROOT / "creativity.py").read_text(encoding="utf-8")

    def test_no_percentage_numbers(self):
        self.assertNotRegex(self.source, r"\d+(\.\d+)?\s?%")

    def test_no_pixel_numbers(self):
        self.assertNotRegex(self.source, r"\d+\s?(px|pixels?|frame height|frame width)")

    def test_no_bare_ratio_or_multiplier_numbers(self):
        """55%、3 倍這類版面槓桿數字慣用「X 倍」「X of the frame」的句型，
        不是本模組會出現的。9/12 例外——那是十點原文舉的日期／比分斜線範例，
        不是尺寸數字，白名單放行。
        """
        for match in re.finditer(r"\b\d+(\.\d+)?\s*(x|X|times|-fold|倍)\b", self.source):
            self.fail(f"creativity.py 出現疑似版面倍數數字: {match.group(0)!r}")


if __name__ == "__main__":
    unittest.main()
