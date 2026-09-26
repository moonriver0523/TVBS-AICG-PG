import ast
import base64
import inspect
import io
import json
import pathlib
import re
import subprocess
import unittest
from unittest.mock import patch

from PIL import Image
from fastapi import HTTPException

import compose
import main
import safe_area_spec


ROOT = pathlib.Path(__file__).resolve().parents[1]


def png_base64(size=(1920, 1080), mode="RGB"):
    image = Image.new(mode, size, (24, 36, 48, 0) if mode == "RGBA" else (24, 36, 48))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class CoordinateAndPixelTests(unittest.TestCase):
    def test_normalized_position_is_the_bbox_center(self):
        bbox = compose.free_label_box(
            "cg", "ai", "", (1920, 1080), position=(0.5, 0.5),
            profile=safe_area_spec.REPORTER_PROFILE,
        )
        self.assertAlmostEqual((bbox[0] + bbox[2]) / 2, 960, delta=1)
        self.assertAlmostEqual((bbox[1] + bbox[3]) / 2, 540, delta=1)

    def test_default_cg_renderer_is_pixel_identical(self):
        raw = base64.b64decode(png_base64())
        old = compose.paste_disclaimer_note(
            raw, kind="ai", corner="lower_right",
            profile=safe_area_spec.REPORTER_PROFILE,
        )
        new, _ = compose.paste_free_label(
            raw, target="cg", kind="ai", position=None,
            profile=safe_area_spec.REPORTER_PROFILE,
            context={"corner": "lower_right"},
        )
        self.assertEqual(old, new)

    def test_broadcast_default_moves_to_opposite_side_and_is_valid(self):
        for hole_side, expected_half in (("left", "right"), ("right", "left")):
            context = {"corner": "lower_right", "hole_side": hole_side}
            bbox = compose.free_label_box(
                "broadcast", "ai", "", (1920, 1080),
                profile=safe_area_spec.REPORTER_PROFILE, context=context,
            )
            compose.validate_free_label_box(
                bbox, target="broadcast", canvas=(1920, 1080),
                profile=safe_area_spec.REPORTER_PROFILE, context=context,
            )
            center_x = (bbox[0] + bbox[2]) / 2
            self.assertEqual(center_x > 960, expected_half == "right")

    def test_ten_cover_edit_handle_is_clamped_into_side_safe_rect(self):
        item = main._default_label_item(
            target="ten_cover", item_id="left", side="left", kind="ai",
            source_text="", provenance_kind="ai",
        )
        compose.validate_free_label_box(
            tuple(item["bbox"]), target="ten_cover", canvas=(1920, 1080),
            profile=safe_area_spec.EDITOR_FRAME_PROFILE, side="left",
        )

    def test_unmeasured_cg_preview_matches_the_renderer_bbox_width(self):
        text_value = "畫面來源：美聯社"
        bbox = compose.free_label_box(
            "cg", "source", text_value, (1920, 1080), position=(0.5, 0.5),
            profile=safe_area_spec.REPORTER_PROFILE,
        )
        expected = (bbox[2] - bbox[0]) / 1920
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        start = source.index("function _freeLabelBoxRatio")
        end = source.index("\n}", start) + 2
        script = (
            source[start:end] + "\n"
            + "const item={kind:'source',source_text:"
            + json.dumps(text_value, ensure_ascii=False)
            + ",bbox:[]};"
            + "const editor={target:'cg',canvasWidth:1920,canvasHeight:1080};"
            + "process.stdout.write(JSON.stringify(_freeLabelBoxRatio(item,editor)));"
        )
        completed = subprocess.run(
            ["node", "-e", script], cwd=ROOT, check=True,
            capture_output=True, text=True, encoding="utf-8",
        )
        actual = json.loads(completed.stdout)["w"]
        self.assertAlmostEqual(actual, expected, delta=0.005)

    def test_illegal_position_moves_to_the_nearest_legal_position(self):
        context = {"original_audio": True, "ai_translation": True, "draw_date": True}
        obstacle = compose.free_label_obstacles(
            "yt_news", (1920, 1080), context=context,
            profile=safe_area_spec.EDITOR_FRAME_PROFILE,
        )[0]["bbox"]
        requested = (
            ((obstacle[0] + obstacle[2]) / 2) / 1920,
            ((obstacle[1] + obstacle[3]) / 2) / 1080,
        )
        position, moved = compose.nearest_legal_free_label_position(
            "yt_news", "source", "美聯社", (1920, 1080), requested,
            profile=safe_area_spec.EDITOR_FRAME_PROFILE, context=context,
        )
        self.assertTrue(moved)
        self.assertNotEqual(position, requested)
        bbox = compose.free_label_box(
            "yt_news", "source", "美聯社", (1920, 1080), position=position,
            profile=safe_area_spec.EDITOR_FRAME_PROFILE, context=context,
        )
        compose.validate_free_label_box(
            bbox, target="yt_news", canvas=(1920, 1080),
            profile=safe_area_spec.EDITOR_FRAME_PROFILE, context=context,
        )


class GeometryGateTests(unittest.TestCase):
    def _request(self, target, position, *, context=None, side="global", kind="source"):
        return main.ImageRestampRequest(
            disclaimer_base_image_base64=png_base64(mode="RGBA" if target == "yt_vstrip" else "RGB"),
            target=target,
            target_side=side,
            position=main.NormalizedDisclaimerPosition(x=position[0], y=position[1]),
            context=context or {},
            disclaimer_kind=kind,
            disclaimer_source_text="中央社" if kind == "source" else "",
            provenance_kind=kind,
            safe_frame_profile=(
                safe_area_spec.EDITOR_FRAME_PROFILE
                if target not in ("cg", "broadcast") else safe_area_spec.REPORTER_PROFILE
            ),
        )

    def test_outside_safe_frame_is_400(self):
        with self.assertRaises(HTTPException) as caught:
            main.restamp_disclaimer(self._request("cg", (0.01, 0.01)))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("安全框", str(caught.exception.detail))

    def test_every_format_rejects_a_fixed_element_collision(self):
        cases = [
            ("broadcast", {"hole_side": "left"}, "global"),
            ("ten_cover", {}, "left"),
            ("yt_news", {"original_audio": True, "ai_translation": True}, "global"),
            ("yt_hourly", {"draw_date": True}, "global"),
            ("yt_live24", {}, "global"),
            ("yt_hot", {}, "global"),
            ("yt_vstrip", {
                "title": "第一標題", "title_second": "第二標題", "title_side": "left",
                "variant": "normal", "logo_corner": "tr", "source_corner": "tl",
            }, "global"),
        ]
        canvas = (1920, 1080)
        for target, context, side in cases:
            profile = (
                safe_area_spec.REPORTER_PROFILE
                if target == "broadcast" else safe_area_spec.EDITOR_FRAME_PROFILE
            )
            safe = compose.free_label_safe_rect(target, canvas, profile=profile, side=side)
            obstacles = compose.free_label_obstacles(
                target, canvas, context=context, profile=profile,
            )
            position = None
            for gx in range(1, 20):
                for gy in range(1, 20):
                    candidate = (
                        (safe[0] + (safe[2] - safe[0]) * gx / 20) / canvas[0],
                        (safe[1] + (safe[3] - safe[1]) * gy / 20) / canvas[1],
                    )
                    bbox = compose.free_label_box(
                        target, "source", "中央社", canvas, position=candidate,
                        profile=profile, side=side, context=context,
                    )
                    inside = (
                        bbox[0] >= safe[0] and bbox[1] >= safe[1]
                        and bbox[2] <= safe[2] and bbox[3] <= safe[3]
                    )
                    hits = any(
                        bbox[0] < box["bbox"][2] and bbox[2] > box["bbox"][0]
                        and bbox[1] < box["bbox"][3] and bbox[3] > box["bbox"][1]
                        for box in obstacles
                    )
                    if inside and hits:
                        position = candidate
                        break
                if position is not None:
                    break
            self.assertIsNotNone(position, target)
            request = self._request(target, position, context=context, side=side)
            if target == "broadcast":
                request = request.model_copy(update={"hole_side": "left"})
            with self.subTest(target=target), self.assertRaises(HTTPException) as caught:
                main.restamp_disclaimer(request)
            self.assertEqual(caught.exception.status_code, 400)
            self.assertIn("固定元素", str(caught.exception.detail))

    def test_obstacle_names_never_expose_internal_sequence_numbers(self):
        contexts = {
            "broadcast": {"hole_side": "left"},
            "yt_news": {"original_audio": True, "ai_translation": True},
            "yt_hourly": {"draw_date": True},
            "yt_vstrip": {
                "title": "第一標題", "title_second": "第二標題", "title_side": "left",
                "variant": "normal", "logo_corner": "tr", "source_corner": "tl",
            },
        }
        for target in compose.FREE_LABEL_TARGETS:
            obstacles = compose.free_label_obstacles(
                target, (1920, 1080), context=contexts.get(target, {}),
                profile=(
                    safe_area_spec.REPORTER_PROFILE
                    if target in ("cg", "broadcast") else safe_area_spec.EDITOR_FRAME_PROFILE
                ),
            )
            with self.subTest(target=target):
                self.assertFalse([
                    item["name"] for item in obstacles
                    if re.search(r"固定元素\s*\d+", item["name"])
                ])


class OverrideAuditTests(unittest.TestCase):
    def test_kind_override_warns_and_is_archived(self):
        req = main.ImageRestampRequest(
            disclaimer_base_image_base64=png_base64(),
            target="cg",
            position=main.NormalizedDisclaimerPosition(x=0.5, y=0.5),
            disclaimer_kind="source",
            disclaimer_source_text="畫面來源：中央社",
            provenance_kind="ai",
            safe_frame_profile=safe_area_spec.REPORTER_PROFILE,
        )
        with patch.object(main, "_archive_generation") as archive:
            result = main.restamp_disclaimer(req)
        self.assertTrue(result.disclaimer_manual_override)
        self.assertIn("此圖含 AI 生成內容", result.notices[0])
        self.assertTrue(archive.call_args.kwargs["label_manual_override"])
        self.assertEqual(archive.call_args.kwargs["label_provenance_kind"], "ai")
        self.assertEqual(archive.call_args.kwargs["label_kind"], "source")

    def test_ten_cover_batch_restamps_both_sides_in_one_request(self):
        req = main.ImageRestampRequest(
            disclaimer_base_image_base64=png_base64(),
            target="ten_cover",
            safe_frame_profile=safe_area_spec.EDITOR_FRAME_PROFILE,
            items=[
                main.DisclaimerRestampItem(
                    id="left", target_side="left", kind="ai",
                    position=main.NormalizedDisclaimerPosition(x=0.25, y=0.25),
                    provenance_kind="ai",
                ),
                main.DisclaimerRestampItem(
                    id="right", target_side="right", kind="source", source_text="中央社",
                    position=main.NormalizedDisclaimerPosition(x=0.75, y=0.25),
                    provenance_kind="",
                ),
            ],
        )
        with patch.object(main, "_archive_generation") as archive:
            result = main.restamp_disclaimer(req)
        self.assertEqual([item["id"] for item in result.disclaimer_items], ["left", "right"])
        self.assertTrue(result.disclaimer_manual_override)
        self.assertEqual(len(archive.call_args.kwargs["label_items"]), 2)

    def test_restamp_source_contains_no_generate_calls(self):
        tree = ast.parse(inspect.getsource(main.restamp_disclaimer))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse([name for name in called if name.startswith("generate_")], called)


class FrontendPayloadTests(unittest.TestCase):
    def _run_refine_payload(self, editor):
        script = f"""
const fs = require('fs');
const source = fs.readFileSync({json.dumps(str(ROOT / 'app.js'))}, 'utf8');
function section(start, end) {{
  return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
}}
const elements = {{
  refineInput: {{value: 'change it'}}, replacementPerson: {{value: ''}},
  refineBtn: {{disabled: false}}, refineBtnText: {{innerText: ''}},
  refineLoading: {{classList: {{add() {{}}, remove() {{}}}}}},
}};
const document = {{getElementById: id => elements[id] || {{}}}};
let state = {{
  refineSource: {{base64: 'raw-source', mimeType: 'image/png'}},
  refineDisplay: {{
    image_data_base64: 'old-display', model: 'old-model',
    disclaimer_kind: '', disclaimer_source_text: '',
    disclaimer_corner: 'lower_right', disclaimer_items: [],
  }},
  refineParameters: {{
    density: 'standard', safe_frame: true,
    safe_frame_profile: 'reporter', aspect_ratio: '16:9',
    image_size: '1K', provider: 'google', model: 'old-model',
  }},
  refineStack: [], restampRequestId: 0,
  ytCoverTitleMode: 'ai', tenCoverMode: 'ai', editorFormat: 'reporter',
  labelEditor: {json.dumps(editor, ensure_ascii=False)},
}};
const editorFormat = () => ({{inputs: 'standard'}});
const requestsNamedFaceReplacement = () => false;
const clearGenerateBannerForNewRequest = () => {{}};
const showGenerateErrorBanner = message => {{throw new Error(message)}};
const showGenerateNoticeBanner = () => {{}};
const updateRefineControls = () => {{}};
const showToast = () => {{}};
const showRefinedImage = () => {{}};
const broadcastHoleForApi = () => '';
const userRefImagesPayload = () => [];
const _apiHeaders = () => ({{}});
const _apiError = () => 'error';
const REFINE_BACKEND_URL = '/api/images/refine';
const refineSourceFromResponse = data => ({{base64: data.source_image_base64, mimeType: data.mime_type}});
let payload;
global.fetch = async (_url, options) => {{
  payload = JSON.parse(options.body);
  return {{ok: true, json: async () => ({{
    image_data_base64: 'new-display', source_image_base64: 'new-source',
    source_mime_type: 'image/png', mime_type: 'image/png',
    model: 'new-model', notices: [],
  }})}};
}};
eval(section('function appliedDisclaimer()', 'function updateRefineControls'));
eval(section('async function handleRefine()', 'function copyToClipboard()'));
handleRefine().then(() => process.stdout.write(JSON.stringify(payload)));
"""
        completed = subprocess.run(
            ["node", "-e", script], cwd=ROOT, check=True,
            capture_output=True, text=True, encoding="utf-8",
        )
        return json.loads(completed.stdout)

    def test_refine_payload_uses_the_current_single_label_snapshot(self):
        for target in (
            "cg", "broadcast", "yt_news", "yt_hourly", "yt_live24", "yt_hot", "yt_vstrip",
        ):
            editor = {
                "base64": "BASE", "target": target, "context": {}, "model": "pillow",
                "items": [{
                    "id": "global", "side": "global", "kind": "source",
                    "source_text": "美聯社", "position": {"x": 0.23, "y": 0.31},
                    "provenance_kind": "ai", "manual_override": True,
                }],
            }
            with self.subTest(target=target):
                payload = self._run_refine_payload(editor)
                self.assertEqual(payload["disclaimer_kind"], "source")
                self.assertEqual(payload["disclaimer_source_text"], "美聯社")
                self.assertEqual(payload["disclaimer_position"], {"x": 0.23, "y": 0.31})
                self.assertTrue(payload["disclaimer_manual_override"])
                self.assertEqual(payload["disclaimer_provenance_kind"], "ai")

    def test_refine_payload_keeps_both_ten_cover_items(self):
        editor = {
            "base64": "BASE", "target": "ten_cover", "context": {}, "model": "pillow",
            "items": [
                {"id": "left", "side": "left", "kind": "ai", "source_text": "",
                 "position": {"x": 0.2, "y": 0.3}, "provenance_kind": "ai",
                 "manual_override": False},
                {"id": "right", "side": "right", "kind": "source", "source_text": "路透社",
                 "position": {"x": 0.8, "y": 0.3}, "provenance_kind": "",
                 "manual_override": True},
            ],
        }
        payload = self._run_refine_payload(editor)
        self.assertEqual([item["id"] for item in payload["disclaimer_items"]], ["left", "right"])
        self.assertEqual(payload["disclaimer_items"][1]["position"], {"x": 0.8, "y": 0.3})
        self.assertTrue(payload["disclaimer_items"][1]["manual_override"])

    def test_payload_builder_executes_and_keeps_both_ten_cover_items(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        start = source.index("function buildFreeLabelPayload")
        end = source.index("\n}", start) + 2
        function_source = source[start:end]
        editor = {
            "base64": "BASE", "target": "ten_cover", "context": {}, "model": "pillow",
            "items": [
                {"id": "left", "side": "left", "kind": "ai", "source_text": "",
                 "position": {"x": 0.2, "y": 0.2}, "provenance_kind": "ai"},
                {"id": "right", "side": "right", "kind": "source", "source_text": "中央社",
                 "position": {"x": 0.8, "y": 0.2}, "provenance_kind": ""},
            ],
        }
        script = (
            function_source + "\n"
            + f"const payload=buildFreeLabelPayload({json.dumps(editor, ensure_ascii=False)}, '編輯');"
            + "process.stdout.write(JSON.stringify(payload));"
        )
        completed = subprocess.run(
            ["node", "-e", script], cwd=ROOT, check=True,
            capture_output=True, text=True, encoding="utf-8",
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["target"], "ten_cover")
        self.assertEqual([item["target_side"] for item in payload["items"]], ["left", "right"])
        self.assertEqual(payload["items"][1]["provenance_kind"], "")

    def test_successful_restamp_clears_the_previous_collision_toast(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        start = source.index("async function restampFreeLabels")
        end = source.index("\n}", start) + 2
        function_source = source[start:end]
        script = f"""
let cleared = 0;
const editor = {{imageId:'oneClickImage',items:[],safeRect:[],obstacles:[]}};
const state = {{labelEditor:editor,labelRestampRequestId:0,refineDisplay:{{}},currentRole:'記者'}};
const API_BASE = '';
const _apiHeaders = () => ({{}});
const _apiError = () => 'error';
const buildFreeLabelPayload = () => ({{}});
const hideToast = () => {{cleared += 1;}};
const showToast = () => {{}};
const showGenerateNoticeBanner = () => {{}};
const renderFreeLabelEditor = () => {{}};
const image = {{src:''}};
const document = {{getElementById: () => image}};
global.fetch = async () => ({{ok:true,json:async()=>({{
  mime_type:'image/png',image_data_base64:'done',disclaimer_items:[],
  disclaimer_safe_rect:[],disclaimer_obstacles:[],notices:[],
}})}});
{function_source}
restampFreeLabels().then(() => process.stdout.write(String(cleared)));
"""
        completed = subprocess.run(
            ["node", "-e", script], cwd=ROOT, check=True,
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(completed.stdout, "1")

    def test_cover_refine_restamps_the_snapshot_after_recompose(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        start = source.index("async function restampRefinedCoverLabels")
        end = source.index("\n}", start) + 2
        function_source = source[start:end]
        script = f"""
const API_BASE = '';
const _apiHeaders = () => ({{}});
const _apiError = () => 'error';
let payload;
global.fetch = async (_url, options) => {{
  payload = JSON.parse(options.body);
  return {{ok:true,json:async()=>({{notices:[],image_data_base64:'done'}})}};
}};
{function_source}
const display = {{
  disclaimer_base_image_base64:'clean',source_image_base64:'raw',
  source_mime_type:'image/png',mime_type:'image/png',model:'fake',notices:[],
}};
const applied = {{
  kind:'',sourceText:'',position:null,provenanceKind:'',manualOverride:true,
  target:'ten_cover',context:{{}},items:[
    {{id:'left',target_side:'left',kind:'ai',source_text:'',position:{{x:0.2,y:0.3}},provenance_kind:'ai',manual_override:false}},
    {{id:'right',target_side:'right',kind:'source',source_text:'路透社',position:{{x:0.8,y:0.3}},provenance_kind:'',manual_override:true}},
  ],
}};
restampRefinedCoverLabels(display, applied).then(result =>
  process.stdout.write(JSON.stringify({{payload,result}}))
);
"""
        completed = subprocess.run(
            ["node", "-e", script], cwd=ROOT, check=True,
            capture_output=True, text=True, encoding="utf-8",
        )
        out = json.loads(completed.stdout)
        self.assertTrue(out["payload"]["clamp_to_legal"])
        self.assertEqual(out["payload"]["target"], "ten_cover")
        self.assertEqual([item["id"] for item in out["payload"]["items"]], ["left", "right"])


class RefineSchemaTests(unittest.TestCase):
    def test_refine_request_accepts_the_complete_label_snapshot(self):
        request = main.ImageRefineRequest(
            source_image_base64=png_base64(),
            instruction="change it",
            disclaimer_kind="source",
            disclaimer_source_text="美聯社",
            disclaimer_corner="lower_right",
            disclaimer_position=main.NormalizedDisclaimerPosition(x=0.23, y=0.31),
            disclaimer_manual_override=True,
            disclaimer_provenance_kind="ai",
            disclaimer_target="cg",
            disclaimer_context={},
            disclaimer_items=[
                main.DisclaimerRestampItem(
                    id="global", target_side="global", kind="source", source_text="美聯社",
                    position=main.NormalizedDisclaimerPosition(x=0.23, y=0.31),
                    provenance_kind="ai", manual_override=True,
                )
            ],
        )
        self.assertEqual(request.disclaimer_position.x, 0.23)
        self.assertTrue(request.disclaimer_manual_override)
        self.assertEqual(request.disclaimer_items[0].source_text, "美聯社")

    def test_refine_response_preserves_both_ten_cover_items(self):
        items = [
            main.DisclaimerRestampItem(
                id="left", target_side="left", kind="ai",
                position=main.NormalizedDisclaimerPosition(x=0.2, y=0.3),
                provenance_kind="ai",
            ),
            main.DisclaimerRestampItem(
                id="right", target_side="right", kind="source", source_text="路透社",
                position=main.NormalizedDisclaimerPosition(x=0.8, y=0.3),
                provenance_kind="", manual_override=True,
            ),
        ]
        request = main.ImageRefineRequest(
            source_image_base64=png_base64(), instruction="change it",
            provider="gemini", cover_kind="ten_cover",
            disclaimer_target="ten_cover", disclaimer_items=items,
        )
        generated = main.ImageGenerateResponse(
            image_data_base64=png_base64(), mime_type="image/png", model="fake",
        )
        with (
            patch.object(main, "supports_reference_image", return_value=True),
            patch.object(main, "generate_image_raw", return_value=generated),
            patch.object(main, "_archive_generation"),
            patch.object(main.request_log, "log_generation"),
        ):
            result = main.refine_image(request)
        self.assertEqual([item["id"] for item in result.disclaimer_items], ["left", "right"])
        self.assertEqual(result.disclaimer_items[1]["position"], {"x": 0.8, "y": 0.3})
        self.assertTrue(result.disclaimer_items[1]["manual_override"])

    def test_refine_clamps_a_label_when_new_broadcast_obstacles_make_it_illegal(self):
        context = {"hole_side": "left"}
        obstacle = compose.free_label_obstacles(
            "broadcast", (1920, 1080), context=context,
            profile=safe_area_spec.REPORTER_PROFILE,
        )[0]["bbox"]
        position = main.NormalizedDisclaimerPosition(
            x=((obstacle[0] + obstacle[2]) / 2) / 1920,
            y=((obstacle[1] + obstacle[3]) / 2) / 1080,
        )
        request = main.ImageRefineRequest(
            source_image_base64=png_base64(), instruction="change it",
            provider="gemini", broadcast_hole="left", hole_side="left",
            safe_frame_profile=safe_area_spec.REPORTER_PROFILE,
            disclaimer_target="broadcast", disclaimer_context=context,
            disclaimer_kind="source", disclaimer_source_text="美聯社",
            disclaimer_position=position, disclaimer_provenance_kind="source",
            disclaimer_items=[main.DisclaimerRestampItem(
                kind="source", source_text="美聯社", position=position,
                provenance_kind="source",
            )],
        )
        generated = main.ImageGenerateResponse(
            image_data_base64=png_base64(), mime_type="image/png", model="fake",
        )
        with (
            patch.object(main, "supports_reference_image", return_value=True),
            patch.object(main, "generate_image_raw", return_value=generated),
            patch.object(main, "_archive_generation"),
            patch.object(main.request_log, "log_generation"),
        ):
            result = main.refine_image(request)
        self.assertNotEqual(result.disclaimer_items[0]["position"], position.model_dump())
        self.assertIn("最近的合法位置", "\n".join(result.notices))


if __name__ == "__main__":
    unittest.main()
