"""真人肖像規則：消化只做判定，畫法由後端依「查不查得到參考照片」決定。

背景（2026-08-01 實驗）：實測 GPT 不會拒絕生成具名真人的寫實肖像，且當時的規則
本身就寫著「允許忠實寫實肖像」。改成由後端決定後，這裡釘住三件事：
1. 舊的「允許寫實肖像」措辭不會回來
2. 送不出參考圖時，絕不能叫模型「參考附圖」
3. 任何非預期狀態一律退回「不生成臉孔」，不是放行
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
import news_prompt  # noqa: E402
import photo_lookup  # noqa: E402
from main import (  # noqa: E402
    DIGEST_OUTPUT_SCHEMA,
    GenerateResponse,
    ImageGenerateRequest,
    resolve_portrait,
    supports_reference_image,
)
from news_prompt import build_prompt  # noqa: E402

PHOTO = photo_lookup.ReferencePhoto(
    image_base64="QUJD",
    mime_type="image/jpeg",
    image_url="https://upload.wikimedia.org/x.jpg",
    source_page="https://zh.wikipedia.org/wiki/%E6%9F%90%E4%BA%BA",
    lang="zh",
)


def _prompt(portrait_mode: str) -> str:
    return build_prompt(
        role="記者",
        engine="gpt",
        type_label="情境示意圖",
        style="style",
        structure="structure",
        variable="[標題]標題",
        portrait_mode=portrait_mode,
    )


class PortraitPromptBlockTests(unittest.TestCase):
    def test_reference_mode_tells_renderer_a_photo_is_attached(self):
        prompt = _prompt("reference")
        self.assertIn("NAMED REAL PERSON — PORTRAIT TREATMENT", prompt)
        self.assertIn("reference photograph of the named real person is attached", prompt)
        self.assertIn("hand-painted editorial portrait illustration", prompt)
        self.assertNotIn("NO REFERENCE AVAILABLE", prompt)

    def test_no_reference_mode_forbids_drawing_the_face(self):
        prompt = _prompt("no_reference")
        self.assertIn("NAMED REAL PERSON — NO REFERENCE AVAILABLE", prompt)
        self.assertIn("MUST NOT draw their face", prompt)
        # 沒有照片時絕不能出現「參考附圖」的指示，否則模型只能憑印象捏臉
        self.assertNotIn("is attached to this request", prompt)

    def test_none_mode_injects_no_portrait_block(self):
        prompt = _prompt("none")
        self.assertNotIn("NAMED REAL PERSON —", prompt)

    def test_unknown_mode_falls_back_to_no_block(self):
        """打錯字或未來新增的模式不能靜靜放行成寫實肖像。"""
        prompt = _prompt("definitely-not-a-mode")
        self.assertNotIn("NAMED REAL PERSON —", prompt)

    def test_default_rule_still_forbids_faces_without_a_block(self):
        prompt = _prompt("none")
        self.assertIn("do NOT draw a recognisable face for a named real person", prompt)

    def test_old_permissive_wording_is_gone(self):
        """釘住舊措辭不會被改回來——它正是寫實假臉的來源。"""
        self.assertNotIn("a faithful portrait is allowed", news_prompt.REAL_WORLD_RENDERING_RULES)
        self.assertNotIn("portraits are allowed", main.REAL_WORLD_FIDELITY_RULES)


class PortraitDigestContractTests(unittest.TestCase):
    def test_schema_requires_portrait_subject(self):
        self.assertIn("portrait_subject", DIGEST_OUTPUT_SCHEMA["properties"])
        self.assertIn("portrait_subject", DIGEST_OUTPUT_SCHEMA["required"])

    def test_response_defaults_to_no_portrait(self):
        self.assertEqual(GenerateResponse(style="s", structure="t", variable="v").portrait_subject, "")

    def test_digest_rule_hands_the_treatment_to_the_backend(self):
        rules = main.REAL_WORLD_FIDELITY_RULES
        self.assertIn("portrait_subject", rules)
        self.assertIn("you do NOT decide how the face is drawn", rules)


class ResolvePortraitTests(unittest.TestCase):
    def test_no_subject_means_no_portrait_handling(self):
        self.assertEqual(resolve_portrait("", "gpt"), ("none", None))

    def test_found_photo_selects_reference_mode(self):
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, photo = resolve_portrait("某人", "gpt")
        self.assertEqual(mode, "reference")
        self.assertIs(photo, PHOTO)

    def test_missing_photo_falls_back_to_no_reference(self):
        with patch.object(photo_lookup, "find_reference_photo", return_value=None):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, photo = resolve_portrait("查無此人", "gpt")
        self.assertEqual((mode, photo), ("no_reference", None))

    def test_lookup_failure_does_not_break_generation(self):
        with patch.object(photo_lookup, "find_reference_photo", side_effect=OSError("boom")):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, photo = resolve_portrait("某人", "gpt")
        self.assertEqual((mode, photo), ("no_reference", None))

    def test_backend_without_reference_channel_never_claims_an_attachment(self):
        """原生 OpenAI 沒有參考圖通道，這時必須退回不畫臉，且不該白查一次圖。"""
        with patch.object(main, "supports_reference_image", return_value=False):
            with patch.object(photo_lookup, "find_reference_photo") as lookup:
                mode, photo = resolve_portrait("某人", "gpt")
        self.assertEqual((mode, photo), ("no_reference", None))
        lookup.assert_not_called()


class SupportsReferenceImageTests(unittest.TestCase):
    def test_openrouter_backend_supports_both_providers(self):
        with patch.dict(
            os.environ, {"IMAGE_BACKEND": "openrouter", "OPENROUTER_API_KEY": "k"}, clear=False
        ):
            self.assertTrue(supports_reference_image("gpt"))
            self.assertTrue(supports_reference_image("gemini"))

    def test_native_openai_has_no_reference_channel(self):
        with patch.dict(
            os.environ, {"IMAGE_BACKEND": "native", "OPENROUTER_API_KEY": ""}, clear=False
        ):
            self.assertFalse(supports_reference_image("gpt"))
            self.assertTrue(supports_reference_image("gemini"))


class ReferenceImagePayloadTests(unittest.TestCase):
    def _payload(self, data_url: str) -> dict:
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"data": [{"b64_json": "QUJD", "media_type": "image/png"}]}'

        def fake_urlopen(request, **kwargs):
            captured.update(__import__("json").loads(request.data.decode("utf-8")))
            return FakeResponse()

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}, clear=False):
            with patch.object(main, "urlopen", fake_urlopen):
                main.generate_via_openrouter(
                    "openai/gpt-image-2",
                    ImageGenerateRequest(prompt="p", reference_image_data_url=data_url),
                )
        return captured

    def test_reference_photo_is_sent_as_input_references(self):
        payload = self._payload("data:image/jpeg;base64,QUJD")
        self.assertEqual(
            payload["input_references"],
            [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}],
        )

    def test_no_reference_means_no_input_references_key(self):
        self.assertNotIn("input_references", self._payload(""))


class PhotoLookupTests(unittest.TestCase):
    API_RESPONSE = (
        b'{"query": {"pages": [{"title": "\\u67d0\\u4eba", '
        b'"thumbnail": {"source": "https://upload.wikimedia.org/x.jpg"}}]}}'
    )

    def test_returns_photo_with_traceable_source(self):
        with patch.object(photo_lookup, "_get", side_effect=[self.API_RESPONSE, b"binary"]):
            photo = photo_lookup.find_reference_photo("某人")
        self.assertIsNotNone(photo)
        self.assertEqual(photo.mime_type, "image/jpeg")
        self.assertTrue(photo.source_page.startswith("https://zh.wikipedia.org/wiki/"))
        self.assertTrue(photo.data_url().startswith("data:image/jpeg;base64,"))

    def test_missing_page_returns_none(self):
        missing = b'{"query": {"pages": [{"title": "x", "missing": true}]}}'
        with patch.object(photo_lookup, "_get", return_value=missing):
            self.assertIsNone(photo_lookup.find_reference_photo("查無此人"))

    def test_page_without_image_returns_none(self):
        no_image = b'{"query": {"pages": [{"title": "x"}]}}'
        with patch.object(photo_lookup, "_get", return_value=no_image):
            self.assertIsNone(photo_lookup.find_reference_photo("沒照片的人"))

    def test_oversized_photo_is_rejected(self):
        huge = b"x" * (photo_lookup.MAX_PHOTO_BYTES + 1)
        with patch.object(photo_lookup, "_get", side_effect=[self.API_RESPONSE, huge]):
            self.assertIsNone(photo_lookup.find_reference_photo("某人", langs=("zh",)))

    def test_blank_name_never_calls_the_api(self):
        with patch.object(photo_lookup, "_get") as get:
            self.assertIsNone(photo_lookup.find_reference_photo("   "))
        get.assert_not_called()

    def test_network_failure_returns_none(self):
        with patch.object(photo_lookup, "_get", return_value=None):
            self.assertIsNone(photo_lookup.find_reference_photo("某人"))


if __name__ == "__main__":
    unittest.main()
