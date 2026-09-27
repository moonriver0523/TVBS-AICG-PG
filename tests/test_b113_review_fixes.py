import base64
import io
import json
import os
import pathlib
import subprocess
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "b113-test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "b113-internal-key")

import compose
import main
import safe_area_spec


ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = TestClient(main.app)


def headers():
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}


def image_b64(size=(640, 360), *, pixels=None):
    image = Image.frombytes("RGB", size, pixels) if pixels is not None else Image.new("RGB", size, (23, 45, 67))
    out = io.BytesIO()
    image.save(out, "PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


def sealed_image(*, target="cg", context=None, profile=safe_area_spec.EDITOR_FRAME_PROFILE,
                 kind="ai", size=(640, 360), source=None):
    clean = image_b64(size)
    response = main.ImageGenerateResponse(
        image_data_base64=clean,
        mime_type="image/png",
        model="test",
        source_image_base64=source or clean,
        source_mime_type="image/png",
        disclaimer_base_image_base64=clean,
        disclaimer_kind=kind,
        disclaimer_provenance_kind=kind,
        disclaimer_items=[{
            "id": "global", "side": "global", "kind": kind,
            "source_text": "", "provenance_kind": kind,
        }],
    )
    return main._seal_label_response(
        response, target=target, context=context or {}, profile=profile,
    )


class B113LabelCredentialTests(unittest.TestCase):
    def _restamp(self, sealed, **updates):
        payload = dict(
            disclaimer_base_image_base64=sealed.disclaimer_base_image_base64,
            label_token=sealed.label_token,
            target="cg",
            position={"x": 0.5, "y": 0.5},
            disclaimer_kind="ai",
            provenance_kind="source",
            items=[{
                "id": "global", "target_side": "global", "kind": "ai",
                "source_text": "", "position": {"x": 0.5, "y": 0.5},
                "provenance_kind": "source", "manual_override": False,
            }],
        )
        payload.update(updates)
        with patch.object(main, "_archive_generation"), patch.object(main, "_record_generation_failure"):
            return main.restamp_disclaimer(main.ImageRestampRequest(**payload))

    def test_01_provenance_comes_from_credential(self):
        sealed = sealed_image(kind="ai")
        result = self._restamp(sealed, items=[{
            "id": "global", "target_side": "global", "kind": "source",
            "source_text": "中央社", "position": {"x": 0.5, "y": 0.5},
            "provenance_kind": "source", "manual_override": False,
        }])
        self.assertEqual(result.disclaimer_provenance_kind, "ai")
        self.assertTrue(result.disclaimer_manual_override)
        self.assertIn("此圖含 AI 生成內容", "\n".join(result.notices))

    def test_02_target_context_spoof_cannot_bypass_obstacle(self):
        context = {"original_audio": True, "ai_translation": True, "draw_date": True}
        sealed = sealed_image(target="yt_news", context=context, size=(1920, 1080))
        obstacles = compose.free_label_obstacles(
            "yt_news", (1920, 1080), context=context,
            profile=safe_area_spec.EDITOR_FRAME_PROFILE,
        )
        safe = compose.free_label_safe_rect(
            "yt_news", (1920, 1080), profile=safe_area_spec.EDITOR_FRAME_PROFILE,
        )
        position = None
        for gx in range(1, 30):
            for gy in range(1, 30):
                candidate = {
                    "x": (safe[0] + (safe[2] - safe[0]) * gx / 30) / 1920,
                    "y": (safe[1] + (safe[3] - safe[1]) * gy / 30) / 1080,
                }
                box = compose.free_label_box(
                    "yt_news", "ai", "", (1920, 1080),
                    position=(candidate["x"], candidate["y"]),
                    profile=safe_area_spec.EDITOR_FRAME_PROFILE, context=context,
                )
                inside = box[0] >= safe[0] and box[1] >= safe[1] and box[2] <= safe[2] and box[3] <= safe[3]
                hits = any(box[0] < o["bbox"][2] and box[2] > o["bbox"][0]
                           and box[1] < o["bbox"][3] and box[3] > o["bbox"][1] for o in obstacles)
                if inside and hits:
                    position = candidate
                    break
            if position:
                break
        self.assertIsNotNone(position)
        with self.assertRaises(HTTPException) as caught:
            self._restamp(sealed, target="cg", context={}, items=[{
                "id": "global", "target_side": "global", "kind": "ai",
                "position": position, "provenance_kind": "ai",
            }])
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("固定元素", str(caught.exception.detail))

    def test_04_missing_or_wrong_credential_rejects_arbitrary_image(self):
        sealed = sealed_image()
        with self.assertRaises(HTTPException) as missing:
            self._restamp(sealed, label_token="")
        self.assertEqual(missing.exception.status_code, 400)
        self.assertEqual(missing.exception.detail, main.LABEL_DATA_EXPIRED_DETAIL)
        other = image_b64((640, 360), pixels=bytes([99, 4, 7]) * (640 * 360))
        with self.assertRaises(HTTPException) as mismatch:
            self._restamp(sealed, disclaimer_base_image_base64=other)
        self.assertEqual(mismatch.exception.status_code, 400)
        self.assertEqual(mismatch.exception.detail, main.LABEL_DATA_EXPIRED_DETAIL)

    def test_08_safe_frame_profile_comes_from_credential(self):
        sealed = sealed_image(profile=safe_area_spec.EDITOR_FRAME_PROFILE, size=(1920, 1080))
        # y=.08 is legal in the thin editor frame but outside the narrower 編輯 profile.
        result = self._restamp(sealed, safe_frame_profile=safe_area_spec.EDITOR_PROFILE, items=[{
            "id": "global", "target_side": "global", "kind": "ai",
            "position": {"x": 0.5, "y": 0.08}, "provenance_kind": "source",
        }])
        self.assertEqual(result.label_safe_frame_profile, safe_area_spec.EDITOR_FRAME_PROFILE)

    def test_12_pixel_limits_run_before_decode_work(self):
        sealed = sealed_image(size=(4097, 10))
        with self.assertRaises(HTTPException) as caught:
            self._restamp(sealed)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("4097×10", str(caught.exception.detail))

    def test_14_generate_restamp_twice_override_refine_undo_refine(self):
        """瀏覽器實測原路徑：restamp 不重送大張 source，token 仍須綁原 refine 圖。"""
        counter = 0

        def fake_raw(_req):
            nonlocal counter
            counter += 1
            return main.ImageGenerateResponse(
                image_data_base64=image_b64((1536, 864), pixels=bytes([
                    20 + counter, 40 + counter, 60 + counter,
                ]) * (1536 * 864)),
                mime_type="image/png", model=f"b113-fake-{counter}",
            )

        def restamp(display, *, position, kind=None):
            items = []
            for item in display["disclaimer_items"]:
                next_kind = item["kind"] if kind is None else kind
                items.append({
                    "id": item["id"],
                    "target_side": item.get("side", "global"),
                    "kind": next_kind,
                    "source_text": "畫面來源：美聯社" if next_kind == "source" else "",
                    "position": position,
                    "provenance_kind": item.get("provenance_kind", ""),
                    "manual_override": item.get("manual_override", False),
                })
            response = CLIENT.post("/api/images/restamp-disclaimer", json={
                "disclaimer_base_image_base64": display["disclaimer_base_image_base64"],
                "disclaimer_base_mime_type": display["disclaimer_base_mime_type"],
                "label_token": display["label_token"],
                "target": display["label_target"],
                "context": display["label_context"],
                "safe_frame_profile": display["label_safe_frame_profile"],
                "model": display["model"],
                "items": items,
            }, headers=headers())
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def refine(source, display, instruction):
            response = CLIENT.post("/api/images/refine", json={
                "source_image_base64": source["base64"],
                "source_mime_type": source["mime_type"],
                "label_token": display["label_token"],
                "instruction": instruction,
                "provider": "gemini",
                "aspect_ratio": "16:9",
                "image_size": "1K",
                "density": "normal",
                "safe_frame": True,
                "safe_frame_profile": "編輯",
                "disclaimer_items": [{
                    **item, "target_side": item.get("side", "global"),
                } for item in display["disclaimer_items"]],
            }, headers=headers())
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "_archive_generation"), \
             patch.object(main, "_record_generation_failure"), \
             patch.object(main.request_log, "log_generation"):
            generated_response = CLIENT.post("/api/images/generate", json={
                "prompt": "新聞資訊圖卡", "provider": "gemini",
                "aspect_ratio": "16:9", "image_size": "1K", "density": "normal",
                "safe_frame": True, "safe_frame_profile": "編輯",
                "disclaimer_source_text": "畫面來源：美聯社",
            }, headers=headers())
            self.assertEqual(generated_response.status_code, 200, generated_response.text)
            generated = generated_response.json()
            self.assertEqual(generated["disclaimer_provenance_kind"], "source")
            self.assertFalse(generated["disclaimer_manual_override"])
            source = {
                "base64": generated["source_image_base64"],
                "mime_type": generated["source_mime_type"],
            }

            moved_once = restamp(generated, position={"x": 0.16, "y": 0.12})
            self.assertFalse(moved_once["disclaimer_manual_override"])
            moved_twice = restamp(moved_once, position={"x": 0.20, "y": 0.16})
            self.assertFalse(moved_twice["disclaimer_manual_override"])
            overridden = restamp(moved_twice, position={"x": 0.20, "y": 0.16}, kind="ai")
            self.assertTrue(overridden["disclaimer_manual_override"])

            first_refine = refine(source, overridden, "把主標改成紅色")
            self.assertTrue(first_refine["label_token"])
            # 等同前端退回上一版：使用 stack 中舊 source/display 再送一次。
            second_refine = refine(source, overridden, "把副標改成白色")
            self.assertTrue(second_refine["label_token"])

    def test_16_ten_and_yt_cover_restamp_refine_undo_refine(self):
        """十點與 YT 封面各走一遍 token 延續鏈，避免只修一般 CG。"""
        counter = 0

        def fake_raw(_req):
            nonlocal counter
            counter += 1
            return main.ImageGenerateResponse(
                image_data_base64=image_b64(
                    (1536, 864),
                    pixels=bytes([70 + counter, 90 + counter, 110 + counter]) * (1536 * 864),
                ),
                mime_type="image/png", model=f"b113-cover-{counter}",
            )

        cases = [
            ("ten", "/api/editor/cover", {
                "title_left": "十點新聞測試標題", "layout": "full",
                "mode": "ai", "title_creativity": 1, "provider": "gemini",
            }),
            ("yt", "/api/editor/yt-cover", {
                "title": "國際新聞 測試標題", "layout": "news",
                "title_mode": "ai", "creativity": 1, "provider": "gemini",
            }),
        ]
        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "resolve_cover_visuals", return_value=("測試場景", "測試場景")), \
             patch.object(main, "resolve_yt_cover_plan", return_value=main.YtCoverPlan(
                 ("國際新聞", "測試標題"), "測試場景", [], [],
             )), \
             patch.object(main, "apply_title_break_hints"), \
             patch.object(main, "_archive_generation"), \
             patch.object(main, "_record_generation_failure"), \
             patch.object(main.request_log, "log_generation"):
            for family, endpoint, body in cases:
                with self.subTest(family=family):
                    generated_response = CLIENT.post(endpoint, json=body, headers=headers())
                    self.assertEqual(generated_response.status_code, 200, generated_response.text)
                    generated = generated_response.json()
                    self.assertTrue(generated["source_image_base64"])
                    source = {
                        "base64": generated["source_image_base64"],
                        "mime_type": generated["source_mime_type"],
                    }

                    current = generated
                    for _ in range(2):
                        restamped = CLIENT.post("/api/images/restamp-disclaimer", json={
                            "disclaimer_base_image_base64": current["disclaimer_base_image_base64"],
                            "disclaimer_base_mime_type": current["disclaimer_base_mime_type"],
                            "label_token": current["label_token"],
                            "target": current["label_target"],
                            "context": current["label_context"],
                            "safe_frame_profile": current["label_safe_frame_profile"],
                            "model": current["model"],
                            "clamp_to_legal": True,
                            "items": [{
                                **item,
                                "target_side": item.get("side", item.get("target_side", "global")),
                            } for item in current["disclaimer_items"]],
                        }, headers=headers())
                        self.assertEqual(restamped.status_code, 200, restamped.text)
                        current = restamped.json()
                        self.assertFalse(current["disclaimer_manual_override"])

                    switched_items = [{
                        **item,
                        "target_side": item.get("side", item.get("target_side", "global")),
                        "kind": "source", "source_text": "畫面來源：美聯社",
                    } for item in current["disclaimer_items"]]
                    switched_response = CLIENT.post("/api/images/restamp-disclaimer", json={
                        "disclaimer_base_image_base64": current["disclaimer_base_image_base64"],
                        "disclaimer_base_mime_type": current["disclaimer_base_mime_type"],
                        "label_token": current["label_token"],
                        "target": current["label_target"],
                        "context": current["label_context"],
                        "safe_frame_profile": current["label_safe_frame_profile"],
                        "model": current["model"], "items": switched_items,
                        "clamp_to_legal": True,
                    }, headers=headers())
                    self.assertEqual(switched_response.status_code, 200, switched_response.text)
                    previous = switched_response.json()
                    self.assertTrue(previous["disclaimer_manual_override"])

                    for instruction in ("把背景調亮", "退回上一版後再把背景調暗"):
                        refined = CLIENT.post("/api/images/refine", json={
                            "source_image_base64": source["base64"],
                            "source_mime_type": source["mime_type"],
                            "label_token": previous["label_token"],
                            "instruction": instruction, "provider": "gemini",
                            "aspect_ratio": "16:9", "image_size": "1K",
                            "cover_kind": "ten_cover" if family == "ten" else "yt_live_cover",
                            "disclaimer_items": [{
                                **item,
                                "target_side": item.get("side", item.get("target_side", "global")),
                            } for item in previous["disclaimer_items"]],
                        }, headers=headers())
                        self.assertEqual(refined.status_code, 200, refined.text)
                        self.assertTrue(refined.json()["label_token"])

    def test_18_generated_provenance_is_not_an_override_in_every_layout_family(self):
        """CG、播出、十點左右、YT、直標的首次 restamp 都沿用後端生成時判定。"""
        asis = f"data:image/png;base64,{image_b64((1200, 700))}"

        def fake_raw(_req):
            return main.ImageGenerateResponse(
                image_data_base64=image_b64((1536, 864)),
                mime_type="image/png", model="b113-provenance",
            )

        requests = [
            ("cg", "/api/images/generate", {
                "prompt": "一般 CG", "provider": "gemini",
                "disclaimer_source_text": "畫面來源：美聯社",
            }),
            ("broadcast", "/api/images/generate", {
                "prompt": "播出鏡面", "provider": "gemini", "hole_side": "left",
                "disclaimer_source_text": "畫面來源：美聯社",
            }),
            ("ten_split", "/api/editor/cover", {
                "title_left": "左標題", "title_right": "右標題", "layout": "split",
                "mode": "composite", "asis_left": asis, "asis_right": asis,
                "source_left": "美聯社", "source_right": "路透社",
            }),
            ("yt", "/api/editor/yt-cover", {
                "title": "國際新聞 測試標題", "layout": "news", "title_mode": "composite",
                "reference_images": [{"data_url": asis, "purpose": "asis"}],
                "source_text": "美聯社",
            }),
            ("vstrip", "/api/editor/yt-overlay", {
                "title": "明早晚涼中午仍破30度", "source_text": "畫面來源：美聯社",
            }),
        ]
        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "apply_title_break_hints"), \
             patch.object(main, "_archive_generation"), \
             patch.object(main, "_record_generation_failure"), \
             patch.object(main.request_log, "log_generation"):
            for family, endpoint, body in requests:
                with self.subTest(family=family):
                    response = CLIENT.post(endpoint, json=body, headers=headers())
                    self.assertEqual(response.status_code, 200, response.text)
                    generated = response.json()
                    items = generated["disclaimer_items"]
                    self.assertTrue(items)
                    self.assertTrue(all(item["kind"] == item["provenance_kind"] for item in items))

                    restamped = CLIENT.post("/api/images/restamp-disclaimer", json={
                        "disclaimer_base_image_base64": generated["disclaimer_base_image_base64"],
                        "disclaimer_base_mime_type": generated["disclaimer_base_mime_type"],
                        "label_token": generated["label_token"],
                        "target": generated["label_target"],
                        "context": generated["label_context"],
                        "safe_frame_profile": generated["label_safe_frame_profile"],
                        "model": generated.get("model", ""), "clamp_to_legal": True,
                        "items": [{
                            **item,
                            "target_side": item.get("side", item.get("target_side", "global")),
                        } for item in items],
                    }, headers=headers())
                    self.assertEqual(restamped.status_code, 200, restamped.text)
                    restamped_data = restamped.json()
                    self.assertFalse(restamped_data["disclaimer_manual_override"])
                    self.assertTrue(all(not item["manual_override"]
                                        for item in restamped_data["disclaimer_items"]))


class B113StateAndContextTests(unittest.TestCase):
    def test_03_cover_refine_uses_server_recompose_items(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        start = source.index("async function restampRefinedCoverLabels")
        end = source.index("\n}", start) + 2
        script = f"""
let sent;
const API_BASE=''; const _apiHeaders=()=>({{}}); const _apiError=()=>'';
global.fetch=async(_u,o)=>(sent=JSON.parse(o.body),{{ok:true,json:async()=>({{notices:[]}})}});
{source[start:end]}
const display={{disclaimer_base_image_base64:'base',disclaimer_base_mime_type:'image/webp',
 label_token:'token',label_target:'ten_cover',label_context:{{layout:'split'}},
 disclaimer_items:[{{id:'left',side:'left',kind:'ai',provenance_kind:'ai'}},
 {{id:'right',side:'right',kind:'ai',provenance_kind:'ai'}}]}};
restampRefinedCoverLabels(display,{{items:[{{id:'global'}}]}}).then(()=>
 process.stdout.write(JSON.stringify(sent.items.map(x=>x.id))));
"""
        done = subprocess.run(["node", "-e", script], cwd=ROOT, check=True,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(done.stdout), ["left", "right"])

    def test_05_verbatim_clears_context_at_backend_boundary(self):
        captured = {}

        def fake(req):
            captured["context"] = req.visual_context
            return main.ImageGenerateResponse(
                image_data_base64=image_b64(), mime_type="image/png", model="fake",
            )

        req = main.ImageGenerateRequest(
            prompt="draw", provider="gemini", density="verbatim",
            visual_context="這段內容不應進入模型",
        )
        with patch.dict(os.environ, {"IMAGE_BACKEND": "native"}), \
             patch.object(main, "generate_gemini_image", side_effect=fake):
            main.generate_image_raw(req)
        self.assertEqual(captured["context"], "")
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        start = source.index("function visualContextPayload")
        end = source.index("\n}", start) + 2
        script = f"""
const state={{density:'normal',digestVisualContext:'摘要',digestId:'digest-A'}};
{source[start:end]}
process.stdout.write(JSON.stringify(visualContextPayload('verbatim')));
"""
        done = subprocess.run(["node", "-e", script], cwd=ROOT, check=True,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(done.stdout), {"visual_context": "", "digest_id": "digest-A"})

    def test_06_editor_identity_comes_from_response_not_current_ui(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        start = source.index("function setupFreeLabelEditor")
        end = source.index("function _freeLabelBoxRatio", start)
        script = f"""
const state={{labelEditor:null}}; const renderFreeLabelEditor=()=>{{}};
const _defaultFreeLabelItem=()=>({{id:'global'}});
const document={{getElementById:()=>({{naturalWidth:0,naturalHeight:0,addEventListener:()=>{{}}}})}};
{source[start:end]}
setupFreeLabelEditor({{disclaimer_base_image_base64:'base',label_target:'yt_vstrip',
 label_context:{{live:false,hole_side:'right'}},label_safe_frame_profile:'profile-A',
 label_token:'token-A',disclaimer_items:[{{id:'global'}}]}},'image');
process.stdout.write(JSON.stringify({{target:state.labelEditor.target,
 context:state.labelEditor.context,profile:state.labelEditor.safeFrameProfile,
 token:state.labelEditor.labelToken}}));
"""
        done = subprocess.run(["node", "-e", script], cwd=ROOT, check=True,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(done.stdout), {
            "target": "yt_vstrip", "context": {"live": False, "hole_side": "right"},
            "profile": "profile-A", "token": "token-A",
        })

    def test_07_refine_locks_editor_until_response(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        refine = source[source.index("async function handleRefine"):source.index("function undoRefine")]
        self.assertIn("state.refineInFlight = true", refine)
        self.assertIn("state.refineInFlight = false", refine)
        start = source.index("function beginFreeLabelDrag")
        end = source.index("function changeFreeLabelKind", start)
        script = f"""
let toast=''; const state={{refineInFlight:true,labelEditor:{{items:[{{position:{{x:.5,y:.5}}}}]}}}};
const showToast=x=>(toast=x); const window={{matchMedia:()=>({{matches:false}})}};
{source[start:end]}
beginFreeLabelDrag({{pointerType:'mouse'}},0,{{}},{{}});
process.stdout.write(toast);
"""
        done = subprocess.run(["node", "-e", script], cwd=ROOT, check=True,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertIn("暫時鎖定", done.stdout)

    def test_15_refine_locks_before_fetch_and_unlocks_on_400_and_network_error(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        api_start = source.index("function _apiError")
        api_error = source[api_start:source.index("\n}", api_start) + 2]
        refine = source[source.index("async function handleRefine"):source.index("function undoRefine")]
        script = f"""
const elements = {{
 refineInput: {{value:'修改標題'}}, replacementPerson: {{value:'', focus:()=>{{}}}},
 refineBtn: {{disabled:false}}, refineBtnText: {{innerText:''}},
 refineLoading: {{classList:{{add:()=>{{}},remove:()=>{{}}}}}},
}};
const document={{getElementById:id=>elements[id] || {{}}}};
const state={{refineSource:{{base64:'source',mimeType:'image/webp'}},
 refineDisplay:{{label_token:'token'}}, refineParameters:{{provider:'gemini',aspect_ratio:'16:9',
 image_size:'1K',density:'normal',safe_frame:true,safe_frame_profile:'編輯',frame_strategy:''}},
 refineStack:[],refineInFlight:false,editorFormat:'cg',tenCoverMode:'ai',ytCoverTitleMode:'ai'}};
let renders=[]; let toasts=[]; let rejectFetch;
const renderFreeLabelEditor=()=>renders.push(state.refineInFlight);
const showToast=x=>toasts.push(x); const requestsNamedFaceReplacement=()=>false;
const clearGenerateBannerForNewRequest=()=>{{}}; const showGenerateErrorBanner=()=>{{}};
const showGenerateNoticeBanner=()=>{{}}; const editorFormat=()=>({{inputs:'normal',hole:false}});
const refineParametersFromState=()=>state.refineParameters;
const appliedDisclaimer=()=>({{kind:'ai',sourceText:'',corner:'lower_right',position:null,
 provenanceKind:'ai',manualOverride:false,target:'cg',context:{{}},items:[]}});
const REFINE_BACKEND_URL='/api/images/refine'; const _apiHeaders=()=>({{}});
const broadcastHoleForApi=()=>''; const userRefImagesPayload=()=>[];
const updateRefineControls=()=>{{elements.refineBtn.disabled=!state.refineSource}};
{api_error}
{refine}
async function runNetworkError() {{
 global.fetch=()=>new Promise((_resolve,reject)=>{{rejectFetch=reject}});
 const pending=handleRefine();
 const lockedImmediately=state.refineInFlight && renders[0] === true;
 rejectFetch(new Error('network down'));
 await pending;
 return {{lockedImmediately,unlocked:!state.refineInFlight,toast:toasts.at(-1)}};
}}
async function runCredential400() {{
 toasts=[]; renders=[];
 global.fetch=async()=>({{ok:false,status:400,json:async()=>({{detail:'標籤憑證與底圖不符'}})}});
 await handleRefine();
 return {{unlocked:!state.refineInFlight,toast:toasts.at(-1)}};
}}
runNetworkError().then(async first=>({{first,second:await runCredential400()}}))
 .then(result=>process.stdout.write(JSON.stringify(result)));
"""
        done = subprocess.run(["node", "-e", script], cwd=ROOT, check=True,
                              capture_output=True, text=True, encoding="utf-8")
        result = json.loads(done.stdout)
        self.assertEqual(result["first"], {
            "lockedImmediately": True, "unlocked": True, "toast": "network down",
        })
        self.assertEqual(result["second"], {
            "unlocked": True,
            "toast": "標籤資料已過期，請重新整理頁面或重新生成",
        })

    def test_17_frontend_restamp_refine_undo_refine_state_chain(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")

        def js_function(start_name, next_name):
            start = source.index(start_name)
            return source[start:source.index(next_name, start)]

        restamp = js_function("async function restampFreeLabels", "function buildFreeLabelPayload")
        payload = js_function("function buildFreeLabelPayload", "function onDisclaimerSourceInput")
        applied = js_function("function appliedDisclaimer", "function refineDisclaimerPayload")
        refine_source = js_function("function refineSourceFromResponse", "function appliedDisclaimer")
        refine = js_function("async function handleRefine", "function undoRefine")
        undo_start = source.index("function undoRefine")
        undo = source[undo_start:source.index("\n}", undo_start) + 2]
        script = f"""
const elements={{oneClickImage:{{src:''}},oneClickDownload:{{href:''}},
 refineInput:{{value:'第一次修改'}},replacementPerson:{{value:'',focus:()=>{{}}}},
 refineBtn:{{disabled:false}},refineBtnText:{{innerText:''}},
 refineLoading:{{classList:{{add:()=>{{}},remove:()=>{{}}}}}}}};
const document={{getElementById:id=>elements[id] || {{}}}};
const state={{labelRestampRequestId:0,refineInFlight:false,refineStack:[],
 refineSource:{{base64:'source-0',mimeType:'image/webp'}},
 refineDisplay:{{label_token:'token-0',disclaimer_items:[]}},
 refineParameters:{{provider:'gemini',aspect_ratio:'16:9',image_size:'1K',density:'normal',
 safe_frame:true,safe_frame_profile:'編輯',frame_strategy:'',model:'model-0'}},
 labelEditor:{{imageId:'oneClickImage',target:'cg',context:{{safe_frame:true}},
 safeFrameProfile:'編輯安全框',labelToken:'token-0',base64:'clean',baseMimeType:'image/webp',
 model:'model-0',safeRect:[],obstacles:[],items:[{{id:'global',side:'global',kind:'source',
 source_text:'畫面來源：美聯社',provenance_kind:'source',manual_override:false,
 position:{{x:.2,y:.2}}}}]}},editorFormat:'cg',tenCoverMode:'ai',ytCoverTitleMode:'ai'}};
const API_BASE=''; const REFINE_BACKEND_URL='/api/images/refine'; const _apiHeaders=()=>({{}});
const _apiError=(data,status)=>data.detail || `HTTP ${{status}}`;
const hideToast=()=>{{}}; const hideGenerateErrorBanner=()=>{{}}; const showGenerateNoticeBanner=()=>{{}};
const renderFreeLabelEditor=()=>{{}}; const showToast=()=>{{}}; const requestsNamedFaceReplacement=()=>false;
const clearGenerateBannerForNewRequest=()=>{{}}; const showGenerateErrorBanner=()=>{{}};
const editorFormat=()=>({{inputs:'normal',hole:false}}); const broadcastHoleForApi=()=>'';
const userRefImagesPayload=()=>[]; const updateRefineControls=()=>{{}};
const showRefinedImage=()=>{{}}; const refineParametersFromState=()=>state.refineParameters;
const showGenerateNoticeBanner2=()=>{{}};
let restampCount=0; const refineBodies=[];
const restampResponse=(token,kind,manual)=>({{ok:true,json:async()=>({{
 image_data_base64:'shown',mime_type:'image/png',model:'model-0',label_token:token,
 disclaimer_base_image_base64:'clean',disclaimer_base_mime_type:'image/webp',
 disclaimer_items:[{{...state.labelEditor.items[0],kind,
  source_text:kind==='source'?'畫面來源：美聯社':'',manual_override:manual}}],
 disclaimer_manual_override:manual,notices:[]
}})}});
global.fetch=async(url,options)=>{{
 const body=JSON.parse(options.body);
 if (url.includes('restamp-disclaimer')) {{
   restampCount += 1;
   const kind=restampCount < 3 ? 'source' : 'ai';
   return restampResponse(`token-${{restampCount}}`,kind,restampCount===3);
 }}
 refineBodies.push(body);
 const n=refineBodies.length;
 return {{ok:true,json:async()=>({{image_data_base64:`refined-${{n}}`,mime_type:'image/png',
  model:`refined-model-${{n}}`,source_image_base64:`source-${{n}}`,source_mime_type:'image/webp',
  label_token:`refined-token-${{n}}`,disclaimer_items:state.labelEditor.items,notices:[]}})}};
}};
{payload}
{restamp}
{refine_source}
{applied}
{refine}
{undo}
async function run() {{
 await restampFreeLabels();
 state.labelEditor.items[0].position={{x:.25,y:.25}};
 await restampFreeLabels();
 state.labelEditor.items[0].kind='ai'; state.labelEditor.items[0].source_text='';
 await restampFreeLabels();
 const before={{token:state.refineDisplay.label_token,source:state.refineSource.base64,
  manual:state.labelEditor.items[0].manual_override}};
 await handleRefine();
 const afterFirst={{token:state.refineDisplay.label_token,source:state.refineSource.base64,
  stack:state.refineStack.length}};
 undoRefine(); elements.refineInput.value='第二次修改';
 const afterUndo={{token:state.refineDisplay.label_token,source:state.refineSource.base64}};
 await handleRefine();
 return {{before,afterFirst,afterUndo,refineBodies}};
}}
run().then(result=>process.stdout.write(JSON.stringify(result)));
"""
        done = subprocess.run(["node", "-e", script], cwd=ROOT, check=True,
                              capture_output=True, text=True, encoding="utf-8")
        result = json.loads(done.stdout)
        self.assertEqual(result["before"], {
            "token": "token-3", "source": "source-0", "manual": True,
        })
        self.assertEqual(result["afterFirst"], {
            "token": "refined-token-1", "source": "source-1", "stack": 1,
        })
        self.assertEqual(result["afterUndo"], {"token": "token-3", "source": "source-0"})
        self.assertEqual(
            [(body["label_token"], body["source_image_base64"]) for body in result["refineBodies"]],
            [("token-3", "source-0"), ("token-3", "source-0")],
        )

    def test_09_digest_archive_pairing_is_exact(self):
        token = main._current_user.set({"user_id": "b113-user"})
        try:
            main._remember_digest(digest_id="A", news_text="article-A", visual_context="summary-A")
            main._remember_digest(digest_id="B", news_text="article-B", visual_context="summary-B")
            matched = main._enrich_archive_fields({"digest_id": "A", "news_text": "", "visual_context": "summary-A"})
            unknown = main._enrich_archive_fields({"digest_id": "missing", "news_text": "", "visual_context": "summary-X"})
        finally:
            main._current_user.reset(token)
            main._digest_memo.pop("b113-user", None)
        self.assertEqual(matched["news_text"], "article-A")
        self.assertEqual(matched["digest_match"], "matched")
        self.assertEqual(unknown["news_text"], "")
        self.assertEqual(unknown["digest_match"], "unknown")

    def test_10_visual_context_drops_only_bad_sentences(self):
        clean = "現場救援持續進行，工作人員引導居民離開危險區域，周邊道路保持暢通並等待後續安排。"
        data = {"visual_context": "路透社報導有２０人受傷。TVBS Logo出現在畫面。" + clean}
        main.downgrade_visual_context(data)
        self.assertEqual(data["visual_context"], clean)
        all_bad = {"visual_context": "新华社報導有20人受傷。TVBS Logo清楚可見。"}
        main.downgrade_visual_context(all_bad)
        self.assertEqual(all_bad["visual_context"], "")

    def test_11_worst_case_2k_response_stays_under_32_mib(self):
        size = (2560, 1440)
        final = image_b64(size, pixels=os.urandom(size[0] * size[1] * 3))
        source = image_b64(size, pixels=os.urandom(size[0] * size[1] * 3))
        response = main.ImageGenerateResponse(
            image_data_base64=final, mime_type="image/png", model="test",
            source_image_base64=source, source_mime_type="image/png",
            disclaimer_base_image_base64=final,
            disclaimer_kind="ai", disclaimer_provenance_kind="ai",
            disclaimer_items=[{"id": "global", "side": "global", "kind": "ai", "provenance_kind": "ai"}],
        )
        sealed = main._seal_label_response(
            response, target="cg", context={}, profile=safe_area_spec.EDITOR_FRAME_PROFILE,
        )
        payload_bytes = len(sealed.model_dump_json().encode("utf-8"))
        self.assertLess(payload_bytes, 32 * 1024 * 1024)

    def test_13_live_false_removes_only_live_obstacle(self):
        off = compose.free_label_obstacles("yt_vstrip", (1920, 1080), context={"live": False})
        on = compose.free_label_obstacles("yt_vstrip", (1920, 1080), context={"live": True})
        self.assertNotIn("LIVE", [item["name"] for item in off])
        self.assertIn("LIVE", [item["name"] for item in on])


if __name__ == "__main__":
    unittest.main()
