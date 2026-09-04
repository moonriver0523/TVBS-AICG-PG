"""色調亮／暗（2026-09-04 使用者要求）。

原本畫面一律偏深藍夜色系——災害、突發題材對，但民生、政策、生活題材用同一套
會顯得每則都在出事，所以交給使用者選。三條紅線：

1. tone=None 一個字都不能注入——LINE 與舊呼叫端行為不變，記者 frozen 快照
   靠這點維持綠燈（作法比照蓋章）。
2. 兩檔都要明說「蓋過上面的風格描述」。樣板與各類型規則裡散落著偏暗的措辭，
   只寫「請用亮色」而不點名蓋過誰，模型會兩邊各聽一半、出半亮半暗的圖。
3. 真正會出事的是**對比**，不是明暗：淺底淺字、深底深字在電視上都會糊掉。
   所以兩檔各自把字色寫死，不讓模型自己配。
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import GenerateRequest, NewsImageGenerateRequest, build_digest_instructions  # noqa: E402

ROLES = ("記者", "編輯")
DENSITIES = ("standard", "simplified", "verbatim")


def prompt(role="記者", density="standard", tone=None, stamp=None, instruction=""):
    return build_digest_instructions(
        role=role,
        density=density,
        type_label="資料圖表",
        tone=tone,
        stamp=stamp,
        user_instruction=instruction,
    )


class NoInjectionByDefaultTests(unittest.TestCase):
    def test_none_injects_nothing(self):
        for role in ROLES:
            for density in DENSITIES:
                with self.subTest(role=role, density=density):
                    self.assertNotIn("COLOUR TONE:", prompt(role=role, density=density))

    def test_request_models_default_to_none(self):
        self.assertIsNone(GenerateRequest(news_text="x", type_label="資料圖表").tone)
        self.assertIsNone(NewsImageGenerateRequest(news_text="x").tone)

    def test_both_entry_points_accept_both_tones(self):
        for tone in ("light", "dark"):
            with self.subTest(tone=tone):
                self.assertEqual(
                    GenerateRequest(news_text="x", type_label="資料圖表", tone=tone).tone, tone
                )
                self.assertEqual(NewsImageGenerateRequest(news_text="x", tone=tone).tone, tone)


class MutuallyExclusiveTests(unittest.TestCase):
    def test_one_tone_never_drags_in_the_other(self):
        for role in ROLES:
            for density in DENSITIES:
                with self.subTest(role=role, density=density):
                    dark = prompt(role=role, density=density, tone="dark")
                    light = prompt(role=role, density=density, tone="light")
                    self.assertIn("COLOUR TONE: DARK", dark)
                    self.assertNotIn("COLOUR TONE: LIGHT", dark)
                    self.assertIn("COLOUR TONE: LIGHT", light)
                    self.assertNotIn("COLOUR TONE: DARK", light)


class OverridesTemplateWordingTests(unittest.TestCase):
    def test_both_tones_say_they_outrank_the_style_guidance(self):
        for tone in ("dark", "light"):
            with self.subTest(tone=tone):
                self.assertIn(
                    "OVERRIDES ANY TONE WORDING IN THE STYLE GUIDANCE ABOVE",
                    prompt(tone=tone),
                )

    def test_tone_sits_after_the_density_and_stamp_blocks_it_may_reference(self):
        # 亮色調第 4 條要引用蓋章那條深色橫幅的例外，順序倒過來就引用不到
        text = prompt(density="verbatim", stamp=True, tone="light")
        self.assertLess(text.index("STAMP BANNER: ON"), text.index("COLOUR TONE: LIGHT"))
        self.assertLess(
            text.index("VERBATIM MODE (THE USER TURNED DIGESTION OFF)"),
            text.index("COLOUR TONE: LIGHT"),
        )

    def test_instruction_field_outranks_the_tone_block(self):
        text = prompt(tone="dark", instruction="用亮一點的底")
        self.assertIn("the colour tone block", text)
        self.assertLess(
            text.index("COLOUR TONE: DARK"),
            text.index("PRIORITY OVER THE USER'S OWN UI SETTINGS"),
            "指令欄優先序必須排在色調之後才蓋得掉它",
        )


class ContrastIsPinnedTests(unittest.TestCase):
    """明暗交給使用者，對比不交給模型——淺底淺字在電視上就是看不見。"""

    def test_dark_tone_pins_light_text(self):
        text = prompt(tone="dark")
        self.assertIn("must be light — white or near-white", text)
        self.assertIn("Never place dark text on the dark ground", text)

    def test_light_tone_pins_dark_text(self):
        text = prompt(tone="light")
        self.assertIn("must be DARK — near-black, deep navy or deep charcoal", text)
        self.assertIn("Never place white text on the light ground", text)

    def test_light_tone_keeps_accents_readable_on_pale_ground(self):
        self.assertIn("rather than pastel or neon", prompt(tone="light"))

    def test_light_tone_carves_out_the_stamp_banner(self):
        # 蓋章橫幅本來就是深底亮字的對比塊，不能被亮色調一併洗白
        self.assertIn("may keep its dark fill with light text", prompt(tone="light"))

    def test_directional_colour_rules_survive_both_tones(self):
        # 漲紅跌綠是內容語意，不隨色調改變
        for tone in ("dark", "light"):
            with self.subTest(tone=tone):
                self.assertIn("a rise is still red, a fall is still green", prompt(tone=tone))

    def test_tone_is_mood_not_subject(self):
        for tone in ("dark", "light"):
            with self.subTest(tone=tone):
                self.assertIn("This is the mood the user asked for", prompt(tone=tone))


if __name__ == "__main__":
    unittest.main()
