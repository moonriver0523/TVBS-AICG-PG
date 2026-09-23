import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

from fastapi import HTTPException

os.environ.setdefault("OPENAI_API_KEY", "test-key")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402


APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")


def _run_node(body: str) -> dict:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const source = fs.readFileSync({json.dumps(str(ROOT / 'app.js'))}, 'utf8');
        function section(start, end) {{
          return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
        }}
        {body}
        """
    )
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class B102RefineParameterSnapshotTests(unittest.TestCase):
    def test_reset_uses_the_request_snapshot_and_response_model(self):
        out = _run_node(
            """
            let state = {
              density: 'current', safeFrame: true, currentRole: 'current-role',
              imageSize: '1K', refineStack: [], restampRequestId: 0,
            };
            const document = {getElementById: () => null};
            const currentAspectRatio = () => 'current-ratio';
            const effectiveImageProvider = () => 'current-provider';
            const updateRefineControls = () => {};
            eval(section('function appliedDisclaimer()', 'function updateRefineControls'));
            const sent = {
              density: 'sent-density', safe_frame: false,
              safe_frame_profile: 'sent-role', aspect_ratio: 'sent-ratio',
              image_size: '2K', provider: 'sent-provider', model: 'stale-model',
            };
            resetRefineState(
              {base64: 'raw', mimeType: 'image/png'},
              {image_data_base64: 'done', model: 'actual-model'}, sent,
            );
            console.log(JSON.stringify(state.refineParameters));
            """
        )
        self.assertEqual(
            out,
            {
                "density": "sent-density",
                "safe_frame": False,
                "safe_frame_profile": "sent-role",
                "aspect_ratio": "sent-ratio",
                "image_size": "2K",
                "provider": "sent-provider",
                "model": "actual-model",
            },
        )

    def test_all_generation_paths_capture_before_await_and_pass_the_snapshot(self):
        cases = (
            ("async function handleTenCoverGenerate", "const COVER_TITLES_BACKEND_URL", "COVER_BACKEND_URL", "resetRefineState("),
            ("async function handleYtCoverGenerate", "/* ============================================================\n   YT 直播「直標」", "YT_COVER_BACKEND_URL", "showYtCoverResult("),
            ("async function handleOneClickGenerate", "function appliedDisclaimer", "IMAGE_BACKEND_URL", "resetRefineState("),
        )
        for start, end, backend, sink in cases:
            with self.subTest(path=start):
                section = APP_JS[APP_JS.index(start):APP_JS.index(end, APP_JS.index(start))]
                snapshot_at = section.index("refineParametersFromState()")
                fetch_at = section.index(f"fetch({backend}")
                reset_at = section.index(sink)
                self.assertLess(snapshot_at, fetch_at)
                self.assertLess(fetch_at, reset_at)
                reset_call = section[reset_at:section.index(");", reset_at) + 2]
                self.assertIn("generationParameters", reset_call)

    def test_refine_success_and_undo_keep_the_saved_snapshot(self):
        out = _run_node(
            """
            const elements = {
              refineInput: {value: 'change it'}, replacementPerson: {value: ''},
              refineBtn: {disabled: false}, refineBtnText: {innerText: ''},
              refineLoading: {classList: {add() {}, remove() {}}},
            };
            const document = {getElementById: id => elements[id] || {}};
            let state = {
              refineSource: {base64: 'old-source', mimeType: 'image/png'},
              refineDisplay: {image_data_base64: 'old-display', model: 'old-model'},
              refineParameters: {
                density: 'saved-density', safe_frame: false,
                safe_frame_profile: 'saved-role', aspect_ratio: 'saved-ratio',
                image_size: '2K', provider: 'saved-provider', model: 'old-model',
              },
              refineStack: [], ytCoverTitleMode: 'ai', tenCoverMode: 'ai',
              editorFormat: 'reporter',
            };
            const editorFormat = () => ({inputs: 'standard'});
            const currentAspectRatio = () => {throw new Error('must not read current aspect ratio')};
            const effectiveImageProvider = () => {throw new Error('must not read current provider')};
            const requestsNamedFaceReplacement = () => false;
            const clearGenerateBannerForNewRequest = () => {};
            const showGenerateErrorBanner = () => {};
            const showGenerateNoticeBanner = () => {};
            const updateRefineControls = () => {};
            const showToast = () => {};
            const shown = [];
            const showRefinedImage = data => shown.push(data.image_data_base64);
            const appliedDisclaimer = () => ({kind: '', sourceText: '', corner: 'lower_right'});
            const broadcastHoleForApi = () => '';
            const userRefImagesPayload = () => [];
            const _apiHeaders = () => ({});
            const _apiError = () => 'error';
            const REFINE_BACKEND_URL = '/api/images/refine';
            const refineSourceFromResponse = data => ({base64: data.source_image_base64, mimeType: data.mime_type});
            let payload;
            global.fetch = async (_url, options) => {
              payload = JSON.parse(options.body);
              return {ok: true, json: async () => ({
                image_data_base64: 'new-display', source_image_base64: 'new-source',
                mime_type: 'image/png', model: 'actual-new-model', notices: [],
              })};
            };
            eval(section('async function handleRefine()', 'function copyToClipboard()'));
            handleRefine().then(() => {
              const afterSuccess = {...state.refineParameters};
              undoRefine();
              console.log(JSON.stringify({payload, afterSuccess, afterUndo: state.refineParameters, shown}));
            });
            """
        )
        expected = {
            "density": "saved-density",
            "safe_frame": False,
            "safe_frame_profile": "saved-role",
            "aspect_ratio": "saved-ratio",
            "image_size": "2K",
            "provider": "saved-provider",
        }
        self.assertEqual({key: out["payload"][key] for key in expected}, expected)
        self.assertEqual({key: out["afterSuccess"][key] for key in expected}, expected)
        self.assertEqual(out["afterSuccess"]["model"], "actual-new-model")
        self.assertEqual({key: out["afterUndo"][key] for key in expected}, expected)
        self.assertEqual(out["afterUndo"]["model"], "old-model")
        self.assertEqual(out["shown"], ["new-display", "old-display"])


class B103RestampValidationAuditTests(unittest.TestCase):
    @staticmethod
    def _request(**overrides):
        payload = {
            "source_image_base64": "eA==",
            "disclaimer_kind": "source",
            "disclaimer_source_text": "TVBS",
            "disclaimer_corner": "lower_right",
        }
        payload.update(overrides)
        return main.ImageRestampRequest(**payload)

    def test_blank_source_text_is_400_and_is_audited(self):
        for source_text in ("", " \t\r\n "):
            with self.subTest(source_text=repr(source_text)), patch.object(
                main, "_record_generation_failure"
            ) as record:
                with self.assertRaises(HTTPException) as caught:
                    main.restamp_disclaimer(
                        self._request(disclaimer_source_text=source_text)
                    )
                self.assertEqual(caught.exception.status_code, 400)
                record.assert_called_once()
                self.assertEqual(record.call_args.kwargs["source"], "web-restamp")

    def test_broadcast_hole_400_is_audited(self):
        with patch.object(main, "_record_generation_failure") as record:
            with self.assertRaises(HTTPException) as caught:
                main.restamp_disclaimer(self._request(broadcast_hole="left"))
            self.assertEqual(caught.exception.status_code, 400)
            record.assert_called_once()
            self.assertEqual(record.call_args.kwargs["source"], "web-restamp")


class B104UpstreamSecretRedactionTests(unittest.TestCase):
    class FakeError(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.message = message
            self.status_code = 502

    def test_every_supported_secret_shape_is_redacted_from_detail(self):
        secrets = (
            "sk-abcdefghijklmnopqrstuvwxyz",
            "pk-abcdefghijklmnopqrstuvwxyz",
            "Authorization: Bearer bearer-secret-123456",
            "AIzaSyA1234567890abcdefghijklmnop",
            "https://example.test/path?api_key=query-secret-123&x=1",
            "https://example.test/path?key=query-secret-456&x=1",
        )
        for secret in secrets:
            with self.subTest(secret=secret):
                detail = main.upstream_error_detail(self.FakeError(f"provider said {secret}"))
                self.assertNotIn(secret, detail)


if __name__ == "__main__":
    unittest.main()
