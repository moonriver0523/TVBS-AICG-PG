"""YT 整點直播「雙則」：一張封面帶兩則新聞（2026-09-08 WP2）。

版面：**同一張底圖、上下兩行標題**——上白＝第一則、下黃＝第二則，每一行是一則新聞的
完整標題（不是同一句拆兩段）。底圖由左右兩張羽化拼成一張。

守的紅線：
1. **兩行不拆段。** 雙則走的是 title／title_second 原樣兩行，不能再被 split_live_title 切。
2. **接縫不能有硬邊。** 標題橫跨全寬，中間任何一條直線都會從字中間穿過去。
3. **附圖要先拆到各自那一格。** 左格附了一張圖不能讓右格以為自己也有底圖、跳過畫面推導。
4. **每行 18 字上限（2026-09-08 晚由 14 放寬）只套用在雙則。** 單則是同一句拆兩段，長度受原標題限制，行為不能變。
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

WIDTH, HEIGHT = compose.YT_CANVAS
FIRST = "尼泊爾洪災逾1380死家屬抗議"
SECOND = "直播帶貨美國爆紅砸數十億"


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


def _payload(**extra):
    body = {
        "title": FIRST,
        "title_second": SECOND,
        "layout": "hourly",
        "title_mode": "composite",
        "date_text": "2026/09/08",
        "time_text": "20:00",
    }
    body.update(extra)
    return body


class DualDetectionTests(unittest.TestCase):
    def test_hourly_plus_second_title_is_dual(self):
        self.assertTrue(editor_formats.yt_cover_is_dual("hourly", SECOND))

    def test_empty_second_title_is_not_dual(self):
        self.assertFalse(editor_formats.yt_cover_is_dual("hourly", ""))
        self.assertFalse(editor_formats.yt_cover_is_dual("hourly", "   "))

    def test_other_layouts_never_dual(self):
        for layout in ("news", "hot"):
            self.assertFalse(editor_formats.yt_cover_is_dual(layout, SECOND))


class SeamBlendTests(unittest.TestCase):
    """羽化拼接：中線附近是兩側顏色的漸變，整張圖沒有一條垂直高對比線。"""

    LEFT = _png((1000, 1000), (40, 70, 140))
    RIGHT = _png((1000, 1000), (200, 150, 60))

    def _blended(self, **kwargs) -> Image.Image:
        raw = compose.blend_backgrounds_lr(self.LEFT, self.RIGHT, **kwargs)
        return Image.open(io.BytesIO(raw)).convert("RGB")

    def test_output_is_full_hd(self):
        self.assertEqual(self._blended().size, compose.YT_CANVAS)

    def test_each_side_keeps_its_own_colour_away_from_the_seam(self):
        image = self._blended()
        row = HEIGHT // 2
        self.assertEqual(image.getpixel((60, row)), (40, 70, 140))
        self.assertEqual(image.getpixel((WIDTH - 60, row)), (200, 150, 60))

    def test_seam_is_a_gradient_between_the_two_sides(self):
        """羽化帶裡每一欄的紅色分量要單調遞增（藍→棕），不是一步跳過去。"""
        image = self._blended()
        row = HEIGHT // 2
        band = round(WIDTH * compose.YT_SEAM_FEATHER_RATIO)
        seam = round(WIDTH * compose.YT_SEAM_CENTRE_RATIO)
        reds = [image.getpixel((x, row))[0] for x in range(seam - band, seam + band)]
        self.assertGreater(reds[-1], reds[0])
        # 至少 30 個不同的紅色值＝真的是漸變，不是兩塊色
        self.assertGreater(len(set(reds)), 30)

    def test_no_hard_vertical_edge_anywhere(self):
        """相鄰兩欄的差距不得超過門檻——split_canvas 那種白線會是 200 以上。"""
        image = self._blended()
        row = HEIGHT // 2
        cols = [image.getpixel((x, row)) for x in range(WIDTH)]
        worst = max(
            max(abs(a - b) for a, b in zip(cols[x], cols[x + 1]))
            for x in range(WIDTH - 1)
        )
        self.assertLess(worst, 12, f"接縫有硬邊，相鄰欄最大落差 {worst}")

    def test_seam_carries_a_slight_dark_shade(self):
        """接縫疊一層淡的深色暈：中線比兩側同位置的純混色暗一些。"""
        shaded = self._blended()
        plain = self._blended(shade_alpha=0)
        row = HEIGHT // 2
        seam = round(WIDTH * compose.YT_SEAM_CENTRE_RATIO)
        self.assertLess(sum(shaded.getpixel((seam, row))), sum(plain.getpixel((seam, row))))
        self.assertLessEqual(compose.YT_SEAM_SHADE_ALPHA, 64, "深色暈不得超過 25%")

    def test_seam_centre_defaults_to_the_middle(self):
        self.assertEqual(compose.YT_SEAM_CENTRE_RATIO, 0.5)

    def test_seam_centre_is_adjustable_within_bounds(self):
        left_ish = self._blended(seam_ratio=0.4)
        row = HEIGHT // 2
        # 接縫左移之後，正中間那一欄已經完全是右圖的顏色
        self.assertEqual(left_ish.getpixel((WIDTH // 2, row)), (200, 150, 60))
        for bad in (0.2, 0.8):
            with self.subTest(bad=bad), self.assertRaises(compose.ComposeError):
                self._blended(seam_ratio=bad)


class HourlyLineLimitTests(unittest.TestCase):
    BG = _png((1920, 1080), (20, 20, 20))

    def _cover(self, line1, line2, **kwargs):
        return compose.compose_yt_hourly_cover(
            self.BG, line1=line1, line2=line2, date_text="2026/09/08", **kwargs
        )

    def test_dual_rejects_a_line_over_the_cap(self):
        with self.assertRaises(compose.ComposeError) as ctx:
            self._cover("一二三四五六七八九十一二三四五六七八九", SECOND,
                        line_max_chars=compose.YT_HOURLY_LINE_MAX_CHARS)
        self.assertIn("請縮短這一行", str(ctx.exception))

    def test_half_width_digits_count_as_half(self):
        """「尼泊爾洪災逾1380死家屬抗議」len() 是 15，排出來只有 13 個全形字寬。"""
        self.assertEqual(len(FIRST), 15)
        self.assertLessEqual(compose.title_display_width(FIRST), compose.YT_HOURLY_LINE_MAX_CHARS)
        self._cover(FIRST, SECOND, line_max_chars=compose.YT_HOURLY_LINE_MAX_CHARS)

    def test_single_mode_has_no_character_cap(self):
        """單則不帶 line_max_chars，行為與 WP2 之前一模一樣。"""
        self._cover("一二三四五六七八九十一二三四五六七八九", "第二段")

    def test_a_line_that_cannot_fit_at_all_still_raises(self):
        with self.assertRaises(compose.ComposeError) as ctx:
            self._cover("一" * 30, "第二段")
        self.assertIn("請縮短這一行", str(ctx.exception))


class DualPanelSplitTests(unittest.TestCase):
    @staticmethod
    def _req(**extra):
        return main.YtCoverRequest(**_payload(**extra))

    def test_titles_go_to_their_own_panel(self):
        left, right = main.yt_dual_panel_requests(self._req())
        self.assertEqual((left.title, right.title), (FIRST, SECOND))
        self.assertEqual((left.title_second, right.title_second), ("", ""))

    def test_one_asis_goes_to_the_left_panel_only(self):
        req = self._req(reference_images=[{"data_url": _data_url(_png()), "purpose": "asis"}])
        left, right = main.yt_dual_panel_requests(req)
        self.assertEqual([r.purpose for r in left.reference_images], ["asis"])
        self.assertEqual(right.reference_images, [])

    def test_two_asis_go_one_per_panel(self):
        req = self._req(reference_images=[
            {"data_url": _data_url(_png(colour=(10, 10, 10))), "purpose": "asis"},
            {"data_url": _data_url(_png(colour=(200, 200, 200))), "purpose": "asis"},
        ])
        left, right = main.yt_dual_panel_requests(req)
        self.assertNotEqual(left.reference_images[0].data_url, right.reference_images[0].data_url)

    def test_non_asis_references_are_shared(self):
        req = self._req(reference_images=[{"data_url": _data_url(_png()), "purpose": "scene"}])
        left, right = main.yt_dual_panel_requests(req)
        self.assertEqual([r.purpose for r in left.reference_images], ["scene"])
        self.assertEqual([r.purpose for r in right.reference_images], ["scene"])


class DualEndpointTests(unittest.TestCase):
    def test_two_asis_end_to_end_without_any_model(self):
        payload = _payload(reference_images=[
            {"data_url": _data_url(_png(colour=(10, 40, 10))), "purpose": "asis"},
            {"data_url": _data_url(_png(colour=(120, 90, 40))), "purpose": "asis"},
        ])
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["dual"])
        # 兩行原樣，不再依空格拆段
        self.assertEqual((data["line1"], data["line2"]), (FIRST, SECOND))
        self.assertTrue(data["source_image_base64"], "雙則的底圖是一張，追加修改照樣可用")
        with Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))) as image:
            self.assertEqual(image.size, compose.YT_CANVAS)

    def test_titles_with_spaces_are_not_split_in_dual_mode(self):
        payload = _payload(title="第一則 有空格", title_second="第二則 也有空格",
                           reference_images=[
                               {"data_url": _data_url(_png()), "purpose": "asis"},
                               {"data_url": _data_url(_png(colour=(9, 9, 9))), "purpose": "asis"},
                           ])
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        data = res.json()
        self.assertEqual((data["line1"], data["line2"]), ("第一則 有空格", "第二則 也有空格"))

    def test_missing_panel_is_generated_as_a_square(self):
        payload = _payload(reference_images=[
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
        self.assertTrue(res.json()["background_is_ai"], "有一格是生的就要標 AI示意圖")

    def test_recompose_reuses_the_blended_background(self):
        blended = _png((1920, 1080), (60, 60, 60))
        payload = _payload(
            background_image_base64=base64.b64encode(blended).decode("ascii"),
            title="改過的第一則", title_second="改過的第二則",
        )
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")), \
             patch.object(main, "derive_yt_cover_plan", side_effect=AssertionError("不該打文字模型")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual((data["line1"], data["line2"]), ("改過的第一則", "改過的第二則"))
        self.assertEqual(data["model"], "yt-cover:recomposite")

    def test_ai_title_mode_feeds_both_lines_to_the_template(self):
        seen = {}

        def fake_full(req, lines, visual, subjects, english, excluded=None):
            seen["lines"] = lines
            return _png((1920, 1080)), "image/png", "fake-model"

        with patch.object(main, "_yt_cover_full_image", side_effect=fake_full), \
             patch.object(main, "derive_yt_cover_plan", return_value={"visual": "示意畫面"}):
            res = client.post("/api/editor/yt-cover", json=_payload(title_mode="ai"), headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(seen["lines"], (FIRST, SECOND))
        self.assertEqual(res.json()["title_mode"], "ai", "雙則不再強制程式壓字")

    def test_line_over_the_cap_returns_400_before_any_image_is_generated(self):
        """審查必修（2026-09-08）：字數擋要在生底圖之前，不能燒完兩次生圖才回錯。"""
        payload = _payload(title="一二三四五六七八九十一二三四五六七八九")
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")),              patch.object(main, "yt_dual_panel_plan", side_effect=AssertionError("不該推導")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("第一標題超過 18 字", res.json()["detail"])
        self.assertIn("請縮短這一行", res.json()["detail"])

    def test_second_title_over_the_cap_names_the_second_line(self):
        payload = _payload(title_second="一二三四五六七八九十一二三四五六七八九")
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("第二標題超過 18 字", res.json()["detail"])

    def test_frontend_pre_checks_the_cap_before_sending(self):
        js = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("const YT_HOURLY_LINE_MAX_CHARS = 18;", js)
        self.assertRegex(js, r"function displayWidth\(text\)")
        self.assertRegex(js, r"displayWidth\(t\) > YT_HOURLY_LINE_MAX_CHARS")
        self.assertNotIn("async function handleAIDigestion", js)
        self.assertRegex(js, r"state\.tenCoverBackground = null;[\s\S]{0,300}state\.refineSource = null;")

    def test_news_layout_ignores_the_second_title(self):
        payload = _payload(layout="news", title="新北診所爆C肝群聚 11人確診",
                           reference_images=[{"data_url": _data_url(_png()), "purpose": "asis"}])
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["dual"])
        self.assertEqual((data["line1"], data["line2"]), ("新北診所爆C肝群聚", "11人確診"))

    def test_hourly_without_second_title_still_splits_on_the_space(self):
        payload = _payload(title_second="", title="新北診所爆C肝群聚 11人確診",
                           reference_images=[{"data_url": _data_url(_png()), "purpose": "asis"}])
        with patch.object(main, "generate_image_raw", side_effect=AssertionError("不該生圖")):
            res = client.post("/api/editor/yt-cover", json=payload, headers=_headers())
        data = res.json()
        self.assertFalse(data["dual"])
        self.assertEqual((data["line1"], data["line2"]), ("新北診所爆C肝群聚", "11人確診"))


class HourlyDigestTests(unittest.TestCase):
    def _post(self, payload, target="yt_hourly"):
        with patch.object(main, "digest_completion", return_value=_completion(payload)) as dc:
            res = client.post(
                "/api/editor/cover-titles",
                json={"news_text": "一則夠長的新聞內文，足以觸發消化流程。", "target": target},
                headers=_headers(),
            )
        return res, dc

    def test_two_topics_fill_both_titles(self):
        res, dc = self._post({"topics": 2, "title": FIRST, "title_second": SECOND})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual((data["topics"], data["title"], data["title_second"]), (2, FIRST, SECOND))
        self.assertIn(
            editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT_HOURLY,
            dc.call_args.kwargs["system_prompt"],
        )

    def test_prompt_says_two_stories_are_one_line_each_capped_at_18(self):
        prompt = editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT_HOURLY
        self.assertIn("ONE full-width line", prompt)
        self.assertIn("at most 18 characters", prompt)

    def test_single_topic_leaves_the_second_title_empty(self):
        res, _ = self._post({"topics": 1, "title": "新北診所爆C肝群聚 11人確診", "title_second": ""})
        data = res.json()
        self.assertEqual(data["topics"], 1)
        self.assertEqual(data["title_second"], "")

    def test_model_saying_one_but_giving_two_is_trimmed(self):
        res, _ = self._post({"topics": 1, "title": FIRST, "title_second": SECOND})
        self.assertEqual(res.json()["topics"], 1)
        self.assertEqual(res.json()["title_second"], "")

    def test_model_saying_two_but_giving_one_falls_back(self):
        res, _ = self._post({"topics": 2, "title": FIRST, "title_second": ""})
        self.assertEqual(res.json()["topics"], 1)

    def test_plain_yt_cover_target_is_unchanged(self):
        res, dc = self._post({"title": FIRST}, target="yt_cover")
        self.assertEqual(res.json()["title_second"], "")
        self.assertIn(editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT, dc.call_args.kwargs["system_prompt"])


class FrontendWiringTests(unittest.TestCase):
    def test_second_title_field_and_indicator_exist(self):
        self.assertIn('id="ytCoverTitleSecond"', INDEX_HTML)
        self.assertIn('id="ytLayoutIndicator"', INDEX_HTML)
        self.assertIn('data-yt-layout="dual"', INDEX_HTML)
        self.assertIn('data-yt-layout="single"', INDEX_HTML)
        self.assertIn('oninput="updateYtLayoutIndicator()"', INDEX_HTML)

    def test_digest_button_asks_for_the_layout_specific_target(self):
        self.assertIn("handleCoverTitleDigest(ytCoverDigestTarget())", INDEX_HTML)
        self.assertIn("'yt_hourly' : 'yt_cover'", APP_JS)

    def test_layout_is_decided_by_the_second_title(self):
        self.assertIn("? 'dual' : 'single'", APP_JS)

    def test_download_short_name_has_a_dual_variant(self):
        self.assertIn("yt_hourly_cover: { single: 'YT整點', dual: 'YT整點雙則' }", APP_JS)
        self.assertIn("if (key === 'yt_hourly_cover') return name[ytLayoutNow()]", APP_JS)

    def test_fields_carry_the_second_title_only_for_hourly(self):
        self.assertIn("title_second: layout === 'hourly' ? val('ytCoverTitleSecond') : ''", APP_JS)

    def test_single_topic_toast_uses_the_hourly_wording(self):
        """整點的單一主題是「單則」，不是十點那個「滿版」。"""
        self.assertIn("${ten ? '滿版' : '單則'}", APP_JS)

    def test_no_leftover_split_wiring(self):
        for dead in ("ytSplitBackgrounds", "background_second_base64", "data.split", "second_line1"):
            with self.subTest(dead=dead):
                self.assertNotIn(dead, APP_JS)


if __name__ == "__main__":
    unittest.main()


class TenDigestRetryTests(unittest.TestCase):
    """2026-09-08 晚：十點消化標題常違反三段字數（字太少撐不出三段、或一段 11 字），不合格就重問一次。"""

    def _post(self, payloads, target="ten_cover"):
        with patch.object(main, "digest_completion",
                          side_effect=[_completion(p) for p in payloads]) as dc:
            res = client.post(
                "/api/editor/cover-titles",
                json={"news_text": "一則夠長的新聞內文，足以觸發消化流程。", "target": target},
                headers=_headers(),
            )
        return res, dc

    def test_a_compliant_answer_is_accepted_first_time(self):
        good = {"topics": 1, "title_left": "韓國電力吃緊 擬增二十座 核反應爐", "title_right": ""}
        res, dc = self._post([good])
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(dc.call_count, 1)
        self.assertEqual(editor_formats.ten_digest_violations(good), [])

    def test_an_overlong_segment_triggers_one_retry_with_the_reason(self):
        bad = {"topics": 1, "title_left": "AI熱潮推升韓國電力需求 路透需增建 核反應爐", "title_right": ""}
        good = {"topics": 1, "title_left": "韓國電力吃緊 擬增二十座 核反應爐", "title_right": ""}
        res, dc = self._post([bad, good])
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(dc.call_count, 2)
        self.assertEqual(res.json()["title_left"], good["title_left"])
        retry_prompt = dc.call_args_list[1].kwargs["system_prompt"]
        self.assertIn("BROKE THESE RULES", retry_prompt)
        self.assertIn("AI熱潮推升韓國電力需求", retry_prompt)
        self.assertNotIn("BROKE THESE RULES", dc.call_args_list[0].kwargs["system_prompt"])

    def test_too_few_characters_also_count_as_a_violation(self):
        short = {"topics": 1, "title_left": "韓國 缺電 建核", "title_right": ""}
        problems = editor_formats.ten_digest_violations(short)
        self.assertTrue(any("must be 4" in p for p in problems), problems)
        self.assertTrue(any("must be 12" in p for p in problems), problems)

    def test_a_second_bad_answer_is_still_returned_not_looped_forever(self):
        bad = {"topics": 1, "title_left": "AI熱潮推升韓國電力需求 路透需增建 核反應爐", "title_right": ""}
        res, dc = self._post([bad, bad])
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(dc.call_count, main.TEN_DIGEST_MAX_ATTEMPTS)
        self.assertEqual(res.json()["title_left"], bad["title_left"])

    def test_the_hourly_target_never_retries(self):
        res, dc = self._post([{"topics": 1, "title": "一 二", "title_second": ""}], target="yt_hourly")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(dc.call_count, 1)
