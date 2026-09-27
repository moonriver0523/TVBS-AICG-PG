"""D22 第一關：一般 CG／播出鏡面的畫面用摘要。全程不呼叫外部 API。"""

import json
import base64
import io
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
import news_prompt  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
VALID_CONTEXT = (
    "臺北市政府前的廣場聚集市民與採訪車，主要人物站在入口雨棚旁向媒體說明，"
    "背景可見市政大樓外牆、濕潤路面與警方設置的動線護欄。事件焦點是現場協調與"
    "人群疏導，人物身分應依新聞原文辨識，不要把同姓的地方官員誤認成中央官員；"
    "畫面中的車輛、制服與建築皆屬臺灣都會場景，避免畫成外國城市或選舉造勢活動。"
    "鏡頭應呈現陰雨天的真實採訪現場、群眾等待與工作人員往來的關係。"
)


def valid_png_base64():
    out = io.BytesIO()
    Image.new("RGB", (64, 36), (12, 34, 56)).save(out, "PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


def valid_digest(**updates):
    data = {
        "style": "professional broadcast visual style",
        "structure": "a clear central scene with supporting side panels",
        "variable": (
            "[標題] 測試標題\n"
            "[內文小標] 重點甲\n"
            "[內文小標] 重點乙\n"
            "[內文小標] 重點丙\n"
            "[內文小標] 重點丁\n"
            "[內文小標] 重點戊"
        ),
        "visual_context": VALID_CONTEXT,
        "chart_type": "資料圖表",
        "portrait_subjects": [],
        "portrait_subjects_en": [],
        "portrait_subjects_en_guess": [],
    }
    data.update(updates)
    return data


def digest_response(payload):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
            finish_reason="stop",
        )]
    )


def extract_js_function(name):
    start = APP_JS.index(f"function {name}(")
    brace = APP_JS.index("{", start)
    depth = 0
    for index in range(brace, len(APP_JS)):
        if APP_JS[index] == "{":
            depth += 1
        elif APP_JS[index] == "}":
            depth -= 1
            if depth == 0:
                return APP_JS[start:index + 1]
    raise AssertionError(f"找不到完整的 {name}()")


class DigestSchemaAndQualityTests(unittest.TestCase):
    def test_schema_and_response_expose_visual_context(self):
        self.assertIn("visual_context", main.GenerateResponse.model_fields)
        self.assertIn("visual_context", main.DIGEST_OUTPUT_SCHEMA["properties"])
        self.assertIn("visual_context", main.DIGEST_OUTPUT_SCHEMA["required"])
        self.assertFalse(main.DIGEST_OUTPUT_SCHEMA["additionalProperties"])
        for role in ("記者", "編輯"):
            prompt = main.build_digest_instructions(role, "simplified", "資料圖表")
            self.assertIn('"visual_context"', prompt)
            self.assertIn("400", prompt)
        main.ImageGenerateRequest(prompt="ok", visual_context="景" * 4_000)
        with self.assertRaises(ValidationError):
            main.ImageGenerateRequest(prompt="ok", visual_context="景" * 4_001)

    def test_bad_context_downgrades_without_failing_digest(self):
        cases = {
            "wrong type": None,
            "empty": "   ",
            "too short": "臺北現場人群聚集",
            "garbled": VALID_CONTEXT + "ԱԲԳ",
            "channel leak": VALID_CONTEXT + " assistant to=system ",
        }
        for label, value in cases.items():
            with self.subTest(label=label):
                data = valid_digest(visual_context=value)
                self.assertEqual(main.digest_quality_problem(data, "stop"), "")
                self.assertEqual(data["visual_context"], "")

    def test_long_context_is_capped_without_retry_signal(self):
        data = valid_digest(visual_context=VALID_CONTEXT * 5)
        self.assertEqual(main.digest_quality_problem(data, "stop"), "")
        self.assertEqual(len(data["visual_context"]), main.VISUAL_CONTEXT_MAX_CHARS)

    def test_invalid_context_does_not_trigger_generate_retry(self):
        payload = valid_digest(visual_context="太短")
        token = main._inside_pipeline.set(True)
        try:
            with patch.object(main, "digest_completion", return_value=digest_response(payload)) as call:
                result = main.generate(main.GenerateRequest(
                    news_text="測試素材", type_label="資料圖表", density="standard", seed=7,
                ))
        finally:
            main._inside_pipeline.reset(token)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result.visual_context, "")

    def test_verbatim_always_returns_empty_context(self):
        news = "逐字保留這一段新聞文字"
        payload = valid_digest(variable=news, visual_context=VALID_CONTEXT)
        token = main._inside_pipeline.set(True)
        try:
            with patch.object(main, "digest_completion", return_value=digest_response(payload)):
                result = main.generate(main.GenerateRequest(
                    news_text=news, type_label="資料圖表", density="verbatim", seed=8,
                ))
        finally:
            main._inside_pipeline.reset(token)
        self.assertEqual(result.visual_context, "")


class ImagePromptInjectionTests(unittest.TestCase):
    def _result(self):
        return main.ImageGenerateResponse(
            image_data_base64="eA==", mime_type="image/png", model="fake",
        )

    def _captured_request(self, backend, provider):
        req = main.ImageGenerateRequest(
            prompt="approved prompt", visual_context=VALID_CONTEXT, provider=provider,
        )
        env = {"IMAGE_BACKEND": backend}
        if backend == "openrouter":
            env["OPENROUTER_API_KEY"] = "test-key"
        target = (
            "generate_via_openrouter" if backend == "openrouter"
            else "generate_gpt_image" if provider == "gpt"
            else "generate_gemini_image"
        )
        with patch.dict(os.environ, env, clear=False), patch.object(
            main, target, return_value=self._result()
        ) as generate:
            main.generate_image_raw(req)
        sent = generate.call_args.args[-1]
        self.assertEqual(req.prompt, "approved prompt", "不得 mutate caller request")
        return sent

    def test_common_injection_is_once_and_before_final_policy_for_all_backends(self):
        for backend, provider in (
            ("openrouter", "gpt"), ("native", "gpt"), ("native", "gemini"),
        ):
            with self.subTest(backend=backend, provider=provider):
                sent = self._captured_request(backend, provider)
                self.assertEqual(sent.prompt.count(news_prompt.VISUAL_CONTEXT_MARKER), 1)
                self.assertLess(
                    sent.prompt.index(news_prompt.VISUAL_CONTEXT_MARKER),
                    sent.prompt.index(news_prompt.FINAL_IMAGE_BASELINE_MARKER),
                )
                self.assertIn("僅供理解新聞背景與消歧，不得把其中任何文字畫進圖中", sent.prompt)

    def test_empty_context_keeps_existing_image_prompt_byte_identical(self):
        prompt = news_prompt.build_prompt(
            role="記者", engine="gpt", type_label="資料圖表",
            style="[S]", structure="[T]", variable="[V]", safe_frame=False,
        )
        self.assertIs(news_prompt.append_visual_context(prompt, ""), prompt)
        frozen = (ROOT / "tests/fixtures/reporter-image-prompt-plain.txt").read_text(encoding="utf-8")
        self.assertEqual(prompt, frozen)

    def test_title_layer_refine_and_restamp_never_carry_context(self):
        self.assertNotIn("visual_context", main.ImageRefineRequest.model_fields)
        self.assertNotIn("visual_context", main.ImageRestampRequest.model_fields)
        req = main.ImageGenerateRequest(
            prompt="render only the approved title",
            visual_context=VALID_CONTEXT,
            provider="gpt",
            transparent_background=True,
            reference_images=[main.UserReferenceImage(
                data_url="data:image/png;base64,eA==", purpose="titlelayer",
            )],
        )
        with patch.dict(os.environ, {"IMAGE_BACKEND": "native"}, clear=False), patch.object(
            main, "generate_gpt_image", return_value=self._result()
        ) as generate:
            main.generate_image_raw(req)
        sent = generate.call_args.args[0]
        self.assertEqual(sent.visual_context, "")
        self.assertNotIn(news_prompt.VISUAL_CONTEXT_MARKER, sent.prompt)


class AuditArchiveTests(unittest.TestCase):
    def test_digest_and_image_archives_record_context(self):
        with patch.object(main, "digest_completion", return_value=digest_response(valid_digest())), \
             patch.object(main, "apply_photo_availability", side_effect=lambda result, _req: result), \
             patch.object(main.request_log, "log_generation"), \
             patch.object(main, "_archive_generation") as digest_archive, \
             patch.object(main, "_remember_digest"):
            main.generate(main.GenerateRequest(
                news_text="測試素材", type_label="資料圖表", density="standard", seed=9,
            ))
        self.assertEqual(digest_archive.call_args.kwargs["visual_context"], VALID_CONTEXT)

        req = main.ImageGenerateRequest(prompt="approved", visual_context=VALID_CONTEXT)
        result = main.ImageGenerateResponse(
            image_data_base64=valid_png_base64(), mime_type="image/png", model="fake",
        )
        identities = (
            "apply_portrait_to_image_request", "apply_map_reference_to_image_request",
            "apply_user_references_to_image_request", "apply_broadcast_hole_layout_to_image_request",
        )
        patches = [patch.object(main, name, side_effect=lambda value: value) for name in identities]
        started = [item.start() for item in patches]
        self.addCleanup(lambda: [item.stop() for item in patches])
        self.assertEqual(len(started), len(identities))
        with patch.object(main, "generate_image_raw", return_value=result), \
             patch.object(main, "finalize_image_result", return_value=result), \
             patch.object(main.request_log, "log_generation"), \
             patch.object(main, "_archive_generation") as image_archive:
            main.generate_image(req)
        self.assertEqual(image_archive.call_args.kwargs["visual_context"], VALID_CONTEXT)
        self.assertEqual(image_archive.call_args.kwargs["visual_context_chars"], len(VALID_CONTEXT))


class FrontendVisualContextTests(unittest.TestCase):
    def test_both_image_payloads_use_the_bound_digest_context(self):
        one_click = APP_JS[APP_JS.index("async function handleOneClickGenerate"):]
        one_click = one_click[:one_click.index("/* ============================================================\n   圖片生成")]
        manual = APP_JS[APP_JS.index("async function handleImageGeneration"):]
        manual = manual[:manual.index("/* ============================================================\n   ① 專用指令欄位")]
        self.assertIn("...visualContextPayload(generationParameters.density)", one_click)
        self.assertIn("...visualContextPayload(generationParameters.density)", manual)

        node = shutil.which("node")
        if not node:
            self.skipTest("本機沒有 node，跳過前端行為測試")
        script = "\n".join((
            "let state = {digestVisualContext: '', digestVisualContextSource: ''};",
            extract_js_function("rememberDigestVisualContext"),
            extract_js_function("visualContextPayload"),
            f"rememberDigestVisualContext({{visual_context: {json.dumps(VALID_CONTEXT, ensure_ascii=False)}}}, '舊原文', 'standard');",
            "const first = visualContextPayload();",
            "const editedTextarea = '新原文但沒有重消化';",
            "const afterEdit = visualContextPayload();",
            "const boundSource = state.digestVisualContextSource;",
            f"rememberDigestVisualContext({{visual_context: {json.dumps(VALID_CONTEXT, ensure_ascii=False)}}}, '逐字原文', 'verbatim');",
            "console.log(JSON.stringify({first, afterEdit, boundSource, editedTextarea, verbatim: visualContextPayload()}));",
        ))
        proc = subprocess.run(
            [node, "-e", script], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out["first"], {"visual_context": VALID_CONTEXT, "digest_id": ""})
        self.assertEqual(out["afterEdit"], out["first"])
        self.assertEqual(out["boundSource"], "舊原文")
        self.assertNotEqual(out["boundSource"], out["editedTextarea"])
        self.assertEqual(out["verbatim"], {"visual_context": "", "digest_id": ""})


if __name__ == "__main__":
    unittest.main()
