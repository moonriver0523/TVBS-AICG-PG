"""YT 整點直播雙切的端點、消化與前端接線（WP2 第二階段，2026-09-08）。

守的紅線：
1. **雙切只由「整點＋第二標題有值」判定。** 國內外新聞直播／今日熱搜帶了第二標題也照舊走滿版。
2. **附圖要先拆到各自那一格。** 左格附了一張圖不能讓右格以為自己也有底圖、跳過畫面推導。
3. **AI 整張版遇到雙切要強制程式壓字並在回應說明。** 雙切的版面是程式拼的，沒有一張圖可以交給模型畫。
4. **雙切沒有追加修改。** source_image_base64 留空，兩格底圖走自己的欄位回來給「只改文字」。
"""
import base64
import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402

APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")

LEFT_TITLE = "尼泊爾洪災逾千死 家屬赴總理府"
RIGHT_TITLE = "直播帶貨美國爆紅 砸數十億美元"


def _png(size=(1200, 700), colour=(30, 60, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _completion(payload):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))]
    )


def _split_payload(**extra):
    payload = {
        "title": LEFT_TITLE,
        "title_second": RIGHT_TITLE,
        "layout": "hourly",
        "title_mode": "composite",
        "date_text": "2026/09/08",
        "time_text": "20:00",
    }
    payload.update(extra)
    return payload


class SplitDetectionTests(unittest.TestCase):
    def test_hourly_plus_second_title_is_split(self):
        self.assertTrue(editor_formats.yt_cover_is_split("hourly", RIGHT_TITLE))

    def test_empty_second_title_is_not_split(self):
        self.assertFalse(editor_formats.yt_cover_is_split("hourly", ""))
        self.assertFalse(editor_formats.yt_cover_is_split("hourly", "   "))

    def test_other_layouts_never_split(self):
        for layout in ("news", "hot"):
            self.assertFalse(editor_formats.yt_cover_is_split(layout, RIGHT_TITLE))


class PanelSplitTests(unittest.TestCase):
    """雙切請求拆成兩個單格請求：標題、附圖與既有底圖各歸各格。"""

    @staticmethod
    def _req(**extra):
        return main.YtCoverRequest(**_split_payload(**extra))

    def test_titles_go_to_their_own_panel(self):
        left, right = main.yt_split_panel_requests(self._req())
        self.assertEqual(left.title, LEFT_TITLE)
        self.assertEqual(right.title, RIGHT_TITLE)
        self.assertEqual((left.title_second, right.title_second), ("", ""))

    def test_one_asis_goes_to_the_left_panel_only(self):
        req = self._req(reference_images=[{"data_url": _data_url(_png()), "purpose": "asis"}])
        left, right = main.yt_split_panel_requests(req)
        self.assertEqual([r.purpose for r in left.reference_images], ["asis"])
        self.assertEqual(right.reference_images, [])

    def test_two_asis_go_one_per_panel(self):
        req = self._req(reference_images=[
            {"data_url": _data_url(_png(colour=(10, 10, 10))), "purpose": "asis"},
            {"data_url": _data_url(_png(colour=(200, 200, 200))), "purpose": "asis"},
        ])
        left, right = main.yt_split_panel_requests(req)
        self.assertEqual(len(left.reference_images), 1)
        self.assertEqual(len(right.reference_images), 1)
        self.assertNotEqual(left.reference_images[0].data_url, right.reference_images[0].data_url)

    def test_non_asis_references_are_shared_by_both_panels(self):
        req = self._req(reference_images=[{"data_url": _data_url(_png()), "purpose": "scene"}])
        left, right = main.yt_split_panel_requests(req)
        self.assertEqual([r.purpose for r in left.reference_images], ["scene"])
        self.assertEqual([r.purpose for r in right.reference_images], ["scene"])

    def test_second_background_fields_go_to_the_right_panel(self):
        req = self._req(
            background_image_base64="TEFB", background_is_ai=True,
            background_second_base64="UklG", background_second_is_ai=False,
        )
        left, right = main.yt_split_panel_requests(req)
        self.assertEqual(left.background_image_base64, "TEFB")
        self.assertTrue(left.background_is_ai)
        self.assertEqual(right.background_image_base64, "UklG")
        self.assertFalse(right.background_is_ai)


class SplitEndpointTests(unittest.TestCase):
    def test_two_asis_end_to_end_without_any_model(self):
        """兩格都有原圖放置：一次 API 都不打，兩組標題各壓各的。"""
        payload = _split_payload(reference_images=[
            {"data_url": _data_url(_png(colour=(10, 40, 10))), "purpose": "asis"},
            {"data_url": _data_url(_png(colour=(120, 90, 40))), "purpose": "asis"},
        ])
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["split"])
        self.assertEqual((data["line1"], data["line2"]), ("尼泊爾洪災逾千死", "家屬赴總理府"))
        self.assertEqual((data["second_line1"], data["second_line2"]), ("直播帶貨美國爆紅", "砸數十億美元"))
        self.assertFalse(data["background_is_ai"])
        self.assertFalse(data["background_second_is_ai"])
        with Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))) as image:
            self.assertEqual(image.size, compose.YT_CANVAS)

    def test_split_carries_no_refine_source_but_both_backgrounds(self):
        """雙切沒有追加修改：source 留空，兩格底圖走自己的欄位回來給「只改文字」。"""
        payload = _split_payload(reference_images=[
            {"data_url": _data_url(_png(colour=(10, 40, 10))), "purpose": "asis"},
            {"data_url": _data_url(_png(colour=(120, 90, 40))), "purpose": "asis"},
        ])
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        data = res.json()
        self.assertEqual(data["source_image_base64"], "")
        self.assertTrue(data["background_image_base64"])
        self.assertTrue(data["background_second_base64"])
        self.assertNotEqual(data["background_image_base64"], data["background_second_base64"])

    def test_ai_title_mode_is_forced_to_composite_with_a_notice(self):
        payload = _split_payload(title_mode="ai", reference_images=[
            {"data_url": _data_url(_png(colour=(10, 40, 10))), "purpose": "asis"},
            {"data_url": _data_url(_png(colour=(120, 90, 40))), "purpose": "asis"},
        ])
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["title_mode"], "composite")
        self.assertIn("程式壓字", data["notice"])

    def test_missing_panel_is_generated_as_a_square(self):
        """只附了左格的圖：右格生一張 1:1 底圖（半格塞 16:9 會被裁掉左右兩側）。"""
        payload = _split_payload(reference_images=[
            {"data_url": _data_url(_png(colour=(10, 40, 10))), "purpose": "asis"},
        ])
        seen = {}

        def fake_panel(visual, provider, references=None, subjects=None, english=None, excluded=None):
            seen["visual"] = visual
            return _png((900, 900), (80, 80, 120)), "fake-model"

        with patch.object(main, "_cover_panel_image", side_effect=fake_panel) as panel, \
             patch.object(main, "derive_yt_cover_plan", return_value={"visual": "直播主對著手機介紹商品"}):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(panel.call_count, 1, "只有沒附圖的那一格要生")
        self.assertEqual(seen["visual"], "直播主對著手機介紹商品")
        data = res.json()
        self.assertFalse(data["background_is_ai"], "左格是附圖，不標 AI示意圖")
        self.assertTrue(data["background_second_is_ai"], "右格是生的，要標 AI示意圖")

    def test_recompose_uses_both_backgrounds_without_any_model(self):
        left, right = _png((960, 1080), (10, 40, 10)), _png((960, 1080), (120, 90, 40))
        payload = _split_payload(
            background_image_base64=base64.b64encode(left).decode("ascii"),
            background_second_base64=base64.b64encode(right).decode("ascii"),
            title="改過的標題 第一則", title_second="改過的標題 第二則",
        )
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual((data["line1"], data["second_line1"]), ("改過的標題", "改過的標題"))
        self.assertEqual(data["model"], "yt-cover:recomposite")

    def test_news_layout_ignores_the_second_title(self):
        payload = _split_payload(layout="news", reference_images=[
            {"data_url": _data_url(_png()), "purpose": "asis"},
        ])
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["split"])
        self.assertEqual(data["second_line1"], "")

    def test_hourly_without_second_title_stays_full(self):
        payload = _split_payload(title_second="", reference_images=[
            {"data_url": _data_url(_png()), "purpose": "asis"},
        ])
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["split"])
        self.assertTrue(data["source_image_base64"], "滿版仍然可以追加修改")

    def test_title_too_long_returns_500_with_the_compose_hint(self):
        payload = _split_payload(title="這是一個長到塞不進半格的第一段標題 第二段")
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "_cover_panel_image", return_value=(_png((900, 900)), "fake")), \
             patch.object(main, "derive_yt_cover_plan", return_value={"visual": "示意畫面"}):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 500, res.text)
        self.assertIn("請縮短這一段", res.json()["detail"])


class HourlyDigestTests(unittest.TestCase):
    """消化 target yt_hourly：同十點的「先判 1／2 主題」，回 title／title_second。"""

    def _post(self, payload, target="yt_hourly"):
        with patch.object(main, "digest_completion", return_value=_completion(payload)) as dc:
            res = client.post(
                "/api/editor/cover-titles",
                json={"news_text": "一則夠長的新聞內文，足以觸發消化流程。", "target": target},
                headers=_headers(),
            )
        return res, dc

    def test_two_topics_fill_both_titles(self):
        res, dc = self._post({"topics": 2, "title": LEFT_TITLE, "title_second": RIGHT_TITLE})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["topics"], 2)
        self.assertEqual(data["title"], LEFT_TITLE)
        self.assertEqual(data["title_second"], RIGHT_TITLE)
        self.assertIn(
            editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT_HOURLY,
            dc.call_args.kwargs["system_prompt"],
        )

    def test_single_topic_leaves_the_second_title_empty(self):
        res, _ = self._post({"topics": 1, "title": LEFT_TITLE, "title_second": ""})
        data = res.json()
        self.assertEqual(data["topics"], 1)
        self.assertEqual(data["title_second"], "")

    def test_model_saying_one_but_giving_two_is_trimmed(self):
        res, _ = self._post({"topics": 1, "title": LEFT_TITLE, "title_second": RIGHT_TITLE})
        data = res.json()
        self.assertEqual(data["topics"], 1)
        self.assertEqual(data["title_second"], "")

    def test_model_saying_two_but_giving_one_falls_back_to_one(self):
        res, _ = self._post({"topics": 2, "title": LEFT_TITLE, "title_second": ""})
        self.assertEqual(res.json()["topics"], 1)

    def test_plain_yt_cover_target_is_unchanged(self):
        res, dc = self._post({"title": LEFT_TITLE}, target="yt_cover")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["title_second"], "")
        self.assertIn(
            editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT,
            dc.call_args.kwargs["system_prompt"],
        )


class FrontendWiringTests(unittest.TestCase):
    def test_second_title_field_and_indicator_exist(self):
        self.assertIn('id="ytCoverTitleSecond"', INDEX_HTML)
        self.assertIn('id="ytLayoutIndicator"', INDEX_HTML)
        self.assertIn('data-yt-layout="split"', INDEX_HTML)
        self.assertIn('oninput="updateYtLayoutIndicator()"', INDEX_HTML)

    def test_digest_button_asks_for_the_layout_specific_target(self):
        self.assertIn("handleCoverTitleDigest(ytCoverDigestTarget())", INDEX_HTML)
        self.assertIn("'yt_hourly' : 'yt_cover'", APP_JS)

    def test_layout_is_decided_by_the_second_title(self):
        self.assertIn("function ytLayoutNow()", APP_JS)
        self.assertIn("ytCoverTitleSecond", APP_JS)

    def test_download_short_name_has_a_split_variant(self):
        self.assertIn("yt_hourly_cover: { full: 'YT整點', split: 'YT整點雙切' }", APP_JS)
        self.assertIn("if (key === 'yt_hourly_cover') return name[ytLayoutNow()]", APP_JS)

    def test_fields_carry_the_second_title_only_for_hourly(self):
        self.assertIn("title_second: layout === 'hourly' ? val('ytCoverTitleSecond') : ''", APP_JS)

    def test_recompose_sends_both_backgrounds_for_split(self):
        self.assertIn("background_second_base64: split.right.base64", APP_JS)
        self.assertIn("state.ytSplitBackgrounds", APP_JS)

    def test_split_result_disables_refine(self):
        self.assertIn("resetRefineState(null, data)", APP_JS)

    def test_switching_format_clears_the_split_backgrounds(self):
        self.assertIn("state.ytSplitBackgrounds = null;", APP_JS)


if __name__ == "__main__":
    unittest.main()
