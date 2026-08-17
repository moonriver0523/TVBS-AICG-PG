"""真人肖像規則：消化只做判定，畫法由後端依「查不查得到參考照片」決定。

背景（2026-08-01 實驗）：實測 GPT 不會拒絕生成具名真人的寫實肖像，且當時的規則
本身就寫著「允許忠實寫實肖像」。改成由後端決定後，這裡釘住三件事：
1. 舊的「允許寫實肖像」措辭不會回來
2. 送不出參考圖時，絕不能叫模型「參考附圖」
3. 任何非預期狀態一律退回「不生成臉孔」，不是放行
"""

import json
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
    apply_portrait_to_image_request,
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
        self.assertIn("NAMED REAL PEOPLE — NO REFERENCE AVAILABLE", prompt)
        self.assertIn("MUST NOT draw the face of ANY named real person", prompt)
        # 沒有照片時絕不能出現「參考附圖」的指示，否則模型只能憑印象捏臉
        self.assertNotIn("is attached to this request", prompt)

    def test_no_reference_block_covers_multi_person_layouts(self):
        """2026-08-05 事故：兩格肖像只附一張照片，沒照片那格被編出來還掛真名。"""
        prompt = _prompt("no_reference")
        self.assertIn("two or more portraits side by side", prompt)
        self.assertIn("never beside an invented face", prompt)

    def test_none_mode_injects_no_portrait_block(self):
        prompt = _prompt("none")
        self.assertNotIn("NAMED REAL PERSON —", prompt)
        self.assertNotIn("NAMED REAL PEOPLE —", prompt)

    def test_unknown_mode_falls_back_to_no_block(self):
        """打錯字或未來新增的模式不能靜靜放行成寫實肖像。"""
        prompt = _prompt("definitely-not-a-mode")
        self.assertNotIn("NAMED REAL PERSON —", prompt)
        self.assertNotIn("NAMED REAL PEOPLE —", prompt)

    def test_default_rule_still_forbids_faces_without_a_block(self):
        prompt = _prompt("none")
        self.assertIn("do NOT draw a recognisable face for a named real person", prompt)

    def test_old_permissive_wording_is_gone(self):
        """釘住舊措辭不會被改回來——它正是寫實假臉的來源。"""
        self.assertNotIn("a faithful portrait is allowed", news_prompt.REAL_WORLD_RENDERING_RULES)
        self.assertNotIn("portraits are allowed", main.REAL_WORLD_FIDELITY_RULES)


class PortraitDigestContractTests(unittest.TestCase):
    def test_schema_requires_portrait_subjects(self):
        self.assertIn("portrait_subjects", DIGEST_OUTPUT_SCHEMA["properties"])
        self.assertIn("portrait_subjects", DIGEST_OUTPUT_SCHEMA["required"])

    def test_schema_field_is_a_list_so_two_people_both_fit(self):
        """單一字串裝不下第二個人，那正是 2026-08-05 事故的起點。"""
        field = DIGEST_OUTPUT_SCHEMA["properties"]["portrait_subjects"]
        self.assertEqual(field["type"], "array")
        self.assertEqual(field["items"]["type"], "string")

    def test_response_defaults_to_no_portrait(self):
        self.assertEqual(
            GenerateResponse(style="s", structure="t", variable="v").portrait_subjects, []
        )

    def test_digest_rule_hands_the_treatment_to_the_backend(self):
        rules = main.REAL_WORLD_FIDELITY_RULES
        self.assertIn("portrait_subjects", rules)
        self.assertIn("you do NOT decide how the face is drawn", rules)

    def test_digest_rule_demands_every_person_be_listed(self):
        self.assertIn("EVERY specific named real person", main.REAL_WORLD_FIDELITY_RULES)
        self.assertIn("listing only the first is a defect", main.REAL_WORLD_FIDELITY_RULES)


class ResolvePortraitTests(unittest.TestCase):
    def test_no_subject_means_no_portrait_handling(self):
        self.assertEqual(resolve_portrait([], "gpt"), ("none", None))

    def test_found_photo_selects_reference_mode(self):
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, photo = resolve_portrait(["某人"], "gpt")
        self.assertEqual(mode, "reference")
        self.assertIs(photo, PHOTO)

    def test_missing_photo_falls_back_to_no_reference(self):
        with patch.object(photo_lookup, "find_reference_photo", return_value=None):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, photo = resolve_portrait(["查無此人"], "gpt")
        self.assertEqual((mode, photo), ("no_reference", None))

    def test_lookup_failure_does_not_break_generation(self):
        with patch.object(photo_lookup, "find_reference_photo", side_effect=OSError("boom")):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, photo = resolve_portrait(["某人"], "gpt")
        self.assertEqual((mode, photo), ("no_reference", None))

    def test_backend_without_reference_channel_never_claims_an_attachment(self):
        """原生 OpenAI 沒有參考圖通道，這時必須退回不畫臉，且不該白查一次圖。"""
        with patch.object(main, "supports_reference_image", return_value=False):
            with patch.object(photo_lookup, "find_reference_photo") as lookup:
                mode, photo = resolve_portrait(["某人"], "gpt")
        self.assertEqual((mode, photo), ("no_reference", None))
        lookup.assert_not_called()

    def test_two_people_never_draw_faces(self):
        """2026-08-05 事故：一張照片配兩個肖像框，模型把沒照片的那格編出來還掛真名。

        參考圖通道一次只對應得了一個人，所以兩人以上一律退回不畫臉，
        而且不該白查照片——查到了也不能用。
        """
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO) as lookup:
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, photo = resolve_portrait(["鄭明典", "吳軒彤"], "gpt")
        self.assertEqual((mode, photo), ("no_reference", None))
        lookup.assert_not_called()

    def test_three_people_also_blocked(self):
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, _ = resolve_portrait(["甲", "乙", "丙"], "gpt")
        self.assertEqual(mode, "no_reference")

    def test_duplicate_name_is_still_one_person(self):
        """同一個人被列兩次不該被誤判成多人——清洗過的名單才進判斷。"""
        subjects = main.clean_portrait_subjects(["某人", "某人 ", "某人"])
        self.assertEqual(subjects, ["某人"])
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, _ = resolve_portrait(subjects, "gpt")
        self.assertEqual(mode, "reference")


class CleanPortraitSubjectsTests(unittest.TestCase):
    """消化端偶爾回 null／回字串／混進空值，這些都不該讓後面的判斷歪掉。"""

    def test_none_and_bad_types_become_empty(self):
        self.assertEqual(main.clean_portrait_subjects(None), [])
        self.assertEqual(main.clean_portrait_subjects(123), [])
        self.assertEqual(main.clean_portrait_subjects([None, 5, ""]), [])

    def test_bare_string_is_treated_as_one_name(self):
        self.assertEqual(main.clean_portrait_subjects("某人"), ["某人"])

    def test_whitespace_is_trimmed_and_order_kept(self):
        self.assertEqual(main.clean_portrait_subjects([" 甲 ", "乙"]), ["甲", "乙"])


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
    """查圖：條目首圖優先、Wikidata 只當身分閘門與備援（2026-08-18 改）。

    `_get` 的呼叫順序就是這條流程的規格：
    1. wikipedia query（一次要齊 thumbnail 與 wikibase_item）
    2. wbgetclaims P31（驗是不是人）
    3.（首圖缺才有）wbgetclaims P18
    4. 下載圖片
    """

    @staticmethod
    def _page(*, qid="Q1", thumbnail=True, missing=False) -> bytes:
        page: dict = {"title": "某人"}
        if missing:
            page["missing"] = True
        if qid:
            page["pageprops"] = {"wikibase_item": qid}
        if thumbnail:
            page["thumbnail"] = {"source": "https://upload.wikimedia.org/x.jpg"}
        return json.dumps({"query": {"pages": [page]}}).encode("utf-8")

    @staticmethod
    def _claim(prop: str, value) -> bytes:
        return json.dumps(
            {"claims": {prop: [{"mainsnak": {"datavalue": {"value": value}}}]}}
        ).encode("utf-8")

    def test_returns_photo_with_traceable_source(self):
        calls = [self._page(), self._claim("P31", {"id": "Q5"}), b"binary"]
        with patch.object(photo_lookup, "_get", side_effect=calls):
            photo = photo_lookup.find_reference_photo("某人")
        self.assertIsNotNone(photo)
        self.assertEqual(photo.mime_type, "image/jpeg")
        self.assertTrue(photo.source_page.startswith("https://zh.wikipedia.org/wiki/"))
        self.assertTrue(photo.data_url().startswith("data:image/jpeg;base64,"))

    def test_non_human_entity_is_rejected(self):
        """「馬斯克」在 Wikidata 的同名實體之一是「姓氏」，那不是人，不能當肖像。"""
        calls = [self._page(), self._claim("P31", {"id": "Q101352"})]
        with patch.object(photo_lookup, "_get", side_effect=calls):
            self.assertIsNone(photo_lookup.find_reference_photo("某姓氏", langs=("zh",)))

    def test_page_without_wikidata_entity_is_rejected(self):
        """沒有對應實體＝身分無從驗證，寧可不畫臉。"""
        with patch.object(photo_lookup, "_get", side_effect=[self._page(qid=None)]):
            self.assertIsNone(photo_lookup.find_reference_photo("無實體", langs=("zh",)))

    def test_falls_back_to_p18_when_article_has_no_lead_image(self):
        calls = [
            self._page(thumbnail=False),
            self._claim("P31", {"id": "Q5"}),
            self._claim("P18", "Some Person.jpg"),
            b"binary",
        ]
        with patch.object(photo_lookup, "_get", side_effect=calls) as get:
            photo = photo_lookup.find_reference_photo("沒首圖的人", langs=("zh",))
        self.assertIsNotNone(photo)
        # 出處改標實體頁——圖是從那裡來的，回查才對得上
        self.assertEqual(photo.source_page, "https://www.wikidata.org/wiki/Q1")
        self.assertIn("Special:FilePath/Some%20Person.jpg", get.call_args_list[-1][0][0])

    def test_human_without_any_image_returns_none(self):
        calls = [
            self._page(thumbnail=False),
            self._claim("P31", {"id": "Q5"}),
            json.dumps({"claims": {}}).encode("utf-8"),
        ]
        with patch.object(photo_lookup, "_get", side_effect=calls):
            self.assertIsNone(
                photo_lookup.find_reference_photo("沒照片的人", langs=("zh",))
            )

    def test_missing_page_returns_none(self):
        with patch.object(photo_lookup, "_get", side_effect=[self._page(missing=True)]):
            self.assertIsNone(photo_lookup.find_reference_photo("查無此人", langs=("zh",)))

    def test_oversized_photo_is_rejected(self):
        huge = b"x" * (photo_lookup.MAX_PHOTO_BYTES + 1)
        calls = [self._page(), self._claim("P31", {"id": "Q5"}), huge]
        with patch.object(photo_lookup, "_get", side_effect=calls):
            self.assertIsNone(photo_lookup.find_reference_photo("某人", langs=("zh",)))

    def test_blank_name_never_calls_the_api(self):
        with patch.object(photo_lookup, "_get") as get:
            self.assertIsNone(photo_lookup.find_reference_photo("   "))
        get.assert_not_called()

    def test_network_failure_returns_none(self):
        with patch.object(photo_lookup, "_get", return_value=None):
            self.assertIsNone(photo_lookup.find_reference_photo("某人"))


class ApplyPortraitToImageRequestTests(unittest.TestCase):
    """網頁版 /api/images/generate 在生圖前補上肖像規則與參考照。"""

    def test_no_subjects_leaves_request_unchanged(self):
        req = ImageGenerateRequest(prompt="hello prompt")
        self.assertIs(apply_portrait_to_image_request(req), req)

    def test_one_person_with_photo_injects_rules_and_attachment(self):
        req = ImageGenerateRequest(prompt="base prompt", portrait_subjects=["某人"], provider="gpt")
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                out = apply_portrait_to_image_request(req)
        self.assertIn("NAMED REAL PERSON — PORTRAIT TREATMENT", out.prompt)
        self.assertTrue(out.reference_image_data_url.startswith("data:image/jpeg;base64,"))

    def test_two_people_forbid_faces_and_attach_nothing(self):
        req = ImageGenerateRequest(
            prompt="base prompt", portrait_subjects=["鄭明典", "吳軒彤"], provider="gpt"
        )
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                out = apply_portrait_to_image_request(req)
        self.assertIn("NO REFERENCE AVAILABLE", out.prompt)
        self.assertEqual(out.reference_image_data_url, "")

    def test_existing_block_is_not_duplicated(self):
        already = "base\n\n" + news_prompt.PORTRAIT_WITH_REFERENCE_RULES
        req = ImageGenerateRequest(
            prompt=already, portrait_subjects=["某人"], provider="gpt"
        )
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                out = apply_portrait_to_image_request(req)
        self.assertEqual(out.prompt.count("NAMED REAL PERSON — PORTRAIT TREATMENT"), 1)


if __name__ == "__main__":
    unittest.main()
