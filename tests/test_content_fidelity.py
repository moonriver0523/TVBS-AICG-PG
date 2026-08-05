"""內容忠實度規則：稿件怎麼寫就怎麼出，不得由模型自行添加。

起因（2026-07-30 實測）：GPT 生的圖自行畫出來源文字沒有的完整季線數值
（2.10／2.28／…／3.80）與「資料來源 ICE Trading Economics USDA ICO」。
來源只提到均價 3.8 美元、減產 12%、落後約 2 個月。新聞產品不能出現
模型發明的數據與來源機構。

規則分兩層，兩層的職責不同，測試也分開驗：
- 消化階段（main.py）：只能用原文有的；只有原文明確要求（「幫我補充」）才可增補。
- 生圖階段（news_prompt.py／app.js）：一律不得添加，模型只是渲染器。
"""

import io
import os
import pathlib
import re
import unittest

import news_prompt

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import build_digest_instructions  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


class DigestStageFidelityTests(unittest.TestCase):
    """消化階段：允許在原文授權時增補，其餘一律不得無中生有。"""

    def all_variants(self):
        for role in ("記者", "編輯"):
            for density in ("standard", "simplified"):
                yield role, density, build_digest_instructions(role, density, "資料圖表")

    def test_every_role_and_density_carries_the_rules(self):
        for role, density, prompt in self.all_variants():
            with self.subTest(role=role, density=density):
                self.assertIn("CONTENT FIDELITY", prompt)

    def test_forbids_inventing_figures_and_series(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        for phrase in ("NEVER invent or infer", "a series of values over time", "axis scales"):
            self.assertIn(phrase, prompt)

    def test_forbids_inventing_sources_and_institutions(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        for phrase in ("data source", "wire service", "analyst name"):
            self.assertIn(phrase, prompt)

    def test_thin_source_should_yield_fewer_points_not_padding(self):
        """稿件內容少就少寫，不得補滿——這是本規則最容易被違反的一條。"""
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("produce fewer points", prompt)

    def test_hedged_wording_must_not_be_upgraded(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("hedged wording", prompt)

    def test_supplementation_allowed_only_when_source_asks(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("幫我補充", prompt)
        self.assertIn("EXCEPTION", prompt)
        self.assertIn("Absent such an instruction, add nothing", prompt)

    def test_fidelity_outranks_density_override(self):
        """簡化模式會覆寫長度與格式要求，但不得覆寫忠實度，故須排在其前。"""
        prompt = build_digest_instructions("記者", "simplified", "資料圖表")
        self.assertLess(
            prompt.index("CONTENT FIDELITY"),
            prompt.index("SIMPLIFIED MODE OVERRIDE"),
        )


class ImageStageFidelityTests(unittest.TestCase):
    """生圖階段：完全不得添加，連「看起來太空」也不是理由。"""

    def build(self, role="記者", engine="gemini"):
        return news_prompt.build_prompt(
            role=role,
            engine=engine,
            type_label="資料圖表",
            style="S",
            structure="T",
            variable="V",
        )

    def test_rules_present_for_both_roles_and_engines(self):
        for role in ("記者", "編輯"):
            for engine in ("gemini", "gpt"):
                with self.subTest(role=role, engine=engine):
                    self.assertIn("CONTENT FIDELITY", self.build(role, engine))

    def test_declares_renderer_not_author(self):
        self.assertIn("You are a renderer, not an author", self.build())

    def test_chart_without_data_must_be_schematic_and_unlabelled(self):
        prompt = self.build()
        self.assertIn("no series of values was supplied", prompt)
        self.assertIn("NO numeric labels", prompt)
        self.assertIn("NO axis tick values", prompt)

    def test_forbids_adding_source_line_or_logo(self):
        prompt = self.build()
        for phrase in ("data-source line", "wire service", "logo", "watermark", "timestamp"):
            self.assertIn(phrase, prompt)

    def test_sparse_layout_must_not_be_filled_with_invented_content(self):
        """實測的病灶正是「版面看起來空 → 自己補內容」，這條要明確擋掉。"""
        prompt = self.build()
        self.assertIn("Empty space is correct and acceptable", prompt)
        self.assertIn("do NOT fill the gap with invented content", prompt)

    def test_image_stage_has_no_supplementation_exception(self):
        """增補只能發生在消化階段；生圖階段不得有任何例外開口。"""
        prompt = self.build()
        self.assertNotIn("幫我補充", prompt)
        self.assertNotIn("EXCEPTION", prompt)


class DualSourceParityTests(unittest.TestCase):
    """規則同時存在於 app.js 與 news_prompt.py，兩邊必須逐字一致。"""

    def test_app_js_final_output_rule_matches_python(self):
        source = io.open(ROOT / "app.js", encoding="utf-8").read()
        match = re.search(r"FINAL OUTPUT RULE\n=+\n(.*?)`;", source, re.S)
        self.assertIsNotNone(match, "app.js 找不到 FINAL OUTPUT RULE 區塊")
        js_rules = match.group(1)
        python_rules = news_prompt.build_prompt(
            role="記者",
            engine="gemini",
            type_label="T",
            style="S",
            structure="U",
            variable="V",
        ).split("FINAL OUTPUT RULE\n" + "=" * 50 + "\n")[1]
        self.assertEqual(js_rules, python_rules, "兩份來源的忠實度規則不同步")

    # 已退役的版本字串：每次實質改動 prompt 規則時把舊值加進來再 bump，
    # 讓「忘記 bump」在測試就會炸，而不是停在上一版靜默通過。
    RETIRED_PROMPT_VERSIONS = {
        "v1-2026-07-29",
        "v2-2026-07-30",
        "v3-2026-07-31",
        "v4-2026-08-01",
    }

    def test_prompt_version_was_bumped(self):
        """外部整合方（WorkCord）靠 PROMPT_VERSION 追規則版本，實質改動要遞增。"""
        self.assertNotIn(news_prompt.PROMPT_VERSION, self.RETIRED_PROMPT_VERSIONS)


if __name__ == "__main__":
    unittest.main()
