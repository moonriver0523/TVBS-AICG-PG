"""2026-09-22 使用者回報的三件事的守門測試。

B83 追加修改後「畫面來源」／「示意圖」整個消失
    `/api/images/refine` 從來沒有貼過標籤——`ImageRefineRequest` 沒有那三個欄位，
    `refine_image()` 也不呼叫 `apply_image_disclaimer`。標籤的正確性測試在
    `test_b70_f43_disclaimer.py`，這裡只釘「refine 這條路要把上一張貼的原樣帶過去」。

B84 檔位（density）漏送兩處，F38 的 2K 從來沒在那兩條路上成立過
    ① 第二／三頁的生圖送出點 ② 追加修改（前端與後端都沒有這格）。
    後端收到 `density=""` → `image_generation_size()` 的高解析度閘門永遠是 False。

F47 標籤事後改角落
    貼標籤全程是 Pillow，沒有理由為了挪一行字重生一張圖（還要付一次生圖費）。
"""

import ast
import base64
import inspect
import io
import os
import re
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("INTERNAL_API_KEY", "test-key")

import main  # noqa: E402
import safe_area_spec  # noqa: E402

APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")


def _png(size=(1280, 720), colour=(40, 60, 90)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _dimensions(image_base64: str) -> tuple[int, int]:
    with Image.open(io.BytesIO(base64.b64decode(image_base64))) as opened:
        return opened.size


class RefineCarriesTheLabelTests(unittest.TestCase):
    """B83：追加修改要把上一張實際貼的標籤帶過去。"""

    def test_the_request_model_has_the_three_fields(self):
        for field in ("disclaimer_kind", "disclaimer_source_text", "disclaimer_corner"):
            with self.subTest(field=field):
                self.assertIn(field, main.ImageRefineRequest.model_fields)

    def test_refine_hands_them_to_the_generate_request(self):
        source = inspect.getsource(main.refine_image)
        self.assertIn("disclaimer_source_text=", source)
        self.assertIn("disclaimer_corner=req.disclaimer_corner", source)

    def test_a_face_swap_cannot_keep_a_source_credit(self):
        """具名換臉之後畫面上那張臉是模型畫的，來源名必須被丟掉。

        不丟的話使用者只要把來源名留在輸入框，一張換過臉的圖就會掛上
        「畫面來源：○○○」——那是對觀眾說謊，也是 F43 互斥規則要擋的事。
        """
        source = inspect.getsource(main.refine_image)
        self.assertIn('"" if replacement_person else req.disclaimer_source_text', source)


class DensityReachesEveryPathTests(unittest.TestCase):
    """B84：F38 的 2K 閘門要在每一條生圖路徑上都判得出來。"""

    def test_the_refine_request_model_has_density(self):
        self.assertIn("density", main.ImageRefineRequest.model_fields)

    def test_refine_passes_density_through(self):
        self.assertIn("density=req.density", inspect.getsource(main.refine_image))

    def test_every_frontend_image_payload_sends_density(self):
        """四個會產圖的送出點：第一頁生成、第二／三頁生成、追加修改、標籤重貼。

        漏掉任何一個，那條路就靜靜掉回 1K——畫面上看不出來，要量成品尺寸才知道。
        """
        self.assertEqual(APP_JS.count("density: state.density"), 3)
        self.assertEqual(
            APP_JS.count("density: refineParameters.density"), 1,
            "標籤重貼必須沿用原成品密度，不可讀當下 state",
        )

    def test_the_high_res_gate_actually_fires_for_a_dense_editor_job(self):
        req = main.ImageGenerateRequest(
            prompt="x",
            provider="gpt",
            aspect_ratio="16:9",
            density="standard",
            safe_frame_profile=safe_area_spec.EDITOR_PROFILE,
        )
        provider_size, canvas = main.image_generation_size(req)
        self.assertEqual(provider_size, "2560x1440")
        self.assertEqual(canvas, (2560, 1440))

    def test_an_empty_density_silently_drops_to_the_base_canvas(self):
        """這就是漏送那格的後果——留著當反例，讓人一眼看出漏送有多安靜。"""
        req = main.ImageGenerateRequest(
            prompt="x",
            provider="gpt",
            aspect_ratio="16:9",
            density="",
            safe_frame_profile=safe_area_spec.EDITOR_PROFILE,
        )
        _, canvas = main.image_generation_size(req)
        self.assertEqual(canvas, safe_area_spec.BASE_CANVAS)


class RestampTests(unittest.TestCase):
    """F47：標籤改角落不重新生圖。"""

    def _request(self, corner: str, **over) -> main.ImageRestampRequest:
        payload = dict(
            source_image_base64=_png(),
            source_mime_type="image/png",
            provider="gpt",
            aspect_ratio="16:9",
            safe_frame=False,
            safe_frame_profile=safe_area_spec.REPORTER_PROFILE,
            disclaimer_kind="source",
            disclaimer_source_text="美聯社",
            disclaimer_corner=corner,
        )
        payload.update(over)
        return main.ImageRestampRequest(**payload)

    def test_it_never_calls_a_generation_model(self):
        """整支函式體裡不能出現任何生圖呼叫——這條路的賣點就是零成本。"""
        source = inspect.getsource(main.restamp_disclaimer)
        for forbidden in ("generate_image_raw", "generate_via_openrouter", "generate_gpt_image"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_two_corners_give_two_different_pictures_of_the_same_size(self):
        lower = main.restamp_disclaimer(self._request("lower_right"))
        upper = main.restamp_disclaimer(self._request("upper_left"))
        self.assertNotEqual(lower.image_data_base64, upper.image_data_base64)
        self.assertEqual(
            _dimensions(lower.image_data_base64), _dimensions(upper.image_data_base64)
        )

    def test_it_reports_back_what_it_stamped(self):
        result = main.restamp_disclaimer(self._request("upper_right"))
        self.assertEqual(result.disclaimer_kind, "source")
        self.assertEqual(result.disclaimer_source_text, "美聯社")
        self.assertEqual(result.disclaimer_corner, "upper_right")

    def test_the_editor_off_path_follows_the_density_split(self):
        """D24（2026-09-22 使用者裁決，同日修正為「只在字多 字超多生效」）。

        非字多檔仍是 1748×924（對位框本身，2026-08-19）；字多／字超多不後製，
        進去多大出來就多大。重貼標籤必須跟生圖給出同一種尺寸，否則挪一下標籤
        就換了一張不同尺寸的圖。
        """
        light = main.restamp_disclaimer(
            self._request(
                "lower_left",
                safe_frame=False,
                safe_frame_profile=safe_area_spec.EDITOR_PROFILE,
            )
        )
        self.assertEqual(_dimensions(light.image_data_base64), (1748, 924))
        dense = main.restamp_disclaimer(
            self._request(
                "lower_left",
                density="standard",
                safe_frame=False,
                safe_frame_profile=safe_area_spec.EDITOR_PROFILE,
            )
        )
        self.assertEqual(_dimensions(dense.image_data_base64), (1280, 720))

    def test_the_editor_on_path_still_lands_on_the_thin_frame_canvas(self):
        """ON 那檔沒被 D24 動到：仍是 2% 薄框、輸出完整畫布。"""
        result = main.restamp_disclaimer(
            self._request(
                "lower_left",
                safe_frame=True,
                safe_frame_profile=safe_area_spec.EDITOR_PROFILE,
            )
        )
        self.assertEqual(
            _dimensions(result.image_data_base64), safe_area_spec.BASE_CANVAS
        )

    def test_a_dense_editor_job_restamps_at_the_high_res_canvas(self):
        """B84 的另一半：少帶 density 會把一張 2K 成品悄悄重算成 1K。

        用 ON 那檔驗——OFF 之後不置框，畫布參數根本不會被用到（D24）。
        """
        result = main.restamp_disclaimer(
            self._request(
                "lower_left",
                density="maximum",
                safe_frame=True,
                safe_frame_profile=safe_area_spec.EDITOR_PROFILE,
                source_image_base64=_png((2560, 1440)),
            )
        )
        self.assertEqual(_dimensions(result.image_data_base64), (2560, 1440))

    def test_it_refuses_a_broadcast_hole_job(self):
        """播出鏡面的浮水印版位綁在挖空框上，不吃 disclaimer_corner——寧可 400。"""
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            main.restamp_disclaimer(self._request("lower_left", broadcast_hole="left"))
        self.assertEqual(caught.exception.status_code, 400)

    def test_the_frontend_calls_it_when_the_corner_changes(self):
        self.assertIn("restampDisclaimer()", APP_JS)
        corner_fn = APP_JS.split("function setDisclaimerCorner(corner)")[1][:600]
        self.assertIn("restampDisclaimer()", corner_fn)

    def test_the_frontend_does_nothing_when_there_is_no_stamped_result(self):
        """沒有成品、或那張根本沒貼標籤時要安靜地不做事，不是報錯。"""
        body = APP_JS.split("async function restampDisclaimer()")[1][:400]
        self.assertIn("if (!applied.kind || !state.refineSource) return;", body)


class ExactlyOneLabelTests(unittest.TestCase):
    """B86：未置框那條路（記者＋安全框 OFF）不能被貼上第二枚標籤。

    `finalize_image_result` 在 `safe_frame=False` 時提早 return，`source_image_base64`
    留空，前端 `refineSourceFromResponse()` 因此退而取**成品本身**——而成品此刻
    已經有一枚標籤。那張再送進 refine／restamp 就會多出第二枚（舊角落一枚、
    新角落一枚）。`ImageRestampRequest` 的 docstring 早就寫了「再貼會變兩枚」，
    但沒有任何東西擋住它。
    """

    def _stamped_unframed(self, corner: str = "lower_right") -> main.ImageGenerateResponse:
        raw = main.ImageGenerateResponse(
            image_data_base64=_png(), mime_type="image/png", model="test"
        )
        req = main.ImageGenerateRequest(
            prompt="x",
            aspect_ratio="16:9",
            safe_frame=False,
            safe_frame_profile=safe_area_spec.REPORTER_PROFILE,
            disclaimer_kind="source",
            disclaimer_source_text="美聯社",
            disclaimer_corner=corner,
        )
        result = main.finalize_image_result(
            raw, aspect_ratio="16:9", safe_frame=False,
            profile=safe_area_spec.REPORTER_PROFILE,
        )
        return main.apply_image_disclaimer(
            result, req, profile=safe_area_spec.REPORTER_PROFILE
        )

    def test_an_unframed_stamped_result_still_hands_back_a_clean_source(self):
        stamped = self._stamped_unframed()
        self.assertTrue(stamped.source_image_base64, "貼過標籤就必須留下貼之前那張")
        self.assertNotEqual(stamped.source_image_base64, stamped.image_data_base64)
        self.assertEqual(stamped.source_image_base64, _png())

    def test_restamping_at_the_same_corner_reproduces_the_same_picture(self):
        """同角落重貼要跟原本那張**逐像素相同**——不同就代表貼了兩枚。"""
        stamped = self._stamped_unframed("lower_right")
        again = main.restamp_disclaimer(
            main.ImageRestampRequest(
                source_image_base64=stamped.source_image_base64,
                source_mime_type=stamped.source_mime_type,
                aspect_ratio="16:9",
                safe_frame=False,
                safe_frame_profile=safe_area_spec.REPORTER_PROFILE,
                disclaimer_kind="source",
                disclaimer_source_text="美聯社",
                disclaimer_corner="lower_right",
            )
        )
        self.assertEqual(again.image_data_base64, stamped.image_data_base64)

    def test_the_framed_path_keeps_its_own_pre_frame_original(self):
        """置框那條路的 source 是**置框前**原圖，補寫不能把它蓋掉。"""
        raw = main.ImageGenerateResponse(
            image_data_base64=_png(), mime_type="image/png", model="test"
        )
        req = main.ImageGenerateRequest(
            prompt="x",
            aspect_ratio="16:9",
            safe_frame=True,
            safe_frame_profile=safe_area_spec.REPORTER_PROFILE,
            disclaimer_kind="ai",
            disclaimer_corner="upper_left",
        )
        framed = main.finalize_image_result(
            raw, aspect_ratio="16:9", safe_frame=True,
            profile=safe_area_spec.REPORTER_PROFILE,
        )
        stamped = main.apply_image_disclaimer(
            framed, req, profile=safe_area_spec.REPORTER_PROFILE
        )
        self.assertEqual(stamped.source_image_base64, _png(), "置框前原圖不可被覆寫")


class TheOldGapIsDocumentedTests(unittest.TestCase):
    """把「以前為什麼會漏」釘住，避免有人依樣畫葫蘆再加一條沒接上的路徑。"""

    def test_every_post_endpoint_that_returns_an_image_response_stamps_or_says_why(self):
        """回 ImageGenerateResponse 的端點，要嘛貼標籤、要嘛在原始碼裡講明為什麼不貼。

        B70／B83 兩次事故是同一種：新增一條會交出成品的路徑，卻沒有接上貼標籤
        那一半。這裡用 AST 找出所有回 ImageGenerateResponse 的 POST 端點逐一檢查。
        """
        main_src = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(main_src)
        checked = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            returns = getattr(node.returns, "id", "")
            if returns != "ImageGenerateResponse":
                continue
            is_post = any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr == "post"
                for d in node.decorator_list
            )
            if not is_post:
                continue
            checked.add(node.name)
            src = ast.get_source_segment(main_src, node) or ""
            with self.subTest(endpoint=node.name):
                self.assertIn(
                    "disclaimer", src,
                    f"{node.name} 交出成品卻完全沒提標籤——B70／B83 的斷線長這樣",
                )
        self.assertIn("refine_image", checked)
        self.assertIn("restamp_disclaimer", checked)

    def test_the_refine_docstring_no_longer_claims_it_skips_post_processing(self):
        """refine 現在會後製（置框＋貼標籤），註解不能還停在「只改圖」。"""
        source = inspect.getsource(main.refine_image)
        self.assertIn("B83", source)


if __name__ == "__main__":
    unittest.main()
