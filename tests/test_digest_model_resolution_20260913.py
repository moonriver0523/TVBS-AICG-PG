"""消化模型的解析要看後端（2026-09-13）。

真因：.env 的 `DIGEST_MODEL=anthropic/claude-sonnet-5` 是 OpenRouter slug，
`load_dotenv()` 之後原生路徑照樣讀到它，送進 api.openai.com 得到 400
「invalid model ID」，畫面描述整段走退路、指令欄被丟掉。之前誤判成
「gpt-5.6-terra 在使用者 key 上不存在」。

規則：帶 `/` 的 slug 只在 client 真的指向 openrouter 時才採用；
否則退回該後端預設。判斷看 client 的 base_url，不看 DIGEST_BACKEND 字串。
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402

OPENROUTER = SimpleNamespace(base_url="https://openrouter.ai/api/v1/")
NATIVE = SimpleNamespace(base_url="https://api.openai.com/v1/")
SLUG = "anthropic/claude-sonnet-5"


class DigestModelResolution(unittest.TestCase):
    def test_openrouter_client_honours_slug(self):
        with patch.dict(os.environ, {"DIGEST_MODEL": SLUG}), \
                patch.object(main, "openai_client", OPENROUTER), \
                patch.object(main, "DEFAULT_DIGEST_MODEL", "x/default"):
            self.assertEqual(main.resolve_digest_model(), SLUG)

    def test_native_client_ignores_openrouter_slug(self):
        with patch.dict(os.environ, {"DIGEST_MODEL": SLUG}), \
                patch.object(main, "openai_client", NATIVE), \
                patch.object(main, "DEFAULT_DIGEST_MODEL", "gpt-5.5"):
            self.assertEqual(main.resolve_digest_model(), "gpt-5.5")

    def test_native_client_honours_native_override(self):
        with patch.dict(os.environ, {"DIGEST_MODEL": "gpt-5.4-mini"}), \
                patch.object(main, "openai_client", NATIVE), \
                patch.object(main, "DEFAULT_DIGEST_MODEL", "gpt-5.5"):
            self.assertEqual(main.resolve_digest_model(), "gpt-5.4-mini")

    def test_backend_string_openrouter_without_key_still_native(self):
        # DIGEST_BACKEND=openrouter 但沒 key 會落到原生 client，字串仍寫 openrouter
        with patch.dict(os.environ, {"DIGEST_MODEL": SLUG}), \
                patch.object(main, "DIGEST_BACKEND", "openrouter"), \
                patch.object(main, "openai_client", NATIVE), \
                patch.object(main, "DEFAULT_DIGEST_MODEL", "gpt-5.5"):
            self.assertEqual(main.resolve_digest_model(), "gpt-5.5")

    def test_legacy_openai_digest_model_still_secondary(self):
        env = {"DIGEST_MODEL": "", "OPENAI_DIGEST_MODEL": "gpt-4.1"}
        with patch.dict(os.environ, env), \
                patch.object(main, "openai_client", NATIVE), \
                patch.object(main, "DEFAULT_DIGEST_MODEL", "gpt-5.5"):
            self.assertEqual(main.resolve_digest_model(), "gpt-4.1")

    def test_no_override_returns_backend_default(self):
        with patch.dict(os.environ, {"DIGEST_MODEL": "", "OPENAI_DIGEST_MODEL": ""}), \
                patch.object(main, "openai_client", NATIVE), \
                patch.object(main, "DEFAULT_DIGEST_MODEL", "gpt-5.5"):
            self.assertEqual(main.resolve_digest_model(), "gpt-5.5")


if __name__ == "__main__":
    unittest.main()
