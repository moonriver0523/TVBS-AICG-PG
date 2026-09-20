"""半版附圖位放 2 張以上：原圖放置一律轉 AI改圖（2026-09-13 使用者裁決）。

一個半格只有一個版位，以前默默只取第 1 張；多張的用意是讓模型融成一張示意圖。
滿版那一格（十點滿版左格／YT 單則）不鎖——多張原圖是自動切格，另一條規則。
"""

import base64
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

APP_JS = ROOT.joinpath("app.js").read_text(encoding="utf-8")


def _ref(colour, purpose):
    return {"data_url": _data_url(_png_bytes(colour=colour)), "purpose": purpose}


class BackendLock(unittest.TestCase):
    def _run(self, url, body):
        calls = []

        def fake_raw(req):
            calls.append([r.purpose for r in req.reference_images])
            w, h = {"1:1": (1024, 1024)}.get(req.aspect_ratio, (1280, 720))
            return SimpleNamespace(
                image_data_base64=base64.b64encode(_png_bytes(size=(w, h))).decode(),
                model="fake", mime_type="image/png",
            )

        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
                patch.object(main, "resolve_cover_visuals", return_value=("左景", "右景")), \
                patch.object(main, "derive_yt_cover_plan", return_value={"visual": "景"}), \
                patch.object(main, "_archive_generation", lambda **k: None), \
                patch.object(main, "supports_multiple_reference_images", return_value=True):
            res = client.post(url, json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text[:300])
        return calls

    def test_helper_converts_only_when_more_than_one(self):
        one = [main.UserReferenceImage(data_url="data:image/png;base64,AA", purpose="asis")]
        self.assertEqual([r.purpose for r in main.lock_half_slot_asis(one)], ["asis"])
        two = one + [main.UserReferenceImage(data_url="data:image/png;base64,BB", purpose="asis")]
        self.assertEqual([r.purpose for r in main.lock_half_slot_asis(two)], ["aiedit", "aiedit"])
        self.assertEqual([r.purpose for r in two], ["asis", "asis"], "不得改動原清單")

    def test_ten_split_two_asis_in_left_slot_becomes_aiedit_panel(self):
        calls = self._run("/api/editor/cover", {
            "title_left": "左標", "title_right": "右標", "layout": "split", "mode": "composite",
            "slot_left": [_ref((200, 0, 0), "asis"), _ref((220, 40, 40), "asis")],
            "slot_right": [_ref((0, 0, 200), "asis")],
        })
        # 左格不再直接上版而是生底圖（帶 2 張 AI改圖）；右格單張原圖照放、不生
        self.assertEqual(calls, [["aiedit", "aiedit"]])

    def test_ten_full_left_slot_not_locked(self):
        req = main.TenCoverRequest(
            title_left="標", title_right="", layout="full",
            slot_left=[main.UserReferenceImage(data_url="data:image/png;base64,AA", purpose="asis"),
                       main.UserReferenceImage(data_url="data:image/png;base64,BB", purpose="asis")],
        )
        self.assertEqual([r.purpose for r in req.slot_refs(0)], ["asis", "asis"])

    def test_ten_auto_layout_with_second_title_is_split_and_locks(self):
        req = main.TenCoverRequest(
            title_left="標", title_right="右", layout=None,
            slot_left=[main.UserReferenceImage(data_url="data:image/png;base64,AA", purpose="asis"),
                       main.UserReferenceImage(data_url="data:image/png;base64,BB", purpose="scene")],
        )
        self.assertEqual([r.purpose for r in req.slot_refs(0)], ["aiedit", "scene"])

    def test_yt_dual_slot_locks(self):
        calls = self._run("/api/editor/yt-cover", {
            "title": "第一則", "title_second": "第二則", "layout": "hourly", "title_mode": "composite",
            "date_text": "2026/09/13",
            "slot_left": [_ref((200, 0, 0), "asis"), _ref((220, 40, 40), "aiedit")],
            "slot_right": [_ref((0, 0, 200), "asis")],
        })
        self.assertEqual(calls, [["aiedit", "aiedit"]])


class FrontendLock(unittest.TestCase):
    def test_render_ref_list_has_lock_option(self):
        self.assertIn("function renderRefList(listEl, items, onChange, opts)", APP_JS)
        self.assertIn("if (lockAsis && value === 'asis') continue;", APP_JS)
        self.assertIn("if (ref.purpose === 'asis') ref.purpose = 'aiedit';", APP_JS)

    def test_half_slot_rule_applied_to_both_slots(self):
        self.assertIn("slotAsisLocked(state.coverAsis[side], split)", APP_JS)
        self.assertIn("slotAsisLocked(state.ytAsis[side], dual)", APP_JS)
        block = re.search(r"function slotAsisLocked\(list, isHalf\) \{(.*?)\n\}", APP_JS, re.S).group(1)
        self.assertIn("if (isHalf) return items.length >= 2;", block)
        self.assertIn("items.some(ref => ref.purpose === 'aiedit')", block)

    def test_layout_change_rerenders_slots(self):
        block = re.search(r"function updateCoverLayoutIndicator\(\) \{(.*?)\n\}\n", APP_JS, re.S).group(1)
        self.assertIn("renderCoverAsis()", block)


if __name__ == "__main__":
    unittest.main()
