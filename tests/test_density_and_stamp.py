"""2026-09-03 改版：消化程度三檔＋蓋章開關＋指令欄優先序。

三件事各自的紅線：
1. 「不消化」必須真的關掉消化，而且要明文蓋掉編輯版樣板那幾條 NON-NEGOTIABLE
   （150-180 字、禁「，」「。」、標題拆兩行），否則模型兩邊都想遵守、還是動了字。
2. 蓋章 None 時一個字都不能注入——記者 frozen 快照靠這點維持綠燈。
3. 指令欄優先序要點名它蓋得掉什麼、蓋不掉什麼；漏掉「蓋不掉」那半段，
   「不要留邊」這種指令就會去撞安全框的 NON-NEGOTIABLE。
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import (  # noqa: E402
    GenerateRequest,
    NewsImageGenerateRequest,
    build_digest_instructions,
    strip_wrapping_quotes,
    verbatim_fidelity_problem,
)

ROLES = ("記者", "編輯")
DENSITIES = ("standard", "simplified", "verbatim")


def prompt(role="記者", density="standard", stamp=None, instruction=""):
    return build_digest_instructions(
        role=role,
        density=density,
        type_label="資料圖表",
        stamp=stamp,
        user_instruction=instruction,
    )


class VerbatimDensityTests(unittest.TestCase):
    def test_verbatim_block_only_in_verbatim_mode(self):
        for role in ROLES:
            for density in DENSITIES:
                with self.subTest(role=role, density=density):
                    text = prompt(role=role, density=density)
                    self.assertEqual(
                        "VERBATIM MODE (THE USER TURNED DIGESTION OFF)" in text,
                        density == "verbatim",
                    )

    def test_verbatim_excludes_simplified_block(self):
        text = prompt(density="verbatim")
        self.assertNotIn("SIMPLIFIED MODE OVERRIDE — THESE RULES", text)

    def test_verbatim_forbids_adding_or_removing_characters(self):
        for role in ROLES:
            with self.subTest(role=role):
                text = prompt(role=role, density="verbatim")
                self.assertIn(
                    "Not one character may be added, and not one character may be removed",
                    text,
                )

    def test_verbatim_names_the_format_rules_it_overrides(self):
        # 編輯版樣板寫死了這幾條，不點名就蓋不掉
        text = prompt(role="編輯", density="verbatim")
        for needle in ("150-180 character target", "「，」", "「。」", "two-line 標題 split"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_verbatim_keeps_instruction_text_out_of_content(self):
        text = prompt(density="verbatim")
        self.assertIn("TEXT THAT IS NOT NEWS MATERIAL IS STILL NOT CONTENT", text)

    def test_verbatim_final_reminder_is_the_last_block(self):
        # 中段那塊實測壓不住樣板開頭的「Digest the raw news text」，
        # 所以另外在最末端補一塊自我檢查。位置錯了等於沒補。
        text = prompt(density="verbatim", stamp=True, instruction="用手繪風")
        self.assertIn("FINAL CHECK BEFORE YOU ANSWER", text)
        self.assertTrue(
            text.rstrip().endswith("The interface setting alone never does."),
            "不消化的自我檢查必須是整份指令的最後一塊",
        )

    def test_final_reminder_only_in_verbatim_mode(self):
        for density in ("standard", "simplified"):
            with self.subTest(density=density):
                self.assertNotIn("FINAL CHECK BEFORE YOU ANSWER", prompt(density=density))

    def test_final_reminder_still_yields_to_an_explicit_instruction(self):
        # 它排在指令欄優先序之後，若不自己讓路就會把「濃縮成三點」蓋掉
        text = prompt(density="verbatim", instruction="濃縮成三點")
        self.assertIn(
            "The only thing that may relax this is an explicit request from the user",
            text,
        )

    def test_verbatim_does_not_name_the_emphasis_marker_as_addable(self):
        # 實測模型會把 <強調文字> 這四個字當字面內容寫進 variable
        text = prompt(density="verbatim")
        self.assertIn("Never write out the NAME of a marker", text)

    def test_verbatim_still_asks_for_style_and_structure(self):
        text = prompt(density="verbatim")
        self.assertIn('"style" and "structure" are still yours to design', text)


class StampToggleTests(unittest.TestCase):
    def test_none_injects_nothing(self):
        for role in ROLES:
            for density in DENSITIES:
                with self.subTest(role=role, density=density):
                    text = prompt(role=role, density=density, stamp=None)
                    self.assertNotIn("STAMP BANNER:", text)

    def test_on_and_off_are_mutually_exclusive(self):
        for role in ROLES:
            for density in DENSITIES:
                with self.subTest(role=role, density=density):
                    on = prompt(role=role, density=density, stamp=True)
                    off = prompt(role=role, density=density, stamp=False)
                    self.assertIn("STAMP BANNER: ON", on)
                    self.assertNotIn("STAMP BANNER: OFF", on)
                    self.assertIn("STAMP BANNER: OFF", off)
                    self.assertNotIn("STAMP BANNER: ON", off)

    def test_off_forbids_the_marker(self):
        text = prompt(role="編輯", stamp=False)
        self.assertIn('"variable" MUST NOT contain the marker <蓋章>', text)

    def test_on_defers_to_verbatim(self):
        # 蓋章 ON ＋ 不消化：只能標記既有的一行，不准生出新字
        text = prompt(density="verbatim", stamp=True)
        self.assertIn("IN VERBATIM MODE THE STAMP IS A MARKER ONLY", text)
        self.assertLess(
            text.index("VERBATIM MODE (THE USER TURNED DIGESTION OFF)"),
            text.index("STAMP BANNER: ON"),
            "蓋章區塊要放在逐字區塊之後，才引用得到它",
        )


class InstructionPriorityTests(unittest.TestCase):
    def test_priority_block_only_with_an_instruction(self):
        self.assertNotIn("PRIORITY OVER THE USER'S OWN UI SETTINGS", prompt())
        self.assertIn(
            "PRIORITY OVER THE USER'S OWN UI SETTINGS",
            prompt(instruction="用手繪風"),
        )

    def test_priority_block_names_what_it_overrides(self):
        text = prompt(instruction="不要蓋章")
        for needle in (
            "the digestion density block",
            "the stamp banner block",
            "the chart type directive",
            "the visual style",
            "uploaded reference images",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_priority_block_carves_out_what_it_cannot_override(self):
        text = prompt(instruction="不要留邊")
        for needle in (
            "It does NOT outrank",
            "CONTENT FIDELITY",
            "BROADCAST SAFE AREA / FULL-FRAME layout sentence",
            "reporter/editor role",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_priority_block_sits_after_every_block_it_overrides(self):
        text = prompt(density="verbatim", stamp=True, instruction="濃縮成三點 不要蓋章")
        pos = text.index("PRIORITY OVER THE USER'S OWN UI SETTINGS")
        for earlier in (
            "VERBATIM MODE (THE USER TURNED DIGESTION OFF)",
            "STAMP BANNER: ON",
            'The "chart_type" field MUST be exactly',
        ):
            with self.subTest(earlier=earlier):
                self.assertLess(text.index(earlier), pos)


class VerbatimFidelityGateTests(unittest.TestCase):
    """實測（2026-09-03）內容已逐字相符，但模型會在頭尾多吐東西：整段被 " 包起來、
    尾巴接上「⟦json_schema_error_recovery…⟧」。那些字元會被原樣畫進鏡面。"""

    SRC = "台北市今天下午出現強降雨，氣象署發布大雨特報。"

    def test_markers_and_whitespace_do_not_count_as_differences(self):
        variable = "[標題]台北市今天下午出現強降雨，\n<氣象署>發布大雨特報。"
        self.assertEqual(verbatim_fidelity_problem(variable, self.SRC), "")

    def test_missing_characters_are_reported(self):
        problem = verbatim_fidelity_problem("台北市今天下午出現強降雨", self.SRC)
        self.assertIn("不消化模式但 variable 與原文不符", problem)

    def test_trailing_model_noise_is_reported(self):
        noisy = self.SRC + "}】}⟦json_schema_error_recovery: remove extraneous⟧{"
        self.assertIn("多", verbatim_fidelity_problem(noisy, self.SRC))

    def test_wrapping_quotes_are_stripped_not_reported(self):
        for wrapped in (f'"{self.SRC}"', f"「{self.SRC}」", f"“{self.SRC}”"):
            with self.subTest(wrapped=wrapped[:3]):
                self.assertEqual(strip_wrapping_quotes(wrapped), self.SRC)
                self.assertEqual(verbatim_fidelity_problem(wrapped, self.SRC), "")

    def test_quotes_inside_the_text_survive(self):
        text = "他說「好」然後走了"
        self.assertEqual(strip_wrapping_quotes(text), text)

    def test_normal_variable_is_untouched(self):
        text = "[標題]台北強降雨\n[內文小標]低窪警戒"
        self.assertEqual(strip_wrapping_quotes(text), text)


class RequestModelTests(unittest.TestCase):
    def test_verbatim_is_an_accepted_density(self):
        self.assertEqual(
            GenerateRequest(news_text="x", type_label="資料圖表", density="verbatim").density,
            "verbatim",
        )
        self.assertEqual(
            NewsImageGenerateRequest(news_text="x", density="verbatim").density,
            "verbatim",
        )

    def test_stamp_defaults_to_none_on_both_entry_points(self):
        self.assertIsNone(GenerateRequest(news_text="x", type_label="資料圖表").stamp)
        self.assertIsNone(NewsImageGenerateRequest(news_text="x").stamp)


if __name__ == "__main__":
    unittest.main()
