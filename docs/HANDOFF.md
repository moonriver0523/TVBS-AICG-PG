# 新聞 CG Prompt 生成器 — 技術交接文件

> 這份文件用來讓新的 Claude Code 工作階段快速接手專案，不必重新解釋背景、架構與目前進度。

---

## 一、專案是什麼

這是一個給 TVBS 國際新聞使用的內部工具。使用者輸入新聞素材或少數變量後，系統依標準化模板組成圖片生成 Prompt，交給 Gemini 或 GPT 產出電視新聞資訊圖表（CG）。

核心目標是把新聞圖表的視覺風格、構圖、文字內容與播出安全區規格標準化，減少每次從零撰寫 Prompt 的時間。產品成敗不只看能否生成圖片，而要看內容是否正確、能否直接上鏡、是否減少重生與人工修圖，以及單張製作時間能否由 20～30 分鐘降低至約 10 分鐘。

原始「準時收工」提案的產品痛點、KPI、導入路線與功能優先原則整理於 `docs/product-proposal-summary.md`。後續重大功能決策應同時參考該文件。

目前版本為 **V8.2**。專案已從單檔 Artifact 原型演進為本機前後端工具，但尚未正式部署成多人使用的網路服務。

---

## 二、目前檔案結構

```text
project/
├── index.html                  # 前端 UI 與樣式（Tailwind CDN）
├── app.js                      # 模板資料、狀態、渲染、Prompt 組合與前端 API 呼叫
├── main.py                     # FastAPI 後端：AI 消化與 Gemini／GPT 圖片生成代理
├── dev.sh                      # 同時啟動後端 8787 與 BrowserSync 前端 3000
├── pyproject.toml / uv.lock    # Python 依賴與鎖定檔
├── tests/
│   └── test_digest_prompts.py  # AI 消化密度與後端預設規則測試
├── notion-templates/           # 記者 Notion 資料庫快照、代表圖與解析工具
├── editor-templates/           # 編輯版 Prompt、提案與版型參考圖
└── docs/
    ├── HANDOFF.md
    ├── product-proposal-summary.md  # 原始提案產品目標、KPI 與功能缺口
    ├── notion-integration-plan.md
    └── superpowers/            # 已核准設計規格與實作計畫
```

開發時執行：

```bash
./dev.sh
```

- 前端即時預覽：`http://localhost:3000`
- FastAPI 後端：`http://127.0.0.1:8787`

`index.html` 與 `app.js` 維持分離，BrowserSync 會在修改後自動刷新頁面。

---

## 三、核心架構：三層變量模型

一張新聞圖表拆成三層：

```text
風格（Style）      → 品牌配色、材質、視覺語言
構圖（Structure）  → 元素排列、資訊層級、圖表或場景布局
變量（Variable）   → 標題、數據、重點文字等實際內容
```

三層可以獨立替換。同一套構圖可以套用不同風格，使用者也可以只更換變量來重複產出同類型圖表。

### `CHART_TYPES`

`app.js` 目前有四大類型：

```js
CHART_TYPES = {
  data:    { label: '資料圖表', styles, structures, visual },
  scene:   { label: '情境示意圖', styles, structures, visual },
  map:     { label: '地圖／位置', styles, structures, visual },
  process: { label: '3D示意／流程', styles, structures, visual }
}
```

每個類型包含：

- `styles`：UI 顯示名稱 `zh` 與實際 Prompt 描述 `en`
- `structures`：構圖描述及可自動帶入的 `template`
- `visual`：背景、視感、標記、後製預留等補充要求

共用資源：

- `SHARED_STYLES`：TVBS、ABC、CNN、CNBC、Bloomberg、Art Deco 等風格
- `CARD_LAYOUT_ITEMS`：雙分割、三分割、四分割、半版示意圖等卡牌構圖

「人物／小檔案」是 Notion 模板庫中的大型分類，但目前尚未新增為第五個 `CHART_TYPES` 類型。

---

## 四、最終 Prompt 組合

`app.js` 的 `buildPrompt()` 依兩個維度組合最終圖片 Prompt：

1. **角色**：記者／編輯
2. **圖片引擎**：Gemini／GPT

角色規則：

- 記者：上、左、右固定 15% 完全留空；底部 15～18% 完全留空
- 編輯：四周固定 15% 完全留空；標題強制兩行並加大
- 四周安全區只延伸背景，不得放文字、圖示、Logo、圖表、線條或裝飾元素
- 安全區規則優先於 Style、Structure 與 Variable 內的衝突指令

引擎差異只在起手句：

- Gemini：`Create a professional international TV news infographic...`
- GPT：`Generate an image: a professional international TV news infographic...`

正文共用 CANVAS、Text Rules、STYLE、STRUCTURE、VARIABLE、SAFE AREA 與 FINAL OUTPUT RULE。

`[ ]` 是指令標籤，`< >` 是強調／替換標記。最終圖片不得顯示括號符號本身。

---

## 五、AI 消化功能

前端 `handleAIDigestion()` 呼叫本機 FastAPI 的 `/api/generate`。API key 只存在 `.env`，不會送到瀏覽器。

後端目前使用 **OpenAI Responses API**：

- 預設模型：`gpt-5.6-terra`
- 可用 `OPENAI_DIGEST_MODEL` 覆寫
- 使用 JSON Schema 強制回傳 `style`、`structure`、`variable`
- 記者與編輯使用不同的角色規則

### 工作角色與文字密度

AI 消化有兩個獨立維度：

- 角色：記者／編輯
- 文字密度：標準／簡化

上下兩處「記者／編輯」控制使用同一個狀態並雙向同步。

#### 標準

維持既有行為：

- 記者：精簡新聞圖表內容與專業英文構圖
- 編輯：150～180 字以內、兩行標題、條列重點及強制 `<蓋章>` 結論

#### 簡化

依素材動態選擇 **1～3 個重點**，不強迫湊滿三點，並選擇最適合的一種聚焦方式：

1. 單一主視覺＋最多三個短標註
2. 一個大數字或大結論＋一至兩個輔助標籤
3. 主題大圖／地圖／場景＋集中於單一區域的少量文字

簡化模式禁止多組次要卡片、重複資訊、不必要裝飾 icon、互相競爭的視覺焦點，以及為填滿版面新增的文字。

編輯＋簡化模式不強迫達到 150～180 字；`<蓋章>` 改為視素材決定，且計入最多三個重點。

**文字密度只影響 AI 自動消化。**手動模板、手動欄位與最終 Prompt 不會被系統刪減。

---

## 六、圖片生成

前端確認最終 Prompt 後，可透過 `/api/images/generate` 使用 Gemini 或 GPT 生成圖片。

- 傳輸層預設 `IMAGE_BACKEND=openrouter`（設 `native` 切回原生直連）
- Gemini 預設模型：`google/gemini-3-pro-image`（原生那條為 `gemini-3-pro-image`，同一個模型）
- Gemini 圖片尺寸：原生 `1K`
- GPT 預設模型：`openai/gpt-image-2`（原生那條為 `gpt-image-2`，同一個模型）
- GPT 圖片尺寸：依 `aspect_ratio` 換算（16:9→`1280×720`、21:9→`1680×720`）PNG
- **模型做不到要求的 `aspect_ratio` 一律回 400**，不默默改尺寸；例外要用
  `ALLOW_UNSUPPORTED_ASPECT_RATIO=1` 明示（2026-08-01 清查後加，見
  `docs/error-cases/2026-08-01-真人肖像與生圖模型清查-分析.md`）
- OpenAI 與 Gemini 金鑰都只由後端讀取
- 前端可預覽並下載生成圖片

除非使用者明確要求，測試時不呼叫需要計費的 AI 或圖片生成 API；改用單元測試及瀏覽器請求攔截。

---

## 七、Notion 與模板資料庫

### 記者模板庫

`notion-templates/templates.json` 是 2026-07-14 從 Notion「AI圖資料庫」匯出的快照：

- 205 個模板
- 195 張壓縮代表圖
- 包含完整 Prompt、風格 TAG、構圖 TAG、用途 TAG 與來源資訊
- `notion-templates/tools/` 保留解析、索引與代表圖產生工具

### 編輯模板庫

`editor-templates/` 來源為「編輯版型彙整（準時收工）」：

- `PROMPTS.md`：整理小幫手、視覺小幫手等實戰 Prompt
- `proposal/`：隊伍提案文件
- `images/`：130 張主播鏡面版型參考圖

### 四大類型現況

- `data`：資料圖表、統計圖、摘要卡片、卡牌陳列等
- `scene`：已加入 WPA Poster、UE5、軍事 UI、要件情境圖解等實戰內容
- `map`：已加入 TVBS 向量地圖、軍事戰棋、地震速報、航跡與部署圖等實戰內容
- `process`：已加入流程圖、時間軸、線索卡、夜藍檳金與教科書立體等實戰內容

scene／map／process 已不再是通用佔位模板，但仍需持續用實際生成圖驗收措辭與安全區表現。

### Notion 同步策略

目前採用「批次快照／半自動整理」，不做即時 API 直連。完整階段 A／B／C 規劃見 `docs/notion-integration-plan.md`。

---

## 八、目前待辦

1. **待決定：整併「圖表類型」與「構圖／子結構」**。目前兩者在使用者視角都像是在挑選範本版型，但程式中的圖表類型還同時負責 AI `type_label`、風格／模板篩選與最終 Prompt 類型。整併前需進一步決定 AI 自動消化的版型來源：
   - 使用者先選具體版型，AI 只把內容整理進該模板
   - AI 從全部版型自動挑選，使用者可再改選
   - 使用者先選大類，再由 AI 從該類挑具體版型
   在此決策完成前，不修改現有選擇流程。
2. 持續用實際生成圖驗收新版 scene／map／process 模板與四邊安全區
3. 決定是否新增第五類「人物／小檔案」（目前尚未納入）
4. 持續從 Notion 批次匯入或整理精選模板
5. 模板更新頻率提高後，再評估 Notion 直連階段 B
6. **待使用者決策：評估「AI 視覺素材＋固定版型合成」方案**。AI 只生成無文字背景／插圖，APP 以 SVG 固定版型繪製繁體中文、數字、圖表與資料來源，並保留現有完整 AI 生圖模式。完整架構、版型格式、UI、API、品質檢查、分階段工期與決策標準見 `docs/hybrid-rendering-proposal.md`。**目前僅列入待辦，未獲使用者明確批准前不得開始實作。**

---

## 九、固定規格

- 一律使用繁體中文與台灣用語
- 度量衡、姓名、職稱與國家名使用台灣慣用譯名
- 圖表 Prompt 的 `[ ]`、`< >` 是內部指令標記，不得出現在生成圖片
- 所有圖片生成與 Prompt 解析度統一為 1K
- 新增或匯入模板時，不得重新帶入 2K、4K 或其他高解析度要求
- `.env` 不得進入 Git；前端不得保存 API key

---

## 十、工作紀錄

### 2026-07-15 — 混合式圖片合成提案列入待辦

- 使用者要求將「AI 生成背景／插圖，APP 依固定版型疊加中文、數字與圖表」的完整提案列入待辦，留待日後評估
- 完整提案保存於 `docs/hybrid-rendering-proposal.md`
- 狀態為「待使用者決策」，不代表已批准開發
- 未獲使用者明確指示前，不得開始實作或取代現有完整 AI 生圖流程

### 2026-07-14

### 標準／簡化 AI 消化模式

- 新增獨立文字密度設定：標準／簡化
- 密度只影響 AI 消化，不限制手動內容
- 簡化模式動態選擇 1～3 個重點及三種視覺聚焦方式
- 編輯＋簡化的 `<蓋章>` 改為可選並計入三點上限
- 自動消化區與模板庫的角色控制雙向同步
- 自動消化按鈕顯示目前角色與密度

### 全部生圖規格統一為 1K

- Gemini 使用原生 `image_size: 1K`
- GPT Image 2 使用 `1280×720` PNG
- 前端標籤、確認提示、API 請求與文件統一
- `editor-templates/PROMPTS.md` 的 4K／1920×1080 衝突要求改為 1K
- `notion-templates/templates.json` 的 Prompt 不再含獨立 2K／4K 規格

### 安全區調整

- 記者：上、左、右固定 15%；底部 15～18%
- 編輯：四周固定 15%
- 四側均加入逐項 NO-list、禁用詞與完全留空要求
- rollback tag：`backup-before-symmetric-safe-area-2026-07-14`
