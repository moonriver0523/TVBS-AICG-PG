"""2026-09-07：蓋章 OFF 的確定性兜底——消化模型不聽話仍回 <蓋章> 行時，後端一律刪掉。

使用者回報「播出鏡面 OFF 還是蓋章」；prompt 層另有修正（editor_formats 第 6 條），
這裡守的是所有版型共用的最後一道。
"""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import GenerateRequest, drop_stamp_lines, generate  # noqa: E402

PAYLOAD = {
    "style": "cinematic broadcast style",
    "structure": "three panels",
    "variable": "[標題] 颱風逼近\n[內文小標] 明晨<陸警>\n[內文小標] 北部<豪雨>\n[內文小標] 停班課<晚間>宣布\n<蓋章> 嚴防豪雨成災",
    "chart_type": "資料圖表",
}


def response(payload):
    message = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


class DropStampLinesTests(unittest.TestCase):
    def test_removes_only_the_stamp_line(self):
        out = drop_stamp_lines(PAYLOAD["variable"])
        self.assertNotIn("蓋章", out)
        self.assertEqual(out.count("\n"), 3)
        self.assertTrue(out.startswith("[標題] 颱風逼近"))

    def test_handles_fullwidth_brackets_and_indent(self):
        self.assertEqual(drop_stamp_lines("[標題] A\n  ＜蓋章＞ B"), "[標題] A")

    def test_leaves_text_without_stamp_untouched(self):
        self.assertEqual(drop_stamp_lines("[標題] A\n[內文小標] B"), "[標題] A\n[內文小標] B")


class GenerateGuardTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(main.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, **req):
        request = GenerateRequest(news_text="素材", type_label="資料圖表", **req)
        with patch.object(main.openai_client.chat.completions, "create", return_value=response(PAYLOAD)):
            return generate(request)

    def test_stamp_off_strips_stamp_line_for_every_format(self):
        for fmt in ("default", "broadcast_left", "broadcast_right"):
            with self.subTest(fmt=fmt):
                result = self._run(stamp=False, role="編輯", editor_format=fmt)
                self.assertNotIn("蓋章", result.variable)
                if fmt == "default":
                    self.assertIn("[內文小標] 停班課<晚間>宣布", result.variable)
                else:
                    # 播出鏡面（2026-09-09 第四批）：蓋章 OFF 時挖空框底下那條帶要有東西，
                    # 消化沒生出 <底帶> 就把最後一張卡升級（見 main.ensure_bottom_band_line）。
                    self.assertIn("<底帶> 停班課<晚間>宣布", result.variable)

    def test_stamp_off_on_broadcast_leaves_a_compliant_bottom_band_alone(self):
        payload = dict(PAYLOAD)
        payload["variable"] = "[標題] 颱風逼近\n[內文小標] 明晨<陸警>\n<底帶> 停班課<晚間>宣布"
        request = GenerateRequest(
            news_text="素材", type_label="資料圖表", stamp=False,
            role="編輯", editor_format="broadcast_left",
        )
        with patch.object(main.openai_client.chat.completions, "create", return_value=response(payload)):
            result = generate(request)
        self.assertEqual(result.variable, payload["variable"])

    def test_stamp_on_and_unset_keep_the_line(self):
        for stamp in (True, None):
            with self.subTest(stamp=stamp):
                result = self._run(stamp=stamp, role="編輯")
                self.assertIn("<蓋章> 嚴防豪雨成災", result.variable)


if __name__ == "__main__":
    unittest.main()
