"""B105＋B34：字少提高、字極少補硬上限。"""

import hashlib
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402


def points(count: int) -> str:
    return "\n".join(f"[內文小標] 重點{i}" for i in range(count))


def digest(variable: str) -> dict:
    return {"style": "broadcast", "structure": "cards", "variable": variable}


def response(variable: str):
    payload = {**digest(variable), "chart_type": "資料圖表"}
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)), finish_reason="stop")]
    )


class DensityRuleContractTests(unittest.TestCase):
    def test_new_rule_text_states_the_targets_lengths_and_no_padding_rule(self):
        simplified = main.SIMPLIFIED_DENSITY_RULES
        self.assertIn("TARGET four", simplified)
        self.assertIn("never fewer than three", simplified)
        self.assertIn("fourteen to eighteen", simplified)
        self.assertIn("forty-five to seventy-five", simplified)
        self.assertIn("never pad, repeat", simplified)

        minimal = main.MINIMAL_DENSITY_RULES
        self.assertIn("TARGET ONE", minimal)
        self.assertIn("One to three points are acceptable", minimal)
        self.assertIn("THREE is the HARD MAXIMUM", minimal)
        self.assertIn("at most about twelve", minimal)
        self.assertIn("twelve to thirty", minimal)
        self.assertIn("Never pad, repeat or invent", minimal)

    def test_standard_and_maximum_rule_bytes_are_unchanged(self):
        self.assertEqual(
            hashlib.sha256(main.STANDARD_DENSITY_RULES.encode()).hexdigest(),
            "ebda509a05ef438c0e2c155b82fa2c366e71dccf52b88bc0b4863ba1e1e94ab5",
        )
        self.assertEqual(
            hashlib.sha256(main.MAXIMUM_DENSITY_RULES.encode()).hexdigest(),
            "76f22c9633b028d657280d4ddc89066349a561323b4a6c3705dc44c3fc3d46db",
        )


class DensityGuardTests(unittest.TestCase):
    def test_minimal_accepts_one_to_three_and_rejects_more_than_three(self):
        for count in (1, 2, 3):
            with self.subTest(count=count):
                self.assertEqual(main.digest_quality_problem(digest(points(count)), "stop", "minimal"), "")
        self.assertIn("超過上限", main.digest_quality_problem(digest(points(4)), "stop", "minimal"))

    def test_simplified_floor_applies_at_the_visible_source_threshold(self):
        source = "甲" * main.SIMPLIFIED_SOURCE_MIN_VISIBLE_CHARS
        self.assertEqual(main.source_visible_char_count("甲 乙\n丙"), 3)
        self.assertIn(
            "塊數不足",
            main.digest_quality_problem(digest(points(2)), "stop", "simplified", news_text=source),
        )
        self.assertEqual(
            main.digest_quality_problem(digest(points(3)), "stop", "simplified", news_text=source),
            "",
        )

    def test_simplified_thin_source_does_not_trigger_the_floor(self):
        source = "甲" * (main.SIMPLIFIED_SOURCE_MIN_VISIBLE_CHARS - 1)
        self.assertEqual(
            main.digest_quality_problem(digest(points(1)), "stop", "simplified", news_text=source),
            "",
        )

    def test_minimal_guard_stops_at_the_existing_short_retry_cap(self):
        request = main.GenerateRequest(news_text="素材", type_label="資料圖表", density="minimal")
        too_many = response(points(4))
        with patch.object(main.time, "sleep"), patch.object(
            main.openai_client.chat.completions, "create", side_effect=[too_many] * main.DIGEST_ATTEMPTS
        ) as create:
            with self.assertRaises(main.HTTPException) as raised:
                main.generate(request)
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(create.call_count, main.DIGEST_POINT_COUNT_ATTEMPTS)
        self.assertLess(main.DIGEST_POINT_COUNT_ATTEMPTS, main.DIGEST_ATTEMPTS)

    def test_simplified_shortfall_is_released_after_the_short_retry_cap(self):
        """B67：塊數不足試滿三次就放行——防呆分不出模型偷懶與素材真的只有兩點。"""
        request = main.GenerateRequest(
            news_text="甲" * main.SIMPLIFIED_SOURCE_MIN_VISIBLE_CHARS,
            type_label="資料圖表",
            density="simplified",
        )
        too_few = response(points(2))
        with patch.object(main.time, "sleep"), patch.object(
            main.openai_client.chat.completions, "create", side_effect=[too_few] * main.DIGEST_ATTEMPTS
        ) as create:
            result = main.generate(request)
        self.assertEqual(create.call_count, main.DIGEST_POINT_COUNT_ATTEMPTS)
        self.assertEqual(main.count_density_points(result.variable), 2)

    def test_broadcast_simplified_is_not_gated_until_d17(self):
        source = "甲" * main.SIMPLIFIED_SOURCE_MIN_VISIBLE_CHARS
        for fmt in ("broadcast", "broadcast_left"):
            with self.subTest(fmt=fmt):
                self.assertIsNotNone(main._format_exact_point_count(fmt, "simplified"))
                self.assertEqual(
                    main.digest_point_count_problem(points(2), "simplified", fmt, news_text=source),
                    "",
                )


if __name__ == "__main__":
    unittest.main()
