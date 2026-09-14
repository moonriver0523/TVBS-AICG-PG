"""Stage 2 跨功能契約：D16、D2、seed 與無字檔。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import creativity  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402


class D16TitlePolicyTests(unittest.TestCase):
    def test_editor_title_template_only_allows_minimal_to_use_one_line(self):
        for density in ("minimal", "simplified", "standard", "maximum"):
            with self.subTest(density=density):
                prompt = main.build_digest_instructions("編輯", density, "資料圖表")
                self.assertIn("預設拆分為兩行", prompt)
                if density == "minimal":
                    self.assertIn("可依可讀性使用單行，但不強制單行", prompt)
                else:
                    self.assertIn("只有字極少 MODE 可依可讀性使用單行", prompt)

    def test_density_blocks_never_contain_editor_line_count_rules(self):
        """密度 block 為兩角色共用；行數只准存在編輯樣板，避免洩漏到記者版。"""
        density_blocks = (
            main.STANDARD_DENSITY_RULES,
            main.SIMPLIFIED_DENSITY_RULES,
            main.MINIMAL_DENSITY_RULES,
            main.MAXIMUM_DENSITY_RULES,
            main.VERBATIM_DENSITY_RULES,
        )
        for block in density_blocks:
            with self.subTest(block=block[:20]):
                self.assertNotRegex(block, r"(?i)\b(one|two|three|single)\s+lines?\b")

    def test_each_density_declares_the_visible_headline_cap(self):
        blocks = {
            10: main.MINIMAL_DENSITY_RULES,
            13: main.SIMPLIFIED_DENSITY_RULES,
            18: main.STANDARD_DENSITY_RULES,
            22: main.MAXIMUM_DENSITY_RULES,
        }
        for cap, block in blocks.items():
            with self.subTest(cap=cap):
                self.assertIn(f"{cap}", block)
                self.assertIn("[標題]", block)
                self.assertIn("whitespace", block)
                self.assertIn("<", block)
                self.assertIn(">", block)

    def test_broadcast_single_headline_rule_is_unchanged(self):
        for stamp_block in (
            editor_formats._BROADCAST_STAMP_ON,
            editor_formats._BROADCAST_STAMP_OFF,
        ):
            self.assertIn('exactly one [標題] line', stamp_block)


class D2ChromaKeySafetyTests(unittest.TestCase):
    def test_cg_chroma_key_rule_exists_at_creativity_zero_for_all_densities(self):
        for density in ("minimal", "simplified", "standard", "maximum"):
            with self.subTest(density=density):
                prompt = main.build_digest_instructions(
                    "編輯", density, "資料圖表", visual_creativity=0
                )
                self.assertIn("chroma-key green", prompt)
                self.assertNotIn("green-family colour", prompt)

    def test_cg_chroma_key_rule_keeps_directional_market_green(self):
        prompt = main.build_digest_instructions(
            "編輯", "standard", "資料圖表", visual_creativity=0
        )
        self.assertIn("下跌／減少／負向 = green", prompt)
        self.assertIn("non-chroma data green remains allowed", prompt)

    def test_cover_rule_no_longer_bans_olive_teal_or_mint(self):
        for rule in (
            editor_formats.COVER_NO_GREEN_RULE,
            editor_formats.COVER_NO_GREEN_ROW,
        ):
            self.assertIn("chroma-key green", rule)
            self.assertNotIn("green-family", rule)
            self.assertNotIn("teal", rule)
            self.assertNotIn("mint", rule)
            self.assertIn("olive green remain allowed", rule)
        self.assertNotIn("teal", creativity.COVER_CHROMA_KEY_BANNED_COLOUR_WORDS)
        self.assertNotIn("mint", creativity.COVER_CHROMA_KEY_BANNED_COLOUR_WORDS)
        self.assertNotIn("olive", creativity.COVER_CHROMA_KEY_BANNED_COLOUR_WORDS)

    def test_existing_cover_palettes_are_not_mutated_only_to_prove_permission(self):
        self.assertEqual(
            creativity.COVER_PALETTES,
            (
                ("white", "deep navy", "vivid red", "bright golden yellow"),
                ("white", "black", "bright golden yellow", "vivid red"),
                ("bright golden yellow", "white", "vivid red", "deep navy"),
                ("icy white-blue", "deep indigo", "hot orange", "white"),
                ("white", "electric cyan", "magenta", "black"),
                ("black", "white", "hot orange", "electric cyan"),
                ("white", "royal purple", "bright golden yellow", "hot orange"),
                ("pale gold", "deep crimson", "white", "black"),
                ("white", "hot orange", "electric cyan", "deep navy"),
            ),
        )


class SourceAssertions:
    """原始碼比對的斷言。直接用 assertIn 會把整份 app.js／main.py 印進失敗訊息
    （800KB），失敗報告因此完全讀不了——這兩支只印找的那一段。"""

    def assertSourceContains(self, source: str, needle: str):
        self.assertTrue(needle in source, f"原始碼裡找不到：{needle}")

    def assertNotSourceContains(self, source: str, needle: str):
        self.assertFalse(needle in source, f"原始碼裡不該還留著：{needle}")


class F0SeedTests(SourceAssertions, unittest.TestCase):
    """F0（D1 已裁）：三條線都收明確的整數 seed，重生遞增而不是靠改標題偷湊。

    紅線一：**seed 絕對不准進 prompt**。seed 一旦變成生圖輸入的一部分，同一顆 seed
    就再也複現不出原圖，F0 這個功能本身就自我否定了（監督 2026-09-14 Q2）。
    所以 seed 只走「請求欄位 → 抽籤 → 回應／稽核」，不走 prompt 文字。
    """

    def test_next_generation_seed_is_a_bounded_unpredictable_int(self):
        seeds = {main.next_generation_seed() for _ in range(20)}
        for seed in seeds:
            self.assertIsInstance(seed, int)
            self.assertGreaterEqual(seed, 0)
            self.assertLess(seed, 2 ** 31)
        # 每次都同一顆＝沒有隨機性；20 次只出現 1 種值的機率可以忽略。
        self.assertGreater(len(seeds), 1)

    def test_all_three_lines_accept_an_explicit_seed_and_default_to_none(self):
        models = {
            "cg": (main.GenerateRequest, {"news_text": "測試", "type_label": "資料圖表"}),
            "pipeline": (main.NewsImageGenerateRequest, {"news_text": "測試"}),
            "ten": (main.TenCoverRequest, {"title_left": "測試"}),
            "yt": (main.YtCoverRequest, {"title": "測試"}),
        }
        for line, (model, fields) in models.items():
            with self.subTest(line=line):
                self.assertIsNone(model(**fields).seed)
                self.assertEqual(model(**fields, seed=4242).seed, 4242)

    def test_every_response_reports_the_seed_actually_used(self):
        """回應要帶實際採用的 seed：前端下一次重生要遞增它，稽核要對得回來。"""
        for model in (
            main.GenerateResponse,
            main.NewsImageGenerateResponse,
            main.TenCoverResponse,
            main.YtCoverResponse,
        ):
            with self.subTest(model=model.__name__):
                self.assertIn("seed", model.model_fields)

    def test_build_digest_instructions_takes_the_seed_through(self):
        """2-6 要靠它把 CG 接上變化池；這一步先把資料流打通。"""
        import inspect

        self.assertIn("seed", inspect.signature(main.build_digest_instructions).parameters)

    def test_yt_no_longer_uses_the_title_and_date_as_its_only_seed(self):
        """舊寫法 seed=f"{req.title}|{date_text}"：同標題重生永遠同貌。"""
        source = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        self.assertNotSourceContains(source, 'seed=f"{req.title}|{date_text}"')

    def test_same_seed_is_reproducible_and_a_different_seed_changes_the_look(self):
        def cover(s):
            return editor_formats.cover_design_brief(
                4, titles=("甲標題", "乙標題"), seed=s, full_width=False
            )

        def yt(s):
            return editor_formats.yt_design_brief(4, lines=("甲", "乙"), seed=s)

        for name, fn in (("ten", cover), ("yt", yt)):
            with self.subTest(line=name):
                self.assertEqual(fn(7), fn(7))
                self.assertNotEqual(fn(7), fn(8))

    def test_pipeline_forwards_the_seed_into_the_digest_request(self):
        """generate_news_image 自己重組一份 GenerateRequest，是最容易漏欄位的地方。"""
        import types
        from unittest import mock

        captured = {}

        def fake_generate(request):
            captured["seed"] = request.seed
            raise RuntimeError("stop-after-capture")

        with mock.patch.object(main, "generate", fake_generate), mock.patch.object(
            main, "check_input", return_value=types.SimpleNamespace(accepted=True, user_message="")
        ):
            with self.assertRaises(RuntimeError):
                main.generate_news_image(
                    main.NewsImageGenerateRequest(news_text="測試新聞內容", seed=4242)
                )
        self.assertEqual(captured["seed"], 4242)

    def test_the_seed_never_reaches_the_prompt(self):
        """釘死監督裁決 Q2：seed 不得出現在送給模型的任何字串裡。"""
        prompt = main.build_digest_instructions(
            "編輯", "standard", "資料圖表", visual_creativity=4, seed=1234567
        )
        self.assertNotIn("1234567", prompt)

    def test_the_frontend_keeps_one_seed_per_line_and_only_bumps_on_regenerate(self):
        app_js = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")
        # 三條線各存各的 seed，且三個 payload 都要送出去
        for needle in ("seed: state.cgSeed", "seed: state.coverSeed", "seed: state.ytSeed"):
            with self.subTest(needle=needle):
                self.assertSourceContains(app_js, needle)
        # 遞增只能走這支；不准靠改標題／日期偷湊出新長相
        self.assertSourceContains(app_js, "function bumpSeed(")


class A1AccessoryOwnershipTests(SourceAssertions, unittest.TestCase):
    """2-5：招式件數與選取邏輯搬進 creativity.py，editor_formats 只留十點 adapter。

    這一步**不准改任何既有行為**：封面件數表原封不動、既有 52 筆 RNG pin 逐字元
    不變。重構偷改視覺是這個 repo 記過的病灶，所以件數表本身也釘在這裡。
    """

    def test_the_shared_module_owns_the_counts_and_the_picker(self):
        self.assertTrue(hasattr(creativity, "COVER_ACCESSORY_COUNTS"))
        self.assertTrue(callable(getattr(creativity, "accessories", None)))
        # 別名，不是副本——兩份會各自漂移，這正是搬家要解決的事
        self.assertIs(editor_formats.COVER_ACCESSORY_COUNTS, creativity.COVER_ACCESSORY_COUNTS)

    def test_the_refactor_does_not_change_the_cover_counts(self):
        self.assertEqual(creativity.COVER_ACCESSORY_COUNTS, {0: 0, 1: 0, 2: 1, 3: 2, 4: 3})

    def test_the_shared_picker_takes_no_ten_cover_layout_information(self):
        """titles／full_width 是十點版型的事，跨拉桿共用的那支不該知道。"""
        import inspect

        params = inspect.signature(creativity.accessories).parameters
        for banned in ("titles", "full_width"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, params)

    def test_editor_formats_keeps_an_adapter_not_a_second_copy(self):
        source = (Path(__file__).resolve().parent.parent / "editor_formats.py").read_text(
            encoding="utf-8"
        )
        # 件數表的字面值與洗牌迴圈都該只剩 creativity.py 一份
        self.assertNotSourceContains(source, "{0: 0, 1: 0, 2: 1, 3: 2, 4: 3}")
        self.assertNotSourceContains(source, "rng.shuffle(entries)")
        self.assertSourceContains(source, "creativity.accessories(")

    def test_the_ten_cover_adapter_still_supplies_its_own_geometry(self):
        """幾何提示是十點的版型資訊，留在 adapter：雙切才有切線那句。"""
        split = editor_formats.cover_accessories(4, seed=1, full_width=False)
        full = editor_formats.cover_accessories(4, seed=1, full_width=True)
        self.assertTrue(all("never across the centre seam" in t for t in split))
        self.assertFalse(any("never across the centre seam" in t for t in full))


if __name__ == "__main__":
    unittest.main()
