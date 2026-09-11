"""創意拉桿模組化 P4：yt_design_brief 改用 creativity.draw(seed, anchor=False)。

P3 已經把池子與抽籤序列搬進 creativity.py，但 yt_design_brief 那一輪仍然是
自己手寫的 `random.Random(seed)` 五連抽（見 editor_formats.py 該函式 P3 時的
註解：「這一輪仍然不接，只是先把介面留對」）。P4 把這條線接上——換接線，
不是換行為：三個 YT 版型（hourly／news／hot）已經共用這支函式，換掉裡面的
抽籤實作，輸出必須一字不改。

跟 tests/test_creativity_p3_rng_pins_20260911.py（十點那邊的等價測試）走同一個
做法：換接線**之前**先把現況輸出釘成 fixture，換完線後逐字元回放比對。

fixture 覆蓋 3 個 layout（hourly／news／hot）× level 1–4 × 13 顆 seed
（11 顆 int + 2 顆字串）＝156 筆，跟十點那份的 seed 池同一批（沿用其中一部分），
確保兩邊蓋到同一批「有 {shape} 佔位符」與「沒有」的招式抽籤分支
——那是 rng 消耗量隨內容分岔、最容易在換接線時被靜默改掉的地方。
"""
import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats as ef  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "yt_design_brief_rng_pins_20260911.json"


class YtDesignBriefRngPinTests(unittest.TestCase):
    """換接線前後，同一顆 seed／layout／level 抽到的完整 brief 文字要逐字元一致。"""

    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            cls.fixture = json.load(f)

    def test_fixture_has_representative_coverage(self):
        """3 layout × 4 level × 13 seed＝156 筆，三個版型都要蓋到。"""
        self.assertEqual(len(self.fixture), 156)
        layouts = {row["layout"] for row in self.fixture}
        self.assertEqual(layouts, {"hourly", "news", "hot"})
        levels = {row["level"] for row in self.fixture}
        self.assertEqual(levels, {1, 2, 3, 4})
        seeds = {row["seed"] for row in self.fixture}
        self.assertGreaterEqual(len(seeds), 12)

    def test_pinned_seeds_reproduce_exactly(self):
        for row in self.fixture:
            with self.subTest(layout=row["layout"], seed=row["seed"], level=row["level"]):
                brief = ef.yt_design_brief(
                    row["level"],
                    lines=tuple(row["lines"]),
                    seed=row["seed"],
                    layout=row["layout"],
                )
                self.assertEqual(brief, row["brief"])


if __name__ == "__main__":
    unittest.main()
