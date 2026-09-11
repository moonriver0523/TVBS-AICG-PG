"""創意拉桿模組化 P1／P2（2026-09-11）：creativity.py 收進共用的持有權。

三處拉桿（CG／十點／YT）各自帶一段「拉桿不准碰的東西」，原本各寫一份，
改一處很容易忘了改另外兩處——2026-09-11 YT 那批就是手動抄十點的措辭抄漏
一部分才長出來的。P1 把 FIXED 條文收進 creativity.py，這裡守兩條紅線：

1. **三處都要真的從 creativity.fixed_block() 取字，不是各自留一份副本再
   湊巧長得像。** 直接改 creativity.py 的常數，斷言三處呼叫端的輸出跟著變——
   這樣以後才會真的「改一處，三處一起變」，而不是測試通過但其實沒接上。
2. **creativity.py 原始碼裡不准出現版面尺寸的百分比或像素數字。**
   這支模組只管「拉桿不准碰的東西」，不管拉桿本身要調的版面尺寸；
   那些數字屬於各自呼叫端的 DESIGN BRIEF，抽到這裡來連號碼一起被抽掉，
   就是 docs/plan-20260911-創意拉桿模組化.md 風險 3 點名的那種誤傷。

P2 把「等級名稱」也收進來（creativity.LEVEL_NAMES）：CG（main.py）與十點
（editor_formats.py）原本各手寫一份 0-4 的中文名稱字典，值逐字相同——這種
「兩份值相同的手寫清單」正是 P1 要防的那種病灶的另一個實例。app.js 那邊
也各有一份 [名稱, 說明] 陣列（CG_CREATIVITY／COVER_TITLE_CREATIVITY），
說明文字是每支拉桿專屬的不歸這裡管，但**名稱**（陣列第一個元素）理應與
creativity.LEVEL_NAMES 同步，所以下面的 LevelNamesParityTests 直接比對
app.js 原始碼，不是只比對兩份 Python 常數是不是同一個物件——後者只能
證明「main.py／editor_formats.py 有沒有各自留副本」，證明不了「app.js
是不是也還在講同一組名稱」，而 app.js 是使用者實際看到的字。
"""
import ast
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
APP_JS = REPO_ROOT / "app.js"


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


class LevelNamesParityTests(unittest.TestCase):
    """P2：等級名稱單一真相源，且與 app.js 兩份手寫陣列的名稱同步。

    main.CG_CREATIVITY_LEVEL_NAMES／editor_formats.COVER_AI_TITLE_LEVEL_NAMES
    現在都是 creativity.LEVEL_NAMES 的別名（同一個 dict 物件），先驗證別名
    真的接上；再解析 app.js 的兩個陣列常數，逐級比對第一個元素（名稱）。
    說明文字（第二個元素）刻意不比對——那是各拉桿專屬的措辭，見檔頭說明。
    """

    def test_main_and_editor_formats_alias_the_same_dict(self):
        # 用 is 而不是 == ：確認是同一份物件被三處共用，不是三份湊巧相等的
        # 獨立字典（那樣改一處還是會漏另外兩處，跟 P1 要防的病灶一模一樣）。
        self.assertIs(main.CG_CREATIVITY_LEVEL_NAMES, creativity.LEVEL_NAMES)
        self.assertIs(ef.COVER_AI_TITLE_LEVEL_NAMES, creativity.LEVEL_NAMES)
        self.assertIs(main.CG_CREATIVITY_LEVEL_MIN, creativity.LEVEL_MIN)
        self.assertIs(main.CG_CREATIVITY_LEVEL_MAX, creativity.LEVEL_MAX)
        self.assertIs(ef.COVER_AI_TITLE_LEVEL_MIN, creativity.LEVEL_MIN)
        self.assertIs(ef.COVER_AI_TITLE_LEVEL_MAX, creativity.LEVEL_MAX)

    def _js_array_first_elements(self, name: str, source: str) -> list[str]:
        """取出 app.js 裡 `const NAME = [ ['名稱', '說明'], ... ];` 的名稱欄。

        用 ast 而不是逐條 regex 拆欄位：陣列裡的說明文字含中文頓號、括號、
        全形冒號，regex 抓字串邊界很容易在某一級上抓錯，用 Python 的
        list literal 語法直接 parse 陣列本體最不會出錯——JS 陣列字面值的
        語法剛好是合法的 Python list 字面值（字串、逗號、方括號通用）。
        """
        match = re.search(r"const " + name + r"\s*=\s*(\[.*?\]);", source, re.S)
        self.assertIsNotNone(match, f"app.js 裡找不到 {name}，移植來源可能被改名")
        parsed = ast.literal_eval(match.group(1))
        return [pair[0] for pair in parsed]

    def test_cg_creativity_names_match(self):
        source = APP_JS.read_text(encoding="utf-8")
        names = self._js_array_first_elements("CG_CREATIVITY", source)
        self.assertEqual(len(names), len(creativity.LEVEL_NAMES))
        for level, name in enumerate(names):
            with self.subTest(level=level):
                self.assertEqual(
                    name, creativity.LEVEL_NAMES[level],
                    "CG_CREATIVITY 的等級名稱與 creativity.LEVEL_NAMES 不同步",
                )

    def test_cover_title_creativity_names_match(self):
        source = APP_JS.read_text(encoding="utf-8")
        names = self._js_array_first_elements("COVER_TITLE_CREATIVITY", source)
        self.assertEqual(len(names), len(creativity.LEVEL_NAMES))
        for level, name in enumerate(names):
            with self.subTest(level=level):
                self.assertEqual(
                    name, creativity.LEVEL_NAMES[level],
                    "COVER_TITLE_CREATIVITY 的等級名稱與 creativity.LEVEL_NAMES 不同步",
                )

    def test_yt_creativity_names_match(self):
        """P5（2026-09-11）新增：YT 三版型共用的拉桿，陣列名字是 YT_CREATIVITY——
        跟前兩份走同一個護欄，名稱同步，說明文字（YT 封面專屬的行為描述）不比對。
        """
        source = APP_JS.read_text(encoding="utf-8")
        names = self._js_array_first_elements("YT_CREATIVITY", source)
        self.assertEqual(len(names), len(creativity.LEVEL_NAMES))
        for level, name in enumerate(names):
            with self.subTest(level=level):
                self.assertEqual(
                    name, creativity.LEVEL_NAMES[level],
                    "YT_CREATIVITY 的等級名稱與 creativity.LEVEL_NAMES 不同步",
                )


if __name__ == "__main__":
    unittest.main()
