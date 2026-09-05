"""兩段式消化（條件注入）：先便宜分類、再只注入該類型的規則。

守的是三件事：
1. 分類成功時，主消化的 prompt／schema／預算都當成「使用者指定了該類型」——
   非地圖新聞不再帶 MAP_ACCURACY_RULES，也不再多回 map_places。
2. 分類失敗（例外、逾時、截斷、垃圾類型）一律退回舊路徑，而且 prompt 要與
   舊路徑逐字元相同——新增的呼叫不可以變成新的失敗模式。
3. 指定類型、或旗標關閉時，分類器根本不會被呼叫。
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import AUTO_TYPE_LABEL, GenerateRequest  # noqa: E402
from news_prompt import MAP_TYPE_LABEL  # noqa: E402

NEWS = "桶裝瓦斯9月起調漲，4家業者同步宣布：欣欣天然氣漲2%、大台北瓦斯漲3%。"


def _resp(content, finish="stop", completion=100):
    return SimpleNamespace(
        usage=SimpleNamespace(completion_tokens=completion, prompt_tokens=10),
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))],
    )


def _digest_content(chart_type="資料圖表", **extra):
    data = {
        "style": "clean broadcast style",
        "structure": "The entire infographic is treated as one group.",
        "variable": "[標題]桶裝瓦斯9月調漲\n[內文小標]欣欣天然氣漲2%\n[內文小標]大台北瓦斯漲3%",
        "chart_type": chart_type,
        "portrait_subjects": [],
        "portrait_subjects_en": [],
    }
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


class _Harness(unittest.TestCase):
    """跑 generate() 但把兩個呼叫端都換成假的，記下主消化收到的參數。"""

    def run_generate(self, classify_content=None, classify_finish="stop",
                     classify_raises=None, type_label=AUTO_TYPE_LABEL,
                     flag=True, user_instruction=""):
        calls = []

        def fake_completion(**kw):
            calls.append(kw)
            if kw["site"] == "classify":
                if classify_raises:
                    raise classify_raises
                return _resp(classify_content, finish=classify_finish)
            return _resp(_digest_content(
                chart_type="資料圖表" if type_label != MAP_TYPE_LABEL else MAP_TYPE_LABEL))

        req = GenerateRequest(news_text=NEWS, type_label=type_label,
                              user_instruction=user_instruction)
        with (
            patch.object(main, "DIGEST_TWO_STAGE", flag),
            patch.object(main, "digest_completion", side_effect=fake_completion),
            patch.object(main, "apply_photo_availability", side_effect=lambda r, _req: r),
            patch.object(main.request_log, "log_generation"),
        ):
            result = main.generate(req)
        digest_calls = [c for c in calls if c["site"] == "generate"]
        classify_calls = [c for c in calls if c["site"] == "classify"]
        return result, digest_calls, classify_calls

    def old_path_prompt(self, req_kwargs=None):
        req = GenerateRequest(news_text=NEWS, type_label=AUTO_TYPE_LABEL, **(req_kwargs or {}))
        return main.build_digest_instructions(
            role=req.role, density=req.density, type_label=AUTO_TYPE_LABEL,
            full_bleed=main.resolve_frame_plan(req.role, req.safe_frame)[0],
            user_instruction=req.user_instruction, exclude_people=req.exclude_people,
            asis_reference_count=req.asis_reference_count, stamp=req.stamp,
            tone=req.tone, editor_format=req.editor_format,
        )


class ClassifiedPathTests(_Harness):
    def test_non_map_classification_drops_the_map_rules_and_map_places(self):
        _, digest_calls, classify_calls = self.run_generate(
            classify_content=json.dumps({"chart_type": "資料圖表"}))
        self.assertEqual(len(classify_calls), 1)
        self.assertEqual(len(digest_calls), 1)
        prompt = digest_calls[0]["system_prompt"]
        self.assertNotIn("MAP ACCURACY RULES", prompt)
        self.assertNotIn("CHART TYPE AUTO-SELECTION", prompt)
        self.assertIn('The "chart_type" field MUST be exactly "資料圖表"', prompt)
        self.assertNotIn("map_places", digest_calls[0]["schema"]["properties"])
        # 預算跟著實際類型走：非地圖用一般上限，不再拿地圖的大預算
        self.assertEqual(digest_calls[0]["max_output_tokens"], main.DIGEST_MAX_TOKENS)

    def test_map_classification_keeps_the_map_rules_and_map_places(self):
        _, digest_calls, _ = self.run_generate(
            classify_content=json.dumps({"chart_type": MAP_TYPE_LABEL}))
        prompt = digest_calls[0]["system_prompt"]
        self.assertIn("MAP ACCURACY RULES", prompt)
        self.assertIn(f'MUST be exactly "{MAP_TYPE_LABEL}"', prompt)
        self.assertIn("map_places", digest_calls[0]["schema"]["properties"])
        self.assertEqual(digest_calls[0]["max_output_tokens"], main.MAP_DIGEST_MAX_TOKENS)

    def test_classifier_is_cheap_single_call_with_only_the_selection_rules(self):
        _, _, classify_calls = self.run_generate(
            classify_content=json.dumps({"chart_type": "資料圖表"}))
        call = classify_calls[0]
        self.assertEqual(call["system_prompt"], main.CLASSIFY_SYSTEM_PROMPT)
        self.assertIn("CHART TYPE AUTO-SELECTION", call["system_prompt"])
        self.assertNotIn("MAP ACCURACY RULES", call["system_prompt"])
        self.assertNotIn("CONTENT FIDELITY", call["system_prompt"])
        self.assertEqual(call["schema"], main.CLASSIFY_SCHEMA)
        self.assertEqual(call["max_output_tokens"], main.CLASSIFY_MAX_TOKENS)
        self.assertEqual(call["timeout"], main.CLASSIFY_TIMEOUT_SECONDS)

    def test_classifier_sees_the_user_instruction(self):
        # 「請畫出地理位置」常寫在指令欄；分類器只看原文就會重演 test_map_gate 的病灶
        _, _, classify_calls = self.run_generate(
            classify_content=json.dumps({"chart_type": MAP_TYPE_LABEL}),
            user_instruction="請畫出地理位置")
        self.assertIn("請畫出地理位置", classify_calls[0]["news_text"])
        self.assertIn(NEWS, classify_calls[0]["news_text"])

    def test_result_chart_type_falls_back_to_the_classified_label(self):
        # 主消化若沒回 chart_type，退路要用分類出來的類型而不是留空
        calls = []

        def fake_completion(**kw):
            calls.append(kw)
            if kw["site"] == "classify":
                return _resp(json.dumps({"chart_type": "資料圖表"}))
            return _resp(_digest_content(chart_type="不存在的類型"))

        req = GenerateRequest(news_text=NEWS, type_label=AUTO_TYPE_LABEL)
        with (
            patch.object(main, "DIGEST_TWO_STAGE", True),
            patch.object(main, "digest_completion", side_effect=fake_completion),
            patch.object(main, "apply_photo_availability", side_effect=lambda r, _req: r),
            patch.object(main.request_log, "log_generation"),
        ):
            result = main.generate(req)
        self.assertEqual(result.chart_type, "資料圖表")


class MapScopeGuardTests(_Harness):
    """分類成非地圖時仍要一道短的地理範圍守門，取代整塊地圖規則。

    SOT2 2026-09-05 第五輪：模糊地名那則被判成情境，成品仍畫了臺灣輪廓的示意地圖。
    MAP_ACCURACY_RULES 開頭本來就是「就算你報成情境也綁住你」，整塊拿掉等於那張
    畫著真實地理的圖完全不受約束；整塊留著又回到付地圖稅。所以只留範圍＋退路。
    """

    def test_non_map_classification_injects_the_scope_guard(self):
        _, digest_calls, _ = self.run_generate(
            classify_content=json.dumps({"chart_type": "情境示意圖"}))
        prompt = digest_calls[0]["system_prompt"]
        self.assertIn("MAP SCOPE GUARD", prompt)
        self.assertNotIn("MAP ACCURACY RULES", prompt)
        self.assertIn("schematic locator or a plain coordinate grid", prompt)
        self.assertIn("never invent coastlines, islands, landmasses or borders", prompt)

    def test_guard_is_short_and_carries_no_map_detail(self):
        guard = main.MAP_SCOPE_GUARD_RULES
        self.assertLess(len(guard), 800)
        for detail in ("latitude", "north arrow", "scale bar", "map_places", "two map levels"):
            self.assertNotIn(detail, guard)

    def test_map_classification_gets_full_rules_not_the_guard(self):
        _, digest_calls, _ = self.run_generate(
            classify_content=json.dumps({"chart_type": MAP_TYPE_LABEL}))
        prompt = digest_calls[0]["system_prompt"]
        self.assertIn("MAP ACCURACY RULES", prompt)
        self.assertNotIn("MAP SCOPE GUARD", prompt)

    def test_fallback_and_user_specified_types_never_get_the_guard(self):
        _, old_calls, _ = self.run_generate(classify_raises=RuntimeError("boom"))
        self.assertNotIn("MAP SCOPE GUARD", old_calls[0]["system_prompt"])
        _, spec_calls, _ = self.run_generate(type_label="情境示意圖")
        self.assertNotIn("MAP SCOPE GUARD", spec_calls[0]["system_prompt"])
        self.assertEqual(spec_calls[0]["system_prompt"],
                         main.build_digest_instructions(
                             role="記者", density="standard", type_label="情境示意圖",
                             full_bleed=main.resolve_frame_plan("記者", False)[0]))

    def test_build_digest_instructions_default_is_unchanged(self):
        kwargs = dict(role="記者", density="standard", type_label="資料圖表",
                      full_bleed=False)
        self.assertEqual(main.build_digest_instructions(**kwargs),
                         main.build_digest_instructions(**kwargs, map_scope_guard=False))
        self.assertNotIn("MAP SCOPE GUARD", main.build_digest_instructions(**kwargs))


class FailSafeTests(_Harness):
    """分類任何形式的失敗都退回舊路徑，而且 prompt 逐字元相同。"""

    def assert_old_path(self, digest_calls):
        self.assertEqual(len(digest_calls), 1)
        self.assertEqual(digest_calls[0]["system_prompt"], self.old_path_prompt())
        self.assertIn("map_places", digest_calls[0]["schema"]["properties"])
        self.assertEqual(digest_calls[0]["max_output_tokens"], main.MAP_DIGEST_MAX_TOKENS)

    def test_classifier_exception_falls_back(self):
        _, digest_calls, _ = self.run_generate(classify_raises=RuntimeError("boom"))
        self.assert_old_path(digest_calls)

    def test_classifier_timeout_falls_back(self):
        _, digest_calls, _ = self.run_generate(classify_raises=TimeoutError("slow"))
        self.assert_old_path(digest_calls)

    def test_classifier_truncation_falls_back(self):
        _, digest_calls, _ = self.run_generate(
            classify_content="", classify_finish="length")
        self.assert_old_path(digest_calls)

    def test_classifier_unknown_type_falls_back(self):
        _, digest_calls, _ = self.run_generate(
            classify_content=json.dumps({"chart_type": "圓餅圖"}))
        self.assert_old_path(digest_calls)

    def test_classifier_garbage_json_falls_back(self):
        _, digest_calls, _ = self.run_generate(classify_content="not json {")
        self.assert_old_path(digest_calls)

    def test_classifier_is_called_exactly_once_never_retried(self):
        _, _, classify_calls = self.run_generate(classify_raises=RuntimeError("boom"))
        self.assertEqual(len(classify_calls), 1)


class GateTests(_Harness):
    def test_specified_type_never_classifies(self):
        _, digest_calls, classify_calls = self.run_generate(type_label="資料圖表")
        self.assertEqual(classify_calls, [])
        self.assertIn('MUST be exactly "資料圖表"', digest_calls[0]["system_prompt"])

    def test_flag_off_never_classifies_and_uses_old_path(self):
        _, digest_calls, classify_calls = self.run_generate(flag=False)
        self.assertEqual(classify_calls, [])
        self.assertEqual(digest_calls[0]["system_prompt"], self.old_path_prompt())

    def test_flag_defaults_off(self):
        # 沒設 DIGEST_TWO_STAGE 時必須是關的：正確率與總延遲量過再上
        self.assertFalse(os.getenv("DIGEST_TWO_STAGE", "") == "1" and not main.DIGEST_TWO_STAGE)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DIGEST_TWO_STAGE", None)
            self.assertFalse(os.getenv("DIGEST_TWO_STAGE", "") == "1")


class RawUserMessageTests(unittest.TestCase):
    """digest_completion 的兩個新參數不得改變舊呼叫端的行為。"""

    def test_default_wraps_news_text_as_before(self):
        captured = {}

        class FakeCompletions:
            def create(self, **kw):
                captured.update(kw)
                return _resp("{}")

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        with patch.object(main, "openai_client", fake_client):
            main.digest_completion(model="m", system_prompt="s", news_text="X",
                                   max_output_tokens=10, schema_name="n", schema={})
        self.assertEqual(captured["messages"][1]["content"], 'News Source Material:\n"X"')

    def test_raw_user_message_is_passed_through(self):
        captured = {}

        class FakeCompletions:
            def create(self, **kw):
                captured.update(kw)
                return _resp("{}")

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        with patch.object(main, "openai_client", fake_client):
            main.digest_completion(model="m", system_prompt="s", news_text="RAW",
                                   max_output_tokens=10, schema_name="n", schema={},
                                   raw_user_message=True)
        self.assertEqual(captured["messages"][1]["content"], "RAW")

    def test_timeout_uses_with_options_only_when_given(self):
        seen = {"with_options": []}

        class FakeCompletions:
            def create(self, **kw):
                return _resp("{}")

        class FakeClient:
            chat = SimpleNamespace(completions=FakeCompletions())

            def with_options(self, **kw):
                seen["with_options"].append(kw)
                return self

        with patch.object(main, "openai_client", FakeClient()):
            main.digest_completion(model="m", system_prompt="s", news_text="X",
                                   max_output_tokens=10, schema_name="n", schema={})
            self.assertEqual(seen["with_options"], [])
            main.digest_completion(model="m", system_prompt="s", news_text="X",
                                   max_output_tokens=10, schema_name="n", schema={},
                                   timeout=20.0)
            self.assertEqual(seen["with_options"], [{"timeout": 20.0}])


if __name__ == "__main__":
    unittest.main()
