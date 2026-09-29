"""F53「只留標題（前一張）」：固定指令走既有 web-refine，不打真實 API。"""

import base64
import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi import HTTPException  # noqa: E402
from PIL import Image  # noqa: E402

import main  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")
MAIN_PY = (ROOT / "main.py").read_text(encoding="utf-8")


def png_base64(colour=(30, 40, 50), size=(1920, 1080)) -> str:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


FIXED_INSTRUCTION = """保留標題「媽祖遶境」的文字內容、字形、字級、顏色、位置與外觀完全不變。
保留所有既有版面框架、卡片、底板、照片、人物、圖示、背景、整體構圖與每個元素的位置完全不變。
刪除標題以外的所有文字，包括內文、數字、小標、說明、註記與標籤牌上的字；刪字後原本的框、卡片、底板、標籤牌與色塊必須留空保留，不要把框或任何容器一起刪掉。
不要新增任何文字、圖像、符號或元素，不要重新設計，不要改變構圖，只做上述刪字。"""


class RefinePathTests(unittest.TestCase):
    def request(self):
        return main.ImageRefineRequest(
            source_image_base64=png_base64(),
            source_mime_type="image/png",
            label_token="signed-label-token",
            instruction=FIXED_INSTRUCTION,
            audit_action="title-only",
            provider="gpt",
            safe_frame_profile="記者",
            disclaimer_kind="ai",
            disclaimer_items=[{
                "id": "global", "target_side": "global", "kind": "ai",
            }],
        )

    @staticmethod
    def claims():
        return {
            "target": "cg",
            "context": {"safe_frame": False},
            "safe_frame_profile": "記者",
            "items": [{
                "id": "global", "side": "global", "provenance_kind": "ai",
            }],
        }

    def test_title_only_uses_refine_generation_label_and_archive_pipeline(self):
        generated = main.ImageGenerateResponse(
            image_data_base64=png_base64(), mime_type="image/png", model="fake-model",
        )
        labelled = generated.model_copy(update={
            "disclaimer_kind": "ai",
            "disclaimer_items": [{
                "id": "global", "side": "global", "kind": "ai",
                "provenance_kind": "ai",
            }],
        })
        with patch.object(main, "_validate_reusable_image"), \
             patch.object(main, "_verified_label_claims", return_value=self.claims()), \
             patch.object(main, "supports_reference_image", return_value=True), \
             patch.object(main, "generate_image_raw", return_value=generated) as generate, \
             patch.object(main, "finalize_image_result", return_value=generated), \
             patch.object(
                 main, "_apply_refine_label_snapshot", return_value=labelled,
             ) as apply_label, \
             patch.object(main.request_log, "log_generation") as log_generation, \
             patch.object(main, "_archive_generation") as archive:
            response = main.refine_image(self.request())

        sent = generate.call_args.args[0]
        self.assertIn("媽祖遶境", sent.prompt)
        self.assertIn("框、卡片、底板、標籤牌與色塊必須留空保留", sent.prompt)
        self.assertTrue(sent.reference_image_data_url.startswith("data:image/png;base64,"))
        self.assertEqual(apply_label.call_count, 1)
        self.assertEqual(response.disclaimer_kind, "ai")
        self.assertEqual(log_generation.call_args.kwargs["source"], "web-title-only")
        archived = archive.call_args.kwargs
        self.assertEqual(archived["source"], "web-title-only")
        self.assertEqual(archived["action"], "只留標題（前一張）")
        self.assertIn(FIXED_INSTRUCTION, archived["prompt"])
        self.assertEqual(archived["label_kind"], "ai")
        self.assertEqual(archived["label_items"][0]["id"], "global")

    def test_failure_is_a_title_only_failure_and_never_archives_a_result(self):
        failure = HTTPException(status_code=502, detail="上游改圖失敗")
        with patch.object(main, "_validate_reusable_image"), \
             patch.object(main, "_verified_label_claims", return_value=self.claims()), \
             patch.object(main, "supports_reference_image", return_value=True), \
             patch.object(main, "generate_image_raw", side_effect=failure), \
             patch.object(main, "_record_generation_failure") as record, \
             patch.object(main, "_archive_generation") as archive:
            with self.assertRaises(HTTPException):
                main.refine_image(self.request())
        self.assertEqual(record.call_args.kwargs["source"], "web-title-only")
        self.assertEqual(record.call_args.kwargs["action"], "只留標題（前一張）")
        self.assertIn("媽祖遶境", record.call_args.kwargs["prompt"])
        archive.assert_not_called()

    def test_old_ocr_mask_and_local_repair_path_is_gone(self):
        self.assertFalse((ROOT / "title_only.py").exists())
        for obsolete in (
            "edit_mask_data_url", "local-opencv", "plan_title_only_edit",
            "verify_body_text_removed", '"/api/images/title-only"',
        ):
            self.assertNotIn(obsolete, MAIN_PY)


class FrontendWiringTests(unittest.TestCase):
    def section(self, start, end):
        return APP_JS.split(start, 1)[1].split(end, 1)[0]

    def test_fixed_instruction_contains_title_empty_frames_and_no_redesign_rule(self):
        instruction = self.section(
            "function titleOnlyInstruction(title)", "function clearTitleOnlyResult"
        )
        self.assertIn('保留標題「${title}」', instruction)
        self.assertIn("框、卡片、底板、標籤牌與色塊必須留空保留", instruction)
        self.assertIn("不要把框或任何容器一起刪掉", instruction)
        self.assertIn("不要重新設計", instruction)
        self.assertIn("不要新增任何文字、圖像、符號或元素", instruction)

    def test_button_is_only_revealed_after_a_generated_supported_result(self):
        self.assertIn('id="titleOnlyAction" class="hidden', INDEX_HTML)
        controls = self.section("function updateRefineControls()", "function showRefinedImage")
        self.assertIn("!!state.refineSource && !!state.refineDisplay", controls)
        self.assertIn("supportsTitleOnlyFormat()", controls)
        support = self.section("function supportsTitleOnlyFormat()", "function titleOnlyInstruction")
        self.assertIn("EDITOR_FORMAT_DEFAULT", support)
        self.assertIn("'broadcast'", support)
        for excluded in ("ten_cover", "yt_live_cover", "yt_vstrip"):
            self.assertNotIn(excluded, support)

    def test_button_posts_the_fixed_instruction_to_the_existing_refine_endpoint(self):
        handler = self.section("async function handleTitleOnly()", "// F32")
        self.assertIn("fetch(REFINE_BACKEND_URL", handler)
        self.assertIn("titleOnlyInstruction(title)", handler)
        self.assertIn("audit_action: 'title-only'", handler)
        for field in (
            "source_image_base64", "source_mime_type", "label_token", "instruction",
            "disclaimer_kind", "disclaimer_items", "safe_frame", "frame_strategy",
        ):
            self.assertIn(field, handler)
        self.assertNotIn("TITLE_ONLY_BACKEND_URL", APP_JS)

    def test_success_and_failure_leave_the_full_result_untouched(self):
        handler = self.section("async function handleTitleOnly()", "// F32")
        self.assertNotIn("state.refineDisplay =", handler)
        self.assertNotIn("state.refineSource =", handler)
        self.assertIn("showTitleOnlyImage(data)", handler)
        self.assertIn("完整版仍保留在上方", handler)
        self.assertIn("完整版未受影響", handler)

    def test_previous_image_is_separate_and_download_name_has_suffix(self):
        show = self.section("function showTitleOnlyImage(data)", "async function handleTitleOnly")
        self.assertIn("state.titleOnlyDisplay = data", show)
        self.assertIn("'_前一張'", show)
        self.assertIn("titleOnlyDownload", APP_JS)
        self.assertIn('id="titleOnlyResult" class="hidden', INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
