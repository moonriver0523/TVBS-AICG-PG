"""消化輸出健檢與地圖類 token 預算。

2026-07-31 休達案例的根因：地圖類消化用一般 token 預算幾乎必定截斷，重試又在長度
壓力下吐出摻雜垃圾字元的 variable——語法上是合法 JSON，舊版直接收下送去生圖。
這裡釘住三件事：地圖類拿到較高預算、截斷／污染的結果會被擋下、正常結果不受影響。
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import (  # noqa: E402
    AUTO_TYPE_LABEL,
    DIGEST_MAX_TOKENS,
    MAP_DIGEST_MAX_TOKENS,
    digest_quality_problem,
)
from news_prompt import MAP_TYPE_LABEL  # noqa: E402

GOOD = {
    "style": "Geographically accurate simplified cartography with a restrained palette.",
    "structure": "Use a north-up locator overview across the upper area with a scale bar.",
    "variable": "[標題]摩洛哥移民湧入西班牙飛地休達\n[內文小標]經陸路及海路進入",
}


def with_field(field: str, value: str) -> dict:
    data = dict(GOOD)
    data[field] = value
    return data


class QualityCheckTests(unittest.TestCase):
    def test_clean_output_passes(self):
        self.assertEqual(digest_quality_problem(GOOD, "stop"), "")

    def test_truncated_output_is_rejected(self):
        # 能解析的截斷結果最危險：舊版會直接收下
        self.assertIn("截斷", digest_quality_problem(GOOD, "length"))

    def test_foreign_script_contamination_is_rejected(self):
        # 實測撞到的污染：亞美尼亞文與西里爾文混進 variable 尾端
        polluted = with_field(
            "variable",
            GOOD["variable"] + "】} արվել әскәртәыҟны",
        )
        self.assertIn("variable", digest_quality_problem(polluted, "stop"))

    def test_model_self_talk_in_variable_is_rejected(self):
        # 實測撞到：模型在 variable 裡用英文自言自語
        chatty = with_field(
            "variable",
            "Need correct. We accidentally weird. Need final only JSON exact keys.",
        )
        self.assertIn("拉丁字母", digest_quality_problem(chatty, "stop"))

    def test_empty_field_is_rejected(self):
        for field in ("style", "structure", "variable"):
            with self.subTest(field=field):
                self.assertIn(field, digest_quality_problem(with_field(field, "  "), "stop"))

    def test_runaway_line_spam_is_rejected(self):
        # 放寬 token 上限後的失控模式：把原文每個詞拆成一條小標灌到幾十行
        spam = with_field(
            "variable",
            "[標題]休達大批移民湧入\n"
            + "\n".join(f"[內文小標]第{i}個詞" for i in range(90)),
        )
        self.assertIn("失控", digest_quality_problem(spam, "stop"))

    def test_repeated_lines_are_rejected(self):
        repeated = with_field(
            "variable",
            "[標題]休達大批移民湧入\n" + "[內文小標]邊境管制\n" * 12,
        )
        self.assertIn("重複", digest_quality_problem(repeated, "stop"))

    def test_emphasis_markers_do_not_look_like_duplicates(self):
        # <...> 是整句強調而非前綴標記，剝錯會讓多個強調行都變成空字串誤判重複
        emphasised = with_field(
            "variable",
            "[標題]休達大批移民湧入\n"
            "[內文小標]31日經陸路及海路自摩洛哥進入\n<數以千計人抵達>\n"
            "[內文小標]休達隸屬西班牙\n<約8萬3000人口>\n<面積19平方公里>\n"
            "[內文小標]與摩洛哥接壤\n"
            "[內文小標]法國啟動快速干預邊境部隊\n<強化法西邊界管制>\n"
            "[內文小標]多數為摩洛哥籍年輕男子和青少年\n"
            "[內文小標]努涅斯與格蘭德討論休達移民問題",
        )
        self.assertEqual(digest_quality_problem(emphasised, "stop"), "")

    def test_verbatim_length_script_is_not_mistaken_for_runaway(self):
        # 逐字模式重現的完稿腳本本來就有十幾行，不得誤傷
        script = with_field(
            "variable",
            "[標題]休達移民情勢\n"
            + "\n".join(f"[內文小標]第{i}項獨立敘述內容不同" for i in range(15)),
        )
        self.assertEqual(digest_quality_problem(script, "stop"), "")

    def test_legitimate_latin_and_symbols_pass(self):
        # 地名、機型代號、歐洲人名的附加符號與度數符號都是正常內容
        ok = dict(GOOD)
        ok["variable"] = "[標題]休達 Ceuta 移民湧入\n[內文小標]努涅斯 Nuñez 宣布\n<氣溫 25°C>"
        ok["structure"] = GOOD["structure"] + " Plot Ceuta at 35.8894°N 5.3213°W."
        self.assertEqual(digest_quality_problem(ok, "stop"), "")


class ChannelLeakTests(unittest.TestCase):
    """2026-09-05：gpt-5.6-terra 把角色／頻道標記洩漏進內容。

    最危險的不是整段亂碼被擋下，是只夾兩個異常字元的那種——未達
    DIGEST_MAX_STRAY_CHARS，其餘是 CJK 與 ASCII 所以拉丁字母比例也過關，
    於是原樣進入最終 prompt 送去生圖。真正的指紋是頻道標記本身。
    """

    def test_channel_marker_in_variable_is_rejected(self):
        leaked = with_field(
            "variable",
            GOOD["variable"] + "}} դժ assistant to=system.summary  天天中彩票不json: {",
        )
        self.assertIn("variable", digest_quality_problem(leaked, "stop"))

    def test_final_channel_marker_is_rejected(self):
        leaked = with_field("variable", GOOD["variable"] + " assistant to=final")
        self.assertIn("variable", digest_quality_problem(leaked, "stop"))

    def test_channel_marker_in_structure_is_rejected(self):
        leaked = with_field("structure", GOOD["structure"] + " assistant to=assistant.final")
        self.assertIn("structure", digest_quality_problem(leaked, "stop"))

    def test_numerusform_token_is_rejected(self):
        leaked = with_field("variable", GOOD["variable"] + " numerusformassistant")
        self.assertIn("variable", digest_quality_problem(leaked, "stop"))

    def test_ordinary_text_mentioning_assistant_still_passes(self):
        # 「assistant」單獨出現是正常英文字，不能一看到就擋
        ok = with_field("variable", "[標題]AI assistant 進駐新聞編輯台")
        self.assertEqual(digest_quality_problem(ok, "stop"), "")


class RawExcerptTests(unittest.TestCase):
    """解析失敗時記到日誌的摘要要看得到尾巴。

    2026-09-05 的病因整個在尾巴（脫軌後吐純空白直到撞天花板），舊版只記前 800
    字元，日誌永遠只看得到正常的開頭，只好在本機重跑才找得到病因。
    """

    def test_short_output_is_kept_whole(self):
        raw = '{"style":"ok","variable":"[標題]測試"}'
        self.assertIn("測試", main.digest_excerpt(raw))

    def test_long_output_keeps_the_tail(self):
        raw = '{"style":"' + "頭" * 2000 + '","variable":"' + "尾巴標記" + '"}'
        excerpt = main.digest_excerpt(raw)
        self.assertIn("尾巴標記", excerpt)
        self.assertIn("中間省略", excerpt)

    def test_whitespace_padding_is_reported_not_dumped(self):
        raw = '{"style":"開頭"' + " \n" * 4000 + ',"variable":"x"}'
        excerpt = main.digest_excerpt(raw)
        self.assertLess(len(excerpt), 1200)
        self.assertIn("空白佔", excerpt)


class TokenBudgetTests(unittest.TestCase):
    def test_map_budget_is_larger_than_default(self):
        self.assertGreater(MAP_DIGEST_MAX_TOKENS, DIGEST_MAX_TOKENS)

    def test_budgets_cover_the_measured_worst_case(self):
        """預算要容得下思考 token 的尖峰，不是只容得下正文。

        2026-09-05 用 8000 的寬鬆上限量過記者／編輯 × 自動判斷／資料圖表
        共 16 次（claude-sonnet-5）：正文很穩定，872-1259；思考變異極大，
        560-4873；total 落在 1459-6042，最兇的是編輯＋自動判斷。
        同日一度把地圖類收到 3000，上線後編輯＋地圖 5 次 attempt 全部
        finish=length，其中兩次 raw content 整個空白——預算在吐出第一個字
        之前就被思考用光。這兩個下限是那次回歸的防線，不要再往下調。
        """
        self.assertGreaterEqual(MAP_DIGEST_MAX_TOKENS, 9000)
        self.assertGreaterEqual(DIGEST_MAX_TOKENS, 5000)
        self.assertLess(DIGEST_MAX_TOKENS, MAP_DIGEST_MAX_TOKENS)

    def test_map_and_auto_types_get_the_larger_budget(self):
        # 自動判斷也要給，因為 AI 可能選地圖
        for type_label in (MAP_TYPE_LABEL, AUTO_TYPE_LABEL):
            with self.subTest(type_label=type_label):
                self.assertEqual(budget_for(type_label), MAP_DIGEST_MAX_TOKENS)

    def test_other_types_keep_the_default_budget(self):
        for type_label in ("資料圖表", "情境示意圖", "3D示意／流程"):
            with self.subTest(type_label=type_label):
                self.assertEqual(budget_for(type_label), DIGEST_MAX_TOKENS)


def budget_for(type_label: str) -> int:
    """跑一次 generate()，攔截 digest_completion 讀出實際使用的 token 上限。"""
    captured = {}

    def fake_digest_completion(**kwargs):
        captured["max_output_tokens"] = kwargs["max_output_tokens"]
        raise RuntimeError("stop here")

    original = main.digest_completion
    main.digest_completion = fake_digest_completion
    try:
        main.generate(
            main.GenerateRequest(news_text="測試新聞文字內容", type_label=type_label)
        )
    except RuntimeError:
        pass
    finally:
        main.digest_completion = original
    return captured["max_output_tokens"]


class HeadlineSubjectRuleTests(unittest.TestCase):
    def test_rule_present_for_map_and_auto(self):
        for type_label in (MAP_TYPE_LABEL, AUTO_TYPE_LABEL):
            with self.subTest(type_label=type_label):
                prompt = main.build_digest_instructions("記者", "standard", type_label)
                self.assertIn("ONE SUBJECT PLACE IN THE HEADLINE", prompt)

    def test_rule_names_the_failure_mode(self):
        prompt = main.build_digest_instructions("記者", "standard", MAP_TYPE_LABEL)
        self.assertIn("merely reacted, commented, protested or announced a response", prompt)


if __name__ == "__main__":
    unittest.main()
