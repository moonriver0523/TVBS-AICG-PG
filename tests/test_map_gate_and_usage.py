"""地圖規則的適用範圍，以及消化用量監控。

2026-09-04 正式站實測（「請標出基隆廟口／西定路／大武崙，標：基隆市多處地區淹水，
請畫出地理位置」）：模型把 chart_type 判成「情境示意圖」，而 MAP_ACCURACY_RULES
開頭原本寫「只在你指定的是地圖類圖表時適用，不是就整段忽略」——適用範圍綁在模型
自己的分類上，一判錯就整套地理安全規則自我關閉。但它照樣在 structure 寫
「Show a faithful geographic map of Keelung City」並要求把三個地名標在正確位置，
卻沒給任何經緯度。生圖端手上只有地名，只能亂擺。

所以要釘住三件事：分類遇到明確地理需求不准選別類、適用範圍改由「要求了什麼」決定、
沒有定位資料就不准寫「忠實地圖」。
"""

import contextlib
import io
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import (  # noqa: E402
    AUTO_TYPE_LABEL,
    DIGEST_USAGE_WARN_RATIO,
    build_digest_instructions,
    log_digest_usage,
)
from news_prompt import MAP_TYPE_LABEL  # noqa: E402


def digest(type_label=MAP_TYPE_LABEL, role="記者", density="standard"):
    return build_digest_instructions(role, density, type_label)


class ScopeIsNotDecidedByChartTypeTests(unittest.TestCase):
    def test_old_self_disabling_wording_is_gone(self):
        # 這句就是病灶：把適用範圍交給模型自己回報的標籤
        self.assertNotIn(
            "apply ONLY when the graphic you are specifying is a 地圖／位置 map graphic",
            digest(),
        )

    def test_scope_is_stated_as_what_you_ask_for(self):
        text = digest()
        self.assertIn("SCOPE IS SET BY WHAT YOU ASK FOR, NOT BY THE LABEL YOU REPORT", text)

    def test_block_binds_even_when_reporting_another_chart_type(self):
        text = digest()
        for label in ("情境示意圖", "資料圖表", "3D示意／流程"):
            with self.subTest(label=label):
                self.assertIn(label, text)

    def test_the_reproduced_failure_wording_is_named(self):
        # 直接點名實測那句，模型才知道「這正是不可以做的事」
        self.assertIn("a faithful map of X", digest())

    def test_still_self_limits_for_non_geographic_graphics(self):
        # 範圍放寬不等於無條件適用；沒有真實地點時仍要能整段忽略
        text = digest()
        self.assertIn("ignore this whole block", text)

    def test_scope_wording_reaches_auto_mode_too(self):
        # 自動判斷是實際出事的那條路徑
        self.assertIn(
            "SCOPE IS SET BY WHAT YOU ASK FOR, NOT BY THE LABEL YOU REPORT",
            digest(AUTO_TYPE_LABEL),
        )

    def test_non_map_types_still_get_no_block_at_all(self):
        for label in ("資料圖表", "情境示意圖", "3D示意／流程"):
            with self.subTest(label=label):
                self.assertNotIn("MAP ACCURACY RULES", digest(label))


class NoDataNoFaithfulMapTests(unittest.TestCase):
    def test_rule_forbids_asking_for_a_map_without_coordinates(self):
        text = digest()
        self.assertIn("NEVER ASK FOR A FAITHFUL MAP YOU HAVE NOT SUPPLIED THE DATA FOR", text)

    def test_rule_points_at_the_schematic_fallback(self):
        text = digest()
        self.assertIn("rule 6 fallback", text)
        self.assertIn("labelled coordinate grid", text)

    def test_rule_names_the_forbidden_adjectives(self):
        self.assertIn('"faithful", "accurate", "real" or "geographic" map wording', digest())

    def test_headline_rule_survived_the_renumbering(self):
        # 這條被往後推過兩次（加「沒資料不准畫忠實地圖」、加 map_places），
        # 每次都要確認它沒有在重新編號時被吃掉
        text = digest()
        self.assertIn("ONE SUBJECT PLACE IN THE HEADLINE", text)
        self.assertIn("\n13. ONE SUBJECT PLACE", text)

    def test_cross_references_still_point_at_real_rules(self):
        text = digest()
        self.assertIn("use two maps (rule 8)", text)


class GeographyBeatsSceneTests(unittest.TestCase):
    """分類本身也要補強，否則規則放寬只是把錯誤往後推一格。"""

    def test_auto_selection_forces_map_for_explicit_geographic_intent(self):
        text = digest(AUTO_TYPE_LABEL)
        self.assertIn("GEOGRAPHY WINS OVER THE INCIDENT", text)
        self.assertIn("請畫出地理位置", text)

    def test_scene_is_named_as_the_wrong_answer(self):
        text = digest(AUTO_TYPE_LABEL)
        self.assertIn("is NOT a substitute for showing where it happened", text)

    def test_rule_only_appears_in_auto_mode(self):
        # 指定類型時沒有選型可言，注入只會變成噪音
        self.assertNotIn("GEOGRAPHY WINS OVER THE INCIDENT", digest(MAP_TYPE_LABEL))


def _response(finish="stop", completion=100):
    return SimpleNamespace(
        usage=SimpleNamespace(completion_tokens=completion),
        choices=[SimpleNamespace(finish_reason=finish)],
    )


class DigestUsageLogTests(unittest.TestCase):
    """截斷監控：出事前就要看得到，不是出事後才去猜。"""

    def _capture(self, response, budget=1000, site="generate"):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            log_digest_usage(site, "test-model", budget, response)
        return buffer.getvalue()

    def test_normal_call_logs_one_greppable_line(self):
        out = self._capture(_response(completion=100))
        self.assertIn("[digest_usage]", out)
        self.assertIn("site=generate", out)
        self.assertIn("budget=1000", out)
        self.assertIn("completion_tokens=100", out)
        self.assertNotIn("NEAR-LIMIT", out)
        self.assertNotIn("TRUNCATED", out)

    def test_truncation_is_flagged(self):
        out = self._capture(_response(finish="length", completion=1000))
        self.assertIn("TRUNCATED", out)

    def test_near_limit_is_flagged_before_it_truncates(self):
        # 該提早看到的是「差一點」，不是「已經撞牆」
        completion = int(1000 * DIGEST_USAGE_WARN_RATIO) + 1
        out = self._capture(_response(completion=completion))
        self.assertIn("NEAR-LIMIT", out)

    def test_just_below_the_threshold_is_quiet(self):
        completion = int(1000 * DIGEST_USAGE_WARN_RATIO) - 1
        out = self._capture(_response(completion=completion))
        self.assertNotIn("NEAR-LIMIT", out)

    def test_broken_response_never_raises(self):
        # 監控壞掉不可以拖垮消化
        out = self._capture(SimpleNamespace())
        self.assertIn("[digest_usage]", out)

    def test_missing_usage_is_tolerated(self):
        out = self._capture(
            SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason="stop")])
        )
        self.assertIn("completion_tokens=0", out)


if __name__ == "__main__":
    unittest.main()
