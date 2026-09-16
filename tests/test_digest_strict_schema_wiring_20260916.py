# -*- coding: utf-8 -*-
"""消化端 strict JSON schema 的送出路徑（2026-09-16 補測試覆蓋）。

背景：消化階段（新聞稿→結構化 JSON）在查截斷根因（Sonnet 5 忽略
reasoning.max_tokens）之前，先把安全網補起來。既有測試（test_digest_prompts.py、
test_map_reference_wiring.py、test_portrait_rules.py）都只檢查 DIGEST_OUTPUT_SCHEMA
這個常數「長什麼樣」，沒有任何測試釘住它真的被包進送給上游的 request body。
這裡補的是「送出去的 payload 長什麼樣」——回歸基準，不是規格。
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import (  # noqa: E402
    AUTO_TYPE_LABEL,
    DIGEST_OUTPUT_SCHEMA,
    GenerateRequest,
    digest_completion,
    digest_schema,
    generate,
)
from news_prompt import MAP_TYPE_LABEL  # noqa: E402


def ok_response(payload=None):
    body = payload if payload is not None else {
        "style": "s",
        "structure": "t",
        "variable": "[標題]測試\n[內文小標]內容",
        "chart_type": "資料圖表",
        "portrait_subjects": [],
        "portrait_subjects_en": [],
    }
    message = SimpleNamespace(content=json.dumps(body))
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


class DigestCompletionPayloadTests(unittest.TestCase):
    """digest_completion() 本身：傳進去的 schema 是否原封不動送出去。"""

    def call_once(self, **overrides):
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return ok_response()

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        kwargs = dict(
            model="anthropic/claude-sonnet-5",
            system_prompt="s",
            news_text="n",
            max_output_tokens=1000,
            schema_name="news_cg_digest",
            schema=DIGEST_OUTPUT_SCHEMA,
        )
        kwargs.update(overrides)
        with patch.object(main, "openai_client", client), patch.object(
            main, "log_digest_usage", lambda *a, **k: None
        ):
            digest_completion(**kwargs)
        return calls[0]

    def test_response_format_is_json_schema(self):
        call = self.call_once()
        self.assertEqual(call["response_format"]["type"], "json_schema")

    def test_strict_mode_is_on(self):
        call = self.call_once()
        self.assertIs(call["response_format"]["json_schema"]["strict"], True)

    def test_the_schema_object_passed_in_is_sent_verbatim(self):
        call = self.call_once()
        self.assertEqual(call["response_format"]["json_schema"]["schema"], DIGEST_OUTPUT_SCHEMA)

    def test_the_schema_name_passed_in_is_sent_verbatim(self):
        call = self.call_once(schema_name="custom_name")
        self.assertEqual(call["response_format"]["json_schema"]["name"], "custom_name")

    def test_map_variant_schema_is_sent_verbatim_too(self):
        map_schema = digest_schema(MAP_TYPE_LABEL)
        call = self.call_once(schema=map_schema)
        self.assertEqual(call["response_format"]["json_schema"]["schema"], map_schema)
        self.assertIn("map_places", call["response_format"]["json_schema"]["schema"]["properties"])


class GenerateWiresTheRealSchemaTests(unittest.TestCase):
    """generate() 本身：不是隨便一個 schema 物件，是 digest_schema(type_label) 真正算出來的那份。"""

    def capture_schema(self, type_label):
        captured = {}

        def fake_digest_completion(**kwargs):
            captured["schema"] = kwargs["schema"]
            captured["schema_name"] = kwargs["schema_name"]
            raise RuntimeError("stop here")

        original = main.digest_completion
        main.digest_completion = fake_digest_completion
        try:
            try:
                generate(GenerateRequest(news_text="測試新聞文字內容", type_label=type_label))
            except RuntimeError:
                pass
        finally:
            main.digest_completion = original
        return captured

    def test_non_map_types_get_the_shared_schema_object(self):
        captured = self.capture_schema("資料圖表")
        self.assertIs(captured["schema"], DIGEST_OUTPUT_SCHEMA)

    def test_map_type_gets_the_map_variant_with_the_extra_field(self):
        captured = self.capture_schema(MAP_TYPE_LABEL)
        self.assertIn("map_places", captured["schema"]["properties"])
        self.assertIn("map_places", captured["schema"]["required"])

    def test_auto_type_gets_the_map_variant_too(self):
        # 自動判斷可能選到地圖類，schema 要先開放 map_places 欄位
        captured = self.capture_schema(AUTO_TYPE_LABEL)
        self.assertIn("map_places", captured["schema"]["properties"])

    def test_schema_name_is_stable(self):
        captured = self.capture_schema("資料圖表")
        self.assertEqual(captured["schema_name"], "news_cg_digest")


class SchemaFieldConsistencyTests(unittest.TestCase):
    """strict json_schema 模式的硬性要求，以及跟 parse 端消費欄位的對應。

    OpenAI/OpenRouter 的 strict 模式規定：additionalProperties 必須是 False，
    且 required 必須列出 properties 的每一個鍵（不支援選填欄位）。這裡釘住
    schema 真的符合這個前提——不符合的話上游會直接 400，而不是走到品質閘。
    """

    def test_additional_properties_is_false(self):
        self.assertIs(DIGEST_OUTPUT_SCHEMA["additionalProperties"], False)

    def test_every_property_is_required_and_vice_versa(self):
        self.assertEqual(
            set(DIGEST_OUTPUT_SCHEMA["properties"].keys()),
            set(DIGEST_OUTPUT_SCHEMA["required"]),
        )

    def test_map_variant_keeps_the_same_strict_contract(self):
        map_schema = digest_schema(MAP_TYPE_LABEL)
        self.assertIs(map_schema["additionalProperties"], False)
        self.assertEqual(
            set(map_schema["properties"].keys()), set(map_schema["required"])
        )

    def test_fields_generate_reads_off_the_parsed_data_are_all_declared(self):
        # main.py 的 generate() 在成功路徑會讀這些鍵（見 main.py:2874-2902）；
        # 少一個宣告，strict 模式下模型就吐不出那個欄位，程式讀到的永遠是空值。
        consumed_fields = {
            "chart_type",
            "variable",
            "style",
            "structure",
            "portrait_subjects",
            "portrait_subjects_en",
        }
        self.assertTrue(consumed_fields.issubset(DIGEST_OUTPUT_SCHEMA["properties"].keys()))

    def test_map_places_is_only_declared_on_the_map_variant(self):
        self.assertNotIn("map_places", DIGEST_OUTPUT_SCHEMA["properties"])
        map_schema = digest_schema(MAP_TYPE_LABEL)
        self.assertIn("map_places", map_schema["properties"])


if __name__ == "__main__":
    unittest.main()
