"""B68：封面推導的 material 不得含字面 `\\n`（反斜線＋n 兩個字元），必須是真換行。

根因：`resolve_cover_visuals()` 原本用 `'...{}\\nLEFT description...'.format(...)`
組字串——寫在單引號字串裡的 `\\n` 是「反斜線」加「n」兩個字元，不是換行。B53
（news_text 段）與 2026-09-08 WP1（instruction 段）沿用同一個手誤，所以整段材料
三處都中招；模型收到的是一整行黏在一起的文字，不是分段的四行／多段落。

`derive_yt_cover_plan()` 一開始就用真換行 `\n`（單引號跳脫），這裡順便補一條
回歸測試釘住它，避免以後被複製貼上帶壞。
"""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import main  # noqa: E402

TWO_PEOPLE = {
    "visual_left": "梅爾茨與蕭茲同框，正面半身", "visual_right": "柏林街頭",
    "portrait_subjects_left": ["梅爾茨", "蕭茲"], "portrait_subjects_left_en": ["Friedrich Merz", "Olaf Scholz"],
    "portrait_subjects_right": [], "portrait_subjects_right_en": [],
}


def _completion(payload):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])


class TenCoverMaterialNewlineTests(unittest.TestCase):
    def test_base_headline_material_uses_real_linebreaks(self):
        req = main.TenCoverRequest(title_left="標題左", title_right="標題右")
        with patch.object(main, "digest_completion", return_value=_completion(TWO_PEOPLE)) as digest:
            main.resolve_cover_visuals(req)
        material = digest.call_args.kwargs["news_text"]
        self.assertNotIn("\\n", material, "material 仍含字面 \\n，不是真換行")
        self.assertIn("LEFT headline: 標題左\nLEFT description already supplied:", material)
        self.assertIn("RIGHT headline: 標題右\nRIGHT description already supplied:", material)

    def test_news_text_segment_uses_real_linebreaks(self):
        req = main.TenCoverRequest(
            title_left="德國總理深感震驚",
            news_text="梅爾茨在柏林表示對選舉結果深感震驚，誓言推動改革。",
        )
        with patch.object(main, "digest_completion", return_value=_completion(TWO_PEOPLE)) as digest:
            main.resolve_cover_visuals(req)
        material = digest.call_args.kwargs["news_text"]
        self.assertNotIn("\\n", material, "news_text 段仍含字面 \\n，不是真換行")
        self.assertIn("supplied: (none — write one)\n\nNews article source material", material)

    def test_instruction_segment_uses_real_linebreaks(self):
        req = main.TenCoverRequest(
            title_left="德國總理深感震驚",
            instruction="用手繪風",
        )
        with patch.object(main, "digest_completion", return_value=_completion(TWO_PEOPLE)) as digest:
            main.resolve_cover_visuals(req)
        material = digest.call_args.kwargs["news_text"]
        self.assertNotIn("\\n", material, "instruction 段仍含字面 \\n，不是真換行")
        self.assertIn("supplied: (none — write one)\n\nExtra instruction from the editor", material)

    def test_both_extra_segments_together_still_use_real_linebreaks(self):
        req = main.TenCoverRequest(
            title_left="德國總理深感震驚",
            news_text="梅爾茨在柏林表示對選舉結果深感震驚。",
            instruction="用手繪風",
        )
        with patch.object(main, "digest_completion", return_value=_completion(TWO_PEOPLE)) as digest:
            main.resolve_cover_visuals(req)
        material = digest.call_args.kwargs["news_text"]
        self.assertNotIn("\\n", material)
        # 兩段都要各自以真換行銜接，不能因為疊加又被壓回同一行
        self.assertIn("\n\nNews article source material", material)
        self.assertIn("\n\nExtra instruction from the editor", material)


class YtCoverMaterialNewlineRegressionTests(unittest.TestCase):
    """derive_yt_cover_plan 本來就是對的，這裡是防止以後被改壞的回歸釘子。"""

    def test_material_never_contains_literal_backslash_n(self):
        with patch.object(main, "digest_completion", return_value=_completion(TWO_PEOPLE)) as digest:
            main.derive_yt_cover_plan(
                "梅爾茨深感震驚", None, "用手繪風",
                "梅爾茨在柏林表示對選舉結果深感震驚。",
            )
        material = digest.call_args.kwargs["news_text"]
        self.assertNotIn("\\n", material)


if __name__ == "__main__":
    unittest.main()
