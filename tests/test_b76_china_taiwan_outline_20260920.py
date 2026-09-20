"""B76：中國大陸輪廓誤含臺灣（播出事故等級，2026-09-17 R7 實拍輪 A2 使用者當場指認）。

事故重現：新聞是「國銀對中國大陸曝險」，chart_type 判成「資料圖表」——不是地圖類，
走的是 MAP_SCOPE_GUARD_RULES 那條路，但成品仍把臺灣畫進中國大陸輪廓的同一圈填色／
光暈裡。MAP_ACCURACY_RULES（地圖類）與 MAP_SCOPE_GUARD_RULES（非地圖類「別畫地圖」）
都沒有明文禁止這件事本身，所以另立 `CHINA_TAIWAN_OUTLINE_RULES`，獨立於既有的
地圖／非地圖分流之外、不看 chart_type 一律注入——這正是本檔要釘住的地方：不管
分類結果落在哪一邊，這塊規則都要在。

使用者原話：「這是絕對不可以接受的，因為台灣不屬於中國大陸……一定要百分之百絕對
避免」。MASTER 列管清單.md B76 已裁定「這一波要修」並在「重凍預算已批准」節追加
授權重凍 `tests/test_reporter_prompt_frozen.py` 的 fixture。
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
import news_prompt  # noqa: E402
from main import AUTO_TYPE_LABEL, CHART_TYPE_CHOICES, build_digest_instructions  # noqa: E402
from news_prompt import MAP_TYPE_LABEL, build_prompt  # noqa: E402

NON_MAP_TYPES = [t for t in CHART_TYPE_CHOICES if t != MAP_TYPE_LABEL]
# 事故重現的實際型別：資料圖表（非地圖類，走 MAP_SCOPE_GUARD_RULES 那條路）
INCIDENT_TYPE_LABEL = "資料圖表"


def digest(type_label: str, role: str = "記者", density: str = "standard", full_bleed: bool = False) -> str:
    return build_digest_instructions(role, density, type_label, full_bleed=full_bleed)


def image_prompt(type_label: str, role: str = "記者", engine: str = "gemini") -> str:
    return build_prompt(
        role=role, engine=engine, type_label=type_label,
        style="S", structure="T", variable="V", safe_frame=True,
    )


class ChinaTaiwanOutlineInjectionTests(unittest.TestCase):
    """不管分類落在地圖類還是非地圖類，這塊規則都要在——這正是 B76 事故證明
    既有兩塊規則（各自只顧地圖準確度／別畫地圖）擋不住的地方。
    """

    def test_map_type_gets_the_rule(self):
        prompt = digest(MAP_TYPE_LABEL)
        self.assertIn("MAP ACCURACY RULES", prompt)
        self.assertIn("CHINA OUTLINE / TAIWAN SEPARATION", prompt)

    def test_auto_type_gets_the_rule(self):
        prompt = digest(AUTO_TYPE_LABEL)
        self.assertIn("MAP ACCURACY RULES", prompt)
        self.assertIn("CHINA OUTLINE / TAIWAN SEPARATION", prompt)

    def test_every_non_map_type_gets_the_rule_including_the_incident_type(self):
        for type_label in NON_MAP_TYPES:
            with self.subTest(type_label=type_label):
                prompt = digest(type_label)
                self.assertIn("MAP SCOPE GUARD", prompt)
                self.assertIn("CHINA OUTLINE / TAIWAN SEPARATION", prompt)
        self.assertIn(INCIDENT_TYPE_LABEL, NON_MAP_TYPES)

    def test_present_for_both_roles(self):
        for role in ("記者", "編輯"):
            with self.subTest(role=role):
                self.assertIn(
                    "CHINA OUTLINE / TAIWAN SEPARATION",
                    digest(INCIDENT_TYPE_LABEL, role=role),
                )

    def test_present_for_every_density_and_layout_combo(self):
        for density in ("standard", "simplified"):
            for full_bleed in (True, False):
                with self.subTest(density=density, full_bleed=full_bleed):
                    prompt = digest(INCIDENT_TYPE_LABEL, density=density, full_bleed=full_bleed)
                    self.assertIn("CHINA OUTLINE / TAIWAN SEPARATION", prompt)


class ChinaTaiwanOutlineContentTests(unittest.TestCase):
    """規則措辭要是可檢驗的具體禁令，不是空泛的「不要把臺灣畫進中國」。"""

    def setUp(self):
        self.rule = main.CHINA_TAIWAN_OUTLINE_RULES

    def test_names_every_outlying_island(self):
        for name in ("臺灣", "澎湖", "金門", "馬祖"):
            with self.subTest(name=name):
                self.assertIn(name, self.rule)

    def test_hainan_is_explicitly_carved_out(self):
        # 海南島本來就是中國領土，規則要講清楚這條不是在禁海南島同色
        self.assertIn("海南島", self.rule)
        self.assertIn("PRC territory", self.rule)

    def test_applies_regardless_of_chart_type_wording(self):
        self.assertIn("no matter what chart type", self.rule)
        self.assertIn("data chart", self.rule)

    def test_zero_tolerance_wording_present(self):
        self.assertIn("ZERO TOLERANCE", self.rule)

    def test_fallback_when_renderer_cannot_be_trusted(self):
        # 沒把握時的退路：乾脆別畫輪廓，改用文字描述
        self.assertIn("do not ask for China's outline or silhouette at all", self.rule)


class ChinaTaiwanOutlineImagePromptInjectionTests(unittest.TestCase):
    """事故根因其實在生圖端：那則新聞 chart_type=資料圖表，生圖模型連
    MAP_ACCURACY_IMAGE_RULES（只在地圖類才注入）都拿不到，是它自己把臺灣填進
    中國大陸輪廓的裝飾背景，不是消化端的 structure 叫它這樣畫。只在消化端補規則
    擋不住生圖模型自己的世界知識，所以 news_prompt.build_prompt() 也要比照
    TEXT_PLACEMENT_RULES 不看 type_label 一律注入這一塊。
    """

    def test_map_type_gets_the_rule(self):
        prompt = image_prompt(MAP_TYPE_LABEL)
        self.assertIn("MAP ACCURACY RULES", prompt)
        self.assertIn("CHINA OUTLINE / TAIWAN SEPARATION", prompt)

    def test_every_non_map_type_gets_the_rule_including_the_incident_type(self):
        for type_label in NON_MAP_TYPES:
            with self.subTest(type_label=type_label):
                prompt = image_prompt(type_label)
                self.assertNotIn("MAP ACCURACY RULES", prompt)
                self.assertIn("CHINA OUTLINE / TAIWAN SEPARATION", prompt)
        self.assertIn(INCIDENT_TYPE_LABEL, NON_MAP_TYPES)

    def test_present_for_both_roles_and_engines(self):
        for role in ("記者", "編輯"):
            for engine in ("gemini", "gpt"):
                with self.subTest(role=role, engine=engine):
                    self.assertIn(
                        "CHINA OUTLINE / TAIWAN SEPARATION",
                        image_prompt(INCIDENT_TYPE_LABEL, role=role, engine=engine),
                    )

    def test_present_regardless_of_safe_frame_and_no_text_mode(self):
        base = news_prompt.build_prompt(
            role="記者", engine="gemini", type_label=INCIDENT_TYPE_LABEL,
            style="S", structure="T", variable="V", safe_frame=False,
        )
        no_text = news_prompt.build_prompt(
            role="記者", engine="gemini", type_label=INCIDENT_TYPE_LABEL,
            style="S", structure="T", variable="V", safe_frame=False, no_text=True,
        )
        self.assertIn("CHINA OUTLINE / TAIWAN SEPARATION", base)
        self.assertIn("CHINA OUTLINE / TAIWAN SEPARATION", no_text)


class ChinaTaiwanOutlineImagePromptContentTests(unittest.TestCase):
    """生圖端的措辭要對生圖模型講「不要畫」，不是消化端那句「改用文字描述」——
    生圖端沒有 structure 這層退路。
    """

    def setUp(self):
        self.rule = news_prompt.CHINA_TAIWAN_OUTLINE_IMAGE_RULES

    def test_names_every_outlying_island(self):
        for name in ("臺灣", "澎湖", "金門", "馬祖"):
            with self.subTest(name=name):
                self.assertIn(name, self.rule)

    def test_hainan_is_explicitly_carved_out(self):
        self.assertIn("海南島", self.rule)
        self.assertIn("PRC territory", self.rule)

    def test_zero_tolerance_wording_present(self):
        self.assertIn("ZERO TOLERANCE", self.rule)

    def test_fallback_tells_the_renderer_not_to_draw(self):
        self.assertIn("do not draw China's outline or silhouette at all", self.rule)


class DedicatedInstructionCannotRelaxTheRuleTests(unittest.TestCase):
    """B76 規則要進 DEDICATED_INSTRUCTION_RULES_TEMPLATE 的「不可鬆綁」清單，
    否則使用者指令欄理論上可以宣稱「outranks the visual style」而蓋過它。
    """

    def test_never_relax_list_names_the_rule(self):
        prompt = build_digest_instructions(
            "記者", "standard", INCIDENT_TYPE_LABEL, user_instruction="用手繪風",
        )
        self.assertIn("PRIORITY OVER THE USER'S OWN UI SETTINGS", prompt)
        self.assertIn("It does NOT outrank", prompt)
        idx = prompt.index("It does NOT outrank")
        self.assertIn("CHINA OUTLINE / TAIWAN SEPARATION", prompt[idx:idx + 400])


if __name__ == "__main__":
    unittest.main()
