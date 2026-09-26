# -*- coding: utf-8 -*-
"""B107（2026-09-26 使用者裁決）：封面 AI 標籤只看圖片素材來源。

AI 標題／創意度不再讓全 asis 原圖封面自動標「AI示意圖」；缺圖生背景、aiedit
與 refine 仍標。十點雙切分側判定，YT 四版型維持任一 AI 素材就標整張。
"""

import base64
import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "b107-test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "b107-internal-key")

import compose  # noqa: E402
import main  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
CLIENT = TestClient(main.app)


def _headers() -> dict:
    # 整包跑時其他測試模組會在 import 期改寫 NEWS_IMAGE_API_KEY，執行時再讀才對得上。
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}


def _png(size=(1600, 900), colour=(230, 230, 230)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url(colour=(230, 230, 230)) -> str:
    return "data:image/png;base64," + base64.b64encode(_png(colour=colour)).decode("ascii")


def _ref(purpose="asis", colour=(230, 230, 230)) -> dict:
    return {"data_url": _data_url(colour), "purpose": purpose}


def _fake_image(req):
    size = (1024, 1024) if req.aspect_ratio == "1:1" else (1536, 864)
    return main.ImageGenerateResponse(
        image_data_base64=base64.b64encode(_png(size=size)).decode("ascii"),
        mime_type="image/png",
        model="b107-fake-model",
    )


class OriginalMaterialsWithAiTitleTests(unittest.TestCase):
    """B107：六版型全原圖，即使 AI 標題開啟也不標 AI。"""

    def _post_ten(self, layout):
        body = {
            "title_left": "第一則新聞標題", "layout": layout,
            "mode": "ai", "title_creativity": 1, "provider": "gemini",
            "slot_left": [_ref("asis", (210, 40, 40))],
        }
        if layout == "split":
            body.update({
                "title_right": "第二則新聞標題",
                "slot_right": [_ref("asis", (40, 40, 210))],
            })
        with patch.object(main, "generate_image_raw", side_effect=_fake_image), \
             patch.object(compose, "restore_photo_outside_title_band", side_effect=lambda base, ai, **kw: ai), \
             patch.object(compose, "_draw_cover_ai_note") as note:
            response = CLIENT.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), note

    def _post_yt(self, layout):
        body = {
            "title": "第一則新聞 標題內容", "layout": layout,
            "title_mode": "ai", "creativity": 1, "provider": "gemini",
            "slot_left": [_ref("asis", (210, 40, 40))],
        }
        if layout == "hourly":
            body.update({
                "title_second": "第二則新聞標題內容",
                "slot_right": [_ref("asis", (40, 40, 210))],
            })
        with patch.object(main, "generate_image_raw", side_effect=_fake_image), \
             patch.object(main, "derive_yt_cover_plan", return_value={"visual": "本地假場景", "portrait_subjects": []}), \
             patch.object(compose, "restore_yt_cover_photo", side_effect=lambda base, ai, **kw: ai), \
             patch.object(compose, "_draw_ai_note") as note, \
             patch.object(compose, "_draw_live24_ai_note") as live_note:
            response = CLIENT.post("/api/editor/yt-cover", json=body, headers=_headers())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), note, live_note

    def test_six_layouts_with_all_originals_and_ai_title_do_not_label_ai(self):
        """B107（2026-09-26 使用者裁決）：AI 標題不改變全 asis 的標籤判定。"""
        for layout in ("full", "split"):
            with self.subTest(family="ten", layout=layout):
                data, note = self._post_ten(layout)
                self.assertFalse(data["left_is_ai"])
                self.assertFalse(data["right_is_ai"])
                note.assert_not_called()
        for layout in ("news", "hourly", "live24", "hot"):
            with self.subTest(family="yt", layout=layout):
                data, note, live_note = self._post_yt(layout)
                self.assertFalse(data["background_is_ai"])
                note.assert_not_called()
                live_note.assert_not_called()


class CompositeOriginalTests(unittest.TestCase):
    """B107：全原圖 composite 不標 AI，也完全不呼叫模型。"""

    def test_all_original_composite_skips_models_for_all_six_layouts(self):
        """B107（2026-09-26 使用者裁決）：原圖＋程式排字維持零模型、零 AI 標籤。"""
        cases = [
            ("ten", "full"), ("ten", "split"),
            ("yt", "news"), ("yt", "hourly"), ("yt", "live24"), ("yt", "hot"),
        ]
        for family, layout in cases:
            with self.subTest(family=family, layout=layout), \
                 patch.object(main, "generate_image_raw", side_effect=AssertionError("全原圖 composite 不得呼叫生圖模型")), \
                 patch.object(main, "segment_titles_for_breaks", return_value={}), \
                 patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("全原圖 composite 不得呼叫文字模型")), \
                 patch.object(main, "resolve_cover_visuals", side_effect=AssertionError("全原圖 composite 不得呼叫文字模型")):
                if family == "ten":
                    body = {
                        "title_left": "第一則新聞標題", "layout": layout, "mode": "composite",
                        "slot_left": [_ref("asis", (210, 40, 40))],
                    }
                    if layout == "split":
                        body.update({"title_right": "第二則新聞標題", "slot_right": [_ref("asis", (40, 40, 210))]})
                    response = CLIENT.post("/api/editor/cover", json=body, headers=_headers())
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertFalse(response.json()["left_is_ai"])
                    self.assertFalse(response.json()["right_is_ai"])
                else:
                    body = {
                        "title": "第一則新聞 標題內容", "layout": layout, "title_mode": "composite",
                        "slot_left": [_ref("asis", (210, 40, 40))],
                    }
                    if layout == "hourly":
                        body.update({"title_second": "第二則新聞標題內容", "slot_right": [_ref("asis", (40, 40, 210))]})
                    response = CLIENT.post("/api/editor/yt-cover", json=body, headers=_headers())
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertFalse(response.json()["background_is_ai"])


class AiMaterialAndRefineTests(unittest.TestCase):
    """B107：缺圖、aiedit、分側 AI 與 refine 都保留 AI 標籤。"""

    def test_missing_image_generated_background_is_labelled(self):
        """B107（2026-09-26 使用者裁決）：沒有 asis、實際生背景時仍標 AI。"""
        body = {"title_left": "缺圖生成背景", "layout": "full", "mode": "composite"}
        with patch.object(main, "_cover_full_image", return_value=(_png(), "b107-fake-model")), \
             patch.object(main, "resolve_cover_visuals", return_value=("本地假場景", "本地假場景")):
            response = CLIENT.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["left_is_ai"])

    def test_aiedit_material_is_labelled(self):
        """B107（2026-09-26 使用者裁決）：aiedit 仍是 AI 修改，不得套原圖豁免。"""
        body = {
            "title": "AI 改圖仍須 標示意圖", "layout": "hot",
            "title_mode": "ai", "creativity": 1,
            "slot_left": [_ref("aiedit")],
        }
        with patch.object(main, "generate_image_raw", side_effect=_fake_image), \
             patch.object(main, "derive_yt_cover_plan", return_value={"visual": "本地假場景", "portrait_subjects": []}):
            response = CLIENT.post("/api/editor/yt-cover", json=body, headers=_headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["background_is_ai"])

    def test_ten_split_labels_only_the_ai_generated_side(self):
        """B107（2026-09-26 使用者裁決）：十點雙切原圖側不標、缺圖生成側照舊標。"""
        body = {
            "title_left": "左側使用原圖", "title_right": "右側缺圖生成",
            "layout": "split", "mode": "ai", "title_creativity": 1,
            "slot_left": [_ref("asis")],
        }
        with patch.object(main, "generate_image_raw", side_effect=_fake_image), \
             patch.object(main, "resolve_cover_visuals", return_value=("左場景", "右場景")), \
             patch.object(compose, "_draw_cover_ai_note") as note:
            response = CLIENT.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertFalse(data["left_is_ai"])
        self.assertTrue(data["right_is_ai"])
        self.assertEqual([call.kwargs["align_right"] for call in note.call_args_list], [True])

    def test_refined_ten_and_yt_covers_are_labelled_ai(self):
        """B107（2026-09-26 使用者裁決）：refine 是 AI 修改，重貼固定元素時必須標 AI。"""
        encoded = base64.b64encode(_png(size=(1536, 864))).decode("ascii")
        with patch.object(main, "apply_title_break_hints"):
            ten = CLIENT.post("/api/editor/cover", json={
                "title_left": "refine 後重貼", "layout": "full", "mode": "ai",
                "background_image_base64": encoded,
            }, headers=_headers())
        self.assertEqual(ten.status_code, 200, ten.text)
        self.assertTrue(ten.json()["left_is_ai"])

        with patch.object(main, "apply_title_break_hints"), patch.object(
            main, "resolve_yt_cover_plan",
            return_value=main.YtCoverPlan(("refine 後", "重貼固定元素"), "", [], []),
        ):
            yt = CLIENT.post("/api/editor/yt-cover", json={
                "title": "refine 後 重貼固定元素", "layout": "news", "title_mode": "composite",
                "background_image_base64": encoded, "background_is_ai": True,
            }, headers=_headers())
        self.assertEqual(yt.status_code, 200, yt.text)
        self.assertTrue(yt.json()["background_is_ai"])

        self.assertIn("recomposeYtCover(data, true)", APP_JS)


class YtFormatSwitchResetTests(unittest.TestCase):
    def test_switching_to_a_yt_cover_resets_state_before_ui_sync(self):
        """B107（2026-09-26 使用者裁決）：切 YT 版型重設拉桿／勾選框並由既有 render 同步 UI。"""
        body = APP_JS[APP_JS.index("function setEditorFormat(key) {"):]
        body = body[:body.index("\n}\n")]
        reset = body.index("state.ytCreativity = 0;")
        self.assertIn("if ((EDITOR_FORMATS[next] || {}).inputs === 'yt_cover')", body)
        self.assertGreater(body.index("state.ytAiTitle = false;"), reset)
        self.assertGreater(body.index("applyEditorFormatInputs();"), reset)


if __name__ == "__main__":
    unittest.main()
