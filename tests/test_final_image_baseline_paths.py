"""B61／B62：所有生圖路徑在 provider transport 前都經同一條冪等鐵律。

mock 停在 generate_image_raw 下游的 urlopen（OpenRouter images），不斷言 route URL
就算完成。前端不准複製 baseline 文字——ownership 留在後端。
"""

from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import unittest
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "b61-baseline-key")

import main  # noqa: E402
import news_prompt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
client = TestClient(main.app)

MARKER = "=== FINAL IMAGE POLICY BASELINE ==="
HYBRID_JS = ROOT / "hybrid.js"
APP_JS = ROOT / "app.js"
NEWS = "熊本強震重創九州 當地疏散逾21萬人 多處道路中斷"
FAKE_DIGEST = main.GenerateResponse(
    style="S",
    structure="T",
    variable="[標題] 熊本強震重創九州\n[內文小標] 疏散逾21萬人",
    chart_type="資料圖表",
)


def _headers() -> dict:
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}


def _png_b64(aspect_ratio: str = "16:9") -> str:
    ratio = main.parse_aspect_ratio(aspect_ratio) or 1.0
    height = 720
    buf = io.BytesIO()
    Image.new("RGB", (round(height * ratio), height), (30, 60, 90)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class _FakeUrlopenResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _openrouter_env():
    return patch.dict(
        os.environ,
        {"IMAGE_BACKEND": "openrouter", "OPENROUTER_API_KEY": "test-or-key"},
    )


class BaselineTextTests(unittest.TestCase):
    def test_marker_is_a_stable_dedicated_string(self):
        self.assertEqual(news_prompt.FINAL_IMAGE_BASELINE_MARKER, MARKER)
        self.assertIn(MARKER, news_prompt.FINAL_IMAGE_BASELINE)
        self.assertEqual(news_prompt.FINAL_IMAGE_BASELINE.count(MARKER), 1)

    def test_marker_does_not_appear_in_older_prompt_blocks(self):
        for block in (
            news_prompt.REAL_WORLD_RENDERING_RULES,
            news_prompt.PORTRAIT_WITH_REFERENCE_RULES,
            news_prompt.PORTRAIT_NO_REFERENCE_RULES,
            news_prompt.PORTRAIT_MULTI_WITH_REFERENCE_RULES,
            news_prompt.SOURCE_BRANDS_RULE,
            news_prompt.NO_TEXT_IMAGE_OVERRIDE,
            news_prompt.USER_REFERENCE_MAP_RULES,
        ):
            with self.subTest(block=block[:40]):
                self.assertNotIn(MARKER, block)

    def test_ensure_appends_once_when_missing(self):
        out = news_prompt.ensure_final_image_baseline("plain scene")
        self.assertTrue(out.startswith("plain scene"))
        self.assertEqual(out.count(MARKER), 1)
        self.assertIn(news_prompt.FINAL_IMAGE_BASELINE, out)

    def test_ensure_is_idempotent_on_the_marker_not_a_body_phrase(self):
        confusing = (
            "Do not invent logos. Named real people appear in this news graphic. "
            "Do not draw a recognisable face."
        )
        once = news_prompt.ensure_final_image_baseline(confusing)
        twice = news_prompt.ensure_final_image_baseline(once)
        self.assertEqual(once, twice)
        self.assertEqual(once.count(MARKER), 1)
        already = "keep me\n\n" + news_prompt.FINAL_IMAGE_BASELINE
        self.assertEqual(news_prompt.ensure_final_image_baseline(already), already)

    def test_baseline_does_not_blanket_ban_requested_title_text(self):
        text = news_prompt.FINAL_IMAGE_BASELINE
        lowered = text.lower()
        self.assertNotIn("absolutely no text", lowered)
        self.assertNotIn("render no text of any kind", lowered)
        self.assertNotIn("no text at all", lowered)
        self.assertRegex(
            text,
            r"(did not request|not requested|not ask)",
        )
        self.assertIn("named", lowered)
        self.assertIn("face", lowered)
        self.assertIn("logo", lowered)


class GenerateImageRawInjectionTests(unittest.TestCase):
    def _raw_ok(self, sent):
        return main.ImageGenerateResponse(
            image_data_base64=_png_b64(sent.aspect_ratio),
            mime_type="image/png",
            model="fake-or",
        )

    def test_copies_request_injects_once_and_does_not_mutate_caller(self):
        req = main.ImageGenerateRequest(prompt="plain scene", provider="gpt")
        original = req.prompt
        captured: list[main.ImageGenerateRequest] = []

        def fake_or(_model, sent):
            captured.append(sent)
            return self._raw_ok(sent)

        with _openrouter_env(), patch.object(
            main, "generate_via_openrouter", side_effect=fake_or
        ):
            main.generate_image_raw(req)

        self.assertEqual(req.prompt, original)
        self.assertEqual(len(captured), 1)
        self.assertIsNot(captured[0], req)
        self.assertEqual(captured[0].prompt.count(MARKER), 1)
        self.assertIn(news_prompt.FINAL_IMAGE_BASELINE, captured[0].prompt)

    def test_retry_with_the_same_caller_object_still_injects_once(self):
        req = main.ImageGenerateRequest(prompt="plain scene", provider="gpt")
        captured: list[str] = []

        def fake_or(_model, sent):
            captured.append(sent.prompt)
            return self._raw_ok(sent)

        with _openrouter_env(), patch.object(
            main, "generate_via_openrouter", side_effect=fake_or
        ):
            main.generate_image_raw(req)
            main.generate_image_raw(req)

        self.assertEqual(req.prompt, "plain scene")
        self.assertEqual(len(captured), 2)
        for prompt in captured:
            self.assertEqual(prompt.count(MARKER), 1)

    def test_stacked_portrait_map_user_ref_still_one_marker(self):
        stacked = "\n\n".join(
            [
                "a news graphic",
                news_prompt.PORTRAIT_WITH_REFERENCE_RULES,
                news_prompt.USER_REFERENCE_MAP_RULES,
                news_prompt.USER_REFERENCE_SCENE_RULES,
            ]
        )
        req = main.ImageGenerateRequest(prompt=stacked, provider="gpt")
        captured: list[str] = []

        def fake_or(_model, sent):
            captured.append(sent.prompt)
            return self._raw_ok(sent)

        with _openrouter_env(), patch.object(
            main, "generate_via_openrouter", side_effect=fake_or
        ):
            main.generate_image_raw(req)

        self.assertEqual(req.prompt, stacked)
        self.assertEqual(captured[0].count(MARKER), 1)
        self.assertIn(news_prompt.PORTRAIT_WITH_REFERENCE_RULES, captured[0])
        self.assertIn(news_prompt.USER_REFERENCE_MAP_RULES, captured[0])


class _TransportHarness(unittest.TestCase):
    def setUp(self):
        self.payloads: list[dict] = []
        env = _openrouter_env()
        env.start()
        self.addCleanup(env.stop)

        def fake_urlopen(request, **_kwargs):
            payload = json.loads(request.data.decode("utf-8"))
            self.payloads.append(payload)
            ratio = payload.get("aspect_ratio") or "16:9"
            return _FakeUrlopenResponse(
                {"data": [{"b64_json": _png_b64(ratio), "media_type": "image/png"}]}
            )

        urlopen = patch.object(main, "urlopen", side_effect=fake_urlopen)
        urlopen.start()
        self.addCleanup(urlopen.stop)
        archive = patch.object(main, "_archive_generation", lambda **_k: None)
        archive.start()
        self.addCleanup(archive.stop)
        fail = patch.object(main, "_archive_generation_failure", lambda **_k: None)
        fail.start()
        self.addCleanup(fail.stop)
        breaks = patch.object(main, "apply_title_break_hints", lambda *_a, **_k: None)
        breaks.start()
        self.addCleanup(breaks.stop)

    def _assert_each_payload_has_marker_once(self, *, min_calls=1, label=""):
        self.assertGreaterEqual(len(self.payloads), min_calls, label)
        for i, payload in enumerate(self.payloads):
            prompt = payload.get("prompt") or ""
            self.assertEqual(
                prompt.count(MARKER),
                1,
                f"{label} call {i} marker count={prompt.count(MARKER)}\n{prompt[-600:]}",
            )


class PathTableTests(_TransportHarness):
    def test_web_images_generate(self):
        res = client.post(
            "/api/images/generate",
            json={"prompt": "a quiet studio backdrop", "provider": "gpt"},
            headers=_headers(),
        )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(min_calls=1, label="web_generate")

    def test_news_image_generate(self):
        with patch.object(main, "generate", return_value=FAKE_DIGEST), patch.object(
            main, "resolve_digest_portraits", side_effect=lambda d, *_a, **_k: (d, [])
        ), patch.object(main, "resolve_portraits", return_value=("none", [])):
            res = client.post(
                "/api/news-image/generate",
                json={"news_text": NEWS, "provider": "gpt", "safe_frame": False},
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(min_calls=1, label="news_image")

    def test_refine(self):
        res = client.post(
            "/api/images/refine",
            json={
                "source_image_base64": _png_b64("16:9"),
                "instruction": "把天空改暗",
                "provider": "gpt",
                "aspect_ratio": "16:9",
                "safe_frame": False,
            },
            headers=_headers(),
        )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(min_calls=1, label="refine")

    def test_ten_cover_split_panels(self):
        with patch.object(
            main, "resolve_cover_visuals", return_value=("左景", "右景")
        ):
            res = client.post(
                "/api/editor/cover",
                json={
                    "title_left": "左標題",
                    "title_right": "右標題",
                    "layout": "split",
                    "mode": "composite",
                    "provider": "gpt",
                },
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(min_calls=2, label="ten_cover_panels")
        self.assertEqual(len(self.payloads), 2)

    def test_ten_cover_ai_full(self):
        with patch.object(
            main, "resolve_cover_visuals", return_value=("滿版景", "")
        ):
            res = client.post(
                "/api/editor/cover",
                json={
                    "title_left": "滿版標題",
                    "layout": "full",
                    "mode": "ai",
                    "title_creativity": 1,
                    "provider": "gpt",
                },
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(min_calls=1, label="ten_cover_ai_full")
        prompt = self.payloads[0]["prompt"]
        self.assertIn("TEXT TO RENDER", prompt)
        self.assertIn("滿版標題", prompt)

    def test_ten_cover_composite_full_slot(self):
        with patch.object(
            main, "resolve_cover_visuals", return_value=("滿版景", "")
        ):
            res = client.post(
                "/api/editor/cover",
                json={
                    "title_left": "滿版標題",
                    "layout": "full",
                    "mode": "composite",
                    "provider": "gpt",
                },
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(
            min_calls=1, label="ten_cover_composite_full"
        )

    def test_yt_single_background(self):
        with patch.object(
            main,
            "derive_yt_cover_plan",
            return_value={"visual": "單則場景", "portrait_subjects": [], "portrait_subjects_en": []},
        ):
            res = client.post(
                "/api/editor/yt-cover",
                json={
                    "title": "前段 後段",
                    "layout": "news",
                    "title_mode": "composite",
                    "provider": "gpt",
                },
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(min_calls=1, label="yt_single_bg")

    def test_yt_dual_slots(self):
        with patch.object(
            main,
            "derive_yt_cover_plan",
            return_value={"visual": "雙則場景", "portrait_subjects": [], "portrait_subjects_en": []},
        ):
            res = client.post(
                "/api/editor/yt-cover",
                json={
                    "title": "第一則",
                    "title_second": "第二則",
                    "layout": "hourly",
                    "title_mode": "composite",
                    "provider": "gpt",
                },
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(min_calls=2, label="yt_dual_slots")
        self.assertEqual(len(self.payloads), 2)

    def test_yt_ai_full(self):
        with patch.object(
            main,
            "derive_yt_cover_plan",
            return_value={"visual": "AI標題場景", "portrait_subjects": [], "portrait_subjects_en": []},
        ):
            res = client.post(
                "/api/editor/yt-cover",
                json={
                    "title": "前段 後段",
                    "layout": "news",
                    "title_mode": "ai",
                    "creativity": 1,
                    "provider": "gpt",
                },
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(min_calls=1, label="yt_ai_full")
        prompt = self.payloads[0]["prompt"]
        self.assertIn("前段", prompt)
        self.assertIn("後段", prompt)

    def test_hybrid_background_hits_images_generate_transport(self):
        source = HYBRID_JS.read_text(encoding="utf-8")
        self.assertIn("/api/images/generate", source)
        self.assertIn("function buildBgPrompt", source)
        res = client.post(
            "/api/images/generate",
            json={
                "prompt": (
                    "Generate a text-free broadcast news background image.\n"
                    "Subject:\nUS Capitol at dusk\n"
                    "Requirements:\n- Absolutely NO text, NO numbers, NO letters"
                ),
                "provider": "gpt",
                "aspect_ratio": "16:9",
                "image_size": "1K",
            },
            headers=_headers(),
        )
        self.assertEqual(res.status_code, 200, res.text[:400])
        self._assert_each_payload_has_marker_once(min_calls=1, label="hybrid_bg")


class FrontendOwnershipTests(unittest.TestCase):
    def test_app_js_does_not_own_the_baseline(self):
        source = APP_JS.read_text(encoding="utf-8")
        self.assertNotIn(MARKER, source)
        self.assertNotIn("FINAL_IMAGE_BASELINE", source)

    def test_hybrid_js_does_not_copy_baseline_and_still_posts_to_backend(self):
        source = HYBRID_JS.read_text(encoding="utf-8")
        self.assertNotIn(MARKER, source)
        self.assertNotIn("FINAL_IMAGE_BASELINE", source)
        self.assertIn("${HYBRID_API_BASE}/api/images/generate", source)
        self.assertIn("fetch(IMAGE_BACKEND_URL", source)


if __name__ == "__main__":
    unittest.main()
