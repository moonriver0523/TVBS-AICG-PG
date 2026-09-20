"""Stage 2 跨功能契約：D16、D2、seed 與無字檔。"""
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
            # 2026-09-14 D14 新增的第六檔也是兩角色共用的 *_DENSITY_RULES，
            # 同一條鐵律照樣適用——守門名單漏一塊就等於那一塊沒被守。
            main.NO_TEXT_DENSITY_RULES,
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


class A1A5A2CgVariationTests(SourceAssertions, unittest.TestCase):
    """2-6：CG 線接上既有變化池（A1／A5），配件件數改由程式決定（A2）。

    使用者回報「最高級還是不夠亮」的直接原因：CG 每一級注入的是固定文字、沒有抽籤，
    所以每次成品同一個長相。封面線 2026-09-11 已經證明過解法——同一批池子、同一顆
    seed、命令句而不是許可句。
    """

    def test_level_zero_still_injects_nothing(self):
        """0 級＝現行成品，這一批不准讓它多出半個字（凍結快照也靠這條）。"""
        self.assertEqual(main.cg_creativity_rules(0, seed=1), "")
        self.assertEqual(main.cg_creativity_rules(0, seed=999), "")

    def test_the_same_seed_reproduces_the_same_rules(self):
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                self.assertEqual(
                    main.cg_creativity_rules(level, seed=7),
                    main.cg_creativity_rules(level, seed=7),
                )

    def test_different_seeds_actually_change_the_draw(self):
        """池子接上了才會變。這一條就是「最高級還是不夠亮」的直接驗收。"""
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                variants = {main.cg_creativity_rules(level, seed=s) for s in range(12)}
                self.assertGreaterEqual(len(variants), 2)

    def test_the_draw_is_stated_as_a_decision_not_a_menu(self):
        """許可句推不動模型——這個 repo 記過三次。池子的輸出一律是命令句。"""
        rules = main.cg_creativity_rules(3, seed=3).lower()
        for banned in ("you may choose", "if you like", "optionally"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, rules)

    def test_all_three_lines_share_one_accessory_count_table(self):
        """CP4 使用者裁決（2026-09-15 更正）：三條線共用封面現行那張表，CG 不另立。

        另立一張 {2: 0} 的 CG 表會讓「共用一張表」這句話當場不成立；把封面改成
        {2: 0} 則會動到 52 筆 cover RNG pin 與 YT fixture，屬未授權的視覺變更。
        """
        self.assertEqual(creativity.COVER_ACCESSORY_COUNTS, {0: 0, 1: 0, 2: 1, 3: 2, 4: 3})
        self.assertFalse(
            hasattr(creativity, "CG_ACCESSORY_COUNTS"), "CG 不得另立一張件數表"
        )

    def test_the_device_count_per_level_follows_that_shared_table(self):
        self.assertNotIn(main.CG_ACCESSORY_HEADING, main.cg_creativity_rules(1, seed=1))
        for level, want in ((2, 1), (3, 2), (4, 3)):
            with self.subTest(level=level):
                rules = main.cg_creativity_rules(level, seed=1)
                self.assertIn(main.CG_ACCESSORY_HEADING, rules)
                block = rules.split(main.CG_ACCESSORY_HEADING, 1)[1]
                listed = [ln for ln in block.splitlines() if ln.startswith("- ")]
                self.assertEqual(len(listed), want)

    def test_the_old_permission_phrasing_is_gone(self):
        """「一兩個」「至多三個」正是 A2 要換掉的許可句：件數由程式列，不是模型挑。"""
        source = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        self.assertNotSourceContains(source, "One or two flat wordless pictograms")
        self.assertNotSourceContains(source, "Up to three wordless pictograms")

    def test_the_cg_devices_carry_no_ten_cover_layout_wording(self):
        """CG 不是封面：雙切切線、十點的深藍底條這類版型幾何不該跟著搬過來。"""
        rules = main.cg_creativity_rules(4, seed=2)
        for banned in ("centre seam", "navy bottom strip"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, rules)

    def test_the_fixed_paragraph_is_still_last(self):
        """FIXED 段要壓在創意條文後面，順序倒了就變成創意蓋掉 FIXED。"""
        rules = main.cg_creativity_rules(4, seed=2)
        self.assertLess(
            rules.index("LEVEL 4 OF 4"),
            rules.index("WHAT THE CREATIVITY SETTING NEVER CHANGES"),
        )

    def test_the_seed_reaches_the_rules_through_the_real_data_flow(self):
        """只在 unit test 直接呼叫函式會漏掉真正的資料流：端點 → build_digest_instructions。"""
        a = main.build_digest_instructions(
            "編輯", "standard", "資料圖表", visual_creativity=4, seed=1
        )
        b = main.build_digest_instructions(
            "編輯", "standard", "資料圖表", visual_creativity=4, seed=1
        )
        self.assertEqual(a, b)
        others = {
            main.build_digest_instructions(
                "編輯", "standard", "資料圖表", visual_creativity=4, seed=s
            )
            for s in range(12)
        }
        self.assertGreaterEqual(len(others), 2)


class D3SplitAuthorisationTests(unittest.TestCase):
    """2-7：只有「字超多」拿得到「拆原有內容」的授權（D3，2026-09-14 已裁）。

    裁決原文：鬆綁，但**只允許拆原有內容**——不得新增原文沒有的事實。這是 B21
    那批忠實度問題的高風險區，所以「拆」與「補」的界線要寫到模型分得出來。
    """

    def test_maximum_authorises_splitting_what_is_already_there(self):
        block = main.MAXIMUM_DENSITY_RULES
        self.assertIn("SPLIT", block)
        self.assertIn("already", block)

    def test_maximum_states_the_boundary_between_splitting_and_supplying(self):
        """只寫「可以拆」等於拿掉防線。不能做的事要在同一條裡逐項列出。"""
        block = main.MAXIMUM_DENSITY_RULES
        for banned in ("cause", "person", "time", "figure", "place", "consequence"):
            with self.subTest(banned=banned):
                self.assertIn(banned, block)

    def test_no_other_density_gets_the_split_licence(self):
        """字多也給的話，字多與字超多會再次塌成同一檔——F1 要拉開的就是這個。"""
        for name, block in (
            ("standard", main.STANDARD_DENSITY_RULES),
            ("simplified", main.SIMPLIFIED_DENSITY_RULES),
            ("minimal", main.MINIMAL_DENSITY_RULES),
            ("verbatim", main.VERBATIM_DENSITY_RULES),
        ):
            with self.subTest(density=name):
                self.assertNotIn("SPLIT", block)

    def test_the_creativity_fixed_block_still_forbids_new_text(self):
        """D3 是內容切分，不是創意拉桿的例外。"""
        self.assertIn("NO NEW TEXT OF ANY KIND", creativity.fixed_block(target="digest"))


class F1DensityLadderTests(unittest.TestCase):
    """2-8：級距要拉得開，而且拉開的方式是單調的。

    這一步刻意**不重開數字裁決**：點數（1／1-3／6／8）、行長與標題上限
    （10／13／18／22）都是已裁定的值，這裡只釘住它們仍然單調、沒有人事後偷改。
    """

    def test_the_headline_caps_are_strictly_monotonic(self):
        caps = []
        for block in (
            main.MINIMAL_DENSITY_RULES,
            main.SIMPLIFIED_DENSITY_RULES,
            main.STANDARD_DENSITY_RULES,
            main.MAXIMUM_DENSITY_RULES,
        ):
            match = re.search(r"no more than (\d+) visible characters", block)
            self.assertIsNotNone(match)
            caps.append(int(match.group(1)))
        self.assertEqual(caps, [10, 13, 18, 22])
        self.assertEqual(caps, sorted(set(caps)))

    def test_the_point_ceilings_are_monotonic_too(self):
        self.assertIn("ONE point", main.MINIMAL_DENSITY_RULES)
        self.assertIn("1 to 3 key points", main.SIMPLIFIED_DENSITY_RULES)
        std_min, std_target = main.density_point_bounds("standard")
        max_min, max_target = main.density_point_bounds("maximum")
        self.assertLess(std_target, max_target)
        self.assertLess(std_min, max_min)
        prompt_std = main.build_digest_instructions("記者", "standard", "資料圖表")
        prompt_max = main.build_digest_instructions("記者", "maximum", "資料圖表")
        self.assertIn(f"TARGET {main.density_count_word(std_target)}", prompt_std)
        self.assertIn(
            f"TARGET {main.density_count_word(max_target).upper()}", prompt_max
        )

    def test_the_broadcast_card_count_is_a_layout_limit_not_a_density_one(self):
        """版面實體限制不隨拉桿長：F1 不動 _broadcast_point_count 的既定差異。"""
        self.assertEqual(
            editor_formats._broadcast_point_count("maximum"),
            editor_formats._broadcast_point_count("standard"),
        )


class D14F20NoTextTests(SourceAssertions, unittest.TestCase):
    """2-9：「完全不要文字」變成拉桿最左端的一檔（D14 已裁形式、F20 實作）。

    D14 裁決：拉桿改六段，無字放最左端——兩個極端（無字／不改字）推到兩頭，避免選錯。

    F20 的 MASTER 曾提「無字可跳過整個 digest 呼叫」當 token 效益，**本波不做**
    （監督 2026-09-14 Q3）：生圖仍然需要 style／structure／圖表類型／地圖與肖像結果，
    跳過是另一件大工程。這裡做的是最小可用解——照常消化，但產出的是無文字視覺。
    """

    def test_the_enum_and_order_put_no_text_at_the_far_left(self):
        self.assertEqual(
            main.DIGEST_DENSITY_ORDER,
            ("no_text", "verbatim", "minimal", "simplified", "standard", "maximum"),
        )

    def test_both_request_models_accept_no_text_and_still_reject_nonsense(self):
        import pydantic

        self.assertEqual(
            main.GenerateRequest(
                news_text="測試", type_label="資料圖表", density="no_text"
            ).density,
            "no_text",
        )
        self.assertEqual(
            main.NewsImageGenerateRequest(news_text="測試", density="no_text").density, "no_text"
        )
        with self.assertRaises(pydantic.ValidationError):
            main.GenerateRequest(news_text="測試", type_label="資料圖表", density="nope")

    def test_the_defaults_are_untouched(self):
        """D14 只加一檔，不動預設：後端 request 仍是 standard、前台拉桿仍停在字少。"""
        self.assertEqual(
            main.GenerateRequest(news_text="測試", type_label="資料圖表").density, "standard"
        )
        app_js = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")
        self.assertRegex(app_js, r"digestDensity:\s*'simplified'")

    def test_the_no_text_prompt_shuts_off_every_text_product(self):
        prompt = main.build_digest_instructions("編輯", "no_text", "資料圖表", stamp=True)
        # 要點名它們才關得掉——留一條沒點名，模型就會挑最寬鬆的那句遵守
        for marker in ("[標題]", "[內文小標]", "<蓋章>"):
            with self.subTest(marker=marker):
                self.assertIn(marker, main.NO_TEXT_FINAL_REMINDER)
        self.assertIn(main.NO_TEXT_FINAL_REMINDER, prompt)

    def test_no_text_does_not_drag_in_verbatim_mode(self):
        """兩個極端共用拉桿兩頭，但語意完全相反：無字不得帶進「逐字保留」那一套。

        注意不能直接找 "VERBATIM MODE" 這個字面——USER_INSTRUCTION_RULES 第 5 條
        本來就在講「使用者自己寫了逐字保留」那條通道，每一檔都會注入，跟拉桿無關。
        要比對的是 density block 本體。
        """
        prompt = main.build_digest_instructions("編輯", "no_text", "資料圖表")
        self.assertNotIn(main.VERBATIM_DENSITY_RULES, prompt)
        self.assertNotIn(main.VERBATIM_FINAL_REMINDER, prompt)

    def test_no_text_does_not_ship_a_stamp_rule_that_contradicts_it(self):
        """「有蓋章」與「完全無字」兩條矛盾 prompt 不得同時送出。"""
        prompt = main.build_digest_instructions("編輯", "no_text", "資料圖表", stamp=True)
        self.assertNotIn("STAMP BANNER: ON", prompt)

    def test_the_no_text_block_does_not_pollute_the_other_densities(self):
        for density in ("verbatim", "minimal", "simplified", "standard", "maximum"):
            with self.subTest(density=density):
                prompt = main.build_digest_instructions("編輯", density, "資料圖表")
                self.assertNotIn(main.NO_TEXT_DENSITY_RULES, prompt)

    def test_the_quality_gate_lets_an_empty_variable_through_only_for_no_text(self):
        """無字檔要求 variable 是空字串，但通用品質閘把「欄位為空」當成截斷等級的
        故障——不處理的話無字會連撞 5 次重試然後 502，而且錯誤訊息還看不出原因。"""
        empty_variable = {"style": "a wordless photograph", "structure": "one subject, centred", "variable": ""}
        self.assertEqual(
            main.digest_quality_problem(empty_variable, "stop", density="no_text"), ""
        )
        for density in ("simplified", "standard", "maximum", "minimal", "verbatim"):
            with self.subTest(density=density):
                self.assertIn(
                    "variable",
                    main.digest_quality_problem(empty_variable, "stop", density=density),
                )

    def test_the_image_prompt_also_gets_a_no_text_override(self):
        """消化端產出空的 variable 還不夠：生圖 prompt 從頭到尾都在講「把 VARIABLE
        FIELDS 的字畫上去」，而空欄位會被換成 [No Variables Defined]。留著不管，
        模型有機會把那串字面畫進畫面，或自己補一個標題去滿足前面那些條款。"""
        import news_prompt

        kwargs = dict(
            role="編輯", engine="gpt", type_label="資料圖表",
            style="a wordless photograph", structure="one subject, centred",
            variable=news_prompt.compose_variable(""),
        )
        self.assertNotIn(
            "NO TEXT AT ALL", news_prompt.build_prompt(**kwargs, no_text=False)
        )
        self.assertIn("NO TEXT AT ALL", news_prompt.build_prompt(**kwargs, no_text=True))

    def test_the_pipeline_endpoint_forwards_no_text(self):
        """網頁版可用、LINE／整合端悄悄失效是這條線最典型的漏法。"""
        import types
        from unittest import mock

        captured = {}

        def fake_generate(request):
            captured["density"] = request.density
            raise RuntimeError("stop-after-capture")

        with mock.patch.object(main, "generate", fake_generate), mock.patch.object(
            main, "check_input", return_value=types.SimpleNamespace(accepted=True, user_message="")
        ):
            with self.assertRaises(RuntimeError):
                main.generate_news_image(
                    main.NewsImageGenerateRequest(news_text="測試新聞內容", density="no_text")
                )
        self.assertEqual(captured["density"], "no_text")

    def test_the_frontend_slider_grew_to_six_steps(self):
        app_js = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")
        index_html = (Path(__file__).resolve().parent.parent / "index.html").read_text(
            encoding="utf-8"
        )
        order = app_js.split("const DENSITY_ORDER = [")[1].split("]")[0]
        self.assertEqual(
            [s.strip().strip("'") for s in order.split(",")], list(main.DIGEST_DENSITY_ORDER)
        )
        labels = app_js.split("const DENSITY_LABELS = {")[1].split("};")[0]
        self.assertSourceContains(labels, "no_text: '無字'")
        self.assertSourceContains(index_html, ">無字</span>")
        # 預設仍是字少，而字少在六段裡排第四格（index 3）
        self.assertEqual(main.DIGEST_DENSITY_ORDER.index("simplified"), 3)
        self.assertSourceContains(
            index_html,
            'id="digestDensityRange" type="range" min="0" max="5" step="1" value="3"',
        )


class ImageRequestDensityWiringTests(unittest.TestCase):
    def test_news_pipeline_forwards_density_into_image_request(self):
        import types
        from unittest import mock

        captured = {}
        digest = main.GenerateResponse(
            style="style",
            structure="structure",
            variable="[標題] title",
            chart_type="資料圖表",
            seed=0,
        )
        generated = main.ImageGenerateResponse(
            image_data_base64="a", mime_type="image/png", model="fake"
        )

        def fake_image(request):
            captured["request"] = request
            return generated

        with mock.patch.object(
            main, "check_input", return_value=types.SimpleNamespace(accepted=True, user_message="")
        ), mock.patch.object(main, "generate", return_value=digest), mock.patch.object(
            main, "resolve_digest_portraits", return_value=(digest, {})
        ), mock.patch.object(main, "resolve_portraits", return_value=("", [])), mock.patch.object(
            main, "build_prompt", return_value="prompt"
        ), mock.patch.object(main, "generate_image", side_effect=fake_image), mock.patch.object(
            main, "_archive_generation", return_value=None
        ), mock.patch.object(main.request_log, "log_generation", return_value=None):
            main.generate_news_image(
                main.NewsImageGenerateRequest(
                    news_text="測試新聞內容", role="編輯", density="maximum"
                )
            )

        self.assertEqual(captured["request"].density, "maximum")
        self.assertEqual(captured["request"].safe_frame_profile, "編輯")
        self.assertEqual(captured["request"].provider, "gpt")


if __name__ == "__main__":
    unittest.main()
