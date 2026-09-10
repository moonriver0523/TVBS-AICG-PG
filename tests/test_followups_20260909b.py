"""2026-09-09 第四批使用者回饋的守門測試（第 2、5 項）。

第 1、3、4、6、7、8 項在 test_app_version／test_followups_20260909／
test_yt_title_parity／test_stamp_off_guard 裡。
"""

import json
import os
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402


def _response(payload: dict):
    """digest_completion 的最小替身：只要走得到 .choices[0].message.content。"""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )


class VstripTitleDigestTests(unittest.TestCase):
    """第 2 項：直標新增 AI 自動消化——貼一段文字，出兩段標題＋判定來源。"""

    def prompt(self) -> str:
        return editor_formats.vstrip_title_digest_system(
            compose.VSTRIP_MAIN_MAX_CELLS, compose.VSTRIP_SUB_MAX_CELLS
        )

    def test_the_cell_limits_come_from_compose_not_a_copy(self):
        """格數上限手抄一份，遲早跟版面對不上（compose 才是唯一真相源）。"""
        text = self.prompt()
        self.assertIn(f"at most {compose.VSTRIP_MAIN_MAX_CELLS} cells", text)
        self.assertIn(f"at most {compose.VSTRIP_SUB_MAX_CELLS} cells", text)

    def test_the_prompt_explains_that_length_is_counted_in_cells(self):
        """直排的長度單位是格不是字元：連續英數字併成一格（compose._vertical_cells）。"""
        text = self.prompt()
        self.assertIn("PRINTED CELLS, not characters", text)
        self.assertIn("is ONE cell together", text)
        self.assertEqual(len(compose._vertical_cells("破30度")), 3)

    def test_the_prompt_handles_a_foreign_wire_despatch(self):
        """使用者給的範例就是一則路透通稿：英文 slug、場次、Restrictions。"""
        text = self.prompt()
        self.assertIn("raw foreign wire despatch", text)
        self.assertIn("Traditional Chinese, Taiwan usage", text)

    def test_the_source_comes_from_the_credit_requirement(self):
        """範例的來源寫在「Must credit George W. Bush Presidential Center」。"""
        text = self.prompt()
        self.assertIn("Must credit", text)
        self.assertIn("return an empty string rather than guessing", text)

    def test_the_model_must_not_write_the_prefix_itself(self):
        """「畫面來源：」由 compose.vstrip_source_text 自動補，補兩次很醜。"""
        self.assertIn("Do NOT write 「畫面來源」", self.prompt())
        self.assertEqual(compose.vstrip_source_text("美聯社"), "畫面來源：美聯社")

    def test_the_endpoint_fills_all_three_fields(self):
        payload = {
            "title": "布希出席九一一週年活動",
            "title_second": "達拉斯布希總統中心紀念廿五週年",
            "source": "布希總統中心",
        }
        request = main.CoverTitleDigestRequest(
            news_text="US: TX SEPT 11 ANNIVERSARY BUSH CENTER ...", target="yt_vstrip"
        )
        with patch.object(main, "digest_completion", return_value=_response(payload)):
            result = main.editor_cover_titles(request)
        self.assertEqual(result.title, payload["title"])
        self.assertEqual(result.title_second, payload["title_second"])
        self.assertEqual(result.source_text, payload["source"])
        # 直標不是十點／整點，不該回主題數的判定
        self.assertEqual(result.title_left, "")

    def test_the_endpoint_uses_the_vstrip_prompt_and_schema(self):
        request = main.CoverTitleDigestRequest(news_text="x" * 30, target="yt_vstrip")
        payload = {"title": "甲", "title_second": "乙", "source": ""}
        with patch.object(main, "digest_completion", return_value=_response(payload)) as call:
            main.editor_cover_titles(request)
        kwargs = call.call_args.kwargs
        self.assertIn("vertical caption strip", kwargs["system_prompt"])
        self.assertEqual(kwargs["schema"], editor_formats.VSTRIP_TITLE_DIGEST_SCHEMA)


class BottomBandMarkerTests(unittest.TestCase):
    """`<底帶>` 是新標記，凡是「認得標記」的地方都要跟著認得它。"""

    def test_verbatim_fidelity_strips_the_marker_like_the_stamp_one(self):
        """不消化 ＋ 播出鏡面 ＋ 蓋章 OFF 是合法組合。標記沒被剝掉的話，
        「底帶」兩個字會被當成多出來的內文，逐字守門員判不合格 → 五次重試 → 502。"""
        self.assertEqual(
            main.verbatim_fidelity_problem("[標題] 甲\n<底帶> 丁", "甲丁"), ""
        )

    def test_the_marker_is_listed_explicitly_not_just_by_the_brackets(self):
        self.assertIn("<底帶>", main._VERBATIM_MARKER_RE.pattern)


class SlashInTitleTests(unittest.TestCase):
    """第 6 項：整條路徑（分段 → 超寬拆行）都不准把日期切開。"""

    TITLE = "古羅馬圖拉真浴場 9/12開放民眾參觀"

    def test_the_date_survives_the_whole_pipeline(self):
        for full_width in (True, False):
            with self.subTest(full_width=full_width):
                lines = compose.cover_title_lines(self.TITLE, full_width=full_width)
                self.assertTrue(any("9/12" in line for line in lines), lines)
                self.assertNotIn("9", [line.strip() for line in lines])

    def test_a_real_separator_still_separates(self):
        self.assertEqual(
            editor_formats.split_cover_title("羅馬/浴場/開放"), ["羅馬", "浴場", "開放"]
        )

    def test_other_numeric_separators_are_protected_too(self):
        for text in ("跌破5.5元今天收盤", "晚間20:00開播特別報導"):
            with self.subTest(text=text):
                head, tail = compose._split_line_near_middle(text)
                self.assertNotIn(head[-1] + tail[0], ("5.", ".5", "0:", ":0"))


class DigestLatencyTests(unittest.TestCase):
    """第 5 項：播出鏡面消化太久、偶有逾時沒生成。

    這個 repo 自己量過：正文 token 很穩（856-1361），爆的是思考（603-4873），而且
    思考量跟規則條數走。所以治法是把思考封頂，不是繼續刪使用者驗收過的規則。
    """

    def test_the_reasoning_cap_leaves_room_for_the_body(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), \
                patch.object(main, "DIGEST_REASONING_MAX_TOKENS", 2000):
            body = main.digest_reasoning_body(main.DIGEST_MAX_TOKENS)
        budget = body["reasoning"]["max_tokens"]
        self.assertEqual(budget, 2000)
        # 觀測到的正文最大值是 1361 token，剩下的空間要明顯大於它
        self.assertGreater(main.DIGEST_MAX_TOKENS - budget, 1361)

    def test_a_tight_budget_drops_the_cap_instead_of_starving_the_body(self):
        """預算小到留不下正文空間時就不要設思考上限——寧可慢，不要吐半截 JSON。"""
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), \
                patch.object(main, "DIGEST_REASONING_MAX_TOKENS", 2000):
            self.assertEqual(main.digest_reasoning_body(3000), {})

    def test_non_openrouter_backends_send_nothing(self):
        """reasoning 是 OpenRouter 的統一欄位，送給原生 OpenAI 會直接 400。"""
        for backend in ("native", "gemini"):
            with self.subTest(backend=backend):
                with patch.object(main, "DIGEST_BACKEND", backend):
                    self.assertEqual(main.digest_reasoning_body(6000), {})

    def test_setting_zero_disables_it_entirely(self):
        with patch.object(main, "DIGEST_BACKEND", "openrouter"), \
                patch.object(main, "DIGEST_REASONING_MAX_TOKENS", 0):
            self.assertEqual(main.digest_reasoning_body(6000), {})

    def test_the_deadline_stays_under_the_cloud_run_request_limit(self):
        """Cloud Run 的請求上限是 300 秒，超過就是連錯誤訊息都沒有的斷線。
        重試迴圈必須在那之前收手，才有機會回一句看得懂的話。"""
        self.assertLess(main.DIGEST_DEADLINE_SECONDS, 300)
        self.assertGreater(main.DIGEST_DEADLINE_SECONDS, 60)


if __name__ == "__main__":
    unittest.main()
