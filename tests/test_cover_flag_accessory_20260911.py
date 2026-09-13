"""開放國旗當招式素材——限「照片裡已經有的旗子」（2026-09-11 第十批）。

使用者：「國旗開放當創意元素」。原本 creativity._IMAGE_FIXED 明文禁「no flag
chips」，理由是模型憑記憶重畫的旗子（比例、色帶順序、徽記）可能畫錯，跟 CG 那條
(g) 不准畫真實地理地圖同一個判準。這批放開的是「照片裡本來就有的那面旗」——不是
模型畫的，裁下來用不會有畫錯的風險。

放行走兩條線：
1. 禁令本身**就地改寫**（creativity._IMAGE_FIXED），見
   test_cover_brands_and_digest_chips.py／test_designed_title_house_style.py
   的更新。
2. 正面命令：creativity.COVER_FLAG_ACCESSORY，**不進**
   COVER_ACCESSORY_POOL（不跟其他九件一起被 rng.shuffle）——改成確定性換入：
   editor_formats.cover_accessories() 偵測 visuals 裡有沒有 "flag"／「旗」，
   3 級以上（COVER_ACCESSORY_COUNTS 給到 2 件以上）才把抽到的最後一件換成它。

這裡驗三件事：(a) 沒偵測到旗子時，行為與改動前完全一致（既有 seed 的長相不變，
呼應 fixture 的 diff 應該是空的）；(b) 偵測到旗子且件數 >=2 時才換入，2 級（只有
1 件）不換；(c) 換入的那件仍然帶自己的幾何排除區，跟其他招式同一套規矩。
"""
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import creativity  # noqa: E402
import editor_formats  # noqa: E402


class FlagBanRewriteTests(unittest.TestCase):
    def test_the_ban_is_rewritten_in_place_not_appended_elsewhere(self):
        """禁令就地改寫：原字面「no flag chips」整句消失，新字面在同一個位置。"""
        text = creativity.fixed_block(target="image")
        self.assertNotIn("no flag chips", text)
        self.assertIn("no flag redrawn from memory", text)
        # 兩句被凍結測試釘死的措辭完全沒動
        self.assertIn("No text of any kind other than the listed", text)
        self.assertIn("NO NEW TEXT OF ANY KIND", text)

    def test_the_rewrite_still_bans_an_invented_or_swapped_flag(self):
        text = creativity.fixed_block(target="image")
        self.assertIn("never redrawn", text)
        self.assertIn("never swapped for a different", text)
        self.assertIn("never labelled with a name", text)

    def test_the_rewrite_carves_out_a_flag_already_in_the_photograph(self):
        text = creativity.fixed_block(target="image")
        self.assertIn("ALREADY VISIBLE IN THE PHOTOGRAPH", text)


class FlagAccessoryPoolTests(unittest.TestCase):
    def test_flag_accessory_is_not_in_the_shuffled_pool(self):
        """不進 COVER_ACCESSORY_POOL：進去會讓 rng.shuffle 的消耗量變，
        所有既有 seed 的長相跟著全換（風險 2）。池子條目數維持 9。"""
        keys = [key for key, _text in creativity.COVER_ACCESSORY_POOL]
        self.assertNotIn("flag", keys)
        self.assertEqual(len(creativity.COVER_ACCESSORY_POOL), 9)

    def test_flag_accessory_text_is_wordless_and_bound_to_the_real_flag(self):
        _key, text = creativity.COVER_FLAG_ACCESSORY
        self.assertIn("ALREADY VISIBLE IN THIS PHOTOGRAPH", text)
        self.assertIn("never redrawn from memory", text)
        self.assertIn("never labelled with a name", text)


class CoverAccessoriesFlagSwapTests(unittest.TestCase):
    def test_no_flag_mention_leaves_seeds_unchanged(self):
        """沒有旗子可提時，行為要跟改動前完全一致——這是 fixture 空 diff 的依據。"""
        for level in (2, 3, 4):
            for seed in range(6):
                with self.subTest(level=level, seed=seed):
                    without_visuals = editor_formats.cover_accessories(level, seed=seed)
                    with_empty_visuals = editor_formats.cover_accessories(
                        level, seed=seed, visuals=("", ""))
                    self.assertEqual(without_visuals, with_empty_visuals)

    def test_flag_mention_swaps_the_last_pick_at_level_three_and_up(self):
        for level in (3, 4):
            with self.subTest(level=level):
                plain = editor_formats.cover_accessories(level, seed=5)
                flagged = editor_formats.cover_accessories(
                    level, seed=5, visuals=("挪威王室在皇宮陽台揮舞國旗", ""))
                self.assertEqual(len(plain), len(flagged))
                self.assertEqual(plain[:-1], flagged[:-1])
                self.assertNotEqual(plain[-1], flagged[-1])
                self.assertIn("ALREADY VISIBLE IN THIS PHOTOGRAPH", flagged[-1])

    def test_flag_mention_does_not_swap_at_level_two(self):
        """2 級只有 1 件招式——換掉唯一那件會讓這一級的「規矩」感整個讓給國旗。"""
        plain = editor_formats.cover_accessories(2, seed=5)
        flagged = editor_formats.cover_accessories(2, seed=5, visuals=("a flag waving", ""))
        self.assertEqual(plain, flagged)

    def test_detection_matches_english_flag_and_chinese_qi(self):
        for visual in ("a large flag on the roof", "屋頂掛著一面旗"):
            with self.subTest(visual=visual):
                flagged = editor_formats.cover_accessories(4, seed=5, visuals=(visual, ""))
                self.assertIn("ALREADY VISIBLE IN THIS PHOTOGRAPH", flagged[-1])

    def test_the_swapped_in_flag_still_carries_its_geometry_note(self):
        """跟其他招式同一套規矩：不進上三分之一、雙切版不跨縫線。"""
        flagged = editor_formats.cover_accessories(4, seed=5, visuals=("national flag", ""))
        self.assertIn("MIDDLE OR LOWER AREA ONLY", flagged[-1])
        self.assertIn("never the top third", flagged[-1])
        full_width_flagged = editor_formats.cover_accessories(
            4, seed=5, visuals=("national flag", ""), full_width=True)
        self.assertNotIn("centre seam", full_width_flagged[-1])

    def test_yt_design_brief_accepts_a_single_visual_string(self):
        """YT 傳的是單一字串（沒有左右格），不是 tuple。"""
        plain = editor_formats.yt_design_brief(4, lines=("A", "B"), seed=5)
        flagged = editor_formats.yt_design_brief(
            4, lines=("A", "B"), seed=5, visual="a soldier holding a flag")
        self.assertNotEqual(plain, flagged)
        self.assertIn("ALREADY VISIBLE IN THIS PHOTOGRAPH", flagged)

    def test_cover_design_brief_default_visuals_do_not_change_output(self):
        """新增的 visuals 參數預設值不能改變既有呼叫端（沒傳這個參數）的輸出。"""
        old_style = editor_formats.cover_design_brief(
            4, titles=("胰臟癌6大 前兆",), seed=0)
        new_default = editor_formats.cover_design_brief(
            4, titles=("胰臟癌6大 前兆",), seed=0, visuals=("", ""))
        self.assertEqual(old_style, new_default)


if __name__ == "__main__":
    unittest.main()
