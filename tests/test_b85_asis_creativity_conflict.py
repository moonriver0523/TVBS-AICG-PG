"""B85 候選④（2026-09-22）：創意階梯不准再把「原圖放置」那一格切開、轉斜、染色。

正式站 10:47:32（`99b1373ef899`，編輯／自動判斷／份量 maximum／創意 4）的成品
prompt 裡，STRUCTURE 逐字寫著：

    a full-height dramatic hero cutout image showing the user's original supplied
    photograph placed unaltered, intersecting an anticlockwise diagonal
    brush-stroke dividing edge

「placed unaltered」證明 USER_REFERENCE_ASIS_DIGEST_RULES 有生效；但同一句話同時
下令 cutout ＋ 與斜切邊界相交，與生圖端 USER_REFERENCE_ASIS_RULES 的「Do not crop,
stretch, rotate, mirror or otherwise distort」正面矛盾。來源是創意階梯命令的
（_CG_L3_EXTRA 的 cut the main subject out／_CG_L4_EXTRA 的 full-height dramatic
image／_CG_DESIGN_DRAW_TEMPLATE 的 palette 硬性令），不是模型自由發揮。

⚠ 這一刀只消掉那條**必然衝突**，不是 B85 的解：這條路仍然沒有任何像素保護
（B55 實測創意 0 級 change_ratio 68.1%，那時還沒有這條矛盾）。見 D25。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import main  # noqa: E402
import news_prompt  # noqa: E402


class TheGuardNamesTheActualVerbsTests(unittest.TestCase):
    """原本的護欄只封畫風形容詞（depiction／illustration），實際出事的是動作。"""

    BLOCK = news_prompt.USER_REFERENCE_ASIS_DIGEST_RULES

    def test_every_verb_seen_in_the_production_failure_is_named(self):
        for word in ("cut out", "cutout", "cut-out", "cropped", "tilted", "slanted",
                     "intersecting", "colour-graded", "recoloured", "tinted"):
            self.assertIn(word, self.BLOCK, f"護欄沒有點名「{word}」")

    def test_the_old_wording_guard_is_still_there(self):
        """候選④是**加**一段，不是換掉原本那段——2026-08-23 那兩次事故仍要擋住。"""
        for word in ("depiction", "illustration", "artistic rendering", "reinterpreted"):
            self.assertIn(word, self.BLOCK)

    def test_it_says_out_loud_that_it_overrides_the_creativity_ladder(self):
        """本 repo 慣例：位置在後**＋明文 OVERRIDE**，只靠位置壓不住命令句。"""
        self.assertIn("(OVERRIDE)", self.BLOCK)
        self.assertIn("VISUAL CREATIVITY", self.BLOCK)
        self.assertIn("DESIGN DRAW", self.BLOCK)

    def test_it_tells_the_model_what_to_do_instead_of_only_what_not_to_do(self):
        """光說「不准斜」會讓模型連整張版面的斜切一起放掉——那是創意 4 級的本體。
        要明講：角度走這一格**周圍**，這一格自己保持正的。"""
        self.assertIn("AROUND this image", self.BLOCK)
        self.assertIn("upright rectangular panel", self.BLOCK)


class InjectionOrderTests(unittest.TestCase):
    def test_the_guard_lands_after_the_creativity_ladder(self):
        """位置在後才壓得住。這裡用真的 prompt 組裝，不是讀原始碼。"""
        prompt = main.build_digest_instructions(
            role="編輯", density="maximum", type_label="自動判斷", full_bleed=True,
            visual_creativity=4, asis_reference_count=1, seed=7,
        )
        creativity_at = prompt.find("VISUAL CREATIVITY — LEVEL 4 OF 4")
        guard_at = prompt.find("ATTACHED IMAGE TO BE PLACED AS-IS")
        self.assertGreater(creativity_at, -1, "創意 4 級沒注入，這個測試就沒有意義")
        self.assertGreater(guard_at, creativity_at, "護欄排在創意階梯前面等於沒有")

    def test_no_asis_upload_changes_nothing(self):
        """沒有附圖時消化 prompt 要逐字元不變——凍結快照全部走這條路。"""
        kwargs = dict(role="編輯", density="maximum", type_label="自動判斷",
                      full_bleed=True, visual_creativity=4, seed=7)
        self.assertEqual(
            main.build_digest_instructions(**kwargs),
            main.build_digest_instructions(asis_reference_count=0, **kwargs),
        )
        self.assertNotIn(
            "ATTACHED IMAGE TO BE PLACED AS-IS",
            main.build_digest_instructions(**kwargs),
        )

    def test_the_guard_is_injected_at_every_creativity_level(self):
        """創意 0 也要有：B55 實測 0 級照樣被重畫，護欄不是只為 3–4 存在的。"""
        for level in range(5):
            prompt = main.build_digest_instructions(
                role="編輯", density="standard", type_label="自動判斷", full_bleed=True,
                visual_creativity=level, asis_reference_count=1, seed=7,
            )
            self.assertIn("(OVERRIDE)", prompt, f"創意 {level} 級沒注入護欄")


class StillNotTheFixTests(unittest.TestCase):
    """釘住「這不是 B85 的解」這件事，免得日後有人看到護欄就把 B85 結案。"""

    def test_the_image_stage_still_has_no_pixel_protection(self):
        """候選④完全沒碰生圖端：asis 仍然只有一段文字，沒有閘門也沒有程式疊圖。"""
        source = Path(main.__file__).read_text(encoding="utf-8")
        block = source[source.index("def apply_user_references_to_image_request"):]
        block = block[: block.index("\ndef ", 1)]
        self.assertNotIn("change_ratio", block)
        self.assertNotIn("protect_base", block)


if __name__ == "__main__":
    unittest.main()
