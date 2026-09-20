"""上傳圖片全站統一成一個模組，並新增用途「AI改圖」（2026-09-13 使用者裁決）。

使用者原話：「十點不一樣／YT整點直播 上傳圖片現在只有放置，要跟其他地方的上傳圖片
功能對齊。可以上傳多張。可以選擇原圖放置(預設) 或新增的選項 AI改圖。全站所有上傳圖片
功能都要統一(模組化?)。上傳後的選單列表順序：原圖放置(預設)／AI改圖／實景參考／
肖像照片／地圖底稿」。

三處裁決（見 docs/plan-20260913-上傳圖片模組化.md）：
  1. AI改圖＝以這張圖為底重繪（同一個畫面，換成版型的畫風），不是拿去參考畫別的
  2. AI改圖的成品**要**標「AI示意圖」——畫面是 AI 重繪的，不是使用者提供的真實素材
  3. AI改圖**不**強制程式壓字：強制的理由是「真照重畫會走樣」，重畫本來就是它的目的
"""
import base64
import io
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
import news_prompt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT.joinpath("app.js").read_text(encoding="utf-8")
INDEX_HTML = ROOT.joinpath("index.html").read_text(encoding="utf-8")

client = TestClient(main.app)


def headers() -> dict:
    # 整包跑時其他測試模組會在 import 期改寫 NEWS_IMAGE_API_KEY，執行時再讀才對得上
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}



def _png(size=(1536, 864), colour=(30, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url(colour=(30, 30, 30)) -> str:
    return "data:image/png;base64," + base64.b64encode(_png(colour=colour)).decode("ascii")


def _ref(purpose: str, colour=(30, 30, 30)) -> dict:
    return {"data_url": _data_url(colour), "purpose": purpose}


class VocabularyParityTests(unittest.TestCase):
    """editor_formats.REF_PURPOSE_ORDER 是唯一真相源，app.js 抄一份。"""

    def _app_js_purposes(self):
        block = re.search(r"const REF_PURPOSES = \[(.*?)\];", APP_JS, re.S)
        self.assertIsNotNone(block, "app.js 的 REF_PURPOSES 不再是有序陣列了")
        return re.findall(r"\['([a-z]+)', '([^']+)'\]", block.group(1))

    def test_the_order_and_labels_match_the_backend(self):
        self.assertEqual(self._app_js_purposes(), editor_formats.REF_PURPOSE_ORDER)

    def test_the_order_is_the_one_the_user_asked_for(self):
        """順序是規格的一部分（使用者逐字指定），不是實作細節。"""
        self.assertEqual(
            editor_formats.REF_PURPOSE_ORDER,
            [
                ("asis", "原圖放置"),
                ("aiedit", "AI改圖"),
                ("scene", "實景參考"),
                ("portrait", "肖像照片"),
                ("map", "地圖底稿"),
            ],
        )

    def test_the_default_is_place_as_is_on_both_sides(self):
        """2026-09-13 由 scene 改成 asis。連帶影響見 plan 文件。"""
        self.assertEqual(editor_formats.REF_PURPOSE_DEFAULT, "asis")
        self.assertIn("const REF_PURPOSE_DEFAULT = 'asis';", APP_JS)

    def test_every_purpose_has_a_backend_rules_block(self):
        """下拉選得到、後端卻沒有對應措辭＝使用者選了等於沒選。"""
        for key, label in editor_formats.REF_PURPOSE_ORDER:
            with self.subTest(purpose=key, label=label):
                self.assertIn(key, news_prompt.USER_REFERENCE_MODES)
                self.assertTrue(news_prompt.USER_REFERENCE_MODES[key].strip())

    def test_the_pydantic_literal_accepts_exactly_these_keys(self):
        for key, _ in editor_formats.REF_PURPOSE_ORDER:
            with self.subTest(purpose=key):
                self.assertEqual(
                    main.UserReferenceImage(data_url="data:image/png;base64,AA", purpose=key).purpose,
                    key,
                )
        with self.assertRaises(Exception):
            main.UserReferenceImage(data_url="data:image/png;base64,AA", purpose="nope")


class FrontendModuleTests(unittest.TestCase):
    """三份逐字重複的實作收成一份——重複本身就是這次要修的東西。"""

    def test_all_three_upload_entry_points_go_through_the_shared_reader(self):
        for fn in ("handleRefFilesSelected", "handleCoverAsisSelected", "handleYtAsisSelected"):
            body = re.search(rf"async function {fn}\(.*?\n\}}", APP_JS, re.S)
            self.assertIsNotNone(body, f"{fn} 不見了")
            self.assertIn("addImageFilesTo", body.group(0), f"{fn} 沒走共用讀檔")

    def test_all_three_lists_are_drawn_by_the_shared_renderer(self):
        for fn in ("renderRefUploads", "renderCoverAsis", "renderYtAsis"):
            body = re.search(rf"function {fn}\(\) \{{.*?\n\}}", APP_JS, re.S)
            self.assertIsNotNone(body, f"{fn} 不見了")
            self.assertIn("renderRefList", body.group(0), f"{fn} 沒走共用 render")

    def test_the_old_per_slot_single_image_previews_are_gone(self):
        """舊的單張預覽（coverAsisLeftImg 等）留著會跟清單並存，變成兩個真相。"""
        for stale in ("coverAsisLeftImg", "coverAsisRightImg", "ytAsisLeftImg", "ytAsisRightImg"):
            with self.subTest(id=stale):
                self.assertNotIn(stale, INDEX_HTML)
                self.assertNotIn(stale, APP_JS)

    def test_every_slot_input_accepts_more_than_one_file(self):
        """使用者要的第一件事就是「可以上傳多張」——少一個 multiple 就少一格能放。"""
        for input_id in ("refFileInput", "coverAsisLeftInput", "coverAsisRightInput",
                         "ytAsisLeftInput", "ytAsisRightInput"):
            with self.subTest(id=input_id):
                tag = re.search(rf'<input id="{input_id}"[^>]*>', INDEX_HTML)
                self.assertIsNotNone(tag, f"{input_id} 不見了")
                self.assertIn("multiple", tag.group(0))

    def test_each_slot_has_a_list_container_for_the_shared_renderer(self):
        for list_id in ("refUploadList", "coverAsisLeftList", "coverAsisRightList",
                        "ytAsisLeftList", "ytAsisRightList"):
            with self.subTest(id=list_id):
                self.assertIn(f'id="{list_id}"', INDEX_HTML)


class SlotReadingTests(unittest.TestCase):
    """一格＝一份清單：第一張 asis 是版位圖，其餘是那一格的生圖參考。"""

    def test_the_legacy_single_data_url_still_reads_as_one_as_is_image(self):
        """舊呼叫端（LINE、既有測試）送的是單一 data URL 字串，一字不用改。"""
        refs = main.slot_reference_list([], "data:image/png;base64,AAA")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].purpose, "asis")

    def test_the_new_list_field_wins_over_the_legacy_string(self):
        refs = main.slot_reference_list(
            [main.UserReferenceImage(data_url="data:image/png;base64,NEW", purpose="aiedit")],
            "data:image/png;base64,OLD",
        )
        self.assertEqual([r.purpose for r in refs], ["aiedit"])

    def test_the_placement_image_is_the_first_as_is_in_the_slot(self):
        refs = [
            main.UserReferenceImage(data_url="data:image/png;base64,SCENE", purpose="scene"),
            main.UserReferenceImage(data_url="data:image/png;base64,FIRST", purpose="asis"),
            main.UserReferenceImage(data_url="data:image/png;base64,SECOND", purpose="asis"),
        ]
        self.assertEqual(main.slot_placement_url(refs), "data:image/png;base64,FIRST")

    def test_a_slot_with_no_as_is_has_no_placement_image(self):
        """只放了 AI改圖／參考的格子＝那格照樣生底圖，不是「有附圖」。"""
        refs = [main.UserReferenceImage(data_url="data:image/png;base64,A", purpose="aiedit")]
        self.assertEqual(main.slot_placement_url(refs), "")

    def test_everything_that_is_not_as_is_becomes_that_slots_reference(self):
        refs = [
            main.UserReferenceImage(data_url="data:image/png;base64,A", purpose="asis"),
            main.UserReferenceImage(data_url="data:image/png;base64,B", purpose="aiedit"),
            main.UserReferenceImage(data_url="data:image/png;base64,C", purpose="portrait"),
        ]
        self.assertEqual([r.purpose for r in main.slot_generation_refs(refs)], ["aiedit", "portrait"])


class AiEditPromptTests(unittest.TestCase):
    def test_the_rules_say_redraw_this_same_picture(self):
        """裁決 1：與 scene 的差別就在這句。少了它，模型會畫成另一個畫面。"""
        block = news_prompt.USER_REFERENCE_AIEDIT_RULES
        self.assertIn("REDRAW THIS SAME PICTURE", block)
        self.assertIn("NOT a loose style reference", block)

    def test_aiedit_rules_preserve_existing_text_and_control_new_text(self):
        block = news_prompt.USER_REFERENCE_AIEDIT_RULES.lower()
        for term in ("preserve-existing", "do-not-invent", "explicit-removal"):
            with self.subTest(term=term):
                self.assertIn(term, block)
        self.assertIn("text already present in the attached reference image is requested content", block)

    def test_fusion_rules_preserve_existing_text_and_block_cross_image_reuse(self):
        block = news_prompt.USER_REFERENCE_AIEDIT_FUSION_RULES_TEMPLATE.lower()
        for term in ("preserve-existing", "do-not-invent", "explicit-removal"):
            with self.subTest(term=term):
                self.assertIn(term, block)
        self.assertIn("from one attached image onto an object from another attached image", block)

    def test_asis_and_scene_reference_contracts_remain_separate(self):
        self.assertIn("may remain exactly as supplied", news_prompt.USER_REFERENCE_ASIS_RULES)
        self.assertIn("Do not copy readable text or brand marks", news_prompt.USER_REFERENCE_SCENE_RULES)

    def test_an_ai_edit_image_keeps_the_ai_disclaimer_label(self):
        """裁決 2：畫面是 AI 重繪的，「有使用者上傳就不標示意圖」那條豁免不適用。"""
        req = main.ImageGenerateRequest(
            prompt="BASE",
            reference_images=[main.UserReferenceImage(data_url=_data_url(), purpose="aiedit")],
        )
        with patch.object(main, "supports_multiple_reference_images", return_value=True):
            out = main.apply_user_references_to_image_request(req)
        self.assertIn(news_prompt.USER_REFERENCE_AIEDIT_RULES, out.prompt)
        self.assertNotIn(news_prompt.USER_REFERENCE_NO_DISCLAIMER_RULES, out.prompt)

    def test_a_scene_reference_still_drops_the_label(self):
        """回歸：2026-08-17 的裁決沒有被這次改動掃到。"""
        req = main.ImageGenerateRequest(
            prompt="BASE",
            reference_images=[main.UserReferenceImage(data_url=_data_url(), purpose="scene")],
        )
        with patch.object(main, "supports_multiple_reference_images", return_value=True):
            out = main.apply_user_references_to_image_request(req)
        self.assertIn(news_prompt.USER_REFERENCE_NO_DISCLAIMER_RULES, out.prompt)

    def test_named_portrait_subjects_keep_the_ai_disclaimer_label(self):
        """B28：畫真人＋掛真名時，有附圖也不能洗掉 AI示意圖。"""
        req = main.ImageGenerateRequest(
            prompt="BASE",
            reference_images=[main.UserReferenceImage(data_url=_data_url(), purpose="scene")],
            portrait_subjects=["吳軒彤"],
        )
        with patch.object(main, "supports_multiple_reference_images", return_value=True):
            out = main.apply_user_references_to_image_request(req)
        self.assertNotIn(news_prompt.USER_REFERENCE_NO_DISCLAIMER_RULES, out.prompt)

    def test_blank_portrait_subjects_still_drop_the_label(self):
        req = main.ImageGenerateRequest(
            prompt="BASE",
            reference_images=[main.UserReferenceImage(data_url=_data_url(), purpose="scene")],
            portrait_subjects=["  ", ""],
        )
        with patch.object(main, "supports_multiple_reference_images", return_value=True):
            out = main.apply_user_references_to_image_request(req)
        self.assertIn(news_prompt.USER_REFERENCE_NO_DISCLAIMER_RULES, out.prompt)

    def test_one_ai_edit_among_others_is_enough_to_keep_the_label(self):
        """一張成品只有一個標籤：有任何一塊是 AI 重繪的就得標。"""
        req = main.ImageGenerateRequest(
            prompt="BASE",
            reference_images=[
                main.UserReferenceImage(data_url=_data_url(), purpose="scene"),
                main.UserReferenceImage(data_url=_data_url(), purpose="aiedit"),
            ],
        )
        with patch.object(main, "supports_multiple_reference_images", return_value=True):
            out = main.apply_user_references_to_image_request(req)
        self.assertNotIn(news_prompt.USER_REFERENCE_NO_DISCLAIMER_RULES, out.prompt)


class TenCoverSlotEndpointTests(unittest.TestCase):
    def _post(self, payload, panel_returns=None):
        base = {
            "title_left": "勞保撥補 上看1300億",
            "date_text": "2026/09/14",
            "mode": "composite",
        }
        base.update(payload)
        with patch.object(main, "_cover_panel_image",
                          return_value=(_png((1080, 1080)), "fake-model")) as panel, \
             patch.object(main, "resolve_cover_visuals",
                          return_value=("左邊畫面", "右邊畫面")), \
             patch.object(main, "_cover_full_image",
                          return_value=(_png((1920, 1080)), "fake-model")) as full:
            res = client.post("/api/editor/cover", json=base, headers=headers())
        self.assertEqual(res.status_code, 200, res.text)
        return res.json(), panel, full

    def test_an_ai_edit_only_slot_still_generates_that_panel(self):
        """裁決 3：AI改圖 不是版位圖，那一格照舊生底圖。"""
        data, _, full = self._post({"slot_left": [_ref("aiedit")]})
        self.assertTrue(data["left_is_ai"])
        self.assertEqual(full.call_count, 1)

    def test_the_ai_edit_image_actually_reaches_the_model_for_that_panel(self):
        """放了卻沒送進去，就是 2026-08-23 那兩次「附圖被忽略」事故的形狀。"""
        _, _, full = self._post({"slot_left": [_ref("aiedit")]})
        refs = full.call_args.args[2]
        self.assertEqual([r.purpose for r in refs], ["aiedit"])

    def test_an_as_is_slot_still_places_the_photo_in_composite(self):
        """回歸：合成版的一標一附圖行為一字不變（2026-09-13 起 ai＋原圖改走 AI 疊底圖，
        見 test_ai_title_over_base_20260913，這裡明送 composite）。"""
        data, panel, full = self._post(
            {"title_right": "病理醫師 月薪65萬仍缺工", "mode": "composite",
             "slot_left": [_ref("asis", (200, 30, 30))]}
        )
        self.assertEqual(data["mode"], "composite")
        self.assertFalse(data["left_is_ai"])
        self.assertTrue(data["right_is_ai"])

    def test_the_legacy_asis_left_string_behaves_exactly_as_before(self):
        data, _, _ = self._post(
            {"title_right": "病理醫師 月薪65萬仍缺工", "mode": "composite", "asis_left": _data_url((200, 30, 30))}
        )
        self.assertEqual(data["mode"], "composite")
        self.assertFalse(data["left_is_ai"])

    def test_the_default_all_ai_mode_also_sends_the_slot_image(self):
        """整張 AI 版是十點的**預設**模式。漏掉這條，使用者在格子裡選了 AI改圖
        卻一張都沒送進模型——2026-08-23 那兩次「附圖被忽略」就是這個形狀。"""
        # 2026-09-13 起雙切 ai＋附圖位＝兩段生圖：第一段那一格 1:1、第二段整張 16:9，
        # 假生圖要依比例回圖，不然比例驗證會把 1:1 那格擋掉
        def fake_raw(req):
            size = (1024, 1024) if req.aspect_ratio == "1:1" else (1920, 1080)
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png(size)).decode("ascii"),
                mime_type="image/png", model="fake-model",
            )
        with patch.object(main, "generate_image_raw", side_effect=fake_raw) as raw,              patch.object(main, "supports_multiple_reference_images", return_value=True),              patch.object(main, "resolve_cover_visuals", return_value=("左邊畫面", "右邊畫面")):
            res = client.post("/api/editor/cover", json={
                "title_left": "勞保撥補 上看1300億",
                "title_right": "病理醫師 月薪65萬仍缺工",
                "date_text": "2026/09/14", "mode": "ai", "title_creativity": 1,
                "slot_left": [_ref("aiedit")],
            }, headers=headers())
        self.assertEqual(res.status_code, 200, res.text)
        # 第一段：左格自己的 AI改圖 進了那一格的 1:1 生圖
        panel_req = raw.call_args_list[0].args[0]
        self.assertEqual(panel_req.aspect_ratio, "1:1")
        self.assertIn("aiedit", [r.purpose for r in panel_req.reference_images])
        image_req = raw.call_args.args[0]
        self.assertIn("aiedit", [r.purpose for r in image_req.reference_images])
        # 附上去還不夠：沒有這段措辭，模型會把它當成鬆散的風格參考去畫別的畫面
        self.assertIn(news_prompt.USER_REFERENCE_AIEDIT_RULES, image_req.prompt)

    def test_each_panel_only_gets_its_own_slots_references(self):
        """左格放的 AI改圖 不該跑去影響右格——那正是附圖位存在的理由。"""
        _, panel, _ = self._post({
            "title_right": "病理醫師 月薪65萬仍缺工",
            "slot_left": [_ref("aiedit")],
            "slot_right": [_ref("scene")],
        })
        by_side = {call.args[0]: call.args[2] for call in panel.call_args_list}
        self.assertEqual([r.purpose for r in by_side["左邊畫面"]], ["aiedit"])
        self.assertEqual([r.purpose for r in by_side["右邊畫面"]], ["scene"])


class YtCoverSlotEndpointTests(unittest.TestCase):
    def _post(self, payload):
        fake = main.ImageGenerateResponse(
            image_data_base64=base64.b64encode(_png()).decode("ascii"),
            mime_type="image/png", model="fake-model",
        )
        # 2026-09-14 起創意 0 一律程式壓字，這組要驗 AI 標題路徑所以帶 1
        base = {"layout": "hourly", "date_text": "2026/09/14", "title_mode": "ai", "creativity": 1}
        base.update(payload)
        with patch.object(main, "generate_image_raw", return_value=fake) as raw, \
             patch.object(main, "derive_yt_cover_plan",
                          return_value={"visual": "一個場景", "portrait_subjects": []}), \
             patch.object(compose, "compose_yt_hourly_cover",
                          wraps=compose.compose_yt_hourly_cover) as hourly:
            res = client.post("/api/editor/yt-cover", json=base, headers=headers())
        self.assertEqual(res.status_code, 200, res.text)
        return res.json(), raw, hourly

    def test_a_single_item_slot_with_only_an_ai_edit_does_not_blow_up(self):
        """清單化前這裡是 next(... if s)，沒有版位圖時會直接 StopIteration。"""
        data, raw, hourly = self._post({
            "title": "挪威國王哈拉德辭世 開放公眾瞻仰遺容",
            "slot_left": [_ref("aiedit")],
        })
        self.assertEqual(raw.call_count, 1)
        self.assertEqual([r.purpose for r in raw.call_args.args[0].reference_images], ["aiedit"])

    def test_an_ai_edit_slot_leaves_the_title_on_the_creativity_ladder(self):
        """裁決 3：只有原圖放置才強制程式壓字。"""
        data, _, _ = self._post({
            "title": "挪威國王哈拉德辭世 開放公眾瞻仰遺容",
            "slot_left": [_ref("aiedit")],
        })
        self.assertEqual(data["title_mode"], "ai")

    def test_an_as_is_slot_with_ai_title_draws_over_the_photo(self):
        """2026-09-13 使用者裁決：原圖放置＋AI 標題不再強制壓字，原圖當唯一附圖送模型畫字。

        provider=gemini（2026-09-20 修法甲後）：這裡的 fake `raw` 固定回不透明 PNG，
        provider=gpt 時剛好 1 張原圖放置會改走透明底圖層（見
        tests/test_b55_transparent_title_layer.py），對這張不透明假圖會被 (a) 擋下。
        這支測的是請求組裝（reference_images purpose），不是 B55 的像素保證，改用
        gemini 沿用差異遮罩那條路，跟這支原本要測的東西一致。
        """
        data, raw, _ = self._post({
            "title": "挪威國王哈拉德辭世 開放公眾瞻仰遺容",
            "provider": "gemini",
            "slot_left": [_ref("asis")],
        })
        self.assertEqual(data["title_mode"], "ai")
        self.assertEqual(raw.call_count, 1)
        self.assertEqual([r.purpose for r in raw.call_args.args[0].reference_images], ["aiedit"])

    def test_the_legacy_asis_left_string_also_draws_over_the_photo(self):
        # provider=gemini：同上一支的理由，這裡測的是舊版 asis_left 字串欄位的相容
        # 組裝邏輯，不是 B55 的像素保證。
        data, raw, _ = self._post({
            "title": "挪威國王哈拉德辭世 開放公眾瞻仰遺容",
            "provider": "gemini",
            "asis_left": _data_url(),
        })
        self.assertEqual(data["title_mode"], "ai")
        self.assertEqual(raw.call_count, 1)

    def test_dual_keeps_each_slots_extra_references_in_its_own_panel(self):
        left, right = main.yt_dual_panel_requests(main.YtCoverRequest(
            layout="hourly", title="第一則標題文字", title_second="第二則標題文字",
            slot_left=[main.UserReferenceImage(data_url=_data_url(), purpose="aiedit")],
            slot_right=[main.UserReferenceImage(data_url=_data_url(), purpose="asis")],
        ))
        self.assertEqual([r.purpose for r in left.reference_images], ["aiedit"])
        self.assertEqual([r.purpose for r in right.reference_images], ["asis"])
        # 拆完的單格請求不能再自認為「有附圖位」——那是拆格前才有的身分
        for panel in (left, right):
            self.assertFalse(panel.uses_asis_slots())


class AiEditInstructionTests(unittest.TestCase):
    """裁決 4（2026-09-13）：「AI改圖 如果使用者在給 AI 指令欄寫需求 會吃到嗎? 應該要吃到」。

    權限＝可以改內容。在此之前指令欄只送給推導畫面描述的文字模型，實拍證明那條路
    在 AI改圖 下會被 REDRAW 區塊整個蓋掉（推導寫「工人正在架設遮陽棚」，成品是照片
    原本那群站在已搭好棚下的遊客），所以改成直接送進生圖 prompt。
    """

    INSTRUCTION = "把天空改成入夜後的深藍色"

    def _apply(self, purposes, instruction):
        req = main.ImageGenerateRequest(
            prompt="BASE",
            reference_images=[
                main.UserReferenceImage(data_url=_data_url(), purpose=p) for p in purposes
            ],
            editor_instruction=instruction,
        )
        with patch.object(main, "supports_multiple_reference_images", return_value=True):
            return main.apply_user_references_to_image_request(req)

    def test_the_instruction_reaches_the_image_model(self):
        out = self._apply(["aiedit"], self.INSTRUCTION)
        self.assertIn(self.INSTRUCTION, out.prompt)

    def test_it_sits_after_the_redraw_block_so_the_model_knows_what_it_governs(self):
        out = self._apply(["aiedit"], self.INSTRUCTION)
        self.assertLess(
            out.prompt.index(news_prompt.USER_REFERENCE_AIEDIT_RULES),
            out.prompt.index(self.INSTRUCTION),
        )

    def test_an_empty_instruction_injects_nothing(self):
        out = self._apply(["aiedit"], "   ")
        self.assertNotIn("THE EDITOR'S INSTRUCTION FOR THIS REDRAW", out.prompt)

    def test_other_purposes_do_not_get_it(self):
        """scene／portrait／map 的指令欄早就由文字模型消化進畫面描述了，再下一次是重複下令。"""
        for purpose in ("scene", "portrait", "map", "asis"):
            with self.subTest(purpose=purpose):
                out = self._apply([purpose], self.INSTRUCTION)
                self.assertNotIn("THE EDITOR'S INSTRUCTION FOR THIS REDRAW", out.prompt)

    def test_the_same_content_clause_no_longer_contradicts_it(self):
        """repo 慣例：矛盾條款要移除，不是在後面疊一段 override。"""
        rules = news_prompt.USER_REFERENCE_AIEDIT_RULES
        self.assertNotIn("It is the treatment that changes, never the content.", rules)
        self.assertIn("Apart from whatever an editor's instruction below asks you to change", rules)

    def test_the_instruction_is_framed_as_a_change_not_as_words_to_draw(self):
        """不講清楚的話，「改成夜晚」會被模型當字幕畫上去。"""
        block = news_prompt.USER_REFERENCE_AIEDIT_INSTRUCTION_TEMPLATE
        self.assertIn("never words to render", block)
        self.assertIn("leave everything it does not mention", block)

    def test_it_does_not_relax_the_face_and_brand_rules(self):
        self.assertIn(
            "does not relax the brand-mark, human-face or NAMED REAL PERSON rules",
            news_prompt.USER_REFERENCE_AIEDIT_INSTRUCTION_TEMPLATE,
        )


class AiEditInstructionWiringTests(unittest.TestCase):
    """每一條會跑到 AI改圖 的生圖路徑都要把指令欄接上，漏一條就等於那個版型沒這功能。"""

    INSTRUCTION = "把背景換成暴雨"

    def _capture(self, url, payload):
        def fake(req):
            # 合成版的兩格底圖是 1:1，滿版／整張 AI 是 16:9——回錯比例會被
            # verify_output_aspect_ratio 擋成 502，就測不到指令欄那件事了
            size = (1080, 1080) if req.aspect_ratio == "1:1" else (1920, 1080)
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png(size)).decode("ascii"),
                mime_type="image/png", model="fake-model",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake) as raw,              patch.object(main, "supports_multiple_reference_images", return_value=True),              patch.object(main, "resolve_cover_visuals", return_value=("左邊畫面", "右邊畫面")),              patch.object(main, "derive_yt_cover_plan", return_value={}):
            res = client.post(url, json=payload, headers=headers())
        self.assertEqual(res.status_code, 200, res.text)
        return [call.args[0] for call in raw.call_args_list]

    def test_ten_cover_all_ai_mode(self):
        """十點的預設模式。"""
        reqs = self._capture("/api/editor/cover", {
            "title_left": "勞保撥補 上看1300億",
            "date_text": "2026/09/14", "mode": "ai", "title_creativity": 1,
            "instruction": self.INSTRUCTION,
            "slot_left": [_ref("aiedit")],
        })
        self.assertTrue(any(self.INSTRUCTION in r.prompt for r in reqs))

    def test_ten_cover_composite_full(self):
        reqs = self._capture("/api/editor/cover", {
            "title_left": "勞保撥補 上看1300億",
            "date_text": "2026/09/14", "mode": "composite",
            "instruction": self.INSTRUCTION,
            "slot_left": [_ref("aiedit")],
        })
        self.assertTrue(any(self.INSTRUCTION in r.prompt for r in reqs))

    def test_ten_cover_composite_split_only_the_slot_that_has_it(self):
        """左格放 AI改圖、右格沒有：右格那張 prompt 不該出現這條指令。"""
        reqs = self._capture("/api/editor/cover", {
            "title_left": "勞保撥補 上看1300億",
            "title_right": "病理醫師 月薪65萬仍缺工",
            "date_text": "2026/09/14", "mode": "composite",
            "instruction": self.INSTRUCTION,
            "slot_left": [_ref("aiedit")],
        })
        hit = [self.INSTRUCTION in r.prompt for r in reqs]
        self.assertEqual(hit.count(True), 1, "只有放了 AI改圖 的那一格該吃到")

    def test_the_cg_page_sends_it_too(self):
        """全站統一後 CG 的共用上傳區也有 AI改圖，前端要一起送。"""
        self.assertIn("editor_instruction: currentUserInstruction()", APP_JS)


if __name__ == "__main__":
    unittest.main()
