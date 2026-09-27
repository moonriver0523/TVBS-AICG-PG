import os
import pathlib
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import creativity  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
import news_prompt  # noqa: E402


class DirectionQualificationTests(unittest.TestCase):
    def test_positive_rules_cover_the_five_allowed_relationships(self):
        positives = (
            ("颱風持續西移，今晚進入巴士海峽", "資料圖表"),
            ("方案先由地方初審，再送中央複核", "資料圖表"),
            ("豪雨導致土石鬆動，因此封閉道路", "情境示意圖"),
            ("出口金額年增12%，失業率下降", "資料圖表"),
            ("單位由倉庫移交給醫院", "資料圖表"),
            ("只有靜態名單", "3D示意／流程"),
        )
        for content, type_label in positives:
            with self.subTest(content=content, type_label=type_label):
                self.assertTrue(creativity.directional_content_eligible(content, type_label))

    def test_negative_rules_reject_topic_only_or_static_facts(self):
        negatives = (
            "市府今天公布新圖書館設計，基地面積三千坪",
            "董事長出席記者會，展示三款新產品",
            "調查列出六項民眾最在意的議題",
        )
        for content in negatives:
            with self.subTest(content=content):
                self.assertFalse(creativity.directional_content_eligible(content, "資料圖表"))

    def test_ineligible_magnifier_has_matching_outline_and_no_back_arrow(self):
        text = creativity.condition_directional_accessory(
            "magnifier",
            dict(creativity.COVER_ACCESSORY_POOL)["magnifier"],
            direction_context="市府公布三款新產品",
        )
        self.assertIn("matching source area", text)
        self.assertIn("no arrow", text)
        self.assertNotIn("pointing back", text)

    def test_same_seed_keeps_every_non_directional_move_unchanged(self):
        chosen_seed = None
        for seed in range(500):
            rng = random.Random(seed)
            entries = list(creativity.COVER_ACCESSORY_POOL)
            rng.shuffle(entries)
            keys = [key for key, _ in entries[:3]]
            if "arrow" in keys and "magnifier" not in keys:
                chosen_seed = seed
                break
        self.assertIsNotNone(chosen_seed)
        eligible = creativity.accessories(
            4, seed=chosen_seed, direction_context="營收年增兩成"
        )
        ineligible = creativity.accessories(
            4, seed=chosen_seed, direction_context="公司公布三款新產品"
        )
        self.assertEqual(len(eligible), len(ineligible))
        differing = [i for i, pair in enumerate(zip(eligible, ineligible)) if pair[0] != pair[1]]
        self.assertEqual(len(differing), 1)
        self.assertIn("DIRECTIONLESS FOCUS HALO", ineligible[differing[0]])
        for i in set(range(len(eligible))) - set(differing):
            self.assertEqual(eligible[i], ineligible[i])

    def test_every_shared_pool_path_forwards_the_deterministic_context(self):
        context = "貨物由港口送往倉庫"
        for editor_format in (None, "broadcast"):
            with self.subTest(path=editor_format or "general_cg"):
                with patch("creativity.accessories", return_value=[]) as mocked:
                    main.build_digest_instructions(
                        "編輯",
                        "simplified",
                        "資料圖表",
                        editor_format=editor_format,
                        visual_creativity=4,
                        seed=27,
                        direction_context=context,
                    )
                self.assertEqual(mocked.call_args.kwargs["direction_context"], context)
                self.assertEqual(mocked.call_args.kwargs["type_label"], "資料圖表")

        for name, call in (
            (
                "ten_oclock",
                lambda: editor_formats.cover_design_brief(
                    4, titles=("標題",), seed=27, direction_context=context
                ),
            ),
            (
                "youtube",
                lambda: editor_formats.yt_design_brief(
                    4, lines=("標題", "副標"), seed=27, direction_context=context
                ),
            ),
        ):
            with self.subTest(path=name):
                with patch("creativity.accessories", return_value=[]) as mocked:
                    call()
                self.assertEqual(mocked.call_args.kwargs["direction_context"], context)


class OptionalBottomBandTests(unittest.TestCase):
    def _prompt(self, variable: str) -> str:
        return news_prompt.build_prompt(
            role="編輯",
            engine="gpt",
            type_label="資料圖表",
            style="news",
            structure="broadcast",
            variable=variable,
            safe_frame=True,
            hole_side="left",
        )

    def test_prompt_with_band_renders_only_the_supplied_line(self):
        prompt = self._prompt("[標題] 標題\n[內文小標] 重點\n<底帶> 新事實")
        self.assertIn("BROADCAST BOTTOM BAND CONTENT", prompt)
        self.assertIn("Remove the <底帶> marker", prompt)
        self.assertIn("render exactly that line's supplied wording", prompt)
        self.assertNotIn("BROADCAST BOTTOM BAND IS TEXT-FREE", prompt)

    def test_prompt_without_band_keeps_the_region_text_free(self):
        prompt = self._prompt("[標題] 標題\n[內文小標] 重點")
        self.assertIn("BROADCAST BOTTOM BAND IS TEXT-FREE", prompt)
        self.assertIn("NO text, digits, caption, slogan, label, icon or invented filler", prompt)

    def test_ensure_no_longer_promotes_the_last_card(self):
        variable = "[標題] 標題\n[內文小標] 第一點\n[內文小標] 最後一點"
        self.assertEqual(main.ensure_bottom_band_line(variable), variable)
        self.assertNotIn("<底帶>", main.ensure_bottom_band_line(variable))

    def test_digest_rule_allows_one_real_point_or_no_line(self):
        rules = editor_formats.digest_rules(
            "broadcast", "編輯", stamp=False, density="simplified", side="left"
        )
        self.assertIn("ONLY IF", rules)
        self.assertIn("OMIT <底帶> ENTIRELY", rules)
        self.assertIn("EMPTY IS REQUIRED", rules)

    def test_browser_prompt_has_the_same_variable_driven_switch(self):
        source = pathlib.Path("app.js").read_text(encoding="utf-8")
        self.assertIn("function broadcastBottomBandRules(variable, side)", source)
        self.assertIn("BROADCAST BOTTOM BAND IS TEXT-FREE", source)
        self.assertIn("broadcastBottomBandRules(variable, holeSide)", source)


if __name__ == "__main__":
    unittest.main()
