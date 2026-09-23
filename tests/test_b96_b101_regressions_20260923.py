import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import compose
import main
import name_aliases
import photo_lookup


class B96PortraitFallbackTests(unittest.TestCase):
    def test_baghaei_alias_uses_the_confirmed_english_article(self):
        self.assertEqual(photo_lookup.TW_PORTRAIT_NAME_ALIASES["貝卡伊"], "Esmail Baghaei")

    def test_no_entry_fallback_is_enabled_by_default(self):
        self.assertTrue(main.PORTRAIT_NO_ENTRY_FALLBACK)

    def test_guessed_english_name_requires_description_context_match(self):
        photo = photo_lookup.ReferencePhoto("eA==", "image/jpeg", "https://img", "https://page", "en")

        def lookup(name, lang, timeout, *, identity_context=""):
            if name == "Esmail Baghaei":
                return (True, photo) if "伊朗外交" in identity_context else (False, None)
            return False, None

        with patch.object(photo_lookup, "_lookup_lang", side_effect=lookup):
            accepted = photo_lookup.find_portrait_outcome(
                "巴蓋伊",
                guessed_alt_names=["Esmail Baghaei"],
                source_context="伊朗外交部發言人貝卡伊表示",
                langs=("zh", "en"),
            )
            rejected = photo_lookup.find_portrait_outcome(
                "同名人士",
                guessed_alt_names=["Esmail Baghaei"],
                source_context="法國足球教練接受訪問",
                langs=("zh", "en"),
            )
        self.assertIs(accepted.photo, photo)
        self.assertIsNone(rejected.photo)

    def test_cross_language_identity_check_requires_nationality_and_role(self):
        description = ["Iranian diplomat and government spokesperson"]
        self.assertTrue(photo_lookup._identity_description_matches(
            description, "伊朗外交部發言人貝卡伊表示",
        ))
        self.assertFalse(photo_lookup._identity_description_matches(
            description, "法國足球教練貝卡伊受訪",
        ))


class B97B98RestampFrontendTests(unittest.TestCase):
    @staticmethod
    def _run_node(body: str) -> dict:
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const source = fs.readFileSync({json.dumps(str(ROOT / 'app.js'))}, 'utf8');
            function section(start, end) {{
              return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
            }}
            let state = {{
              density: 'text_heavy', safeFrame: false, currentRole: '記者', imageSize: '2K',
              disclaimerCorner: 'lower_left', refineSource: null, refineDisplay: null,
              refineStack: [], restampRequestId: 0, editorFormat: 'reporter'
            }};
            const document = {{ getElementById: () => null }};
            const RESTAMP_BACKEND_URL = '/api/images/restamp-disclaimer';
            const _apiHeaders = () => ({{}});
            const editorFormat = () => ({{ hides: {{}} }});
            const effectiveImageProvider = () => 'gemini';
            const currentAspectRatio = () => '21:9';
            const broadcastHoleForApi = () => '';
            const DISCLAIMER_CORNER_LABELS = {{lower_left: '左下', upper_right: '右上'}};
            const updateRefineControls = () => {{}};
            const shown = [];
            const toasts = [];
            const showRefinedImage = data => shown.push(data.image_data_base64);
            const showToast = msg => toasts.push(msg);
            const _apiError = () => 'error';
            eval(section('async function restampDisclaimer()', 'function onDisclaimerSourceInput'));
            eval(section('function appliedDisclaimer()', 'function updateRefineControls'));
            {body}
            """
        )
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8",
            capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    def test_restamp_uses_the_parameters_saved_with_the_original(self):
        out = self._run_node(
            """
            let payload;
            global.fetch = async (_url, options) => {
              payload = JSON.parse(options.body);
              return {ok: true, json: async () => ({image_data_base64: 'new', mime_type: 'image/png'})};
            };
            resetRefineState({base64: 'raw', mimeType: 'image/png'}, {
              image_data_base64: 'old', mime_type: 'image/png', model: 'original-model',
              disclaimer_kind: 'ai'
            });
            state.density = 'simplified'; state.safeFrame = true; state.currentRole = '編輯';
            state.imageSize = '1K';
            restampDisclaimer().then(() => console.log(JSON.stringify(payload)));
            """
        )
        self.assertEqual(
            {key: out[key] for key in (
                "density", "safe_frame", "safe_frame_profile", "aspect_ratio",
                "image_size", "provider", "model",
            )},
            {
                "density": "text_heavy", "safe_frame": False,
                "safe_frame_profile": "記者", "aspect_ratio": "21:9",
                "image_size": "2K", "provider": "gemini", "model": "original-model",
            },
        )

    def test_stale_restamp_response_cannot_replace_the_newer_one_or_toast(self):
        out = self._run_node(
            """
            const pending = [];
            global.fetch = () => new Promise(resolve => pending.push(resolve));
            resetRefineState({base64: 'raw', mimeType: 'image/png'}, {
              image_data_base64: 'old', mime_type: 'image/png', model: 'm', disclaimer_kind: 'ai'
            });
            state.disclaimerCorner = 'lower_left'; const older = restampDisclaimer();
            state.disclaimerCorner = 'upper_right'; const newer = restampDisclaimer();
            pending[1]({ok: true, json: async () => ({image_data_base64: 'newer', mime_type: 'image/png'})});
            setImmediate(() => {
              pending[0]({ok: true, json: async () => ({image_data_base64: 'older', mime_type: 'image/png'})});
              Promise.all([older, newer]).then(() => console.log(JSON.stringify({
                display: state.refineDisplay.image_data_base64, shown, toasts
              })));
            });
            """
        )
        self.assertEqual(out["display"], "newer")
        self.assertEqual(out["shown"], ["newer"])
        self.assertEqual(len(out["toasts"]), 1)
        self.assertIn("右上", out["toasts"][0])


class B99AliasBoundaryTests(unittest.TestCase):
    def test_common_words_after_two_character_alias_are_blocked(self):
        for text in ("永川習俗", "山川習性", "冰川習性"):
            with self.subTest(text=text):
                self.assertNotIn("川習", [alias for alias, _ in name_aliases.find_aliases(text)])

    def test_real_abbreviation_uses_remain_recognised(self):
        for text in ("川習會", "川習通話", "川習互動"):
            with self.subTest(text=text):
                aliases = [alias for alias, _ in name_aliases.find_aliases(text)]
                self.assertTrue("川習" in aliases or "川習會" in aliases)

    def test_prefix_guard_still_blocks_sichuan_xi_jinping(self):
        aliases = [alias for alias, _ in name_aliases.find_aliases("四川習近平視察")]
        self.assertNotIn("川習", aliases)


class B100AtomicCoverTokenTests(unittest.TestCase):
    def test_unbreakable_latin_token_is_left_for_fit_logic(self):
        token = "SUPERCALIFRAGILISTIC"
        self.assertEqual(compose._split_line_near_middle(token), (token, ""))
        self.assertEqual(compose._fill_cover_title_lines([token]), [token])

    def test_symbols_inside_latin_tokens_are_atomic(self):
        for token in ("AT&T", "C++", "C#"):
            with self.subTest(token=token):
                self.assertEqual(compose._split_line_near_middle(token), (token, ""))


class B101DeterministicUpstreamErrorsTests(unittest.TestCase):
    class FakeError(Exception):
        def __init__(self, message, status_code):
            super().__init__(message)
            self.message = message
            self.status_code = status_code

    def test_non_retryable_4xx_stop_and_keep_upstream_text(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                stop = main.non_retryable_upstream_error(
                    self.FakeError("model is not available for this key", status)
                )
                self.assertIsNotNone(stop)
                self.assertIn(str(status), stop.detail)
                self.assertIn("model is not available", stop.detail)

    def test_transient_statuses_still_retry(self):
        for status in (408, 429, 500, 502, 503):
            with self.subTest(status=status):
                self.assertIsNone(
                    main.non_retryable_upstream_error(self.FakeError("temporary", status))
                )


if __name__ == "__main__":
    unittest.main()
