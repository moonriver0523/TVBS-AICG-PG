"""F54 透 CG：純綠外框、後端強制規則與前端資料流。"""

import base64
import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from PIL import Image  # noqa: E402

import main  # noqa: E402
import compose  # noqa: E402
import news_prompt  # noqa: E402
import safe_area_spec  # noqa: E402
import safe_frame  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def png_bytes(size=(1280, 720), colour=(24, 48, 96)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, colour).save(output, format="PNG")
    return output.getvalue()


def png_base64(size=(1280, 720), colour=(24, 48, 96)) -> str:
    return base64.b64encode(png_bytes(size, colour)).decode("ascii")


class ChromaSafeFrameTests(unittest.TestCase):
    def test_every_sample_outside_safe_area_is_exact_chroma_green(self):
        output = safe_frame.apply_safe_frame(
            png_bytes(), background=safe_frame.CHROMA,
        )
        with Image.open(io.BytesIO(output)) as opened:
            image = opened.convert("RGB")
        self.assertEqual(image.format, None)  # 已 decode；下面另驗實際輸出簽名
        self.assertTrue(output.startswith(b"\x89PNG\r\n\x1a\n"))
        x0, y0, x1, y1 = safe_area_spec.safe_rect(*image.size, "記者")
        probes = []
        for x in range(0, image.width, 17):
            probes.extend(((x, 0), (x, y0 - 1), (x, y1), (x, image.height - 1)))
        for y in range(0, image.height, 13):
            probes.extend(((0, y), (x0 - 1, y), (x1, y), (image.width - 1, y)))
        probes.extend(((0, 0), (image.width - 1, 0),
                       (0, image.height - 1), (image.width - 1, image.height - 1)))
        for point in probes:
            with self.subTest(point=point):
                self.assertEqual(image.getpixel(point), safe_frame.CHROMA_KEY_GREEN)

        # 安全區中央仍是來源內容；純色外框沒有陰影或漸層。
        self.assertEqual(image.getpixel(((x0 + x1) // 2, (y0 + y1) // 2)), (24, 48, 96))
        outside_colours = {
            image.getpixel((x, y0 - 1)) for x in range(image.width)
        } | {
            image.getpixel((x0 - 1, y)) for y in range(image.height)
        }
        self.assertEqual(outside_colours, {safe_frame.CHROMA_KEY_GREEN})


class BackendContractTests(unittest.TestCase):
    def test_request_models_default_to_off(self):
        self.assertFalse(main.GenerateRequest(news_text="x", type_label="資料圖表").transparent_cg)
        self.assertFalse(main.ImageGenerateRequest(prompt="p").transparent_cg)
        self.assertFalse(main.NewsImageGenerateRequest(news_text="x").transparent_cg)
        self.assertFalse(main.ImageRefineRequest(
            source_image_base64="x", instruction="x",
        ).transparent_cg)
        self.assertFalse(main.ImageRestampRequest().transparent_cg)

    def test_true_forces_safe_frame_and_disables_model_extension(self):
        req = main.ImageGenerateRequest(
            prompt="p", safe_frame=False, frame_strategy="model_extension",
            transparent_cg=True,
        )
        forced = main.enforce_transparent_cg(req)
        self.assertTrue(forced.safe_frame)
        self.assertEqual(forced.frame_strategy, "")

    def test_false_is_identity_and_keeps_existing_values(self):
        req = main.ImageGenerateRequest(
            prompt="p", safe_frame=False, frame_strategy="model_extension",
            transparent_cg=False,
        )
        self.assertIs(main.enforce_transparent_cg(req), req)
        self.assertFalse(req.safe_frame)
        self.assertEqual(req.frame_strategy, "model_extension")


class PromptTests(unittest.TestCase):
    REQUIRED = (
        "TRANSPARENT CG TEXT CARD",
        "text and numbers are the primary visual",
        "Unless USER INSTRUCTION explicitly requests",
        "near (0,255,0)",
    )

    def test_digest_rules_only_appear_when_on_and_off_is_byte_for_byte_compatible(self):
        baseline = main.build_digest_instructions("記者", "standard", "資料圖表")
        explicit_off = main.build_digest_instructions(
            "記者", "standard", "資料圖表", transparent_cg=False,
        )
        enabled = main.build_digest_instructions(
            "記者", "standard", "資料圖表", transparent_cg=True,
        )
        self.assertEqual(explicit_off, baseline)
        for phrase in self.REQUIRED:
            self.assertNotIn(phrase, baseline)
            self.assertIn(phrase, enabled)
        self.assertIn("non-chroma data green remains allowed", baseline)
        self.assertIn("non-chroma data green remains allowed", enabled)

    def test_image_prompt_rules_only_appear_when_on(self):
        kwargs = dict(
            role="記者", engine="gpt", type_label="資料圖表",
            style="style", structure="structure", variable="variable",
            safe_frame=True,
        )
        baseline = news_prompt.build_prompt(**kwargs)
        self.assertEqual(news_prompt.build_prompt(**kwargs, transparent_cg=False), baseline)
        enabled = news_prompt.build_prompt(**kwargs, transparent_cg=True)
        for phrase in self.REQUIRED:
            self.assertNotIn(phrase, baseline)
            self.assertIn(phrase, enabled)
        self.assertIn("non-chroma data green remains allowed", enabled)


class RefineAndTitleOnlyTests(unittest.TestCase):
    def _request(self, action=""):
        return main.ImageRefineRequest(
            source_image_base64=png_base64(), source_mime_type="image/png",
            instruction="只改指定內容", audit_action=action, provider="gpt",
            safe_frame=False, frame_strategy="model_extension", transparent_cg=True,
        )

    @staticmethod
    def _claims():
        return {
            "target": "cg",
            "context": {"safe_frame": False, "frame_strategy": "model_extension",
                        "transparent_cg": True},
            "safe_frame_profile": "記者",
            "items": [{"id": "global", "side": "global", "provenance_kind": ""}],
        }

    def _run(self, action=""):
        raw = main.ImageGenerateResponse(
            image_data_base64=png_base64(), mime_type="image/png", model="fake",
        )
        with patch.object(main, "_validate_reusable_image"), \
             patch.object(main, "_verified_label_claims", return_value=self._claims()), \
             patch.object(main, "supports_reference_image", return_value=True), \
             patch.object(main, "generate_image_raw", return_value=raw), \
             patch.object(main.request_log, "log_generation"), \
             patch.object(main, "_archive_generation") as archive:
            result = main.refine_image(self._request(action))
        return result, archive.call_args.kwargs

    def assert_green_frame(self, result):
        with Image.open(io.BytesIO(base64.b64decode(result.image_data_base64))) as opened:
            image = opened.convert("RGB")
        x0, y0, x1, y1 = safe_area_spec.safe_rect(*image.size, "記者")
        for point in ((0, 0), (image.width - 1, 0), (0, image.height - 1),
                      (image.width - 1, image.height - 1), (x0 - 1, y0), (x1, y1 - 1)):
            self.assertEqual(image.getpixel(point), safe_frame.CHROMA_KEY_GREEN)

    def test_refine_reapplies_green_frame_after_ai_output(self):
        result, archived = self._run()
        self.assert_green_frame(result)
        self.assertTrue(archived["transparent_cg"])

    def test_title_only_reapplies_green_frame_after_ai_output(self):
        result, archived = self._run("title-only")
        self.assert_green_frame(result)
        self.assertEqual(archived["source"], "web-title-only")
        self.assertTrue(archived["transparent_cg"])


class ProgramLabelPlacementTests(unittest.TestCase):
    def test_cg_labels_are_wholly_inside_the_reporter_safe_area(self):
        canvas = safe_area_spec.BASE_CANVAS
        safe = compose.free_label_safe_rect("cg", canvas, profile="記者")
        for corner in ("upper_left", "upper_right", "lower_left", "lower_right", "lower_center"):
            with self.subTest(corner=corner):
                box = compose.free_label_box(
                    "cg", "source", "畫面來源：測試", canvas,
                    profile="記者", context={"corner": corner},
                )
                self.assertGreaterEqual(box[0], safe[0])
                self.assertGreaterEqual(box[1], safe[1])
                self.assertLessEqual(box[2], safe[2])
                self.assertLessEqual(box[3], safe[3])

class FrontendSourceTests(unittest.TestCase):
    def section(self, start, end):
        return APP_JS.split(start, 1)[1].split(end, 1)[0]

    def test_button_and_default_off_exist(self):
        self.assertIn('id="p1-btnTransparentCg"', INDEX_HTML)
        self.assertIn('onclick="toggleTransparentCg()"', INDEX_HTML)
        self.assertRegex(APP_JS, r"transparentCg:\s*false")
        self.assertNotIn("localStorage", self.section("function toggleTransparentCg", "function toggleSafeFrame"))

    def test_on_disables_safe_frame_and_model_extension(self):
        sync = self.section("function syncTransparentCgControl", "function toggleSafeFrame")
        self.assertIn("state.safeFrame = true", sync)
        self.assertIn("state.modelExtension = false", sync)
        self.assertIn("safeButton.disabled", sync)
        self.assertIn("extension.disabled", sync)
        toggle = self.section("function toggleSafeFrame", "// 蓋章開關")
        self.assertIn("if (state.transparentCg) return", toggle)

    def test_role_or_hidden_safe_frame_turns_it_off(self):
        sync = self.section("function syncTransparentCgControl", "function toggleSafeFrame")
        self.assertIn("state.currentRole !== '記者'", sync)
        self.assertIn("formatHidesSafeFrame", sync)
        self.assertIn("state.transparentCg = false", sync)

    def test_all_safe_frame_payloads_also_carry_transparent_cg(self):
        lines = APP_JS.splitlines()
        safe_payloads = [i for i, line in enumerate(lines) if "safe_frame:" in line]
        self.assertGreaterEqual(len(safe_payloads), 5)
        for index in safe_payloads:
            nearby = "\n".join(lines[index:index + 5])
            with self.subTest(line=index + 1):
                self.assertIn("transparent_cg:", nearby)

    def test_frontend_prompt_receives_transparent_flag(self):
        signature = self.section("function buildPrompt(", ") {").splitlines()[0]
        self.assertIn("transparentCg = false", signature)
        self.assertIn("transparentCg: state.transparentCg", APP_JS)


if __name__ == "__main__":
    unittest.main()
