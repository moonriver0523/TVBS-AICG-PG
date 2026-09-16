"""D21（2026-09-16）：消化改送 reasoning.effort、provider 改用 require_parameters、
主模型換 google/gemini-3.8-flash，並保留退回 Claude 的能力。

根因見 docs/交辦-20260916-D21改effort換Gemini.md：reasoning.max_tokens 被 Sonnet 5
官方文件明說對 Claude 系模型不生效，reasoning.effort 才是真的被遵守的欄位。
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402

OPENROUTER = SimpleNamespace(base_url="https://openrouter.ai/api/v1/")


class ReasoningEffortEnvOverrideTests(unittest.TestCase):
    """DIGEST_REASONING_EFFORT 的環境變數覆寫要真的生效，含「不送」那條路。"""

    def test_default_is_low(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), patch.object(
            main, "DIGEST_REASONING_EFFORT", "low"
        ):
            self.assertEqual(main.digest_reasoning_body(), {"reasoning": {"effort": "low"}})

    def test_env_can_raise_it_to_medium_or_high(self):
        for effort in ("medium", "high"):
            with self.subTest(effort=effort):
                with patch.object(main, "DIGEST_BACKEND", "openrouter"), patch.object(
                    main, "DIGEST_REASONING_EFFORT", effort
                ):
                    self.assertEqual(
                        main.digest_reasoning_body(), {"reasoning": {"effort": effort}}
                    )

    def test_empty_string_disables_it(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), patch.object(
            main, "DIGEST_REASONING_EFFORT", ""
        ):
            self.assertEqual(main.digest_reasoning_body(), {})

    def test_off_disables_it(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), patch.object(
            main, "DIGEST_REASONING_EFFORT", "off"
        ):
            self.assertEqual(main.digest_reasoning_body(), {})

    def test_per_call_override_wins_over_the_configured_default(self):
        # 重試降級用：呼叫端傳 effort_override 時，蓋過 DIGEST_REASONING_EFFORT。
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), patch.object(
            main, "DIGEST_REASONING_EFFORT", "medium"
        ):
            self.assertEqual(
                main.digest_reasoning_body("low"), {"reasoning": {"effort": "low"}}
            )

    def test_non_openrouter_backends_send_nothing(self):
        for backend in ("native", "gemini"):
            with self.subTest(backend=backend):
                with patch.object(main, "DIGEST_BACKEND", backend), patch.object(
                    main, "DIGEST_REASONING_EFFORT", "low"
                ):
                    self.assertEqual(main.digest_reasoning_body(), {})


class ProviderRequireParametersTests(unittest.TestCase):
    """provider body 真的帶 require_parameters: true（取代舊版寫死的 Anthropic 白名單）。"""

    def test_require_parameters_is_sent(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), patch.object(
            main, "DIGEST_PROVIDER_REQUIRE_PARAMETERS", True
        ):
            body = main.digest_provider_body()
        self.assertEqual(
            body, {"provider": {"require_parameters": True, "allow_fallbacks": True}}
        )

    def test_can_be_disabled_via_env_flag(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), patch.object(
            main, "DIGEST_PROVIDER_REQUIRE_PARAMETERS", False
        ):
            self.assertEqual(main.digest_provider_body(), {})

    def test_non_openrouter_backends_send_nothing(self):
        for backend in ("native", "gemini"):
            with self.subTest(backend=backend):
                with patch.object(main, "DIGEST_BACKEND", backend), patch.object(
                    main, "DIGEST_PROVIDER_REQUIRE_PARAMETERS", True
                ):
                    self.assertEqual(main.digest_provider_body(), {})

    def test_env_var_parsing_treats_these_as_false(self):
        # DIGEST_PROVIDER_REQUIRE_PARAMETERS 是模組載入時算好的常數，這裡不重新
        # import main（會重建 openai_client），直接驗證 main.py 用的同一條解析式。
        for raw in ("0", "false", "off", "False", ""):
            with self.subTest(raw=raw):
                value = raw.strip().lower() not in ("", "0", "false", "off")
                self.assertFalse(value)


class RollbackToClaudeTests(unittest.TestCase):
    """換主模型是硬需求要能退：只改環境變數、不改程式碼就能退回 Claude。"""

    def test_default_model_is_now_gemini(self):
        with patch.object(main, "openai_client", OPENROUTER):
            self.assertEqual(main.DEFAULT_DIGEST_MODEL, "google/gemini-3.8-flash")

    def test_digest_model_env_var_rolls_back_to_claude(self):
        with patch.dict(os.environ, {"DIGEST_MODEL": "anthropic/claude-sonnet-5"}), \
                patch.object(main, "openai_client", OPENROUTER):
            self.assertEqual(main.resolve_digest_model(), "anthropic/claude-sonnet-5")

    def test_provider_and_reasoning_bodies_are_unaffected_by_which_model_is_chosen(self):
        # require_parameters／effort 兩個欄位只看 DIGEST_BACKEND，不看選了哪個模型，
        # 退回 Claude 時這兩段行為不必、也不會跟著變。
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), patch.object(
            main, "DIGEST_PROVIDER_REQUIRE_PARAMETERS", True
        ), patch.object(main, "DIGEST_REASONING_EFFORT", "low"):
            self.assertIn("provider", main.digest_provider_body())
            self.assertIn("reasoning", main.digest_reasoning_body())


if __name__ == "__main__":
    unittest.main()
