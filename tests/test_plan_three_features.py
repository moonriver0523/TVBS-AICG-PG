"""PLAN.md 三項功能的守門測試（全程 mock 生圖，不打任何付費 API）。

③ 追加指令改圖（/api/images/refine）：
   - refine 送出的參考圖必須是「置框前」原圖（失真疊加是本項目最大的坑）
   - refine 不得呼叫消化端
   - 置框後回傳 source_image_base64＝置框前原圖，連續多輪尺寸不變
① 指令拆欄（user_instruction）：
   - 沒填時消化指令逐字元不變（記者 frozen 測試的前提）
   - 有填時注入專用區塊，且措辭涵蓋「兩邊都有」與 VERBATIM 觸發
② 使用者上傳參考圖（reference_images）：
   - generate_via_openrouter 依「肖像照在前、上傳圖在後」組多張 input_references
   - 依 purpose 注入用途區塊；沒上傳時請求物件原樣不動（回歸保證）
   - 送不出參考圖的後端（原生 OpenAI）直接 400，不靜靜忽略
"""

import base64
import io
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
import news_prompt  # noqa: E402
import safe_area_spec  # noqa: E402
from PIL import Image  # noqa: E402


def png_base64(width: int, height: int, colour=(200, 30, 30)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# 編輯版生成尺寸（16:9）與置框後的對位框內緣尺寸（PLAN.md 現況速查）
EDITOR_RAW = png_base64(1536, 864)
# PROFILES 是 (x, y, w, h)；編輯置框成品＝對位框內緣 1748×924（無畫布、無留白）
EDITOR_FRAMED_SIZE = safe_area_spec.PROFILES["編輯"][2:4]


def fake_raw_response(image_base64: str) -> main.ImageGenerateResponse:
    return main.ImageGenerateResponse(
        image_data_base64=image_base64, mime_type="image/png", model="fake-model"
    )


class RefineEndpointTests(unittest.TestCase):
    """③ 追加指令改圖。"""

    def refine_request(self, **overrides):
        payload = dict(
            source_image_base64=EDITOR_RAW,
            instruction="把標題改成紅色",
            provider="gpt",
            aspect_ratio="16:9",
            safe_frame=True,
            safe_frame_profile="編輯",
        )
        payload.update(overrides)
        return main.ImageRefineRequest(**payload)

    def test_refine_sends_pre_frame_image_as_reference(self):
        with patch.object(
            main, "generate_image_raw", return_value=fake_raw_response(EDITOR_RAW)
        ) as mock_raw:
            main.refine_image(self.refine_request())
        sent = mock_raw.call_args[0][0]
        self.assertEqual(
            sent.reference_image_data_url,
            f"data:image/png;base64,{EDITOR_RAW}",
            "refine 必須把置框前原圖當參考圖送出",
        )

    def test_refine_prompt_contains_rules_and_instruction(self):
        with patch.object(
            main, "generate_image_raw", return_value=fake_raw_response(EDITOR_RAW)
        ) as mock_raw:
            main.refine_image(self.refine_request())
        prompt = mock_raw.call_args[0][0].prompt
        self.assertIn("IMAGE REFINE RULES", prompt)
        self.assertIn("USER CHANGE REQUEST", prompt)
        self.assertIn("把標題改成紅色", prompt)

    def test_refine_never_calls_digest(self):
        with (
            patch.object(
                main, "generate_image_raw", return_value=fake_raw_response(EDITOR_RAW)
            ),
            patch.object(main, "generate") as mock_digest,
            patch.object(main, "digest_completion") as mock_completion,
        ):
            main.refine_image(self.refine_request())
        mock_digest.assert_not_called()
        mock_completion.assert_not_called()

    def test_three_rounds_keep_size_and_match_direct_stretch(self):
        """連續 3 輪 refine：成品尺寸不變，且與「原圖直接置框」逐像素相符。

        證明沒有二次拉伸：每輪都拿 source_image_base64（置框前）繼續改，
        成品永遠等於 apply_safe_frame(原圖) 一次的結果。
        """
        import safe_frame

        expected = safe_frame.apply_safe_frame(
            base64.b64decode(EDITOR_RAW), profile="編輯"
        )
        source = EDITOR_RAW
        for round_number in range(3):
            with patch.object(
                main, "generate_image_raw", return_value=fake_raw_response(EDITOR_RAW)
            ) as mock_raw:
                result = main.refine_image(
                    self.refine_request(source_image_base64=source)
                )
            # 下一輪一律用新的置框前原圖，成品只拿來顯示
            self.assertEqual(result.source_image_base64, EDITOR_RAW)
            sent = mock_raw.call_args[0][0]
            self.assertNotIn(
                result.image_data_base64,
                sent.reference_image_data_url,
                f"第 {round_number + 1} 輪把置框後成品餵回去了（會失真疊加）",
            )
            with Image.open(
                io.BytesIO(base64.b64decode(result.image_data_base64))
            ) as image:
                self.assertEqual(image.size, EDITOR_FRAMED_SIZE)
            self.assertEqual(
                base64.b64decode(result.image_data_base64),
                expected,
                "成品必須與原圖直接置框逐位元相符（無二次拉伸）",
            )
            source = result.source_image_base64

    def test_source_mime_type_reports_raw_mime(self):
        """置框前原圖的實際 MIME 要回給前端；模型回 jpeg 時不能被硬當成 png。"""
        raw = main.ImageGenerateResponse(
            image_data_base64=EDITOR_RAW, mime_type="image/jpeg", model="fake-model"
        )
        with patch.object(main, "generate_image_raw", return_value=raw):
            result = main.refine_image(self.refine_request())
        self.assertEqual(result.source_mime_type, "image/jpeg")

    def test_reporter_profile_refine_fits_into_official_canvas(self):
        """記者 profile：21:9 原圖 FIT 進 1920×1080 畫布（與編輯的拉伸是兩條路）。"""
        reporter_raw = png_base64(1792, 768)
        with patch.object(
            main, "generate_image_raw", return_value=fake_raw_response(reporter_raw)
        ):
            result = main.refine_image(
                self.refine_request(
                    source_image_base64=reporter_raw,
                    aspect_ratio="21:9",
                    safe_frame_profile="記者",
                )
            )
        self.assertEqual(result.source_image_base64, reporter_raw)
        with Image.open(
            io.BytesIO(base64.b64decode(result.image_data_base64))
        ) as image:
            self.assertEqual(image.size, (1920, 1080))

    def test_no_safe_frame_returns_empty_source(self):
        with patch.object(
            main, "generate_image_raw", return_value=fake_raw_response(EDITOR_RAW)
        ):
            result = main.refine_image(self.refine_request(safe_frame=False))
        self.assertEqual(result.source_image_base64, "")
        self.assertEqual(result.image_data_base64, EDITOR_RAW)


class GenerateImageSourceFieldTests(unittest.TestCase):
    """③ 前置：/api/images/generate 置框時要回傳置框前原圖。"""

    def test_safe_frame_response_carries_pre_frame_source(self):
        req = main.ImageGenerateRequest(
            prompt="P", provider="gpt", aspect_ratio="16:9",
            safe_frame=True, safe_frame_profile="編輯",
        )
        with patch.object(
            main, "generate_image_raw", return_value=fake_raw_response(EDITOR_RAW)
        ):
            result = main.generate_image(req)
        self.assertEqual(result.source_image_base64, EDITOR_RAW)
        self.assertNotEqual(result.image_data_base64, EDITOR_RAW)

    def test_unframed_response_has_empty_source(self):
        req = main.ImageGenerateRequest(prompt="P", aspect_ratio="16:9")
        with patch.object(
            main, "generate_image_raw", return_value=fake_raw_response(EDITOR_RAW)
        ):
            result = main.generate_image(req)
        self.assertEqual(result.source_image_base64, "")


class UserInstructionFieldTests(unittest.TestCase):
    """① 指令拆欄。"""

    KWARGS = dict(role="記者", density="standard", type_label="資料圖表")

    def test_empty_field_leaves_instructions_byte_identical(self):
        self.assertEqual(
            main.build_digest_instructions(**self.KWARGS),
            main.build_digest_instructions(**self.KWARGS, user_instruction=""),
        )
        self.assertEqual(
            main.build_digest_instructions(**self.KWARGS),
            main.build_digest_instructions(**self.KWARGS, user_instruction="   "),
        )

    def test_filled_field_appends_dedicated_block_with_instruction(self):
        instructions = main.build_digest_instructions(
            **self.KWARGS, user_instruction="用手繪風"
        )
        self.assertIn("DEDICATED USER INSTRUCTION", instructions)
        self.assertIn("<<USER INSTRUCTION START>>\n用手繪風\n<<USER INSTRUCTION END>>", instructions)
        # 專用區塊必須排在文內解析規則之後（它引用 the block above）
        self.assertLess(
            instructions.index("USER INSTRUCTIONS INSIDE THE MATERIAL"),
            instructions.index("DEDICATED USER INSTRUCTION"),
        )

    def test_block_wording_covers_both_channels_and_verbatim(self):
        instructions = main.build_digest_instructions(
            **self.KWARGS, user_instruction="逐字保留"
        )
        block = instructions[instructions.index("DEDICATED USER INSTRUCTION"):]
        self.assertIn("obey both", block, "兩邊都有時不得互相取消")
        self.assertIn("VERBATIM MODE", block, "欄位寫逐字保留要能觸發逐字模式")
        self.assertIn("NEVER news content", block)

    def test_news_image_request_forwards_user_instruction(self):
        digest = main.GenerateResponse(
            style="S", structure="T", variable="[標題] X", chart_type="資料圖表"
        )
        image = fake_raw_response(EDITOR_RAW)
        with (
            patch.object(main, "generate", return_value=digest) as mock_generate,
            patch.object(main, "generate_image", return_value=image),
        ):
            main.generate_news_image(
                main.NewsImageGenerateRequest(
                    news_text="熊本強震重創九州 當地疏散逾21萬人 多處道路中斷",
                    user_instruction="不要科技藍",
                )
            )
        self.assertEqual(
            mock_generate.call_args[0][0].user_instruction, "不要科技藍"
        )


class FakeUrlopenResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class UserReferenceImageTests(unittest.TestCase):
    """② 使用者上傳參考圖。"""

    MAP_REF = main.UserReferenceImage(data_url="data:image/png;base64,TUFQ", purpose="map")
    SCENE_REF = main.UserReferenceImage(
        data_url="data:image/jpeg;base64,U0NFTkU=", purpose="scene"
    )

    def openrouter_request(self, **overrides):
        payload = dict(prompt="P", provider="gpt", aspect_ratio="16:9")
        payload.update(overrides)
        return main.ImageGenerateRequest(**payload)

    def sent_payload(self, req) -> dict:
        captured = {}

        def fake_urlopen(request, **kwargs):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeUrlopenResponse(
                {"data": [{"b64_json": EDITOR_RAW, "media_type": "image/png"}]}
            )

        with patch.object(main, "urlopen", side_effect=fake_urlopen):
            main.generate_via_openrouter("openai/gpt-image-2", req)
        return captured["payload"]

    def test_portrait_first_then_user_references(self):
        payload = self.sent_payload(
            self.openrouter_request(
                reference_image_data_url="data:image/jpeg;base64,RkFDRQ==",
                reference_images=[self.MAP_REF, self.SCENE_REF],
            )
        )
        urls = [item["image_url"]["url"] for item in payload["input_references"]]
        self.assertEqual(
            urls,
            [
                "data:image/jpeg;base64,RkFDRQ==",
                "data:image/png;base64,TUFQ",
                "data:image/jpeg;base64,U0NFTkU=",
            ],
            "順序必須是肖像照在前、使用者上傳在後",
        )

    def test_no_references_sends_no_input_references(self):
        payload = self.sent_payload(self.openrouter_request())
        self.assertNotIn("input_references", payload)

    def test_too_many_references_rejected_at_request_layer(self):
        """上限在 request 層就擋（pydantic max_length），任何後端路徑都收不進超量。"""
        from pydantic import ValidationError

        refs = [self.SCENE_REF] * (main.MAX_INPUT_REFERENCES + 1)
        with self.assertRaises(ValidationError):
            self.openrouter_request(reference_images=refs)

    def test_purpose_blocks_injected_once_per_purpose(self):
        req = self.openrouter_request(
            reference_images=[self.MAP_REF, self.SCENE_REF, self.SCENE_REF]
        )
        updated = main.apply_user_references_to_image_request(req)
        self.assertIn("ATTACHED MAP REFERENCE", updated.prompt)
        self.assertIn("ATTACHED SCENE REFERENCE", updated.prompt)
        self.assertEqual(updated.prompt.count("ATTACHED SCENE REFERENCE"), 1)

    def test_no_uploads_leaves_request_untouched(self):
        req = self.openrouter_request()
        self.assertIs(main.apply_user_references_to_image_request(req), req)

    def test_backend_without_reference_channel_rejects_uploads(self):
        req = self.openrouter_request(reference_images=[self.MAP_REF])
        with patch.dict(os.environ, {"IMAGE_BACKEND": "native"}):
            with self.assertRaises(main.HTTPException) as ctx:
                main.apply_user_references_to_image_request(req)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_native_gemini_also_rejects_uploads(self):
        """native-gemini 送得出單張肖像照，但送不出 reference_images 陣列。
        不擋下來的話上傳圖被靜默丟掉、prompt 卻寫著「依附圖」——比不附更糟。"""
        req = self.openrouter_request(provider="gemini", reference_images=[self.MAP_REF])
        with patch.dict(os.environ, {"IMAGE_BACKEND": "native"}):
            with self.assertRaises(main.HTTPException) as ctx:
                main.apply_user_references_to_image_request(req)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_scene_rules_do_not_relax_portrait_iron_rule(self):
        """上傳圖措辭不得繞過「不畫具名真人臉孔」鐵律：實景區塊明文禁抄臉。"""
        self.assertIn(
            "Do not copy any recognisable human face",
            news_prompt.USER_REFERENCE_SCENE_RULES,
        )


class UserPortraitUploadTests(unittest.TestCase):
    """使用者上傳肖像照（2026-08-17 使用者裁決開放）。

    鐵律的解除範圍必須精準：只有**使用者親自上傳肖像照**這一條通道解除
    「兩位以上具名真人不畫臉」，自動查圖路徑原樣維持；且措辭仍要求
    沒附照片的人不畫臉。
    """

    PORTRAIT_REF = main.UserReferenceImage(
        data_url="data:image/jpeg;base64,RkFDRQ==", purpose="portrait"
    )

    def request(self, **overrides):
        payload = dict(prompt="P", provider="gpt", aspect_ratio="16:9")
        payload.update(overrides)
        return main.ImageGenerateRequest(**payload)

    def test_portrait_upload_skips_auto_lookup_and_no_face_block(self):
        """有上傳肖像照：不查照片、不注入兩套 PORTRAIT_MODES 區塊。"""
        req = self.request(
            portrait_subjects=["鄭明典", "吳軒彤"],
            reference_images=[self.PORTRAIT_REF],
        )
        with patch.object(main.photo_lookup, "find_reference_photo") as mock_lookup:
            result = main.apply_portrait_to_image_request(req)
        mock_lookup.assert_not_called()
        self.assertNotIn("NO REFERENCE AVAILABLE", result.prompt)
        self.assertNotIn("PORTRAIT TREATMENT", result.prompt)

    def test_portrait_upload_injects_user_portrait_block(self):
        req = self.request(reference_images=[self.PORTRAIT_REF])
        result = main.apply_user_references_to_image_request(req)
        self.assertIn("USER-SUPPLIED PORTRAIT REFERENCE", result.prompt)
        # REAL_WORLD_RENDERING_RULES 的預設條款認「NAMED REAL PERSON」區塊標題
        self.assertIn("NAMED REAL PERSON", result.prompt)

    def test_iron_rule_intact_without_portrait_upload(self):
        """沒上傳肖像照：兩位以上具名真人照舊不畫臉。"""
        req = self.request(portrait_subjects=["鄭明典", "吳軒彤"])
        result = main.apply_portrait_to_image_request(req)
        self.assertIn("NO REFERENCE AVAILABLE", result.prompt)

    def test_scene_upload_does_not_lift_iron_rule(self):
        """非肖像用途的上傳不解除鐵律。"""
        req = self.request(
            portrait_subjects=["鄭明典", "吳軒彤"],
            reference_images=[
                main.UserReferenceImage(
                    data_url="data:image/png;base64,U0NFTkU=", purpose="scene"
                )
            ],
        )
        result = main.apply_portrait_to_image_request(req)
        self.assertIn("NO REFERENCE AVAILABLE", result.prompt)

    def test_wording_keeps_faceless_rule_for_uncovered_persons(self):
        """措辭仍要求：只有附了照片的人可以畫臉，沒附的維持背影／剪影。"""
        rules = news_prompt.USER_REFERENCE_PORTRAIT_RULES
        self.assertIn("ONLY for a person whose photograph is attached", rules)
        self.assertIn("WITHOUT an attached photograph", rules)


if __name__ == "__main__":
    unittest.main()
