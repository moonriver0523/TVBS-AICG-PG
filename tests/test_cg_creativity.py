"""播出鏡面／記者版的 CG 美術創意拉桿 0–4（2026-09-10）。

使用者：「創意程度除了十點不一樣之外，編輯的播出鏡面、記者版的，是否也可以加入
這個功能。編輯的 yt 封面就不用了。」→「你先做一版給我看」「兩條一起做」。

為什麼另寫一套而不是接十點那一段：十點調的是封面上那三行標題，整段條文都在講
標題塊；播出鏡面／記者版是一整張資訊圖，身上綁著安全框、卡片列數、標題拆兩行。
照抄會被忽略。

這一批守的紅線：

1. **拉桿只調美術。** 版面骨架、點數、安全留白、字句都不歸它管——每一級都要
   原樣附上那段 FIXED，而且 FIXED 要明寫自己「outranks」上面那段設計條文，
   否則位置在後的設計段會把它蓋掉（本 repo 的 OVERRIDE 慣例是雙面刃）。
2. **高一級＝低一級全文再加碼**，不用「照 level 2 那樣做」的引用：模型看不到別份
   prompt，引用等於沒寫。
3. **0 是預設，而且完全不注入**——現有成品逐字元不變。
4. YT／十點封面走別的端點，不吃這條。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import main  # noqa: E402

APP_JS = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")


def _rules(level):
    return main.cg_creativity_rules(level)


def _prompt(level, **kw):
    body = dict(role="編輯", density="simplified", type_label="資訊卡",
                visual_creativity=level)
    body.update(kw)
    return main.build_digest_instructions(**body)


class LadderTests(unittest.TestCase):
    def test_level_zero_injects_nothing(self):
        self.assertEqual(_rules(0), "")

    def test_level_zero_leaves_the_digest_prompt_byte_identical(self):
        """0 是預設。現有成品不能因為這批多出半個字。"""
        self.assertEqual(_prompt(0), _prompt(0, visual_creativity=0))
        self.assertNotIn("VISUAL CREATIVITY", _prompt(0))

    def test_every_level_declares_its_own_step(self):
        for level in range(1, 5):
            with self.subTest(level=level):
                self.assertIn(f"LEVEL {level} OF 4", _rules(level))

    def test_every_level_carries_the_whole_fixed_paragraph(self):
        """拉桿不准碰的四件事：字句、點數、安全框、清單外文字。"""
        for level in range(1, 5):
            with self.subTest(level=level):
                clause = _rules(level)
                for pinned in ("WHAT THE CREATIVITY SETTING NEVER CHANGES",
                               "it never rewrites it",
                               "THE POINT COUNT AND THE LINE STRUCTURE stay exactly",
                               "THE BROADCAST SAFE AREA stays exactly",
                               "NO NEW TEXT OF ANY KIND",
                               "EVERY CHARACTER STAYS COMPLETE"):
                    self.assertIn(pinned, clause)

    def test_the_fixed_paragraph_outranks_the_design_paragraph(self):
        """設計段位置在後，照本 repo 的慣例會壓過前面——所以 FIXED 必須自己宣告更高階，
        不然「安全框」「點數」會被順手當成可設計項目。"""
        for level in range(1, 5):
            with self.subTest(level=level):
                clause = _rules(level)
                self.assertIn("THIS PARAGRAPH OUTRANKS THE ONE ABOVE IT", clause)
                self.assertLess(clause.index("VISUAL CREATIVITY"),
                                clause.index("THIS PARAGRAPH OUTRANKS THE ONE ABOVE IT"))

    def test_higher_levels_repeat_the_lower_level_requirements_verbatim(self):
        """模型看不到別份 prompt，「照 level 2 那樣做」等於沒寫。"""
        for pinned in ("pulled out visually", "Cards and panels get a defined edge"):
            for level in (2, 3, 4):
                with self.subTest(level=level, pinned=pinned):
                    self.assertIn(pinned, _rules(level))
            self.assertNotIn(pinned, _rules(1))

    def test_freedoms_only_ever_grow(self):
        # 字級落差、圖示、主題背景：3 級才開
        for level in (1, 2):
            with self.subTest(level=level):
                self.assertNotIn("SIZE HIERARCHY INSIDE THE TYPE", _rules(level))
                self.assertNotIn("pictograms", _rules(level))
        for level in (3, 4):
            with self.subTest(level=level):
                self.assertIn("SIZE HIERARCHY INSIDE THE TYPE", _rules(level))
                self.assertIn("pictograms", _rules(level))
        # 傾斜、多層描邊、爆裂：只有最高級
        for level in (1, 2, 3):
            with self.subTest(level=level):
                self.assertNotIn("GO FURTHER", _rules(level))
        self.assertIn("GO FURTHER", _rules(4))

    def test_the_loudest_level_repeats_the_no_overrun_guard(self):
        """傾斜與裝飾最容易吃掉安全留白，這一級要自己再講一次。"""
        clause = _rules(4)
        self.assertIn("LOUD IS NOT THE SAME AS BROKEN", clause)
        self.assertIn("never more than about eight", clause)


class RequestTests(unittest.TestCase):
    def test_the_level_reaches_the_digest_prompt(self):
        for level in range(1, 5):
            with self.subTest(level=level):
                self.assertIn(f"LEVEL {level} OF 4", _prompt(level))

    def test_the_reporter_role_gets_it_too(self):
        """使用者點名的兩條線之一。記者版沒有版型區塊，條文仍要進得去。"""
        self.assertIn("LEVEL 3 OF 4", _prompt(3, role="記者"))

    def test_the_broadcast_mirror_gets_it_after_its_own_format_block(self):
        """播出鏡面的版型區塊寫死了卡片列數。創意條文必須排在它後面（OVERRIDE 慣例），
        但 FIXED 段又要把列數釘回去——順序錯了就會多出一張卡。"""
        prompt = _prompt(4, editor_format="broadcast", stamp=False, hole_side="left")
        self.assertIn("LEVEL 4 OF 4", prompt)
        self.assertLess(prompt.index("no more and no fewer"), prompt.index("VISUAL CREATIVITY"))

    def test_out_of_range_is_rejected_by_the_model(self):
        from pydantic import ValidationError
        for bad in (-1, 5):
            with self.subTest(level=bad):
                with self.assertRaises(ValidationError):
                    main.GenerateRequest(news_text="測試", type_label="資訊卡",
                                         visual_creativity=bad)

    def test_the_request_defaults_to_zero(self):
        self.assertEqual(main.GenerateRequest(news_text="測試", type_label="資訊卡").visual_creativity, 0)


class FrontendTests(unittest.TestCase):
    def test_the_slider_exists_and_is_wired(self):
        self.assertIn('id="cgCreativityRange"', INDEX_HTML)
        self.assertIn("setCgCreativity(this.value)", INDEX_HTML)
        self.assertIn("function setCgCreativity(", APP_JS)

    def test_it_defaults_to_zero_and_has_five_labels(self):
        self.assertRegex(APP_JS, r"cgCreativity:\s*0")
        block = APP_JS.split("const CG_CREATIVITY = [")[1].split("];")[0]
        self.assertEqual(block.count("['"), 5)

    def test_the_payload_carries_it(self):
        self.assertIn("visual_creativity: state.cgCreativity", APP_JS)

    def test_it_is_a_separate_knob_from_the_cover_slider(self):
        """兩條拉桿走不同端點、不同欄位。共用一個 state 遲早互相污染。"""
        self.assertIn("coverTitleCreativity", APP_JS)
        self.assertNotIn("title_creativity: state.cgCreativity", APP_JS)


if __name__ == "__main__":
    unittest.main()
