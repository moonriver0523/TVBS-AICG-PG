"""編輯格式精簡（2026-09-08 使用者裁決 WP1）。

四件事合在這一支：
1. **播出鏡面只剩一個版型**，挖空方向改由請求欄位 `hole_side` 決定。
2. **十點不一樣只剩一個版型**，滿版／雙切由「第二標題有沒有值」自動判定。
3. **舊 key 仍然可用**：`broadcast_left`／`broadcast_right`／`ten_cover_full` 是後端別名，
   LINE／WorkCord 與舊紀錄照樣打得進來，而且行為逐字元不變——別名**不吃**請求的
   `hole_side`，不然舊呼叫端沒帶欄位時右切會被預設值翻成左切。
4. **消化自動判定主題數**：一個主題只回第一標題，兩個主題依內文順序填左右。
"""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats  # noqa: E402
import main  # noqa: E402
from main import build_digest_instructions  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402


def _completion(payload):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))]
    )


class BroadcastMergeTests(unittest.TestCase):
    """合併後的播出鏡面：方向由請求決定，預設左。"""

    def test_single_broadcast_key_in_the_frontend_list(self):
        keys = editor_formats.EDITOR_FORMAT_KEYS
        self.assertIn("broadcast", keys)
        self.assertNotIn("broadcast_left", keys)
        self.assertNotIn("broadcast_right", keys)
        self.assertEqual(editor_formats.EDITOR_FORMATS["broadcast"]["label"], "播出鏡面")

    def test_default_side_is_left(self):
        self.assertEqual(editor_formats.hole_side("broadcast", "編輯"), "left")
        self.assertEqual(editor_formats.hole_side("broadcast", "編輯", side=None), "left")

    def test_request_side_decides_the_hole(self):
        self.assertEqual(editor_formats.hole_side("broadcast", "編輯", side="right"), "right")
        self.assertEqual(editor_formats.hole_side("broadcast", "編輯", side="left"), "left")

    def test_garbage_side_falls_back_to_the_default(self):
        for junk in ("top", "", "LEFT"):
            with self.subTest(junk=junk):
                self.assertEqual(editor_formats.hole_side("broadcast", "編輯", side=junk), "left")

    def test_digest_rules_follow_the_request_side(self):
        left = build_digest_instructions(
            "編輯", "simplified", "資料圖表", editor_format="broadcast", hole_side="left"
        )
        right = build_digest_instructions(
            "編輯", "simplified", "資料圖表", editor_format="broadcast", hole_side="right"
        )
        self.assertIn("the left half of the frame, centred vertically", left)
        self.assertIn("the right half of the frame, centred vertically", right)
        self.assertNotIn("the right half of the frame, centred vertically", left)

    def test_merged_format_matches_the_old_key_word_for_word(self):
        """合併不是改寫規則：同一側算出來的消化規則要跟舊 key 逐字元相同。"""
        for side, legacy in (("left", "broadcast_left"), ("right", "broadcast_right")):
            with self.subTest(side=side):
                self.assertEqual(
                    editor_formats.digest_rules("broadcast", "編輯", side=side),
                    editor_formats.digest_rules(legacy, "編輯"),
                )

    def test_endpoint_hole_follows_the_request(self):
        def req(**kw):
            base = {"news_text": "測試新聞內容", "role": "編輯", "editor_format": "broadcast"}
            return main.NewsImageGenerateRequest(**{**base, **kw})

        self.assertEqual(main.broadcast_hole_for(req(hole=True, hole_side="right")), "right")
        self.assertEqual(main.broadcast_hole_for(req(hole=True, hole_side="left")), "left")
        # 壓框關著就不蓋框，方向再怎麼選都一樣
        self.assertEqual(main.broadcast_hole_for(req(hole=False, hole_side="right")), "")
        # 記者拿不到（第三層防呆）
        self.assertEqual(
            main.broadcast_hole_for(req(hole=True, hole_side="right", role="記者")), ""
        )


class LegacyAliasTests(unittest.TestCase):
    """三個舊 key 一定要留著能用——LINE／WorkCord／舊請求紀錄還在送。"""

    def test_all_three_aliases_resolve(self):
        for key in ("broadcast_left", "broadcast_right", "ten_cover_full"):
            with self.subTest(key=key):
                self.assertIsNot(
                    editor_formats.get(key), editor_formats.get(editor_formats.DEFAULT_FORMAT),
                    "別名不該退回 default",
                )
                self.assertTrue(editor_formats.get(key)["label"])

    def test_alias_hole_sides_are_unchanged(self):
        self.assertEqual(editor_formats.hole_side("broadcast_left", "編輯"), "left")
        self.assertEqual(editor_formats.hole_side("broadcast_right", "編輯"), "right")

    def test_alias_ignores_the_request_side(self):
        """舊呼叫端不會帶 hole_side，欄位預設 left——別名若吃它，右切會被默默翻成左切。"""
        self.assertEqual(
            editor_formats.hole_side("broadcast_right", "編輯", side="left"), "right"
        )
        self.assertEqual(
            editor_formats.digest_rules("broadcast_right", "編輯", side="left"),
            editor_formats.digest_rules("broadcast_right", "編輯"),
        )

    def test_ten_cover_full_alias_is_full_layout(self):
        self.assertEqual(editor_formats.cover_layout("ten_cover_full"), "full")
        self.assertEqual(editor_formats.cover_mode("ten_cover_full"), editor_formats.COVER_MODE_AI)


class CoverLayoutAutoTests(unittest.TestCase):
    """滿版／雙切自動判定：第二標題有值＝雙切；請求明示 layout 時以請求為準。"""

    def test_second_title_decides(self):
        self.assertEqual(editor_formats.resolve_cover_layout(None, "第二標題"), "split")
        self.assertEqual(editor_formats.resolve_cover_layout(None, ""), "full")
        self.assertEqual(editor_formats.resolve_cover_layout(None, "   "), "full")

    def test_explicit_layout_wins(self):
        self.assertEqual(editor_formats.resolve_cover_layout("full", "第二標題"), "full")
        self.assertEqual(editor_formats.resolve_cover_layout("split", ""), "split")

    def test_merged_key_is_auto(self):
        self.assertEqual(editor_formats.cover_layout("ten_cover"), "auto")
        self.assertEqual(editor_formats.EDITOR_FORMATS["ten_cover"]["label"], "十點不一樣")

    def test_request_layout_is_optional(self):
        self.assertIsNone(main.TenCoverRequest(title_left="標題").layout)

    def test_endpoint_picks_full_when_second_title_is_empty(self):
        seen = {}

        def fake_full(req, date_text):
            seen["layout"] = req.layout
            return main.TenCoverResponse(image_data_base64="x", mime_type="image/png", model="m")

        with patch.object(main, "_editor_cover_full", side_effect=fake_full):
            res = client.post(
                "/api/editor/cover", json={"title_left": "只有一個 標題 在這"}, headers=_headers()
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(seen["layout"], "full")

    def test_endpoint_picks_split_when_second_title_is_present(self):
        """沒帶 layout＋兩個標題＝雙切：走雙切路徑，而且下游看到的 layout 已正規化。"""
        seen = {}

        def fake_ai(req, date_text, visuals):
            seen["layout"] = req.layout
            return b"cover", "fake-model", b"", ""

        with patch.object(main, "_editor_cover_full") as full, \
             patch.object(main, "resolve_cover_visuals", return_value=("左景", "右景")), \
             patch.object(main, "_cover_ai", side_effect=fake_ai):
            res = client.post(
                "/api/editor/cover",
                json={"title_left": "第一 標題 在此", "title_right": "第二 標題 在此"},
                headers=_headers(),
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(full.called, "有第二標題不該走滿版")
        self.assertEqual(seen["layout"], "split")

    def test_explicit_split_without_second_title_is_still_400(self):
        res = client.post(
            "/api/editor/cover",
            json={"title_left": "只有左", "layout": "split", "mode": "composite"},
            headers=_headers(),
        )
        self.assertEqual(res.status_code, 400)


class CoverTitleTopicsTests(unittest.TestCase):
    """消化端自動判定主題數（1／2），回應帶 topics。"""

    def _post(self, payload, target="ten_cover"):
        with patch.object(main, "digest_completion", return_value=_completion(payload)) as dc:
            res = client.post(
                "/api/editor/cover-titles",
                json={"news_text": "一則夠長的新聞內文，足以觸發消化流程。", "target": target},
                headers=_headers(),
            )
        return res, dc

    def test_two_topics_fill_both_titles(self):
        res, _ = self._post({"topics": 2, "title_left": "左標 三段 在此", "title_right": "右標 三段 在此"})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["topics"], 2)
        self.assertEqual(data["title_left"], "左標 三段 在此")
        self.assertEqual(data["title_right"], "右標 三段 在此")

    def test_single_topic_leaves_the_second_title_empty(self):
        res, _ = self._post({"topics": 1, "title_left": "唯一 標題 在此", "title_right": ""})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["topics"], 1)
        self.assertEqual(data["title_right"], "")

    def test_model_saying_one_but_giving_two_is_trimmed(self):
        """自相矛盾時以 topics 為準把右標清掉——回一組打架的值，前端指示器會跟欄位不同調。"""
        res, _ = self._post({"topics": 1, "title_left": "唯一 標題 在此", "title_right": "多出來的"})
        data = res.json()
        self.assertEqual((data["topics"], data["title_right"]), (1, ""))

    def test_model_saying_two_but_giving_one_falls_back_to_one(self):
        res, _ = self._post({"topics": 2, "title_left": "唯一 標題 在此", "title_right": "  "})
        data = res.json()
        self.assertEqual((data["topics"], data["title_right"]), (1, ""))

    def test_missing_first_title_is_502(self):
        res, _ = self._post({"topics": 1, "title_left": "", "title_right": ""})
        self.assertEqual(res.status_code, 502)

    def test_prompt_asks_for_the_topic_count_first(self):
        _, dc = self._post({"topics": 1, "title_left": "唯一 標題 在此", "title_right": ""})
        prompt = dc.call_args.kwargs["system_prompt"]
        self.assertIn('"topics"', prompt)
        self.assertIn("TWO genuinely different events", prompt)
        self.assertIn("appears FIRST in the article", prompt)

    def test_schema_requires_topics(self):
        schema = editor_formats.COVER_TITLE_DIGEST_SCHEMA_TEN
        self.assertEqual(schema["properties"]["topics"]["enum"], [1, 2])
        for field in ("topics", "title_left", "title_right"):
            self.assertIn(field, schema["required"])

    def test_full_target_still_returns_a_single_title(self):
        res, dc = self._post({"title": "全球 三千條 冰川"}, target="ten_cover_full")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["title"], "全球 三千條 冰川")
        self.assertEqual(res.json()["topics"], 1)
        self.assertIn("single headline", dc.call_args.kwargs["system_prompt"])


class InstructionFieldTests(unittest.TestCase):
    """指令欄回來了（2026-09-08 下午裁決推翻早上的隱藏），內容當畫面提示餵給推導步驟。"""

    def test_ten_cover_request_takes_an_instruction(self):
        field = main.TenCoverRequest.model_fields["instruction"]
        self.assertEqual(field.default, "")
        self.assertEqual(main.TenCoverRequest(title_left="標題", instruction="x").instruction, "x")

    def test_instruction_over_the_limit_is_rejected(self):
        with self.assertRaises(Exception):
            main.TenCoverRequest(title_left="標題", instruction="字" * 501)

    def test_instruction_reaches_the_visual_derivation(self):
        seen = {}

        def fake_digest(**kwargs):
            seen.update(kwargs)
            return _completion({
                "visual_left": "左景", "visual_right": "右景",
                "portrait_subjects_left": [], "portrait_subjects_left_en": [],
                "portrait_subjects_right": [], "portrait_subjects_right_en": [],
            })

        with patch.object(main, "digest_completion", side_effect=fake_digest):
            main.resolve_cover_visuals(
                main.TenCoverRequest(title_left="標題 在此 三段", title_right="第二 標題 在此",
                                     instruction="用手繪風，鏡頭拉遠")
            )
        self.assertIn("用手繪風，鏡頭拉遠", seen["news_text"])
        self.assertIn("never text to render", seen["news_text"])

    def test_no_instruction_leaves_the_material_untouched(self):
        seen = {}

        def fake_digest(**kwargs):
            seen.update(kwargs)
            return _completion({
                "visual_left": "左景", "visual_right": "右景",
                "portrait_subjects_left": [], "portrait_subjects_left_en": [],
                "portrait_subjects_right": [], "portrait_subjects_right_en": [],
            })

        with patch.object(main, "digest_completion", side_effect=fake_digest):
            main.resolve_cover_visuals(main.TenCoverRequest(title_left="標題 在此 三段"))
        self.assertNotIn("Extra instruction", seen["news_text"])

    def test_yt_cover_instruction_reaches_the_derivation(self):
        seen = {}

        def fake_digest(**kwargs):
            seen.update(kwargs)
            return _completion({
                "line1": "第一行", "line2": "第二行", "visual": "畫面",
                "portrait_subjects": [], "portrait_subjects_en": [],
            })

        with patch.object(main, "digest_completion", side_effect=fake_digest):
            main.derive_yt_cover_plan("標題 兩段", None, "夜景、廣角")
        self.assertIn("夜景、廣角", seen["news_text"])


if __name__ == "__main__":
    unittest.main()
