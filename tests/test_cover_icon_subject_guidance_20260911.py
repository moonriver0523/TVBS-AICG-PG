"""配件不看題材（2026-09-11 第十批）。

實拍缺陷：國王逝世的封面，L4 抽到的 icon 配了一朵雨雲，掛在「辭世」旁邊。根因是
COVER_ACCESSORY_POOL 的 icon 條目帶著一份災難／氣象例子清單
`(raincloud, flame, siren, warning triangle, syringe)`——條目裡明明已經寫了
「taken from the subject」，卻被這份清單當成錨點蓋過去。

改法：(1) creativity.py 的 icon 條目拿掉那份清單；(2) 產生圖示的三條招式
（icon／bubbles／iconrow）不在各自的池子文字裡各補一次正面方法，改在
editor_formats.cover_accessories() 集中管一次：抽到這三條的任何一條，就在它
前面掛一句共通指示——方法（先讀標題自己的名詞，沒有才用照片主體）＋具體反例
（死亡配雨雲＝氣象語氣，不是肅穆語氣），一次管住三條。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import creativity  # noqa: E402
import editor_formats  # noqa: E402


class IconPoolNoLongerAnchoredToADisasterListTests(unittest.TestCase):
    def test_the_icon_entry_no_longer_lists_disaster_examples(self):
        pool = dict(creativity.COVER_ACCESSORY_POOL)
        self.assertNotIn("raincloud", pool["icon"])
        self.assertNotIn("warning triangle", pool["icon"])

    def test_the_icon_entry_still_says_taken_from_the_subject(self):
        """條目本身那句沒被拿掉——被拿掉的是蓋過它的那份清單，不是這句話。"""
        pool = dict(creativity.COVER_ACCESSORY_POOL)
        self.assertIn("taken from the subject", pool["icon"])
        self.assertIn("WORDLESS PICTOGRAM", pool["icon"])
        self.assertIn("never covering a stroke", pool["icon"])


class CentralGuidanceCoversAllThreeIconLikeAccessoriesTests(unittest.TestCase):
    """不在三個地方各改一次：guidance 只住在 cover_accessories() 一處，
    抽到 icon／bubbles／iconrow 任何一條都會掛上同一句。"""

    def test_guidance_text_names_a_method_and_a_concrete_counter_example(self):
        text = editor_formats._ICON_SUBJECT_GUIDANCE
        # 正面方法：找不到清單可以照抄，就要有「從哪裡取材」的命令
        self.assertIn("headline", text.lower())
        self.assertIn("subject", text.lower())
        # 具體反例：只給方法不夠，這個 repo 已證實具體反例才擋得住圖模亂套錨點
        self.assertIn("raincloud", text)
        self.assertIn("death", text)

    @staticmethod
    def _picked_keys(level: int, seed) -> list[str]:
        """複現 cover_accessories() 內部的洗牌，只為了知道這個 seed／level 實際
        抽到哪幾個 key——不重寫抽籤邏輯本身，只重現同一段 `random.Random(seed)`
        + `rng.shuffle(entries)`，因為 cover_accessories() 只回傳拼好的文字，
        測試需要知道「有沒有抽到 icon 類」才能斷言 guidance 該不該出現。
        """
        import random
        want = editor_formats.COVER_ACCESSORY_COUNTS.get(level, 0)
        entries = list(creativity.COVER_ACCESSORY_POOL)
        random.Random(seed).shuffle(entries)
        return [key for key, _text in entries[:want]]

    def test_guidance_appears_exactly_when_an_icon_like_key_is_drawn(self):
        """逐顆 seed 核對：抽到 icon/bubbles/iconrow 才有 guidance，沒抽到就沒有
        ——不是「有時候出現」，是精確對應。"""
        saw_with = saw_without = False
        for seed in range(40):
            for level in (2, 3, 4):
                keys = self._picked_keys(level, seed)
                expect_guidance = any(k in editor_formats._ICON_LIKE_KEYS for k in keys)
                picked = editor_formats.cover_accessories(level, seed=seed)
                has_guidance = any(editor_formats._ICON_SUBJECT_GUIDANCE in text for text in picked)
                with self.subTest(seed=seed, level=level):
                    self.assertEqual(has_guidance, expect_guidance)
                saw_with = saw_with or expect_guidance
                saw_without = saw_without or not expect_guidance
        self.assertTrue(saw_with, "40 顆 seed 應該至少有一筆抽到圖示類招式")
        self.assertTrue(saw_without, "40 顆 seed 應該至少有一筆完全沒抽到圖示類招式")

    def test_guidance_is_attached_at_most_once_per_brief(self):
        """4 級最多 3 件招式，就算三條圖示類全被抽到，guidance 也只掛一次——
        重複三遍只是噪音，不會多壓住什麼。"""
        for seed in range(200):
            picked = editor_formats.cover_accessories(4, seed=seed)
            occurrences = sum(text.count(editor_formats._ICON_SUBJECT_GUIDANCE) for text in picked)
            with self.subTest(seed=seed):
                self.assertLessEqual(occurrences, 1)

    def test_a_seed_that_draws_all_three_icon_like_accessories_still_gets_one_guidance(self):
        """挑一顆會把 icon／bubbles／iconrow 三條全抽出來的 seed，專門驗證這個邊界。"""
        found = False
        for seed in range(500):
            keys = self._picked_keys(4, seed)
            if set(keys) >= editor_formats._ICON_LIKE_KEYS:
                picked = editor_formats.cover_accessories(4, seed=seed)
                occurrences = sum(t.count(editor_formats._ICON_SUBJECT_GUIDANCE) for t in picked)
                self.assertEqual(occurrences, 1)
                found = True
                break
        self.assertTrue(found, "500 顆 seed 內應該找得到一顆三條圖示類全抽到的")


class DesignBriefLengthCeilingStillHoldsTests(unittest.TestCase):
    """test_cover_title_creativity.LadderTests 釘著 L4 最壞情況 brief < 3000 字元
    ——加了 guidance 之後這條上限還是要守住，這裡重驗一次當這個新功能的回歸鎖。"""

    def test_worst_case_brief_stays_under_the_length_ceiling(self):
        worst = max(
            len(editor_formats.cover_design_brief(level, seed=s, full_width=f))
            for level in range(1, 5)
            for s in range(40)
            for f in (False, True)
        )
        self.assertLess(worst, 3000)


if __name__ == "__main__":
    unittest.main()
