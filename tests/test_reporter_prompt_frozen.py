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
- 2026-09-20（B70／F43）：使用者當面追加重凍額度，把「示意圖」標籤全站化——
  Stage 5a 那批只改了 portrait_mode≠"none" 時才注入的四個 PORTRAIT_* 區塊
  （見上一條），沒有動「no portrait block present」時的預設路徑，那條預設路徑
  這一批才補上，本檔管的 `build_digest_instructions()`（unconditional 注入，不看
  portrait_mode）與 `news_prompt.build_prompt()` 的預設路徑因此都要重凍。
  改了兩處：①`main.py` 的 `REAL_WORLD_FIDELITY_RULES` 第 3、5 條——原本要求
  文字模型「把『示意圖』寫進 variable」，改成「不要自己寫，成品由後端程式壓字」，
  與 B70 甲案（compose.paste_disclaimer_note）呼應，消化端不再產出這個字串。
  ②`news_prompt.py` 的 `REAL_WORLD_RENDERING_RULES` 第 2、4 條（一般重建圖的預設
  標籤規則、NAMED REAL PEOPLE 沒有專屬 portrait 區塊時的預設分支）——同樣從
  「模型自己畫」改成「軟體後貼在右下角，模型只需留空」。②同時是 `app.js` 的
  `REAL_WORLD_RENDERING_RULES` 平行常數（`tests/test_prompt_parity.py` 逐字比對），
  已同步改過，兩邊仍逐字相同。
  ⚠**這批刻意沒有改的**：`main.py` 的 `CONTENT_FIDELITY_RULES` 第 6 條（禁止
  「示意圖」等版型名稱出現在 variable 裡）——那條講的是別的事（版型名稱不是新聞
  內容），不是標籤機制，維持原樣；也沒有替「非具名人物的一般重建圖」（例如單純
  建物、事件現場）新增程式端判斷是否要壓標籤的邏輯——目前後端只在
  portrait_mode ∈ {reference, reference_multi, entry_only} 時才會真的貼「示意圖」
  （見 `main.resolve_image_disclaimer`），這批只把「模型不要自己畫」的 prompt 半
  邊補齊，「一般重建圖到底該不該自動貼」是待裁的 D 級題，不在這批範圍內，
  未裁決前這類圖仍不會有任何標籤（不是退步，是本來就沒有，只是現在也不會被
  模型自己畫出一個來湊數）。
  重建的十份快照：`reporter/editor-digest-{standard,simplified}-{fullbleed,safearea}.txt`
  （八份，`REAL_WORLD_FIDELITY_RULES` 那兩條差異）、
  `reporter-image-prompt-{plain,safeframe}.txt`（兩份，`REAL_WORLD_RENDERING_RULES`
  那兩條差異）。`git diff --stat tests/fixtures/` 只列出這十份，`cover_design_brief_rng_pins_20260911.json`
  等其他 fixture 零異動。
- 2026-09-20（B70／F43 修正，同日稍後）：回填 B70／F43 帳本時自己發現上一條的
  一半程度不夠——同一批把「不要自己畫，軟體會後貼」推到 `portrait_mode=none`（一般重建圖）與
  `no_reference`（無人場景）這兩條路，但 `resolve_image_disclaimer()` 只在
  `PORTRAIT_MODES_NEEDING_DISCLAIMER`（reference／reference_multi／entry_only）
  才回 `"ai"`，這兩條路永遠回 `""`，變成「模型不畫、軟體也不壓」，標籤從
  「有時錯」惡化成「保證沒有」。⚠**使用者尚未裁決這一題**——這裡是依既有原則
  直接推論（沒有軟體背書就不能叫模型不要畫，寧可讓模型畫醜一點的標籤也不能
  整個消失）先回到全站化之前的安全值，不是替使用者拍板；軟體端要不要也對
  none／no_reference 補壓、觸發條件是什麼，仍登記在帳本 B70 待裁。
  因此**回退**上一條的以下部分（其餘
  三個有軟體背書的 portrait_mode 區塊不受影響，仍是「不要自己畫」）：
  ①`main.py` `REAL_WORLD_FIDELITY_RULES` 第 3 條（一般重建圖）回退成原始
  「你必須把示意圖寫進 variable」；第 5 條（具名真人）**不回退**，因為
  no_reference 不畫臉、本來就沒有字要寫，三個有背書的 mode 仍然靠這句避免
  雙重標籤。②`news_prompt.py` `REAL_WORLD_RENDERING_RULES` 第 2、4 條與 `app.js`
  鏡像常數回退成原始「模型自己判斷、必須清楚可見」。③`news_prompt.py`
  `PORTRAIT_NO_REFERENCE_RULES`（非凍結，no_reference 專屬區塊）同步回退。
  十份 fixture 因此第二次改動，`git diff --stat tests/fixtures/` 這次也只列出
  同一批十份，每份只改回這一兩句，B76 那塊與其餘內容不受影響（逐份 grep
  `CHINA OUTLINE`／`TAIWAN SEPARATION` 十份仍全部找得到）。
- 2026-09-20（B70 第 5 條收窄，同日再稍後）：獨立複查（gpt-5.6-sol，第二輪）點名
  上一條「第 5 條不回退」的理由不成立。第 5 條寫的是「Never write 示意圖 into
  "variable" for a **depicted person**」，而 `portrait_subjects` 依它自己的定義
  只收**會露臉**的具名真人；因此「具名真人出現在畫面上、但只畫背影／剪影／無臉
  替身」會落到 `portrait_mode="none"`——模型被第 5 條禁止規劃標籤，
  `resolve_image_disclaimer("none", "")` 又回 `("", "")` 程式也不貼，
  **一個具名真人的重建畫面完全沒有示意圖標籤**。跟上一條修的是同一個病灶，
  只是躲在第 5 條裡。
  修法不是整條回退，是把豁免範圍**收窄**到 `portrait_subjects` 這個陣列本身，
  並明講沒列進去的人仍適用第 3 條（模型自己規劃標籤）。三個有軟體背書的
  portrait_mode 行為不變，雙重標籤仍然擋著。
  只動 `main.py` 的 `REAL_WORLD_FIDELITY_RULES` 第 5 條一句 ⇒ **八份 digest
  快照**第三次改動、每份只差一行（`git diff --numstat tests/fixtures/` 全是
  `1 1`）；兩份 `reporter-image-prompt-*.txt` **這次沒有變**（`news_prompt.py`
  沒動）。B76 那塊逐份 grep 十份仍全部找得到。
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
