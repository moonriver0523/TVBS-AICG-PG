# 淺色精品科技與編輯安全框 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在第二頁四種圖表類型加入共用「淺色風格 → 銀藍香檳金」，移除編輯版消化的配色範例錨定，並將編輯薄邊安全框由實際 3% 改為四邊 4%。

**Architecture:** 前端風格以一個不可變的共用物件供四個 `styles` 資料表引用，沿用現有 `renderParents()`／`renderTags()`／`updateSpecificField()`，不新增 UI 狀態或分支。消化端只中性化 `EDITOR_SYSTEM_PROMPT_TEMPLATE` 的 style 指令；安全框仍以 `safe_area_spec.PROFILES` 為唯一幾何來源，前端只顯示同步文案。

**Tech Stack:** Vanilla JavaScript、HTML、Python 3.14、FastAPI、Pydantic、Pillow、`unittest`。

## Global Constraints

- 第二頁分類固定為 `淺色風格`，選項固定為 `銀藍香檳金`。
- 四種圖表類型都必須引用同一個 `LIGHT_LUXURY_TECH_STYLE` 物件，不複製四份 Prompt。
- 編輯版消化 style 指令不得包含任何範例色名；記者版 Prompt 與 frozen fixture 不得變動。
- 編輯薄邊安全框固定為 1920×1080 上的 `(77, 43, 1766, 994)`，約為四邊 4%。
- 記者官方安全框與編輯對位框不得變動。
- 不新增淺色模式開關、不部署、不呼叫付費圖片 API。
- 不執行可能呼叫真實 API 的全套測試；只執行本計畫列出的無付費測試。
- 不 commit，除非使用者另行明確要求。

---

### Task 1: 新增四種類型共用的淺色風格

**Files:**
- Create: `tests/test_light_luxury_style.py`
- Modify: `app.js:9-32`
- Modify: `app.js:117-133`
- Modify: `app.js:172-186`
- Modify: `app.js:228-242`
- Modify: `index.html:629`

**Interfaces:**
- Consumes: 既有 `CHART_TYPES[type].styles[parent] -> Array<{zh: string, en: string}>` 資料介面。
- Produces: `const LIGHT_LUXURY_TECH_STYLE = {zh: '銀藍香檳金', en: string}`，並由四個 `styles` 物件的 `淺色風格` 陣列引用。

- [x] **Step 1: 建立會失敗的前端風格守門測試**

建立 `tests/test_light_luxury_style.py`：

```python
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "app.js"
INDEX_HTML = ROOT / "index.html"


class LightLuxuryStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_JS.read_text(encoding="utf-8")

    def test_shared_style_is_registered_for_all_four_chart_types(self):
        self.assertIn("const LIGHT_LUXURY_TECH_STYLE = {", self.source)
        self.assertEqual(
            self.source.count("'淺色風格': [LIGHT_LUXURY_TECH_STYLE]"),
            4,
        )

    def test_style_keeps_the_verified_palette_and_material_contract(self):
        for token in (
            "銀藍香檳金",
            "#B4C7D5",
            "#D1DADB",
            "#A3B8CA",
            "#CBA352",
            "#D6CDAF",
            "#966F30",
            "brushed metal",
            "high-key studio lighting",
            "large dark-blue or black background",
            "rise and increase use red",
            "fall and decrease use green",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_cache_buster_moves_forward(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('app.js?v=20260820a', html)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: 執行測試並確認紅燈理由正確**

Run:

```bash
./.venv/Scripts/python.exe -m unittest tests.test_light_luxury_style -v
```

Expected: FAIL；缺少 `LIGHT_LUXURY_TECH_STYLE`、四個 `淺色風格` 註冊及新 cache-buster。

- [x] **Step 3: 在 `app.js` 定義唯一共用風格物件**

在 `SHARED_STYLES` 前加入：

```javascript
const LIGHT_LUXURY_TECH_STYLE = {
    zh: '銀藍香檳金',
    en: 'Professional Taiwanese broadcast infographic in a light-luxury technology aesthetic: overall high-brightness, low-to-medium saturation; misty blue-grey, silver-blue and pearl-white background tones (#B4C7D5, #D1DADB, #A3B8CA); semi-transparent ice-blue, silvery-white and cool-grey glass information panels; champagne-gold, soft-gold and restrained antique-bronze accents (#CBA352, #D6CDAF, #966F30); all text in deep steel-grey or deep blue-grey; never use pure black text, a large dark-blue or black background, neon colours or saturated tech blue; use translucent glass, brushed metal, fine line-grid textures and soft high-key studio lighting for a clean upscale broadcast finish. Taiwan directional colour convention is mandatory: rise and increase use red, fall and decrease use green; do not use red or green as unrelated decoration.'
};
```

- [x] **Step 4: 將同一物件註冊到四種圖表類型**

在 `SHARED_STYLES`、`scene.styles`、`map.styles`、`process.styles` 各加入一次：

```javascript
'淺色風格': [LIGHT_LUXURY_TECH_STYLE]
```

每個相鄰屬性之間保留正確逗號；不得複製 `en` 字串。

- [x] **Step 5: 更新前端 cache-buster**

將 `index.html`：

```html
<script src="app.js?v=20260819a"></script>
```

改為：

```html
<script src="app.js?v=20260820a"></script>
```

- [x] **Step 6: 執行測試確認綠燈**

Run:

```bash
./.venv/Scripts/python.exe -m unittest tests.test_light_luxury_style -v
```

Expected: 3 tests PASS。

- [x] **Step 7: 檢查本 Task diff**

Run:

```bash
git diff --check
git diff -- app.js index.html tests/test_light_luxury_style.py
```

Expected: `diff --check` 無輸出；四種類型只引用共用常數，沒有四份重複 Prompt。

---

### Task 2: 移除編輯版消化的配色範例錨定

**Files:**
- Modify: `tests/test_digest_prompts.py:22-77`
- Modify: `main.py:338-357`

**Interfaces:**
- Consumes: `build_digest_instructions(role: str, density: DigestDensity, type_label: str, ...) -> str`。
- Produces: 編輯版中性的 style 指令；記者版輸出逐字不變。

- [x] **Step 1: 先寫會失敗的編輯版中性配色測試**

在 `DigestPromptTests` 加入：

```python
    def test_editor_style_rule_chooses_colours_without_examples(self):
        prompt = build_digest_instructions("編輯", "standard", "資料圖表")
        self.assertIn(
            '根據新聞調性（財經、災難、溫馨、政治）自行選擇最合適的主色調與畫面風格',
            prompt,
        )
        self.assertNotIn("深藍色科技感", prompt)
        self.assertNotIn("紅白色警戒感", prompt)
```

- [x] **Step 2: 執行單一測試確認先失敗**

Run:

```bash
./.venv/Scripts/python.exe -m unittest tests.test_digest_prompts.DigestPromptTests.test_editor_style_rule_chooses_colours_without_examples -v
```

Expected: FAIL；新中性句子不存在，舊範例仍存在。

- [x] **Step 3: 最小化修改 `EDITOR_SYSTEM_PROMPT_TEMPLATE`**

把 `main.py` 的 style 規則：

```text
2. "style": 根據新聞調性（財經、災難、溫馨、政治）選擇主色調與畫面風格（例如：深藍色科技感、紅白色警戒感），written in professional English.
```

改為：

```text
2. "style": 根據新聞調性（財經、災難、溫馨、政治）自行選擇最合適的主色調與畫面風格，written in professional English.
```

不得修改 `SYSTEM_PROMPT_TEMPLATE` 或任何記者 fixture。

- [x] **Step 4: 執行消化 Prompt 相關測試**

Run:

```bash
./.venv/Scripts/python.exe -m unittest tests.test_digest_prompts tests.test_reporter_prompt_frozen -v
```

Expected: 全部 PASS；新增測試綠燈，記者 frozen fixture 維持逐字一致。

- [x] **Step 5: 靜態確認全庫主流程不再含舊範例**

Run:

```bash
rg -n "深藍色科技感|紅白色警戒感" main.py tests
```

Expected: 只允許出現在斷言 `assertNotIn`；`main.py` 不得命中。

---

### Task 3: 將編輯薄邊安全框改為四邊 4%

**Files:**
- Modify: `tests/test_safe_frame.py:442-531`
- Modify: `safe_area_spec.py:15-45`
- Modify: `app.js:748-758`
- Modify: `TODO.md:42-60`

**Interfaces:**
- Consumes: `safe_area_spec.PROFILES[EDITOR_FRAME_PROFILE]` 與 `safe_area_spec.required_margins_px()`。
- Produces: `EDITOR_FRAME_PROFILE == (77, 43, 1766, 994)`；前端徽章顯示四邊 4%。

- [x] **Step 1: 先把安全框測試改成目標 4% 規格**

在 `EditorTwoFrameModesTests` 將：

```python
    THIN_FRAME_RATIO = 0.03
```

改為：

```python
    THIN_FRAME_RATIO = 0.04  # 使用者 2026-08-20 指定（2% → 4% → 3% → 4%）
```

並把百分比測試的 docstring 改成：

```python
        """4% 是使用者指定的數字，四邊都要精準吃到，不能只對兩邊。"""
```

在同一 class 加入精確基準測試：

```python
    def test_thin_frame_uses_the_four_percent_base_geometry(self):
        self.assertEqual(
            safe_area_spec.PROFILES[safe_area_spec.EDITOR_FRAME_PROFILE],
            (77, 43, 1766, 994),
        )
```

並把 `test_thin_frame_fits_sixteen_by_nine_without_cropping` 的 docstring 從 `2%` 改成 `4%`。

- [x] **Step 2: 執行安全框單元測試確認紅燈**

Run:

```bash
./.venv/Scripts/python.exe -m unittest tests.test_safe_frame.EditorTwoFrameModesTests -v
```

Expected: FAIL；現況仍是 `(58, 32, 1804, 1016)` 與約 3%。

- [x] **Step 3: 修改唯一幾何來源**

在 `safe_area_spec.py` 將：

```python
    EDITOR_FRAME_PROFILE: (58, 32, 1804, 1016),
```

改為：

```python
    EDITOR_FRAME_PROFILE: (77, 43, 1766, 994),
```

同步更新相鄰註解：目前值為 4%，2026-08-20 使用者由 3% 改回 4%，內容區比例約 1.7767。保留三種比例都在幾何容差內的歷史說明。

- [x] **Step 4: 修正前端徽章文案**

在 `app.js` 將：

```javascript
? `${currentAspectRatio()} → 編輯安全框（四邊 2%）1920×1080`
```

改為：

```javascript
? `${currentAspectRatio()} → 編輯安全框（四邊 4%）1920×1080`
```

- [x] **Step 5: 更新 TODO 的目前狀態與歷程**

將 `TODO.md` 開頭編輯 ON 模式更新為：

```markdown
- **ON ＝ 新的**：滿版 16:9 → 四邊各壓 4% → 完整 1920×1080
```

將幾何說明更新為 `77/43` 留白、`1766×994` 內容區、比例約 `1.7767`，並記錄歷程：2026-08-19 的 `2%→4%→3%`，2026-08-20 使用者再裁決為 `4%`。投影段落保留「4% 仍由 `_shadow_fits()` 通則停用」的既有實測結論。

- [x] **Step 6: 執行安全框與規格測試**

Run:

```bash
./.venv/Scripts/python.exe -m unittest tests.test_safe_frame tests.test_safe_area_spec tests.test_news_image_endpoint -v
```

Expected: 全部 PASS；記者框 `(140, 109, 1634, 751)` 與編輯對位框 `(90, 70, 1748, 924)` 維持不變。

- [x] **Step 7: 檢查本 Task diff**

Run:

```bash
git diff --check
git diff -- safe_area_spec.py app.js tests/test_safe_frame.py TODO.md
```

Expected: `diff --check` 無輸出；所有「目前值」文案一致為 4%，歷史敘述保留完整。

---

### Task 4: 無付費整合驗證與瀏覽器驗收

**Files:**
- Verify: `app.js`
- Verify: `index.html`
- Verify: `main.py`
- Verify: `safe_area_spec.py`
- Verify: `tests/test_light_luxury_style.py`
- Verify: `tests/test_digest_prompts.py`
- Verify: `tests/test_safe_frame.py`
- Verify: `TODO.md`

**Interfaces:**
- Consumes: Tasks 1–3 的前端風格、消化 Prompt 與安全框幾何。
- Produces: 可在第二頁操作的四類共用風格，以及一致的 4% 安全框顯示；不產生圖片 API 請求。

- [x] **Step 1: 執行所有受影響的無付費測試**

Run:

```bash
./.venv/Scripts/python.exe -m unittest \
  tests.test_light_luxury_style \
  tests.test_digest_prompts \
  tests.test_reporter_prompt_frozen \
  tests.test_prompt_parity \
  tests.test_safe_frame \
  tests.test_safe_area_spec \
  tests.test_news_image_endpoint -v
```

Expected: 全部 PASS，沒有真實圖片 API 呼叫。

- [x] **Step 2: 掃描禁止的未完成標記**

Run:

```bash
rg -n "TODO|TBD|test\.skip|\.only\(" app.js index.html main.py safe_area_spec.py tests/test_light_luxury_style.py tests/test_digest_prompts.py tests/test_safe_frame.py
```

Expected: 不得出現本次新增的占位符、跳過測試或 `.only(`；既有註解若命中，逐筆確認與本次無關。

- [x] **Step 3: 啟動本機網站**

Run:

```bash
./.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8788
```

Expected: `Uvicorn running on http://127.0.0.1:8788`。

- [x] **Step 4: 在瀏覽器逐一驗收四種類型**

開啟 `http://127.0.0.1:8788/`，點選「進階微調」。依序操作：

1. 點選「資料圖表」→「風格包／子風格」→「淺色風格」→「銀藍香檳金」。
2. 重複檢查「情境示意圖」「地圖／位置」「3D示意／流程」。
3. 每一類都確認 `field-style` 出現 `#B4C7D5`、`#CBA352`、`brushed metal`。
4. 確認 Final Prompt Output 同步包含該完整風格。
5. 切換角色為「編輯」，確認安全框 ON 徽章顯示「四邊 4%」。
6. 不點「一鍵生成」、不勾確認 Prompt、不點任何生成圖片按鈕。

Expected: 四類皆可選且寫入 Prompt；徽章顯示 4%；Network 面板沒有 `/api/images/generate` 或 `/api/news-image/generate` 請求。

- [x] **Step 5: 最終工作樹與差異檢查**

Run:

```bash
git status --short --branch
git diff --check
git diff --stat
git diff -- app.js index.html main.py safe_area_spec.py tests/test_light_luxury_style.py tests/test_digest_prompts.py tests/test_safe_frame.py TODO.md docs/superpowers/specs/2026-08-20-light-luxury-tech-style-design.md
```

Expected: 只有本計畫列出的檔案變更；沒有 `.env`、金鑰、生成圖或其他非預期檔案；`diff --check` 無輸出。
