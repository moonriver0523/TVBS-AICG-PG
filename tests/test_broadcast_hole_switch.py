"""播出鏡面白色壓框開關（2026-09-07 使用者裁決）。

使用者測出白框壓到標題：根因是消化規則允許標題「橫跨上緣」，而挖空框 09-03 起垂直置中，
上緣變窄就撞上。裁決：(1) 壓框改成開關、預設 OFF，底圖完整交給後製；(2) 標題規則收緊，
標題與所有內容一律留在非影片那半邊、不得跨中線。
"""
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats  # noqa: E402
import main  # noqa: E402


class HeadlineRuleTests(unittest.TestCase):
    def test_headline_must_stay_in_content_half_for_both_stamp_variants(self):
        for key, opposite, side in (("broadcast_left", "right", "left"), ("broadcast_right", "left", "right")):
            for stamp in (True, False):
                with self.subTest(key=key, stamp=stamp):
                    rules = editor_formats.digest_rules(key, "編輯", stamp=stamp)
                    self.assertIn("cross the vertical midline", rules)
                    self.assertIn(f"headline AND every content block", rules)
                    self.assertIn(f"sit in the {opposite} half", rules)
                    # 舊寫法允許標題橫跨上緣，正是白框壓到字的根因
                    self.assertNotIn("spans the upper band", rules)
                    self.assertNotIn("may run across the upper band", rules)
                    self.assertNotIn("hang down into", rules)
                    self.assertIn(f"stays inside the {opposite} half above the cards", rules)
                    self.assertNotIn(f"stays inside the {side} half", rules)

    def test_rules_still_carry_no_numbers(self):
        for key in ("broadcast_left", "broadcast_right"):
            for stamp in (True, False):
                body = editor_formats.digest_rules(key, "編輯", stamp=stamp)
                # 允許條號（1.–8.）；其餘數字禁止（模型會把數字畫進圖）
                stripped = re.sub(r"^\d+\.", "", body, flags=re.M)
                self.assertFalse(re.search(r"\d", stripped), stripped)


class BackendSwitchTests(unittest.TestCase):
    def _req(self, **kw):
        base = {"news_text": "測試新聞內容", "role": "編輯", "editor_format": "broadcast_left"}
        base.update(kw)
        return main.NewsImageGenerateRequest(**base)

    def test_default_is_off(self):
        self.assertFalse(main.NewsImageGenerateRequest.model_fields["hole"].default)
        self.assertEqual(main.broadcast_hole_for(self._req()), "")

    def test_on_follows_format_side(self):
        self.assertEqual(main.broadcast_hole_for(self._req(hole=True)), "left")
        self.assertEqual(main.broadcast_hole_for(self._req(hole=True, editor_format="broadcast_right")), "right")

    def test_on_without_hole_format_or_for_reporter_is_noop(self):
        self.assertEqual(main.broadcast_hole_for(self._req(hole=True, editor_format="default")), "")
        self.assertEqual(main.broadcast_hole_for(self._req(hole=True, role="記者")), "")

    def test_digest_rules_unaffected_by_switch(self):
        # 不管蓋不蓋框，內容都要避開影片那半邊——規則不因開關而變
        self.assertIn("reserved for a video window", editor_formats.digest_rules("broadcast_left", "編輯"))


class FrontendSwitchTests(unittest.TestCase):
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_state_default_off_and_button_starts_hidden_off(self):
        self.assertRegex(self.js, r"(?m)^\s*hole: false,", "state.hole 預設 OFF")
        btn = re.search(r'<button id="p1-btnHole"[^>]*>([^<]*)</button>', self.html)
        self.assertIsNotNone(btn)
        self.assertEqual(btn.group(1).strip(), "壓框 OFF")
        self.assertIn("hidden", btn.group(0).split('class="')[1].split('"')[0].split())

    def test_every_payload_goes_through_the_switch(self):
        payloads = re.findall(r"broadcast_hole:\s*([^,\n]+)", self.js)
        self.assertEqual(len(payloads), 3, payloads)
        for expr in payloads:
            self.assertIn("broadcastHoleForApi()", expr, expr)
        self.assertNotIn("broadcast_hole: editorFormat().hole", self.js)
        self.assertIn("return state.hole ? (editorFormat().hole || '') : '';", self.js)

    def test_button_only_shown_for_hole_formats(self):
        self.assertIn("_hide(document.getElementById('p1-btnHole'), !format.hole);", self.js)


if __name__ == "__main__":
    unittest.main()
