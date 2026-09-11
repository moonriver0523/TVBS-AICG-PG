"""創意拉桿模組化 P3（2026-09-11）：變化池與 draw() 搬進 creativity.py。

風險 2（見 docs/plan-20260911-創意拉桿模組化.md）：cover_design_brief 抽籤
順序是「plate → stagger → typeface → palette → anchor → tilt_dir」，接著
cover_accessories 用同一顆 rng 繼續抽招式。動了順序、多抽或少抽一次，
所有既有 seed 的長相就全部換掉，而現存測試沒有一條看得出來——因為原本
沒有任何測試釘住「同一顆 seed 抽出的完整文字」。

這支測試在搬家**之前**先跑一次、把 tests/fixtures/cover_design_brief_rng_pins_
20260911.json 產出來（產生腳本沒留在 repo 裡，那是一次性動作；fixture 本身
才是要留住的東西），涵蓋 13 顆 seed（11 顆 int＋2 顆字串）× level 1-4，
特意挑到「該級抽到含 {shape} 佔位符的招式」與「沒抽到」兩種都有的組合
（scan 過 seed 0-39 的 cover_accessories 輸出才選出來，見 fixture 內容），
因為那是唯一會讓 rng 消耗量隨內容變動的分支，最容易在搬家時被靜默改掉。

fixture 釘的是**跨 level 各自的實際輸出**，不是「同一顆 seed 跨 level 應該
一致」——cover_accessories 的抽籤深度本來就隨 level（COVER_ACCESSORY_COUNTS）
分岔，這是原設計，不是這裡要驗證的東西。
"""
import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import creativity  # noqa: E402
import editor_formats as ef  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "cover_design_brief_rng_pins_20260911.json"


class CoverDesignBriefRngPinTests(unittest.TestCase):
    """搬家前後，同一顆 seed 抽到的完整 brief 文字要逐字元一致。"""

    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            cls.fixture = json.load(f)

    def test_fixture_has_representative_coverage(self):
        """fixture 本身要涵蓋 13 顆 seed × level 1-4＝52 筆，不是隨便挑幾顆交差。"""
        self.assertEqual(len(self.fixture), 52)
        seeds = {row["seed"] for row in self.fixture}
        self.assertGreaterEqual(len(seeds), 12)
        levels = {row["level"] for row in self.fixture}
        self.assertEqual(levels, {1, 2, 3, 4})

    def test_pinned_seeds_reproduce_exactly(self):
        for row in self.fixture:
            with self.subTest(seed=row["seed"], level=row["level"]):
                brief = ef.cover_design_brief(
                    row["level"],
                    titles=tuple(row["titles"]),
                    seed=row["seed"],
                    full_width=row["full_width"],
                )
                self.assertEqual(brief, row["brief"])


class DrawFunctionTests(unittest.TestCase):
    """creativity.draw() 本身：介面、序列長度、anchor 開關。"""

    def test_draw_is_deterministic_per_seed(self):
        self.assertEqual(creativity.draw(11), creativity.draw(11))

    def test_draw_anchor_true_matches_cover_design_brief_first_six_draws(self):
        """anchor=True 時六顆的值要跟十點自己 random.Random(seed) 依序抽出來的
        六顆完全一樣——這是「順序沒有被搬歪」最直接的證據。
        """
        import random
        seed = 42
        rng = random.Random(seed)
        expected = (
            rng.choice(creativity.COVER_PLATE_SHAPES),
            rng.choice(creativity.COVER_STAGGER_PATTERNS),
            rng.choice(creativity.COVER_TYPEFACES),
            rng.choice(creativity.COVER_PALETTES),
            rng.choice(creativity.COVER_ANCHORS),
            rng.choice(creativity.COVER_TILT_DIRECTIONS),
        )
        d = creativity.draw(seed, anchor=True)
        self.assertEqual((d.plate, d.stagger, d.typeface, d.palette, d.anchor, d.tilt_dir), expected)

    def test_draw_anchor_false_skips_the_draw_not_just_the_use(self):
        """anchor=False 時 tilt_dir 遞補成第 5 抽，不是第 6 抽——這是 YT 那套
        「少一顆」的序列，跟十點的六顆不是同一串亂數消費量。
        """
        import random
        seed = 42
        rng = random.Random(seed)
        rng.choice(creativity.COVER_PLATE_SHAPES)
        rng.choice(creativity.COVER_STAGGER_PATTERNS)
        rng.choice(creativity.COVER_TYPEFACES)
        rng.choice(creativity.COVER_PALETTES)
        expected_tilt = rng.choice(creativity.COVER_TILT_DIRECTIONS)
        d = creativity.draw(seed, anchor=False)
        self.assertIsNone(d.anchor)
        self.assertEqual(d.tilt_dir, expected_tilt)

    def test_draw_result_is_frozen(self):
        d = creativity.draw(1)
        with self.assertRaises(Exception):
            d.plate = "changed"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
