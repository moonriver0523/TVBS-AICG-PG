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

from fastapi import HTTPException

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
import news_prompt  # noqa: E402
import photo_lookup  # noqa: E402
from main import (  # noqa: E402
    DIGEST_OUTPUT_SCHEMA,
    GenerateResponse,
    GenerateRequest,
    ImageGenerateRequest,
    apply_photo_availability,
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

# F40：完全查無此人（第 4 層）與確認有條目但沒照片（第 3 層）的假 outcome，
# 供不想實連網路的測試直接餵值。
NO_ENTRY_OUTCOME = photo_lookup.PortraitLookupOutcome(
    photo=None, entry_found=False, matched_name=None, language=None
)


def _entry_only_outcome(name: str) -> photo_lookup.PortraitLookupOutcome:
    return photo_lookup.PortraitLookupOutcome(
        photo=None, entry_found=True, matched_name=name, language="zh"
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
        # B66（2026-09-16）：寫實為主、只帶一點插畫筆觸，舊的「手繪插畫」措辭已換掉
        self.assertIn("realistic editorial news portrait", prompt)
        self.assertIn("light illustrative touch", prompt)
        self.assertNotIn("hand-painted editorial portrait illustration", prompt)
        self.assertNotIn("NO PERSON IN THIS SCENE", prompt)

    def test_no_reference_mode_forbids_drawing_the_face(self):
        """F40 第 4 層：連條目都查不到時改成「無人場景」，不是背影／剪影退路。"""
        prompt = _prompt("no_reference")
        self.assertIn("NAMED REAL PEOPLE — NO PERSON IN THIS SCENE", prompt)
        self.assertIn("designed WITHOUT that person as a figure at all", prompt)
        # 「畫出背影就是錯的」裁決落地：第 4 層規則本身不建議、甚至不提「背影／剪影」
        # 這類字眼當退路選項，改成一律禁止任何人形圖案，斷絕模型往那個方向想。
        self.assertNotIn("back view", news_prompt.PORTRAIT_NO_REFERENCE_RULES)
        self.assertNotIn("silhouette", news_prompt.PORTRAIT_NO_REFERENCE_RULES)
        # 沒有照片時絕不能出現「參考附圖」的指示，否則模型只能憑印象捏臉
        self.assertNotIn("is attached to this request", prompt)

    def test_no_reference_block_covers_multi_person_layouts(self):
        """2026-08-05 事故：兩格肖像只附一張照片，沒照片那格被編出來還掛真名。"""
        prompt = _prompt("no_reference")
        self.assertIn("two or more of them side by side", prompt)
        self.assertIn("no figure of any kind represents them visually", prompt)

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

    def test_names_are_extracted_verbatim_never_inferred(self):
        rules = main.REAL_WORLD_FIDELITY_RULES
        self.assertIn("copied VERBATIM", rules)
        self.assertIn("never infer a person from a job title", rules)
        self.assertIn("總統", rules)
        self.assertIn("執行長", rules)
        self.assertIn("common knowledge", rules)
        self.assertNotIn("from your own knowledge", rules)

    def test_english_name_stays_empty_when_the_source_has_none(self):
        rules = main.REAL_WORLD_FIDELITY_RULES
        self.assertIn("MUST be an empty string", rules)
        self.assertIn('portrait_subjects_en=[""]', rules)
        self.assertNotIn("otherwise from your own knowledge of the person", rules)


class ResolvePortraitTests(unittest.TestCase):
    def setUp(self):
        # 用到的人名（某人／查無此人）與其他測試檔共用同一個行程內快取，
        # 不清乾淨會讓某一輪的 mock 結果被下一輪誤判成快取命中。
        photo_lookup.clear_photo_lookup_cache()

    def test_no_subject_means_no_portrait_handling(self):
        self.assertEqual(resolve_portrait([], "gpt"), ("none", None))

    def test_found_photo_selects_reference_mode(self):
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, photo = resolve_portrait(["某人"], "gpt")
        self.assertEqual(mode, "reference")
        self.assertIs(photo, PHOTO)

    def test_missing_photo_falls_back_to_no_reference(self):
        """沒照片、也查無條目（F40 第 4 層）→ no_reference。"""
        with patch.object(photo_lookup, "find_reference_photo", return_value=None):
            with patch.object(photo_lookup, "find_portrait_outcome", return_value=NO_ENTRY_OUTCOME):
                with patch.object(main, "supports_reference_image", return_value=True):
                    mode, photo = resolve_portrait(["查無此人"], "gpt")
        self.assertEqual((mode, photo), ("no_reference", None))

    def test_lookup_failure_does_not_break_generation(self):
        with patch.object(photo_lookup, "find_reference_photo", side_effect=OSError("boom")):
            with patch.object(photo_lookup, "find_portrait_outcome", side_effect=OSError("boom")):
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

    def test_two_or_three_people_all_with_photos_draw_faces(self):
        """2026-08-18 使用者裁定放寬：1-3 人且每位都查到照片就畫臉。

        依據是同日的實測——全員有照片時 9/9 張臉正確對到姓名條、0 交換 0 捏臉
        （docs/error-cases/2026-08-18-多人肖像放寬到3人-實驗-分析.md）。
        """
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                with patch.object(main, "supports_multiple_reference_images", return_value=True):
                    two = main.resolve_portraits(["鄭明典", "吳軒彤"], "gpt")
                    three = main.resolve_portraits(["甲", "乙", "丙"], "gpt")
        self.assertEqual(two[0], "reference_multi")
        self.assertEqual(len(two[1]), 2)
        self.assertEqual(three[0], "reference_multi")
        self.assertEqual(len(three[1]), 3)

    def test_one_missing_photo_blocks_every_face(self):
        """全有或全無：只要有一位查不到，整張退回不畫臉。

        2026-08-18 實測 2/2 證明「有照片的畫、沒照片的畫剪影」生圖模型辦不到——
        沒照片的那位被憑空捏臉還掛真名。
        """
        def lookup(name, **kwargs):
            return None if name == "吳軒彤" else PHOTO

        def outcome(name, **kwargs):
            return NO_ENTRY_OUTCOME if name == "吳軒彤" else _entry_only_outcome(name)

        with patch.object(photo_lookup, "find_reference_photo", side_effect=lookup):
            with patch.object(photo_lookup, "find_portrait_outcome", side_effect=outcome):
                with patch.object(main, "supports_reference_image", return_value=True):
                    with patch.object(main, "supports_multiple_reference_images", return_value=True):
                        mode, photos = main.resolve_portraits(["鄭明典", "吳軒彤"], "gpt")
        self.assertEqual((mode, photos), ("no_reference", []))

    def test_more_than_three_people_is_not_truncated(self):
        """超過 3 人不畫臉，而且**不能**自己砍成 3 人——版面是照 4 個人設計的。
        壓在 3 人以內是消化階段的事（REAL_WORLD_FIDELITY_RULES 第 6 條）。
        """
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO) as lookup:
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, photos = main.resolve_portraits(["甲", "乙", "丙", "丁"], "gpt")
        self.assertEqual((mode, photos), ("no_reference", []))
        lookup.assert_not_called()

    def test_multi_needs_the_multi_reference_channel(self):
        """送不出多張參考圖的後端，不能宣稱附了多張——措辭與能力必須一致。"""
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO) as lookup:
            with patch.object(main, "supports_reference_image", return_value=True):
                with patch.object(main, "supports_multiple_reference_images", return_value=False):
                    mode, photos = main.resolve_portraits(["甲", "乙"], "gpt")
        self.assertEqual((mode, photos), ("no_reference", []))
        lookup.assert_not_called()

    def test_multi_block_keeps_the_disclaimer_label(self):
        """自動查來的照片仍要標「示意圖」：那個不標的 override 只適用於使用者自己
        提供的素材。寫實照片感＋真名＋沒有標籤是最糟組合。"""
        self.assertIn("示意圖", news_prompt.PORTRAIT_MULTI_WITH_REFERENCE_RULES)
        self.assertIn(
            "NEVER swap likenesses", news_prompt.PORTRAIT_MULTI_WITH_REFERENCE_RULES
        )

    def test_duplicate_name_is_still_one_person(self):
        """同一個人被列兩次不該被誤判成多人——清洗過的名單才進判斷。"""
        subjects = main.clean_portrait_subjects(["某人", "某人 ", "某人"])
        self.assertEqual(subjects, ["某人"])
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                mode, _ = resolve_portrait(subjects, "gpt")
        self.assertEqual(mode, "reference")


class EnglishNameLookupTests(unittest.TestCase):
    """臺灣譯名查不到時改用英文原名（2026-08-18）。

    起因：一則美伊新聞的「卡利巴夫」「阿拉奇」「巴薩尼」「瓦希迪」在中文維基
    全部查無條目（連重導向都沒有），整張圖因此一個真人臉都畫不出來；但英文名
    `Ahmad Vahidi` 查得到。
    """

    def setUp(self):
        photo_lookup.clear_photo_lookup_cache()

    def test_english_name_is_tried_when_the_chinese_name_misses(self):
        def by_name(name, *_args):
            return (True, PHOTO) if name == "Ahmad Vahidi" else (False, None)

        with patch.object(photo_lookup, "_lookup_lang", side_effect=by_name):
            photo = photo_lookup.find_reference_photo("瓦希迪", alt_names=["Ahmad Vahidi"])
        self.assertIs(photo, PHOTO)

    def test_chinese_name_wins_when_both_resolve(self):
        """中文條目優先——臺灣新聞的人物用中文維基的照片較貼近本地認知。"""
        with patch.object(photo_lookup, "_lookup_lang", return_value=(True, PHOTO)):
            photo = photo_lookup.find_reference_photo("賴清德", alt_names=["Lai Ching-te"])
        self.assertIs(photo, PHOTO)

    def test_blank_english_name_is_ignored(self):
        with patch.object(photo_lookup, "_lookup_lang", return_value=(False, None)) as lookup:
            self.assertIsNone(
                photo_lookup.find_reference_photo("某人", alt_names=["", "  "], langs=("zh",))
            )
        # 只查中文名那一次，空字串不該變成一次無謂的查詢
        self.assertEqual(lookup.call_count, 1)

    def test_english_names_are_paired_by_original_name_not_by_index(self):
        """清洗會去掉空值與重複，直接按索引取會讓第 2 個人拿到第 3 個人的英文名。"""
        raw_subjects = ["", "瓦希迪", "瓦希迪", "巴薩尼"]
        raw_en = ["", "Ahmad Vahidi", "Ahmad Vahidi", "Masoud Barzani"]
        cleaned = main.clean_portrait_subjects(raw_subjects)
        self.assertEqual(cleaned, ["瓦希迪", "巴薩尼"])
        self.assertEqual(
            main.align_english_names(cleaned, raw_en, raw_subjects),
            ["Ahmad Vahidi", "Masoud Barzani"],
        )

    def test_missing_english_list_degrades_to_blanks(self):
        self.assertEqual(
            main.align_english_names(["甲", "乙"], None, ["甲", "乙"]), ["", ""]
        )


class ExcludePeopleDigestTests(unittest.TestCase):
    """查不到照片的人改在消化階段排出版面（2026-08-18 使用者裁決）。

    為什麼不在生圖階段處理：實測 2/2 證明生圖模型做不到逐人區分。消化端是文字
    模型，而且要拿掉的不只一張臉——姓名條、引言框、版位都要重新安排。
    """

    def test_empty_exclusion_leaves_the_prompt_byte_identical(self):
        """沒有人要排除時 prompt 必須逐字不變，記者 frozen 測試靠這點維持綠燈。"""
        base = main.build_digest_instructions("記者", "standard", "資料圖表")
        self.assertEqual(
            main.build_digest_instructions("記者", "standard", "資料圖表", exclude_people=[]),
            base,
        )
        self.assertEqual(
            main.build_digest_instructions("記者", "standard", "資料圖表", exclude_people=["  "]),
            base,
        )

    def test_excluded_people_are_named_and_may_still_appear_as_text(self):
        out = main.build_digest_instructions(
            "記者", "standard", "資料圖表", exclude_people=["吳軒彤"]
        )
        self.assertIn("吳軒彤", out)
        self.assertIn("PEOPLE WHO MUST NOT BE DRAWN", out)
        # 使用者 2026-08-18 補充：名字可以用文字提及，只是不畫臉
        self.assertIn("may still appear as TEXT", out)

    def test_cap_binds_the_layout_not_just_the_list(self):
        """上限要綁版面：只綁清單的話，模型可以畫 4 張臉卻只列 3 個，
        第 4 張就是 2026-08-05 那種掛真名的捏臉。"""
        out = main.build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn("AT MOST THREE FACES", out)
        self.assertIn("truthful mirror", out)


class ResolveDigestPortraitsTests(unittest.TestCase):
    """兩段式消化：只有第 4 層才重新消化，第 3 層留在版面並通知。"""

    def _digest(self, subjects):
        return main.GenerateResponse(
            style="s", structure="t", variable="v", chart_type="資料圖表",
            portrait_subjects=subjects,
        )

    def _req(self):
        return main.NewsImageGenerateRequest(news_text="新聞內容" * 10)

    def test_no_retry_when_every_photo_is_found(self):
        photo_outcome = photo_lookup.PortraitLookupOutcome(
            photo=PHOTO, entry_found=True, matched_name="甲", language="zh"
        )
        with patch.object(
            main,
            "lookup_portrait_outcomes",
            return_value={"甲": photo_outcome, "乙": photo_outcome},
        ):
            with patch.object(main, "supports_reference_image", return_value=True):
                with patch.object(main, "generate") as regenerate:
                    digest, photos = main.resolve_digest_portraits(
                        self._digest(["甲", "乙"]), self._req(), "gpt"
                    )
        regenerate.assert_not_called()
        self.assertEqual(len(photos), 2)
        self.assertEqual(digest.portrait_subjects, ["甲", "乙"])

    def test_missing_photo_triggers_exactly_one_redigest(self):
        retried = self._digest(["鄭明典"])
        photo_outcome = photo_lookup.PortraitLookupOutcome(
            photo=PHOTO, entry_found=True, matched_name="鄭明典", language="zh"
        )
        with patch.object(
            main,
            "lookup_portrait_outcomes",
            side_effect=[
                {"鄭明典": photo_outcome, "吳軒彤": NO_ENTRY_OUTCOME},
                {"鄭明典": photo_outcome},
            ],
        ):
            with patch.object(main, "supports_reference_image", return_value=True):
                with patch.object(main, "generate", return_value=retried) as regenerate:
                    digest, photos = main.resolve_digest_portraits(
                        self._digest(["鄭明典", "吳軒彤"]), self._req(), "gpt"
                    )
        regenerate.assert_called_once()
        # 重新消化時要把查不到的人明確傳下去
        self.assertEqual(regenerate.call_args[0][0].exclude_people, ["吳軒彤"])
        self.assertEqual(digest.portrait_subjects, ["鄭明典"])
        self.assertEqual(list(photos), ["鄭明典"])

    def test_second_pass_still_missing_gives_up_instead_of_looping(self):
        """第二次消化又挑出沒照片的人時不再重試——無限重試會一直燒消化費用。"""
        retried = self._digest(["另一個查不到的人"])
        with patch.object(
            main,
            "lookup_portrait_outcomes",
            side_effect=[
                {"甲": NO_ENTRY_OUTCOME},
                {"另一個查不到的人": NO_ENTRY_OUTCOME},
            ],
        ):
            with patch.object(main, "supports_reference_image", return_value=True):
                with patch.object(main, "generate", return_value=retried) as regenerate:
                    digest, photos = main.resolve_digest_portraits(
                        self._digest(["甲"]), self._req(), "gpt"
                    )
        regenerate.assert_called_once()
        self.assertEqual(photos, {})
        # 交給 resolve_portraits 退回全員不畫臉
        with patch.object(main, "supports_reference_image", return_value=True):
            mode, _ = main.resolve_portraits(
                digest.portrait_subjects,
                "gpt",
                photos=photos,
                outcomes={"另一個查不到的人": NO_ENTRY_OUTCOME},
            )
        self.assertEqual(mode, "no_reference")

    def test_entry_only_stays_in_line_layout_and_records_notice(self):
        main.reset_portrait_notices()
        entry_only = _entry_only_outcome("甲")
        with patch.object(
            main, "lookup_portrait_outcomes", return_value={"甲": entry_only}
        ):
            with patch.object(main, "supports_reference_image", return_value=True):
                with patch.object(main, "generate") as regenerate:
                    digest, photos = main.resolve_digest_portraits(
                        self._digest(["甲"]), self._req(), "gpt"
                    )
        regenerate.assert_not_called()
        self.assertEqual(digest.portrait_subjects, ["甲"])
        self.assertEqual(photos, {})
        self.assertEqual(len(main.collected_portrait_notices()), 1)


class ApplyPhotoAvailabilityTests(unittest.TestCase):
    """網頁版消化端也必須在 F40 第 3／4 層分流。"""

    def _result(self, names):
        return GenerateResponse(
            style="s", structure="t", variable="v", chart_type="資料圖表",
            portrait_subjects=names,
        )

    def _request(self, portrait_photo_count=0):
        return GenerateRequest(
            news_text="新聞內容", type_label="自動判斷", portrait_photo_count=portrait_photo_count
        )

    def test_entry_only_stays_in_layout_and_records_notice(self):
        main.reset_portrait_notices()
        with patch.object(
            main,
            "lookup_portrait_outcomes",
            return_value={"甲": _entry_only_outcome("甲")},
        ):
            with patch.object(main, "generate") as regenerate:
                result = apply_photo_availability(self._result(["甲"]), self._request())
        regenerate.assert_not_called()
        self.assertEqual(result.portrait_subjects, ["甲"])
        self.assertEqual(len(main.collected_portrait_notices()), 1)

    def test_no_entry_is_the_only_case_that_redigests(self):
        retried = self._result([])
        with patch.object(
            main,
            "lookup_portrait_outcomes",
            return_value={"甲": NO_ENTRY_OUTCOME},
        ):
            with patch.object(main, "generate", return_value=retried) as regenerate:
                result = apply_photo_availability(self._result(["甲"]), self._request())
        regenerate.assert_called_once()
        self.assertEqual(regenerate.call_args.args[0].exclude_people, ["甲"])
        self.assertIs(result, retried)

    def test_mixed_entry_only_and_no_entry_excludes_only_no_entry(self):
        retried = self._result(["甲"])
        with patch.object(
            main,
            "lookup_portrait_outcomes",
            return_value={"甲": _entry_only_outcome("甲"), "乙": NO_ENTRY_OUTCOME},
        ):
            with patch.object(main, "generate", return_value=retried) as regenerate:
                apply_photo_availability(self._result(["甲", "乙"]), self._request())
        self.assertEqual(regenerate.call_args.args[0].exclude_people, ["乙"])


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

    def test_native_openai_sends_single_reference_via_images_edit(self):
        """2026-09-16（B64）：原生 GPT 送得出單張參考圖，這裡原本釘的是相反的事實。

        2026-09-10 起 generate_gpt_image 有參考圖就改走 images.edit；這支判斷沒跟著
        改，肖像參考照在原生後端被整批丟掉、真人題退回背影。兩種拼法（native／
        openai）都要成立——路由只看「是不是 openrouter＋有 key」。
        """
        for backend in ("native", "openai"):
            with self.subTest(backend=backend):
                with patch.dict(
                    os.environ,
                    {"IMAGE_BACKEND": backend, "OPENROUTER_API_KEY": ""},
                    clear=False,
                ):
                    self.assertTrue(supports_reference_image("gpt"))
                    self.assertTrue(supports_reference_image("gemini"))

    def test_openrouter_without_key_falls_back_to_native(self):
        """沒有 key 時 generate_image_raw 會落到原生，能力判斷必須跟著落。"""
        with patch.dict(
            os.environ, {"IMAGE_BACKEND": "openrouter", "OPENROUTER_API_KEY": ""}, clear=False
        ):
            self.assertFalse(main.using_openrouter_images())
            self.assertTrue(supports_reference_image("gpt"))


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

    def setUp(self):
        photo_lookup.clear_photo_lookup_cache()

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

    def test_two_people_with_photos_attach_both(self):
        """2026-08-18 放寬：兩位都查得到照片就兩張都附，走多張通道。"""
        req = ImageGenerateRequest(
            prompt="base prompt", portrait_subjects=["鄭明典", "吳軒彤"], provider="gpt"
        )
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                with patch.object(main, "supports_multiple_reference_images", return_value=True):
                    out = apply_portrait_to_image_request(req)
        self.assertIn("MULTIPLE PORTRAITS", out.prompt)
        self.assertEqual(len(out.portrait_reference_data_urls), 2)
        # 單張欄位維持空的：多人一律走多張通道，兩邊都塞會重複送同一張
        self.assertEqual(out.reference_image_data_url, "")

    def test_two_people_with_one_missing_photo_forbid_faces(self):
        req = ImageGenerateRequest(
            prompt="base prompt", portrait_subjects=["鄭明典", "吳軒彤"], provider="gpt"
        )

        def lookup(name, **kwargs):
            return None if name == "吳軒彤" else PHOTO

        def outcome_lookup(subjects, english=None):
            return {
                name: photo_lookup.PortraitLookupOutcome(
                    photo=None, entry_found=False, matched_name=None, language=None
                )
                for name in subjects
            }

        with patch.object(photo_lookup, "find_reference_photo", side_effect=lookup):
            with patch.object(main, "lookup_portrait_outcomes", side_effect=outcome_lookup):
                with patch.object(main, "supports_reference_image", return_value=True):
                    with patch.object(main, "supports_multiple_reference_images", return_value=True):
                        out = apply_portrait_to_image_request(req)
        self.assertIn("NO PERSON IN THIS SCENE", out.prompt)
        self.assertEqual(out.reference_image_data_url, "")
        self.assertEqual(out.portrait_reference_data_urls, [])

    def test_upload_shortfall_is_filled_by_lookup(self):
        """使用者上傳 1 張、畫面 2 人：缺的那位由自動查圖補上（2026-08-18 裁決）。"""
        req = ImageGenerateRequest(
            prompt="base prompt",
            portrait_subjects=["鄭明典", "吳軒彤"],
            provider="gpt",
            reference_images=[
                main.UserReferenceImage(data_url="data:image/jpeg;base64,QQ==", purpose="portrait")
            ],
        )

        def lookup(name, **kwargs):
            return None if name == "吳軒彤" else PHOTO

        with patch.object(photo_lookup, "find_reference_photo", side_effect=lookup):
            with patch.object(main, "supports_reference_image", return_value=True):
                out = apply_portrait_to_image_request(req)
        # 上傳的那張視為對應查不到的吳軒彤，鄭明典由維基補上
        self.assertEqual(len(out.portrait_reference_data_urls), 1)

    def test_upload_still_short_is_blocked_before_paying_for_an_image(self):
        """補完仍有人沒照片就擋下不生圖（沿用 2026-08-05 裁決）。"""
        req = ImageGenerateRequest(
            prompt="base prompt",
            portrait_subjects=["甲", "乙", "丙"],
            provider="gpt",
            reference_images=[
                main.UserReferenceImage(data_url="data:image/jpeg;base64,QQ==", purpose="portrait")
            ],
        )
        with patch.object(photo_lookup, "find_reference_photo", return_value=None):
            with patch.object(main, "supports_reference_image", return_value=True):
                with self.assertRaises(HTTPException) as caught:
                    apply_portrait_to_image_request(req)
        self.assertEqual(caught.exception.status_code, 400)

    def test_one_person_with_photo_sets_the_ai_disclaimer_kind(self):
        """2026-09-20 team-lead 複查點名的回歸（獨立複查 gpt-5.6-sol 發現、
        team-lead 驗證）：這支函式以前從沒設過 disclaimer_kind，prompt 已經告知
        模型「不要自己畫、軟體會壓」，但軟體那半沒被叫到，標籤整個消失
        （LINE 路徑的 generate_news_image 沒有這個洞）。"""
        req = ImageGenerateRequest(prompt="base prompt", portrait_subjects=["某人"], provider="gpt")
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                out = apply_portrait_to_image_request(req)
        self.assertEqual(out.disclaimer_kind, "ai")

    def test_two_people_with_photos_sets_the_ai_disclaimer_kind(self):
        req = ImageGenerateRequest(
            prompt="base prompt", portrait_subjects=["鄭明典", "吳軒彤"], provider="gpt"
        )
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                with patch.object(main, "supports_multiple_reference_images", return_value=True):
                    out = apply_portrait_to_image_request(req)
        self.assertEqual(out.disclaimer_kind, "ai")

    def test_no_person_scene_sets_no_disclaimer(self):
        """no_reference：畫面不安排這個人，沒有臉可標，disclaimer_kind 維持空字串。"""
        req = ImageGenerateRequest(
            prompt="base prompt", portrait_subjects=["鄭明典", "吳軒彤"], provider="gpt"
        )

        def outcome_lookup(subjects, english=None):
            return {
                name: photo_lookup.PortraitLookupOutcome(
                    photo=None, entry_found=False, matched_name=None, language=None
                )
                for name in subjects
            }

        with patch.object(photo_lookup, "find_reference_photo", return_value=None):
            with patch.object(main, "lookup_portrait_outcomes", side_effect=outcome_lookup):
                with patch.object(main, "supports_reference_image", return_value=True):
                    with patch.object(main, "supports_multiple_reference_images", return_value=True):
                        out = apply_portrait_to_image_request(req)
        self.assertEqual(out.disclaimer_kind, "")

    def test_uploaded_portrait_photo_still_sets_the_ai_disclaimer_kind(self):
        """B28 例外三：使用者親自上傳肖像照，具名真人仍要標「示意圖」——這條路
        （uploaded 分支）以前連 prompt 都沒告訴模型要標，disclaimer_kind 也沒設過，
        是比另一半更早就存在的洞。"""
        req = ImageGenerateRequest(
            prompt="base prompt",
            portrait_subjects=["某人"],
            provider="gpt",
            reference_images=[
                main.UserReferenceImage(data_url="data:image/jpeg;base64,QQ==", purpose="portrait")
            ],
        )
        with patch.object(main, "supports_reference_image", return_value=True):
            out = apply_portrait_to_image_request(req)
        self.assertEqual(out.disclaimer_kind, "ai")

    def test_uploaded_portrait_with_lookup_shortfall_also_sets_the_disclaimer(self):
        req = ImageGenerateRequest(
            prompt="base prompt",
            portrait_subjects=["鄭明典", "吳軒彤"],
            provider="gpt",
            reference_images=[
                main.UserReferenceImage(data_url="data:image/jpeg;base64,QQ==", purpose="portrait")
            ],
        )

        def lookup(name, **kwargs):
            return None if name == "吳軒彤" else PHOTO

        with patch.object(photo_lookup, "find_reference_photo", side_effect=lookup):
            with patch.object(main, "supports_reference_image", return_value=True):
                out = apply_portrait_to_image_request(req)
        self.assertEqual(out.disclaimer_kind, "ai")

    def test_existing_block_is_not_duplicated(self):
        already = "base\n\n" + news_prompt.PORTRAIT_WITH_REFERENCE_RULES
        req = ImageGenerateRequest(
            prompt=already, portrait_subjects=["某人"], provider="gpt"
        )
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO):
            with patch.object(main, "supports_reference_image", return_value=True):
                out = apply_portrait_to_image_request(req)
        self.assertEqual(out.prompt.count("NAMED REAL PERSON — PORTRAIT TREATMENT"), 1)


class F40FourTierDecisionTests(unittest.TestCase):
    """F40（2026-09-16 使用者裁決）：四層分流，優先序固定。

    1 使用者上傳 portrait → 直接用（既有測試覆蓋，見 ApplyPortraitToImageRequestTests）
    2 維基有合格照片 → 附照片走 reference 規則（既有測試覆蓋）
    3 維基有條目但沒有合格照片 → 允許模型自畫＋回 notice（本類新增）
    4 連條目都查不到 → 無人場景，不回 notice（本類新增）
    """

    def setUp(self):
        photo_lookup.clear_photo_lookup_cache()
        main.reset_portrait_notices()

    def test_entry_only_single_subject(self):
        outcome = _entry_only_outcome("查得到條目的人")
        with patch.object(main, "supports_reference_image", return_value=True):
            mode, photos = main.resolve_portraits(
                ["查得到條目的人"], "gpt", outcomes={"查得到條目的人": outcome}
            )
        self.assertEqual((mode, photos), ("entry_only", []))

    def test_entry_only_prompt_block_allows_context_drawn_likeness(self):
        prompt = _prompt("entry_only")
        self.assertIn("NAMED REAL PERSON — NO VERIFIED PHOTOGRAPH, DRAW FROM CONTEXT", prompt)
        self.assertIn("Draw a plausible likeness consistent with that context", prompt)
        # 使用者明確裁定：不要在圖上標「長相為 AI 推測」，這句免責文字不進畫面
        self.assertNotIn("長相為 AI 推測", prompt)
        self.assertNotIn("AI 推測", prompt)

    def test_no_entry_falls_back_to_no_person_scene(self):
        with patch.object(main, "supports_reference_image", return_value=True):
            mode, photos = main.resolve_portraits(
                ["查無此人"], "gpt", outcomes={"查無此人": NO_ENTRY_OUTCOME}
            )
        self.assertEqual((mode, photos), ("no_reference", []))

    def test_mixed_missing_falls_back_to_no_person_scene_not_entry_only(self):
        """一位有條目、一位連條目都沒有：全有或全無，退到最保守的無人場景。"""
        outcomes = {"有條目的人": _entry_only_outcome("有條目的人"), "查無此人": NO_ENTRY_OUTCOME}
        with patch.object(main, "supports_reference_image", return_value=True):
            with patch.object(main, "supports_multiple_reference_images", return_value=True):
                mode, photos = main.resolve_portraits(
                    ["有條目的人", "查無此人"], "gpt", outcomes=outcomes
                )
        self.assertEqual((mode, photos), ("no_reference", []))

    def test_apply_portrait_to_image_request_records_entry_only_notice(self):
        req = ImageGenerateRequest(
            prompt="base prompt", portrait_subjects=["查得到條目的人"], provider="gpt"
        )
        outcome = _entry_only_outcome("查得到條目的人")
        with patch.object(main, "lookup_portrait_photos", return_value=({}, ["查得到條目的人"])):
            with patch.object(main, "lookup_portrait_outcomes", return_value={"查得到條目的人": outcome}):
                with patch.object(main, "supports_reference_image", return_value=True):
                    out = apply_portrait_to_image_request(req)
        self.assertIn("NO VERIFIED PHOTOGRAPH, DRAW FROM CONTEXT", out.prompt)
        # 不畫進圖裡的免責聲明改成回 notice，走 main._portrait_notices（response 層見
        # ImageGenerateResponse.notices，本測試只釘住 apply_portrait_to_image_request
        # 有把它記進去）
        notices = main.collected_portrait_notices()
        self.assertEqual(len(notices), 1)
        self.assertIn("查得到條目的人", notices[0])
        self.assertIn("並非本人的精確肖像", notices[0])

    def test_no_entry_records_no_notice(self):
        req = ImageGenerateRequest(
            prompt="base prompt", portrait_subjects=["查無此人"], provider="gpt"
        )
        with patch.object(main, "lookup_portrait_photos", return_value=({}, ["查無此人"])):
            with patch.object(main, "lookup_portrait_outcomes", return_value={"查無此人": NO_ENTRY_OUTCOME}):
                with patch.object(main, "supports_reference_image", return_value=True):
                    apply_portrait_to_image_request(req)
        self.assertEqual(main.collected_portrait_notices(), [])

    def test_empty_subjects_prompt_still_carries_final_baseline(self):
        """空 subjects 不繞過 Stage 4 的鐵律層（FINAL_IMAGE_BASELINE）。"""
        req = ImageGenerateRequest(prompt="base prompt", provider="gpt")
        out = apply_portrait_to_image_request(req)
        self.assertIs(out, req)  # 沒有 subjects 時這支本身不動 prompt
        baselined = news_prompt.ensure_final_image_baseline(out.prompt)
        self.assertIn(news_prompt.FINAL_IMAGE_BASELINE_MARKER, baselined)

    def test_b66_realism_wording_is_consistent_across_the_three_reference_constants(self):
        """B66：三組「查到參考照」常數的措辭要一致——寫實為主、只帶一點插畫筆觸。"""
        for rules in (
            news_prompt.PORTRAIT_WITH_REFERENCE_RULES,
            news_prompt.PORTRAIT_MULTI_WITH_REFERENCE_RULES,
            news_prompt.USER_REFERENCE_PORTRAIT_RULES,
        ):
            self.assertIn("realistic editorial news portrait", rules)
            self.assertIn("light illustrative touch", rules)
            self.assertNotIn("hand-painted editorial portrait illustration", rules)
            self.assertNotIn("must be readable as an illustration", rules)


if __name__ == "__main__":
    unittest.main()
