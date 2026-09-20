"""記者與編輯的 digest prompt 逐字元快照。

2026-08-17 使用者要求記者 prompt 不得被編輯端修改誤傷。兩個角色共用不少常數，
這類漂移不會出現執行期錯誤，卻會讓成品悄悄改變；因此以 role × density × 安全框
的快照逐字比對。未經明確放行不得更新 fixture。

快照更新記錄：
- 2026-09-09：使用者要求「字多」在**記者與編輯共通**放寬（資訊卡數量／密度／字數），
  density="standard" 因此開始注入 STANDARD_DENSITY_RULES，記者的 standard 兩份快照
  隨之更新。這是明確行為變更，不是誤傷。
- 2026-09-10：非地圖類型改成一律注入 MAP_SCOPE_GUARD_RULES；四份記者快照因此更新。
  起因是 type_label=資訊卡 的高溫新聞畫出縣市界全錯的臺灣地圖。
- 2026-09-14：CP1 經使用者放行，D16 以 10／13／18／22 接上標題可見字元上限，D2
  收窄為只禁螢光綠／chroma-key green。這是有意改動記者 prompt，不是誤傷；同次補齊
  編輯的 standard／simplified × fullbleed／safearea 四份 digest 快照。
- 2026-09-16：Stage 3（B57＋F41 文字端）經使用者放行重凍。八份 digest 快照都因
  F41 改寫 REAL_WORLD_FIDELITY_RULES 第 5、7 條（人名只准逐字擷取，英文名原文不
  存在就留空）。其中四份 standard 另外因 B57 把「最多六點」改成 target 6／下限 5。
  未改 image snapshot、RNG pins 或其他 fixture。
- 2026-09-16（Stage 5a，B53＋F40＋F41 生圖端＋B66）：這一批的凍結額度涵蓋
  B57、B61、F40、F41、B66，但本檔管的是 `build_digest_instructions()`（文字端 digest
  prompt），F40／B66 動到的是 `news_prompt.build_prompt()` 的 portrait_mode 相關常數
  （PORTRAIT_WITH_REFERENCE_RULES／PORTRAIT_MULTI_WITH_REFERENCE_RULES／
  USER_REFERENCE_PORTRAIT_RULES／PORTRAIT_NO_REFERENCE_RULES／新增的
  PORTRAIT_ENTRY_ONLY_RULES）。這些常數只在明確傳入非 "none" 的 portrait_mode 時才
  注入，而本檔所有快照都用預設 portrait_mode="none" 呼叫 `build_digest_instructions()`，
  逐一核對後確認**沒有任何一份快照的文字因這批改動而變**，因此本批**沒有重建任何
  fixture**（`tests/fixtures/` 目錄零異動，`git diff --stat` 可查證）。
  B53（news_text 併入補畫面描述的 material）與四層分流的 mode 判斷邏輯只影響
  `main.py` 的 cover／yt-cover／一般生圖路徑，同樣不動這裡管的 digest 快照。
- 2026-09-20（B76）：中國大陸輪廓誤含臺灣（播出事故等級，使用者當面追加授權重凍，
  見 MASTER-列管清單.md「重凍預算已批准」節）。分兩層修，兩層各補一塊新規則：
  ① 消化端 `main.py` 新增 `CHINA_TAIWAN_OUTLINE_RULES`，明文禁止把臺灣／澎湖／
  金門／馬祖畫進中國大陸的輪廓、同填色或同一圈光暈，獨立於既有的地圖／非地圖分流
  （`MAP_ACCURACY_RULES` 對 `MAP_SCOPE_GUARD_RULES`）之外一律注入。八份 digest
  快照都因此在 `MAP SCOPE GUARD` 段落之後多出這一塊。
  ② 生圖端 `news_prompt.py` 新增 `CHINA_TAIWAN_OUTLINE_IMAGE_RULES`，比照
  `TEXT_PLACEMENT_RULES` 不看 type_label 一律注入到 `build_prompt()`——事故根因
  在這一層：那則新聞的 chart_type 是「資料圖表」，生圖模型本來連 `MAP_ACCURACY_
  IMAGE_RULES`（只在地圖類才注入）都拿不到，是它自己把臺灣填進中國大陸輪廓的裝飾
  背景，不是消化端的 structure 叫它這樣畫；只修消化端擋不住生圖模型自己的世界知識。
  兩份 `reporter-image-prompt-{safeframe,plain}.txt` 因此在 `TEXT PLACEMENT` 段落
  之後、`FINAL OUTPUT RULE` 之前多出這一塊。
  逐一核對後確認十份快照**其餘文字完全沒有改變**；沒有動到 RNG pins 或其他 fixture。
"""

import os
import pathlib
import unittest

import news_prompt

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import build_digest_instructions  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def frozen(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ReporterDigestFrozenTests(unittest.TestCase):
    def test_digest_instructions_unchanged(self):
        for role, fixture_role in (("記者", "reporter"), ("編輯", "editor")):
            for density in ("standard", "simplified"):
                for full_bleed in (True, False):
                    tag = "fullbleed" if full_bleed else "safearea"
                    with self.subTest(role=role, density=density, mode=tag):
                        self.assertEqual(
                            build_digest_instructions(
                                role, density, "資料圖表", full_bleed=full_bleed
                            ),
                            frozen(f"{fixture_role}-digest-{density}-{tag}.txt"),
                            f"{role}的消化指令被改到了",
                        )


class ReporterImagePromptFrozenTests(unittest.TestCase):
    def test_image_prompt_unchanged(self):
        for safe_frame in (True, False):
            tag = "safeframe" if safe_frame else "plain"
            with self.subTest(mode=tag):
                self.assertEqual(
                    news_prompt.build_prompt(
                        role="記者", engine="gpt", type_label="資料圖表",
                        style="[S]", structure="[T]", variable="[V]",
                        safe_frame=safe_frame,
                    ),
                    frozen(f"reporter-image-prompt-{tag}.txt"),
                    "記者的生圖 prompt 被改到了",
                )


if __name__ == "__main__":
    unittest.main()
