"""B70／F43（2026-09-20）：具名肖像「示意圖」標籤改由程式端 Pillow 壓字，
新增互斥的「畫面來源」欄位。

B70 根因：標籤以前完全交給生圖模型自己畫進「variable」，沒有程式保證——4 張
具名肖像實拍裡 2 張不合格（一張整張找不到標籤，一張寫成錯字「示憊佪」，見
MASTER-列管清單.md）。2026-09-16 使用者裁定採甲案：改由程式後貼，模型只被
告知「這個角落留空」。

F43 追加「畫面來源」欄位，與「示意圖」互斥：圖是 AI 生成／被 AI 改過 → 標
「示意圖」；圖是使用者原圖且保證未被動過像素 → 標「畫面來源：○○○」。

三塊測試：
1. main.resolve_image_disclaimer 的互斥判定表
2. compose.paste_disclaimer_note 的貼字幾何與錯誤處理
3. main.generate_image／generate_news_image 的實際串接
"""

import base64
import io
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402
import main  # noqa: E402
import news_prompt  # noqa: E402
import photo_lookup  # noqa: E402
import safe_area_spec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

client = TestClient(main.app)
PHOTO = photo_lookup.ReferencePhoto(
    image_base64="QUJD",
    mime_type="image/jpeg",
    image_url="https://upload.wikimedia.org/x.jpg",
    source_page="https://zh.wikipedia.org/wiki/%E6%9F%90%E4%BA%BA",
    lang="zh",
)


def png_base64(width: int, height: int, colour=(40, 60, 90)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def fake_raw_response(image_base64: str) -> main.ImageGenerateResponse:
    return main.ImageGenerateResponse(
        image_data_base64=image_base64, mime_type="image/png", model="fake-model"
    )


class ResolveImageDisclaimerTests(unittest.TestCase):
    """互斥判定表：每一種 (portrait_mode, source_text) 組合恰好落在
    {"ai", "source", ""} 其中一種，AI 標籤永遠贏。"""

    AI_MODES = ("reference", "reference_multi", "entry_only")
    NON_AI_MODES = ("no_reference", "none", "", "unknown_future_mode")

    def test_ai_modes_always_win_regardless_of_source_text(self):
        for mode in self.AI_MODES:
            for source_text in ("", "美聯社", "  路透社  "):
                with self.subTest(mode=mode, source_text=source_text):
                    self.assertEqual(
                        main.resolve_image_disclaimer(mode, source_text),
                        ("ai", ""),
                    )

    def test_non_ai_modes_with_source_text_get_source(self):
        for mode in self.NON_AI_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(
                    main.resolve_image_disclaimer(mode, "美聯社"),
                    ("source", "美聯社"),
                )

    def test_non_ai_modes_without_source_text_get_nothing(self):
        for mode in self.NON_AI_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(main.resolve_image_disclaimer(mode, ""), ("", ""))

    def test_whitespace_only_source_text_counts_as_empty(self):
        self.assertEqual(main.resolve_image_disclaimer("none", "   "), ("", ""))

    def test_result_is_always_exactly_one_of_the_three_kinds(self):
        """明確釘住互斥——不可能同一次回傳同時暗示兩種標籤。"""
        for mode in self.AI_MODES + self.NON_AI_MODES:
            for source_text in ("", "來源名"):
                with self.subTest(mode=mode, source_text=source_text):
                    kind, text = main.resolve_image_disclaimer(mode, source_text)
                    self.assertIn(kind, ("", "ai", "source"))
                    if kind == "ai":
                        self.assertEqual(text, "")
                    if kind == "":
                        self.assertEqual(text, "")


class ComposePasteDisclaimerNoteTests(unittest.TestCase):
    def setUp(self):
        self.canvas = (1920, 1080)
        self.image_bytes = base64.b64decode(png_base64(*self.canvas))

    def test_ai_kind_draws_the_fixed_text(self):
        out = compose.paste_disclaimer_note(self.image_bytes, kind="ai")
        with Image.open(io.BytesIO(out)) as img:
            self.assertEqual(img.size, self.canvas)
            self.assertEqual(img.mode, "RGB")

    def test_source_kind_normalises_the_prefix(self):
        """沿用 vstrip_source_text：使用者只填來源名，「畫面來源：」自動補。"""
        with patch.object(
            compose, "vstrip_source_text", wraps=compose.vstrip_source_text
        ) as spy:
            compose.paste_disclaimer_note(
                self.image_bytes, kind="source", source_text="美聯社"
            )
        spy.assert_called_once_with("美聯社")

    def test_source_kind_with_empty_text_raises(self):
        with self.assertRaises(compose.ComposeError):
            compose.paste_disclaimer_note(self.image_bytes, kind="source", source_text="")

    def test_source_kind_with_whitespace_only_text_raises(self):
        with self.assertRaises(compose.ComposeError):
            compose.paste_disclaimer_note(self.image_bytes, kind="source", source_text="   ")

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(compose.ComposeError):
            compose.paste_disclaimer_note(self.image_bytes, kind="watermark")

    def test_unknown_corner_is_rejected(self):
        with self.assertRaises(compose.ComposeError):
            compose.paste_disclaimer_note(self.image_bytes, kind="ai", corner="middle")

    def test_every_corner_lands_inside_the_safe_area(self):
        """B70 動工前要釘的第②件事：自訂位置必須限制在安全框內。"""
        x0, y0, x1, y1 = safe_area_spec.safe_rect(
            *self.canvas, safe_area_spec.REPORTER_PROFILE
        )
        for corner in compose.PORTRAIT_DISCLAIMER_CORNERS:
            with self.subTest(corner=corner):
                left, top, right, bottom = compose._disclaimer_box(
                    self.canvas, corner, safe_area_spec.REPORTER_PROFILE,
                    box_w=200, box_h=60,
                )
                self.assertGreaterEqual(left, x0)
                self.assertLessEqual(right, x1)
                self.assertGreaterEqual(top, y0)
                self.assertLessEqual(bottom, y1)

    def test_corners_are_mutually_distinct_positions(self):
        boxes = {
            corner: compose._disclaimer_box(
                self.canvas, corner, safe_area_spec.REPORTER_PROFILE, 200, 60
            )
            for corner in compose.PORTRAIT_DISCLAIMER_CORNERS
        }
        self.assertEqual(len(set(boxes.values())), len(boxes))

    def test_output_canvas_size_is_unchanged(self):
        """貼標籤不能順便改動畫布尺寸——那是另一個 bug 類型（見安全框系列教訓）。"""
        for corner in compose.PORTRAIT_DISCLAIMER_CORNERS:
            with self.subTest(corner=corner):
                out = compose.paste_disclaimer_note(
                    self.image_bytes, kind="ai", corner=corner
                )
                with Image.open(io.BytesIO(out)) as img:
                    self.assertEqual(img.size, self.canvas)

    def test_actual_image_size_wins_over_the_default_canvas_argument(self):
        """理由同 apply_broadcast_hole：上游可能改了尺寸，不能硬信呼叫端傳的 canvas。"""
        smaller = base64.b64decode(png_base64(1280, 720))
        out = compose.paste_disclaimer_note(
            smaller, kind="ai", canvas=self.canvas
        )
        with Image.open(io.BytesIO(out)) as img:
            self.assertEqual(img.size, (1280, 720))


class GenerateImageWiringTests(unittest.TestCase):
    """generate_image() 實際串接：置框／挖空框跑完之後才貼標籤，
    且播出鏡面挖空框已經自己貼過一次，兩者不疊貼。"""

    def test_disclaimer_kind_empty_skips_stamping_entirely(self):
        raw = fake_raw_response(png_base64(1920, 1080))
        with patch.object(main, "generate_image_raw", return_value=raw), patch.object(
            compose, "paste_disclaimer_note"
        ) as spy:
            main.generate_image(main.ImageGenerateRequest(prompt="p", disclaimer_kind=""))
        spy.assert_not_called()

    def test_ai_disclaimer_is_stamped_after_safe_framing(self):
        raw = fake_raw_response(png_base64(1280, 720))
        with patch.object(main, "generate_image_raw", return_value=raw):
            result = main.generate_image(
                main.ImageGenerateRequest(
                    prompt="p", provider="gpt", safe_frame=True,
                    safe_frame_profile="記者", disclaimer_kind="ai",
                )
            )
        with Image.open(io.BytesIO(base64.b64decode(result.image_data_base64))) as img:
            self.assertEqual(img.size, safe_area_spec.BASE_CANVAS)

    def test_source_disclaimer_needs_source_text(self):
        raw = fake_raw_response(png_base64(1920, 1080))
        with patch.object(main, "generate_image_raw", return_value=raw):
            with self.assertRaises(main.HTTPException) as ctx:
                main.generate_image(
                    main.ImageGenerateRequest(
                        prompt="p", disclaimer_kind="source", disclaimer_source_text="",
                    )
                )
        self.assertEqual(ctx.exception.status_code, 500)

    def test_broadcast_hole_set_skips_the_new_stamp_to_avoid_double_stamping(self):
        """apply_broadcast_hole 已經在同一個安全區角落自己貼過一次「示意圖」浮水印
        （compose.WATERMARK_TEXT）；disclaimer_kind 同時有值時不重貼第二次。"""
        raw = fake_raw_response(png_base64(1280, 720))
        with patch.object(main, "generate_image_raw", return_value=raw), patch.object(
            compose, "paste_disclaimer_note"
        ) as spy:
            main.generate_image(
                main.ImageGenerateRequest(
                    prompt="p", provider="gpt", safe_frame=True,
                    safe_frame_profile="編輯", broadcast_hole="left",
                    disclaimer_kind="ai",
                )
            )
        spy.assert_not_called()

    def test_stamping_failure_raises_instead_of_downgrading(self):
        raw = fake_raw_response(png_base64(1920, 1080))
        with patch.object(main, "generate_image_raw", return_value=raw), patch.object(
            compose, "paste_disclaimer_note", side_effect=compose.ComposeError("boom")
        ):
            with self.assertRaises(main.HTTPException) as ctx:
                main.generate_image(
                    main.ImageGenerateRequest(prompt="p", disclaimer_kind="ai")
                )
        self.assertEqual(ctx.exception.status_code, 500)


class FullPipelineWiringTests(unittest.TestCase):
    """generate_news_image：portrait_mode 一路決定 disclaimer_kind 傳進
    ImageGenerateRequest，不用呼叫端自己算。"""

    def _run(self, portrait_mode: str):
        digest = main.GenerateResponse(
            style="S", structure="T", variable="[標題] X", chart_type="資料圖表"
        )
        image = fake_raw_response(png_base64(1536, 864))
        with (
            patch.object(main, "generate", return_value=digest),
            patch.object(main, "resolve_portraits", return_value=(portrait_mode, [])),
            patch.object(main, "generate_image", return_value=image) as mock_image,
        ):
            main.generate_news_image(
                main.NewsImageGenerateRequest(
                    news_text="颱風假消息滿天飛 氣象署嚴正闢謠並呼籲民眾勿轉傳"
                )
            )
        return mock_image.call_args[0][0]

    def test_reference_mode_asks_for_the_ai_disclaimer(self):
        self.assertEqual(self._run("reference").disclaimer_kind, "ai")

    def test_reference_multi_mode_asks_for_the_ai_disclaimer(self):
        self.assertEqual(self._run("reference_multi").disclaimer_kind, "ai")

    def test_entry_only_mode_asks_for_the_ai_disclaimer(self):
        self.assertEqual(self._run("entry_only").disclaimer_kind, "ai")

    def test_no_reference_mode_asks_for_nothing(self):
        self.assertEqual(self._run("no_reference").disclaimer_kind, "")

    def test_none_mode_asks_for_nothing(self):
        self.assertEqual(self._run("none").disclaimer_kind, "")


class PortraitPromptNoLongerAsksTheModelToDrawTheLabelTests(unittest.TestCase):
    """B70 甲案：三個「查得到怎麼畫、且真的畫出臉」的肖像區塊改口——模型不再自己
    規劃／畫標籤，程式後貼。舊的被動措辭（「有給才畫、沒給就不畫」）必須整句
    換掉，不是並存。這三塊都有 resolve_image_disclaimer 對應的 "ai" 回傳值撐腰
    （PORTRAIT_MODES_NEEDING_DISCLAIMER），軟體真的會壓。"""

    # PORTRAIT_NO_REFERENCE_RULES 不在這裡——2026-09-20 晚間已回退，見
    # RealWorldRulesRevertedWhereNothingBacksThemTests 的說明：no_reference 不在
    # PORTRAIT_MODES_NEEDING_DISCLAIMER 裡，resolve_image_disclaimer 永遠不會替
    # 這條路回 "ai"，告訴模型「不要畫」會讓標籤兩邊都沒有人負責。
    BLOCKS = (
        news_prompt.PORTRAIT_WITH_REFERENCE_RULES,
        news_prompt.PORTRAIT_MULTI_WITH_REFERENCE_RULES,
        news_prompt.PORTRAIT_ENTRY_ONLY_RULES,
    )

    def test_blocks_tell_the_model_not_to_draw_it_itself(self):
        for block in self.BLOCKS:
            with self.subTest(block=block[:50]):
                self.assertIn("Do NOT draw any 示意圖", block)
                self.assertIn("Software stamps the disclaimer afterwards", block)
                self.assertIn("OVERRIDES the general instruction", block)
                self.assertNotIn(
                    "If VARIABLE FIELDS supplies no such label, do not add one yourself",
                    block,
                )

    def test_position_is_expressed_as_a_direction_word_never_a_number(self):
        import re

        for block in self.BLOCKS:
            with self.subTest(block=block[:50]):
                self.assertIn("lower-right corner", block)
                self.assertNotRegex(block, r"\d")

    def test_frozen_baseline_reference_prompt_snapshot_is_untouched(self):
        """這三塊只在明確傳入非 none 的 portrait_mode 時才注入，凍結快照
        （tests/test_reporter_prompt_frozen.py）全部用 portrait_mode="none" 呼叫，
        不受這批影響——這裡直接重新確認一次。"""
        plain = news_prompt.build_prompt(
            role="記者", engine="gpt", type_label="資料圖表",
            style="[S]", structure="[T]", variable="[V]",
        )
        for block in self.BLOCKS:
            self.assertNotIn(block, plain)


class RealWorldRulesRevertedWhereNothingBacksThemTests(unittest.TestCase):
    """B70 全站化第一版（2026-09-20 稍早）曾經把「一般重建圖」與「NAMED REAL
    PEOPLE 的預設分支」也改成「不要自己畫，軟體會後貼」——回填 B70／F43 帳本時
    自己發現：這兩條路沒有對應的程式端壓字。`resolve_image_disclaimer()` 只在
    portrait_mode ∈ PORTRAIT_MODES_NEEDING_DISCLAIMER（reference／reference_multi／
    entry_only）時回 "ai"；一般重建圖（跟具名肖像無關的建物、場景）與
    portrait_mode="none"／no_reference 這兩條路永遠回 ""，沒有人會壓標籤。

    ⚠**使用者尚未裁決這一題**。這裡採用的是既有原則的直接推論——沒有軟體背書
    就不能叫模型不要畫，寧可讓模型畫醜一點的標籤，也不能讓標籤整個消失（這正是
    原本 B70 要修的那個缺陷，等級接近 B76）——所以先**回退成全站化之前的安全值**，
    不是替使用者拍板。**仍待使用者裁決的是**：軟體端要不要也對 portrait_mode=
    "none"／"no_reference" 補壓「示意圖」，以及用什麼當觸發條件（一個候選是
    「variable 裡出現 示意圖 就把 disclaimer_kind 設成 'ai'」）。帳本 B70 那列
    已登記這題，未裁決前程式與文件都不得先給答案。

    因此這批把下列三處**回退**成原始措辭（模型自己判斷要不要畫、軟體不介入）：
    - main.py `REAL_WORLD_FIDELITY_RULES` 第 3 條（一般重建圖，消化端）
      ——第 5 條（具名真人，消化端）**不回退**：那條講的是「別把字寫進 variable」，
      三個有軟體背書的 portrait_mode 都在用，no_reference 不畫臉所以本來就沒有
      要寫的字，維持新措辭沒有風險。
    - news_prompt.py `REAL_WORLD_RENDERING_RULES` 第 2、4 條（一般重建圖預設路徑、
      NAMED REAL PEOPLE 沒有專屬區塊時的預設分支）與 app.js 的鏡像常數
    - news_prompt.py `PORTRAIT_NO_REFERENCE_RULES` 的標籤句（no_reference 專屬
      區塊，不在凍結範圍內）

    重凍紀錄見 tests/test_reporter_prompt_frozen.py 的 docstring
    「2026-09-20（B70／F43 修正）」段落；十份 fixture 因此第二次改動，
    只改回這幾句，其餘（含 B76 那塊）不動。
    """

    def test_digest_side_reverted_to_asking_the_model_to_write_it_itself(self):
        """一般重建圖沒有軟體背書，回退成原始措辭——模型自己判斷、自己寫。"""
        for role in ("記者", "編輯"):
            with self.subTest(role=role):
                instructions = main.build_digest_instructions(role, "standard", "資料圖表")
                self.assertIn("you MUST plan a clearly visible 示意圖 label", instructions)
                self.assertNotIn(
                    'do NOT write the word 示意圖 into "variable" yourself', instructions
                )

    def test_digest_side_named_person_rule_is_scoped_to_portrait_subjects_only(self):
        """第 5 條不整條回退，但**範圍要收窄**（2026-09-20 獨立複查 gpt-5.6-sol
        第二項）。

        原本寫「Never write 示意圖 into "variable" for a depicted person」——
        「depicted person」比 `portrait_subjects` 寬。那個陣列只收**會露臉**的
        具名真人（第 5 條自己的定義），所以「具名真人出現在畫面上、但只畫背影／
        剪影／無臉替身」會落到 `portrait_mode="none"`：模型被第 5 條禁止規劃標籤，
        `resolve_image_disclaimer("none", "")` 又回 `("", "")` 程式也不貼
        ⇒ **一個具名真人的重建畫面完全沒有示意圖標籤**。跟 none／no_reference
        同一個病灶，只是躲在第 5 條裡。

        修法：把豁免範圍釘死在 `portrait_subjects` 上，並明講沒列進去的人仍適用
        第 3 條（模型自己規劃標籤）。三個有軟體背書的 portrait_mode 行為不變。
        """
        instructions = main.build_digest_instructions("記者", "standard", "資料圖表")
        self.assertIn(
            'Never write 示意圖 into "variable" for a person you listed in "portrait_subjects"',
            instructions,
        )
        self.assertNotIn(
            'Never write 示意圖 into "variable" for a depicted person either',
            instructions,
            "舊的寬鬆措辭還在——背影／剪影的具名真人會掉進沒有人負責標籤的縫裡",
        )
        # 收窄之後必須明講「沒列進去的人要自己畫」，否則等於只是換句話說
        self.assertIn("a back view, a silhouette, a faceless stand-in", instructions)
        self.assertIn("rule 3 above applies in full", instructions)
        self.assertNotIn(
            'Always plan the 示意圖 label into "variable" when a person is depicted',
            instructions,
        )

    def test_generation_side_default_path_reverted_to_asking_the_model_itself(self):
        """portrait_mode="none"（或未知值）時沒有任何 PORTRAIT_MODES 區塊注入，
        REAL_WORLD_RENDERING_RULES 的預設措辭才是實際生效的那一份——沒有軟體
        背書，回退成原始「模型自己判斷、自己畫」。"""
        prompt = news_prompt.build_prompt(
            role="記者", engine="gpt", type_label="資料圖表",
            style="[S]", structure="[T]", variable="[V]", portrait_mode="none",
        )
        self.assertIn(
            "the 示意圖 label supplied in VARIABLE FIELDS must be clearly visible",
            prompt,
        )
        self.assertIn("and keep the 示意圖 label visible", prompt)
        self.assertNotIn("do not draw a 示意圖 label yourself", prompt)
        self.assertNotIn("do not draw the 示意圖 label yourself either", prompt)

    def test_no_reference_block_reverted_too(self):
        """no_reference 不在 PORTRAIT_MODES_NEEDING_DISCLAIMER 裡，
        resolve_image_disclaimer 永遠不會替它回 "ai"——回退成原始措辭。"""
        prompt = news_prompt.build_prompt(
            role="記者", engine="gpt", type_label="資料圖表",
            style="[S]", structure="[T]", variable="[V]", portrait_mode="no_reference",
        )
        self.assertIn(
            "The 示意圖 label supplied in VARIABLE FIELDS must stay clearly visible "
            "when the scene is a generic stand-in",
            prompt,
        )
        self.assertNotIn("Software stamps the disclaimer afterwards", prompt)

    def test_content_fidelity_rule_six_is_left_alone(self):
        """CONTENT_FIDELITY_RULES 第 6 條管的是「版型名稱不是新聞內容」，跟標籤
        機制是兩件事，這批不動它——確認它還在、還是舊措辭。"""
        self.assertIn(
            "THE NAME OF THE LAYOUT IS NOT NEWS", main.CONTENT_FIDELITY_RULES
        )
        self.assertIn(
            "say so in \"structure\" as a small caption", main.CONTENT_FIDELITY_RULES
        )

    def test_app_js_mirror_reverted_too(self):
        """news_prompt.REAL_WORLD_RENDERING_RULES 與 app.js 是兩份來源
        （tests/test_prompt_parity.py 逐字比對）；這裡直接重新核對一次回退
        真的兩邊都做了，不是漏了其中一邊。"""
        js_source = (main.__file__.rsplit("main.py", 1)[0] + "app.js")
        with open(js_source, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(
            "the 示意圖 label supplied in VARIABLE FIELDS must be clearly visible", text
        )
        self.assertIn("and keep the 示意圖 label visible", text)
        self.assertNotIn("do not draw a 示意圖 label yourself", text)


class WebImageGenerateEndToEndRegressionTests(unittest.TestCase):
    """2026-09-20 team-lead 複查點名的回歸（獨立複查 gpt-5.6-sol 發現、team-lead
    驗證）：網頁版 /api/images/generate 這條路（不是
    LINE 的 generate_news_image）曾經完全沒有貼上「示意圖」——prompt 已經告訴
    模型「不要自己畫」，但 apply_portrait_to_image_request() 從沒設過
    disclaimer_kind，後貼那半沒被叫到，兩邊斷開＝標籤整個消失，而這正是網頁版
    編輯日常在用的那條路。

    這裡打真正的 HTTP 端點（不是直接呼叫 Python 函式），帶 portrait_subjects，
    斷言成品上真的貼了「示意圖」——不只是 disclaimer_kind 這個中繼欄位對了。
    """

    def _headers(self) -> dict:
        return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}

    def test_named_portrait_via_web_endpoint_gets_the_stamped_label(self):
        raw = main.ImageGenerateResponse(
            image_data_base64=png_base64(1280, 720), mime_type="image/png", model="fake-model",
        )
        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO), patch.object(
            main, "supports_reference_image", return_value=True
        ), patch.object(main, "generate_image_raw", return_value=raw):
            res = client.post(
                "/api/images/generate",
                json={"prompt": "一張新聞圖", "provider": "gpt", "portrait_subjects": ["某人"]},
                headers=self._headers(),
            )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        with Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))) as img:
            self.assertEqual(img.size, (1280, 720))
            # 底片背景是純色 (40,60,90)；貼字底板是半透明黑（見
            # PORTRAIT_DISCLAIMER_PLATE_FILL），錨點釘死在安全區右下角減去 HOLE_INSET
            # （不論文字寬度，這個角落必定被底板蓋到——見 compose._disclaimer_box：
            # right=x1-inset、bottom=y1-inset 是 kind="ai" 時該格底板的右下角本身）。
            x0, y0, x1, y1 = safe_area_spec.safe_rect(
                *img.size, safe_area_spec.REPORTER_PROFILE
            )
            inset = compose._scaled_pixel(compose.HOLE_INSET, img.size[1])
            corner_pixel = img.convert("RGB").getpixel((x1 - inset - 2, y1 - inset - 2))
        background_pixel = (40, 60, 90)
        self.assertLess(
            sum(corner_pixel), sum(background_pixel) * 0.85,
            f"右下角底板錨點像素 {corner_pixel} 沒有比純色底片 {background_pixel} 暗，標籤可能沒貼上",
        )

    def test_named_portrait_via_web_endpoint_sets_disclaimer_kind_upstream(self):
        """中繼欄位也順帶釘住：apply_portrait_to_image_request 產出的
        disclaimer_kind 一路帶到 generate_image_raw 收到的請求上。"""
        captured = {}

        def fake_raw(req):
            captured["disclaimer_kind"] = req.disclaimer_kind
            return main.ImageGenerateResponse(
                image_data_base64=png_base64(1280, 720), mime_type="image/png", model="fake-model",
            )

        with patch.object(photo_lookup, "find_reference_photo", return_value=PHOTO), patch.object(
            main, "supports_reference_image", return_value=True
        ), patch.object(main, "generate_image_raw", side_effect=fake_raw):
            res = client.post(
                "/api/images/generate",
                json={"prompt": "一張新聞圖", "provider": "gpt", "portrait_subjects": ["某人"]},
                headers=self._headers(),
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(captured["disclaimer_kind"], "ai")


if __name__ == "__main__":
    unittest.main()
