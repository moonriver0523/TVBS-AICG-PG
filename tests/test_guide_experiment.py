"""B 階段實驗腳本的組裝正確性。

實驗結論的可信度完全建立在「各 arm 之間只差一個變因」上。這裡把那個前提變成測試：
- baseline arm 必須與 production 逐字相同，否則對照組本身就不是基準。
- guide arm 必須只是 baseline 多一段引導說明。
- mask arm 必須真的把所有留白指示都清掉，否則會二次縮小成過縮浪費。
另外釘住從 main.py 複製過來的強制開頭句，防止兩邊漂移。
"""

import importlib.util
import json
import pathlib
import unittest

import news_prompt

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


experiment = _load("guide_image_experiment")


def load_fixture() -> dict[str, str]:
    return json.loads(experiment.DEFAULT_FIXTURE.read_text(encoding="utf-8"))


class MandatedSentenceParityTests(unittest.TestCase):
    """腳本裡的強制開頭句必須與 main.py 的消化 system prompt 逐字相同。"""

    def setUp(self):
        self.main_source = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_reporter_sentence_still_in_main(self):
        self.assertIn(
            experiment.MANDATED_STRUCTURE_SENTENCE_REPORTER,
            self.main_source,
            "main.py 的記者版強制開頭句已改動，請同步 scripts/guide_image_experiment.py",
        )

    def test_editor_sentence_still_in_main(self):
        self.assertIn(
            experiment.MANDATED_STRUCTURE_SENTENCE_EDITOR,
            self.main_source,
            "main.py 的編輯版強制開頭句已改動，請同步 scripts/guide_image_experiment.py",
        )


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.digest = load_fixture()

    def test_fixture_structure_starts_with_mandated_sentence(self):
        self.assertTrue(
            self.digest["structure"].startswith(
                experiment.MANDATED_STRUCTURE_SENTENCE_REPORTER
            ),
            "fixture 必須符合消化契約，否則測的就不是 production 會遇到的輸入",
        )

    def test_fixture_structure_has_no_numeric_positions(self):
        """消化規則禁止在 structure 用百分比／像素定位——數字會被畫進圖裡。"""
        structure = self.digest["structure"]
        self.assertNotIn("%", structure)
        self.assertNotIn("px", structure)

    def test_fixture_variable_uses_arabic_numerals(self):
        self.assertIn("3.8", self.digest["variable"])
        self.assertIn("12%", self.digest["variable"])


class ArmPromptTests(unittest.TestCase):
    def setUp(self):
        self.digest = load_fixture()

    def production_prompt(self, provider: str) -> str:
        """完全複製 main.generate_news_image() 的組法。"""
        return news_prompt.build_prompt(
            role=self.digest["role"],
            engine=provider,
            type_label=self.digest["chart_type"],
            style=self.digest["style"],
            structure=self.digest["structure"],
            variable=news_prompt.compose_variable(self.digest["variable"]),
        )

    def test_baseline_is_byte_identical_to_production(self):
        for arm, provider in (("gemini-baseline", "gemini"), ("gpt-baseline", "gpt")):
            with self.subTest(arm=arm):
                self.assertEqual(
                    experiment.build_arm_prompt(self.digest, arm),
                    self.production_prompt(provider),
                )

    def test_guide_arm_is_baseline_plus_guide_clause(self):
        baseline = experiment.build_arm_prompt(self.digest, "gemini-baseline")
        guided = experiment.build_arm_prompt(self.digest, "gemini-guide-wireframe")
        self.assertEqual(guided, baseline + "\n" + experiment.GUIDE_IMAGE_CLAUSE)

    def test_guide_clause_mentions_no_numbers(self):
        self.assertFalse(
            any(ch.isdigit() for ch in experiment.GUIDE_IMAGE_CLAUSE),
            "引導說明不得含任何數字：歷史實驗證實數字會被當文字畫進圖裡",
        )

    def test_mask_arm_strips_every_margin_instruction(self):
        prompt = experiment.build_arm_prompt(self.digest, "gpt-mask")
        self.assertNotIn(news_prompt.REPORTER_SAFE_AREA, prompt)
        self.assertNotIn(experiment.MANDATED_STRUCTURE_SENTENCE_REPORTER, prompt)
        self.assertNotIn("make the margin bigger", prompt)
        self.assertIn("EDITABLE REGION", prompt)

    def test_mask_arm_keeps_content_and_text_rules(self):
        """拿掉留白規則不能連內容與文字規則一起拿掉。"""
        prompt = experiment.build_arm_prompt(self.digest, "gpt-mask")
        self.assertIn("全球咖啡豆行情", prompt)
        self.assertIn("Text Rules", prompt)
        self.assertIn("FINAL OUTPUT RULE", prompt)

    def test_every_arm_builds(self):
        for arm in experiment.ARMS:
            with self.subTest(arm=arm):
                self.assertGreater(len(experiment.build_arm_prompt(self.digest, arm)), 1000)

    def test_rounds_only_reference_known_arms(self):
        for name, arms in experiment.ROUNDS.items():
            for arm in arms:
                self.assertIn(arm, experiment.ARMS, f"{name} 輪引用了未定義的 arm {arm}")


if __name__ == "__main__":
    unittest.main()
